"""
logger_config.py — 结构化日志系统
Stage 4.2 v2.1：三级输出 / 按日期滚动 / JSON 结构化 / 模块名+行号自动注入

P3-4 增强：
  - InterceptHandler: stdlib logging → loguru 路由，统一所有模块日志
  - export_logs(): 日志打包导出为 zip，供用户提交反馈
  - 修复 CSAM_LOG_LEVEL 环境变量失效问题
"""

from __future__ import annotations
import os
import sys
import logging
import zipfile
import datetime
from pathlib import Path

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
    logger = logging.getLogger("csam")
    logger.setLevel(logging.DEBUG)


def _resolve_log_dir() -> str:
    """优先使用 PathManager 的统一日志目录，失败时回退到 get_data_dir()/logs。"""
    try:
        from repair_app.software.path_manager import PathManager
        return str(PathManager.get_instance().logs_dir)
    except Exception:
        return os.path.join(str(get_data_dir()), "logs")


LOG_DIR = _resolve_log_dir()
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


# ============================================================
# P3-4: InterceptHandler — stdlib logging → loguru 路由
# ============================================================
class InterceptHandler(logging.Handler):
    """将 stdlib logging 调用重定向到 loguru。

    解决 bridge/* 等模块直接使用 logging.getLogger("csam.bridge.*") 时，
    在 loguru 模式下日志脱离主日志管线的问题。

    用法：在 setup_logging 中 logging.basicConfig(handlers=[InterceptHandler()])
    """

    def __init__(self):
        super().__init__()
        self._level_map = {
            "DEBUG": "DEBUG",
            "INFO": "INFO",
            "WARNING": "WARNING",
            "ERROR": "ERROR",
            "CRITICAL": "CRITICAL",
        }

    def emit(self, record):
        """Forward a stdlib LogRecord to loguru."""
        # 获取对应的 loguru level
        level_name = record.levelname
        loguru_level = self._level_map.get(level_name, "INFO")
        # 查找原始调用栈
        frame, depth = None, 6
        while frame is None and depth > 0:
            try:
                frame = sys._getframe(depth)
            except ValueError:
                break
            depth -= 1
        if frame is None:
            depth = 2
        logger.opt(depth=depth, exception=record.exc_info).log(
            loguru_level, record.getMessage()
        )

    def __call__(self, record):
        """Backward-compatible direct-call form used by older tests/tools."""
        self.emit(record)


def _install_intercept_handler():
    """安装 InterceptHandler 到 stdlib logging 根 logger。"""
    if not _LOGURU_AVAILABLE:
        return  # 退化模式不需要
    handler = InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    logger.debug("InterceptHandler 已安装，stdlib logging 将路由到 loguru")


def setup_logging(
    level: str | None = None,
    app_log: bool = True,
    error_log: bool = True,
    console: bool = True,
    json_log: bool = False,
) -> None:
    """配置日志系统。

    P3-4: 修复 CSAM_LOG_LEVEL 环境变量失效问题（level=None 时读取环境变量）。
    P3-4: 安装 InterceptHandler 统一 stdlib → loguru 路由。

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

        if console and sys.stderr is not None:
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

        # P3-4: 安装 InterceptHandler，统一 stdlib logging → loguru
        _install_intercept_handler()

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


# 模块级便捷函数（支持 printf 风格位置参数，与 stdlib logging 兼容）
def _format_msg(msg: str, args: tuple) -> str:
    """printf 风格格式化（loguru 原生不支持 %s/%d，需手动处理）。"""
    if args:
        try:
            return msg % args
        except Exception:
            return msg
    return msg

def info(msg: str, *args, **kwargs) -> None:
    formatted = _format_msg(msg, args)
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).info(formatted, **kwargs)
    else:
        logger.info(formatted, **kwargs)

def debug(msg: str, *args, **kwargs) -> None:
    formatted = _format_msg(msg, args)
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).debug(formatted, **kwargs)
    else:
        logger.debug(formatted, **kwargs)

def warning(msg: str, *args, **kwargs) -> None:
    formatted = _format_msg(msg, args)
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).warning(formatted, **kwargs)
    else:
        logger.warning(formatted, **kwargs)

def error(msg: str, *args, **kwargs) -> None:
    formatted = _format_msg(msg, args)
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).error(formatted, **kwargs)
    else:
        logger.error(formatted, **kwargs)

def exception(msg: str, *args, **kwargs) -> None:
    formatted = _format_msg(msg, args)
    if _LOGURU_AVAILABLE:
        logger.opt(depth=1).exception(formatted, **kwargs)
    else:
        logger.exception(formatted, **kwargs)


# ============================================================
# P3-4: 日志导出功能
# ============================================================
def export_logs(output_path: str | None = None) -> str:
    """将日志目录打包导出为 zip 文件。

    用于用户提交反馈时附上完整日志。

    Args:
        output_path: 输出 zip 路径。None 时保存到 LOG_DIR/logs_export_{timestamp}.zip

    Returns:
        实际输出的 zip 文件路径
    """
    if output_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(LOG_DIR, f"logs_export_{ts}.zip")

    log_dir = Path(LOG_DIR)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 打包日志目录下所有文件（.log, .jsonl, .zip 等）
        for item in log_dir.rglob("*"):
            if item.is_file() and item.name != os.path.basename(output_path):
                arcname = item.relative_to(log_dir)
                zf.write(item, arcname)

    info(f"日志已导出: {output_path}")
    return output_path
