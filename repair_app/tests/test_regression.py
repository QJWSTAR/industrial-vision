"""test_regression.py — 回归测试

验证关键 bug 修复不回归。覆盖任务 H/K/J/L 中的修复点：
- G-code 坐标模式输出正确（任务H MF-5）
- License HMAC 空密钥处理（任务H MF-3）
- ErrorManager 7 类错误分类（任务K）
- ThemeManager 生成非空 QSS（任务L）
- DefectSelector 选区操作不丢失数据（任务L）
- parameter_schema 无 Magic Number（任务J）
- Workers failed 信号是三元组 (str, str, str)（任务K）
- Toast 4 级别通知可创建（任务L）
- UndoStack 单例可获取（任务L）

运行：pytest -m regression -v
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 强制 Qt 离屏模式（CI/无显示环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import hashlib
import hmac as hmac_module
import numpy as np
import pytest


# ================================================================
# 1. G-code 坐标模式输出正确（任务H MF-5 修复）
# ================================================================
@pytest.mark.regression
class TestGCodeCoordinateMode:
    """验证 G-code 绝对/增量坐标模式输出正确。"""

    def test_absolute_mode_contains_g90(self):
        """绝对坐标模式输出应包含 G90。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        waypoints = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
        exporter = GCodeExporter(coordinate_mode="absolute", safe_z=10.0)
        gcode = exporter.export(waypoints)
        assert "G90" in gcode, "绝对坐标模式应包含 G90"
        assert "G1" in gcode, "应包含 G1 进给指令"

    def test_incremental_mode_contains_g91(self):
        """增量坐标模式输出应包含 G91。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        waypoints = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
        exporter = GCodeExporter(coordinate_mode="incremental", safe_z=10.0)
        gcode = exporter.export(waypoints)
        assert "G91" in gcode, "增量坐标模式应包含 G91"

    def test_mode_label_in_output(self):
        """输出应包含模式标注。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        waypoints = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        exporter_abs = GCodeExporter(coordinate_mode="absolute", safe_z=10.0)
        gcode_abs = exporter_abs.export(waypoints)
        assert "absolute" in gcode_abs, "绝对模式应标注 absolute"

        exporter_inc = GCodeExporter(coordinate_mode="incremental", safe_z=10.0)
        gcode_inc = exporter_inc.export(waypoints)
        assert "incremental" in gcode_inc, "增量模式应标注 incremental"


# ================================================================
# 2. License HMAC 空密钥处理（任务H MF-3 修复）
# ================================================================
@pytest.mark.regression
class TestLicenseHmacEmptyKey:
    """验证 HMAC 空密钥时验证失败（MF-3 安全修复）。"""

    def test_empty_secret_rejects_hmac(self, monkeypatch):
        """空密钥时应拒绝 HMAC 验证。"""
        from repair_app.utils import license_manager
        # 将模块级密钥设为空字符串
        monkeypatch.setattr(license_manager, "_DEFAULT_HMAC_SECRET", "")
        mgr = license_manager.LicenseManager()
        result = mgr._verify_hmac({"machine_id": "test"}, "fake_signature")
        assert result is False, "空密钥应返回 False"

    def test_valid_secret_accepts_correct_hmac(self, monkeypatch):
        """有效密钥 + 正确签名应通过 HMAC 验证。"""
        from repair_app.utils import license_manager
        monkeypatch.setattr(license_manager, "_DEFAULT_HMAC_SECRET", "test_secret_2026")
        mgr = license_manager.LicenseManager()
        raw = {"machine_id": "test", "issued_to": "user"}
        payload = json.dumps(raw, sort_keys=True).encode()
        expected_sig = hmac_module.new(b"test_secret_2026", payload, hashlib.sha256).hexdigest()
        result = mgr._verify_hmac(raw, expected_sig)
        assert result is True, "正确签名应通过验证"

    def test_valid_secret_rejects_wrong_hmac(self, monkeypatch):
        """有效密钥 + 错误签名应拒绝。"""
        from repair_app.utils import license_manager
        monkeypatch.setattr(license_manager, "_DEFAULT_HMAC_SECRET", "test_secret_2026")
        mgr = license_manager.LicenseManager()
        result = mgr._verify_hmac({"machine_id": "test"}, "wrong_signature")
        assert result is False, "错误签名应被拒绝"


