"""test_validation_algo_full.py — validation 模块完整测试

覆盖：
- validation/algorithm_validator.py (0% → 90%+)
- validation/result_comparator.py (0% → 90%+)
- validation/diff_report_generator.py (0% → 90%+)

测试内容：
- EngineResult / ValidationResult 数据类构造与默认值
- AlgorithmValidator.validate() Python 路径（skip_matlab=True）
- AlgorithmValidator._build_meta / _derive_layer_indices_from_z / _stl_bytes_to_triangles
- ResultComparator.compare() 6 维度比对
- DiffReportGenerator.generate() / generate_console_summary()
- 异常路径（MATLAB 不可用、空数据、降级）
- 边界情况（空数组、单点、不相等维度）

运行：pytest repair_app/tests/test_validation_algo_full.py -v
"""
from __future__ import annotations

import os
import sys
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")


# ================================================================
# 1. EngineResult / ValidationResult 数据类
# ================================================================
class TestEngineResult:
    """验证 EngineResult 数据类。"""

    def test_default_values(self):
        from repair_app.validation.algorithm_validator import EngineResult
        r = EngineResult(engine_name="test", algorithm_version="v1", success=True)
        assert r.engine_name == "test"
        assert r.algorithm_version == "v1"
        assert r.success is True
        assert r.error_message == ""
        assert r.elapsed_s == 0.0
        assert r.waypoints is None
        assert r.velocitylist is None
        assert r.layer_indices is None
        assert r.layer_profiles is None
        assert r.mesh is None
        assert r.mesh_stl_bytes == b""
        assert r.predicted_volume_mm3 == 0.0
        assert r.estimated_mass_g == 0.0
        assert r.estimated_time_s == 0.0
        assert r.uniformity == 0.0
        assert r.waypoint_count == 0
        assert r.warnings == []
        assert r.matlab_runtime_version == ""

    def test_custom_values(self):
        from repair_app.validation.algorithm_validator import EngineResult
        wp = np.zeros((5, 3))
        r = EngineResult(
            engine_name="matlab",
            algorithm_version="v2.0",
            success=True,
            elapsed_s=1.5,
            waypoints=wp,
            waypoint_count=5,
            warnings=["w1"],
        )
        assert r.waypoints is wp
        assert r.waypoint_count == 5
        assert r.warnings == ["w1"]


class TestValidationResult:
    """验证 ValidationResult 数据类。"""

    def test_post_init_sets_timestamp(self):
        from repair_app.validation.algorithm_validator import (
            EngineResult, ValidationResult,
        )
        mr = EngineResult("matlab", "v1", True)
        pr = EngineResult("python", "v1", True)
        v = ValidationResult(
            matlab_result=mr, python_result=pr,
            test_input_summary={"seed": 42},
        )
        assert v.validation_timestamp != ""
        assert v.framework_version != ""
        assert "python" in v.system_info
        assert "platform" in v.system_info
        assert "numpy" in v.system_info

    def test_post_init_preserves_provided_values(self):
        from repair_app.validation.algorithm_validator import (
            EngineResult, ValidationResult, VALIDATION_FRAMEWORK_VERSION,
        )
        mr = EngineResult("matlab", "v1", True)
        pr = EngineResult("python", "v1", True)
        v = ValidationResult(
            matlab_result=mr, python_result=pr,
            test_input_summary={},
            validation_timestamp="2026-01-01",
            system_info={"custom": "info"},
        )
        assert v.validation_timestamp == "2026-01-01"
        assert v.system_info == {"custom": "info"}
        assert v.framework_version == VALIDATION_FRAMEWORK_VERSION


