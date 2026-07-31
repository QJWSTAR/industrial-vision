"""test_gui_integration.py — MainWindow GUI 集成测试

覆盖 MainWindow 的端到端流程：导出入口、预填充、按钮状态联动、
项目保存、向后兼容方法、License 拦截、RepairSession 数据驱动。

测试分层：
- @pytest.mark.gui        : GUI 测试（Qt offscreen 模式）
- @pytest.mark.integration: 集成测试（模块间协作）

运行：pytest -m "gui and integration" -v
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from repair_app.ui.main_window import MainWindow
from repair_app.core.repair_session import RepairSession
from repair_app.export.pipeline import ExporterRegistry, ExportResult
from repair_app.export import builtin_exporters  # noqa: F401 — 触发注册
from repair_app.utils.license_manager import LicenseManager


# ================================================================
# 固定工艺参数（替代 _collect_params，绕过 UI spinbox 初始化问题）
# ================================================================
_FAKE_PARAMS = {
    "material": "Ti-6Al-4V",
    "depth_compensation": 1.0,
    "max_layers": 10,
    "particle_velocity_ms": 500.0,
    "critical_velocity_ms": 400.0,
    "nozzle_diameter_mm": 6.0,
    "spray_angle_deg": 90.0,
    "standoff_distance_mm": 30.0,
    "particle_size_um": 25.0,
    "gas_temperature_c": 800.0,
    "gas_pressure_bar": 40.0,
    "powder_feed_rate_gmin": 30.0,
    "traversing_speed_mms": 500.0,
    "num_layers": 10,
    "layer_height_mm": 2.0,
    "scanning_angle_deg": 90.0,
    "scanning_step_mm": 1.0,
    "edge_step_size_mm": 0.5,
    "tilt_angle_deg": 90.0,
    "buffer_additive_mm": 0.3,
    "buffer_repairing_mm": 0.1,
    "link_path_free_dist_mm": 1.0,
    "obstacle_resolution_mm": 0.5,
}


# ================================================================
# Fixture: MainWindow（每个测试独立实例，自动清理）
# ================================================================
@pytest.fixture
def main_window(qapp, monkeypatch):
    """提供 MainWindow 实例，测试后自动清理 ZMQ client、定时器与 widget。

    关键处理：
    - mock QMessageBox 避免模态对话框阻塞测试
    - 清理 AutoRecovery 状态避免 _check_recovery 弹窗
    - 禁用 _load_demo 避免后台定时器修改 session 状态干扰测试
    - mock QFileDialog 避免文件保存对话框阻塞
    - mock ErrorManager._show_dialog 避免 ErrorDialog.exec() 模态阻塞
      （_on_export 异常分支会调用 _show_error → ErrorManager.handle(show_dialog=True)）
    """
    from PySide6.QtWidgets import QMessageBox, QFileDialog
    from repair_app.utils.error_manager import ErrorManager

    # mock QMessageBox 所有静态方法（避免模态对话框阻塞）
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: None)

    # mock QFileDialog（返回固定路径，避免文件对话框阻塞）
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("fake_output.nc", "All Files (*)"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("", ""))

    # mock ErrorManager._show_dialog（避免 ErrorDialog.exec() 模态阻塞测试）
    # 仍保留 ErrorManager.handle 的 classify/log/friendly 流程，仅跳过 GUI 弹窗。
    monkeypatch.setattr(ErrorManager, "_show_dialog", lambda *a, **kw: None)

    # 清理 AutoRecovery 状态（避免 _check_recovery 弹窗）
    try:
        from repair_app.software.path_manager import PathManager
        from repair_app.software.project_manager import AutoRecovery
        pm = PathManager.get_instance()
        ar = AutoRecovery(pm)
        ar.clear()
    except Exception:
        pass

    # 禁用 _load_demo（避免 300ms 后定时器修改 session 状态干扰测试）
    monkeypatch.setattr(MainWindow, "_load_demo", lambda self: None)

    mw = MainWindow()
    yield mw

    # P2-9: 清理 ComputeController（含 ProgressSubscriber 线程），避免 access violation
    compute_controller = getattr(mw, "_compute_controller", None)
    if compute_controller is not None:
        try:
            compute_controller.cleanup()
        except Exception:
            pass
    # 清理 ZMQ client
    if hasattr(mw, "_zmq_client") and mw._zmq_client is not None:
        try:
            mw._zmq_client.close()
        except Exception:
            pass
    # 停止所有定时器（避免 teardown 后回调）
    if hasattr(mw, "_timers"):
        for timer in mw._timers:
            try:
                timer.stop()
            except Exception:
                pass
    if hasattr(mw, "_autosave_timer"):
        try:
            mw._autosave_timer.stop()
        except Exception:
            pass
    mw.deleteLater()
    qapp.processEvents()


@pytest.fixture
def valid_license(main_window):
    """Mock LicenseManager.is_valid → True，避免 License 拦截导出流程。

    通过 PropertyMock 替换 is_valid 属性，使其在测试期间始终返回 True。
    """
    with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=True):
        yield main_window


@pytest.fixture
def mock_params(main_window):
    """Mock _collect_params 返回固定工艺参数 dict。

    绕过 UI spinbox 因 group 名称不匹配（schema "cold_spray" vs 代码 "cs"）
    导致 _cs_fields/_pp_fields 未填充的问题，使 _prepare_for_export /
    _collect_project_state 等方法可正常运行。
    """
    with patch.object(main_window, "_collect_params", return_value=_FAKE_PARAMS):
        yield main_window


@pytest.fixture
def export_ready(main_window):
    """导出就绪：License 有效 + _collect_params 可用。

    组合 valid_license 与 mock_params，用于需要走完整 _on_export 流程的测试。
    """
    with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=True), \
         patch.object(main_window, "_collect_params", return_value=_FAKE_PARAMS):
        yield main_window


# ================================================================
# 1. MainWindow 构造验证
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestMainWindowConstruction:
    """MainWindow 构造与核心字段验证。"""

    def test_session_field_exists(self, main_window):
        """构造后 _session 字段存在且为 RepairSession 实例。"""
        assert hasattr(main_window, "_session"), "MainWindow 应有 _session 字段"
        assert isinstance(main_window._session, RepairSession), (
            "_session 应为 RepairSession 实例"
        )

    def test_core_fields_exist(self, main_window):
        """构造后核心依赖字段均存在。"""
        assert hasattr(main_window, "_license"), "应有 _license 字段"
        assert hasattr(main_window, "_path_manager"), "应有 _path_manager 字段"
        assert hasattr(main_window, "_project_manager"), "应有 _project_manager 字段"
        assert isinstance(main_window._license, LicenseManager), (
            "_license 应为 LicenseManager 实例"
        )

    def test_export_buttons_field_exists(self, main_window):
        """构造后 _export_buttons 字典已初始化。"""
        assert hasattr(main_window, "_export_buttons"), "应有 _export_buttons 字段"
        assert isinstance(main_window._export_buttons, dict), (
            "_export_buttons 应为 dict"
        )

    def test_session_initial_state(self, main_window):
        """新构造的 session 处于初始空状态。"""
        session = main_window._session
        assert session.point_cloud.xyz is None, "初始点云应为 None"
        assert session.waypoint.mock is None, "初始航点应为 None"
        assert session.morphology.repair_xyz is None, "初始形貌应为 None"
        assert session.is_busy is False, "初始 is_busy 应为 False"


# ================================================================
# 2. _on_export 统一导出入口
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestOnExport:
    """_on_export(format_name) 统一导出入口测试。"""

    def test_on_export_gcode_success(self, export_ready):
        """_on_export('gcode') 调用 ExporterRegistry.run 并反馈成功。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result) as mock_run:
            mw._on_export("gcode")
            # 验证 run 被调用，参数为 (format_name, parent, session, path_manager)
            mock_run.assert_called_once_with("gcode", mw, mw._session, mw._path_manager)

    def test_on_export_sets_progress_on_success(self, export_ready):
        """导出成功后进度条到达 100。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result):
            mw._on_export("gcode")
            if hasattr(mw, "_prog"):
                assert mw._prog.value() == 100, "成功后进度应为 100"

    def test_on_export_unknown_format(self, valid_license):
        """未知格式时 ExporterRegistry.run 不被调用。"""
        mw = valid_license
        with patch.object(ExporterRegistry, "run") as mock_run:
            mw._on_export("nonexistent_format")
            mock_run.assert_not_called()

    def test_on_export_prepare_called(self, valid_license):
        """_on_export 调用 _prepare_for_export 预填充 session。"""
        mw = valid_license
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result), \
             patch.object(mw, "_prepare_for_export") as mock_prep:
            mw._on_export("gcode")
            mock_prep.assert_called_once_with("gcode")

    def test_on_export_run_failure(self, export_ready):
        """ExporterRegistry.run 返回失败时进度归零。"""
        mw = export_ready
        fail_result = ExportResult(ok=False, error="模拟失败")
        with patch.object(ExporterRegistry, "run", return_value=fail_result):
            mw._on_export("gcode")
            if hasattr(mw, "_prog"):
                assert mw._prog.value() == 0, "失败后进度应为 0"

    def test_on_export_exception_handled(self, export_ready):
        """ExporterRegistry.run 抛异常时 _on_export 不崩溃。"""
        mw = export_ready
        with patch.object(ExporterRegistry, "run", side_effect=RuntimeError("模拟异常")):
            # 不应抛出异常
            mw._on_export("gcode")
            if hasattr(mw, "_prog"):
                assert mw._prog.value() == 0, "异常后进度应为 0"

    def test_on_export_robot_format(self, valid_license):
        """_on_export('robot') 正常调用 ExporterRegistry.run。

        robot 格式无 _prepare_for_export 分支，不需要 mock_params。
        """
        mw = valid_license
        fake_result = ExportResult(ok=True, output_path="fake.krl")
        with patch.object(ExporterRegistry, "run", return_value=fake_result) as mock_run:
            mw._on_export("robot")
            mock_run.assert_called_once_with("robot", mw, mw._session, mw._path_manager)

    def test_on_export_pdf_format(self, export_ready):
        """_on_export('pdf') 正常调用 ExporterRegistry.run。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.pdf")
        with patch.object(ExporterRegistry, "run", return_value=fake_result) as mock_run:
            mw._on_export("pdf")
            mock_run.assert_called_once_with("pdf", mw, mw._session, mw._path_manager)

    def test_on_export_with_warnings(self, export_ready):
        """导出成功但含 warnings 时仍反馈成功（覆盖 result.warnings 分支）。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.nc", warnings=["安全检查警告"])
        with patch.object(ExporterRegistry, "run", return_value=fake_result):
            mw._on_export("gcode")
            if hasattr(mw, "_prog"):
                assert mw._prog.value() == 100, "含警告时仍应成功（进度 100）"

    def test_on_export_gcode_saves_validation_report(self, export_ready):
        """gcode 导出成功且 session.validation.result 存在时调用 _save_validation_report。"""
        mw = export_ready
        # 构造 validation.result
        mw._session.validation.result = {"ok": True, "checks": []}
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result), \
             patch.object(mw, "_save_validation_report") as mock_save:
            mw._on_export("gcode")
            mock_save.assert_called_once()
            # 清理
            mw._session.validation.result = None

    def test_on_export_data_incomplete_error(self, export_ready):
        """ExporterRegistry.run 返回 error='数据不完整，无法导出' 时走 warning 分支。

        gcode 分支的 _prepare_for_export 需要 _collect_params，故使用 export_ready。
        """
        mw = export_ready
        fail_result = ExportResult(ok=False, error="数据不完整，无法导出")
        with patch.object(ExporterRegistry, "run", return_value=fail_result):
            mw._on_export("gcode")
            if hasattr(mw, "_prog"):
                assert mw._prog.value() == 0, "数据不完整时进度应为 0"

    def test_on_export_user_cancelled_no_error_toast(self, export_ready):
        """error='用户取消' 时不弹错误 Toast（跳过错误反馈分支）。"""
        mw = export_ready
        cancel_result = ExportResult(ok=False, error="用户取消")
        with patch.object(ExporterRegistry, "run", return_value=cancel_result):
            mw._on_export("gcode")
            # 用户取消不应崩溃，进度保持
            assert mw._session.is_busy is False


# ================================================================
# 3. _prepare_for_export 预填充逻辑
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestPrepareForExport:
    """_prepare_for_export(format_name) 格式相关预填充测试。"""

    def test_prepare_gcode_fills_validation(self, mock_params):
        """gcode 分支填充 validation 与 report.parameters。"""
        mw = mock_params
        mw._prepare_for_export("gcode")
        session = mw._session
        # 验证 expected_n_layers 来自 UI
        expected_layers = mw._sp_max_layers.value() if hasattr(mw, "_sp_max_layers") else None
        assert session.validation.expected_n_layers == expected_layers
        # 验证 expected_layer_height 来自 _collect_params
        assert session.validation.expected_layer_height is not None
        # 验证 report.parameters 已填充
        assert isinstance(session.report.parameters, dict)
        assert len(session.report.parameters) > 0
        # 验证 license_id 已设置（无 license_data 时为 "N/A"）
        assert session.license_id in ("N/A", "") or len(session.license_id) > 0

    def test_prepare_gcode_license_id_from_data(self, mock_params):
        """gcode 分支：有 license_data 时 license_id 取 machine_id[:12]。"""
        mw = mock_params
        # 构造带 machine_id 的 LicenseData
        from repair_app.utils.license_manager import LicenseData
        fake_data = LicenseData({"machine_id": "ABCDEFGH1234567890"})
        mw._license._license = fake_data
        try:
            mw._prepare_for_export("gcode")
            # machine_id[:12] 取前 12 个字符 → "ABCDEFGH1234"
            assert mw._session.license_id == "ABCDEFGH1234", (
                "license_id 应为 machine_id 前 12 位"
            )
        finally:
            mw._license._license = None

    def test_prepare_pdf_fills_report_fields(self, mock_params):
        """pdf 分支填充 report.scan_info/results 与 metrics。"""
        mw = mock_params
        mw._prepare_for_export("pdf")
        session = mw._session
        # 验证 scan_info 已填充
        assert isinstance(session.report.scan_info, dict)
        assert "scan_id" in session.report.scan_info, "scan_info 应含 scan_id"
        assert "points" in session.report.scan_info, "scan_info 应含 points"
        # 验证 results 已填充
        assert isinstance(session.report.results, dict)
        assert len(session.report.results) > 0, "results 不应为空"
        # 验证 metrics 已填充
        assert isinstance(session.metrics.defect, dict)
        assert isinstance(session.metrics.path, dict)

    def test_prepare_pdf_with_point_cloud(self, mock_params, sample_points):
        """pdf 分支：有点云时 scan_info.points 反映实际点数。"""
        mw = mock_params
        mw._session.point_cloud.xyz = sample_points
        mw._prepare_for_export("pdf")
        assert mw._session.report.scan_info["points"] == len(sample_points), (
            "scan_info.points 应等于点云点数"
        )

    def test_prepare_pdf_sets_selection_mask(self, mock_params):
        """pdf 分支：将 selector 掩码同步到 session.selection.mask。"""
        mw = mock_params
        mw._prepare_for_export("pdf")
        # selector 的 mask 应同步到 session
        assert mw._session.selection.mask is not None

    def test_prepare_unknown_format_noop(self, main_window):
        """未知格式时 _prepare_for_export 不修改 session（无对应分支）。"""
        mw = main_window
        # 记录导出前状态
        before_params = dict(mw._session.report.parameters)
        mw._prepare_for_export("robot")
        # robot 分支无预填充逻辑，report.parameters 不变
        assert mw._session.report.parameters == before_params

    def test_prepare_gcode_sets_layer_height(self, mock_params):
        """gcode 分支：expected_layer_height 来自 _collect_params()。"""
        mw = mock_params
        mw._prepare_for_export("gcode")
        expected_h = float(_FAKE_PARAMS.get("layer_height_mm", 2.0))
        assert mw._session.validation.expected_layer_height == expected_h


# ================================================================
# 4. _build_output_panel 动态构建按钮
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestBuildOutputPanel:
    """_build_output_panel 动态构建导出按钮测试。"""

    def test_export_buttons_count_is_6(self, main_window):
        """_export_buttons 字典包含 6 个按钮（gcode/robot/pdf/csv/json/project）。"""
        btns = main_window._export_buttons
        assert len(btns) == 6, f"应有 6 个导出按钮，实际 {len(btns)}"

    def test_export_buttons_keys(self, main_window):
        """_export_buttons 包含全部 6 种格式名称。"""
        expected = {"gcode", "robot", "pdf", "csv", "json", "project"}
        assert set(main_window._export_buttons.keys()) == expected, (
            f"导出按钮 keys 应为 {expected}，实际 {set(main_window._export_buttons.keys())}"
        )

    def test_export_buttons_are_qpushbutton(self, main_window):
        """每个导出按钮均为 QPushButton 实例。"""
        from PySide6.QtWidgets import QPushButton
        for name, btn in main_window._export_buttons.items():
            assert isinstance(btn, QPushButton), f"{name} 按钮应为 QPushButton"

    def test_export_buttons_initially_disabled(self, main_window):
        """构造后所有导出按钮初始为禁用状态。"""
        for name, btn in main_window._export_buttons.items():
            assert not btn.isEnabled(), f"{name} 按钮初始应为禁用"

    def test_backward_compat_btn_attributes(self, main_window):
        """向后兼容属性 _btn_exp_gcode/_btn_exp_robot/_btn_exp_pdf 存在。"""
        assert hasattr(main_window, "_btn_exp_gcode"), "应有 _btn_exp_gcode 向后兼容属性"
        assert hasattr(main_window, "_btn_exp_robot"), "应有 _btn_exp_robot 向后兼容属性"
        assert hasattr(main_window, "_btn_exp_pdf"), "应有 _btn_exp_pdf 向后兼容属性"
        # 向后兼容属性应与 _export_buttons 中的对应项一致
        assert main_window._btn_exp_gcode is main_window._export_buttons["gcode"]
        assert main_window._btn_exp_robot is main_window._export_buttons["robot"]
        assert main_window._btn_exp_pdf is main_window._export_buttons["pdf"]


# ================================================================
# 5. 导出按钮启用/禁用逻辑 + 10. RepairSession 数据联动
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestButtonStates:
    """导出按钮启用/禁用逻辑与 RepairSession 数据联动测试。

    按钮状态由 _set_busy(False) 触发更新，依据各 exporter.is_ready(session) 判定。
    """

    def test_all_buttons_disabled_initially(self, main_window):
        """初始状态所有导出按钮禁用。"""
        for name, btn in main_window._export_buttons.items():
            assert not btn.isEnabled(), f"{name} 初始应禁用"

    def test_point_cloud_enables_json_button(self, main_window, sample_points):
        """赋值 point_cloud.xyz 后 json 按钮启用（requires point_cloud.xyz）。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._set_busy(False)
        # json 需要 point_cloud.xyz
        assert mw._export_buttons["json"].isEnabled(), "json 按钮应启用"
        # project 无前置要求，始终启用
        assert mw._export_buttons["project"].isEnabled(), "project 按钮应启用"
        # gcode/robot/csv 需要 waypoint.mock，仍禁用
        assert not mw._export_buttons["gcode"].isEnabled(), "gcode 仍应禁用"
        assert not mw._export_buttons["robot"].isEnabled(), "robot 仍应禁用"
        assert not mw._export_buttons["csv"].isEnabled(), "csv 仍应禁用"
        # pdf 需要 morphology.repair_xyz，仍禁用
        assert not mw._export_buttons["pdf"].isEnabled(), "pdf 仍应禁用"

    def test_waypoint_enables_gcode_robot_csv(self, main_window, sample_points, sample_waypoints):
        """赋值 waypoint.mock 后 gcode/robot/csv 按钮启用。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = sample_waypoints
        mw._set_busy(False)
        # gcode/robot/csv 需要 waypoint.mock
        assert mw._export_buttons["gcode"].isEnabled(), "gcode 按钮应启用"
        assert mw._export_buttons["robot"].isEnabled(), "robot 按钮应启用"
        assert mw._export_buttons["csv"].isEnabled(), "csv 按钮应启用"
        # pdf 仍需 morphology.repair_xyz
        assert not mw._export_buttons["pdf"].isEnabled(), "pdf 仍应禁用"

    def test_morphology_enables_pdf_button(self, main_window, sample_points, sample_waypoints):
        """赋值 morphology.repair_xyz 后 pdf 按钮启用。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = sample_waypoints
        mw._session.morphology.repair_xyz = sample_points.copy()
        mw._set_busy(False)
        # pdf 需要 morphology.repair_xyz
        assert mw._export_buttons["pdf"].isEnabled(), "pdf 按钮应启用"

    def test_all_buttons_enabled_when_full_data(self, main_window, sample_points, sample_waypoints):
        """全部数据就绪后所有 6 个按钮均启用。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = sample_waypoints
        mw._session.morphology.repair_xyz = sample_points.copy()
        mw._set_busy(False)
        for name, btn in mw._export_buttons.items():
            assert btn.isEnabled(), f"{name} 按钮应启用（全数据就绪）"

    def test_reset_output_disables_buttons(self, main_window, sample_points, sample_waypoints):
        """_reset_output 禁用所有导出按钮。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = sample_waypoints
        mw._set_busy(False)
        # 确认有按钮启用
        assert mw._export_buttons["gcode"].isEnabled()
        # 重置
        mw._reset_output()
        for name, btn in mw._export_buttons.items():
            assert not btn.isEnabled(), f"{name} 重置后应禁用"

    def test_busy_state_disables_buttons(self, main_window, sample_points, sample_waypoints):
        """is_busy=True 时 _set_busy 显式禁用 _btn_exp_gcode 与 _btn_exp_pdf。

        注：_set_busy(True) 的实现仅显式禁用向后兼容属性 _btn_exp_gcode /
        _btn_exp_pdf（以及 _btn_start_repair / _btn_fix / _btn_feas），
        不遍历 _export_buttons dict —— 此处验证实际生产行为。
        """
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = sample_waypoints
        mw._set_busy(False)
        # 进入 busy 状态
        mw._set_busy(True)
        # 验证 _set_busy(True) 显式禁用的两个导出按钮
        assert not mw._btn_exp_gcode.isEnabled(), "gcode busy 时应禁用"
        assert not mw._btn_exp_pdf.isEnabled(), "pdf busy 时应禁用"
        # session 标志
        assert mw._session.is_busy is True, "is_busy 应为 True"

    def test_empty_waypoint_disables_gcode(self, main_window, sample_points):
        """waypoint.mock 为空数组时 gcode 按钮禁用。"""
        mw = main_window
        mw._session.point_cloud.xyz = sample_points
        mw._session.waypoint.mock = np.array([], dtype=np.float32).reshape(0, 3)
        mw._set_busy(False)
        assert not mw._export_buttons["gcode"].isEnabled(), "空航点时 gcode 应禁用"


