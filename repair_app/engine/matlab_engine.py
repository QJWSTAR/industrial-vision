"""[DEPRECATED] MATLAB engine — IAlgorithmEngine implementation over TCP to MATLAB Server.

.. deprecated::
    This module implements the TCP + JSON + Protocol v3.0 + port 5570
    communication stack, which has been SUPERSEDED by the finalized
    production communication architecture:

        GUI -> CoordinationService -> MatlabService / LegacyZmqClient
             -> Bridge -> ZeroMQ (port 5555) -> Protocol Buffers (v2.1)
             -> matlab_bridge_server.m -> MATLAB R2025b

    The production path uses ZeroMQ + Protocol Buffers (repair_protocol.proto,
    v2.1) on port 5555 via ``repair_app.bridge``. This TCP/JSON/v3.0 module is
    retained ONLY for backward compatibility and for the mock-server test
    suite (test_matlab_platform.py). It must NOT be wired into the GUI or any
    production code path. See docs/COMMUNICATION.md for the rationale.

Original description (for historical reference):
    Connects to the MATLAB Server (matlab_server/) via TCP using
    length-prefixed JSON framing. Implements the IEngine interface so the
    GUI/Service layer never knows which backend is executing.

    Transport: TCP (java.net.ServerSocket on MATLAB side) with 4-byte
    big-endian length prefix + UTF-8 JSON payload.
    Protocol: v3.0 algorithm-agnostic messages (JSON-encoded).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional

import numpy as np

from repair_app.domain.interfaces import IEngine
from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams

logger = logging.getLogger("csam.engine.matlab")


# ============================================================
# Protocol v3.0 — JSON wire format (MATLAB-compatible)
# ============================================================

PROTOCOL_VERSION = "3.0"
SERVER_APP_VERSION = "matlab_server/1.0.0"


class MessageType:
    ALGORITHM_REQUEST    = "ALGORITHM_REQUEST"
    ALGORITHM_RESPONSE   = "ALGORITHM_RESPONSE"
    PROGRESS_UPDATE      = "PROGRESS_UPDATE"
    HEARTBEAT            = "HEARTBEAT"
    PONG                 = "PONG"
    HEALTH_CHECK         = "HEALTH_CHECK"
    HEALTH_STATUS        = "HEALTH_STATUS"
    CANCELLATION         = "CANCELLATION"
    VERSION_NEGOTIATE    = "VERSION_NEGOTIATE"
    VERSION_RESULT       = "VERSION_RESULT"
    LIST_ALGORITHMS      = "LIST_ALGORITHMS"
    LIST_ALGORITHMS_RESP = "LIST_ALGORITHMS_RESPONSE"
    SHUTDOWN_REQUEST     = "SHUTDOWN_REQUEST"
    SHUTDOWN_ACK         = "SHUTDOWN_ACK"


class ResponseStatus(IntEnum):
    OK            = 0
    ERR_INVALID   = 1
    ERR_TIMEOUT   = 2
    ERR_ALGORITHM = 3
    ERR_DEPS      = 4
    ERR_NOT_FOUND = 5
    ERR_CANCELLED = 6
    ERR_VERSION   = 7
    UNKNOWN       = 99


# ============================================================
# Tensor <-> JSON (base64) codec
# ============================================================

_DTYPE_TO_CODE = {
    np.dtype(np.float32): "F32",
    np.dtype(np.float64): "F64",
    np.dtype(np.int32):   "I32",
    np.dtype(np.int64):   "I64",
    np.dtype(np.uint8):   "U8",
}
_CODE_TO_DTYPE = {v: k for k, v in _DTYPE_TO_CODE.items()}


def _numpy_to_json(arr: np.ndarray, units: str = "") -> dict:
    arr = np.ascontiguousarray(arr)
    code = _DTYPE_TO_CODE.get(arr.dtype, "F64")
    if code == "F64" and arr.dtype != np.float64:
        arr = arr.astype(np.float64)
    return {
        "dtype": code,
        "shape": list(arr.shape),
        "data": base64.b64encode(arr.tobytes()).decode("ascii"),
        "units": units,
    }


def _json_to_numpy(d: dict) -> np.ndarray:
    code = d.get("dtype", "F64")
    np_dtype = _CODE_TO_DTYPE.get(code, np.float64)
    raw = base64.b64decode(d["data"])
    arr = np.frombuffer(raw, dtype=np_dtype)
    shape = tuple(d.get("shape", [])) or (arr.size,)
    return arr.reshape(shape)


def _py_to_value(v: Any) -> Any:
    if isinstance(v, bool):
        return {"flag": v}
    if isinstance(v, (int, np.integer)):
        return {"intval": int(v)}
    if isinstance(v, (float, np.floating)):
        return {"num": float(v)}
    if isinstance(v, str):
        return {"str": v}
    if isinstance(v, np.ndarray):
        return {"tensor": _numpy_to_json(v)}
    if isinstance(v, (list, tuple)):
        return {"tensor": _numpy_to_json(np.array(v))}
    return {"str": str(v)}


def _value_to_py(val: dict) -> Any:
    if "num" in val:
        return val["num"]
    if "intval" in val:
        return val["intval"]
    if "str" in val:
        return val["str"]
    if "flag" in val:
        return val["flag"]
    if "tensor" in val:
        return _json_to_numpy(val["tensor"])
    return None


# ============================================================
# TCP Framing (4-byte big-endian length + UTF-8 JSON)
# ============================================================

def _send_framed(sock: socket.socket, obj: dict) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    header = struct.pack(">I", len(payload))
    sock.sendall(header + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed during recv")
        buf.extend(chunk)
    return bytes(buf)


def _recv_framed(sock: socket.socket) -> dict:
    header = _recv_exact(sock, 4)
    (length,) = struct.unpack(">I", header)
    payload = _recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))


# ============================================================
# Result dataclass
# ============================================================

@dataclass
class AlgorithmResult:
    status: int
    results: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    compute_time_ms: int = 0
    algorithm_ver: str = ""
    error_code: str = ""
    error_message: str = ""
    error_stack: str = ""

    @property
    def ok(self) -> bool:
        return self.status == ResponseStatus.OK

    def raise_for_error(self) -> None:
        if not self.ok:
            raise AlgorithmEngineError(
                f"[{self.error_code}] {self.error_message}",
                status=self.status,
                stack=self.error_stack,
            )


class AlgorithmEngineError(Exception):
    def __init__(self, msg: str, status: int = ResponseStatus.UNKNOWN, stack: str = ""):
        super().__init__(msg)
        self.status = status
        self.stack = stack


# ============================================================
# TCP Channel — synchronous request/reply with timeout & retry
# ============================================================

class TcpChannel:
    """Low-level TCP channel to MATLAB Server with reconnect support."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5570,
                 timeout_ms: int = 30000, max_retries: int = 3):
        self._host = host
        self._port = port
        self._timeout_ms = timeout_ms
        self._max_retries = max_retries
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return f"tcp://{self._host}:{self._port}"

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        with self._lock:
            if self._sock is not None:
                return
            self._sock = socket.create_connection(
                (self._host, self._port), timeout=self._timeout_ms / 1000.0
            )
            logger.info("connected to MATLAB Server at %s", self.endpoint)

    def disconnect(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                logger.info("disconnected from MATLAB Server")

    def _ensure_connected(self) -> socket.socket:
        if self._sock is None:
            self.connect()
        return self._sock  # type: ignore[return-value]

    def request(self, envelope: dict) -> dict:
        """Send an envelope, receive a response envelope. Retries on connection errors."""
        last_err: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                sock = self._ensure_connected()
                sock.settimeout(self._timeout_ms / 1000.0)
                _send_framed(sock, envelope)
                return _recv_framed(sock)
            except (ConnectionError, socket.error, OSError) as e:
                last_err = e
                logger.warning("request attempt %d/%d failed: %s", attempt, self._max_retries, e)
                self.disconnect()
                if attempt < self._max_retries:
                    time.sleep(min(0.1 * attempt, 1.0))
        raise AlgorithmEngineError(
            f"channel request failed after {self._max_retries} attempts: {last_err}",
            status=ResponseStatus.ERR_TIMEOUT,
        )

    def close(self) -> None:
        self.disconnect()


# ============================================================
# MatlabEngine — IEngine implementation
# ============================================================

class MatlabEngine(IEngine):
    """Production MATLAB engine via TCP to matlab_server.

    Implements the IEngine interface so the GUI/Service layer can swap
    between LocalEngine (Python prototype) and MatlabEngine without code changes.

    The engine speaks protocol v3.0 (algorithm-agnostic) to the MATLAB Server.
    Business-specific calls (plan_path / predict_morphology) are mapped to
    algorithm names: 'path_planning.generate_path' and 'morphology.spot_interp'.
    """

    def __init__(self, host: str = "", port: int = 0,
                 timeout_ms: int = 30000, max_retries: int = 3) -> None:
        import warnings
        warnings.warn(
            "MatlabEngine (TCP/JSON/Protocol v3.0/port 5570) is DEPRECATED. "
            "The production communication path is ZeroMQ + Protocol Buffers "
            "(v2.1) on port 5555 via repair_app.bridge. See "
            "docs/COMMUNICATION.md. This engine is retained only for "
            "backward compatibility and tests.",
            DeprecationWarning,
            stacklevel=2,
        )
        host = host or os.environ.get("CSAM_MATLAB_HOST", "127.0.0.1")
        port = port or int(os.environ.get("CSAM_MATLAB_PORT", "5570"))
        self._channel = TcpChannel(host, port, timeout_ms, max_retries)
        self._available: Optional[bool] = None
        self._algorithm_cache: Optional[list] = None

    # ---- IEngine properties ----

    @property
    def name(self) -> str:
        return "MATLAB Production Engine"

    @property
    def is_available(self) -> bool:
        if self._available is None:
            self._available = self.check_health()
        return self._available

    # ---- Generic algorithm execution ----

    def execute(
        self,
        algorithm_name: str,
        params: Optional[dict] = None,
        inputs: Optional[dict] = None,
        assets: Optional[dict] = None,
        *,
        version: str = "latest",
        timeout_ms: int = 0,
    ) -> AlgorithmResult:
        """Execute an algorithm by name on the MATLAB Server."""
        params = params or {}
        inputs = inputs or {}
        assets = assets or {}

        request_id = str(uuid.uuid4())
        payload = {
            "algorithm_name": algorithm_name,
            "algorithm_ver": version,
            "timeout_ms": timeout_ms,
            "stream_progress": False,
            "params": {k: _py_to_value(v) for k, v in params.items()},
            "inputs": {k: _numpy_to_json(v) for k, v in inputs.items()},
            "assets": {k: base64.b64encode(v).decode("ascii") for k, v in assets.items()},
            "client_version": SERVER_APP_VERSION,
        }
        envelope = {
            "request_id": request_id,
            "timestamp_ms": int(time.time() * 1000),
            "message_type": MessageType.ALGORITHM_REQUEST,
            "protocol_ver": PROTOCOL_VERSION,
            "payload": payload,
        }

        logger.debug("execute %s req_id=%s", algorithm_name, request_id)
        resp_env = self._channel.request(envelope)

        if resp_env.get("message_type") != MessageType.ALGORITHM_RESPONSE:
            raise AlgorithmEngineError(
                f"unexpected response type: {resp_env.get('message_type')}",
                status=ResponseStatus.ERR_ALGORITHM,
            )

        p = resp_env.get("payload", {})
        return AlgorithmResult(
            status=int(p.get("status", ResponseStatus.UNKNOWN)),
            results={k: _value_to_py(v) for k, v in p.get("results", {}).items()},
            artifacts={k: _json_to_numpy(v) for k, v in p.get("artifacts", {}).items()},
            assets={k: base64.b64decode(v) for k, v in p.get("assets", {}).items()},
            compute_time_ms=int(p.get("compute_time_ms", 0)),
            algorithm_ver=p.get("algorithm_ver", ""),
            error_code=p.get("error_code", ""),
            error_message=p.get("error_message", ""),
            error_stack=p.get("error_stack", ""),
        )

    # ---- Metadata discovery ----

    def list_algorithms(self) -> list:
        """List available algorithms on the server (cached)."""
        if self._algorithm_cache is not None:
            return self._algorithm_cache
        env = self._make_envelope(MessageType.LIST_ALGORITHMS, {"category": ""})
        resp = self._channel.request(env)
        if resp.get("message_type") == MessageType.LIST_ALGORITHMS_RESP:
            self._algorithm_cache = resp.get("payload", {}).get("algorithms", [])
        else:
            self._algorithm_cache = []
        return self._algorithm_cache

    def get_algorithm_metadata(self, name: str) -> Optional[dict]:
        for a in self.list_algorithms():
            if a.get("name") == name:
                return a
        return None

    # ---- Health & lifecycle ----

    def check_health(self) -> bool:
        """Check if MATLAB Server is reachable and healthy."""
        try:
            env = self._make_envelope(MessageType.HEALTH_CHECK, {"client_version": SERVER_APP_VERSION})
            resp = self._channel.request(env)
            if resp.get("message_type") == MessageType.HEALTH_STATUS:
                state = resp.get("payload", {}).get("state", 2)
                return state in (0, 1)  # OK or DEGRADED
        except Exception as e:
            logger.debug("health check failed: %s", e)
        return False

    def get_health_status(self) -> dict:
        env = self._make_envelope(MessageType.HEALTH_CHECK, {"client_version": SERVER_APP_VERSION})
        resp = self._channel.request(env)
        return resp.get("payload", {})

    def heartbeat(self) -> dict:
        env = self._make_envelope(MessageType.HEARTBEAT, {"request_id": str(uuid.uuid4()), "client_ts_ms": int(time.time()*1000)})
        resp = self._channel.request(env)
        return resp.get("payload", {})

    def shutdown_server(self, reason: str = "client", grace_ms: int = 5000) -> dict:
        env = self._make_envelope(MessageType.SHUTDOWN_REQUEST, {"reason": reason, "grace_period_ms": grace_ms})
        resp = self._channel.request(env)
        self._channel.close()
        return resp.get("payload", {})

    # ---- IEngine methods (business-specific wrappers) ----

    def plan_path(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        params: ProcessParams,
        is_additive: bool = False,
    ):
        """Generate repair waypoints by calling MATLAB path_planning.* .

        Maps the business request to a MATLAB algorithm call. The actual
        algorithm invoked depends on server-side registration; by default
        this targets 'workflow.path_planning' (a server-side orchestrator
        that runs model_process → layer_slice → generate_path).
        """
        xyz = point_cloud.xyz
        mask = defect_region.mask
        algo_params = {
            "layer_height_mm": params.layer_height_mm,
            "scanning_angle_deg": params.scanning_angle_deg,
            "scanning_step_mm": params.scanning_step_mm,
            "buffer_additive_mm": params.buffer_additive_mm,
            "buffer_repairing_mm": params.buffer_repairing_mm,
            "num_layers": params.num_layers,
            "is_additive": is_additive,
        }
        algo_inputs = {
            "point_cloud": xyz,
            "defect_mask": mask.astype(np.float32),
        }
        result = self.execute(
            "workflow.path_planning",
            params=algo_params,
            inputs=algo_inputs,
            timeout_ms=60000,
        )
        result.raise_for_error()
        waypoints = result.artifacts.get("waypoints")
        if waypoints is None:
            raise AlgorithmEngineError("path_planning returned no waypoints")
        yield waypoints

    def predict_morphology(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        waypoints: np.ndarray,
        params: ProcessParams,
    ):
        """Predict deposition morphology by calling MATLAB morphology.*."""
        algo_params = {
            "particle_velocity_ms": params.particle_velocity_ms,
            "critical_velocity_ms": params.critical_velocity_ms,
            "nozzle_diameter_mm": params.nozzle_diameter_mm,
            "num_layers": params.num_layers,
        }
        algo_inputs = {
            "point_cloud": point_cloud.xyz,
            "defect_mask": defect_region.mask.astype(np.float32),
            "waypoints": waypoints,
        }
        result = self.execute(
            "workflow.morphology_prediction",
            params=algo_params,
            inputs=algo_inputs,
            timeout_ms=120000,
        )
        result.raise_for_error()
        predicted = result.artifacts.get("predicted_cloud")
        if predicted is None:
            raise AlgorithmEngineError("morphology returned no predicted cloud")
        yield predicted

    # ---- Cleanup ----

    def close(self) -> None:
        self._channel.close()

    # ---- Internal helpers ----

    @staticmethod
    def _make_envelope(msg_type: str, payload: dict) -> dict:
        return {
            "request_id": str(uuid.uuid4()),
            "timestamp_ms": int(time.time() * 1000),
            "message_type": msg_type,
            "protocol_ver": PROTOCOL_VERSION,
            "payload": payload,
        }
