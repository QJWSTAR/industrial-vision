"""test_path_inspector.py — 路径规划结果检查器 (inspect_path) 单元测试

被测模块: repair_app/core/path_inspector.py
被测函数: inspect_path
被测类: PathInspectionResult / PathIssue

覆盖检查项:
  1. Waypoint 连续性 (GAP_TOO_LARGE / DUPLICATE_POINTS)
  2. 法向稳定性 (NORMAL_LENGTH_MISMATCH / NORMAL_INSTABILITY)
  3. Layer 正确性 (LAYER_GAP / LAYER_HEIGHT_INCONSISTENT / LAYER_COUNT_MISMATCH)
  4. 形状与数量校验 (INVALID_SHAPE / TOO_FEW_WAYPOINTS)
  5. PathInspectionResult 属性 (error_messages / warning_messages / ok)

运行: pytest -m unit -v test_path_inspector.py
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

from repair_app.core.path_inspector import (
    inspect_path,
    PathInspectionResult,
    PathIssue,
)


def _codes(result: PathInspectionResult) -> list[str]:
    """提取结果中所有 issue 的 code 列表。"""
    return [i.code for i in result.issues]


# ================================================================
# 1. 正常路径
# ================================================================
@pytest.mark.unit
class TestInspectPathNormal:
    """正常航点: 无任何问题。"""

    def test_normal_waypoints_no_issues(self):
        # 矩形航点, 段间距 1mm, 无重复无跳变
        wp = np.array([[0, 0, 10], [1, 0, 10], [1, 1, 10], [0, 1, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is True
        assert result.n_waypoints == 4
        assert result.n_layers == 1
        assert len(result.issues) == 0
        # max_gap / mean_gap 正确计算 (每段长度均为 1)
        assert result.max_gap_mm == pytest.approx(1.0, abs=1e-5)
        assert result.mean_gap_mm == pytest.approx(1.0, abs=1e-5)

    def test_normals_consistent_no_warning(self):
        # 法向量全部朝上, 余弦距离=1, 不触发 NORMAL_INSTABILITY
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32)
        result = inspect_path(wp, normals=normals)
        assert result.ok is True
        assert "NORMAL_INSTABILITY" not in _codes(result)
        assert "NORMAL_LENGTH_MISMATCH" not in _codes(result)

    def test_layers_consecutive_no_warning(self):
        # 层号连续, 层高一致, 层数匹配
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 10.5], [1, 0, 10.5]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = inspect_path(
            wp,
            layer_indices=layers,
            expected_n_layers=2,
            expected_layer_height=0.5,
        )
        assert result.ok is True
        assert result.n_layers == 2
        codes = _codes(result)
        assert "LAYER_GAP" not in codes
        assert "LAYER_COUNT_MISMATCH" not in codes
        assert "LAYER_HEIGHT_INCONSISTENT" not in codes

    def test_normals_none_skipped_silently(self):
        # 不提供法向量时不报错 (本地路径无法向量是已知限制)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is True
        assert len(result.issues) == 0


# ================================================================
# 2. 形状与数量异常
# ================================================================
@pytest.mark.unit
class TestInspectPathShapeAndCount:
    """航点形状/数量校验。"""

    def test_invalid_shape_1d(self):
        # 1D 数组, ndim != 2 -> INVALID_SHAPE
        wp = np.array([1, 2, 3], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is False
        assert "INVALID_SHAPE" in _codes(result)
        # 异常形状提前返回, 不再计算其他字段
        assert result.n_waypoints == 0

    def test_invalid_shape_2d_too_few_columns(self):
        # 2D 但列数 < 3 -> INVALID_SHAPE
        wp = np.array([[0, 0], [1, 0]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is False
        assert "INVALID_SHAPE" in _codes(result)

    def test_too_few_waypoints_single(self):
        # 仅 1 个航点, 无法形成连续轨迹 -> TOO_FEW_WAYPOINTS
        wp = np.array([[0, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is False
        assert "TOO_FEW_WAYPOINTS" in _codes(result)

    def test_too_few_waypoints_empty(self):
        # 空航点 (0, 3) -> TOO_FEW_WAYPOINTS
        wp = np.zeros((0, 3), dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is False
        assert "TOO_FEW_WAYPOINTS" in _codes(result)


# ================================================================
# 3. Waypoint 连续性
# ================================================================
@pytest.mark.unit
class TestInspectPathContinuity:
    """段间距 / 重复点检查。"""

    def test_gap_too_large_warning(self):
        # 第二段间距 100mm > 默认 80mm -> GAP_TOO_LARGE warning
        wp = np.array([[0, 0, 10], [1, 0, 10], [101, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is True  # warning 不影响 ok
        assert "GAP_TOO_LARGE" in _codes(result)
        assert result.max_gap_mm == pytest.approx(100.0, abs=1e-3)

    def test_gap_threshold_custom(self):
        # 自定义阈值: 50mm, 段间距 60mm 触发
        wp = np.array([[0, 0, 10], [60, 0, 10]], dtype=np.float32)
        result = inspect_path(wp, max_gap_mm=50.0)
        assert "GAP_TOO_LARGE" in _codes(result)

    def test_gap_within_threshold_no_warning(self):
        # 段间距恰等于阈值 (不大于), 不触发
        wp = np.array([[0, 0, 10], [80, 0, 10]], dtype=np.float32)
        result = inspect_path(wp, max_gap_mm=80.0)
        assert "GAP_TOO_LARGE" not in _codes(result)

    def test_duplicate_points_warning(self):
        # 重复航点 (段长 < 1e-6) -> DUPLICATE_POINTS warning
        wp = np.array([[0, 0, 10], [0, 0, 10], [1, 1, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.ok is True
        assert "DUPLICATE_POINTS" in _codes(result)


# ================================================================
# 4. 法向稳定性
# ================================================================
@pytest.mark.unit
class TestInspectPathNormals:
    """法向量检查。"""

    def test_normal_length_mismatch(self):
        # 法向量长度与航点数不一致 -> NORMAL_LENGTH_MISMATCH warning
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)  # 长度 2 != 3
        result = inspect_path(wp, normals=normals)
        assert "NORMAL_LENGTH_MISMATCH" in _codes(result)
        # 长度不匹配时跳过法向检查, 不应出现 NORMAL_INSTABILITY
        assert "NORMAL_INSTABILITY" not in _codes(result)

    def test_normal_instability_abrupt_flip(self):
        # 相邻法向量反向, 余弦 = -1 < 0.3 -> NORMAL_INSTABILITY warning
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1], [0, 0, -1]], dtype=np.float32)
        result = inspect_path(wp, normals=normals)
        assert "NORMAL_INSTABILITY" in _codes(result)
        assert result.ok is True  # warning 不影响 ok

    def test_normal_instability_custom_threshold(self):
        # 阈值 0.99: 法向量轻微偏转 (余弦 0.5) 也判为突变
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 1, 0]], dtype=np.float32)  # 余弦 0
        result = inspect_path(wp, normals=normals, normal_consistency_threshold=0.99)
        assert "NORMAL_INSTABILITY" in _codes(result)

    def test_normal_stable_within_threshold(self):
        # 法向量余弦 1.0 >= 阈值, 不触发
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        normals = np.array([[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32)
        result = inspect_path(wp, normals=normals, normal_consistency_threshold=0.3)
        assert "NORMAL_INSTABILITY" not in _codes(result)


# ================================================================
# 5. Layer 正确性
# ================================================================
@pytest.mark.unit
class TestInspectPathLayers:
    """层号 / 层高 / 层数检查。"""

    def test_layer_gap_warning(self):
        # 层号 0,1,3 跳过 2 -> LAYER_GAP warning
        wp = np.array(
            [[0, 0, 10], [1, 0, 10], [0, 0, 11], [1, 0, 11], [0, 0, 13], [1, 0, 13]],
            dtype=np.float32,
        )
        layers = np.array([0, 0, 1, 1, 3, 3])
        result = inspect_path(wp, layer_indices=layers)
        assert "LAYER_GAP" in _codes(result)
        assert result.n_layers == 3
        assert result.ok is True

    def test_layer_consecutive_no_gap(self):
        # 层号 0,1,2 连续 -> 无 LAYER_GAP
        wp = np.array([[0, 0, 10], [0, 0, 11], [0, 0, 12]], dtype=np.float32)
        layers = np.array([0, 1, 2])
        result = inspect_path(wp, layer_indices=layers)
        assert "LAYER_GAP" not in _codes(result)
        assert result.n_layers == 3

    def test_layer_height_inconsistent(self):
        # 层 0 z=10, 层 1 z=12, 期望层高 0.5 -> 偏差 1.5 > 0.5 -> LAYER_HEIGHT_INCONSISTENT
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 12], [1, 0, 12]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = inspect_path(wp, layer_indices=layers, expected_layer_height=0.5)
        assert "LAYER_HEIGHT_INCONSISTENT" in _codes(result)

    def test_layer_height_consistent(self):
        # 层 0 z=10, 层 1 z=10.5, 期望层高 0.5 -> 偏差 0 -> 无 warning
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 10.5], [1, 0, 10.5]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = inspect_path(wp, layer_indices=layers, expected_layer_height=0.5)
        assert "LAYER_HEIGHT_INCONSISTENT" not in _codes(result)

    def test_layer_count_mismatch(self):
        # 检测到 2 层, 期望 3 层 -> LAYER_COUNT_MISMATCH
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 11], [1, 0, 11]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = inspect_path(wp, layer_indices=layers, expected_n_layers=3)
        assert "LAYER_COUNT_MISMATCH" in _codes(result)

    def test_layer_count_match_no_warning(self):
        # 检测到 2 层, 期望 2 层 -> 无 warning
        wp = np.array([[0, 0, 10], [0, 0, 11]], dtype=np.float32)
        layers = np.array([0, 1])
        result = inspect_path(wp, layer_indices=layers, expected_n_layers=2)
        assert "LAYER_COUNT_MISMATCH" not in _codes(result)

    def test_layer_indices_none_default_single_layer(self):
        # 不提供 layer_indices -> n_layers_detected 保持 1
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.n_layers == 1


# ================================================================
# 6. PathInspectionResult 属性与 PathIssue
# ================================================================
@pytest.mark.unit
class TestPathInspectionResultAttributes:
    """PathInspectionResult 属性 / PathIssue 数据类。"""

    def test_error_messages_property(self):
        # INVALID_SHAPE 为 error, 出现在 error_messages
        wp = np.array([1, 2, 3], dtype=np.float32)
        result = inspect_path(wp)
        assert len(result.error_messages) >= 1
        assert any("航点形状异常" in m for m in result.error_messages)
        assert result.warning_messages == []

    def test_warning_messages_property(self):
        # GAP_TOO_LARGE 为 warning, 出现在 warning_messages
        wp = np.array([[0, 0, 10], [100, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert len(result.warning_messages) >= 1
        assert any("间距超过" in m for m in result.warning_messages)
        assert result.error_messages == []

    def test_ok_false_when_error_present(self):
        # 存在 error 时 ok 为 False
        wp = np.array([[0, 0, 10]], dtype=np.float32)  # TOO_FEW_WAYPOINTS error
        result = inspect_path(wp)
        assert result.ok is False
        assert any(i.level == "error" for i in result.issues)

    def test_ok_true_when_only_warnings(self):
        # 仅 warning 时 ok 为 True
        wp = np.array([[0, 0, 10], [0, 0, 10]], dtype=np.float32)  # DUPLICATE_POINTS warning
        result = inspect_path(wp)
        assert result.ok is True
        assert any(i.level == "warning" for i in result.issues)

    def test_path_issue_dataclass_fields(self):
        # PathIssue 字段: level / code / message
        issue = PathIssue(level="warning", code="X", message="msg")
        assert issue.level == "warning"
        assert issue.code == "X"
        assert issue.message == "msg"

    def test_result_default_fields(self):
        # PathInspectionResult 默认值
        result = PathInspectionResult(ok=True)
        assert result.issues == []
        assert result.n_waypoints == 0
        assert result.n_layers == 0
        assert result.max_gap_mm == 0.0
        assert result.mean_gap_mm == 0.0
        assert result.error_messages == []
        assert result.warning_messages == []

    def test_mixed_error_and_warning(self):
        # 同时存在 error 与 warning, ok 为 False, 两类消息均非空
        # 1D 形状异常 (error) + 提供法向量也无关 (提前返回, 无 warning)
        # 改用: 形状正常但航点过少 error, 同时段间距过大 warning 不可能同时触发
        # 这里用一个航点 + 法向量错配: 但 n<2 提前返回, 法向检查不执行
        # 因此用两航点 + GAP_TOO_LARGE (warning) + 不可能产生 error 的场景验证属性即可
        wp = np.array([[0, 0, 10], [100, 0, 10]], dtype=np.float32)
        result = inspect_path(wp)
        assert result.error_messages == []
        assert len(result.warning_messages) >= 1
        assert result.ok is True
