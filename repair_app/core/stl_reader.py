"""
stl_reader.py — STL 文件读取（二进制/ASCII）
基于路径规划/read_stl_file.m 翻译
"""

from __future__ import annotations
import os
import struct
import numpy as np


def read_stl_file(filepath: str) -> np.ndarray:
    """读取 STL 文件，返回 triangles N×12 矩阵。

    输出格式: [x1, y1, z1, x2, y2, z2, x3, y3, z3, nx, ny, nz]
    """
    with open(filepath, "rb") as f:
        header = f.read(80)
        facet_count_bytes = f.read(4)
        facet_count = struct.unpack("<I", facet_count_bytes)[0]

    file_size = os.path.getsize(filepath)
    expected_binary = facet_count * 50 + 84

    if file_size == expected_binary:
        return _read_binary(filepath, facet_count)
    else:
        return _read_ascii(filepath)


def _read_binary(filepath: str, facet_count: int) -> np.ndarray:
    """二进制 STL 向量化读取（numpy 批量解析，大文件性能优化）。"""
    dtype = np.dtype([
        ('normal', '<f4', 3),
        ('v1', '<f4', 3),
        ('v2', '<f4', 3),
        ('v3', '<f4', 3),
        ('attr', '<u2'),
    ])
    with open(filepath, "rb") as f:
        f.seek(84)
        data = np.frombuffer(f.read(facet_count * 50), dtype=dtype)
    # 拼接为 N×12: [x1,y1,z1, x2,y2,z2, x3,y3,z3, nx,ny,nz]
    triangles = np.column_stack([
        data['v1'], data['v2'], data['v3'], data['normal'],
    ]).astype(np.float32)
    return triangles


def _read_ascii(filepath: str) -> np.ndarray:
    triangles = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("facet normal"):
            parts = line.split()
            nx, ny, nz = float(parts[2]), float(parts[3]), float(parts[4])
            i += 1
            if i < len(lines) and "outer loop" in lines[i]:
                i += 1
                v1 = _parse_vertex(lines[i]); i += 1
                v2 = _parse_vertex(lines[i]); i += 1
                v3 = _parse_vertex(lines[i]); i += 1
                triangles.append([*v1, *v2, *v3, nx, ny, nz])
        i += 1

    return np.array(triangles, dtype=np.float32)


def _parse_vertex(line: str):
    parts = line.strip().split()
    return [float(parts[1]), float(parts[2]), float(parts[3])]
