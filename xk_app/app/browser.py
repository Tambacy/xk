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

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from .humanize import HumanActor, NORMAL, RELAXED, URGENT, wait_for_condition

BASE = "http://zhjwxk.cic.tsinghua.edu.cn/"
XKLOGIN = BASE + "xklogin.do"
XK_HOST = "zhjwxk.cic.tsinghua.edu.cn"
SSO_HOST = "id.tsinghua.edu.cn"

# 课程类别 → 页面/字段/提交动作
COURSE_KINDS = {
    "bx": {"name": "必修课", "search": "bxSearch",     "field": "p_bxk_id",  "submit": "saveBxKc"},
    "xx": {"name": "限选课", "search": "xxSearch",     "field": "p_xx_id",   "submit": "saveXxKc"},
    "rx": {"name": "任选课", "search": "rxSearch",     "field": "p_rx_id",   "submit": "saveRxKc"},
    "ty": {"name": "体育课", "search": "tySearch",     "field": "p_rxTy_id", "submit": "saveTyKc"},
    "cx": {"name": "重修课", "search": "cxSearchTab",  "field": "p_cx_id",   "submit": "saveCxKc"},
}
KIND_BY_NAME = {v["name"]: k for k, v in COURSE_KINDS.items()}


class SessionExpired(Exception):
    """会话失效，需要重新登录。"""


class PageError(Exception):
    """页面操作失败（可向用户展示的原因）。"""


