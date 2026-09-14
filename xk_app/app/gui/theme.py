# -*- coding: utf-8 -*-
"""界面主题：配色、字体、样式表。

用学校紫做主色，浅色背景，圆角卡片，整体偏现代简洁。
所有尺寸都用布局管理器控制，不写死像素位置 —— 这样换分辨率、换 DPI 缩放都不会错位。
"""
from __future__ import annotations

# ---- 配色 ----
C = {
    "primary":      "#7B2D8E",   # 学校紫
    "primary_dark": "#5E1F6E",
    "primary_light": "#F3E9F7",
    "primary_mid":  "#C9A6D6",
    "accent":       "#2E9E6B",   # 成功绿
    "warn":         "#D9822B",
    "danger":       "#C0392B",
    "bg":           "#F5F6F8",
    "card":         "#FFFFFF",
    "border":       "#E3E5E9",
    "text":         "#23262B",
    "text_dim":     "#6B7280",
    "text_faint":   "#9AA1AC",
    "log_bg":       "#1E2128",
    "log_text":     "#D6DAE1",
}

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'


def stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 14px;
    color: {C['text']};
}}
QWidget#Root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {C['bg']};
}}
QScrollArea {{ border: none; }}

/* ---------- 卡片 ---------- */
QFrame#Card {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
QFrame#CardFlat {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}
QLabel#CardTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#PageTitle {{ font-size: 24px; font-weight: 600; }}
QLabel#PageSub   {{ font-size: 13px; color: {C['text_dim']}; }}
QLabel#Hint      {{ color: {C['text_dim']}; font-size: 13px; }}
QLabel#Faint     {{ color: {C['text_faint']}; font-size: 12px; }}
QLabel#Error     {{ color: {C['danger']}; font-size: 13px; }}
QLabel#Success   {{ color: {C['accent']}; font-size: 13px; }}
QLabel#Warn      {{ color: {C['warn']}; font-size: 13px; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 8px 18px;
    min-height: 20px;
}}
QPushButton:hover  {{ background: #FAFAFC; border-color: {C['primary_mid']}; }}
QPushButton:pressed{{ background: #F0F0F4; }}
QPushButton:disabled {{ color: {C['text_faint']}; background: #F2F3F5; }}

QPushButton#Primary {{
    background: {C['primary']};
    color: white;
    border: none;
    font-weight: 600;
    padding: 10px 26px;
}}
QPushButton#Primary:hover   {{ background: {C['primary_dark']}; }}
QPushButton#Primary:pressed {{ background: {C['primary_dark']}; }}
QPushButton#Primary:disabled{{ background: #C9C9CF; color: #FFFFFF; }}

QPushButton#Ghost {{
    background: transparent; border: none; color: {C['primary']};
    padding: 6px 10px;
}}
QPushButton#Ghost:hover {{ background: {C['primary_light']}; border-radius: 6px; }}

QPushButton#Danger {{ color: {C['danger']}; }}
QPushButton#Danger:hover {{ background: #FDECEA; border-color: {C['danger']}; }}

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 7px 11px;
    min-height: 22px;          /* 防止被竖直方向压扁成一条线 */
    selection-background-color: {C['primary_mid']};
}}
QComboBox {{ min-height: 24px; }}
QDateTimeEdit {{ min-height: 24px; }}
QSpinBox, QDoubleSpinBox {{ min-height: 24px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {C['primary']};
}}
QLineEdit:disabled, QComboBox:disabled {{ background: #F4F5F7; color: {C['text_faint']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {C['card']}; border: 1px solid {C['border']};
    selection-background-color: {C['primary_light']};
    selection-color: {C['text']}; outline: none;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {C['border']}; border-radius: 5px; background: white;
}}
QCheckBox::indicator:checked {{
    background: {C['primary']}; border-color: {C['primary']};
    image: none;
}}
QCheckBox::indicator:hover {{ border-color: {C['primary_mid']}; }}

/* ---------- 进度/日志 ---------- */
QPlainTextEdit#Log {{
    background: {C['log_bg']};
    color: {C['log_text']};
    border: none; border-radius: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 10px;
}}

QProgressBar {{
    border: none; border-radius: 4px; background: #E9EAEE;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {C['primary']}; border-radius: 4px; }}

/* ---------- 列表 ---------- */
QListWidget {{
    background: transparent; border: none; outline: none;
}}
QListWidget::item {{ border-radius: 10px; margin: 3px 0; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #CFD3DA; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #B8BEC8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CFD3DA; border-radius: 5px; min-width: 30px; }}

QToolTip {{
    background: #2B2F36; color: white; border: none;
    padding: 6px 10px; border-radius: 6px;
}}
"""


# ---- 步骤条 ----
STEPS = ["登录", "选择模式", "预定课程", "确认启动", "运行监控"]


def step_chip(index: int, current: int) -> str:
    """返回单个步骤的显示文本与配色（供步骤条控件使用）。"""
    done = index < current
    active = index == current
    if active:
        color, bg = "#FFFFFF", C["primary"]
    elif done:
        color, bg = C["primary"], C["primary_light"]
    else:
        color, bg = C["text_faint"], "#EEF0F3"
    label = ("✓ " if done else "") + STEPS[index]
    return (f'<span style="background:{bg};color:{color};'
            f'padding:4px 12px;border-radius:11px;">{label}</span>')
