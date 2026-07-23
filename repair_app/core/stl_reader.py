"""
stl_reader.py — STL 文件读取（二进制/ASCII）
基于路径规划/read_stl_file.m 翻译
"""

from __future__ import annotations
import os
import struct
import numpy as np

# ---------------------------------------------------------------------------
# 安全常量
# ---------------------------------------------------------------------------
_MAX_FILE_SIZE = 500 * 1024 * 1024          # 500 MB
_MAX_TRIANGLE_COUNT = 10_000_000            # 10 million
_BYTES_PER_TRIANGLE = 50                    # 3 vertices * 3 coords * 4 bytes + normal
_BINARY_HEADER_SIZE = 84                    # 80 bytes header + 4 bytes facet count


class STLValidationError(Exception):
    """STL 文件安全验证异常。"""


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def read_stl_file(filepath: str) -> np.ndarray:
    """读取 STL 文件，返回 triangles N×12 矩阵。

    输出格式: [x1, y1, z1, x2, y2, z2, x3, y3, z3, nx, ny, nz]
    """
    # ---- 文件大小检查 ----
    file_size = os.path.getsize(filepath)
    if file_size > _MAX_FILE_SIZE:
        raise STLValidationError(
            f"STL 文件过大: {file_size} bytes，超过限制 {_MAX_FILE_SIZE} bytes"
        )
    if file_size == 0:
        raise STLValidationError("STL 文件为空")

    # ---- 读取文件头部，判断 ASCII / 二进制 ----
    with open(filepath, "rb") as f:
        header = f.read(80)

    # ASCII STL 以 "solid" 开头
    if header.startswith(b"solid"):
        return _read_ascii(filepath)

    # ---- 二进制 STL 路径 ----
    if file_size < _BINARY_HEADER_SIZE:
        raise STLValidationError(
            f"STL 文件过小: {file_size} bytes，至少需要 {_BINARY_HEADER_SIZE} bytes"
        )
    if len(header) < 80:
        raise STLValidationError("STL 文件头部不完整（不足 80 字节）")

    with open(filepath, "rb") as f:
        f.seek(80)
        facet_count_bytes = f.read(4)
        if len(facet_count_bytes) < 4:
            raise STLValidationError("STL 文件三角形计数不完整（不足 4 字节）")
        facet_count = struct.unpack("<I", facet_count_bytes)[0]

    expected_binary = facet_count * _BYTES_PER_TRIANGLE + _BINARY_HEADER_SIZE

    if file_size == expected_binary:
        # 精确匹配二进制格式 —— 执行安全验证
        if facet_count > _MAX_TRIANGLE_COUNT:
            raise STLValidationError(
                f"STL 三角形数量过多: {facet_count}，超过限制 {_MAX_TRIANGLE_COUNT}"
            )
        if facet_count == 0:
            raise STLValidationError("STL 文件三角形数量为 0")
        _check_allocation(facet_count)
        return _read_binary(filepath, facet_count, file_size)
    elif facet_count > _MAX_TRIANGLE_COUNT and not _looks_like_text(header):
        # 二进制文件的三角形计数超过限制（即使文件大小不匹配也可能是被截断的二进制）
        raise STLValidationError(
            f"STL 三角形数量过多: {facet_count}，超过限制 {_MAX_TRIANGLE_COUNT}"
        )
    elif file_size < expected_binary and not _looks_like_text(header):
        # 文件看起来像二进制但被截断
        raise STLValidationError(
            f"二进制 STL 文件被截断: 期望 {expected_binary} bytes，"
            f"实际 {file_size} bytes"
        )
    else:
        # 文件大小不匹配二进制格式：尝试 ASCII（无 solid 头的 ASCII 文件）
        return _read_ascii(filepath)


# ---------------------------------------------------------------------------
# 二进制读取
# ---------------------------------------------------------------------------

def _read_binary(filepath: str, facet_count: int, file_size: int) -> np.ndarray:
    """二进制 STL 向量化读取（numpy 批量解析，大文件性能优化）。"""
    dtype = np.dtype([
        ('normal', '<f4', 3),
        ('v1', '<f4', 3),
        ('v2', '<f4', 3),
        ('v3', '<f4', 3),
        ('attr', '<u2'),
    ])
    data_size = facet_count * _BYTES_PER_TRIANGLE
    with open(filepath, "rb") as f:
        f.seek(_BINARY_HEADER_SIZE)
        raw = f.read(data_size)
        if len(raw) < data_size:
            raise STLValidationError(
                f"二进制 STL 文件被截断: 期望 {data_size} bytes，实际 {len(raw)} bytes"
            )
        data = np.frombuffer(raw, dtype=dtype)

    _validate_triangles(data['v1'], data['v2'], data['v3'], data['normal'])
    # 拼接为 N×12: [x1,y1,z1, x2,y2,z2, x3,y3,z3, nx,ny,nz]
    triangles = np.column_stack([
        data['v1'], data['v2'], data['v3'], data['normal'],
    ]).astype(np.float32)
    return triangles


