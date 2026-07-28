"""Realtime progress publisher owned by the MATLAB bridge worker.

Socket ownership contract
-------------------------
The bridge worker binds one PUB socket for its whole lifetime.  The socket is
created, used, and closed exclusively by the publisher's sender thread.
MATLAB computation code only serializes/enqueues events; it never touches the
ZeroMQ socket.  The GUI owns one long-lived SUB socket and only connects.
"""
from __future__ import annotations

from collections import deque
import logging
import os
import struct
import threading
import time
from typing import Optional

import numpy as np

from repair_app.config import schema_loader

logger = logging.getLogger("csam.bridge.progress")

DEFAULT_PUB_PORT = 5556
DEFAULT_PUB_ADDRESS = f"tcp://127.0.0.1:{DEFAULT_PUB_PORT}"


class ProgressPublisher:
    """Application-scoped, non-blocking ZMQ progress publisher.

    High-rate preview/progress events use a single replaceable slot.  Path
    layers and terminal events use the reliable FIFO because dropping one of
    those would corrupt the UI's accumulated state.
    """

    _instance: Optional["ProgressPublisher"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        address: Optional[str] = None,
        heartbeat_interval_s: float = 1.0,
    ) -> None:
        self._address = (
            address
            or os.environ.get("CSAM_ZMQ_PROGRESS_ADDRESS")
            or str(schema_loader.get_network_value("zmq_progress_address"))
            or DEFAULT_PUB_ADDRESS
        )
        self._heartbeat_interval_s = max(0.25, float(heartbeat_interval_s))
        self._sock = None
        self._ctx = None
        self._enabled = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._condition = threading.Condition()
        self._reliable: deque[bytes] = deque()
        self._latest_coalescible: Optional[bytes] = None
        self._active_operation_id = ""
        self._sequence_by_operation: dict[str, int] = {}

    @classmethod
    def get_instance(cls) -> "ProgressPublisher":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is None:
                return
            if cls._instance.stop():
                cls._instance = None

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_running(self) -> bool:
        return bool(self._enabled and self._thread and self._thread.is_alive())

    def start(self, wait_s: float = 2.0) -> bool:
        """Bind once in a dedicated sender thread."""
        if self._enabled:
            return True
        if self._thread is not None and self._thread.is_alive():
            return self._ready_event.wait(wait_s) and self._enabled

        self._stop_event.clear()
        self._ready_event.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._sender_loop,
            name="csam-progress-publisher",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(wait_s)
        if not self._enabled:
            if self._start_error is not None:
                logger.warning(
                    "ProgressPublisher 启动失败 (%s): %s",
                    self._address,
                    self._start_error,
                )
            return False
        return True

    def stop(self, wait_s: float = 2.0) -> bool:
        """Stop the sender and close its socket in the owner thread.

        A timed-out owner thread must retain its references.  Clearing them
        would allow ``start()`` to create a second PUB owner while the first
        thread may still hold the bound port.
        """
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, wait_s))
            if thread.is_alive():
                logger.error(
                    "ProgressPublisher 发送线程未在 %.1fs 内退出；保留线程状态以防重复绑定",
                    wait_s,
                )
                return False

        # Compatibility and failed-start cleanup: normally _sender_loop has
        # already cleared these references in its own thread.
        if thread is None:
            try:
                if self._sock is not None:
                    self._sock.close(0)
                if self._ctx is not None:
                    self._ctx.term()
            except Exception as exc:
                logger.warning("ProgressPublisher 关闭异常: %s", exc)
            finally:
                self._sock = None
                self._ctx = None

        self._thread = None
        self._enabled = False
        with self._condition:
            self._latest_coalescible = None
            self._reliable.clear()
        self._active_operation_id = ""
        return True

    def _sender_loop(self) -> None:
        try:
            import zmq

            self._ctx = zmq.Context()
            self._sock = self._ctx.socket(zmq.PUB)
            self._sock.setsockopt(zmq.LINGER, 0)
            self._sock.bind(self._address)
            self._enabled = True
            logger.info("ProgressPublisher 已绑定: %s", self._address)
        except Exception as exc:
            self._start_error = exc
            self._enabled = False
            self._ready_event.set()
            self._close_owned_socket()
            return

        self._ready_event.set()
        next_heartbeat = time.monotonic() + self._heartbeat_interval_s
        try:
            while not self._stop_event.is_set():
                payload = self._take_next_payload(next_heartbeat)
                if payload is not None:
                    self._sock.send(payload)

                now = time.monotonic()
                if now >= next_heartbeat:
                    heartbeat = self._build_heartbeat()
                    if heartbeat is not None:
                        self._sock.send(heartbeat)
                    next_heartbeat = now + self._heartbeat_interval_s
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.warning("ProgressPublisher 发送线程异常: %s", exc)
        finally:
            self._enabled = False
            self._close_owned_socket()

    def _take_next_payload(self, heartbeat_deadline: float) -> Optional[bytes]:
        with self._condition:
            if not self._reliable and self._latest_coalescible is None:
                timeout = max(0.0, heartbeat_deadline - time.monotonic())
                self._condition.wait(timeout=min(timeout, 0.25))
            if self._reliable:
                return self._reliable.popleft()
            payload = self._latest_coalescible
            self._latest_coalescible = None
            return payload

    def _close_owned_socket(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close(0)
            if self._ctx is not None:
                self._ctx.term()
        except Exception as exc:
            logger.warning("ProgressPublisher socket 清理异常: %s", exc)
        finally:
            self._sock = None
            self._ctx = None

    def _next_sequence(self, operation_id: str) -> int:
        with self._condition:
            seq = self._sequence_by_operation.get(operation_id, 0) + 1
            self._sequence_by_operation[operation_id] = seq
            return seq

    def _enqueue(self, payload: bytes, *, reliable: bool) -> None:
        if not self._enabled:
            return
        with self._condition:
            if reliable:
                self._reliable.append(payload)
            else:
                self._latest_coalescible = payload
            self._condition.notify()

    def _build_heartbeat(self) -> Optional[bytes]:
        operation_id = self._active_operation_id
        if not operation_id:
            return None
        try:
            from repair_app.communication.repair_protocol_pb2 import ProgressEventType
            from repair_app.communication.repair_serialization import (
                build_progress_envelope,
            )

            msg = build_progress_envelope(
                operation_id,
                ProgressEventType.PROGRESS_HEARTBEAT,
                # Heartbeats are liveness metadata, not ordered algorithm
                # payloads.  Using the next payload sequence here can leapfrog
                # a reliable FIFO backlog and make the subscriber discard
                # queued path layers as stale.
                0,
                message="MATLAB worker alive",
            )
            return msg.SerializeToString()
        except Exception as exc:
            logger.debug("构建 heartbeat 失败: %s", exc)
            return None

    def publish_progress(
        self,
        request_id: str,
        stage: int = 0,
        layer_index: int = 0,
        total_layers: int = 0,
        progress: float = 0.0,
        message: str = "",
        waypoints: Optional[object] = None,
        layer_max_height: float = 0.0,
        layer_avg_height: float = 0.0,
        layer_dep_eff: float = 0.0,
        mesh_triangles: Optional[object] = None,
        elapsed_s: float = 0.0,
        event_type: Optional[int] = None,
        mesh_frame_kind: Optional[int] = None,
        reliable: bool = False,
    ) -> None:
        """Serialize and queue one v3 realtime event.

        The signature remains MATLAB-friendly and backward-compatible with the
        previous module-level ``publish_progress`` entry point.
        """
        if not self._enabled:
            return

        try:
            from repair_app.communication.repair_protocol_pb2 import (
                MeshFrameKind,
                ProgressEventType,
            )
            from repair_app.communication.repair_serialization import (
                build_progress_envelope,
            )

            operation_id = str(request_id)
            if not operation_id:
                return
            self._active_operation_id = operation_id

            wp_np = None
            if waypoints is not None and len(waypoints) > 0:
                candidate = np.asarray(waypoints, dtype=np.float32)
                if candidate.ndim == 2 and candidate.shape[1] >= 3:
                    wp_np = candidate

            partial_mesh = b""
            mesh_count = 0
            if mesh_triangles is not None and len(mesh_triangles) > 0:
                tris = np.asarray(mesh_triangles, dtype=np.float32)
                if tris.ndim == 2 and tris.shape[1] >= 9:
                    partial_mesh = _triangles_to_stl_bytes(tris)
                    mesh_count = len(tris)

            resolved_frame_kind = (
                int(mesh_frame_kind)
                if mesh_frame_kind is not None
                else int(MeshFrameKind.MESH_PREVIEW_SNAPSHOT)
            )
            if event_type is None:
                if partial_mesh:
                    event_type = (
                        ProgressEventType.PROGRESS_TOPO_LAYER_READY
                        if resolved_frame_kind
                        == MeshFrameKind.MESH_FULL_RESOLUTION_SNAPSHOT
                        else ProgressEventType.PROGRESS_TOPO_SNAPSHOT
                    )
                elif wp_np is not None:
                    event_type = ProgressEventType.PROGRESS_PATH_LAYER_READY
                    reliable = True
                else:
                    event_type = ProgressEventType.PROGRESS_TOPO_SNAPSHOT

            msg = build_progress_envelope(
                operation_id,
                int(event_type),
                self._next_sequence(operation_id),
                layer_index=int(layer_index),
                total_layers=int(total_layers),
                progress=float(progress),
                message=str(message),
                elapsed_s=float(elapsed_s),
                waypoints=wp_np,
                mesh_data=partial_mesh,
                mesh_frame_kind=resolved_frame_kind,
                triangle_count=mesh_count,
                layer_max_height_mm=float(layer_max_height),
                layer_avg_height_mm=float(layer_avg_height),
                layer_dep_efficiency=float(layer_dep_eff),
            )
            reliable = bool(
                reliable
                or int(event_type)
                in {
                    ProgressEventType.PROGRESS_PATH_LAYER_READY,
                    ProgressEventType.PROGRESS_PATH_SEGMENT_READY,
                    ProgressEventType.PROGRESS_TOPO_LAYER_READY,
                    ProgressEventType.PROGRESS_COMPLETED,
                    ProgressEventType.PROGRESS_FAILED,
                    ProgressEventType.PROGRESS_CANCELLED,
                }
            )
            self._enqueue(msg.SerializeToString(), reliable=reliable)
        except Exception as exc:
            logger.warning("发布进度异常: %s", exc)

    def begin_operation(self, request_id: str) -> None:
        operation_id = str(request_id)
        if not operation_id:
            raise ValueError("request_id is required")
        with self._condition:
            self._active_operation_id = operation_id
            self._sequence_by_operation[operation_id] = 0
            self._latest_coalescible = None
            self._condition.notify_all()

    def publish_terminal(
        self,
        request_id: str,
        event_type: int,
        *,
        message: str = "",
        error_code: str = "",
        retryable: bool = False,
        elapsed_s: float = 0.0,
    ) -> None:
        """Queue a reliable terminal event."""
        if not self._enabled:
            return
        try:
            from repair_app.communication.repair_serialization import (
                build_progress_envelope,
            )

            operation_id = str(request_id)
            self._active_operation_id = operation_id
            msg = build_progress_envelope(
                operation_id,
                int(event_type),
                self._next_sequence(operation_id),
                progress=1.0,
                message=message,
                elapsed_s=elapsed_s,
                error_code=error_code,
                error_message=message if error_code else "",
                retryable=retryable,
            )
            self._enqueue(msg.SerializeToString(), reliable=True)
        except Exception as exc:
            logger.warning("发布终止事件异常: %s", exc)

    def finish_operation(self, request_id: str) -> None:
        """Stop heartbeats for a completed operation after queued events flush."""
        if self._active_operation_id == str(request_id):
            self._active_operation_id = ""


def publish_progress(**kwargs) -> None:
    """MATLAB ``pyargs`` entry point."""
    try:
        ProgressPublisher.get_instance().publish_progress(**kwargs)
    except Exception as exc:
        logger.warning("publish_progress 异常: %s", exc)


def publish_terminal(**kwargs) -> None:
    """MATLAB/bridge terminal-event entry point."""
    try:
        ProgressPublisher.get_instance().publish_terminal(**kwargs)
    except Exception as exc:
        logger.warning("publish_terminal 异常: %s", exc)


def _triangles_to_stl_bytes(triangles: np.ndarray) -> bytes:
    """Convert an N×9 triangle array to binary STL."""
    n = len(triangles)
    body = [b"\0" * 80, struct.pack("<I", n)]
    for tri in triangles:
        v1 = tri[0:3]
        v2 = tri[3:6]
        v3 = tri[6:9]
        e1 = v2 - v1
        e2 = v3 - v1
        nx = e1[1] * e2[2] - e1[2] * e2[1]
        ny = e1[2] * e2[0] - e1[0] * e2[2]
        nz = e1[0] * e2[1] - e1[1] * e2[0]
        nl = (nx * nx + ny * ny + nz * nz) ** 0.5
        if nl > 0:
            nx /= nl
            ny /= nl
            nz /= nl
        body.append(struct.pack("<fff", nx, ny, nz))
        body.append(struct.pack("<fff", *v1))
        body.append(struct.pack("<fff", *v2))
        body.append(struct.pack("<fff", *v3))
        body.append(struct.pack("<H", 0))
    return b"".join(body)
