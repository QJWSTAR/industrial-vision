"""software.exception_reporter — 异常报告生成器

在崩溃时生成结构化的异常报告，包含：
- 时间戳
- 软件版本 / Python 版本 / 平台
- 完整 traceback
- 系统信息（MATLAB 版本、License 状态）
- 最近操作日志（从 logger 提取）

报告保存到 logs/exception_YYYYMMDD_HHMMSS.log

与 crash_handler 配合使用：crash_handler 捕获异常 → ExceptionReporter 生成报告
"""
from __future__ import annotations

import os
import sys
import platform
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from repair_app.software.path_manager import PathManager


def _safe_get_version() -> str:
    try:
        from repair_app import __version__
        return __version__
    except Exception:
        return "unknown"


def _safe_get_license_info() -> str:
    try:
        from repair_app.utils.license_manager import LicenseManager
        lm = LicenseManager()
        lm.load_license()
        if lm.is_valid:
            data = lm.license_data
            days = lm.days_remaining
            return (
                f"有效 (授权给: {data.issued_to}, "
                f"到期: {data.expires_at}, 剩余 {days} 天)"
            )
        return f"无效/未授权 ({lm.error})"
    except Exception as exc:
        return f"查询失败: {exc}"


def _safe_get_matlab_info() -> str:
    try:
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance()
        return f"{m.status.name}: {m.message} (version={m.matlab_version or 'unknown'})"
    except Exception:
        return "未初始化"


class ExceptionReporter:
    """异常报告生成器。

    生成结构化的异常报告文件，并可选弹出 GUI 提示。
    """

    def __init__(self, path_manager: Optional[PathManager] = None) -> None:
        self._pm = path_manager or PathManager.get_instance()

    def report_exception(
        self,
        exc_type,
        exc_value,
        exc_tb,
        context: Optional[str] = None,
    ) -> Path:
        """生成异常报告文件。

        Args:
            exc_type: 异常类型
            exc_value: 异常值
            exc_tb: traceback 对象
            context: 额外上下文描述
        Returns:
            报告文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self._pm.exception_log_path(timestamp)
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        lines = []
        lines.append("=" * 70)
        lines.append(f"CSAM Repair 异常报告 - {datetime.now().isoformat()}")
        lines.append("=" * 70)
        lines.append("")
        lines.append("[软件信息]")
        lines.append(f"  版本: {_safe_get_version()}")
        lines.append(f"  Python: {sys.version.split()[0]}")
        lines.append(f"  平台: {platform.platform()}")
        lines.append(f"  可执行文件: {sys.executable}")
        lines.append("")
        lines.append("[License 状态]")
        lines.append(f"  {_safe_get_license_info()}")
        lines.append("")
        lines.append("[MATLAB 状态]")
        lines.append(f"  {_safe_get_matlab_info()}")
        lines.append("")
        if context:
            lines.append("[上下文]")
            lines.append(f"  {context}")
            lines.append("")
        lines.append("[用户数据目录]")
        lines.append(f"  {self._pm.root}")
        lines.append("")
        lines.append("[Traceback]")
        lines.append(tb_text)
        lines.append("")
        lines.append("=" * 70)
        lines.append("请将此报告发送给技术支持以协助诊断问题。")
        lines.append("=" * 70)

        try:
            report_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            # 写失败时退化为 stderr
            print("\n".join(lines), file=sys.stderr)

        return report_path

    def report_text(self, message: str, context: Optional[str] = None) -> Path:
        """生成文本报告（用于非异常类错误）。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self._pm.exception_log_path(timestamp)
        lines = [
            "=" * 70,
            f"CSAM Repair 错误报告 - {datetime.now().isoformat()}",
            "=" * 70,
            "",
            "[软件信息]",
            f"  版本: {_safe_get_version()}",
            f"  Python: {sys.version.split()[0]}",
            f"  平台: {platform.platform()}",
            "",
        ]
        if context:
            lines += ["[上下文]", f"  {context}", ""]
        lines += ["[错误描述]", message, "", "=" * 70]
        try:
            report_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            print("\n".join(lines), file=sys.stderr)
        return report_path


def install_exception_reporter(
    show_dialog: bool = True,
) -> Callable[[Path], None]:
    """安装带异常报告生成的全局异常钩子。

    替换 sys.excepthook，在崩溃时：
    1. 生成结构化异常报告（ExceptionReporter）
    2. 写入 crash_*.log（原有 crash_handler 行为）
    3. 可选弹出 GUI 对话框提示用户

    Args:
        show_dialog: 是否尝试弹出 GUI 对话框
    Returns:
        on_reported 回调函数，接收报告文件路径
    """
    from repair_app.utils.crash_handler import install_crash_handler
    from repair_app.software.path_manager import PathManager

    pm = PathManager.get_instance()
    reporter = ExceptionReporter(pm)
    reported_paths: list[Path] = []

    def on_crash(tb_text: str) -> None:
        # crash_handler 已经写了 crash_*.log
        # 这里不再重复，只在 reported_paths 中记录 None
        pass

    def on_reported(path: Path) -> None:
        reported_paths.append(path)
        if show_dialog:
            try:
                _show_crash_dialog(path)
            except Exception:
                pass

    # 安装底层 crash_handler（写 crash_*.log）
    install_crash_handler(log_dir=str(pm.logs_dir), on_crash=on_crash)

    # 包装 sys.excepthook，额外生成结构化报告
    prev_hook = sys.excepthook

    def wrapped_hook(exc_type, exc_value, exc_tb):
        try:
            report_path = reporter.report_exception(exc_type, exc_value, exc_tb)
            on_reported(report_path)
        except Exception:
            pass
        # 调用前一个钩子（crash_handler 的）
        prev_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = wrapped_hook
    return on_reported


def _show_crash_dialog(report_path: Path) -> None:
    """尝试弹出 GUI 崩溃对话框（不依赖 QApplication 已创建）。"""
    try:
        from PySide6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app is None:
            return  # 无 QApplication，跳过 GUI
        QMessageBox.critical(
            None,
            "程序异常",
            f"软件遇到未预期错误，已自动保存异常报告。\n\n"
            f"报告路径：\n{report_path}\n\n"
            f"请将此报告发送给技术支持。\n"
            f"软件可能仍可继续使用，但建议重启。",
        )
    except Exception:
        pass
