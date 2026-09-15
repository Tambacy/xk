# -*- coding: utf-8 -*-
"""
日志系统
========

目标：**出问题能溯源、能纠正**。

设计：
  * 每天一个文件，自动轮转，只保留最近 N 天（默认 14 天）
  * 分两个通道：
      - helper-*.log    正常业务日志（轮询结果、决策、提交、报错）
      - trace-*.log     浏览器动作流水（每一次导航/点击/输入），只留 3 天
  * **所有写出去的文本都过一遍脱敏**：密码、Cookie、密文一旦登记，
    在日志里永远显示成 ***，从机制上杜绝"日志泄密"
  * 高频轮询按 DEBUG 记流水，INFO 只在关键时刻/汇总时记 —— 否则跑一夜日志能撑爆磁盘
  * 未捕获异常自动落盘（含堆栈），GUI 里可一键导出诊断包

诊断包里**只含日志和脱敏后的环境信息**，绝不含账号密码。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from .secretstore import redactor

BUSINESS_LOGGER = "xk"
TRACE_LOGGER = "xk.trace"

_FMT = "%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class RedactingFilter(logging.Filter):
    """把日志文本里出现的敏感值全部替换掉。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = redactor.scrub(msg)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        # 顺带把异常文本也洗一遍
        if record.exc_text:
            record.exc_text = redactor.scrub(record.exc_text)
        return True


class DropNoiseFilter(logging.Filter):
    """把第三方库的噪音压掉。"""

    NOISY = ("urllib3", "httpx", "httpcore", "asyncio", "PIL")

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(n) for n in self.NOISY)


def setup_logging(log_dir: str | Path, *, level: int = logging.INFO,
                  trace: bool = True, keep_days: int = 14,
                  console: bool = False) -> dict:
    """初始化日志。返回 {'log_dir':…, 'business':…, 'trace':…}"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)
    redact = RedactingFilter()
    noise = DropNoiseFilter()

    business_path = log_dir / "helper.log"
    fh = logging.handlers.TimedRotatingFileHandler(
        business_path, when="midnight", backupCount=keep_days, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(redact)
    fh.setLevel(level)
    root.addHandler(fh)

    trace_path = None
    if trace:
        trace_path = log_dir / "trace.log"
        th = logging.handlers.TimedRotatingFileHandler(
            trace_path, when="midnight", backupCount=3, encoding="utf-8")
        th.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", datefmt=_DATEFMT))
        th.addFilter(redact)
        trace_logger = logging.getLogger(TRACE_LOGGER)
        trace_logger.handlers.clear()
        trace_logger.addHandler(th)
        trace_logger.setLevel(logging.DEBUG)
        trace_logger.propagate = False

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.addFilter(redact)
        ch.setLevel(level)
        root.addHandler(ch)

    for name in ("urllib3", "httpx", "httpcore", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)

    log = logging.getLogger(BUSINESS_LOGGER)
    log.info("=" * 70)
    log.info("日志系统已启动")
    log.info(f"日志目录：{log_dir}   级别：{logging.getLevelName(level)}   保留 {keep_days} 天")
    log.info(f"系统：{platform.platform()}   Python {platform.python_version()}")
    return {"log_dir": log_dir, "business": business_path, "trace": trace_path}


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{BUSINESS_LOGGER}.{name}" if name else BUSINESS_LOGGER)


def get_trace_logger() -> logging.Logger:
    return logging.getLogger(TRACE_LOGGER)


def install_excepthook():
    """未捕获的异常也写进日志，不然崩溃了什么都查不到。"""
    log = get_logger("crash")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("未捕获异常：%s: %s", exc_type.__name__, exc,
                  exc_info=(exc_type, exc, tb))
    sys.excepthook = hook

    # 线程里抛的异常也要记
    import threading
    _orig = threading.excepthook

    def thook(args):
        log.error("线程未捕获异常：%s: %s", args.exc_type.__name__, args.exc_value,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        try:
            _orig(args)
        except Exception:
            pass
    threading.excepthook = thook


def log_environment(extra: dict | None = None):
    """把排查问题需要的环境信息记下来（不含任何凭据）。"""
    log = get_logger("env")
    info = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        info["screen"] = f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
    except Exception:
        pass
    if extra:
        info.update(extra)
    for k, v in info.items():
        log.info("  环境 %s = %s", k, v)
    return info


def export_diagnostics(zip_path: str | Path, log_dir: str | Path,
                       config_snapshot: dict | None = None,
                       extra_text: str = "") -> str:
    """打包诊断信息，方便发给别人排查。只含日志和脱敏配置。"""
    log_dir = Path(log_dir)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(log_dir.glob("*.log*")):
            try:
                z.write(f, f"logs/{f.name}")
            except Exception:
                pass
        env = [
            f"导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"系统: {platform.platform()}",
            f"Python: {sys.version}",
            f"打包运行: {bool(getattr(sys, 'frozen', False))}",
            "",
        ]
        if config_snapshot:
            import json
            env.append("配置快照（不含账号密码）：")
            env.append(json.dumps(config_snapshot, ensure_ascii=False, indent=2))
        if extra_text:
            env.append("")
            env.append(extra_text)
        z.writestr("environment.txt", redactor.scrub("\n".join(env)))
        z.writestr("README.txt",
                   "这是选课助手导出的诊断包。\n"
                   "内含运行日志与环境信息，已自动脱敏，不含账号密码。\n")
    return str(zip_path)


def format_exc_short(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()
