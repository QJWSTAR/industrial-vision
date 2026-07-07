"""File service — coordinates file I/O through Repository layer.

Provides high-level file operations: loading point clouds, saving/loading
waypoints, managing export files, etc.
"""

from __future__ import annotations
import os
from typing import Optional, Tuple

import numpy as np

from repair_app.repository.file_repository import FileRepository
from repair_app.utils.logger_config import info, warning, error as log_error


class FileService:
    """Service for file operations in the repair workflow.

    Delegates to FileRepository for raw I/O, adding validation,
    logging, and high-level coordination.
    """

    SUPPORTED_EXTENSIONS = ('.csv', '.txt', '.xyz', '.asc')

    def __init__(self, file_repo: Optional[FileRepository] = None) -> None:
        self._repo = file_repo or FileRepository()

    # ---- Point Cloud ----

    def load_point_cloud(self, file_path: str) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Load and validate a point cloud file.

        Args:
            file_path: Path to the point cloud file.

        Returns:
            (xyz, normals) tuple.

        Raises:
            ValueError: If file is not supported or cannot be parsed.
        """
        if not file_path:
            raise ValueError("No file path specified")
        # 输入验证：防止空字节注入和异常字符
        if "\x00" in file_path:
            raise ValueError("文件路径包含非法字符")
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format: '{ext}'. "
                f"Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )
        xyz, normals = self._repo.load_point_cloud(file_path)
        if len(xyz) == 0:
            raise ValueError("Point cloud is empty")
        return xyz, normals

    # ---- Waypoints ----

    def save_waypoints(
        self,
        waypoints: np.ndarray,
        velocity_list: Optional[list[str]] = None,
    ) -> bool:
        """Save waypoints to disk.

        Returns:
            True if save succeeded.
        """
        return self._repo.save_waypoints(waypoints, velocity_list)

    def load_waypoints(self) -> Optional[np.ndarray]:
        """Load previously saved waypoints.

        Returns:
            (N, 3) ndarray or None if no saved data.
        """
        return self._repo.load_waypoints()

    def has_saved_waypoints(self) -> bool:
        """Check if saved waypoints exist."""
        return self._repo.has_saved_waypoints()

    @property
    def morph_dir(self) -> str:
        return self._repo.morph_dir