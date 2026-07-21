"""software.about_dialog — 关于对话框（About + 版本信息）

显示：
- 软件名称 / 版本
- License 状态（授权给、到期时间、剩余天数）
- 用户数据目录（项目/导出/日志/恢复/缓存）
- MATLAB 状态
- 技术支持联系方式
- 第三方组件版权
"""
from __future__ import annotations

import sys
import platform
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QTextEdit, QFrame, QSizePolicy,
)


def _get_version() -> str:
    try:
        from repair_app import __version__
        return __version__
    except Exception:
        return "unknown"


def _get_license_text() -> str:
    try:
        from repair_app.utils.license_manager import LicenseManager
        lm = LicenseManager()
        lm.load_license()
        if lm.is_valid:
            data = lm.license_data
            days = lm.days_remaining
            if days < 0:
                days_str = "永久授权"
            else:
                days_str = f"{days} 天"
            return (
                f"✅ 授权有效\n"
                f"  授权对象: {data.issued_to}\n"
                f"  签发时间: {data.issued_at}\n"
                f"  到期时间: {data.expires_at}\n"
                f"  剩余天数: {days_str}\n"
                f"  最大层数: {data.max_layers}"
            )
        return f"⚠️ 授权无效\n  原因: {lm.error}"
    except Exception as exc:
        return f"⚠️ 授权信息查询失败\n  原因: {exc}"


def _get_paths_text() -> str:
    try:
        from repair_app.software.path_manager import PathManager
        return PathManager.get_instance().describe()
    except Exception as exc:
        return f"路径信息查询失败: {exc}"


def _get_matlab_text() -> str:
    try:
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance()
        return (
            f"状态: {m.status.name}\n"
            f"消息: {m.message}\n"
            f"MATLAB 版本: {m.matlab_version or '未知'}"
        )
    except Exception:
        return "MATLAB 生命周期管理器未初始化"


def _get_system_text() -> str:
    return (
        f"操作系统: {platform.platform()}\n"
        f"Python: {sys.version.split()[0]}\n"
        f"可执行文件: {sys.executable}\n"
        f"工作目录: {sys.path[0] if sys.path else 'N/A'}"
    )


def _get_credits_text() -> str:
    return (
        "CSAM Repair 基于以下开源组件构建：\n\n"
        "  · PySide6 (Qt for Python) — LGPL\n"
        "  · NumPy / SciPy — BSD\n"
        "  · matplotlib — matplotlib license\n"
        "  · PyZMQ — LGPL\n"
        "  · protobuf — BSD\n"
        "  · reportlab — BSD\n"
        "  · cryptography — Apache 2.0\n"
        "  · shapely — BSD\n\n"
        "MATLAB 算法由 MathWorks 提供，需单独授权。\n\n"
        "技术支持：请联系您的设备供应商。"
    )


class AboutDialog(QDialog):
    """关于对话框（带标签页）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 CSAM Repair")
        self.setMinimumSize(560, 460)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # ---- 头部：标题 + 版本 ----
        header = QFrame()
        header.setStyleSheet(
            "QFrame{background:#0F172A;border:1px solid #1E293B;"
            "border-radius:12px;padding:12px;}"
        )
        hl = QVBoxLayout(header)
        hl.setSpacing(4)

        title = QLabel("冷喷涂缺陷修复软件")
        title.setStyleSheet("color:#F8FAFC;font-size:22px;font-weight:bold;")
        hl.addWidget(title)

        version = QLabel(f"版本 {_get_version()}")
        version.setStyleSheet("color:#94A3B8;font-size:13px;")
        hl.addWidget(version)

        subtitle = QLabel("CSAM Repair · Cold Spray Additive Manufacturing")
        subtitle.setStyleSheet("color:#64748B;font-size:11px;")
        hl.addWidget(subtitle)

        layout.addWidget(header)

        # ---- 标签页 ----
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border:1px solid #1E293B; border-radius:8px;
                               background:#0B1120; top:-1px; }
            QTabBar::tab { background:#0F172A; color:#94A3B8; padding:6px 14px;
                           margin-right:2px; border:1px solid #1E293B;
                           border-bottom:none; border-top-left-radius:6px;
                           border-top-right-radius:6px; font-weight:600; }
            QTabBar::tab:selected { background:#1D4ED8; color:#FFFFFF; }
        """)

        # 概览
        overview = QTextEdit()
        overview.setReadOnly(True)
        overview.setPlainText(
            f"CSAM Repair v{_get_version()}\n\n"
            "面向冷喷涂增材制造与缺陷修复的工艺规划软件。\n"
            "支持点云导入、缺陷选区、路径规划、形貌预测、G-code 导出\n"
            "全流程自动化。\n\n"
            f"{_get_system_text()}"
        )
        tabs.addTab(overview, "概览")

        # License
        license_tab = QTextEdit()
        license_tab.setReadOnly(True)
        license_tab.setPlainText(_get_license_text())
        tabs.addTab(license_tab, "License")

        # 数据目录
        paths_tab = QTextEdit()
        paths_tab.setReadOnly(True)
        paths_tab.setPlainText(_get_paths_text())
        tabs.addTab(paths_tab, "数据目录")

        # MATLAB
        matlab_tab = QTextEdit()
        matlab_tab.setReadOnly(True)
        matlab_tab.setPlainText(_get_matlab_text())
        tabs.addTab(matlab_tab, "MATLAB")

        # 致谢
        credits_tab = QTextEdit()
        credits_tab.setReadOnly(True)
        credits_tab.setPlainText(_get_credits_text())
        tabs.addTab(credits_tab, "致谢")

        layout.addWidget(tabs, 1)

        # ---- 关闭按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setMinimumWidth(90)
        btn_close.setMinimumHeight(32)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
