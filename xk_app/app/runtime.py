# -*- coding: utf-8 -*-
"""
打包运行时的路径处理
====================

PyInstaller 打包后目录长这样：

    XkHelper.exe
    _internal\\            ← sys._MEIPASS，Python 代码和依赖都在这
        playwright\\driver\\   （node.exe + cli.js）
        browsers\\             （Chromium）
        ...

浏览器不能由 PyInstaller 打进去（427MB，而且会拖慢每次构建），
改由 Inno Setup 直接拷到 `_internal\\browsers`，这里只负责把
PLAYWRIGHT_BROWSERS_PATH 指过去，Playwright 才知道去哪找。
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """打包后的资源根目录（开发时就是项目目录）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def setup_frozen_environment() -> dict:
    """在启动最早期调用。返回诊断信息（日志用）。"""
    info = {"frozen": is_frozen()}
    if not is_frozen():
        return info

    base = bundle_root()
    info["bundle_root"] = str(base)

    # 浏览器目录：优先 _internal\browsers，其次 exe 同级的 browsers
    for cand in (base / "browsers", base.parent / "browsers"):
        if cand.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
            info["browsers_path"] = str(cand)
            break
    else:
        info["browsers_path"] = "（没找到，将回退到用户目录下的 ms-playwright）"

    # 让 Playwright 的 node 驱动别去用户目录找
    if "PLAYWRIGHT_DRIVER_PATH" not in os.environ:
        d = base / "playwright" / "driver"
        if d.is_dir():
            os.environ["PLAYWRIGHT_DRIVER_PATH"] = str(d)
    return info


def find_bundled_chromium() -> str | None:
    """找到随包发布的 Chromium 可执行文件。

    显式指定它可以强制用"完整 Chromium"运行（含无头模式），
    这样安装包只需要带一份浏览器，不用再带一份 headless shell。
    """
    roots = []
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root and os.path.isdir(root):
        roots.append(root)
    # 回退：Playwright 默认的浏览器目录（开发环境，或没随包发布时）
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local:
        roots.append(str(Path(local) / "ms-playwright"))
    patterns = [
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    ]
    for r in roots:
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(r, pat)))
            if hits:
                return hits[-1]
    return None


def chromium_version() -> str | None:
    """从随包 Chromium 的版本清单文件里读出实际版本号。

    chrome-win64 目录下有个 `151.0.7922.34.manifest`，文件名就是版本。
    无头模式下要把 UA 里的 HeadlessChrome 换成同版本的 Chrome，
    版本号必须对得上，不然反而更可疑。
    """
    exe = find_bundled_chromium()
    if not exe:
        return None
    d = Path(exe).parent
    for m in sorted(d.glob("*.manifest")):
        mm = re.match(r"^(\d+\.\d+\.\d+\.\d+)\.manifest$", m.name)
        if mm:
            return mm.group(1)
    return None


def chrome_user_agent() -> str | None:
    """构造一个与随包 Chromium 版本一致的、不带 Headless 的 UA。"""
    v = chromium_version()
    if not v:
        return None
    major = v.split(".")[0]
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


def find_doc(name: str = "使用说明.html") -> str | None:
    """找到随包发布的使用说明（打包后在 _internal\\docs，开发时在项目 docs）。"""
    for base in (bundle_root() / "docs", bundle_root().parent / "docs",
                 bundle_root().parent):
        p = base / name
        if p.exists():
            return str(p)
    return None


def describe_environment() -> dict:
    d = {
        "frozen": is_frozen(),
        "executable": sys.executable,
        "bundle_root": str(bundle_root()),
        "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "(未设置)"),
        "bundled_chromium": find_bundled_chromium() or "(未找到，用默认)",
    }
    return d
