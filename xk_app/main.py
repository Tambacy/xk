# -*- coding: utf-8 -*-
"""
学校选课助手 —— 程序入口
=========================

启动顺序：先建好日志（这样崩溃也能查到），再建应用目录，最后开界面。
"""
from __future__ import annotations

import sys
import traceback


def _ensure_stdio():
    """修好标准输出/错误流，两个坑一起填：

    1) 无控制台（windowed）模式下 sys.stdout/stderr/stdin 是 None。
       Playwright 要起 node 子进程驱动浏览器，子进程需要能继承标准句柄，
       句柄是 None 的话会一直卡住不返回。这里补上指向 NUL 的假句柄。
    2) 有控制台时默认编码是 GBK，print 一个 ✅ 就会抛 UnicodeEncodeError，
       在 windowed 模式下这个异常没人接，程序直接静默崩掉。
       统一改成 UTF-8 + 出错也别抛。
    """
    import os as _os
    for name, mode in (("stdout", "w"), ("stderr", "w"), ("stdin", "r")):
        stream = getattr(sys, name, None)
        if stream is None:
            try:
                setattr(sys, name, open(_os.devnull, mode))
                stream = getattr(sys, name)
            except Exception:
                continue
        if mode != "r":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def selftest() -> int:
    """打包自检：确认随包浏览器能被找到并真的跑起来。

    装完之后如果怀疑有问题，跑 `XkHelper.exe --selftest` 就能看到结论，
    不用图形界面、不需要登录。
    """
    from app.runtime import describe_environment, find_bundled_chromium
    from app.config import Paths
    from app.logging_setup import setup_logging, get_logger

    paths = Paths.build()
    setup_logging(paths.logs, console=True)
    log = get_logger("selftest")

    print("=" * 62)
    print("学校选课助手 自检")
    print("=" * 62)
    ok = True
    for k, v in describe_environment().items():
        print(f"  {k:<26} = {v}")
        log.info("自检 %s = %s", k, v)
    log.info("自检 stdio = out:%s err:%s in:%s",
             type(sys.stdout).__name__, type(sys.stderr).__name__,
             type(getattr(sys, "stdin", None)).__name__)

    exe = find_bundled_chromium()
    if not exe:
        print("  ❌ 没找到随包 Chromium")
        ok = False

    print()
    print("正在尝试启动浏览器…")
    try:
        log.info("自检：import playwright")
        from playwright.sync_api import sync_playwright
        log.info("自检：sync_playwright() 开始")
        with sync_playwright() as p:
            log.info("自检：驱动已就绪")
            kw = {"headless": True}
            if exe:
                kw["executable_path"] = exe
            log.info("自检：launch(%s)", kw)
            b = p.chromium.launch(**kw)
            print(f"  ✅ 浏览器启动成功：{b.version}")
            log.info("自检：浏览器启动成功 %s", b.version)
            ctx = b.new_context()
            page = ctx.new_page()
            page.goto("http://zhjwxk.cic.tsinghua.edu.cn/xklogin.do",
                      wait_until="domcontentloaded", timeout=45000)
            print(f"  ✅ 打开选课系统入口成功：{(page.url or '')[:70]}")
            log.info("自检：网络可达 %s", page.url)
            ctx.close()
            b.close()
    except Exception as e:
        print(f"  ❌ 浏览器自检失败：{type(e).__name__}: {e}")
        log.error("自检失败", exc_info=True)
        ok = False

    print()
    print("=" * 62)
    print("自检通过 ✅" if ok else "自检失败 ❌")
    print(f"日志目录：{paths.logs}")
    print("=" * 62)
    return 0 if ok else 1


def main():
    _ensure_stdio()

    # ---- 打包运行时：先把浏览器路径指好，必须在 Playwright 启动之前 ----
    from app.runtime import setup_frozen_environment, describe_environment
    setup_frozen_environment()

    if "--selftest" in sys.argv:
        return selftest()

    # ---- 高 DPI 适配（必须在创建 QApplication 之前设）----
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    for attr in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        try:
            getattr(Qt, attr)
            setattr(QGuiApplication, attr, True)
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFont, QIcon

    from app.config import Paths, APP_DISPLAY_NAME, APP_VERSION
    from app.logging_setup import setup_logging, install_excepthook, log_environment

    paths = Paths.build()

    # 日志要在最前面建好
    from app.config import AppConfig
    cfg_pre, _ = AppConfig.load(paths.config)
    setup_logging(paths.logs, level=cfg_pre.log_level,
                  keep_days=cfg_pre.keep_log_days)
    install_excepthook()
    # 环境信息一次性合并记录，否则每个键都会把系统信息重复打一遍
    from app.runtime import describe_environment
    env_info = {"app": f"{APP_DISPLAY_NAME} {APP_VERSION}",
                "data_dir": str(paths.root)}
    env_info.update({f"runtime.{k}": v for k, v in describe_environment().items()})
    log_environment(env_info)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(APP_VERSION)

    try:
        app.setFont(QFont("Microsoft YaHei UI", 10))
    except Exception:
        pass

    # 窗口/任务栏图标。exe 自身内嵌了图标，但开发运行时（python main.py）
    # 显示的是 Python 的默认图标，所以显式设一次。
    try:
        from app.runtime import find_asset
        _ico = find_asset("app.ico") or find_asset("app.png")
        if _ico:
            app.setWindowIcon(QIcon(_ico))
    except Exception:
        pass

    from app.gui.theme import stylesheet
    app.setStyleSheet(stylesheet())

    from app.gui.main_window import MainWindow
    win = MainWindow(paths)
    win.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "启动失败", traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
