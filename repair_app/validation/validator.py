"""Unified validation framework — abstract validators and result types.

Provides a common interface for all validation operations:
- PointCloudValidator: compare point clouds (Python vs MATLAB)
- WaypointValidator: compare path planning results
- MorphologyValidator: compare morphology predictions

Each validator produces a ValidationResult with pass/fail, metrics, and details.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any
import json
import time

import numpy as np

from repair_app.validation.metrics import (
    compute_rmse,
    compute_chamfer_distance,
    compute_hausdorff_distance,
    compute_iou_3d,
    compute_waypoint_deviation,
)


class ComparisonMetric(Enum):
    """Available comparison metrics."""
    RMSE = "rmse"
    CHAMFER = "chamfer"
    HAUSDORFF = "hausdorff"
    IOU_3D = "iou_3d"
    WAYPOINT_DEVIATION = "waypoint_deviation"
    MAX_Z_DIFF = "max_z_diff"
    MEAN_Z_DIFF = "mean_z_diff"


@dataclass
class ValidationResult:
    """Result of a single validation comparison.

    Attributes:
        name: Human-readable test name.
        passed: Whether the comparison passed all thresholds.
        metrics: Dict of metric_name → value.
        thresholds: Dict of metric_name → threshold that was checked.
        details: Additional diagnostic information.
        duration_s: Time taken for the comparison.
        reference_source: Source of reference data (e.g. "MATLAB R2024a").
        test_source: Source of test data (e.g. "Python v0.11.0").
    """
    name: str
    passed: bool
    metrics: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    reference_source: str = ""
    test_source: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "details": self.details,
            "duration_s": self.duration_s,
            "reference_source": self.reference_source,
            "test_source": self.test_source,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.name}"]
        for k, v in self.metrics.items():
            thresh = self.thresholds.get(k)
            thresh_str = f" (threshold: {thresh})" if thresh is not None else ""
            lines.append(f"  {k}: {v:.6f}{thresh_str}")
        return "\n".join(lines)


class PointCloudValidator:
    """Validate point cloud consistency between two sources.

    Compares Python-generated point clouds against MATLAB-generated
    reference point clouds.
    """

    def __init__(
        self,
        reference_source: str = "MATLAB",
        test_source: str = "Python",
    ) -> None:
        self._ref_source = reference_source
        self._test_source = test_source

    def compare(
        self,
        name: str,
        py_cloud: np.ndarray,
        matlab_cloud: np.ndarray,
        chamfer_threshold: float = 5.0,
        hausdorff_threshold: float = 15.0,
    ) -> ValidationResult:
        """Compare two point clouds.

        Args:
            name: Test name.
            py_cloud: (N, 3) Python point cloud.
            matlab_cloud: (M, 3) MATLAB reference point cloud.
            chamfer_threshold: Max acceptable chamfer distance (mm).
            hausdorff_threshold: Max acceptable Hausdorff distance (mm, 95th percentile).

        Returns:
            ValidationResult with pass/fail and metrics.
        """
        t0 = time.perf_counter()
        metrics = {}
        thresholds = {
            "chamfer": chamfer_threshold,
            "hausdorff_95": hausdorff_threshold,
        }

        try:
            metrics["chamfer"] = compute_chamfer_distance(py_cloud, matlab_cloud)
            metrics["hausdorff_95"] = compute_hausdorff_distance(py_cloud, matlab_cloud, percentile=95)
            metrics["rmse_z"] = float(np.sqrt(np.mean(
                (np.mean(py_cloud[:, 2]) - np.mean(matlab_cloud[:, 2])) ** 2
            )))
            metrics["iou_3d"] = compute_iou_3d(py_cloud, matlab_cloud)
        except Exception as e:
            return ValidationResult(
                name=name, passed=False, metrics=metrics,
                thresholds=thresholds,
                details={"error": str(e)},
                reference_source=self._ref_source,
                test_source=self._test_source,
            )

        passed = (
            metrics["chamfer"] <= chamfer_threshold
            and metrics["hausdorff_95"] <= hausdorff_threshold
        )
        duration = time.perf_counter() - t0

        return ValidationResult(
            name=name, passed=passed,
            metrics=metrics, thresholds=thresholds,
            details={
                "py_points": len(py_cloud),
                "matlab_points": len(matlab_cloud),
            },
            duration_s=duration,
            reference_source=self._ref_source,
            test_source=self._test_source,
        )


class WaypointValidator:
    """Validate path planning results between two sources."""

    def __init__(
        self,
        reference_source: str = "MATLAB",
        test_source: str = "Python",
    ) -> None:
        self._ref_source = reference_source
        self._test_source = test_source

    def compare(
        self,
        name: str,
        py_waypoints: np.ndarray,
        matlab_waypoints: np.ndarray,
        deviation_threshold: float = 5.0,
        coverage_threshold: float = 0.8,
    ) -> ValidationResult:
        """Compare two waypoint sets.

        Args:
            name: Test name.
            py_waypoints: (N, 3) Python waypoints.
            matlab_waypoints: (M, 3) MATLAB reference waypoints.
            deviation_threshold: Max acceptable mean deviation (mm).
            coverage_threshold: Min acceptable coverage ratio.

        Returns:
            ValidationResult.
        """
        t0 = time.perf_counter()
        metrics = {}
        thresholds = {
            "mean_deviation": deviation_threshold,
            "coverage": coverage_threshold,
        }

        try:
            dev = compute_waypoint_deviation(py_waypoints, matlab_waypoints)
            metrics.update(dev)
            metrics["wp_count_ratio"] = (
                len(py_waypoints) / max(len(matlab_waypoints), 1)
            )
        except Exception as e:
            return ValidationResult(
                name=name, passed=False,
                thresholds=thresholds,
                details={"error": str(e)},
                reference_source=self._ref_source,
                test_source=self._test_source,
            )

        passed = (
            metrics.get("mean_deviation", float("inf")) <= deviation_threshold
            and metrics.get("coverage", 0.0) >= coverage_threshold
        )
        duration = time.perf_counter() - t0

        return ValidationResult(
            name=name, passed=passed,
            metrics=metrics, thresholds=thresholds,
            details={
                "py_waypoints": len(py_waypoints),
                "matlab_waypoints": len(matlab_waypoints),
            },
            duration_s=duration,
            reference_source=self._ref_source,
            test_source=self._test_source,
        )


class MorphologyValidator:
    """Validate morphology prediction results between two sources."""

    def __init__(
        self,
        reference_source: str = "MATLAB",
        test_source: str = "Python",
    ) -> None:
        self._ref_source = reference_source
        self._test_source = test_source

    def compare(
        self,
        name: str,
        py_morph: np.ndarray,
        matlab_morph: np.ndarray,
        chamfer_threshold: float = 5.0,
        z_threshold: float = 3.0,
    ) -> ValidationResult:
        """Compare morphology predictions.

        Args:
            name: Test name.
            py_morph: (N, 3) Python morphology result.
            matlab_morph: (M, 3) MATLAB reference morphology.
            chamfer_threshold: Max acceptable chamfer distance (mm).
            z_threshold: Max acceptable mean Z difference (mm).

        Returns:
            ValidationResult.
        """
        t0 = time.perf_counter()
        metrics = {}
        thresholds = {
            "chamfer": chamfer_threshold,
            "mean_z_diff": z_threshold,
        }

        try:
            metrics["chamfer"] = compute_chamfer_distance(py_morph, matlab_morph)
            metrics["hausdorff_95"] = compute_hausdorff_distance(
                py_morph, matlab_morph, percentile=95
            )
            metrics["mean_z_diff"] = float(np.abs(
                np.mean(py_morph[:, 2]) - np.mean(matlab_morph[:, 2])
            ))
            metrics["max_z_diff"] = float(np.abs(
                np.max(py_morph[:, 2]) - np.max(matlab_morph[:, 2])
            ))
            metrics["iou_3d"] = compute_iou_3d(py_morph, matlab_morph)
        except Exception as e:
            return ValidationResult(
                name=name, passed=False,
                thresholds=thresholds,
                details={"error": str(e)},
                reference_source=self._ref_source,
                test_source=self._test_source,
            )

        passed = (
            metrics["chamfer"] <= chamfer_threshold
            and metrics["mean_z_diff"] <= z_threshold
        )
        duration = time.perf_counter() - t0

        return ValidationResult(
            name=name, passed=passed,
            metrics=metrics, thresholds=thresholds,
            details={
                "py_points": len(py_morph),
                "matlab_points": len(matlab_morph),
            },
            duration_s=duration,
            reference_source=self._ref_source,
            test_source=self._test_source,
        )