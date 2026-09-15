# -*- coding: utf-8 -*-
"""本地凭据的统一读取入口（开发期探针与测试专用）
==================================================

**为什么要有这个文件**

早期版本把学号密码**明文**写在仓库根的一个 json 里，被二十多个探针/测试直接
`json.load(open(...))` 读取。明文凭据只要落到磁盘上，泄露就只是时间问题。
现在统一走这个模块，两级来源：

    1. 环境变量 XK_USER / XK_PASS        —— CI、临时用，不落盘
    2. Windows DPAPI 加密存储（app.secretstore）—— 默认，只本机本账户能解

优先级从高到低。**不再支持读取明文文件** —— 那一级只会让「统一走 DPAPI」
有名无实；迁移完成后就该把它去掉。

用法：

    import _creds
    s = _creds.load_secrets()        # {'user': ..., 'pass': ...}；读不到就是 {}

命令行：

    python _creds.py --status         # 看凭据从哪来（不打印任何秘密）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "XkHelper"


def _fix_stdio():
    """Windows 控制台默认 GBK，打印 ⚠ 之类的字符会直接抛 UnicodeEncodeError。

    （这正是 README 里记的第 10 条坑：windowed 模式下没人接这个异常，
    程序会静默崩掉，日志断在半截。）
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_stdio()


# --------------------------------------------------------------------------
# 位置
# --------------------------------------------------------------------------

def _candidate_roots() -> list[Path]:
    """可能存放 DPAPI 凭据的应用数据目录，按优先级排列。

    只列当前目录名就够了：改名前的旧目录由 `app.config.app_root()` 负责
    一次性搬迁，走到这里时它已经不存在了。
    """
    out: list[Path] = []
    override = os.environ.get("XK_HOME")
    if override:
        out.append(Path(override))
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        out.append(Path(base) / APP_DIR_NAME)
    out.append(Path.home() / ".local" / "share" / APP_DIR_NAME)
    # 去重且保持顺序
    seen, uniq = set(), []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


# --------------------------------------------------------------------------
# 三级读取
# --------------------------------------------------------------------------

def _from_env() -> dict:
    u, p = os.environ.get("XK_USER", ""), os.environ.get("XK_PASS", "")
    if u and p:
        return {"user": u, "pass": p}
    return {}


def _from_dpapi() -> dict:
    """从 DPAPI 加密存储读。任何失败都当作「没有」，不抛。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from app.secretstore import SecretStore
    except Exception:
        return {}
    for root in _candidate_roots():
        try:
            if not (root / "credentials.dat").exists():
                continue
            d = SecretStore(root).load()
            if d.get("user") and d.get("pass"):
                return {"user": d["user"], "pass": d["pass"]}
        except Exception:
            continue
    return {}


def _from_legacy() -> dict:
    """已废弃：曾经支持从旧的明文凭据文件读取，现已移除。

    那个文件里的密码本来就是明文落盘的，留着它只会让「凭据统一走 DPAPI」
    这件事有名无实。迁移完成后这一级就没有存在必要了。
    """
    return {}


def load_secrets() -> dict:
    """返回 {'user':…, 'pass':…}。读不到就返回 {}，绝不抛异常。"""
    for fn in (_from_env, _from_dpapi):
        d = fn()
        if d:
            return d
    return {}


def credential_source() -> str:
    """凭据来自哪里（给人看的，不含任何秘密值）。"""
    if _from_env():
        return "环境变量 XK_USER / XK_PASS"
    if _from_dpapi():
        for root in _candidate_roots():
            if (root / "credentials.dat").exists():
                return f"DPAPI 加密存储（{root / 'credentials.dat'}）"
        return "DPAPI 加密存储"
    return "（没有可用的凭据）"


# --------------------------------------------------------------------------

def main() -> int:
    if "--status" in sys.argv:
        print(f"凭据来源：{credential_source()}")
        d = load_secrets()
        return 0 if d else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