class NeedSecondFactor(PageError):
    """登录要求二次认证（短信/微信验证码）。

    这种情况程序自己过不去，必须让真人在浏览器窗口里操作，或者让用户知道
    该切到「可见窗口」模式。绝不能像以前那样傻等超时。
    """


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
    """长期存活的浏览器会话：登录 + 所有教务系统操作。"""

    def __init__(self, profile_dir: str | Path, *,
                 xnxq: str = "2026-2027-1",
                 headless: bool = False,
                 viewport: tuple[int, int] = (1366, 900),
                 log: Callable[[str, str], None] | None = None,
                 actor: HumanActor | None = None):
        self.profile_dir = Path(profile_dir)
        self.xnxq = xnxq
        self.headless = headless
        self.viewport = viewport
        self._log = log or (lambda msg, level="INFO": None)
        self.actor = actor or HumanActor(NORMAL, self._log)
        self._pw = None
        self._ctx = None
        self.page = None
        self._loaded: tuple | None = None
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
        self.log(f"启动浏览器（{'后台无窗口' if self.headless else '可见窗口'}）…")
        self._tr(f"launch profile={self.profile_dir} headless={self.headless} "
                 f"viewport={self.viewport[0]}x{self.viewport[1]}")
        self._pw = sync_playwright().start()
        launch_kw = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate,AcceptCHFrame",
                # 固定缩放为 1，避免不同机器 DPI 缩放影响坐标换算
                "--force-device-scale-factor=1",
            ],
            viewport={"width": int(self.viewport[0]), "height": int(self.viewport[1])},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 装了随包浏览器时，显式指向完整 Chromium：
        # 1) 安装包只需带一份浏览器（不用再带 headless shell）
        # 2) 保证别人电脑上用的就是我们测过的那一版，行为完全一致
        try:
            from .runtime import find_bundled_chromium, chrome_user_agent
            exe = find_bundled_chromium()
            if exe:
                launch_kw["executable_path"] = exe
                self._tr(f"使用随包 Chromium：{exe}")
            # 无头浏览器的 UA 会带 "HeadlessChrome"，这是最直白的破绽，
            # 换成与浏览器实际版本一致的正版 Chrome UA。
            if self.headless:
                ua = chrome_user_agent()
                if ua:
                    launch_kw["user_agent"] = ua
                    self._tr(f"无头模式：UA 已替换为 {ua[-40:]}")
        except Exception:
            pass
        self._ctx = self._pw.chromium.launch_persistent_context(**launch_kw)
        # navigator.webdriver 是最扎眼的自动化标记，抹掉
        self._ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});"
        )
        # 无头模式还有一堆别的破绽（插件为 0、没有 window.chrome、
        # WebGL 报软件渲染……），额外补一层。有头模式本来就没有这些问题，
        # 不需要也不应该去"伪装"成别的样子。
        if self.headless:
            try:
                from .stealth import build_init_script
                self._ctx.add_init_script(build_init_script())
                self._tr("无头模式：已注入反检测脚本")
            except Exception as e:
                self.log(f"注入反检测脚本失败（不影响使用）：{e}", "WARN")
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.page.set_default_timeout(20000)
        self.page.on("dialog", self._on_dialog)
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
              timeout: float = 150) -> bool:
        """用真实浏览器完成统一身份认证。

        on_progress 会在每个阶段被调用，界面据此显示进度 ——
        登录要几十秒，没有反馈的话用户根本不知道成没成。
        """
        def step(msg: str):
            self.log(msg)
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass

        a = self.actor
        a.set_tempo(NORMAL)
        step("正在启动/连接浏览器…")
        self.page.goto(XKLOGIN, wait_until="domcontentloaded", timeout=60000)
        a.ui_pause(0.4, 1.0)
        self._loaded = None

        if SSO_HOST not in (self.page.url or ""):
            step("已有有效会话，无需登录。")
            return True

        step("已到达统一身份认证页，准备填写账号…")
        a.scroll_page(self.page)
        a.think()

        if self._captcha_visible():
            code = ask_captcha() if ask_captcha else None
            if not code:
                raise PageError("登录需要图形验证码")
            a.type_text(self.page, self.page.locator("#i_code"), code)

        step("正在输入账号…")
        a.type_text(self.page, self.page.locator("#i_user"), user)
        a.ui_pause(0.25, 0.7)
        step("正在输入密码…")
        a.type_text(self.page, self.page.locator("#i_pass"), password, clear=False)
        if single_login:
            try:
                a.check(self.page, self.page.locator('#theform input[name="singleLogin"]').first)
                step("已勾选「信任/单点登录」。")
            except Exception:
                pass
        a.think()
        step("正在提交登录…")
        a.click(self.page, self.page.locator("a[onclick*='doLogin']").first)
        step("已提交，等待服务器响应（这一步有时要几十秒）…")

        ok = self._wait_landing(timeout, on_progress=on_progress)
        if not ok:
            body = self._safe_body_text()
            if "验证码" in body:
                raise PageError("登录要求验证码")
            if "不正确" in body or "密码错误" in body:
                raise PageError("用户名或密码不正确")
            if "sso_fail" in (self.page.url or ""):
                raise PageError("统一身份认证票据校验失败（短时间内登录过于频繁，请稍后再试）")
            raise PageError(f"登录失败，页面停在：{(self.page.url or '')[:90]}")
        step(f"登录成功！落地页：{(self.page.url or '')[:70]}")
        return True

    def _wait_landing(self, timeout: float, on_progress=None) -> bool:
        """等真正落进教务系统内部页面。

        中途可能出现的几种情况都要认出来：
          * sso_fail         —— 票据校验失败
          * 二次认证页面      —— 必须真人操作，不能傻等
          * 中间跳转页        —— 继续等
        """
        t0 = time.time()
        end = t0 + timeout
        reported_2fa = False
        while time.time() < end:
            try:
                u = self.page.url or ""
            except Exception:
                u = ""
            if "sso_fail" in u:
                return False

            # 二次认证：这是必须让真人介入的情况
            if self._is_second_factor_page():
                if not reported_2fa:
                    reported_2fa = True
                    if self.headless:
                        # 无头模式下用户看不到、点不到，直接报错说清楚
                        raise NeedSecondFactor(
                            "本次登录要求二次认证（短信/微信验证码），"
                            "但当前是「后台无窗口」模式，你看不到验证页面。\n"
                            "请到「运行设置」把浏览器改成「可见窗口」，"
                            "重新登录后在弹出的窗口里完成验证即可。")
                    self.log("⚠ 本次登录要求二次认证。请在浏览器窗口里按提示"
                             "完成验证（短信 / 微信），程序会继续等待，最多 5 分钟。", "WARN")
                if on_progress:
                    on_progress("等待你在浏览器窗口中完成二次认证…")
                # 给足时间让用户操作
                if time.time() - t0 > 300:
                    raise NeedSecondFactor("二次认证等待超时（5 分钟）。")
                try:
                    self.page.wait_for_timeout(500)
                except Exception:
                    time.sleep(0.5)
                continue

            if XK_HOST in u and ("m=" in u or "zhjw.do" in u or "xsxk_index" in u):
                return True

            if on_progress and int(time.time() - t0) % 3 == 0:
                on_progress(f"等待跳转中…（已 {time.time()-t0:.0f} 秒）")
            try:
                self.page.wait_for_timeout(350)
            except Exception:
                time.sleep(0.35)
        return XK_HOST in (self.page.url or "") and "sso_fail" not in (self.page.url or "")

    def _is_second_factor_page(self) -> bool:
        """判断当前是不是统一身份认证的二次验证页面。"""
        try:
            u = (self.page.url or "").lower()
            if "doubleauth" in u or "checksecond" in u:
                return True
            # 只在认证域下判断，避免误伤其它页面
            if SSO_HOST not in (self.page.url or ""):
                return False
            html = self.page.content()[:6000]
            return ("二次认证" in html or "二次验证" in html
                    or "doubleAuth" in html or "需要二次" in html)
        except Exception:
            return False

    def _captcha_visible(self) -> bool:
        try:
            loc = self.page.locator("#i_code")
            return loc.count() > 0 and loc.is_visible()
        except Exception:
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

    def _navigate(self, m: str, *, force_check: bool = False, pause_range=(0.25, 0.7),
                  **params):
        """在浏览器里打开一个子系统页面（真实导航 + 真人的短暂停顿）。"""
        key = (m, tuple(sorted((k, str(v)) for k, v in params.items())))
        if not force_check and self._loaded == key:
            return self.page
        url = self._url(m, **params)
        self._tr(f"navigate {url}")
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
    # 读：学期列表
    # ------------------------------------------------------------------
    def read_semesters(self) -> tuple[str, list[tuple[str, str]]]:
        """读教务系统的学期下拉。

        左侧菜单栏（m=showTree）里有个 name="menu1" 的下拉，带当前学期和历史学期。
        有了它就不用把学期写死在配置里 —— 换学期、换机器都能自适应。

        返回 (当前学期值, [(值, 显示名), …])；读不到就返回 ("", [])。
        """
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
        if navigate:
            self._navigate(info["search"], tokenPriFlag=kind, p_kch=kch, p_kxh=kxh)
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

    def search_course_human(self, kind: str, keyword: str, *, by_kch: bool = False
                            ) -> list[CapacityRow]:
        """用页面自带的搜索框查询（真人打字 + 点「查询」）。

        中文不适合塞进 URL（页面是 GBK），所以这一步必须走页面表单：
        浏览器会用页面自身的编码提交 POST，服务端才认。
        任选课尤其明显 —— 不搜索的话永远是「没有记录」。
        """
        a = self.actor
        info = COURSE_KINDS[kind]
        self._navigate(info["search"], tokenPriFlag=kind, pause_range=(0.3, 0.9))
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
        a.click(self.page, btn)
        a.ui_pause(0.6, 1.4)
        self._loaded = None          # 查询是表单提交，页面状态已变
        self.current_list = {"kind": kind, "kch": keyword if by_kch else ""}
        rows = self._parse_grid() or self._parse_table()
        self.log(f"搜索结果 {len(rows)} 行")
        return rows

    # ------------------------------------------------------------------
    # 读：已选定课程
    # ------------------------------------------------------------------
    def read_selected(self, *, navigate: bool = True) -> list[SelectedCourse]:
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
        a = self.actor
        info = COURSE_KINDS[kind]
        try:
            self._navigate(info["search"], tokenPriFlag=kind, p_kch=kch,
                           force_check=not self._has_cid(info["field"], cid),
                           pause_range=(0.2, 0.6))
        except SessionExpired:
            raise
        if not self._has_cid(info["field"], cid):
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
        a = self.actor
        self._navigate("yxSearchTab", tokenPriFlag="yx", pause_range=(0.2, 0.6))
        radio = self.page.locator(f"input[name='p_del_id'][value='{del_id}']").first
        if radio.count() == 0:
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
