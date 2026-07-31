"""test_ui_supplement.py — 低覆盖 UI 模块补充测试

覆盖：
- ui/dialogs.py: ErrorDialog / LoadingDialog / _EnsureReadyWorker /
  RobotExportDialog / CalibrationDialog / CoordinateSystemDialog /
  ParameterPresetDialog / BatchValidationDialog / ParameterValidatorDialog / classify_error
- ui/context_menu.py: ContextMenuManager
- ui/profile_result_panel.py: ProfileResultPanel / _MetricCard / decode_binary_stl

使用 conftest.py 的 qapp fixture（session 级别，offscreen 模式）。
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Qt 离屏模式 + Python 算法引擎（必须在导入 PySide6 之前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")

import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox


# ============================================================
# 共享 fixture：mock QMessageBox 避免模态对话框阻塞
# ============================================================
@pytest.fixture(autouse=True)
def _mock_message_boxes(monkeypatch):
    """自动 mock QMessageBox 静态方法，避免模态对话框阻塞测试。"""
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: None)


# ============================================================
# 辅助函数
# ============================================================
def _cleanup_widget(widget, qapp):
    """清理 widget：关闭 + deleteLater + processEvents，避免泄漏。"""
    try:
        widget.close()
    except Exception:
        pass
    widget.deleteLater()
    qapp.processEvents()


def _make_stl_bytes(n_faces: int = 2) -> bytes:
    """构造最小有效的二进制 STL 字节串。"""
    header = b"\x00" * 80
    count = struct.pack("<I", n_faces)
    faces = b""
    for i in range(n_faces):
        normal = struct.pack("<3f", 0.0, 0.0, 1.0)
        v1 = struct.pack("<3f", float(i), 0.0, 0.0)
        v2 = struct.pack("<3f", float(i + 1), 1.0, 0.1)
        v3 = struct.pack("<3f", float(i), 1.0, 0.0)
        attr = b"\x00\x00"
        faces += normal + v1 + v2 + v3 + attr
    return header + count + faces


# ============================================================
# 1. dialogs.py — ErrorDialog
# ============================================================
@pytest.mark.gui
class TestErrorDialog:
    """ErrorDialog 测试。"""

    def test_explicit_what_why_how(self, qapp):
        """显式传 what/why/how 构造对话框。"""
        from repair_app.ui.dialogs import ErrorDialog
        dlg = ErrorDialog(what="发生了错误", why="参数无效", how="请检查参数")
        assert dlg.windowTitle() == "操作失败"
        assert dlg.minimumWidth() == 520
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_custom_title(self, qapp):
        """自定义标题。"""
        from repair_app.ui.dialogs import ErrorDialog
        dlg = ErrorDialog(title="自定义错误", what="x")
        assert dlg.windowTitle() == "自定义错误"
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_code_and_exc_auto_generate(self, qapp):
        """传 code+exc 通过 ErrorManager 自动生成友好消息。"""
        from repair_app.ui.dialogs import ErrorDialog
        from repair_app.utils.error_manager import ErrorCode
        exc = FileNotFoundError("test missing file")
        dlg = ErrorDialog(code=ErrorCode.FILE, exc=exc, context="加载文件")
        assert dlg.windowTitle() == "加载文件失败"
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_code_and_exc_keeps_explicit_title(self, qapp):
        """传 code+exc 但显式指定非默认 title 时保留 title。"""
        from repair_app.ui.dialogs import ErrorDialog
        from repair_app.utils.error_manager import ErrorCode
        exc = RuntimeError("matlab boom")
        dlg = ErrorDialog(title="自定义标题", code=ErrorCode.MATLAB, exc=exc)
        assert dlg.windowTitle() == "自定义标题"
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_code_and_exc_matlab(self, qapp):
        """MATLAB 错误码自动生成消息。"""
        from repair_app.ui.dialogs import ErrorDialog
        from repair_app.utils.error_manager import ErrorCode
        exc = RuntimeError("matlab engine crash")
        dlg = ErrorDialog(code=ErrorCode.MATLAB, exc=exc, context="路径规划")
        assert "失败" in dlg.windowTitle()
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_log_text_creates_log_view(self, qapp):
        """log_text 存在时创建折叠日志区。"""
        from repair_app.ui.dialogs import ErrorDialog
        dlg = ErrorDialog(what="err", log_text="Traceback content here")
        assert hasattr(dlg, "_log_view")
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_toggle_log_expand(self, qapp):
        """日志视图不可见时点击展开。"""
        from repair_app.ui.dialogs import ErrorDialog
        dlg = ErrorDialog(what="err", log_text="log content")
        btn = MagicMock()
        with patch.object(dlg._log_view, "isVisible", return_value=False):
            dlg._toggle_log(btn, dlg._log_view)
        btn.setText.assert_called_once_with("▾ 收起技术日志")
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_toggle_log_collapse(self, qapp):
        """日志视图可见时点击收起。"""
        from repair_app.ui.dialogs import ErrorDialog
        dlg = ErrorDialog(what="err", log_text="log content")
        btn = MagicMock()
        with patch.object(dlg._log_view, "isVisible", return_value=True):
            dlg._toggle_log(btn, dlg._log_view)
        btn.setText.assert_called_once_with("▸ 展开技术日志（供技术员排查）")
        dlg.accept()
        _cleanup_widget(dlg, qapp)

    def test_show_explicit_messages(self, qapp):
        """路径 A：显式传 what/why/how。"""
        from repair_app.ui.dialogs import ErrorDialog
        with patch.object(ErrorDialog, "exec", return_value=0):
            ErrorDialog.show(what="w", why="y", how="h")
        qapp.processEvents()

    def test_show_with_exc_and_explicit_messages(self, qapp):
        """路径 A：显式传 what/why/how + exc（生成 log_text）。"""
        from repair_app.ui.dialogs import ErrorDialog
        exc = ValueError("test error")
        with patch.object(ErrorDialog, "exec", return_value=0):
            ErrorDialog.show(what="w", why="y", how="h", exc=exc)
        qapp.processEvents()

    def test_show_via_error_manager(self, qapp):
        """路径 B：走 ErrorManager 统一编排。"""
        from repair_app.ui.dialogs import ErrorDialog
        from repair_app.utils.error_manager import ErrorCode
        exc = FileNotFoundError("not found")
        with patch.object(ErrorDialog, "exec", return_value=0):
            ErrorDialog.show(exc=exc, code=ErrorCode.FILE, context="加载")
        qapp.processEvents()

    def test_show_no_exc_no_messages(self, qapp):
        """路径 C：无异常，仅传文案。"""
        from repair_app.ui.dialogs import ErrorDialog
        with patch.object(ErrorDialog, "exec", return_value=0):
            ErrorDialog.show(title="提示", what="简单消息")
        qapp.processEvents()


# ============================================================
# 2. dialogs.py — classify_error 兼容函数
# ============================================================
@pytest.mark.gui
class TestClassifyError:
    """classify_error 兼容函数测试。"""

    def test_classify_file_error(self, qapp):
        """文件异常分类返回 dict。"""
        from repair_app.ui.dialogs import classify_error
        exc = FileNotFoundError("test.txt not found")
        result = classify_error("加载文件", exc)
        assert isinstance(result, dict)
        assert "title" in result
        assert "what" in result
        assert "why" in result
        assert "how" in result

    def test_classify_matlab_error(self, qapp):
        """MATLAB 异常分类。"""
        from repair_app.ui.dialogs import classify_error
        exc = RuntimeError("matlab algorithm failed")
        result = classify_error("路径规划", exc)
        assert isinstance(result, dict)
        assert len(result["title"]) > 0


# ============================================================
# 3. dialogs.py — LoadingDialog
# ============================================================
@pytest.mark.gui
class TestLoadingDialog:
    """LoadingDialog 测试。"""

    def test_construction_default_timeout(self, qapp):
        """默认超时从 schema 读取。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog()
        assert dlg.windowTitle() == "正在启动 MATLAB"
        assert dlg._timeout_sec > 0
        assert dlg.result_ok is False
        assert dlg.result_msg == ""
        assert dlg.cancelled is False
        _cleanup_widget(dlg, qapp)

    def test_construction_custom_timeout(self, qapp):
        """自定义超时。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=30)
        assert dlg._timeout_sec == 30
        assert "30" in dlg._countdown_lb.text()
        _cleanup_widget(dlg, qapp)

    def test_on_tick_updates_countdown(self, qapp):
        """_on_tick 更新倒计时。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._on_tick()
        assert dlg._elapsed == 1
        assert "9" in dlg._countdown_lb.text()
        _cleanup_widget(dlg, qapp)

    def test_on_tick_rolls_status_dots(self, qapp):
        """多次 _on_tick 滚动状态文字。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        for _ in range(3):
            dlg._on_tick()
        assert dlg._elapsed == 3
        _cleanup_widget(dlg, qapp)

    def test_on_tick_triggers_timeout(self, qapp):
        """elapsed 达到 timeout 时触发 _on_timeout。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=1)
        with patch.object(dlg, "_on_timeout") as mock_timeout:
            dlg._on_tick()
            mock_timeout.assert_called_once()
        _cleanup_widget(dlg, qapp)

    def test_on_cancel(self, qapp):
        """取消按钮设置 cancelled 并 reject。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._on_cancel()
        assert dlg.cancelled is True
        assert dlg.result_ok is False
        assert "取消" in dlg.result_msg
        _cleanup_widget(dlg, qapp)

    def test_on_timeout(self, qapp):
        """超时设置错误消息并 reject。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=5)
        dlg._on_timeout()
        assert dlg.result_ok is False
        assert "超时" in dlg.result_msg
        _cleanup_widget(dlg, qapp)

    def test_on_worker_ok(self, qapp):
        """worker 成功时设置 result_ok 并 accept。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._on_worker_ok(True)
        assert dlg.result_ok is True
        _cleanup_widget(dlg, qapp)

    def test_on_worker_ok_false(self, qapp):
        """worker 返回 False 时 result_ok 为 False。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._on_worker_ok(False)
        assert dlg.result_ok is False
        _cleanup_widget(dlg, qapp)

    def test_on_worker_ok_cancelled(self, qapp):
        """取消后 worker 回调不更新结果。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._cancelled = True
        dlg._on_worker_ok(True)
        assert dlg.result_ok is False
        _cleanup_widget(dlg, qapp)

    def test_on_worker_msg(self, qapp):
        """worker 消息回调设置 result_msg。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        dlg._on_worker_msg("ready")
        assert dlg.result_msg == "ready"
        _cleanup_widget(dlg, qapp)

    def test_start_with_mock_manager(self, qapp):
        """start 创建 worker 并启动计时器（mock worker 避免真实线程）。"""
        from repair_app.ui.dialogs import LoadingDialog
        dlg = LoadingDialog(timeout_sec=10)
        manager = MagicMock()
        manager.ensure_ready.return_value = True
        manager.message = "ok"
        with patch("repair_app.ui.dialogs._EnsureReadyWorker") as MockWorker:
            mock_worker = MagicMock()
            MockWorker.return_value = mock_worker
            dlg.start(manager)
            MockWorker.assert_called_once_with(manager)
            mock_worker.finished_ok.connect.assert_called_once()
            mock_worker.finished_msg.connect.assert_called_once()
            mock_worker.start.assert_called_once()
        assert dlg._timer.isActive()
        dlg._timer.stop()
        _cleanup_widget(dlg, qapp)