# ================================================================
# 3. ErrorManager 7 类错误分类正确（任务K）
# ================================================================
@pytest.mark.regression
class TestErrorManagerClassification:
    """验证 ErrorManager 的 7 类错误分类。"""

    def test_file_error_classification(self):
        """FileNotFoundError → ErrorCode.FILE。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(FileNotFoundError("test"))
        assert code == ErrorCode.FILE, f"FileNotFoundError 应分类为 FILE，实际 {code}"

    def test_permission_error_classification(self):
        """PermissionError → ErrorCode.FILE。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(PermissionError("denied"))
        assert code == ErrorCode.FILE, f"PermissionError 应分类为 FILE，实际 {code}"

    def test_timeout_error_classification(self):
        """TimeoutError → ErrorCode.NETWORK。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(TimeoutError("timeout"))
        assert code == ErrorCode.NETWORK, f"TimeoutError 应分类为 NETWORK，实际 {code}"

    def test_license_keyword_classification(self):
        """包含 'license' 关键字的异常 → ErrorCode.LICENSE。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(RuntimeError("license expired"))
        assert code == ErrorCode.LICENSE, f"license 关键字应分类为 LICENSE，实际 {code}"

    def test_matlab_keyword_classification(self):
        """包含 'matlab' 关键字的异常 → ErrorCode.MATLAB。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(RuntimeError("matlab engine failed"))
        assert code == ErrorCode.MATLAB, f"matlab 关键字应分类为 MATLAB，实际 {code}"

    def test_export_keyword_classification(self):
        """包含 'export' 关键字的异常 → ErrorCode.EXPORT。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(ValueError("export failed"))
        assert code == ErrorCode.EXPORT, f"export 关键字应分类为 EXPORT，实际 {code}"

    def test_mesh_keyword_classification(self):
        """包含 'mesh' 关键字的异常 → ErrorCode.MESH（避开 file 关键字优先）。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        # 注意：消息中不能包含 "file"，否则会先匹配到 FILE
        code = ErrorManager.classify(ValueError("mesh triangulation failed"))
        assert code == ErrorCode.MESH, f"mesh 关键字应分类为 MESH，实际 {code}"

    def test_unknown_fallback_classification(self):
        """未分类的异常 → ErrorCode.UNKNOWN。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(Exception("something unknown happened"))
        assert code == ErrorCode.UNKNOWN, f"未分类异常应为 UNKNOWN，实际 {code}"

    def test_all_7_error_codes_exist(self):
        """验证 7 类 ErrorCode 全部存在。"""
        from repair_app.utils.error_manager import ErrorCode
        expected_codes = {"license", "matlab", "file", "mesh", "network", "export", "unknown"}
        actual_codes = {c.value for c in ErrorCode}
        assert actual_codes == expected_codes, f"ErrorCode 应为 7 类，实际 {actual_codes}"


# ================================================================
# 4. ThemeManager 生成非空 QSS（任务L）
# ================================================================
@pytest.mark.regression
class TestThemeManagerQss:
    """验证 ThemeManager 生成非空 QSS。"""

    def test_qss_non_empty(self):
        """get_qss 应返回非空字符串。"""
        from repair_app.ui.theme_manager import ThemeManager
        qss = ThemeManager.get_qss()
        assert isinstance(qss, str), "QSS 应为字符串"
        assert len(qss) > 100, f"QSS 应有实质内容，长度仅 {len(qss)}"

    def test_qss_contains_key_widgets(self):
        """QSS 应包含关键控件样式。"""
        from repair_app.ui.theme_manager import ThemeManager
        qss = ThemeManager.get_qss()
        for widget in ["QPushButton", "QMenuBar", "QStatusBar", "QToolBar", "QComboBox"]:
            assert widget in qss, f"QSS 应包含 {widget} 样式"

    def test_dark_theme_qss_differs_from_light(self):
        """切换主题后 QSS 应变化。"""
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        qss_dark = ThemeManager.get_qss()
        ThemeManager.set_theme("light")
        qss_light = ThemeManager.get_qss()
        assert qss_dark != qss_light, "深色和浅色主题 QSS 应不同"


