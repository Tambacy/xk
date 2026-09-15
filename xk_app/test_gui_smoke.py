# -*- coding: utf-8 -*-
"""界面冒烟测试：构建主窗口，逐页渲染成 PNG 检查排版；并模拟一遍完整流程。"""
import os
import sys
import traceback
from pathlib import Path

# 注意：不要用 offscreen —— 那个平台报告 0 个字体，中文会全渲染成方框，
# 看不出真实排版。这里用真实平台，窗口会一闪而过。
os.environ["XK_HOME"] = str(Path(__file__).parent / "data" / "gutest")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer, QDateTime
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QFont

from app.config import Paths, CourseEntry
from app.logging_setup import setup_logging

paths = Paths.build()
setup_logging(paths.logs, console=False)

app = QApplication(sys.argv)
app.setFont(QFont("Microsoft YaHei UI", 10))
from app.gui.theme import stylesheet
app.setStyleSheet(stylesheet())

from app.gui.main_window import MainWindow
from app.gui import motion

# 截图回归必须关掉动效：否则抓到的是动画中间帧。
# （第一版没关，模式页切过去时三张模式卡正好还在淡出，整片不见了。）
motion.ENABLED = False

out = Path(__file__).parent / "shots"
out.mkdir(exist_ok=True)

win = MainWindow(paths)
win.resize(1120, 760)
win.show()


def shot(name):
    for _ in range(3):
        app.processEvents()
    pix = win.grab()
    p = out / f"{name}.png"
    pix.save(str(p))
    print(f"  已渲染 {p.name}  {pix.width()}x{pix.height()}")


print("=" * 60)
print("逐页渲染")
print("=" * 60)

# 1 登录页
win.page_login.ed_user.setText("2020000000")
win.page_login.ed_pwd.setText('*'*10)
win.page_login.begin_progress()
win.page_login.set_progress('已提交，等待服务器响应（这一步有时要几十秒）…')
win.page_login.set_elapsed(23)
win.goto(0)
shot("1-login")

# 2 模式页
win.goto(1)
shot("2-mode")

# 3 课程页（塞几门样例课程，覆盖各种状态）
#
# ⚠ 这里的冲突**必须用真实逻辑算出来**，不能手写。
# 之前这里写死了 conflicts=["控制工程基础（4-2(全周)）"]，而目标是 5-6(单周) ——
# 两者根本不撞，真实 find_conflicts 永远返回空。于是 README 的截图里
# 出现了一个「不可能的冲突」，谁看谁困惑。
win.cfg.mode = 3
entries = [
    CourseEntry(action="grab", kind="ty", name="三年级男生乒乓球", kch="10721071",
                kxh="2", time_text="4-1", resolved=True, resolved_name="三年级男生乒乓球",
                resolved_time="4-1(全周)", resolved_teacher="刘国正", resolved_kyl=0,
                resolved_cid="2026-2027-1;10721071;2;"),
    CourseEntry(action="grab", kind="rx", name="高技术战争", kch="02090091",
                resolved=True, resolved_name="高技术战争", resolved_time="5-6(单周)",
                resolved_teacher="高成耀", resolved_kyl=0,
                resolved_cid="2026-2027-1;02090091;92;"),
    CourseEntry(action="drop", kind="ty", name="三年级男生冰球", kch="10726031",
                kxh="2", resolved=True, resolved_name="三年级男生冰球",
                resolved_time="3-4(全周)", resolved_cid="2026-2027-1;10726031;2;"),
]
win.entries = entries

from app.browser import SelectedCourse
from app.courses import find_conflicts, same_course

# 本学期的已选课程（真实形状的对象，不是占位符 —— 否则列表里会显示成「[—] -」）
SELECTED = [
    SelectedCourse(kind="必修", kch="30110012", kxh="1", name="控制工程基础",
                   time_text="5-6(全周)", teacher="王丹",
                   del_id="2026-2027-1;30110012;1;"),
    SelectedCourse(kind="必修", kch="10421055", kxh="3", name="大学物理",
                   time_text="2-3(全周)", teacher="李强",
                   del_id="2026-2027-1;10421055;3;"),
    SelectedCourse(kind="限选", kch="02090080", kxh="1", name="信号与系统",
                   time_text="1-2(全周)", teacher="张伟",
                   del_id="2026-2027-1;02090080;1;"),
    SelectedCourse(kind="体育课", kch="10726031", kxh="2", name="三年级男生冰球",
                   time_text="3-4(全周)", teacher="许跃昊",
                   del_id="2026-2027-1;10726031;2;"),
]


