"""bridge.communication.protocol — 协议常量与版本管理（任务4）

复用现有 repair_protocol_pb2（Protobuf v2.1），不重新生成。
本模块定义协议元数据与消息类型分发。
"""
from __future__ import annotations

from enum import IntEnum

# 协议版本（与 repair_protocol.proto 一致）
PROTOCOL_VERSION = "2.1"
COMPATIBLE_PROTOCOL_VERSIONS = ("2.0", "2.1")

# 复用现有生成的 Protobuf 消息
from repair_app.communication.repair_protocol_pb2 import (  # noqa: E402
    RepairRequest,
    RepairResult,
    HealthCheckRequest,
    HealthCheckResponse,
    ProgressUpdate,
    RepairStatusCode,
    MaterialType,
)


class MessageType(IntEnum):
    """消息类型枚举（用于消息信封分发）。"""

    HEALTH_CHECK = 1
    REPAIR_REQUEST = 2
    REPAIR_RESULT = 3
    PROGRESS_UPDATE = 4
    SHUTDOWN = 99


class EngineStatus(IntEnum):
    """引擎状态（健康检查结果映射）。"""

    OK = 0
    DEGRADED = 1
    DOWN = 2


# 状态码到异常的映射（任务8用）
STATUS_CODE_NAMES = {
    RepairStatusCode.SUCCESS: "SUCCESS",
    RepairStatusCode.ERR_INVALID_INPUT: "INVALID_INPUT",
    RepairStatusCode.ERR_NO_DEFECT_FOUND: "NO_DEFECT_FOUND",
    RepairStatusCode.ERR_ALGORITHM_FAIL: "ALGORITHM_FAIL",
    RepairStatusCode.ERR_TIMEOUT: "TIMEOUT",
    RepairStatusCode.ERR_NOT_FEASIBLE: "NOT_FEASIBLE",
    RepairStatusCode.ERR_UNKNOWN: "UNKNOWN",
}


def is_status_success(status_code: int) -> bool:
    """判断状态码是否为成功。"""
    return status_code == RepairStatusCode.SUCCESS


def is_status_retriable(status_code: int) -> bool:
    """判断状态码是否值得重试（超时/未知可重试，参数错误不可重试）。"""
    return status_code in (RepairStatusCode.ERR_TIMEOUT, RepairStatusCode.ERR_UNKNOWN)