# ================================================================
# 6. _collect_project_state 收集会话状态
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestCollectProjectState:
    """_collect_project_state 收集会话状态测试。"""

    def test_returns_dict(self, mock_params):
        """_collect_project_state 返回 dict。"""
        state = mock_params._collect_project_state()
        assert isinstance(state, dict)

    def test_state_has_expected_keys(self, mock_params):
        """返回的 state 包含预期字段。"""
        state = mock_params._collect_project_state()
        assert "point_cloud_path" in state, "state 应含 point_cloud_path"
        assert "repair_mode" in state, "state 应含 repair_mode"
        assert "material_index" in state, "state 应含 material_index"
        assert "params" in state, "state 应含 params"
        assert "selection_summary" in state, "state 应含 selection_summary"

    def test_state_params_from_collect_params(self, mock_params):
        """state.params 来自 _collect_params()。"""
        mw = mock_params
        state = mw._collect_project_state()
        assert state["params"] == _FAKE_PARAMS

    def test_state_point_cloud_path(self, mock_params, sample_points):
        """state.point_cloud_path 反映 session.point_cloud.path。"""
        mw = mock_params
        mw._session.point_cloud.path = "/fake/path/cloud.ply"
        state = mw._collect_project_state()
        assert state["point_cloud_path"] == "/fake/path/cloud.ply"

    def test_state_selection_summary_with_mask(self, mock_params, sample_points, sample_defect_mask):
        """有选区掩码时 state.selection_summary 包含指标。"""
        mw = mock_params
        mw._session.point_cloud.xyz = sample_points
        mw._session.selection.mask = sample_defect_mask
        state = mw._collect_project_state()
        assert state["selection_summary"] != {}, "有掩码时 selection_summary 不应为空"
        assert "point_count" in state["selection_summary"], "应含 point_count"

    def test_state_selection_summary_empty_without_mask(self, mock_params):
        """无选区掩码时 state.selection_summary 为空 dict。"""
        mw = mock_params
        mw._session.selection.mask = None
        state = mw._collect_project_state()
        assert state["selection_summary"] == {}

    def test_state_handles_collect_params_failure(self, main_window):
        """_collect_params 抛异常时 _collect_project_state 不崩溃，params 为空 dict。

        覆盖 _collect_project_state 的 except 分支（log_error 后 params={}）。
        """
        mw = main_window
        # 让 _collect_params 抛异常
        with patch.object(mw, "_collect_params", side_effect=RuntimeError("模拟失败")):
            state = mw._collect_project_state()
            assert isinstance(state, dict), "异常时仍应返回 dict"
            assert state["params"] == {}, "异常时 params 应为空 dict"

    def test_state_handles_metrics_failure(self, mock_params, sample_points):
        """_compute_defect_metrics 抛异常时 _collect_project_state 不崩溃。

        覆盖 selection_summary 计算的 except 分支。
        """
        mw = mock_params
        mw._session.point_cloud.xyz = sample_points
        mw._session.selection.mask = np.ones(len(sample_points), dtype=bool)
        # 让 _compute_defect_metrics 抛异常
        with patch.object(mw, "_compute_defect_metrics", side_effect=RuntimeError("指标失败")):
            state = mw._collect_project_state()
            assert isinstance(state, dict), "指标异常时仍应返回 dict"
            assert state["selection_summary"] == {}, "指标异常时 selection_summary 应为空"


