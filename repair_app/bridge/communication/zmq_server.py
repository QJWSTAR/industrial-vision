"""bridge.communication.zmq_server — ZMQ 服务端基类（任务6）

提供 REP 服务端骨架，MATLAB 适配器继承此类实现算法回调。
支持优雅关闭与统计。
"""
from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import zmq
    _ZMQ_AVAILABLE = True
except ImportError:
    _ZMQ_AVAILABLE = False
    zmq = None

from .config import BridgeConfig
from .protocol import RepairStatusCode
from .serializer import Serializer
from repair_app.communication.repair_protocol_pb2 import (
    HealthCheckResponse,
    RepairRequest,
    RepairResult,
)

logger = logging.getLogger("csam.bridge.server")


@dataclass
class ServerStats:
    """服务端运行统计。"""
    started_at: float = 0.0
    handled_requests: int = 0
    health_checks: int = 0
    errors: int = 0


class BridgeServer:
    """ZMQ REP 服务端基类。

    子类实现 handle_repair(request) -> RepairResult。
    健康检查与消息分发由基类处理。
    """

    SERVICE_VERSION = "bridge-server-1.0.0"

    def __init__(
        self,
        address: Optional[str] = None,
        config: Optional[BridgeConfig] = None,
    ) -> None:
        self._config = config or BridgeConfig.from_env()
        self._address = address or self._config.address
        self._stats = ServerStats(started_at=time.time())
        self._running = False

    # ---- 子类实现 ----
    def handle_repair(self, request: RepairRequest) -> RepairResult:
        """处理修复请求。子类必须实现。"""
        raise NotImplementedError("子类必须实现 handle_repair")

    # ---- 服务生命周期 ----
    def serve(self) -> None:
        """启动服务（阻塞，但使用 poll 可被 stop() 中断）。"""
        if not _ZMQ_AVAILABLE:
            raise RuntimeError("pyzmq 未安装，无法启动服务")

        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REP)
        sock.setsockopt(zmq.LINGER, 0)
        sock.bind(self._address)
        self._running = True
        logger.info("Bridge server listening at %s", self._address)

        try:
            while self._running:
                # 使用 poll 避免永久阻塞，每 200ms 检查 _running
                if not sock.poll(200, zmq.POLLIN):
                    continue
                try:
                    data = sock.recv(zmq.NOBLOCK)
                except zmq.Again:
                    continue
                response = self._dispatch(data)
                sock.send(response)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
        except zmq.ContextTerminated:
            pass
        finally:
            sock.close(linger=0)
            self._running = False
            logger.info(
                "Bridge server stopped (handled=%d, health=%d, errors=%d)",
                self._stats.handled_requests,
                self._stats.health_checks,
                self._stats.errors,
            )

    def stop(self) -> None:
        """请求停止。"""
        self._running = False

    # ---- 消息分发 ----
    def _dispatch(self, data: bytes) -> bytes:
        """分发消息：健康检查 or 修复请求。"""
        # 尝试健康检查
        health_req = Serializer.try_deserialize_health(data)
        if health_req is not None:
            self._stats.health_checks += 1
            return self._build_health_response()

        # 修复请求
        self._stats.handled_requests += 1
        try:
            request = Serializer.deserialize_request(data)
            result = self.handle_repair(request)
            return Serializer.serialize_result(result)
        except Exception as exc:
            self._stats.errors += 1
            logger.exception("处理修复请求失败")
            error_result = Serializer.build_repair_result(
                __import__("numpy").zeros((0, 3), dtype="float32"),
                status_code=RepairStatusCode.ERR_ALGORITHM_FAIL,
                error_message=str(exc),
                is_feasible=False,
                feasibility_reason=str(exc),
            )
            return Serializer.serialize_result(error_result)

    def _build_health_response(self) -> bytes:
        resp = HealthCheckResponse()
        resp.status = HealthCheckResponse.OK
        resp.service_version = self.SERVICE_VERSION
        resp.memory_usage_mb = 0.0
        resp.uptime_s = int(time.time() - self._stats.started_at)
        resp.pending_requests = 0
        return resp.SerializeToString()

    # ---- 信号处理（POSIX）----
    def install_signal_handlers(self) -> None:
        """安装 SIGINT/SIGTERM 处理器以优雅关闭。"""
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: self.stop())