def real_conflicts(entry):
    """按 core._handle_validate 的同一套规则算冲突：排除掉「要退的课」。"""
    drops = [e for e in entries if e.action == "drop"]
    kept = [c for c in SELECTED if not any(same_course(c, d) for d in drops)]
    return find_conflicts(entry.resolved_time,
                          [(c.name, c.time_text) for c in kept])


win.results = {
    0: {"ok": True, "rows": [{"kyl": 0, "queue": "", "note": "限:2023男生选课"}]},
    # 高技术战争 5-6(单周) 撞上已选的 控制工程基础 5-6(全周)（单周与全周有交集）
    1: {"ok": True, "conflicts": real_conflicts(entries[1]),
        "rows": [{"kyl": 0, "queue": ""}]},
    2: {"ok": True, "rows": [{"kyl": -1}]},
}
print(f"  样例数据：高技术战争 5-6(单周) 的冲突 = {win.results[1]['conflicts']}")
print(f"           乒乓球 4-1(全周) 的冲突 = {real_conflicts(entries[0])}")
win.goto(2)
win.page_courses.set_selected_snapshot(SELECTED)
win.page_courses.set_entries(entries, win.results)
win.page_courses.sp_avg.setValue(60.0)
shot("3-courses")

# 4 确认页
win.cfg.poll_avg = 60.0
win.cfg.night_silence = ["01:00", "06:00"]
win.page_confirm.refresh(win.cfg, entries)
win.goto(3)
shot("4-confirm")

# 5 监控页
win.page_monitor.reset(entries)
win.goto(4)
win.page_monitor.append_log("启动浏览器（后台无窗口）…")
win.page_monitor.append_log("需要登录学校统一身份认证。")
win.page_monitor.append_log("登录成功，落地页：http://zhjwxk.cic.tsinghua.edu.cn/…")
win.page_monitor.append_log("开始长期监听 1 门课，平均间隔 60 秒")
win.page_monitor.append_log("三年级男生乒乓球 10721071-2 4-1(全周) 课余量=0")
win.page_monitor.append_log("夜间静默中，暂停所有请求。", "WARN")
win.page_monitor.append_log("⚡ 检测到课余量！三年级男生乒乓球 4-1 课余量 1", "WARN")
win.page_monitor.append_log("先退课：三年级男生冰球 10726031-2 3-4(全周)")
win.page_monitor.append_log("退课结果：删除选课成功")
win.page_monitor.append_log("提交选课：提交选课成功;")
win.page_monitor.append_log("✅ 抢课成功！三年级男生乒乓球 10721071-2  [整条链路 1832 ms]", "WARN")
win.page_monitor.update_status({
    "state": "success", "message": "已抢到 三年级男生乒乓球 10721071-2 4-1(全周)",
    "polls": 1284, "next_poll_in": 0, "success": ["三年级男生乒乓球"],
    "courses": [{"label": "三年级男生乒乓球 10721071-2 4-1(全周)", "kyl": 0}]})
# 「已运行」由每秒一次的计时器刷新，而这里是瞬间渲染 —— 补一个模拟时长，
# 否则截图里会出现「已完成 / 已运行 —」这种看着别扭的组合。
win.page_monitor.st_run.set("00:41:06")
shot("5-monitor")

# ---- 再验一遍小窗口下的排版 ----
win.resize(940, 640)
for i, n in enumerate(["1-login", "2-mode", "3-courses", "4-confirm", "5-monitor"]):
    win.goto(i)
    shot(f"small-{n}")

print()
print("=" * 60)
print("全部页面渲染完成，图片在", out)
print("=" * 60)

win.core_shutdown = True
try:
    if win.core:
        win.core.shutdown()
        win.core.wait(3000)
except Exception:
    pass
win.close()
app.processEvents()

# ---------------------------------------------------------------------------
# 「记住密码」的往返：保存 → 重启 → 自动填回
#
# 这个功能曾经整个失效过，而且**不报任何错**：自动填凭据的那段代码被挤到
# eventFilter 的 return 之后成了死代码 —— 保存正常、读回正常、就是没人把它
# 填进输入框，表现成「勾了记住密码，下次还得重输」。
# 所以这里必须真的重建一次 MainWindow，只测 store.load() 是测不出来的。
# ---------------------------------------------------------------------------
import shutil
import tempfile

from app.secretstore import SecretStore

print()
print("=" * 60)
print("「记住密码」往返")
print("=" * 60)

