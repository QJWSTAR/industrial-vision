"""
test_normal_estimator.py — 点云法向量估计 (estimate_normals) 单元测试

被测模块: repair_app/core/normal_estimator.py
被测函数: estimate_normals(xyz, k=30)

说明:
    实现基于局部邻域 PCA (SVD)，并将法向量方向统一为 "z 分量朝上"。
    因此球面点云的法向量并不全部指向球心外侧——下半球点因朝上翻转而指向内侧，
    这些测试断言与实际实现行为一致。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from repair_app.core.normal_estimator import estimate_normals


def _make_plane(n: int = 400, seed: int = 0) -> np.ndarray:
    """生成 z=0 平面上的点云。"""
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-5.0, 5.0, size=(n, 2))
    z = np.zeros((n, 1))
    return np.hstack([xy, z]).astype(np.float32)


def _make_sphere(n: int = 600, radius: float = 3.0, seed: int = 1) -> np.ndarray:
    """生成球面点云（均匀采样）。"""
    rng = np.random.default_rng(seed)
    u = rng.uniform(0.0, 1.0, n)
    v = rng.uniform(0.0, 1.0, n)
    theta = 2.0 * np.pi * u
    phi = np.arccos(2.0 * v - 1.0)
    x = radius * np.sin(phi) * np.cos(theta)
    y = radius * np.sin(phi) * np.sin(theta)
    z = radius * np.cos(phi)
    return np.stack([x, y, z], axis=1).astype(np.float32)


class TestEstimateNormalsPlane:
    """平面点云: 法向量应大致垂直于平面 (≈ +z)。"""

    def test_plane_normals_shape(self):
        xyz = _make_plane(n=200)
        normals = estimate_normals(xyz, k=12)
        assert normals.shape == (200, 3)

    def test_plane_normals_align_with_z(self):
        xyz = _make_plane(n=400)
        normals = estimate_normals(xyz, k=12)
        # 平面法向量应接近 [0, 0, 1]
        assert np.all(normals[:, 2] >= 0.0), "实现统一 z 朝上, z 分量应非负"
        assert np.mean(normals[:, 2]) > 0.95
        assert np.mean(np.abs(normals[:, 0])) < 0.1
        assert np.mean(np.abs(normals[:, 1])) < 0.1

    def test_plane_normals_unit_length(self):
        xyz = _make_plane(n=200)
        normals = estimate_normals(xyz, k=12)
        norms = np.linalg.norm(normals, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)


class TestEstimateNormalsSphere:
    """球面点云: 实现将法向量统一为 z 朝上, 故仅上半球指向外侧。"""

    def test_sphere_normals_shape_and_unit(self):
        xyz = _make_sphere(n=500)
        normals = estimate_normals(xyz, k=12)
        assert normals.shape == (500, 3)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-5)

    def test_sphere_normals_oriented_upward(self):
        xyz = _make_sphere(n=500)
        normals = estimate_normals(xyz, k=12)
        # 朝上统一方向 => z 分量非负
        assert np.all(normals[:, 2] >= 0.0)

    def test_sphere_upper_hemisphere_outward(self):
        radius = 3.0
        xyz = _make_sphere(n=800, radius=radius)
        normals = estimate_normals(xyz, k=15)
        pos_dir = xyz / np.linalg.norm(xyz, axis=1, keepdims=True)
        dots = np.sum(normals * pos_dir, axis=1)
        upper = xyz[:, 2] > 0.0
        # 上半球: 朝上方向与朝外方向一致 => 应指向外侧
        assert np.mean(dots[upper] > 0.0) > 0.95

    def test_sphere_lower_hemisphere_inward_due_to_up_orientation(self):
        """下半球: 朝外法向量 z<0 被翻转为 z>0 => 实际指向内侧 (实现的已知行为)。"""
        radius = 3.0
        xyz = _make_sphere(n=800, radius=radius)
        normals = estimate_normals(xyz, k=15)
        pos_dir = xyz / np.linalg.norm(xyz, axis=1, keepdims=True)
        dots = np.sum(normals * pos_dir, axis=1)
        lower = xyz[:, 2] < 0.0
        assert np.mean(dots[lower] < 0.0) > 0.95


class TestEstimateNormalsKBoundary:
    """k 参数边界情况。"""

    def test_k_equals_one_raises(self):
        # k=1 时邻域仅含自身, 协方差矩阵退化为 0 维, SVD 抛出 LinAlgError
        # 这是实现的已知限制 (需要 k>=2 才能进行 SVD)
        xyz = _make_plane(n=50)
        with pytest.raises(np.linalg.LinAlgError):
            estimate_normals(xyz, k=1)

    def test_k_equals_two(self):
        xyz = _make_plane(n=50)
        normals = estimate_normals(xyz, k=2)
        assert normals.shape == (50, 3)
        assert np.all(np.isfinite(normals))

    def test_k_equals_num_points(self):
        n = 60
        xyz = _make_plane(n=n)
        normals = estimate_normals(xyz, k=n)
        assert normals.shape == (n, 3)
        # 平面 => 仍朝上
        assert np.mean(normals[:, 2]) > 0.95

    def test_k_larger_than_num_points_is_clamped(self):
        n = 30
        xyz = _make_plane(n=n)
        normals = estimate_normals(xyz, k=1000)
        assert normals.shape == (n, 3)
        assert np.all(np.isfinite(normals))


class TestEstimateNormalsEdgeCases:
    """空 / 极小点云的容错。"""

    def test_empty_point_cloud(self):
        xyz = np.zeros((0, 3), dtype=np.float32)
        normals = estimate_normals(xyz, k=12)
        assert normals.shape == (0, 3)

    def test_single_point(self):
        xyz = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        normals = estimate_normals(xyz, k=12)
        assert normals.shape == (1, 3)
        # 点数 < 3 => 返回默认朝上法向量
        assert np.allclose(normals, [[0.0, 0.0, 1.0]])

    def test_two_points(self):
        xyz = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32)
        normals = estimate_normals(xyz, k=12)
        assert normals.shape == (2, 3)
        assert np.allclose(normals, [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])

    def test_returns_float32(self):
        xyz = _make_plane(n=50)
        normals = estimate_normals(xyz, k=12)
        assert normals.dtype == np.float32
