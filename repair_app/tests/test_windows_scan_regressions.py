"""Regression coverage for defects found during Windows acceptance scanning."""

from __future__ import annotations

import builtins
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_release_config_is_license_safe_by_default():
    config = json.loads(
        (PROJECT_ROOT / "config" / "app_config.json").read_text(encoding="utf-8")
    )
    assert config["developer_mode"] is False


def test_pyinstaller_spec_requires_key_and_includes_operation_control():
    spec = (PROJECT_ROOT / "repair_app.spec").read_text(encoding="utf-8")
    assert "CSAM_PUBLIC_KEY_PATH" in spec
    assert "License public key not found" in spec
    assert "'repair_app.bridge.operation_control'" in spec


def test_windows_build_chain_never_generates_production_keys():
    windows_build = (PROJECT_ROOT / "build_windows.bat").read_text(encoding="utf-8")
    release_build = (PROJECT_ROOT / "build_release.bat").read_text(encoding="utf-8")
    installer = (PROJECT_ROOT / "installer" / "setup.iss").read_text(
        encoding="utf-8"
    )
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    for script in (windows_build, release_build):
        assert "CSAM_PUBLIC_KEY_PATH" in script
        assert "license_manager keygen" not in script
    assert installer.count('Source: "{#PublicKeySource}"') == 1
    assert r"dist\config\public_key.pem" not in installer
    assert "CSAM_PUBLIC_KEY_B64" in workflow


def test_installer_detects_real_matlab_r2025b_registry_version():
    installer = (PROJECT_ROOT / "installer" / "setup.iss").read_text(
        encoding="utf-8"
    )
    assert "TryMatlabRelease('25.2', 'R2025b')" in installer
    assert "TryMatlabRelease('9.15', 'R2025b')" not in installer


def test_matlab_sources_do_not_use_nonexistent_cleanup_keyword():
    source = (PROJECT_ROOT / "path_planning" / "read_stl_file.m").read_text(
        encoding="utf-8"
    )
    assert "\n        cleanup\n" not in source
    assert "onCleanup" in source
    assert "CSAM:InvalidSTLLength" in source


def test_path_planning_sources_guard_empty_geometry():
    generate = (PROJECT_ROOT / "path_planning" / "generate_path.m").read_text(
        encoding="utf-8"
    )
    model = (PROJECT_ROOT / "path_planning" / "model_process.m").read_text(
        encoding="utf-8"
    )
    assert "flatten_layers" in generate
    assert "isempty(infill_points)" in generate
    assert "warning_guard = onCleanup" in generate
    assert "CSAM:NoSliceableTriangles" in model


def test_astar_guards_zero_distance_and_updates_existing_priority():
    source = (PROJECT_ROOT / "path_planning" / "aStarSearch.m").read_text(
        encoding="utf-8"
    )
    assert "if initialDist <= eps || ~isfinite(initialDist)" in source
    assert "openSet(neighborKey) = [" in source
    assert "if ~isempty(pathRows) && ~isequal(OriginalGoalNode, GoalNode)" in source


def test_license_iso_z_is_supported():
    from repair_app.utils.license_manager import LicenseData

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    future_z = future.replace("+00:00", "Z")
    license_data = LicenseData({"expires_at": future_z})
    assert license_data.expired is False
    assert license_data.days_remaining >= 1


def test_lod_level_zero_and_negative_indexes_are_safe():
    from repair_app.utils.lod import LODManager

    xyz = np.arange(30, dtype=np.float32).reshape(10, 3)
    colors = np.arange(10, dtype=np.float32)
    manager = LODManager(xyz, colors=colors, max_levels=0)
    level_xyz, level_colors, _ = manager.get_level(-10)
    assert manager.level_count == 1
    np.testing.assert_array_equal(level_xyz, xyz)
    np.testing.assert_array_equal(level_colors, colors)
    np.testing.assert_array_equal(manager.get_level_for_distance(-50)[0], xyz)


