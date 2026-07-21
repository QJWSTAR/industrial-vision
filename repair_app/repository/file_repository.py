"""File repository — centralized file I/O for point clouds, waypoints, and exports.

This extracts file operations from MainWindow into a testable, reusable layer.

中间文件策略（V1.0）：
- 航点缓存（pointlist.npz / velocitylist.json）写入系统临时目录，不污染项目目录
- 软件退出时自动清理（通过 atexit 注册）
- 生产路径优先使用内存传递（MATLABPipeline），文件仅作降级缓存
"""

from __future__ import annotations
import atexit
import json
import os
import shutil
import tempfile
from typing import Optional, Tuple

import numpy as np

from repair_app.utils.logger_config import info, warning, error as log_error
from repair_app.utils.config import get_morph_dir


# ---- 缓存目录管理 ----
_CACHE_DIR: Optional[str] = None


def _get_cache_dir() -> str:
    """获取（或创建）专用缓存目录，软件退出时自动清理。"""
    global _CACHE_DIR
    if _CACHE_DIR is None:
        _CACHE_DIR = tempfile.mkdtemp(prefix="csam_cache_")
        atexit.register(_cleanup_cache_dir)
        info(f"缓存目录已创建: {_CACHE_DIR}")
    return _CACHE_DIR


def _cleanup_cache_dir() -> None:
    """退出时清理缓存目录。"""
    global _CACHE_DIR
    if _CACHE_DIR is not None and os.path.isdir(_CACHE_DIR):
        try:
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)
            info(f"缓存目录已清理: {_CACHE_DIR}")
        except Exception as exc:
            warning(f"清理缓存目录失败: {exc}")
    _CACHE_DIR = None


class FileRepository:
    """Handles all file I/O operations for the repair workflow.

    Responsibilities:
        - Load point cloud files (CSV, TXT, etc.)
        - Save/load waypoint data (缓存目录，退出自动清理)
    """

    def __init__(self, morph_dir: Optional[str] = None) -> None:
        # morph_dir 仅用于兼容旧调用，实际缓存写入系统临时目录
        self._morph_dir = morph_dir or get_morph_dir()
        cache = _get_cache_dir()
        self._pointlist_path = os.path.join(cache, "pointlist.npz")
        self._velocitylist_path = os.path.join(cache, "velocitylist.npz")

    # ---- Point Cloud Loading ----

    @staticmethod
    def load_point_cloud(file_path: str) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Load a point cloud from CSV/TXT file.

        Args:
            file_path: Path to the point cloud file.

        Returns:
            (xyz, normals) tuple. normals is None if file has < 6 columns.

        Raises:
            ValueError: If file cannot be parsed.
        """
        data = np.loadtxt(file_path, delimiter=',', dtype=np.float32)
        if data.ndim == 1:
            data = data.reshape(-1, 3)
        xyz = data[:, :3].astype(np.float32)
        if data.shape[1] >= 6:
            normals = data[:, 3:6].astype(np.float32)
        else:
            normals = None
        info(f"Point cloud loaded: {os.path.basename(file_path)} ({len(xyz):,} points)")
        return xyz, normals

    # ---- Waypoint Persistence ----

    def save_waypoints(
        self,
        waypoints: np.ndarray,
        velocity_list: Optional[list[str]] = None,
    ) -> bool:
        """Save waypoints and velocity list to the morph directory.

        Args:
            waypoints: (N, 3) ndarray of waypoint coordinates.
            velocity_list: List of velocity strings (e.g. ["v500", "v300"]).

        Returns:
            True if save succeeded, False otherwise.
        """
        os.makedirs(os.path.dirname(self._pointlist_path), exist_ok=True)
        try:
            np.savez(self._pointlist_path, pointlist=waypoints)
            if velocity_list is not None:
                vel_path = self._velocitylist_path.replace('.npz', '.json')
                with open(vel_path, 'w', encoding='utf-8') as f:
                    json.dump(velocity_list, f)
            info(f"已缓存航点到临时目录: pointlist.npz ({len(waypoints)} waypoints)")
            return True
        except Exception as e:
            log_error(f"Failed to save waypoints: {e}")
            return False

    def load_waypoints(self) -> Optional[np.ndarray]:
        """Load waypoints from the pointlist file.

        Returns:
            (N, 3) ndarray or None if file doesn't exist or fails to load.
        """
        if not os.path.exists(self._pointlist_path):
            return None
        try:
            data = np.load(self._pointlist_path, allow_pickle=False)
            waypoints = data["pointlist"]
            info(f"Loaded waypoints from file: {len(waypoints)} points")
            return waypoints
        except Exception as e:
            log_error(f"Failed to load waypoints: {e}")
            return None

    def has_saved_waypoints(self) -> bool:
        """Check if waypoint files exist on disk."""
        return os.path.exists(self._pointlist_path)

    @property
    def morph_dir(self) -> str:
        return self._morph_dir