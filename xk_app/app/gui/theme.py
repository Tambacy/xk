# -*- coding: utf-8 -*-
"""界面主题：设计令牌 + 全局样式表。

视觉语言取自 espaciolanube.com，但只保留它的**关系**（深色底 → 玻璃 → 大字），
配色换成**淡紫**系统。

三层结构：

  1. **深色天幕**（`backdrop.paint_sky`）—— 深夜紫的天空，带缓慢漂移的极光色块、
     星点与同心弧纹。它是整屏唯一有「气氛」的地方，也是玻璃能成立的前提。
  2. **淡紫主色** —— 按钮、选中态、强调线。因为是淡紫，白字压在上面要够，
     所以主色取 #6F5CAD 而不是更浅的薰衣草色。
  3. **冷调中性** —— 背景不再是暖骨白，改成带一点紫的浅灰，跟着主色走。

动效不靠外部依赖：PySide6 自带 QPropertyAnimation / QVariantAnimation /
自定义 QGraphicsEffect 就够了（见 motion.py）。
"""
from __future__ import annotations

# ---- 配色 -----------------------------------------------------------------
C = {
    # 淡紫主色阶（从最深到最浅，够撑渐变、色块和状态）
    "primary_deep":   "#1B1236",
    "primary_ink":    "#2A1F52",
    "primary":        "#6F5CAD",   # 主色：白字压得住
    "primary_2":      "#8B79C9",   # 渐变亮端
    "primary_soft":   "#A99AD8",
    "primary_mid":    "#C6BCE6",
    "primary_light":  "#E5E0F6",   # 浅底
    "primary_tint":   "#F5F2FD",   # 极浅底
    "primary_dark":   "#57468C",

    # 天幕（backdrop.paint_sky 用）
    "sky_top":        "#3A2A6E",
    "sky_mid":        "#241A4A",
    "sky_bottom":     "#140D2B",
    "sky_aurora_a":   "#A78CE6",   # 极光·薰衣草
    "sky_aurora_b":   "#E296BE",   # 极光·暮粉
    "sky_aurora_c":   "#786EDC",   # 极光·蓝紫
    "sky_glow":       "#F3C9DE",   # 低空辉光

    # 语义色
    "accent":         "#3D8F6D",   # 成功：柔和的玉绿（小面积，不破坏紫色调）
    "accent_light":   "#E6F2EC",
    "warn":           "#96681C",
    "warn_mid":       "#C79433",
    "warn_light":     "#F8F0DF",
    "danger":         "#B03A4A",
    "danger_mid":     "#D2606F",
    "danger_light":   "#FAEAEC",
    "danger_bright":  "#FF8095",   # 深色面板上的告警红

    # 中性（冷调，跟着紫走）
    "bg":             "#F4F3F9",
    "bg_soft":        "#EAE7F2",
    "bg_deep":        "#E1DDEC",
    "card":           "#FFFFFF",
    "card_soft":      "#FCFBFE",
    "glass":          "rgba(255, 255, 255, 16%)",
    "border":         "#E4E1EE",
    "border_soft":    "#EFEDF6",
    "border_strong":  "#D2CDE0",
    "hairline":       "rgba(28, 20, 54, 7%)",
    "hairline_dark":  "rgba(255, 255, 255, 12%)",

    # 文字
    "text":           "#1B1926",
    "text_dim":       "#66626F",
    "text_faint":     "#96929E",
    "text_ghost":     "#B6B2C0",

    # 深色面板（日志）
    "log_bg":         "#171029",
    "log_text":       "#DAD6E6",
    "log_dim":        "#6E6A82",
    "ink":            "#171029",
    "ink_soft":       "#221A3C",
    "ink_text":       "#DAD6E6",
    "ink_dim":        "#847E99",
}

# ---- 字体 -----------------------------------------------------------------
FONT_FAMILY = ('"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
               '"Segoe UI", "Helvetica Neue", sans-serif')
MONO_FAMILY = '"Cascadia Mono", "Consolas", "SF Mono", "Menlo", monospace'

# ---- 圆角 -----------------------------------------------------------------
R_PILL = 22
R_CARD = 20
R_MD = 14
R_IN = 11
R_SM = 8

