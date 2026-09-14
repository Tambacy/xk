# -*- coding: utf-8 -*-
"""主窗口：串起五个页面。"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QStackedWidget, QMessageBox, QLabel, QFrame,
                               QFileDialog, QApplication, QPushButton)

from .core import BrowserCore
from .pages import LoginPage, ModePage, CoursesPage, ConfirmPage, MonitorPage
from .theme import C, stylesheet
from .widgets import StepBar
from ..config import AppConfig, CourseEntry, Paths, APP_DISPLAY_NAME, APP_VERSION
from ..secretstore import SecretStore, redactor
from ..logging_setup import setup_logging, get_logger, export_diagnostics

log = get_logger("gui")


class MainWindow(QMainWindow):
    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        self.cfg, note = AppConfig.load(paths.config)
        self.store = SecretStore(paths.root)
        self.entries: list[CourseEntry] = self.cfg.courses_as_entries()
        self.results: dict[int, dict] = {}
        self.core: BrowserCore | None = None

        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.resize(1120, 760)
        self.setMinimumSize(940, 640)          # 小屏也能用

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 顶部标题 + 步骤条 ----
        header = QFrame()
        header.setStyleSheet(f"background:{C['card']};border-bottom:1px solid {C['border']};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(28, 14, 28, 12)
        hl.setSpacing(8)
        top = QHBoxLayout()
        logo = QLabel("学校选课助手")
        logo.setStyleSheet(f"font-size:17px;font-weight:700;color:{C['primary']};")
        top.addWidget(logo)
        top.addStretch(1)
        self.btn_help = QPushButton("使用说明")
        self.btn_help.setObjectName("Ghost")
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.clicked.connect(self.on_help)
        top.addWidget(self.btn_help)
        self.lb_user = QLabel("")
        self.lb_user.setObjectName("Hint")
        top.addWidget(self.lb_user)
        hl.addLayout(top)
        self.steps = StepBar()
        hl.addWidget(self.steps)
        lay.addWidget(header)

        # ---- 页面 ----
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.page_login = LoginPage(self.cfg)
        self.page_mode = ModePage()
        self.page_courses = CoursesPage(self.cfg)
        self.page_confirm = ConfirmPage(self.cfg)
        self.page_monitor = MonitorPage(self.cfg)
        for p in (self.page_login, self.page_mode, self.page_courses,
                  self.page_confirm, self.page_monitor):
            self.stack.addWidget(p)

        self._wire()
        self.page_login.set_config(self.cfg)
        if self.cfg.user:
            self.lb_user.setText(f"学号 {self.cfg.user}")
        self.goto(0)

        # 已经有保存的凭据就自动填上
        d = self.store.load()
        if d:
            if d.get("user"):
                self.page_login.ed_user.setText(d["user"])
            if d.get("pass"):
                self.page_login.ed_pwd.setText(d["pass"])
        if note and note != "配置已载入":
            self.page_login.set_status(note, "warn")

    # ------------------------------------------------------------------
    def _wire(self):
        self.page_login.submit.connect(self.on_login)
        self.page_mode.chosen.connect(self.on_mode)
        self.page_mode.back.connect(lambda: self.goto(0))
        self.page_login.btn_forget.clicked.connect(self.on_forget)
        self.page_courses.add_course.connect(self.on_add_course)
        self.page_courses.remove_course.connect(self.on_remove_course)
        self.page_courses.validate.connect(self.on_validate)
        self.page_courses.reload_selected.connect(self.on_reload_selected)
        self.page_courses.back.connect(lambda: self.goto(1))
        self.page_courses.next.connect(lambda: self.goto(3))
        self.page_confirm.back.connect(lambda: self.goto(2))
        self.page_confirm.start.connect(self.on_start)
        self.page_monitor.stop.connect(self.on_stop)
        self.page_monitor.open_logs.connect(self.on_open_logs)
        self.page_monitor.export_diag.connect(self.on_export_diag)

    def goto(self, index: int):
        self.stack.setCurrentIndex(index)
        self.steps.set_current(index)
        if index == 2:
            self.page_courses.apply_mode(self.cfg.mode)
            self.page_courses.set_entries(self.entries, self.results)
        if index == 3:
            self.page_confirm.refresh(self.cfg, self.entries)

    # ------------------------------------------------------------------
    def on_login(self, user, pwd, remember, trust):
        self.cfg.user = user
        self.cfg.remember_password = remember
        self.cfg.single_login = trust
        # 密码和学号都登记进脱敏表：日志、诊断包里永远不会出现原值
        redactor.add(pwd, user)
        self.lb_user.setText(f"学号 {user[:3]}****{user[-2:]}" if len(user) > 5
                             else f"学号 {user}")

        # 登录动辄几十秒，必须让用户看得到在动
        self.page_login.begin_progress()
        self._login_t0 = datetime.now()
        if getattr(self, "_login_timer", None) is None:
            self._login_timer = QTimer(self)
            self._login_timer.timeout.connect(self._tick_login)
        self._login_timer.start(500)

        if self.core is None:
            self.core = BrowserCore(self.cfg, self.paths)
            self.core.logged_in.connect(self.on_logged_in)
            self.core.login_progress.connect(self.on_login_progress)
            self.core.log_line.connect(self.page_monitor.append_log)
            self.core.status_changed.connect(self.page_monitor.update_status)
            self.core.validated.connect(self.on_validated)
            self.core.selected_loaded.connect(self.on_selected_loaded)
            self.core.semesters_loaded.connect(self.on_semesters_loaded)
            self.core.finished.connect(self.on_core_finished)
            self.core.start()
        self.core.do_login(user, pwd)

    def on_login_progress(self, text: str):
        self.page_login.set_progress(text)

    def _tick_login(self):
        t0 = getattr(self, "_login_t0", None)
        if t0 is None:
            return
        self.page_login.set_elapsed((datetime.now() - t0).total_seconds())

    def on_logged_in(self, ok, msg):
        try:
            self._login_timer.stop()
        except Exception:
            pass
        self._login_t0 = None
        self.page_login.on_done(ok, msg)
        if not ok:
            return
        # 保存 / 清除凭据
        if self.cfg.remember_password:
            saved, info = self.store.save(self.cfg.user, self.page_login.ed_pwd.text(),
                                          remember=True)
            if not saved:
                self.page_login.set_status(f"登录成功，但凭据未保存：{info}", "warn")
            log.info("凭据保存结果：%s", info)
        else:
            self.store.clear()
        self.save_config()
        self.core.request_selected()
        QTimer.singleShot(300, lambda: self.goto(1))

    def on_mode(self, mode: int):
        self.cfg.mode = mode
        self.save_config()
        # 模式一/二必须有开始时间
        if mode in (1, 2):
            self.page_courses.dt_start.setVisible(True)
        self.goto(2)
        if self.core:
            self.core.request_selected()

    def on_reload_selected(self):
        if self.core:
            self.core.request_selected()

    def on_selected_loaded(self, rows):
        self.page_courses.set_selected_snapshot(rows)

    def on_semesters_loaded(self, current: str, options):
        self.page_courses.set_semesters(current or self.cfg.xnxq, options)
        if current:
            self.cfg.xnxq = current
            self.save_config()

    def on_forget(self):
        if QMessageBox.question(
                self, "清除已保存的账号密码",
                "将从本机删除已加密保存的账号密码。\n"
                "下次打开需要重新输入（浏览器里的登录态也会一起清掉）。\n\n确定吗？"
        ) != QMessageBox.Yes:
            return
        ok = self.store.clear()
        # 浏览器 profile 里存着登录态，一并清干净
        try:
            import shutil
            if self.paths.profile.exists():
                shutil.rmtree(self.paths.profile, ignore_errors=True)
        except Exception:
            pass
        self.page_login.ed_pwd.clear()
        self.cfg.user = ""
        self.cfg.courses = []
        self.entries = []
        self.results = {}
        self.save_config()
        self.lb_user.setText("")
        self.page_login.set_status(
            "已清除本机保存的账号密码。" if ok else "清除时出了点问题，可手动删除数据目录。",
            "ok" if ok else "warn")
        log.info("用户清除了本机保存的凭据。")

    # ------------------------------------------------------------------
    def on_add_course(self, entry: CourseEntry):
        self.entries.append(entry)
        self.results[len(self.entries) - 1] = None
        self.cfg.set_courses(self.entries)
        self.save_config()
        self.page_courses.set_entries(self.entries, self.results)
        idx = len(self.entries) - 1
        snap = self.page_courses.selected_snapshot
        if self.core:
            self.core.do_validate(idx, entry, snap)

    def on_remove_course(self, index: int):
        if 0 <= index < len(self.entries):
            self.entries.pop(index)
            self.results = {i: v for i, v in enumerate(self.results.values()) if v is not None}
            self.results = {}
            self.cfg.set_courses(self.entries)
            self.save_config()
            self.page_courses.set_entries(self.entries, self.results)
            for i, e in enumerate(self.entries):
                if self.core:
                    self.core.do_validate(i, e, self.page_courses.selected_snapshot)

    def on_validate(self, index: int, entry, snapshot):
        if self.core:
            self.core.do_validate(index, entry, snapshot)

    def on_validated(self, index: int, result: dict):
        self.results[index] = result
        self.cfg.set_courses(self.entries)
        self.save_config()
        self.page_courses.set_entries(self.entries, self.results)
        if result.get("ok"):
            log.info("课程校验通过：%s", self.entries[index].label())
        else:
            log.warning("课程校验未通过：%s -> %s",
                        self.entries[index].label(), result.get("reason"))

    # ------------------------------------------------------------------
    def on_start(self):
        cfg = self.cfg
        cfg.poll_avg = self.page_courses.sp_avg.value()
        cfg.lead_seconds = self.page_courses.sp_lead.value()
        cfg.dry_run = self.page_courses.cb_dry.isChecked()
        cfg.xnxq = self.page_courses.current_xnxq() or cfg.xnxq
        cfg.night_silence = (["01:00", "06:00"]
                             if self.page_courses.cb_night.isChecked() else [])
        if cfg.mode in (1, 2):
            dt = self.page_courses.dt_start.dateTime().toPython()
            cfg.start_time = dt.strftime("%Y-%m-%d %H:%M")
        else:
            cfg.start_time = ""
        cfg.set_courses(self.entries)
        self.save_config()

        self.page_monitor.reset(self.entries)
        self.goto(4)
        log.info("启动任务：模式=%s 课程=%d 门 间隔=%ss 试运行=%s",
                 cfg.mode, len(self.entries), cfg.poll_avg, cfg.dry_run)
        if self.core:
            self.core.do_start()

    def on_stop(self):
        if QMessageBox.question(self, "确认停止",
                                "确定要停止吗？停止后就不会再帮你盯着了。") == QMessageBox.Yes:
            if self.core:
                self.core.do_stop()
            self.page_monitor.set_state("stopped", "正在停止…", "等待当前动作结束")

    def on_core_finished(self, reason: str):
        titles = {"success": "已完成", "stopped": "已停止",
                  "error": "出错了", "done": "已结束"}
        self.page_monitor.set_state(reason if reason in titles else "stopped",
                                    titles.get(reason, "已结束"))
        if reason == "success":
            QMessageBox.information(self, "完成", "目标课程已抢到，可以关闭程序了。")

    # ------------------------------------------------------------------
    def on_open_logs(self):
        try:
            os.startfile(str(self.paths.logs))     # noqa: S606
        except Exception as e:
            QMessageBox.warning(self, "打不开", f"无法打开日志目录：{e}\n{self.paths.logs}")

    def on_help(self):
        """打开随包的使用说明。"""
        from ..runtime import find_doc
        p = find_doc()
        if not p:
            QMessageBox.information(
                self, "使用说明",
                "没找到随包的使用说明文件。\n"
                f"数据目录：{self.paths.root}")
            return
        try:
            os.startfile(p)                        # noqa: S606
        except Exception as e:
            QMessageBox.warning(self, "打不开", f"无法打开使用说明：{e}\n{p}")

    def on_export_diag(self):
        default = str(self.paths.diagnostics /
                      f"诊断包-{datetime.now():%Y%m%d-%H%M%S}.zip")
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", default, "压缩包 (*.zip)")
        if not path:
            return
        try:
            snap = self.cfg.to_dict()
            snap.pop("courses", None)
            snap.pop("user", None)          # 学号不写进诊断包
            out = export_diagnostics(path, self.paths.logs, config_snapshot=snap,
                                     extra_text=f"运行模式={self.cfg.mode} 课程数={len(self.entries)}")
            QMessageBox.information(self, "已导出",
                                   f"诊断包已保存到：\n{out}\n\n"
                                   "内含日志与环境信息，已自动脱敏，不含账号密码。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ------------------------------------------------------------------
    def save_config(self):
        ok, msg = self.cfg.save(self.paths.config)
        if not ok:
            log.error(msg)

    def closeEvent(self, e):
        running = self.core is not None and self.core.isRunning()
        if running and self.stack.currentIndex() == 4:
            r = QMessageBox.question(
                self, "还在运行中",
                "抢课任务正在运行，关闭程序会停止抢课。\n确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
        self.save_config()
        if self.core:
            try:
                self.core.shutdown()
                self.core.wait(8000)
            except Exception:
                pass
        log.info("程序退出。")
        e.accept()
