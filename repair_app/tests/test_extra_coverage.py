"""test_extra_coverage.py — targeted coverage for validation/export/core."""
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from repair_app.core.morphology_predictor import (
    _deposit_layer_naive,
    _sparsify_waypoints,
    iter_repair_mesh_layers,
)
from repair_app.core.stl_reader import _read_ascii, _read_binary, read_stl_file
from repair_app.service.export_service import ExportService
from repair_app.validation.dataset import DatasetManager
from repair_app.validation.experiment import ExperimentManager
from repair_app.validation.result_manager import ResultManager
from repair_app.validation.validator import ComparisonMetric, MorphologyValidator


def test_dataset_list_and_versions(tmp_path) -> None:
    mgr = DatasetManager(data_dir=str(tmp_path))
    xyz = np.random.rand(20, 3).astype(np.float32)
    meta = mgr.create("ds", "v1", xyz, description="d")
    assert meta.point_count == 20
    assert mgr.list_datasets() == ["ds"]
    assert mgr.list_versions("ds") == ["v1"]
    assert mgr.get_metadata("ds", "v1").point_count == 20


def test_dataset_missing(tmp_path) -> None:
    mgr = DatasetManager(data_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        mgr.load("missing", "v1")


def test_experiment_save_load(tmp_path) -> None:
    mgr = ExperimentManager(exp_dir=str(tmp_path))
    rec = mgr.create_experiment("exp", {"x": 1})
    mgr.record_validation(rec, None)
    key = "xyz"
    data = np.eye(3, dtype=np.float32)
    mgr.record_result(rec, key, data, save=False)
    assert rec.results[key].shape == (3, 3)
    loaded = mgr.load_experiment("exp", rec.id)
    assert loaded.status == "running"


def test_result_report_markdown_and_csv(tmp_path) -> None:
    rm = ResultManager()
    md = rm.generate_report("noexperiments")
    assert md.startswith("# Validation Report")
    csv_text = rm.generate_report("noexperiments", format="csv")
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert rows and rows[0][0] == "name"


def test_validator_comparison_metric_passed_fields() -> None:
    cm = ComparisonMetric.RMSE
    # 验证：枚举值是具体字符串（不只是 str 类型）
    assert cm.value == "rmse", f"RMSE 值应为 'rmse'，实际 {cm.value}"


def test_morphology_validator_identical() -> None:
    pts = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
    res = MorphologyValidator().compare("same", pts, pts)
    assert res.passed is True


def test_export_service_toolpath_validation_and_gcode(tmp_path) -> None:
    from repair_app.core.repair_session import RepairSession
    svc = ExportService()
    session = RepairSession()
    session.waypoint.mock = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
    ok, result = svc.validate_toolpath(session)
    assert ok is True
    out = tmp_path / "out.nc"
    ok = svc.export_gcode(session, str(out))
    assert ok is True
    assert out.exists()


def test_stl_readers_direct(tmp_path) -> None:
    path = tmp_path / "min.stl"
    with open(path, "wb") as f:
        f.write(b" " * 80)
        f.write((1).to_bytes(4, "little"))
        import struct
        f.write(struct.pack("<12fH", 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0))
    arr = read_stl_file(str(path))
    assert arr.shape[1] == 12

    txt = "solid\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid\n"
    ascii_path = tmp_path / "a.stl"
    ascii_path.write_text(txt)
    ascii = _read_ascii(str(ascii_path))
    assert ascii.shape[0] >= 1


def test_iter_repair_mesh_layers_empty_mask() -> None:
    xyz = np.eye(3, dtype=np.float32)
    layers = list(iter_repair_mesh_layers(xyz, np.zeros(3, dtype=bool), xyz, n_layers=2, waypoint_sparsify_step=0.0))
    assert layers == []


def test_iter_repair_mesh_layers_nonempty() -> None:
    xyz = np.random.rand(30, 3).astype(np.float32)
    mask = np.ones(30, dtype=bool)
    wp = np.random.rand(20, 3).astype(np.float32)
    layers = list(iter_repair_mesh_layers(xyz, mask, wp, n_layers=2, waypoint_sparsify_step=0.0))
    assert len(layers) == 2
    assert layers[-1].shape == xyz.shape


def test_sparsify_waypoints_step_zero() -> None:
    wp = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
    assert np.array_equal(_sparsify_waypoints(wp, 0.0), wp)
