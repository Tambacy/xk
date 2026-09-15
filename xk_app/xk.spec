# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置
====================

要点：
  * playwright 的 node 驱动必须一起打进去，否则程序起不来
  * Chromium **不**由 PyInstaller 打（427MB，会把每次构建拖成几分钟），
    改由 Inno Setup 直接拷进 `_internal\\browsers`
  * 裁掉所有用不到的 Qt 模块，安装包能小一大截
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)

# 调试用：设 XK_CONSOLE=1 构建一个带控制台的版本，能看到真实报错
CONSOLE = os.environ.get("XK_CONSOLE") == "1"

# ---------------- playwright 驱动 ----------------
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

datas = list(pw_datas)
binaries = list(pw_binaries)
hiddenimports = list(pw_hidden)

# ---------------- 自己的包 ----------------
hiddenimports += collect_submodules("app")

# ---------------- 使用说明（随包发布，界面里可一键打开）----------------
_doc = ROOT / "docs" / "使用说明.html"
if _doc.exists():
    datas.append((str(_doc), "docs"))

# ---------------- 应用图标 ----------------
# exe 的图标由下面 EXE(icon=…) 内嵌；窗口图标要在运行时单独 setWindowIcon，
# 所以 png 也得打进去，否则打包后窗口图标取不到文件。
for _name in ("app.png", "app.ico"):
    _p = ROOT / "assets" / _name
    if _p.exists():
        datas.append((str(_p), "assets"))

# ---------------- exe 的版本资源 ----------------
# 不写这个，右键 XkHelper.exe → 属性 → 详细信息 里是空白（没有产品名、没有版本）。
# 版本号从 app/config.py 现读，避免又多出一处要手工同步的地方（见 skill.md 8.2）。
import re as _re
_src = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
APP_VER = _re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _src).group(1)
_v = (APP_VER.split(".") + ["0", "0", "0"])[:4]
_t = ", ".join(str(int(x)) for x in _v)
_ver_file = ROOT / "build" / "version_info.txt"
_ver_file.parent.mkdir(parents=True, exist_ok=True)
_ver_file.write_text(
    "VSVersionInfo(\n"
    f"  ffi=FixedFileInfo(filevers=({_t}), prodvers=({_t}), mask=0x3f, flags=0x0,\n"
    "                  OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
    "  kids=[StringFileInfo([StringTable('080404B0', [\n"
    "      StringStruct('CompanyName', '个人自用'),\n"
    "      StringStruct('FileDescription', '学校选课助手'),\n"
    f"      StringStruct('FileVersion', '{APP_VER}'),\n"
    "      StringStruct('InternalName', 'XkHelper'),\n"
    "      StringStruct('OriginalFilename', 'XkHelper.exe'),\n"
    "      StringStruct('ProductName', '学校选课助手'),\n"
    f"      StringStruct('ProductVersion', '{APP_VER}')])]),\n"
    "    VarFileInfo([VarStruct('Translation', [2052, 1200])])]\n"
    ")\n", encoding="utf-8")

# ---------------- 裁掉用不到的大件 ----------------
excludes = [
    # Qt 里没用到的模块（PySide6 默认会塞一堆进来）
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtSvgWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    # 其它用不到的科学计算栈
    "tkinter", "matplotlib", "numpy", "scipy", "pandas", "PIL",
    "IPython", "jupyter", "notebook", "pytest", "setuptools", "pip",
    "PyQt5", "PyQt6", "wx",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XkHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,        # 默认不要黑窗口；调试时设 XK_CONSOLE=1
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico") if (ROOT / "assets" / "app.ico").exists() else None,
    version=str(_ver_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="XkHelper",
)
