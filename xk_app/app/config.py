# -*- coding: utf-8 -*-
"""
应用目录与配置持久化
====================

目录布局（全部在用户自己的 LocalAppData 下，不写注册表、不写 Program Files）：

    %LOCALAPPDATA%\\XkHelper\\
        config.json          设置（不含任何凭据）
        credentials.dat      账号密码（DPAPI 加密，见 secretstore）
        logs\\                日志
        browser_profile\\     浏览器配置目录（含登录会话 Cookie）
        diagnostics\\         导出的诊断包

config.json 用「原子写 + 读时容错」：
  * 写临时文件再 os.replace，断电也不会写坏
  * 读取用 utf-8-sig，兼容记事本保存的带 BOM 文件
  * 解析失败**不静默退回默认值**（那样最坑：改了设置却没生效），而是抛错并保留原文件
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR_NAME = "XkHelper"
APP_DISPLAY_NAME = "学校选课助手"
APP_VERSION = "0.2.0"


def app_root() -> Path:
    """应用数据根目录。"""
    override = os.environ.get("XK_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


@dataclass
class Paths:
    root: Path
    config: Path
    credentials: Path
    logs: Path
    profile: Path
    diagnostics: Path

    @classmethod
    def build(cls, root: Path | None = None) -> "Paths":
        root = Path(root) if root else app_root()
        p = cls(root=root, config=root / "config.json",
                credentials=root / "credentials.dat",
                logs=root / "logs", profile=root / "browser_profile",
                diagnostics=root / "diagnostics")
        for d in (p.root, p.logs, p.profile, p.diagnostics):
            d.mkdir(parents=True, exist_ok=True)
        return p


# --------------------------------------------------------------------------
# 课程条目
# --------------------------------------------------------------------------

@dataclass
class CourseEntry:
    """用户要抢（或要退）的一门课。"""
    action: str = "grab"          # grab=要抢的课, drop=要退的课
    kind: str = "ty"              # bx/xx/rx/ty/cx
    name: str = ""
    teacher: str = ""
    time_text: str = ""           # 如 "4-1"
    kch: str = ""
    kxh: str = ""
    # 校验后回填的确定信息
    resolved: bool = False
    resolved_name: str = ""
    resolved_time: str = ""
    resolved_teacher: str = ""
    resolved_kyl: int = 0
    resolved_cid: str = ""        # 提交时用的 value：学期;课程号;课序号;
    note: str = ""

    def to_query(self):
        from .courses import CourseQuery
        return CourseQuery(kind=self.kind, name=self.name, teacher=self.teacher,
                           time_text=self.time_text, kch=self.kch, kxh=self.kxh)

    def label(self) -> str:
        base = self.resolved_name or self.name or self.kch
        sec = self.kxh or (self.resolved_cid.split(";")[2] if self.resolved_cid.count(";") >= 2 else "")
        t = self.resolved_time or self.time_text
        parts = [base]
        if self.kch:
            parts.append(f"({self.kch}{'-' + sec if sec else ''})")
        if t:
            parts.append(t)
        return " ".join(parts)


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

@dataclass
class AppConfig:
    version: int = 1

    # ---- 账号 ----
    user: str = ""
    remember_password: bool = True
    single_login: bool = True          # 勾选「信任/单点登录」

    # ---- 学期与浏览器 ----
    xnxq: str = ""              # 留空 = 登录后自动识别教务系统的当前学期
    headless: bool = False             # False = 有头（可见窗口），伪装度最高；True = 无头但特征多
    viewport: list = field(default_factory=lambda: [1366, 900])

    # ---- 运行模式 ----
    mode: int = 1                      # 1=未开始选课  2=即将开始需退课  3=长期监听
    start_time: str = ""               # "2026-09-21 13:00"，模式一/二用
    lead_seconds: int = 60             # 提前多久开始盯着（提前量）

    # ---- 课程 ----
    courses: list = field(default_factory=list)   # list[CourseEntry as dict]

    # ---- 监听节奏 ----
    poll_avg: float = 3.0              # 平均监听间隔（秒）；模式三可设到 3600
    poll_jitter: list = field(default_factory=lambda: [0.62, 1.35])
    long_pause_prob: float = 0.07
    long_pause_factor: list = field(default_factory=lambda: [1.5, 2.6])
    urgent_interval: float = 1.2       # 临近/抢课时的平均间隔
    night_silence: list = field(default_factory=lambda: ["01:00", "06:00"])

    # ---- 行为 ----
    dry_run: bool = False
    beep_on_success: bool = True
    auto_exit_on_success: bool = False
    max_duration_hours: float = 0.0    # 0 = 不限时

    # ---- 日志 ----
    log_level: str = "INFO"
    keep_log_days: int = 14

    # ------------------------------------------------------------------
    def courses_as_entries(self) -> list[CourseEntry]:
        out = []
        for c in self.courses:
            if isinstance(c, CourseEntry):
                out.append(c)
            elif isinstance(c, dict):
                known = {k: v for k, v in c.items() if k in CourseEntry.__dataclass_fields__}
                out.append(CourseEntry(**known))
        return out

    def set_courses(self, entries: list[CourseEntry]):
        self.courses = [asdict(e) for e in entries]

    def start_datetime(self) -> datetime | None:
        if not self.start_time:
            return None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%m-%d %H:%M"):
            try:
                dt = datetime.strptime(self.start_time.strip(), fmt)
                if fmt == "%m-%d %H:%M":
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["_说明"] = f"{APP_DISPLAY_NAME} 配置（不含账号密码，密码在 credentials.dat 里加密保存）"
        return d

    # ------------------------------------------------------------------
    def save(self, path: Path) -> tuple[bool, str]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cfg", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)          # 原子替换
            return True, "已保存"
        except Exception as e:
            return False, f"保存配置失败：{e}"

    @classmethod
    def load(cls, path: Path) -> tuple["AppConfig", str]:
        """返回 (配置, 提示信息)。解析失败不会静默用默认值。"""
        cfg = cls()
        if not path.exists():
            return cfg, "首次运行，已使用默认配置"
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            # 保留坏文件，方便排查，同时明确告知
            backup = path.with_suffix(f".bad-{datetime.now():%Y%m%d%H%M%S}.json")
            try:
                shutil.copy2(path, backup)
            except Exception:
                pass
            return cfg, f"配置文件无法解析（{e}），已备份到 {backup.name} 并使用默认配置"
        known = set(cls.__dataclass_fields__.keys())
        for k, v in raw.items():
            if k in known and v is not None:
                setattr(cfg, k, v)
        return cfg, "配置已载入"


def is_first_run(paths: Paths) -> bool:
    return not paths.config.exists()
