"""test_export_full.py — 导出服务与导出器完整流程测试

被测模块:
  - repair_app/service/export_service.py: ExportService（validate_toolpath /
    export_gcode / export_pdf_report / _compute_safe_z / _validate_waypoints）
  - repair_app/export/gcode_exporter.py: GCodeExporter（export 含 layer_indices /
    velocities / nozzle_on_mask / set_metadata / _emit_lead_in / _emit_lead_out /
    _emit_layer_transition / _header M3 / _footer M5+M30）
  - repair_app/export/robot_exporter.py: RobotExporter（KUKA KRL / ABB Rapid /
    normals / mm→m 转换）
  - repair_app/export/report_generator.py: RepairReport（set_scan_info /
    set_parameters / set_results / set_layers / set_statistics / set_quality /
    add_comparison_figure / add_height_colormap / generate PDF）
  - 导出器注册边缘用例（补充 test_pipeline.py）

运行: pytest -m export -v test_export_full.py

目标覆盖: ExportService 90%+。
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

from repair_app.core.repair_session import RepairSession
from repair_app.export.gcode_exporter import GCodeExporter
from repair_app.export.robot_exporter import RobotExporter, RobotType
from repair_app.service.export_service import ExportService

# 检测 reportlab 是否可用
try:
    import reportlab  # noqa: F401
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


# ============================================================
# 辅助函数
# ============================================================
def make_session() -> RepairSession:
    """构造含点云/选区/航点/形貌/报告字段的完整 session（任务指定）。"""
    session = RepairSession()
    session.point_cloud.xyz = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32,
    )
    session.selection.mask = np.array([False, True, True, False])
    session.waypoint.mock = np.array(
        [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.float32,
    )
    session.waypoint.layers = np.array([0, 0, 1, 1])
    session.morphology.repair_xyz = np.array([[0.5, 0.5, 2]], dtype=np.float32)
    session.report.parameters = {
        "layer_height_mm": 2.0, "traversing_speed_mms": 500.0, "material": "Al",
    }
    session.report.scan_info = {
        "scan_id": "TEST-001", "points": 4,
        "defect_volume_mm3": 1.0, "defect_depth_mm": 1.0, "material": "Al",
    }
    session.report.results = {"填充点数": "1", "修复层数": "2"}
    return session


def make_session_full_report() -> RepairSession:
    """构造含全部 report 章节（layers/statistics/quality）的 session。"""
    session = make_session()
    session.report.layers = [
        {"points": 2, "avg_height": 1.0, "mass_g": 0.05},
        {"points": 2, "avg_height": 2.0, "mass_g": 0.08},
    ]
    session.report.statistics = {"mean": 1.5, "min": 1.0, "max": 2.0, "std": 0.5}
    session.report.quality = {
        "uniformity_score": 0.92, "coverage_rate": 0.88, "overspray_ratio": 0.05,
    }
    return session


# ============================================================
# 1. ExportService 测试
# ============================================================
@pytest.mark.export
class TestExportServiceComputeSafeZ:
    """_compute_safe_z 静态方法测试。"""

    def test_returns_max_z_plus_5(self):
        waypoints = np.array([[0, 0, 5], [1, 0, 10], [2, 0, 3]], dtype=np.float32)
        safe_z = ExportService._compute_safe_z(waypoints)
        # max(10, 10 + 5) = 15
        assert safe_z == 15.0

    def test_minimum_10mm(self):
        """Z 最大值 + 5 不足 10 时返回 10。"""
        waypoints = np.array([[0, 0, 1], [1, 0, 2]], dtype=np.float32)
        safe_z = ExportService._compute_safe_z(waypoints)
        # max(10, 2 + 5) = 10
        assert safe_z == 10.0

    def test_single_waypoint(self):
        waypoints = np.array([[0, 0, 0]], dtype=np.float32)
        assert ExportService._compute_safe_z(waypoints) == 10.0

    def test_negative_z(self):
        waypoints = np.array([[0, 0, -3]], dtype=np.float32)
        # max(10, -3 + 5) = 10
        assert ExportService._compute_safe_z(waypoints) == 10.0


@pytest.mark.export
class TestExportServiceValidateWaypoints:
    """_validate_waypoints 静态方法测试。"""

    def test_none_raises(self):
        with pytest.raises(ValueError, match="航点数组为空"):
            ExportService._validate_waypoints(None)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="航点数组为空"):
            ExportService._validate_waypoints(np.zeros((0, 3)))

    def test_wrong_ndim_raises(self):
        with pytest.raises(ValueError, match="航点形状"):
            ExportService._validate_waypoints(np.array([1, 2, 3]))

    def test_too_few_columns_raises(self):
        with pytest.raises(ValueError, match="航点形状"):
            ExportService._validate_waypoints(np.array([[1, 2]], dtype=np.float32))

    def test_valid_waypoints_no_raise(self):
        wp = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        # 不抛异常即通过
        ExportService._validate_waypoints(wp)


@pytest.mark.export
class TestExportServiceValidateToolpath:
    """validate_toolpath 测试。"""

    def test_returns_ok_tuple(self):
        session = make_session()
        service = ExportService()
        ok, result = service.validate_toolpath(session)
        assert isinstance(ok, bool)
        assert ok is True
        # 结果回写 session
        assert session.validation.result is result

    def test_result_written_to_session(self):
        session = make_session()
        service = ExportService()
        service.validate_toolpath(session)
        assert session.validation.result is not None
        assert session.validation.result.ok is True

    def test_build_volume_check(self):
        """航点在构建体积内时校验通过。"""
        session = make_session()
        service = ExportService()
        # 构建体积 [-10, -10, 0] - [10, 10, 50]
        ok, result = service.validate_toolpath(session, build_volume=(-10, -10, 0, 10, 10, 50))
        assert ok is True

    def test_build_volume_out_of_bounds(self):
        """航点超出构建体积时校验失败。"""
        session = make_session()
        service = ExportService()
        # 构建体积过小，航点 [1,1,1] 超出 [0,0,0]-[0.5, 0.5, 50]
        ok, result = service.validate_toolpath(
            session, build_volume=(0, 0, 0, 0.5, 0.5, 50),
        )
        assert ok is False
        assert any("超出构建体积" in m for m in result.blocking_messages)

    def test_empty_waypoints_raises(self):
        session = make_session()
        session.waypoint.mock = np.zeros((0, 3), dtype=np.float32)
        service = ExportService()
        with pytest.raises(ValueError, match="航点数组为空"):
            service.validate_toolpath(session)


@pytest.mark.export
class TestExportServiceExportGcode:
    """export_gcode 测试。"""

    def test_export_success(self, tmp_path):
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "repair.nc")
        ok = service.export_gcode(session, out, feed_rate=500.0)
        assert ok is True
        assert os.path.exists(out)
        assert session.output.last_gcode_path == out

    def test_export_with_metadata(self, tmp_path):
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "repair_meta.nc")
        metadata = {
            "model_version": "v2.1",
            "material": "Al",
            "parameters": {"layer_height": 2.0},
            "license_id": "LIC-001",
        }
        ok = service.export_gcode(session, out, feed_rate=500.0, metadata=metadata)
        assert ok is True
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        assert "v2.1" in content
        assert "LIC-001" in content
        assert "layer_height=2.0" in content

    def test_export_writes_gcode_content(self, tmp_path):
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "repair.nc")
        service.export_gcode(session, out, feed_rate=500.0)
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        assert "G90" in content       # 绝对坐标
        assert "M3" in content        # 主轴启动
        assert "G21" in content       # 单位 mm
        assert "M30" in content       # 程序结束
        assert "M5" in content        # 主轴停

    def test_export_invalid_path_returns_false(self, tmp_path):
        """输出路径目录不存在时返回 False。"""
        session = make_session()
        service = ExportService()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.nc")
        ok = service.export_gcode(session, bad_path, feed_rate=500.0)
        assert ok is False
        assert session.output.last_gcode_path != bad_path

    def test_export_empty_waypoints_returns_false(self):
        """空航点返回 False（不抛异常）。"""
        session = make_session()
        session.waypoint.mock = np.zeros((0, 3), dtype=np.float32)
        service = ExportService()
        ok = service.export_gcode(session, "/tmp/empty.nc", feed_rate=500.0)
        assert ok is False

    def test_export_default_feed_rate(self, tmp_path):
        """不传 feed_rate 时使用默认 500.0。"""
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "default_feed.nc")
        ok = service.export_gcode(session, out)
        assert ok is True
        assert os.path.exists(out)


@pytest.mark.export
class TestExportServiceExportPdfReport:
    """export_pdf_report 测试。"""

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_success(self, tmp_path):
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "report.pdf")
        ok = service.export_pdf_report(session, out)
        assert ok is True
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert session.output.last_pdf_path == out

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_with_full_report_fields(self, tmp_path):
        """含全部 report 章节（layers/statistics/quality）的 PDF 导出。"""
        session = make_session_full_report()
        service = ExportService()
        out = str(tmp_path / "report_full.pdf")
        ok = service.export_pdf_report(session, out)
        assert ok is True
        assert os.path.exists(out)

    def test_export_pdf_no_reportlab_returns_false(self, tmp_path):
        """reportlab 未安装时返回 False。"""
        if _REPORTLAB_AVAILABLE:
            pytest.skip("reportlab 已安装，跳过失败路径测试")
        session = make_session()
        service = ExportService()
        out = str(tmp_path / "report.pdf")
        ok = service.export_pdf_report(session, out)
        assert ok is False

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_invalid_path_returns_false(self, tmp_path):
        """输出路径目录不存在时返回 False。"""
        session = make_session()
        service = ExportService()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.pdf")
        ok = service.export_pdf_report(session, bad_path)
        assert ok is False

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_no_point_cloud(self, tmp_path):
        """无点云时跳过图表但仍生成 PDF。"""
        session = make_session()
        session.point_cloud.xyz = None
        service = ExportService()
        out = str(tmp_path / "report_no_pc.pdf")
        ok = service.export_pdf_report(session, out)
        assert ok is True
        assert os.path.exists(out)


# ============================================================
# 2. GCodeExporter 完整流程测试
# ============================================================
@pytest.mark.export
class TestGCodeExporterLayerIndices:
    """export() 含 layer_indices 分层测试。"""

    def test_layer_transition_emitted(self):
        """层切换时生成层间过渡 G-code。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([
            [0, 0, 1], [1, 0, 1],   # layer 0
            [1, 1, 3], [0, 1, 3],   # layer 1
        ], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = exporter.export(waypoints, layer_indices=layers, validate=False)
        assert "层切换" in result
        assert "Layer 1" in result
        # 层间过渡包含抬刀
        assert "G0 Z100.000" in result  # safe_z

    def test_single_layer_no_transition(self):
        """单层时不生成层切换。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        layers = np.array([0, 0])
        result = exporter.export(waypoints, layer_indices=layers, validate=False)
        assert "层切换" not in result

    def test_layer_indices_none_treated_single_layer(self):
        """layer_indices=None 视为单层。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1], [2, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, layer_indices=None, validate=False)
        assert "层切换" not in result

    def test_layer_indices_mismatched_length_treats_single(self):
        """layer_indices 长度不匹配时视为单层。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        layers = np.array([0, 0, 1])  # 长度不匹配
        result = exporter.export(waypoints, layer_indices=layers, validate=False)
        assert "层切换" not in result


@pytest.mark.export
class TestGCodeExporterVelocities:
    """export() 含 velocities 进给速度测试。"""

    def test_velocities_applied(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1], [2, 0, 1]], dtype=np.float32)
        velocities = np.array([300.0, 600.0, 900.0], dtype=np.float32)
        result = exporter.export(
            waypoints, velocities=velocities, validate=False,
        )
        assert "F300" in result
        assert "F600" in result
        assert "F900" in result

    def test_velocities_length_mismatch_uses_default(self):
        """velocities 长度不足时缺失部分使用默认 feed_rate。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1], [2, 0, 1]], dtype=np.float32)
        velocities = np.array([300.0], dtype=np.float32)  # 仅 1 个
        result = exporter.export(
            waypoints, velocities=velocities, validate=False,
        )
        assert "F300" in result
        assert "F1000" in result  # 默认