_tmp_home = Path(tempfile.mkdtemp(prefix="xk-remember-"))
try:
    _paths = Paths.build(_tmp_home)
    FAKE_USER = "2020000000"
    FAKE_PWD = "Fixture-Pwd-2026!"

    _w = MainWindow(_paths)
    app.processEvents()
    assert _w.page_login.ed_user.text() == "", "全新目录下学号不该有值"
    assert _w.page_login.ed_pwd.text() == "", "全新目录下密码不该有值"
    print("  全新目录：输入框为空            PASS")

    SecretStore(_paths.root).save(FAKE_USER, FAKE_PWD, remember=True)
    _w.close()
    app.processEvents()
    del _w

    _w2 = MainWindow(_paths)
    app.processEvents()
    assert _w2.page_login.ed_user.text() == FAKE_USER, "学号没有自动填回"
    assert _w2.page_login.ed_pwd.text() == FAKE_PWD, "密码没有自动填回"
    assert _w2.page_login.cb_remember.isChecked(), "「记住密码」没有保持勾选"
    print(f"  重启后自动填回 {FAKE_USER} / {'*' * len(FAKE_PWD)}  PASS")
    _w2.close()
    app.processEvents()
    del _w2

    # 不勾「记住密码」时只留学号，密码必须清掉
    SecretStore(_paths.root).save(FAKE_USER, "", remember=False)
    _w3 = MainWindow(_paths)
    app.processEvents()
    assert _w3.page_login.ed_user.text() == FAKE_USER, "学号应该仍然填回"
    assert _w3.page_login.ed_pwd.text() == "", "不记住密码时不该填回密码"
    print("  不勾选时只填学号、不留密码      PASS")
    _w3.close()
    app.processEvents()
finally:
    shutil.rmtree(_tmp_home, ignore_errors=True)

# ---------------------------------------------------------------------------
# 监控页「目标课程」反复重跑不能留旧行
#
# 用户报过：停止监听 → 返回设置 → 再跑一次之后，同一门课在卡片里出现了两次，
# 看着像要抢两次。
#
# 根因是 `clear_layout(..., keep_tail=1)` —— 想留下的是**卡片标题**，
# 但标题在 body 的**最前面**，而 keep_tail 保留的是最后 N 个。于是留下的
# 是最后一条课程，标题反被删掉；每重跑一次就多留一行旧课程。
# 断言里连标题一起比，就是为了守住「留下的必须是标题」这一点。
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("监控页目标课程：反复重跑不留旧行")
print("=" * 60)


def _card_rows(card):
    """卡片 body 里所有 QLabel 的文本，按界面顺序（含标题）。"""
    out = []
    for _i in range(card.body.count()):
        _w = card.body.itemAt(_i).widget()
        if isinstance(_w, QLabel):
            out.append(_w.text())
    return out


def _expect(es):
    return ["目标课程"] + [("退　" if e.action == "drop" else "抢　") + e.label()
                           for e in es]


_mp = win.page_monitor
for _i, _case in enumerate((entries, entries[:2], [entries[1]], [])):
    _mp.reset(list(_case))
    app.processEvents()
    _got = _card_rows(_mp.card_courses)
    _want = _expect(_case)
    assert _got == _want, (f"第 {_i + 1} 次 reset 后卡片内容不对\n"
                           f"  实际={_got}\n  期望={_want}")
    print(f"  reset #{_i + 1}（{len(_case)} 门）行数与内容正确  PASS")

# 顺手确认标题没被吃掉 —— 这正是原 bug 的第二个症状
_mp.reset(list(entries))
app.processEvents()
assert _card_rows(_mp.card_courses)[0] == "目标课程", "卡片标题丢了"
print("  卡片标题仍在                    PASS")

# ---------------------------------------------------------------------------
# 同一门课不能既抢又退
#
# 用户报过：目标课程卡片上同一门课一条「退」一条「抢」，两个页面的截图
# 还互相矛盾 —— 说明清单里真的有两条。
#
# 来路：「本学期已选课程」里点「要退」时只查了「要退」有没有重复，
# 没查它是不是已经在「要抢」里 —— 而抢到之后那门课就会出现在这个列表里。
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("清单自相矛盾：同一门课既抢又退")
print("=" * 60)

from PySide6.QtWidgets import QMessageBox
from app.browser import SelectedCourse

_asked = []
_answer = {"v": QMessageBox.Yes}
# question 和 warning 都要记账 —— 只记 question 的话，
# 「开跑时被拦住」那条断言会因为 warning 没被记录而假失败。
QMessageBox.question = staticmethod(lambda *a, **k: (_asked.append(1), _answer["v"])[1])
QMessageBox.information = staticmethod(lambda *a, **k: (_asked.append(1), None)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: (_asked.append(1), QMessageBox.Ok)[1])


def _mk(action, kch, kxh, name):
    return CourseEntry(action=action, kind="ty", kch=kch, kxh=kxh, name=name,
                       resolved=True, resolved_name=name,
                       resolved_cid=f"2026-2027-1;{kch};{kxh};")


