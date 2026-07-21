"""undo_framework.py — 全局 Undo/Redo 框架

参考 SolidWorks / Siemens NX 的特征树撤销。
基于 Qt QUndoStack + QUndoCommand。

支持：
- Ctrl+Z 撤销
- Ctrl+Y / Ctrl+Shift+Z 重做
- 选区操作撤销（push 到栈）
- 参数修改撤销
- 菜单项状态联动（enabled 随栈变化）

用法：
    from repair_app.ui.undo_framework import UndoStack

    stack = UndoStack.instance()
    stack.push(UndoableSelection(...))
"""
from __future__ import annotations

from typing import Optional, Callable, Any
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack, QUndoCommand, QAction


class UndoableAction(QUndoCommand):
    """可撤销动作的基类。

    子类需要实现：
    - undo(): 撤销操作
    - redo(): 执行操作（首次 push 时也会调用）
    """

    def __init__(self, text: str, parent: Optional[QObject] = None) -> None:
        super().__init__(text, parent)


class CallbackAction(UndoableAction):
    """基于回调的可撤销动作。

    用法：
        cmd = CallbackAction(
            text="修改层高",
            do_callback=lambda: set_value(2.0),
            undo_callback=lambda: set_value(1.0),
        )
        stack.push(cmd)
    """

    def __init__(
        self,
        text: str,
        do_callback: Callable[[], None],
        undo_callback: Callable[[], None],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(text, parent)
        self._do = do_callback
        self._undo = undo_callback
        self._first_redo = True

    def redo(self) -> None:
        """执行动作（首次 push 时调用）。"""
        if self._first_redo:
            # 首次 redo 不执行回调（因为业务层已经执行了操作）
            self._first_redo = False
        else:
            self._do()

    def undo(self) -> None:
        """撤销动作。"""
        self._undo()


class SelectionAction(UndoableAction):
    """选区操作动作（针对 DefectSelector 的选区修改）。"""

    def __init__(
        self,
        selector,
        old_mask,
        new_mask,
        text: str = "修改选区",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(text, parent)
        self._selector = selector
        self._old_mask = old_mask.copy() if old_mask is not None else None
        self._new_mask = new_mask.copy() if new_mask is not None else None

    def redo(self) -> None:
        """应用新选区。"""
        if self._selector is not None and self._new_mask is not None:
            self._selector.set_selection_mask(self._new_mask)

    def undo(self) -> None:
        """恢复旧选区。"""
        if self._selector is not None and self._old_mask is not None:
            self._selector.set_selection_mask(self._old_mask)


class UndoStack(QObject):
    """全局撤销栈管理器（单例）。

    职责：
    - 维护 QUndoStack
    - 提供 create_undo_action / create_redo_action（供菜单/工具栏使用）
    - 联动 enabled 状态
    """

    _instance: Optional["UndoStack"] = None
    _stack: QUndoStack
    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._stack = QUndoStack(self)
        self._stack.cleanChanged.connect(lambda clean: self.changed.emit())
        self._stack.indexChanged.connect(lambda idx: self.changed.emit())

    @classmethod
    def instance(cls) -> "UndoStack":
        """获取单例。"""
        if cls._instance is None:
            cls._instance = UndoStack()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（测试用）。"""
        cls._instance = None

    def push(self, cmd: QUndoCommand) -> None:
        """压入撤销命令。"""
        self._stack.push(cmd)

    def can_undo(self) -> bool:
        return self._stack.canUndo()

    def can_redo(self) -> bool:
        return self._stack.canRedo()

    def undo(self) -> None:
        self._stack.undo()

    def redo(self) -> None:
        self._stack.redo()

    def clear(self) -> None:
        self._stack.clear()

    def create_undo_action(self, parent: QObject, text: str = "撤销") -> QAction:
        """创建撤销 QAction（自动联动 enabled）。"""
        action = self._stack.createUndoAction(parent, text)
        action.setShortcut("Ctrl+Z")
        return action

    def create_redo_action(self, parent: QObject, text: str = "重做") -> QAction:
        """创建重做 QAction（自动联动 enabled）。"""
        action = self._stack.createRedoAction(parent, text)
        # Ctrl+Y 或 Ctrl+Shift+Z
        action.setShortcuts(["Ctrl+Y", "Ctrl+Shift+Z"])
        return action

    def undo_text(self) -> str:
        """当前可撤销操作的文本（供菜单显示）。"""
        if self._stack.canUndo():
            return f"撤销 {self._stack.undoText()}"
        return "撤销"

    def redo_text(self) -> str:
        """当前可重做操作的文本（供菜单显示）。"""
        if self._stack.canRedo():
            return f"重做 {self._stack.redoText()}"
        return "重做"