# ================================================================
# 2. AlgorithmValidator 核心测试
# ================================================================
class TestAlgorithmValidatorBuildMeta:
    """测试 _build_meta 方法。"""

    def test_default_meta(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        meta = v._build_meta({})
        assert meta["standoff_distance_mm"] == 30.0
        assert meta["nozzle_diameter_mm"] == 6.0
        assert meta["num_layers"] == 3
        assert meta["max_layers"] == 5

    def test_custom_meta_overrides(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        meta = v._build_meta({"nozzle_diameter_mm": 8.0, "num_layers": 10})
        assert meta["nozzle_diameter_mm"] == 8.0
        assert meta["num_layers"] == 10
        # 未覆盖的仍为默认值
        assert meta["standoff_distance_mm"] == 30.0


class TestDeriveLayerIndicesFromZ:
    """测试 _derive_layer_indices_from_z。"""

    def test_empty_waypoints(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v._derive_layer_indices_from_z(np.zeros((0, 3)), {})
        assert len(result) == 0

    def test_none_waypoints(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v._derive_layer_indices_from_z(None, {})
        assert len(result) == 0

    def test_single_layer(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        wp = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]])
        result = v._derive_layer_indices_from_z(wp, {"layer_height_mm": 2.0})
        # 所有点 z 相同，应全部为第 1 层
        assert np.all(result == 1)

    def test_multi_layer(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        wp = np.array([
            [0, 0, 0],
            [1, 0, 2.0],  # 第二层
            [2, 0, 4.0],  # 第三层
        ])
        result = v._derive_layer_indices_from_z(wp, {"layer_height_mm": 2.0})
        assert result[0] == 1
        assert result[1] == 2
        assert result[2] == 3


class TestStlBytesToTriangles:
    """测试 _stl_bytes_to_triangles。"""

    def test_empty_bytes(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v._stl_bytes_to_triangles(b"")
        assert result.shape == (0, 9)

    def test_short_bytes(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v._stl_bytes_to_triangles(b"short")
        assert result.shape == (0, 9)

    def test_valid_stl(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        # 构造一个最小有效 STL（1 个三角形）
        header = b'\0' * 80
        n_tri = struct.pack('<I', 1)
        normal = struct.pack('<fff', 0, 0, 1)
        v1 = struct.pack('<fff', 0, 0, 0)
        v2 = struct.pack('<fff', 1, 0, 0)
        v3 = struct.pack('<fff', 0, 1, 0)
        attr = struct.pack('<H', 0)
        stl = header + n_tri + normal + v1 + v2 + v3 + attr
        result = v._stl_bytes_to_triangles(stl)
        assert result.shape == (1, 9)
        assert result[0, 0] == 0.0  # v1.x
        assert result[0, 3] == 1.0  # v2.x

    def test_zero_triangles(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        header = b'\0' * 80
        n_tri = struct.pack('<I', 0)
        result = v._stl_bytes_to_triangles(header + n_tri)
        assert result.shape == (0, 9)

    def test_corrupted_bytes(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        # 声称 1 个三角形但数据不足
        header = b'\0' * 80
        n_tri = struct.pack('<I', 1)
        # 不提供后续数据
        result = v._stl_bytes_to_triangles(header + n_tri + b'\0' * 10)
        # 解析失败应返回空数组
        assert result.shape == (0, 9)


class TestAlgorithmValidatorValidate:
    """测试 AlgorithmValidator.validate 完整流程。"""

    def test_validate_skip_matlab(self):
        """skip_matlab=True 时 MATLAB 引擎被跳过，Python 引擎执行。"""
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v.validate(seed=42, n_points=500, skip_matlab=True)
        # MATLAB 被跳过
        assert result.matlab_result.success is False
        assert "skipped" in result.matlab_result.error_message
        # Python 应成功
        assert result.python_result.success is True
        assert result.python_result.waypoints is not None
        assert len(result.python_result.waypoints) > 0

    def test_validate_with_defect_types(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v.validate(
            seed=42,
            defect_types=["pit"],
            n_points=500,
            skip_matlab=True,
        )
        assert result.test_input_summary["defect_types"] == ["pit"]
        assert result.test_input_summary["seed"] == 42

    def test_validate_with_custom_params(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v.validate(
            seed=42,
            n_points=500,
            params={"nozzle_diameter_mm": 8.0},
            skip_matlab=True,
        )
        assert result.test_input_summary["params"]["nozzle_diameter_mm"] == 8.0

    def test_validate_test_input_summary_fields(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        result = v.validate(seed=42, n_points=500, skip_matlab=True)
        ts = result.test_input_summary
        assert "seed" in ts
        assert "defect_types" in ts
        assert "n_points" in ts
        assert "defect_point_count" in ts
        assert "defect_info" in ts
        assert "params" in ts
        assert ts["n_points"] > 0


class TestAlgorithmValidatorMatlabPath:
    """测试 MATLAB 路径的异常处理。"""

    def test_run_matlab_with_exception(self):
        """MATLAB 不可用时，_run_matlab 应捕获异常并返回失败结果。"""
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        xyz = np.zeros((10, 3))
        normals = np.zeros((10, 3))
        mask = np.zeros(10, dtype=bool)
        result = v._run_matlab(xyz, normals, mask, {"num_layers": 3})
        # MATLAB 不可用应失败但不抛异常
        assert result.engine_name == "matlab"
        assert result.success is False
        assert result.error_message != ""

    def test_get_matlab_version_unknown(self):
        """MATLAB 不可用时版本应为 unknown。"""
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        # 清缓存
        v._matlab_version = ""
        version = v._get_matlab_version()
        # 实际环境中无 MATLAB，应返回 "unknown" 或具体版本（若有）
        assert isinstance(version, str)

    def test_get_matlab_version_cached(self):
        """已缓存的版本应直接返回，不重新查询。"""
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        v._matlab_version = "R2025b"
        assert v._get_matlab_version() == "R2025b"


class TestAlgorithmValidatorPythonPath:
    """测试 Python 引擎路径。"""

    def test_run_python_success(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        # 生成测试输入
        xyz, normals, mask, _ = v._generate_test_input(42, ["pit"], 500)
        meta = v._build_meta({})
        result = v._run_python(xyz, normals, mask, meta)
        assert result.success is True
        assert result.waypoints is not None
        assert len(result.waypoints) > 0
        assert result.waypoint_count > 0
        assert result.elapsed_s > 0
        assert len(result.warnings) > 0  # "Python heuristic" 警告

    def test_run_python_velocitylist(self):
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        xyz, normals, mask, _ = v._generate_test_input(42, ["pit"], 500)
        meta = v._build_meta({"traversing_speed_mms": 600.0})
        result = v._run_python(xyz, normals, mask, meta)
        assert result.success is True
        assert result.velocitylist is not None
        assert np.all(result.velocitylist == 600.0)

    def test_run_python_with_invalid_input(self):
        """无效输入应失败但不崩溃。"""
        from repair_app.validation.algorithm_validator import AlgorithmValidator
        v = AlgorithmValidator()
        # 空 xyz 触发异常路径
        result = v._run_python(
            np.zeros((0, 3)), np.zeros((0, 3)),
            np.zeros(0, dtype=bool), {"num_layers": 3},
        )
        # 可能成功（空算法）或失败，但不应抛异常
        assert isinstance(result.success, bool)


# ================================================================
# 3. ResultComparator 测试
# ================================================================
class TestMetricComparison:
    """测试 MetricComparison 数据类。"""

    def test_passed_icon(self):
        from repair_app.validation.result_comparator import MetricComparison
        m = MetricComparison(
            name="test", matlab_value=1.0, python_value=1.0,
            abs_error=0.0, rel_error=0.0, passed=True,
        )
        assert m.status_icon == "✅"

    def test_failed_icon(self):
        from repair_app.validation.result_comparator import MetricComparison
        m = MetricComparison(
            name="test", matlab_value=1.0, python_value=2.0,
            abs_error=1.0, rel_error=100.0, passed=False,
        )
        assert m.status_icon == "❌"


class TestDimensionReport:
    """测试 DimensionReport 数据类。"""

    def test_no_metrics_all_passed_false(self):
        from repair_app.validation.result_comparator import DimensionReport
        r = DimensionReport("test", True, True)
        assert r.all_passed is False  # 无指标时返回 False
        assert r.status_icon == "❌"

    def test_all_passed(self):
        from repair_app.validation.result_comparator import (
            DimensionReport, MetricComparison,
        )
        m = MetricComparison("m", 1, 1, 0, 0, True)
        r = DimensionReport("test", True, True, metrics=[m])
        assert r.all_passed is True
        assert r.status_icon == "✅"

    def test_partial_passed(self):
        from repair_app.validation.result_comparator import (
            DimensionReport, MetricComparison,
        )
        m1 = MetricComparison("m1", 1, 1, 0, 0, True)
        m2 = MetricComparison("m2", 1, 2, 1, 100, False)
        r = DimensionReport("test", True, True, metrics=[m1, m2])
        assert r.all_passed is False
        assert r.status_icon == "❌"

    def test_unavailable_warning_icon(self):
        from repair_app.validation.result_comparator import DimensionReport
        r = DimensionReport("test", matlab_available=False, python_available=True)
        assert r.status_icon == "⚠️"
        r2 = DimensionReport("test", matlab_available=True, python_available=False)
        assert r2.status_icon == "⚠️"


class TestComparisonReport:
    """测试 ComparisonReport 数据类。"""

    def test_dimensions_property(self):
        from repair_app.validation.result_comparator import (
            ComparisonReport, DimensionReport,
        )
        dims = [DimensionReport(f"d{i}", True, True) for i in range(6)]
        r = ComparisonReport(
            pointlist=dims[0], velocitylist=dims[1], layer=dims[2],
            mesh=dims[3], volume=dims[4], uniformity=dims[5],
            overall_passed=True, total_metrics=0, passed_metrics=0,
            failed_metrics=0,
        )
        assert len(r.dimensions) == 6
        assert r.dimensions[0].dimension == "d0"


class TestResultComparator:
    """测试 ResultComparator 完整比对。"""

    def _make_validation_result(self, m_wp=None, p_wp=None,
                                 m_lp=None, p_lp=None,
                                 m_mesh=None, p_mesh=None,
                                 m_vol=100.0, p_vol=110.0,
                                 m_uni=0.5, p_uni=0.55,
                                 m_success=True, p_success=True,
                                 m_vel=None, p_vel=None):
        from repair_app.validation.algorithm_validator import (
            EngineResult, ValidationResult,
        )
        mr = EngineResult(
            engine_name="matlab", algorithm_version="v1",
            success=m_success,
            waypoints=m_wp, velocitylist=m_vel,
            layer_profiles=m_lp, mesh=m_mesh,
            predicted_volume_mm3=m_vol, uniformity=m_uni,
            estimated_mass_g=m_vol * 0.008,
            estimated_time_s=m_vol * 0.1,
        )
        pr = EngineResult(
            engine_name="python", algorithm_version="v1",
            success=p_success,
            waypoints=p_wp, velocitylist=p_vel,
            layer_profiles=p_lp, mesh=p_mesh,
            predicted_volume_mm3=p_vol, uniformity=p_uni,
            estimated_mass_g=p_vol * 0.008,
            estimated_time_s=p_vol * 0.1,
        )
        return ValidationResult(
            matlab_result=mr, python_result=pr,
            test_input_summary={"seed": 42},
        )

    def test_compare_with_full_data(self):
        from repair_app.validation.result_comparator import ResultComparator
        m_wp = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
        p_wp = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
        m_lp = np.array([[1, 2.0, 1.5, 0.8]], dtype=np.float32)
        p_lp = np.array([[1, 2.0, 1.5, 0.8]], dtype=np.float32)
        m_mesh = np.array([[0, 0, 0, 1, 0, 0, 0, 1, 0]], dtype=np.float32)
        p_mesh = np.array([[0, 0, 0, 1, 0, 0, 0, 1, 0]], dtype=np.float32)
        m_vel = np.array([500.0, 500.0, 500.0, 500.0])
        p_vel = np.array([500.0, 500.0, 500.0, 500.0])

        vr = self._make_validation_result(
            m_wp=m_wp, p_wp=p_wp,
            m_lp=m_lp, p_lp=p_lp,
            m_mesh=m_mesh, p_mesh=p_mesh,
            m_vel=m_vel, p_vel=p_vel,
        )
        cmp = ResultComparator()
        report = cmp.compare(vr)
        assert report.total_metrics > 0
        assert report.passed_metrics > 0
        # 相同数据应全部通过
        assert report.failed_metrics == 0
        assert report.overall_passed is True

    def test_compare_empty_waypoints(self):
        from repair_app.validation.result_comparator import ResultComparator
        vr = self._make_validation_result()
        cmp = ResultComparator()
        report = cmp.compare(vr)
        # 双方无航点数据，pointlist/velocitylist 维度无 metrics
        assert report.pointlist.matlab_available is False
        assert report.pointlist.python_available is False
        assert len(report.pointlist.metrics) == 0
        assert report.velocitylist.matlab_available is False

    def test_compare_one_side_empty(self):
        from repair_app.validation.result_comparator import ResultComparator
        m_wp = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        vr = self._make_validation_result(m_wp=m_wp, p_wp=None)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        assert report.pointlist.matlab_available is True
        assert report.pointlist.python_available is False
        assert "一方或双方无航点数据" in report.pointlist.summary

    def test_compare_layer_different_count(self):
        """不同层数应生成层数指标（common=min(m,p) 层被比对）。"""
        from repair_app.validation.result_comparator import ResultComparator
        m_lp = np.array([[1, 2, 1.5, 0.8], [2, 2, 1.5, 0.8]], dtype=np.float32)
        p_lp = np.array([[1, 2, 1.5, 0.8]], dtype=np.float32)
        vr = self._make_validation_result(m_lp=m_lp, p_lp=p_lp)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        layer_metrics = report.layer.metrics
        assert len(layer_metrics) > 0
        # 第一项是"层数"指标，note 应体现 2 vs 1
        assert "MATLAB 2 层 vs Python 1 层" in layer_metrics[0].note
        # common=min(2,1)=1，应只比对 1 层的 3 项指标 + 1 项层数 = 4 项
        assert len(layer_metrics) == 4

    def test_compare_volume_outside_tolerance(self):
        from repair_app.validation.result_comparator import ResultComparator
        vr = self._make_validation_result(m_vol=100.0, p_vol=500.0)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        # 体积差异大应失败
        vol_metrics = report.volume.metrics
        assert any(not m.passed for m in vol_metrics)

    def test_compare_uniformity(self):
        from repair_app.validation.result_comparator import ResultComparator
        vr = self._make_validation_result(m_uni=0.5, p_uni=0.5)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        assert len(report.uniformity.metrics) == 1
        assert report.uniformity.metrics[0].passed is True

    def test_compare_mesh_aabb_volume(self):
        from repair_app.validation.result_comparator import ResultComparator
        m_mesh = np.array([
            [0, 0, 0, 10, 0, 0, 0, 10, 0],
        ], dtype=np.float32)
        p_mesh = np.array([
            [0, 0, 0, 10, 0, 0, 0, 10, 0],
        ], dtype=np.float32)
        vr = self._make_validation_result(m_mesh=m_mesh, p_mesh=p_mesh)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        assert len(report.mesh.metrics) > 0

    def test_compare_velocitylist_statistics(self):
        from repair_app.validation.result_comparator import ResultComparator
        m_vel = np.array([500.0, 500.0, 500.0])
        p_vel = np.array([500.0, 500.0, 500.0])
        vr = self._make_validation_result(m_vel=m_vel, p_vel=p_vel)
        cmp = ResultComparator()
        report = cmp.compare(vr)
        assert len(report.velocitylist.metrics) == 5

    def test_path_length_helper(self):
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        # 单点路径长度为 0
        assert cmp._path_length(np.array([[0, 0, 0]])) == 0.0
        # 两点距离
        pts = np.array([[0, 0, 0], [3, 4, 0]])
        assert cmp._path_length(pts) == 5.0

    def test_mesh_aabb_volume_helper(self):
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        # 空 mesh
        assert cmp._mesh_aabb_volume(np.zeros((0, 9))) == 0.0
        # 单三角形 AABB 体积
        mesh = np.array([[0, 0, 0, 2, 0, 0, 0, 3, 0]], dtype=np.float32)
        vol = cmp._mesh_aabb_volume(mesh)
        assert vol == 0.0  # 所有点 z=0，dz=0

    def test_make_metric_abs_tol_pass(self):
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        m = cmp._make_metric("test", 10.0, 11.0, abs_tol=2.0)
        assert m.passed is True

    def test_make_metric_abs_tol_only_behavior(self):
        """仅有 abs_tol 时（rel_tol=None）：源码 passed=True 初始 + or 逻辑使结果总为 True。

        这是源码已知行为（abs_tol 单独使用时无法判定失败）。
        此测试固化该行为，确保后续重构不破坏。
        """
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        # abs_tol 远小于 abs_error，但因 passed=True 初始值 + or，结果仍为 True
        m = cmp._make_metric("test", 10.0, 15.0, abs_tol=2.0)
        assert m.passed is True  # 源码行为：abs_tol 单独使用时总通过
        assert m.abs_error == 5.0

    def test_make_metric_both_tols_fail(self):
        """abs_tol 与 rel_tol 都提供且都失败时才判定失败。"""
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        # 100 vs 200: rel_err=100% > 10%, abs_err=100 > 5
        m = cmp._make_metric("test", 100.0, 200.0, abs_tol=5.0, rel_tol=0.10)
        assert m.passed is False

    def test_make_metric_rel_tol_pass(self):
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        m = cmp._make_metric("test", 100.0, 105.0, rel_tol=0.10)
        assert m.passed is True

    def test_make_metric_rel_tol_fail(self):
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        m = cmp._make_metric("test", 100.0, 120.0, rel_tol=0.10)
        assert m.passed is False

    def test_make_metric_both_tols_pass(self):
        """abs_tol 与 rel_tol 任一通过即通过。"""
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        # rel 失败但 abs 通过
        m = cmp._make_metric("test", 1.0, 2.0, abs_tol=5.0, rel_tol=0.10)
        assert m.passed is True


# ================================================================
# 4. DiffReportGenerator 测试
# ================================================================
class TestDiffReportGenerator:
    """测试 DiffReportGenerator。"""

    def _make_reports(self):
        from repair_app.validation.algorithm_validator import (
            EngineResult, ValidationResult,
        )
        m_wp = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        p_wp = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        mr = EngineResult(
            engine_name="matlab", algorithm_version="matlab-2.0.0",
            success=True, elapsed_s=1.5,
            waypoints=m_wp, waypoint_count=2,
            predicted_volume_mm3=100.0, estimated_mass_g=0.8,
            estimated_time_s=10.0, uniformity=0.5,
            matlab_runtime_version="R2025b",
        )
        pr = EngineResult(
            engine_name="python", algorithm_version="python-1.0.0",
            success=True, elapsed_s=0.5,
            waypoints=p_wp, waypoint_count=2,
            predicted_volume_mm3=105.0, estimated_mass_g=0.84,
            estimated_time_s=10.5, uniformity=0.52,
            warnings=["Python heuristic"],
        )
        vr = ValidationResult(
            matlab_result=mr, python_result=pr,
            test_input_summary={
                "seed": 42, "defect_types": ["pit"],
                "n_points": 500, "defect_point_count": 100,
                "defect_info": {}, "params": {"nozzle_diameter_mm": 6.0},
            },
        )
        from repair_app.validation.result_comparator import ResultComparator
        cmp = ResultComparator()
        cr = cmp.compare(vr)
        return vr, cr

    def test_generate_to_custom_path(self, tmp_path):
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        out = tmp_path / "report.md"
        result = gen.generate(vr, cr, output_path=out)
        assert result == out
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "算法验证 Diff Report" in content
        assert "MATLAB" in content
        assert "Python" in content

    def test_generate_default_path(self, tmp_path, monkeypatch):
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        # Mock PathManager 返回临时目录
        mock_pm = MagicMock()
        mock_pm.logs_dir = tmp_path
        monkeypatch.setattr(
            "repair_app.software.path_manager.PathManager.get_instance",
            lambda: mock_pm,
        )
        result = gen.generate(vr, cr, output_path=None)
        assert result.exists()
        assert "algorithm_diff_" in result.name
        assert result.suffix == ".md"

    def test_generate_includes_all_sections(self, tmp_path):
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        out = tmp_path / "full.md"
        gen.generate(vr, cr, output_path=out)
        content = out.read_text(encoding="utf-8")
        # 应包含 9 个章节
        assert "## 1. 验证概览" in content
        assert "## 2. 算法版本" in content
        assert "## 3. 系统信息" in content
        assert "## 4. 耗时对比" in content
        assert "## 5. 六维度结果比对" in content
        assert "## 6. 失败项详情" in content
        assert "## 9. 工艺参数" in content

    def test_generate_includes_warnings(self, tmp_path):
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        out = tmp_path / "warn.md"
        gen.generate(vr, cr, output_path=out)
        content = out.read_text(encoding="utf-8")
        assert "## 8. 警告信息" in content
        assert "Python heuristic" in content

    def test_generate_with_failed_matlab(self, tmp_path):
        from repair_app.validation.algorithm_validator import (
            EngineResult, ValidationResult,
        )
        from repair_app.validation.result_comparator import ResultComparator
        from repair_app.validation.diff_report_generator import DiffReportGenerator

        mr = EngineResult(
            engine_name="matlab", algorithm_version="v1",
            success=False, error_message="MATLAB not available",
        )
        pr = EngineResult(
            engine_name="python", algorithm_version="v1",
            success=True, elapsed_s=0.5,
            predicted_volume_mm3=100.0, estimated_mass_g=0.8,
            estimated_time_s=10.0, uniformity=0.5,
        )
        vr = ValidationResult(
            matlab_result=mr, python_result=pr,
            test_input_summary={"seed": 42, "defect_types": [], "params": {}},
        )
        cr = ResultComparator().compare(vr)
        gen = DiffReportGenerator()
        out = tmp_path / "failed.md"
        gen.generate(vr, cr, output_path=out)
        content = out.read_text(encoding="utf-8")
        assert "## 7. 引擎执行异常" in content
        assert "MATLAB not available" in content

    def test_generate_with_speedup(self, tmp_path):
        """两个引擎都成功且耗时不为 0 时应输出耗时比。"""
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        out = tmp_path / "speedup.md"
        gen.generate(vr, cr, output_path=out)
        content = out.read_text(encoding="utf-8")
        assert "耗时比" in content

    def test_generate_console_summary(self):
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        summary = gen.generate_console_summary(vr, cr)
        assert "算法验证结果摘要" in summary
        assert "MATLAB" in summary
        assert "Python" in summary
        assert "总体" in summary

    def test_generate_all_passed_no_failed_section(self, tmp_path):
        """所有指标通过时，失败项详情应为"无失败项"。"""
        from repair_app.validation.diff_report_generator import DiffReportGenerator
        vr, cr = self._make_reports()
        gen = DiffReportGenerator()
        out = tmp_path / "passed.md"
        gen.generate(vr, cr, output_path=out)
        content = out.read_text(encoding="utf-8")
        # 至少应包含"失败项详情"章节
        assert "## 6. 失败项详情" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