# ---- 高度 -----------------------------------------------------------------
# 顶部天幕带整条（HERO_H + HeroBand.FADE）压到 142px 左右。
# 之前是 112+64=176 —— 在 760 高的窗口里占了近四分之一，
# 「预定课程」这类要操作的页面会明显感觉内容被顶到下面去了。
HERO_H = 96         # 顶部天幕（不含底部化开区）
NAV_H = 44
RAIL_H = 30

# ---- 动效时长（毫秒）------------------------------------------------------
D_PAGE = 340        # 页面切换
D_HOVER = 230       # 悬停抬起
D_ENTER = 420       # 卡片入场


def shadow_spec(level: str = "card") -> tuple[int, int, int, int, int, int, int]:
    """投影规格：(blur, dx, dy, r, g, b, alpha)。

    分层柔投影 —— 一大一小两层叠出来的那种。淡紫主色下投影也偏紫，
    否则会在卡片边缘泛出一圈脏灰。
    """
    return {
        "card":    (30, 0, 7, 38, 28, 74, 22),
        "raised":  (48, 0, 17, 34, 24, 68, 42),
        "glass":   (22, 0, 8, 10, 6, 26, 48),
        "glow":    (28, 0, 9, 111, 92, 173, 78),
        "glow_hi": (38, 0, 14, 111, 92, 173, 120),
        "panel":   (40, 0, 14, 12, 8, 30, 62),
    }[level]


