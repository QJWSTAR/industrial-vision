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
    def test_setup_logging_no_crash(self, tmp_path, monkeypatch):
        """验证 setup_logging 正常执行且创建日志目录。"""
        # 重定向日志目录到临时目录
        monkeypatch.setattr(
            "repair_app.utils.logger_config.LOG_DIR", str(tmp_path)
        )
        from repair_app.utils.logger_config import setup_logging, LOG_DIR
        setup_logging(level="DEBUG", console=False, app_log=True,
                      error_log=True, json_log=False)
        # 验证：日志目录已创建
        assert os.path.exists(LOG_DIR), "日志目录应被创建"
        # 验证：loguru 至少有一个 handler（app_log=True 添加了文件 handler）
        try:
            from loguru import logger
            # loguru 的 _core.handlers 包含所有 handler
            assert len(logger._core.handlers) > 0, "应至少有一个日志 handler"
        except ImportError:
            pass  # 无 loguru 时退化到 stdlib logging

    def test_get_logger(self):
        from repair_app.utils.logger_config import get_logger
        lg = get_logger("test_module")
        # 验证：返回对象有标准日志方法（不论是 loguru 还是 logging.Logger）
        assert hasattr(lg, "info"), "应有 info 方法"
        assert hasattr(lg, "warning"), "应有 warning 方法"
        assert hasattr(lg, "error"), "应有 error 方法"
        assert hasattr(lg, "debug"), "应有 debug 方法"
        # 验证：可调用（不抛异常）
        lg.info("test get_logger info")

    def test_info_debug_warning_error(self, tmp_path, monkeypatch):
        """验证 4 个日志函数确实产生了日志记录（通过文件 sink 验证）。"""
        # 重定向日志目录到临时目录
        monkeypatch.setattr(
            "repair_app.utils.logger_config.LOG_DIR", str(tmp_path)
        )
        from repair_app.utils.logger_config import setup_logging, info, debug, warning, error
        setup_logging(level="DEBUG", console=False, app_log=True,
                      error_log=False, json_log=False)
        # 写入日志
        info("test info message unique_marker_12345")
        debug("test debug message unique_marker_67890")
        warning("test warning unique_marker_abcde")
        error("test error unique_marker_fghij")
        # 验证：日志已写入文件（等待 loguru enqueue flush）
        import time
        time.sleep(0.2)  # loguru enqueue=True 需要时间刷新
        log_files = list(tmp_path.glob("app_*.log"))
        assert len(log_files) > 0, "应创建 app 日志文件"
        content = log_files[0].read_text(encoding="utf-8")
        assert "unique_marker_12345" in content, "info 未写入文件"
        assert "unique_marker_67890" in content, "debug 未写入文件"
        assert "unique_marker_abcde" in content, "warning 未写入文件"
        assert "unique_marker_fghij" in content, "error 未写入文件"

    def test_exception_logging(self, tmp_path, monkeypatch):
        """验证 exception() 记录了异常 traceback。"""
        monkeypatch.setattr(
            "repair_app.utils.logger_config.LOG_DIR", str(tmp_path)
        )
        from repair_app.utils.logger_config import setup_logging, exception
        setup_logging(level="DEBUG", console=False, app_log=True,
                      error_log=True, json_log=False)
        try:
            raise ValueError("test exception unique_marker_exc_999")
        except ValueError:
            exception("caught exception unique_marker_exc_888")
        # 验证：异常日志已写入 error 日志文件
        import time
        time.sleep(0.2)
        error_files = list(tmp_path.glob("error_*.log"))
        assert len(error_files) > 0, "应创建 error 日志文件"
        content = error_files[0].read_text(encoding="utf-8")
        assert "unique_marker_exc_888" in content, "exception 消息未记录"
        assert "ValueError" in content or "unique_marker_exc_999" in content, \
            "异常类型/traceback 未记录"


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
        # 验证：类可实例化（不只是 not None）
        assert callable(LicenseManager), "LicenseManager 应为可调用类"
        assert callable(RepairReport), "RepairReport 应为可调用类"
        # 验证：实例化成功
        report = RepairReport()
        assert hasattr(report, "title"), "RepairReport 应有 title 属性"
        # 验证：setup_logging 可调用
        assert callable(setup_logging), "setup_logging 应为可调用函数"
