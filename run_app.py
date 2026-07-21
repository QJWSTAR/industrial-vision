#!/usr/bin/env python3
"""
run_app.py — 冷喷涂缺陷修复软件启动入口

负责：
1. 日志初始化
2. 崩溃处理
3. QApplication 创建
4. MATLAB 生命周期管理器初始化（自动检测 R2025b、启动 Bridge、监控崩溃）
5. 主窗口创建与退出清理
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer

# DPI 缩放支持（Qt6 默认开启，显式设置确保 100%-200% 缩放正确）
# 支持的缩放比例：100% / 125% / 150% / 175% / 200%
Qt.AA_EnableHighDpiScaling = getattr(Qt, "AA_EnableHighDpiScaling", None)
Qt.AA_UseHighDpiPixmaps = getattr(Qt, "AA_UseHighDpiPixmaps", None)

from repair_app.ui.main_window import MainWindow
from repair_app.utils.logger_config import setup_logging, info, warning, error as log_error
from repair_app.utils.license_manager import LicenseManager
from repair_app.utils.app_config import AppConfig
from repair_app.software.path_manager import PathManager
from repair_app.software.exception_reporter import install_exception_reporter
from repair_app.utils.error_manager import ErrorManager
from repair_app.ui.theme_manager import ThemeManager


def _log_developer_mode_banner() -> None:
    """输出 Developer Mode 启动横幅（醒目，避免误判为正式版）。"""
    info("=" * 60)
    info("Developer Mode Enabled")
    info("License Verification Skipped")
    info("=" * 60)


def _log_release_mode_banner(status) -> None:
    """输出 Release Mode 启动横幅。"""
    info(f"Release Mode: {status.message}")
    if status.days_remaining >= 0:
        info(f"License 有效，剩余 {status.days_remaining} 天")
    else:
        info("License 有效（永久授权）")


def main():
    """Main entry point."""
    # 1. 初始化统一目录（用户数据目录：项目/导出/日志/恢复/缓存）
    pm = PathManager.get_instance()
    # 2. 初始化日志（写入统一日志目录）
    setup_logging()
    info("软件启动中...")
    info(pm.describe())
    # 3. 安装异常报告器（替代原 crash_handler，生成结构化异常报告）
    install_exception_reporter(show_dialog=True)
    # 3.1 安装 ErrorManager 全局钩子（覆盖主线程 + 子线程未捕获异常）
    # 用户永远不看到 Python Traceback：exception_reporter 生成报告文件，
    # ErrorManager 显示用户友好对话框
    ErrorManager.install_global_hooks(show_dialog=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # 应用工业级主题（统一 QSS + QPalette + QFont）
    ThemeManager.apply(app, theme="dark")

    # MF-3: License 运行时统一校验（Developer Mode / Release Mode）
    # 启动流程的唯一决策点：通过 verify_runtime() 决定是否允许进入主界面
    license_mgr = LicenseManager()
    status = license_mgr.verify_runtime()

    if status.is_developer:
        # Developer Mode: 跳过 License 校验，输出醒目横幅
        _log_developer_mode_banner()
    elif status.valid:
        # Release Mode: License 校验通过
        _log_release_mode_banner(status)
    else:
        # Release Mode: License 校验失败，拒绝启动
        warning(f"License 验证失败，软件拒绝启动: {status.message}")
        QMessageBox.critical(
            None,
            "License 无效 — 无法启动软件",
            f"软件无法启动，因为 License 验证失败。\n\n"
            f"错误详情：{status.message}\n\n"
            "请按以下步骤解决：\n"
            "1. 确认 config 目录下存在 license.key 文件\n"
            "2. 确认 license.key 未被篡改或损坏\n"
            "3. 确认本机机器码与 License 中记录的一致\n"
            "4. 确认 License 未过期\n\n"
            "如需帮助，请联系管理员重新签发 License 文件。",
        )
        sys.exit(1)

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 软件启动后异步初始化 MATLAB 生命周期管理
    # 使用 QTimer.singleShot 确保窗口先显示，再启动 MATLAB（避免阻塞 UI）
    project_root = os.path.dirname(os.path.abspath(__file__))

    def init_lifecycle():
        try:
            from repair_app.bridge.lifecycle_manager import (
                MatlabLifecycleManager, LifecycleStatus,
            )
            manager = MatlabLifecycleManager.get_instance(project_root)

            # 订阅状态变更，更新状态栏
            def on_status_changed(status: str, message: str):
                icons = {
                    LifecycleStatus.UNKNOWN: "⚪",
                    LifecycleStatus.DETECTING: "🔍",
                    LifecycleStatus.STARTING: "🟡",
                    LifecycleStatus.READY: "🟢",
                    LifecycleStatus.BUSY: "🔵",
                    LifecycleStatus.CRASHED: "🔴",
                    LifecycleStatus.RESTARTING: "🟠",
                    LifecycleStatus.FAILED: "⛔",
                    LifecycleStatus.STOPPED: "⚫",
                }
                icon = icons.get(status, "⚪")
                window._sb.showMessage(f"{icon} MATLAB: {message}")
                info("MATLAB 状态: %s - %s", status, message)

            manager.status_changed.connect(on_status_changed)

            # 启动 MATLAB（后台自动检测 + 启动 + 监控）
            info("开始初始化 MATLAB 生命周期...")
            ok = manager.start(auto_restart=True)
            if ok:
                info("MATLAB 已就绪: %s", manager.matlab_version)
            else:
                warning("MATLAB 初始化失败，用户可手动启动 MATLAB Bridge")
        except Exception as exc:
            warning("MATLAB 生命周期初始化异常: %s", exc)

    # 延迟 500ms 启动，确保窗口已显示
    QTimer.singleShot(500, init_lifecycle)

    # 应用退出时清理 MATLAB
    def on_about_to_quit():
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            manager = MatlabLifecycleManager.get_instance(project_root)
            manager.stop()
            info("MATLAB 生命周期已清理")
        except Exception as exc:
            warning("退出清理异常: %s", exc)

    app.aboutToQuit.connect(on_about_to_quit)

    exit_code = app.exec()
    info("软件退出，exit_code=%d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
