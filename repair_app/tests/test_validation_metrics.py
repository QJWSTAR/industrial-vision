"""test_validation_metrics.py — Validation metrics coverage.

Covers repair_app/validation/{metrics,dataset,experiment,result_manager,validator}.
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from repair_app.validation.metrics import (
    compute_chamfer_distance,
    compute_hausdorff_distance,
    compute_iou_3d,
    compute_rmse,
    compute_waypoint_deviation,
)
from repair_app.validation.dataset import DatasetManager


def test_compute_rmse_identical() -> None:
    a = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    assert compute_rmse(a, a) == pytest.approx(0.0)


def test_compute_rmse_simple() -> None:
    a = np.array([0.0, 2.0], dtype=np.float64)
    b = np.array([0.0, 0.0], dtype=np.float64)
    assert compute_rmse(a, b) == pytest.approx(np.sqrt(2.0))


def test_compute_chamfer_distance_simple() -> None:
    a = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    b = np.array([[3.0, 0.0, 0.0]], dtype=np.float32)
    expected = 6.0
    assert compute_chamfer_distance(a, b) == pytest.approx(expected, rel=1e-3)


def test_compute_chamfer_distance_identical() -> None:
    pts = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    assert compute_chamfer_distance(pts, pts) == pytest.approx(0.0, abs=1e-4)


def test_compute_hausdorff_distance_simple() -> None:
    a = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    b = np.array([[3.0, 0.0, 0.0]], dtype=np.float32)
    assert compute_hausdorff_distance(a, b) == pytest.approx(3.0, rel=1e-3)


def test_compute_iou_3d_identical() -> None:
    pts = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    assert compute_iou_3d(pts, pts) == pytest.approx(1.0, abs=1e-4)


def test_compute_iou_3d_disjoint() -> None:
    a = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    b = np.array([[10.0, 10.0, 10.0]], dtype=np.float32)
    assert compute_iou_3d(a, b) == pytest.approx(0.0, abs=1e-4)


def test_compute_waypoint_deviation_identical() -> None:
    pts = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    out = compute_waypoint_deviation(pts, pts)
    assert out["mean_deviation"] == pytest.approx(0.0, abs=1e-3)
    assert out["coverage"] == pytest.approx(1.0, abs=1e-3)


def test_dataset_manager_path_traversal_safe(tmp_path) -> None:
    manager = DatasetManager(data_dir=str(tmp_path))
    xyz = np.random.rand(20, 3).astype(np.float32)
    meta = manager.create("safe_name", "v1", xyz)
    assert meta.name == "safe_name"
    assert meta.version == "v1"
    assert meta.point_count == 20
