# -*- coding: utf-8 -*-
"""真实环境全流程演练（**只读 + 试运行**，不改变选课结果）

覆盖：登录 → 学期列表 → 当前选课阶段 → 已选课程 → 课余量（体育课 URL 快路径 /
非体育课"默认列表 + 搜索"）→ 课程定位与冲突校验 → 模式三长期监听（dry_run）。

**本脚本不会退课、也不会提交选课**，可以放心反复跑。
需要凭据（`_creds.load_secrets()`，来自 DPAPI）和能连上学校网络。

    python test_live_flow.py
"""
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent  # 项目根
sys.path.insert(0, str(ROOT / "xk_app"))  # noqa: E501
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _creds
from app.browser import ScholarBrowser, COURSE_KINDS
from app.config import AppConfig, CourseEntry, Paths
from app.courses import CourseQuery, resolve, parse_slots, parse_weeks, find_conflicts
from app.humanize import HumanActor, NORMAL
from app.logging_setup import setup_logging
from app.scheduler import Scheduler, phase_allows_select, phase_time_range

paths = Paths.build()
setup_logging(paths.logs, console=False)
sec = _creds.load_secrets()

T0 = time.perf_counter()
LOG = []


def say(msg=""):
    line = f"[{time.perf_counter()-T0:7.1f}s] {msg}"
    LOG.append(line)
    print(line, flush=True)


def rule(t=""):
    say()
    say("=" * 78)
    if t:
        say(t)
        say("=" * 78)


b = ScholarBrowser(paths.profile, headless=True, log=lambda m, l="INFO": None,
                   actor=HumanActor(NORMAL, lambda m, l="INFO": None))

rule("① 登录")
b.start()
b.login(sec["user"], sec["pass"], single_login=True,
        ask_human_code=lambda *a, **k: None)
say(f"登录成功，落地页 {b.page.url[:70]}")

rule("② 课程信息 —— 学期列表")
cur, opts = b.read_semesters()
say(f"当前学期：{cur}")
for v, t in opts[:8]:
    say(f"    {v}  {t}")

rule("③ 课程信息 —— 当前选课阶段")
phase = b.read_phase_text()
say(f"阶段原文：{phase[:160]}")
allow = phase_allows_select(phase)
t1, t2 = phase_time_range(phase)
say(f"现在能先到先得地选课吗：{allow}   阶段区间：{t1} ~ {t2}")

rule("④ 课程信息 —— 已选定课程（权威列表 m=yxSearchTab）")
sel = b.read_selected()
say(f"共 {len(sel)} 门：")
for c in sel:
    say(f"    [{c.kind or '—':<4}] {c.kch:<10} {c.kxh:<3} {c.name:<22} "
        f"{c.time_text:<18} {c.teacher:<8} 学分{c.credit:<4} del_id={c.del_id[:28]}")

rule("⑤ 课程信息 —— 课余量（体育课：URL 快路径）")
t0 = time.perf_counter()
rows_ty = b.read_capacity_rows("ty", kch="10721071")
say(f"读完用时 {time.perf_counter()-t0:.2f}s，{len(rows_ty)} 行")
for r in rows_ty:
    say(f"    {r.kch}-{r.kxh:<3} {r.name:<22} {r.time_text:<16} "
        f"课余量={r.kyl:<3} 教师={r.teacher}")

rule("⑥ 课程信息 —— 课余量（非体育课：必须走页面搜索，这是本次修过的地方）")
for kind, kw, by_kch in (("bx", "30120163", True), ("rx", "高技术战争", False),
                         ("xx", "20310423", True)):
    t0 = time.perf_counter()
    try:
        rows = b.search_course_human(kind, kw, by_kch=by_kch)
        say(f"{COURSE_KINDS[kind]['name']}「{kw}」→ {len(rows)} 行，"
            f"用时 {time.perf_counter()-t0:.2f}s")
        for r in rows[:4]:
            say(f"    {r.kch}-{r.kxh:<3} {r.name:<24} {r.time_text:<18} 课余量={r.kyl}")
    except Exception as e:
        say(f"{COURSE_KINDS[kind]['name']}「{kw}」失败：{type(e).__name__}: {e}")

rule("⑦ 选课模块 —— 课程定位与时间冲突校验（只读，不提交）")
for q in (CourseQuery(kind="ty", kch="10721071", kxh="2", time_text="4-1"),
          CourseQuery(kind="bx", kch="30120163"),
          CourseQuery(kind="rx", name="高技术战争")):
    res = resolve(b, q)
    say(f"查询「{q.describe()}」→ ok={res.ok} 命中{len(res.rows)}条 "
        f"ambiguous={res.ambiguous}")
    if res.reason:
        say(f"    说明：{res.reason[:120]}")
    for r in res.rows[:3]:
        conflicts = find_conflicts(r.time_text, [(c.name, c.time_text) for c in sel])
        say(f"    {r.kch}-{r.kxh} {r.name} {r.time_text} 课余量={r.kyl} "
            f"周次={sorted(parse_weeks(r.time_text))[:5]}... "
            f"冲突={conflicts or '无'}")

rule("⑧ 监听模块 —— 模式三试运行（dry_run，绝不提交）")
cfg = AppConfig()
cfg.xnxq = cur or "2026-2027-1"
cfg.mode = 3
cfg.poll_avg = 3.0
cfg.night_silence = []
cfg.dry_run = True
cfg.headless = True
targets = [CourseEntry(action="grab", kind="ty", kch="10721071", kxh="2",
                       name="三年级男生乒乓球", time_text="4-1")]
if sel:
    # 再拿一门学生已经选上的课当第二个目标，顺便验证非体育课那条搜索路径
    extra = next((c for c in sel if not c.kch.startswith("107")), None)
    if extra:
        targets.append(CourseEntry(action="grab", kind="bx", kch=extra.kch,
                                   name=extra.name, time_text=extra.time_text))
cfg.set_courses(targets)
say(f"目标 {len(targets)} 门：")
for t in targets:
    say(f"    {COURSE_KINDS[t.kind]['name']} {t.kch} {t.name} {t.time_text}")

lines = []
s = Scheduler(cfg, paths, password=sec["pass"],
              on_log=lambda m, l="INFO": lines.append(f"[{l}] {m}"),
              on_status=lambda st: None,
              on_finished=lambda r: say(f"监听结束：{r}"))
s.attach_browser(b)
threading.Timer(45.0, lambda: s.stop("演练结束")).start()
s.run_inline()

rule("监听结果")
say(f"共轮询 {s.status.polls} 次，最终状态 {s.status.state}")
say(f"最后一条状态：{s.status.message[:160]}")
for c in (s.status.courses or []):
    say(f"    {c.get('label','')[:60]}  课余量={c.get('kyl')} {c.get('state','')}")
say("轮询日志（最后 25 条）：")
for l in lines[-25:]:
    say("    " + l[:150])

# 会话还在吗（证明监听没把会话跑坏）
say()
say("监听后会话是否仍然有效：" + str(b.is_logged_in()))

rule("⑨ 关掉浏览器，收尾")
b.stop()
say("完成")

(ROOT / "_diag" / "live-flow.log").write_text("\n".join(LOG), encoding="utf-8")
print(f"\n完整日志已存：{ROOT / '_diag' / 'live-flow.log'}")
