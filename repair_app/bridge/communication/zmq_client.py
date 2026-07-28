"""bridge.communication.zmq_client — 异步 ZMQ 客户端（任务7）

特性：
- QThread 封装，与现有架构一致
- 协作式中断（poll 间隔可配）
- 结构化异常翻译（任务8）
- 延迟日志（任务10）
- 心跳集成（任务7）
- 资源自动清理

ZMQ Socket Thread Ownership:
- 每个 ZMQ socket 由单个线程创建和独占使用。
- BridgeClient.request_blocking(): 在调用线程中创建 REQ socket。
- _RequestWorker: 在其 QThread 中创建 REQ socket。
- ProgressPublisher: PUB socket 由专属发送线程持有。
- ProgressSubscriber: SUB socket 由其 QThread 持有。
- 严禁跨线程共享 ZMQ socket。
"""
from __future__ import annotations

import logging
import time
import threading
from typing import Callable, Optional

logger = logging.getLogger("csam.bridge.client")

from PySide6.QtCore import QThread, Signal

try:
    import zmq
    _ZMQ_AVAILABLE = True
except ImportError:
    _ZMQ_AVAILABLE = False
    zmq = None

from .config import BridgeConfig
from .exceptions import (
    BridgeError,
    ConnectionError,
    ConnectionTimeoutError,
    EngineUnavailableError,
    SerializationError,
    ShutdownError,
    translate_zmq_error,
)
from .message import MessageEnvelope, generate_request_id
from .protocol import MessageType
from .serializer import Serializer
from .protocol import (
    HealthCheckRequest,
    HealthCheckResponse,
    RepairRequest,
    RepairResult,
    RepairStatusCode,
)


class _RequestWorker(QThread):
    """单次请求工作线程。"""

    result_ready = Signal(object)      # RepairResult
    error_occurred = Signal(str, str)  # (error_message, request_id)

    def __init__(
        self,
        request_bytes: bytes,
        address: str,
        config: BridgeConfig,
        request_id: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._request = request_bytes
        self._address = address
        self._config = config
        self._request_id = request_id

    def run(self) -> None:
        if not _ZMQ_AVAILABLE:
            self.error_occurred.emit("pyzmq 未安装", "")
            return

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, self._config.request_timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, self._config.connect_timeout_ms)

        try:
            sock.connect(self._address)
            sock.send(self._request)

            poll_interval = self._config.poll_interval_ms
            elapsed = 0
            while elapsed < self._config.request_timeout_ms:
                if self.isInterruptionRequested():
                    return
                if sock.poll(poll_interval, zmq.POLLIN):
                    reply = sock.recv()
                    result = Serializer.deserialize_result(reply)
                    self.result_ready.emit(result)
                    return
                elapsed += poll_interval

            self.error_occurred.emit(
                f"请求超时 ({self._config.request_timeout_ms}ms)", ""
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc), self._request_id)
        finally:
            sock.close(linger=0)


class _HealthWorker(QThread):
    """健康检查工作线程。"""

    result_ready = Signal(bool, str, float)  # (ok, message, latency_s)

    def __init__(self, address: str, config: BridgeConfig, parent=None) -> None:
        super().__init__(parent)
        self._address = address
        self._config = config

    def run(self) -> None:
        if not _ZMQ_AVAILABLE:
            self.result_ready.emit(False, "pyzmq 未安装", 0.0)
            return

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, self._config.health_check_timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, 2000)

        start = time.time()
        try:
            sock.connect(self._address)
            hb = Serializer.build_health_check()
            sock.send(Serializer.serialize_health(hb))
            if self.isInterruptionRequested():
                return
            if sock.poll(self._config.health_check_timeout_ms, zmq.POLLIN):
                resp_bytes = sock.recv()
                resp = HealthCheckResponse()
                resp.ParseFromString(resp_bytes)
                parsed = Serializer.parse_health_response(resp)
                latency = time.time() - start
                # P3-3: Version Mismatch 检测
                from repair_app.bridge.communication.protocol import (
                    PROTOCOL_VERSION, COMPATIBLE_PROTOCOL_VERSIONS,
                )
                protocol_version = parsed.get("protocol_version", "")
                if (
                    protocol_version
                    and protocol_version not in COMPATIBLE_PROTOCOL_VERSIONS
                ):
                    from repair_app.bridge.communication.exceptions import ProtocolError
                    self.result_ready.emit(
                        False,
                        "协议版本不兼容: "
                        f"客户端 {PROTOCOL_VERSION} / 服务端 {protocol_version}",
                        latency,
                    )
                    return
                self.result_ready.emit(
                    parsed.get("status_code") == 0,
                    parsed.get("status", "OK"),
                    latency,
                )
            else:
                self.result_ready.emit(False, "健康检查超时", time.time() - start)
        except Exception as exc:
            self.result_ready.emit(False, str(exc), time.time() - start)
        finally:
            sock.close(linger=0)


