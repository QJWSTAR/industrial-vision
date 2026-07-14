"""bridge.communication.message — 消息信封（任务4）

为每条消息附加元数据：request_id、timestamp、message_type、version。
Protobuf 消息作为 payload 透明传输。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .protocol import MessageType, PROTOCOL_VERSION


@dataclass
class MessageEnvelope:
    """消息信封：包裹 Protobuf payload + 元数据。

    设计目标：
    - request_id：全链路追踪
    - timestamp：延迟分析
    - message_type：消息分发
    - version：协议兼容性检查
    """

    message_type: MessageType
    payload: bytes
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    version: str = PROTOCOL_VERSION
    algorithm: str = ""
    processing_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "message_type": self.message_type.name,
            "timestamp": self.timestamp,
            "version": self.version,
            "algorithm": self.algorithm,
            "processing_time_ms": self.processing_time_ms,
            "payload_size": len(self.payload),
        }

    @property
    def age_ms(self) -> float:
        """消息从创建至今的毫秒数。"""
        return (time.time() - self.timestamp) * 1000.0

    def is_version_compatible(self, compatible_versions: tuple[str, ...] = ()) -> bool:
        target = compatible_versions or (PROTOCOL_VERSION,)
        return self.version in target


def generate_request_id(prefix: str = "req") -> str:
    """生成可读的请求 ID。"""
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
