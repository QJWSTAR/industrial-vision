"""Validation service — parameter validation and feasibility checks.

Extracts validation logic from MainWindow into a reusable service,
ensuring consistent boundary checks across all entry points.
"""

from __future__ import annotations
from typing import Optional, Tuple

import numpy as np

from repair_app.domain.models import ProcessParams, DefectRegion, PointCloud
from repair_app.repository.material_repository import MaterialRepository
from repair_app.utils.config import PARAM_BOUNDS
from repair_app.utils.logger_config import warning


class ValidationService:
    """Validates process parameters, point clouds, and material constraints."""

    def __init__(self, material_repo: Optional[MaterialRepository] = None) -> None:
        self._material_repo = material_repo or MaterialRepository()

    def validate_params(self, params: ProcessParams) -> Tuple[bool, list[str]]:
        """Validate process parameters against known bounds.

        Returns:
            (is_valid, list_of_error_messages).
        """
        errors = []
        for name, (lo, hi) in PARAM_BOUNDS.items():
            if not hasattr(params, name):
                message = (
                    f"Validation schema references unknown ProcessParams field: {name}"
                )
                warning(message)
                errors.append(message)
                continue
            val = getattr(params, name)
            if val is None:
                continue
            if not (lo <= val <= hi):
                errors.append(f"{name} = {val} is out of range [{lo}, {hi}]")
        if errors:
            warning(f"Parameter validation failed: {len(errors)} error(s)")
        return len(errors) == 0, errors

    def validate_point_cloud(self, pc: PointCloud) -> Tuple[bool, str]:
        """Validate point cloud data.

        Returns:
            (is_valid, error_message).
        """
        if pc is None or pc.xyz is None or len(pc.xyz) == 0:
            return False, "Point cloud is empty or missing"
        if pc.xyz.shape[1] < 3:
            return False, f"Point cloud must have 3 columns (XYZ), got {pc.xyz.shape[1]}"
        if not np.all(np.isfinite(pc.xyz)):
            return False, "Point cloud contains NaN or Inf values"
        return True, ""

    def validate_defect_selection(
        self,
        pc: PointCloud,
        defect: DefectRegion,
    ) -> Tuple[bool, str]:
        """Validate defect region selection.

        Returns:
            (is_valid, error_message).
        """
        if defect is None:
            return False, "No defect region selected"
        if defect.is_empty:
            return False, "Defect region is empty (no points selected)"
        if len(defect.mask) != pc.point_count:
            return False, (
                f"Defect mask size ({len(defect.mask)}) "
                f"doesn't match point count ({pc.point_count})"
            )
        return True, ""

    def validate_material(self, material_code: str) -> Tuple[bool, str]:
        """Validate that the material code exists in the database.

        Returns:
            (is_valid, error_message).
        """
        if material_code not in self._material_repo.material_keys:
            return False, f"Unknown material: {material_code}"
        return True, ""
