"""test_export.py — 导出模块测试

全面测试导出模块：GCodeExporter / RobotExporter / RepairReport / export_validator。
覆盖 G-code 坐标模式（G90/G91）、送粉 M 代码、进给速度、追溯元数据、文件写入、
KUKA KRL / ABB Rapid 机器人代码、mm→m 坐标转换、法向量→姿态转换、
PDF 报告生成、路径安全校验。

运行：pytest -m export -v
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


# ================================================================
# 1. GCodeExporter 测试
# ================================================================
@pytest.mark.export
class TestGCodeExporter:
    """G-code 导出器测试。"""

    def test_export_returns_nonempty_string(self, sample_waypoints):
        """export 返回非空字符串。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        # 显式传参避免依赖 schema 默认值
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        result = exporter.export(sample_waypoints, validate=False)
        assert isinstance(result, str), "export 应返回字符串"
        assert len(result) > 0, "export 返回的字符串不应为空"

    def test_output_contains_g90_absolute(self, sample_waypoints):
        """绝对坐标模式输出包含 G90。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            coordinate_mode="absolute",
        )
        result = exporter.export(sample_waypoints, validate=False)
        assert "G90" in result, "绝对坐标模式输出应包含 G90"

    def test_output_contains_g91_incremental(self, sample_waypoints):
        """增量坐标模式输出包含 G91。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            coordinate_mode="incremental",
        )
        result = exporter.export(sample_waypoints, validate=False)
        assert "G91" in result, "增量坐标模式输出应包含 G91"

    def test_output_contains_m_code(self, sample_waypoints):
        """输出包含送粉 M 代码（开启 + 关闭）。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        m_code = 8
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=m_code,
        )
        result = exporter.export(sample_waypoints, validate=False)
        # 送粉开启代码
        assert f"M{m_code}" in result, f"输出应包含 M{m_code} 送粉开启代码"
        # 送粉关闭代码 = m_code + 2
        assert f"M{m_code + 2}" in result, f"输出应包含 M{m_code + 2} 送粉关闭代码"

    def test_output_contains_feed_rate(self, sample_waypoints):
        """输出包含进给速度 F 值。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        feed_rate = 1500.0
        exporter = GCodeExporter(
            feed_rate=feed_rate, safe_z=100.0, powder_m_code=8,
        )
        result = exporter.export(sample_waypoints, validate=False)
        expected_f = f"F{feed_rate:.0f}"
        assert expected_f in result, f"输出应包含 {expected_f} 进给速度"

    def test_set_metadata_in_output(self, sample_waypoints):
        """set_metadata 后输出包含追溯元数据。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        exporter.set_metadata(
            model_version="v2.1",
            material="Cu-Al2O3",
            parameters={"layer_height": 0.5},
            license_id="LIC-001",
        )
        result = exporter.export(sample_waypoints, validate=False)
        assert "v2.1" in result, "输出应包含模型版本 v2.1"
        assert "Cu-Al2O3" in result, "输出应包含材料 Cu-Al2O3"
        assert "LIC-001" in result, "输出应包含 License ID LIC-001"
        # 参数以 key=value 格式输出
        assert "layer_height=0.5" in result, "输出应包含参数 layer_height=0.5"

    def test_file_write_success(self, sample_waypoints, tmp_path):
        """export 指定 output_path 时成功写入文件。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        exporter = GCodeExporter(feed_rate=1000.0, safe_z=100.0, powder_m_code=8)
        out_file = str(tmp_path / "test_output.nc")
        result = exporter.export(sample_waypoints, output_path=out_file, validate=False)
        assert os.path.exists(out_file), "输出文件应存在"
        # 文件内容应与返回值一致
        with open(out_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == result, "文件内容应与 export 返回值一致"
        assert len(content) > 0, "文件内容不应为空"

    def test_incremental_mode_output_structure(self, sample_waypoints):
        """增量模式输出结构正确（含 G90 临时定位 + G91 恢复）。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        exporter = GCodeExporter(
            feed_rate=1000.0, safe_z=100.0, powder_m_code=8,
            coordinate_mode="incremental",
        )
        result = exporter.export(sample_waypoints, validate=False)
        # 增量模式头部包含 G91
        assert "G91" in result, "增量模式应包含 G91"
        # 增量模式包含临时 G90 定位起点
        assert "G90" in result, "增量模式应包含 G90（临时绝对定位）"
        # 增量模式尾部恢复 G90
        assert result.count("G90") >= 2, "增量模式应至少有 2 处 G90（临时定位 + 恢复）"


# ================================================================
# 2. RobotExporter 测试
# ================================================================
@pytest.mark.export
class TestRobotExporter:
    """工业机器人轨迹导出测试。"""

    def test_kuka_contains_def_and_end(self, sample_waypoints):
        """KUKA KRL 导出包含 DEF 和 END。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        result = exporter.export(sample_waypoints)
        assert "DEF" in result, "KUKA 导出应包含 DEF"
        assert "END" in result, "KUKA 导出应包含 END"

    def test_abb_contains_movel(self, sample_waypoints):
        """ABB Rapid 导出包含 MoveL。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        exporter = RobotExporter(robot_type=RobotType.ABB)
        result = exporter.export(sample_waypoints)
        assert "MoveL" in result, "ABB 导出应包含 MoveL"

    def test_coordinate_conversion_mm_to_m(self, sample_waypoints):
        """坐标从 mm 转换为 m（除以 1000）。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        result = exporter.export(sample_waypoints)
        # 取第一个航点的 X 坐标（mm），验证输出中包含转换后的 m 值
        first_x_mm = float(sample_waypoints[0, 0])
        first_x_m = first_x_mm / 1000.0
        expected_str = f"X {first_x_m:.3f}"
        assert expected_str in result, (
            f"输出应包含转换后的米坐标 '{expected_str}'，"
            f"原始 mm 值为 {first_x_mm}"
        )

    def test_normal_to_euler_kuka(self):
        """法向量→KUKA ABC 欧拉角转换。"""
        from repair_app.export.robot_exporter import _normal_to_euler_kuka
        # Z 轴方向法向量 → A=0, B=0, C=0
        normal = np.array([0.0, 0.0, 1.0])
        a, b, c = _normal_to_euler_kuka(normal)
        assert isinstance(a, float), "A 角应为 float"
        assert isinstance(b, float), "B 角应为 float"
        assert isinstance(c, float), "C 角应为 float"
        assert abs(a) < 1e-6, f"Z 轴法向量 A 角应接近 0，实际 {a}"
        assert abs(b) < 1e-6, f"Z 轴法向量 B 角应接近 0，实际 {b}"
        assert c == 0.0, f"C 角应为 0，实际 {c}"

    def test_normal_to_quaternion_abb(self):
        """法向量→ABB 四元数转换。"""
        from repair_app.export.robot_exporter import _normal_to_quaternion_abb
        # Z 轴方向法向量 → 单位四元数 (1, 0, 0, 0)
        normal = np.array([0.0, 0.0, 1.0])
        q1, q2, q3, q4 = _normal_to_quaternion_abb(normal)
        assert isinstance(q1, float), "q1 应为 float"
        assert isinstance(q2, float), "q2 应为 float"
        assert isinstance(q3, float), "q3 应为 float"
        assert isinstance(q4, float), "q4 应为 float"
        assert abs(q1 - 1.0) < 1e-6, f"Z 轴法向量 q1 应为 1，实际 {q1}"
        assert abs(q2) < 1e-6, f"q2 应接近 0，实际 {q2}"
        assert abs(q3) < 1e-6, f"q3 应接近 0，实际 {q3}"
        assert abs(q4) < 1e-6, f"q4 应接近 0，实际 {q4}"

    def test_kuka_file_write(self, sample_waypoints, tmp_path):
        """KUKA 导出指定 output_path 时成功写入文件。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        exporter = RobotExporter(robot_type=RobotType.KUKA)
        out_file = str(tmp_path / "test_robot.krl")
        result = exporter.export(sample_waypoints, output_path=out_file)
        assert os.path.exists(out_file), "KUKA 输出文件应存在"
        with open(out_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == result, "文件内容应与返回值一致"


# ================================================================
# 3. RepairReport 测试
# ================================================================
@pytest.mark.export
class TestRepairReport:
    """修复报告生成器测试。"""

    def test_report_creation_and_scan_info(self):
        """RepairReport 创建 + set_scan_info 设置正确。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(
            scan_id="SCAN-001",
            points=10000,
            defect_volume_mm3=125.5,
            defect_depth_mm=2.3,
            material="Cu",
        )
        # 验证 scan_info 各字段
        assert report.scan_info["scan_id"] == "SCAN-001"
        assert report.scan_info["points"] == 10000
        assert report.scan_info["defect_volume_mm3"] == 125.5
        assert report.scan_info["defect_depth_mm"] == 2.3
        assert report.scan_info["material"] == "Cu"

    def test_generate_returns_bool(self, tmp_path):
        """generate 返回 bool 类型。"""
        from repair_app.export.report_generator import RepairReport
        report = RepairReport()
        report.set_scan_info(scan_id="SCAN-001", points=100, material="Cu")
        out_file = str(tmp_path / "report.pdf")
        result = report.generate(out_file)
        assert isinstance(result, bool), "generate 应返回 bool"

    def test_generate_creates_pdf_file(self, tmp_path):
        """reportlab 可用时 generate 成功创建 PDF 文件。"""
        from repair_app.export.report_generator import RepairReport, _REPORTLAB_AVAILABLE
        if not _REPORTLAB_AVAILABLE:
            pytest.skip("reportlab 未安装，跳过 PDF 生成测试")
        report = RepairReport()
        report.set_scan_info(scan_id="SCAN-001", points=100, material="Cu")
        out_file = str(tmp_path / "report.pdf")
        result = report.generate(out_file)
        assert result is True, "reportlab 可用时 generate 应返回 True"
        assert os.path.exists(out_file), "PDF 文件应存在"
        assert os.path.getsize(out_file) > 0, "PDF 文件不应为空"


# ================================================================
# 4. export_validator 测试
# ================================================================
@pytest.mark.export
class TestExportValidator:
    """导出路径校验器测试。"""

    def test_validate_returns_result(self, sample_waypoints):
        """validate_toolpath 返回 ExportValidationResult 且含 ok/issues。"""
        from repair_app.export.export_validator import (
            validate_toolpath, ExportValidationResult,
        )
        result = validate_toolpath(sample_waypoints)
        assert isinstance(result, ExportValidationResult), "应返回 ExportValidationResult"
        assert isinstance(result.ok, bool), "ok 应为 bool"
        assert isinstance(result.issues, list), "issues 应为 list"

    def test_validate_valid_waypoints(self):
        """有效航点校验通过（ok=True）。"""
        from repair_app.export.export_validator import validate_toolpath
        # 构造有效航点：不重复、间距合理、无 NaN、safe_z 足够高
        waypoints = np.array([
            [0, 0, 1],
            [1, 0, 1],
            [2, 0, 1],
            [3, 0, 1],
        ], dtype=np.float32)
        result = validate_toolpath(waypoints, safe_z=100.0)
        assert result.ok is True, "有效航点应校验通过"
        assert len(result.blocking_messages) == 0, "有效航点不应有阻塞错误"

    def test_validate_invalid_shape(self):
        """无效形状（1D 数组）校验失败。"""
        from repair_app.export.export_validator import validate_toolpath
        bad_waypoints = np.array([1, 2, 3], dtype=np.float32)
        result = validate_toolpath(bad_waypoints)
        assert result.ok is False, "无效形状应校验失败"
        assert len(result.blocking_messages) > 0, "应有阻塞错误"

    def test_validate_nan_coordinates(self):
        """NaN 坐标校验失败。"""
        from repair_app.export.export_validator import validate_toolpath
        bad_waypoints = np.array([
            [0, 0, 1],
            [np.nan, 0, 1],
            [2, 0, 1],
        ], dtype=np.float32)
        result = validate_toolpath(bad_waypoints)
        assert result.ok is False, "NaN 坐标应校验失败"

    def test_validate_unsafe_z(self):
        """安全高度不足校验失败。"""
        from repair_app.export.export_validator import validate_toolpath
        waypoints = np.array([
            [0, 0, 10],
            [1, 0, 10],
        ], dtype=np.float32)
        # safe_z (5) < z_max (10) → 不安全
        result = validate_toolpath(waypoints, safe_z=5.0)
        assert result.ok is False, "安全高度不足应校验失败"
        assert len(result.blocking_messages) > 0, "应有安全高度阻塞错误"
