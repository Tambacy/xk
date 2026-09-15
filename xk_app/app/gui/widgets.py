# -*- coding: utf-8 -*-
"""可复用的界面组件。

风格规则见 theme.py。这一版重点补三样东西，缺了它们界面就只是「方块叠方块」：

  · **深度** —— `apply_shadow()` 分层柔投影 + 悬停时真实抬起（带补间动画）
  · **形体变化** —— 圆（LogoMark / 状态点）、弧（深色带的同心弧纹）、
    色条（课程卡左侧状态条）、超大幽灵数字（模式卡）
  · **手绘细节** —— 深色带、品牌面板、步骤导轨、统计块的图形都用 QPainter 画，
    而不是拿一堆 QLabel 拼出来
"""
from __future__ import annotations

from PySide6.QtCore import (Qt, Signal, QEvent, QPointF, QRectF, QSize,
                            QVariantAnimation, QEasingCurve)
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from .backdrop import paint_sky
from .motion import Aurora, CountUp
from .theme import C, HERO_H, RAIL_H, STEPS, shadow_spec


# ==========================================================================
# 基础工具
# ==========================================================================
def repolish(w: QWidget):
    """改了动态属性之后，必须重新走一遍样式表才会生效。"""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def clear_layout(lay, keep_tail: int = 0):
    """清空布局里的控件。

    必须 setParent(None) 再 deleteLater()：deleteLater 是异步的，
    只调它的话旧控件在事件循环跑起来之前仍然可见，快速重建时会看到重影。
    """
    while lay.count() > keep_tail:
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        else:
            sub = item.layout()
            if sub is not None:
                clear_layout(sub)
                sub.deleteLater()


def eyebrow(text: str, dark: bool = False) -> QLabel:
    """眉标：小字号、淡色、压在大标题之上（参考站的 "Nube 02"）。"""
    lb = QLabel(text)
    lb.setObjectName("EyebrowDark" if dark else "Eyebrow")
    return lb


def divider(dark: bool = False) -> QLabel:
    f = QLabel()
    f.setObjectName("RuleDark" if dark else "Rule")
    f.setFixedHeight(1)
    f.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return f


def ui_font(px: int, weight: int = QFont.Normal) -> QFont:
    f = QFont()
    f.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                   "Segoe UI"])
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    return f


def apply_shadow(w: QWidget, level: str = "card") -> QGraphicsDropShadowEffect:
    blur, dx, dy, r, g, b, a = shadow_spec(level)
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    eff.setColor(QColor(r, g, b, a))
    w.setGraphicsEffect(eff)
    return eff


class ShadowAnim:
    """把投影在两个档位之间补间 —— 悬停「抬起」的手感就来自这里。

    直接换 QGraphicsDropShadowEffect 的参数会「啪」地跳一下；
    这里对 模糊半径 / 偏移 / 透明度 三个量同时做缓动。
    """

    def __init__(self, w: QWidget, level: str = "card"):
        self.eff = apply_shadow(w, level)
        self._a = shadow_spec(level)
        self._b = shadow_spec(level)
        self._t = 1.0
        self.anim = QVariantAnimation(w)
        self.anim.setDuration(230)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._apply_t)

    def to(self, level: str):
        self._a = self._current()
        self._b = shadow_spec(level)
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _current(self):
        o = self.eff.offset()
        col = self.eff.color()
        return (self.eff.blurRadius(), o.x(), o.y(),
                col.red(), col.green(), col.blue(), col.alpha())

    def _apply_t(self, t: float):
        a, b = self._a, self._b
        v = [a[i] + (b[i] - a[i]) * t for i in range(7)]
        self.eff.setBlurRadius(v[0])
        self.eff.setOffset(int(round(v[1])), int(round(v[2])))
        self.eff.setColor(QColor(int(v[3]), int(v[4]), int(v[5]), int(v[6])))


