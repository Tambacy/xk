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
win.results = {
    0: {"ok": True, "rows": [{"kyl": 0, "queue": "", "note": "限:2023男生选课"}]},
    1: {"ok": True, "conflicts": ["控制工程基础（4-2(全周)）"],
        "rows": [{"kyl": 0, "queue": ""}]},
    2: {"ok": True, "rows": [{"kyl": -1}]},
}
win.goto(2)
win.page_courses.set_selected_snapshot([object()] * 7)
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
print("OK")
