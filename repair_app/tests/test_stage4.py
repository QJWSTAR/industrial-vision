"""
test_stage4.py — Stage 4 集成自检 v2.1
验证：LicenseManager / logger_config / RepairReport

运行：
    python3 -m pytest test_stage4.py -v
"""

from __future__ import annotations
import sys, os, tempfile, json
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# 1. LicenseManager 测试
# ================================================================
class TestLicenseManager:
    def test_no_license_file(self):
        from repair_app.utils.license_manager import LicenseManager
        lm = LicenseManager()
        ok = lm.load_license()
        assert not ok
        assert "不存在" in lm.error

    def test_generate_and_verify(self):
        from repair_app.utils.license_manager import generate_license, LicenseManager, _get_machine_id
        with tempfile.TemporaryDirectory() as tmpdir:
            lic_path = os.path.join(tmpdir, "test_license.key")
            generate_license(lic_path, issued_to="TestUser", days_valid=30)
            assert os.path.exists(lic_path)

            # 验证生成的 license
            with open(lic_path) as f:
                raw = json.load(f)
            assert raw["issued_to"] == "TestUser"
            assert "signature" in raw

    def test_license_data_expired(self):
        from repair_app.utils.license_manager import LicenseData
        ld = LicenseData({
            "machine_id": "test", "issued_to": "test",
            "expires_at": "2020-01-01T00:00:00",
        })
        assert ld.expired
        assert ld.days_remaining == 0

    def test_license_data_valid(self):
        from repair_app.utils.license_manager import LicenseData
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(days=100)).isoformat()
        ld = LicenseData({
            "machine_id": "test", "issued_to": "test",
            "expires_at": future,
        })
        assert not ld.expired
        assert ld.days_remaining >= 99

    def test_license_data_expiring_soon(self):
        from repair_app.utils.license_manager import LicenseData
        from datetime import datetime, timedelta
        soon = (datetime.now() + timedelta(days=5)).isoformat()
        ld = LicenseData({
            "machine_id": "test", "issued_to": "test",
            "expires_at": soon,
        })
        assert ld.expiring_soon

    def test_machine_id_consistent(self):
        from repair_app.utils.license_manager import _get_machine_id
        mid1 = _get_machine_id()
        mid2 = _get_machine_id()
        assert mid1 == mid2
        assert len(mid1) > 0


# ================================================================
# 2. Logger 测试
# ================================================================
class TestLoggerConfig:
    def test_setup_logging_no_crash(self):
        from repair_app.utils.logger_config import setup_logging
        setup_logging(level="DEBUG", console=False, app_log=False,
                      error_log=False, json_log=False)

    def test_get_logger(self):
        from repair_app.utils.logger_config import get_logger
        lg = get_logger("test_module")
        assert lg is not None

    def test_info_debug_warning_error(self):
        from repair_app.utils.logger_config import info, debug, warning, error
        info("test info message")
        debug("test debug message")
        warning("test warning")
        error("test error")

    def test_exception_logging(self):
        from repair_app.utils.logger_config import exception
        try:
            raise ValueError("test exception")
        except ValueError:
            exception("caught exception")  # 不应崩溃


# ================================================================
# 3. RepairReport 测试
# ================================================================
class TestRepairReport:
    def test_create_report_object(self):
        from repair_app.export.report_generator import RepairReport
        r = RepairReport()
        assert r.title == "冷喷涂缺陷修复报告"

    def test_set_scan_info(self):
        from repair_app.export.report_generator import RepairReport
        r = RepairReport()
        r.set_scan_info(
            scan_id="TEST-001", points=5000,
            defect_volume_mm3=12.5, defect_depth_mm=2.3,
            material="316L 不锈钢",
        )
        assert r.scan_info["scan_id"] == "TEST-001"
        assert r.scan_info["points"] == 5000

    def test_add_comparison_figure(self):
        from repair_app.export.report_generator import RepairReport
        rng = np.random.default_rng(1)
        pts = rng.uniform(-5, 5, (200, 3))
        mask = np.zeros(200, dtype=bool)
        mask[:30] = True
        repair = rng.uniform(-2, 2, (50, 3))
        repair[:, 2] += 3

        r = RepairReport()
        r.add_comparison_figure(pts, mask, repair)
        assert len(r.images) == 1
        assert "修复前后对比" in r.images[0][0]
        assert os.path.exists(r.images[0][1])

    def test_add_height_colormap(self):
        from repair_app.export.report_generator import RepairReport
        rng = np.random.default_rng(2)
        repair = rng.uniform(-2, 2, (100, 3))
        repair[:, 2] = np.abs(rng.normal(3, 1, 100))

        r = RepairReport()
        r.add_height_colormap(repair)
        assert len(r.images) >= 1

    def test_generate_pdf_or_degrade(self):
        from repair_app.export.report_generator import RepairReport, _REPORTLAB_AVAILABLE
        rng = np.random.default_rng(3)
        pts = rng.uniform(-5, 5, (200, 3))
        mask = np.zeros(200, dtype=bool)
        mask[:30] = True

        r = RepairReport()
        r.set_scan_info(scan_id="TEST", points=200)
        r.set_parameters({"粒子速度": "500 m/s"})
        r.set_results({"填充点数": "50"})
        r.add_comparison_figure(pts, mask, None)

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp_path = tmp.name
            tmp.close()  # Windows 下需先关闭句柄，避免 reportlab 写入时文件被占用
            ok = r.generate(tmp_path)
            if _REPORTLAB_AVAILABLE:
                assert ok
                assert os.path.getsize(tmp_path) > 0
            else:
                assert not ok
        finally:
            try:
                os.unlink(tmp_path)
            except (PermissionError, OSError):
                pass  # Windows 下偶发文件占用，忽略清理失败


# ================================================================
# 4. 集成导入测试
# ================================================================
class TestS4Integration:
    def test_all_modules_importable(self):
        from repair_app.utils.license_manager import LicenseManager
        from repair_app.utils.logger_config import setup_logging
        from repair_app.export.report_generator import RepairReport
        assert LicenseManager is not None
        assert RepairReport is not None
