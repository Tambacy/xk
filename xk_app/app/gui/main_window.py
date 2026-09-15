# -*- coding: utf-8 -*-
"""主窗口：串起五个页面。"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QEvent
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QStackedWidget, QMessageBox, QLabel, QFrame,
                               QFileDialog, QApplication, QPushButton)

from .core import BrowserCore
from .pages import LoginPage, ModePage, CoursesPage, ConfirmPage, MonitorPage
from .theme import stylesheet
from . import motion
from .motion import ParticleOverlay, RevealCurtain
from .widgets import HeroBand, LogoMark
from ..config import AppConfig, CourseEntry, Paths, APP_DISPLAY_NAME, APP_VERSION
from ..browser import COURSE_KINDS
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
        self.curtain: RevealCurtain | None = None
        self.particles: ParticleOverlay | None = None

        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.resize(1120, 760)
        self.setMinimumSize(940, 640)          # 小屏也能用

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 顶部：深色 Hero 带（玻璃导航胶囊 + 步骤导轨）----
        # 参考站的 nav 是一条浮在深色影像上的玻璃胶囊，不是通栏白条。
        # 这里给桌面应用补上等价的「深色底」：一幅程序生成的夜空（见 backdrop.py）。
        # 登录页不显示这条带子 —— 那一页整屏都是深色品牌分栏，见 pages.LoginPage。
        self.band = HeroBand()
        nr = self.band.nav_row

        nr.addWidget(LogoMark(32, "清", dark=True))

        logo = QLabel(APP_DISPLAY_NAME)
        logo.setObjectName("Wordmark")
        nr.addWidget(logo)

        nr.addSpacing(8)
        sep = QLabel()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet("background: rgba(255, 255, 255, 0.16);")
        nr.addWidget(sep)
        nr.addSpacing(2)

        self.btn_help = QPushButton("使用说明")
        self.btn_help.setObjectName("NavGhost")
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.clicked.connect(self.on_help)
        nr.addWidget(self.btn_help)

        self.lb_user = QLabel("")
        self.lb_user.setObjectName("NavMeta")
        nr.addWidget(self.lb_user)

        self.steps = self.band.rail
        lay.addWidget(self.band)

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
        self.page_courses.set_headless(self.cfg.headless)
        if self.cfg.user:
            self._set_user_label(self.cfg.user)

        # 粒子层：盖在内容之上，但不吃鼠标事件（否则按钮全被挡住）
        self.particles = ParticleOverlay(root)
        self.particles.setGeometry(root.rect())
        self.particles.raise_()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.goto(0)

    # ------------------------------------------------------------------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.particles is not None:
            self.particles.setGeometry(self.centralWidget().rect())

    def eventFilter(self, obj, ev):
        """按钮悬停 / 按下时溅一小簇粒子。

        用应用级事件过滤器而不是逐个按钮 connect —— 页面里的按钮是动态
        重建的，逐个挂钩会漏。
        """
        if self.particles is not None and isinstance(obj, QPushButton):
            t = ev.type()
            if t == QEvent.Enter:
                self.particles.emit_from(obj, 10)
            elif t == QEvent.MouseButtonPress:
                self.particles.emit_from(obj, 22)
        return super().eventFilter(obj, ev)

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
        self.page_login.btn_help.clicked.connect(self.on_help)
        self.page_courses.add_course.connect(self.on_add_course)
        self.page_courses.remove_course.connect(self.on_remove_course)
        self.page_courses.validate.connect(self.on_validate)
        self.page_courses.reload_selected.connect(self.on_reload_selected)
        self.page_courses.drop_requested.connect(self.on_drop_requested)
        self.page_courses.cb_headed.toggled.connect(self.on_headless_toggled)
        self.page_courses.back.connect(lambda: self.goto(1))
        self.page_courses.next.connect(lambda: self.goto(3))
        self.page_confirm.back.connect(lambda: self.goto(2))
        self.page_confirm.start.connect(self.on_start)
        self.page_monitor.stop.connect(self.on_stop)
        self.page_monitor.open_logs.connect(self.on_open_logs)
        self.page_monitor.export_diag.connect(self.on_export_diag)

    # 每页一种天幕「心情」：五页共用同一张背景的话，翻过去几乎没有
    # 「换了个地方」的感觉。索引 = 页面索引。
    SKY_VARIANTS = ["rose", "cool", "warm", "violet", "deep"]

    def goto(self, index: int):
        changed = self.stack.currentIndex() != index
        reverse = changed and index < self.stack.currentIndex()
        snap_old = snap_new = None
        geo = None
        if changed and self.isVisible() and motion.ENABLED:
            old = self.stack.currentWidget()
            if old is not None and old.width() > 0 and old.height() > 0:
                snap_old = old.grab()
                geo = QRect(self.stack.mapTo(self.centralWidget(), QPoint(0, 0)),
                            self.stack.size())
        self.stack.setCurrentIndex(index)
        self.steps.set_current(index)
        # 登录页整屏是天幕品牌分栏，顶上的天幕条会让两片深色撞在一起
        self.band.setVisible(index != 0)
        self.band.set_variant(self.SKY_VARIANTS[index % len(self.SKY_VARIANTS)])
        # 翻页：新页先抓一张快照，和旧页一起交给幕布做滑出 / 滑入
        if snap_old is not None and motion.ENABLED:
            cur = self.stack.currentWidget()
            if cur is not None and cur.width() > 0 and cur.height() > 0:
                snap_new = cur.grab()
        if snap_old is not None and snap_new is not None:
            if self.curtain is None:
                self.curtain = RevealCurtain(self.centralWidget())
            self.curtain.play(snap_old, snap_new, geo, reverse=reverse)
        if index == 2:
            self.page_courses.apply_mode(self.cfg.mode)
            self.page_courses.set_headless(self.cfg.headless)
            self.page_courses.set_entries(self.entries, self.results)
        if index == 3:
            self.page_confirm.refresh(self.cfg, self.entries)

    # ------------------------------------------------------------------
    def _set_user_label(self, user: str):
        """右上角只显示打码后的学号（202****06）。

        学号属于个人信息，截图、录屏、直播时不该整串露出来；
        启动时（读本地配置）和登录后走同一个格式，避免两处不一致。
        """
        user = (user or "").strip()
        if not user:
            text = ""
        elif len(user) > 5:
            text = f"学号 {user[:3]}****{user[-2:]}"
        else:
            text = f"学号 {user}"
        self.lb_user.setText(text)
        # 登录页不显示顶部导航，那一页的同一个信息挂在品牌面板底部
        brand = getattr(self.page_login, "lb_user_brand", None)
        if brand is not None:
            brand.setText(text)

    # ------------------------------------------------------------------
    def on_login(self, user, pwd, remember, trust):
        self.cfg.user = user
        self.cfg.remember_password = remember
        self.cfg.single_login = trust
        # 密码和学号都登记进脱敏表：日志、诊断包里永远不会出现原值
        redactor.add(pwd, user)
        self._set_user_label(user)

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
            self.core.login_human.connect(self.on_login_human)
            self.core.human_input.connect(self.on_human_input)
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

    def on_login_human(self, text: str):
        """需要你本人操作：界面高亮显示该做什么。"""
        self.page_login.set_human(text)

    def on_human_input(self, prompt):
        """工作线程要一次人工输入（验证码）—— 显示在**主窗口**里，不开新窗口。"""
        self.goto(0)                        # 保证用户看得见输入框
        self.page_login.show_prompt(prompt)
        log.info("等待用户输入验证码（可重发=%s 可改用窗口=%s）",
                 getattr(prompt, "allow_resend", False),
                 getattr(prompt, "allow_visible", False))

    def on_headless_toggled(self, headed: bool):
        headless = not headed
        self.cfg.headless = headless
        self.save_config()
        if self.core:
            self.core.do_set_headless(headless)
        log.info("浏览器模式切换为：%s", "后台无窗口" if headless else "可见窗口")

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

    @staticmethod
    def _kind_for(kind_text: str) -> str:
        """把页面上那列中文「属性」还原成内部类别代号（认不出就用 ty 兜底，
        退课校验是按课程号匹配的，类别只影响去哪一页找）。"""
        from ..browser import KIND_BY_NAME
        name = (kind_text or "").strip()
        if name in COURSE_KINDS:
            return name
        for full, code in KIND_BY_NAME.items():
            if name == full or name == full.rstrip("课"):
                return code
        return "ty"

    def on_drop_requested(self, c):
        """在「本学期已选课程」里点了某门课的「要退」→ 加进要退的清单。

        学生就不用自己去选课系统里翻课程号了（模式二让位最常用）。
        """
        for e in self.entries:
            if (e.action == "drop" and e.kch
                    and e.kch == getattr(c, "kch", "")
                    and str(e.kxh or "") == str(getattr(c, "kxh", ""))):
                QMessageBox.information(
                    self, "已经在清单里",
                    f"{getattr(c, 'name', '')}（{c.kch}-{c.kxh}）"
                    f"已经在「要退的课」清单里了。")
                return
        entry = CourseEntry(action="drop", kind=self._kind_for(getattr(c, "kind", "")),
                            kch=getattr(c, "kch", ""), kxh=getattr(c, "kxh", ""),
                            name=getattr(c, "name", ""),
                            time_text=getattr(c, "time_text", ""),
                            teacher=getattr(c, "teacher", ""))
        log.info("从已选课程加入要退的课：%s", entry.label())
        self.on_add_course(entry)

    def on_semesters_loaded(self, current: str, options):
        self.page_courses.set_semesters(current or self.cfg.xnxq, options)
        if current:
            self.cfg.xnxq = current
            self.save_config()

    def on_forget(self):
        """清除本机凭据。

        这里要分清两件事 —— 以前它们被合成了一个动作，代价很大：

          * 删密码          —— 无害，随时可以重新输入
          * 删浏览器身份    —— 把「信任此设备」的状态一起删了。下次登录会被学校
                              当成一台新电脑，很可能要求短信 / 微信二次验证，
                              而且之后每次都要验证。**这是不可逆的。**

        所以默认只做第一件事，第二件事必须由用户明确选择。
        """
        box = QMessageBox(self)
        box.setWindowTitle("清除本机保存的账号密码")
        box.setText("将删除本机加密保存的账号密码。")
        box.setInformativeText(
            "「仅清除密码」：只删密码，浏览器里的「信任此设备」状态保留，"
            "下次登录通常不需要二次验证。\n\n"
            "「连浏览器身份一起重置」：把浏览器配置目录也删掉。下次登录会被学校"
            "当成一台新设备，很可能要求短信 / 微信二次验证，而且以后每次都要验证。"
            "这一步不可逆。")
        b_pwd = box.addButton("仅清除密码（推荐）", QMessageBox.AcceptRole)
        b_all = box.addButton("连浏览器身份一起重置", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_pwd)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked is not b_pwd and clicked is not b_all:
            return
        reset_profile = clicked is b_all

        if reset_profile:
            confirm = QMessageBox.warning(
                self, "确认重置浏览器身份",
                "这会删除浏览器配置目录：\n"
                f"{self.paths.profile}\n\n"
                "删除后本机不再被识别为可信设备，下次登录很可能要求"
                "短信 / 微信二次验证 —— 而且以后每次登录都会要求。\n\n"
                "确定要重置吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return

        ok = self.store.clear()
        if reset_profile:
            try:
                import shutil
                if self.paths.profile.exists():
                    shutil.rmtree(self.paths.profile, ignore_errors=True)
                log.info("用户重置了浏览器身份（信任态已删除）。")
            except Exception as e:
                log.warning("删除浏览器目录失败：%s", e)

        self.page_login.ed_pwd.clear()
        self.cfg.user = ""
        self.cfg.courses = []
        self.entries = []
        self.results = {}
        self.save_config()
        self._set_user_label("")
        if ok and reset_profile:
            msg = ("已清除密码，并重置了浏览器身份。下次登录可能需要二次验证。")
        elif ok:
            msg = "已清除本机保存的密码（浏览器登录态保留，下次登录通常不用二次验证）。"
        else:
            msg = "清除时出了点问题，可手动删除数据目录。"
        self.page_login.set_status(msg, "ok" if ok else "warn")
        log.info("用户清除了本机保存的凭据（重置浏览器身份=%s）。", reset_profile)

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
            # 下标变了，旧的校验结果全部作废（下面重新校验一遍）
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
        cfg.headless = self.page_courses.headless()
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
        log.info("启动任务：模式=%s 课程=%d 门 间隔=%ss 试运行=%s 浏览器=%s",
                 cfg.mode, len(self.entries), cfg.poll_avg, cfg.dry_run,
                 "后台无窗口" if cfg.headless else "可见窗口")
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
        elif running and getattr(self.page_login, "_prompt", None) is not None:
            # 正卡在"等你输验证码"上：说清楚关掉就等于放弃这次登录，
            # 但绝不能不让关 —— 以前这里会卡住，用户想临时退出都退不掉。
            r = QMessageBox.question(
                self, "正在等待验证码",
                "程序正在等你输入验证码。\n现在关闭会取消这次登录，确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
        self.save_config()
        if self.core:
            try:
                # shutdown() 会先取消正在等待的人工输入，工作线程才能退出来
                self.core.shutdown()
                if not self.core.wait(8000):
                    log.warning("工作线程未在 8 秒内退出，仍继续关闭程序。")
            except Exception:
                pass
        log.info("程序退出。")
        e.accept()