def test_gcode_rejects_empty_waypoints_even_without_validator():
    from repair_app.export.gcode_exporter import GCodeExporter

    with pytest.raises(ValueError, match="航点数组为空"):
        GCodeExporter(safe_z=10).export(
            np.zeros((0, 3), dtype=np.float32), validate=False
        )


def test_gcode_lead_in_out_follow_path_tangent():
    from repair_app.export.gcode_exporter import GCodeExporter

    waypoints = np.array([[10, 10, 1], [10, 20, 1], [10, 30, 1]], dtype=float)
    code = GCodeExporter(
        safe_z=20,
        lead_in_length=5,
        lead_out_length=5,
    ).export(waypoints, validate=False)
    assert "X10.000 Y5.000 Z20.000" in code
    assert "X10.000 Y35.000" in code


def test_boundary_violation_counts_unique_waypoints():
    from repair_app.export.export_validator import validate_toolpath

    waypoints = np.array([[2, 2, 2], [0.5, 0.5, 0.5]], dtype=float)
    result = validate_toolpath(
        waypoints,
        build_volume=(0, 0, 0, 1, 1, 1),
    )
    issue = next(item for item in result.issues if item.code == "OUT_OF_BOUNDS")
    assert "存在 1 个航点" in issue.message


def test_collision_validation_degrades_if_scipy_is_unavailable(monkeypatch):
    from repair_app.export.export_validator import validate_toolpath

    real_import = builtins.__import__

    def reject_scipy_spatial(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scipy.spatial":
            raise ImportError("simulated missing scipy")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_scipy_spatial)
    result = validate_toolpath(
        np.array([[0, 0, 1], [1, 1, 1]], dtype=float),
        substrate_xyz=np.array([[0, 0, 0]], dtype=float),
    )
    assert any(issue.code == "COLLISION_CHECK_SKIPPED" for issue in result.issues)


def test_robot_export_rejects_misaligned_normals():
    from repair_app.export.robot_exporter import RobotExporter

    with pytest.raises(ValueError, match="normals must have shape"):
        RobotExporter().export(
            np.zeros((2, 3), dtype=float),
            normals=np.zeros((1, 3), dtype=float),
        )


def test_abb_downward_normal_is_not_identity_rotation():
    from repair_app.export.robot_exporter import _normal_to_quaternion_abb

    assert _normal_to_quaternion_abb(np.array([0.0, 0.0, -1.0])) == (
        0.0, 1.0, 0.0, 0.0
    )


def test_morphology_explicit_repair_points_are_not_length_inferred():
    from repair_app.core.repair_session import MorphologyData

    substrate = np.zeros((100, 3), dtype=np.float32)
    repair = np.ones((2, 3), dtype=np.float32)
    morphology = MorphologyData()
    morphology.set_repair_points(substrate, repair)
    assert morphology.repair_xyz.shape == (102, 3)
    np.testing.assert_array_equal(morphology.get_repair_points(substrate), repair)


def test_morphology_legacy_composite_is_verified_before_slicing():
    from repair_app.core.repair_session import MorphologyData

    substrate = np.zeros((3, 3), dtype=np.float32)
    legacy_composite = np.vstack([substrate, np.ones((1, 3), dtype=np.float32)])
    morphology = MorphologyData(repair_xyz=legacy_composite)
    np.testing.assert_array_equal(
        morphology.get_repair_points(substrate),
        np.ones((1, 3), dtype=np.float32),
    )

    # Same/shorter length is not enough to infer concatenation.  Only an
    # actual substrate prefix is treated as a legacy composite.
    legacy_repair_only = np.full((3, 3), 2.0, dtype=np.float32)
    morphology = MorphologyData(repair_xyz=legacy_repair_only)
    np.testing.assert_array_equal(
        morphology.get_repair_points(substrate),
        legacy_repair_only,
    )


