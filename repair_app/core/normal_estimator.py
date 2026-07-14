"""
normal_estimator.py — 点云法向量估计

基于局部邻域 PCA (SVD) 的法向量估计算法，从 MainWindow._est_normals 提取。
当输入点云不含法向量时，用于自动估计曲面法向量。
"""

from __future__ import annotations
import numpy as np


def estimate_normals(xyz: np.ndarray, k: int = 30) -> np.ndarray:
    """基于局部邻域 PCA 估计点云法向量。

    对每个点取 k 近邻，计算协方差矩阵的最小特征值对应的特征向量作为法向量。
    法向量方向统一朝上（z 分量为正）。

    Args:
        xyz: (N, 3) 点云坐标数组。
        k: 近邻数量，默认 30。

    Returns:
        (N, 3) 法向量数组，模长 ≈ 1.0。
    """
    from scipy.spatial import KDTree

    n_points = len(xyz)
    if n_points == 0:
        return np.zeros((0, 3), dtype=np.float32)
    if n_points < 3:
        # 点数不足 3 时无法进行 SVD，返回朝上的默认法向量
        return np.tile([0.0, 0.0, 1.0], (n_points, 1)).astype(np.float32)

    tree = KDTree(xyz)
    normals = np.zeros_like(xyz, dtype=np.float32)
    actual_k = min(k, n_points)

    for i in range(n_points):
        _, idx = tree.query(xyz[i], k=actual_k)
        neighbors = xyz[idx]
        centroid = neighbors.mean(axis=0)
        centered = neighbors - centroid
        # SVD: 最小特征值对应的右奇异向量即为法向量
        _, _, vh = np.linalg.svd(centered.T @ centered)
        normal = vh[2]
        # 统一法向量方向朝上
        if normal[2] < 0:
            normal = -normal
        normals[i] = normal

    return normals