# ============================================================
# 4. dialogs.py — _EnsureReadyWorker
# ============================================================
@pytest.mark.gui
class TestEnsureReadyWorker:
    """_EnsureReadyWorker 后台线程测试。"""

    def test_run_success(self, qapp):
        """ensure_ready 成功时发射 finished_ok(True)。"""
        from repair_app.ui.dialogs import _EnsureReadyWorker
        manager = MagicMock()
        manager.ensure_ready.return_value = True
        manager.message = "ready"
        worker = _EnsureReadyWorker(manager.ensure_ready)
        worker.run()
        manager.ensure_ready.assert_called_once()
        _cleanup_widget(worker, qapp)

    def test_run_failure(self, qapp):
        """ensure_ready 返回 False 时发射 finished_ok(False)。"""
        from repair_app.ui.dialogs import _EnsureReadyWorker
        manager = MagicMock()
        manager.ensure_ready.return_value = False
        worker = _EnsureReadyWorker(manager.ensure_ready)
        worker.run()
        manager.ensure_ready.assert_called_once()
        _cleanup_widget(worker, qapp)

    def test_run_exception(self, qapp):
        """ensure_ready 抛异常时被捕获，发射 finished_ok(False)。"""
        from repair_app.ui.dialogs import _EnsureReadyWorker
        manager = MagicMock()
        manager.ensure_ready.side_effect = RuntimeError("crash")
        worker = _EnsureReadyWorker(manager.ensure_ready)
        worker.run()
        manager.ensure_ready.assert_called_once()
        _cleanup_widget(worker, qapp)