def test_workflow_failure_has_distinct_state():
    from repair_app.ui.workflow_controller import StepState, WorkflowController

    controller = WorkflowController()
    controller.set_step_failed(1)
    assert controller.get_step_state(1) is StepState.FAILED


@pytest.mark.real_qtimer
def test_real_qtimer_channel_executes(qapp):
    from PySide6.QtCore import QTimer

    called: list[bool] = []
    QTimer.singleShot(0, lambda: called.append(True))
    qapp.processEvents()
    assert called == [True]


def test_progress_subscriber_connection_failure_stops_thread():
    # Run this real QThread lifecycle check in a fresh process.  The main test
    # suite intentionally shares one QApplication, and earlier UI tests may
    # still have deferred QObject deletions waiting in its event queue.
    script = """
import time
from PySide6.QtWidgets import QApplication
from repair_app.ui.progress_subscriber import ProgressSubscriber

app = QApplication.instance() or QApplication([])
subscriber = ProgressSubscriber()
try:
    subscriber.start("invalid://progress-endpoint")
    deadline = time.monotonic() + 5.0
    while subscriber.is_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert subscriber.is_running is False
    assert subscriber._flush_timer.isActive() is False
finally:
    assert subscriber.stop()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_compute_controller_never_overwrites_a_live_worker_thread(qapp):
    """P1-25: 旧线程仍在运行时拒绝启动新计算，不阻塞 UI 等待旧线程退出。"""
    from repair_app.ui.compute_controller import ComputeController

    controller = ComputeController(project_root="/unused")
    previous_thread = MagicMock()
    previous_thread.isRunning.return_value = True
    controller._compute_thread = previous_thread
    controller._compute_worker = MagicMock()

    # P1-25: 不再抛 RuntimeError 也不调用 wait 阻塞 UI，改为返回 False 拒绝启动
    result = controller._start_worker(b"request")

    assert result is False
    # 旧线程引用保留（由其自身 finished 回调清理）
    assert controller._compute_thread is previous_thread
    # 不应强制中断或等待旧线程
    previous_thread.requestInterruption.assert_not_called()
    previous_thread.quit.assert_not_called()
    previous_thread.wait.assert_not_called()

    # Prevent QObject teardown from treating the test double as a real child.
    controller._compute_thread = None
    controller._compute_worker = None


def test_compute_controller_shutdown_disarms_cancel_timeout(qapp, monkeypatch):
    from repair_app.ui.compute_controller import ComputeController

    controller = ComputeController(project_root="/unused")
    controller._busy = True
    monkeypatch.setattr(
        controller,
        "cancel_computation",
        lambda: controller._cancel_completion_timer.start(1000),
    )

    assert controller.cleanup() is True
    assert controller._cancel_completion_timer.isActive() is False


def test_path_sanitizer_decodes_bytes_before_redaction(monkeypatch):
    from repair_app.utils.path_sanitizer import PathSanitizer

    monkeypatch.setattr(PathSanitizer, "_home_path", "/Users/example")
    result = PathSanitizer.sanitize(b"/Users/example/private/file.txt")
    assert isinstance(result, str)
    assert result.startswith("<USER_HOME>")


def test_version_info_uses_standard_five_fields():
    from repair_app import __version_info__

    assert __version_info__ == (1, 0, 0, "final", 0)


def test_exception_reporter_survives_missing_stderr(monkeypatch, tmp_path):
    from repair_app.software.exception_reporter import ExceptionReporter

    report_path = tmp_path / "exception.log"
    path_manager = SimpleNamespace(exception_log_path=lambda _stamp: report_path)
    reporter = ExceptionReporter(path_manager=path_manager)

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated read-only log directory")

    monkeypatch.setattr(Path, "write_text", fail_write)
    monkeypatch.setattr("sys.stderr", None)
    assert reporter.report_text("cannot persist") == report_path
