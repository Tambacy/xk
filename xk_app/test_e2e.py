# -*- coding: utf-8 -*-
"""
端到端联调：完整走一遍界面流程，连真实教务系统。

    登录 → 读取已选课程 → 选模式三 → 添加课程 → 自动校验 → 确认 → 启动监听 → 停止

全程只读（dry_run=True），不会真的提交任何选课。
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
os.environ["XK_HOME"] = str(ROOT / "data" / "e2e")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtWidgets import QApplication
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

T0 = time.perf_counter()
FAIL = []


def st(msg, ok=None):
    mark = "" if ok is None else ("  ✅" if ok else "  ❌")
    print(f"[{time.perf_counter()-T0:6.1f}s] {msg}{mark}", flush=True)
    if ok is False:
        FAIL.append(msg)


def wait_until(pred, timeout, desc, poll=0.1):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        app.processEvents()
        try:
            if pred():
                return True
        except Exception as e:
            last = e
        time.sleep(poll)
    st(f"等待超时：{desc}" + (f"（{last}）" if last else ""), False)
    return False


out = ROOT / "shots"
out.mkdir(exist_ok=True)


def shot(name):
    for _ in range(3):
        app.processEvents()
    win.grab().save(str(out / f"e2e-{name}.png"))
    st(f"截图 e2e-{name}.png")


import _creds  # 凭据统一从环境变量 / DPAPI 读取
sec = _creds.load_secrets()

print("=" * 72)
print("端到端联调开始")
print("=" * 72)

win = MainWindow(paths)
win.resize(1120, 760)
win.show()
app.processEvents()

# ---------------- 1. 登录 ----------------
st("① 填写登录表单并点击登录")
win.page_login.ed_user.setText(sec["user"])
win.page_login.ed_pwd.setText(sec["pass"])
win.page_login.cb_remember.setChecked(True)
win.page_login.cb_trust.setChecked(True)
shot("1-before-login")
win.page_login._emit()

ok = wait_until(lambda: win.stack.currentIndex() == 1, 120, "登录完成并跳到模式页")
st(f"② 登录成功，当前页 = {win.stack.currentIndex()}（1=模式选择）", ok)
st(f"   已选课程快照：{len(win.page_courses.selected_snapshot)} 门")
shot("2-logged-in")
if not ok:
    print("登录没通过，后面没法继续")
    sys.exit(1)

# ---------------- 2. 选模式三 ----------------
st("③ 选择模式三（长期监听）")
win.on_mode(3)
wait_until(lambda: win.stack.currentIndex() == 2, 10, "进入课程页")
shot("3-courses-empty")

# ---------------- 3. 添加课程并自动校验 ----------------
st("④ 添加目标课程：三年级男生乒乓球 / 10721071 / 课序号 2")
entry = CourseEntry(action="grab", kind="ty", name="三年级男生乒乓球",
                    kch="10721071", kxh="2", time_text="4-1")
win.on_add_course(entry)
ok = wait_until(lambda: (win.results.get(0) or {}).get("ok") is True
                or (win.results.get(0) or {}).get("ambiguous"), 90, "课程校验返回")
r = win.results.get(0) or {}
st(f"⑤ 校验结果：ok={r.get('ok')} ambiguous={r.get('ambiguous')} "
   f"reason={r.get('reason','')[:60]}", r.get("ok") is True)
st(f"   解析到：{entry.resolved_name} {entry.kch}-{entry.kxh} "
   f"{entry.resolved_time} {entry.resolved_teacher}  课余量={entry.resolved_kyl}")
st(f"   时间冲突：{r.get('conflicts') or '无'}")
shot("4-course-validated")

# ---------------- 4. 再添加一门"要退的课" ----------------
st("⑥ 添加一门要退的课：三年级男生冰球 / 10726031 / 2")
drop = CourseEntry(action="drop", kind="ty", name="三年级男生冰球",
                   kch="10726031", kxh="2")
win.on_add_course(drop)
wait_until(lambda: bool((win.results.get(1) or {}).get("ok"))
           or bool((win.results.get(1) or {}).get("reason")), 60, "退课项校验返回")
r1 = win.results.get(1) or {}
st(f"   结果：ok={r1.get('ok')} {str(r1.get('reason'))[:70]}", r1.get("ok") is True)
shot("5-two-courses")

# ---------------- 5. 确认页 ----------------
st("⑦ 进入确认页")
win.page_courses.sp_avg.setValue(3.0)
win.goto(3)
app.processEvents()
shot("6-confirm")

# ---------------- 6. 启动 ----------------
st("⑧ 点击开始运行")
win.page_courses.cb_dry.setChecked(True)      # 试运行，不真提交
win.on_start()
ok = wait_until(lambda: win.stack.currentIndex() == 4, 10, "进入监控页")
st(f"   当前页 = {win.stack.currentIndex()}（4=监控）", ok)
shot("7-monitor-start")

# ---------------- 7. 观察监听 ----------------
st("⑨ 观察监听 40 秒…")
seen_states = set()
end = time.time() + 40
while time.time() < end:
    app.processEvents()
    s = win.page_monitor._last_status or {}
    if s.get("state"):
        seen_states.add(s["state"])
    time.sleep(0.2)
s = win.page_monitor._last_status or {}
st(f"   已轮询 {s.get('polls')} 次，状态集合={sorted(seen_states)}")
st(f"   当前消息：{s.get('message','')}")
st(f"   目标课程状态：{s.get('courses')}")
st("   轮询确实发生了", (s.get("polls") or 0) > 0)
shot("8-monitor-running")

# ---------------- 8. 停止 ----------------
st("⑩ 点击停止")
win.core.do_stop()
wait_until(lambda: (win.page_monitor._last_status or {}).get("state") in
           ("stopped", "success"), 30, "停止生效")
s = win.page_monitor._last_status or {}
st(f"   停止后状态 = {s.get('state')}  共轮询 {s.get('polls')} 次")
shot("9-monitor-stopped")

# ---------------- 9. 诊断包 ----------------
st("⑪ 导出诊断包")
from app.logging_setup import export_diagnostics
z = paths.diagnostics / "e2e-diag.zip"
p = export_diagnostics(z, paths.logs, config_snapshot={"mode": 3, "user": sec["user"]})
size = Path(p).stat().st_size
st(f"   诊断包 {Path(p).name}  {size} 字节")
import zipfile
with zipfile.ZipFile(p) as zf:
    txt = zf.read("environment.txt").decode("utf-8")
st("   诊断包里不含完整学号", sec["user"] not in txt)
st("   诊断包里不含密码", sec["pass"] not in txt)

# ---------------- 收尾 ----------------
st("⑫ 关闭程序")
win.close()
app.processEvents()

print()
print("=" * 72)
if FAIL:
    print(f"❌ {len(FAIL)} 项失败：")
    for x in FAIL:
        print("   -", x)
    sys.exit(1)
print("✅ 端到端联调全部通过")
print("=" * 72)
