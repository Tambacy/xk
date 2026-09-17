# -*- coding: utf-8 -*-
"""
浏览器会话与教务系统页面操作
============================

**全程真实浏览器**，没有任何裸 HTTP 请求：

  * 用 Playwright 驱动的 Chromium（不是系统 Edge —— 实测 Edge 会被要求二次认证）
  * 所有点击/输入都走真实输入通道，产生 isTrusted=true 的事件
  * 不用 page.evaluate 去改 DOM 或触发 click()（读数据除外）
  * TLS 指纹、请求头、Cookie、时序全部来自浏览器本身

页面导航采用"直接打开子系统页面"（等价于用户输入网址 / 用书签），
因为老式 frameset 菜单又慢又容易 detached；而**所有会留下行为痕迹的操作**
—— 输入课程名、点查询、勾选课程、点提交、点删除 —— 都是真人式操作。

页面清单（全部是独立页面，不依赖 frameset）：

    m=yxSearchTab      已选定课程       表格每行一个 p_del_id
    m=bxSearch/xxSearch/rxSearch/tySearch/cxSearchTab
                       各类课程的选课页  gridData 里有课余量
    表单提交            POST xkBks.vxkBksXkbBs.do，m=saveXxKc / deleteYxk
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from .humanize import HumanActor, NORMAL, URGENT
from .runtime import logical_screen
from . import fingerprint

BASE = "http://zhjwxk.cic.tsinghua.edu.cn/"
XKLOGIN = BASE + "xklogin.do"
XK_HOST = "zhjwxk.cic.tsinghua.edu.cn"
SSO_HOST = "id.tsinghua.edu.cn"

# 课程类别 → 页面/字段/提交动作
# extra 是这个类别页面额外需要的 URL 参数，缺了它页面会返回错的列表（任选课尤其明显）
COURSE_KINDS = {
    "bx": {"name": "必修课", "search": "bxSearch",     "field": "p_bxk_id",  "submit": "saveBxKc", "extra": {}},
    "xx": {"name": "限选课", "search": "xxSearch",     "field": "p_xx_id",   "submit": "saveXxKc", "extra": {}},
    "rx": {"name": "任选课", "search": "rxSearch",     "field": "p_rx_id",   "submit": "saveRxKc",
           "extra": {"is_zyrxk": "1"}},
    "ty": {"name": "体育课", "search": "tySearch",     "field": "p_rxTy_id", "submit": "saveTyKc", "extra": {}},
    "cx": {"name": "重修课", "search": "cxSearchTab",  "field": "p_cx_id",   "submit": "saveCxKc", "extra": {}},
}
KIND_BY_NAME = {v["name"]: k for k, v in COURSE_KINDS.items()}


class SessionExpired(Exception):
    """会话失效，需要重新登录。"""


class PageError(Exception):
    """页面操作失败（可向用户展示的原因）。"""


class NeedSecondFactor(PageError):
    """登录要求二次认证（短信/微信验证码），但程序既没能在主窗口里问到你，
    也没能打开浏览器窗口。正常流程不该走到这里。
    """


class LoginCancelled(PageError):
    """用户主动取消了登录（点了「取消」或关掉了程序）。"""


# 「人工输入」回调的约定：界面收到 (提示语, 图片, 允许的功能, 超时)，
# 返回下面三种之一 —— 用户填的验证码字符串，或者两个特殊指令。
HUMAN_RESEND = "__resend__"      # 重新发一次验证码
HUMAN_VISIBLE = "__visible__"    # 改成在浏览器窗口里完成


@dataclass
class SelectedCourse:
    kind: str = ""       # 必修/限选/任选/…（这列由页面 JS 填，可能为空）
    kch: str = ""
    kxh: str = ""
    name: str = ""
    time_text: str = ""
    teacher: str = ""
    credit: str = ""
    del_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.kch}-{self.kxh}"


@dataclass
class CapacityRow:
    kch: str = ""
    kxh: str = ""
    name: str = ""
    time_text: str = ""
    teacher: str = ""
    kyl: int = 0
    queue: str = ""
    note: str = ""
    cid: str = ""

    @property
    def key(self) -> str:
        return f"{self.kch}-{self.kxh}"


def _int(s) -> int:
    try:
        return int(re.sub(r"[^\d-]", "", str(s)) or 0)
    except Exception:
        return 0


class ScholarBrowser:
    """长期存活的浏览器会话：登录 + 所有教务系统操作。

    **只用有头模式（可见窗口），没有无头分支。**

    无头省的那点桌面空间，代价是一整类可判定的破绽：没有真实窗口就
   沒有真实的 screen / outer / inner 关系，没有窗口意味着没有最小化、
    没有焦点变化、没有 IME 上下文，UA 里还会带 "HeadlessChrome"。
    这些都能靠 CDP 和 JS 补，但补出来的是一致性，不是真实性 ——
    真实窗口本来就不要补。
    """

    def __init__(self, profile_dir: str | Path, *,
                 xnxq: str = "2026-2027-1",
                 viewport: tuple[int, int] = (1366, 900),
                 log: Callable[[str, str], None] | None = None,
                 actor: HumanActor | None = None):
        self.profile_dir = Path(profile_dir)
        self.xnxq = xnxq
        self.viewport = viewport
        self._log = log or (lambda msg, level="INFO": None)
        self.actor = actor or HumanActor(NORMAL, self._log)
        self._pw = None
        self._ctx = None
        self.page = None
        self._loaded: tuple | None = None
        self._fp_cache: dict | None = None   # 身份对齐的缓存（内含 CDP session 引用）
        # 统一身份认证对短时间内的重复登录很敏感：会回 sso_fail，甚至把要求
        # 从「直接登录」升级成图形验证码 / 短信二次认证。所以不管是谁来调用
        # login（界面、调度器、自动重登都会），两次**提交**之间都强制留间隔。
        self._last_submit_at = 0.0
        self.min_submit_gap = 10.0
        try:
            from .logging_setup import get_trace_logger
            self.trace = get_trace_logger()
        except Exception:
            self.trace = None

    def _tr(self, msg: str):
        """浏览器动作流水，写进独立的 trace 日志，方便事后逐帧复盘。"""
        if self.trace is not None:
            try:
                self.trace.debug(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def log(self, msg: str, level: str = "INFO"):
        self._log(msg, level)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        if self._ctx is not None:
            return
        from playwright.sync_api import sync_playwright
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.log("启动浏览器（可见窗口）…")
        self._tr(f"launch profile={self.profile_dir} "
                 f"viewport={self.viewport[0]}x{self.viewport[1]}")
        self._pw = sync_playwright().start()
        # 屏幕的真实逻辑尺寸：用来钳住窗口。
        # 不钳的话小屏机器上窗口会高过屏幕，页面里就是 outerHeight >
        # screen.height —— 物理上不成立，一次加载即可判定。
        sw, sh, sdpr = logical_screen()
        want_w, want_h = int(self.viewport[0]), int(self.viewport[1])

        launch_kw = dict(
            user_data_dir=str(self.profile_dir),
            headless=False,               # 只用有头，理由见类文档
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate,AcceptCHFrame",
            ],
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 窗口尺寸交给**真实窗口**，不用 Playwright 的视口模拟。
        # 用视口模拟时 Playwright 会把 screen 一起设成视口大小，于是
        # screen.width == innerWidth、甚至 outerWidth > screen.width
        # （窗口比屏幕还宽）—— 两个都物理上不成立。
        # 真实窗口下 screen / outer / inner / dpr 全是真值。
        w, h = want_w, want_h
        if sw and sh:
            w = min(w, max(640, sw - 20))
            h = min(h, max(480, sh - 60))
        launch_kw["args"] = launch_kw["args"] + [f"--window-size={w},{h}"]
        launch_kw["no_viewport"] = True
        # 装了随包浏览器时，显式指向完整 Chromium：
        # 1) 安装包只需带一份浏览器（不用再带 headless shell）
        # 2) 保证别人电脑上用的就是我们测过的那一版，行为完全一致
        try:
            from .runtime import find_bundled_chromium
            exe = find_bundled_chromium()
            if exe:
                launch_kw["executable_path"] = exe
                self._tr(f"使用随包 Chromium：{exe}")
        except Exception:
            pass
        self._ctx = self._pw.chromium.launch_persistent_context(**launch_kw)
        # 这里**故意不再注入 webdriver 的 init_script**。
        #
        # 以前注入的是 `{get: () => undefined}`。但正常浏览器里
        # navigator.webdriver 的值是 **false**，不是 undefined ——
        # 于是 `navigator.webdriver !== false` 反而成了一个更容易命中的
        # 判据，而且用 defineProperty 覆盖原型 getter 之后，
        # getOwnPropertyDescriptor 一看就知道不是原生的。
        #
        # 实测：只靠上面那个 `--disable-blink-features=AutomationControlled`
        # 启动参数，Chromium 的**原生 getter** 就会返回 false ——
        # 值和原生性都对，什么都不用改。
        # 这里**不注入任何 JS 补妆脚本**。
        #
        # 实测（2026-09，逐项对着真实浏览器量过）：这个 Chromium 在无头下
        # 本来就是对的 —— 插件 5 个且名字与真 Chrome 一致、mimeTypes 2 个、
        # pdfViewerEnabled 为 true、window.chrome.app 在、WebGL 报的是真显卡
        # （RTX 4070，不是 SwiftShader）、navigator 上没有任何多余的自有属性。
        #
        # （曾经有个 stealth.py 干这事，已经删掉了。）
# 那种补妆是用 Object.defineProperty 把 plugins / mimeTypes /
        # pdfViewerEnabled **定义在 navigator 实例上**，于是
        # `Object.getOwnPropertyNames(navigator).length` 从 0 变成 3 ——
        # 真 Chrome 是 0。也就是说：它在修一个不存在的问题，同时制造了一个
        # 更容易命中的破绽。
        #
        # 无头模式真正需要处理的只有 UA 里的 "HeadlessChrome"（见上面），
        # 以及品牌列表（由 fingerprint 模块处理）。
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.page.set_default_timeout(20000)
        self.page.on("dialog", self._on_dialog)
        # 身份对齐：随包的是 Chromium，它的品牌列表里**只有 "Chromium"**，
        # 而正常用户要么 Chrome 要么 Edge —— 一行 JS 就能查出来。
        # 用 CDP 在浏览器进程层面把品牌补成真 Chrome 的样子：
        # navigator.userAgentData 仍是原生 getter，JS 侧查不出痕迹。
        try:
            self._fp_cache = fingerprint.install(self._ctx, self.page, log=self.log)
        except Exception as e:
            self.log(f"对齐浏览器身份失败（不影响使用）：{e}", "WARN")
        # 当前页面标记：用来判断"现在页面上摆的是哪一类课程的列表"，
        # 避免把别的类别的数据当成目标课程的。
        self.current_list: dict | None = None      # {"kind": "ty", "kch": "10721071"}

    def is_on_list_page(self, kind: str, kch: str = "") -> bool:
        """当前页面上摆的是不是这一类课程（可选再要求某个课程号的筛选结果）。"""
        c = self.current_list
        if not c or c.get("kind") != kind:
            return False
        if kch and c.get("kch") != kch:
            return False
        return True

    def _on_dialog(self, dialog):
        """选课/退课都会弹 confirm()，真人会点「确定」。"""
        try:
            self.log(f"浏览器确认框：{(dialog.message or '')[:50]} → 点「确定」")
            self.actor.ui_pause(0.3, 1.0)
            dialog.accept()
        except Exception:
            pass

    def stop(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self.page = None
        self._loaded = None

    def restart(self):
        """重建浏览器（**profile 目录不变**）。

        为什么强调 profile 不变：统一身份认证的「信任此设备」状态就存在这个
        目录里。换个目录等于换了一台新电脑，服务端会立刻要求二次验证。
        """
        self.log("重新打开浏览器（可见窗口）…")
        self._tr("restart")
        self.stop()
        self.start()
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        return self

    def ensure_visible(self, on_progress: Callable[[str], None] | None = None) -> bool:
        """把浏览器窗口提到最前。

        以前这里还要处理「无头 -> 有头」的切换；现在只用有头，它就只剩
        「确保窗口在最前面」这一个作用 —— 二次验证（短信/微信）和图形验证码
        都要真人在窗口里点，窗口必须可见、可点。

        返回值保留但恒为 False（表示没有重建过浏览器）。
        """
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        return False


    # ------------------------------------------------------------------
    # 浏览器窗口被关掉之后的自我修复
    # ------------------------------------------------------------------
    @staticmethod
    def _looks_closed(exc: BaseException) -> bool:
        """这个异常是不是「窗口/上下文被关掉了」。"""
        t = f"{type(exc).__name__}: {exc}".lower()
        return any(k in t for k in (
            "has been closed", "targetclosed", "target page", "browser has been closed",
            "connection closed", "context or browser", "browser closed",
            "page closed", "session closed",
        ))

    def is_alive(self) -> bool:
        """浏览器窗口还在不在。

        用户手动把那个 Chromium 窗口关掉是很常见的操作 —— 以前一旦关掉，
        后面每个功能都会报「窗口已关闭」然后整个任务就废了。
        """
        if self._ctx is None or self.page is None:
            return False
        try:
            return not self.page.is_closed()
        except Exception:
            return False

    def revive(self, *, visible: bool = False,
               on_progress: Callable[[str], None] | None = None) -> bool:
        """把被关掉的浏览器重新拉起来（**同一个 profile 目录**，登录态还在）。

        只用有头，所以重开出来的一定是可见窗口。窗口被关掉之后用户多半
        是希望它回来的（不然监听就断了），露出来是合理的。

        visible 参数保留只为兼容旧调用，现在没有作用。

        注意 profile 目录不会变 —— 「信任此设备」的状态就存在里面。
        """
        if self.is_alive():
            return True
        if on_progress:
            try:
                on_progress("浏览器窗口已关闭，正在重新打开…")
            except Exception:
                pass
        self.log("浏览器窗口已关闭，正在重新打开（登录态保留）…", "WARN")
        try:
            self.restart()
            self.log("浏览器已重新打开，继续运行。")
            return True
        except Exception as e:
            self.log(f"重新打开浏览器失败：{e}", "ERROR")
            return False

    def _ensure_alive(self, where: str = ""):
        """每个页面操作之前先确认窗口还在；不在就自动重开。"""
        if self.is_alive():
            return
        self._tr(f"_ensure_alive({where or '?'}): 窗口已关闭，自动重开")
        self.revive(on_progress=None)
        if not self.is_alive():
            raise PageError(
                "浏览器窗口已被关闭，而且没能重新打开。请重新点一次「登录」。")


    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def login(self, user: str, password: str, *, single_login: bool = True,
              ask_captcha: Callable[[], str | None] | None = None,
              on_progress: Callable[[str], None] | None = None,
              on_human: Callable[[str], None] | None = None,
              ask_human_code: Callable[..., str | None] | None = None,
              timeout: float = 150,
              human_timeout: float = 300,
              visible_for_login: bool = False) -> bool:
        """用真实浏览器完成统一身份认证。

        **默认全程只有一个窗口**：图形验证码和二次验证都由主窗口向你要，
        程序在后台页面上替你填好并提交（图形验证码还会截图显示在主窗口里）。
        只有你明确选择「改用浏览器窗口完成」时，才会打开浏览器窗口。

        on_progress       普通阶段提示
        on_human          需要你本人操作时的提示（界面高亮显示）
        ask_human_code    要验证码的回调：ask_human_code(提示, image=…,
                          allow_resend=…, allow_visible=…, timeout=…)
                          返回验证码字符串，或 HUMAN_RESEND / HUMAN_VISIBLE，
                          或 None 表示用户取消
        human_timeout     等真人操作的上限（秒）
        visible_for_login 强制用可见窗口认证（调度器等没有界面的调用方用）
        """
        def step(msg: str, human: bool = False):
            self.log(msg, "WARN" if human else "INFO")
            cb = on_human if human else on_progress
            if cb:
                try:
                    cb(msg)
                except Exception:
                    pass

        a = self.actor
        a.set_tempo(NORMAL)

        # 窗口可能在等待期间被关掉，先确认它还活着（不在就自动重开）
        self._ensure_alive("login")

        # 登录最多重走几轮，防止服务端反复要求验证时死循环
        restarts = 0
        guard = 0
        self._did_2fa = False

        while True:
            guard += 1
            if guard > 6:
                raise NeedSecondFactor(
                    "登录反复要求人工验证，始终没完成。请检查网络后稍后再试。")

            step("正在启动/连接浏览器…")
            self._goto_login_entry()
            a.ui_pause(0.4, 1.0)
            self._loaded = None

            if SSO_HOST not in (self.page.url or ""):
                # 这里原来直接 return True。但"URL 不在认证域"并不等于
                # "会话可用" —— 学校在会话处于中间态时也会把我们送到
                # m=main，看着像已经登录了。
                if self._verify_session():
                    step("已有有效会话，无需登录。")
                    return True
                self.log("落地页不在认证域，但数据页拿不到内容 —— "
                         "会话说不上有效，继续走登录流程。", "WARN")

            # ---- 认证方式 ----
            # 浏览器窗口一直开着（只用有头）：图形验证码和二次验证都在
            # 主窗口里问你要，你输入后程序替你在页面上填好、提交。

            step("已到达统一身份认证页，准备填写账号…")
            a.scroll_page(self.page)
            a.think()

            # ---- 图形验证码：截图显示在主窗口里，不用看第二个窗口 ----
            if self._captcha_visible():
                box = self.page.locator(self._captcha_selector()).first
                if ask_human_code is not None:
                    answer = ask_human_code("请输入图片里的验证码。",
                                            image=self._captcha_image(),
                                            allow_resend=False, allow_visible=True,
                                            timeout=human_timeout)
                    if answer is None:
                        raise LoginCancelled("已取消登录。")
                    if answer == HUMAN_VISIBLE:
                        self.ensure_visible(on_progress)
                        done = self._wait_human_login(
                            "请在浏览器窗口里填写图形验证码并点「登录」，程序会自动继续。",
                            human_timeout, step)
                        return done
                    a.type_text(self.page, box, answer)
                else:
                    code = ask_captcha() if ask_captcha else None
                    if not code:
                        raise PageError("登录需要图形验证码")
                    a.type_text(self.page, box, code)

            step("正在输入账号…")
            user_box = self.page.locator("#i_user")
            # 实测踩过：记完信任后学校会自己跳转，如果这时重走登录，可能落到
            # 一个**没有登录表单**的页面上（可能是中转页或已经登录了）。
            # 这时候硬填 #i_user 会抛 15 秒超时，把一次本该成功的登录搞失败。
            if user_box.count() == 0:
                self.log("当前页面没有登录表单，先确认会话是否已经好了。", "WARN")
                if self.is_logged_in():
                    step("✅ 已经登录成功。")
                    return True
                hint = ""
                if getattr(self, "_bad_session", 0):
                    # 刚才已经出现过"登录提交成功但会话无效"，八成是这台
                    # 设备还没过二次认证 —— 那就别再报"页面不对"这种没用的
                    # 话了，直接告诉用户该干什么。
                    hint = ("\n\n前面已经出现过「登录提交成功、但会话拿不到」的"
                            "情况，这通常是这台设备还没通过学校的二次认证。\n"
                            "请在已打开的浏览器窗口里手动完成一次登录"
                            "（含二次认证那一步）。完成后这台设备会被记住，"
                            "以后就不用再验证了。")
                raise PageError(
                    f"登录页看起来不对（找不到账号输入框），页面停在："
                    f"{(self.page.url or '')[:90]}{hint}")
            # 真实页面会把已经填好的账号设成 readonly（
            #   if ($("#i_user").val() != "") { $("#i_user").attr("readonly","readonly"); }
            # ）。这时别去填 —— 对只读元素 fill/type 会直接抛「元素不可编辑」。
            readonly, prefill = None, ""
            try:
                readonly = user_box.get_attribute("readonly")
                prefill = (user_box.input_value() or "").strip()
            except Exception:
                pass
            if readonly is not None and prefill:
                self._tr("#i_user 只读且已预填，跳过输入")
                step("账号已由登录页自动填好，跳过输入。")
            else:
                a.type_text(self.page, user_box, user)
            a.ui_pause(0.25, 0.7)
            step("正在输入密码…")
            a.type_text(self.page, self.page.locator("#i_pass"), password, clear=False)

            if single_login:
                try:
                    a.check(self.page,
                            self.page.locator('#theform input[name="singleLogin"]').first)
                    step("已勾选「信任/单点登录」。")
                except Exception as e:
                    # 勾不上就等于每次登录都被当成新设备，必然被要求二次认证。
                    # 这里以前是静默 pass，出了问题日志里一个字都没有。
                    self.log(f"⚠ 没勾上「信任/单点登录」（{e}）——"
                             f"少了它下次登录很可能被要求二次认证。", "WARN")

            a.think()
            step("正在提交登录…")
            self._respect_sso_cooldown(on_progress)
            a.click(self.page, self.page.locator("a[onclick*='doLogin']").first)
            step("已提交，等待服务器响应（这一步有时要几十秒）…")

            status = self._wait_landing(timeout, on_progress=on_progress)

            if status == "ok":
                if self._verify_session():
                    step(f"登录成功！落地页：{(self.page.url or '')[:70]}")
                    return True
                # 落地了、但会话是死的。全新设备最常这样：学校接受了登录
                # 却不给会话，因为这台设备还没通过二次认证。
                self.log("落地页看着像登录成功，但数据页返回「登陆超时」——"
                         "会话其实没建立起来。多半是这台设备还没通过二次认证。",
                         "WARN")
                self._bad_session = getattr(self, "_bad_session", 0) + 1
                if self._bad_session >= 2:
                    raise PageError(
                        "登录提交后始终拿不到有效会话（数据页返回「登陆超时」）。\n\n"
                        "最常见的原因是这台设备还没通过学校的二次认证。\n"
                        "请在已经打开的浏览器窗口里手动完成一次登录"
                        "（含二次认证那一步），之后再运行程序。\n"
                        "完成后这台设备会被记住，后续就不用再验证了。")
                step("落地页拿到了但会话无效，再试一次…")
                time.sleep(4)
                continue

            if status == "need_human":
                # ---- 首选：在程序主窗口里完成，不开浏览器窗口 ----
                if ask_human_code is not None and not getattr(self, "_did_2fa", False):
                    solved = self._solve_second_factor_here(step, ask_human_code,
                                                            human_timeout)
                    if solved:
                        return True

                # 已经完整走过一次二次验证（选了「记为信任」或「否」）却还停在
                # 验证页 —— 实测这是选「否」时的正常现象：学校会立刻再问一遍。
                # 这时候直接重走一次登录就能进去（会话其实已经建立好了），
                # 不必去麻烦用户开浏览器窗口。
                if getattr(self, "_did_2fa", False) and restarts < 2:
                    restarts += 1
                    self.log("二次验证已走完但学校又要求验证一次，"
                             "先等它自己跳转完。", "WARN")
                    step("正在确认登录状态…", human=True)
                    # 学校那边可能正在 redirect2Jsp 上自己跳，先给它 12 秒；
                    # 跳过去就直接进系统了，不用重走登录。
                    if self._wait_landing(12, on_progress=None) == "ok":
                        step("✅ 二次验证通过，已进入选课系统。")
                        return True
                    if getattr(self, "_trust_choice", "") == "否":
                        # 没登记信任设备 → 下次登录还会要验证码，这是正常的，
                        # 不是错误。直接说清楚就收尾。
                        raise PageError(
                            "二次验证已经通过了，但你没把本机登记为「信任设备」，"
                            "所以这次登录到此为止。下次登录还会要验证码 —— "
                            "想免验证码就在最后那一步选「是」。")
                    self.log("页面没有自己跳转，重新走一次登录入口。", "WARN")
                    continue

                # ---- 页面认不出来：只问"要不要开窗口"，绝不擅自开 ----
                if ask_human_code is not None:
                    answer = ask_human_code(
                        "这个验证页面程序没法自动认出来，需要打开浏览器窗口，"
                        "由你在里面完成。",
                        image=None, allow_resend=False, allow_visible=True,
                        allow_code=False, timeout=human_timeout)
                    if answer != HUMAN_VISIBLE:
                        # 用户没明确要开窗口（取消、或超时）—— 那就别开
                        raise LoginCancelled("已取消登录。")
                self.ensure_visible(on_progress)
                done = self._wait_human_login(
                    "本次登录要求二次认证（短信 / 微信验证码）。请在已经打开的"
                    "浏览器窗口里输入收到的验证码，程序会自动继续。",
                    human_timeout, step)
                return done

            # ---- 失败：尽量说清楚是哪一种 ----
            body = self._safe_body_text()
            url = self.page.url or ""
            if "验证码" in body:
                raise PageError("登录要求验证码")
            if "不正确" in body or "密码错误" in body:
                raise PageError("用户名或密码不正确")
            if "sso_fail" in url:
                raise PageError("统一身份认证票据校验失败"
                                "（短时间内登录过于频繁，请等几分钟再试）")
            raise PageError(f"登录失败，页面停在：{url[:90]}")

        raise NeedSecondFactor("需要你在浏览器窗口里完成二次验证，但可见窗口没能打开。")

    def _respect_sso_cooldown(self, on_progress=None):
        """两次提交登录之间强制留出间隔，避免自己把自己搞成「异常登录」。

        实测：短时间内连续提交会被判 sso_fail，甚至把要求升级成图形验证码 /
        二次认证。原型里的探针也是靠 3~30 秒的间隔才跑得稳。
        """
        gap = float(getattr(self, "min_submit_gap", 10.0) or 0.0)
        last = float(getattr(self, "_last_submit_at", 0.0) or 0.0)
        if last and gap > 0:
            wait = gap - (time.time() - last)
            if wait > 0:
                self.log(f"距上次提交登录才 {time.time() - last:.0f} 秒，"
                         f"为避免被当成异常登录，等 {wait:.0f} 秒再提交。", "WARN")
                if on_progress:
                    try:
                        on_progress(f"为免触发风控，等 {wait:.0f} 秒后重新提交登录…")
                    except Exception:
                        pass
                end = time.time() + wait
                while time.time() < end:
                    try:
                        self.page.wait_for_timeout(250)
                    except Exception:
                        time.sleep(0.25)
        self._last_submit_at = time.time()

    def _wait_human_login(self, hint: str, human_timeout: float, step) -> bool:
        """把窗口交给真人，等他完成验证码 / 二次认证，然后确认真的进去了。"""
        step(hint, human=True)
        t0 = time.time()
        last_tick = 0
        while time.time() - t0 < human_timeout:
            # 用户可能把窗口关了（或者误关）—— 重新打开并把窗口提到最前，
            # 否则他会一直盯着屏幕等，而程序在等一个已经不存在的页面。
            if not self.is_alive():
                if self.revive(visible=True, on_progress=None):
                    step("浏览器窗口被关闭了，已重新打开。请在这个新窗口里继续完成验证。",
                         human=True)
                    continue
            try:
                self.page.bring_to_front()
            except Exception:
                pass
            if self._landed():
                step(f"✅ 验证已完成，已进入选课系统（用时 {time.time() - t0:.0f} 秒）。")
                return True
            # 万一停在"是否记为信任浏览器"那一步，也按用户的选择处理 ——
            # 否则页面永远不跳转（学校不会自动跳）。
            if self._trust_radios():
                self._solve_trust_step(step, None, human_timeout)
            elapsed = int(time.time() - t0)
            if elapsed >= last_tick + 15:
                last_tick = elapsed
                # 走普通进度通道：只刷新"进度"那一行，别把上面那块
                # 「需要你本人操作」的指引文字覆盖掉 —— 用户随时看都还在。
                step(f"仍在等你完成验证…（已 {elapsed} 秒）")
            try:
                self.page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)
        raise NeedSecondFactor(
            f"等了 {human_timeout / 60:.0f} 分钟仍未看到验证完成。"
            f"请在浏览器窗口里完成短信 / 微信验证后，再点一次「登录」。")

    def _landed(self) -> bool:
        """当前是不是已经真的落进教务系统内部页面。

        比原来的「URL 里有选课域名」严格：认证域、二次认证页、
        以及会话失效的那种几百字节小页面都不算。
        """
        try:
            u = self.page.url or ""
        except Exception:
            return False
        if "sso_fail" in u or SSO_HOST in u:
            return False
        if XK_HOST not in u:
            return False
        try:
            if self._is_second_factor_page():
                return False
        except Exception:
            pass
        try:
            if len(self.page.content()) < 1500:      # 登陆超时那种小页面
                return False
        except Exception:
            pass
        return True

    def _goto_login_entry(self) -> None:
        """打开选课系统入口（xklogin.do）。

        注意：页面**可能正在自己跳转**（二次验证成功后，学校那边会执行
        window.location.href = redirectUrl）。这时我们的导航会被 abort，
        报 net::ERR_ABORTED —— 实测踩过，不能把它当成登录失败。
        所以这里等它跳完再试一次。
        """
        for attempt in range(2):
            try:
                self.page.goto(XKLOGIN, wait_until="domcontentloaded", timeout=60000)
                return
            except Exception as e:
                msg = str(e)
                racy = ("ERR_ABORTED" in msg or "interrupted" in msg.lower()
                        or "navigation" in msg.lower())
                if attempt == 0 and racy:
                    self.log("导航被页面自身的跳转打断了，等它跳完再试一次。", "WARN")
                    try:
                        self.page.wait_for_timeout(2000)
                    except Exception:
                        time.sleep(2)
                    continue
                raise

    def _wait_landing(self, timeout: float, on_progress=None) -> str:
        """等真正落进教务系统内部页面。

        返回：
            "ok"          已经进去
            "need_human"  需要真人操作（二次认证页）
            "fail"        sso_fail 或超时
        """
        t0 = time.time()
        end = t0 + timeout
        reported = False
        while time.time() < end:
            u = self.page.url or ""
            if "sso_fail" in u:
                return "fail"

            if self._is_second_factor_page():
                if not reported:
                    reported = True
                    self.log("⚠ 本次登录要求二次认证（短信 / 微信验证码）。", "WARN")
                return "need_human"

            if self._landed():
                return "ok"

            if on_progress and int(time.time() - t0) % 3 == 0:
                on_progress(f"等待跳转中…（已 {time.time()-t0:.0f} 秒）")
            try:
                self.page.wait_for_timeout(350)
            except Exception:
                time.sleep(0.35)
        return "ok" if self._landed() else "fail"

    def _is_second_factor_page(self) -> bool:
        """判断当前是不是统一身份认证的二次验证页面。

        除了 URL 和文案，还认**真实源码里的标记** —— 二次验证前端
        （doubleAuth.bundle.js）一定会渲染出：
            <input name="vericode" id="vericode" maxlength="6">
            <input type="hidden" name="action" value="VERITY_CODE">
        这比猜文案可靠得多（URL 里未必有 doubleauth，页面上也未必写着"二次认证"）。
        """
        try:
            u = (self.page.url or "").lower()
            if "doubleauth" in u or "checksecond" in u:
                return True
            for sel in self._SECOND_FACTOR_MARKERS:
                try:
                    if self.page.locator(sel).count() > 0:
                        return True
                except Exception:
                    continue
            # 只在认证域下按文案判断，避免误伤其它页面
            if SSO_HOST not in (self.page.url or ""):
                return False
            html = self.page.content()[:6000]
            # ⚠ 实测踩过：验证**通过之后**的中转页会写着
            #   「二次验证成功……是否将本次登录使用的设备记为信任浏览器？」
            # 里面同样含"二次验证"四个字。以前会把它误判成"还要验证"，
            # 于是白等 60 秒、最后还要重来一遍。
            if any(k in html for k in ("验证成功", "正在跳转", "记为信任浏览器")):
                return False
            return ("二次认证" in html or "二次验证" in html
                    or "doubleAuth" in html or "需要二次" in html)
        except Exception:
            return False

    def _captcha_selector(self) -> str:
        """图形验证码输入框。SSO 页上有 #i_code，也有版本用 #c_code。"""
        return "#i_code, #c_code"

    # 验证码输入框的候选选择器。
    # 头两个取自学校二次验证前端的真实源码（doubleAuth.bundle.js）：
    #     Input({autoFocus:true, inputMode:"numeric", maxLength:6,
    #            name:"vericode", id:"vericode"})
    # 后面的是图形验证码和兜底。注意 input[type=text] 很宽松 ——
    # 登录表单里的 #i_user 也是 text，所以下面还要按 name 排掉它。
    _CODE_INPUT_SELECTORS = (
        "#vericode", "input[name='vericode']",
        "#i_code", "#c_code", "#code", "#smsCode", "#authCode",
        "input[name*='code' i]", "input[id*='code' i]",
        "input[name*='verify' i]", "input[id*='verify' i]",
        "input[autocomplete='one-time-code']",
        "input[inputmode='numeric']",
        "input[placeholder*='验证码']", "input[placeholder*='校验码']",
        "input[type=tel]", "input[maxlength='6']", "input[maxlength='4']",
        "input[type=text]",
    )
    # 二次验证页的精确标记（同样来自真实源码）
    _SECOND_FACTOR_MARKERS = (
        "#vericode", "input[name='vericode']",
        "input[name='action'][value='VERITY_CODE']",
        "input[name='action'][value='VERITY_CARD_CODE']",
    )
    _LOGIN_FIELD_NAMES = ("i_user", "i_pass", "user", "pass", "username",
                          "password", "j_username", "j_password")
    _SUBMIT_TEXTS = ("提交", "确定", "确认", "验证", "下一步", "完成", "继续", "登录")
    _RESEND_TEXTS = ("重新发送", "重发", "再次发送", "获取验证码", "发送验证码", "发送")

    def _visible_locator(self, selector: str):
        """返回第一个可见的元素；没有就返回 None。"""
        try:
            loc = self.page.locator(selector).first
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            pass
        return None

    def _find_code_input(self):
        """在验证页面上找「验证码输入框」。找不到返回 None。"""
        for sel in self._CODE_INPUT_SELECTORS:
            loc = self._visible_locator(sel)
            if loc is None:
                continue
            try:
                name = (loc.get_attribute("name") or "").strip().lower()
                if name in self._LOGIN_FIELD_NAMES:
                    continue                      # 这是账号框，不是验证码框
                typ = (loc.get_attribute("type") or "").lower()
                if typ in ("password", "hidden", "submit", "button", "checkbox"):
                    continue
            except Exception:
                pass
            return loc
        return None

    # 可点元素的标签。注意：`a, b:has-text('x')` 这种写法里 :has-text() 只作用于
    # 最后一个标签，前面的会变成"任意元素都算"—— 所以必须逐个标签拼选择器。
    _CLICKABLE_TAGS = ("button", "a", "input[type=button]", "input[type=submit]",
                       "span", "div")
    # 找「提交」时要排掉这些词，否则「获取验证码」这种按钮会被当成提交按钮
    _NOT_SUBMIT_WORDS = ("发送", "获取", "重发", "重新")

    def _find_by_texts(self, texts, tags=None, exclude_words=()):
        """按可见文字找一个可点的控件。"""
        tags = tags or self._CLICKABLE_TAGS
        for t in texts:
            for tag in tags:
                try:
                    loc = self.page.locator(f"{tag}:has-text('{t}')").first
                    if not (loc.count() and loc.is_visible()):
                        continue
                    # 别把一大块容器当成按钮
                    box = loc.bounding_box()
                    if box and box["height"] > 80:
                        continue
                    if exclude_words:
                        try:
                            txt = (loc.inner_text() or "")
                        except Exception:
                            txt = ""
                        if any(w in txt for w in exclude_words):
                            continue
                    return loc
                except Exception:
                    continue
        return None

    def _find_submit_button(self):
        return self._find_by_texts(self._SUBMIT_TEXTS,
                                   exclude_words=self._NOT_SUBMIT_WORDS)

    def _find_resend_control(self):
        return self._find_by_texts(self._RESEND_TEXTS, tags=("a", "button", "span"))

    def _captcha_image(self) -> bytes | None:
        """把图形验证码截成 PNG —— 好显示在**程序主窗口**里。

        这样用户不用去看第二个窗口：验证码图片直接出现在程序界面里。
        """
        for sel in ("img#captcha", "img[id*='captcha' i]", "img[src*='captcha' i]",
                    "img[id*='code' i]", "img[src*='code' i]",
                    "img[src*='validate' i]", "#i_code ~ img", "#c_code ~ img",
                    "#theform img"):
            loc = self._visible_locator(sel)
            if loc is None:
                continue
            try:
                data = loc.screenshot()
                if data and len(data) > 100:
                    return data
            except Exception:
                continue
        return None

    # 二次验证「选择方式」页上的取值（取自真实页面 HTML）：
    #   <input name="type" type="radio" value="wechat" checked> 发送到您的微信
    #   <input name="type" type="radio" value="mobile">         发送短信到手机
    _METHOD_LABELS = {"mobile": "发短信到我手机", "wechat": "发到我的企业微信"}

    # 验证通过之后的「是否记为信任浏览器」也复用 name=type，但取值是「是」/「否」。
    # 必须按 value 区分 —— 否则会把这一步误当成"选择验证方式"。
    _TRUST_VALUES = ("是", "否")

    def _trust_radios(self) -> list:
        """「是否将本次登录使用的设备及浏览器记为信任浏览器」的单选按钮。

        真实源码（doubleAuth.bundle.js）：
            <input type="radio" name="type" value="是">  是，记为信任（180天）
            <input type="radio" name="type" value="否" defaultChecked> 否
            <Button onClick={handleConfirm}>确定</Button>
            → POST /b/doubleAuth/personal/saveFinger {radioVal:…}
            → 成功后 window.location.href = redirectUrl（**不会自动跳**）
        """
        out = []
        try:
            radios = self.page.locator("input[type=radio][name='type']")
            n = radios.count()
        except Exception:
            return out
        for i in range(n):
            r = radios.nth(i)
            try:
                if not r.is_visible():
                    continue
                v = (r.get_attribute("value") or "").strip()
            except Exception:
                continue
            if v in self._TRUST_VALUES:
                out.append((r, v))
        return out

    def _solve_trust_step(self, step, ask=None, human_timeout: float = 300.0) -> bool:
        """处理「是否记为信任浏览器」这一步。

        **这一步不处理就永远登不进去**：验证码通过后学校不自动跳转，而是问
        你要不要把本设备记为信任，必须选一个再点「确定」，它才 POST
        saveFinger 然后跳转。

        ⚠ 「选是还是选否」**不在这一步问** —— 用户在登录表单上早就回答过了：
        那个「信任此浏览器（会话过期后免密码重登）」勾选框（name=singleLogin，
        页面原话是「本次登录使用信任浏览器访问校内其他系统时不必再输入账号
        密码（统一登录）」）说的就是这件事。

        两边必须一致：一开始勾了"我要用信任浏览器"、最后又答"否"，等于自己
        打自己脸 —— 页面上那句「否(您本次登录未使用可信浏览器，将无法支持
        统一登录。)」写得很清楚，学校就不发统一登录票据，于是又弹回验证页，
        重走登录也没用（实测就是死循环）。所以这里直接跟随那个勾选框。
        """
        radios = self._trust_radios()
        if not radios:
            return False
        btn = self._find_by_texts(("确定", "确认"))
        if btn is None:
            return False

        want = None
        if ask is not None:
            # 这一步**和登录表单上的「信任此浏览器」不是一回事**，别混：
            #   * 登录表单那个（singleLogin）：接下来登录别的校内系统不用再输
            #     账号密码（统一登录票据），只管这一次会话
            #   * 这一步（saveFinger）：把**本设备**登记为信任设备，之后退出
            #     再登录不用验证码，学校给 180 天
            # 所以必须单独问一次，不能拿前者去替用户决定后者。
            try:
                ans = ask("学校问：是否把本设备登记为「信任设备」？\n"
                          "（登记后 180 天内这台电脑再登录都不用输验证码）",
                          choices=[
                              {"label": "是，登记（之后免验证码）",
                               "value": "__choice__:是"},
                              {"label": "否，这次不登记（下次还要验证码）",
                               "value": "__choice__:否"},
                          ],
                          allow_code=False, allow_visible=False,
                          timeout=human_timeout)
            except TypeError:
                ans = None          # 回调不接受 choices 时按下面的默认走
            if isinstance(ans, str) and ans.startswith("__choice__:"):
                want = ans.split(":", 1)[1].strip()
            elif ans is None:
                self.log("用户没有回答是否登记信任设备，按默认（是）处理。", "WARN")
        if want not in self._TRUST_VALUES:
            # 没界面可问（调度器自动重登）：必须选一个，否则页面不跳转、
            # 登录就废了。程序长期自动重登显然需要免验证码，所以选「是」。
            want = "是"
            self._tr(f"没有界面可询问，默认登记为信任设备：{want}")

        self._tr(f"「记为信任设备」最终选择：{want}")
        if want == "是":
            step("已把本机登记为「信任设备」（180 天内再登录不用验证码）。",
                 human=True)
        else:
            step("这次不登记信任设备 —— 下次登录还会要验证码。", human=True)

        pick = next((r for r, v in radios if v == want), None) or radios[0][0]
        self._trust_choice = want
        try:
            self.actor.check(self.page, pick)
        except Exception:
            try:
                pick.check(timeout=4000)
            except Exception as e:
                self.log(f"勾选「{want}」失败：{e}", "WARN")
        try:
            self.actor.click(self.page, btn)
        except Exception as e:
            self.log(f"点「确定」失败：{e}", "WARN")
            return False
        return True

    def _code_method_radios(self) -> list:
        """二次验证第一步的「选择验证方式」单选按钮。

        返回 [(locator, value, 显示文字)]。

        实测（2026-09-14 用 Edge+无头逼出来的真实页面）：
            URL  https://id.tsinghua.edu.cn/do/off/ui/auth/login/check
            <input name="type" type="radio" value="wechat" checked>
            <input name="type" type="radio" value="mobile">
            <button type="submit">确定</button>
            正文：为保障您的账号安全，本次登录需要进行二次验证。
                  请选择以下方式之一获取验证码：

        **这一步必须处理**：不选方式、不点「确定」，学校根本不会发验证码，
        也就永远不会出现 #vericode 输入框。以前直接去找输入框，找不到就
        误判成"页面认不出来"，然后问用户要不要开浏览器窗口。
        """
        out = []
        try:
            radios = self.page.locator("input[type=radio][name='type']")
            n = radios.count()
        except Exception:
            return out
        for i in range(n):
            r = radios.nth(i)
            try:
                if not r.is_visible():
                    continue
            except Exception:
                continue
            value = ""
            label = ""
            try:
                value = (r.get_attribute("value") or "").strip()
            except Exception:
                pass
            # 「是/否」是"记为信任浏览器"那一步的选项，不是验证方式，跳过
            if value in self._TRUST_VALUES:
                continue
            try:
                # 单选按钮的文字就在它**后面**的同级节点里。
                # 不能用 closest('label')：实测外层 label 把两个选项都包住了，
                # 那样两项会取到同一段文字（第二项会错显成第一项的文案）。
                label = (r.evaluate(r"""el => {
                    let t = '';
                    let n = el.nextSibling;
                    while (n) {
                        if (n.nodeType === 3) t += n.textContent;
                        else if (n.nodeType === 1) t += (n.innerText || n.textContent || '');
                        n = n.nextSibling;
                    }
                    return t.trim();
                }""") or "").strip()
            except Exception:
                pass
            # 显示名优先用我们自己起的简短中文 —— 学校那句太长了，
            # 放在按钮上不好看；认不出的取值才退回页面原文。
            label = self._METHOD_LABELS.get(value) or label or value or f"方式{i + 1}"
            out.append((r, value, " ".join(label.split())))
        return out

    def _wait_method_page(self, timeout: float = 12.0) -> bool:
        """等「选择验证方式」这一屏渲染出来。

        二次验证页是 React 单页应用，页面加载完 ≠ 表单画好了。实测：刚检测到
        二次验证时按钮还没渲染出来，看一眼就断言"认不出来"会误判成失败。
        """
        end = time.time() + timeout
        while time.time() < end:
            if self._code_method_radios() and \
                    self._find_by_texts(("确定", "确认", "下一步", "继续")) is not None:
                return True
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                time.sleep(0.25)
        return False

    def _solve_method_selection(self, step, ask, human_timeout: float) -> str:
        """处理「选择验证方式 + 点确定」这一步。

        返回 "sent"（已请求发送验证码）/ "visible"（用户要求改用浏览器窗口）
        / "cancel"（用户取消）/ "none"（这一步不存在或没做成）。
        """
        radios = self._code_method_radios()
        if not radios:
            return "none"
        btn = self._find_by_texts(("确定", "确认", "下一步", "继续", "提交"))
        if btn is None:
            return "none"

        values = [v for _, v, _ in radios]
        labels = [lab or v or f"方式{i+1}" for i, (_, v, lab) in enumerate(radios)]
        self._tr(f"验证方式选项：{list(zip(values, labels))}")

        # 默认选短信：手机上收验证码最省事（页面默认选的是微信）
        default_idx = 0
        for i, v in enumerate(values):
            if v == "mobile" or "短信" in labels[i] or "手机" in labels[i]:
                default_idx = i
                break

        idx = default_idx
        if len(radios) > 1 and ask is not None:
            choices = [{"label": labels[i], "value": f"__choice__:{i}"}
                       for i in range(len(radios))]
            ans = ask("学校要求二次验证。请选择验证码发到哪里：",
                      choices=choices, allow_code=False, allow_visible=True,
                      timeout=human_timeout)
            if ans is None:
                return "cancel"
            if ans == HUMAN_VISIBLE:
                return "visible"
            if isinstance(ans, str) and ans.startswith("__choice__:"):
                try:
                    idx = int(ans.split(":", 1)[1])
                    if not (0 <= idx < len(radios)):
                        idx = default_idx
                except Exception:
                    idx = default_idx

        if not self._click_method(radios[idx][0], btn, labels[idx], step):
            return "none"
        try:
            self.page.wait_for_timeout(1800)
        except Exception:
            time.sleep(1.8)
        return "sent"

    def _click_method(self, radio, btn, label: str, step) -> bool:
        """选中某个方式并点「确定」。"""
        try:
            self.actor.check(self.page, radio)
        except Exception:
            try:
                radio.check(timeout=4000)
            except Exception as e:
                self.log(f"选中「{label}」失败：{e}", "WARN")
        step(f"已选择「{label}」，正在请学校发送验证码…", human=True)
        try:
            self.actor.click(self.page, btn)
        except Exception as e:
            self.log(f"点「确定」失败：{e}", "WARN")
            return False
        return True

    def _try_other_method(self, step) -> bool:
        """换一种验证方式重新请求验证码（短信 ↔ 微信）。"""
        radios = self._code_method_radios()
        if len(radios) < 2:
            return False
        btn = self._find_by_texts(("确定", "确认", "下一步", "继续", "提交"))
        if btn is None:
            return False
        checked = 0
        for i, (r, _v, _lab) in enumerate(radios):
            try:
                if r.is_checked():
                    checked = i
                    break
            except Exception:
                pass
        other = 1 - checked if len(radios) == 2 else (checked + 1) % len(radios)
        r, _v, lab = radios[other]
        self.log(f"改用「{lab}」重新发送验证码。", "WARN")
        if not self._click_method(r, btn, lab, step):
            return False
        try:
            self.page.wait_for_timeout(1800)
        except Exception:
            time.sleep(1.8)
        return True

    def _fill_code(self, box, code: str) -> bool:
        """用**真实键盘**把验证码一个字一个字敲进去，敲完回读确认。

        刻意**不用** JS 直接设 value：这个项目的原则就是"像人一样操作"，
        而且合成出来的事件 isTrusted=false，本身就是最典型的脚本特征。

        为什么敲完要回读：二次验证页是 React 受控组件，个别情况下值没进
        state，提交时服务端收到的是空 —— 表现就是"验证码明明对着却总说不对"。
        回读能当场发现，然后**重新敲一遍**（而不是用 JS 硬塞）。
        """
        for attempt in range(3):
            try:
                self.actor.click(self.page, box)          # 真实鼠标点击聚焦
            except Exception:
                try:
                    box.click(timeout=5000)
                except Exception:
                    pass
            try:
                box.fill("")                              # 清掉可能的残留
            except Exception:
                pass
            try:
                # press_sequentially：逐字符真实 keydown/keypress/keyup
                box.press_sequentially(code, delay=random.uniform(60, 140))
            except Exception:
                try:
                    for ch in code:
                        box.press(ch)
                        time.sleep(random.uniform(0.06, 0.14))
                except Exception as e:
                    self.log(f"键入验证码失败（第 {attempt + 1} 次）：{e}", "WARN")
                    continue
            got = ""
            try:
                got = (box.input_value() or "").strip()
            except Exception:
                pass
            if got == code:
                return True
            self.log(f"回读发现框里是「{got}」而不是验证码，重新敲一遍。", "WARN")
            try:
                self.page.wait_for_timeout(350)
            except Exception:
                time.sleep(0.35)
        return False

    def _confirm_seems_submitted(self, before_hint: str, box,
                                 timeout: float = 6.0) -> bool:
        """点完「确定」后，判断这次点击到底生效没有。

        任一条成立就算生效：URL 变了 / 验证码输入框没了 / 页面出现了新提示。
        都没发生 → 多半这次点击没落上，值得用原生点击再补一次。
        """
        u0 = ""
        try:
            u0 = self.page.url
        except Exception:
            pass
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page.url != u0:
                    return True
                if box is None or box.count() == 0:
                    return True
                if self._page_hint(160) != before_hint:
                    return True
            except Exception:
                return True
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                time.sleep(0.25)
        return False

    def _page_hint(self, limit: int = 200) -> str:
        """抓页面上的提示语（二次验证页会把服务端的出错信息显示出来）。"""
        try:
            return " ".join((self.page.inner_text("body") or "").split())[:limit]
        except Exception:
            return ""

    def _wait_landing_or_error(self, timeout: float = 25.0) -> str:
        """提交验证码之后，等「进系统」或「服务端报错」。

        实测（真实接口 /b/doubleAuth/login）：对错都是 1 秒内就回，
        并且页面会立刻显示服务端的话。例如
            {"result":"error","msg":"校验码已失效，请重新发送。"}
        所以要盯这个，而不是傻等 90 秒 —— 学校发的验证码只有 **3 分钟**
        有效期，白等就是真过期。

        返回 "ok" / "trust"（到了"记为信任"那一步）/ "error" / "timeout"。
        """
        base = self._page_hint(200)
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self._landed():
                    return "ok"
                # 验证通过后学校会问"是否记为信任浏览器"—— 那也是页面变了，
                # 但它是好消息，不能当成出错
                if self._trust_radios():
                    return "trust"
                if self._page_hint(200) != base:
                    return "error"
            except Exception:
                pass
            try:
                self.page.wait_for_timeout(300)
            except Exception:
                time.sleep(0.3)
        return "timeout"

    def _wait_code_input(self, timeout: float = 12.0):
        """等验证码输入框渲染出来。

        二次验证页是 React 单页应用（源码里是 React.createElement 建出来的），
        页面加载完 ≠ 表单已经画好。看一眼就断言"认不出来"会误判，
        所以这里等一会儿，边等边试。
        """
        end = time.time() + timeout
        while True:
            loc = self._find_code_input()
            if loc is not None:
                return loc
            if time.time() >= end:
                return None
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                time.sleep(0.25)

    def _solve_second_factor_here(self, step, ask, human_timeout: float):
        """**不打开浏览器窗口**完成二次验证。

        做法：程序在（后台的）页面上找到验证码输入框和提交按钮，通过主窗口
        向你要验证码，然后替你填进去提交。

        页面结构取自学校二次验证前端的真实源码（doubleAuth.bundle.js）：
            <input name="vericode" id="vericode" maxlength="6" inputmode="numeric">
            <button type="submit">确认</button>
            <a class="text-muted">…重新发送…</a>       ← 带倒计时

        返回 True 表示过了；返回 None 表示这个页面程序认不出来（交给上层
        去问用户要不要改开浏览器窗口）。
        """
        if not self.is_alive():
            self.revive(visible=False)
        step("检测到二次验证，正在识别验证页面…")

        # ---- 第一步：可能有「选择验证方式」页 ----
        # 必须先等它渲染出来（React 单页应用是异步画的），否则会误判成认不出来。
        if self._wait_method_page(timeout=12.0):
            res = self._solve_method_selection(step, ask, human_timeout)
            if res == "cancel":
                raise LoginCancelled("已取消登录。")
            if res == "visible":
                return None
            if res == "sent":
                # 万一点完没出现验证码输入框（比如短信没登记成功），
                # 换成另一种方式再试一次
                if self._wait_code_input(timeout=12.0) is None:
                    self.log("点了确定但没出现验证码输入框，换一种验证方式重试…",
                             "WARN")
                    alt = self._try_other_method(step)
                    if alt:
                        step("已改用另一种方式重新发送，请查收。", human=True)

        box = self._wait_code_input(timeout=15.0)
        if box is None:
            self._tr("二次验证页认不出验证码输入框")
            return None
        # 提交按钮也可能晚一点才渲染出来
        submit = None
        end = time.time() + 6.0
        while submit is None and time.time() < end:
            submit = self._find_submit_button()
            if submit is None:
                try:
                    self.page.wait_for_timeout(250)
                except Exception:
                    time.sleep(0.25)
        if submit is None:
            self._tr("二次验证页认不出提交按钮")
            return None

        for attempt in range(3):
            step("请在程序窗口里输入收到的验证码。", human=True)
            answer = ask("请输入收到的 6 位验证码（学校发的短信/微信验证码 3 分钟内有效）。",
                         image=self._captcha_image(),
                         allow_resend=self._find_resend_control() is not None,
                         allow_visible=True,
                         timeout=human_timeout)
            if answer is None:
                raise LoginCancelled("已取消登录。")
            if answer == HUMAN_VISIBLE:
                return None
            if answer == HUMAN_RESEND:
                resend = self._find_resend_control()
                if resend is not None:
                    try:
                        self.actor.click(self.page, resend)
                        self.page.wait_for_timeout(1500)
                        step("已重新发送验证码，请查收。", human=True)
                    except Exception as e:
                        self.log(f"重新发送验证码没成功：{e}", "WARN")
                continue

            try:
                filled = self._fill_code(box, answer)
                self._tr(f"验证码已键入（回读一致={filled}）")
                if not filled:
                    self.log("验证码没能正确敲进输入框，重新来一次。", "WARN")
                    step("刚才没输进去，请再输一次。", human=True)
                    continue
                before = self._page_hint(160)
                self.actor.click(self.page, submit)      # 真实鼠标点击
                if not self._confirm_seems_submitted(before, box):
                    # 点了没反应 → 用 Playwright 原生点击补一次（同样是真实事件，
                    # 只是会等元素可点、并且点得更准）
                    self.log("第一次点「确定」似乎没生效，补一次原生点击。", "WARN")
                    try:
                        submit.click(timeout=8000)
                    except Exception as e:
                        self.log(f"补点击也失败：{e}", "WARN")
                    self._confirm_seems_submitted(before, box, timeout=5.0)
            except Exception as e:
                self.log(f"提交验证码失败：{e}", "WARN")
                return None

            outcome = self._wait_landing_or_error(25.0)
            if outcome == "ok":
                step("✅ 验证通过。")
                return True
            if outcome == "trust":
                # 验证码对了，学校在问"要不要把本设备登记为信任设备"。
                self._did_2fa = True
                if self._solve_trust_step(step, ask, human_timeout):
                    # 记完之后学校会 redirect2Jsp → 选课系统。
                    # 但**别只靠页面文案判断**（实测这里有误判），
                    # 直接去确认一次会话是不是真的好了。
                    if self._wait_landing(20, on_progress=None) == "ok":
                        step("✅ 二次验证通过，已进入选课系统。")
                        return True
                    step("正在确认登录状态…", human=True)
                    if self.is_logged_in():
                        step("✅ 二次验证通过（会话已建立）。")
                        return True
                    self.log("记完信任后会话仍未建立，交给上层重试。", "WARN")
                return None
            if outcome == "error":
                # 把服务端的原话告诉你 —— 尤其是"已失效"，那要重发而不是重输
                hint = self._page_hint(160)
                self.log(f"服务端提示：{hint}", "WARN")
                expired = any(k in hint for k in ("失效", "过期", "重新发送"))
                if expired:
                    step("验证码已失效（学校发的码只有 3 分钟有效）。"
                         "请点「重新发送验证码」再试。", human=True)
                else:
                    step(f"没通过：{hint}", human=True)
            else:
                step("验证码好像不对，请再输一次。", human=True)
            # 失败后页面可能重绘，重新找一次输入框
            box = self._wait_code_input(timeout=6.0) or box
            submit = self._find_submit_button() or submit
        raise PageError("二次验证连续 3 次没通过，请稍后在浏览器窗口里完成。")

    def _captcha_visible(self) -> bool:
        """SSO 的图形验证码**是不是真的要求填**。

        实测（2026-09-14 抓的真实页面）：页面上**永远**有这一段

            <div id="c_code" class="form-group hidden">
              <input type="text" id="i_code" placeholder="图形验证码" name="i_captcha">
              <img id="captcha" width="60" height="45" src="/captcha.jpg?t=...">
            </div>

        平时靠 class="hidden" 藏着，只有服务器要求时才由 JS 去掉。页面自己的
        doLogin() 也是这么判断的：`if (!$("#c_code").hasClass("hidden")) {...}`。

        ⚠ 所以**绝对不能**用「HTML 里有没有『验证码』字样」来判断 —— 那段永远在，
        那样会永远判成需要验证码，让用户去输一个根本没显示、也没发过来的码。
        （这正是之前"没收到验证码"的原因。）
        """
        try:
            box = self.page.locator("#c_code").first
            if box.count():
                cls = (box.get_attribute("class") or "")
                if "hidden" in cls.split():
                    return False
        except Exception:
            pass
        # 兜底：只认"真的看得见"的输入框或图片
        for sel in ("#i_code", "#c_code input", "img#captcha"):
            if self._visible_locator(sel) is not None:
                return True
        return False

    def _refresh_captcha(self):
        """换一张图形验证码（点图片，页面自带 onclick="refreshCaptcha()"）。"""
        for sel in ("img#captcha", "#c_code img"):
            try:
                loc = self.page.locator(sel).first
                if loc.count():
                    loc.click(timeout=3000)
                    self.page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
        return False

    def _safe_body_text(self, limit: int = 500) -> str:
        try:
            if self.page.locator("body").count() == 0:
                return ""
            return (self.page.inner_text("body") or "")[:limit]
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # 会话检查 / 自动重登
    # ------------------------------------------------------------------
    def is_logged_in(self) -> bool:
        try:
            self._navigate("yxSearchTab", tokenPriFlag="yx", force_check=True)
            html = self.page.content()
            return len(html) > 5000 and "已选定课程" in html and "token" in html
        except Exception:
            return False

    def _verify_session(self) -> bool:
        """登录后确认会话**真的**可用，而不是"落地页看着对"。

        为什么必须验：实测全新浏览器配置（这台设备还没登记过信任）下，
        学校那边会接受登录、把我们送到 m=main，但**不给有效会话** ——
        之后所有数据页拿到的都是 355 字节的「登陆超时」小页面。

        以前只看"落地页在教务域名下"就宣布登录成功，于是程序带着一个
        死会话进入监听，每次轮询都撞会话失效、反复重登。现在多花一次
        数据页读取，把这个谎话堵掉。
        """
        try:
            return bool(self.is_logged_in())
        except Exception:
            return False

    def ensure_login(self, user: str, password: str, **kw) -> bool:
        if self.is_logged_in():
            return True
        self.log("会话已失效，自动重新登录…", "WARN")
        self.login(user, password, **kw)
        return self.is_logged_in()

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def _url(self, m: str, **params) -> str:
        q = {"m": m, "p_xnxq": self.xnxq}
        q.update({k: v for k, v in params.items() if v not in (None, "")})
        return BASE + "xkBks.vxkBksXkbBs.do?" + urlencode(q)

    _FIND_SITE_LINK = r"""
    (want) => {
      // 只读：找出指向 want 的**可见**链接，返回它在 a[href] 列表里的下标。
      // 不修改任何 DOM —— 只做查询。
      const norm = (h) => {
        try {
          const u = new URL(h, location.href);
          const ps = Array.from(u.searchParams.entries()).sort();
          return u.origin + u.pathname + '?' +
                 ps.map(([k, v]) => k + '=' + v).join('&');
        } catch (e) { return ''; }
      };
      const target = norm(want);
      const now = norm(location.href);
      if (!target || target === now) return -1;
      const all = Array.from(document.querySelectorAll('a[href]'));
      for (let i = 0; i < all.length; i++) {
        const a = all[i];
        // 隐藏的链接（折叠菜单）点了也没用，跳过
        if (!(a.offsetParent !== null || a.getClientRects().length)) continue;
        if (norm(a.href) === target) return i;
      }
      return -1;
    }
    """

    def _click_site_link(self, url: str) -> bool:
        """当前页面里若有指向 url 的**可见站内链接**，就用真实点击走它。

        为什么绕这一下：直接 goto 时浏览器发出的文档请求是
        `Sec-Fetch-Site: none` 且**没有 Referer**；而真人从菜单点进去是
        `Sec-Fetch-Site: same-origin` + 上一页作 Referer。
        这个头就是给服务端判断「本次导航是不是站内内容发起的」，查起来零成本。

        点真实链接时这些头由浏览器自己算出来，**不需要伪造任何东西**。
        （反过来，手动塞一个 Referer 去 goto 会造出「有 Referer 但
        Sec-Fetch-Site 是 none」这种自相矛盾的组合，比直开更可疑，所以不做。）

        只在找到**完全一致**的链接时才走这条路 —— 避免点了别的菜单项、
        拿回一份不相干的课程列表。
        """
        try:
            idx = self.page.evaluate(self._FIND_SITE_LINK, url)
            if not isinstance(idx, int) or idx < 0:
                return False
            link = self.page.locator("a[href]").nth(idx)
            self._tr(f"navigate 经站内链接 #{idx}")
            self.actor.click(self.page, link)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            # **点完必须确认真的过去了**。只凭"点了"不够：链接可能被
            # 拦掉、可能是被 JS 接管后什么都不做。真没过去却返回 True，
            # 上层就会把 _loaded 标成目标页，后面读到的是上一页的数据 ——
            # 这种错比慢一点危险得多。
            # 用页面自己的 location.href 判断（最可靠），并且只比对 m 参数：
            # 服务端可能补/去别的参数，但我们关心的是"是不是同一个页面"。
            want_m = self._query_param(url, "m")
            want_norm = self._norm_url(url)
            end = time.time() + 12
            while time.time() < end:
                try:
                    cur = self.page.evaluate("() => location.href") or ""
                except Exception:
                    cur = ""
                if cur:
                    # 有 m 参数时按 m 判：服务端可能补/去别的参数，
                    # 但我们只关心"是不是同一个页面"。
                    if want_m:
                        if self._query_param(cur, "m") == want_m:
                            return True
                    elif self._norm_url(cur) == want_norm:
                        return True
                time.sleep(0.2)
            self._tr("navigate 点了站内链接但页面没过去，改用直接导航")
            return False
        except Exception as e:
            self._tr(f"navigate 走站内链接失败：{e}")
            return False

    @staticmethod
    def _query_param(url: str, name: str) -> str:
        """从一个 URL 里取一个查询参数。取不到返回空串。"""
        try:
            from urllib.parse import urlparse, parse_qs
            return (parse_qs(urlparse(url).query).get(name) or [""])[0]
        except Exception:
            return ""

    @staticmethod
    def _norm_url(url: str) -> str:
        """规范化 URL：去掉 fragment、查询参数排序。

        与页面上那段查找链接的 JS 里的 norm() 保持一致，两边才算得一样。
        """
        try:
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            u = urlparse(url)
            q = urlencode(sorted(parse_qsl(u.query)))
            return urlunparse((u.scheme, u.netloc, u.path, "", q, ""))
        except Exception:
            return url

    def _navigate(self, m: str, *, force_check: bool = False, pause_range=(0.25, 0.7),
                  **params):
        """在浏览器里打开一个子系统页面（真实导航 + 真人的短暂停顿）。"""
        self._ensure_alive("navigate")
        key = (m, tuple(sorted((k, str(v)) for k, v in params.items())))
        if not force_check and self._loaded == key:
            return self.page
        url = self._url(m, **params)
        self._tr(f"navigate {url}")
        # 先试站内链接；找不到一致的链接才直接开 URL。
        if not self._click_site_link(url):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                # 窗口正好在这一瞬间被用户关掉：上面的 _ensure_alive 检查过了也没用，
                # 因为关闭发生在那之后。重开一次再来。
                if not self._looks_closed(e):
                    raise
                self.log("导航过程中浏览器窗口被关闭，重新打开后重试本次导航…", "WARN")
                if not self.revive():
                    raise
                self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._loaded = key
        if pause_range:
            self.actor.ui_pause(*pause_range)
        # 会话失效会落到 355 字节的「登陆超时」小页面
        try:
            html_len = len(self.page.content())
        except Exception:
            html_len = 99999
        if html_len < 1500:
            self._loaded = None
            self._tr(f"navigate 失败：页面只有 {html_len} 字节（登陆超时）")
            raise SessionExpired("会话已失效（页面提示登陆超时）")
        self._tr(f"navigate 完成 {m}  {html_len} 字节")
        return self.page

    # ------------------------------------------------------------------
    # 伪装：闲逛 / 改窗口大小 / 切标签页
    # ------------------------------------------------------------------
    #
    # 为什么需要这些：服务端日志里，这个程序原本只呈现一种形态 ——
    # 同一个 m=yxSearchTab 端点被精确重复几百次，中间不访问任何其他页面。
    # 真人在教务系统里是会点来点去的。下面三个动作就是用来打散这个形态的。
    #
    # 它们**花的是两次轮询之间本来就要等掉的时间**，不是额外延时，
    # 所以对抢课时机没有影响（由调度器负责塞进空闲窗口）。

    # 闲逛目标：真人在等放课时会看的页面。
    # main 权重高（最常回去看），showTree 是左侧菜单（frameset 的框架页），
    # cxSearchTab 是选课页本身。
    BROWSE_TARGETS = ("main", "main", "cxSearchTab", "main", "showTree")

    def browse_somewhere(self, m: str | None = None) -> bool:
        """像真人一样到别的页面看一眼。失败一律吞掉（只是伪装，不影响监听）。"""
        self._ensure_alive("browse")
        m = m or random.choice(self.BROWSE_TARGETS)
        try:
            self._navigate(m, pause_range=(0.35, 1.05))
        except Exception as e:
            self._loaded = None
            self._tr(f"闲逛 {m} 没成功（忽略）：{type(e).__name__}: {e}")
            return False
        # 已经把会话带到别的页面了，必须让下一轮轮询重新导航，
        # 否则 _navigate 会以为"还在选课页"而直接返回。
        self._loaded = None
        self.actor.browse_around(self.page, seconds=random.uniform(2.5, 6.0))
        self._tr(f"闲逛了一下：{m}")
        return True

    def nudge_window(self) -> bool:
        """改变**真实窗口**的大小（等价于用户拖窗口边缘）。

        用 CDP 的 Browser.setWindowBounds 改的是操作系统窗口，不是页面视口 ——
        因为浏览器是 no_viewport 启动的，视口会跟着窗口一起变，
        所以 outerWidth/innerWidth/screenX/screenY 全都保持自洽。

        真人用久了窗口大小是会变的；一个开了六个小时、尺寸一动不动、
        坐标永远在 (10,10) 的窗口，本身也是个信号。
        """
        self._ensure_alive("window")
        try:
            cdp = self.page.context.new_cdp_session(self.page)
        except Exception as e:
            self._tr(f"拿不到 CDP 会话，跳过改窗口：{e}")
            return False
        try:
            info = cdp.send("Browser.getWindowForTarget")
        except Exception as e:
            self._tr(f"getWindowForTarget 失败，跳过改窗口：{e}")
            try:
                cdp.detach()
            except Exception:
                pass
            return False
        try:
            wid = info.get("windowId")
            if wid is None:
                return False
            sw, sh, _ = logical_screen()
            if sw < 800:
                sw, sh = 1707, 960
            # 挑一个还装得下的尺寸；窗口外框比 inner 大，所以留足余量
            w = min(random.choice((1280, 1330, 1400, 1460, 1520)), max(900, sw - 80))
            h = min(random.choice((740, 800, 855, 895)), max(560, sh - 140))
            cdp.send("Browser.setWindowBounds", {
                "windowId": wid,
                "bounds": {"width": int(w), "height": int(h), "windowState": "normal"},
            })
            # 窗口变了，HumanActor 里缓存的视口尺寸就废了 —— 必须清掉，
            # 否则后面鼠标坐标会算到窗口外面去。
            try:
                self.actor._vw = 0
                self.actor._vh = 0
            except Exception:
                pass
            self._tr(f"把窗口调成了 {w}x{h}")
            return True
        except Exception as e:
            self._tr(f"setWindowBounds 失败，跳过：{e}")
            return False
        finally:
            try:
                cdp.detach()
            except Exception:
                pass

    def flash_tab(self, *, m: str = "main") -> bool:
        """多开一个标签页看一眼，来回切几次，再关掉。

        标签页是**真标签页**（同一个浏览器窗口里的新标签），不是新窗口 ——
        真人在等放课时会开一个标签去查别的课，再切回来。
        """
        self._ensure_alive("tab")
        main_page = self.page
        try:
            extra = self.page.context.new_page()
        except Exception as e:
            self._tr(f"开新标签页失败，跳过：{e}")
            return False
        try:
            try:
                extra.goto(self._url(m), wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                self._tr(f"新标签页导航失败（忽略）：{e}")
                return False
            self.actor.browse_around(extra, seconds=random.uniform(1.5, 3.5))
            # 来回切几次焦点
            for _ in range(random.randint(1, 3)):
                try:
                    extra.bring_to_front()
                except Exception:
                    pass
                self.actor.ui_pause(0.5, 1.4)
                try:
                    main_page.bring_to_front()
                except Exception:
                    pass
                self.actor.ui_pause(0.4, 1.1)
            self._tr("开了一个标签页又切了回来")
            return True
        except Exception as e:
            self._tr(f"切标签页出错（忽略）：{e}")
            return False
        finally:
            try:
                extra.close()
            except Exception:
                pass
            try:
                main_page.bring_to_front()
            except Exception:
                pass
            # 主页面可能因为切来切去被重新加载/换了地址，让下轮轮询重新导航
            self._loaded = None

    # ------------------------------------------------------------------
    # 读：学期列表
    # ------------------------------------------------------------------
    def read_semesters(self) -> tuple[str, list[tuple[str, str]]]:
        """读教务系统的学期下拉。

        左侧菜单栏（m=showTree）里有个 name="menu1" 的下拉，带当前学期和历史学期。
        有了它就不用把学期写死在配置里 —— 换学期、换机器都能自适应。

        返回 (当前学期值, [(值, 显示名), …])；读不到就返回 ("", [])。
        """
        self._ensure_alive("read_semesters")
        try:
            self.page.goto(BASE + "xkBks.vxkBksXkbBs.do?m=showTree",
                           wait_until="domcontentloaded", timeout=30000)
            self._loaded = None
            self.actor.ui_pause(0.15, 0.4)
            info = self.page.evaluate(
                "() => { const s = document.querySelector('select[name=menu1], select#menu1');"
                " if (!s) return null;"
                " return {value: s.value,"
                "         opts: Array.from(s.options).map(o => [o.value, (o.text||'').trim()])}; }")
            if not info:
                return "", []
            opts = [(str(v), str(t)) for v, t in info.get("opts", []) if v]
            return str(info.get("value") or ""), opts
        except Exception as e:
            self.log(f"读取学期列表失败：{e}", "WARN")
            return "", []

    # ------------------------------------------------------------------
    # 读：当前选课阶段
    # ------------------------------------------------------------------
    def read_phase_text(self) -> str:
        """一级选课页顶部的「当前选课阶段：…」。"""
        self._ensure_alive("read_phase_text")
        try:
            self.page.goto(BASE + f"xkBks.vxkBksXkbBs.do?m=selectKc&p_xnxq={self.xnxq}",
                           wait_until="domcontentloaded", timeout=45000)
            self._loaded = None
            self.actor.ui_pause(0.3, 0.8)
            txt = self.page.evaluate(
                "() => { try { return typeof getData === 'function' ? getData() : ''; }"
                " catch (e) { return ''; } }")
            return re.sub(r"<[^>]*>|&nbsp;", " ", txt or "").strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # 读：课程列表（课余量）
    # ------------------------------------------------------------------
    def read_capacity_rows(self, kind: str, *, kch: str = "", kcm: str = "",
                           kxh: str = "", navigate: bool = True) -> list[CapacityRow]:
        """读某类课程列表页的每一行（课余量/时间/教师/选课文字说明）。

        kch 是纯数字，可以安全地放进 URL；kcm 含中文，走页面搜索框更稳妥。
        """
        info = COURSE_KINDS[kind]
        self._ensure_alive("read_capacity_rows")
        if navigate:
            self._navigate(info["search"], tokenPriFlag=kind, p_kch=kch, p_kxh=kxh,
                           **info.get("extra", {}))
            self.current_list = {"kind": kind, "kch": kch}
        rows = self._parse_grid()
        if rows:
            return rows
        return self._parse_table()

    # 各类课程页的列不完全一样（必修 10 列、任选 11 列、体育 8 列），
    # 所以按页面自己给出的 gridColumns 表头来定位列，而不是写死下标。
    _COL_ALIASES = {
        "kch": ("课程号",),
        "kxh": ("课序号",),
        "name": ("课程名", "课程名称"),
        "kyl": ("课余量", "余量"),
        "queue": ("队列",),
        "time_text": ("上课时间", "时间"),
        "teacher": ("任课教师", "教师"),
        "note": ("选课文字说明", "文字说明", "说明"),
    }

    def _column_map(self) -> dict:
        """列名 → 下标。不同页面用的数组名不一样，最后再退回读 DOM 表头。"""
        m = {}
        try:
            cols = self.page.evaluate(
                "() => { for (const n of ['gridColumns','gridColumnsbxk','gridColumnsrxt','gridColumnsxx'])"
                " { try { if (typeof window[n] !== 'undefined' && window[n]) return window[n]; }"
                " catch (e) {} } return null; }")
        except Exception:
            cols = None
        if isinstance(cols, list):
            for field, aliases in self._COL_ALIASES.items():
                for i, c in enumerate(cols):
                    c = re.sub(r"<[^>]*>|//.*$", "", str(c)).strip()
                    if any(a in c for a in aliases):
                        m[field] = i
                        break
        if len(m) >= 4:
            return m

        # 退回：读页面上的表头单元格
        try:
            ths = self.page.locator("table#table_h tr td, table#table_h tr th")
            for i in range(ths.count()):
                t = re.sub(r"<[^>]*>", "", (ths.nth(i).inner_text() or "")).strip()
                for field, aliases in self._COL_ALIASES.items():
                    if field not in m and any(a in t for a in aliases):
                        m[field] = i
        except Exception:
            pass
        return m

    def _parse_grid(self) -> list[CapacityRow]:
        """页面自己的 JS 数组 gridData —— 页面就是用它在渲染表格的。"""
        try:
            data = self.page.evaluate(
                "() => (typeof gridData === 'undefined') ? null : gridData")
        except Exception:
            return []
        if not isinstance(data, list) or not data:
            return []
        cm = self._column_map()
        i_kch = cm.get("kch", 1)
        i_kxh = cm.get("kxh", 2)
        i_name = cm.get("name", 3)
        i_kyl = cm.get("kyl", 4)
        i_queue = cm.get("queue")
        i_time = cm.get("time_text", 5)
        i_teacher = cm.get("teacher", 6)
        i_note = cm.get("note")

        out = []
        for r in data:
            def cell(i):
                if i is None or i >= len(r):
                    return ""
                return re.sub(r"<[^>]*>", "", str(r[i])).strip()

            try:
                m = re.search(r"value='([^']*)'", str(r[0]))
                nm = re.search(r"<a[^>]*>([^<]*)</a>", str(r[i_name]))
                out.append(CapacityRow(
                    kch=cell(i_kch), kxh=cell(i_kxh),
                    name=(nm.group(1) if nm else cell(i_name)).strip(),
                    kyl=_int(cell(i_kyl)),
                    queue=cell(i_queue),
                    time_text=cell(i_time),
                    teacher=cell(i_teacher),
                    note=cell(i_note),
                    cid=m.group(1) if m else "",
                ))
            except Exception:
                continue
        return out

    def _parse_table(self) -> list[CapacityRow]:
        """回退：直接解析 DOM。表头也按名字找列。"""
        # 先读表头
        head = {}
        try:
            ths = self.page.locator("table#table_h tr td, table#table_h tr th")
            for i in range(ths.count()):
                t = re.sub(r"<[^>]*>", "", (ths.nth(i).inner_text() or "")).strip()
                for field, aliases in self._COL_ALIASES.items():
                    if field not in head and any(a in t for a in aliases):
                        head[field] = i
        except Exception:
            pass
        i_kch = head.get("kch", 1)
        i_kxh = head.get("kxh", 2)
        i_name = head.get("name", 3)
        i_kyl = head.get("kyl", 4)
        i_time = head.get("time_text", 5)
        i_teacher = head.get("teacher", 6)
        i_note = head.get("note")

        out = []
        try:
            trs = self.page.locator("table#table_t tr.trr2")
            for i in range(trs.count()):
                tr = trs.nth(i)
                n = tr.locator("td").count()
                cells = [(tr.locator("td").nth(j).inner_text() or "").strip() for j in range(n)]

                def cell(ix):
                    return cells[ix] if (ix is not None and ix < len(cells)) else ""

                if len(cells) < 5:
                    continue
                cb = tr.locator("input[type=checkbox]").first
                out.append(CapacityRow(
                    kch=cell(i_kch), kxh=cell(i_kxh), name=cell(i_name),
                    kyl=_int(cell(i_kyl)), time_text=cell(i_time),
                    teacher=cell(i_teacher), note=cell(i_note),
                    cid=(cb.get_attribute("value") or "") if cb.count() else ""))
        except Exception:
            pass
        return out

    def _grid_signature(self) -> str:
        """表格内容指纹，用来判断"查询结果刷新了没有"。

        注意各类别页面渲染方式不同（实测）：
          * 体育 / 任选：数据在 JS 数组 gridData 里，DOM 里**没有** tr.trr2
          * 必修 / 限选：反过来，DOM 里有 tr.trr2，gridData 不存在
        所以两种都要看，只盯一个会永远读不到"变了没有"。
        """
        try:
            return str(self.page.evaluate(r"""() => {
              const dom = Array.from(document.querySelectorAll('table#table_t tr.trr2'))
                .slice(0, 4)
                .map(tr => Array.from(tr.querySelectorAll('td')).slice(0, 4)
                  .map(td => (td.innerText || '').trim()).join(',')).join('|');
              const g = (typeof gridData === 'undefined' || !gridData) ? ''
                : gridData.slice(0, 4)
                    .map(r => String(r[1]) + ',' + String(r[2]) + ',' + String(r[3]))
                    .join('|');
              return dom + '##' + g;
            }"""))
        except Exception:
            return ""

    def _wait_grid_changed(self, before: str, timeout: float = 3.5) -> bool:
        """等表格内容真的变过来（查询结果是 POST 回来的，要等）。

        不等的话会读到**上一次**的结果 —— 实测：查必修课 30120163 却拿到默认
        列表里 14 行无关课程，而稍后再读就是正确的。

        超时给得比较短（3.5 秒）：有些页面上的「查询」按钮 onclick 指向的函数
        根本没定义，点了毫无反应，死等只会白拖时间。真查询实测 2 秒内就回来了。
        """
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.page.wait_for_timeout(200)
            except Exception:
                time.sleep(0.2)
            now = self._grid_signature()
            if now and now != before:
                return True
        return False

    def search_course_human(self, kind: str, keyword: str, *, by_kch: bool = False
                            ) -> list[CapacityRow]:
        """用页面自带的搜索框查询（真人打字 + 点「查询」）。

        中文不适合塞进 URL（页面是 GBK），所以这一步必须走页面表单：
        浏览器会用页面自身的编码提交 POST，服务端才认。
        任选课尤其明显 —— 不搜索的话永远是「没有记录」。
        """
        self._ensure_alive("search_course_human")
        a = self.actor
        info = COURSE_KINDS[kind]
        self._navigate(info["search"], tokenPriFlag=kind, pause_range=(0.3, 0.9),
                       **info.get("extra", {}))
        field = "p_kch" if by_kch else "p_kcm"
        box = self.page.locator(f"input[name='{field}']").first
        if box.count() == 0:
            box = self.page.locator("input[name='p_kcm']").first
        if box.count() == 0:
            raise PageError("这个页面没有可用的搜索框")
        self.log(f"在「{info['name']}」里按{'课程号' if by_kch else '课程名'}搜索「{keyword}」…")
        a.type_text(self.page, box, keyword)
        a.ui_pause(0.2, 0.6)
        btn = self.page.locator("input[value='查询']").first
        before = self._grid_signature()
        a.click(self.page, btn)
        # 关键：等结果真的刷新，否则读回来的是上一次的表格
        if not self._wait_grid_changed(before):
            self.log("查询结果似乎没有刷新，再等一会儿…", "WARN")
            a.ui_pause(0.8, 1.4)
        self._loaded = None          # 查询是表单提交，页面状态已变
        self.current_list = {"kind": kind, "kch": keyword if by_kch else ""}
        rows = self._parse_grid() or self._parse_table()
        self.log(f"搜索结果 {len(rows)} 行")
        return rows

    # ------------------------------------------------------------------
    # 读：已选定课程
    # ------------------------------------------------------------------
    def read_selected(self, *, navigate: bool = True) -> list[SelectedCourse]:
        self._ensure_alive("read_selected")
        if navigate:
            self._navigate("yxSearchTab", tokenPriFlag="yx")
        out: list[SelectedCourse] = []
        trs = self.page.locator("tr.trr2")
        for i in range(trs.count()):
            tr = trs.nth(i)
            n = tr.locator("td").count()
            if n < 6:
                continue
            cells = [(tr.locator("td").nth(j).inner_text() or "").strip() for j in range(n)]
            rid = tr.locator("input[name='p_del_id']").first
            del_id = ""
            if rid.count():
                try:
                    del_id = rid.get_attribute("value") or ""
                except Exception:
                    del_id = ""
            out.append(SelectedCourse(
                kind=cells[1], kch=cells[2], name=cells[3], kxh=cells[4],
                time_text=cells[5], teacher=cells[6],
                credit=cells[7] if len(cells) > 7 else "", del_id=del_id))
        return out

    # ------------------------------------------------------------------
    # 写：选课 / 退课（真人操作）
    # ------------------------------------------------------------------
    def submit_selection(self, kind: str, cid: str, *, urgent: bool = False,
                         kch: str = "") -> str:
        """勾选一门课并点「提交」。cid 形如 '2026-2027-1;10721071;2;'。

        如果当前页面已经是筛选好的选课页，就不再重新导航（省一次加载）。
        """
        self._ensure_alive("submit_selection")
        a = self.actor
        info = COURSE_KINDS[kind]
        try:
            self._navigate(info["search"], tokenPriFlag=kind, p_kch=kch,
                           force_check=not self._has_cid(info["field"], cid),
                           pause_range=(0.2, 0.6), **info.get("extra", {}))
        except SessionExpired:
            raise
        if not self._wait_cid(info["field"], cid):
            # URL 参数在必修/限选/任选上是无效的，打开的是默认列表；
            # 目标课不在里面时，用搜索框把它找出来再试一次。
            if kch:
                self.log(f"列表里没找到 {cid}，改用搜索框找…", "WARN")
                try:
                    self.search_course_human(kind, kch, by_kch=True)
                except Exception as e:
                    self.log(f"搜索失败：{e}", "WARN")
            if not self._wait_cid(info["field"], cid):
                raise PageError(f"页面上找不到课程 {cid}（可能已调整或已选满下架）")

        old = a.tempo
        if urgent:
            a.set_tempo(URGENT)
        try:
            cb = self.page.locator(f"input[name='{info['field']}'][value='{cid}']").first
            self.log(f"勾选课程 {cid}")
            self._tr(f"click checkbox {info['field']}={cid}")
            got = a.check(self.page, cb, force_fast=urgent)
            if not got:
                raise PageError(f"勾选课程 {cid} 没成功（可能要重新登录或页面已变）")
            a.ui_pause(0.08, 0.3)
            btn = self.page.locator("input[value='提交']").first
            self.log("点「提交」…")
            self._tr("click 提交")
            a.click(self.page, btn, force_fast=urgent)
            a.ui_pause(0.5, 1.2)
            self._loaded = None
            msg = self.read_result_message()
            self._tr(f"提交结果：{msg}")
            return msg
        finally:
            a.set_tempo(old)

    def drop_course(self, del_id: str, *, urgent: bool = False) -> str:
        """在「已选定课程」里勾选并点「删除」。"""
        self._ensure_alive("drop_course")
        a = self.actor
        self._navigate("yxSearchTab", tokenPriFlag="yx", pause_range=(0.2, 0.6))
        radio = self.page.locator(f"input[name='p_del_id'][value='{del_id}']").first
        # 同样要等渲染：表格是 JS 画出来的
        if not self._wait_selector(f"input[name='p_del_id'][value='{del_id}']"):
            raise PageError(f"选课记录里没有 {del_id}")

        old = a.tempo
        if urgent:
            a.set_tempo(URGENT)
        try:
            self.log(f"勾选要退的课 {del_id}")
            self._tr(f"click radio p_del_id={del_id}")
            if not a.check(self.page, radio, force_fast=urgent):
                raise PageError(f"勾选退课项 {del_id} 没成功")
            a.ui_pause(0.08, 0.3)
            btn = self.page.locator("input[value='删除']").first
            self.log("点「删除」…")
            self._tr("click 删除")
            a.click(self.page, btn, force_fast=urgent)
            a.ui_pause(0.5, 1.2)
            self._loaded = None
            msg = self.read_result_message()
            self._tr(f"退课结果：{msg}")
            return msg
        finally:
            a.set_tempo(old)

    def _has_cid(self, field: str, cid: str) -> bool:
        try:
            return self.page.locator(f"input[name='{field}'][value='{cid}']").count() > 0
        except Exception:
            return False

    def _wait_selector(self, selector: str, timeout: float = 7.0) -> bool:
        """等某个选择器出现（同样是给 JS 渲染留时间）。"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                pass
            try:
                self.page.wait_for_timeout(200)
            except Exception:
                time.sleep(0.2)
        return False

    def _wait_cid(self, field: str, cid: str, timeout: float = 7.0) -> bool:
        """等那一行真的渲染出来。

        ⚠ 这一步是必须的：课程列表是 JS 渲染的，导航返回 ≠ 表格已经画好。
        实测（真退真选测试）：刚导航完立刻找 checkbox 会找不到，程序于是报
        「页面上找不到课程」而放弃；2 秒后再找就有了。抢课的时候这就是
        **白白错过一次机会**。
        """
        end = time.time() + timeout
        while time.time() < end:
            if self._has_cid(field, cid):
                return True
            try:
                self.page.wait_for_timeout(200)
            except Exception:
                time.sleep(0.2)
        return False

    def read_result_message(self) -> str:
        """抓页面上的业务提示（showMsg(...) 或正文里的提示句）。"""
        try:
            html = self.page.content()
        except Exception:
            return ""
        msgs = re.findall(r"showMsg\(\s*[\"']([^\"']*)[\"']\s*\)", html)
        if not msgs:
            try:
                body = self.page.inner_text("body")
                for line in (body or "").splitlines():
                    line = line.strip()
                    if line and any(k in line for k in
                                    ("成功", "失败", "不能", "不存在", "错误", "请选择")):
                        msgs.append(line)
                        if len(msgs) >= 3:
                            break
            except Exception:
                pass
        return "；".join(dict.fromkeys(m.strip() for m in msgs if m.strip()))

    # ------------------------------------------------------------------
    def title(self) -> str:
        try:
            return self.page.title() or ""
        except Exception:
            return ""
