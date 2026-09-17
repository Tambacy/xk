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


def logical_screen() -> tuple[int, int, float]:
    """本机显示器的**逻辑**尺寸与缩放比，返回 (宽, 高, dpr)。

    为什么需要它：浏览器窗口如果比屏幕还大，页面里就会出现
    `outerWidth > screen.width` —— 窗口比屏幕还宽，物理上不成立，
    是一眼可判的自动化特征。所以窗口尺寸必须按屏幕钳一下。

    为什么要「逻辑」而不是物理尺寸：`screen.width` 在 CSS 像素里报的是
    物理宽度除以缩放比（本机 2560/1.5 = 1707），窗口尺寸用的也是同一个
    单位，两边必须都用逻辑值才对得上。

    拿不到就返回 (0, 0, 1.0)，调用方按「不钳」处理。
    """
    try:
        import ctypes
        u = ctypes.windll.user32
        try:
            u.SetProcessDPIAware()
        except Exception:
            pass
        w = int(u.GetSystemMetrics(0))       # SM_CXSCREEN
        h = int(u.GetSystemMetrics(1))       # SM_CYSCREEN
        if w <= 0 or h <= 0:
            return 0, 0, 1.0
        dpi = 96
        try:
            dpi = int(u.GetDpiForSystem())   # Win10+；150% 缩放时返回 144
        except Exception:
            dpi = 96
        dpr = (dpi / 96.0) if dpi else 1.0
        if dpr <= 0:
            dpr = 1.0
        return max(1, int(round(w / dpr))), max(1, int(round(h / dpr))), dpr
    except Exception:
        return 0, 0, 1.0




def find_doc(name: str = "使用说明.html") -> str | None:
    """找到随包发布的使用说明（打包后在 _internal\\docs，开发时在项目 docs）。"""
    for base in (bundle_root() / "docs", bundle_root().parent / "docs",
                 bundle_root().parent):
        p = base / name
        if p.exists():
            return str(p)
    return None


def find_asset(name: str) -> str | None:
    """找到随包发布的资源文件（图标等）。

    打包后在 `_internal\\assets`，开发时在项目 `assets`。
    exe 本身已经内嵌了图标，但窗口图标要单独设 —— 否则开发运行时
    任务栏显示的是 Python 的默认图标。
    """
    for base in (bundle_root() / "assets", bundle_root().parent / "assets"):
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


# --------------------------------------------------------------------------
# 系统剪贴板（给「中文用粘贴输入」用）
# --------------------------------------------------------------------------
#
# 为什么要这个：Playwright 的 locator.type / keyboard.type 遇到中文这类
# 非 ASCII 字符时，是直接往渲染进程塞文本（Input.insertText），页面上只会
# 看到 beforeinput / input 两个事件、inputType 是 "insertText"，
# **没有任何 keydown / keyup**。真人不可能这样打出中文 —— 那是 IME 干的活。
#
# 而「复制课程名 → 粘贴到搜索框」是真人常见操作，粘贴产生的事件是完整且
# 正常的：keydown(Control) / keydown(v) / paste / input(inputType=
# insertFromPaste) / keyup(v) / keyup(Control)。
#
# 所以这里直接操作 **Windows 系统剪贴板**（浏览器外面），再让浏览器自己
# 处理 Ctrl+V —— 全程不碰页面 JS，剪贴板内容对页面而言就是真的。

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040


def _clip_api():
    """取 user32/kernel32 并**补齐签名**。

    必须显式声明 restype/argtypes：否则 64 位下 GlobalAlloc 返回的句柄会
    被当成 32 位 int 截断，GlobalLock 拿到的是废值，直接访问违例。
    """
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.CloseClipboard.argtypes = []
    u32.CloseClipboard.restype = wintypes.BOOL
    u32.EmptyClipboard.argtypes = []
    u32.EmptyClipboard.restype = wintypes.BOOL
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.GetClipboardData.restype = wintypes.HANDLE
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.restype = wintypes.BOOL
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.restype = wintypes.HGLOBAL
    return ctypes, u32, k32


def get_clipboard_text() -> str | None:
    """读当前剪贴板文本。读不到（是图片、为空、被别的进程占用）返回 None。"""
    try:
        ctypes, u32, k32 = _clip_api()
        if not u32.OpenClipboard(None):
            return None
        try:
            h = u32.GetClipboardData(_CF_UNICODETEXT)
            if not h:
                return None
            p = k32.GlobalLock(h)
            if not p:
                return None
            try:
                return ctypes.wstring_at(p)
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return None


def set_clipboard_text(text: str) -> bool:
    """把文本写进系统剪贴板。成功返回 True。"""
    try:
        ctypes, u32, k32 = _clip_api()
        data = text.encode("utf-16-le") + b"\x00\x00"
        if not u32.OpenClipboard(None):
            return False
        h = None
        try:
            if not u32.EmptyClipboard():
                return False
            h = k32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, len(data))
            if not h:
                return False
            p = k32.GlobalLock(h)
            if not p:
                return False
            try:
                ctypes.memmove(p, data, len(data))
            finally:
                k32.GlobalUnlock(h)
            # SetClipboardData 成功后所有权归系统，不能再 GlobalFree
            if not u32.SetClipboardData(_CF_UNICODETEXT, h):
                k32.GlobalFree(h)
                return False
            h = None
            return True
        finally:
            u32.CloseClipboard()
    except Exception:
        return False
