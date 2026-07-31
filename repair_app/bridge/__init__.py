"""bridge — Python-MATLAB 通信桥接层。

业务层通过 MatlabService 与 MATLAB 交互：
    from repair_app.bridge import MatlabService, RepairOutcome

通信层细节封装在 bridge.communication 中，业务层不应直接导入。
"""
from .communication import (
    BridgeClient,
    BridgeConfig,
    BridgeError,
    BridgeServer,
    BridgeConnectionError,
    ConnectionError,  # backward-compatible alias
    ConnectionTimeoutError,
    DEFAULT_CONFIG,
    EngineStatus,
    EngineUnavailableError,
    EngineCrashError,
    InvalidParameterError,
    AlgorithmError,
    ProtocolError,
    SerializationError,
    ShutdownError,
    MessageEnvelope,
    MessageType,
    PROTOCOL_VERSION,
    Serializer,
    generate_request_id,
)
from .services.matlab_service import MatlabService, RepairOutcome

__version__ = "1.0.0"

__all__ = [
    "MatlabService",
    "RepairOutcome",
    "BridgeClient",
    "BridgeServer",
    "BridgeConfig",
    "BridgeError",
    "BridgeConnectionError",
    "ConnectionError",  # backward-compatible alias
    "ConnectionTimeoutError",
    "EngineUnavailableError",
    "EngineCrashError",
    "InvalidParameterError",
    "AlgorithmError",
    "ProtocolError",
    "SerializationError",
    "ShutdownError",
    "DEFAULT_CONFIG",
    "EngineStatus",
    "MessageEnvelope",
    "MessageType",
    "PROTOCOL_VERSION",
    "Serializer",
    "generate_request_id",
]
