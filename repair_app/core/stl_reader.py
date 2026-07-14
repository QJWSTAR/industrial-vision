"""
stl_reader.py — STL 文件读取（二进制/ASCII）
基于路径规划/read_stl_file.m 翻译
"""

from __future__ import annotations
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
    triangles = np.zeros((facet_count, 12), dtype=np.float32)
    with open(filepath, "rb") as f:
        f.seek(84)
        for i in range(facet_count):
            data = struct.unpack("<12fH", f.read(50))
            nx, ny, nz = data[0], data[1], data[2]
            x1, y1, z1 = data[3], data[4], data[5]
            x2, y2, z2 = data[6], data[7], data[8]
            x3, y3, z3 = data[9], data[10], data[11]
            triangles[i] = [x1, y1, z1, x2, y2, z2, x3, y3, z3, nx, ny, nz]
    return triangles


def _read_ascii(filepath: str) -> np.ndarray:
    triangles = []
    with open(filepath, "r") as f:
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


import os
