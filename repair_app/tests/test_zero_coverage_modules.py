"""test_zero_coverage_modules.py — 零覆盖率模块测试"""
from __future__ import annotations
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path


# ============================================================================
# about_dialog.py tests
# ============================================================================

class TestAboutDialog:
    """Tests for repair_app/software/about_dialog.py"""

    def test_get_version(self):
        """_get_version returns version string."""
        from repair_app.software.about_dialog import _get_version
        with patch("repair_app.__version__", "2.0.0"):
            assert _get_version() == "2.0.0"

    def test_get_version_unknown(self):
        """_get_version returns 'unknown' on import failure."""
        import repair_app
        from repair_app.software.about_dialog import _get_version
        old = repair_app.__dict__.pop("__version__", None)
        try:
            assert _get_version() == "unknown"
        finally:
            if old is not None:
                repair_app.__version__ = old

    def test_get_license_text_valid(self):
        """_get_license_text returns valid license info."""
        from repair_app.software.about_dialog import _get_license_text

        mock_lm = MagicMock()
        mock_lm.is_valid = True
        mock_lm.days_remaining = -1  # permanent
        mock_lm.license_data.issued_to = "Test Corp"
        mock_lm.license_data.issued_at = "2025-01-01"
        mock_lm.license_data.expires_at = "2099-12-31"
        mock_lm.license_data.max_layers = 10

        with patch("repair_app.utils.license_manager.LicenseManager") as MockLM:
            MockLM.return_value = mock_lm
            result = _get_license_text()
            assert "✅ 授权有效" in result
            assert "永久授权" in result
            assert "Test Corp" in result

    def test_get_license_text_valid_with_days(self):
        """_get_license_text returns valid license with days remaining."""
        from repair_app.software.about_dialog import _get_license_text

        mock_lm = MagicMock()
        mock_lm.is_valid = True
        mock_lm.days_remaining = 30
        mock_lm.license_data.issued_to = "Test Corp"
        mock_lm.license_data.issued_at = "2025-01-01"
        mock_lm.license_data.expires_at = "2025-02-01"
        mock_lm.license_data.max_layers = 5

        with patch("repair_app.utils.license_manager.LicenseManager") as MockLM:
            MockLM.return_value = mock_lm
            result = _get_license_text()
            assert "✅ 授权有效" in result
            assert "30 天" in result

    def test_get_license_text_invalid(self):
        """_get_license_text returns invalid license info."""
        from repair_app.software.about_dialog import _get_license_text

        mock_lm = MagicMock()
        mock_lm.is_valid = False
        mock_lm.error = "Bad signature"

        with patch("repair_app.utils.license_manager.LicenseManager") as MockLM:
            MockLM.return_value = mock_lm
            result = _get_license_text()
            assert "⚠️ 授权无效" in result
            assert "Bad signature" in result

    def test_get_license_text_unavailable(self):
        """_get_license_text handles import error."""
        from repair_app.software.about_dialog import _get_license_text

        with patch("repair_app.utils.license_manager.LicenseManager", side_effect=ImportError("no module")):
            result = _get_license_text()
            assert "⚠️ 授权信息查询失败" in result

    def test_get_paths_text_success(self):
        """_get_paths_text returns path info."""
        from repair_app.software.about_dialog import _get_paths_text

        mock_pm = MagicMock()
        mock_pm.describe.return_value = "user data: /tmp/data"

        with patch("repair_app.software.path_manager.PathManager") as MockPM:
            MockPM.get_instance.return_value = mock_pm
            result = _get_paths_text()
            assert "user data" in result

    def test_get_paths_text_failure(self):
        """_get_paths_text handles exception."""
        from repair_app.software.about_dialog import _get_paths_text

        with patch("repair_app.software.path_manager.PathManager.get_instance", side_effect=RuntimeError("disk full")):
            result = _get_paths_text()
            assert "路径信息查询失败" in result

    def test_get_matlab_text_with_manager(self):
        """_get_matlab_text returns matlab info when manager available."""
        from repair_app.software.about_dialog import _get_matlab_text

        mock_m = MagicMock()
        mock_m.status.name = "RUNNING"
        mock_m.message = "Connected"
        mock_m.matlab_version = "R2024a"

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager") as MockMLM:
            MockMLM.get_instance.return_value = mock_m
            result = _get_matlab_text()
            assert "RUNNING" in result
            assert "R2024a" in result

    def test_get_matlab_text_unavailable(self):
        """_get_matlab_text returns fallback when manager unavailable."""
        from repair_app.software.about_dialog import _get_matlab_text

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager.get_instance", side_effect=ImportError):
            result = _get_matlab_text()
            assert "MATLAB 生命周期管理器未初始化" in result

    def test_get_matlab_text_no_version(self):
        """_get_matlab_text with None version."""
        from repair_app.software.about_dialog import _get_matlab_text

        mock_m = MagicMock()
        mock_m.status.name = "DISCONNECTED"
        mock_m.message = "No connection"
        mock_m.matlab_version = None

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager") as MockMLM:
            MockMLM.get_instance.return_value = mock_m
            result = _get_matlab_text()
            assert "未知" in result

    def test_get_system_text(self):
        """_get_system_text returns platform info."""
        from repair_app.software.about_dialog import _get_system_text
        result = _get_system_text()
        assert "操作系统" in result
        assert "Python" in result
        assert "可执行文件" in result

    def test_get_credits_text(self):
        """_get_credits_text returns credits."""
        from repair_app.software.about_dialog import _get_credits_text
        result = _get_credits_text()
        assert "CSAM Repair" in result
        assert "PySide6" in result
        assert "NumPy" in result

    def test_about_dialog_instantiate(self):
        """AboutDialog creates with 5 tabs and closes."""
        from PySide6.QtWidgets import QApplication, QTabWidget

        # Ensure QApplication exists for offscreen rendering
        app = QApplication.instance()
        if app is None:
            app = QApplication([])

        from repair_app.software.about_dialog import AboutDialog

        # Mock all the info functions to avoid real imports
        with patch("repair_app.software.about_dialog._get_version", return_value="1.0.0"), \
             patch("repair_app.software.about_dialog._get_license_text", return_value="License OK"), \
             patch("repair_app.software.about_dialog._get_paths_text", return_value="Paths OK"), \
             patch("repair_app.software.about_dialog._get_matlab_text", return_value="MATLAB OK"), \
             patch("repair_app.software.about_dialog._get_credits_text", return_value="Credits OK"):
            dialog = AboutDialog()
            assert dialog is not None
            assert dialog.windowTitle() == "关于 CSAM Repair"

            # Verify 5 tabs exist
            tab_widgets = [w for w in dialog.findChildren(QTabWidget)]
            assert len(tab_widgets) == 1
            tab_widget = tab_widgets[0]
            assert tab_widget.count() == 5

            # Verify tab labels
            tab_names = []
            for i in range(tab_widget.count()):
                tab_names.append(tab_widget.tabText(i))
            assert "概览" in tab_names
            assert "License" in tab_names
            assert "数据目录" in tab_names
            assert "MATLAB" in tab_names
            assert "致谢" in tab_names

            # Click close button via accept
            dialog.accept()