# ---------------------------------------------------------------------------
# ASCII 读取
# ---------------------------------------------------------------------------

def _read_ascii(filepath: str) -> np.ndarray:
    triangles = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # ---- solid/endsolid 一致性检查 ----
    if lines:
        first_line = lines[0].strip().lower()
        if first_line.startswith("solid"):
            has_endsolid = any(
                line.strip().lower().startswith("endsolid") for line in lines
            )
            if not has_endsolid:
                raise STLValidationError(
                    "ASCII STL 文件以 'solid' 开头但缺少 'endsolid'"
                )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("facet normal"):
            parts = line.split()
            if len(parts) < 5:
                raise STLValidationError(
                    f"ASCII STL facet normal 格式无效: {line!r}"
                )
            try:
                nx, ny, nz = float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                raise STLValidationError(
                    f"ASCII STL 法线值解析失败: {line!r}"
                )
            i += 1
            if i >= len(lines) or "outer loop" not in lines[i]:
                raise STLValidationError(
                    f"ASCII STL facet 缺少 outer loop（第 {i} 行附近）"
                )
            i += 1
            # 读取三个顶点
            v1 = _parse_vertex(lines[i]); i += 1
            v2 = _parse_vertex(lines[i]); i += 1
            v3 = _parse_vertex(lines[i]); i += 1
            if i >= len(lines) or "endloop" not in lines[i]:
                raise STLValidationError(
                    f"ASCII STL facet 缺少 endloop（第 {i} 行附近）"
                )
            triangles.append([*v1, *v2, *v3, nx, ny, nz])
        i += 1

    if len(triangles) == 0:
        raise STLValidationError("ASCII STL 文件中未找到任何三角形")

    result = np.array(triangles, dtype=np.float32)
    _validate_triangles(
        result[:, 0:3], result[:, 3:6], result[:, 6:9], result[:, 9:12]
    )
    return result


def _parse_vertex(line: str):
    parts = line.strip().split()
    if len(parts) < 4 or parts[0] != "vertex":
        raise STLValidationError(
            f"ASCII STL vertex 行格式无效: {line!r}"
        )
    try:
        return [float(parts[1]), float(parts[2]), float(parts[3])]
    except ValueError:
        raise STLValidationError(
            f"ASCII STL 顶点坐标解析失败: {line!r}"
        )


# ---------------------------------------------------------------------------
# 验证辅助函数
# ---------------------------------------------------------------------------

def _looks_like_text(data: bytes) -> bool:
    """判断二进制数据是否看起来像文本（可打印 ASCII 占比 > 80%）。"""
    if len(data) == 0:
        return False
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
    return printable / len(data) > 0.8


def _check_allocation(facet_count: int) -> None:
    """检查三角形数量对应的内存分配是否在合理范围内。"""
    estimated_bytes = facet_count * _BYTES_PER_TRIANGLE
    if estimated_bytes > _MAX_FILE_SIZE:
        raise STLValidationError(
            f"STL 三角形所需内存过大: ~{estimated_bytes} bytes "
            f"({facet_count} 个三角形)，超过限制"
        )


def _validate_triangles(
    v1: np.ndarray,
    v2: np.ndarray,
    v3: np.ndarray,
    normals: np.ndarray,
) -> None:
    """验证三角形顶点坐标与法线。"""
    # ---- NaN/Inf 检查 ----
    all_vertices = np.concatenate([v1, v2, v3])
    if not np.all(np.isfinite(all_vertices)):
        nan_count = int(np.sum(np.isnan(all_vertices)))
        inf_count = int(np.sum(np.isinf(all_vertices)))
        raise STLValidationError(
            f"STL 顶点坐标包含非法值: {nan_count} 个 NaN, {inf_count} 个 Inf"
        )

    if not np.all(np.isfinite(normals)):
        nan_count = int(np.sum(np.isnan(normals)))
        inf_count = int(np.sum(np.isinf(normals)))
        raise STLValidationError(
            f"STL 法线包含非法值: {nan_count} 个 NaN, {inf_count} 个 Inf"
        )

    # ---- 零法线检查 ----
    normal_magnitudes = np.linalg.norm(normals, axis=1)
    zero_normals = normal_magnitudes == 0.0
    if np.any(zero_normals):
        count = int(np.sum(zero_normals))
        raise STLValidationError(
            f"STL 包含 {count} 个零长度法线"
        )