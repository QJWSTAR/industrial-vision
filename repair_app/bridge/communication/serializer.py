"""bridge.communication.serializer — 序列化抽象层（任务5）

复用现有 repair_serialization.py 的 Protobuf 编解码，
提供统一的序列化/反序列化接口与错误处理。

序列化方案选型结论（任务5）：
- Protocol Buffers：已采用（v2.1 协议固定），二进制紧凑、跨语言、schema 强类型
- JSON：人类可读但体积大 3-5x，大数组慢，仅用于日志/调试
- MessagePack：紧凑但无 schema，跨语言类型歧义
- NumPy binary：最快但仅限 Python，MATLAB 无法直接解析
- MAT files：MATLAB 原生但 Python 需 scipy，且不适合 RPC

选型：Protobuf（RPC 消息）+ NumPy（大数组 SoA 布局已内嵌于 Protobuf）
"""
from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np

from repair_app.communication.repair_serialization import (
    build_repair_request as _build_repair_request,
    parse_point_cloud as _parse_point_cloud,
    build_repair_result as _build_repair_result,
    parse_repair_result as _parse_repair_result,
    serialize_request as _serialize_request,
    deserialize_request as _deserialize_request,
    serialize_result as _serialize_result,
    deserialize_result as _deserialize_result,
    build_health_check_request as _build_health_check_request,
    parse_health_check_response as _parse_health_check_response,
)
from repair_app.communication.repair_protocol_pb2 import (
    HealthCheckRequest,
    HealthCheckResponse,
    RepairRequest,
    RepairResult,
    RepairStatusCode,
)
from .exceptions import SerializationError
from .protocol import PROTOCOL_VERSION


class Serializer:
    """统一序列化门面：封装 Protobuf 编解码 + 错误翻译。

    所有业务层通过此类序列化，不直接调用 repair_serialization。
    """

    CLIENT_VERSION = f"bridge-{PROTOCOL_VERSION}"

    # ---- 修复请求 ----
    @staticmethod
    def build_repair_request(
        xyz: np.ndarray,
        normals: np.ndarray,
        scan_id: str,
        **kwargs: Any,
    ) -> RepairRequest:
        """构建修复请求（NumPy → Protobuf）。"""
        try:
            return _build_repair_request(xyz, normals, scan_id, **kwargs)
        except (ValueError, TypeError) as exc:
            raise SerializationError(f"构建修复请求失败: {exc}") from exc

    @staticmethod
    def parse_point_cloud(msg: RepairRequest) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        """解析请求中的点云（Protobuf → NumPy）。"""
        try:
            return _parse_point_cloud(msg)
        except Exception as exc:
            raise SerializationError(f"解析点云失败: {exc}") from exc

    # ---- 修复结果 ----
    @staticmethod
    def build_repair_result(
        waypoints: np.ndarray,
        **kwargs: Any,
    ) -> RepairResult:
        """构建修复结果。"""
        try:
            return _build_repair_result(waypoints, **kwargs)
        except (ValueError, TypeError) as exc:
            raise SerializationError(f"构建修复结果失败: {exc}") from exc

    @staticmethod
    def parse_repair_result(msg: RepairResult) -> dict[str, Any]:
        """解析修复结果（Protobuf → dict）。"""
        try:
            return _parse_repair_result(msg)
        except Exception as exc:
            raise SerializationError(f"解析修复结果失败: {exc}") from exc

    # ---- 健康检查 ----
    @staticmethod
    def build_health_check() -> HealthCheckRequest:
        req = _build_health_check_request()
        req.client_version = Serializer.CLIENT_VERSION
        return req

    @staticmethod
    def parse_health_response(msg: HealthCheckResponse) -> dict[str, Any]:
        try:
            return _parse_health_check_response(msg)
        except Exception as exc:
            raise SerializationError(f"解析健康检查响应失败: {exc}") from exc

    # ---- 字节级编解码 ----
    @staticmethod
    def serialize_request(msg: RepairRequest) -> bytes:
        try:
            return _serialize_request(msg)
        except Exception as exc:
            raise SerializationError(f"序列化请求失败: {exc}") from exc

    @staticmethod
    def deserialize_request(data: bytes) -> RepairRequest:
        try:
            return _deserialize_request(data)
        except Exception as exc:
            raise SerializationError(f"反序列化请求失败: {exc}") from exc

    @staticmethod
    def serialize_result(msg: RepairResult) -> bytes:
        try:
            return _serialize_result(msg)
        except Exception as exc:
            raise SerializationError(f"序列化结果失败: {exc}") from exc

    @staticmethod
    def deserialize_result(data: bytes) -> RepairResult:
        try:
            return _deserialize_result(data)
        except Exception as exc:
            raise SerializationError(f"反序列化结果失败: {exc}") from exc

    @staticmethod
    def serialize_health(msg: HealthCheckRequest) -> bytes:
        try:
            return msg.SerializeToString()
        except Exception as exc:
            raise SerializationError(f"序列化健康检查失败: {exc}") from exc

    @staticmethod
    def try_deserialize_health(data: bytes) -> Optional[HealthCheckRequest]:
        """尝试解析为健康检查，失败返回 None（用于消息分发）。"""
        msg = HealthCheckRequest()
        try:
            msg.ParseFromString(data)
        except Exception:
            return None
        return msg if msg.client_version else None