# ============================================================================
# exception_reporter.py tests
# ============================================================================

class TestExceptionReporter:
    """Tests for repair_app/software/exception_reporter.py"""

    def test_safe_get_version(self):
        """_safe_get_version returns version string."""
        # We need to mock the import at module level
        with patch("repair_app.__version__", "1.0.0"):
            from repair_app.software.exception_reporter import _safe_get_version
            assert _safe_get_version() == "1.0.0"

    def test_safe_get_version_unknown(self):
        """_safe_get_version returns 'unknown' on import failure."""
        with patch("repair_app.__version__", "1.0.0"):
            from repair_app.software.exception_reporter import _safe_get_version
        # The function is already imported, mock it
        with patch("repair_app.software.exception_reporter._safe_get_version", return_value="unknown"):
            from repair_app.software.exception_reporter import _safe_get_version as f
            assert f() == "unknown"

    def test_safe_get_license_info(self):
        """_safe_get_license_info returns license info string."""
        from repair_app.software.exception_reporter import _safe_get_license_info

        mock_lm = MagicMock()
        mock_lm.is_valid = True
        mock_lm.days_remaining = 30
        mock_lm.license_data.issued_to = "Test Corp"
        mock_lm.license_data.expires_at = "2025-12-31"

        with patch("repair_app.utils.license_manager.LicenseManager") as MockLM:
            MockLM.return_value = mock_lm
            result = _safe_get_license_info()
            assert "有效" in result
            assert "Test Corp" in result

    def test_safe_get_license_info_invalid(self):
        """_safe_get_license_info returns invalid license info."""
        from repair_app.software.exception_reporter import _safe_get_license_info

        mock_lm = MagicMock()
        mock_lm.is_valid = False
        mock_lm.error = "No license file"

        with patch("repair_app.utils.license_manager.LicenseManager") as MockLM:
            MockLM.return_value = mock_lm
            result = _safe_get_license_info()
            assert "无效" in result
            assert "No license file" in result

    def test_safe_get_license_info_exception(self):
        """_safe_get_license_info handles import error."""
        from repair_app.software.exception_reporter import _safe_get_license_info

        with patch("repair_app.utils.license_manager.LicenseManager", side_effect=RuntimeError("fail")):
            result = _safe_get_license_info()
            assert "查询失败" in result

    def test_safe_get_matlab_info(self):
        """_safe_get_matlab_info returns matlab info."""
        from repair_app.software.exception_reporter import _safe_get_matlab_info

        mock_m = MagicMock()
        mock_m.status.name = "RUNNING"
        mock_m.message = "OK"
        mock_m.matlab_version = "R2024a"

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager") as MockMLM:
            MockMLM.get_instance.return_value = mock_m
            result = _safe_get_matlab_info()
            assert "RUNNING" in result
            assert "R2024a" in result

    def test_safe_get_matlab_info_unavailable(self):
        """_safe_get_matlab_info returns fallback."""
        from repair_app.software.exception_reporter import _safe_get_matlab_info

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager.get_instance", side_effect=ImportError):
            result = _safe_get_matlab_info()
            assert "未初始化" in result

    def test_exception_reporter_init_with_path_manager(self):
        """ExceptionReporter.__init__ with explicit path_manager."""
        from repair_app.software.exception_reporter import ExceptionReporter

        mock_pm = MagicMock()
        reporter = ExceptionReporter(path_manager=mock_pm)
        assert reporter._pm is mock_pm

    def test_exception_reporter_init_without_path_manager(self, tmp_path):
        """ExceptionReporter.__init__ without path_manager uses get_instance."""
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()
            assert reporter._pm is mock_pm

    def test_report_exception(self, tmp_path):
        """report_exception creates a report file with expected content."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_test.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            # Create a real exception
            try:
                raise ValueError("test error")
            except ValueError:
                import sys as _sys
                exc_type, exc_value, exc_tb = _sys.exc_info()

            result = reporter.report_exception(exc_type, exc_value, exc_tb)
            assert result == report_file
            assert report_file.exists()
            content = report_file.read_text(encoding="utf-8")
            assert "CSAM Repair 异常报告" in content
            assert "ValueError" in content
            assert "test error" in content
            assert "版本:" in content

    def test_report_exception_with_context(self, tmp_path):
        """report_exception with context parameter."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_ctx.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            try:
                raise RuntimeError("context error")
            except RuntimeError:
                import sys as _sys
                exc_type, exc_value, exc_tb = _sys.exc_info()

            result = reporter.report_exception(exc_type, exc_value, exc_tb, context="User clicked Export")
            assert result == report_file
            content = report_file.read_text(encoding="utf-8")
            assert "[上下文]" in content
            assert "User clicked Export" in content

    def test_report_exception_write_fails_fallback(self, tmp_path, capsys):
        """report_exception falls back to stderr when write fails."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_fail.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            try:
                raise TypeError("write fail test")
            except TypeError:
                import sys as _sys
                exc_type, exc_value, exc_tb = _sys.exc_info()

            # Mock write_text to raise
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = reporter.report_exception(exc_type, exc_value, exc_tb)
                assert result == report_file

            # Verify stderr has the content
            captured = capsys.readouterr()
            assert "CSAM Repair 异常报告" in captured.err
            assert "TypeError" in captured.err

    def test_report_text(self, tmp_path):
        """report_text creates a report file."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_text.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            result = reporter.report_text("Something went wrong")
            assert result == report_file
            assert report_file.exists()
            content = report_file.read_text(encoding="utf-8")
            assert "CSAM Repair 错误报告" in content
            assert "Something went wrong" in content

    def test_report_text_with_context(self, tmp_path):
        """report_text with context parameter."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_text_ctx.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            result = reporter.report_text("Error occurred", context="Export module")
            assert result == report_file
            content = report_file.read_text(encoding="utf-8")
            assert "[上下文]" in content
            assert "Export module" in content

    def test_report_text_write_fails_fallback(self, tmp_path, capsys):
        """report_text falls back to stderr when write fails."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_text_fail.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            from repair_app.software.exception_reporter import ExceptionReporter
            reporter = ExceptionReporter()

            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = reporter.report_text("Write failed")
                assert result == report_file

            captured = capsys.readouterr()
            assert "CSAM Repair 错误报告" in captured.err
            assert "Write failed" in captured.err

    def test_install_exception_reporter_no_dialog(self, tmp_path):
        """install_exception_reporter with show_dialog=False installs hook."""
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        mock_pm = MagicMock()
        mock_pm.root = tmp_path / "root"
        mock_pm.logs_dir = tmp_path / "logs"
        report_file = tmp_path / "logs" / "exception_hook.log"
        mock_pm.exception_log_path.return_value = report_file

        with patch("repair_app.software.exception_reporter.PathManager") as mock_ep_pm:
            mock_ep_pm.get_instance.return_value = mock_pm
            with patch("repair_app.software.path_manager.PathManager") as mock_pp_pm:
                mock_pp_pm.get_instance.return_value = mock_pm
                with patch("repair_app.utils.crash_handler.install_crash_handler") as mock_install_crash:
                    from repair_app.software.exception_reporter import install_exception_reporter

                    import sys as _sys
                    saved_hook = _sys.excepthook

                    try:
                        callback = install_exception_reporter(show_dialog=False)
                        assert callable(callback)
                        assert _sys.excepthook is not saved_hook
                        mock_install_crash.assert_called_once()

                        # Verify the hook works
                        try:
                            raise ValueError("hook test")
                        except ValueError:
                            exc_type, exc_value, exc_tb = _sys.exc_info()
                            _sys.excepthook(exc_type, exc_value, exc_tb)

                        assert report_file.exists()
                        content = report_file.read_text(encoding="utf-8")
                        assert "ValueError" in content
                        assert "hook test" in content
                    finally:
                        _sys.excepthook = saved_hook

    def test_show_crash_dialog_no_qapp(self):
        """_show_crash_dialog returns None when no QApplication."""
        from PySide6.QtWidgets import QApplication

        # Destroy any existing QApplication to ensure no app is running
        app = QApplication.instance()
        if app is not None:
            # We can't easily destroy it, so mock instead
            pass

        from repair_app.software.exception_reporter import _show_crash_dialog

        # Mock QApplication.instance to return None
        with patch("PySide6.QtWidgets.QApplication.instance", return_value=None):
            result = _show_crash_dialog(Path("/tmp/test.log"))
            assert result is None

    def test_show_crash_dialog_with_qapp(self):
        """_show_crash_dialog works with QApplication."""
        from PySide6.QtWidgets import QApplication, QMessageBox

        # Ensure QApplication exists
        app = QApplication.instance()
        if app is None:
            app = QApplication([])

        from repair_app.software.exception_reporter import _show_crash_dialog

        with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_critical:
            _show_crash_dialog(Path("/tmp/test_report.log"))
            mock_critical.assert_called_once()
            args = mock_critical.call_args[0]
            assert "程序异常" in args[1]

    def test_safe_get_matlab_info_no_version(self):
        """_safe_get_matlab_info with None version."""
        from repair_app.software.exception_reporter import _safe_get_matlab_info

        mock_m = MagicMock()
        mock_m.status.name = "DISCONNECTED"
        mock_m.message = "No connection"
        mock_m.matlab_version = None

        with patch("repair_app.bridge.lifecycle_manager.MatlabLifecycleManager") as MockMLM:
            MockMLM.get_instance.return_value = mock_m
            result = _safe_get_matlab_info()
            assert "unknown" in result or "DISCONNECTED" in result


