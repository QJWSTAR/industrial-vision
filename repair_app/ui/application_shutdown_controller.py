"""ui.application_shutdown_controller — 应用关闭控制器（Phase 12）

纯 Python 类，不依赖 QObject，可在无 QApplication 环境下使用和测试。

用法::

    controller = ApplicationShutdownController(
        autosave_fn=self._do_autosave,
        autosave_timer=self._autosave_timer,
        worker_threads=[self._path_thread, self._morph_thread, self._compute_thread],
        progress_subscriber=self._progress_subscriber,
        zmq_client=self._zmq_client,
        visualizer=self._visualizer,
    )
    controller.shutdown()
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional


class ApplicationShutdownController:
    """应用关闭控制器。

    标准关闭顺序：
    1. 自动保存
    2. 停止定时器
    3. 停止工作线程（请求中断 + 优雅退出 + 超时强制终止）
    4. 停止进度订阅器
    5. 关闭 MATLAB 生命周期管理器
    6. 关闭 ZMQ 客户端
    7. 清理可视化组件
    """

    # 超时配置（毫秒）
    THREAD_WAIT_MS = 5000
    THREAD_TERMINATE_WAIT_MS = 2000

    def __init__(
        self,
        autosave_fn: Optional[Callable[[], None]] = None,
        autosave_timer: Any = None,
        worker_threads: Optional[List[Any]] = None,
        progress_subscriber: Any = None,
        zmq_client: Any = None,
        visualizer: Any = None,
    ) -> None:
        self._autosave_fn = autosave_fn
        self._autosave_timer = autosave_timer
        self._worker_threads = worker_threads or []
        self._progress_subscriber = progress_subscriber
        self._zmq_client = zmq_client
        self._visualizer = visualizer

    # ── 公开接口 ──────────────────────────────────────────────────

    def shutdown(self) -> None:
        """按标准顺序执行关闭流程。每步独立容错，不因某步异常而中断。"""
        self._step_autosave()
        self._step_stop_timer()
        self._step_stop_worker_threads()
        self._step_stop_progress_subscriber()
        self._step_stop_lifecycle()
        self._step_close_zmq()
        self._step_cleanup_visualizer()

    # ── 关闭步骤 ──────────────────────────────────────────────────

    def _step_autosave(self) -> None:
        """步骤 1：自动保存。"""
        if self._autosave_fn is not None:
            try:
                self._autosave_fn()
            except Exception:
                pass  # 关闭时保存失败不应阻止退出

    def _step_stop_timer(self) -> None:
        """步骤 2：停止自动保存定时器。"""
        if self._autosave_timer is not None and self._autosave_timer.isActive():
            try:
                self._autosave_timer.stop()
            except Exception:
                pass

    def _step_stop_worker_threads(self) -> None:
        """步骤 3：停止所有工作线程。

        顺序：requestInterruption → quit → wait(5s) → terminate(2s)
        """
        for thread in self._worker_threads:
            if thread is None or not thread.isRunning():
                continue
            try:
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(self.THREAD_WAIT_MS):
                    thread.terminate()
                    thread.wait(self.THREAD_TERMINATE_WAIT_MS)
            except Exception:
                pass

    def _step_stop_progress_subscriber(self) -> None:
        """步骤 4：停止实时进度订阅器。"""
        if self._progress_subscriber is not None:
            try:
                if getattr(self._progress_subscriber, 'is_running', False):
                    self._progress_subscriber.stop()
            except Exception:
                pass

    def _step_stop_lifecycle(self) -> None:
        """步骤 5：关闭 MATLAB 生命周期管理器。"""
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            manager = MatlabLifecycleManager.get_instance()
            manager.stop()
        except Exception:
            pass

    def _step_close_zmq(self) -> None:
        """步骤 6：关闭 ZMQ 客户端。"""
        if self._zmq_client is not None and hasattr(self._zmq_client, "close"):
            try:
                self._zmq_client.close()
            except Exception:
                pass

    def _step_cleanup_visualizer(self) -> None:
        """步骤 7：清理可视化组件 matplotlib 资源。"""
        if self._visualizer is not None and hasattr(self._visualizer, "cleanup"):
            try:
                self._visualizer.cleanup()
            except Exception:
                pass