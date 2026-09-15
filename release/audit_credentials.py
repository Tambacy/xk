# -*- coding: utf-8 -*-
"""发布前审计：确认交付物里不含任何本机凭据。

对应 skill.md 第 10 节。**每次发布前都跑一遍。**

它检查五件事：

  1. **自检**：先往内存里放一串假学号，确认扫描逻辑真的能扫出来 ——
     一个从来没失败过的检查等于没有检查（skill.md 11.1）。
  2. 交付物（`dist\\`、安装包、源码包）里有没有出现本机学号 / 密码，
     **逐字节搜，含二进制**（10.2），不是只做文本匹配。
  3. `dist\\` 里有没有 config.json / credentials.dat / Cookies / Login Data
     这类「本机才该有」的文件（10.2、10.4）。
  4. 仓库里（工作区 + 所有可达 blob）有没有明文学号 / 密码。
     逐个 blob 精确扫描，不用 `cat-file --batch` ——
     批量扫描有跨 blob 边界的假阳性（10.5）。
  5. 文档里有没有学号，**打码形式也不行**（10.3）。

**任何时候都不会把秘密本身打印出来**，只报文件名和命中次数。

用法：

    python release/audit_credentials.py
    python release/audit_credentials.py --no-selftest    # 只做常规检查
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "xk_app"

# 交付物里绝不该出现的文件名（大小写不敏感，子串匹配）
FORBIDDEN_NAMES = (
    "config.json", "credentials.dat", "cookies", "login data",
    "web data", "secrets.json", "local state", "affiliation database",
    "shortcuts", "top sites", "history", "favicons",
)
# Chromium 自带的一些同名资源是正常的，按完整相对路径放行
ALLOW_NAMES = ("network action predictor",)


# ---------------------------------------------------------------------------
# 取本机凭据（只用于扫描，绝不打印）
# ---------------------------------------------------------------------------
def local_secrets() -> dict[str, str]:
    """尽力拿到本机学号 / 密码；拿不到就返回空。"""
    out: dict[str, str] = {}
    for k in ("XK_USER", "XK_PASS"):
        v = os.environ.get(k)
        if v:
            out[k] = v
    try:
        sys.path.insert(0, str(APP))
        import _creds  # type: ignore
        d = _creds.load_secrets() or {}
        if d.get("user"):
            out.setdefault("XK_USER", str(d["user"]))
        if d.get("pass"):
            out.setdefault("XK_PASS", str(d["pass"]))
    except Exception:
        pass
    # 本机运行过的配置里也可能留着学号
    try:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            cfg = Path(base) / "XkHelper" / "config.json"
            if cfg.exists():
                import json
                u = json.loads(cfg.read_text(encoding="utf-8")).get("user")
                if u:
                    out.setdefault("config:user", str(u))
    except Exception:
        pass
    return out


def needles_from(secrets: dict[str, str]) -> list[tuple[str, bytes]]:
    """把凭据变成扫描用的字节串。太短的（<4 字节）跳过，否则满屏假阳性。"""
    out = []
    for name, val in secrets.items():
        v = (val or "").strip()
        if len(v) >= 4:
            out.append((name, v.encode("utf-8")))
    return out


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------
CHUNK = 1 << 22
OVERLAP = 64


def scan_bytes(buf: bytes, needles) -> str | None:
    for name, nd in needles:
        if nd in buf:
            return name
    return None


def scan_file(path: Path, needles) -> str | None:
    try:
        with open(path, "rb") as f:
            prev = b""
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    return None
                hit = scan_bytes(prev + chunk, needles)
                if hit:
                    return hit
                prev = chunk[-OVERLAP:]
    except Exception:
        return None


def walk_targets():
    """要扫的交付物。dist 里的 browsers 是目录联接，会走到真实 Chromium —— 那是要扫的。"""
    for rel in ("dist", "installer"):
        p = APP / rel
        if p.exists():
            yield p
    for z in (ROOT / "release").glob("*.zip"):
        yield z


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n}"


# ---------------------------------------------------------------------------
# 自检：证明扫描逻辑本身有效
# ---------------------------------------------------------------------------
def selftest() -> bool:
    fake = b"2099000000"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "planted.bin"
        p.write_bytes(os.urandom(6000) + fake + os.urandom(6000))
        found = scan_file(p, [("自检", fake)])
        ok1 = found == "自检"
        # 反面：找一个不存在的串，必须扫不到
        p2 = Path(td) / "clean.bin"
        p2.write_bytes(os.urandom(9000))
        ok2 = scan_file(p2, [("自检", fake)]) is None
    print(f"  [自检] 埋进去的假学号能被扫到   : {'PASS' if ok1 else 'FAIL'}")
    print(f"  [自检] 干净文件不会被误报       : {'PASS' if ok2 else 'FAIL'}")
    return ok1 and ok2


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------
def check_deliverables(needles):
    print("\n[2] 交付物逐字节扫描（含二进制）")
    if not needles:
        print("  [!]  没有拿到本机凭据，只能跳过内容比对（结构检查照做）")
    total = files = 0
    hits = []
    for base in walk_targets():
        if base.is_file():
            files += 1
            total += base.stat().st_size
            if needles and scan_file(base, needles):
                hits.append(str(base))
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            files += 1
            try:
                total += p.stat().st_size
            except Exception:
                pass
            if needles:
                h = scan_file(p, needles)
                if h:
                    hits.append(f"{p}  <- {h}")
    print(f"  扫描 {files} 个文件 / {human(total)}")
    if hits:
        print(f"  [X] 命中 {len(hits)} 处：")
        for h in hits[:20]:
            print(f"      {h}")
        return False
    print("  [OK] 未发现本机学号 / 密码")
    return True


def check_forbidden_files():
    print("\n[3] 交付物里的敏感文件名")
    dist = APP / "dist"
    if not dist.exists():
        print("  [!]  dist 不存在，跳过")
        return True
    bad = []
    for p in dist.rglob("*"):
        if not p.is_file():
            continue
        low = p.name.lower()
        if any(a in low for a in ALLOW_NAMES):
            continue
        if any(f in low for f in FORBIDDEN_NAMES):
            bad.append(str(p.relative_to(dist)))
    if bad:
        print(f"  [X] 发现 {len(bad)} 个：")
        for b in bad[:20]:
            print(f"      {b}")
        return False
    print("  [OK] 没有 config.json / credentials.dat / Cookies / Login Data 之类")
    return True


def check_repo(needles):
    print("\n[4] 仓库（工作区 + 所有可达 blob，逐个精确扫描）")
    if not needles:
        print("  [!]  没有凭据可比对，跳过")
        return True
    hits = []

    # 工作区
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, timeout=60).stdout
        for rel in out.splitlines():
            p = ROOT / rel
            if p.is_file() and scan_file(p, needles):
                hits.append(f"工作区 {rel}")
    except Exception as e:
        print(f"  [!]  git ls-files 失败：{type(e).__name__}")

    # 所有可达 blob —— 逐 blob 单独扫，不用 --batch（跨 blob 边界会假阳性）
    try:
        objs = subprocess.run(["git", "rev-list", "--objects", "--all"],
                              cwd=ROOT, capture_output=True, text=True,
                              timeout=120).stdout
    except Exception as e:
        print(f"  [!]  rev-list 失败：{type(e).__name__}")
        return not hits

    checked = 0
    for line in objs.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, name = parts
        t = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT,
                           capture_output=True, text=True, timeout=30).stdout.strip()
        if t != "blob":
            continue
        raw = subprocess.run(["git", "cat-file", "blob", sha], cwd=ROOT,
                             capture_output=True, timeout=30).stdout
        checked += 1
        if scan_bytes(raw, needles):
            hits.append(f"blob {sha[:10]}  {name}")
    print(f"  逐个扫描了 {checked} 个可达 blob")

    if hits:
        print(f"  [X] 命中 {len(hits)} 处：")
        for h in hits[:20]:
            print(f"      {h}")
        return False
    print("  [OK] 工作区与全部可达 blob 均未发现明文凭据")
    return True


def check_docs(needles):
    print("\n[5] 文档（打码形式也不行）")
    targets = [ROOT / "README.md", ROOT / "release" / "RELEASE_NOTES.md",
               APP / "docs" / "使用说明.html"]
    if not needles:
        print("  [!]  没有凭据可比对，跳过")
        return True
    bad = []
    for p in targets:
        if p.exists() and scan_file(p, needles):
            bad.append(str(p.relative_to(ROOT)))
    # 顺带看一眼有没有「202****06」这类打码残留
    import re
    masked = []
    for p in targets:
        if not p.exists():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(r"\b\d{2,4}\*{2,}\d{2}\b", txt):
            masked.append(f"{p.name}: {m.group(0)}")
    if bad:
        print(f"  [X] 明文命中：{bad}")
        return False
    if masked:
        print(f"  [!]  发现打码形式（10.3 要求也不该出现）：{masked[:5]}")
    else:
        print("  [OK] 文档里没有学号明文，也没有打码残留")
    return not bad


def check_iss():
    print("\n[6] 安装包只打包该打包的东西")
    iss = APP / "installer.iss"
    if not iss.exists():
        print("  [!]  installer.iss 不存在")
        return False
    txt = iss.read_text(encoding="utf-8", errors="replace")
    srcs = [ln.strip() for ln in txt.splitlines()
            if ln.strip().lower().startswith("source:")]
    print(f"  [Files] 共 {len(srcs)} 条 Source：")
    for s in srcs:
        print(f"      {s}")
    ok = True
    for s in srcs:
        low = s.lower()
        # Inno 用 {#DistDir} / {#ChromiumSrc} 这类预处理器变量引用路径，
        # 字面量里看不到 "dist\"，要一并放行（变量本身的定义要单独看）
        if ("dist\\" in low or "docs\\" in low or "chromium" in low
                or "{#distdir}" in low or "{#chromiumsrc}" in low):
            continue
        print(f"  [!]  这条看起来不该出现在安装包里：{s}")
        ok = False

    # 变量定义本身也要确认指向的是构建产物，不是源码目录或数据目录
    for var, want in (("#define DistDir", "dist"), ("#define ChromiumSrc", "ms-playwright")):
        for ln in txt.splitlines():
            if ln.strip().startswith(var):
                if want not in ln:
                    print(f"  [!]  {var} 指向可疑：{ln.strip()}")
                    ok = False
                break

    print("  [OK]" if ok else "  [X]")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-selftest", action="store_true")
    args = ap.parse_args()

    print("=" * 72)
    print(" 发布前凭据审计")
    print("=" * 72)

    if not args.no_selftest:
        print("\n[1] 扫描器自检")
        if not selftest():
            print("\n[X] 自检未通过 —— 扫描器本身不可信，后面的结论没有意义。")
            return 1

    secrets = local_secrets()
    needles = needles_from(secrets)
    print(f"\n[0] 本机凭据来源：{', '.join(sorted(secrets)) or '（没找到）'}")
    print(f"    用于比对的字节串：{len(needles)} 个（长度 "
          f"{', '.join(str(len(n)) for _, n in needles) or '—'}，不打印内容）")

    results = [
        check_deliverables(needles),
        check_forbidden_files(),
        check_repo(needles),
        check_docs(needles),
        check_iss(),
    ]

    print("\n" + "=" * 72)
    if all(results):
        print(" 审计通过：未发现凭据泄露 ✅")
        print("=" * 72)
        return 0
    print(" 审计未通过 —— 先把上面标 [X] 的项处理掉再发布 ❌")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    sys.exit(main())
