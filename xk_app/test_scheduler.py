# -*- coding: utf-8 -*-
"""调度器测试：先验证离线逻辑，再在真实环境干跑模式三。"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.config import AppConfig, CourseEntry, Paths
from app.scheduler import phase_allows_select, phase_time_range, Scheduler, State
from app.logging_setup import setup_logging

FAIL = 0


def check(label, got, want=True):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label:<52} 实际={got!r}" + ("" if ok else f" 期望={want!r}"))


print("=" * 74)
print("【1】选课阶段判断")
print("=" * 74)
cases = [
    ("当前选课阶段：本科生补退选（第一阶段） 2026年09月14日13时开始", True),
    ("当前选课阶段：本科生正选 2026年09月14日13时开始", True),
    ("当前选课阶段：本科生选课报名阶段 2026年09月10日13时开始", False),
    ("当前选课阶段：本科生补退选（第二阶段）", False),
    ("现在不是选课阶段", False),
    ("选课已结束", False),
    ("", None),
    ("当前选课阶段：本科生选课调整", True),
]
for text, want in cases:
    check(f"phase_allows_select({text[:26]!r}…)", phase_allows_select(text), want)

print()
print("【2】阶段时间解析")
t1, t2 = phase_time_range("当前选课阶段：本科生补退选（第一阶段）  "
                          "2026年09月14日13时开始  2026年09月21日08时结束")
print("     起 =", t1, " 止 =", t2)
check("起点正确", str(t1), "2026-09-14 13:00:00")
check("终点正确", str(t2), "2026-09-21 08:00:00")

print()
print("=" * 74)
print("【3】该退哪些课（让位逻辑）")
print("=" * 74)
cfg = AppConfig()
cfg.xnxq = "2026-2027-1"
entries = [
    CourseEntry(action="grab", kind="ty", kch="10721071", kxh="2",
                name="三年级男生乒乓球", time_text="4-1"),
    CourseEntry(action="drop", kind="rx", kch="02090091", name="高技术战争"),
]
cfg.set_courses(entries)

paths = Paths.build()
setup_logging(paths.logs, console=False)

s = Scheduler(cfg, paths, password="")
from app.browser import SelectedCourse, CapacityRow

selected = [
    SelectedCourse(kind="必修", kch="30120163", kxh="4", name="控制工程基础",
                   time_text="4-2(全周)", del_id="2026-2027-1;30120163;4;"),
    SelectedCourse(kind="任选", kch="02090091", kxh="92", name="高技术战争",
                   time_text="5-6(单周)", del_id="2026-2027-1;02090091;92;"),
    SelectedCourse(kind="", kch="10726031", kxh="2", name="三年级男生冰球",
                   time_text="3-4(全周)", del_id="2026-2027-1;10726031;2;"),
    SelectedCourse(kind="必修", kch="40990001", kxh="1", name="某门与乒乓撞时间的课",
                   time_text="4-1(全周)", del_id="2026-2027-1;40990001;1;"),
]
target = CapacityRow(kch="10721071", kxh="2", name="三年级男生乒乓球",
                     time_text="4-1(全周)", kyl=1,
                     cid="2026-2027-1;10721071;2;")

victims = s._victims(entries[0], selected, target)
names = [v.name for v in victims]
print("     目标：三年级男生乒乓球 4-1(全周)")
print("     已选：控制工程基础 4-2 / 高技术战争 5-6 / 三年级男生冰球 3-4 / 某门撞时间的课 4-1")
print("     需要退：", names)
check("退掉显式指定的课（高技术战争）", "高技术战争" in names)
check("退掉与目标冲突的课", "某门与乒乓撞时间的课" in names)
check("退掉另一门体育课（一学期只能一门）", "三年级男生冰球" in names)
check("不该动不冲突的必修课", "控制工程基础" in names, False)

print()
print("=" * 74)
print("【4】真实环境干跑模式三（约 25 秒）")
print("=" * 74)

import json
import _creds  # 凭据统一从环境变量 / DPAPI 读取
sec = _creds.load_secrets()
cfg.user = sec["user"]
cfg.mode = 3
cfg.poll_avg = 3.0
cfg.dry_run = True
cfg.headless = True
cfg.night_silence = []          # 测试时关掉，现在是白天本来也不受影响
cfg.set_courses([CourseEntry(action="grab", kind="ty", kch="10721071", kxh="2",
                             name="三年级男生乒乓球", time_text="4-1")])

lines = []
pushes = []          # 每次推给界面的状态字典，用来验证推送顺序
s2 = Scheduler(cfg, paths, password=sec["pass"],
               on_log=lambda m, l="INFO": (lines.append(f"[{l}] {m}"), print("     ", m)),
               on_status=lambda st: pushes.append(dict(st)),
               on_finished=lambda r: print("     完成：", r))
s2.start()
deadline = time.time() + 25
while time.time() < deadline and s2.is_running():
    time.sleep(1)
    st = s2.status
    print(f"     状态={st.state:<11} 轮询={st.polls:<3} {st.message[:50]}")
s2.stop()
s2.join(20)

check("实际发起了轮询", s2.status.polls > 0)
check("运行中状态正确", s2.status.state in (State.MONITORING, State.STOPPED, State.SUCCESS, "monitoring", "stopped", "success"))
check("没有异常退出", any("运行出错" in l for l in lines), False)

# 推送顺序：message 里写的秒数必须和 next_poll_in 对得上。
#
# 这是那个 bug 的准确特征 —— 界面同一块地方显示两个值：上面那行文字写
# 「下次 260.5s 后」，下面的「距下次检查」却是一根横杠。因为 _push() 在
# next_poll_in 赋值之前执行，字段里是上一轮的（第一轮是 0）。
#
# 不能简单地断言 next_poll_in > 0：轮询本身耗时超过一个周期时，
# remain 合法地就是 0（实测重新登录那一次就会）。要比的是两者一致。
import re as _re


def _secs_in_message(msg):
    m = _re.search(r"下次\s*([\d.]+)\s*s", msg or "")
    return float(m.group(1)) if m else None


_bad_push = []
for p in pushes:
    if p.get("state") not in ("monitoring", "waiting"):
        continue
    want = _secs_in_message(p.get("message"))
    if want is None:
        continue                      # 「夜间静默中」这类消息里没有秒数
    got = float(p.get("next_poll_in") or 0)
    if abs(want - got) > 1.0:         # 消息里四舍五入过，给 1 秒容差
        _bad_push.append({"message": p.get("message"), "next_poll_in": got})

_checked = sum(1 for p in pushes
               if p.get("state") in ("monitoring", "waiting")
               and _secs_in_message(p.get("message")) is not None)
print(f"     共推送 {len(pushes)} 次状态；可比对的 {_checked} 次，"
      f"对不上的 {len(_bad_push)} 次")
check("message 里的秒数与 next_poll_in 一致", _bad_push, [])
check("确实比对到了（自检：别扫了个空）", _checked > 0, True)
print()
print("    最近日志：")
for l in lines[-10:]:
    print("     ", l)

print()
print("=" * 74)
if FAIL:
    print(f"{FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
