# -*- coding: utf-8 -*-
"""五个页面：登录 → 模式 → 预定课程 → 确认 → 监控。"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal, QDateTime, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QCheckBox, QComboBox, QListWidget,
                               QListWidgetItem, QScrollArea, QFrame, QMessageBox,
                               QDateTimeEdit, QDoubleSpinBox, QPlainTextEdit,
                               QSizePolicy, QGridLayout, QSpinBox, QProgressBar)

from .theme import C
from .widgets import Card, CourseCard, ModeCard, StatBox, Dot, clear_layout
from ..browser import COURSE_KINDS
from ..config import CourseEntry


def _title(text, sub=""):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    t = QLabel(text)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


# ==========================================================================
# 1. 登录
# ==========================================================================
class LoginPage(QWidget):
    submit = Signal(str, str, bool, bool)     # user, pwd, remember, trust

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 36, 48, 36)
        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        card = Card()
        card.setFixedWidth(460)
        card.body.addWidget(_title("登录", "使用学校统一身份认证账号"))

        card.body.addSpacing(6)
        card.body.addWidget(self._lab("学号"))
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("学号 / 工作证号")
        card.body.addWidget(self.ed_user)

        card.body.addSpacing(8)
        card.body.addWidget(self._lab("密码"))
        self.ed_pwd = QLineEdit()
        self.ed_pwd.setEchoMode(QLineEdit.Password)
        self.ed_pwd.setPlaceholderText("统一身份认证密码")
        self.ed_pwd.returnPressed.connect(self._emit)
        card.body.addWidget(self.ed_pwd)

        self.cb_remember = QCheckBox("记住密码（用 Windows 加密保存在本机，仅当前账户可解）")
        self.cb_remember.setChecked(True)
        card.body.addWidget(self.cb_remember)

        self.cb_trust = QCheckBox("信任此浏览器（会话过期后免密码重登）")
        self.cb_trust.setChecked(True)
        card.body.addWidget(self.cb_trust)

        card.body.addSpacing(10)
        self.btn = QPushButton("登 录")
        self.btn.setObjectName("Primary")
        self.btn.setMinimumHeight(42)
        self.btn.clicked.connect(self._emit)
        card.body.addWidget(self.btn)

        self.lb_status = QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setObjectName("Hint")
        card.body.addWidget(self.lb_status)

        # 登录进度：登录常要几十秒，必须让用户看得到它在动
        self.progress_box = QFrame()
        self.progress_box.setObjectName("CardFlat")
        self.progress_box.setVisible(False)
        pb = QVBoxLayout(self.progress_box)
        pb.setContentsMargins(12, 10, 12, 10)
        pb.setSpacing(5)
        prow = QHBoxLayout()
        self.lb_prog_step = QLabel("")
        self.lb_prog_step.setWordWrap(True)
        prow.addWidget(self.lb_prog_step, 1)
        self.lb_prog_time = QLabel("0s")
        self.lb_prog_time.setStyleSheet(f"color:{C['primary']};font-weight:600;")
        prow.addWidget(self.lb_prog_time)
        pb.addLayout(prow)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)          # 不确定进度，走马灯
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        pb.addWidget(self.bar)
        self.lb_prog_tip = QLabel("登录通常 10~40 秒。请勿关闭程序；"
                                 "若弹出浏览器窗口要求二次验证，请在那里完成。")
        self.lb_prog_tip.setObjectName("Faint")
        self.lb_prog_tip.setWordWrap(True)
        pb.addWidget(self.lb_prog_tip)
        card.body.addWidget(self.progress_box)

        card.body.addSpacing(2)
        tip = QLabel("账号密码只加密保存在本机（Windows DPAPI），换用户或换电脑都解不开；"
                     "卸载程序时不会删除。")
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        card.body.addWidget(tip)

        self.btn_forget = QPushButton("清除本机已保存的账号密码")
        self.btn_forget.setObjectName("Ghost")
        self.btn_forget.setCursor(Qt.PointingHandCursor)
        card.body.addWidget(self.btn_forget)

        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    @staticmethod
    def _lab(t):
        lb = QLabel(t)
        lb.setStyleSheet("font-weight:600;")
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
        self.lb_prog_step.setText("正在准备…")
        self.set_elapsed(0)

    def set_progress(self, text: str):
        self.progress_box.setVisible(True)
        self.lb_prog_step.setText(text)

    def set_elapsed(self, seconds: float):
        self.lb_prog_time.setText(f"{seconds:.0f}s")

    def end_progress(self):
        self.progress_box.setVisible(False)

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(14)
        outer.addWidget(_title("选择运行模式", "根据你现在处在选课的哪个阶段来选"))

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
        grid.setSpacing(16)
        for idx, title, badge, desc, bullets in specs:
            c = ModeCard(idx, title, badge, desc, bullets)
            c.clicked.connect(self.chosen.emit)
            grid.addWidget(c, 1)
            self.cards.append(c)
        outer.addLayout(grid)
        outer.addStretch(1)

        bar = QHBoxLayout()
        b = QPushButton("← 返回")
        b.setObjectName("Ghost")
        b.clicked.connect(self.back.emit)
        bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)


# ==========================================================================
# 3. 预定课程
# ==========================================================================
class CoursesPage(QWidget):
    validate = Signal(int, object, object)     # index, entry, selected_snapshot
    reload_selected = Signal()
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
        root.setContentsMargins(40, 28, 40, 28)
        root.setSpacing(18)

        # ---------- 左：录入 ----------
        # 窗口不高时这里会放不下（会被 Qt 压扁），所以套一层滚动区
        left_inner = QWidget()
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 12, 0)
        left.setSpacing(12)
        left.addWidget(_title("预定课程", "信息不用填全，能唯一定位到一门课就行"))

        self.form_card = Card()
        f = self.form_card.body
        self.lb_action = QLabel("我要抢这门课")
        f.addWidget(self.lb_action)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 76)
        grid.setColumnStretch(1, 1)          # 输入框占满剩余宽度
        self.cb_action = QComboBox()
        self.cb_action.addItems(["要抢的课", "要退的课"])
        self.cb_action.currentIndexChanged.connect(self._on_action_changed)
        grid.addWidget(QLabel("用途"), 0, 0)
        grid.addWidget(self.cb_action, 0, 1)

        self.cb_kind = QComboBox()
        for k, v in COURSE_KINDS.items():
            self.cb_kind.addItem(v["name"], k)
        self.cb_kind.setCurrentIndex(list(COURSE_KINDS).index("ty"))
        grid.addWidget(QLabel("课程种类"), 1, 0)
        grid.addWidget(self.cb_kind, 1, 1)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如 大学物理（可只填这一项）")
        grid.addWidget(QLabel("课程名"), 2, 0)
        grid.addWidget(self.ed_name, 2, 1)

        self.ed_teacher = QLineEdit()
        self.ed_teacher.setPlaceholderText("选填")
        grid.addWidget(QLabel("任课教师"), 3, 0)
        grid.addWidget(self.ed_teacher, 3, 1)

        self.ed_time = QLineEdit()
        self.ed_time.setPlaceholderText("选填，如 4-1")
        grid.addWidget(QLabel("上课时间"), 4, 0)
        grid.addWidget(self.ed_time, 4, 1)

        self.ed_kch = QLineEdit()
        self.ed_kch.setPlaceholderText("选填，如 10421055")
        grid.addWidget(QLabel("课程号"), 5, 0)
        grid.addWidget(self.ed_kch, 5, 1)

        self.ed_kxh = QLineEdit()
        self.ed_kxh.setPlaceholderText("选填，如 2")
        grid.addWidget(QLabel("课序号"), 6, 0)
        grid.addWidget(self.ed_kxh, 6, 1)
        f.addLayout(grid)

        f.addSpacing(4)
        self.lb_hint = QLabel("提示：同名课程有多个课堂时，请补上课序号或上课时间。")
        self.lb_hint.setObjectName("Faint")
        self.lb_hint.setWordWrap(True)
        f.addWidget(self.lb_hint)

        rowb = QHBoxLayout()
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
        sg.setHorizontalSpacing(10)
        sg.setVerticalSpacing(8)

        self.dt_start = QDateTimeEdit()
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        sg.addWidget(QLabel("开始选课时间"), 0, 0)
        sg.addWidget(self.dt_start, 0, 1)
        self.row_start = (0,)

        self.sp_lead = QSpinBox()
        self.sp_lead.setRange(0, 3600)
        self.sp_lead.setValue(60)
        self.sp_lead.setSuffix(" 秒")
        sg.addWidget(QLabel("提前盯梢"), 1, 0)
        sg.addWidget(self.sp_lead, 1, 1)

        self.sp_avg = QDoubleSpinBox()
        self.sp_avg.setRange(0.5, 3600)
        self.sp_avg.setValue(3.0)
        self.sp_avg.setSuffix(" 秒")
        sg.addWidget(QLabel("平均监听间隔"), 2, 0)
        sg.addWidget(self.sp_avg, 2, 1)

        # 学期：登录后自动识别并填充，也可手动改（换学期、跨学期提前预定都能用）
        self.cb_xnxq = QComboBox()
        self.cb_xnxq.setToolTip("登录后自动识别当前学期；也可以手动切换")
        sg.addWidget(QLabel("学期"), 3, 0)
        sg.addWidget(self.cb_xnxq, 3, 1)
        self.lb_xnxql = sg.itemAtPosition(3, 0).widget()

        self.lb_lead = sg.itemAtPosition(1, 0).widget()
        self.lb_avgl = sg.itemAtPosition(2, 0).widget()
        self.lb_startl = sg.itemAtPosition(0, 0).widget()
        s.addLayout(sg)

        self.cb_night = QCheckBox("夜间静默 01:00 ~ 06:00（该时段完全不发请求）")
        self.cb_night.setChecked(True)
        s.addWidget(self.cb_night)

        self.cb_dry = QCheckBox("试运行（只监听、不真的提交）")
        s.addWidget(self.cb_dry)

        left.addWidget(self.set_card)
        left.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left_inner)
        left_scroll.setMinimumWidth(400)
        root.addWidget(left_scroll, 5)

        # ---------- 右：清单 ----------
        right_host = QWidget()
        right_host.setMinimumWidth(430)
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
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
        self.list_lay.setContentsMargins(2, 2, 12, 2)   # 右边留出滚动条位置
        self.list_lay.setSpacing(10)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        right.addWidget(self.scroll, 1)

        self.lb_summary = QLabel("")
        self.lb_summary.setWordWrap(True)
        right.addWidget(self.lb_summary)

        barb = QHBoxLayout()
        b_back = QPushButton("← 返回")
        b_back.setObjectName("Ghost")
        b_back.clicked.connect(self.back.emit)
        barb.addWidget(b_back)
        barb.addStretch(1)
        self.btn_next = QPushButton("下一步 →")
        self.btn_next.setObjectName("Primary")
        self.btn_next.clicked.connect(self.next.emit)
        barb.addWidget(self.btn_next)
        right.addLayout(barb)

        root.addWidget(right_host, 6)

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
        if e.is_empty() if hasattr(e, "is_empty") else not any(
                [e.name, e.kch, e.kxh, e.teacher, e.time_text]):
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
                        card.set_state("⚠ 与已选课程时间冲突：" + "、".join(r["conflicts"]),
                                       "warn")
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
        self.selected_snapshot = rows or []
        n = len(self.selected_snapshot)
        self.lb_hint.setText(
            f"已读取你这学期 {n} 门已选课程。"
            "提示：同名课程有多个课堂时，请补上课序号或上课时间。")


# ==========================================================================
# 4. 确认启动
# ==========================================================================
class ConfirmPage(QWidget):
    start = Signal()
    back = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(16)
        outer.addWidget(_title("确认并启动", "点开始后请保持程序运行"))

        row = QHBoxLayout()
        row.setSpacing(16)

        self.card_plan = Card("将要做什么")
        row.addWidget(self.card_plan, 3)

        self.card_warn = Card("请注意")
        row.addWidget(self.card_warn, 2)
        outer.addLayout(row)

        outer.addStretch(1)
        bar = QHBoxLayout()
        b = QPushButton("← 返回修改")
        b.setObjectName("Ghost")
        b.clicked.connect(self.back.emit)
        bar.addWidget(b)
        bar.addStretch(1)
        self.btn = QPushButton("开始运行")
        self.btn.setObjectName("Primary")
        self.btn.setMinimumHeight(44)
        self.btn.clicked.connect(self.start.emit)
        bar.addWidget(self.btn)
        outer.addLayout(bar)

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
            add("拟人化：间隔随机长尾、偶尔拉长、夜间静默。")

        if cfg.night_silence:
            add(f"🌙 夜间静默：{cfg.night_silence[0]} ~ {cfg.night_silence[1]} 期间完全不发请求")
        if cfg.dry_run:
            add('<span style="color:#D9822B"><b>当前是试运行：只监听，不会真的提交。</b></span>')

        add("<b>课程清单</b>", "margin-top:6px;")
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 26, 40, 26)
        outer.setSpacing(14)

        head = QHBoxLayout()
        self.dot = Dot(C["primary"])
        head.addWidget(self.dot)
        self.lb_state = QLabel("准备中")
        self.lb_state.setStyleSheet("font-size:20px;font-weight:600;")
        head.addWidget(self.lb_state)
        head.addStretch(1)
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
        outer.addLayout(head)

        self.lb_msg = QLabel("")
        self.lb_msg.setObjectName("Hint")
        self.lb_msg.setWordWrap(True)
        outer.addWidget(self.lb_msg)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.st_poll = StatBox("已轮询次数")
        self.st_next = StatBox("距下次检查")
        self.st_run = StatBox("已运行")
        self.st_got = StatBox("已抢到")
        for s in (self.st_poll, self.st_next, self.st_run, self.st_got):
            stats.addWidget(s, 1)
        outer.addLayout(stats)

        self.card_courses = Card("目标课程")
        outer.addWidget(self.card_courses)

        logc = Card("运行日志")
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setMinimumHeight(220)
        logc.body.addWidget(self.log)
        outer.addWidget(logc, 1)

        self._t0 = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._last_status = {}

    def reset(self, entries):
        self.log.clear()
        self._t0 = datetime.now()
        self._rows = {}
        self.set_state("preparing", "准备中", "正在启动浏览器并登录…")
        clear_layout(self.card_courses.body, keep_tail=1)
        self.course_labels = []
        for e in entries:
            lb = QLabel("　" + ("[退] " if e.action == "drop" else "[抢] ") + e.label())
            lb.setWordWrap(True)
            self.card_courses.body.addWidget(lb)
            self.course_labels.append(lb)

    def append_log(self, text, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        color = {"ERROR": "#FF8A80", "WARN": "#FFD180",
                 "DEBUG": "#8A93A0"}.get(level, "#D6DAE1")
        safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        self.log.appendHtml(
            f'<span style="color:#6E7681">{ts}</span> '
            f'<span style="color:{color}">{safe}</span>')

    def _tick(self):
        if self._t0:
            secs = int((datetime.now() - self._t0).total_seconds())
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self.st_run.set(f"{h:02d}:{m:02d}:{s:02d}")

    def set_state(self, state, title, message=""):
        colors = {
            "preparing": C["primary"], "waiting": C["warn"],
            "monitoring": C["accent"], "acting": C["primary"],
            "success": C["accent"], "stopped": C["text_faint"],
            "error": C["danger"],
        }
        self.dot.set_color(colors.get(state, C["text_faint"]))
        self.lb_state.setText(title)
        if message:
            self.lb_msg.setText(message)

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
        nxt = s.get("next_poll_in") or 0
        self.st_next.set(f"{nxt:.1f}s" if nxt else "—")
        got = s.get("success") or []
        self.st_got.set(len(got))
        rows = s.get("courses") or []
        for i, lb in enumerate(getattr(self, "course_labels", [])):
            if i < len(rows):
                r = rows[i]
                kyl = r.get("kyl", -1)
                txt = r.get("label", "")
                if kyl is None or kyl < 0:
                    lb.setText(f"　{txt}　（没查到）")
                else:
                    mark = "✅ 有余量！" if kyl > 0 else "暂无余量"
                    lb.setText(f"　{txt}　课余量 {kyl}　{mark}")