def stylesheet() -> str:
    return f"""
/* ======================================================================
   基础
   ====================================================================== */
* {{
    font-family: {FONT_FAMILY};
    font-size: 14px;
    color: {C['text']};
}}
QWidget#Root, QStackedWidget, QScrollArea,
QScrollArea > QWidget > QWidget {{
    background: {C['bg']};
}}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{
    background: {C['primary_deep']}; color: {C['ink_text']};
    border: 1px solid {C['hairline_dark']};
    padding: 8px 13px; border-radius: {R_SM}px; font-size: 12.5px;
}}

/* ======================================================================
   顶部天幕：玻璃导航浮在上面
   ====================================================================== */
QWidget#HeroBand, QWidget#BrandPanel {{ background: transparent; }}
QFrame#NavPill {{
    background: rgba(255, 255, 255, 13%);
    border: 1px solid rgba(255, 255, 255, 20%);
    border-radius: {NAV_H // 2}px;
}}
QLabel#Wordmark {{
    font-size: 15.5px; font-weight: 700; color: rgba(255, 255, 255, 97%);
}}
QLabel#NavMeta {{
    color: rgba(255, 255, 255, 54%); font-size: 12.5px; padding-right: 6px;
}}
QPushButton#NavGhost {{
    background: transparent; border: 1px solid transparent;
    color: rgba(255, 255, 255, 76%);
    font-size: 12.5px; font-weight: 600;
    padding: 4px 14px; min-height: 16px; border-radius: 13px;
}}
QPushButton#NavGhost:hover {{
    background: rgba(255, 255, 255, 14%);
    border: 1px solid rgba(255, 255, 255, 26%);
    color: #FFFFFF;
}}
QPushButton#NavGhost:pressed {{ background: rgba(255, 255, 255, 22%); }}

/* ======================================================================
   排版层级：眉标（小 / 淡）压在大标题（大 / 700）之上
   ====================================================================== */
QLabel#Eyebrow {{
    color: {C['text_faint']};
    font-size: 12.5px; font-weight: 600; letter-spacing: 1.2px;
}}
QLabel#EyebrowDark {{
    color: rgba(255, 255, 255, 56%);
    font-size: 12.5px; font-weight: 600; letter-spacing: 1.2px;
}}
QLabel#PageTitle {{
    font-size: 33px; font-weight: 700; color: {C['text']};
}}
QLabel#FormTitle {{
    font-size: 26px; font-weight: 700; color: {C['text']};
}}
QLabel#PageSub {{
    font-size: 14px; color: {C['text_faint']};
}}
QLabel#CardTitle {{
    font-size: 19px; font-weight: 700; color: {C['text']};
}}
QLabel#SectionTitle {{
    font-size: 15.5px; font-weight: 700; color: {C['text']};
}}
QLabel#FieldLabel {{
    color: {C['text_dim']}; font-size: 12.5px; font-weight: 600;
    letter-spacing: .4px;
}}
QLabel#Hint  {{ color: {C['text_dim']};   font-size: 13px; }}
QLabel#Faint {{ color: {C['text_faint']}; font-size: 12.5px; }}
QLabel#Error {{ color: {C['danger']};     font-size: 13px; }}
QLabel#Success {{ color: {C['accent']};   font-size: 13px; }}
QLabel#Warn  {{ color: {C['warn']};       font-size: 13px; }}

QLabel#StatValue {{
    font-size: 30px; font-weight: 700; color: {C['text']};
}}
QLabel#StatLabel {{
    color: {C['text_faint']}; font-size: 12px;
}}
QLabel#BigState {{
    font-size: 27px; font-weight: 700; color: {C['text']};
}}
QLabel#BrandTitle {{
    font-size: 40px; font-weight: 700; color: rgba(255, 255, 255, 98%);
}}
QLabel#BrandSub {{
    font-size: 14.5px; color: rgba(255, 255, 255, 66%);
}}
QLabel#BrandMeta {{
    font-size: 13px; color: rgba(255, 255, 255, 58%);
}}
QLabel#Rule {{ background: {C['border_soft']}; border: none; }}
QLabel#RuleDark {{ background: rgba(255, 255, 255, 14%); border: none; }}

/* ======================================================================
   卡片：浅渐变 + 发丝描边（投影在代码里加）
   ====================================================================== */
QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 {C['card_soft']});
    border: 1px solid {C['hairline']};
    border-radius: {R_CARD}px;
}}
QFrame#CardFlat {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FDFCFE);
    border: 1px solid {C['hairline']};
    border-radius: {R_MD}px;
}}
QFrame#CardFlat[hovered="true"] {{
    border: 1px solid rgba(111, 92, 173, 38%);
    background: #FFFFFF;
}}
QFrame#Inset {{
    background: {C['primary_tint']};
    border: 1px solid rgba(111, 92, 173, 12%);
    border-radius: {R_MD}px;
}}
QFrame#GlassCard {{
    background: rgba(255, 255, 255, 10%);
    border: 1px solid rgba(255, 255, 255, 16%);
    border-radius: {R_MD}px;
}}
QFrame#HumanBox {{
    background: {C['warn_light']};
    border: 1px solid rgba(150, 104, 28, 20%);
    border-left: 3px solid {C['warn']};
    border-radius: {R_MD}px;
}}

/* ======================================================================
   按钮
   ====================================================================== */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FBFAFE);
    border: 1px solid {C['border_strong']};
    border-radius: {R_PILL}px;
    padding: 11px 22px;
    min-height: 20px;
    font-size: 13.5px; font-weight: 600;
    color: {C['text']};
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 {C['primary_tint']});
    border: 1px solid {C['primary']};
    color: {C['primary']};
}}
QPushButton:pressed {{ background: {C['bg_soft']}; }}
QPushButton:disabled {{
    color: {C['text_ghost']};
    background: #F2F1F7;
    border: 1px solid {C['border_soft']};
}}

QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {C['primary_2']}, stop:1 {C['primary']});
    color: #FFFFFF;
    border: 1px solid {C['primary']};
    font-weight: 700; padding: 11px 28px;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #9C8BD6, stop:1 #7A67BB);
    border: 1px solid {C['primary_2']};
    color: #FFFFFF;
}}
QPushButton#Primary:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {C['primary']}, stop:1 {C['primary_dark']});
}}
QPushButton#Primary:disabled {{
    background: #C9C5D6; border: 1px solid #C9C5D6; color: #FFFFFF;
}}

QPushButton#OnDark {{
    background: rgba(255, 255, 255, 12%);
    border: 1px solid rgba(255, 255, 255, 28%);
    color: rgba(255, 255, 255, 96%);
    font-weight: 600;
}}
QPushButton#OnDark:hover {{
    background: rgba(255, 255, 255, 22%);
    border: 1px solid rgba(255, 255, 255, 50%);
    color: #FFFFFF;
}}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid {C['border']};
    color: {C['text_dim']};
    padding: 5px 14px; min-height: 16px;
    border-radius: 14px;
    font-size: 12.5px; font-weight: 600;
}}
QPushButton#Ghost:hover {{
    background: {C['primary_tint']};
    border: 1px solid rgba(111, 92, 173, 30%);
    color: {C['primary']};
}}
QPushButton#Ghost:pressed {{ background: {C['primary_light']}; }}

QPushButton#Danger {{
    color: {C['danger']};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FDF9FA);
    border: 1px solid rgba(176, 58, 74, 32%);
}}
QPushButton#Danger:hover {{
    background: {C['danger_light']};
    border: 1px solid {C['danger']};
    color: {C['danger']};
}}

QPushButton#Link {{
    background: transparent; border: none;
    color: {C['text_dim']}; padding: 6px 4px;
    font-size: 13px; font-weight: 600;
}}
QPushButton#Link:hover {{ color: {C['primary']}; background: transparent; }}

/* ======================================================================
   输入
   ====================================================================== */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit {{
    background: #FFFFFF;
    border: 1px solid {C['border_strong']};
    border-radius: {R_IN}px;
    padding: 9px 14px;
    min-height: 22px;
    font-size: 14px;
    selection-background-color: {C['primary']};
    selection-color: #FFFFFF;
}}
QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox {{ min-height: 22px; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover,
QDateTimeEdit:hover {{
    border: 1px solid {C['primary_mid']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateTimeEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {C['primary']};
    background: #FFFFFF;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateTimeEdit:disabled {{
    background: #F2F1F7; color: {C['text_ghost']};
    border: 1px solid {C['border_soft']};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: #FFFFFF;
    border: 1px solid {C['hairline']};
    border-radius: {R_IN}px;
    padding: 6px;
    outline: none;
    selection-background-color: {C['primary_light']};
    selection-color: {C['primary']};
}}

QCheckBox {{ spacing: 10px; font-size: 13px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {C['border_strong']};
    border-radius: 6px;
    background: #FFFFFF;
}}
QCheckBox::indicator:hover {{ border: 1px solid {C['primary']}; }}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {C['primary_2']}, stop:1 {C['primary']});
    border: 1px solid {C['primary']};
}}

/* ======================================================================
   进度 / 日志
   ====================================================================== */
QProgressBar {{
    border: none; border-radius: 3px;
    background: rgba(111, 92, 173, 12%);
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {C['primary_soft']}, stop:1 {C['primary']});
    border-radius: 3px;
}}

QPlainTextEdit#Log {{
    background: {C['log_bg']};
    color: {C['log_text']};
    border: 1px solid {C['hairline_dark']};
    border-radius: {R_MD}px;
    font-family: {MONO_FAMILY};
    font-size: 12.5px;
    padding: 16px 18px;
    selection-background-color: {C['primary_dark']};
}}

/* ======================================================================
   列表 / 滚动条
   ====================================================================== */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: {R_MD}px; margin: 3px 0; }}

/* 滚动条：**平时完全透明**，鼠标移到该区域或拖到把手上才显形。
   常驻一条浅灰竖条横在版面中间是最伤观感的东西 —— 但直接藏掉又会让
   「下面还有内容」变得不可知（课程页确实有一屏放不下）。所以做成
   悬停显形的浮层式滚动条，不滚的时候等于不存在。 */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px 2px; }}
QScrollBar::handle:vertical {{
    background: transparent; border-radius: 5px; min-height: 44px;
}}
QScrollArea:hover QScrollBar::handle:vertical,
QScrollBar:hover QScrollBar::handle:vertical {{
    background: rgba(38, 28, 74, 20%);
}}
QScrollBar::handle:vertical:hover {{ background: rgba(38, 28, 74, 40%); }}

QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px 3px; }}
QScrollBar::handle:horizontal {{
    background: transparent; border-radius: 5px; min-width: 44px;
}}
QScrollArea:hover QScrollBar::handle:horizontal,
QScrollBar:hover QScrollBar::handle:horizontal {{
    background: rgba(38, 28, 74, 20%);
}}
QScrollBar::handle:horizontal:hover {{ background: rgba(38, 28, 74, 40%); }}

QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* 深色日志面板里的滚动条同理 */
QPlainTextEdit#Log QScrollBar::handle:vertical {{ background: transparent; }}
QPlainTextEdit#Log:hover QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 24%);
}}
QPlainTextEdit#Log QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 40%);
}}
"""


# ---- 步骤条 ---------------------------------------------------------------
STEPS = ["登录", "选择模式", "预定课程", "确认启动", "运行监控"]


def step_state(index: int, current: int) -> str:
    """步骤状态：done / active / todo。"""
    if index == current:
        return "active"
    return "done" if index < current else "todo"