@pytest.mark.export
class TestGCodeExporterNozzleMask:
    """export() 含 nozzle_on_mask 喷枪开关测试。"""

    def test_nozzle_off_emits_powder_off(self):
        """nozzle_on_mask 含 False 时生成送粉关闭代码。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1], [2, 0, 1]], dtype=np.float32)
        nozzle_mask = np.array([True, False, True])
        result = exporter.export(
            waypoints, nozzle_on_mask=nozzle_mask, validate=False,
        )
        # M10 = m_code + 2 = 送粉关闭
        assert "M10" in result
        # 含抬刀 + 快速移动 + 下降
        assert "抬刀" in result
        assert "快速移动" in result
        assert "下降" in result

    def test_nozzle_all_on_no_powder_off_in_middle(self):
        """nozzle_on_mask 全 True 时中途不生成送粉关闭。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        nozzle_mask = np.array([True, True])
        result = exporter.export(
            waypoints, nozzle_on_mask=nozzle_mask, validate=False,
        )
        # 尾部仍有关闭（M10），但中途不应有额外的 M10
        # M10 出现次数 = 1（仅尾部关闭）
        assert result.count("M10") == 1


@pytest.mark.export
class TestGCodeExporterMetadata:
    """set_metadata 追溯元数据测试。"""

    def test_metadata_in_output(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter.set_metadata(
            model_version="v2.1",
            material="Cu-Al2O3",
            parameters={"layer_height": 0.5, "scanning_step": 2.0},
            license_id="LIC-001",
        )
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, validate=False)
        assert "v2.1" in result
        assert "Cu-Al2O3" in result
        assert "LIC-001" in result
        assert "layer_height=0.5" in result
        assert "scanning_step=2.0" in result

    def test_metadata_defaults_when_empty(self):
        """set_metadata 未设置时使用默认占位值。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, validate=False)
        assert "unknown" in result    # model_version 默认
        assert "未指定" in result      # material 默认
        assert "N/A" in result        # license_id / parameters 默认

    def test_metadata_no_parameters(self):
        """set_metadata 不传 parameters 时显示 N/A。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter.set_metadata(model_version="v1.0", material="Al", license_id="L-1")
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, validate=False)
        assert "参数: N/A" in result


