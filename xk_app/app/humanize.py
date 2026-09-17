# -*- coding: utf-8 -*-
"""
拟人化引擎
==========

所有"像人"的随机性都集中在这里，方便统一调参。

三类节奏：
  * RELAXED —— 长期轮询。间隔长、停顿多，像人偶尔来看一眼。
  * NORMAL  —— 常规页面操作。有停顿，但不会慢得离谱。
  * URGENT  —— 抢课瞬间。压到最短，但**仍然不是 0**：
                完全零延迟的连续动作本身就是脚本特征。

设计原则（都是踩过坑总结出来的）：
  1. 间隔不能用"固定值 + 均匀抖动"就算完，还要有长尾（偶尔走神更久），
     并且取值区间必须连续 —— 否则长期统计能看出空档。
  2. 相邻两次取值不能雷同。
  3. 按"周期"结算睡眠（扣掉已耗时），否则真实节奏会被请求耗时拖长。
  4. 鼠标不能瞬移，要走轨迹；输入不能粘贴，要逐字敲。
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def _as_range(v, default: tuple[float, float]) -> tuple[float, float]:
    try:
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return float(v[0]), float(v[1])
        f = float(v)
        return f, f
    except Exception:
        return default


def pause(a: float, b: float) -> float:
    """随机停一会儿，返回实际睡了多久。"""
    d = random.uniform(a, b)
    if d > 0:
        time.sleep(d)
    return d


def gauss_pause(mu: float, sigma: float, lo: float, hi: float) -> float:
    """正态分布停顿，比均匀分布更接近真人（大多数快、偶尔特别慢）。"""
    d = min(hi, max(lo, random.gauss(mu, sigma)))
    time.sleep(d)
    return d


# --------------------------------------------------------------------------
# 节奏档位
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Tempo:
    """一套节奏参数。所有停顿都会乘上 ui_scale。"""
    name: str
    ui_scale: float          # 界面操作停顿的缩放
    key_delay: tuple         # 打字每个字符的延迟范围（毫秒）
    mouse_steps: tuple       # 鼠标轨迹步数范围
    think_prob: float        # "思考一下"的概率
    think_range: tuple       # 思考时长范围

    def think(self) -> float:
        """偶尔像人一样停顿一下再操作。"""
        if random.random() < self.think_prob:
            return pause(*self.think_range)
        return 0.0


RELAXED = Tempo("relaxed", 1.0, (60, 190), (12, 34), 0.35, (0.5, 2.2))
NORMAL = Tempo("normal", 0.55, (35, 110), (8, 22), 0.15, (0.25, 1.0))
URGENT = Tempo("urgent", 0.12, (12, 38), (3, 9), 0.0, (0.0, 0.0))


# --------------------------------------------------------------------------
# 轮询周期
# --------------------------------------------------------------------------

class PollRhythm:
    """生成轮询周期。

    真实周期 = 平均间隔 × U(j1, j2) × (偶尔 × U(long_a, long_b))

    用"乘"而不是"加"来制造长停顿，是为了让取值区间保持连续：
    加法会在 (j2, j2+long_a) 之间留下一个永远取不到的空档，
    长期跑下来统计直方图是双峰的，一眼就能看出是程序。
    """

    def __init__(self, avg: float = 1.0, jitter=(0.62, 1.35),
                 long_prob: float = 0.07, long_factor=(1.5, 2.6),
                 min_gap: float = 0.05, floor: float = 0.12):
        self.avg = float(avg)
        self.j1, self.j2 = _as_range(jitter, (0.62, 1.35))
        self.long_prob = float(long_prob)
        self.la, self.lb = _as_range(long_factor, (1.5, 2.6))
        self.min_gap = float(min_gap)
        self.floor = float(floor)
        self._last = 0.0

    def next(self) -> float:
        """抽一个周期。**对数正态**，不是均匀分布。

        均匀分布 U(j1, j2) 有一个致命缺点：它**永远取不到 avg*j2 以上**。
        样本一多，间隔的分布就是一条在 avg*j2 处齐刷刷截断的方波 ——
        真人的操作间隔是重尾的（接近对数正态），没有这么干净的上限，
        偶尔就是会拖得特别长。这个边界在直方图上一眼可见。

        改用对数正态后：中位数 = avg（所以平均速度一点没变），
        但右侧有一条自然的长尾，永远不会有硬截断。

        sigma 由 jitter 区间反推，让 ~5% / ~95% 分位正好落在 (j1, j2) 上 ——
        这样 jitter 这个配置项的含义完全不变，调试时看到的数字还能对上。
        """
        sigma = max(0.05, math.log(self.j2 / self.j1) / 3.2897)
        d = self.avg * random.lognormvariate(0.0, sigma)
        # 极端长尾（>avg*5）偶尔会抽出来，掐掉以免把一次轮询拖太久
        d = min(d, self.avg * 5.0)
        for _ in range(6):
            if abs(d - self._last) >= self.min_gap:
                break
            d = self.avg * random.lognormvariate(0.0, sigma)
            d = min(d, self.avg * 5.0)
        if random.random() < self.long_prob:
            d *= random.uniform(self.la, self.lb)
        self._last = d
        return max(self.floor, d)

    def describe(self) -> str:
        sigma = max(0.05, math.log(self.j2 / self.j1) / 3.2897)
        return (f"中位 {self.avg:g} 秒（对数正态 sigma={sigma:.2f}，"
                f"5%~95% 分位 ×{self.j1:g}~×{self.j2:g}，"
                f"{self.long_prob * 100:.0f}% 概率再 ×{self.la:g}~{self.lb:g}）")


# --------------------------------------------------------------------------
# 夜间静默
# --------------------------------------------------------------------------

def _minutes_of_day(s) -> int:
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


def night_silence_active(window, now: datetime | None = None) -> bool:
    """window 形如 ["01:00", "06:00"]；支持跨午夜；空/None 表示不启用。"""
    if not window or not isinstance(window, (list, tuple)) or len(window) != 2:
        return False
    try:
        start, end = _minutes_of_day(window[0]), _minutes_of_day(window[1])
    except Exception:
        return False
    if start == end:
        return False
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


# --------------------------------------------------------------------------
# 浏览器动作（依赖 playwright 的 Locator / Page）
# --------------------------------------------------------------------------

class HumanActor:
    """把"人怎么操作浏览器"封装成一组动作。

    刻意不用 page.evaluate 去直接改 DOM / 触发 click()：
    那样产生的事件 isTrusted=false，是最典型的脚本特征。
    这里全部走 Playwright 的真实输入通道（会生成可信事件）。
    """

    def __init__(self, tempo: Tempo = NORMAL, log=None):
        self.tempo = tempo
        self.log = log
        self._mx = 400.0          # 鼠标当前位置（在 Python 侧跟踪，
        self._my = 300.0          # 避免每次移动都往页面里打 evaluate）
        self._vw = 0              # 视口尺寸，懒读一次，给空闲噪声用
        self._vh = 0

    def set_tempo(self, tempo: Tempo):
        self.tempo = tempo

    # ---- 停顿 ----
    def ui_pause(self, a: float = 0.12, b: float = 0.45) -> float:
        s = self.tempo.ui_scale
        return pause(a * s, b * s)

    def think(self) -> float:
        return self.tempo.think()

    # ---- 鼠标 ----
    def move_mouse(self, page, x: float, y: float):
        """让鼠标走出轨迹，而不是瞬间跳到目标。

        轨迹按真人的三条特征来拼：

          1. **最小抖动轨迹**（minimum-jerk，`10t³-15t⁴+6t⁵`）—— 这是
             生物力学里描述人手伸取动作的标准模型，比 smoothstep 更接近
             真人：起步和收尾都平滑，中段最快。
          2. **逐帧抖动** —— 真手有微颤，轨迹完全光滑是"算出来的"特征。
          3. **过冲再修正** —— 长途移动有一定概率冲过目标一点再拉回来，
             这是真人鼠标最典型的行为，纯插值不会有。

        步数也随距离变化（真人远距离移动的采样点更多），不再是固定区间。
        """
        x0, y0 = self._mx, self._my
        dx, dy = x - x0, y - y0
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            self._mx, self._my = float(x), float(y)
            return

        steps = random.randint(*self.tempo.mouse_steps)
        steps = max(4, min(48, steps + int(dist / 90.0)))
        skew = random.uniform(0.85, 1.20)      # 速度曲线左右不对称
        # 过冲：短距离几乎不会，长距离比较常见
        overshoot = 0.0
        if dist > 120 and random.random() < 0.35:
            overshoot = random.uniform(0.02, 0.09)
        ox = x0 + dx * (1.0 + overshoot)
        oy = y0 + dy * (1.0 + overshoot)
        jitter = max(0.35, min(2.4, dist / 260.0))
        step_sleep = random.uniform(0.005, 0.019) * max(self.tempo.ui_scale, 0.2)
        split = 0.85 if overshoot else 1.0
        try:
            for i in range(1, steps + 1):
                t = i / steps
                if t <= split:
                    u = (t / split) ** skew
                    e = 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5
                    mx, my = x0 + (ox - x0) * e, y0 + (oy - y0) * e
                else:
                    # 修正段：从过冲点拉回真实目标
                    u = (t - split) / max(1e-6, 1.0 - split)
                    e = 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5
                    mx, my = ox + (x - ox) * e, oy + (y - oy) * e
                # 最后一步精确落到目标，保证点得中
                if i == steps:
                    mx, my = float(x), float(y)
                else:
                    mx += random.gauss(0.0, jitter)
                    my += random.gauss(0.0, jitter)
                page.mouse.move(mx, my)
                if step_sleep > 0:
                    time.sleep(step_sleep * random.uniform(0.7, 1.45))
        except Exception:
            pass
        self._mx, self._my = float(x), float(y)

    def click(self, page, locator, *, scroll: bool = True, force_fast: bool = False):
        """像人一样点一个元素。

        优先走真实鼠标轨迹；如果元素不可见（比如折叠菜单里），
        退回 Playwright 的 locator.click —— 它仍然是真实事件，
        只是会先帮你滚动/展开。
        """
        if force_fast:
            locator.click(timeout=15000)
            return
        try:
            if scroll:
                locator.scroll_into_view_if_needed(timeout=4000)
            box = locator.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                # 不点正中心，随机落在元素内的偏一点的位置
                px = box["x"] + box["width"] * random.uniform(0.32, 0.68)
                py = box["y"] + box["height"] * random.uniform(0.35, 0.65)
                self.move_mouse(page, px, py)
                self.ui_pause(0.05, 0.22)
                # 按下和抬起之间必须有停留：真人一次点击按住 60~150ms。
                # Playwright 的 mouse.click 是 down+up 连续发出（≈0ms），
                # 页面只要量一下 mousedown→mouseup 的时间差就能认出来。
                hold = random.uniform(0.06, 0.15) * max(self.tempo.ui_scale, 0.35)
                page.mouse.down()
                time.sleep(hold)
                page.mouse.up()
                return
        except Exception:
            pass
        locator.click(timeout=15000)

    def idle_noise(self, page) -> None:
        """轮询间隙"动一下鼠标 / 滚一下页面"。

        程序轮询只做「开页面 + 读表格」，全程**没有任何鼠标事件**，
        而真人打开的页面会持续产生 mousemove / wheel。一个长时间开着
        却零输入的页面，本身就不像有人在用。

        纯噪声，不影响任何取值；失败也一律吞掉。
        """
        try:
            if self._vw <= 0:
                try:
                    size = page.evaluate("() => [innerWidth, innerHeight]")
                    self._vw, self._vh = int(size[0]), int(size[1])
                except Exception:
                    self._vw, self._vh = 1366, 900
            if random.random() < 0.6:
                self.move_mouse(page,
                                random.uniform(self._vw * 0.12, self._vw * 0.85),
                                random.uniform(self._vh * 0.15, self._vh * 0.80))
            if random.random() < 0.35:
                self.scroll_page(page, random.randint(-260, 260))
            # 悬停到某一行、按几下 Tab：真人在列表页上是这样动的
            if random.random() < 0.30:
                self.hover_row(page)
            if random.random() < 0.15:
                self.tab_navigate(page, random.randint(1, 2))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 拟人浏览动作（"闲逛"时用）
    # ------------------------------------------------------------------

    def hover_row(self, page) -> bool:
        """把鼠标移到表格里某一行的随机位置。

        程序读表格是从不碰鼠标的；真人看课程列表时鼠标会落在某一行上。
        走 move_mouse 的最小抖动轨迹，不用 locator.hover()（那个是瞬移）。
        """
        try:
            rows = page.locator("table tr")
            n = rows.count()
            if n <= 1:
                return False
            i = random.randint(1, min(n - 1, 40))
            box = rows.nth(i).bounding_box()
            if not box or box["width"] < 20 or box["height"] < 6:
                return False
            self.move_mouse(page,
                            box["x"] + box["width"] * random.uniform(0.15, 0.75),
                            box["y"] + box["height"] * random.uniform(0.3, 0.7))
            return True
        except Exception:
            return False

    def tab_navigate(self, page, presses: int | None = None) -> None:
        """按几下 Tab 键。

        真人在表单间切换靠 Tab；一个页面在很长一段时间里**只有鼠标事件、
        没有一个 Tab**，也是个小特征。只按 Tab（不回车不空格），不会触发
        任何提交 —— Tab 只移动焦点，本身没有副作用。
        """
        try:
            n = presses if presses is not None else random.randint(1, 4)
            for _ in range(n):
                page.keyboard.press("Tab")
                self.ui_pause(0.09, 0.32)
        except Exception:
            pass

    def browse_around(self, page, *, seconds: float | None = None) -> None:
        """在一张页面上停留一小段时间，模拟"人在看"。

        组合：鼠标移动 + 滚动 + 悬停到某一行 + 按几下 Tab。
        全部是纯噪声，不改任何值；任何一步失败都吞掉。
        """
        end = time.time() + (seconds if seconds is not None
                             else random.uniform(2.0, 5.0))
        try:
            self.move_mouse(page,
                            random.uniform(0.15, 0.8) * max(self._vw, 800),
                            random.uniform(0.2, 0.7) * max(self._vh, 600))
            while time.time() < end:
                r = random.random()
                if r < 0.34:
                    self.scroll_page(page, random.randint(-380, 420))
                elif r < 0.60:
                    self.hover_row(page)
                elif r < 0.75:
                    self.tab_navigate(page)
                else:
                    self.move_mouse(page,
                                    random.uniform(0.1, 0.9) * max(self._vw, 800),
                                    random.uniform(0.15, 0.85) * max(self._vh, 600))
                self.ui_pause(0.25, 0.85)
            # 收尾：往上滚回一点，别把页面留在奇怪的位置
            if random.random() < 0.5:
                self.scroll_page(page, -random.randint(80, 260))
        except Exception:
            pass

    def paste_text(self, page, locator, text: str) -> bool:
        """用**真实剪贴板粘贴**的方式输入文本。

        为什么需要它：`locator.type()` 遇到中文这类非 ASCII 字符时，是直接
        调 Input.insertText 往渲染进程塞文本，页面上只看得到
        beforeinput / input 两个事件、inputType 是 "insertText"，
        **一个 keydown / keyup 都没有**。真人打中文必然经过 IME，不可能
        长出这种事件序列。

        而「复制课程名 → 粘到搜索框」是真人常见操作，事件完整：
            keydown(Control) keydown(v) paste input(insertFromPaste)
            keyup(v) keyup(Control)

        做法：先把文本写进 **Windows 系统剪贴板**（浏览器外面，不碰页面
        JS），再让浏览器自己处理 Ctrl+V。粘贴完把用户原来的剪贴板内容
        放回去 —— 不能因为抢课就把人家的剪贴板弄没了。

        返回 True 表示走的是粘贴路径。
        """
        from .runtime import get_clipboard_text, set_clipboard_text

        locator.scroll_into_view_if_needed()
        saved = get_clipboard_text()
        try:
            if not set_clipboard_text(text):
                return False
            self.click(page, locator)
            self._clear(page, locator)
            self.ui_pause(0.15, 0.35)
            page.keyboard.press("Control+V")
            # 等值真的落进去；没落进去就说明这条路不通，交给调用方回退
            end = time.time() + 4
            while time.time() < end:
                try:
                    if (locator.input_value() or "").strip() == text.strip():
                        self.ui_pause(0.1, 0.3)
                        return True
                except Exception:
                    pass
                time.sleep(0.1)
            return False
        finally:
            # 还原用户原本的剪贴板
            if saved is not None:
                try:
                    set_clipboard_text(saved)
                except Exception:
                    pass

    def _clear(self, page, locator):
        """清空输入框 —— 走键盘，不用 fill("")。

        fill("") 不产生任何按键事件，页面上直接看到值变空却没有对应输入，
        一眼就是脚本。全选 + Delete 才是真人会做的事。
        """
        try:
            locator.press("Control+a")
            locator.press("Delete")
        except Exception:
            try:
                locator.fill("")
            except Exception:
                pass

    def type_text(self, page, locator, text: str, *, clear: bool = True, force_fast: bool = False):
        """逐字输入。clear=True 时先清空。"""

        # 含非 ASCII（中文、全角标点等）时改用剪贴板粘贴：type() 对这些
        # 字符只会产生 insertText，没有按键事件，是明显的脚本痕迹。
        if any(ord(ch) > 127 for ch in text):
            if self.paste_text(page, locator, text):
                return
            # 粘贴失败（比如剪贴板被别的程序占着）才退回逐字输入
        self.click(page, locator, force_fast=force_fast)
        self.ui_pause(0.08, 0.3)
        lo, hi = self.tempo.key_delay
        if force_fast:
            lo = hi = 8
        if clear:
            try:
                # 真人清空输入框是「全选 + 删除」，不是直接给 value 赋值。
                # locator.fill("") 只改属性、不产生任何按键事件 —— 页面上
                # 看不到 keydown/keyup 却看到内容变了，是个可查的差别。
                locator.press("Control+a")
                self.ui_pause(0.04, 0.13)
                locator.press("Delete")
            except Exception:
                try:
                    locator.fill("")          # 兜底：至少保证能清掉
                except Exception:
                    pass
        for ch in text:
            locator.type(ch, delay=random.uniform(lo, hi))
            # 偶尔卡一下，像人在找键位
            if not force_fast and random.random() < 0.06:
                pause(0.12, 0.45)
        self.ui_pause(0.08, 0.28)

    def check(self, page, locator, *, force_fast: bool = False, verify: bool = True) -> bool:
        """勾选复选框，并且**点完确认真的勾上了**。

        不同分辨率 / 缩放 / 字体大小下，元素位置会变，偶尔可能被遮挡或点偏。
        所以这里点完会回读一次状态，没勾上就退回 Playwright 原生点击再试一次。
        """
        try:
            if locator.is_checked():
                return True
        except Exception:
            pass

        self.click(page, locator, force_fast=force_fast)
        if not verify:
            return True
        if self._wait_checked(locator):
            return True

        if self.log:
            self.log("坐标点击没勾上，改用原生点击重试", "WARN")
        try:
            locator.click(timeout=8000)
        except Exception:
            return False
        return self._wait_checked(locator, 2.0)

    @staticmethod
    def _wait_checked(locator, timeout: float = 1.2) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if locator.is_checked():
                    return True
            except Exception:
                pass
            time.sleep(0.08)
        return False

    def scroll_page(self, page, amount: int | None = None):
        """随机滚一滚，像人在看页面。"""
        amount = amount or random.randint(-320, 320)
        try:
            page.mouse.wheel(0, amount)
        except Exception:
            pass
        self.ui_pause(0.12, 0.5)


# --------------------------------------------------------------------------
# 节奏的"读取"侧：把人味也用在等待上
# --------------------------------------------------------------------------

def wait_for_condition(fn, timeout: float, interval: float = 0.25, human: HumanActor | None = None):
    """轮询等待一个条件成立；等待本身也带抖动，避免精确等间隔探测。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        d = interval * random.uniform(0.65, 1.5)
        if human is not None:
            d *= max(human.tempo.ui_scale, 0.25)
        time.sleep(max(0.05, d))
    return False