# ================================================================
# 5. DefectSelector 选区操作不丢失数据（任务L）
# ================================================================
@pytest.mark.regression
class TestDefectSelectorDataIntegrity:
    """验证选区操作不丢失点云数据。"""

    def test_clear_selection_preserves_points(self, qapp):
        """清除选区后点云数据不应丢失。"""
        from repair_app.ui.defect_selector import DefectSelector
        selector = DefectSelector()
        try:
            pts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0],
                            [0, 1, 0], [1, 1, 0]], dtype=float)
            selector.set_points(pts)
            # 选中部分点
            selector._mask = np.array([True, True, False, False, False])
            # 清除选区
            selector.clear_selection()
            # 验证点云未丢失
            assert selector._points is not None, "清除选区后点云不应为 None"
            assert len(selector._points) == 5, "点云数量应不变"
            # 验证掩码已清空
            assert not np.any(selector.get_selection_mask()), "掩码应全部为 False"
        finally:
            selector.deleteLater()
            qapp.processEvents()

    def test_invert_selection_preserves_points(self, qapp):
        """反选操作后点云数据不应丢失。"""
        from repair_app.ui.defect_selector import DefectSelector
        selector = DefectSelector()
        try:
            pts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0],
                            [0, 1, 0], [1, 1, 0]], dtype=float)
            selector.set_points(pts)
            selector._mask = np.array([True, False, True, False, False])
            # 反选
            selector.invert_selection()
            # 验证点云未丢失
            assert len(selector._points) == 5, "点云数量应不变"
            # 验证掩码已反转
            expected = np.array([False, True, False, True, True])
            assert np.array_equal(selector.get_selection_mask(), expected), "掩码应反转"
        finally:
            selector.deleteLater()
            qapp.processEvents()