@pytest.mark.export
class TestGCodeExporterLeadInOut:
    """_emit_lead_in / _emit_lead_out 测试。"""

    def test_emit_lead_in_absolute(self):
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            lead_in_length=5.0,
        )
        exporter._lines = []
        exporter._emit_lead_in(10.0, 20.0, 5.0, is_incremental=False)
        lines = "\n".join(exporter._lines)
        # approach_x = x0 - L = 10 - 5 = 5
        assert "X5.000" in lines
        assert "Y20.000" in lines
        assert "Z100.000" in lines  # safe_z
        assert "Z5.000" in lines    # 下降到工作高度
        # 切线接近起点
        assert "X10.000" in lines

    def test_emit_lead_in_incremental(self):
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            lead_in_length=5.0,
        )
        exporter._lines = []
        exporter._emit_lead_in(10.0, 20.0, 5.0, is_incremental=True)
        lines = "\n".join(exporter._lines)
        # 增量模式含临时 G90 + 恢复 G91
        assert "G90" in lines
        assert "G91" in lines

    def test_emit_lead_out_absolute(self):
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            lead_out_length=5.0,
        )
        exporter._lines = []
        exporter._emit_lead_out(10.0, 20.0, 5.0, is_incremental=False)
        lines = "\n".join(exporter._lines)
        # exit_x = end_x + L = 10 + 5 = 15
        assert "X15.000" in lines
        assert "Y20.000" in lines
        assert "Z100.000" in lines  # safe_z 抬刀

    def test_emit_lead_out_incremental(self):
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            lead_out_length=5.0,
        )
        exporter._lines = []
        exporter._emit_lead_out(10.0, 20.0, 5.0, is_incremental=True)
        lines = "\n".join(exporter._lines)
        assert "G90" in lines
        assert "G91" in lines