# ============================================================
# 5. dialogs.py — RobotExportDialog
# ============================================================
@pytest.mark.gui
class TestRobotExportDialog:
    """RobotExportDialog 测试。"""

    def test_construction_no_waypoints(self, qapp):
        """无航点时构造对话框。"""
        from repair_app.ui.dialogs import RobotExportDialog
        dlg = RobotExportDialog()
        assert dlg.windowTitle() == "导出工业机器人轨迹"
        assert dlg.result_path == ""
        assert "未加载航点" in dlg._lb_wp.text()
        _cleanup_widget(dlg, qapp)

    def test_construction_with_waypoints(self, qapp):
        """有航点时构造对话框。"""
        from repair_app.ui.dialogs import RobotExportDialog
        wps = np.array([[0, 0, 0], [1, 1, 0]], dtype=np.float32)
        dlg = RobotExportDialog(waypoints=wps)
        assert "已加载 2" in dlg._lb_wp.text()
        _cleanup_widget(dlg, qapp)

    def test_on_export_no_waypoints(self, qapp):
        """无航点时点击导出弹出警告。"""
        from repair_app.ui.dialogs import RobotExportDialog
        dlg = RobotExportDialog()
        dlg._on_export()
        assert dlg.result_path == ""
        _cleanup_widget(dlg, qapp)

    def test_on_export_cancelled(self, qapp, monkeypatch):
        """用户在文件对话框取消保存。"""
        from repair_app.ui.dialogs import RobotExportDialog
        wps = np.array([[0, 0, 0], [1, 1, 0]], dtype=np.float32)
        dlg = RobotExportDialog(waypoints=wps)
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
        dlg._on_export()
        assert dlg.result_path == ""
        _cleanup_widget(dlg, qapp)

    def test_on_export_success_kuka(self, qapp, monkeypatch, tmp_path):
        """KUKA 导出成功路径。"""
        from repair_app.ui.dialogs import RobotExportDialog
        wps = np.array([[0, 0, 0], [1, 1, 0]], dtype=np.float32)
        dlg = RobotExportDialog(waypoints=wps)
        out_file = str(tmp_path / "test.krl")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (out_file, ""))
        with patch("repair_app.export.robot_exporter.RobotExporter") as MockExporter:
            mock_exp = MagicMock()
            MockExporter.return_value = mock_exp
            dlg._on_export()
            mock_exp.export.assert_called_once()
        assert dlg.result_path == out_file
        _cleanup_widget(dlg, qapp)

    def test_on_export_success_abb(self, qapp, monkeypatch, tmp_path):
        """ABB 导出成功路径。"""
        from repair_app.ui.dialogs import RobotExportDialog
        wps = np.array([[0, 0, 0], [1, 1, 0]], dtype=np.float32)
        dlg = RobotExportDialog(waypoints=wps)
        dlg._cb_type.setCurrentIndex(1)  # ABB
        out_file = str(tmp_path / "test.mod")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (out_file, ""))
        with patch("repair_app.export.robot_exporter.RobotExporter") as MockExporter:
            mock_exp = MagicMock()
            MockExporter.return_value = mock_exp
            dlg._on_export()
            mock_exp.export.assert_called_once()
        assert dlg.result_path == out_file
        _cleanup_widget(dlg, qapp)

    def test_on_export_error(self, qapp, monkeypatch, tmp_path):
        """导出异常时弹出 ErrorDialog。"""
        from repair_app.ui.dialogs import RobotExportDialog, ErrorDialog
        wps = np.array([[0, 0, 0]], dtype=np.float32)
        dlg = RobotExportDialog(waypoints=wps)
        out_file = str(tmp_path / "test.krl")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (out_file, ""))
        with patch("repair_app.export.robot_exporter.RobotExporter") as MockExporter, \
             patch.object(ErrorDialog, "exec", return_value=0):
            MockExporter.return_value.export.side_effect = RuntimeError("export failed")
            dlg._on_export()
        assert dlg.result_path == ""
        _cleanup_widget(dlg, qapp)