# ==========================================================================
# 天幕：顶部 Hero 带 / 登录页品牌面板共用
# ==========================================================================
class SkySurface(QWidget):
    """画天幕的基类，并持有一个慢速相位驱动。

    相位每帧推进一点点 → 极光漂移、星点明灭。窗口失焦时停掉，
    不做无意义的后台重绘。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aurora = Aurora(self)
        self._phase = 0.0
        self._variant = "violet"

    def phase(self) -> float:
        return self._aurora.phase

    def set_variant(self, name: str):
        """换一种天幕「心情」（见 backdrop.VARIANTS）。"""
        if name != self._variant:
            self._variant = name
            self.update()

    def variant(self) -> str:
        return self._variant

    def showEvent(self, e):
        self._aurora.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._aurora.stop()
        super().hideEvent(e)

    def changeEvent(self, e):
        # 失焦 / 最小化时停，回到前台再开 —— 不做无意义的后台重绘
        t = e.type()
        if t == QEvent.WindowStateChange:
            if self.window().isMinimized():
                self._aurora.stop()
            elif self.isVisible():
                self._aurora.start()
        elif t == QEvent.ActivationChange:
            if self.window().isActiveWindow():
                if self.isVisible():
                    self._aurora.start()
            else:
                self._aurora.stop()
        super().changeEvent(e)


class HeroBand(SkySurface):
    """窗口顶部那条天幕：玻璃导航胶囊 + 步骤导轨都在它上面。

    参考站的首屏是「满幅深色影像 + 浮在上面的玻璃导航 + 白色大字」。
    玻璃只有浮在深色上才成立 —— 浮在浅色底上的玻璃等于看不见。
    这里用程序生成的夜空（backdrop.paint_sky）充当那块「影像」。
    """

    FADE = 46          # 底部化开进页面的像素高度。太短会在天幕下沿
                       # 压出一条发亮的横带（深紫到浅底之间的落差不小）；
                       # 但也不能太长 —— 整条带子占的竖向空间是要还回去的。

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroBand")
        self.setFixedHeight(HERO_H + self.FADE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 10, 28, 0)
        v.setSpacing(8)

        # 居中、贴合内容的玻璃胶囊（参考站的 nav 就是这样一条，不是通栏横条）
        self.nav = QFrame()
        self.nav.setObjectName("NavPill")
        self.nav_row = QHBoxLayout(self.nav)
        self.nav_row.setContentsMargins(7, 7, 7, 7)
        self.nav_row.setSpacing(8)
        v.addWidget(self.nav, 0, Qt.AlignHCenter)

        self.rail = StepRail()
        v.addWidget(self.rail)
        v.addStretch(1)

    def paintEvent(self, e):
        p = QPainter(self)
        paint_sky(p, self.width(), self.height(), self.phase(),
                  fade_to=C["bg"], fade_h=self.FADE, variant=self._variant)


class BrandPanel(SkySurface):
    """登录页左侧的品牌面板 —— 和顶部天幕同一套画法，只是更高。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrandPanel")
        self.setMinimumWidth(380)
        self.setMaximumWidth(560)
        self._variant = "rose"

    def paintEvent(self, e):
        p = QPainter(self)
        paint_sky(p, self.width(), self.height(), self.phase(),
                  variant=self._variant)


class LogoMark(QWidget):
    """圆形品牌标：浅色圆 + 深绿字。深色底上够跳，浅色底上也站得住。"""

    def __init__(self, size: int = 32, text: str = "清", dark: bool = True,
                 parent=None):
        super().__init__(parent)
        self._size = size
        self._text = text
        self._dark = dark          # True = 画在深色背景上
        self.setFixedSize(size, size)

    def sizeHint(self):
        return QSize(self._size, self._size)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0.5, 0.5, self._size - 1.0, self._size - 1.0)

        if self._dark:
            g = QLinearGradient(0, 0, 0, self._size)
            g.setColorAt(0.0, QColor(255, 255, 255, 245))
            g.setColorAt(1.0, QColor(226, 238, 229, 235))
            p.setBrush(g)
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.drawEllipse(r)
            p.setPen(QColor(C["primary"]))
        else:
            g = QLinearGradient(0, 0, 0, self._size)
            g.setColorAt(0.0, QColor(C["primary_2"]))
            g.setColorAt(1.0, QColor(C["primary"]))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
            p.setPen(QColor("#FFFFFF"))

        p.setFont(ui_font(int(self._size * 0.44), QFont.Bold))
        p.drawText(r, Qt.AlignCenter, self._text)


