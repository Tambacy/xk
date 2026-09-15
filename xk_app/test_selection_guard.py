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
print("【6】时间冲突：判据、周次感知、要退的课不算冲突")
print("=" * 78)

from app.courses import find_conflicts, parse_slots, parse_weeks, same_course

# 判据：同一大节的同一小节，且周次有交集
check("同一时段 -> 冲突",
      bool(find_conflicts("4-1(全周)", [("控制工程基础", "4-1(全周)")])))
check("不同大节 -> 不冲突",
      find_conflicts("4-1(全周)", [("控制工程基础", "5-1(全周)")]), [])
check("不同小节 -> 不冲突",
      find_conflicts("4-1(全周)", [("控制工程基础", "4-2(全周)")]), [])
check("周次不重叠 -> 不冲突（前八周 vs 后八周）",
      find_conflicts("4-1(前八周)", [("控制工程基础", "4-1(后八周)")]), [])
check("周次部分重叠 -> 冲突（前八周 vs 全周）",
      bool(find_conflicts("4-1(前八周)", [("控制工程基础", "4-1(全周)")])))
check("单周 vs 双周 -> 不冲突",
      find_conflicts("4-1(单周)", [("控制工程基础", "4-1(双周)")]), [])
check("单周 vs 全周 -> 冲突",
      bool(find_conflicts("4-1(单周)", [("控制工程基础", "4-1(全周)")])))
check("目标课没填时间 -> 不报冲突",
      find_conflicts("", [("控制工程基础", "4-1(全周)")]), [])

# 「要退的课」不算冲突 —— 这是这次要确认的关键行为
TARGET_TIME = "4-1(全周)"
SEL = [
    SelectedCourse(kind="必修", kch="30110012", kxh="1", name="控制工程基础",
                   time_text="4-1(全周)", del_id="2026-2027-1;30110012;1;"),
    SelectedCourse(kind="任选", kch="02090091", kxh="92", name="高技术战争",
                   time_text="5-6(单周)", del_id="2026-2027-1;02090091;92;"),
]
before = find_conflicts(TARGET_TIME, [(c.name, c.time_text) for c in SEL])
check("不排除任何课时，撞上的那门会被报出来",
      len(before) == 1 and "控制工程基础" in before[0])

drop = CourseEntry(action="drop", kind="bx", name="控制工程基础", kch="30110012", kxh="1")
kept = [c for c in SEL if not same_course(c, drop)]
after = find_conflicts(TARGET_TIME, [(c.name, c.time_text) for c in kept])
check("把那门课列进「要退的课」之后，不再报冲突", after, [])

# 认课程的三条线索
check("按课程号认得出来", same_course(SEL[0], CourseEntry(action="drop", kch="30110012")))
check("只填课程名也认得出来", same_course(SEL[0], CourseEntry(action="drop", name="控制工程基础")))
check("课程名 + 课序号认得出来",
      same_course(SEL[0], CourseEntry(action="drop", name="控制工程基础", kxh="1")))
check("课序号对不上就不算同一门",
      same_course(SEL[0], CourseEntry(action="drop", name="控制工程基础", kxh="9")), False)
check("cid 认得出来",
      same_course(SEL[0], CourseEntry(action="drop", resolved_cid="2026-2027-1;30110012;1;")))
check("不相干的课不会被误判", same_course(SEL[0], CourseEntry(action="drop", kch="99999999")), False)

print()
print("=" * 78)
print("【7】静态护栏：return 之后不留死代码")
print("=" * 78)
# 这类问题的危害是**它不报错** —— 代码照常跑，只是那几行永远不执行。
# 「记住密码」失效就是这么来的：一段自动填凭据的代码被挤到 eventFilter 的
# return 之后，保存正常、读回正常，就是没人把它填进输入框。
import ast as _ast

_TERMINAL = (_ast.Return, _ast.Raise, _ast.Continue, _ast.Break)
_BODIES = ("body", "orelse", "finalbody")
_dead = []
_parsed = 0
for _p in sorted(Path(__file__).parent.rglob("*.py")):
    _rel = _p.relative_to(Path(__file__).parent).as_posix()
    if any(x in _rel for x in ("__pycache__", "/build/", "/dist/")):
        continue
    try:
        # utf-8-sig：有文件带 BOM，用 utf-8 读会把 U+FEFF 留在开头导致解析失败
        _tree = _ast.parse(_p.read_text(encoding="utf-8-sig"), filename=str(_p))
    except SyntaxError as _e:
        _dead.append(f"{_rel}:{_e.lineno} 语法错误 {_e.msg}")
        continue
    _parsed += 1
    for _node in _ast.walk(_tree):
        for _attr in _BODIES:
            _body = getattr(_node, _attr, None)
            if not isinstance(_body, list):
                continue
            for _i, _st in enumerate(_body[:-1]):
                if isinstance(_st, _TERMINAL):
                    _dead.append(f"{_rel}:{_body[_i + 1].lineno} "
                                 f"{type(_st).__name__} 之后还有语句")
print(f"     解析了 {_parsed} 个文件")
check("没有不可达语句", _dead, [])
check("确实解析到了文件（自检：别扫了个空）", _parsed > 10, True)

print()
print("=" * 78)
if FAIL:
    print(f"{FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
