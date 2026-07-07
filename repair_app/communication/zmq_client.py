"""
zmq_client.py — ZeroMQ 通信客户端
Stage 3.1 v2.1：QThread 封装的 ZMQ REQ/REP 客户端，Protobuf 编解码
"""

from __future__ import annotations
import time
from typing import Optional, Callable

from PySide6.QtCore import QThread, Signal

from repair_app.communication.repair_serialization import (
    serialize_request, deserialize_result,
    build_health_check_request, parse_health_check_response,
)
from repair_app.communication.repair_protocol_pb2 import RepairRequest, RepairResult

try:
    import zmq
    _ZMQ_AVAILABLE = True
except ImportError:
    _ZMQ_AVAILABLE = False
    zmq = None


from repair_app.platform.transport import get_zmq_address_from_env
DEFAULT_IPC_ADDR = get_zmq_address_from_env()
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_RETRY_INTERVAL_MS = 2000
DEFAULT_MAX_RETRIES = 3


class ZmqRepairWorker(QThread):
    """工作线程：发送请求并等待响应。"""

    result_ready = Signal(object)    # RepairResult
    error_occurred = Signal(str)     # 错误消息
    health_ok = Signal(bool)         # 健康检查结果

    def __init__(
        self,
        request_bytes: bytes,
        address: str = DEFAULT_IPC_ADDR,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._request = request_bytes
        self._address = address
        self._timeout_ms = timeout_ms

    def run(self) -> None:
        if not _ZMQ_AVAILABLE:
            self.error_occurred.emit("pyzmq 未安装，无法连接 MATLAB 引擎")
            return

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        # TODO(SECURITY): ZMQ 通信未使用 CURVE 加密或 PLAIN 认证，
        # 本地进程可伪装成服务端。生产环境应配置 CURVE 密钥对。
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, 5000)

        try:
            sock.connect(self._address)
            sock.send(self._request)

            # 协作式中断：每 200ms 检查一次中断请求，避免长时间阻塞
            poll_interval = 200
            elapsed = 0
            replied = False
            while elapsed < self._timeout_ms:
                if self.isInterruptionRequested():
                    return
                if sock.poll(poll_interval, zmq.POLLIN):
                    reply = sock.recv()
                    result = deserialize_result(reply)
                    self.result_ready.emit(result)
                    replied = True
                    break
                elapsed += poll_interval
            if not replied:
                self.error_occurred.emit(f"请求超时 ({self._timeout_ms}ms)")
        except zmq.ZMQError as e:
            self.error_occurred.emit(f"ZMQ 错误: {e}")
        except Exception as e:
            self.error_occurred.emit(f"通信异常: {e}")
        finally:
            sock.close(linger=0)


class HealthCheckWorker(QThread):
    """健康检查工作线程。"""

    result_ready = Signal(bool, str)

    def __init__(self, address: str = DEFAULT_IPC_ADDR, parent=None) -> None:
        super().__init__(parent)
        self._address = address

    def run(self) -> None:
        if not _ZMQ_AVAILABLE:
            self.result_ready.emit(False, "pyzmq 未安装")
            return

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, 3000)
        sock.setsockopt(zmq.SNDTIMEO, 2000)

        try:
            sock.connect(self._address)
            hb = build_health_check_request()
            sock.send(hb.SerializeToString())
            if self.isInterruptionRequested():
                return
            if sock.poll(3000, zmq.POLLIN):
                resp = sock.recv()
                parsed = parse_health_check_response(resp)
                self.result_ready.emit(parsed["status_code"] == 0, parsed["status"])
            else:
                self.result_ready.emit(False, "健康检查超时")
        except Exception as e:
            self.result_ready.emit(False, str(e))
        finally:
            sock.close(linger=0)


class ZmqRepairClient:
    """ZMQ 修复客户端（主线程安全封装）。

    用法:
        client = ZmqRepairClient()
        client.request_repair(request, on_result, on_error)
        client.check_health(on_health)
    """

    def __init__(self, address: str = DEFAULT_IPC_ADDR, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        self._address = address
        self._timeout_ms = timeout_ms
        self._pending_worker: Optional[ZmqRepairWorker] = None
        self._health_worker: Optional[HealthCheckWorker] = None
        self._on_result: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_health: Optional[Callable] = None
        self._connected = False
        self._retry_count = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def zmq_available(self) -> bool:
        return _ZMQ_AVAILABLE

    def request_repair(
        self,
        request: RepairRequest,
        on_result: Callable[[RepairResult], None],
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """发送修复请求。"""
        # 检查前一个请求是否仍在进行
        if self._pending_worker is not None and self._pending_worker.isRunning():
            if on_error:
                on_error("前一个修复请求仍在进行中，请稍后重试")
            return

        self._on_result = on_result
        self._on_error = on_error

        try:
            req_bytes = serialize_request(request)
        except Exception as e:
            if on_error:
                on_error(f"序列化失败: {e}")
            return

        self._pending_worker = ZmqRepairWorker(req_bytes, self._address, self._timeout_ms)
        self._pending_worker.result_ready.connect(self._on_result_ready)
        self._pending_worker.error_occurred.connect(self._on_error_occurred)
        self._pending_worker.finished.connect(self._on_worker_finished)
        self._pending_worker.start()

    def check_health(self, on_health: Callable[[bool, str], None]) -> None:
        """检查 MATLAB 引擎健康状态。"""
        self._on_health = on_health
        self._health_worker = HealthCheckWorker(self._address)
        self._health_worker.result_ready.connect(self._on_health_ready)
        self._health_worker.finished.connect(self._on_health_finished)
        self._health_worker.start()

    def close(self, wait_ms: int = 4000) -> None:
        """停止仍在运行的后台 worker，用于测试和程序退出收尾。"""
        for worker_attr in ("_pending_worker", "_health_worker"):
            worker = getattr(self, worker_attr)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(wait_ms):
                    worker.terminate()
                    worker.wait(1000)
            setattr(self, worker_attr, None)

    def _on_result_ready(self, result: RepairResult) -> None:
        if self._on_result:
            self._on_result(result)

    def _on_error_occurred(self, msg: str) -> None:
        self._connected = False
        self._retry_count += 1
        if self._on_error:
            self._on_error(msg)

    def _on_worker_finished(self) -> None:
        self._pending_worker = None

    def _on_health_ready(self, ok: bool, msg: str) -> None:
        self._connected = ok
        if self._on_health:
            self._on_health(ok, msg)

    def _on_health_finished(self) -> None:
        self._health_worker = None
