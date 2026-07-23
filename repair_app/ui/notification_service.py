"""ui.notification_service — 统一通知服务

为 MainWindow 提供单一通知入口，封装 Toast / ErrorDialog / StatusBar 三种通知渠道。
可注入、可 mock，方便测试。

用法::

    notifier = NotificationService(parent=main_window, status_bar=status_bar)
    notifier.success("保存成功")
    notifier.error("计算失败", exc=TimeoutError("..."))
    notifier.status("正在连接 MATLAB...", timeout=3000)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QStatusBar, QWidget

from repair_app.ui.toast import Toast
from repair_app.ui.dialogs import ErrorDialog
from repair_app.utils.error_manager import ErrorCode


class NotificationService:
    """统一通知服务 — 单一入口点。

    通知路由规则：
    - success / info / warning → Toast（非阻塞，自动消失）
    - error（无异常）→ Toast（非阻塞）
    - error（有异常）→ Toast + ErrorDialog（模态，用户需确认）
    - status → StatusBar（短暂状态文本）
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        status_bar: Optional[QStatusBar] = None,
    ) -> None:
        self._parent = parent
        self._status_bar = status_bar

    # ── 非阻塞通知（Toast） ──────────────────────────────────────

    def success(self, message: str, duration: int = 3000) -> None:
        """成功通知（Toast，绿色）。"""
        Toast.success(self._parent, message, duration)

    def info(self, message: str, duration: int = 3000) -> None:
        """信息通知（Toast，蓝色）。"""
        Toast.info(self._parent, message, duration)

    def warning(self, message: str, duration: int = 4000) -> None:
        """警告通知（Toast，黄色，稍长显示时间）。"""
        Toast.warning(self._parent, message, duration)

    def error(
        self,
        message: str,
        exc: Optional[Exception] = None,
        code: Optional[ErrorCode] = None,
        context: str = "",
        duration: int = 5000,
    ) -> None:
        """错误通知。

        - 始终显示 Toast（红色，5 秒）
        - 若提供异常，额外弹出 ErrorDialog（模态，用户需关闭）
        """
        Toast.error(self._parent, message, duration)
        if exc is not None:
            ErrorDialog.show(
                self._parent,
                exc=exc,
                code=code,
                context=context,
            )

    # ── 状态栏通知 ───────────────────────────────────────────────

    def status(self, message: str, timeout: int = 0) -> None:
        """状态栏短文本（timeout=0 表示持久显示直到下一条）。"""
        if self._status_bar is not None:
            self._status_bar.showMessage(message, timeout)

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def parent(self) -> Optional[QWidget]:
        return self._parent

    @property
    def status_bar(self) -> Optional[QStatusBar]:
        return self._status_bar