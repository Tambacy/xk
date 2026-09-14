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
        d = self.avg * random.uniform(self.j1, self.j2)
        for _ in range(6):
            if abs(d - self._last) >= self.min_gap:
                break
            d = self.avg * random.uniform(self.j1, self.j2)
        if random.random() < self.long_prob:
            d *= random.uniform(self.la, self.lb)
        self._last = d
        return max(self.floor, d)

    def describe(self) -> str:
        return (f"平均 {self.avg:g} 秒（浮动 ×{self.j1:g}~×{self.j2:g}，"
                f"{self.long_prob * 100:.0f}% 概率 ×{self.la:g}~×{self.lb:g}）")


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
        """让鼠标走出轨迹，而不是瞬间跳到目标。"""
        x0, y0 = self._mx, self._my
        steps = random.randint(*self.tempo.mouse_steps)
        # 加一点弧度，直线移动也很假
        bend = random.uniform(-0.18, 0.18)
        step_sleep = random.uniform(0.004, 0.018) * max(self.tempo.ui_scale, 0.2)
        try:
            for i in range(1, steps + 1):
                t = i / steps
                ease = t * t * (3 - 2 * t)                  # smoothstep
                mx = x0 + (x - x0) * ease
                my = y0 + (y - y0) * ease + math.sin(math.pi * t) * bend * abs(x - x0)
                page.mouse.move(mx, my)
                if step_sleep > 0:
                    time.sleep(step_sleep)
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
                page.mouse.click(px, py)
                return
        except Exception:
            pass
        locator.click(timeout=15000)

    def type_text(self, page, locator, text: str, *, clear: bool = True, force_fast: bool = False):
        """逐字输入。clear=True 时先清空。"""
        self.click(page, locator, force_fast=force_fast)
        self.ui_pause(0.08, 0.3)
        lo, hi = self.tempo.key_delay
        if force_fast:
            lo = hi = 8
        if clear:
            try:
                locator.fill("")
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
