# -*- coding: utf-8 -*-
"""动效。

全部用 PySide6 自带的动画框架实现，**不引入任何第三方依赖** ——
安装包已经有 334 MB 了，为几个淡入再多带一个库不划算；
而且 Qt 自带的这几个类（QPropertyAnimation / QVariantAnimation /
QGraphicsEffect 子类）足够做出需要的效果。

  · `RevealCurtain` —— 页面切换：新页通过一张径向渐变遮罩从中心化开，
    边缘跑一圈粒子，像新内容由粒子聚拢而成。
  · `ParticleOverlay` —— 覆盖窗口的粒子层。按钮悬停 / 点击时在它周围
    炸开一小簇，颜色取自当前主题。
  · `Aurora` —— 驱动天幕相位的计时器。相位推进 → 极光漂移、星点明灭。
    窗口失焦时自动停，不白烧 CPU。
  · `CountUp` —— 统计数字从旧值滚到新值。

`ENABLED` 是总开关：截图回归测试会把它关掉，
否则抓到的可能是动画中间帧（第一版就踩了这个：三张模式卡整片不见了）。
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QRect,
                            QRectF, QTimer, QVariantAnimation, Qt)
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPixmap,
                           QRadialGradient, QRegion)
from PySide6.QtWidgets import QWidget

from .theme import C, D_PAGE

ENABLED = True


# ==========================================================================
# 页面切换：翻页
# ==========================================================================
class RevealCurtain(QWidget):
    """粒子渐变揭示。

    旧页整片垫底，新页通过一张**径向渐变遮罩**从中心化开：遮罩边缘是软的
    （不是硬切一条线），边缘上再跑一圈粒子，读起来像新页面由粒子聚拢而成。

    为什么不用「翻页」那种位移：位移会把注意力引到「一张纸在滑」上，
    而这个程序切页时用户关心的是新页内容 —— 渐变揭示让新内容**浮现**出来，
    比滑入安静，也更像同一块界面在换内容。

    几个实现要点：
      · 遮罩按 1/3 分辨率画再放大 —— 径向渐变放大不会糊，但能省下十几倍开销
      · 新页始终保持原分辨率（只有遮罩是低分辨率的），否则过程中会先糊一下
      · 两层都画在同一个控件里：真实页面就在幕布下面，分开画会露出底下的内容
    """

    DURATION = 620
    BAND = 0.19          # 羽化带占半径的比例。太大整屏会糊成一团雾
    MASK_DIV = 3         # 遮罩降采样倍数

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._old = None
        self._new = None
        self._old_pos = QPoint(0, 0)
        self._new_pos = QPoint(0, 0)
        self._p = 0.0
        self._prev_r = 0.0
        self._ps = []
        self._bg = QColor(C["bg"])
        # 每帧要用的两块位图缓存起来复用。每帧新建一张 1120×760 的 QImage
        # 是 3.4MB，60fps 就是 200MB/s 的分配/回收 —— 掉帧就是这么来的。
        self._mask = None
        self._comp = None
        self._cache_size = (0, 0)
        self.hide()

        # 自己用 QTimer 驱动，不用 QVariantAnimation 内部那个定时器：
        # 后者的间隔不稳定，实测 480ms 只跑到 21 帧、单帧进度能跳 0.14
        # （约 68ms 的停顿），看起来就是「帧数不够、一顿一顿」。
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._tick)
        self._t0 = 0.0

    def _done(self):
        self._ps = []
        self.hide()

    # -- 生命周期 ------------------------------------------------------
    def play(self, old: QPixmap, new: QPixmap, geo: QRect,
             old_pos: QPoint = None, new_pos: QPoint = None,
             reverse: bool = False):
        self._old, self._new = old, new
        self._old_pos = QPoint(old_pos) if old_pos is not None else QPoint(0, 0)
        self._new_pos = QPoint(new_pos) if new_pos is not None else QPoint(0, 0)
        self._ps = []
        self._p = 0.0
        self._prev_r = 0.0
        self.setGeometry(geo)
        self.raise_()
        self.show()
        self._timer.stop()
        self._t0 = time.perf_counter()
        self.update()               # 首帧整屏重画一次，之后只重画环带
        self._timer.start()

    @staticmethod
    def _ease(t: float) -> float:
        """InOutCubic。"""
        if t < 0.5:
            return 4.0 * t * t * t
        return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0

    def _tick(self):
        el = (time.perf_counter() - self._t0) * 1000.0
        t = el / float(self.DURATION)
        done = t >= 1.0
        self._on(self._ease(min(1.0, max(0.0, t))))
        if done:
            self._timer.stop()
            self._done()

    def _buffers(self, w: int, h: int):
        """按需分配、跨帧复用。尺寸没变就不重新分配。"""
        mw = max(24, w // self.MASK_DIV)
        mh = max(24, h // self.MASK_DIV)
        if self._cache_size != (w, h) or self._mask is None:
            self._mask = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
            self._comp = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            self._cache_size = (w, h)
        return mw, mh

    def _max_r(self) -> float:
        """盖住四个角所需的半径。"""
        return math.hypot(self.width(), self.height()) / 2.0 * 1.02

    def _radius(self, t: float) -> float:
        return self._max_r() * (0.04 + 0.96 * t)

    def _on(self, v):
        t = float(v)
        r = self._radius(t)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._new_pos is not None:
            cx = self._new_pos.x() + self.width() / 2.0
            cy = self._new_pos.y() + self.height() / 2.0

        # 沿揭示边缘撒粒子
        if t < 0.98:
            for _ in range(5):
                a = random.random() * math.tau
                rr = r * (0.90 + random.random() * 0.14)
                sp = 0.85 + random.random() * 1.7
                self._ps.append({
                    "x": cx + math.cos(a) * rr,
                    "y": cy + math.sin(a) * rr,
                    "vx": math.cos(a) * sp,
                    "vy": math.sin(a) * sp,
                    "r": 1.4 + random.random() * 2.4,
                    "life": 1.0,
                    "decay": 0.018 + random.random() * 0.016,
                })

        alive = []
        for q in self._ps:
            q["x"] += q["vx"]
            q["y"] += q["vy"]
            q["vx"] *= 0.972
            q["vy"] *= 0.972
            q["life"] -= q["decay"]
            if q["life"] > 0:
                alive.append(q)
        self._ps = alive[-260:]

        self._p = t
        self.update(self._dirty_region(r, cx, cy))
        self._prev_r = r

    def _dirty_region(self, r: float, cx: float, cy: float) -> QRegion:
        """这一帧真正变了的地方：圆环带 + 粒子所占范围。

        整屏重画在这里是**几十毫秒**级别的开销 —— 1.5 倍缩放下后台缓冲是
        1680×1140（7.7MB），每帧都要重画并上屏。实测定时器设 15ms，
        实际 59ms 才走一帧，掉到 17fps，看起来就是一顿一顿。
        揭示动画每帧其实只有一圈窄环在变，把重画范围收到环带 + 粒子即可。
        """
        band = r * self.BAND
        pad = int(band * 2.2) + 26
        outer = QRegion(QRect(int(cx - r - pad), int(cy - r - pad),
                              int(2 * (r + pad)) + 1, int(2 * (r + pad)) + 1),
                        QRegion.Ellipse)
        inner_r = self._prev_r - pad
        if inner_r > 2:
            outer = outer.subtracted(
                QRegion(QRect(int(cx - inner_r), int(cy - inner_r),
                              int(2 * inner_r) + 1, int(2 * inner_r) + 1),
                        QRegion.Ellipse))
        if self._ps:
            xs = [q["x"] for q in self._ps]
            ys = [q["y"] for q in self._ps]
            outer = outer.united(
                QRect(int(min(xs)) - 10, int(min(ys)) - 10,
                      int(max(xs) - min(xs)) + 20, int(max(ys) - min(ys)) + 20))
        return outer

    # -- 绘制 ----------------------------------------------------------
    def paintEvent(self, e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 兜底先铺一层页面底色。控件是 WA_NoSystemBackground，
        # 没画到的地方会露出未初始化内容（在 Windows 上就是**大片黑色**）。
        # 两页高度可能不同（登录页不显示顶部天幕条，比其它页高整整一条带子），
        # 所以「没画到的地方」是常态，不是异常。
        p.fillRect(0, 0, w, h, self._bg)
        if self._old is None or self._old.isNull():
            return
        p.drawPixmap(self._old_pos, self._old)

        t = self._p
        if self._new is None or self._new.isNull():
            return

        if t > 0.97:
            # 已经铺满，直接整幅画上去，省掉一次离屏合成
            p.drawPixmap(self._new_pos, self._new)
            self._draw_particles(p)
            return
        if t <= 0.002:
            self._draw_particles(p)
            return

        cx = self._new_pos.x() + w / 2.0
        cy = self._new_pos.y() + h / 2.0
        r = self._radius(t)
        edge = max(1.0, r)

        # 只在这一块矩形里干活 —— 前 60% 的时间里圆还很小，
        # 全屏合成是纯浪费（实测占掉大半的绘制时间）。
        bx = max(0, int(cx - edge - 4))
        by = max(0, int(cy - edge - 4))
        bw = min(w, int(cx + edge + 4)) - bx
        bh = min(h, int(cy + edge + 4)) - by
        if bw <= 0 or bh <= 0:
            return
        clip = QRect(bx, by, bw, bh)

        mw, mh = self._buffers(w, h)
        k = float(self.MASK_DIV)

        # 低分辨率的径向遮罩（复用缓存）
        self._mask.fill(0)
        mp = QPainter(self._mask)
        mp.setRenderHint(QPainter.Antialiasing, True)
        rg = QRadialGradient(cx / k, cy / k, max(1.0, edge / k))
        rg.setColorAt(0.0, QColor(0, 0, 0, 255))
        solid = max(0.0, 1.0 - self.BAND)
        rg.setColorAt(solid, QColor(0, 0, 0, 255))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        mp.setClipRect(QRect(int(bx / k), int(by / k),
                             max(1, int(bw / k) + 1), max(1, int(bh / k) + 1)))
        mp.fillRect(0, 0, mw, mh, rg)
        mp.end()

        # 新页按遮罩抠出来（新页保持原分辨率，只有遮罩是低分辨率的）
        comp = self._comp
        comp.fill(0)
        tp = QPainter(comp)
        tp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        tp.setClipRect(clip)
        tp.drawPixmap(self._new_pos, self._new)
        tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tp.drawImage(QRect(0, 0, w, h), self._mask)
        tp.end()
        p.drawImage(clip, comp, clip)

        # 边缘一圈柔光：窄一点、亮一点，是「化开的那条边」而不是一片雾
        gg = QRadialGradient(cx, cy, edge)
        gg.setColorAt(max(0.0, 1.0 - self.BAND * 2.2), QColor(196, 178, 240, 0))
        gg.setColorAt(max(0.0, 1.0 - self.BAND * 0.75), QColor(222, 210, 255, 120))
        gg.setColorAt(1.0, QColor(167, 140, 230, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(gg)
        p.drawEllipse(QPointF(cx, cy), edge, edge)

        self._draw_particles(p)

    def _draw_particles(self, p: QPainter):
        if not self._ps:
            return
        p.setPen(Qt.NoPen)
        for q in self._ps:
            c = QColor(C["primary_2"])
            c.setAlpha(int(235 * max(0.0, q["life"]) ** 1.2))
            p.setBrush(c)
            rr = q["r"] * (0.35 + q["life"] * 0.95)
            p.drawEllipse(QRectF(q["x"] - rr, q["y"] - rr, rr * 2, rr * 2))


# ==========================================================================
# 按钮粒子
# ==========================================================================
class ParticleOverlay(QWidget):
    """覆盖整个窗口的透明粒子层：按钮悬停 / 点击时在它周围炸开一小簇。

    必须 WA_TransparentForMouseEvents，否则会把底下的按钮全挡住。
    没有存活粒子时把计时器停掉，不白烧 CPU。
    """

    FPS = 60

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._ps = []
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / self.FPS))
        self._timer.timeout.connect(self._tick)

    def emit_from(self, w: QWidget, n: int = 12):
        if not ENABLED or w is None or not w.isVisible():
            return
        try:
            tl = w.mapTo(self, QPoint(0, 0))
        except Exception:
            return
        r = QRect(tl, w.size())
        if r.width() <= 0 or r.height() <= 0:
            return

        base = QColor(C["primary_2"])
        for _ in range(n):
            # 沿按钮边缘取点、速度朝外 —— 像从边上溅出来
            side = random.randrange(4)
            if side == 0:
                x = r.left() + random.random() * r.width(); y = r.top()
                vx = (random.random() - .5) * 1.5; vy = -.5 - random.random() * 1.1
            elif side == 1:
                x = r.left() + random.random() * r.width(); y = r.bottom()
                vx = (random.random() - .5) * 1.5; vy = .5 + random.random() * 1.1
            elif side == 2:
                x = r.left(); y = r.top() + random.random() * r.height()
                vx = -.5 - random.random() * 1.1; vy = (random.random() - .5) * 1.5
            else:
                x = r.right(); y = r.top() + random.random() * r.height()
                vx = .5 + random.random() * 1.1; vy = (random.random() - .5) * 1.5
            c = QColor(base)
            c.setHsv((base.hue() + random.randint(-18, 18)) % 360,
                     base.saturation(),
                     min(255, base.value() + random.randint(-24, 26)))
            self._ps.append({"x": float(x), "y": float(y), "vx": vx, "vy": vy,
                             "r": 1.5 + random.random() * 2.3,
                             "life": 1.0, "decay": 0.015 + random.random() * 0.016,
                             "c": c})
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _tick(self):
        alive = []
        for q in self._ps:
            q["x"] += q["vx"]
            q["y"] += q["vy"]
            q["vy"] += 0.035                 # 一点重力
            q["vx"] *= 0.985
            q["life"] -= q["decay"]
            if q["life"] > 0 and -50 < q["x"] < self.width() + 50 \
               and -50 < q["y"] < self.height() + 50:
                alive.append(q)
        self._ps = alive
        if not self._ps:
            self._timer.stop()
        self.update()

    def paintEvent(self, e):
        if not self._ps:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        for q in self._ps:
            c = QColor(q["c"])
            c.setAlpha(int(238 * max(0.0, q["life"]) ** 1.2))
            p.setBrush(c)
            rr = q["r"] * (0.35 + q["life"] * 0.9)
            p.drawEllipse(QRectF(q["x"] - rr, q["y"] - rr, rr * 2, rr * 2))


# ==========================================================================
# 天幕相位
# ==========================================================================
class Aurora(QObject):
    """推进天幕相位。

    20fps、每帧相位移 0.012 —— 慢到几乎察觉不到在动，但盯着看是活的。
    窗口失焦就停：不做无意义的后台重绘。
    """

    FPS = 20
    RATE = 0.013

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.parent = parent
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / self.FPS))
        self.timer.timeout.connect(self._tick)

    def start(self):
        if not self.timer.isActive():
            self.timer.start()

    def stop(self):
        self.timer.stop()

    def _tick(self):
        self.phase += self.RATE
        if self.phase > 1e6:
            self.phase = 0.0
        self.parent.update()


# ==========================================================================
# 数字滚动
# ==========================================================================
class CountUp(QObject):
    """统计数字从旧值滚到新值。非数字（'—'、'00:01:23'）直接落值，不硬编。"""

    def __init__(self, label, parent=None):
        super().__init__(parent or label)
        self.label = label
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(520)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(
            lambda v: self.label.setText(self._fmt(v)))

    @staticmethod
    def _parse(text: str):
        t = (text or "").strip()
        if not t:
            return None
        try:
            if "." in t:
                return float(t.rstrip("s").strip())
            return float(t)
        except Exception:
            return None

    def _fmt(self, v):
        if self._is_int:
            return str(int(round(v)))
        return f"{v:.1f}"

    def to(self, text: str):
        target = self._parse(text)
        if target is None:
            self.anim.stop()
            self.label.setText(str(text))
            return
        cur = self._parse(self.label.text())
        self._is_int = (target == int(target)) and (cur is None or cur == int(cur))
        if cur is None or not self.label.isVisible():
            self.label.setText(str(text))
            return
        if abs(cur - target) < 1e-9:
            self.label.setText(str(text))
            return
        self.anim.stop()
        self.anim.setStartValue(float(cur))
        self.anim.setEndValue(float(target))
        self.anim.start()
