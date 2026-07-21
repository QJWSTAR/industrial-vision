"""toast.py — 非模态浮层提示（Toast Notification）

参考 VS Code / Materialise Magics 的右下角通知。
不阻塞用户操作，自动消失，支持 4 种级别。

用法：
    from repair_app.ui.toast import Toast

    Toast.info(parent, "项目已保存")
    Toast.success(parent, "计算完成")
    Toast.warning(parent, "MATLAB 未启动")
    Toast.error(parent, "导出失败")
"""
from __future__ import annotations

from typing import Optional
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QEasingCurve, QPoint
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication, QGraphicsOpacityEffect

from repair_app.ui.theme_manager import ThemeManager


class Toast(QWidget):
    """非模态浮层提示。

    特性：
    - 右下角浮层，不抢焦点
    - 自动消失（默认 3 秒）
    - 淡入淡出动画
    - 4 种级别（info / success / warning / error）
    - 多条堆叠
    """

    # 级别样式
    _STYLES = {
        "info":    {"color": "#3B82F6", "icon": "ℹ"},
        "success": {"color": "#10B981", "icon": "✓"},
        "warning": {"color": "#F59E0B", "icon": "⚠"},
        "error":   {"color": "#EF4444", "icon": "✕"},
    }

    # 堆叠管理：当前活跃的 Toast 列表
    _active_toasts: list = []

    def __init__(
        self,
        parent: Optional[QWidget],
        message: str,
        level: str = "info",
        duration: int = 3000,
    ) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        style = self._STYLES.get(level, self._STYLES["info"])
        accent_color = style["color"]
        icon = style["icon"]

        p = ThemeManager.get_palette()

        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(4)

        # 消息标签
        label = QLabel(f"{icon}  {message}")
        label.setStyleSheet(f"""
            color:{p.text_primary};
            font-size:13px;
            font-weight:500;
            background:transparent;
        """)
        layout.addWidget(label)

        # 整体样式
        self.setStyleSheet(f"""
            QWidget#Toast {{
                background:{p.bg_panel};
                border:1px solid {p.border_default};
                border-left:3px solid {accent_color};
                border-radius:4px;
            }}
        """)
        self.setObjectName("Toast")
        self.setFixedWidth(360)
        self.adjustSize()

        # 淡入动画
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        # 淡出动画
        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.close)

        # 自动消失定时器
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start_fade_out)

        self._duration = duration
        self._parent = parent

    def show_toast(self) -> None:
        """显示 Toast（堆叠在右下角）。"""
        # 计算位置
        if self._parent is not None:
            parent_rect = self._parent.rect()
            parent_global = self._parent.mapToGlobal(QPoint(0, 0))
        else:
            screen = QApplication.primaryScreen().geometry()
            parent_rect = screen
            parent_global = QPoint(0, 0)

        # 堆叠：从下往上排列，每条间隔 8px
        offset_y = 16 + len(Toast._active_toasts) * (self.height() + 8)
        x = parent_global.x() + parent_rect.width() - self.width() - 16
        y = parent_global.y() + parent_rect.height() - self.height() - offset_y
        self.move(x, y)

        # 加入活跃列表
        Toast._active_toasts.append(self)

        # 显示
        self.show()
        self._fade_in.start()
        self._timer.start(self._duration)

    def _start_fade_out(self) -> None:
        """开始淡出。"""
        if self in Toast._active_toasts:
            Toast._active_toasts.remove(self)
            self._reposition_others()
        self._fade_out.start()

    def _reposition_others(self) -> None:
        """重新排列剩余的 Toast（向上移动）。"""
        if self._parent is None:
            return
        parent_rect = self._parent.rect()
        parent_global = self._parent.mapToGlobal(QPoint(0, 0))
        for i, toast in enumerate(Toast._active_toasts):
            offset_y = 16 + i * (toast.height() + 8)
            x = parent_global.x() + parent_rect.width() - toast.width() - 16
            y = parent_global.y() + parent_rect.height() - toast.height() - offset_y
            toast.move(x, y)

    # ============================================================
    # 便捷类方法
    # ============================================================

    @classmethod
    def info(cls, parent: Optional[QWidget], message: str, duration: int = 3000) -> "Toast":
        toast = cls(parent, message, "info", duration)
        toast.show_toast()
        return toast

    @classmethod
    def success(cls, parent: Optional[QWidget], message: str, duration: int = 3000) -> "Toast":
        toast = cls(parent, message, "success", duration)
        toast.show_toast()
        return toast

    @classmethod
    def warning(cls, parent: Optional[QWidget], message: str, duration: int = 4000) -> "Toast":
        toast = cls(parent, message, "warning", duration)
        toast.show_toast()
        return toast

    @classmethod
    def error(cls, parent: Optional[QWidget], message: str, duration: int = 5000) -> "Toast":
        toast = cls(parent, message, "error", duration)
        toast.show_toast()
        return toast
