"""test_smoke.py — 冒烟测试

验证核心模块可导入、核心函数可调用、核心类可实例化。
快速验证系统启动无致命错误（目标 <2s）。

运行：pytest -m smoke -v
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


@pytest.mark.smoke
class TestSmokeImports:
    """验证关键模块可导入且暴露核心 API。"""

    def test_version_exists(self):
        """验证 repair_app.__version__ 存在且为非空字符串。"""
        import repair_app
        assert hasattr(repair_app, "__version__"), "repair_app 应有 __version__ 属性"
        assert isinstance(repair_app.__version__, str), "__version__ 应为字符串"
        assert len(repair_app.__version__) > 0, "__version__ 不应为空"

    def test_import_path_planner(self):
        """验证 path_planner 模块可导入且有核心函数。"""
        from repair_app.core import path_planner
        assert hasattr(path_planner, "plan_path_from_cloud"), "path_planner 应有 plan_path_from_cloud"
        assert hasattr(path_planner, "generate_path"), "path_planner 应有 generate_path"
        assert hasattr(path_planner, "iter_path_from_cloud"), "path_planner 应有 iter_path_from_cloud"
        assert callable(path_planner.plan_path_from_cloud)

    def test_import_morphology_predictor(self):
        """验证 morphology_predictor 模块可导入。"""
        from repair_app.core import morphology_predictor
        assert hasattr(morphology_predictor, "predict_profile"), "morphology_predictor 应有 predict_profile"
        assert hasattr(morphology_predictor, "iter_repair_mesh_layers"), "应有 iter_repair_mesh_layers"
        assert callable(morphology_predictor.predict_profile)

    def test_import_gcode_exporter(self):
        """验证 gcode_exporter 模块可导入。"""
        from repair_app.export import gcode_exporter
        assert hasattr(gcode_exporter, "GCodeExporter"), "gcode_exporter 应有 GCodeExporter 类"
        assert hasattr(gcode_exporter, "export_snake_path"), "gcode_exporter 应有 export_snake_path"

    def test_import_robot_exporter(self):
        """验证 robot_exporter 模块可导入。"""
        from repair_app.export import robot_exporter
        assert hasattr(robot_exporter, "RobotExporter"), "robot_exporter 应有 RobotExporter 类"
        assert hasattr(robot_exporter, "RobotType"), "robot_exporter 应有 RobotType 枚举"

    def test_import_report_generator(self):
        """验证 report_generator 模块可导入。"""
        from repair_app.export import report_generator
        assert hasattr(report_generator, "RepairReport"), "report_generator 应有 RepairReport 类"

    def test_import_license_manager(self):
        """验证 license_manager 模块可导入。"""
        from repair_app.utils import license_manager
        assert hasattr(license_manager, "LicenseManager"), "license_manager 应有 LicenseManager 类"
        assert hasattr(license_manager, "LicenseData"), "license_manager 应有 LicenseData 类"

    def test_import_logger_config(self):
        """验证 logger_config 模块可导入且有核心函数。"""
        from repair_app.utils import logger_config
        assert hasattr(logger_config, "setup_logging"), "logger_config 应有 setup_logging"
        assert hasattr(logger_config, "info"), "logger_config 应有 info"
        assert hasattr(logger_config, "error"), "logger_config 应有 error"
        assert hasattr(logger_config, "get_logger"), "logger_config 应有 get_logger"
        assert callable(logger_config.info)

    def test_import_error_manager(self):
        """验证 error_manager 模块可导入。"""
        from repair_app.utils import error_manager
        assert hasattr(error_manager, "ErrorManager"), "error_manager 应有 ErrorManager 类"
        assert hasattr(error_manager, "ErrorCode"), "error_manager 应有 ErrorCode 枚举"

    def test_import_theme_manager(self):
        """验证 theme_manager 模块可导入。"""
        from repair_app.ui import theme_manager
        assert hasattr(theme_manager, "ThemeManager"), "theme_manager 应有 ThemeManager 类"

    def test_import_main_window(self):
        """验证 main_window 模块可导入。"""
        from repair_app.ui import main_window
        assert hasattr(main_window, "MainWindow"), "main_window 应有 MainWindow 类"


@pytest.mark.smoke
class TestSmokeFunctions:
    """验证核心函数可调用且返回值结构正确。"""

    def test_generate_defect_sample(self):
        """验证 generate_defect_sample(n_points=50) 返回非空且结构正确。"""
        from repair_app.core.defect_sample import generate_defect_sample
        xyz, normals, defect_mask, defect_info = generate_defect_sample(n_points=50)
        # 验证返回值结构与内容
        assert isinstance(xyz, np.ndarray), "xyz 应为 np.ndarray"
        assert xyz.ndim == 2 and xyz.shape[1] == 3, f"xyz 形状应为 (N,3)，实际 {xyz.shape}"
        assert len(xyz) > 0, "xyz 不应为空"
        assert isinstance(normals, np.ndarray), "normals 应为 np.ndarray"
        assert normals.shape == xyz.shape, "normals 形状应与 xyz 一致"
        assert isinstance(defect_mask, np.ndarray), "defect_mask 应为 np.ndarray"
        assert defect_mask.dtype == bool, "defect_mask 应为 bool 类型"
        assert len(defect_mask) == len(xyz), "defect_mask 长度应与 xyz 一致"
        assert isinstance(defect_info, dict), "defect_info 应为 dict"
        assert "defects" in defect_info, "defect_info 应包含 'defects' 键"

    def test_schema_loader_brush_radius(self):
        """验证 schema_loader.get_ui_default('brush_radius_mm') 返回正数。"""
        from repair_app.config import schema_loader
        val = schema_loader.get_ui_default("brush_radius_mm")
        assert isinstance(val, (int, float)), f"brush_radius_mm 应为数值，实际 {type(val)}"
        assert val > 0, f"brush_radius_mm 应为正数，实际 {val}"

    def test_error_manager_classify(self):
        """验证 ErrorManager.classify(ValueError('test')) 返回 ErrorCode 枚举。"""
        from repair_app.utils.error_manager import ErrorManager, ErrorCode
        code = ErrorManager.classify(ValueError("test"))
        assert isinstance(code, ErrorCode), f"classify 应返回 ErrorCode，实际 {type(code)}"

    def test_deterministic_algorithm_mock(self):
        """验证确定性算法 Mock 可用且返回结构正确的非空数组。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        result = deterministic_algorithm(np.zeros((10, 3)), {})
        assert isinstance(result, np.ndarray), "deterministic_algorithm 应返回 np.ndarray"
        assert result.ndim == 2, f"结果应为 2D 数组，实际 {result.ndim}D"
        assert result.shape[1] == 3, f"结果列数应为 3，实际 {result.shape[1]}"
        assert len(result) > 0, "结果不应为空"
        assert result.dtype == np.float32, f"结果 dtype 应为 float32，实际 {result.dtype}"
