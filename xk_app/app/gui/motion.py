# -*- coding: utf-8 -*-
"""动效。

全部用 PySide6 自带的动画框架实现，**不引入任何第三方依赖** ——
安装包已经有 334 MB 了，为几个淡入再多带一个库不划算；
而且 Qt 自带的这几个类（QPropertyAnimation / QVariantAnimation /
QGraphicsEffect 子类）足够做出需要的效果。

  · `PageCurtain` —— 页面切换的交叉淡出。见下面那段注释：为什么不能用
    「给页面挂一个 QGraphicsEffect」这个显然的做法。
  · `Aurora` —— 驱动天幕相位的计时器。相位推进 → 极光漂移、星点明灭。
    窗口失焦时自动停，不白烧 CPU。
  · `CountUp` —— 统计数字从旧值滚到新值。

`ENABLED` 是总开关：截图回归测试会把它关掉，
否则抓到的可能是动画中间帧（第一版就踩了这个：三张模式卡整片不见了）。
"""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QObject, QRect, QTimer,
                            QVariantAnimation, Qt)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QLabel, QWidget)

from .theme import D_PAGE

ENABLED = True


# ==========================================================================
# 页面切换
# ==========================================================================
class PageCurtain(QLabel):
    """切换页面时盖在内容区上的一层「旧页面快照」，淡出 + 上移。

    为什么不用「给页面挂一个 RiseFadeEffect」这种显然的做法：

      QGraphicsEffect 只要落在**父控件**上，父控件就会连同整棵子树渲染进
      一张离屏位图。而卡片自己已经挂了投影用的 QGraphicsEffect ——
      两层 effect 嵌套时，子控件那层会被漏掉：实测模式页切过去之后，
      标题和按钮都在，**三张模式卡整片消失**。

      换成一层没有子控件的快照（QLabel + 位图 + 不透明度）就没有嵌套，
      而且只有一层合成，比给整页套 effect 便宜。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("PageCurtain")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setScaledContents(False)
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(1.0)
        self.setGraphicsEffect(self._eff)
        self._base_y = 0
        self.hide()

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(D_PAGE)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._on)
        self.anim.finished.connect(self.hide)

    def play(self, pixmap: QPixmap, geo: QRect):
        self._base_y = geo.y()
        self.setGeometry(geo)
        self.setPixmap(pixmap)
        self._eff.setOpacity(1.0)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _on(self, v):
        v = float(v)
        self._eff.setOpacity(1.0 - v)
        self.move(self.x(), self._base_y - int(16 * v))


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
