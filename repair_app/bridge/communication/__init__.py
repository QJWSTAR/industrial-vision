"""bridge.communication — 通信层公共 API。"""
from .config import BridgeConfig, DEFAULT_CONFIG
from .exceptions import (
    AlgorithmError,
    BridgeError,
    BridgeConnectionError,
    ConnectionError,  # backward-compatible alias for BridgeConnectionError
    ConnectionTimeoutError,
    EngineCrashError,
    EngineUnavailableError,
    InvalidParameterError,
    ProtocolError,
    SerializationError,
    ShutdownError,
    translate_zmq_error,
)
from .message import MessageEnvelope, generate_request_id
from .protocol import (
    COMPATIBLE_PROTOCOL_VERSIONS,
    EngineStatus,
    MessageType,
    PROTOCOL_VERSION,
)
from .serializer import Serializer
from .zmq_client import BridgeClient
from .zmq_server import BridgeServer, ServerStats

__all__ = [
    "BridgeConfig",
    "DEFAULT_CONFIG",
    "BridgeClient",
    "BridgeServer",
    "ServerStats",
    "Serializer",
    "MessageEnvelope",
    "generate_request_id",
    "PROTOCOL_VERSION",
    "COMPATIBLE_PROTOCOL_VERSIONS",
    "MessageType",
    "EngineStatus",
    "BridgeError",
    "BridgeConnectionError",
    "ConnectionError",  # backward-compatible alias
    "ConnectionTimeoutError",
    "EngineUnavailableError",
    "EngineCrashError",
    "SerializationError",
    "InvalidParameterError",
    "AlgorithmError",
    "ProtocolError",
    "ShutdownError",
    "translate_zmq_error",
]
