"""test_stl_security.py — STL 安全验证测试。

测试 STL 文件读取的安全加固，包括：
  - 空文件
  - 仅头部文件
  - 二进制 STL 三角形计数不匹配
  - ASCII STL 缺少 solid/endsolid
  - NaN 顶点
  - Inf 顶点
  - 零法线
  - 极端大的三角形计数
  - 截断的二进制 STL
"""

from __future__ import annotations

import os
import struct
import tempfile

import numpy as np
import pytest

from repair_app.core.stl_reader import (
    STLValidationError,
    read_stl_file,
    _BINARY_HEADER_SIZE,
    _BYTES_PER_TRIANGLE,
)


# ============================================================
# 辅助函数
# ============================================================

def _make_binary_stl(
    facet_count: int,
    triangles_data: list[tuple] | None = None,
    header: bytes | None = None,
    truncate_bytes: int = 0,
) -> bytes:
    """构造二进制 STL 文件内容。

    Args:
        facet_count: 三角形数量（写入 header）
        triangles_data: 三角形数据列表，每个元素为 (nx,ny,nz, v1x,v1y,v1z, v2x,v2y,v2z, v3x,v3y,v3z)
        header: 自定义 80 字节头部（默认全零）
        truncate_bytes: 截断末尾的字节数（模拟截断文件）
    """
    if header is None:
        header = b'\x00' * 80
    data = header + struct.pack('<I', facet_count)

    if triangles_data is not None:
        for tri in triangles_data:
            (nx, ny, nz, v1x, v1y, v1z, v2x, v2y, v2z, v3x, v3y, v3z) = tri
            data += struct.pack('<3f', nx, ny, nz)
            data += struct.pack('<3f', v1x, v1y, v1z)
            data += struct.pack('<3f', v2x, v2y, v2z)
            data += struct.pack('<3f', v3x, v3y, v3z)
            data += struct.pack('<H', 0)
    else:
        # 填充默认三角形数据
        for _ in range(facet_count):
            data += struct.pack('<3f', 0.0, 0.0, 1.0)   # normal
            data += struct.pack('<3f', 0.0, 0.0, 0.0)   # v1
            data += struct.pack('<3f', 1.0, 0.0, 0.0)   # v2
            data += struct.pack('<3f', 0.0, 1.0, 0.0)   # v3
            data += struct.pack('<H', 0)

    if truncate_bytes > 0:
        data = data[:-truncate_bytes]
    return data


def _make_ascii_stl(
    triangles_data: list[tuple],
    solid_name: str = "test",
    with_endsolid: bool = True,
) -> str:
    """构造 ASCII STL 文件内容。

    Args:
        triangles_data: 三角形数据列表
        solid_name: solid 名称
        with_endsolid: 是否包含 endsolid
    """
    lines = [f"solid {solid_name}"]
    for tri in triangles_data:
        (nx, ny, nz, v1x, v1y, v1z, v2x, v2y, v2z, v3x, v3y, v3z) = tri
        lines.append(f"  facet normal {nx} {ny} {nz}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v1x} {v1y} {v1z}")
        lines.append(f"      vertex {v2x} {v2y} {v2z}")
        lines.append(f"      vertex {v3x} {v3y} {v3z}")
        lines.append("    endloop")
        lines.append("  endfacet")
    if with_endsolid:
        lines.append(f"endsolid {solid_name}")
    return "\n".join(lines)


# ============================================================
# 测试用例
# ============================================================

class TestEmptyFile:
    """空文件测试。"""

    def test_empty_file(self, tmp_path):
        filepath = tmp_path / "empty.stl"
        filepath.write_bytes(b"")
        with pytest.raises(STLValidationError, match="STL 文件为空"):
            read_stl_file(str(filepath))


