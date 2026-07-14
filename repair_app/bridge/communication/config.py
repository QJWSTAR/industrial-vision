"""bridge.communication.config — 集中化配置（任务9）

所有通信参数集中于此，无硬编码值。
支持环境变量覆盖 + dataclass 默认值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from repair_app.platform.transport import get_zmq_address_from_env


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    try:
        return float(val) if val is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class BridgeConfig:
    """通信层全局配置（不可变）。"""

    # ---- 网络 ----
    address: str = field(default_factory=get_zmq_address_from_env)
    """ZMQ 绑定/连接地址。默认读取 CSAM_ZMQ_ADDRESS 环境变量。"""

    # ---- 超时（毫秒）----
    request_timeout_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_TIMEOUT_MS", 30000))
    connect_timeout_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_CONNECT_MS", 5000))
    health_check_timeout_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_HEALTH_MS", 3000))

    # ---- 心跳 ----
    heartbeat_interval_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_HEARTBEAT_MS", 5000))
    heartbeat_miss_threshold: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_HEARTBEAT_MISS", 3))

    # ---- 重试 ----
    max_retries: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_MAX_RETRIES", 3))
    retry_interval_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_RETRY_MS", 2000))

    # ---- 协议 ----
    protocol_version: str = "2.1"
    client_version: str = "bridge-1.0.0"

    # ---- 日志 ----
    log_level: str = field(default_factory=lambda: os.environ.get("CSAM_LOG_LEVEL", "INFO"))
    log_latency_threshold_ms: int = field(default_factory=lambda: _env_int("CSAM_BRIDGE_LATENCY_LOG_MS", 1000))

    # ---- 性能 ----
    poll_interval_ms: int = 200
    """协作式中断的 poll 间隔，兼顾响应性与 CPU 开销。"""

    large_array_warn_threshold: int = 1_000_000

    @property
    def request_timeout_s(self) -> float:
        return self.request_timeout_ms / 1000.0

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        """从环境变量加载配置。"""
        return cls()


# 全局默认配置单例（业务层通过 MatlabService.config 访问）
DEFAULT_CONFIG = BridgeConfig.from_env()