class StepRail(QWidget):
    """步骤导轨：编号圆点 + 连接线 + 文字，一次画完。

    旧版是一排 QLabel 富文本胶囊，Qt 的富文本引擎不支持 border-radius，
    渲染出来是直角方块；而用真控件又会得到一排互不相连的色块。
    这里整条导轨自绘，编号圆点和连接线才连得起来。
    """

    NODE = 24
    GAP = 9           # 圆点 → 文字
    LINK = 28         # 文字 → 下一个圆点
    LINK_MIN = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = 0
        self.setFixedHeight(RAIL_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_current(self, index: int):
        self.current = index
        self.update()

    def _layout(self, fm: 'QFontMetrics'):
        widths = [self.NODE + self.GAP + fm.horizontalAdvance(s) for s in STEPS]
        total = sum(widths) + self.LINK * (len(STEPS) - 1)
        link = self.LINK
        avail = self.width()
        if total > avail:
            spare = total - avail
            link = max(self.LINK_MIN, self.LINK - spare // max(1, len(STEPS) - 1))
            total = sum(widths) + link * (len(STEPS) - 1)
        return widths, link, total

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        f_lab = ui_font(12.5, QFont.DemiBold)
        p.setFont(f_lab)
        fm = p.fontMetrics()
        widths, link, total = self._layout(fm)

        x = max(0.0, (self.width() - total) / 2.0)
        h = self.height()
        cy = h / 2.0

        for i in range(len(STEPS)):
            st = "active" if i == self.current else (
                "done" if i < self.current else "todo")

            # 连接线（画在当前圆点右侧，进度未到就是暗的）
            if i < len(STEPS) - 1:
                x0 = x + widths[i] + link / 2.0
                x1 = x + widths[i] + link
                done = i < self.current
                pen = QPen(QColor(255, 255, 255, 88 if done else 30))
                pen.setWidthF(1.4)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(x0, cy), QPointF(x1, cy))

            # 圆点
            nx = x + self.NODE / 2.0
            r = self.NODE / 2.0

            if st == "active":
                # 外圈柔光
                glow = QRadialGradient(QPointF(nx, cy), r * 2.5)
                glow.setColorAt(0.0, QColor(255, 255, 255, 60))
                glow.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QPointF(nx, cy), r * 2.5, r * 2.5)
                p.setBrush(QColor(255, 255, 255, 248))
                p.setPen(Qt.NoPen)
            elif st == "done":
                p.setBrush(QColor(255, 255, 255, 42))
                p.setPen(QPen(QColor(255, 255, 255, 78), 1.2))
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 30), 1.2))
            p.drawEllipse(QPointF(nx, cy), r, r)

            # 圆点里的字 / 勾
            if st == "done":
                p.setPen(QColor(255, 255, 255, 220))
                p.setFont(ui_font(12.5, QFont.Bold))
                p.drawText(QRectF(nx - r, cy - r, r * 2, r * 2),
                           Qt.AlignCenter, "✓")
                p.setFont(f_lab)
            else:
                col = QColor(C["primary"]) if st == "active" else QColor(255, 255, 255, 105)
                p.setPen(col)
                p.setFont(ui_font(12.5, QFont.Bold))
                p.drawText(QRectF(nx - r, cy - r, r * 2, r * 2),
                           Qt.AlignCenter, str(i + 1))
                p.setFont(f_lab)

            # 文字
            tx = x + self.NODE + self.GAP
            if st == "active":
                col, weight = QColor(255, 255, 255, 250), QFont.Bold
            elif st == "done":
                col, weight = QColor(255, 255, 255, 200), QFont.DemiBold
            else:
                col, weight = QColor(255, 255, 255, 108), QFont.Normal
            p.setFont(ui_font(12.5, weight))
            p.setPen(col)
            p.drawText(QRectF(tx, 0, widths[i] - self.NODE - self.GAP, h),
                       Qt.AlignVCenter | Qt.AlignLeft, STEPS[i])
            p.setFont(f_lab)

            x += widths[i] + link


