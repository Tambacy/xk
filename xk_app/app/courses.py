# -*- coding: utf-8 -*-
"""
课程定位与校验
==============

学生输入的信息可能不完整：课程名 / 任课教师 / 上课时间 / 课程号 / 课序号 / 课程种类，
只要**足以唯一定位到一门课**就行，否则明确告诉学生还缺什么。

定位流程：
  1. 按课程种类选页面（必修/限选/任选/体育/重修）
  2. 有课程号 → 用课程号搜；否则用课程名搜（中文必须走页面搜索框，见下）
  3. 用教师 / 上课时间 / 课序号 进一步筛选
  4. 0 条 → 报"没找到"；多条 → 报"信息不够，请补充"

关于搜索方式（实测结论）：
  * 体育课页支持把 p_kch 放进 URL 直接筛选，一次页面加载 0.6 秒 —— 轮询用这条快路径
  * 必修/限选/任选**不认** URL 参数（带上 p_kch、page=-1 都返回默认列表或空），
    必须在页面搜索框里打字再点「查询」，浏览器会用页面自身的 GBK 编码提交 POST，
    服务端才认。任选课尤其明显：不搜索永远是「没有记录」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .browser import CapacityRow, COURSE_KINDS, KIND_BY_NAME, ScholarBrowser, PageError

# 每周节次：学校一节课的位置用 "星期-节次" 表示，如 4-1 = 星期四第 1 大节
SLOT_RE = re.compile(r"(\d)\s*-\s*(\d)")
WEEK_TAG_RE = re.compile(r"[（(]([^）)]*)[）)]")


@dataclass
class CourseQuery:
    """用户想抢的一门课。除 kind 外都可以留空。"""
    kind: str = "ty"                       # bx/xx/rx/ty/cx
    name: str = ""
    teacher: str = ""
    time_text: str = ""                    # 如 "4-1"
    kch: str = ""
    kxh: str = ""

    def describe(self) -> str:
        parts = [COURSE_KINDS.get(self.kind, {}).get("name", self.kind)]
        if self.name:
            parts.append(self.name)
        if self.kch:
            parts.append(f"课程号{self.kch}")
        if self.kxh:
            parts.append(f"课序号{self.kxh}")
        if self.teacher:
            parts.append(self.teacher)
        if self.time_text:
            parts.append(self.time_text)
        return " / ".join(parts)

    def is_empty(self) -> bool:
        return not any([self.name, self.kch, self.kxh, self.teacher, self.time_text])


@dataclass
class ResolveResult:
    rows: list[CapacityRow] = field(default_factory=list)
    reason: str = ""            # 失败原因（给学生看的）
    ambiguous: bool = False     # 找到了但信息不够唯一（需要学生补充）

    @property
    def ok(self) -> bool:
        return bool(self.rows) and not self.ambiguous


# --------------------------------------------------------------------------
# 上课时间解析
# --------------------------------------------------------------------------

def parse_slots(time_text: str) -> list[tuple[int, int]]:
    """'4-1(全周)' -> [(4,1)]；'2-4(全周),2-3(全周)' -> [(2,4),(2,3)]"""
    return [(int(d), int(p)) for d, p in SLOT_RE.findall(time_text or "")]


def parse_weeks(time_text: str, total: int = 16) -> set[int]:
    """把 '(全周)/(前八周)/(后八周)/(单周)/(双周)/(1-11周)' 解析成周次集合。"""
    weeks: set[int] = set()
    for tag in WEEK_TAG_RE.findall(time_text or ""):
        tag = tag.strip()
        if not tag:
            continue
        if "全周" in tag:
            weeks |= set(range(1, total + 1))
        if "前八周" in tag or "前半" in tag:
            weeks |= set(range(1, 9))
        if "后八周" in tag or "后半" in tag:
            weeks |= set(range(9, total + 1))
        if "单周" in tag:
            weeks |= {w for w in range(1, total + 1) if w % 2 == 1}
        if "双周" in tag:
            weeks |= {w for w in range(1, total + 1) if w % 2 == 0}
        m = re.match(r"^(\d+)\s*-\s*(\d+)\s*周?$", tag)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            weeks |= set(range(a, b + 1))
    if not weeks:
        weeks = set(range(1, total + 1))
    return weeks


def same_course(selected, entry) -> bool:
    """判断一条「已选课程」是不是清单里某个条目所指的那门课。

    清单条目的信息可能不全（学生常常只填一个课程名），所以三条线索
    任一命中就算：
      · 课程号一致
      · 课程名包含 + 课序号一致（课序号没填就只看名字）
      · 校验时拿到的 cid 与已选记录的 del_id 一致

    校验冲突和运行时挑「让位课」用的是同一个判断，
    分开写迟早会漂移成两套行为。
    """
    skch = str(getattr(selected, "kch", "") or "")
    ekch = str(getattr(entry, "kch", "") or "")
    if ekch and skch == ekch:
        return True
    ename = getattr(entry, "name", "") or ""
    if ename and ename in (getattr(selected, "name", "") or ""):
        ekxh = str(getattr(entry, "kxh", "") or "")
        if not ekxh or str(getattr(selected, "kxh", "") or "") == ekxh:
            return True
    ecid = getattr(entry, "resolved_cid", "") or ""
    if ecid and ecid == (getattr(selected, "del_id", "") or ""):
        return True
    return False


def find_conflicts(target_time: str, others: Iterable[tuple[str, str]]) -> list[str]:
    """判断 target_time 与其它课程时间是否冲突。

    others 是 (课程名, 上课时间) 序列，返回冲突的课程名列表。

    判据是「同一大节的同一小节」且「周次有交集」——
    第 4 周周四第 1 节 和 第 5 周周四第 1 节 不算冲突。
    """
    t_slots = parse_slots(target_time)
    if not t_slots:
        return []
    t_weeks = parse_weeks(target_time)
    hits = []
    for name, tm in others:
        o_slots = parse_slots(tm)
        if not o_slots:
            continue
        common_slot = set(t_slots) & set(o_slots)
        if not common_slot:
            continue
        if t_weeks & parse_weeks(tm):
            hits.append(f"{name}（{tm}）")
    return hits


# --------------------------------------------------------------------------
# 定位课程
# --------------------------------------------------------------------------

def _match(row: CapacityRow, q: CourseQuery) -> bool:
    if q.kch and row.kch != q.kch:
        return False
    if q.kxh and str(row.kxh).strip() != str(q.kxh).strip():
        return False
    if q.name and q.name not in (row.name or ""):
        return False
    if q.teacher and q.teacher not in (row.teacher or ""):
        return False
    if q.time_text:
        want = set(parse_slots(q.time_text))
        have = set(parse_slots(row.time_text))
        if want and have and not (want & have):
            return False
        # 时间文字完全对不上（例如 4-1 vs 4-2）也算不匹配
        if want and have and want != have:
            return False
    return True


def fetch_candidates(browser: ScholarBrowser, q: CourseQuery) -> list[CapacityRow]:
    """把该课程种类下可能相关的行都取回来。

    实测结论（2026-09-14，对着真实页面量过）：
      * 体育课页认 URL 里的课程号，会把数据直接筛成目标课那几行 —— 快路径
      * 必修 / 限选 / 任选**不认** URL 参数，但返回的是「默认候选列表」；
        实测必修课的默认列表里就包含目标课的 4 个课堂，所以在列表里找目标课
        才是对的（以前写的"非体育课一律走搜索框"会拿回 14 行无关课程）
      * 页面上的「查询」按钮 onclick 指向的函数在某些页面上根本没定义
        （点了毫无反应），所以只能当兜底手段
    """
    # 快路径：体育课页认 URL 里的课程号，一次加载约 0.3 秒
    if q.kind == "ty" and q.kch:
        return browser.read_capacity_rows("ty", kch=q.kch)

    # 只给了课程名：没法靠列表定位，必须走搜索框
    if not q.kch:
        if not q.name:
            raise PageError("至少需要课程号或课程名才能搜索")
        return browser.search_course_human(q.kind, q.name, by_kch=False)

    rows = browser.read_capacity_rows(q.kind)
    if any(r.kch == q.kch for r in rows):
        return rows

    # 默认列表里没有 → 再试搜索框
    try:
        found = browser.search_course_human(q.kind, q.kch, by_kch=True)
        if found:
            return found
    except Exception:
        pass
    return rows


def resolve(browser: ScholarBrowser, q: CourseQuery) -> ResolveResult:
    """定位唯一课程。返回所有匹配的课堂（同一门课的不同课序号）。"""
    if q.is_empty():
        return ResolveResult(reason="请至少填写课程名或课程号。")

    try:
        rows = fetch_candidates(browser, q)
    except PageError as e:
        return ResolveResult(reason=str(e))
    except Exception as e:
        return ResolveResult(reason=f"查询失败：{e}")

    # 先按课程号精确锁定（如果给了）
    if q.kch:
        rows = [r for r in rows if r.kch == q.kch] or rows

    matched = [r for r in rows if _match(row=r, q=q)]

    if not matched:
        if not rows:
            return ResolveResult(reason=f"没有查到相关课程。"
                                        f"（{COURSE_KINDS[q.kind]['name']}，关键词："
                                        f"{q.kch or q.name}）可能是课程号/课程名有误，"
                                        f"或本学期未开课。")
        names = sorted({f"{r.name}({r.kch})" for r in rows})[:6]
        return ResolveResult(reason=f"找到了课程，但按你填的条件没匹配上。"
                                    f"该关键词下的课程有：{'、'.join(names)}。"
                                    f"请检查教师 / 上课时间 / 课序号是否写错。")

    # 匹配到多门不同课程号 → 必须让学生说清楚是哪一门
    distinct_kch = {r.kch for r in matched}
    if len(distinct_kch) > 1:
        names = sorted({f"{r.name}({r.kch})" for r in matched})[:6]
        return ResolveResult(rows=matched, ambiguous=True,
                             reason=f"匹配到多门课程：{'、'.join(names)}。请补充课程号。")

    # 同一门课但有多个课堂，而学生没指明是哪个 → 也要补
    if len(matched) > 1 and not q.kxh and not q.time_text:
        secs = "、".join(sorted({r.kxh for r in matched}))
        return ResolveResult(
            rows=matched, ambiguous=True,
            reason=f"「{matched[0].name}」有 {len(matched)} 个课堂（课序号 {secs}），"
                   f"上课时间分别是 "
                   f"{'、'.join(r.time_text for r in matched)}。"
                   f"请补充课序号或上课时间。")

    return ResolveResult(rows=matched)


def pick_section(rows: Sequence[CapacityRow], kxh: str = "", time_text: str = "") -> CapacityRow | None:
    for r in rows:
        if kxh and str(r.kxh) == str(kxh):
            return r
    for r in rows:
        if time_text and set(parse_slots(r.time_text)) == set(parse_slots(time_text)):
            return r
    return rows[0] if rows else None


def describe_rows(rows: Sequence[CapacityRow]) -> str:
    return "；".join(f"{r.kch}-{r.kxh} {r.name} {r.time_text} 课余量{r.kyl}" for r in rows[:4])
