# -*- coding: utf-8 -*-
"""
界面与浏览器之间的桥
====================

Playwright 的同步接口有**线程亲和性**：浏览器在哪个线程建的，之后所有调用都必须
在那个线程里。所以这里开一个常驻工作线程，它独占浏览器，界面通过任务队列派活。

好处：登录只做一次，设置阶段的课程校验和正式运行共用同一个会话。

界面线程永远不直接碰浏览器 —— 所有回调都通过 Qt 信号跨线程投递，天然安全。
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

from PySide6.QtCore import QThread, Signal

from ..browser import ScholarBrowser, SessionExpired, PageError, NeedSecondFactor
from ..courses import CourseQuery, resolve, find_conflicts, pick_section
from ..config import AppConfig, Paths, CourseEntry
from ..humanize import HumanActor, NORMAL
from ..logging_setup import get_logger
from ..scheduler import Scheduler

log = get_logger("gui.core")


class BrowserCore(QThread):
    """常驻工作线程：持有浏览器，串行执行界面派来的任务。"""

    logged_in = Signal(bool, str)        # (成功?, 说明)
    login_progress = Signal(str)         # 登录过程中的阶段提示
    log_line = Signal(str, str)          # (文本, 级别)
    status_changed = Signal(dict)
    validated = Signal(int, dict)        # (课程下标, 校验结果)
    selected_loaded = Signal(object)     # 已选课程快照 list[SelectedCourse]
    semesters_loaded = Signal(str, object)   # (当前学期, [(值, 显示名), …])
    finished = Signal(str)

    def __init__(self, cfg: AppConfig, paths: Paths, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.paths = paths
        self.password = ""
        self.browser: ScholarBrowser | None = None
        self.scheduler: Scheduler | None = None
        self._jobs: "queue.Queue[tuple]" = queue.Queue()
        self._running = True
        self._login_ok = False

    # ------------------------------------------------------------------
    def say(self, msg: str, level: str = "INFO"):
        self.log_line.emit(msg, level)
        getattr(log, level.lower(), log.info)(msg)

    # ---- 界面派活 ----
    def do_login(self, user: str, password: str):
        self.cfg.user = user
        self.password = password
        self._jobs.put(("login", None))

    def do_validate(self, index: int, entry: CourseEntry, selected_snapshot: list):
        self._jobs.put(("validate", (index, entry, selected_snapshot)))

    def do_start(self):
        self._jobs.put(("start", None))

    def request_selected(self):
        """请工作线程读一次已选课程。"""
        self._jobs.put(("selected", None))

    def do_stop(self):
        if self.scheduler:
            self.scheduler.stop("界面请求停止")
        self._jobs.put(("nop", None))

    def shutdown(self):
        self._running = False
        if self.scheduler:
            self.scheduler.stop("程序退出")
        self._jobs.put(("quit", None))

    # ------------------------------------------------------------------
    def run(self):
        try:
            self.browser = ScholarBrowser(
                self.paths.profile, xnxq=self.cfg.xnxq, headless=self.cfg.headless,
                viewport=tuple(self.cfg.viewport), log=self.say,
                actor=HumanActor(NORMAL, self.say))
            self.browser.start()
        except Exception as e:
            self.say(f"浏览器启动失败：{e}", "ERROR")
            self.logged_in.emit(False, f"浏览器启动失败：{e}")
            self.finished.emit("error")
            return

        while self._running:
            try:
                job, payload = self._jobs.get(timeout=0.4)
            except queue.Empty:
                continue
            try:
                if job == "login":
                    self._handle_login()
                elif job == "selected":
                    rows = self.load_selected()
                    self.selected_loaded.emit(rows)
                elif job == "validate":
                    self._handle_validate(*payload)
                elif job == "start":
                    self._handle_start()
                elif job == "quit":
                    break
            except Exception as e:
                self.say(f"任务出错：{type(e).__name__}: {e}", "ERROR")
                log.error("工作线程任务异常", exc_info=True)

        try:
            if self.browser:
                self.browser.stop()
        except Exception:
            pass
        self.finished.emit("done")

    # ------------------------------------------------------------------
    def _handle_login(self):
        ok, msg = False, ""
        for attempt in range(1, 3):
            try:
                self.browser.login(self.cfg.user, self.password,
                                   single_login=self.cfg.single_login,
                                   on_progress=lambda s: self.login_progress.emit(s))
                ok, msg = True, "登录成功"
                break
            except NeedSecondFactor as e:
                # 需要真人完成二次验证，重试也没用，直接告诉用户怎么办
                msg = str(e)
                self.say(msg, "ERROR")
                break
            except PageError as e:
                msg = str(e)
                self.say(f"登录失败（第 {attempt} 次）：{msg}", "ERROR")
                if "密码" in msg or "用户名" in msg:
                    break
                time.sleep(min(12, 5 * attempt))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                log.error("登录异常", exc_info=True)
                self.say(f"登录异常（第 {attempt} 次）：{msg}", "ERROR")
                time.sleep(min(12, 5 * attempt))
        self._login_ok = ok
        if ok:
            self.say("登录成功，会话已就绪。")
            # 顺手把学期读出来，免得写死在配置里
            try:
                cur, opts = self.browser.read_semesters()
                if cur:
                    self.cfg.xnxq = cur
                    shown = dict(opts).get(cur, cur)
                    self.say(f"当前学期：{shown}（{cur}），共 {len(opts)} 个可选学期")
                self.semesters_loaded.emit(cur, opts)
            except Exception as e:
                self.say(f"读取学期失败：{e}", "WARN")
        self.logged_in.emit(ok, msg)

    def _handle_validate(self, index: int, entry: CourseEntry, selected: list):
        result = {"index": index, "ok": False, "reason": "", "rows": [],
                  "conflicts": [], "entry": entry}
        try:
            # 已选课程列表自己现读一次，不依赖界面传来的快照
            # （快照可能还没加载完，会导致"要退的课"被误判成找不到）
            snap = self.load_selected()
            if snap:
                self.selected_loaded.emit(snap)

            if entry.action == "drop":
                # 要退的课一定是"已选中的课"，直接在已选列表里模糊匹配，比去课程页搜更准
                hits = [c for c in snap
                        if (entry.kch and c.kch == entry.kch)
                        or (entry.name and entry.name in c.name
                            and (not entry.kxh or str(c.kxh) == str(entry.kxh)))
                        or (entry.resolved_cid and c.del_id == entry.resolved_cid)]
                if not hits:
                    result["reason"] = ("在你这学期的选课记录里没找到这门课。"
                                        "已选课程有：" +
                                        "、".join(f"{c.name}({c.kch})" for c in snap[:8]))
                    self.validated.emit(index, result)
                    return
                c = hits[0]
                entry.resolved = True
                entry.resolved_name = c.name
                entry.resolved_time = c.time_text
                entry.resolved_teacher = c.teacher
                entry.resolved_cid = c.del_id
                result.update(ok=True, reason="已找到这门已选课程", rows=[{
                    "kch": c.kch, "kxh": c.kxh, "name": c.name,
                    "time_text": c.time_text, "teacher": c.teacher,
                    "kyl": -1, "cid": c.del_id}])
                self.validated.emit(index, result)
                return

            res = resolve(self.browser, entry.to_query())
            if res.ambiguous:
                result["reason"] = res.reason
                result["rows"] = [r.__dict__ for r in res.rows]
                result["ambiguous"] = True
                self.validated.emit(index, result)
                return
            if not res.ok:
                result["reason"] = res.reason
                self.validated.emit(index, result)
                return

            row = pick_section(res.rows, kxh=entry.kxh, time_text=entry.time_text)
            if row is None:
                result["reason"] = "定位不到具体课堂，请补充课序号或上课时间。"
                self.validated.emit(index, result)
                return

            entry.resolved = True
            entry.resolved_name = row.name
            entry.resolved_time = row.time_text
            entry.resolved_teacher = row.teacher
            entry.resolved_kyl = row.kyl
            entry.resolved_cid = row.cid or f"{self.cfg.xnxq};{row.kch};{row.kxh};"

            # 时间冲突：与已选课程比
            conflicts = find_conflicts(row.time_text,
                                       [(c.name, c.time_text) for c in snap])
            result.update(ok=True, reason="已找到课程", conflicts=conflicts,
                          rows=[row.__dict__])
            self.validated.emit(index, result)
        except SessionExpired:
            self._try_relogin()
            result["reason"] = "会话过期，已自动重新登录，请再点一次校验。"
            self.validated.emit(index, result)
        except Exception as e:
            log.error("校验课程异常", exc_info=True)
            result["reason"] = f"校验失败：{type(e).__name__}: {e}"
            self.validated.emit(index, result)

    def load_selected(self) -> list:
        """读一次已选课程（在工作线程里调用）。"""
        try:
            return self.browser.read_selected()
        except Exception as e:
            self.say(f"读取已选课程失败：{e}", "WARN")
            return []

    def _try_relogin(self):
        try:
            self.say("会话失效，自动重新登录…", "WARN")
            self.browser.login(self.cfg.user, self.password,
                               single_login=self.cfg.single_login)
            self.say("重新登录成功。")
        except Exception as e:
            self.say(f"重新登录失败：{e}", "ERROR")

    def _handle_start(self):
        self.scheduler = Scheduler(
            self.cfg, self.paths, password=self.password,
            on_log=self.say,
            on_status=lambda s: self.status_changed.emit(s),
            on_finished=lambda r: self.finished.emit(r))
        self.scheduler.attach_browser(self.browser)
        self.say("开始执行任务…")
        self.scheduler.run_inline()
        self.say("任务线程结束。")
