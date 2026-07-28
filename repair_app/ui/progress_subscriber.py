"""Long-lived GUI-side subscriber for MATLAB realtime events.

Socket ownership contract
-------------------------
The SUB socket is created, used, and closed in ``ProgressSubscriberWorker``'s
QThread.  It connects to the bridge worker's PUB socket and stays alive across
computations.  High-rate snapshots are written to a single-slot buffer; the UI
thread drains that buffer with a QTimer instead of queuing one Qt event per
network frame.
"""
from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

logger = logging.getLogger("csam.ui.progress")


class RealtimeEventBuffer:
    """Thread-safe coalescing buffer with lossless path/terminal channels."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._operation_id = ""
        self._finished = True
        self._last_sequence = 0
        self._latest_progress: Optional[dict] = None
        self._latest_stats: Optional[dict] = None
        self._latest_mesh: Optional[bytes] = None
        self._pending_path_layers: dict[int, dict] = {}
        self._terminal_events: deque[dict] = deque()
        self._heartbeat_pending = False

    def begin_operation(self, operation_id: str) -> None:
        with self._lock:
            self._operation_id = str(operation_id)
            self._finished = False
            self._last_sequence = 0
            self._latest_progress = None
            self._latest_stats = None
            self._latest_mesh = None
            self._pending_path_layers.clear()
            self._terminal_events.clear()
            self._heartbeat_pending = False

    def finish_operation(self, operation_id: str) -> None:
        with self._lock:
            if self._operation_id == str(operation_id):
                self._finished = True

    def accept(self, parsed: dict, stats: dict) -> bool:
        operation_id = str(
            parsed.get("operation_id") or parsed.get("request_id") or ""
        )
        with self._lock:
            if self._finished or not self._operation_id:
                return False
            if operation_id != self._operation_id:
                return False

            # Heartbeats intentionally live outside the payload sequence.
            # Older publishers may still attach a sequence number, so handle
            # liveness before ordered-payload filtering to prevent a heartbeat
            # from invalidating queued path layers.
            if parsed.get("is_heartbeat"):
                self._heartbeat_pending = True
                return True

            sequence = int(parsed.get("sequence_number", 0) or 0)
            if sequence > 0:
                if sequence <= self._last_sequence:
                    logger.warning(
                        "丢弃乱序实时消息: operation=%s sequence=%d last=%d",
                        operation_id,
                        sequence,
                        self._last_sequence,
                    )
                    return False
                self._last_sequence = sequence

            if parsed.get("is_terminal"):
                self._terminal_events.append(parsed)
                return True

            event_name = str(parsed.get("event_name", ""))
            if event_name in {
                "PROGRESS_PATH_LAYER_READY",
                "PROGRESS_PATH_SEGMENT_READY",
            }:
                self._pending_path_layers[int(parsed.get("layer_index", 0))] = parsed
            else:
                self._latest_progress = parsed

            mesh_data = parsed.get("partial_mesh_data", b"")
            if mesh_data:
                self._latest_mesh = bytes(mesh_data)
            self._latest_stats = stats
            return True

    def drain(self) -> dict:
        with self._lock:
            result = {
                "progress": self._latest_progress,
                "stats": self._latest_stats,
                "mesh": self._latest_mesh,
                "path_layers": [
                    self._pending_path_layers[key]
                    for key in sorted(self._pending_path_layers)
                ],
                "terminal_events": list(self._terminal_events),
                "heartbeat": self._heartbeat_pending,
                "operation_id": self._operation_id,
            }
            self._latest_progress = None
            self._latest_stats = None
            self._latest_mesh = None
            self._pending_path_layers.clear()
            self._terminal_events.clear()
            self._heartbeat_pending = False
            return result


class ProgressSubscriberWorker(QObject):
    """Own and poll one ZMQ SUB socket in a dedicated QThread."""

    # Legacy direct signals remain available for focused worker tests. The
    # production ProgressSubscriber intentionally does not connect these
    # high-rate signals to the UI.
    progress_received = Signal(dict)
    layer_completed = Signal(int)
    mesh_updated = Signal(bytes)
    stats_updated = Signal(dict)
    finished = Signal()

    def __init__(
        self,
        address: str = "tcp://127.0.0.1:5556",
        event_buffer: Optional[RealtimeEventBuffer] = None,
    ) -> None:
        super().__init__()
        self._address = address
        self._operation_id = ""
        self._operation_lock = threading.Lock()
        self._event_buffer = event_buffer

    @Slot()
    def run(self) -> None:
        sock = None
        ctx = None
        try:
            import zmq

            ctx = zmq.Context()
            sock = ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, 1000)
            sock.setsockopt(zmq.RECONNECT_IVL, 250)
            sock.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
            sock.setsockopt(zmq.SUBSCRIBE, b"")
            sock.connect(self._address)
            logger.info("ProgressSubscriber 已连接: %s", self._address)
        except Exception as exc:
            logger.warning("ProgressSubscriber 连接失败: %s", exc)
            try:
                if sock is not None:
                    sock.close(0)
                if ctx is not None:
                    ctx.destroy(linger=0)
            except Exception as close_exc:
                logger.warning(
                    "ProgressSubscriber 连接失败后的清理异常: %s",
                    close_exc,
                )
            self.finished.emit()
            return

        start_time = time.monotonic()
        try:
            while not QThread.currentThread().isInterruptionRequested():
                try:
                    data = sock.recv()
                except zmq.Again:
                    continue
                except Exception as exc:
                    if QThread.currentThread().isInterruptionRequested():
                        break
                    logger.warning("ProgressSubscriber 接收异常: %s", exc)
                    continue
                if data:
                    self._process_message(data, start_time)
        finally:
            try:
                if sock is not None:
                    sock.close(0)
                if ctx is not None:
                    ctx.destroy(linger=0)
            except Exception as exc:
                logger.warning("ProgressSubscriber 关闭异常: %s", exc)
            self.finished.emit()

    def set_operation_id(self, operation_id: str) -> None:
        with self._operation_lock:
            self._operation_id = str(operation_id)

    @staticmethod
    def _decode_message(data: bytes) -> dict:
        """Decode v3 first, then use the legacy v2 message contract."""
        from repair_app.communication.repair_protocol_pb2 import (
            ProgressEnvelope,
            ProgressUpdate,
        )
        from repair_app.communication.repair_serialization import (
            parse_progress_envelope,
            parse_progress_update,
        )

        envelope = ProgressEnvelope()
        try:
            envelope.ParseFromString(data)
            if envelope.schema_version >= 3 and envelope.operation_id:
                return parse_progress_envelope(envelope)
        except Exception:
            pass

        legacy = ProgressUpdate()
        legacy.ParseFromString(data)
        parsed = parse_progress_update(legacy)
        # Generated protobuf classes expose nested enum values as class
        # attributes, but lightweight compatibility test doubles and older
        # generated bindings may not.  The wire value is part of the v2
        # contract, so fall back to the descriptor value instead of rejecting
        # an otherwise valid legacy packet.
        complete_stage = getattr(ProgressUpdate, "COMPLETE", 6)
        is_complete = int(legacy.stage) == int(complete_stage)
        parsed.update({
            "schema_version": 2,
            "operation_id": legacy.request_id,
            "sequence_number": 0,
            "event_name": (
                "PROGRESS_COMPLETED"
                if is_complete
                else "LEGACY_PROGRESS"
            ),
            "is_heartbeat": False,
            "is_terminal": is_complete,
        })
        return parsed

    def _process_message(self, data: bytes, start_time: float) -> None:
        try:
            parsed = self._decode_message(data)
            operation_id = str(
                parsed.get("operation_id") or parsed.get("request_id") or ""
            )
            with self._operation_lock:
                active_operation_id = self._operation_id
            if active_operation_id and operation_id != active_operation_id:
                logger.debug(
                    "忽略旧操作进度: request_id=%s (当前=%s)",
                    operation_id,
                    active_operation_id,
                )
                return

            elapsed = time.monotonic() - start_time
            mesh_data = parsed.get("partial_mesh_data", b"")
            reported_triangle_count = int(
                parsed.get("mesh_triangle_count", 0) or 0
            )
            inferred_triangle_count = (
                max(0, (len(mesh_data) - 84) // 50)
                if len(mesh_data) >= 84
                else 0
            )
            stats = {
                "elapsed_s": float(parsed.get("elapsed_s", elapsed) or elapsed),
                "layer_index": int(parsed.get("layer_index", 0)),
                "total_layers": int(parsed.get("total_layers", 0)),
                "waypoint_count": int(len(parsed.get("waypoints", []))),
                "mesh_triangle_count": (
                    reported_triangle_count or inferred_triangle_count
                ),
                "progress": float(parsed.get("progress", 0.0)),
                "stage_name": str(parsed.get("stage_name", "")),
                "message": str(parsed.get("message", "")),
            }

            accepted = True
            if self._event_buffer is not None:
                accepted = self._event_buffer.accept(parsed, stats)
            if not accepted:
                return

            # Compatibility signals for direct worker consumers/tests.
            self.progress_received.emit(parsed)
            if not parsed.get("is_heartbeat") and not parsed.get("is_terminal"):
                self.layer_completed.emit(int(parsed.get("layer_index", 0)))
            if mesh_data:
                self.mesh_updated.emit(bytes(mesh_data))
            self.stats_updated.emit(stats)
        except Exception as exc:
            logger.warning("丢弃无法解析的实时消息: %s", exc)

    def stop(self) -> None:
        """The owning QThread interruption flag stops the receive loop."""


class ProgressSubscriber(QObject):
    """Application-scoped subscriber with QTimer-based UI coalescing."""

    progress_received = Signal(dict)
    layer_completed = Signal(int)
    mesh_updated = Signal(bytes)
    stats_updated = Signal(dict)
    path_layer_ready = Signal(int, object)
    terminal_received = Signal(dict)
    heartbeat_received = Signal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        flush_interval_ms: int = 200,
    ) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ProgressSubscriberWorker] = None
        self._operation_id = ""
        self._address = ""
        self._buffer = RealtimeEventBuffer()
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(max(50, int(flush_interval_ms)))
        self._flush_timer.timeout.connect(self._flush_buffer)

    @property
    def is_running(self) -> bool:
        thread = self._thread
        if thread is None:
            return False
        try:
            return thread.isRunning()
        except RuntimeError:
            # Qt may already have deleted the C++ wrapper while its queued
            # ``finished`` callback is still waiting in the UI event loop.
            self._thread = None
            self._worker = None
            return False

    def set_operation_id(self, operation_id: str) -> None:
        operation_id = str(operation_id)
        if operation_id == self._operation_id:
            if self._worker is not None:
                self._worker.set_operation_id(operation_id)
            return
        self._operation_id = operation_id
        self._buffer.begin_operation(self._operation_id)
        if self._worker is not None:
            self._worker.set_operation_id(self._operation_id)

    def finish_operation(self, operation_id: str) -> None:
        self._buffer.finish_operation(operation_id)

    def start(self, address: str = "tcp://127.0.0.1:5556") -> None:
        """Start once; subsequent computations reuse the same socket/thread."""
        if self.is_running:
            return
        # A prior startup attempt may have failed asynchronously.  Its thread
        # has fully stopped by this point, so it is safe to retire the wrappers
        # before creating the replacement.
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        self._address = address
        self._thread = QThread(self)
        self._worker = ProgressSubscriberWorker(address, self._buffer)
        self._worker.set_operation_id(self._operation_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # ``run()`` owns a blocking receive loop.  If socket setup fails, the
        # worker returns before ``stop()`` is called; explicitly stop the
        # QThread event loop so ``is_running`` cannot report a dead subscriber
        # as healthy.
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        self._flush_timer.start()

    @Slot()
    def _on_thread_finished(self) -> None:
        """Stop UI polling; wrappers are retired by ``start`` or ``stop``."""
        self._flush_timer.stop()

    def _flush_buffer(self) -> None:
        drained = self._buffer.drain()
        operation_id = str(drained["operation_id"])
        if drained["heartbeat"]:
            self.heartbeat_received.emit(operation_id)

        for parsed in drained["path_layers"]:
            layer_index = int(parsed.get("layer_index", 0))
            self.path_layer_ready.emit(layer_index, parsed)
            self.layer_completed.emit(layer_index)

        parsed = drained["progress"]
        if parsed is not None:
            self.progress_received.emit(parsed)
            event_name = str(parsed.get("event_name", ""))
            if event_name == "PROGRESS_TOPO_LAYER_READY":
                self.layer_completed.emit(int(parsed.get("layer_index", 0)))

        if drained["mesh"] is not None:
            self.mesh_updated.emit(drained["mesh"])
        if drained["stats"] is not None:
            self.stats_updated.emit(drained["stats"])
        for terminal in drained["terminal_events"]:
            self.terminal_received.emit(terminal)

    def stop(self) -> bool:
        """Application shutdown only."""
        self._flush_timer.stop()
        thread = self._thread
        if thread is not None:
            try:
                is_running = thread.isRunning()
            except RuntimeError:
                is_running = False
            if is_running:
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(2500):
                    logger.error("ProgressSubscriber 线程未在超时内退出")
                    return False
            thread.deleteLater()
        self._thread = None
        self._worker = None
        return True