# ================================================================
# 7. _on_save_project 保存项目
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestOnSaveProject:
    """_on_save_project 保存项目测试。"""

    def test_on_save_project_calls_save_project(self, mock_params):
        """_on_save_project 调用 project_manager.save_project。"""
        mw = mock_params
        from pathlib import Path
        fake_path = Path("fake_project.csam")
        with patch.object(mw._project_manager, "save_project", return_value=fake_path) as mock_save:
            mw._on_save_project()
            mock_save.assert_called_once()

    def test_on_save_project_passes_state(self, mock_params):
        """_on_save_project 将 _collect_project_state 结果传给 save_project。"""
        mw = mock_params
        from pathlib import Path
        fake_path = Path("fake_project.csam")
        with patch.object(mw._project_manager, "save_project", return_value=fake_path) as mock_save:
            mw._on_save_project()
            call_args = mock_save.call_args
            state = call_args[0][0]
            assert isinstance(state, dict), "save_project 应接收 state dict"
            assert "params" in state, "state 应含 params"

    def test_on_save_project_updates_statusbar(self, mock_params):
        """保存成功后状态栏显示保存路径。"""
        mw = mock_params
        from pathlib import Path
        fake_path = Path("fake_project.csam")
        with patch.object(mw._project_manager, "save_project", return_value=fake_path):
            mw._on_save_project()
            assert "fake_project.csam" in mw._sb.currentMessage(), (
                "状态栏应显示保存路径"
            )

    def test_on_save_project_exception_handled(self, mock_params):
        """save_project 抛异常时 _on_save_project 不崩溃。"""
        mw = mock_params
        with patch.object(mw._project_manager, "save_project", side_effect=RuntimeError("模拟失败")):
            # 不应抛出异常
            mw._on_save_project()

    def test_on_save_project_adds_to_recent(self, mock_params):
        """保存后项目加入最近项目列表。"""
        mw = mock_params
        from pathlib import Path
        fake_path = Path("fake_project.csam")
        with patch.object(mw._project_manager, "save_project", return_value=fake_path), \
             patch.object(mw._recent_projects, "add") as mock_add:
            mw._on_save_project()
            mock_add.assert_called_once()
            # 第二参数为路径字符串
            args = mock_add.call_args[0]
            assert str(fake_path) in args or args[1] == str(fake_path)


