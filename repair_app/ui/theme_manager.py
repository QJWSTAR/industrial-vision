"""theme_manager.py — 工业级 GUI 主题管理器

参考 Siemens NX / Materialise Magics / Geomagic / ANSYS / SolidWorks /
Visual Studio / MATLAB 的工业软件 GUI 设计风格。

核心设计原则：
  1. 集中设计 token（颜色 / 字体 / 间距 / 圆角 / 阴影）
  2. 统一 QSS 生成（消除散落的 setStyleSheet）
  3. 与商业工业软件视觉一致性（紧凑信息密度 + 高对比度 + 功能分区）
  4. 留白克制（工业软件信息密度优先）

使用方式：
    from repair_app.ui.theme_manager import ThemeManager
    ThemeManager.apply(app)             # 应用到 QApplication
    ThemeManager.get_qss()              # 获取 QSS 字符串
    ThemeManager.get_palette()          # 获取调色板字典
    ThemeManager.set_theme("light")     # 切换浅色主题
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict
from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWidgets import QApplication


# ============================================================
# 1. Design Tokens — 设计令牌（参考工业软件标准）
# ============================================================

@dataclass(frozen=True)
class Palette:
    """调色板：工业软件标准深色主题（参考 Siemens NX Dark / VS Code Dark+）"""

    # ---- 背景层级（从深到浅）----
    bg_app: str = "#0B1120"          # 应用主背景
    bg_panel: str = "#0F172A"        # 面板背景
    bg_elevated: str = "#111827"     # 凸起元素（GroupBox）
    bg_input: str = "#020617"        # 输入框（最深）
    bg_hover: str = "#1E293B"        # 悬停
    bg_menu: str = "#0F172A"         # 菜单背景

    # ---- 边框 ----
    border_default: str = "#1E293B"
    border_strong: str = "#334155"
    border_focus: str = "#3B82F6"

    # ---- 文字 ----
    text_primary: str = "#F8FAFC"    # 标题
    text_body: str = "#E2E8F0"       # 正文
    text_secondary: str = "#CBD5E1"  # 次要
    text_muted: str = "#94A3B8"      # 弱化
    text_disabled: str = "#64748B"   # 禁用

    # ---- 强调色（蓝色系，工业软件主流）----
    accent: str = "#2563EB"          # 主强调（按钮、链接）
    accent_hover: str = "#1D4ED8"    # 悬停
    accent_light: str = "#3B82F6"    # 进度条、滑块
    accent_pale: str = "#60A5FA"     # 标题装饰
    accent_bg: str = "#1E3A8A"       # 强调背景

    # ---- 状态色（ANSYS / SolidWorks 标准）----
    success: str = "#10B981"         # 成功（绿色）
    warning: str = "#F59E0B"         # 警告（橙色）
    error: str = "#EF4444"           # 错误（红色）
    info: str = "#3B82F6"            # 信息（蓝色）

    # ---- 状态色浅版（背景）----
    success_bg: str = "#064E3B"
    warning_bg: str = "#451A03"
    error_bg: str = "#450A0A"
    info_bg: str = "#1E3A8A"

    # ---- 标题色 ----
    title_accent: str = "#93C5FD"    # GroupBox 标题


@dataclass(frozen=True)
class PaletteLight:
    """浅色主题（参考 SolidWorks / MATLAB 浅色）"""
    bg_app: str = "#F1F5F9"
    bg_panel: str = "#FFFFFF"
    bg_elevated: str = "#F8FAFC"
    bg_input: str = "#FFFFFF"
    bg_hover: str = "#E2E8F0"
    bg_menu: str = "#FFFFFF"

    border_default: str = "#CBD5E1"
    border_strong: str = "#94A3B8"
    border_focus: str = "#2563EB"

    text_primary: str = "#0F172A"
    text_body: str = "#1E293B"
    text_secondary: str = "#475569"
    text_muted: str = "#64748B"
    text_disabled: str = "#94A3B8"

    accent: str = "#2563EB"
    accent_hover: str = "#1D4ED8"
    accent_light: str = "#3B82F6"
    accent_pale: str = "#60A5FA"
    accent_bg: str = "#DBEAFE"

    success: str = "#059669"
    warning: str = "#D97706"
    error: str = "#DC2626"
    info: str = "#2563EB"

    success_bg: str = "#D1FAE5"
    warning_bg: str = "#FEF3C7"
    error_bg: str = "#FEE2E2"
    info_bg: str = "#DBEAFE"

    title_accent: str = "#1D4ED8"


@dataclass(frozen=True)
class Typography:
    """排版（参考 Siemens NX / VS Code 字体规范）"""
    # 字体族
    family_ui: str = "'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', sans-serif"
    family_mono: str = "'Cascadia Code', 'Consolas', 'Courier New', monospace"

    # 字号
    size_caption: str = "10px"   # 标注 / Tooltip
    size_body: str = "12px"      # 正文
    size_body_lg: str = "13px"   # 大正文
    size_subtitle: str = "14px"  # 副标题
    size_title: str = "16px"     # 标题
    size_title_lg: str = "20px"  # 大标题
    size_huge: str = "24px"      # 巨型标题

    # 字重
    weight_normal: str = "400"
    weight_medium: str = "500"
    weight_semibold: str = "600"
    weight_bold: str = "700"


@dataclass(frozen=True)
class Spacing:
    """间距系统（8px 栅格）"""
    xs: str = "2px"
    sm: str = "4px"
    md: str = "8px"
    lg: str = "12px"
    xl: str = "16px"
    xxl: str = "24px"

    # 控件内边距
    pad_button: str = "6px 12px"
    pad_input: str = "4px 8px"
    pad_menu_item: str = "6px 24px"
    pad_statusbar: str = "0 8px"


@dataclass(frozen=True)
class Radius:
    """圆角（工业软件偏方正）"""
    none: str = "0px"
    sm: str = "3px"       # 输入框
    md: str = "4px"       # 按钮
    lg: str = "6px"       # GroupBox
    pill: str = "10px"    # 标签芯片


# ============================================================
# 2. ThemeManager — 主题管理器
# ============================================================

class ThemeManager:
    """全局主题管理器（单例）。

    职责：
    - 集中所有设计 token
    - 生成统一 QSS
    - 应用到 QApplication
    - 支持主题切换（Dark / Light）
    """

    _instance = None
    _palette: Palette = Palette()
    _typography: Typography = Typography()
    _spacing: Spacing = Spacing()
    _radius: Radius = Radius()
    _theme_name: str = "dark"

    @classmethod
    def get_palette(cls) -> Palette:
        """获取当前调色板。"""
        return cls._palette

    @classmethod
    def get_typography(cls) -> Typography:
        return cls._typography

    @classmethod
    def get_spacing(cls) -> Spacing:
        return cls._spacing

    @classmethod
    def get_radius(cls) -> Radius:
        return cls._radius

    @classmethod
    def get_theme_name(cls) -> str:
        return cls._theme_name

    @classmethod
    def set_theme(cls, name: str) -> None:
        """切换主题（dark / light）。"""
        cls._theme_name = name
        if name == "light":
            cls._palette = PaletteLight()
        else:
            cls._palette = Palette()

    @classmethod
    def apply(cls, app: QApplication, theme: str = "dark") -> None:
        """应用主题到 QApplication。"""
        cls.set_theme(theme)
        qss = cls.get_qss()
        app.setStyleSheet(qss)

        # 同时设置 QFont（统一字体族，覆盖 QSS 不能控制的某些场景）
        font = QFont()
        font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC"])
        font.setPointSize(9)  # 12px ≈ 9pt
        app.setFont(font)

        # 设置 QPalette（确保原生对话框也跟随主题）
        cls._apply_palette(app)

    @classmethod
    def _apply_palette(cls, app: QApplication) -> None:
        """同步 QPalette（原生对话框用）。"""
        p = cls._palette
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(p.bg_app))
        pal.setColor(QPalette.WindowText, QColor(p.text_body))
        pal.setColor(QPalette.Base, QColor(p.bg_input))
        pal.setColor(QPalette.AlternateBase, QColor(p.bg_elevated))
        pal.setColor(QPalette.Text, QColor(p.text_body))
        pal.setColor(QPalette.Button, QColor(p.bg_hover))
        pal.setColor(QPalette.ButtonText, QColor(p.text_body))
        pal.setColor(QPalette.Highlight, QColor(p.accent))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ToolTipBase, QColor(p.bg_panel))
        pal.setColor(QPalette.ToolTipText, QColor(p.text_body))
        app.setPalette(pal)

    # ============================================================
    # QSS 生成
    # ============================================================

    @classmethod
    def get_qss(cls) -> str:
        """生成统一 QSS（参考工业软件标准）。"""
        p = cls._palette
        t = cls._typography
        s = cls._spacing
        r = cls._radius

        return f"""
        /* ============================================================
           全局基础（QMainWindow / QWidget）
           ============================================================ */
        QMainWindow, QWidget {{
            background:{p.bg_app};
            color:{p.text_secondary};
            font-family:{t.family_ui};
            font-size:{t.size_body};
        }}

        /* ============================================================
           顶部标题栏（AppHeader）
           ============================================================ */
        QFrame#AppHeader {{
            background:{p.bg_input};
            border-bottom:1px solid {p.border_default};
        }}
        QLabel#AppTitle {{
            color:{p.text_primary};
            font-size:{t.size_title_lg};
            font-weight:{t.weight_bold};
        }}
        QLabel#AppSubtitle {{
            color:{p.text_muted};
            font-size:{t.size_body};
        }}
        QLabel#HeaderChip {{
            background:{p.bg_elevated};
            color:{p.accent_pale};
            border:1px solid {p.accent_bg};
            border-radius:{r.pill};
            padding:4px 10px;
            font-weight:{t.weight_semibold};
        }}

        /* ============================================================
           侧边栏 / 工作区 / 辅助面板
           ============================================================ */
        QWidget#SideRail {{
            background:{p.bg_app};
            border-right:1px solid {p.border_default};
        }}
        QWidget#Workspace, QStackedWidget#WorkspaceStack {{
            background:{p.bg_app};
        }}
        QWidget#AuxPanel, QFrame#Inspector {{
            background:{p.bg_panel};
            border:1px solid {p.border_default};
            border-radius:{r.lg};
        }}
        QFrame#P1Header, QFrame#P1Controls {{
            background:{p.bg_panel};
            border:1px solid {p.border_default};
            border-radius:{r.lg};
        }}

        QScrollArea {{
            background:{p.bg_app};
            border:none;
        }}
        QFrame {{
            border:none;
        }}

        /* ============================================================
           QGroupBox（信息分区，参考 NX / ANSYS 紧凑风格）
           ============================================================ */
        QGroupBox {{
            background:{p.bg_elevated};
            border:1px solid {p.border_default};
            border-radius:{r.lg};
            margin-top:10px;
            padding:10px 8px 8px 8px;
            color:{p.text_secondary};
            font-weight:{t.weight_semibold};
            font-size:{t.size_body};
        }}
        QGroupBox::title {{
            subcontrol-origin:margin;
            left:8px;
            padding:0 4px;
            color:{p.title_accent};
        }}

        /* ============================================================
           QLabel
           ============================================================ */
        QLabel {{
            color:{p.text_secondary};
            background:transparent;
        }}

        /* ============================================================
           QPushButton（参考 VS / SolidWorks 扁平按钮）
           ============================================================ */
        QPushButton {{
            background:{p.bg_hover};
            color:{p.text_body};
            border:1px solid {p.border_strong};
            border-radius:{r.md};
            padding:{s.pad_button};
            font-weight:{t.weight_medium};
            min-height:18px;
        }}
        QPushButton:hover {{
            background:{p.border_default};
            border-color:{p.accent};
        }}
        QPushButton:pressed {{
            background:{p.bg_input};
        }}
        QPushButton:disabled {{
            background:{p.bg_elevated};
            color:{p.text_disabled};
            border-color:{p.border_default};
        }}
        /* 主按钮（强调色） */
        QPushButton#PrimaryButton, QPushButton[cssClass="primary"] {{
            background:{p.accent};
            color:#FFFFFF;
            border:1px solid {p.accent};
            font-weight:{t.weight_semibold};
        }}
        QPushButton#PrimaryButton:hover, QPushButton[cssClass="primary"]:hover {{
            background:{p.accent_hover};
            border-color:{p.accent_hover};
        }}
        QPushButton#PrimaryButton:pressed, QPushButton[cssClass="primary"]:pressed {{
            background:{p.accent_hover};
        }}
        /* 危险按钮 */
        QPushButton#DangerButton, QPushButton[cssClass="danger"] {{
            background:transparent;
            color:{p.error};
            border:1px solid {p.error};
        }}
        QPushButton#DangerButton:hover, QPushButton[cssClass="danger"]:hover {{
            background:{p.error_bg};
        }}

        /* ============================================================
           QSlider
           ============================================================ */
        QSlider::groove:horizontal {{
            height:4px;
            border-radius:2px;
            background:{p.border_default};
        }}
        QSlider::handle:horizontal {{
            width:14px;
            margin:-5px 0;
            border-radius:7px;
            background:{p.accent_pale};
            border:1px solid {p.accent};
        }}
        QSlider::handle:horizontal:hover {{
            background:{p.accent_light};
        }}
        QSlider::sub-page:horizontal {{
            border-radius:2px;
            background:{p.accent};
        }}

        /* ============================================================
           输入控件（QComboBox / QSpinBox / QTextEdit / QPlainTextEdit）
           ============================================================ */
        QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit, QLineEdit {{
            background:{p.bg_input};
            color:{p.text_body};
            border:1px solid {p.border_strong};
            border-radius:{r.sm};
            padding:{s.pad_input};
            selection-background-color:{p.accent};
            selection-color:#FFFFFF;
        }}
        QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover,
        QLineEdit:hover, QTextEdit:hover {{
            border-color:{p.accent};
        }}
        QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus,
        QLineEdit:focus, QTextEdit:focus {{
            border-color:{p.border_focus};
        }}
        QComboBox:disabled, QDoubleSpinBox:disabled,
        QSpinBox:disabled, QLineEdit:disabled {{
            color:{p.text_disabled};
            border-color:{p.border_default};
            background:{p.bg_panel};
        }}
        QComboBox::drop-down {{
            border:none;
            width:20px;
        }}
        QComboBox::down-arrow {{
            image:none;
            border-left:4px solid transparent;
            border-right:4px solid transparent;
            border-top:5px solid {p.text_muted};
            margin-right:6px;
        }}
        QComboBox QAbstractItemView {{
            background:{p.bg_menu};
            color:{p.text_body};
            border:1px solid {p.border_default};
            selection-background-color:{p.accent};
            selection-color:#FFFFFF;
            outline:none;
        }}

        /* ============================================================
           QCheckBox / QRadioButton
           ============================================================ */
        QCheckBox, QRadioButton {{
            color:{p.text_secondary};
            spacing:6px;
            background:transparent;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width:14px;
            height:14px;
            border:1px solid {p.border_strong};
            background:{p.bg_input};
        }}
        QCheckBox::indicator {{
            border-radius:{r.sm};
        }}
        QCheckBox::indicator:checked {{
            background:{p.accent};
            border-color:{p.accent};
        }}
        QRadioButton::indicator {{
            border-radius:7px;
        }}
        QRadioButton::indicator:checked {{
            background:{p.accent};
            border-color:{p.accent};
        }}

        /* ============================================================
           QProgressBar（紧凑型，参考 NX 状态栏）
           ============================================================ */
        QProgressBar {{
            background:{p.bg_input};
            color:{p.text_secondary};
            border:1px solid {p.border_default};
            border-radius:{r.sm};
            height:14px;
            text-align:center;
            font-size:{t.size_caption};
        }}
        QProgressBar::chunk {{
            background:{p.accent_light};
            border-radius:2px;
        }}

        /* ============================================================
           QSplitter
           ============================================================ */
        QSplitter::handle {{
            background:{p.border_default};
        }}
        QSplitter::handle:horizontal {{ width:1px; }}
        QSplitter::handle:vertical {{ height:1px; }}

        /* ============================================================
           QStatusBar（双区状态栏，参考 VS Code / NX）
           ============================================================ */
        QStatusBar {{
            background:{p.bg_input};
            color:{p.text_muted};
            border-top:1px solid {p.border_default};
            font-size:{t.size_caption};
        }}
        QStatusBar::item {{ border:none; }}
        QStatusBar QLabel {{
            color:{p.text_muted};
            padding:{s.pad_statusbar};
        }}

        /* ============================================================
           QMenuBar / QMenu（参考 VS / MATLAB 菜单栏）
           ============================================================ */
        QMenuBar {{
            background:{p.bg_input};
            color:{p.text_secondary};
            border-bottom:1px solid {p.border_default};
            padding:2px;
        }}
        QMenuBar::item {{
            padding:5px 10px;
            background:transparent;
            border-radius:{r.sm};
        }}
        QMenuBar::item:selected {{
            background:{p.bg_hover};
        }}
        QMenuBar::item:pressed {{
            background:{p.accent};
            color:#FFFFFF;
        }}
        QMenu {{
            background:{p.bg_menu};
            color:{p.text_secondary};
            border:1px solid {p.border_default};
            padding:4px;
        }}
        QMenu::item {{
            padding:{s.pad_menu_item};
            border-radius:{r.sm};
        }}
        QMenu::item:selected {{
            background:{p.accent};
            color:#FFFFFF;
        }}
        QMenu::separator {{
            height:1px;
            background:{p.border_default};
            margin:4px 8px;
        }}
        QMenu::icon {{
            padding-left:10px;
        }}

        /* ============================================================
           QToolBar（参考 NX / SolidWorks 工具栏）
           ============================================================ */
        QToolBar {{
            background:{p.bg_panel};
            border-bottom:1px solid {p.border_default};
            border:none;
            spacing:2px;
            padding:3px;
        }}
        QToolBar::separator {{
            background:{p.border_default};
            width:1px;
            margin:4px 6px;
        }}
        QToolButton {{
            background:transparent;
            color:{p.text_secondary};
            border:1px solid transparent;
            border-radius:{r.sm};
            padding:4px 8px;
            font-size:{t.size_body};
        }}
        QToolButton:hover {{
            background:{p.bg_hover};
            border-color:{p.border_strong};
        }}
        QToolButton:pressed, QToolButton:checked {{
            background:{p.accent_bg};
            border-color:{p.accent};
        }}

        /* ============================================================
           QDockWidget（可拖拽面板，参考 NX / ANSYS Dock）
           ============================================================ */
        QDockWidget {{
            color:{p.text_primary};
            titlebar-close-icon:url();
            titlebar-normal-icon:url();
        }}
        QDockWidget::title {{
            background:{p.bg_input};
            padding:6px 10px;
            border-bottom:1px solid {p.border_default};
            font-weight:{t.weight_semibold};
            font-size:{t.size_body};
        }}
        QDockWidget > QWidget {{
            background:{p.bg_panel};
        }}

        /* ============================================================
           QTabWidget / QTabBar（参考 VS Code Tab）
           ============================================================ */
        QTabWidget::pane {{
            border:1px solid {p.border_default};
            background:{p.bg_panel};
        }}
        QTabBar::tab {{
            background:{p.bg_input};
            color:{p.text_muted};
            border:1px solid {p.border_default};
            border-bottom:none;
            padding:6px 14px;
            border-top-left-radius:{r.sm};
            border-top-right-radius:{r.sm};
            margin-right:1px;
        }}
        QTabBar::tab:selected {{
            background:{p.bg_panel};
            color:{p.text_primary};
            border-bottom:2px solid {p.accent};
        }}
        QTabBar::tab:hover:!selected {{
            background:{p.bg_hover};
            color:{p.text_body};
        }}

        /* ============================================================
           QToolTip
           ============================================================ */
        QToolTip {{
            background:{p.bg_input};
            color:{p.text_body};
            border:1px solid {p.border_strong};
            border-radius:{r.sm};
            padding:6px 8px;
            font-size:{t.size_caption};
        }}

        /* ============================================================
           QScrollBar
           ============================================================ */
        QScrollBar:vertical {{
            background:transparent;
            width:10px;
            margin:0;
        }}
        QScrollBar::handle:vertical {{
            background:{p.border_strong};
            border-radius:5px;
            min-height:30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background:{p.text_muted};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height:0;
        }}
        QScrollBar:horizontal {{
            background:transparent;
            height:10px;
            margin:0;
        }}
        QScrollBar::handle:horizontal {{
            background:{p.border_strong};
            border-radius:5px;
            min-width:30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background:{p.text_muted};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width:0;
        }}

        /* ============================================================
           QHeaderView（表格表头）
           ============================================================ */
        QHeaderView::section {{
            background:{p.bg_elevated};
            color:{p.text_secondary};
            padding:5px 8px;
            border:none;
            border-right:1px solid {p.border_default};
            border-bottom:1px solid {p.border_default};
            font-weight:{t.weight_semibold};
        }}

        /* ============================================================
           QTableView / QTreeView / QListView
           ============================================================ */
        QTableView, QTreeView, QListView {{
            background:{p.bg_input};
            color:{p.text_body};
            border:1px solid {p.border_default};
            border-radius:{r.sm};
            selection-background-color:{p.accent};
            selection-color:#FFFFFF;
            alternate-background-color:{p.bg_panel};
        }}
        QTableView::item, QTreeView::item, QListView::item {{
            padding:4px 6px;
            border:none;
        }}
        QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
            background:{p.accent};
            color:#FFFFFF;
        }}

        /* ============================================================
           QDialog
           ============================================================ */
        QDialog {{
            background:{p.bg_app};
        }}

        /* ============================================================
           QMessageBox（原生对话框）
           ============================================================ */
        QMessageBox {{
            background:{p.bg_panel};
        }}
        QMessageBox QLabel {{
            color:{p.text_body};
            font-size:{t.size_body_lg};
        }}

        /* ============================================================
           等宽文本区（代码 / 日志）
           ============================================================ */
        QTextEdit[cssClass="mono"], QPlainTextEdit[cssClass="mono"] {{
            font-family:{t.family_mono};
            font-size:{t.size_caption};
        }}
        """