@pytest.mark.export
class TestGCodeExporterLayerTransition:
    """_emit_layer_transition 测试。"""

    def test_layer_transition_absolute(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter._lines = []
        exporter._emit_layer_transition(
            cur_x=0.0, cur_y=0.0, cur_z=1.0,
            next_x=5.0, next_y=5.0, next_z=3.0,
            layer_id=1, is_incremental=False,
        )
        lines = "\n".join(exporter._lines)
        assert "Layer 1" in lines
        assert "M10" in lines  # m_code + 2 = 送粉关闭
        assert "M8" in lines   # 送粉开启
        assert "G0 Z100.000" in lines    # 抬刀到 safe_z
        assert "X5.000" in lines         # 移动到新层 XY
        assert "Z3.000" in lines         # 下降到新层 Z
        assert "G4 P" in lines           # 喷枪稳定延时

    def test_layer_transition_incremental(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter._lines = []
        exporter._emit_layer_transition(
            cur_x=0.0, cur_y=0.0, cur_z=1.0,
            next_x=5.0, next_y=5.0, next_z=3.0,
            layer_id=2, is_incremental=True,
        )
        lines = "\n".join(exporter._lines)
        assert "Layer 2" in lines
        # 增量模式含临时 G90 + 恢复 G91
        assert "G90" in lines
        assert "G91" in lines


@pytest.mark.export
class TestGCodeExporterHeaderFooter:
    """_header / _footer 测试。"""

    def test_header_contains_m3_spindle_start(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter._lines = []
        exporter._header()
        lines = "\n".join(exporter._lines)
        # M3 主轴启动
        assert "M3" in lines
        assert "主轴启动" in lines
        # 追溯信息
        assert "追溯信息" in lines
        assert "软件版本" in lines
        assert "模型版本" in lines
        assert "Git Commit" in lines
        # 坐标模式
        assert "G90" in lines  # 绝对坐标
        assert "G21" in lines  # 单位 mm
        assert "G17" in lines  # XY 平面
        assert "G94" in lines  # 进给 mm/min
        # Lead-in/Lead-out 长度注释
        assert "Lead-in" in lines
        assert "Lead-out" in lines

    def test_header_incremental_mode(self):
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            coordinate_mode="incremental",
        )
        exporter._lines = []
        exporter._header()
        lines = "\n".join(exporter._lines)
        assert "G91" in lines  # 增量坐标

    def test_footer_contains_m5_and_m30(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter._lines = []
        exporter._footer()
        lines = "\n".join(exporter._lines)
        assert "M5" in lines    # 主轴停
        assert "M30" in lines   # 程序结束并复位

    def test_header_contains_metadata(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter.set_metadata(
            model_version="v9.9", material="Ti", license_id="LIC-XYZ",
        )
        exporter._lines = []
        exporter._header()
        lines = "\n".join(exporter._lines)
        assert "v9.9" in lines
        assert "Ti" in lines
        assert "LIC-XYZ" in lines


@pytest.mark.export
class TestGCodeExporterValidation:
    """export() 校验逻辑测试。"""

    def test_nan_coordinates_raises(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        bad_wp = np.array([
            [0, 0, 1], [np.nan, 0, 1], [2, 0, 1],
        ], dtype=np.float32)
        with pytest.raises(ValueError, match="NaN"):
            exporter.export(bad_wp, validate=False)

    def test_invalid_shape_raises(self):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        bad_wp = np.array([1, 2, 3], dtype=np.float32)
        with pytest.raises(ValueError, match="航点必须为"):
            exporter.export(bad_wp, validate=False)

    def test_validation_failure_raises(self):
        """validate=True 且校验不通过时抛 ValueError。"""
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        # safe_z (100) > z_max (1), 但负 Z 会触发 NEGATIVE_HEIGHT
        bad_wp = np.array([[0, 0, -1], [1, 0, -1]], dtype=np.float32)
        with pytest.raises(ValueError):
            exporter.export(bad_wp, validate=True)

    def test_export_to_file(self, tmp_path):
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        waypoints = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        out = str(tmp_path / "out.nc")
        result = exporter.export(waypoints, output_path=out, validate=False)
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == result


# ============================================================
# 3. RobotExporter 完整流程测试
# ============================================================
@pytest.mark.export
class TestRobotExporterKUKA:
    """KUKA KRL 导出测试。"""

    def test_kuka_basic_structure(self):
        exporter = RobotExporter(
            robot_type=RobotType.KUKA, tcp_speed=0.5, tool_frame=1, base_frame=0,
        )
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints)
        assert "DEF" in result
        assert "csam_repair" in result
        assert "END" in result
        assert "BAS(#TOOL, 1)" in result
        assert "BAS(#BASE, 0)" in result
        assert "BAS(#VEL_CP, 0.5" in result
        assert "LIN" in result  # zone=fine → LIN

    def test_kuka_ptp_mode(self):
        """zone != fine 时使用 PTP 模式。"""
        exporter = RobotExporter(
            robot_type=RobotType.KUKA, tcp_speed=0.5, zone="z10",
        )
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints)
        assert "PTP" in result

    def test_kuka_file_write(self, tmp_path):
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        out = str(tmp_path / "repair.krl")
        result = exporter.export(waypoints, output_path=out)
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == result

    def test_kuka_end_with_ptp_axis_act(self):
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[0, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints)
        assert "PTP $AXIS_ACT" in result


@pytest.mark.export
class TestRobotExporterABB:
    """ABB Rapid 导出测试。"""

    def test_abb_basic_structure(self):
        exporter = RobotExporter(
            robot_type=RobotType.ABB, tcp_speed=0.5, tool_frame=1,
        )
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints)
        assert "MODULE" in result
        assert "csam_repair" in result
        assert "PROC main()" in result
        assert "MoveL" in result
        assert "ENDPROC" in result
        assert "ENDMODULE" in result
        # TCP 速度 v500 (= 0.5 * 1000)
        assert "v500" in result

    def test_abb_file_write(self, tmp_path):
        exporter = RobotExporter(robot_type=RobotType.ABB)
        waypoints = np.array([[0, 0, 1], [50, 50, 1]], dtype=np.float32)
        out = str(tmp_path / "repair.mod")
        result = exporter.export(waypoints, output_path=out)
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == result


@pytest.mark.export
class TestRobotExporterNormals:
    """含 normals 的导出测试。"""

    def test_kuka_with_normals(self):
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, normals=normals)
        # 法向量 (0,0,1) → A≈0, B≈0
        assert "A 0.0" in result
        assert "B 0.0" in result

    def test_abb_with_normals(self):
        exporter = RobotExporter(robot_type=RobotType.ABB)
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)
        result = exporter.export(waypoints, normals=normals)
        # Z 轴法向量 → 四元数 (1, 0, 0, 0)
        assert "[1.0000, 0.0000, 0.0000, 0.0000]" in result

    def test_kuka_with_tilted_normals(self):
        """倾斜法向量生成非零 A/B 角度。"""
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[0, 0, 1]], dtype=np.float32)
        normals = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)  # X 方向
        result = exporter.export(waypoints, normals=normals)
        # X 方向法向量 → B=90 (arccos(0))
        assert "B 90.0" in result

    def test_normals_shorter_than_waypoints(self):
        """normals 长度不足时缺失部分使用默认姿态。"""
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[0, 0, 1], [100, 0, 1]], dtype=np.float32)
        normals = np.array([[0, 0, 1]], dtype=np.float32)  # 仅 1 个
        result = exporter.export(waypoints, normals=normals)
        # 不抛异常即通过
        assert "DEF" in result


