"""
test_stage5.py — Stage 5 集成自检 v2.1
验证：GCodeExporter / RobotExporter / CalibrationWizard / 集成

运行：
    python3 -m pytest test_stage5.py -v
"""

from __future__ import annotations
import sys, os, tempfile
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# 1. GCodeExporter 测试
# ================================================================
class TestGCodeExporter:
    def test_basic_export(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        wp = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]])
        exporter = GCodeExporter(feed_rate=500)
        gcode = exporter.export(wp)
        assert "G90" in gcode
        assert "G1" in gcode
        assert "M30" in gcode

    def test_export_to_file(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        wp = np.array([[0, 0, 0], [5, 0, 1]])
        exporter = GCodeExporter()
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False, mode="w") as tmp:
            tmp.close()
            exporter.export(wp, output_path=tmp.name)
            with open(tmp.name) as f:
                content = f.read()
            assert "G0" in content
            os.unlink(tmp.name)

    def test_snake_path(self):
        from repair_app.export.gcode_exporter import export_snake_path
        wp = export_snake_path(0, 10, 0, 20, z=1.0, n_passes=3, pts_per_pass=5)
        assert wp.shape == (15, 3)
        assert wp[0, 0] == 0
        assert wp[-1, 0] == 10  # 蛇形最后一行反向

    def test_nozzle_on_off(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        wp = np.array([[0, 0, 0], [5, 0, 0], [5, 5, 0]])
        nozzle = np.array([True, False, True])
        exporter = GCodeExporter()
        gcode = exporter.export(wp, nozzle_on_mask=nozzle)
        assert "M7" in gcode or "送粉开启" in gcode

    def test_variable_feed_rate(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        wp = np.array([[0, 0, 0], [5, 0, 0]])
        vel = np.array([500, 300])
        exporter = GCodeExporter()
        gcode = exporter.export(wp, velocities=vel)
        assert "F500" in gcode
        assert "F300" in gcode

    def test_export_validator_blocks_bad_path(self):
        from repair_app.export.export_validator import validate_toolpath
        wp = np.array([[0, 0, 0], [np.nan, 0, 0]])
        result = validate_toolpath(wp, safe_z=10)
        assert not result.ok
        assert any("NaN" in msg or "Inf" in msg for msg in result.blocking_messages)

    def test_gcode_export_blocks_unsafe_z(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        wp = np.array([[0, 0, 12], [5, 0, 12]])
        exporter = GCodeExporter(safe_z=10)
        with pytest.raises(ValueError):
            exporter.export(wp)


# ================================================================
# 2. RobotExporter 测试
# ================================================================
class TestRobotExporter:
    def test_kuka_export(self):
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        wp = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 5]])
        ex = RobotExporter(robot_type=RobotType.KUKA)
        code = ex.export(wp)
        assert "DEF csam_repair" in code
        assert "END" in code
        assert "X 0.000" in code

    def test_abb_export(self):
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        wp = np.array([[0, 0, 0], [10, 0, 0]])
        ex = RobotExporter(robot_type=RobotType.ABB)
        code = ex.export(wp)
        assert "MODULE csam_repair" in code
        assert "ENDMODULE" in code

    def test_export_to_file(self):
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        wp = np.array([[0, 0, 0], [5, 0, 1]])
        ex = RobotExporter(robot_type=RobotType.KUKA)
        with tempfile.NamedTemporaryFile(suffix=".src", delete=False) as tmp:
            tmp.close()
            ex.export(wp, output_path=tmp.name)
            with open(tmp.name) as f:
                assert "csam_repair" in f.read()
            os.unlink(tmp.name)

    def test_normal_to_euler(self):
        from repair_app.export.robot_exporter import _normal_to_euler_kuka
        a, b, c = _normal_to_euler_kuka(np.array([0, 0, 1]))
        assert abs(b) < 1  # 法向朝上 → B 角近 0

    def test_normal_to_quaternion(self):
        from repair_app.export.robot_exporter import _normal_to_quaternion_abb
        q1, q2, q3, q4 = _normal_to_quaternion_abb(np.array([0, 0, 1]))
        assert abs(q1 - 1.0) < 0.01  # 无旋转 → 单位四元数


# ================================================================
# 3. CalibrationWizard 测试
# ================================================================
class TestCalibrationWizard:
    def test_full_flow(self):
        from repair_app.utils.calibration_wizard import CalibrationWizard
        cw = CalibrationWizard()

        rec = cw.start_calibration(
            material="STEEL_316L",
            nozzle_diameter_mm=6.0,
            particle_velocity_ms=600.0,
        )
        assert rec.material == "STEEL_316L"

        cw.record_measurement(
            width_mm=6.5,
            height_mm=0.3,
            deposition_efficiency=0.75,
            notes="测试标定",
        )
        assert rec.measured_width_mm == 6.5
        assert rec.width_correction > 0

        cw.save()
        assert len(cw.records) >= 1

    def test_get_latest_for_material(self):
        from repair_app.utils.calibration_wizard import CalibrationWizard
        cw = CalibrationWizard()
        cw.start_calibration(material="COPPER", particle_velocity_ms=400)
        cw.record_measurement(6.0, 0.4)
        cw.save()

        rec = cw.get_latest_for_material("COPPER")
        assert rec is not None
        assert rec.material == "COPPER"

    def test_correction_factors(self):
        from repair_app.utils.calibration_wizard import CalibrationWizard
        cw = CalibrationWizard()
        cw.start_calibration(material="TITANIUM_TI64", nozzle_diameter_mm=5.0)
        cw.record_measurement(5.3, 0.15, 0.70)
        cw.save()

        factors = cw.get_correction_factors("TITANIUM_TI64")
        assert "width" in factors
        assert "height" in factors
        assert factors["width"] > 0

    def test_no_data_fallback(self):
        from repair_app.utils.calibration_wizard import CalibrationWizard
        cw = CalibrationWizard()
        factors = cw.get_correction_factors("NONEXISTENT")
        assert factors["width"] == 1.0


# ================================================================
# 4. 集成测试
# ================================================================
class TestS5Integration:
    def test_all_modules_importable(self):
        from repair_app.export.gcode_exporter import GCodeExporter
        from repair_app.export.export_validator import validate_toolpath
        from repair_app.export.robot_exporter import RobotExporter
        from repair_app.utils.calibration_wizard import CalibrationWizard
        assert GCodeExporter is not None
        assert validate_toolpath is not None
        assert RobotExporter is not None
