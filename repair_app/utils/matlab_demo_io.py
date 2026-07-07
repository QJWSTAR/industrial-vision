"""
matlab_demo_io.py — 轻量读取 demo 里的 MATLAB v5 数值矩阵

只覆盖当前 demo 需要的压缩/非压缩 numeric matrix，例如 pointlist.mat。
复杂 cell/string 如 velocitylist.mat 建议继续用 MATLAB 或 scipy.io.loadmat。
"""

from __future__ import annotations
import struct
import zlib
from pathlib import Path
import numpy as np


MI_MATRIX = 14
MI_COMPRESSED = 15

_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 4,
    9: 8, 12: 8, 13: 8, 16: 1,
}
_DTYPES = {
    1: "i1", 2: "u1", 3: "<i2", 4: "<u2", 5: "<i4", 6: "<u4",
    7: "<f4", 9: "<f8", 12: "<i8", 13: "<u8", 16: "u1",
}


def _read_tag(buf: bytes, offset: int) -> tuple[int, int, int, int]:
    raw = struct.unpack_from("<I", buf, offset)[0]
    small_nbytes = raw >> 16
    small_dtype = raw & 0xFFFF
    if small_nbytes and small_dtype in _SIZES and small_nbytes <= 4:
        return small_dtype, small_nbytes, offset + 4, offset + 8
    dtype, nbytes = struct.unpack_from("<II", buf, offset)
    padding = (8 - nbytes % 8) % 8
    return dtype, nbytes, offset + 8, offset + 8 + nbytes + padding


def _read_element(buf: bytes, offset: int) -> tuple[int, bytes, int]:
    dtype, nbytes, data_offset, next_offset = _read_tag(buf, offset)
    return dtype, buf[data_offset:data_offset + nbytes], next_offset


def _parse_matrix(data: bytes) -> tuple[str, np.ndarray | None]:
    dtype, nbytes, data_offset, next_offset = _read_tag(data, 0)
    if dtype == MI_MATRIX and next_offset == len(data):
        data = data[data_offset:data_offset + nbytes]

    offset = 0
    _dtype, _flags, offset = _read_element(data, offset)
    _dtype, dims_raw, offset = _read_element(data, offset)
    dims = np.frombuffer(dims_raw, dtype="<i4")
    _dtype, name_raw, offset = _read_element(data, offset)
    name = bytes(name_raw).decode("utf-8", errors="replace")
    if offset >= len(data):
        return name, None

    real_dtype, real_raw, _offset = _read_element(data, offset)
    if real_dtype not in _DTYPES:
        return name, None

    arr = np.frombuffer(real_raw, dtype=np.dtype(_DTYPES[real_dtype])).copy()
    if dims.size and arr.size == int(np.prod(dims)):
        arr = arr.reshape(tuple(dims), order="F")
    return name, arr


def load_numeric_matrices(path: str | Path) -> dict[str, np.ndarray]:
    """读取 MATLAB v5 文件中的数值矩阵。"""
    buf = Path(path).read_bytes()
    offset = 128
    result: dict[str, np.ndarray] = {}
    while offset + 8 <= len(buf):
        dtype, nbytes, data_offset, next_offset = _read_tag(buf, offset)
        payload = buf[data_offset:data_offset + nbytes]
        if dtype == MI_COMPRESSED:
            payload = zlib.decompress(payload)
        if dtype in (MI_MATRIX, MI_COMPRESSED):
            name, arr = _parse_matrix(payload)
            if arr is not None and np.issubdtype(arr.dtype, np.number):
                result[name] = arr
        offset = next_offset
    return result


def load_pointlist(path: str | Path) -> np.ndarray:
    matrices = load_numeric_matrices(path)
    if "pointlist" not in matrices:
        raise KeyError(f"{path} 中未找到 pointlist 数值矩阵")
    return matrices["pointlist"]
