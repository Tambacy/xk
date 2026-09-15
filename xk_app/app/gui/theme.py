# -*- coding: utf-8 -*-
"""界面主题：设计令牌 + 全局样式表。

视觉语言取自 espaciolanube.com。第一次改版只搬了它的「令牌」（骨白、深墨绿、
无投影、胶囊），结果是一堆贴在米色底上的白方块 —— 因为参考站的美感**并不**
来自那些令牌，而来自三件事：

  1. **满幅的深色影像**：整站的戏剧性全在那张占满首屏的照片上，
     玻璃导航、白色大字都只是浮在它上面的东西。
  2. **深度**：参考站没有 box-shadow，是因为它用影像和透明度造深度；
     纯色平面上照搬「零投影」，剩下的就只有「方块叠方块」。
  3. **形体变化**：圆、弧、胶囊、满幅色块、叠压的卡片 —— 而不是同一种矩形。

所以这一版补的是这三样：

  · 窗口顶部一条**深墨绿渐变 Hero 带**（带同心弧纹），玻璃导航浮在上面 ——
    这是参考站「深色底 + 玻璃 + 白色大字」那套关系的等价物；
  · 卡片恢复**分层柔和投影 + 极浅渐变 + 发丝描边**，可点卡片悬停会抬起；
  · 主按钮走**渐变 + 绿色辉光**，状态用**左侧色条**而不是灰字，
    登录页做成**深色品牌面板 + 表单**的分栏。
"""
from __future__ import annotations

# ---- 配色 -----------------------------------------------------------------
C = {
    # 品牌绿阶（从最暗到最浅，够撑起渐变和色块，不是只有一个色号）
    "primary_deep":   "#08170E",
    "primary_ink":    "#0C2A19",
    "primary":        "#0F4223",
    "primary_2":      "#17512C",   # 渐变亮端
    "primary_soft":   "#2E6B47",   # 装饰线 / 次级强调
    "primary_mid":    "#8FA898",   # 半调
    "primary_light":  "#E4ECE6",   # 浅底
    "primary_tint":   "#F1F5F1",   # 极浅底

    # 兼容旧键名
    "primary_dark":   "#0A2E18",

    # 语义色（成功沿用主色，参考站是单色系统）
    "accent":         "#0F4223",
    "accent_light":   "#E4ECE6",
    "warn":           "#96631A",
    "warn_mid":       "#C08A2E",
    "warn_light":     "#F7EFE1",
    "danger":         "#A32E22",
    "danger_mid":     "#C8503F",
    "danger_light":   "#F8E9E6",
    "danger_bright":  "#FF6B70",   # 深色面板上的告警红

    # 中性（暖调，跟着参考站的 #989490 走）
    "bg":             "#F2F2F0",   # 骨白
    "bg_soft":        "#EAE9E5",
    "bg_deep":        "#E4E3DE",
    "card":           "#FFFFFF",
    "card_soft":      "#FCFCFB",
    "glass":          "rgba(255, 255, 255, 22%)",
    "border":         "#E3E2DD",
    "border_soft":    "#EEEDE8",
    "border_strong":  "#D5D3CD",
    "hairline":       "rgba(20, 32, 24, 7%)",
    "hairline_dark":  "rgba(255, 255, 255, 12%)",

    "text":           "#191A17",
    "text_dim":       "#6B6862",
    "text_faint":     "#989490",
    "text_ghost":     "#B3B0AD",

    # 深色面板
    "log_bg":         "#0C1410",
    "log_text":       "#D7D6D3",
    "log_dim":        "#6E7671",
    "ink":            "#111411",
    "ink_soft":       "#1B1F1B",
    "ink_text":       "#D7D6D3",
    "ink_dim":        "#7E857F",
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

# ---- 高度 -------------------------------------------------------------
HERO_H = 116        # 顶部深色带（不含底部化开区）
NAV_H = 48          # 玻璃导航胶囊
RAIL_H = 32         # 步骤导轨


def shadow_spec(level: str = "card") -> tuple[int, int, int, int, int, int, int]:
    """投影规格：(blur, dx, dy, r, g, b, alpha)。

    分层柔投影 —— 一大一小两层叠出来的那种。纯色平面上没有它就只剩方块。
    """
    return {
        # 常态卡片：贴着底，几乎感觉不到
        "card":   (28, 0, 6, 18, 34, 24, 20),
        # 悬停 / 抬起的卡片
        "raised": (46, 0, 16, 16, 34, 22, 38),
        # 玻璃导航：窄而实，像浮在带子上
        "glass":  (22, 0, 8, 6, 24, 14, 46),
        # 主按钮的绿色辉光
        "glow":   (26, 0, 8, 15, 66, 35, 64),
        "glow_hi": (34, 0, 12, 15, 66, 35, 92),
        # 品牌面板里的元素
        "panel":  (40, 0, 14, 4, 16, 9, 60),
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
/* 骨白底平涂（和参考站的 body 同色）。顶部 Hero 带与页面之间的过渡
   由 Root 的 paintEvent 画一层柔光，见 widgets.paint_page_wash()。 */
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
   顶部深色带：玻璃导航浮在上面
   ====================================================================== */
QWidget#HeroBand {{ background: transparent; }}
QFrame#NavPill {{
    background: rgba(255, 255, 255, 13%);
    border: 1px solid rgba(255, 255, 255, 17%);
    border-radius: {NAV_H // 2}px;
}}
QLabel#Wordmark {{
    font-size: 15.5px; font-weight: 700; color: rgba(255, 255, 255, 96%);
}}
QLabel#NavMeta {{
    color: rgba(255, 255, 255, 52%); font-size: 12.5px;
    padding-right: 6px;
}}
QPushButton#NavGhost {{
    background: transparent; border: 1px solid transparent;
    color: rgba(255, 255, 255, 74%);
    font-size: 13px; font-weight: 600;
    padding: 5px 16px; min-height: 16px; border-radius: 14px;
}}
QPushButton#NavGhost:hover {{
    background: rgba(255, 255, 255, 13%);
    border: 1px solid rgba(255, 255, 255, 22%);
    color: #FFFFFF;
}}
QPushButton#NavGhost:pressed {{ background: rgba(255, 255, 255, 20%); }}

