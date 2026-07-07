"""Point cloud LOD (Level of Detail) — hierarchical downsampling for visualization.

Provides efficient LOD generation via grid-based downsampling, enabling
real-time rendering of large point clouds (100K+ points) by reducing
detail at distance.
"""

from __future__ import annotations
from typing import Optional

import numpy as np


class LODManager:
    """Manages multiple LOD levels for a point cloud.

    Generates pre-computed LOD levels using grid-based voxel downsampling.
    Each level halves the resolution, reducing point count by ~4x.

    Usage:
        manager = LODManager(xyz, colors, normals)
        lvl0_xyz, lvl0_colors = manager.get_level(0)  # full resolution
        lvl3_xyz, lvl3_colors = manager.get_level(3)  # 1/64 of points
    """

    def __init__(
        self,
        xyz: np.ndarray,
        colors: Optional[np.ndarray] = None,
        normals: Optional[np.ndarray] = None,
        max_levels: int = 5,
    ) -> None:
        """
        Args:
            xyz: (N, 3) point cloud coordinates.
            colors: (N, 3) or (N,) RGB colors.
            normals: (N, 3) normals.
            max_levels: Maximum number of LOD levels (0 = full res only).
        """
        self._levels: list[dict] = []
        self._max_levels = max_levels
        self._build_lods(xyz, colors, normals)

    def _build_lods(
        self,
        xyz: np.ndarray,
        colors: Optional[np.ndarray],
        normals: Optional[np.ndarray],
    ) -> None:
        """Pre-compute all LOD levels."""
        current_xyz = xyz.astype(np.float32)
        current_colors = colors.astype(np.float32) if colors is not None else None
        current_normals = normals.astype(np.float32) if normals is not None else None

        for level in range(self._max_levels):
            self._levels.append({
                "xyz": current_xyz,
                "colors": current_colors,
                "normals": current_normals,
            })
            if len(current_xyz) <= 100:
                break
            # Downsample: halve the voxel size
            voxel_size = 2.0 ** level
            current_xyz, current_colors, current_normals = _downsample(
                current_xyz, current_colors, current_normals, voxel_size,
            )

    def get_level(self, level: int) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        """Get a specific LOD level.

        Args:
            level: 0 = full resolution, higher = more downsampled.

        Returns:
            (xyz, colors, normals) tuple. colors/normals may be None.
        """
        idx = min(level, len(self._levels) - 1)
        lvl = self._levels[idx]
        return lvl["xyz"], lvl["colors"], lvl["normals"]

    def get_level_for_distance(self, distance: float, min_points: int = 1000) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        """Auto-select LOD level based on camera distance.

        Args:
            distance: Camera distance to the point cloud center.
            min_points: Minimum points to render.

        Returns:
            (xyz, colors, normals) for the appropriate LOD level.
        """
        level = min(int(distance / 10), len(self._levels) - 1)
        return self.get_level(level)

    @property
    def level_count(self) -> int:
        return len(self._levels)

    @property
    def point_counts(self) -> list[int]:
        return [len(lvl["xyz"]) for lvl in self._levels]


def _downsample(
    xyz: np.ndarray,
    colors: Optional[np.ndarray],
    normals: Optional[np.ndarray],
    voxel_size: float,
) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Grid-based voxel downsampling: average points within each voxel."""
    if voxel_size <= 0 or len(xyz) <= 1:
        return xyz, colors, normals

    # Compute voxel indices
    voxel_indices = np.floor(xyz[:, :3] / voxel_size).astype(np.int32)
    # Unique voxel key via hashing
    dims = np.max(voxel_indices, axis=0) - np.min(voxel_indices, axis=0) + 1
    keys = (
        voxel_indices[:, 0] * dims[1] * dims[2]
        + voxel_indices[:, 1] * dims[2]
        + voxel_indices[:, 2]
    )

    unique_keys, inverse = np.unique(keys, return_inverse=True)
    n_voxels = len(unique_keys)

    # Average xyz per voxel
    new_xyz = np.zeros((n_voxels, 3), dtype=np.float32)
    np.add.at(new_xyz, inverse, xyz)
    counts = np.bincount(inverse, minlength=n_voxels).reshape(-1, 1)
    new_xyz /= counts

    new_colors = None
    if colors is not None:
        new_colors = np.zeros((n_voxels, colors.shape[1]), dtype=np.float32)
        np.add.at(new_colors, inverse, colors)
        new_colors /= counts

    new_normals = None
    if normals is not None:
        new_normals = np.zeros((n_voxels, 3), dtype=np.float32)
        np.add.at(new_normals, inverse, normals)
        # Re-normalize
        norms = np.linalg.norm(new_normals, axis=1, keepdims=True)
        norms[norms < 1e-8] = 1.0
        new_normals /= norms

    return new_xyz, new_colors, new_normals