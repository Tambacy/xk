# -*- coding: utf-8 -*-
"""五个页面：登录 → 模式 → 预定课程 → 确认 → 监控。"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal, QDateTime, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QCheckBox, QComboBox, QListWidget,
                               QListWidgetItem, QScrollArea, QFrame, QMessageBox,
                               QDateTimeEdit, QDoubleSpinBox, QPlainTextEdit,
                               QSizePolicy, QGridLayout, QSpinBox, QProgressBar)

from .theme import C
from .widgets import (BrandPanel, Card, CourseCard, GlowButton, LogoMark,
                      ModeCard, StatBox, Dot, clear_layout, divider, eyebrow)
from ..browser import COURSE_KINDS, HUMAN_RESEND, HUMAN_VISIBLE
from ..config import APP_VERSION, CourseEntry


def _title(text, sub="", over="", rule=True, style="PageTitle"):
    """页面标题块：眉标 → 大标题 → 说明 → 一条发丝分割线。

    层级照搬参考站：小字号淡色眉标压在大字重标题之上
    （"Nube 02" / "Gravity is in the air"），标题下压一条极淡的横线，
    把「页头」和「内容」分成两段 —— 整屏才有节奏，而不是一摞等距方块。
    """
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    if over:
        lay.addWidget(eyebrow(over))
        lay.addSpacing(9)
    t = QLabel(text)
    t.setObjectName(style)
    lay.addWidget(t)
    if sub:
        lay.addSpacing(7)
        s = QLabel(sub)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(s)
    if rule:
        lay.addSpacing(18)
        lay.addWidget(divider())
    return w


def _flab(text):
    """表单字段标签。"""
    lb = QLabel(text)
    lb.setObjectName("FieldLabel")
    return lb


def _dot_line(text: str, *, color: str = "rgba(255,255,255,0.55)",
              obj: str = "BrandMeta", indent: int = 0) -> QHBoxLayout:
    """深色面板上的一条「圆点 + 说明」。"""
    row = QHBoxLayout()
    row.setSpacing(12)
    row.setContentsMargins(indent, 0, 0, 0)
    d = QLabel()
    d.setFixedSize(5, 5)
    d.setStyleSheet(f"background:{color};border-radius:2px;")
    row.addWidget(d, 0, Qt.AlignTop)
    lb = QLabel(text)
    lb.setObjectName(obj)
    lb.setWordWrap(True)
    row.addWidget(lb, 1)
    return row



# ==========================================================================
# 1. 登录
# ==========================================================================
class LoginPage(QWidget):
    submit = Signal(str, str, bool, bool)     # user, pwd, remember, trust

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        # 分栏：左边深色品牌面板（整屏高），右边表单。
        # 参考站的首屏就是「满幅深色 + 浮在上面的内容」，这一页照这个关系做，
        # 不再是一个白卡片孤零零地飘在米色底上。
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------------- 左：品牌面板 ----------------
        brand = BrandPanel()
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(46, 38, 42, 34)
        bl.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(LogoMark(34, "清", dark=True))
        bm = QLabel("学校选课助手")
        bm.setStyleSheet("font-size:15px;font-weight:700;"
                         "color:rgba(255,255,255,0.95);")
        top.addWidget(bm)
        top.addStretch(1)
        bl.addLayout(top)

        bl.addStretch(3)

        bl.addWidget(eyebrow(f"XK HELPER · v{APP_VERSION}", dark=True))
        bl.addSpacing(18)

        btitle = QLabel("学校选课助手")
        btitle.setObjectName("BrandTitle")
        btitle.setWordWrap(True)
        bl.addWidget(btitle)
        bl.addSpacing(16)

        bsub = QLabel("自动盯课余量、按预定时间抢课 ——\n"
                      "全程用真实浏览器操作，不做任何脚本化请求")
        bsub.setObjectName("BrandSub")
        bsub.setWordWrap(True)
        bl.addWidget(bsub)

        bl.addSpacing(32)
        bl.addWidget(divider(dark=True))
        bl.addSpacing(24)
        for t in ("内置完整 Chromium，所有动作都是真实鼠标键盘事件",
                  "轮询间隔随机浮动，带长尾停顿与夜间静默",
                  "账号密码用 Windows DPAPI 加密，明文不落盘"):
            bl.addLayout(_dot_line(t))
            bl.addSpacing(14)

        bl.addStretch(4)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.btn_help = QPushButton("使用说明")
        self.btn_help.setObjectName("OnDark")
        self.btn_help.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.btn_help)
        foot.addStretch(1)
        self.lb_user_brand = QLabel("")
        self.lb_user_brand.setObjectName("BrandMeta")
        foot.addWidget(self.lb_user_brand)
        bl.addLayout(foot)

        outer.addWidget(brand, 4)

        # ---------------- 右：表单 ----------------
        # 卡片里除了表单还有登录进度和「需要你本人操作」提示块，内容高度会变。
        # 直接放在页面布局里的话，窗口一矮 Qt 就会把这些标签压扁成一条线
        # （字叠在一起）。所以套一层滚动区：放不下就滚动，绝不变形。
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(44, 44, 44, 44)
        lay.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        card = Card()
        card.setFixedWidth(472)
        card.body.setContentsMargins(34, 32, 34, 30)
        card.body.setSpacing(14)
        card.body.addWidget(_title("登录", "使用学校统一身份认证账号",
                                   "统一身份认证", rule=False, style="FormTitle"))

        card.body.addSpacing(12)
        card.body.addWidget(self._lab("学号"))
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("学号 / 工作证号")
        card.body.addWidget(self.ed_user)

        card.body.addSpacing(6)
        card.body.addWidget(self._lab("密码"))
        self.ed_pwd = QLineEdit()
        self.ed_pwd.setEchoMode(QLineEdit.Password)
        self.ed_pwd.setPlaceholderText("统一身份认证密码")
        self.ed_pwd.returnPressed.connect(self._emit)
        card.body.addWidget(self.ed_pwd)

        card.body.addSpacing(4)
        self.cb_remember = QCheckBox("记住密码（用 Windows 加密保存在本机，仅当前账户可解）")
        self.cb_remember.setChecked(True)
        card.body.addWidget(self.cb_remember)

        self.cb_trust = QCheckBox("信任此浏览器（接下来的登录免输账号密码）")
        self.cb_trust.setChecked(True)
        self.cb_trust.setToolTip(
            "学校原话：「本次登录使用信任浏览器访问校内其他系统时不必再输入\n"
            "账号密码（统一登录）」。\n\n"
            "注意：这**不等于**免验证码。要不要把本机登记为「信任设备」\n"
            "（180 天内免验证码）是登录时单独问你的，那一步在登录页上。")
        card.body.addWidget(self.cb_trust)

        card.body.addSpacing(12)
        self.btn = GlowButton("登 录")
        self.btn.setMinimumHeight(44)
        self.btn.clicked.connect(self._emit)
        card.body.addWidget(self.btn)


        self.lb_status = QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setObjectName("Hint")
        card.body.addWidget(self.lb_status)

        # 登录进度：登录常要几十秒，必须让用户看得到它在动
        self.progress_box = QFrame()
        self.progress_box.setObjectName("Inset")
        self.progress_box.setVisible(False)
        pb = QVBoxLayout(self.progress_box)
        pb.setContentsMargins(16, 14, 16, 14)
        pb.setSpacing(8)
        prow = QHBoxLayout()
        self.lb_prog_step = QLabel("")
        self.lb_prog_step.setWordWrap(True)
        prow.addWidget(self.lb_prog_step, 1)
        self.lb_prog_time = QLabel("0s")
        self.lb_prog_time.setStyleSheet(
            f"color:{C['primary']};font-weight:700;font-size:14px;")
        prow.addWidget(self.lb_prog_time)
        pb.addLayout(prow)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)          # 不确定进度，走马灯
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        pb.addWidget(self.bar)
        self.lb_prog_tip = QLabel("登录通常 10~40 秒。请勿关闭程序；"
                                 "如果需要验证码，会直接显示在这个窗口里。")
        self.lb_prog_tip.setObjectName("Faint")
        self.lb_prog_tip.setWordWrap(True)
        pb.addWidget(self.lb_prog_tip)
        card.body.addWidget(self.progress_box)

        # ---- 「需要你本人操作」提示块 ----
        # 图形验证码和二次验证都由这里完成，**不打开浏览器窗口** ——
        # 全程只有一个窗口。验证码图片会直接显示在这块里。
        self.human_box = QFrame()
        self.human_box.setObjectName("HumanBox")
        self.human_box.setVisible(False)
        hb = QVBoxLayout(self.human_box)
        hb.setContentsMargins(16, 14, 16, 14)
        hb.setSpacing(9)
        self.lb_human_title = QLabel("需要你本人验证")
        self.lb_human_title.setStyleSheet(
            f"color:{C['warn']};font-weight:700;font-size:14px;")
        hb.addWidget(self.lb_human_title)

        self.lb_human = QLabel("")
        self.lb_human.setWordWrap(True)
        hb.addWidget(self.lb_human)

        # 图形验证码：直接把图片显示在这里
        self.lb_captcha = QLabel()
        self.lb_captcha.setAlignment(Qt.AlignLeft)
        self.lb_captcha.setVisible(False)
        hb.addWidget(self.lb_captcha)

        row_h = QHBoxLayout()
        self.ed_code = QLineEdit()
        self.ed_code.setPlaceholderText("在这里输入验证码")
        self.ed_code.returnPressed.connect(self._submit_code)
        row_h.addWidget(self.ed_code, 1)
        self.btn_code = QPushButton("确定")
        self.btn_code.setObjectName("Primary")
        self.btn_code.clicked.connect(self._submit_code)
        row_h.addWidget(self.btn_code)
        hb.addLayout(row_h)

        # 需要用户在几个选项里挑一个时（例如验证码发到手机还是发到微信），
        # 这里会动态长出一排按钮
        self.choice_row = QHBoxLayout()
        hb.addLayout(self.choice_row)

        row_h2 = QHBoxLayout()
        self.btn_resend = QPushButton("重新发送验证码")
        self.btn_resend.setObjectName("Ghost")
        self.btn_resend.clicked.connect(
            lambda: self._answer(HUMAN_RESEND))
        row_h2.addWidget(self.btn_resend)
        self.btn_use_window = QPushButton("改用浏览器窗口完成")
        self.btn_use_window.setObjectName("Ghost")
        self.btn_use_window.setToolTip(
            "程序认不出这个验证页面时才需要。会打开一个浏览器窗口让你在里面操作。")
        self.btn_use_window.clicked.connect(
            lambda: self._answer(HUMAN_VISIBLE))
        row_h2.addWidget(self.btn_use_window)
        row_h2.addStretch(1)
        self.btn_cancel_login = QPushButton("取消登录")
        self.btn_cancel_login.setObjectName("Ghost")
        self.btn_cancel_login.clicked.connect(self._cancel_code)
        row_h2.addWidget(self.btn_cancel_login)
        hb.addLayout(row_h2)

        card.body.addWidget(self.human_box)

        card.body.addSpacing(6)
        card.body.addWidget(divider())
        card.body.addSpacing(6)
        tip = QLabel("账号密码只加密保存在本机（Windows DPAPI），换用户或换电脑都解不开；"
                     "卸载程序时不会删除。")
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        card.body.addWidget(tip)

        self.btn_forget = QPushButton("清除本机已保存的账号密码")
        self.btn_forget.setObjectName("Link")
        self.btn_forget.setCursor(Qt.PointingHandCursor)
        card.body.addWidget(self.btn_forget)


        row.addWidget(card)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 6)

    @staticmethod
    def _lab(t):
        lb = QLabel(t)
        lb.setObjectName("FieldLabel")
        return lb

    def set_config(self, cfg):
        self.ed_user.setText(cfg.user or "")
        self.cb_remember.setChecked(bool(cfg.remember_password))
        self.cb_trust.setChecked(bool(cfg.single_login))

    def _emit(self):
        u = self.ed_user.text().strip()
        p = self.ed_pwd.text()
        if not u or not p:
            self.set_status("请填写学号和密码。", "warn")
            return
        self.btn.setEnabled(False)
        self.btn.setText("登录中…")
        self.set_status("正在启动浏览器并登录，第一次会稍慢…")
        self.submit.emit(u, p, self.cb_remember.isChecked(), self.cb_trust.isChecked())

    def set_status(self, text, kind="info"):
        color = {"info": C["text_dim"], "warn": C["warn"],
                 "err": C["danger"], "ok": C["accent"]}.get(kind, C["text_dim"])
        self.lb_status.setStyleSheet(f"color:{color};")
        self.lb_status.setText(text)

    # ---- 登录进度 ----
    def begin_progress(self):
        self.progress_box.setVisible(True)
        self.hide_human()
        self.lb_prog_step.setText("正在准备…")
        self.set_elapsed(0)

    def set_progress(self, text: str):
        self.progress_box.setVisible(True)
        self.lb_prog_step.setText(text)

    def set_human(self, text: str):
        """需要你本人操作时的说明（用于「改用浏览器窗口」那种情况）。"""
        self.progress_box.setVisible(True)
        self.lb_prog_step.setText(text)
        self.lb_human.setText(text)
        self.ed_code.setVisible(False)
        self.btn_code.setVisible(False)
        self.btn_resend.setVisible(False)
        self.lb_captcha.setVisible(False)
        self.human_box.setVisible(True)

    def show_prompt(self, prompt):
        """在工作线程发来一次人工输入请求时显示输入区。

        prompt 是 core.HumanPrompt（这里只 duck-typing 用它，不 import，
        免得界面层和线程层互相依赖）。
        """
        self.progress_box.setVisible(True)
        self.lb_prog_step.setText("等待你输入验证码…")
        self.lb_human.setText(prompt.message)
        self._prompt = prompt

        img = getattr(prompt, "image", None)
        if img:
            pix = QPixmap()
            if pix.loadFromData(img):
                self.lb_captcha.setPixmap(pix)
                self.lb_captcha.setVisible(True)
            else:
                self.lb_captcha.setVisible(False)
        else:
            self.lb_captcha.setVisible(False)

        # 「要不要开浏览器窗口」这种纯选择题里不显示输入框
        allow_code = bool(getattr(prompt, "allow_code", True))
        self.ed_code.clear()
        self.ed_code.setVisible(allow_code)
        self.btn_code.setVisible(allow_code)
        self.btn_resend.setVisible(bool(getattr(prompt, "allow_resend", False)))
        self.btn_use_window.setVisible(bool(getattr(prompt, "allow_visible", False)))
        self.btn_cancel_login.setVisible(True)

        # 选项按钮（例如"验证码发到手机 / 发到微信"）
        clear_layout(self.choice_row, keep_tail=0)
        for ch in (getattr(prompt, "choices", None) or []):
            b = QPushButton(str(ch.get("label", "?")))
            b.setObjectName("Primary")
            b.setCursor(Qt.PointingHandCursor)
            val = str(ch.get("value", ""))
            b.clicked.connect(lambda _=False, v=val: self._answer(v))
            self.choice_row.addWidget(b)
        self.choice_row.addStretch(1)

        self.human_box.setVisible(True)
        if allow_code:
            self.ed_code.setFocus()
        elif (getattr(prompt, "choices", None) or []):
            pass                       # 让用户自己点选项
        else:
            self.btn_use_window.setFocus()

    def _answer(self, value: str):
        p = getattr(self, "_prompt", None)
        if p is not None:
            p.submit(value)

    def _submit_code(self):
        code = self.ed_code.text().strip()
        if not code:
            return
        self.ed_code.clear()
        self._answer(code)

    def _cancel_code(self):
        p = getattr(self, "_prompt", None)
        if p is not None:
            p.cancel()

    def hide_human(self):
        self._prompt = None
        self.human_box.setVisible(False)

    def set_elapsed(self, seconds: float):
        self.lb_prog_time.setText(f"{seconds:.0f}s")

    def end_progress(self):
        self.progress_box.setVisible(False)
        self.hide_human()

    def on_done(self, ok, msg):
        self.btn.setEnabled(True)
        self.btn.setText("登 录")
        self.end_progress()
        if ok:
            self.set_status("登录成功。" + (msg if msg and msg != "登录成功" else ""), "ok")
        else:
            self.set_status(f"登录失败：{msg}", "err")


# ==========================================================================
# 2. 模式选择
# ==========================================================================
class ModePage(QWidget):
    chosen = Signal(int)
    back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 卡片高度固定、窗口一矮就会被压扁或截断 —— 和登录页一样套滚动区
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(52, 28, 52, 30)
        lay.setSpacing(30)
        lay.addWidget(_title("选择运行模式", "根据你现在处在选课的哪个阶段来选",
                             "步骤 2 / 5"))


        self.cards = []
        specs = [
            (1, "还没开始选课", "模式一",
             "现在还不是先到先得，投了也要等抽签，这时候抢没有意义。",
             ["填写学校通知里的开始选课时间",
              "程序提前开始盯「当前选课阶段」",
              "阶段一变成正选 / 补退选就自动选课",
              "全程拟人化节奏，慢一点没关系"]),
            (2, "马上开始，且已有课要让位", "模式二",
             "选课窗口即将打开，你手上有些课（可能没抽中或时间冲突）需要先退掉。",
             ["填写开始时间，并列出要退的课",
              "到点先退冲突课程，再抢目标课程",
              "等待期间拟人化，动手瞬间全速",
              "抢不到会自动把退掉的课选回来"]),
            (3, "长期蹲课余量", "模式三",
             "选课已经在进行中，目标课没余量，只能等别人退课捡漏。",
             ["不设开始时间，长期后台监听",
              "可设置平均监听间隔（最长 1 小时）",
              "尤其强调拟人化：长尾间隔、夜间静默",
              "发现余量立刻抢，需要让位就先退课"]),
        ]
        grid = QHBoxLayout()
        grid.setSpacing(22)
        for idx, title, badge, desc, bullets in specs:
            c = ModeCard(idx, title, badge, desc, bullets)
            c.clicked.connect(self.chosen.emit)
            grid.addWidget(c, 1)
            self.cards.append(c)
        lay.addLayout(grid)
        lay.addStretch(1)

        bar = QHBoxLayout()
        b = QPushButton("← 返回")
        b.clicked.connect(self.back.emit)
        bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll)


# ==========================================================================
# 3. 预定课程
# ==========================================================================
class CoursesPage(QWidget):
    validate = Signal(int, object, object)     # index, entry, selected_snapshot
    reload_selected = Signal()
    drop_requested = Signal(object)            # 用户点了已选课程右边的「要退」
    add_course = Signal(object)
    remove_course = Signal(int)
    back = Signal()
    next = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.entries: list[CourseEntry] = []
        self.selected_snapshot: list = []
        self.results: dict[int, dict] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(40, 26, 40, 24)
        root.setSpacing(26)

        # ---------- 左：录入 ----------
        # 窗口不高时这里会放不下（会被 Qt 压扁），所以套一层滚动区
        left_inner = QWidget()
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 14, 0)
        left.setSpacing(20)
        left.addWidget(_title("预定课程", "信息不用填全，能唯一定位到一门课就行",
                              "步骤 3 / 5"))

        self.form_card = Card()
        f = self.form_card.body
        self.lb_action = QLabel("我要抢这门课")
        self.lb_action.setObjectName("SectionTitle")
        f.addWidget(self.lb_action)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 84)
        grid.setColumnStretch(1, 1)          # 输入框占满剩余宽度
        self.cb_action = QComboBox()
        self.cb_action.addItems(["要抢的课", "要退的课"])
        self.cb_action.currentIndexChanged.connect(self._on_action_changed)
        grid.addWidget(_flab("用途"), 0, 0)
        grid.addWidget(self.cb_action, 0, 1)

        self.cb_kind = QComboBox()
        for k, v in COURSE_KINDS.items():
            self.cb_kind.addItem(v["name"], k)
        self.cb_kind.setCurrentIndex(list(COURSE_KINDS).index("ty"))
        grid.addWidget(_flab("课程种类"), 1, 0)
        grid.addWidget(self.cb_kind, 1, 1)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如 大学物理（可只填这一项）")
        grid.addWidget(_flab("课程名"), 2, 0)
        grid.addWidget(self.ed_name, 2, 1)

        self.ed_teacher = QLineEdit()
        self.ed_teacher.setPlaceholderText("选填")
        grid.addWidget(_flab("任课教师"), 3, 0)
        grid.addWidget(self.ed_teacher, 3, 1)

        self.ed_time = QLineEdit()
        self.ed_time.setPlaceholderText("选填，如 4-1")
        grid.addWidget(_flab("上课时间"), 4, 0)
        grid.addWidget(self.ed_time, 4, 1)

        self.ed_kch = QLineEdit()
        self.ed_kch.setPlaceholderText("选填，如 10421055")
        grid.addWidget(_flab("课程号"), 5, 0)
        grid.addWidget(self.ed_kch, 5, 1)

        self.ed_kxh = QLineEdit()
        self.ed_kxh.setPlaceholderText("选填，如 2")
        grid.addWidget(_flab("课序号"), 6, 0)
        grid.addWidget(self.ed_kxh, 6, 1)
        f.addLayout(grid)

        f.addSpacing(6)
        self.lb_hint = QLabel("提示：同名课程有多个课堂时，请补上课序号或上课时间。")
        self.lb_hint.setObjectName("Faint")
        self.lb_hint.setWordWrap(True)
        f.addWidget(self.lb_hint)

        rowb = QHBoxLayout()
        rowb.setSpacing(12)
        b_add = QPushButton("添加到清单")
        b_add.setObjectName("Primary")
        b_add.clicked.connect(self._on_add)
        rowb.addWidget(b_add)
        b_reload = QPushButton("刷新已选课程")
        b_reload.clicked.connect(self.reload_selected.emit)
        rowb.addWidget(b_reload)
        rowb.addStretch(1)
        f.addLayout(rowb)


        left.addWidget(self.form_card)

        # ---------- 运行设置 ----------
        self.set_card = Card("运行设置")
        s = self.set_card.body
        sg = QGridLayout()
        sg.setHorizontalSpacing(14)
        sg.setVerticalSpacing(12)

        self.dt_start = QDateTimeEdit()
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        sg.addWidget(_flab("开始选课时间"), 0, 0)
        sg.addWidget(self.dt_start, 0, 1)
        self.row_start = (0,)

        self.sp_lead = QSpinBox()
        self.sp_lead.setRange(0, 3600)
        self.sp_lead.setValue(60)
        self.sp_lead.setSuffix(" 秒")
        sg.addWidget(_flab("提前盯梢"), 1, 0)
        sg.addWidget(self.sp_lead, 1, 1)

        self.sp_avg = QDoubleSpinBox()
        self.sp_avg.setRange(0.5, 3600)
        self.sp_avg.setValue(3.0)
        self.sp_avg.setSuffix(" 秒")
        sg.addWidget(_flab("平均监听间隔"), 2, 0)
        sg.addWidget(self.sp_avg, 2, 1)

        # 学期：登录后自动识别并填充，也可手动改（换学期、跨学期提前预定都能用）
        self.cb_xnxq = QComboBox()
        self.cb_xnxq.setToolTip("登录后自动识别当前学期；也可以手动切换")
        sg.addWidget(_flab("学期"), 3, 0)
        sg.addWidget(self.cb_xnxq, 3, 1)
        self.lb_xnxql = sg.itemAtPosition(3, 0).widget()

        self.lb_lead = sg.itemAtPosition(1, 0).widget()
        self.lb_avgl = sg.itemAtPosition(2, 0).widget()
        self.lb_startl = sg.itemAtPosition(0, 0).widget()
        sg.setColumnMinimumWidth(0, 100)
        sg.setColumnStretch(1, 1)
        s.addLayout(sg)
        s.addSpacing(4)

        self.cb_night = QCheckBox("夜间静默 01:00 ~ 06:00（该时段完全不发请求）")
        self.cb_night.setChecked(True)
        s.addWidget(self.cb_night)

        # 这个开关以前根本不存在 —— 可二次认证的报错却让用户「到运行设置里改成
        # 可见窗口」，用户照着做会发现没这个选项。补上，并且默认勾选。
        self.cb_headed = QCheckBox("显示浏览器窗口（推荐）")
        self.cb_headed.setChecked(True)
        self.cb_headed.setToolTip(
            "勾上：浏览器窗口可见，伪装度最高；遇到验证码或二次验证时你可以直接操作。\n"
            "取消：浏览器在后台跑，桌面更清爽。需要你验证时它仍会自动弹出来。\n\n"
            "两种模式下，窗口都可以随时关掉——程序会自动转到后台继续，不会中断。")
        s.addWidget(self.cb_headed)
        lb_headed = QLabel("窗口可以随时关掉，程序会自动在后台重开，不会中断；"
                           "只有需要你输验证码时才会弹出来。不想让它平时占着桌面就取消勾选。")
        lb_headed.setObjectName("Faint")
        lb_headed.setWordWrap(True)
        s.addWidget(lb_headed)

        self.cb_dry = QCheckBox("试运行（只监听、不真的提交）")
        s.addWidget(self.cb_dry)

        left.addWidget(self.set_card)
        left.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left_inner)
        left_scroll.setMinimumWidth(420)
        root.addWidget(left_scroll, 5)

        # ---------- 右：清单 ----------
        right_host = QWidget()
        right_host.setMinimumWidth(430)
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(16)
        head = QHBoxLayout()
        t = QLabel("课程清单")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.lb_count = QLabel("0 门")
        self.lb_count.setObjectName("Hint")
        head.addWidget(self.lb_count)
        right.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(2, 2, 14, 2)   # 右边留出滚动条位置
        self.list_lay.setSpacing(14)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        right.addWidget(self.scroll, 3)

        # ---------- 右：本学期已选课程（从教务系统读回来，不用学生自己去查） ----------
        # 模式二要选「让位」的课，这里直接点「要退」就行，不用去选课系统里翻。
        sel_head = QHBoxLayout()
        t2 = QLabel("本学期已选课程")
        t2.setObjectName("CardTitle")
        sel_head.addWidget(t2)
        self.lb_sel_count = QLabel("未读取")
        self.lb_sel_count.setObjectName("Hint")
        sel_head.addWidget(self.lb_sel_count)
        sel_head.addStretch(1)
        self.btn_sel_reload = QPushButton("刷新")
        self.btn_sel_reload.setObjectName("Ghost")
        self.btn_sel_reload.setCursor(Qt.PointingHandCursor)
        self.btn_sel_reload.clicked.connect(self.reload_selected.emit)
        sel_head.addWidget(self.btn_sel_reload)
        right.addLayout(sel_head)

        self.sel_scroll = QScrollArea()
        self.sel_scroll.setWidgetResizable(True)
        self.sel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sel_scroll.setFrameShape(QFrame.NoFrame)
        self.sel_scroll.setMinimumHeight(140)
        sel_host = QWidget()
        self.sel_lay = QVBoxLayout(sel_host)
        self.sel_lay.setContentsMargins(2, 2, 14, 2)
        self.sel_lay.setSpacing(8)
        self.sel_lay.addStretch(1)
        self.sel_scroll.setWidget(sel_host)
        right.addWidget(self.sel_scroll, 2)

        self.lb_summary = QLabel("")
        self.lb_summary.setWordWrap(True)
        right.addWidget(self.lb_summary)

        barb = QHBoxLayout()
        b_back = QPushButton("← 返回")
        b_back.clicked.connect(self.back.emit)
        barb.addWidget(b_back)
        barb.addStretch(1)
        self.btn_next = GlowButton("下一步 →")
        self.btn_next.clicked.connect(self.next.emit)
        barb.addWidget(self.btn_next)
        right.addLayout(barb)


        root.addWidget(right_host, 6)

    def headless(self) -> bool:
        """「后台无窗口」= 没勾「显示浏览器窗口」。"""
        return not self.cb_headed.isChecked()

    def set_headless(self, headless: bool):
        self.cb_headed.blockSignals(True)
        self.cb_headed.setChecked(not headless)
        self.cb_headed.blockSignals(False)

    # ------------------------------------------------------------------
    def _on_action_changed(self, i):
        self.lb_action.setText("我要退掉这门课" if i == 1 else "我要抢这门课")
        self.cb_kind.setEnabled(i == 0)

    def _on_add(self):
        e = CourseEntry(
            action="drop" if self.cb_action.currentIndex() == 1 else "grab",
            kind=self.cb_kind.currentData(),
            name=self.ed_name.text().strip(),
            teacher=self.ed_teacher.text().strip(),
            time_text=self.ed_time.text().strip(),
            kch=self.ed_kch.text().strip(),
            kxh=self.ed_kxh.text().strip())
        # 注意：CourseEntry 没有 is_empty()（那是 CourseQuery 的），
        # 以前这里写成一个永远走 else 的三元表达式，纯属误导，直接展开。
        if not any([e.name, e.kch, e.kxh, e.teacher, e.time_text]):
            QMessageBox.information(self, "信息不足",
                                    "至少填一个能定位课程的信息（课程名或课程号最稳妥）。")
            return
        self.add_course.emit(e)
        for w in (self.ed_name, self.ed_teacher, self.ed_time, self.ed_kch, self.ed_kxh):
            w.clear()

    # ------------------------------------------------------------------
    def set_semesters(self, cur: str, opts):
        """填充学期下拉。cur 是当前学期值，opts 是 [(值, 显示名), …]。"""
        self.cb_xnxq.blockSignals(True)
        self.cb_xnxq.clear()
        opts = list(opts or [])
        if not opts and cur:
            opts = [(cur, cur)]
        for v, t in opts:
            self.cb_xnxq.addItem(t, v)
        i = self.cb_xnxq.findData(cur)
        if i < 0 and cur:
            self.cb_xnxq.addItem(cur, cur)
            i = self.cb_xnxq.count() - 1
        if i >= 0:
            self.cb_xnxq.setCurrentIndex(i)
        self.cb_xnxq.blockSignals(False)

    def current_xnxq(self) -> str:
        return self.cb_xnxq.currentData() or ""

    def apply_mode(self, mode: int):
        """按模式显示/隐藏设置项。"""
        need_time = mode in (1, 2)
        for w in (self.dt_start, self.lb_startl, self.sp_lead, self.lb_lead):
            w.setVisible(need_time)
        self.lb_avgl.setVisible(True)
        self.sp_avg.setVisible(True)
        if mode == 3:
            self.sp_avg.setValue(max(3.0, self.sp_avg.value()))
            self.sp_avg.setToolTip("长期监听可以设得很大，比如 3600 秒 = 1 小时")
        else:
            self.sp_avg.setToolTip("临近选课开始时的监听间隔")
        self._refresh_summary()

    def _refresh_summary(self):
        grabs = [e for e in self.entries if e.action == "grab"]
        drops = [e for e in self.entries if e.action == "drop"]
        ok = [e for e in grabs if e.resolved]
        parts = []
        if grabs:
            parts.append(f"抢 {len(grabs)} 门（已校验 {len(ok)} 门）")
        if drops:
            parts.append(f"退 {len(drops)} 门")
        self.lb_count.setText("　".join(parts) or "0 门")
        self.btn_next.setEnabled(bool(grabs) and len(ok) == len(grabs))

        warns = []
        for i, e in enumerate(self.entries):
            r = self.results.get(i)
            if r and r.get("conflicts"):
                warns.append(f"{e.label()} 与 " + "、".join(r["conflicts"]) + " 时间冲突")
            if r and r.get("ambiguous"):
                warns.append(f"{e.label()} 需要补充课序号或上课时间")
        self.lb_summary.setText(("⚠ " + "；".join(warns)) if warns else
                                ("" if not grabs else "所有课程都已校验通过，可以下一步。"))
        self.lb_summary.setStyleSheet(
            f"color:{C['warn'] if warns else C['text_dim']};")

    # ------------------------------------------------------------------
    def set_entries(self, entries, results=None):
        self.entries = entries
        self.results = results or {}
        clear_layout(self.list_lay, keep_tail=1)
        for i, e in enumerate(entries):
            card = CourseCard(i)
            card.remove_requested.connect(self.remove_course.emit)
            r = self.results.get(i)
            rows = r.get("rows") if r else None
            card.set_course(e, rows)
            if r:
                if r.get("ok"):
                    card.set_badge("已定位", "ok")
                    if r.get("conflicts"):
                        card.set_badge("时间冲突", "warn")
                        card.set_state(
                            "⚠ 与已选课程时间冲突：" + "、".join(r["conflicts"]) +
                            "　—— 抢到时会自动退掉它们", "warn")
                    elif r.get("waived_conflicts"):
                        # 本来会冲突，但那门课已列在「要退的课」里 —— 届时要让位，
                        # 所以不算冲突。说出来，用户才知道设置真的生效了。
                        card.set_state(
                            "会和「" + "、".join(r["waived_conflicts"]) +
                            "」撞时间，但它已在要退的课里，界面上不计为冲突。", "info")
                elif r.get("ambiguous"):
                    card.set_badge("需补充", "warn")
                    card.set_state(r.get("reason", ""), "warn")
                else:
                    card.set_badge("未找到", "err")
                    card.set_state(r.get("reason", ""), "err")
            else:
                card.set_badge("待校验", "info")
            self.list_lay.insertWidget(self.list_lay.count() - 1, card)
        self._refresh_summary()

    def set_selected_snapshot(self, rows):
        """把从教务系统读回来的「本学期已选课程」显示出来。

        以前这里只更新一句"已读取 N 门"的提示，列表本身从来不显示 ——
        学生想知道自己选了什么，还得回选课系统里翻。现在直接列出来，
        每门右边一个「要退」，点一下就加进「要退的课」清单（模式二让位用）。
        """
        self.selected_snapshot = rows or []
        n = len(self.selected_snapshot)
        self.lb_sel_count.setText(f"{n} 门" if n else "没读到")
        clear_layout(self.sel_lay, keep_tail=1)
        if not self.selected_snapshot:
            lb = QLabel("还没读到已选课程。点上面的「刷新」从教务系统读一次。")
            lb.setObjectName("Faint")
            lb.setWordWrap(True)
            self.sel_lay.insertWidget(self.sel_lay.count() - 1, lb)
        else:
            for c in self.selected_snapshot:
                self.sel_lay.insertWidget(self.sel_lay.count() - 1, self._sel_row(c))
        self.lb_hint.setText(
            f"已读取你这学期 {n} 门已选课程；要哪门让位，直接点它右边的「要退」。"
            "提示：同名课程有多个课堂时，请补上课序号或上课时间。")

    def _sel_row(self, c):
        """已选课程列表里的一行：[类别] 课程号-课序号 课程名 时间 教师  [要退]"""
        f = QFrame()
        f.setObjectName("Inset")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(12)
        kind = (getattr(c, "kind", "") or "—").strip() or "—"
        bits = [f"<b>{getattr(c, 'name', '')}</b>",
                f"<span style='color:{C['text_faint']}'>［{kind}］"
                f"{getattr(c, 'kch', '')}-{getattr(c, 'kxh', '')}　"
                f"{getattr(c, 'time_text', '')}"]
        teacher = getattr(c, "teacher", "")
        if teacher:
            bits.append(f"　{teacher}")
        bits.append("</span>")
        lb = QLabel("".join(bits))
        lb.setWordWrap(True)
        lay.addWidget(lb, 1)
        b = QPushButton("要退")
        b.setObjectName("Ghost")
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip("把这门课加进「要退的课」清单（模式二让它让位）")
        b.clicked.connect(lambda _=False, cc=c: self.drop_requested.emit(cc))
        lay.addWidget(b)
        return f


# ==========================================================================
# 4. 确认启动
# ==========================================================================
class ConfirmPage(QWidget):
    start = Signal()
    back = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        # 两张卡片的文案是动态的（课程多时会长），窗口一矮同样会被截断
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(52, 28, 52, 30)
        lay.setSpacing(28)
        lay.addWidget(_title("确认并启动", "点开始后请保持程序运行", "步骤 4 / 5"))

        row = QHBoxLayout()
        row.setSpacing(24)

        self.card_plan = Card("将要做什么")
        row.addWidget(self.card_plan, 3)

        self.card_warn = Card("请注意")
        row.addWidget(self.card_warn, 2)
        lay.addLayout(row)

        lay.addStretch(1)
        bar = QHBoxLayout()
        b = QPushButton("← 返回修改")
        b.clicked.connect(self.back.emit)
        bar.addWidget(b)
        bar.addStretch(1)
        self.btn = GlowButton("开始运行")
        self.btn.setMinimumHeight(44)
        self.btn.clicked.connect(self.start.emit)
        bar.addWidget(self.btn)
        lay.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll)


    def refresh(self, cfg, entries):
        clear_layout(self.card_plan.body, keep_tail=0)
        head = QLabel("将要做什么")
        head.setObjectName("CardTitle")
        self.card_plan.body.addWidget(head)

        def add(text, style=""):
            lb = QLabel(text)
            lb.setWordWrap(True)
            if style:
                lb.setStyleSheet(style)
            self.card_plan.body.addWidget(lb)

        start_at = cfg.start_datetime()
        if cfg.mode == 1:
            if start_at:
                add(f"<b>将在 {start_at:%Y-%m-%d %H:%M}</b> 前 "
                    f"{cfg.lead_seconds} 秒开始盯「当前选课阶段」。")
                add("阶段一旦变成<b>正选 / 补退选</b>（先到先得），就立刻按清单自动选课。")
            add(f"监听间隔：平均 {cfg.poll_avg:g} 秒（带随机抖动，不是固定间隔）")
        elif cfg.mode == 2:
            if start_at:
                add(f"<b>将在 {start_at:%Y-%m-%d %H:%M}</b> 到点后立即执行。")
            add("先退掉需要让位的课，再抢目标课程；抢不到会自动把退掉的课选回来。")
            add(f"等待期间拟人化，动手瞬间全速。监听间隔：平均 {cfg.poll_avg:g} 秒")
        else:
            add(f"<b>长期后台监听</b>，平均每 {cfg.poll_avg:g} 秒查一次课余量。")
            add("发现有余量立刻抢；需要让位就先退课。")
            # 这里不再写死「夜间静默」—— 它是可关的，写死在说明里会和
            # 下面那行真实状态自相矛盾（取消勾选后上面还写着夜间静默）。
            add("拟人化：间隔随机长尾、偶尔拉长。")

        if cfg.night_silence:
            add(f"🌙 夜间静默：{cfg.night_silence[0]} ~ {cfg.night_silence[1]} 期间完全不发请求")
        if cfg.dry_run:
            add(f'<span style="color:{C["warn"]}"><b>当前是试运行：只监听，不会真的提交。</b></span>')

        add("<b>课程清单</b>", "margin-top:10px;")
        for e in entries:
            act = "退" if e.action == "drop" else "抢"
            add(f"　[{act}] {e.label()}" + (f"　{e.resolved_teacher}" if e.resolved_teacher else ""))

        while self.card_warn.body.count() > 1:
            it = self.card_warn.body.takeAt(1)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for t, color in [
            ("① 请不要关闭本程序，也不要关闭它打开的浏览器。", C["danger"]),
            ("② 关闭程序 = 停止抢课。可以最小化窗口。", C["text"]),
            ("③ 期间电脑不要休眠（合盖 / 睡眠会让监听暂停）。", C["text"]),
            ("④ 会话过期时程序会自动重新登录，不需要你操作。", C["text_dim"]),
            ("⑤ 一切动作都会写进日志，出问题可一键导出诊断包。", C["text_dim"]),
        ]:
            lb = QLabel(t)
            lb.setWordWrap(True)
            lb.setStyleSheet(f"color:{color};")
            self.card_warn.body.addWidget(lb)
        self.card_warn.body.addStretch(1)


# ==========================================================================
# 5. 运行监控
# ==========================================================================
class MonitorPage(QWidget):
    stop = Signal()
    open_logs = Signal()
    export_diag = Signal()
    restart = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        # 这一页内容最多（状态头 + 四个统计 + 目标课程 + 日志），
        # 窗口一矮就会被压扁或截断，所以和登录页一样套一层滚动区。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(40, 26, 40, 24)
        lay.setSpacing(18)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.dot = Dot(C["primary"], size=11)
        head.addWidget(self.dot)
        self.lb_state = QLabel("准备中")
        self.lb_state.setObjectName("BigState")
        head.addWidget(self.lb_state)
        head.addStretch(1)
        # 停止 / 跑完之后得能回得去。以前这一页没有任何返回入口 ——
        # 点完「停止」就卡在这儿，只能关掉整个程序重开。
        self.btn_back = QPushButton("← 返回设置")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self.restart.emit)
        self.btn_back.setVisible(False)
        head.addWidget(self.btn_back)
        self.btn_logs = QPushButton("打开日志")
        self.btn_logs.clicked.connect(self.open_logs.emit)
        head.addWidget(self.btn_logs)
        self.btn_diag = QPushButton("导出诊断包")
        self.btn_diag.clicked.connect(self.export_diag.emit)
        head.addWidget(self.btn_diag)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.clicked.connect(self.stop.emit)
        head.addWidget(self.btn_stop)
        lay.addLayout(head)

        self.lb_msg = QLabel("")
        self.lb_msg.setObjectName("Hint")
        self.lb_msg.setWordWrap(True)
        lay.addWidget(self.lb_msg)

        stats = QHBoxLayout()
        stats.setSpacing(16)
        self.st_poll = StatBox("已轮询次数", accent=C["primary_soft"])
        self.st_next = StatBox("距下次检查", accent=C["warn_mid"])
        self.st_run = StatBox("已运行", accent=C["primary_mid"])
        self.st_got = StatBox("已抢到", accent=C["primary"])
        for s in (self.st_poll, self.st_next, self.st_run, self.st_got):
            stats.addWidget(s, 1)
        lay.addLayout(stats)
        lay.addSpacing(2)

        self.card_courses = Card("目标课程")
        self.card_courses.body.setSpacing(10)
        lay.addWidget(self.card_courses)

        logc = Card("运行日志")
        logc.body.setSpacing(10)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setMinimumHeight(180)
        logc.body.addWidget(self.log)
        lay.addWidget(logc, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll)



        self._t0 = None
        # 下一轮检查的到期时刻（界面自己走秒用，见 _tick）
        self._next_at = None
        # 计时器不在构造时启动 —— 由 set_state 按「还在跑 / 已停下」开关。
        # 以前是无条件 start(1000)，于是点完「停止」之后界面显示「已停止」，
        # 「已运行」那一栏却还在秒秒往上加。
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._last_status = {}
        # 目标课程卡片的两个输入：清单 + 最近一次轮询结果。
        # 卡片永远是这两者的渲染结果，见 _render_courses。
        self._entries = []
        self._render_courses()

    def reset(self, entries):
        self.log.clear()
        self._t0 = datetime.now()
        self._next_at = None
        self._entries = list(entries)
        self._last_status = {}          # 新的一轮，旧的课余量作废
        # 先落到 00:00:00。计时器一秒才走第一格，不初始化的话
        # 刚点开始的那一秒里「已运行」是一根横杠，看着像没跑起来。
        self.st_run.set("00:00:00", animate=False)
        self.st_next.set("—", animate=False)
        self.set_state("preparing", "准备中", "正在启动浏览器并登录…")
        self._render_courses()

    def _render_courses(self):
        """按「清单 + 最近一次轮询结果」**全量重建**目标课程卡片。

        这里刻意不做增量更新。增量更新得自己维护「哪一行对应清单里的哪一条」，
        一旦对不上就会把两门课的信息拼在一起 —— 实测出现过界面凭空长出
        「退　三年级男生乒乓球」（其实那一条是「退冰球」，文字被换成了乒乓的）。

        全量重建就没有这个问题：`entries` 是唯一的事实来源，
        卡片永远是它的一个渲染结果。几条 QLabel 而已，重建的开销可以忽略。
        """
        # keep_head=1：卡片标题在最前面，要留下的是它（不是最后一条课程）
        clear_layout(self.card_courses.body, keep_head=1)

        # 调度器只轮询「要抢的课」，所以按课程号 / 课序号把结果对回去；
        # 「要退的课」不会被轮询，保持清单原文。
        got = {}
        for r in (self._last_status.get("courses") or []):
            got.setdefault(f"{r.get('kch', '')}|{r.get('kxh', '')}", r)

        for e in self._entries:
            prefix = "退　" if e.action == "drop" else "抢　"
            r = got.get(f"{e.kch or ''}|{e.kxh or ''}") if e.action != "drop" else None
            lb = QLabel(self._course_line(prefix, e, r))
            lb.setWordWrap(True)
            if r is not None:
                kyl = r.get("kyl", -1)
                if kyl is not None and kyl > 0:
                    lb.setStyleSheet(f"color:{C['primary']};font-weight:700;")
            self.card_courses.body.addWidget(lb)

    @staticmethod
    def _course_line(prefix: str, e, r) -> str:
        """一行目标课程的文字：清单里的原文，有轮询结果就补上课余量。"""
        if r is None:
            return prefix + e.label()
        kyl = r.get("kyl", -1)
        if kyl is None or kyl < 0:
            return f"{prefix}{e.label()}　　（没查到）"
        mark = "有余量" if kyl > 0 else "暂无余量"
        return f"{prefix}{e.label()}　　课余量 {kyl}　{mark}"

    def append_log(self, text, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        color = {"ERROR": C["danger_bright"], "WARN": "#E8C48A",
                 "DEBUG": C["log_dim"]}.get(level, C["log_text"])
        safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        self.log.appendHtml(
            f'<span style="color:{C["log_dim"]}">{ts}</span> '
            f'<span style="color:{color}">{safe}</span>')


    def _tick(self):
        if self._t0:
            secs = int((datetime.now() - self._t0).total_seconds())
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self.st_run.set(f"{h:02d}:{m:02d}:{s:02d}", animate=False)

        # 「距下次检查」在界面上自己走秒。
        # 调度器一个周期只推一次状态，600 秒的间隔要是照搬那个数字，
        # 屏幕上会一直停在同一个值，看不出到底在不在倒计时。
        if self._next_at is None:
            self.st_next.set("—", animate=False)
        else:
            left = max(0.0, (self._next_at - datetime.now()).total_seconds())
            self.st_next.set(f"{left:.0f}s", animate=False)

    # 「还在跑」的几个状态：这时不给返回入口，避免用户在抢课中途切走。
    # stopping 也算在跑 —— 正在收尾时不该跳出「返回设置」。
    RUNNING_STATES = ("preparing", "waiting", "monitoring", "acting", "stopping")

    def set_state(self, state, title, message=""):
        colors = {
            "preparing": C["primary"], "waiting": C["warn"],
            "monitoring": C["accent"], "acting": C["primary"],
            "success": C["accent"], "stopped": C["text_faint"],
            "stopping": C["text_faint"], "error": C["danger"],
        }
        self.dot.set_color(colors.get(state, C["text_faint"]))
        # 只有「真的在跑」的状态才让光晕呼吸；静止状态不分散注意力
        running = state in self.RUNNING_STATES
        self.dot.set_breathing(state in ("monitoring", "acting"))
        self.lb_state.setText(title)
        if message:
            self.lb_msg.setText(message)

        # 停下来之后才给「返回设置」；跑着的时候只留「停止」
        self.btn_back.setVisible(not running)
        self.btn_stop.setVisible(running)
        self.btn_stop.setEnabled(state != "stopping")

        # 「已运行」只在跑的时候走字；停下就冻结在最后一刻，不再累加
        if running:
            if not self._timer.isActive():
                self._timer.start(1000)
        else:
            self._timer.stop()
            self._t0 = None
            self._next_at = None
            # 立刻刷一次：计时器已经停了，不主动刷的话「距下次检查」会
            # 一直停在最后一个数字上，看起来像还在倒计时。
            self._tick()

    def update_status(self, s: dict):
        self._last_status = s
        state = s.get("state", "idle")
        titles = {
            "preparing": "准备中", "waiting": "等待开始",
            "monitoring": "监听中", "acting": "正在抢课",
            "success": "已完成", "stopped": "已停止", "error": "出错了",
        }
        self.set_state(state, titles.get(state, state), s.get("message", ""))
        self.st_poll.set(s.get("polls", 0))
        # 记下「下一轮什么时候到」，交给 _tick 逐秒刷新成倒计时
        nxt = s.get("next_poll_in") or 0
        self._next_at = (datetime.now() + timedelta(seconds=float(nxt))) if nxt else None
        self._tick()
        got = s.get("success") or []
        self.st_got.set(len(got))
        # 目标课程卡片由「清单 + 这份状态」整体重画，不做增量更新
        self._render_courses()