@pytest.mark.export
class TestRobotExporterCoordConversion:
    """mm → m 坐标转换测试。"""

    def test_kuka_mm_to_m(self):
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[1000.0, 2000.0, 3000.0]], dtype=np.float32)
        result = exporter.export(waypoints)
        # 1000mm → 1.000m
        assert "X 1.000" in result
        assert "Y 2.000" in result
        assert "Z 3.000" in result

    def test_abb_mm_to_m(self):
        exporter = RobotExporter(robot_type=RobotType.ABB)
        waypoints = np.array([[500.0, 250.0, 1000.0]], dtype=np.float32)
        result = exporter.export(waypoints)
        # ABB 使用 %.2f 精度
        assert "0.50" in result   # 500mm → 0.50m
        assert "0.25" in result   # 250mm → 0.25m
        assert "1.00" in result   # 1000mm → 1.00m

    def test_negative_coordinates(self):
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        waypoints = np.array([[-500.0, -250.0, 0.0]], dtype=np.float32)
        result = exporter.export(waypoints)
        assert "X -0.500" in result
        assert "Y -0.250" in result


@pytest.mark.export
class TestRobotExporterHelpers:
    """法向量转换辅助函数测试。"""

    def test_normal_to_euler_kuka_z_axis(self):
        from repair_app.export.robot_exporter import _normal_to_euler_kuka
        a, b, c = _normal_to_euler_kuka(np.array([0.0, 0.0, 1.0]))
        assert abs(a) < 1e-6
        assert abs(b) < 1e-6
        assert c == 0.0

    def test_normal_to_euler_kuka_x_axis(self):
        from repair_app.export.robot_exporter import _normal_to_euler_kuka
        a, b, c = _normal_to_euler_kuka(np.array([1.0, 0.0, 0.0]))
        # X 方向 → B = 90
        assert abs(b - 90.0) < 1e-6
        assert c == 0.0

    def test_normal_to_quaternion_abb_z_axis(self):
        from repair_app.export.robot_exporter import _normal_to_quaternion_abb
        q1, q2, q3, q4 = _normal_to_quaternion_abb(np.array([0.0, 0.0, 1.0]))
        assert abs(q1 - 1.0) < 1e-6
        assert abs(q2) < 1e-6
        assert abs(q3) < 1e-6
        assert abs(q4) < 1e-6

    def test_normal_to_quaternion_abb_x_axis(self):
        from repair_app.export.robot_exporter import _normal_to_quaternion_abb
        q1, q2, q3, q4 = _normal_to_quaternion_abb(np.array([1.0, 0.0, 0.0]))
        # X 方向 → 绕 Y 轴旋转 90° → q2 ≈ 0.707
        assert abs(q1 - 0.7071) < 0.01
        assert abs(q3 - 0.7071) < 0.01

    def test_normal_to_euler_zero_vector(self):
        """零向量法向量不抛异常（归一化时除以 1e-6）。"""
        from repair_app.export.robot_exporter import _normal_to_euler_kuka
        a, b, c = _normal_to_euler_kuka(np.array([0.0, 0.0, 0.0]))
        assert isinstance(a, float)