# ==========================================================================
# 卡片
# ==========================================================================
class Card(QFrame):
    """主容器卡片。

    参考站没有 box-shadow，是因为它用满幅影像造深度；纯色平面上照搬
    「零投影」，结果就是纸片贴在一起。这里用分层柔投影 + 极浅渐变 +
    发丝描边把深度补回来。
    """

    def __init__(self, title: str = "", subtitle: str = "", parent=None,
                 shadow: bool = True):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 22)
        self.body.setSpacing(14)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.body.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("Hint")
            s.setWordWrap(True)
            self.body.addWidget(s)
        if shadow:
            apply_shadow(self, "card")


class ModeCard(QFrame):
    """模式选择用的大卡片。

    结构照搬参考站的图卡：眉标 → 大标题 → 说明 → 要点；
    右上角放一个超大幽灵数字，作为整屏里唯一的「大字号装饰」。
    """

    clicked = Signal(int)

    def __init__(self, index: int, title: str, badge: str, desc: str,
                 bullets: list[str], parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("CardFlat")
        self.setProperty("hovered", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(232)
        self._sh = ShadowAnim(self, "card")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(10)

        lay.addWidget(eyebrow(badge))

        t = QLabel(title)
        t.setObjectName("CardTitle")
        t.setWordWrap(True)
        lay.addWidget(t)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setObjectName("Hint")
        lay.addWidget(d)

        lay.addSpacing(4)
        for x in bullets:
            row = QHBoxLayout()
            row.setSpacing(9)
            tick = QLabel("—")
            tick.setStyleSheet(f"color:{C['primary_soft']};font-weight:700;")
            tick.setFixedWidth(12)
            row.addWidget(tick, 0, Qt.AlignTop)
            lb = QLabel(x)
            lb.setWordWrap(True)
            lb.setObjectName("Faint")
            row.addWidget(lb, 1)
            lay.addLayout(row)
        lay.addStretch(1)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        # 幽灵数字
        p.setFont(ui_font(56, QFont.Bold))
        col = QColor(C["primary"])
        col.setAlpha(20 if self.property("hovered") == "true" else 13)
        p.setPen(col)
        p.drawText(QRectF(0, 2, self.width() - 22, 68),
                   Qt.AlignRight | Qt.AlignTop, f"0{self.index}")
        # 悬停时顶部浮现一条绿色强调条
        if self.property("hovered") == "true":
            pen = QPen(QColor(C["primary_soft"]), 2.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(24, 1), QPointF(self.width() - 24, 1))

    def enterEvent(self, e):
        self.setProperty("hovered", "true")
        repolish(self)
        self._sh.to("raised")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setProperty("hovered", "false")
        repolish(self)
        self._sh.to("card")
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(e)


class CourseCard(QFrame):
    """课程详情小卡片：左侧一条状态色条，状态一眼看出来。"""

    remove_requested = Signal(int)

    RAIL = {"ok": "primary", "warn": "warn_mid", "err": "danger_mid",
            "info": "text_ghost"}
    # 左边留出 22px 给色条
    PAD_L = 24

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("CardFlat")
        self._kind = "info"
        self._sh = ShadowAnim(self, "card")

        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(self.PAD_L, 16, 18, 16)
        self.lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = QLabel("—")
        self.title.setStyleSheet("font-size:15px;font-weight:700;")
        head.addWidget(self.title, 1)
        self.badge = QLabel("")
        self.badge.setVisible(False)
        head.addWidget(self.badge)
        self.btn_del = QPushButton("移除")
        self.btn_del.setObjectName("Ghost")
        self.btn_del.setCursor(Qt.PointingHandCursor)
        self.btn_del.clicked.connect(lambda: self.remove_requested.emit(self.index))
        head.addWidget(self.btn_del)
        self.lay.addLayout(head)

        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setObjectName("Faint")
        self.lay.addWidget(self.meta)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        self.lay.addWidget(self.status)

    # -- 绘制左色条 ----------------------------------------------------
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(C[self.RAIL.get(self._kind, "text_ghost")])
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(10, 13, 4.0, max(10, self.height() - 26)), 2.0, 2.0)

    def _set_kind(self, kind: str):
        if kind != self._kind:
            self._kind = kind
            self.update()

    def enterEvent(self, e):
        self._sh.to("raised")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._sh.to("card")
        super().leaveEvent(e)

    # -- 内容 ----------------------------------------------------------
    def set_course(self, entry, selected_rows=None):
        name = entry.resolved_name or entry.name or entry.kch or "（未命名）"
        self.title.setText(name)

        from ..browser import COURSE_KINDS
        kind_name = COURSE_KINDS.get(entry.kind, {}).get("name", entry.kind)
        act = "要退掉" if entry.action == "drop" else "要抢"
        bits = [f"{act} · {kind_name}"]
        if entry.kch:
            bits.append(f"课程号 {entry.kch}")
        if entry.kxh:
            bits.append(f"课序号 {entry.kxh}")
        if entry.teacher:
            bits.append(f"教师 {entry.teacher}")
        if entry.resolved_time or entry.time_text:
            bits.append(f"上课时间 {entry.resolved_time or entry.time_text}")
        self.meta.setText("　·　".join(bits))

        if selected_rows:
            r = selected_rows[0]

            def g(key, default=None):
                if isinstance(r, dict):
                    return r.get(key, default)
                return getattr(r, key, default)

            parts = []
            kyl = g("kyl")
            if kyl is not None and kyl >= 0:
                color = C["primary"] if kyl > 0 else C["text_faint"]
                parts.append(f'<span style="color:{color}"><b>课余量 {kyl}</b></span>')
            q = g("queue")
            if q:
                parts.append(f"队列 {q}")
            note = g("note")
            if note:
                parts.append(str(note))
            ts = g("time_text")
            if ts and not entry.resolved_time:
                parts.append(f"上课时间 {ts}")
            self.status.setText("　·　".join(parts))
            self.status.setVisible(bool(parts))
        else:
            self.status.setVisible(False)

    def set_state(self, text: str, kind: str = "info"):
        color = {"ok": C["primary"], "warn": C["warn"],
                 "err": C["danger"], "info": C["text_dim"]}.get(kind, C["text_dim"])
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};font-size:13px;")
        self.status.setVisible(True)
        self._set_kind(kind)

    def set_badge(self, text: str, kind: str = "ok"):
        colors = {"ok": (C["primary"], C["accent_light"]),
                  "warn": (C["warn"], C["warn_light"]),
                  "err": (C["danger"], C["danger_light"]),
                  "info": (C["text_dim"], C["bg_soft"])}
        fg, bg = colors.get(kind, colors["info"])
        self.badge.setText(text)
        self.badge.setStyleSheet(
            f"background:{bg};color:{fg};padding:4px 12px;"
            f"border-radius:11px;font-size:12px;font-weight:700;")
        self.badge.setVisible(bool(text))
        self._set_kind(kind)


