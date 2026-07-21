"""test_gui.py — GUI 组件测试

验证 PySide6 GUI 组件创建、属性、交互。
覆盖 MainWindow / DefectSelector / RepairVisualizer / ThemeManager /
Toast / ContextMenuManager。

使用 conftest.py 的 qapp fixture（session 级别，offscreen 模式）。

运行：pytest -m gui -v
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest


# ================================================================
# Fixture: MainWindow（每个测试独立实例，自动清理）
# ================================================================
@pytest.fixture
def main_window(qapp, monkeypatch):
    """提供 MainWindow 实例，测试后自动清理 ZMQ client 与 widget。

    关键：mock QMessageBox 避免模态对话框阻塞测试；
          清理 AutoRecovery 状态避免 _check_recovery 弹窗。
    """
    # mock QMessageBox 所有静态方法（避免模态对话框阻塞）
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: None)

    # 清理 AutoRecovery 状态（避免 _check_recovery 弹窗）
    try:
        from repair_app.software.path_manager import PathManager
        from repair_app.software.project_manager import AutoRecovery
        pm = PathManager.get_instance()
        ar = AutoRecovery(pm)
        ar.clear()  # 清除任何残留的恢复状态
    except Exception:
        pass

    from repair_app.ui.main_window import MainWindow
    mw = MainWindow()
    yield mw
    # 清理 ZMQ client
    if hasattr(mw, "_zmq_client") and mw._zmq_client is not None:
        try:
            mw._zmq_client.close()
        except Exception:
            pass
    # 停止所有定时器（避免 teardown 后回调）
    if hasattr(mw, "_timers"):
        for timer in mw._timers:
            try:
                timer.stop()
            except Exception:
                pass
    mw.deleteLater()
    qapp.processEvents()


# ================================================================
# 1. MainWindow 测试
# ================================================================
@pytest.mark.gui
class TestMainWindow:
    """主窗口创建与结构验证。"""

    def test_main_window_creation(self, main_window):
        """MainWindow 可成功创建且为 QMainWindow 实例。"""
        from PySide6.QtWidgets import QMainWindow
        assert isinstance(main_window, QMainWindow), "MainWindow 应为 QMainWindow 实例"

    def test_menubar_has_5_menus(self, main_window):
        """菜单栏包含 5 个菜单（文件/高级/编辑/视图/帮助）。"""
        menubar = main_window.menuBar()
        actions = menubar.actions()
        assert len(actions) == 5, f"菜单栏应有 5 个菜单，实际 {len(actions)}"
        # 验证菜单文本（含中文菜单名）
        menu_texts = [a.text() for a in actions]
        has_file = any("文件" in t for t in menu_texts)
        has_adv = any("高级" in t for t in menu_texts)
        has_edit = any("编辑" in t for t in menu_texts)
        has_view = any("视图" in t for t in menu_texts)
        has_help = any("帮助" in t for t in menu_texts)
        assert has_file, "应有文件菜单"
        assert has_adv, "应有高级菜单"
        assert has_edit, "应有编辑菜单"
        assert has_view, "应有视图菜单"
        assert has_help, "应有帮助菜单"

    def test_toolbar_exists(self, main_window):
        """主窗口包含至少 1 个工具栏。"""
        from PySide6.QtWidgets import QToolBar
        toolbars = main_window.findChildren(QToolBar)
        assert len(toolbars) >= 1, "应至少有 1 个工具栏"

    def test_statusbar_has_busy_label(self, main_window):
        """状态栏包含 BusyLabel 实例。"""
        from repair_app.ui.busy_indicator import BusyLabel
        assert hasattr(main_window, "_busy_label"), "MainWindow 应有 _busy_label 属性"
        assert isinstance(main_window._busy_label, BusyLabel), (
            "_busy_label 应为 BusyLabel 实例"
        )

    def test_has_defect_selector(self, main_window):
        """MainWindow 包含 DefectSelector 实例。"""
        from repair_app.ui.defect_selector import DefectSelector
        assert hasattr(main_window, "_selector"), "MainWindow 应有 _selector 属性"
        assert isinstance(main_window._selector, DefectSelector), (
            "_selector 应为 DefectSelector 实例"
        )

    def test_has_repair_visualizer(self, main_window):
        """MainWindow 包含 RepairVisualizer 实例。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        assert hasattr(main_window, "_visualizer"), "MainWindow 应有 _visualizer 属性"
        assert isinstance(main_window._visualizer, RepairVisualizer), (
            "_visualizer 应为 RepairVisualizer 实例"
        )