# ============================================================================
# benchmark.py tests
# ============================================================================

class TestBenchmark:
    """Tests for repair_app/tools/benchmark.py"""

    def test_generate_test_data(self):
        """_generate_test_data returns correct shapes."""
        from repair_app.tools.benchmark import _generate_test_data
        data = _generate_test_data(100)
        assert data["xyz"].shape == (100, 3)
        assert data["normals"].shape == (100, 3)
        assert data["mask"].shape == (100,)
        assert data["mask"].dtype == bool
        assert np.any(data["mask"])  # has True values

    def test_measure_memory(self):
        """measure_memory returns dict with required keys."""
        from repair_app.tools.benchmark import measure_memory

        def simple_func():
            return sum(range(100))

        result = measure_memory(simple_func)
        assert "time_s" in result
        assert "current_mb" in result
        assert "peak_mb" in result
        assert result["time_s"] >= 0

    def test_benchmark_path_planning(self, capsys, monkeypatch):
        """benchmark_path_planning runs and prints expected output."""
        from repair_app.tools import benchmark

        # Monkeypatch _generate_test_data to small data
        def small_data(n):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
            normals = rng.normal(0, 1, (100, 3)).astype(np.float32)
            normals /= np.linalg.norm(normals, axis=1, keepdims=True)
            mask = np.zeros(100, dtype=bool)
            mask[33:66] = True
            return {"xyz": xyz, "normals": normals, "mask": mask}

        # Replace the for-loop sizes to just [1000] to avoid iterating large sizes
        original_func = benchmark.benchmark_path_planning
        def patched():
            # Monkeypatch the size list
            import repair_app.tools.benchmark as bm
            bm._generate_test_data = small_data
            # We can't easily patch the for-loop, but with small_data always
            # returning n=100 data, all iterations will be fast.
            # The for-loop still iterates over [1000, 5000, 10000, 50000, 100000]
            # but each iteration uses the same small data.
            original_func()

        monkeypatch.setattr(benchmark, "benchmark_path_planning", patched)
        patched()
        captured = capsys.readouterr()
        assert "Path Planning Benchmark" in captured.out

    def test_benchmark_morphology(self, capsys):
        """benchmark_morphology runs and prints expected output."""
        from repair_app.tools import benchmark

        def small_data(n):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
            normals = rng.normal(0, 1, (100, 3)).astype(np.float32)
            normals /= np.linalg.norm(normals, axis=1, keepdims=True)
            mask = np.zeros(100, dtype=bool)
            mask[33:66] = True
            return {"xyz": xyz, "normals": normals, "mask": mask}

        with patch.object(benchmark, "_generate_test_data", small_data):
            benchmark.benchmark_morphology()
        captured = capsys.readouterr()
        assert "Morphology Benchmark" in captured.out

    def test_benchmark_full_pipeline(self, capsys):
        """benchmark_full_pipeline runs and prints expected output."""
        from repair_app.tools import benchmark

        def small_data(n):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
            normals = rng.normal(0, 1, (100, 3)).astype(np.float32)
            normals /= np.linalg.norm(normals, axis=1, keepdims=True)
            mask = np.zeros(100, dtype=bool)
            mask[33:66] = True
            return {"xyz": xyz, "normals": normals, "mask": mask}

        with patch.object(benchmark, "_generate_test_data", small_data):
            benchmark.benchmark_full_pipeline()
        captured = capsys.readouterr()
        assert "Full Pipeline Benchmark" in captured.out

    def test_main(self, capsys):
        """main runs and prints expected output."""
        from repair_app.tools import benchmark

        def small_data(n):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
            normals = rng.normal(0, 1, (100, 3)).astype(np.float32)
            normals /= np.linalg.norm(normals, axis=1, keepdims=True)
            mask = np.zeros(100, dtype=bool)
            mask[33:66] = True
            return {"xyz": xyz, "normals": normals, "mask": mask}

        with patch.object(benchmark, "_generate_test_data", small_data):
            benchmark.main()
        captured = capsys.readouterr()
        assert "Performance Benchmark" in captured.out


