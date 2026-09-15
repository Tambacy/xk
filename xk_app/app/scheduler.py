# -*- coding: utf-8 -*-
"""
调度器：三种运行模式
====================

所有 Playwright 操作都必须在**同一个线程**里，所以调度器自己持有浏览器，
在后台线程里跑，对界面只暴露线程安全的回调。

模式一  尚未开始选课
    以学校通知的预定开始时间为参照，提前一段时间开始盯「当前选课阶段」。
    阶段一旦从「选课报名（之后抽签）」变成「正选 / 补退选」（先到先得），
    立刻按学生预定的课程清单自动选课。
    这一段**充分拟人化**：间隔长尾抖动、偶尔走神、夜间静默，不追求快。

模式二  马上开始，且已有课程需要让位
    同样是等预定时间，但到点后先退掉时间冲突的课，再抢目标课。
    等待期间拟人化，**动手那一瞬间全速**。

模式三  长期监听
    不设开始时间，按学生设定的平均间隔反复查课余量（可以很久，比如 1 小时），
    一旦有课余量就（必要时先退课）立刻抢。这一模式**尤其强调拟人化**。
"""
from __future__ import annotations

import random
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from .browser import (ScholarBrowser, SessionExpired, PageError,
                      COURSE_KINDS, CapacityRow, SelectedCourse)
from .courses import (CourseQuery, resolve, pick_section, find_conflicts,
                      same_course,
                      parse_slots, describe_rows)
from .config import AppConfig, CourseEntry, Paths
from .humanize import (HumanActor, Tempo, RELAXED, NORMAL, URGENT,
                       PollRhythm, night_silence_active, pause)
from .logging_setup import get_logger, get_trace_logger

log = get_logger("scheduler")


