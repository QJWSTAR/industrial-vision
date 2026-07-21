"""context_menu.py — 右键上下文菜单管理器

参考 Siemens NX / Geomagic 的视图右键菜单。
支持在主视图（RepairVisualizer）上右键弹出功能菜单。

用法：
    from repair_app.ui.context_menu import ContextMenuManager

    mgr = ContextMenuManager(self)
    self._visualizer.setContextMenuPolicy(Qt.CustomContextMenu)
    self._visualizer.customContextMenuRequested.connect(mgr.show_context_menu)
"""
from __future__ import annotations

from typing import Optional, Callable
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtWidgets import QWidget, QMenu
from PySide6.QtGui import QAction, QActionGroup

from repair_app.utils.logger_config import warning


class ContextMenuManager(QObject):
    """右键上下文菜单管理器。

    特性：
    - 动态构建菜单（根据当前状态）
    - 分组组织（视图 / 选区 / 工具 / 导出）
    - 快捷键联动
    - 状态联动（无点云时禁用相关项）
    """

    def __init__(self, main_window: QWidget) -> None:
        super().__init__(main_window)
        self._main_window = main_window

    def show_context_menu(self, pos: QPoint) -> None:
        """在指定位置显示右键菜单。

        Args:
            pos: 相对于目标 widget 的位置
        """
        menu = QMenu(self._main_window)
        menu.setObjectName("ContextMenu")

        mw = self._main_window

        # ---- 视图组 ----
        view_group = menu.addSection("视图")

        act_reset_view = menu.addAction("重置视角")
        act_reset_view.setShortcut("F")
        act_reset_view.triggered.connect(self._on_reset_view)
        act_reset_view.setEnabled(hasattr(mw, "_visualizer") and mw._visualizer is not None)

        act_fit = menu.addAction("适应窗口")
        act_fit.setShortcut("Ctrl+Shift+F")
        act_fit.triggered.connect(self._on_fit_view)
        act_fit.setEnabled(hasattr(mw, "_visualizer") and mw._visualizer is not None)

        act_toggle_axes = menu.addAction("显示/隐藏坐标轴")
        act_toggle_axes.setCheckable(True)
        act_toggle_axes.setChecked(True)
        act_toggle_axes.triggered.connect(self._on_toggle_axes)
        act_toggle_axes.setEnabled(hasattr(mw, "_visualizer") and mw._visualizer is not None)

        menu.addSeparator()

        # ---- 选区组 ----
        sel_group = menu.addSection("选区")

        act_clear_sel = menu.addAction("清除选区")
        act_clear_sel.triggered.connect(self._on_clear_selection)
        act_clear_sel.setEnabled(
            hasattr(mw, "_selector") and mw._selector is not None
        )

        act_invert_sel = menu.addAction("反选")
        act_invert_sel.triggered.connect(self._on_invert_selection)
        act_invert_sel.setEnabled(
            hasattr(mw, "_selector") and mw._selector is not None
        )

        menu.addSeparator()

        # ---- 工具组 ----
        tool_group = menu.addSection("工具")

        act_undo = menu.addAction("撤销")
        act_undo.setShortcut("Ctrl+Z")
        act_undo.triggered.connect(self._on_undo)
        act_undo.setEnabled(self._can_undo())

        act_redo = menu.addAction("重做")
        act_redo.setShortcut("Ctrl+Y")
        act_redo.triggered.connect(self._on_redo)
        act_redo.setEnabled(self._can_redo())

        menu.addSeparator()

        # ---- 导出组 ----
        export_group = menu.addSection("导出")

        act_export_gcode = menu.addAction("导出 G-code...")
        act_export_gcode.setShortcut("Ctrl+E")
        act_export_gcode.triggered.connect(self._on_export_gcode)

        act_export_robot = menu.addAction("导出机器人轨迹...")
        act_export_robot.setShortcut("Ctrl+R")
        act_export_robot.triggered.connect(self._on_export_robot)

        # ---- 显示菜单 ----
        if hasattr(mw, "_visualizer") and mw._visualizer is not None:
            global_pos = mw._visualizer.mapToGlobal(pos)
        else:
            global_pos = mw.mapToGlobal(pos)
        menu.exec(global_pos)

    # ============================================================
    # 动作处理（委托给主窗口）
    # ============================================================

    def _on_reset_view(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_visualizer") and mw._visualizer is not None:
            try:
                mw._visualizer.reset_view()
            except Exception as exc:
                warning(f"重置视角失败: {exc}")

    def _on_fit_view(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_visualizer") and mw._visualizer is not None:
            try:
                mw._visualizer.fit_to_view()
            except Exception as exc:
                warning(f"适应窗口失败: {exc}")

    def _on_toggle_axes(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_visualizer") and mw._visualizer is not None:
            try:
                mw._visualizer.toggle_axes()
            except Exception as exc:
                warning(f"切换坐标轴失败: {exc}")

    def _on_clear_selection(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_selector") and mw._selector is not None:
            try:
                mw._selector.clear_selection()
            except Exception as exc:
                warning(f"清除选区失败: {exc}")

    def _on_invert_selection(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_selector") and mw._selector is not None:
            try:
                mw._selector.invert_selection()
            except Exception as exc:
                warning(f"反选失败: {exc}")

    def _can_undo(self) -> bool:
        try:
            from repair_app.ui.undo_framework import UndoStack
            return UndoStack.instance().can_undo()
        except Exception:
            return False

    def _can_redo(self) -> bool:
        try:
            from repair_app.ui.undo_framework import UndoStack
            return UndoStack.instance().can_redo()
        except Exception:
            return False

    def _on_undo(self) -> None:
        try:
            from repair_app.ui.undo_framework import UndoStack
            UndoStack.instance().undo()
        except Exception as exc:
            warning(f"撤销失败: {exc}")

    def _on_redo(self) -> None:
        try:
            from repair_app.ui.undo_framework import UndoStack
            UndoStack.instance().redo()
        except Exception as exc:
            warning(f"重做失败: {exc}")

    def _on_export_gcode(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_on_export_gcode"):
            mw._on_export_gcode()

    def _on_export_robot(self) -> None:
        mw = self._main_window
        if hasattr(mw, "_on_export_robot"):
            mw._on_export_robot()
