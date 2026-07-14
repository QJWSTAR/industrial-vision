"""[DEPRECATED] Serialization helpers for protocol v3.0.

.. deprecated::
    These helpers serialize the v3.0 generic AlgorithmRequest/Response
    messages (JSON/TCP/port 5570), which have been SUPERSEDED by the
    production Protobuf v2.1 path (repair_protocol.proto over ZeroMQ,
    port 5555). The production serializer lives in
    ``repair_app.bridge.communication.serializer`` and
    ``repair_app.communication.repair_serialization``. This module is
    retained only for backward compatibility and the mock-server test
    suite. See docs/COMMUNICATION.md.

Original description (for historical reference):
    Provides conversions between numpy arrays and Tensor messages,
    and between Python scalars and Value messages.
"""
from __future__ import annotations

import struct
from typing import Any

import numpy as np

from . import Tensor, Value


# ============================================================
# Tensor <-> numpy
# ============================================================

_DTYPE_MAP = {
    np.dtype(np.float32): Tensor.F32,
    np.dtype(np.float64): Tensor.F64,
    np.dtype(np.int32):   Tensor.I32,
    np.dtype(np.int64):   Tensor.I64,
    np.dtype(np.uint8):   Tensor.U8,
}

_REVERSE_DTYPE = {
    Tensor.F32: np.float32,
    Tensor.F64: np.float64,
    Tensor.I32: np.int32,
    Tensor.I64: np.int64,
    Tensor.U8:  np.uint8,
}


def numpy_to_tensor(arr: np.ndarray, units: str = "") -> Tensor:
    """Convert a numpy array to a Tensor message (row-major)."""
    arr = np.ascontiguousarray(arr)
    dt = arr.dtype
    if dt not in _DTYPE_MAP:
        # auto-promote unsupported dtypes to float64
        arr = arr.astype(np.float64)
        dt = arr.dtype
    return Tensor(
        dtype=_DTYPE_MAP[dt],
        shape=list(arr.shape),
        data=arr.tobytes(),
        units=units,
    )


def tensor_to_numpy(t: Tensor) -> np.ndarray:
    """Convert a Tensor message back to a numpy array."""
    if t.dtype not in _REVERSE_DTYPE:
        raise ValueError(f"Unsupported Tensor dtype: {t.dtype}")
    np_dtype = _REVERSE_DTYPE[t.dtype]
    arr = np.frombuffer(t.data, dtype=np_dtype)
    shape = tuple(s for s in t.shape) if t.shape else (arr.size,)
    return arr.reshape(shape)


# ============================================================
# Value <-> Python scalar
# ============================================================

def py_to_value(v: Any) -> Value:
    """Convert a Python scalar/array to a Value message."""
    if isinstance(v, bool):
        return Value(flag=v)
    if isinstance(v, (int, np.integer)):
        return Value(intval=int(v))
    if isinstance(v, (float, np.floating)):
        return Value(num=float(v))
    if isinstance(v, str):
        return Value(str=v)
    if isinstance(v, (bytes, bytearray)):
        return Value(str=v.decode("utf-8", errors="replace"))
    if isinstance(v, np.ndarray):
        return Value(tensor=numpy_to_tensor(v))
    if isinstance(v, (list, tuple)):
        return Value(tensor=numpy_to_tensor(np.array(v)))
    # fallback
    return Value(str=str(v))


def value_to_py(val: Value) -> Any:
    """Convert a Value message back to a Python object."""
    k = val.WhichOneof("kind")
    if k == "num":
        return val.num
    if k == "intval":
        return val.intval
    if k == "str":
        return val.str
    if k == "flag":
        return val.flag
    if k == "tensor":
        return tensor_to_numpy(val.tensor)
    return None


# ============================================================
# Convenience: build params/inputs maps
# ============================================================

def build_params(**kwargs: Any) -> dict:
    """Build a params dict suitable for AlgorithmRequest.params map.

    Scalars become Value messages; arrays are promoted to Tensor inside Value.
    """
    return {k: py_to_value(v) for k, v in kwargs.items()}


def build_inputs(**kwargs: np.ndarray) -> dict:
    """Build an inputs dict of Tensor messages from named numpy arrays."""
    out = {}
    for k, v in kwargs.items():
        if not isinstance(v, np.ndarray):
            v = np.array(v)
        out[k] = numpy_to_tensor(v)
    return out


def parse_params(params_map: dict) -> dict:
    """Parse an AlgorithmRequest.params map back to Python dict."""
    return {k: value_to_py(v) for k, v in params_map.items()}


def parse_inputs(inputs_map: dict) -> dict:
    """Parse an AlgorithmRequest.inputs map back to {name: np.ndarray}."""
    return {k: tensor_to_numpy(t) for k, t in inputs_map.items()}


def parse_results(results_map: dict) -> dict:
    """Parse an AlgorithmResponse.results map back to Python dict."""
    return parse_params(results_map)


def parse_artifacts(artifacts_map: dict) -> dict:
    """Parse an AlgorithmResponse.artifacts map back to {name: np.ndarray}."""
    return parse_inputs(artifacts_map)