win.entries = [_mk("grab", "10721071", "2", "三年级男生乒乓球")]
win.cfg.set_courses(win.entries)
_asked.clear()
_answer["v"] = QMessageBox.Yes
win.on_drop_requested(SelectedCourse(kind="体育课", kch="10721071", kxh="2",
                                     name="三年级男生乒乓球", time_text="4-1(全周)",
                                     del_id="2026-2027-1;10721071;2;"))
app.processEvents()
assert len(_asked) == 1, "应当就用途冲突询问用户"
assert len(win.entries) == 1, f"不该出现同一门课两条：{len(win.entries)}"
assert win.entries[0].action == "drop", "用途应就地改成「退」，而不是再加一条"
assert win._self_contradictions() == [], "仍存在自相矛盾的条目"
print("  点「要退」不会产生重复条目      PASS")

# 旧配置里已经带着矛盾时，开始运行必须被拦住
win.entries = [_mk("grab", "10721071", "2", "三年级男生乒乓球"),
               _mk("drop", "10721071", "2", "三年级男生乒乓球")]
win.cfg.set_courses(win.entries)
assert len(win._self_contradictions()) == 1, "应当检测到一对矛盾"
_asked.clear()
win.on_start()
app.processEvents()
assert len(_asked) >= 1, "开始运行时应当弹警告"
assert win.stack.currentIndex() == 2, "应当退回预定课程页，而不是开始监控"
print("  带着矛盾开跑会被拦住              PASS")

# ---------------------------------------------------------------------------
# 轮询结果必须按课程号对回标签，不能按下标硬配
#
# 用户报过：目标课程卡片上出现
#     退　三年级男生乒乓球 10721071-2 4-1(全周)　课余量 0
#     抢　三年级男生乒乓球 (10721071-2) 4-1(全周)
# 而他从没把乒乓球加进「要退」—— 只停了一次再开。
#
# 根因：调度器只轮询「要抢的课」，回给界面的 rows 只含这一类；
# 而 course_labels 是**全部条目**。清单是 [退冰球, 抢乒乓] 时按下标配，
# 第 0 条「退冰球」的文字被换成第 0 行「乒乓」的内容 —— 凭空长出一个
# 「退乒乓」，同一门课看起来又退又抢。
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("监控页：要退的课排在前面时，轮询结果不能串行")
print("=" * 60)


def _row_texts():
    out = []
    for _i in range(win.page_monitor.card_courses.body.count()):
        _w = win.page_monitor.card_courses.body.itemAt(_i).widget()
        if isinstance(_w, QLabel):
            out.append(_w.text())
    return out


def _status_row(kch, kxh, name, time_text, kyl):
    return {"label": f"{name} {kch}-{kxh} {time_text}",
            "kch": kch, "kxh": kxh, "kyl": kyl, "state": ""}


_drop_b = CourseEntry(action="drop", kind="ty", kch="10726031", kxh="2",
                      name="三年级男生冰球", resolved=True,
                      resolved_name="三年级男生冰球", resolved_time="3-4(全周)",
                      resolved_cid="2026-2027-1;10726031;2;")
_grab_p = CourseEntry(action="grab", kind="ty", kch="10721071", kxh="2",
                      name="三年级男生乒乓球", resolved=True,
                      resolved_name="三年级男生乒乓球", resolved_time="4-1(全周)",
                      resolved_cid="2026-2027-1;10721071;2;")

# 「要退」排在「要抢」前面 —— 正是会串行的顺序
win.page_monitor.reset([_drop_b, _grab_p])
app.processEvents()
win.page_monitor.update_status({
    "state": "monitoring", "message": "监听中", "polls": 1, "next_poll_in": 30.0,
    "courses": [_status_row("10721071", "2", "三年级男生乒乓球", "4-1(全周)", 0)],
    "success": []})
app.processEvents()
_rows = _row_texts()
for _r in _rows:
    print(f"     {_r}")
assert len(_rows) == 3, f"应当只有 标题 + 2 门：{len(_rows)}"
assert _rows[1].startswith("退　三年级男生冰球"), f"第 1 条被串行了：{_rows[1]}"
assert _rows[2].startswith("抢　三年级男生乒乓球") and "课余量 0" in _rows[2], \
    f"第 2 条没拿到课余量：{_rows[2]}"
assert not any(x.startswith("退　三年级男生乒乓球") for x in _rows), "凭空出现了「退　乒乓」"
assert sum(1 for x in _rows if "10721071" in x) == 1, "同一门课出现了两次"
print("  要退的课不会被串行成抢的课      PASS")

print()
print("OK")
