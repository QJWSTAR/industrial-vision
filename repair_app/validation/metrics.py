"""Comparison metrics — quantitative comparison functions for validation.

Provides standard metrics for comparing point clouds, waypoints, and
morphology predictions between Python and MATLAB implementations.

All metrics use scipy.spatial.cKDTree when available, falling back to
a vectorized (but slower) pure-numpy implementation.
"""

from __future__ import annotations
from typing import Optional

import numpy as np

# Try importing scipy for KDTree acceleration
try:
    from scipy.spatial import cKDTree
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _nearest_distances(
    query: np.ndarray,
    target: np.ndarray,
    max_points: int = 50000,
) -> np.ndarray:
    """Compute nearest-neighbor distances from query to target.

    Uses KDTree if scipy is available, otherwise falls back to
    vectorized numpy (slower but no dependencies).
    """
    query = np.asarray(query, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)

    if len(query) > max_points:
        idx = np.random.default_rng(42).choice(len(query), max_points, replace=False)
        query = query[idx]

    if _HAS_SCIPY:
        tree = cKDTree(target[:, :3])
        dists, _ = tree.query(query[:, :3], k=1)
        return dists
    else:
        # Pure numpy fallback: O(N*M) but works without scipy
        dists = np.full(len(query), np.inf, dtype=np.float32)
        chunk_size = 1000
        for i in range(0, len(query), chunk_size):
            chunk = query[i:i + chunk_size, :3]
            diff = chunk[:, np.newaxis, :] - target[np.newaxis, :, :3]
            dists[i:i + chunk_size] = np.min(np.sqrt(np.sum(diff ** 2, axis=2)), axis=1)
        return dists


def compute_rmse(a: np.ndarray, b: np.ndarray, axis: Optional[int] = None) -> float:
    """Root Mean Square Error between two arrays.

    Args:
        a, b: Arrays of same shape.
        axis: Axis along which to compute. None = global.

    Returns:
        RMSE value.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"Shape mismatch: {a.shape} vs {b.shape}")
    diff = a - b
    return float(np.sqrt(np.mean(diff ** 2, axis=axis)))


def compute_chamfer_distance(
    a: np.ndarray,
    b: np.ndarray,
    max_points: int = 50000,
) -> float:
    """Chamfer distance between two point clouds.

    CD(A, B) = mean(min_dist(a→b)) + mean(min_dist(b→a))

    Args:
        a, b: (N, 3) and (M, 3) point clouds.
        max_points: Subsample to this many points for efficiency.

    Returns:
        Chamfer distance.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    if a.shape[1] < 3 or b.shape[1] < 3:
        raise ValueError(f"Expected (N,3) arrays, got {a.shape} and {b.shape}")

    dist_a2b = _nearest_distances(a, b, max_points)
    dist_b2a = _nearest_distances(b, a, max_points)
    return float(np.mean(dist_a2b) + np.mean(dist_b2a))


def compute_hausdorff_distance(
    a: np.ndarray,
    b: np.ndarray,
    percentile: float = 95.0,
    max_points: int = 50000,
) -> float:
    """Robust Hausdorff distance between two point clouds.

    Uses the specified percentile instead of max to be robust to outliers.

    Args:
        a, b: (N, 3) and (M, 3) point clouds.
        percentile: Use this percentile of distances (95 = 95th percentile).
        max_points: Subsample for efficiency.

    Returns:
        Hausdorff distance at the given percentile.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    dist_a2b = _nearest_distances(a, b, max_points)
    dist_b2a = _nearest_distances(b, a, max_points)

    all_dists = np.concatenate([dist_a2b, dist_b2a])
    return float(np.percentile(all_dists, percentile))


def compute_iou_3d(
    a: np.ndarray,
    b: np.ndarray,
    voxel_size: float = 1.0,
) -> float:
    """3D IoU (Intersection over Union) between two point clouds.

    Uses voxelization to approximate volume overlap.

    Args:
        a, b: (N, 3) and (M, 3) point clouds.
        voxel_size: Voxel size for discretization.

    Returns:
        IoU value in [0, 1].
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    # Compute bounding box
    all_pts = np.vstack([a[:, :3], b[:, :3]])
    min_corner = np.min(all_pts, axis=0) - voxel_size
    max_corner = np.max(all_pts, axis=0) + voxel_size

    # Voxelize
    a_vox = np.floor((a[:, :3] - min_corner) / voxel_size).astype(np.int32)
    b_vox = np.floor((b[:, :3] - min_corner) / voxel_size).astype(np.int32)

    a_set = set(tuple(v) for v in a_vox)
    b_set = set(tuple(v) for v in b_vox)

    intersection = len(a_set & b_set)
    union = len(a_set | b_set)

    return float(intersection / max(union, 1))


def compute_waypoint_deviation(
    pred: np.ndarray,
    ref: np.ndarray,
    max_dist: float = 10.0,
) -> dict:
    """Compute waypoint deviation metrics.

    For each predicted waypoint, find the nearest reference waypoint
    and compute statistics.

    Args:
        pred: (N, 3) predicted waypoints.
        ref: (M, 3) reference waypoints.

    Returns:
        Dict with 'mean_deviation', 'max_deviation', 'std_deviation',
        'outlier_count' (deviation > max_dist), 'coverage' (fraction of
        ref waypoints within max_dist of any pred).
    """
    pred = np.asarray(pred, dtype=np.float32)
    ref = np.asarray(ref, dtype=np.float32)

    if len(pred) == 0 or len(ref) == 0:
        return {
            "mean_deviation": float("inf"),
            "max_deviation": float("inf"),
            "std_deviation": float("inf"),
            "outlier_count": 0,
            "coverage": 0.0,
        }

    from scipy.spatial import cKDTree
    tree_ref = cKDTree(ref[:, :3])
    dist_p2r, _ = tree_ref.query(pred[:, :3], k=1)

    tree_pred = cKDTree(pred[:, :3])
    dist_r2p, _ = tree_pred.query(ref[:, :3], k=1)

    return {
        "mean_deviation": float(np.mean(dist_p2r)),
        "max_deviation": float(np.max(dist_p2r)),
        "std_deviation": float(np.std(dist_p2r)),
        "outlier_count": int(np.sum(dist_p2r > max_dist)),
        "coverage": float(np.mean(dist_r2p <= max_dist)),
    }