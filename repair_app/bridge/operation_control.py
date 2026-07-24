"""Reliable cancellation control plane for MATLAB computations.

The control REP socket lives in its own Python thread inside the MATLAB bridge
process, so it remains responsive while the normal repair REP endpoint is
blocked in an algorithm call.  MATLAB loops query the in-process registry via
``py.repair_app.bridge.operation_control.is_cancel_requested``.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
import os
import threading
import time
import uuid
from typing import Optional

from repair_app.config import schema_loader

logger = logging.getLogger("csam.bridge.control")


@dataclass
class _OperationRecord:
    operation_id: str
    cancel_requested: bool = False
    cancel_request_ids: set[str] = field(default_factory=set)
    terminal_status: str = ""


class OperationRegistry:
    """Thread-safe operation and cooperative-cancel registry."""

    def __init__(self, terminal_history_limit: int = 128) -> None:
        self._lock = threading.RLock()
        self._active: dict[str, _OperationRecord] = {}
        self._terminal: "OrderedDict[str, str]" = OrderedDict()
        self._terminal_history_limit = max(8, int(terminal_history_limit))

    def begin(self, operation_id: str) -> None:
        operation_id = str(operation_id)
        if not operation_id:
            raise ValueError("operation_id is required")
        with self._lock:
            self._terminal.pop(operation_id, None)
            self._active[operation_id] = _OperationRecord(operation_id)

    def finish(self, operation_id: str, terminal_status: str) -> None:
        operation_id = str(operation_id)
        with self._lock:
            record = self._active.pop(operation_id, None)
            status = str(terminal_status or "completed")
            if record is not None:
                record.terminal_status = status
            self._terminal[operation_id] = status
            self._terminal.move_to_end(operation_id)
            while len(self._terminal) > self._terminal_history_limit:
                self._terminal.popitem(last=False)

    def is_cancel_requested(self, operation_id: str) -> bool:
        with self._lock:
            record = self._active.get(str(operation_id))
            return bool(record and record.cancel_requested)

    def request_cancel(self, operation_id: str, request_id: str) -> tuple[int, str]:
        from repair_app.communication.repair_protocol_pb2 import ControlStatus

        operation_id = str(operation_id)
        request_id = str(request_id)
        with self._lock:
            record = self._active.get(operation_id)
            if record is None:
                terminal = self._terminal.get(operation_id)
                if terminal == "completed":
                    return (
                        ControlStatus.CONTROL_ALREADY_COMPLETED,
                        "operation already completed",
                    )
                if terminal == "cancelled":
                    return (
                        ControlStatus.CONTROL_DUPLICATE,
                        "operation already cancelled",
                    )
                return (
                    ControlStatus.CONTROL_OPERATION_NOT_FOUND,
                    "operation not found",
                )

            if request_id in record.cancel_request_ids or record.cancel_requested:
                record.cancel_request_ids.add(request_id)
                return ControlStatus.CONTROL_DUPLICATE, "cancel already requested"

            record.cancel_request_ids.add(request_id)
            record.cancel_requested = True
            return ControlStatus.CONTROL_ACCEPTED, "cancel accepted"


_REGISTRY = OperationRegistry()


def begin_operation(operation_id: str) -> None:
    _REGISTRY.begin(str(operation_id))


def finish_operation(operation_id: str, terminal_status: str) -> None:
    _REGISTRY.finish(str(operation_id), str(terminal_status))


def is_cancel_requested(operation_id: str) -> bool:
    return _REGISTRY.is_cancel_requested(str(operation_id))


class CancellationControlServer:
    """Application-scoped ZMQ REP server for cancel acknowledgements."""

    _instance: Optional["CancellationControlServer"] = None
    _instance_lock = threading.Lock()

    def __init__(self, address: Optional[str] = None) -> None:
        self._address = (
            address
            or os.environ.get("CSAM_ZMQ_CONTROL_ADDRESS")
            or str(schema_loader.get_network_value("zmq_control_address"))
        )
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._enabled = False
        self._start_error: Optional[BaseException] = None

    @classmethod
    def get_instance(cls) -> "CancellationControlServer":
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
        if self.is_running:
            return True
        self._stop_event.clear()
        self._ready_event.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._serve,
            name="csam-cancel-control",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(wait_s)
        if not self._enabled and self._start_error is not None:
            logger.warning(
                "取消控制服务启动失败 (%s): %s", self._address, self._start_error
            )
        return self._enabled

    def stop(self, wait_s: float = 2.0) -> bool:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, wait_s))
            if thread.is_alive():
                logger.error(
                    "取消控制线程未在 %.1fs 内退出；保留线程状态以防重复绑定",
                    wait_s,
                )
                return False
        self._thread = None
        self._enabled = False
        return True

    def _serve(self) -> None:
        sock = None
        ctx = None
        try:
            import zmq

            ctx = zmq.Context()
            sock = ctx.socket(zmq.REP)
            sock.setsockopt(zmq.LINGER, 0)
            sock.bind(self._address)
            self._enabled = True
            self._ready_event.set()
            logger.info("取消控制服务已绑定: %s", self._address)

            while not self._stop_event.is_set():
                if not sock.poll(100, zmq.POLLIN):
                    continue
                data = sock.recv()
                sock.send(self._handle_request(data))
        except Exception as exc:
            self._start_error = exc
            if not self._stop_event.is_set():
                logger.warning("取消控制服务异常: %s", exc)
        finally:
            self._enabled = False
            self._ready_event.set()
            try:
                if sock is not None:
                    sock.close(0)
                if ctx is not None:
                    ctx.term()
            except Exception:
                pass

    @staticmethod
    def _handle_request(data: bytes) -> bytes:
        from repair_app.communication.repair_protocol_pb2 import (
            ControlCommand,
            ControlRequest,
            ControlResponse,
            ControlStatus,
        )

        response = ControlResponse(schema_version=3)
        try:
            request = ControlRequest()
            request.ParseFromString(data)
            response.operation_id = request.operation_id
            response.request_id = request.request_id
            if (
                request.schema_version != 3
                or request.command != ControlCommand.CONTROL_CANCEL_REQUEST
                or not request.operation_id
            ):
                response.status = ControlStatus.CONTROL_ERROR
                response.message = "invalid cancel request"
            else:
                status, message = _REGISTRY.request_cancel(
                    request.operation_id, request.request_id
                )
                response.status = status
                response.message = message
        except Exception as exc:
            response.status = ControlStatus.CONTROL_ERROR
            response.message = f"control decode error: {exc}"
        return response.SerializeToString()


def request_cancel(
    operation_id: str,
    *,
    address: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    request_id: Optional[str] = None,
):
    """Send one idempotent cancel request and return ``ControlResponse``."""
    import zmq
    from repair_app.communication.repair_protocol_pb2 import (
        ControlCommand,
        ControlRequest,
        ControlResponse,
    )

    endpoint = (
        address
        or os.environ.get("CSAM_ZMQ_CONTROL_ADDRESS")
        or str(schema_loader.get_network_value("zmq_control_address"))
    )
    timeout = int(
        timeout_ms
        if timeout_ms is not None
        else schema_loader.get_network_value("cancel_ack_timeout_ms")
    )
    req_id = request_id or str(uuid.uuid4())
    request = ControlRequest(
        schema_version=3,
        command=ControlCommand.CONTROL_CANCEL_REQUEST,
        operation_id=str(operation_id),
        request_id=req_id,
        timestamp_ms=int(time.time() * 1000),
    )

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SNDTIMEO, timeout)
    sock.setsockopt(zmq.RCVTIMEO, timeout)
    try:
        sock.connect(endpoint)
        sock.send(request.SerializeToString())
        if not sock.poll(timeout, zmq.POLLIN):
            raise TimeoutError(
                f"cancel acknowledgement timed out after {timeout}ms"
            )
        response = ControlResponse()
        response.ParseFromString(sock.recv())
        if response.request_id != req_id:
            raise RuntimeError("cancel response request_id mismatch")
        return response
    finally:
        sock.close(0)
