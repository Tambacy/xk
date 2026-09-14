# -*- coding: utf-8 -*-
"""离线回归测试：抢课决策的安全护栏（不联网、不登录、不碰真实账号）

这里守的是**最危险**的一类问题：拿错了课的 cid 去退课 / 提交。
课序号都是 0/1/2 这种小数字，一旦页面返回的是别的课程，`pick_section`
很容易在无关课程里撞上一个相同的课序号 —— 那就会真的改掉学生的选课结果。
所以 `_read_target` 必须有一道"拿回来的就是目标课程号"的守门。

顺便覆盖：回滚时的类别还原、服务端硬拒绝不重试。

    python test_selection_guard.py
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.browser import CapacityRow, SelectedCourse
from app.config import AppConfig, CourseEntry, Paths
from app.logging_setup import setup_logging
from app.scheduler import HARD_FAIL_MARKERS, Scheduler, phase_allows_select

FAIL = 0


def check(label, got, want=True):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label:<56} 实际={got!r}"
          + ("" if ok else f"  期望={want!r}"))


class FakeBrowser:
    """假浏览器：返回预先给好的行，并记录被要求提交了什么。

    list_rows   —— 课程页面默认列表返回的内容
    search_rows —— 搜索框返回的内容
    分开是为了验证"先读默认列表、找不到再搜索"这个策略。
    """

    def __init__(self, rows, submit_result="提交选课成功;", fail_kinds=(),
                 search_rows=None):
        self.rows = list(rows)
        self.search_rows = None if search_rows is None else list(search_rows)
        self.submit_result = submit_result
        self.fail_kinds = set(fail_kinds)
        self.submitted = []
        self.searched = []
        self.listed = []

    def read_capacity_rows(self, kind, *, kch="", kcm="", kxh="", navigate=True):
        self.listed.append((kind, kch))
        return list(self.rows)

    def search_course_human(self, kind, keyword, *, by_kch=False):
        self.searched.append((kind, keyword, by_kch))
        return list(self.rows if self.search_rows is None else self.search_rows)

    def submit_selection(self, kind, cid, **kw):
        # 真实现里点提交前会先确认页面上真的有这个 cid；找不到就抛错，
        # 所以"逐个类别试"不会误选到别的课。fail_kinds 模拟"这一类页面上没有"。
        self.submitted.append((kind, cid, kw.get("kch", "")))
        return "页面上找不到课程" if kind in self.fail_kinds else self.submit_result

    def is_on_list_page(self, kind, kch=""):
        return False


paths = Paths.build()
setup_logging(paths.logs, console=False)

cfg = AppConfig()
cfg.xnxq = "2026-2027-1"

TARGET = CourseEntry(action="grab", kind="ty", kch="10721071", kxh="2",
                     name="三年级男生乒乓球", time_text="4-1",
                     resolved_cid="2026-2027-1;10721071;2;")


def row(kch, kxh, name, t="4-1(全周)", kyl=1):
    return CapacityRow(kch=kch, kxh=kxh, name=name, time_text=t, kyl=kyl,
                       cid=f"2026-2027-1;{kch};{kxh};")


def sched(browser):
    s = Scheduler(cfg, paths)
    s.browser = browser
    return s


print("=" * 78)
print("【1】选课阶段判断（回归）")
print("=" * 78)
for text, want in [
    ("当前选课阶段：本科生补退选（第一阶段） 2026年09月14日13时开始", True),
    ("当前选课阶段：本科生正选 2026年09月14日13时开始", True),
    ("当前选课阶段：本科生选课报名阶段 2026年09月10日13时开始", False),
    ("当前选课阶段：本科生补退选（第二阶段）", False),
    ("现在不是选课阶段", False),
    ("选课已结束", False),
    ("", None),
]:
    check(f"phase_allows_select({text[:22]!r}…)", phase_allows_select(text), want)

print()
print("=" * 78)
print("【2】守门：页面返回的不是目标课，就绝不能拿去提交")
print("=" * 78)
r, _ = sched(FakeBrowser([row("10721071", "2", "三年级男生乒乓球")]))._read_target(TARGET)
check("返回目标课 -> 接受", r is not None and r.kch == "10721071")

# 最危险：URL 筛选没生效，页面给的是别的课，但课序号恰好撞上
r, _ = sched(FakeBrowser([row("99999999", "2", "毫不相干的课", kyl=5)]))._read_target(TARGET)
check("课序号撞上的别的课 -> 拒绝", r is None)

# 没有精确匹配时，pick_section 会回退到 rows[0]，也必须被拦下
r, _ = sched(FakeBrowser([row("88888888", "7", "另一门课", "2-3(全周)", 9)]))._read_target(TARGET)
check("无匹配时不再回退到 rows[0]", r is None)

# 学生只填了课程名、没填课程号：靠校验时回填的 resolved_cid 守门
noname = CourseEntry(action="grab", kind="ty", kch="", time_text="4-1",
                     resolved_cid="2026-2027-1;10721071;2;")
r, _ = sched(FakeBrowser([row("99999999", "2", "别的课", kyl=3)]))._read_target(noname)
check("课程号为空时用 resolved_cid 守门", r is None)

print()
print("=" * 78)
print("【3】取数策略：先读默认列表，找不到再搜索（按实测结论）")
print("=" * 78)
# 体育课：URL 带课程号会把数据直接筛好 —— 快路径，不搜索
s = sched(FakeBrowser([row("10721071", "2", "三年级男生乒乓球")]))
s._read_rows(CourseEntry(action="grab", kind="ty", kch="10721071"))
check("体育课走 URL 快路径（不搜索）", s.browser.searched == [])
check("体育课确实带了课程号参数", s.browser.listed == [("ty", "10721071")])

# 必修课：默认列表里就有目标课 -> 直接用，不搜索
# （实测：必修页 URL 参数无效，但默认列表含目标课的 4 个课堂）
s = sched(FakeBrowser([row("30120163", "4", "控制工程基础", "4-2(全周)"),
                       row("20120193", "1", "机械设计基础A(2)", "5-2(全周)")]))
s._read_rows(CourseEntry(action="grab", kind="bx", kch="30120163"))
check("必修课命中的是默认列表（没搜索）", s.browser.searched == [])
check("必修课读的是不带参数的列表页", s.browser.listed == [("bx", "")])

# 任选课：默认列表里没有 -> 先按课程号搜，再按课程名搜
s = sched(FakeBrowser([], search_rows=[row("02090091", "92", "高技术战争", "5-6(单周)")]))
s._read_rows(CourseEntry(action="grab", kind="rx", kch="02090091", name="高技术战争"))
check("默认列表没有时会去搜索", len(s.browser.searched) >= 1)
check("第一次按课程号搜", s.browser.searched[0] == ("rx", "02090091", True))

# 课程号搜不到、课程名搜得到 -> 应该再试一次课程名（实测任选课就是这样）
class OnlyNameSearch(FakeBrowser):
    def search_course_human(self, kind, keyword, *, by_kch=False):
        self.searched.append((kind, keyword, by_kch))
        if by_kch:
            return []
        return [row("20310423", "0", "流体力学", "1-2(全周)")]


s = sched(OnlyNameSearch([]))
got = s._read_rows(CourseEntry(action="grab", kind="xx", kch="20310423", name="流体力学"))
check("按号搜不到时会再按课程名搜",
      s.browser.searched == [("xx", "20310423", True), ("xx", "流体力学", False)])
check("按课程名搜到了目标课", any(r.kch == "20310423" for r in got))

# 两种都搜不到 -> 退回默认列表（守门会兜住）
s = sched(FakeBrowser([], search_rows=[]))
got = s._read_rows(CourseEntry(action="grab", kind="rx", kch="99999999", name="不存在的课"))
check("都搜不到时不抛异常", isinstance(got, list))
check("尝试了两种搜索方式", len(s.browser.searched), 2)

print()
print("=" * 78)
print("【4】回滚：类别认得出就直奔目标，认不出就逐个试")
print("=" * 78)
victim = SelectedCourse(kind="", kch="02090091", kxh="92", name="高技术战争",
                        time_text="5-6(单周)", del_id="2026-2027-1;02090091;92;")
s = sched(FakeBrowser([], fail_kinds=("ty", "rx", "bx")))
msg = s._reselect(victim, TARGET)
tried = [k for k, _cid, _kch in s.browser.submitted]
check("属性列为空时继续往下试", len(tried) > 1)
check("第一个仍是目标课类别（保持原顺序）", tried[0] == "ty")
check("一路试到成功", "成功" in msg)
print("      尝试顺序：", " -> ".join(tried))

# 实测踩到的坑：回滚时必须把**被退课程的课程号**带上。
# 不带的话体育课页打开的是"全部体育课"列表（18 页），目标课根本不在上面，
# 回滚会一次都成功不了（实测连续 5 个类别全失败）。
s = sched(FakeBrowser([], fail_kinds=("ty",)))
s._reselect(SelectedCourse(kind="", kch="10726031", kxh="2", name="三年级男生冰球",
                           del_id="2026-2027-1;10726031;2;"), TARGET)
check("回滚时带上了被退课程的课程号",
      s.browser.submitted[0][2], "10726031")

s = sched(FakeBrowser([]))
s._reselect(SelectedCourse(kind="任选", kch="02090091", kxh="92", name="高技术战争",
                           del_id="2026-2027-1;02090091;92;"), TARGET)
check("「任选」（没写「任选课」）也能认出来", s.browser.submitted[0][0] == "rx")
check("任选课回滚也带课程号", s.browser.submitted[0][2], "02090091")

s = sched(FakeBrowser([]))
s._reselect(SelectedCourse(kind="体育课", kch="10726031", kxh="2", name="冰球",
                           del_id="2026-2027-1;10726031;2;"), TARGET)
check("「体育课」识别为 ty", s.browser.submitted[0][0] == "ty")
check("认出来之后只试一次", len(s.browser.submitted) == 1)

print()
print("=" * 78)
print("【5】服务端硬拒绝不再白白重试")
print("=" * 78)
for msg, should_retry in [
    ("10721071是体育课，只能选一门,不能提交 !", False),
    ("该门课程在选课记录中不存在！", False),
    ("请输入正确的验证码", False),
    ("当前不是选课阶段", False),
    ("提交选课失败，请稍后再试", True),
    ("Timeout 超时，请重试", True),
]:
    hit = any(k in msg for k in HARD_FAIL_MARKERS)
    check(f"「{msg[:22]}」-> {'重试' if should_retry else '不重试'}", (not hit) == should_retry)

print()
print("=" * 78)
if FAIL:
    print(f"{FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