# ================================================================
# 2. DefectSelector 测试
# ================================================================
@pytest.mark.gui
class TestDefectSelector:
    """缺陷选区组件测试。"""

    def test_defect_selector_creation(self, qapp):
        """DefectSelector 可成功创建。"""
        from repair_app.ui.defect_selector import DefectSelector
        from PySide6.QtWidgets import QWidget
        selector = DefectSelector()
        assert isinstance(selector, QWidget), "DefectSelector 应为 QWidget 子类"
        selector.deleteLater()

    def test_set_points_initializes_mask(self, qapp):
        """set_points 后选区掩码初始化为全 False。"""
        from repair_app.ui.defect_selector import DefectSelector
        selector = DefectSelector()
        try:
            points = np.random.rand(50, 3).astype(np.float32)
            selector.set_points(points)
            mask = selector.get_selection_mask()
            assert len(mask) == 50, f"掩码长度应为 50，实际 {len(mask)}"
            assert mask.dtype == bool, "掩码应为 bool 类型"
            assert not np.any(mask), "初始化后掩码应全为 False"
        finally:
            selector.deleteLater()

    def test_clear_selection(self, qapp):
        """clear_selection 清除全部选区。"""
        from repair_app.ui.defect_selector import DefectSelector
        selector = DefectSelector()
        try:
            points = np.random.rand(20, 3).astype(np.float32)
            selector.set_points(points)
            # 先设置部分选区为 True
            mask = np.zeros(20, dtype=bool)
            mask[5:15] = True
            selector.set_selection_mask(mask)
            assert np.any(selector.get_selection_mask()), "设置后应有选区"
            # 清除选区
            selector.clear_selection()
            cleared = selector.get_selection_mask()
            assert not np.any(cleared), "清除后掩码应全为 False"
        finally:
            selector.deleteLater()

    def test_invert_selection(self, qapp):
        """invert_selection 反转选区。"""
        from repair_app.ui.defect_selector import DefectSelector
        selector = DefectSelector()
        try:
            points = np.random.rand(20, 3).astype(np.float32)
            selector.set_points(points)
            # 设置前 10 个为选中
            mask = np.zeros(20, dtype=bool)
            mask[:10] = True
            selector.set_selection_mask(mask)
            # 反选
            selector.invert_selection()
            inverted = selector.get_selection_mask()
            # 反选后：前 10 个为 False，后 10 个为 True
            assert not np.any(inverted[:10]), "反选后前 10 个应为 False"
            assert np.all(inverted[10:]), "反选后后 10 个应为 True"
        finally:
            selector.deleteLater()


# ================================================================
# 3. RepairVisualizer 测试
# ================================================================
@pytest.mark.gui
class TestRepairVisualizer:
    """修复可视化组件测试。"""

    def test_repair_visualizer_creation(self, qapp):
        """RepairVisualizer 可成功创建。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        from PySide6.QtWidgets import QWidget
        viz = RepairVisualizer()
        assert isinstance(viz, QWidget), "RepairVisualizer 应为 QWidget 子类"
        viz.deleteLater()

    def test_set_data(self, qapp):
        """set_data 设置基体点云不崩溃。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        viz = RepairVisualizer()
        try:
            substrate = np.random.rand(50, 3).astype(np.float32)
            defect_mask = np.zeros(50, dtype=bool)
            defect_mask[10:30] = True
            # 不应抛异常
            viz.set_data(substrate, defect_mask=defect_mask)
            # 验证数据已设置
            assert viz._substrate_pts is not None, "set_data 后 _substrate_pts 不应为 None"
            assert len(viz._substrate_pts) == 50, "基体点数应为 50"
        finally:
            viz.deleteLater()

    def test_reset_view(self, qapp):
        """reset_view 不崩溃。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        viz = RepairVisualizer()
        try:
            substrate = np.random.rand(20, 3).astype(np.float32)
            viz.set_data(substrate)
            # 不应抛异常
            viz.reset_view()
        finally:
            viz.deleteLater()

    def test_toggle_axes(self, qapp):
        """toggle_axes 不崩溃。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        viz = RepairVisualizer()
        try:
            substrate = np.random.rand(20, 3).astype(np.float32)
            viz.set_data(substrate)
            # 不应抛异常
            viz.toggle_axes()
        finally:
            viz.deleteLater()


