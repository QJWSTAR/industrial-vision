"""ui.progress_subscriber — GUI 侧进度订阅器

在 QThread 中订阅 ZMQ PUB (port 5556)，接收 ProgressUpdate 消息，
通过 Qt 信号驱动 GUI 实时刷新。

信号：
    progress_received(dict) : 完整解析的 ProgressUpdate dict
    layer_completed(int)    : 当前完成的层号
    mesh_updated(bytes)     : 新的 mesh STL bytes
    stats_updated(dict)     : 统计信息（耗时/层数/点数/网格数）
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

logger = logging.getLogger("csam.ui.progress")


class ProgressSubscriberWorker(QObject):
    """在 QThread 中运行 ZMQ SUB 订阅器。"""

    progress_received = Signal(dict)
    layer_completed = Signal(int)
    mesh_updated = Signal(bytes)
    stats_updated = Signal(dict)
    finished = Signal()

    def __init__(self, address: str = "tcp://127.0.0.1:5556") -> None:
        super().__init__()
        self._address = address

    @Slot()
    def run(self) -> None:
        """订阅 ZMQ PUB，循环接收进度消息。"""
        try:
            import zmq
            ctx = zmq.Context()
            sock = ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, 1000)  # 1s 超时，便于检查中断请求
            sock.setsockopt(zmq.SUBSCRIBE, b"")  # 订阅所有消息
            sock.connect(self._address)
            logger.info("ProgressSubscriber 已连接: %s", self._address)
        except Exception as exc:
            logger.warning("ProgressSubscriber 连接失败: %s", exc)
            self.finished.emit()
            return

        start_time = time.time()

        while not QThread.currentThread().isInterruptionRequested():
            try:
                data = sock.recv()
                if not data:
                    continue
                self._process_message(data, start_time)
            except Exception:
                # RCVTIMEO 超时，继续循环
                continue

        try:
            sock.close(0)
            ctx.term()
        except Exception as exc:
            logger.warning("ProgressSubscriber 关闭异常: %s", exc)
        self.finished.emit()

    def _process_message(self, data: bytes, start_time: float) -> None:
        """解析 ProgressUpdate 消息并发出信号。"""
        try:
            from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
            from repair_app.communication.repair_serialization import parse_progress_update

            msg = ProgressUpdate()
            msg.ParseFromString(data)
            parsed = parse_progress_update(msg)

            # 发出完整解析结果
            self.progress_received.emit(parsed)

            # 层完成信号
            layer_idx = parsed.get("layer_index", 0)
            self.layer_completed.emit(int(layer_idx))

            # mesh 更新信号
            mesh_data = parsed.get("partial_mesh_data", b"")
            if mesh_data:
                self.mesh_updated.emit(mesh_data)

            # 统计信息
            elapsed = time.time() - start_time
            wp_count = len(parsed.get("waypoints", []))
            mesh_count = len(mesh_data) // 50 if mesh_data else 0  # 每个三角形 50 bytes
            stats = {
                "elapsed_s": float(msg.message.split("elapsed=")[1].split("s")[0])
                if "elapsed=" in msg.message else elapsed,
                "layer_index": int(layer_idx),
                "total_layers": int(parsed.get("total_layers", 0)),
                "waypoint_count": int(wp_count),
                "mesh_triangle_count": int(mesh_count),
                "progress": float(parsed.get("progress", 0.0)),
                "stage_name": str(parsed.get("stage_name", "")),
                "message": str(parsed.get("message", "")),
            }
            self.stats_updated.emit(stats)

        except Exception as exc:
            logger.debug("解析进度消息异常: %s", exc)

    def stop(self) -> None:
        """停止订阅（空操作，停止信号由 QThread.requestInterruption 提供）。"""
        pass


class ProgressSubscriber(QObject):
    """进度订阅器管理器（管理 QThread + Worker 生命周期）。"""

    progress_received = Signal(dict)
    layer_completed = Signal(int)
    mesh_updated = Signal(bytes)
    stats_updated = Signal(dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProgressSubscriberWorker] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, address: str = "tcp://127.0.0.1:5556") -> None:
        """启动订阅器。"""
        if self.is_running:
            return
        self._thread = QThread()
        self._worker = ProgressSubscriberWorker(address)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 线程结束后清理 Worker（防止内存泄漏）
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        # 转发信号
        self._worker.progress_received.connect(self.progress_received)
        self._worker.layer_completed.connect(self.layer_completed)
        self._worker.mesh_updated.connect(self.mesh_updated)
        self._worker.stats_updated.connect(self.stats_updated)
        self._thread.start()

    def stop(self) -> None:
        """停止订阅器。"""
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