# ============================================================
# 6. dialogs.py — CalibrationDialog
# ============================================================
@pytest.mark.gui
class TestCalibrationDialog:
    """CalibrationDialog 测试。"""

    def test_construction(self, qapp):
        """构造标定向导对话框。"""
        from repair_app.ui.dialogs import CalibrationDialog
        dlg = CalibrationDialog()
        assert dlg.windowTitle() == "单道沉积标定向导"
        assert dlg._wizard is None
        _cleanup_widget(dlg, qapp)

    def test_on_save_success(self, qapp):
        """保存成功路径。"""
        from repair_app.ui.dialogs import CalibrationDialog
        dlg = CalibrationDialog()
        mock_wizard = MagicMock()
        mock_wizard.save.return_value = "20260101_120000"
        mock_wizard.get_correction_factors.return_value = {
            "width": 1.0, "height": 0.95, "efficiency": 0.88,
        }
        with patch("repair_app.utils.calibration_wizard.CalibrationWizard", return_value=mock_wizard):
            dlg._on_save()
        mock_wizard.start_calibration.assert_called_once()
        mock_wizard.record_measurement.assert_called_once()
        _cleanup_widget(dlg, qapp)

    def test_on_save_error(self, qapp):
        """保存异常时弹出 ErrorDialog。"""
        from repair_app.ui.dialogs import CalibrationDialog, ErrorDialog
        dlg = CalibrationDialog()
        mock_wizard = MagicMock()
        mock_wizard.save.side_effect = RuntimeError("save failed")
        with patch("repair_app.utils.calibration_wizard.CalibrationWizard", return_value=mock_wizard), \
             patch.object(ErrorDialog, "exec", return_value=0):
            dlg._on_save()
        _cleanup_widget(dlg, qapp)

    def test_on_save_zero_efficiency(self, qapp):
        """沉积效率为 0 时传 None。"""
        from repair_app.ui.dialogs import CalibrationDialog
        dlg = CalibrationDialog()
        dlg._sp_eff.setValue(0.0)
        mock_wizard = MagicMock()
        mock_wizard.save.return_value = "ts"
        mock_wizard.get_correction_factors.return_value = {
            "width": 1.0, "height": 1.0, "efficiency": 1.0,
        }
        with patch("repair_app.utils.calibration_wizard.CalibrationWizard", return_value=mock_wizard):
            dlg._on_save()
        # record_measurement 的 deposition_efficiency 参数应为 None
        call_kwargs = mock_wizard.record_measurement.call_args
        assert call_kwargs.kwargs.get("deposition_efficiency") is None
        _cleanup_widget(dlg, qapp)


# ============================================================
# 7. dialogs.py — CoordinateSystemDialog
# ============================================================
@pytest.mark.gui
class TestCoordinateSystemDialog:
    """CoordinateSystemDialog 测试。"""

    def test_construction_no_points(self, qapp):
        """无点云时构造对话框。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        dlg = CoordinateSystemDialog()
        assert dlg.windowTitle() == "坐标系变换"
        assert "未加载点云" in dlg._lb_pc.text()
        assert dlg.transformed_points is None
        _cleanup_widget(dlg, qapp)

    def test_construction_with_points(self, qapp):
        """有点云时构造对话框。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        assert "已加载 2" in dlg._lb_pc.text()
        _cleanup_widget(dlg, qapp)

    def test_on_apply_no_points(self, qapp):
        """无点云时点击应用弹出警告。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        dlg = CoordinateSystemDialog()
        dlg._on_apply()
        assert dlg.transformed_points is None
        _cleanup_widget(dlg, qapp)

    def test_on_apply_success(self, qapp):
        """平移变换成功。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        dlg._sp_tx.setValue(10.0)
        dlg._on_apply()
        result = dlg.transformed_points
        assert result is not None
        assert result.shape == (2, 3)
        assert result[0, 0] == 11.0  # 1 + 10
        _cleanup_widget(dlg, qapp)

    def test_on_apply_with_rotation_z(self, qapp):
        """绕 Z 轴旋转 90°。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[1, 0, 0]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        dlg._sp_rz.setValue(90.0)
        dlg._on_apply()
        result = dlg.transformed_points
        assert result is not None
        assert abs(result[0, 0]) < 1e-6  # X ≈ 0
        assert abs(result[0, 1] - 1.0) < 1e-6  # Y ≈ 1
        _cleanup_widget(dlg, qapp)

    def test_on_apply_with_rotation_x(self, qapp):
        """绕 X 轴旋转。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[0, 1, 0]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        dlg._sp_rx.setValue(90.0)
        dlg._on_apply()
        result = dlg.transformed_points
        assert result is not None
        _cleanup_widget(dlg, qapp)

    def test_on_apply_with_rotation_y(self, qapp):
        """绕 Y 轴旋转。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[0, 0, 1]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        dlg._sp_ry.setValue(90.0)
        dlg._on_apply()
        result = dlg.transformed_points
        assert result is not None
        _cleanup_widget(dlg, qapp)

    def test_on_apply_with_scale(self, qapp):
        """缩放变换。"""
        from repair_app.ui.dialogs import CoordinateSystemDialog
        pts = np.array([[1, 2, 3]], dtype=np.float64)
        dlg = CoordinateSystemDialog(points=pts)
        dlg._sp_sx.setValue(2.0)
        dlg._on_apply()
        result = dlg.transformed_points
        assert result[0, 0] == 2.0  # 1 * 2
        _cleanup_widget(dlg, qapp)


# ============================================================
# 8. dialogs.py — ParameterPresetDialog
# ============================================================
@pytest.mark.gui
class TestParameterPresetDialog:
    """ParameterPresetDialog 测试。"""

    def test_construction(self, qapp, monkeypatch, tmp_path):
        """构造预设管理对话框。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        dlg = ParameterPresetDialog()
        assert dlg.windowTitle() == "参数预设管理"
        assert dlg.result_params is None
        _cleanup_widget(dlg, qapp)

    def test_on_save_empty_name(self, qapp, monkeypatch, tmp_path):
        """名称为空时弹出警告。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        dlg = ParameterPresetDialog()
        dlg._le_name.setText("")
        dlg._on_save()
        _cleanup_widget(dlg, qapp)

    def test_on_save_success(self, qapp, monkeypatch, tmp_path):
        """保存预设成功。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        dlg = ParameterPresetDialog(current_params={"velocity": 500})
        dlg._le_name.setText("test_preset")
        dlg._on_save()
        assert (tmp_path / "param_presets" / "test_preset.json").exists()
        _cleanup_widget(dlg, qapp)

    def test_on_load_no_selection(self, qapp, monkeypatch, tmp_path):
        """无选择时加载弹出警告。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        dlg = ParameterPresetDialog()
        dlg._on_load()
        assert dlg.result_params is None
        _cleanup_widget(dlg, qapp)

    def test_on_load_success(self, qapp, monkeypatch, tmp_path):
        """加载预设成功。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        import json
        preset_dir = tmp_path / "param_presets"
        preset_dir.mkdir(parents=True)
        (preset_dir / "existing.json").write_text(json.dumps({"v": 100}), encoding="utf-8")
        dlg = ParameterPresetDialog()
        dlg._lst_presets.setCurrentRow(0)
        dlg._on_load()
        assert dlg.result_params == {"v": 100}
        _cleanup_widget(dlg, qapp)

    def test_on_delete_no_selection(self, qapp, monkeypatch, tmp_path):
        """无选择时删除弹出警告。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        dlg = ParameterPresetDialog()
        dlg._on_delete()
        _cleanup_widget(dlg, qapp)

    def test_on_delete_success(self, qapp, monkeypatch, tmp_path):
        """删除预设成功。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        import json
        preset_dir = tmp_path / "param_presets"
        preset_dir.mkdir(parents=True)
        (preset_dir / "to_delete.json").write_text(json.dumps({"v": 1}), encoding="utf-8")
        dlg = ParameterPresetDialog()
        dlg._lst_presets.setCurrentRow(0)
        # P2-9: _on_delete 有二次点击确认逻辑，第一次点击仅标记待删除，第二次才实际删除
        dlg._on_delete()
        dlg._on_delete()
        assert not (preset_dir / "to_delete.json").exists()
        _cleanup_widget(dlg, qapp)

    def test_refresh_list(self, qapp, monkeypatch, tmp_path):
        """_refresh_list 列出已保存预设。"""
        from repair_app.ui.dialogs import ParameterPresetDialog
        monkeypatch.setattr("repair_app.utils.resource_path.get_data_dir", lambda: tmp_path)
        import json
        preset_dir = tmp_path / "param_presets"
        preset_dir.mkdir(parents=True)
        (preset_dir / "a.json").write_text("{}", encoding="utf-8")
        (preset_dir / "b.json").write_text("{}", encoding="utf-8")
        dlg = ParameterPresetDialog()
        dlg._refresh_list()
        assert dlg._lst_presets.count() == 2
        _cleanup_widget(dlg, qapp)


