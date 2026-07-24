"""bridge.communication.zmq_server — ZMQ 服务端基类（任务6）

提供 REP 服务端骨架，MATLAB 适配器继承此类实现算法回调。
支持优雅关闭、Ctrl+C 中断与资源清理。
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

    Ctrl+C 行为：
    - 不吞咽 SIGINT，让 KeyboardInterrupt 正常传播
    - MATLAB pyenv 环境下，MATLAB 的 Ctrl+C 会转为 Python KeyboardInterrupt
    - serve() 在 finally 中清理 socket/context，确保无资源泄露
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
        self._sock = None
        self._ctx = None

    # ---- 子类实现 ----
    def handle_repair(self, request: RepairRequest) -> RepairResult:
        """处理修复请求。子类必须实现。"""
        raise NotImplementedError("子类必须实现 handle_repair")

    # ---- 服务生命周期 ----
    def serve(self) -> None:
        """启动服务（阻塞）。

        Ctrl+C 会抛出 KeyboardInterrupt，在 finally 中清理资源。
        不安装 signal handler，让 KeyboardInterrupt 自然传播到 MATLAB。
        """
        if not _ZMQ_AVAILABLE:
            raise RuntimeError("pyzmq 未安装，无法启动服务")

        # 使用独立 Context（非 instance()），确保可完全 terminate 释放端口
        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.REP)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.bind(self._address)
        self._running = True
        logger.info("Bridge server listening at %s", self._address)

        try:
            while self._running:
                # poll 短超时，允许 KeyboardInterrupt 在 100ms 内被处理
                if not self._sock.poll(100, zmq.POLLIN):
                    continue
                try:
                    data = self._sock.recv(zmq.NOBLOCK)
                except zmq.Again:
                    continue
                response = self._dispatch(data)
                self._sock.send(response)
        except KeyboardInterrupt:
            logger.info("收到 Ctrl+C 中断信号，正在关闭...")
            # 让 KeyboardInterrupt 继续传播到调用方（matlab_bridge_server.m）
            raise
        except zmq.ContextTerminated:
            logger.info("ZMQ Context 已终止")
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """清理 ZMQ 资源：socket → context → 子类 shutdown，确保端口释放。"""
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close(linger=0)
            except Exception as exc:
                logger.warning("关闭 socket 异常: %s", exc)
            finally:
                self._sock = None
        if self._ctx is not None:
            try:
                self._ctx.term()
                logger.info("ZMQ Context 已终止，端口已释放")
            except Exception as exc:
                logger.warning("终止 Context 异常: %s", exc)
            finally:
                self._ctx = None
        # 调用子类 shutdown 释放 MATLAB 引擎等资源
        try:
            self.shutdown()
        except AttributeError:
            pass  # 子类未实现 shutdown，忽略
        except Exception as exc:
            logger.warning("子类 shutdown 异常: %s", exc)
        logger.info(
            "Bridge server stopped (handled=%d, health=%d, errors=%d)",
            self._stats.handled_requests,
            self._stats.health_checks,
            self._stats.errors,
        )

    def stop(self) -> None:
        """请求停止（非阻塞，供外部调用）。"""
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
        from .protocol import PROTOCOL_VERSION

        resp = HealthCheckResponse()
        resp.status = HealthCheckResponse.OK
        resp.service_version = self.SERVICE_VERSION
        resp.protocol_version = PROTOCOL_VERSION
        resp.memory_usage_mb = 0.0
        resp.uptime_s = int(time.time() - self._stats.started_at)
        resp.pending_requests = 0
        return resp.SerializeToString()

    # ---- 信号处理（已废弃，保留空实现以兼容旧调用）----
    def install_signal_handlers(self) -> None:
        """兼容旧调用：不再安装 signal handler。

        旧版安装 signal.signal(SIGINT, ...) 会吞咽 Ctrl+C，
        导致 MATLAB 无法收到 KeyboardInterrupt，服务无法退出。
        现在改为让 KeyboardInterrupt 自然传播。
        """
        logger.debug("install_signal_handlers 已废弃（Ctrl+C 由 KeyboardInterrupt 处理）")