class TestHeaderOnlyFile:
    """仅头部文件测试。"""

    def test_header_only_80_bytes(self, tmp_path):
        """仅 80 字节头部，无三角形计数。"""
        filepath = tmp_path / "header_only.stl"
        filepath.write_bytes(b'\x00' * 80)
        with pytest.raises(STLValidationError, match="STL 文件过小"):
            read_stl_file(str(filepath))

    def test_header_only_83_bytes(self, tmp_path):
        """83 字节（头部 + 3 字节三角形计数，不完整）。"""
        filepath = tmp_path / "header_83.stl"
        filepath.write_bytes(b'\x00' * 83)
        with pytest.raises(STLValidationError, match="STL 文件过小"):
            read_stl_file(str(filepath))


class TestWrongTriangleCount:
    """二进制 STL 三角形计数不匹配测试。"""

    def test_triangle_count_too_large_for_data(self, tmp_path):
        """头部声明 10 个三角形，但数据只有 1 个三角形的长度。"""
        data = _make_binary_stl(facet_count=10, triangles_data=None, truncate_bytes=9 * 50)
        filepath = tmp_path / "wrong_count.stl"
        filepath.write_bytes(data)
        # 文件大小不匹配二进制格式，头部非文本 → 检测为截断二进制
        with pytest.raises(STLValidationError, match="被截断"):
            read_stl_file(str(filepath))

    def test_triangle_count_zero(self, tmp_path):
        """三角形计数为 0。"""
        filepath = tmp_path / "zero_count.stl"
        data = b'\x00' * 80 + struct.pack('<I', 0)
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="STL 文件三角形数量为 0"):
            read_stl_file(str(filepath))


class TestMissingSolidEndsolid:
    """ASCII STL 缺少 solid/endsolid 测试。"""

    def test_missing_endsolid(self, tmp_path):
        """以 solid 开头但缺少 endsolid。"""
        tri = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        content = _make_ascii_stl([tri], with_endsolid=False)
        filepath = tmp_path / "missing_endsolid.stl"
        filepath.write_text(content)
        with pytest.raises(STLValidationError, match="缺少 'endsolid'"):
            read_stl_file(str(filepath))

    def test_missing_solid_and_endsolid(self, tmp_path):
        """完全没有 solid/endsolid，但有有效 facet 块。"""
        tri = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        content = _make_ascii_stl([tri])
        # 去掉 solid 和 endsolid 行
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("solid") and not l.strip().startswith("endsolid")]
        filepath = tmp_path / "no_solid.stl"
        filepath.write_text("\n".join(lines))
        # 没有 solid 开头，应该正常解析
        result = read_stl_file(str(filepath))
        assert result.shape == (1, 12)


class TestNaNVertices:
    """NaN 顶点测试。"""

    def test_nan_in_vertex(self, tmp_path):
        """二进制 STL 中顶点包含 NaN。"""
        tri = (0.0, 0.0, 1.0, float('nan'), 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "nan_vertex.stl"
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="NaN"):
            read_stl_file(str(filepath))

    def test_nan_in_normal(self, tmp_path):
        """二进制 STL 中法线包含 NaN。"""
        tri = (float('nan'), 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "nan_normal.stl"
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="NaN"):
            read_stl_file(str(filepath))

    def test_nan_in_ascii_vertex(self, tmp_path):
        """ASCII STL 中顶点包含 NaN。"""
        tri = (0.0, 0.0, 1.0, float('nan'), 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        content = _make_ascii_stl([tri])
        filepath = tmp_path / "nan_ascii.stl"
        filepath.write_text(content)
        with pytest.raises(STLValidationError, match="NaN"):
            read_stl_file(str(filepath))


class TestInfVertices:
    """Inf 顶点测试。"""

    def test_inf_in_vertex(self, tmp_path):
        """二进制 STL 中顶点包含 Inf。"""
        tri = (0.0, 0.0, 1.0, float('inf'), 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "inf_vertex.stl"
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="Inf"):
            read_stl_file(str(filepath))

    def test_neg_inf_in_vertex(self, tmp_path):
        """二进制 STL 中顶点包含 -Inf。"""
        tri = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, float('-inf'), 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "neg_inf_vertex.stl"
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="Inf"):
            read_stl_file(str(filepath))