# ============================================================
# 9. dialogs.py — BatchValidationDialog
# ============================================================
@pytest.mark.gui
class TestBatchValidationDialog:
    """BatchValidationDialog 测试。"""

    def test_construction_no_base_params(self, qapp):
        """无基础参数构造。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        assert dlg.windowTitle() == "批量验证"
        assert dlg._txt.toPlainText() == ""
        _cleanup_widget(dlg, qapp)

    def test_construction_with_base_params(self, qapp):
        """有基础参数构造。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog(base_params={"velocity": 500})
        assert "velocity" in dlg._txt.toPlainText()
        _cleanup_widget(dlg, qapp)

    def test_on_run_empty_input(self, qapp):
        """空输入时弹出警告。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._on_run()
        assert dlg._txt_result.toPlainText() == ""
        _cleanup_widget(dlg, qapp)

    def test_on_run_json_dict(self, qapp):
        """JSON dict 格式输入。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._txt.setPlainText('{"particle_velocity_ms": 500}')
        dlg._on_run()
        assert "批量验证结果" in dlg._txt_result.toPlainText()
        _cleanup_widget(dlg, qapp)

    def test_on_run_json_list(self, qapp):
        """JSON list 格式输入。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._txt.setPlainText('[{"particle_velocity_ms": 500}, {"particle_velocity_ms": 600}]')
        dlg._on_run()
        assert "共 2 组" in dlg._txt_result.toPlainText()
        _cleanup_widget(dlg, qapp)

    def test_on_run_key_value_format(self, qapp):
        """key=value 格式输入。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._txt.setPlainText("particle_velocity_ms=500, gas_temperature_c=800")
        dlg._on_run()
        assert "批量验证结果" in dlg._txt_result.toPlainText()
        _cleanup_widget(dlg, qapp)

    def test_on_run_no_valid_params(self, qapp):
        """无有效参数组合时弹出警告。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._txt.setPlainText("# comment only")
        dlg._on_run()
        _cleanup_widget(dlg, qapp)

    def test_on_run_invalid_json_falls_back(self, qapp):
        """无效 JSON 回退到 key=value 解析。"""
        from repair_app.ui.dialogs import BatchValidationDialog
        dlg = BatchValidationDialog()
        dlg._txt.setPlainText("not_json_key=100, another=200")
        dlg._on_run()
        assert "批量验证结果" in dlg._txt_result.toPlainText()
        _cleanup_widget(dlg, qapp)


# ============================================================
# 10. dialogs.py — ParameterValidatorDialog
# ============================================================
@pytest.mark.gui
class TestParameterValidatorDialog:
    """ParameterValidatorDialog 测试。"""

    def test_construction_no_params(self, qapp):
        """无参数时构造并自动校验。"""
        from repair_app.ui.dialogs import ParameterValidatorDialog
        dlg = ParameterValidatorDialog()
        assert dlg.windowTitle() == "参数校验器"
        text = dlg._txt_result.toPlainText()
        assert "参数校验报告" in text
        assert "未获取到参数" in text
        _cleanup_widget(dlg, qapp)

    def test_construction_with_params(self, qapp):
        """有参数时构造并自动校验。"""
        from repair_app.ui.dialogs import ParameterValidatorDialog
        dlg = ParameterValidatorDialog(current_params={"particle_velocity_ms": 500})
        text = dlg._txt_result.toPlainText()
        assert "参数校验报告" in text
        _cleanup_widget(dlg, qapp)

    def test_on_check_with_ui_short_keys(self, qapp):
        """使用 UI short key 进行参数校验。"""
        from repair_app.ui.dialogs import ParameterValidatorDialog
        dlg = ParameterValidatorDialog()
        dlg._current_params = {
            "layer_height": 0.5,
            "scanning_angle": 45,
            "particle_velocity": 500,
        }
        dlg._on_check()
        text = dlg._txt_result.toPlainText()
        assert "参数校验报告" in text
        _cleanup_widget(dlg, qapp)

    def test_on_check_out_of_range(self, qapp):
        """参数超出范围时显示 ✗。"""
        from repair_app.ui.dialogs import ParameterValidatorDialog
        dlg = ParameterValidatorDialog()
        dlg._current_params = {"particle_velocity_ms": 999999}
        dlg._on_check()
        text = dlg._txt_result.toPlainText()
        assert "✗" in text or "超出" in text
        _cleanup_widget(dlg, qapp)


# ============================================================
# 11. context_menu.py — ContextMenuManager
# ============================================================
@pytest.mark.gui
class TestContextMenuManager:
    """ContextMenuManager 测试。"""

    def test_construction(self, qapp):
        """构造 ContextMenuManager。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        assert mgr._main_window is mw
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_show_context_menu_with_visualizer(self, qapp):
        """有 visualizer 时通过 visualizer.mapToGlobal 定位菜单。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mw._visualizer.mapToGlobal.return_value = QPoint(0, 0)
        mgr = ContextMenuManager(mw)
        # mock QMenu 避免阻塞模态 exec
        with patch("repair_app.ui.context_menu.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mgr.show_context_menu(QPoint(10, 10))
        mw._visualizer.mapToGlobal.assert_called_once_with(QPoint(10, 10))
        mock_menu.exec.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_show_context_menu_without_visualizer(self, qapp):
        """无 visualizer 时通过 main_window.mapToGlobal 定位菜单。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        with patch("repair_app.ui.context_menu.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mgr.show_context_menu(QPoint(10, 10))
        mock_menu.exec.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_show_context_menu_with_selector(self, qapp):
        """有 selector 时选区菜单项可用。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mw._visualizer.mapToGlobal.return_value = QPoint(0, 0)
        mw._selector = MagicMock()
        mgr = ContextMenuManager(mw)
        with patch("repair_app.ui.context_menu.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mgr.show_context_menu(QPoint(5, 5))
        mock_menu.exec.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    # ---- _on_reset_view ----
    def test_on_reset_view(self, qapp):
        """重置视角委托给 visualizer。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_reset_view()
        mw._visualizer.reset_view.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_reset_view_no_visualizer(self, qapp):
        """无 visualizer 时不抛异常。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        mgr._on_reset_view()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_reset_view_exception(self, qapp):
        """visualizer.reset_view 抛异常时记录 warning。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mw._visualizer.reset_view.side_effect = RuntimeError("boom")
        mgr = ContextMenuManager(mw)
        mgr._on_reset_view()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    # ---- _on_fit_view ----
    def test_on_fit_view(self, qapp):
        """适应窗口委托给 visualizer。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_fit_view()
        mw._visualizer.fit_to_view.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_fit_view_exception(self, qapp):
        """fit_to_view 抛异常时被捕获。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mw._visualizer.fit_to_view.side_effect = RuntimeError("boom")
        mgr = ContextMenuManager(mw)
        mgr._on_fit_view()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    # ---- _on_toggle_axes ----
    def test_on_toggle_axes(self, qapp):
        """切换坐标轴委托给 visualizer。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_toggle_axes()
        mw._visualizer.toggle_axes.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_toggle_axes_exception(self, qapp):
        """toggle_axes 抛异常时被捕获。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._visualizer = MagicMock()
        mw._visualizer.toggle_axes.side_effect = RuntimeError("boom")
        mgr = ContextMenuManager(mw)
        mgr._on_toggle_axes()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    # ---- _on_clear_selection / _on_invert_selection ----
    def test_on_clear_selection(self, qapp):
        """清除选区委托给 selector。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._selector = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_clear_selection()
        mw._selector.clear_selection.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_clear_selection_no_selector(self, qapp):
        """无 selector 时不抛异常。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        mgr._on_clear_selection()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_clear_selection_exception(self, qapp):
        """clear_selection 抛异常时被捕获。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._selector = MagicMock()
        mw._selector.clear_selection.side_effect = RuntimeError("boom")
        mgr = ContextMenuManager(mw)
        mgr._on_clear_selection()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_invert_selection(self, qapp):
        """反选委托给 selector。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._selector = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_invert_selection()
        mw._selector.invert_selection.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_invert_selection_exception(self, qapp):
        """invert_selection 抛异常时被捕获。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._selector = MagicMock()
        mw._selector.invert_selection.side_effect = RuntimeError("boom")
        mgr = ContextMenuManager(mw)
        mgr._on_invert_selection()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    # ---- _can_undo / _can_redo ----
    def test_can_undo_redo_empty_stack(self, qapp):
        """空栈时 _can_undo/_can_redo 返回 False。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        from repair_app.ui.undo_framework import UndoStack
        UndoStack.reset()
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        assert isinstance(mgr._can_undo(), bool)
        assert isinstance(mgr._can_redo(), bool)
        assert mgr._can_undo() is False
        assert mgr._can_redo() is False
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)
        UndoStack.reset()

    # ---- _on_undo / _on_redo ----
    def test_on_undo_redo_empty_stack(self, qapp):
        """空栈时撤销/重做不抛异常。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        from repair_app.ui.undo_framework import UndoStack
        UndoStack.reset()
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        mgr._on_undo()
        mgr._on_redo()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)
        UndoStack.reset()

    # ---- _on_export_gcode / _on_export_robot ----
    def test_on_export_gcode(self, qapp):
        """导出 G-code 委托给 main_window._on_export_gcode。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._on_export_gcode = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_export_gcode()
        mw._on_export_gcode.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_export_gcode_not_present(self, qapp):
        """main_window 无 _on_export_gcode 时不抛异常。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        mgr._on_export_gcode()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_export_robot(self, qapp):
        """导出机器人轨迹委托给 main_window._on_export_robot。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mw._on_export_robot = MagicMock()
        mgr = ContextMenuManager(mw)
        mgr._on_export_robot()
        mw._on_export_robot.assert_called_once()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)

    def test_on_export_robot_not_present(self, qapp):
        """main_window 无 _on_export_robot 时不抛异常。"""
        from repair_app.ui.context_menu import ContextMenuManager
        from PySide6.QtWidgets import QWidget
        mw = QWidget()
        mgr = ContextMenuManager(mw)
        mgr._on_export_robot()
        _cleanup_widget(mgr, qapp)
        _cleanup_widget(mw, qapp)