# ================================================================
# 4. ThemeManager 测试
# ================================================================
@pytest.mark.gui
class TestThemeManager:
    """主题管理器测试。"""

    def test_get_qss_nonempty(self, qapp):
        """get_qss 返回非空 QSS 字符串。"""
        from repair_app.ui.theme_manager import ThemeManager
        qss = ThemeManager.get_qss()
        assert isinstance(qss, str), "QSS 应为字符串"
        assert len(qss) > 0, "QSS 不应为空"
        # QSS 应包含基本的样式定义（如 background 或 color）
        assert "background" in qss.lower() or "color" in qss.lower(), (
            "QSS 应包含 background 或 color 样式定义"
        )

    def test_get_palette(self, qapp):
        """get_palette 返回调色板对象且含颜色 token。"""
        from repair_app.ui.theme_manager import ThemeManager, Palette
        palette = ThemeManager.get_palette()
        assert palette is not None, "调色板不应为 None"
        # 验证调色板包含核心颜色 token
        assert hasattr(palette, "bg_app"), "调色板应有 bg_app 属性"
        assert hasattr(palette, "text_primary"), "调色板应有 text_primary 属性"
        assert hasattr(palette, "accent"), "调色板应有 accent 属性"
        # 验证颜色值为非空字符串（hex 格式）
        assert isinstance(palette.bg_app, str), "bg_app 应为字符串"
        assert palette.bg_app.startswith("#"), "bg_app 应为 hex 颜色值"

    def test_set_theme(self, qapp):
        """set_theme 切换主题不崩溃且调色板更新。"""
        from repair_app.ui.theme_manager import ThemeManager
        # 切换到浅色主题
        ThemeManager.set_theme("light")
        light_palette = ThemeManager.get_palette()
        assert light_palette is not None, "浅色主题调色板不应为 None"
        # 切换回深色主题
        ThemeManager.set_theme("dark")
        dark_palette = ThemeManager.get_palette()
        assert dark_palette is not None, "深色主题调色板不应为 None"


