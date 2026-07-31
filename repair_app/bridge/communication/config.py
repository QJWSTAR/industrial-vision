"""bridge.communication.config — 集中化配置（任务9 / 任务J 重构）

所有通信参数集中于此，无硬编码值。
默认值全部从 parameter_schema.json 读取，环境变量优先级最高。

环境变量 → schema 默认值（不再有任何 Magic Number）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from repair_app.config import schema_loader as _schema
from repair_app.platform.transport import get_zmq_address_from_env
from repair_app.utils.logger_config import warning


def _env_int(key: str, schema_key: str, fallback: int = 0) -> int:
    """优先读环境变量，缺失时回退到 schema 默认值，schema 异常时回退到 fallback。"""
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError as exc:
            warning(f"环境变量 {key}='{val}' 无法转为 int，回退 schema 默认值: {exc}")
    try:
        return int(_schema.get_network_value(schema_key))
    except Exception as exc:
        warning(f"读取 schema '{schema_key}' 失败，使用 fallback={fallback}: {exc}")
        return fallback


def _env_str(key: str, schema_key: str, fallback: str = "") -> str:
    """优先读环境变量，缺失时回退到 schema 默认值，schema 异常时回退到 fallback。"""
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        return str(_schema.get_network_value(schema_key))
    except Exception as exc:
        warning(f"读取 schema '{schema_key}' 失败，使用 fallback='{fallback}': {exc}")
        return fallback


@dataclass(frozen=True)
class BridgeConfig:
    """通信层全局配置（不可变）。

    所有默认值从 parameter_schema.json 的 network_parameters 读取。
    """

    # ---- 网络 ----
    address: str = field(default_factory=get_zmq_address_from_env)
    """ZMQ 绑定/连接地址。默认读取 CSAM_ZMQ_ADDRESS 环境变量。"""

    # ---- 超时（毫秒）----
    request_timeout_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_TIMEOUT_MS", "bridge_timeout_ms")
    )
    connect_timeout_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_CONNECT_MS", "bridge_connect_timeout_ms")
    )
    health_check_timeout_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_HEALTH_MS", "bridge_health_check_timeout_ms")
    )

    # ---- 心跳 ----
    heartbeat_interval_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_HEARTBEAT_MS", "bridge_heartbeat_interval_ms")
    )
    heartbeat_miss_threshold: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_HEARTBEAT_MISS", "bridge_heartbeat_miss_threshold")
    )

    # ---- 重试 ----
    max_retries: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_MAX_RETRIES", "bridge_max_retries")
    )
    retry_interval_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_RETRY_MS", "bridge_retry_interval_ms")
    )

    # ---- 协议（版本号从 schema 读取）----
    protocol_version: str = field(
        default_factory=lambda: str(_schema.get_network_value("bridge_protocol_version"))
    )
    client_version: str = field(
        default_factory=lambda: str(_schema.get_network_value("bridge_client_version"))
    )

    # ---- 日志 ----
    log_level: str = field(default_factory=lambda: os.environ.get("CSAM_LOG_LEVEL", "INFO"))
    log_latency_threshold_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_LATENCY_LOG_MS", "bridge_log_latency_threshold_ms")
    )

    # ---- 性能（从 schema 读取）----
    poll_interval_ms: int = field(
        default_factory=lambda: int(_schema.get_network_value("bridge_poll_interval_ms"))
    )
    """协作式中断的 poll 间隔，兼顾响应性与 CPU 开销。"""

    large_array_warn_threshold: int = field(
        default_factory=lambda: int(_schema.get_network_value("bridge_large_array_warn_threshold"))
    )

    @property
    def request_timeout_s(self) -> float:
        return self.request_timeout_ms / 1000.0

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        """从环境变量加载配置。"""
        return cls()


# 全局默认配置单例（惰性初始化，避免模块加载时 schema 异常导致级联导入失败）
_DEFAULT_CONFIG: Optional[BridgeConfig] = None


def get_default_config() -> BridgeConfig:
    """获取全局默认配置（惰性初始化）。"""
    global _DEFAULT_CONFIG
    if _DEFAULT_CONFIG is None:
        try:
            _DEFAULT_CONFIG = BridgeConfig.from_env()
        except Exception as exc:
            warning(f"BridgeConfig 初始化失败，使用空配置: {exc}")
            _DEFAULT_CONFIG = BridgeConfig(
                address="tcp://127.0.0.1:5555",
            )
    return _DEFAULT_CONFIG


# 向后兼容：保留 DEFAULT_CONFIG 属性访问
class _ConfigProxy:
    """惰性代理，首次访问属性时初始化 DEFAULT_CONFIG。"""
    def __getattr__(self, name):
        return getattr(get_default_config(), name)

    def __repr__(self):
        return repr(get_default_config())


DEFAULT_CONFIG = _ConfigProxy()