class TestZeroNormals:
    """零法线测试。"""

    def test_zero_normal(self, tmp_path):
        """二进制 STL 中法线为零向量。"""
        tri = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "zero_normal.stl"
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="零长度法线"):
            read_stl_file(str(filepath))

    def test_zero_normal_ascii(self, tmp_path):
        """ASCII STL 中法线为零向量。"""
        tri = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        content = _make_ascii_stl([tri])
        filepath = tmp_path / "zero_normal_ascii.stl"
        filepath.write_text(content)
        with pytest.raises(STLValidationError, match="零长度法线"):
            read_stl_file(str(filepath))


class TestExtremeTriangleCount:
    """极端三角形计数测试。"""

    def test_max_uint32_triangle_count(self, tmp_path):
        """头部声明 0xFFFFFFFF 个三角形。"""
        filepath = tmp_path / "max_count.stl"
        data = b'\x00' * 80 + struct.pack('<I', 0xFFFFFFFF)
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="三角形数量过多"):
            read_stl_file(str(filepath))

    def test_ten_million_plus_one(self, tmp_path):
        """刚好超过 1000 万限制。"""
        filepath = tmp_path / "over_limit.stl"
        data = b'\x00' * 80 + struct.pack('<I', 10_000_001)
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match="三角形数量过多"):
            read_stl_file(str(filepath))


class TestTruncatedBinarySTL:
    """截断的二进制 STL 测试。"""

    def test_truncated_mid_triangle(self, tmp_path):
        """二进制 STL 在一个三角形中间被截断。"""
        # 声明 2 个三角形，但只提供 1 个完整三角形 + 部分数据
        full_data = _make_binary_stl(facet_count=2)
        # 截断到只包含 1 个三角形 + 部分
        truncated = full_data[:(_BINARY_HEADER_SIZE + _BYTES_PER_TRIANGLE + 20)]
        filepath = tmp_path / "truncated.stl"
        filepath.write_bytes(truncated)
        with pytest.raises(STLValidationError, match=r"被截断"):
            read_stl_file(str(filepath))

    def test_truncated_after_header(self, tmp_path):
        """二进制 STL 在头部后立即截断。"""
        filepath = tmp_path / "truncated_after_header.stl"
        data = b'\x00' * 80 + struct.pack('<I', 5)
        filepath.write_bytes(data)
        with pytest.raises(STLValidationError, match=r"被截断"):
            read_stl_file(str(filepath))


class TestValidSTLStillWorks:
    """验证合法 STL 文件仍然可以正常读取。"""

    def test_valid_binary_stl(self, tmp_path):
        """合法二进制 STL 文件正常读取。"""
        tri = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        data = _make_binary_stl(facet_count=1, triangles_data=[tri])
        filepath = tmp_path / "valid.stl"
        filepath.write_bytes(data)
        result = read_stl_file(str(filepath))
        assert result.shape == (1, 12)
        assert np.all(np.isfinite(result))

    def test_valid_ascii_stl(self, tmp_path):
        """合法 ASCII STL 文件正常读取。"""
        tri = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        content = _make_ascii_stl([tri])
        filepath = tmp_path / "valid_ascii.stl"
        filepath.write_text(content)
        result = read_stl_file(str(filepath))
        assert result.shape == (1, 12)
        assert np.all(np.isfinite(result))

    def test_valid_multi_triangle_binary(self, tmp_path):
        """多个三角形的合法二进制 STL。"""
        tris = [
            (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 1.0, 1.0, 0.0),
        ]
        data = _make_binary_stl(facet_count=2, triangles_data=tris)
        filepath = tmp_path / "multi.stl"
        filepath.write_bytes(data)
        result = read_stl_file(str(filepath))
        assert result.shape == (2, 12)