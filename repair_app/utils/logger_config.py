"""
logger_config.py — 结构化日志系统
Stage 4.2 v2.1：三级输出 / 按日期滚动 / JSON 结构化 / 模块名+行号自动注入
"""

from __future__ import annotations
import os
import sys

try:
    from repair_app.utils.resource_path import get_data_dir
except ImportError:
    def get_data_dir():
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.parent

try:
    from loguru import logger
    _LOGURU_AVAILABLE = True
except ImportError:
    _LOGURU_AVAILABLE = False
    import logging
    logger = logging.getLogger("csam")
    logger.setLevel(logging.DEBUG)


LOG_DIR = os.path.join(str(get_data_dir()), "logs")
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

JSON_FORMAT = (
    '{{"time": "{time:YYYY-MM-DDTHH:mm:ss.SSSZ}", '
    '"level": "{level}", "module": "{name}", '
    '"function": "{function}", "line": {line}, '
    '"message": "{message}"}}'
)


def setup_logging(
    level: str | None = None,
    app_log: bool = True,
    error_log: bool = True,
    console: bool = True,
    json_log: bool = False,
) -> None:
    """配置日志系统。

    Args:
        level: 最低日志级别。未指定时从 CSAM_LOG_LEVEL 环境变量读取，默认 INFO。
        app_log: 是否输出 app.log（全部）
        error_log: 是否输出 error.log（仅 ERROR+）
        console: 是否输出到控制台
        json_log: 是否输出 JSON 格式日志文件
    """
    if level is None:
        level = os.environ.get("CSAM_LOG_LEVEL", "INFO")
    os.makedirs(LOG_DIR, exist_ok=True)

    if _LOGURU_AVAILABLE:
        logger.remove()  # 清除默认 handler

        if app_log:
            logger.add(
                os.path.join(LOG_DIR, "app_{time:YYYY-MM-DD}.log"),
                format=LOG_FORMAT,
                level=level,
                rotation="10 MB",
                retention="30 days",
                compression="zip",
                enqueue=True,
            )

        if error_log:
            logger.add(
                os.path.join(LOG_DIR, "error_{time:YYYY-MM-DD}.log"),
                format=LOG_FORMAT,
                level="ERROR",
                rotation="10 MB",
                retention="60 days",
                compression="zip",
                enqueue=True,
            )

        if console:
            logger.add(
                sys.stderr,
                format=LOG_FORMAT,
                level=level,
                colorize=True,
            )

        if json_log:
            logger.add(
                os.path.join(LOG_DIR, "structured_{time:YYYY-MM-DD}.jsonl"),
                format=JSON_FORMAT,
                level=level,
                rotation="10 MB",
                retention="30 days",
                enqueue=True,
            )

        logger.info("日志系统初始化完成")
    else:
        # 退化到标准 logging
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
        ))
        logger.addHandler(handler)
        # 退化模式也输出到文件
        file_handler = logging.FileHandler(
            os.path.join(LOG_DIR, "app.log"), encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
        ))
        logger.addHandler(file_handler)
        logger.info("日志系统初始化完成 (fallback: logging)")


def get_logger(name: str = "csam"):
    """获取带模块名的 logger（自动注入模块名+行号）。"""
    if _LOGURU_AVAILABLE:
        return logger.bind(name=name)
    return logging.getLogger(name)


# 模块级便捷函数
def info(msg: str, **kwargs) -> None:
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).info(msg, **kwargs)
    else:
        logger.info(msg)

def debug(msg: str, **kwargs) -> None:
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).debug(msg, **kwargs)
    else:
        logger.debug(msg)

def warning(msg: str, **kwargs) -> None:
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).warning(msg, **kwargs)
    else:
        logger.warning(msg)

def error(msg: str, **kwargs) -> None:
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).error(msg, **kwargs)
    else:
        logger.error(msg)

def exception(msg: str, **kwargs) -> None:
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).exception(msg, **kwargs)
    else:
        logger.exception(msg)