# ============================================================
# 12. profile_result_panel.py — decode_binary_stl
# ============================================================
@pytest.mark.gui
class TestDecodeBinaryStl:
    """decode_binary_stl 函数测试。"""

    def test_valid_stl(self):
        """有效 STL 返回 (N, 9) 矩阵。"""
        from repair_app.ui.profile_result_panel import decode_binary_stl
        data = _make_stl_bytes(3)
        tris = decode_binary_stl(data)
        assert tris is not None
        assert tris.shape == (3, 9)

    def test_empty_data(self):
        """空数据返回 None。"""
        from repair_app.ui.profile_result_panel import decode_binary_stl
        assert decode_binary_stl(b"") is None

    def test_too_short(self):
        """数据过短返回 None。"""
        from repair_app.ui.profile_result_panel import decode_binary_stl
        assert decode_binary_stl(b"\x00" * 10) is None

    def test_truncated(self):
        """截断数据返回 None。"""
        from repair_app.ui.profile_result_panel import decode_binary_stl
        data = _make_stl_bytes(5)
        assert decode_binary_stl(data[:100]) is None

    def test_none_input(self):
        """None 输入返回 None。"""
        from repair_app.ui.profile_result_panel import decode_binary_stl
        assert decode_binary_stl(None) is None


# ============================================================
# 13. profile_result_panel.py — _MetricCard
# ============================================================
@pytest.mark.gui
class TestMetricCard:
    """_MetricCard 组件测试。"""

    def test_construction(self, qapp):
        """构造指标卡片。"""
        from repair_app.ui.profile_result_panel import _MetricCard
        card = _MetricCard("材料用量", "100", "g")
        assert card is not None
        _cleanup_widget(card, qapp)

    def test_set_value(self, qapp):
        """set_value 更新数值和单位。"""
        from repair_app.ui.profile_result_panel import _MetricCard
        card = _MetricCard("测试")
        card.set_value("200", "kg", "#FF0000")
        _cleanup_widget(card, qapp)

    def test_default_value(self, qapp):
        """默认值为 —。"""
        from repair_app.ui.profile_result_panel import _MetricCard
        card = _MetricCard("测试")
        assert card._lb_value.text() == "—"
        _cleanup_widget(card, qapp)