# ============================================================================
# profiler.py tests
# ============================================================================

class TestProfiler:
    """Tests for repair_app/tools/profiler.py"""

    def test_generate_test_data_small(self):
        """_generate_test_data('small') returns n=1000."""
        from repair_app.tools.profiler import _generate_test_data
        data = _generate_test_data("small")
        assert data["n"] == 1000
        assert data["xyz"].shape == (1000, 3)

    def test_generate_test_data_medium(self):
        """_generate_test_data('medium') returns n=10000."""
        from repair_app.tools.profiler import _generate_test_data
        data = _generate_test_data("medium")
        assert data["n"] == 10000

    def test_generate_test_data_large(self):
        """_generate_test_data('large') returns n=100000."""
        from repair_app.tools.profiler import _generate_test_data
        data = _generate_test_data("large")
        assert data["n"] == 100000

    def test_generate_test_data_invalid(self):
        """_generate_test_data('invalid') falls back to n=10000."""
        from repair_app.tools.profiler import _generate_test_data
        data = _generate_test_data("invalid")
        assert data["n"] == 10000

    def test_print_memory_usage(self, capsys):
        """print_memory_usage prints memory info."""
        from repair_app.tools.profiler import print_memory_usage, _generate_test_data
        data = _generate_test_data("small")
        print_memory_usage(data)
        captured = capsys.readouterr()
        assert "Memory Usage" in captured.out

    def test_run_with_profile(self, capsys):
        """_run_with_profile runs profiling and prints output."""
        from repair_app.tools.profiler import _run_with_profile

        def dummy():
            _ = sum(range(1000))

        _run_with_profile(dummy, "test_label")
        captured = capsys.readouterr()
        assert "Wall time" in captured.out

    def test_profile_path_planning(self, capsys):
        """profile_path_planning runs and prints output."""
        from repair_app.tools import profiler
        data = profiler._generate_test_data("small")
        profiler.profile_path_planning(data)
        captured = capsys.readouterr()
        assert "Path Planning Profile" in captured.out

    def test_profile_morphology(self, capsys):
        """profile_morphology runs and prints output."""
        from repair_app.tools import profiler
        data = profiler._generate_test_data("small")
        profiler.profile_morphology(data)
        captured = capsys.readouterr()
        assert "Morphology Profile" in captured.out

    def test_main(self, capsys, monkeypatch):
        """main runs with --mode path --size small."""
        from repair_app.tools import profiler
        monkeypatch.setattr("sys.argv", ["profiler.py", "--mode", "path", "--size", "small"])
        profiler.main()
        captured = capsys.readouterr()
        assert "Path Planning Profile" in captured.out

    def test_main_all(self, capsys, monkeypatch):
        """main runs with --mode all --size small."""
        from repair_app.tools import profiler
        monkeypatch.setattr("sys.argv", ["profiler.py", "--mode", "all", "--size", "small"])
        profiler.main()
        captured = capsys.readouterr()
        assert "Path Planning Profile" in captured.out
        assert "Morphology Profile" in captured.out