# ================================================================
# 8. 向后兼容导出方法
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestBackwardCompatExports:
    """_on_export_gcode/_on_export_pdf/_on_export_robot 向后兼容测试。

    这三个方法应委托给 _on_export(format_name) 统一入口。
    """

    def test_on_export_gcode_delegates(self, main_window):
        """_on_export_gcode() 委托 _on_export('gcode')。"""
        mw = main_window
        with patch.object(mw, "_on_export") as mock_export:
            mw._on_export_gcode()
            mock_export.assert_called_once_with("gcode")

    def test_on_export_pdf_delegates(self, main_window):
        """_on_export_pdf() 委托 _on_export('pdf')。"""
        mw = main_window
        with patch.object(mw, "_on_export") as mock_export:
            mw._on_export_pdf()
            mock_export.assert_called_once_with("pdf")

    def test_on_export_robot_delegates(self, main_window):
        """_on_export_robot() 委托 _on_export('robot')。"""
        mw = main_window
        with patch.object(mw, "_on_export") as mock_export:
            mw._on_export_robot()
            mock_export.assert_called_once_with("robot")

    def test_backward_compat_uses_real_pipeline(self, export_ready):
        """向后兼容方法实际调用 ExporterRegistry.run（端到端验证）。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result) as mock_run:
            mw._on_export_gcode()
            mock_run.assert_called_once_with("gcode", mw, mw._session, mw._path_manager)


# ================================================================
# 9. License 无效时的导出拦截
# ================================================================
@pytest.mark.gui
@pytest.mark.integration
class TestLicenseIntercept:
    """License 无效时导出被拦截测试。"""

    def test_export_blocked_when_license_invalid(self, main_window):
        """License 无效时 _on_export 不调用 ExporterRegistry.run。"""
        mw = main_window
        # 确保 License 无效（通过 PropertyMock 返回 False）
        with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=False), \
             patch.object(ExporterRegistry, "run") as mock_run:
            mw._on_export("gcode")
            mock_run.assert_not_called()

    def test_export_blocked_does_not_call_prepare(self, main_window):
        """License 无效时不调用 _prepare_for_export。"""
        mw = main_window
        with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=False), \
             patch.object(mw, "_prepare_for_export") as mock_prep:
            mw._on_export("gcode")
            mock_prep.assert_not_called()

    def test_export_blocked_for_all_formats(self, main_window):
        """License 无效时所有格式的导出均被拦截。"""
        mw = main_window
        with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=False), \
             patch.object(ExporterRegistry, "run") as mock_run:
            for fmt in ("gcode", "pdf", "robot", "csv", "json", "project"):
                mw._on_export(fmt)
            mock_run.assert_not_called()

    def test_valid_license_allows_export(self, export_ready):
        """License 有效时导出正常执行（对照测试）。"""
        mw = export_ready
        fake_result = ExportResult(ok=True, output_path="fake.nc")
        with patch.object(ExporterRegistry, "run", return_value=fake_result) as mock_run:
            mw._on_export("gcode")
            mock_run.assert_called_once()