class BridgeClient:
    """高级 ZMQ 客户端：连接管理 + 请求 + 健康检查 + 心跳。

    用法：
        client = BridgeClient()
        client.request_repair(request, on_result, on_error)
        client.check_health(on_health)
        client.start_heartbeat()
        client.close()
    """

    def __init__(self, config: Optional[BridgeConfig] = None) -> None:
        self._config = config or BridgeConfig.from_env()
        self._address = self._config.address
        self._request_worker: Optional[_RequestWorker] = None
        self._health_worker: Optional[_HealthWorker] = None
        self._heartbeat = None
        self._connected = False
        self._closed = False
        self._on_result: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._lock = threading.Lock()

    # ---- 属性 ----
    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def zmq_available(self) -> bool:
        return _ZMQ_AVAILABLE

    @property
    def config(self) -> BridgeConfig:
        return self._config

    @property
    def address(self) -> str:
        return self._address

    # ---- 修复请求 ----
    def request_repair(
        self,
        request: RepairRequest,
        on_result: Callable[[RepairResult], None],
        on_error: Optional[Callable[[BridgeError], None]] = None,
    ) -> str:
        """发送修复请求（异步）。

        Returns:
            request_id（用于追踪）
        """
        if self._closed:
            err = ShutdownError("客户端已关闭")
            if on_error:
                on_error(err)
            return ""

        if self._request_worker is not None and self._request_worker.isRunning():
            err = BridgeError("前一个请求仍在进行中")
            if on_error:
                on_error(err)
            return ""

        self._on_result = on_result
        self._on_error = on_error

        try:
            req_bytes = Serializer.serialize_request(request)
        except SerializationError as exc:
            if on_error:
                on_error(exc)
            return ""

        self._request_worker = _RequestWorker(
            req_bytes, self._address, self._config,
            request_id=getattr(request, "request_id", ""),
        )
        self._request_worker.result_ready.connect(self._on_result_ready)
        self._request_worker.error_occurred.connect(self._on_error_occurred)
        self._request_worker.finished.connect(self._on_worker_finished)
        self._request_worker.start()
        return getattr(request, "request_id", "")

    # ---- 显式重连（Phase 3） ----
    def reconnect(self) -> bool:
        """显式重连：创建新 socket 并验证连接。

        ZMQ REQ/REP 有严格的 send→recv→send→recv 状态机。
        timeout 后必须关闭旧 socket 并创建新 socket 才能安全复用。

        Returns:
            True if reconnection successful
        """
        if self._closed:
            logger.warning("BridgeClient: 客户端已关闭，跳过重连")
            return False

        logger.info("BridgeClient: 尝试重连 %s ...", self._address)

        if not _ZMQ_AVAILABLE:
            logger.error("BridgeClient: 重连失败 - pyzmq 未安装")
            return False

        try:
            # 创建新 socket 并测试连接
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, self._config.health_check_timeout_ms)
            sock.setsockopt(zmq.SNDTIMEO, 2000)

            try:
                sock.connect(self._address)
                hb = Serializer.build_health_check()
                sock.send(Serializer.serialize_health(hb))

                if sock.poll(self._config.health_check_timeout_ms, zmq.POLLIN):
                    resp_bytes = sock.recv()
                    resp = HealthCheckResponse()
                    resp.ParseFromString(resp_bytes)
                    parsed = Serializer.parse_health_response(resp)
                    if parsed.get("status_code") == 0:
                        logger.info(
                            "BridgeClient: 重连成功 - %s (latency: %s)",
                            parsed.get("status", "OK"),
                            parsed.get("latency_ms", "N/A"),
                        )
                        return True
                    else:
                        logger.warning(
                            "BridgeClient: 重连失败 - %s",
                            parsed.get("status", "UNKNOWN"),
                        )
                else:
                    logger.warning("BridgeClient: 重连超时")
            finally:
                sock.close(linger=0)
        except Exception as exc:
            logger.warning("BridgeClient: 重连异常: %s", exc)

        return False

    # ---- 阻塞请求（任务7 Phase 1） ----
    def request_blocking(self, request_bytes: bytes, timeout_ms: int = 600000) -> bytes:
        """阻塞请求：在调用线程中直接发送 ZMQ 请求并等待响应。

        用于 ComputePipelineWorker 等已在 QThread 中的调用者。

        Args:
            request_bytes: 序列化后的 protobuf 请求字节
            timeout_ms: 超时（毫秒），默认 600s

        Returns:
            原始响应字节

        Raises:
            BridgeError: 超时、连接失败、序列化错误等
        """
        if self._closed:
            raise ShutdownError("客户端已关闭")

        if not _ZMQ_AVAILABLE:
            raise BridgeError("pyzmq 未安装")

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, self._config.connect_timeout_ms)

        try:
            sock.connect(self._address)
            sock.send(request_bytes)

            poll_interval = self._config.poll_interval_ms
            elapsed = 0
            while elapsed < timeout_ms:
                if sock.poll(poll_interval, zmq.POLLIN):
                    reply = sock.recv()
                    return reply
                elapsed += poll_interval
                if self._closed:
                    raise ShutdownError("客户端在请求期间被关闭")

            # 超时：ZMQ REQ/REP socket 状态不确定，必须重置
            logger.warning(
                "BridgeClient REQ socket 超时 (%dms)，重置 socket 并尝试重连",
                timeout_ms,
            )
            self.reconnect()  # 验证连接可用性，为下次请求做准备
            raise ConnectionTimeoutError(
                f"请求超时 ({timeout_ms}ms)", timeout_ms=timeout_ms
            )
        except (BridgeError, ShutdownError, ConnectionTimeoutError):
            raise
        except Exception as exc:
            raise translate_zmq_error(exc) from exc
        finally:
            sock.close(linger=0)

    # ---- 健康检查 ----
    def check_health(self, on_health: Callable[[bool, str], None]) -> None:
        """单次健康检查（异步）。"""
        if self._closed:
            on_health(False, "客户端已关闭")
            return

        # 等待上一个 health worker 完成（防止覆盖竞态）
        if self._health_worker is not None and self._health_worker.isRunning():
            return  # 跳过本次心跳检查

        self._health_worker = _HealthWorker(self._address, self._config)
        self._health_worker.result_ready.connect(
            lambda ok, msg, latency: self._on_health_ready(ok, msg, on_health)
        )
        self._health_worker.start()

    def start_heartbeat(self) -> None:
        """启动后台心跳监控。"""
        from .heartbeat import HeartbeatMonitor

        if self._heartbeat is not None:
            return
        self._heartbeat = HeartbeatMonitor(self.check_health, self._config)
        self._heartbeat.status_changed.connect(self._on_heartbeat_status)
        self._heartbeat.start()

    def stop_heartbeat(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None

    # ---- 清理 ----
    def close(self, wait_ms: int = 4000) -> None:
        """停止所有后台工作并清理资源。"""
        self._closed = True
        self.stop_heartbeat()
        for worker in (self._request_worker, self._health_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(wait_ms):
                    worker.terminate()
                    worker.wait(1000)
        self._request_worker = None
        self._health_worker = None

    # ---- 内部回调 ----
    def _on_result_ready(self, result: RepairResult) -> None:
        if self._on_result:
            self._on_result(result)

    def _on_error_occurred(self, msg: str, request_id: str) -> None:
        with self._lock:
            self._connected = False
        if self._on_error:
            err = translate_zmq_error(Exception(msg), request_id=request_id)
            self._on_error(err)

    def _on_worker_finished(self) -> None:
        self._request_worker = None

    def _on_health_ready(
        self,
        ok: bool,
        msg: str,
        callback: Callable[[bool, str], None],
    ) -> None:
        with self._lock:
            self._connected = ok
        callback(ok, msg)

    def _on_heartbeat_status(self, status: int, msg: str) -> None:
        with self._lock:
            self._connected = status == 0