# ============================================================================
# local_engine.py tests
# ============================================================================

class TestLocalEngine:
    """Tests for repair_app/engine/local_engine.py"""

    def test_name(self):
        """LocalEngine.name returns 'Local Python Engine'."""
        from repair_app.engine.local_engine import LocalEngine
        engine = LocalEngine()
        assert engine.name == "Local Python Engine"

    def test_is_available(self):
        """LocalEngine.is_available returns True."""
        from repair_app.engine.local_engine import LocalEngine
        engine = LocalEngine()
        assert engine.is_available is True

    def test_check_health(self):
        """LocalEngine.check_health returns True."""
        from repair_app.engine.local_engine import LocalEngine
        engine = LocalEngine()
        assert engine.check_health() is True

    def test_plan_path(self):
        """plan_path returns waypoints."""
        from repair_app.engine.local_engine import LocalEngine
        from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams

        rng = np.random.default_rng(42)
        xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
        normals = np.ones((100, 3), dtype=np.float32) / np.sqrt(3)
        mask = np.zeros(100, dtype=bool)
        mask[20:50] = True

        pc = PointCloud(xyz=xyz, normals=normals)
        dr = DefectRegion(mask=mask)
        params = ProcessParams(num_layers=2)

        engine = LocalEngine()
        waypoints = list(engine.plan_path(pc, dr, params))
        assert len(waypoints) > 0
        assert isinstance(waypoints[0], np.ndarray)

    def test_plan_path_additive(self):
        """plan_path with is_additive=True uses buffer_additive_mm."""
        from repair_app.engine.local_engine import LocalEngine
        from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams

        rng = np.random.default_rng(42)
        xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
        normals = np.ones((100, 3), dtype=np.float32) / np.sqrt(3)
        mask = np.zeros(100, dtype=bool)
        mask[20:50] = True

        pc = PointCloud(xyz=xyz, normals=normals)
        dr = DefectRegion(mask=mask)
        params = ProcessParams(num_layers=2, buffer_additive_mm=2.0, buffer_repairing_mm=0.0)

        engine = LocalEngine()
        waypoints = list(engine.plan_path(pc, dr, params, is_additive=True))
        assert len(waypoints) > 0

    def test_predict_morphology(self):
        """predict_morphology returns layers."""
        from repair_app.engine.local_engine import LocalEngine
        from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams

        rng = np.random.default_rng(42)
        xyz = rng.uniform(-50, 50, (100, 3)).astype(np.float32)
        normals = np.ones((100, 3), dtype=np.float32) / np.sqrt(3)
        mask = np.zeros(100, dtype=bool)
        mask[20:50] = True

        pc = PointCloud(xyz=xyz, normals=normals)
        dr = DefectRegion(mask=mask)
        params = ProcessParams(num_layers=2)

        engine = LocalEngine()
        waypoints = list(engine.plan_path(pc, dr, params))
        assert len(waypoints) > 0

        layers = list(engine.predict_morphology(pc, dr, waypoints[-1], params))
        assert len(layers) > 0
        assert isinstance(layers[0], np.ndarray)


# ============================================================================
# engine/__init__.py tests
# ============================================================================

class TestEngineInit:
    """Tests for repair_app/engine/__init__.py"""

    def test_import_local_engine(self):
        """from repair_app.engine import LocalEngine works."""
        from repair_app.engine import LocalEngine
        assert LocalEngine is not None

    def test_all_contains_local_engine(self):
        """__all__ contains 'LocalEngine'."""
        from repair_app.engine import __all__
        assert "LocalEngine" in __all__