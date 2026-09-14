# -*- coding: utf-8 -*-
"""可复用的界面组件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget,
                               QPushButton, QSizePolicy, QGraphicsDropShadowEffect)

from .theme import C, STEPS, step_chip


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


class Card(QFrame):
    """带圆角和浅阴影的卡片容器。"""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.body.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("Hint")
            s.setWordWrap(True)
            self.body.addWidget(s)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(18)
        sh.setOffset(0, 2)
        sh.setColor(QColor(20, 24, 40, 22))
        self.setGraphicsEffect(sh)


class StepBar(QWidget):
    """顶部的步骤指示条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = 0
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self.labels = []
        for i in range(len(STEPS)):
            lb = QLabel()
            lb.setTextFormat(Qt.RichText)
            self._lay.addWidget(lb)
            self.labels.append(lb)
            if i < len(STEPS) - 1:
                arrow = QLabel("›")
                arrow.setStyleSheet(f"color:{C['text_faint']};font-size:16px;")
                self._lay.addWidget(arrow)
        self._lay.addStretch(1)
        self.set_current(0)

    def set_current(self, index: int):
        self.current = index
        for i, lb in enumerate(self.labels):
            lb.setText(step_chip(i, index))


class ModeCard(QFrame):
    """模式选择用的大卡片。"""

    clicked = Signal(int)

    def __init__(self, index: int, title: str, badge: str, desc: str,
                 bullets: list[str], parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("CardFlat")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel(f"<b>{title}</b>")
        t.setStyleSheet("font-size:16px;")
        head.addWidget(t)
        head.addStretch(1)
        b = QLabel(badge)
        b.setStyleSheet(f"background:{C['primary_light']};color:{C['primary']};"
                        f"padding:3px 10px;border-radius:10px;font-size:12px;")
        head.addWidget(b)
        lay.addLayout(head)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{C['text_dim']};")
        lay.addWidget(d)

        for x in bullets:
            lb = QLabel("• " + x)
            lb.setWordWrap(True)
            lb.setStyleSheet(f"color:{C['text_faint']};font-size:12.5px;")
            lay.addWidget(lb)
        lay.addStretch(1)

    def enterEvent(self, e):
        self.setStyleSheet(f"QFrame#CardFlat{{border:2px solid {C['primary']};"
                           f"border-radius:10px;background:{C['card']};}}")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet("")
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(e)


class CourseCard(QFrame):
    """课程详情小卡片。"""

    remove_requested = Signal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("CardFlat")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(6)

        head = QHBoxLayout()
        self.title = QLabel("—")
        self.title.setStyleSheet("font-size:15px;font-weight:600;")
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
        self.meta.setStyleSheet(f"color:{C['text_dim']};")
        self.lay.addWidget(self.meta)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        self.lay.addWidget(self.status)

    def set_course(self, entry, selected_rows=None):
        """把课程条目渲染成卡片。"""
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
                color = C["accent"] if kyl > 0 else C["text_dim"]
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
        color = {"ok": C["accent"], "warn": C["warn"],
                 "err": C["danger"], "info": C["text_dim"]}.get(kind, C["text_dim"])
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};")
        self.status.setVisible(True)

    def set_badge(self, text: str, kind: str = "ok"):
        colors = {"ok": (C["accent"], "#E8F6EF"),
                  "warn": (C["warn"], "#FDF3E7"),
                  "err": (C["danger"], "#FDECEA"),
                  "info": (C["text_dim"], "#EEF0F3")}
        fg, bg = colors.get(kind, colors["info"])
        self.badge.setText(text)
        self.badge.setStyleSheet(f"background:{bg};color:{fg};padding:3px 10px;"
                                 f"border-radius:10px;font-size:12px;")
        self.badge.setVisible(bool(text))


class Dot(QWidget):
    """小圆点状态指示器。"""

    def __init__(self, color: str = None, size: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color or C["text_faint"])
        self._size = size
        self.setFixedSize(size + 2, size + 2)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, self._size, self._size)


class StatBox(QFrame):
    """监控页上的小统计块。"""

    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("CardFlat")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.v = QLabel(value)
        self.v.setStyleSheet("font-size:19px;font-weight:600;")
        lay.addWidget(self.v)
        self.l = QLabel(label)
        self.l.setStyleSheet(f"color:{C['text_faint']};font-size:12px;")
        lay.addWidget(self.l)

    def set(self, value: str):
        self.v.setText(str(value))