# ============================================================
# 4. RepairReport 完整流程测试
# ============================================================
@pytest.mark.export
class TestRepairReportSetters:
    """RepairReport set_* 方法测试。"""

    def test_set_scan_info(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(
            scan_id="SCAN-001", points=10000,
            defect_volume_mm3=125.5, defect_depth_mm=2.3, material="Cu",
        )
        assert report.scan_info["scan_id"] == "SCAN-001"
        assert report.scan_info["points"] == 10000
        assert report.scan_info["defect_volume_mm3"] == 125.5
        assert report.scan_info["defect_depth_mm"] == 2.3
        assert report.scan_info["material"] == "Cu"

    def test_set_scan_info_defaults(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info()
        assert report.scan_info["scan_id"] == ""
        assert report.scan_info["points"] == 0
        assert report.scan_info["material"] == ""

    def test_set_parameters(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        params = {"layer_height_mm": 2.0, "traversing_speed_mms": 500.0}
        report.set_parameters(params)
        assert report.parameters == params

    def test_set_results(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        results = {"path_length_mm": 100.0, "estimated_time_s": 10.0}
        report.set_results(results)
        assert report.results == results

    def test_set_layers(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        layers = [
            {"points": 50, "avg_height": 0.5, "mass_g": 0.12},
            {"points": 30, "avg_height": 1.0, "mass_g": 0.08},
        ]
        report.set_layers(layers)
        assert len(report.layers) == 2
        assert report.layers[0]["points"] == 50

    def test_set_layers_none(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_layers(None)
        assert report.layers == []

    def test_set_statistics(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        stats = {"mean": 1.5, "min": 0.5, "max": 2.5, "std": 0.8}
        report.set_statistics(stats)
        assert report.statistics == stats

    def test_set_statistics_none(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_statistics(None)
        assert report.statistics == {}

    def test_set_quality(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        quality = {"uniformity_score": 0.92, "coverage_rate": 0.88}
        report.set_quality(quality)
        assert report.quality == quality

    def test_set_quality_none(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_quality(None)
        assert report.quality == {}


@pytest.mark.export
class TestRepairReportFigures:
    """add_comparison_figure / add_height_colormap 测试。"""

    def test_add_comparison_figure_adds_image(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        substrate = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32)
        mask = np.array([False, True, True, False])
        repair = np.array([[0.5, 0.5, 2]], dtype=np.float32)
        report.add_comparison_figure(substrate, mask, repair)
        assert len(report.images) == 1
        assert report.images[0][0] == "修复前后对比"
        assert os.path.exists(report.images[0][1])

    def test_add_comparison_figure_empty_mask(self):
        """全 False 掩码时不抛异常。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        substrate = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        mask = np.array([False, False])
        repair = np.array([[0.5, 0.5, 2]], dtype=np.float32)
        report.add_comparison_figure(substrate, mask, repair)
        assert len(report.images) == 1

    def test_add_height_colormap_adds_image(self):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        repair = np.array([
            [0, 0, 1], [1, 0, 2], [1, 1, 3], [0, 1, 2],
        ], dtype=np.float32)
        report.add_height_colormap(repair)
        assert len(report.images) == 1
        assert report.images[0][0] == "沉积体高度色温图"
        assert os.path.exists(report.images[0][1])

    def test_add_height_colormap_empty_skips(self):
        """空修复点云时跳过（不添加图）。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.add_height_colormap(np.zeros((0, 3), dtype=np.float32))
        assert len(report.images) == 0


@pytest.mark.export
class TestRepairReportGenerate:
    """generate() PDF 生成测试。"""

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_generate_creates_pdf(self, tmp_path):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(scan_id="SCAN-001", points=100, material="Cu")
        out = str(tmp_path / "report.pdf")
        ok = report.generate(out)
        assert ok is True
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_generate_returns_bool(self, tmp_path):
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        out = str(tmp_path / "report.pdf")
        result = report.generate(out)
        assert isinstance(result, bool)

    def test_generate_without_reportlab_returns_false(self, tmp_path):
        if _REPORTLAB_AVAILABLE:
            pytest.skip("reportlab 已安装，跳过失败路径测试")
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        out = str(tmp_path / "report.pdf")
        assert report.generate(out) is False

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_generate_with_all_chapters(self, tmp_path):
        """含全部章节（layers/statistics/quality）的 PDF 生成。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(scan_id="FULL-001", points=500, material="Al")
        report.set_parameters({"layer_height_mm": 2.0})
        report.set_results({"path_length_mm": 200.0})
        report.set_layers([
            {"points": 50, "avg_height": 0.5, "mass_g": 0.12},
            {"points": 30, "avg_height": 1.0, "mass_g": 0.08},
        ])
        report.set_statistics({"mean": 1.5, "min": 0.5, "max": 2.5})
        report.set_quality({"uniformity_score": 0.92})
        out = str(tmp_path / "report_full.pdf")
        ok = report.generate(out)
        assert ok is True
        assert os.path.exists(out)

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_generate_with_figures(self, tmp_path):
        """含对比图与高度色温图的 PDF 生成。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(scan_id="FIG-001", points=4, material="Cu")
        substrate = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32)
        mask = np.array([False, True, True, False])
        repair = np.array([[0.5, 0.5, 2], [0.5, 0.5, 3]], dtype=np.float32)
        report.add_comparison_figure(substrate, mask, repair)
        report.add_height_colormap(repair)
        out = str(tmp_path / "report_fig.pdf")
        ok = report.generate(out)
        assert ok is True
        assert os.path.exists(out)

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_generate_cleans_tmp_files(self, tmp_path):
        """generate 后清理临时图片文件。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(scan_id="TMP-001", points=4, material="Cu")
        repair = np.array([[0.5, 0.5, 2], [0.5, 0.5, 3]], dtype=np.float32)
        report.add_height_colormap(repair)
        tmp_files_before = list(report._tmp_files)
        assert len(tmp_files_before) > 0
        out = str(tmp_path / "report_tmp.pdf")
        report.generate(out)
        # generate 后 _tmp_files 应被清理
        assert len(report._tmp_files) == 0


# ============================================================
# 5. 导出器注册边缘用例（补充 test_pipeline.py）
# ============================================================
@pytest.mark.export
class TestExporterRegistryEdgeCases:
    """导出器注册边缘用例测试。"""

    def test_get_unknown_returns_none(self):
        from repair_app.export.pipeline import ExporterRegistry
        assert ExporterRegistry.get("totally_unknown_xyz") is None

    def test_list_returns_sorted_by_sort_order(self):
        """list 返回的导出器按 sort_order 升序。"""
        from repair_app.export.pipeline import ExporterRegistry
        exporters = ExporterRegistry.list()
        orders = [e.sort_order for e in exporters]
        assert orders == sorted(orders)

    def test_list_ready_empty_session_only_no_requires(self):
        """空 session 仅返回 requires=() 的导出器。"""
        from repair_app.export.pipeline import ExporterRegistry
        from repair_app.core.repair_session import RepairSession
        ready = [e.name for e in ExporterRegistry.list_ready(RepairSession())]
        assert "project" in ready
        assert "gcode" not in ready

    def test_builtin_exporters_count(self):
        """内置导出器数量 >= 6。"""
        from repair_app.export.pipeline import ExporterRegistry
        names = [e.name for e in ExporterRegistry.list()]
        builtins = ("gcode", "robot", "pdf", "csv", "json", "project")
        for n in builtins:
            assert n in names, f"{n} 未注册"

    def test_register_and_overwrite(self):
        """同名注册覆盖旧实例（_order 不重复）。"""
        from repair_app.export.pipeline import (
            BaseExporter, ExporterRegistry, ExportResult,
        )
        saved_exporters = dict(ExporterRegistry._exporters)
        saved_order = list(ExporterRegistry._order)
        try:

            class _V1(BaseExporter):
                name = "edge_overwrite_test"
                display_name = "V1"

                def export(self, s, p, **c):
                    return ExportResult(ok=True)

            class _V2(BaseExporter):
                name = "edge_overwrite_test"
                display_name = "V2"

                def export(self, s, p, **c):
                    return ExportResult(ok=True)

            ExporterRegistry.register(_V1())
            ExporterRegistry.register(_V2())
            assert ExporterRegistry.get("edge_overwrite_test").display_name == "V2"
            assert ExporterRegistry._order.count("edge_overwrite_test") == 1
        finally:
            ExporterRegistry._exporters = saved_exporters
            ExporterRegistry._order = saved_order

    def test_register_empty_name_raises(self):
        """空 name 注册抛 ValueError。"""
        from repair_app.export.pipeline import (
            BaseExporter, ExporterRegistry, ExportResult,
        )
        saved_exporters = dict(ExporterRegistry._exporters)
        saved_order = list(ExporterRegistry._order)
        try:

            class _NoName(BaseExporter):
                name = ""

                def export(self, s, p, **c):
                    return ExportResult(ok=True)

            with pytest.raises(ValueError):
                ExporterRegistry.register(_NoName())
        finally:
            ExporterRegistry._exporters = saved_exporters
            ExporterRegistry._order = saved_order


@pytest.mark.export
class TestExportSnakePath:
    """export_snake_path 辅助函数测试。"""

    def test_generates_correct_point_count(self):
        from repair_app.export.gcode_exporter import export_snake_path
        wp = export_snake_path(0, 10, 0, 5, z=1.0, n_passes=3, pts_per_pass=4)
        # 3 passes × 4 points = 12
        assert wp.shape == (12, 3)

    def test_z_constant(self):
        from repair_app.export.gcode_exporter import export_snake_path
        wp = export_snake_path(0, 10, 0, 5, z=2.5, n_passes=2, pts_per_pass=5)
        assert np.all(wp[:, 2] == 2.5)

    def test_zigzag_x_direction(self):
        """Zig-Zag：偶数行 X 递增，奇数行 X 递减。"""
        from repair_app.export.gcode_exporter import export_snake_path
        wp = export_snake_path(0, 10, 0, 5, z=0, n_passes=2, pts_per_pass=5)
        row0 = wp[0:5]
        row1 = wp[5:10]
        assert row0[0, 0] < row0[-1, 0]   # 递增
        assert row1[0, 0] > row1[-1, 0]   # 递减

    def test_custom_feed_rate(self):
        from repair_app.export.gcode_exporter import export_snake_path
        wp = export_snake_path(0, 10, 0, 5, z=0, feed_rate=750.0)
        # 不抛异常即通过（feed_rate 不影响几何）
        assert wp.shape[1] == 3