/* 页面区与 Hero 带之间的标题条 */
QFrame#PageHead {{ background: transparent; }}
QLabel#PageHeadTitle {{
    font-size: 15px; font-weight: 700; color: {C['text']};
}}
QLabel#PageHeadMeta {{ color: {C['text_faint']}; font-size: 12.5px; }}

/* ======================================================================
   排版层级：眉标（小 / 淡）压在大标题（大 / 700 / 负字距）之上
   ====================================================================== */
QLabel#Eyebrow {{
    color: {C['text_faint']};
    font-size: 12.5px; font-weight: 600; letter-spacing: 1.2px;
}}
QLabel#EyebrowDark {{ color: rgba(255, 255, 255, 50%); font-size: 12.5px;
    font-weight: 600; letter-spacing: 1.2px; }}
QLabel#PageTitle {{
    font-size: 33px; font-weight: 700; color: {C['text']};
}}
/* 表单卡片里的标题：比页面标题小一号，不跟左侧品牌面板的大字抢 */
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
QLabel#Success {{ color: {C['primary']};  font-size: 13px; }}
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
/* 深色品牌面板上的大标题 */
QLabel#BrandTitle {{
    font-size: 40px; font-weight: 700; color: rgba(255, 255, 255, 97%);
}}
QLabel#BrandSub {{
    font-size: 14.5px; color: rgba(255, 255, 255, 62%);
}}
QLabel#BrandMeta {{
    font-size: 13px; color: rgba(255, 255, 255, 55%);
}}
QLabel#Rule {{ background: {C['border_soft']}; border: none; }}
QLabel#RuleDark {{ background: rgba(255, 255, 255, 12%); border: none; }}

/* ======================================================================
   卡片：浅渐变 + 发丝描边（投影在代码里加，样式表画不了）
   ====================================================================== */
QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 {C['card_soft']});
    border: 1px solid {C['hairline']};
    border-radius: {R_CARD}px;
}}
QFrame#CardFlat {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FDFDFC);
    border: 1px solid {C['hairline']};
    border-radius: {R_MD}px;
}}
QFrame#CardFlat[hovered="true"] {{
    border: 1px solid rgba(15, 66, 35, 34%);
    background: #FFFFFF;
}}
QFrame#Inset {{
    background: {C['primary_tint']};
    border: 1px solid rgba(15, 66, 35, 10%);
    border-radius: {R_MD}px;
}}
/* 深色带上的玻璃块 */
QFrame#GlassCard {{
    background: rgba(255, 255, 255, 10%);
    border: 1px solid rgba(255, 255, 255, 15%);
    border-radius: {R_MD}px;
}}

/* 需要你本人操作（验证码 / 二次认证）的提示块 */
QFrame#HumanBox {{
    background: {C['warn_light']};
    border: 1px solid rgba(150, 99, 26, 20%);
    border-left: 3px solid {C['warn']};
    border-radius: {R_MD}px;
}}

/* ======================================================================
   按钮：胶囊几何
   ====================================================================== */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FBFBFA);
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
    background: #F2F1ED;
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
                stop:0 #1C6034, stop:1 #124F2A);
    border: 1px solid {C['primary_2']};
    color: #FFFFFF;
}}
QPushButton#Primary:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {C['primary']}, stop:1 {C['primary_dark']});
}}
QPushButton#Primary:disabled {{
    background: #C4C7C2; border: 1px solid #C4C7C2; color: #FFFFFF;
}}

/* 深色带 / 品牌面板上的按钮 */
QPushButton#OnDark {{
    background: rgba(255, 255, 255, 12%);
    border: 1px solid rgba(255, 255, 255, 26%);
    color: rgba(255, 255, 255, 95%);
    font-weight: 600;
}}
QPushButton#OnDark:hover {{
    background: rgba(255, 255, 255, 22%);
    border: 1px solid rgba(255, 255, 255, 46%);
    color: #FFFFFF;
}}

/* 行内小动作：同一种胶囊，只是更小 */
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
    border: 1px solid rgba(15, 66, 35, 26%);
    color: {C['primary']};
}}
QPushButton#Ghost:pressed {{ background: {C['primary_light']}; }}

QPushButton#Danger {{
    color: {C['danger']};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFFFF, stop:1 #FDF9F8);
    border: 1px solid rgba(163, 46, 34, 30%);
}}
QPushButton#Danger:hover {{
    background: {C['danger_light']};
    border: 1px solid {C['danger']};
    color: {C['danger']};
}}

/* 纯文字链接式按钮 */
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
    background: #F2F1ED; color: {C['text_ghost']};
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
    background: rgba(15, 66, 35, 10%);
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
    selection-background-color: {C['primary_soft']};
}}
QPlainTextEdit#Log QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 22%); border-radius: 5px;
}}
QPlainTextEdit#Log QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 36%);
}}
QPlainTextEdit#Log QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 2px;
}}

/* ======================================================================
   列表 / 滚动条
   ====================================================================== */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: {R_MD}px; margin: 3px 0; }}

/* 滚动条：做得尽量轻。原来 11px 宽的浅灰把手会横在布局中间，
   把版面切成两半 —— 这里是整屏最容易被忽略、也最破坏整洁的一处。 */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px; }}
QScrollBar::handle:vertical {{
    background: rgba(20, 32, 24, 12%); border-radius: 4px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(20, 32, 24, 26%); }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px 3px; }}
QScrollBar::handle:horizontal {{
    background: rgba(20, 32, 24, 12%); border-radius: 4px; min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: rgba(20, 32, 24, 26%); }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


# ---- 步骤条 ---------------------------------------------------------------
STEPS = ["登录", "选择模式", "预定课程", "确认启动", "运行监控"]


def step_state(index: int, current: int) -> str:
    """步骤状态：done / active / todo。"""
    if index == current:
        return "active"
    return "done" if index < current else "todo"
