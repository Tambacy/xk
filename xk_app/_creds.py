# -*- coding: utf-8 -*-
"""本地凭据的统一读取入口（开发期探针与测试专用）
==================================================

**为什么要有这个文件**

`thu_xk/secrets.json` 以前是**明文**学号 + 密码，被 20 个探针/测试直接
`json.load(open(...))` 读取。明文凭据只要落到磁盘上，泄露就只是时间问题。
现在统一走这个模块，三级来源：

    1. 环境变量 XK_USER / XK_PASS        —— CI、临时用，不落盘
    2. Windows DPAPI 加密存储（app.secretstore）—— 默认，只本机本账户能解
    3. 旧的明文 secrets.json                    —— 兼容用，会打印醒目告警

优先级从高到低。**第 3 级只是为了让你能平滑迁移**，迁移完就该把明文删掉
（`python _creds.py --import-legacy` 会自动做这件事）。

用法：

    import _creds
    s = _creds.load_secrets()        # {'user': ..., 'pass': ...}；读不到就是 {}

命令行：

    python _creds.py --status         # 看凭据从哪来（不打印任何秘密）
    python _creds.py --import-legacy  # 把旧明文加密搬进 DPAPI，然后抹掉明文密码
"""
from __future__ import annotations

import json
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

def _legacy_path() -> Path:
    """旧的明文凭据文件（仓库根的 thu_xk/secrets.json）。"""
    return Path(__file__).resolve().parent.parent / "thu_xk" / "secrets.json"


def _candidate_roots() -> list[Path]:
    """可能存放 DPAPI 凭据的应用数据目录，按优先级排列。"""
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
    p = _legacy_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    u, pw = str(d.get("user") or ""), str(d.get("pass") or "")
    if u and pw:
        # 醒目告警：这条路径本身就是要被淘汰的东西
        print(f"[_creds] ⚠ 正在从**明文**文件读取凭据：{p}", file=sys.stderr)
        print("[_creds] ⚠ 请尽快执行 `python _creds.py --import-legacy` "
              "把它搬进 DPAPI 加密存储", file=sys.stderr)
        return {"user": u, "pass": pw}
    return {}


def load_secrets() -> dict:
    """返回 {'user':…, 'pass':…}。读不到就返回 {}，绝不抛异常。"""
    for fn in (_from_env, _from_dpapi, _from_legacy):
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
    if _from_legacy():
        return f"⚠ 明文文件 {_legacy_path()}（不推荐，请迁移）"
    return "（没有可用的凭据）"


# --------------------------------------------------------------------------
# 迁移：明文 → DPAPI，然后抹掉明文
# --------------------------------------------------------------------------

def import_legacy(shred: bool = True) -> int:
    """把旧明文凭据加密写进 DPAPI，然后抹掉明文文件里的密码。

    返回 0 成功、1 失败。
    """
    p = _legacy_path()
    if not p.exists():
        print(f"没有找到旧的明文凭据文件：{p}")
        return 0
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"读不了 {p}：{e}")
        return 1

    user, pw = str(raw.get("user") or ""), str(raw.get("pass") or "")
    if not (user and pw):
        print(f"{p} 里没有可迁移的账号密码（可能已经迁移过了）。")
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app.secretstore import SecretStore
    root = _candidate_roots()[0]
    root.mkdir(parents=True, exist_ok=True)
    ok, msg = SecretStore(root).save(user, pw, remember=True)
    print(f"  加密写入 {root / 'credentials.dat'}：{'成功' if ok else '失败'}（{msg}）")
    if not ok:
        print("  迁移未完成，明文文件保持原样。")
        return 1

    if shred:
        raw["pass"] = ""
        raw["_密码已迁移"] = ("出于安全考虑，明文密码已移除。"
                              "请用 xk_app 的登录界面重新登录（会写入 DPAPI），"
                              "或设置环境变量 XK_USER / XK_PASS。")
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
            print(f"  已抹掉 {p} 中的明文密码。")
        except Exception as e:
            print(f"  抹掉明文失败（请手动删除 {p} 里的 pass 字段）：{e}")
            return 1
    return 0


# --------------------------------------------------------------------------

def main() -> int:
    if "--import-legacy" in sys.argv:
        return import_legacy()
    if "--status" in sys.argv:
        print(f"凭据来源：{credential_source()}")
        d = load_secrets()
        return 0 if d else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