# ================================================================
# 6. parameter_schema 无 Magic Number（任务J）
# ================================================================
@pytest.mark.regression
class TestSchemaNoMagicNumber:
    """验证 parameter_schema 结构完整，无 Magic Number。"""

    def test_process_params_have_full_structure(self):
        """所有工艺参数应有完整的 default/min/max/step/unit 字段。"""
        from repair_app.config import schema_loader
        schema = schema_loader.get_schema()
        for key, param in schema["process_parameters"].items():
            assert "default" in param, f"{key} 缺少 default"
            assert "min" in param, f"{key} 缺少 min"
            assert "max" in param, f"{key} 缺少 max"
            assert "step" in param, f"{key} 缺少 step"
            assert "unit" in param, f"{key} 缺少 unit"
            # 验证 min <= default <= max
            assert param["min"] <= param["default"] <= param["max"], \
                f"{key}: min({param['min']}) <= default({param['default']}) <= max({param['max']}) 不成立"

    def test_export_params_have_defaults(self):
        """导出参数应有 default 字段。"""
        from repair_app.config import schema_loader
        schema = schema_loader.get_schema()
        for key, param in schema.get("export_parameters", {}).items():
            assert "default" in param, f"导出参数 {key} 缺少 default"

    def test_gcode_exporter_reads_from_schema(self):
        """GCodeExporter 默认值应从 schema 读取而非硬编码。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        from repair_app.config import schema_loader
        exporter = GCodeExporter()
        expected_feed = float(schema_loader.get_export_value("gcode_feed_rate_mmpmin"))
        assert exporter.feed_rate == expected_feed, \
            f"feed_rate 应从 schema 读取({expected_feed})，实际 {exporter.feed_rate}"
        expected_safe_z = float(schema_loader.get_export_value("gcode_safe_z_mm"))
        assert exporter.safe_z == expected_safe_z, \
            f"safe_z 应从 schema 读取({expected_safe_z})，实际 {exporter.safe_z}"


# ================================================================
# 7. Workers failed 信号是三元组 (str, str, str)（任务K）
# ================================================================
@pytest.mark.regression
class TestWorkersFailedSignal:
    """验证 Worker 的 failed 信号为三元组 (str, str, str)。"""

    def test_pack_error_returns_3_strings(self):
        """_pack_error 应返回 (str, str, str) 三元组。"""
        from repair_app.ui.workers import _pack_error
        from repair_app.utils.error_manager import ErrorCode
        exc = ValueError("test error")
        result = _pack_error(exc, ErrorCode.UNKNOWN, "test context")
        assert isinstance(result, tuple), "_pack_error 应返回 tuple"
        assert len(result) == 3, f"应返回 3 元组，实际 {len(result)} 元组"
        for i, item in enumerate(result):
            assert isinstance(item, str), f"第 {i} 个元素应为 str，实际 {type(item)}"

    def test_path_planning_worker_has_failed_signal(self):
        """PathPlanningWorker 应有 failed 信号属性。"""
        from repair_app.ui.workers import PathPlanningWorker
        assert hasattr(PathPlanningWorker, "failed"), "PathPlanningWorker 应有 failed 信号"

    def test_compute_pipeline_worker_has_failed_signal(self):
        """ComputePipelineWorker 应有 failed 信号。"""
        from repair_app.ui.workers import ComputePipelineWorker
        assert hasattr(ComputePipelineWorker, "failed"), "ComputePipelineWorker 应有 failed 信号"

    def test_failed_signal_emits_3_strings(self, qapp):
        """failed 信号应能 emit 3 个字符串参数。"""
        from repair_app.ui.workers import PathPlanningWorker
        from repair_app.core.repair_session import RepairSession
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        session.selection.mask = np.ones(5, dtype=bool)
        worker = PathPlanningWorker(session, {"layer_height_mm": 2.0}, 1, 1.0)
        try:
            received = []
            worker.failed.connect(lambda c, m, d: received.append((c, m, d)))
            worker.failed.emit("network", "连接失败", "Traceback...")
            assert len(received) == 1, "应收到 1 条信号"
            code, msg, detail = received[0]
            assert code == "network"
            assert msg == "连接失败"
            assert detail == "Traceback..."
        finally:
            worker.deleteLater()
            qapp.processEvents()


# ================================================================
# 8. Toast 4 级别通知可创建（任务L）
# ================================================================
@pytest.mark.regression
class TestToastFourLevels:
    """验证 Toast 的 4 种级别通知可创建。"""

    def test_info_toast(self, qapp):
        """info 级别 Toast 可创建。"""
        from repair_app.ui.toast import Toast
        toast = Toast(None, "信息提示", "info", duration=100)
        assert toast is not None
        toast.deleteLater()
        qapp.processEvents()

    def test_success_toast(self, qapp):
        """success 级别 Toast 可创建。"""
        from repair_app.ui.toast import Toast
        toast = Toast(None, "操作成功", "success", duration=100)
        assert toast is not None
        toast.deleteLater()
        qapp.processEvents()

    def test_warning_toast(self, qapp):
        """warning 级别 Toast 可创建。"""
        from repair_app.ui.toast import Toast
        toast = Toast(None, "警告信息", "warning", duration=100)
        assert toast is not None
        toast.deleteLater()
        qapp.processEvents()

    def test_error_toast(self, qapp):
        """error 级别 Toast 可创建。"""
        from repair_app.ui.toast import Toast
        toast = Toast(None, "错误发生", "error", duration=100)
        assert toast is not None
        toast.deleteLater()
        qapp.processEvents()


# ================================================================
# 9. UndoStack 单例可获取（任务L）
# ================================================================
@pytest.mark.regression
class TestUndoStackSingleton:
    """验证 UndoStack 单例模式。"""

    def test_instance_returns_same_object(self, qapp):
        """UndoStack.instance() 应返回同一实例。"""
        from repair_app.ui.undo_framework import UndoStack
        UndoStack.reset()  # 重置以确保干净状态
        s1 = UndoStack.instance()
        s2 = UndoStack.instance()
        assert s1 is s2, "UndoStack.instance() 应返回同一实例"

    def test_instance_is_undo_stack(self, qapp):
        """UndoStack.instance() 应返回 UndoStack 类型。"""
        from repair_app.ui.undo_framework import UndoStack
        stack = UndoStack.instance()
        assert isinstance(stack, UndoStack), "应为 UndoStack 实例"

    def test_can_undo_initially_false(self, qapp):
        """空栈时 can_undo 应为 False。"""
        from repair_app.ui.undo_framework import UndoStack
        UndoStack.reset()
        stack = UndoStack.instance()
        stack.clear()
        assert stack.can_undo() is False, "空栈 can_undo 应为 False"
        assert stack.can_redo() is False, "空栈 can_redo 应为 False"
