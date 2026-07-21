"""
worker_base.py — Worker 生命周期统一管理基类

P3-1: 统一启动/取消/timeout/cleanup，消除线程残留风险。

设计原则：
  1. 所有 Worker 继承 BaseWorker，获得统一的取消和 timeout 机制
  2. 通过 elapsed 计时实现总超时，超时自动中断
  3. cleanup() 钩子供子类清理资源（socket/进程等）
  4. 不修改现有 Worker 的业务逻辑，仅增强生命周期管理
"""

from __future__ import annotations
import time
from PySide6.QtCore import QObject, QThread, Signal

from repair_app.utils.logger_config import info, warning, error as log_error


class BaseWorker(QObject):
    """Worker 基类：统一取消/timeout/cleanup。

    子类需实现 run()，并在循环中调用 check_interruption()。
    可选重写 cleanup() 清理资源。

    信号：
        timeout_elapsed: Worker 总超时触发（主线程连接后可弹提示）
    """

    timeout_elapsed = Signal(str)  # worker_name

    def __init__(
        self,
        *,
        timeout_s: float | None = None,  # 总超时（秒），None 表示不限制
        check_interval: float = 0.5,     # 超时检查间隔（秒）
    ) -> None:
        super().__init__()
        self._timeout_s = timeout_s
        self._check_interval = check_interval
        self._start_time: float | None = None
        self._worker_name = self.__class__.__name__

    def _mark_start(self) -> None:
        """标记 Worker 开始执行（启动计时）。"""
        self._start_time = time.monotonic()
        info(f"[{self._worker_name}] 启动，timeout={self._timeout_s}s")

    def _check_timeout(self) -> bool:
        """检查是否超时。超时返回 True。"""
        if self._timeout_s is None or self._start_time is None:
            return False
        elapsed = time.monotonic() - self._start_time
        if elapsed > self._timeout_s:
            warning(f"[{self._worker_name}] 总超时 {self._timeout_s}s（已运行 {elapsed:.1f}s）")
            self.timeout_elapsed.emit(self._worker_name)
            return True
        return False

    def check_interruption(self) -> bool:
        """在 Worker 循环中调用：检查中断或超时。

        返回 True 表示应中断（退出循环），False 表示继续。
        """
        thread = QThread.currentThread()
        if thread is not None and thread.isInterruptionRequested():
            info(f"[{self._worker_name}] 收到中断请求，退出")
            return True
        if self._check_timeout():
            return True
        return False

    def cleanup(self) -> None:
        """子类重写：清理资源（socket/子进程/临时文件等）。

        在 thread.finished 信号触发时调用。
        默认实现为空。
        """
        pass


class WorkerManager:
    """Worker 管理器：统一管理所有 Worker 的启动/取消/cleanup。

    用法：
        mgr = WorkerManager(parent=main_window)
        mgr.start("path", worker, thread, on_finished)
        mgr.cancel_all()  # closeEvent 时调用
        mgr.cleanup_all()  # 退出前清理
    """

    def __init__(self, parent: QObject | None = None) -> None:
        self._parent = parent
        self._workers: dict[str, tuple[BaseWorker, QThread]] = {}
        self._wait_ms = 5000
        self._terminate_wait_ms = 2000

    def start(
        self,
        name: str,
        worker: BaseWorker,
        thread: QThread,
        on_finished=None,
    ) -> None:
        """统一启动 Worker。

        Args:
            name: Worker 名称（如 "path"/"morph"/"compute"）
            worker: BaseWorker 实例
            thread: QThread 实例
            on_finished: thread.finished 回调（可选）
        """
        # 若同名 Worker 仍在运行，先停止
        if name in self._workers:
            old_worker, old_thread = self._workers[name]
            if old_thread.isRunning():
                warning(f"[WorkerManager] {name} 仍在运行，强制停止")
                self.cancel(name)

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.cleanup)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        if on_finished is not None:
            thread.finished.connect(on_finished)

        self._workers[name] = (worker, thread)
        thread.start()
        info(f"[WorkerManager] 启动 {name}")

    def cancel(self, name: str) -> None:
        """取消指定 Worker（请求中断 + 等待退出）。"""
        if name not in self._workers:
            return
        worker, thread = self._workers[name]
        if thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            ok = thread.wait(self._wait_ms)
            if not ok:
                warning(f"[WorkerManager] {name} 等待 {self._wait_ms}ms 未退出，terminate")
                thread.terminate()
                thread.wait(self._terminate_wait_ms)
        try:
            worker.cleanup()
        except Exception as exc:
            log_error(f"[WorkerManager] {name} cleanup 失败: {exc}")
        info(f"[WorkerManager] 已取消 {name}")

    def cancel_all(self) -> None:
        """取消所有 Worker（closeEvent 时调用）。"""
        for name in list(self._workers.keys()):
            self.cancel(name)

    def cleanup_all(self) -> None:
        """清理所有 Worker 引用。"""
        self._workers.clear()

    def is_any_running(self) -> bool:
        """是否有 Worker 在运行。"""
        return any(t.isRunning() for _, t in self._workers.values())

    def get_running_names(self) -> list[str]:
        """获取正在运行的 Worker 名称列表。"""
        return [n for n, (_, t) in self._workers.items() if t.isRunning()]