class State(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    WAITING = "waiting"          # 等选课开始
    MONITORING = "monitoring"    # 盯课余量
    ACTING = "acting"            # 正在退课/抢课
    SUCCESS = "success"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class Status:
    state: str = State.IDLE.value
    message: str = ""
    polls: int = 0
    started_at: float = 0.0
    last_poll_at: float = 0.0
    next_poll_in: float = 0.0
    phase_text: str = ""
    courses: list = None          # [{label, kyl, state}]
    success: list = None          # 抢到的课

    def as_dict(self):
        return {
            "state": self.state, "message": self.message, "polls": self.polls,
            "started_at": self.started_at, "last_poll_at": self.last_poll_at,
            "next_poll_in": self.next_poll_in, "phase_text": self.phase_text,
            "courses": self.courses or [], "success": self.success or [],
        }


def beep(times: int = 4):
    try:
        import winsound
        for _ in range(times):
            winsound.Beep(1100, 160)
            winsound.Beep(1500, 160)
    except Exception:
        pass


# --------------------------------------------------------------------------
# 选课阶段判断
# --------------------------------------------------------------------------

SELECT_PHASES = ("正选", "补退选", "补选退", "选课调整")
LOTTERY_PHASES = ("报名", "预选", "抽签")
NEVER_PHASES = ("未开始", "已结束", "不是选课", "不能选课")

# 服务端的「硬拒绝」：重试多少次结果都一样，而且重试只会拖时间、
# 甚至触发防刷（连续提交会被判「请输入正确的验证码」）。
HARD_FAIL_MARKERS = (
    "选课阶段", "不能选课", "只能选一门", "不能提交",
    "不存在", "没有余量", "已满", "验证码", "不允许", "未开放",
)


def phase_allows_select(text: str) -> bool | None:
    """根据「当前选课阶段」文本判断现在能不能先到先得地选课。

    返回 None 表示拿不准（那就交给服务端的实际返回来判断）。
    """
    if not text:
        return None
    t = text.replace(" ", "")
    if any(k in t for k in NEVER_PHASES):
        return False
    # 补退选第二阶段只能删不能选
    if "第二阶段" in t and "补退选" in t:
        return False
    if any(k in t for k in SELECT_PHASES):
        return True
    if any(k in t for k in LOTTERY_PHASES):
        return False       # 报名阶段是抽签，不是先到先得
    return None


def phase_time_range(text: str) -> tuple[datetime | None, datetime | None]:
    """从「…2026年09月14日13时开始 2026年09月21日08时结束」里抠出起止时间。"""
    import re
    stamps = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时", text or "")
    out = []
    for y, mo, d, h in stamps[:2]:
        try:
            out.append(datetime(int(y), int(mo), int(d), int(h)))
        except Exception:
            out.append(None)
    while len(out) < 2:
        out.append(None)
    return out[0], out[1]


# --------------------------------------------------------------------------
# 调度器
# --------------------------------------------------------------------------

class Scheduler:
    """后台线程里跑选课逻辑。界面通过回调拿状态。"""

    def __init__(self, cfg: AppConfig, paths: Paths, password: str = "",
                 on_log: Callable[[str, str], None] | None = None,
                 on_status: Callable[[dict], None] | None = None,
                 on_finished: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.paths = paths
        self.password = password
        self.on_log = on_log or (lambda m, l="INFO": None)
        self.on_status = on_status or (lambda s: None)
        self.on_finished = on_finished or (lambda r: None)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status = Status()
        self.browser: ScholarBrowser | None = None
        self._keep_browser = False      # 接管外部浏览器时不在结束时关掉它

    # ------------------------------------------------------------------
    def attach_browser(self, browser: ScholarBrowser):
        """接管一个已经建好的浏览器（必须与调用线程相同，Playwright 有线程亲和性）。"""
        self.browser = browser
        self._keep_browser = True

    def run_inline(self):
        """在当前线程里直接跑（供界面工作线程调用，避免重复启动浏览器）。"""
        self._stop.clear()
        self._run()

    # ------------------------------------------------------------------
    def say(self, msg: str, level: str = "INFO"):
        try:
            self.on_log(msg, level)
        except Exception:
            pass
        getattr(log, level.lower(), log.info)(msg)

    def _push(self):
        try:
            self.on_status(self.status.as_dict())
        except Exception:
            pass

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        self._stop.clear()
        self.status = Status(state=State.PREPARING, started_at=time.time(),
                             courses=[], success=[])
        self._thread = threading.Thread(target=self._run, name="xk-scheduler",
                                        daemon=True)
        self._thread.start()

    def stop(self, reason: str = "用户停止"):
        self.say(f"收到停止请求（{reason}）", "WARN")
        self._stop.set()

    def join(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------------
    def _run(self):
        try:
            self._main()
        except Exception as e:
            self.say(f"运行出错：{type(e).__name__}: {e}", "ERROR")
            log.error("调度器异常", exc_info=True)
            self.status.state = State.ERROR.value
            self.status.message = f"{type(e).__name__}: {e}"
            self._push()
            self.on_finished("error")
        finally:
            try:
                if self.browser and not self._keep_browser:
                    self.browser.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _main(self):
        cfg = self.cfg
        text = get_trace_logger()
        self.say(f"以模式 {cfg.mode} 启动（{'试运行' if cfg.dry_run else '正式运行'}）")

        # 浏览器必须在本线程里创建（Playwright 有线程亲和性）；
        # 如果界面已经接管了一个，就直接用它，省掉一次启动和登录。
        if self.browser is None:
            self.browser = ScholarBrowser(
                self.paths.profile, xnxq=cfg.xnxq, headless=cfg.headless,
                viewport=tuple(cfg.viewport), log=self.say,
                actor=HumanActor(NORMAL, self.say))
            self.browser.start()
        else:
            self.say("复用已打开的浏览器会话。")
            try:
                self.browser.actor.log = self.say
            except Exception:
                pass
        self.status.message = "正在登录…"
        self._push()

        tries = 0
        while not self._stop.is_set():
            try:
                if not self.browser.is_logged_in():
                    self.browser.login(cfg.user, self.password,
                                       single_login=cfg.single_login)
                break
            except PageError as e:
                tries += 1
                self.say(f"登录失败（第 {tries} 次）：{e}", "ERROR")
                if tries >= 3:
                    raise
                pause(8, 15)
        if self._stop.is_set():
            return self._finish_stopped()
        self.say("登录成功。")

        if cfg.mode == 3:
            self._run_mode3()
        else:
            self._run_scheduled()

        if self._stop.is_set():
            # 被要求停止：必须显式收尾，否则界面永远停在"监听中"
            return self._finish_stopped()

        self.status.state = (State.SUCCESS.value if self.status.success
                             else State.STOPPED.value)
        self._push()
        self.on_finished("success" if self.status.success else "done")

    def _finish_stopped(self):
        self.status.state = State.STOPPED.value
        self.status.message = "已停止"
        self._push()
        self.on_finished("stopped")

    # ==================================================================
    # 模式一 / 二：等选课开始
    # ==================================================================
    def _run_scheduled(self):
        cfg = self.cfg
        start_at = cfg.start_datetime()
        if start_at is None:
            raise PageError("没有设置有效的开始时间，请回到上一步填写")

        lead = timedelta(seconds=int(cfg.lead_seconds))
        arrive = start_at - lead
        self.say(f"预定开始时间：{start_at:%Y-%m-%d %H:%M}，"
                 f"将于 {arrive:%Y-%m-%d %H:%M:%S} 开始提前盯梢")

        # ---- 阶段 A：慢慢等，偶尔看一眼选课阶段 ----
        watcher = PollRhythm(avg=max(30.0, cfg.poll_avg), jitter=(0.7, 1.5),
                             long_prob=0.15, long_factor=(1.4, 2.6))
        while not self._stop.is_set() and datetime.now() < arrive:
            left = (arrive - datetime.now()).total_seconds()
            self.status.state = State.WAITING.value
            self.status.message = f"等待开始（还剩 {self._human_left(left)}）"
            self._push()
            if not self._sleep(min(watcher.next(), max(5.0, left))):
                return self._finish_stopped()
            if random.random() < 0.35:
                self._peek_phase()

        self.say("进入提前盯梢窗口。", "WARN")
        self._watch_until_open(start_at)

        if self._stop.is_set():
            return self._finish_stopped()

        # ---- 阶段 C：动手 ----
        if cfg.mode == 2:
            self._do_drop_list()
        self._do_grab_list(urgent=True)

    def _watch_until_open(self, start_at: datetime):
        """盯「当前选课阶段」，直到可以选课为止。"""
        cfg = self.cfg
        rhythm = PollRhythm(avg=max(2.0, min(cfg.urgent_interval * 2, 15.0)),
                            jitter=(0.6, 1.4), long_prob=0.05,
                            long_factor=(1.3, 2.0))
        asked = False
        while not self._stop.is_set():
            if not self._night_ok():
                continue
            t_round = time.time()
            text = self._peek_phase()
            allow = phase_allows_select(text)
            t_start, t_end = phase_time_range(text)
            now = datetime.now()

            if allow is True:
                if t_start and now < t_start - timedelta(seconds=5):
                    self.status.message = (f"阶段已开放，但按公告 {t_start:%H:%M} 才开始，"
                                           f"继续等")
                else:
                    self.say(f"✅ 检测到可以选课了：{text}", "WARN")
                    return
            elif allow is False:
                self.status.state = State.WAITING.value
                self.status.message = f"尚未开始选课：{text or '（读不到阶段信息）'}"
            else:
                # 拿不准 —— 时间到了就试一次，用服务端的返回当最终判据
                if now >= start_at and not asked:
                    asked = True
                    self.say("阶段信息不明确，但时间已到，先试一次提交。", "WARN")
                    return
                self.status.message = f"阶段信息不明确：{text}"
            # 先算 remain 再 push —— 顺序反了的话界面拿到的是上一轮的
            # next_poll_in（第一轮是初始值 0），「距下次检查」就一直是横杠。
            period = rhythm.next()
            remain = max(0.0, period - (time.time() - t_round))
            self.status.next_poll_in = remain
            self._push()
            if not self._sleep(remain):
                return

    def _peek_phase(self) -> str:
        try:
            text = self.browser.read_phase_text()
            self.status.phase_text = text
            return text
        except SessionExpired:
            self._relogin()
            return ""
        except Exception as e:
            self.say(f"读选课阶段失败：{e}", "WARN")
            return ""

    # ==================================================================
    # 模式三：长期监听
    # ==================================================================
    def _run_mode3(self):
        cfg = self.cfg
        grabs = [c for c in cfg.courses_as_entries() if c.action == "grab"]
        if not grabs:
            raise PageError("没有要抢的课程")
        self.say(f"开始长期监听 {len(grabs)} 门课，"
                 f"平均间隔 {cfg.poll_avg:g} 秒")

        rhythm = PollRhythm(avg=float(cfg.poll_avg), jitter=tuple(cfg.poll_jitter),
                            long_prob=float(cfg.long_pause_prob),
                            long_factor=tuple(cfg.long_pause_factor))
        self.status.state = State.MONITORING.value
        last_report = 0.0
        t0 = time.time()

        while not self._stop.is_set():
            if not self._night_ok():
                self.status.state = State.WAITING.value
                self.status.message = "夜间静默中"
                self._push()
                continue

            if cfg.max_duration_hours and (time.time() - t0) > cfg.max_duration_hours * 3600:
                self.say("达到设定的最长运行时长，停止监听。")
                return self._finish_stopped()

            period = rhythm.next()
            t_round = time.time()
            self.status.state = State.MONITORING.value
            ok = self._poll_once(grabs, quiet=True)
            if ok:
                self.status.state = State.SUCCESS.value
                self._push()
                if cfg.auto_exit_on_success:
                    self.say("全部目标已完成，按设置退出监听。")
                    return
                pause(6, 12)      # 抢到之后再低频确认几次
                continue

            # 按周期结算：扣掉本轮轮询耗掉的时间。非体育课要走页面搜索，
            # 一轮可能好几秒，不扣的话真实间隔会明显长于设定值。
            #
            # ⚠ 必须先算 remain、再写 status、最后 _push()。
            # 原来的顺序是「先 push 再赋值」，界面拿到的永远是**上一轮**的
            # next_poll_in（第一轮就是初始值 0），于是「距下次检查」那一栏
            # 一直显示成横杠 —— 而同一行的 message 里却写着「下次 260.5s 后」，
            # 同一份数据两个说法。
            remain = max(0.0, period - (time.time() - t_round))
            self.status.next_poll_in = remain

            # 给界面一个能看懂的当前状态
            brief = "、".join(f"{c['kyl']}" for c in (self.status.courses or [])) or "—"
            self.status.message = (f"监听中 · 已轮询 {self.status.polls} 次 · "
                                   f"课余量 {brief} · 下次 {remain:.0f}s 后")
            self._push()
            # 每 5 分钟在信息级留一条汇总，方便事后看"那段时间到底在不在跑"
            if time.time() - last_report > 300:
                last_report = time.time()
                log.info("监听中：已轮询 %d 次，状态 %s", self.status.polls,
                         "; ".join(f"{c['label']} 课余量{c['kyl']}" for c in
                                   (self.status.courses or [])))
            if not self._sleep(remain):
                return

    # ==================================================================
    # 公共：轮询 / 抢课
    # ==================================================================
    def _poll_once(self, grabs: list[CourseEntry], quiet: bool = False) -> bool:
        """查一遍所有目标课的课余量；有任何一门有余量就动手。返回是否全部达成。"""
        self.status.polls += 1
        self.status.last_poll_at = time.time()
        done_flags = []
        snapshot = []

        for entry in grabs:
            try:
                row, all_rows = self._read_target(entry)
            except SessionExpired:
                self._relogin()
                done_flags.append(False)
                continue
            except Exception as e:
                self.say(f"查询 {entry.label()} 失败：{e}", "WARN")
                done_flags.append(False)
                continue

            if row is None:
                snapshot.append({"label": entry.label(), "kyl": -1, "state": "没查到"})
                done_flags.append(False)
                continue

            kyl = row.kyl
            snapshot.append({"label": f"{row.name} {row.kch}-{row.kxh} {row.time_text}",
                             "kyl": kyl, "state": ""})
            # DEBUG 级别：界面日志窗能看到轮询在动，但不会撑大业务日志文件
            self.say(f"第 {self.status.polls} 次  {row.name} {row.kch}-{row.kxh} "
                     f"{row.time_text}  课余量={kyl}", "DEBUG")
            if kyl > 0:
                self.say(f"⚡ {row.name} 出现课余量 {kyl}！", "WARN")
                got = self._grab(entry, row, all_rows)
                done_flags.append(got)
            else:
                done_flags.append(False)

        self.status.courses = snapshot
        return bool(done_flags) and all(done_flags)

    def _read_rows(self, entry: CourseEntry) -> list:
        """读一门课的候选行。

        **策略是实测出来的**（2026-09-14 对着真实页面量过）：

          * 体育课：URL 带 p_kch 会把 gridData 直接筛成目标课那几行 ——
            快路径，0.34 秒，实测有效，照用。
          * 必修 / 限选 / 任选：URL 参数**无效**，但页面会返回「默认候选列表」。
            实测必修课的默认列表里就有目标课的 4 个课堂，所以正解是
            **先读默认列表、在里面找目标课**。
          * 默认列表里真的没有时，再走页面搜索框（实测任选课的搜索框有效）。
          * 那个「查询」按钮的 onclick 在必修页是 filter()、体育页是 doQuery()，
            有的页面上压根没定义 —— 点了毫无反应，所以不能只依赖它。

        以前写的是「非体育课一律走搜索框」，结果必修课拿回来的是没筛过的
        14 行无关课程。现在改成列表优先、搜索兜底。
        """
        browser = self.browser
        if entry.kind == "ty" and entry.kch:
            return browser.read_capacity_rows("ty", kch=entry.kch)

        want = self._want_kch(entry)
        rows = browser.read_capacity_rows(entry.kind)
        if not want or any(r.kch == want for r in rows):
            return rows

        keyword = entry.kch or entry.name
        if not keyword:
            return rows
        # 先按课程号搜，不行再按课程名搜 —— 实测任选课按课程名能搜到、
        # 按课程号搜不到；多试一种能救回相当一部分课程。
        tried = []
        for kw, by_kch in ((entry.kch, True), (entry.name, False)):
            if not kw or kw in tried:
                continue
            tried.append(kw)
            try:
                found = browser.search_course_human(entry.kind, kw, by_kch=by_kch)
            except Exception as e:
                self.say(f"搜索 {entry.label()}（{kw}）失败：{e}", "WARN")
                continue
            if found and (not want or any(r.kch == want for r in found)):
                return found
        self.say(f"默认列表和搜索里都没找到 {want or entry.label()}；"
                 f"如果这门课确实开了，可能被分页挡在后面。", "WARN")
        return rows

    @staticmethod
    def _want_kch(entry: CourseEntry) -> str:
        """目标课程号：优先 entry.kch，其次从校验时回填的 resolved_cid 里取。"""
        if entry.kch:
            return entry.kch
        parts = (entry.resolved_cid or "").split(";")
        return parts[1] if len(parts) >= 3 else ""

    def _read_target(self, entry: CourseEntry):
        """读目标课当前状况，返回 (命中的行, 该课程号下所有行)。

        最后有一道守门：挑出来的那行**必须就是目标课程号**。课序号都是 0/1/2
        这种小数字，一旦页面返回的是别的课，`pick_section` 很容易撞上一个
        无关课程的 kxh —— 那就会拿着**别人的课**的 cid 去退课和提交。
        宁可这一轮什么都不做，也绝不能改错学生的选课结果。
        """
        rows = self._read_rows(entry)
        want = self._want_kch(entry)
        if want:
            exact = [r for r in rows if r.kch == want]
            if exact:
                rows = exact

        row = pick_section(rows, kxh=entry.kxh, time_text=entry.time_text)
        if row is not None and want and row.kch != want:
            self.say(f"⚠ 页面返回的是 {row.name} {row.kch}-{row.kxh}，不是目标课程 "
                     f"{want}，本轮跳过（避免选错课）", "WARN")
            row = None
        return row, rows

    def _grab(self, entry: CourseEntry, row: CapacityRow, all_rows: list) -> bool:
        """一次完整的抢课动作：必要时先退课，再提交，最后校验/回滚。"""
        cfg = self.cfg
        cid = row.cid or f"{cfg.xnxq};{row.kch};{row.kxh};"
        self.status.state = State.ACTING.value
        self.status.message = f"正在抢 {row.name} {row.kch}-{row.kxh}"
        self._push()

        self.say("=" * 60)
        self.say(f"⚡ 检测到课余量！{row.name} {row.kch}-{row.kxh} {row.time_text} "
                 f"课余量 {row.kyl}", "WARN")
        t0 = time.perf_counter()

        # 已经选上就不用动了
        try:
            selected = self.browser.read_selected()
        except Exception:
            selected = []
        if any(c.kch == row.kch and str(c.kxh) == str(row.kxh) for c in selected):
            self.say(f"{row.name} 已经在选课记录里了，跳过。")
            self._mark_success(entry, row)
            return True

        if cfg.dry_run:
            self.say("（试运行）跳过实际提交。", "WARN")
            self._mark_success(entry, row)
            return True

        # ---- 让位：退掉指定的课 + 与目标时间冲突的课 ----
        dropped: list[SelectedCourse] = []
        for victim in self._victims(entry, selected, row):
            try:
                self.say(f"先退课：{victim.name} {victim.kch}-{victim.kxh} {victim.time_text}")
                msg = self.browser.drop_course(victim.del_id, urgent=True)
                self.say(f"  退课结果：{msg}")
                dropped.append(victim)
            except Exception as e:
                self.say(f"  退课失败：{e}", "ERROR")

        # ---- 提交 ----
        ok, msg = False, ""
        for attempt in range(1, 4):
            try:
                msg = self.browser.submit_selection(entry.kind, cid, urgent=True,
                                                    kch=row.kch)
            except SessionExpired:
                self._relogin()
                continue
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
            self.say(f"提交选课（第 {attempt} 次）：{msg}")
            if "成功" in msg:
                ok = True
                break
            if any(k in msg for k in HARD_FAIL_MARKERS):
                # 硬拒绝：比如「…是体育课，只能选一门,不能提交 !」。
                # 以前只认「选课阶段」「不能选课」两个词，其余全被当成可重试，
                # 白白重试 3 次（每次还要睡 1.5~3 秒），抢课窗口就这么流失了。
                self.say(f"服务端明确拒绝，不再重试：{msg}", "WARN")
                break
            pause(1.5, 3.0)

        # ---- 校验 ----
        try:
            selected2 = self.browser.read_selected()
        except Exception:
            selected2 = []
        got = [c for c in selected2 if c.kch == row.kch and str(c.kxh) == str(row.kxh)]
        elapsed = (time.perf_counter() - t0) * 1000
        if got or ok:
            self.say(f"✅ 抢课成功！{got[0].name if got else row.name} "
                     f"{row.kch}-{row.kxh}  [整条链路 {elapsed:.0f} ms]", "WARN")
            self._mark_success(entry, row)
            if cfg.beep_on_success:
                beep()
            return True

        self.say(f"❌ 没抢到（{elapsed:.0f} ms）：{msg}", "ERROR")
        # ---- 回滚：把刚才退掉的课选回来 ----
        if dropped:
            self.say("尝试回滚，把退掉的课选回来…", "WARN")
            for c in dropped:
                for _ in range(3):
                    m = self._reselect(c, entry)
                    self.say(f"  回滚 {c.name}：{m}")
                    if "成功" in m:
                        break
                    pause(1.2, 2.0)
        return False

    @staticmethod
    def _kind_of(kind_text: str) -> str | None:
        """把已选列表里那个中文「属性」列还原成内部类别代号；认不出返回 None。

        页面这一列有时写「必修」、有时写「必修课」，两种都要认 —— 以前只按
        COURSE_KINDS 里的全名（「必修课」）精确比对，所以「必修」一律认不出，
        回滚时就退化成了「目标课的类别」。
        """
        name = (kind_text or "").strip()
        if not name:
            return None
        if name in COURSE_KINDS:                    # 已经是代号
            return name
        for k, v in COURSE_KINDS.items():
            full = v["name"]
            if name == full or name == full.rstrip("课"):
                return k
        return None

    def _reselect(self, c: SelectedCourse, entry: CourseEntry) -> str:
        """把退掉的课选回来。

        类别优先用已选列表里的那一列；那一列是页面 JS 填的，**可能为空**，
        空的时候以前会直接退化成「目标课的类别」—— 用体育课当目标去回滚一门
        任选课，就会跑去体育课页面找，永远找不到（等于白退一门课）。

        这里改成依次尝试各个类别。这样做是安全的：`submit_selection` 在点提交
        之前会先确认页面上真的有这个 cid，找不到就抛错，所以「试错」不可能
        误选到别的课，只是多花几次页面加载。
        """
        order: list[str] = []
        for k in ([self._kind_of(c.kind), entry.kind, "ty", "rx", "bx", "xx", "cx"]):
            if k and k not in order:
                order.append(k)
        last = ""
        for kind in order:
            try:
                # ⚠ 必须把课程号带上：体育课页只有带 p_kch 才会筛出目标课那几行，
                # 不带的话打开的是「全部体育课」列表（18 页），目标课根本不在
                # 第一页上 —— 实测就是这样导致回滚一次都成功不了。
                last = self.browser.submit_selection(kind, c.del_id, urgent=False,
                                                     kch=c.kch)
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
            if "成功" in last:
                return last
        return last

    def _victims(self, entry: CourseEntry, selected: list[SelectedCourse],
                 row: CapacityRow) -> list[SelectedCourse]:
        """挑出为了选上这门课而必须退掉的课。"""
        cfg = self.cfg
        victims: list[SelectedCourse] = []

        # 1) 学生显式指定要退的课（模式二）
        #    认课的三条线索走 courses.same_course，和校验冲突用的是同一套 ——
        #    分开写迟早会漂移成「校验说不用退、运行时却退了」。
        drop_entries = [c for c in cfg.courses_as_entries() if c.action == "drop"]
        for de in drop_entries:
            for c in selected:
                if same_course(c, de):
                    victims.append(c)

        # 2) 同课程类别的体育课：一学期只能选一门，必须让位
        if entry.kind == "ty":
            for c in selected:
                if c.kch.startswith("107") and c.kch != row.kch:
                    victims.append(c)

        # 3) 与目标课时间冲突的课
        others = [(c.name, c.time_text, c) for c in selected]
        conflicts = find_conflicts(row.time_text, [(n, t) for n, t, _ in others])
        for name, _, c in others:
            if any(name in cf for cf in conflicts):
                victims.append(c)

        # 去重
        seen, out = set(), []
        for c in victims:
            if c.del_id and c.del_id not in seen:
                seen.add(c.del_id)
                out.append(c)
        return out

    def _mark_success(self, entry: CourseEntry, row: CapacityRow):
        entry.resolved = True
        entry.resolved_name = row.name
        entry.resolved_time = row.time_text
        entry.resolved_teacher = row.teacher
        entry.resolved_kyl = row.kyl
        entry.resolved_cid = row.cid
        s = self.status.success or []
        label = f"{row.name} {row.kch}-{row.kxh} {row.time_text}"
        if label not in s:
            s.append(label)
        self.status.success = s
        self.status.message = f"已抢到 {label}"
        self._push()

    def _do_grab_list(self, urgent: bool):
        grabs = [c for c in self.cfg.courses_as_entries() if c.action == "grab"]
        self.say(f"开始抢 {len(grabs)} 门课")
        for entry in grabs:
            if self._stop.is_set():
                return
            try:
                row, all_rows = self._read_target(entry)
            except Exception as e:
                self.say(f"查询 {entry.label()} 失败：{e}", "ERROR")
                continue
            if row is None:
                self.say(f"没查到 {entry.label()}，跳过", "WARN")
                continue
            self._grab(entry, row, all_rows)

    def _do_drop_list(self):
        """模式二里，先把指定要退的课退掉（不管有没有冲突）。"""
        drops = [c for c in self.cfg.courses_as_entries() if c.action == "drop"]
        if not drops:
            return
        self.say(f"先处理 {len(drops)} 门要退的课")
        try:
            selected = self.browser.read_selected()
        except Exception as e:
            self.say(f"读取已选课程失败：{e}", "ERROR")
            return
        for de in drops:
            for c in selected:
                hit = ((de.kch and c.kch == de.kch) or
                       (de.name and de.name in c.name) or
                       (de.resolved_cid and de.resolved_cid == c.del_id))
                if not hit:
                    continue
                self.say(f"退课：{c.name} {c.kch}-{c.kxh} {c.time_text}")
                try:
                    self.say("  结果：" + self.browser.drop_course(c.del_id, urgent=True))
                except Exception as e:
                    self.say(f"  退课失败：{e}", "ERROR")

    # ==================================================================
    # 杂项
    # ==================================================================
    def _relogin(self):
        self.say("会话失效，自动重新登录…", "WARN")
        for i in range(3):
            try:
                self.browser.login(self.cfg.user, self.password,
                                   single_login=self.cfg.single_login)
                self.say("重新登录成功。")
                return True
            except Exception as e:
                self.say(f"重新登录失败（第 {i+1} 次）：{e}", "ERROR")
                if not self._sleep(random.uniform(8, 16)):
                    return False
        return False

    def _sleep(self, seconds: float) -> bool:
        """可被打断的睡眠。返回 False 表示被要求停止。"""
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self._stop.wait(0.25):
                return False
        return True

    def _night_ok(self) -> bool:
        """夜间静默：整段时间内不碰网络。"""
        win = self.cfg.night_silence
        if not night_silence_active(win):
            return True
        if not getattr(self, "_night_logged", False):
            self.say(f"🌙 进入夜间静默（{win[0]}~{win[1]}），暂停所有请求。")
            self._night_logged = True
        while night_silence_active(win) and not self._stop.is_set():
            if not self._sleep(30):
                return False
        if getattr(self, "_night_logged", False):
            self._night_logged = False
            self.say("🌅 夜间静默结束，恢复监听。")
            try:
                self._relogin()
            except Exception:
                pass
        return not self._stop.is_set()

    @staticmethod
    def _human_left(seconds: float) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds} 秒"
        if seconds < 3600:
            return f"{seconds // 60} 分 {seconds % 60} 秒"
        return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"