# ============================================================
# 14. profile_result_panel.py — ProfileResultPanel
# ============================================================
@pytest.mark.gui
class TestProfileResultPanel:
    """ProfileResultPanel 测试。"""

    def test_construction(self, qapp):
        """构造面板。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        assert panel._profile is None
        assert panel._tabs.count() == 4
        _cleanup_widget(panel, qapp)

    def test_set_profile_result_empty(self, qapp):
        """空结果 dict。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel.set_profile_result({})
        assert panel._profile == {}
        _cleanup_widget(panel, qapp)

    def test_set_profile_result_full(self, qapp):
        """完整结果数据。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        result = {
            "estimated_mass_g": 12.5,
            "estimated_time_s": 60.0,
            "predicted_volume_mm3": 1500.0,
            "uniformity_score": 0.92,
            "mesh_bytes": _make_stl_bytes(2),
            "layer_profiles": [
                {"layer_index": 0, "max_height_mm": 0.5, "avg_height_mm": 0.3, "dep_efficiency": 0.85},
                {"layer_index": 1, "max_height_mm": 0.6, "avg_height_mm": 0.4, "dep_efficiency": 0.80},
            ],
            "particle_dist": {
                "px": [0.0, 1.0, 2.0],
                "py": [0.0, 1.0, 2.0],
                "vx": [100.0, 110.0, 120.0],
                "vy": [10.0, 20.0, 30.0],
                "vz": [1.0, 2.0, 3.0],
                "total_particles": 3,
                "dep_efficiency": 0.82,
            },
            "warnings": ["warning1", "warning2"],
        }
        panel.set_profile_result(result)
        assert panel._profile is result
        assert "已加载" in panel._lb_status.text()
        _cleanup_widget(panel, qapp)

    # ---- _update_metric_cards ----
    def test_metric_cards_no_profile(self, qapp):
        """无 profile 时不更新。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._update_metric_cards()
        _cleanup_widget(panel, qapp)

    def test_metric_cards_with_particle_dist(self, qapp):
        """有 particle_dist 时更新粒子总数。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "estimated_mass_g": 10.0,
            "estimated_time_s": 30.0,
            "predicted_volume_mm3": 500.0,
            "uniformity_score": 0.9,
            "particle_dist": {"total_particles": 1000},
            "warnings": ["w1"],
        }
        panel._update_metric_cards()
        assert "1,000" in panel._card_pd._lb_value.text()
        _cleanup_widget(panel, qapp)

    def test_metric_cards_no_particle_dist(self, qapp):
        """无 particle_dist 时粒子总数显示 —。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "estimated_mass_g": 0,
            "estimated_time_s": 0,
            "predicted_volume_mm3": 0,
            "uniformity_score": 0.5,
            "particle_dist": None,
            "warnings": [],
        }
        panel._update_metric_cards()
        assert panel._card_pd._lb_value.text() == "—"
        _cleanup_widget(panel, qapp)

    def test_metric_cards_many_warnings(self, qapp):
        """警告数 >=3 时颜色为 ERR。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "uniformity_score": 0.9,
            "warnings": ["w1", "w2", "w3", "w4"],
        }
        panel._update_metric_cards()
        assert panel._card_warn._lb_value.text() == "4"
        _cleanup_widget(panel, qapp)

    def test_metric_cards_particle_dist_no_total(self, qapp):
        """particle_dist 无 total_particles 时回退到 len(px)。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "uniformity_score": 0.9,
            "particle_dist": {"px": [1, 2, 3, 4, 5]},
        }
        panel._update_metric_cards()
        assert "5" in panel._card_pd._lb_value.text()
        _cleanup_widget(panel, qapp)

    # ---- _render_mesh ----
    def test_render_mesh_no_profile(self, qapp):
        """无 profile 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._render_mesh()
        _cleanup_widget(panel, qapp)

    def test_render_mesh_no_bytes(self, qapp):
        """无 mesh_bytes 时渲染降级模式。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"mesh_bytes": b""}
        panel._render_mesh()
        _cleanup_widget(panel, qapp)

    def test_render_mesh_invalid_bytes(self, qapp):
        """无效 mesh_bytes 时渲染降级模式。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"mesh_bytes": b"invalid"}
        panel._render_mesh()
        _cleanup_widget(panel, qapp)

    def test_render_mesh_valid(self, qapp):
        """有效 mesh_bytes 时渲染 3D 网格。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"mesh_bytes": _make_stl_bytes(3)}
        panel._render_mesh()
        _cleanup_widget(panel, qapp)

    # ---- _render_layers ----
    def test_render_layers_no_profile(self, qapp):
        """无 profile 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._render_layers()
        _cleanup_widget(panel, qapp)

    def test_render_layers_empty(self, qapp):
        """空 layer_profiles 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"layer_profiles": []}
        panel._render_layers()
        _cleanup_widget(panel, qapp)

    def test_render_layers_with_data(self, qapp):
        """有 layer_profiles 时渲染柱状图。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "layer_profiles": [
                {"layer_index": 0, "max_height_mm": 0.5, "avg_height_mm": 0.3, "dep_efficiency": 0.85},
                {"layer_index": 1, "max_height_mm": 0.6, "avg_height_mm": 0.4, "dep_efficiency": 0.80},
            ]
        }
        panel._render_layers()
        _cleanup_widget(panel, qapp)

    # ---- _render_particles ----
    def test_render_particles_no_profile(self, qapp):
        """无 profile 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._render_particles()
        _cleanup_widget(panel, qapp)

    def test_render_particles_empty(self, qapp):
        """空 px 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"particle_dist": {"px": []}}
        panel._render_particles()
        _cleanup_widget(panel, qapp)

    def test_render_particles_with_data(self, qapp):
        """有粒子数据时渲染散点图。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "particle_dist": {
                "px": [0.0, 1.0, 2.0, 3.0],
                "py": [0.0, 1.0, 2.0, 3.0],
                "vx": [100.0, 110.0, 120.0, 130.0],
                "vy": [10.0, 20.0, 30.0, 40.0],
                "vz": [1.0, 2.0, 3.0, 4.0],
                "dep_efficiency": 0.8,
            }
        }
        panel._render_particles()
        _cleanup_widget(panel, qapp)

    def test_render_particles_no_velocity(self, qapp):
        """无速度数据时 v_mag 为零数组。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "particle_dist": {
                "px": [0.0, 1.0],
                "py": [0.0, 1.0],
                "vx": [],
                "vy": [],
                "vz": [],
            }
        }
        panel._render_particles()
        _cleanup_widget(panel, qapp)

    # ---- _render_uniformity ----
    def test_render_uniformity_no_profile(self, qapp):
        """无 profile 时渲染空状态。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_excellent(self, qapp):
        """均匀性 >= 0.9 显示优秀。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"uniformity_score": 0.95}
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_good(self, qapp):
        """均匀性 >= 0.85 显示良好。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"uniformity_score": 0.87}
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_average(self, qapp):
        """均匀性 >= 0.7 显示一般。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"uniformity_score": 0.75}
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_poor(self, qapp):
        """均匀性 < 0.7 显示较差。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"uniformity_score": 0.5}
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_zero(self, qapp):
        """均匀性为 0 时不绘制数值弧。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {"uniformity_score": 0.0}
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    def test_render_uniformity_with_warnings(self, qapp):
        """有警告时显示警告文字。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel._profile = {
            "uniformity_score": 0.9,
            "warnings": ["w1", "w2", "w3", "w4", "w5"],
        }
        panel._render_uniformity()
        _cleanup_widget(panel, qapp)

    # ---- refresh ----
    def test_refresh_no_data(self, qapp):
        """无数据时 refresh 不操作。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel.refresh()
        assert panel._profile is None
        _cleanup_widget(panel, qapp)

    def test_refresh_with_data(self, qapp):
        """有数据时 refresh 重新渲染。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        result = {"uniformity_score": 0.9, "layer_profiles": []}
        panel.set_profile_result(result)
        panel.refresh()
        _cleanup_widget(panel, qapp)

    # ---- clear ----
    def test_clear(self, qapp):
        """clear 清空所有结果。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel.set_profile_result({"uniformity_score": 0.9})
        panel.clear()
        assert panel._profile is None
        assert "已清空" in panel._lb_status.text()
        _cleanup_widget(panel, qapp)

    def test_clear_empty_panel(self, qapp):
        """对空面板 clear 不抛异常。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        panel = ProfileResultPanel()
        panel.clear()
        assert panel._profile is None
        _cleanup_widget(panel, qapp)

    # ---- _render_empty / _render_empty_2d ----
    def test_render_empty_2d(self, qapp):
        """_render_empty_2d 在轴上绘制空消息。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        import matplotlib.pyplot as plt
        panel = ProfileResultPanel()
        fig = plt.figure()
        ax = fig.add_subplot(111)
        panel._render_empty_2d(ax, "测试消息")
        plt.close(fig)
        _cleanup_widget(panel, qapp)

    def test_render_empty_3d(self, qapp):
        """_render_empty 在 3D 轴上绘制空消息。"""
        from repair_app.ui.profile_result_panel import ProfileResultPanel
        import matplotlib.pyplot as plt
        panel = ProfileResultPanel()
        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")
        panel._render_empty(ax, "测试消息")
        plt.close(fig)
        _cleanup_widget(panel, qapp)
