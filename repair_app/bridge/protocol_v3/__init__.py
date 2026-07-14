"""[DEPRECATED] Protocol v3.0 — algorithm-agnostic communication protocol.

.. deprecated::
    Protocol v3.0 (generic AlgorithmRequest/AlgorithmResponse over JSON/TCP,
    port 5570) has been SUPERSEDED by the finalized production communication
    architecture, which uses Protocol Buffers v2.1 (repair_protocol.proto,
    business-specific RepairRequest/RepairResult) over ZeroMQ on port 5555.

    The production path is:
        GUI -> CoordinationService -> MatlabService / LegacyZmqClient
             -> Bridge -> ZeroMQ (port 5555) -> Protocol Buffers (v2.1)
             -> matlab_bridge_server.m -> MATLAB R2025b

    This package is retained ONLY for backward compatibility and the
    mock-server test suite (test_matlab_platform.py). No production code
    imports it. Do NOT use it for new code. See docs/COMMUNICATION.md for
    the rationale and deprecation timeline.

Original description (for historical reference):
    Generates Python bindings from algorithm_protocol_v3.proto. Re-exports
    key message types (AlgorithmRequest, AlgorithmResponse, etc.).
"""
from __future__ import annotations

import warnings
warnings.warn(
    "repair_app.bridge.protocol_v3 is DEPRECATED. The production protocol "
    "is Protobuf v2.1 (repair_protocol.proto) over ZeroMQ (port 5555). "
    "See docs/COMMUNICATION.md.",
    DeprecationWarning,
    stacklevel=2,
)

from .algorithm_protocol_v3_pb2 import (
    Envelope,
    AlgorithmRequest,
    AlgorithmResponse,
    AlgorithmMetadata,
    FieldSchema,
    FieldSpec,
    ProgressUpdate,
    Heartbeat,
    Pong,
    HealthCheckRequest,
    HealthStatus,
    Cancellation,
    VersionNegotiate,
    VersionResult,
    ListAlgorithmsRequest,
    ListAlgorithmsResponse,
    ShutdownRequest,
    ShutdownAck,
    Value,
    Tensor,
)

PROTOCOL_VERSION = "3.0"

# Message type constants (for Envelope.message_type field)
class MessageType:
    ALGORITHM_REQUEST   = "ALGORITHM_REQUEST"
    ALGORITHM_RESPONSE  = "ALGORITHM_RESPONSE"
    PROGRESS_UPDATE     = "PROGRESS_UPDATE"
    HEARTBEAT           = "HEARTBEAT"
    PONG                = "PONG"
    HEALTH_CHECK        = "HEALTH_CHECK"
    HEALTH_STATUS       = "HEALTH_STATUS"
    CANCELLATION        = "CANCELLATION"
    VERSION_NEGOTIATE   = "VERSION_NEGOTIATE"
    VERSION_RESULT      = "VERSION_RESULT"
    LIST_ALGORITHMS     = "LIST_ALGORITHMS"
    LIST_ALGORITHMS_RESP= "LIST_ALGORITHMS_RESPONSE"
    SHUTDOWN_REQUEST    = "SHUTDOWN_REQUEST"
    SHUTDOWN_ACK        = "SHUTDOWN_ACK"

__all__ = [
    "PROTOCOL_VERSION",
    "MessageType",
    "Envelope",
    "AlgorithmRequest",
    "AlgorithmResponse",
    "AlgorithmMetadata",
    "FieldSchema",
    "FieldSpec",
    "ProgressUpdate",
    "Heartbeat",
    "Pong",
    "HealthCheckRequest",
    "HealthStatus",
    "Cancellation",
    "VersionNegotiate",
    "VersionResult",
    "ListAlgorithmsRequest",
    "ListAlgorithmsResponse",
    "ShutdownRequest",
    "ShutdownAck",
    "Value",
    "Tensor",
]
