# -*- coding: utf-8 -*-
"""动效。

全部用 PySide6 自带的动画框架实现，**不引入任何第三方依赖** ——
安装包已经有 334 MB 了，为几个淡入再多带一个库不划算；
而且 Qt 自带的这几个类（QPropertyAnimation / QVariantAnimation /
QGraphicsEffect 子类）足够做出需要的效果。

  · `TurnCurtain` —— 页面切换的**翻页**效果：旧页向左滑出并轻微收缩，
    新页从右侧滑入，旧页前缘在新页上投一道影子。两层画在同一个控件里。
  · `ParticleOverlay` —— 覆盖窗口的粒子层。按钮悬停 / 点击时在它周围
    炸开一小簇，颜色取自当前主题。
  · `Aurora` —— 驱动天幕相位的计时器。相位推进 → 极光漂移、星点明灭。
    窗口失焦时自动停，不白烧 CPU。
  · `CountUp` —— 统计数字从旧值滚到新值。

`ENABLED` 是总开关：截图回归测试会把它关掉，
否则抓到的可能是动画中间帧（第一版就踩了这个：三张模式卡整片不见了）。
"""
from __future__ import annotations

import random

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QRect, QRectF, QTimer,
                            QVariantAnimation, Qt)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .theme import C, D_PAGE

ENABLED = True


# ==========================================================================
# 页面切换：翻页
# ==========================================================================
class TurnCurtain(QWidget):
    """翻页幕布：把「旧页滑出 + 新页滑入」画在**同一个控件**上。

    为什么不给页面挂 QGraphicsEffect：卡片自己已经挂了投影用的 effect，
    父子两层嵌套时子控件那层会被漏掉（实测切过去之后标题和按钮都在、
    三张模式卡整片消失）。

    为什么两层画在一块：真实页面就在幕布下面。两块独立幕布在交接处会
    露出底下的真实内容；合成到同一张画布上就没有缝。

    质感来自三处：旧页前缘落在新页上的一道投影、两层错开的速度差
    （于是中段能看见旧页「压」在新页上）、以及缓动曲线。

    **两层都必须完全不透明。** 第一版给两层都加了透明度渐变，结果两张页面
    叠在一起互相透视 —— 那是交叉淡出，不是翻页。翻页靠的是**位移**：
    旧页整片滑走，新页整片滑进来，重叠期间旧页盖在新页上面。
    """

    SHIFT = 0.80      # 新页从侧面多远的地方滑入（占宽度比例）
    PUSH = 1.00       # 旧页滑出的距离：必须 ≥1，否则收尾时还压着新页

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._old = None
        self._new = None
        self._p = 1.0
        self._rev = False
        self._bg = QColor(C["bg"])
        self.hide()

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(D_PAGE)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._on)
        self.anim.finished.connect(self.hide)

    def play(self, old: QPixmap, new: QPixmap, geo: QRect, reverse: bool = False):
        self._old, self._new, self._rev = old, new, reverse
        self.setGeometry(geo)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _on(self, v):
        self._p = float(v)
        self.update()

    def paintEvent(self, e):
        if self._old is None or self._new is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        t = self._p
        sgn = -1.0 if self._rev else 1.0

        p.fillRect(0, 0, w, h, self._bg)

        # 新页：从侧面滑入（不透明）
        dx_new = sgn * (1.0 - t) * w * self.SHIFT
        p.save()
        p.translate(dx_new, 0)
        p.drawPixmap(0, 0, self._new)
        p.restore()

        # 旧页：向反方向滑出（不透明，盖在新页上面）
        dx_old = -sgn * t * w * self.PUSH

        # 旧页前缘投在新页上的影子：先画影子，旧页再盖上去
        if sgn < 0:
            edge = dx_old                      # 反向时前缘是左边缘
            gx0 = edge - 76
            g = QLinearGradient(gx0, 0, edge, 0)
            g.setColorAt(0.0, QColor(12, 8, 30, 0))
            g.setColorAt(1.0, QColor(12, 8, 30, 130))
        else:
            edge = dx_old + w                  # 正向时前缘是右边缘
            gx0 = edge
            g = QLinearGradient(gx0, 0, gx0 + 76, 0)
            g.setColorAt(0.0, QColor(12, 8, 30, 130))
            g.setColorAt(1.0, QColor(12, 8, 30, 0))
        p.fillRect(QRectF(gx0, 0, 76, h), g)

        p.save()
        p.translate(dx_old, 0)
        p.drawPixmap(0, 0, self._old)
        p.restore()


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
