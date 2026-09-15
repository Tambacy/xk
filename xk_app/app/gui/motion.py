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

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QRect,
                            QRectF, QTimer, QVariantAnimation, Qt)
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPixmap,
                           QRadialGradient)
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

    DURATION = 480
    BAND = 0.19          # 羽化带占半径的比例。太大整屏会糊成一团雾
    MASK_DIV = 3         # 遮罩降采样倍数

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._old = None
        self._new = None
        self._p = 0.0
        self._ps = []
        self._bg = QColor(C["bg"])
        self.hide()

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(self.DURATION)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self._on)
        self.anim.finished.connect(self._done)

    def _done(self):
        self._ps = []
        self.hide()

    # -- 生命周期 ------------------------------------------------------
    def play(self, old: QPixmap, new: QPixmap, geo: QRect, reverse: bool = False):
        self._old, self._new = old, new
        self._ps = []
        self._p = 0.0
        self.setGeometry(geo)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _max_r(self) -> float:
        """盖住四个角所需的半径。"""
        return math.hypot(self.width(), self.height()) / 2.0 * 1.02

    def _radius(self, t: float) -> float:
        return self._max_r() * (0.04 + 0.96 * t)

    def _on(self, v):
        t = float(v)
        r = self._radius(t)
        cx, cy = self.width() / 2.0, self.height() / 2.0

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
        self.update()

    # -- 绘制 ----------------------------------------------------------
    def paintEvent(self, e):
        if self._old is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        p.drawPixmap(0, 0, self._old)

        t = self._p
        if t > 0.002 and self._new is not None:
            r = self._radius(t)
            mw = max(24, w // self.MASK_DIV)
            mh = max(24, h // self.MASK_DIV)

            # 低分辨率的径向遮罩
            mask = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
            mask.fill(0)
            mp = QPainter(mask)
            mp.setRenderHint(QPainter.Antialiasing, True)
            rg = QRadialGradient(mw / 2.0, mh / 2.0, max(1.0, r / self.MASK_DIV))
            rg.setColorAt(0.0, QColor(0, 0, 0, 255))
            solid = max(0.0, 1.0 - self.BAND)
            rg.setColorAt(solid, QColor(0, 0, 0, 255))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            mp.fillRect(0, 0, mw, mh, rg)
            mp.end()

            # 新页按遮罩抠出来（新页保持原分辨率）
            tmp = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            tmp.fill(0)
            tp = QPainter(tmp)
            tp.setRenderHint(QPainter.SmoothPixmapTransform, True)
            tp.drawPixmap(0, 0, self._new)
            tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            tp.drawImage(QRect(0, 0, w, h), mask)
            tp.end()
            p.drawImage(0, 0, tmp)

            # 边缘一圈柔光：窄一点、亮一点，是「化开的那条边」而不是一片雾
            edge = max(1.0, r)
            gg = QRadialGradient(w / 2.0, h / 2.0, edge)
            gg.setColorAt(max(0.0, 1.0 - self.BAND * 2.2), QColor(196, 178, 240, 0))
            gg.setColorAt(max(0.0, 1.0 - self.BAND * 0.75), QColor(222, 210, 255, 120))
            gg.setColorAt(1.0, QColor(167, 140, 230, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(gg)
            p.drawEllipse(QPointF(w / 2.0, h / 2.0), edge, edge)

        # 粒子
        if self._ps:
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