# ================================================================
# 5. Toast 测试
# ================================================================
@pytest.mark.gui
class TestToast:
    """Toast 通知组件测试。"""

    def test_four_levels_in_styles(self, qapp):
        """Toast._STYLES 包含 4 个级别（info/success/warning/error）。"""
        from repair_app.ui.toast import Toast
        assert hasattr(Toast, "_STYLES"), "Toast 应有 _STYLES 属性"
        assert len(Toast._STYLES) == 4, (
            f"_STYLES 应有 4 个级别，实际 {len(Toast._STYLES)}"
        )
        assert "info" in Toast._STYLES, "应包含 info 级别"
        assert "success" in Toast._STYLES, "应包含 success 级别"
        assert "warning" in Toast._STYLES, "应包含 warning 级别"
        assert "error" in Toast._STYLES, "应包含 error 级别"
        # 每个级别应有 color 和 icon
        for level, style in Toast._STYLES.items():
            assert "color" in style, f"{level} 应有 color 属性"
            assert "icon" in style, f"{level} 应有 icon 属性"

    def test_toast_info(self, qapp):
        """Toast.info 创建 info 级别 Toast。"""
        from repair_app.ui.toast import Toast
        from PySide6.QtWidgets import QWidget, QLabel
        parent = QWidget()
        try:
            toast = Toast.info(parent, "信息消息")
            assert isinstance(toast, Toast), "Toast.info 应返回 Toast 实例"
            # 验证标签包含消息文本和 info 图标
            labels = toast.findChildren(QLabel)
            assert len(labels) > 0, "Toast 应至少有 1 个 QLabel"
            assert "信息消息" in labels[0].text(), "Toast 应包含消息文本"
            assert Toast._STYLES["info"]["icon"] in labels[0].text(), "Toast 应包含 info 图标"
            toast.close()
        finally:
            parent.deleteLater()

    def test_toast_success(self, qapp):
        """Toast.success 创建 success 级别 Toast。"""
        from repair_app.ui.toast import Toast
        from PySide6.QtWidgets import QWidget, QLabel
        parent = QWidget()
        try:
            toast = Toast.success(parent, "成功消息")
            assert isinstance(toast, Toast), "Toast.success 应返回 Toast 实例"
            labels = toast.findChildren(QLabel)
            assert len(labels) > 0, "Toast 应至少有 1 个 QLabel"
            assert "成功消息" in labels[0].text(), "Toast 应包含消息文本"
            assert Toast._STYLES["success"]["icon"] in labels[0].text(), (
                "Toast 应包含 success 图标"
            )
            toast.close()
        finally:
            parent.deleteLater()

    def test_toast_warning(self, qapp):
        """Toast.warning 创建 warning 级别 Toast。"""
        from repair_app.ui.toast import Toast
        from PySide6.QtWidgets import QWidget, QLabel
        parent = QWidget()
        try:
            toast = Toast.warning(parent, "警告消息")
            assert isinstance(toast, Toast), "Toast.warning 应返回 Toast 实例"
            labels = toast.findChildren(QLabel)
            assert len(labels) > 0, "Toast 应至少有 1 个 QLabel"
            assert "警告消息" in labels[0].text(), "Toast 应包含消息文本"
            assert Toast._STYLES["warning"]["icon"] in labels[0].text(), (
                "Toast 应包含 warning 图标"
            )
            toast.close()
        finally:
            parent.deleteLater()

    def test_toast_error(self, qapp):
        """Toast.error 创建 error 级别 Toast。"""
        from repair_app.ui.toast import Toast
        from PySide6.QtWidgets import QWidget, QLabel
        parent = QWidget()
        try:
            toast = Toast.error(parent, "错误消息")
            assert isinstance(toast, Toast), "Toast.error 应返回 Toast 实例"
            labels = toast.findChildren(QLabel)
            assert len(labels) > 0, "Toast 应至少有 1 个 QLabel"
            assert "错误消息" in labels[0].text(), "Toast 应包含消息文本"
            assert Toast._STYLES["error"]["icon"] in labels[0].text(), (
                "Toast 应包含 error 图标"
            )
            toast.close()
        finally:
            parent.deleteLater()


# ================================================================
# 6. ContextMenuManager 测试
# ================================================================
@pytest.mark.gui
class TestContextMenuManager:
    """右键上下文菜单管理器测试。"""

    def test_context_menu_creation(self, main_window):
        """ContextMenuManager 可成功创建。"""
        from repair_app.ui.context_menu import ContextMenuManager
        mgr = ContextMenuManager(main_window)
        assert isinstance(mgr, ContextMenuManager), "应为 ContextMenuManager 实例"

    def test_context_menu_has_actions(self, main_window):
        """ContextMenuManager 包含视图/选区/导出动作处理方法。"""
        from repair_app.ui.context_menu import ContextMenuManager
        mgr = ContextMenuManager(main_window)
        # 验证视图组动作
        assert hasattr(mgr, "_on_reset_view"), "应有 _on_reset_view 方法"
        assert hasattr(mgr, "_on_fit_view"), "应有 _on_fit_view 方法"
        assert hasattr(mgr, "_on_toggle_axes"), "应有 _on_toggle_axes 方法"
        # 验证选区组动作
        assert hasattr(mgr, "_on_clear_selection"), "应有 _on_clear_selection 方法"
        assert hasattr(mgr, "_on_invert_selection"), "应有 _on_invert_selection 方法"
        # 验证导出组动作
        assert hasattr(mgr, "_on_export_gcode"), "应有 _on_export_gcode 方法"
        assert hasattr(mgr, "_on_export_robot"), "应有 _on_export_robot 方法"
        # show_context_menu 应可调用
        assert callable(mgr.show_context_menu), "show_context_menu 应可调用"
