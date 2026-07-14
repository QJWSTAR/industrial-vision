"""bridge.communication.heartbeat — 心跳监控（任务7）

周期性健康检查，检测引擎存活。
基于 QThread + 信号，与现有 ZmqRepairClient 架构一致。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal, QTimer

from .config import BridgeConfig
from .protocol import EngineStatus


class HeartbeatMonitor(QThread):
    """后台心跳线程：周期性 ping 引擎，发出状态变更信号。

    信号：
    - status_changed(EngineStatus, str)：状态变化时
    - latency_updated(float)：每次成功 ping 的延迟（秒）
    - engine_lost()：连续 miss 超阈值
    """

    status_changed = Signal(int, str)   # EngineStatus, message
    latency_updated = Signal(float)     # seconds
    engine_lost = Signal()

    def __init__(
        self,
        ping_fn: Callable[[Callable[[bool, str], None]], None],
        config: Optional[BridgeConfig] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ping_fn = ping_fn
        self._config = config or BridgeConfig.from_env()
        self._miss_count = 0
        self._last_status: Optional[EngineStatus] = None
        self._running = False

    def run(self) -> None:
        self._running = True
        interval_ms = self._config.heartbeat_interval_ms
        threshold = self._config.heartbeat_miss_threshold

        while self._running:
            if self.isInterruptionRequested():
                break

            result: list[tuple[bool, str]] = []
            start = time.time()

            try:
                self._ping_fn(lambda ok, msg: result.append((ok, msg)))
            except Exception:
                result.append((False, "心跳调用异常"))

            # 等待回调（最多 1.5x 超时）
            deadline = time.time() + self._config.health_check_timeout_ms / 1000.0 * 1.5
            while not result and time.time() < deadline:
                if self.isInterruptionRequested():
                    return
                self.msleep(50)

            latency = time.time() - start

            if result and result[0][0]:
                self._on_pong(latency, result[0][1])
            else:
                self._on_miss(result[0][1] if result else "心跳超时")

            # sleep 可被中断
            slept = 0
            while slept < interval_ms and self._running:
                if self.isInterruptionRequested():
                    return
                step = min(100, interval_ms - slept)
                self.msleep(step)
                slept += step

    def _on_pong(self, latency: float, message: str) -> None:
        self._miss_count = 0
        self.latency_updated.emit(latency)
        if self._last_status != EngineStatus.OK:
            self._last_status = EngineStatus.OK
            self.status_changed.emit(int(EngineStatus.OK), message)

    def _on_miss(self, reason: str) -> None:
        self._miss_count += 1
        if self._miss_count >= self._config.heartbeat_miss_threshold:
            if self._last_status != EngineStatus.DOWN:
                self._last_status = EngineStatus.DOWN
                self.status_changed.emit(int(EngineStatus.DOWN), f"引擎失联: {reason}")
                self.engine_lost.emit()

    def stop(self, wait_ms: int = 3000) -> None:
        """请求停止并等待线程退出。"""
        self._running = False
        self.requestInterruption()
        self.quit()
        if not self.wait(wait_ms):
            self.terminate()
            self.wait(1000)