class GlowButton(QPushButton):
    """主行动按钮：绿色辉光。

    整屏只有一两个这种按钮，辉光让「该点哪个」一眼可见 ——
    也让纯色平面上唯一的深色块有了发光感，而不是一块贴上去的绿纸。
    禁用时辉光自动收掉，否则灰按钮配绿光会很怪。
    """

    def __init__(self, text: str, parent=None, strength: int = 92):
        super().__init__(text, parent)
        self.setObjectName("Primary")
        self._strength = strength
        eff = QGraphicsDropShadowEffect(self)
        eff.setOffset(0, 7)
        eff.setBlurRadius(24)
        eff.setColor(QColor(15, 66, 35, strength))
        self.setGraphicsEffect(eff)
        self._eff = eff

    def changeEvent(self, e):
        if e.type() == QEvent.EnabledChange:
            self._eff.setColor(
                QColor(15, 66, 35, self._strength if self.isEnabled() else 0))
        super().changeEvent(e)


class StatTile(QFrame):
    """统计块：小标签（带状态点）在上，大数字在下。

    标签压在数字之上，是参考站那套「小字眉标 → 大字号」层级的最小用法。
    旧版是「大数字 + 下面一行小字」，四个并排就是四条一模一样的白矩形。
    """

    def __init__(self, label: str, value: str = "—", accent: str = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("CardFlat")
        self._accent = accent or C["primary_soft"]
        self._sh = ShadowAnim(self, "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 17, 20, 17)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(9)
        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        self._dot.setStyleSheet(
            f"background:{self._accent};border-radius:3px;")
        head.addWidget(self._dot, 0, Qt.AlignVCenter)
        self.l = QLabel(label)
        self.l.setObjectName("StatLabel")
        head.addWidget(self.l, 1)
        lay.addLayout(head)

        self.v = QLabel(value)
        self.v.setObjectName("StatValue")
        lay.addWidget(self.v)
        self._count = CountUp(self.v, self)

    def set_accent(self, color: str):
        self._accent = color
        self._dot.setStyleSheet(f"background:{color};border-radius:3px;")

    def set(self, value: str, animate: bool = True):
        """数字滚动到新值；'—'、'00:01:23' 这类非数字直接落值。"""
        if animate:
            self._count.to(str(value))
        else:
            self.v.setText(str(value))

    def enterEvent(self, e):
        self._sh.to("raised")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._sh.to("card")
        super().leaveEvent(e)


# 旧名字，pages.py 里还在用
StatBox = StatTile


class Dot(QWidget):
    """状态点：外圈柔光。`set_pulse()` 推进光晕大小 —— 监听中会「呼吸」。"""

    def __init__(self, color: str = None, size: int = 10, halo: bool = True,
                 parent=None):
        super().__init__(parent)
        self._color = QColor(color or C["text_faint"])
        self._size = size
        self._halo = halo
        self._pulse = 0.0
        self._breathing = False
        pad = int(size * 1.5) if halo else 2
        self.setFixedSize(size + pad * 2, size + pad * 2)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(2100)
        self._anim.setLoopCount(-1)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._on_pulse)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def set_breathing(self, on: bool):
        """监听中 / 正在抢课时让光晕呼吸；其余状态静止，不分散注意力。"""
        if on == self._breathing:
            return
        self._breathing = on
        if on:
            self._anim.start()
        else:
            self._anim.stop()
            self._pulse = 0.0
            self.update()

    def _on_pulse(self, v):
        self._pulse = float(v)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._halo:
            r = self._size * (1.7 + 0.75 * self._pulse)
            g = QRadialGradient(QPointF(cx, cy), r)
            h = QColor(self._color)
            h.setAlpha(int(58 + 70 * self._pulse))
            g.setColorAt(0.0, h)
            h2 = QColor(self._color)
            h2.setAlpha(0)
            g.setColorAt(1.0, h2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(self._color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), self._size / 2.0, self._size / 2.0)
