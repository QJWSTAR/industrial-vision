"""test_validation_full.py — 导出前路径安全校验 (validate_toolpath) 单元测试

被测模块: repair_app/export/export_validator.py
被测函数: validate_toolpath
被测类: ExportValidationResult / ExportIssue / ExportIssueLevel
被测方法: ExportValidationResult.generate_report

覆盖检查项:
  1. 基础校验 (INVALID_SHAPE / TOO_FEW_WAYPOINTS / NON_FINITE_COORD /
     DUPLICATE_POINTS / LONG_SEGMENT)
  2. 安全高度 (UNSAFE_Z)
  3. 速度校验 (VELOCITY_LENGTH / NON_FINITE_FEED / FEED_OUT_OF_RANGE)
  4. P2-5: 碰撞检查 (COLLISION_RISK)
  5. P2-5: 边界检查 (OUT_OF_BOUNDS)
  6. P2-5: 高度检查 (NEGATIVE_HEIGHT / HEIGHT_OVER_SAFE_Z)
  7. P2-5: 层检查 (LAYER_GAP / LAYER_COUNT_MISMATCH / LAYER_HEIGHT_INCONSISTENT)
  8. ExportValidationResult 属性 (ok / blocking_messages / warning_messages / info_messages)
  9. ExportValidationResult.generate_report() Markdown 报告落盘

运行: pytest -m unit -v test_validation_full.py
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

from repair_app.export.export_validator import (
    validate_toolpath,
    ExportValidationResult,
    ExportIssue,
    ExportIssueLevel,
)


def _codes(result: ExportValidationResult) -> list[str]:
    """提取结果中所有 issue 的 code 列表。"""
    return [i.code for i in result.issues]


# ================================================================
# 1. 正常路径
# ================================================================
@pytest.mark.unit
class TestValidateToolpathNormal:
    """正常航点: 无任何问题。"""

    def test_normal_waypoints_ok(self):
        # 矩形航点, 段间距 1mm, 无重复/无长段/无 NaN
        wp = np.array([[0, 0, 10], [1, 0, 10], [1, 1, 10], [0, 1, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert result.ok is True
        assert len(result.issues) == 0

    def test_normal_with_valid_velocities(self):
        # 提供合法速度数组 (长度匹配 + 在范围内)
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        velocities = np.array([1000.0, 2000.0, 3000.0])
        result = validate_toolpath(wp, velocities=velocities)
        assert result.ok is True
        assert "VELOCITY_LENGTH" not in _codes(result)
        assert "FEED_OUT_OF_RANGE" not in _codes(result)

    def test_safe_z_above_path(self):
        # safe_z 高于路径最高点 -> 无 UNSAFE_Z
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp, safe_z=100.0)
        assert "UNSAFE_Z" not in _codes(result)
        assert result.ok is True


# ================================================================
# 2. 形状 / 数量 / 非有限值
# ================================================================
@pytest.mark.unit
class TestValidateToolpathShapeAndFinite:
    """形状异常 / 航点过少 / NaN 坐标。"""

    def test_invalid_shape_1d(self):
        # 1D 数组 -> INVALID_SHAPE (BLOCKED), 提前返回
        wp = np.array([1, 2, 3], dtype=np.float32)
        result = validate_toolpath(wp)
        assert result.ok is False
        assert "INVALID_SHAPE" in _codes(result)
        # 提前返回, 仅含 INVALID_SHAPE
        assert len(result.issues) == 1

    def test_invalid_shape_2d_too_few_columns(self):
        # 2D 列数 < 3 -> INVALID_SHAPE
        wp = np.array([[0, 0], [1, 0]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert result.ok is False
        assert "INVALID_SHAPE" in _codes(result)

    def test_too_few_waypoints(self):
        # 仅 1 个航点 -> TOO_FEW_WAYPOINTS (BLOCKED)
        wp = np.array([[0, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert result.ok is False
        assert "TOO_FEW_WAYPOINTS" in _codes(result)

    def test_non_finite_coord_nan(self):
        # NaN 坐标 -> NON_FINITE_COORD (BLOCKED)
        wp = np.array([[0, 0, 10], [1, np.nan, 10], [1, 1, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert result.ok is False
        assert "NON_FINITE_COORD" in _codes(result)

    def test_non_finite_coord_inf(self):
        # Inf 坐标同样触发 NON_FINITE_COORD
        wp = np.array([[0, 0, 10], [1, 0, np.inf]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert "NON_FINITE_COORD" in _codes(result)
        assert result.ok is False


# ================================================================
# 3. 重复点 / 长段
# ================================================================
@pytest.mark.unit
class TestValidateToolpathSegments:
    """重复点 / 长段路径。"""

    def test_duplicate_points_warning(self):
        # 重复航点 (段长 <= 1e-9) -> DUPLICATE_POINTS (WARNING)
        wp = np.array([[0, 0, 10], [0, 0, 10], [1, 1, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert "DUPLICATE_POINTS" in _codes(result)
        assert result.ok is True  # warning 不阻断

    def test_long_segment_warning(self):
        # 段长 100mm > 默认 80mm -> LONG_SEGMENT (WARNING)
        wp = np.array([[0, 0, 10], [100, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert "LONG_SEGMENT" in _codes(result)
        assert result.ok is True

    def test_long_segment_custom_threshold(self):
        # 自定义 max_segment_mm=50, 段长 60mm 触发
        wp = np.array([[0, 0, 10], [60, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp, max_segment_mm=50.0)
        assert "LONG_SEGMENT" in _codes(result)

    def test_segment_within_threshold_no_warning(self):
        # 段长恰等于阈值 (不大于), 不触发 LONG_SEGMENT
        wp = np.array([[0, 0, 10], [80, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp, max_segment_mm=80.0)
        assert "LONG_SEGMENT" not in _codes(result)


# ================================================================
# 4. 安全高度
# ================================================================
@pytest.mark.unit
class TestValidateToolpathSafeZ:
    """安全高度检查。"""

    def test_unsafe_z_blocked(self):
        # safe_z == z_max (<=) -> UNSAFE_Z (BLOCKED)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp, safe_z=10.0)
        assert "UNSAFE_Z" in _codes(result)
        assert result.ok is False

    def test_unsafe_z_below_path(self):
        # safe_z < z_max -> UNSAFE_Z (BLOCKED)
        wp = np.array([[0, 0, 15], [1, 0, 15]], dtype=np.float32)
        result = validate_toolpath(wp, safe_z=5.0)
        assert "UNSAFE_Z" in _codes(result)


# ================================================================
# 5. 速度校验
# ================================================================
@pytest.mark.unit
class TestValidateToolpathVelocities:
    """速度数组校验。"""

    def test_velocity_length_mismatch_warning(self):
        # 速度数组长度 != 航点数 -> VELOCITY_LENGTH (WARNING)
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        velocities = np.array([1000.0, 2000.0])  # 长度 2 != 3
        result = validate_toolpath(wp, velocities=velocities)
        assert "VELOCITY_LENGTH" in _codes(result)
        # 速度本身合法, 无 FEED_OUT_OF_RANGE
        assert "FEED_OUT_OF_RANGE" not in _codes(result)

    def test_feed_out_of_range_blocked(self):
        # 速度 100000 > max_feed_rate 60000 -> FEED_OUT_OF_RANGE (BLOCKED)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        velocities = np.array([1000.0, 100000.0])
        result = validate_toolpath(wp, velocities=velocities)
        assert "FEED_OUT_OF_RANGE" in _codes(result)
        assert result.ok is False

    def test_feed_below_min_blocked(self):
        # 速度 0.5 < min_feed_rate 1.0 -> FEED_OUT_OF_RANGE (BLOCKED)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        velocities = np.array([1000.0, 0.5])
        result = validate_toolpath(wp, velocities=velocities, min_feed_rate=1.0)
        assert "FEED_OUT_OF_RANGE" in _codes(result)
        assert result.ok is False

    def test_feed_custom_range(self):
        # 自定义范围 [10, 5000], 速度 6000 超出 -> FEED_OUT_OF_RANGE
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        velocities = np.array([100.0, 6000.0])
        result = validate_toolpath(
            wp, velocities=velocities, min_feed_rate=10.0, max_feed_rate=5000.0
        )
        assert "FEED_OUT_OF_RANGE" in _codes(result)

    def test_non_finite_feed_blocked(self):
        # 速度包含 NaN -> NON_FINITE_FEED (BLOCKED)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        velocities = np.array([1000.0, np.nan])
        result = validate_toolpath(wp, velocities=velocities)
        assert "NON_FINITE_FEED" in _codes(result)
        assert result.ok is False


# ================================================================
# 6. P2-5: 碰撞检查
# ================================================================
@pytest.mark.unit
class TestValidateToolpathCollision:
    """碰撞检查 (COLLISION_RISK)。"""

    def test_collision_risk_warning(self):
        # 基板点与航点重合 (距离 0 < 阈值 0.5) -> COLLISION_RISK (WARNING)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        substrate = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp, substrate_xyz=substrate, collision_threshold_mm=0.5)
        assert "COLLISION_RISK" in _codes(result)
        assert result.ok is True  # warning 不阻断

    def test_no_collision_when_far(self):
        # 基板远离航点 -> 无 COLLISION_RISK
        wp = np.array([[0, 0, 50], [1, 0, 50]], dtype=np.float32)
        substrate = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        result = validate_toolpath(wp, substrate_xyz=substrate, collision_threshold_mm=0.5)
        assert "COLLISION_RISK" not in _codes(result)

    def test_collision_custom_threshold(self):
        # 自定义阈值 2.0mm, 距离 1.0mm 触发
        wp = np.array([[0, 0, 1]], dtype=np.float32)
        substrate = np.array([[0, 0, 0]], dtype=np.float32)
        result = validate_toolpath(wp, substrate_xyz=substrate, collision_threshold_mm=2.0)
        assert "COLLISION_RISK" in _codes(result)

    def test_collision_large_substrate_sampling(self):
        # 基板点 > 1000, 触发采样分支 (>1000 时使用固定种子采样 1000 点)
        # 所有基板点均聚集在原点, 保证采样后仍含近距点
        wp = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        substrate = np.zeros((1500, 3), dtype=np.float32)
        result = validate_toolpath(wp, substrate_xyz=substrate, collision_threshold_mm=0.5)
        assert "COLLISION_RISK" in _codes(result)


# ================================================================
# 7. P2-5: 边界检查
# ================================================================
@pytest.mark.unit
class TestValidateToolpathBounds:
    """构建体积边界检查 (OUT_OF_BOUNDS)。"""

    def test_out_of_bounds_blocked(self):
        # 航点 x=0 < x_min=5 -> OUT_OF_BOUNDS (BLOCKED)
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        build_volume = (5.0, 5.0, 0.0, 20.0, 20.0, 100.0)
        result = validate_toolpath(wp, build_volume=build_volume)
        assert "OUT_OF_BOUNDS" in _codes(result)
        assert result.ok is False

    def test_within_bounds_no_warning(self):
        # 航点全部在构建体积内 -> 无 OUT_OF_BOUNDS
        wp = np.array([[5, 5, 10], [10, 10, 10]], dtype=np.float32)
        build_volume = (0.0, 0.0, 0.0, 20.0, 20.0, 100.0)
        result = validate_toolpath(wp, build_volume=build_volume)
        assert "OUT_OF_BOUNDS" not in _codes(result)


# ================================================================
# 8. P2-5: 高度检查
# ================================================================
@pytest.mark.unit
class TestValidateToolpathHeight:
    """Z 坐标合理性 (NEGATIVE_HEIGHT / HEIGHT_OVER_SAFE_Z)。"""

    def test_negative_height_blocked(self):
        # Z = -1 < 0 -> NEGATIVE_HEIGHT (BLOCKED)
        wp = np.array([[0, 0, -1], [1, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert "NEGATIVE_HEIGHT" in _codes(result)
        assert result.ok is False

    def test_height_over_safe_z_warning(self):
        # Z=15 > safe_z=10 -> HEIGHT_OVER_SAFE_Z (WARNING)
        # 同时 safe_z <= z_max 也会触发 UNSAFE_Z, 这里只断言 HEIGHT_OVER_SAFE_Z 存在
        wp = np.array([[0, 0, 15], [1, 0, 15]], dtype=np.float32)
        result = validate_toolpath(wp, safe_z=10.0)
        assert "HEIGHT_OVER_SAFE_Z" in _codes(result)
        assert "UNSAFE_Z" in _codes(result)

    def test_no_negative_height_when_all_positive(self):
        # Z 全部非负 -> 无 NEGATIVE_HEIGHT
        wp = np.array([[0, 0, 10], [1, 0, 10]], dtype=np.float32)
        result = validate_toolpath(wp)
        assert "NEGATIVE_HEIGHT" not in _codes(result)


# ================================================================
# 9. P2-5: 层检查
# ================================================================
@pytest.mark.unit
class TestValidateToolpathLayers:
    """层数 / 层高 / 层号一致性检查。"""

    def test_layer_gap_warning(self):
        # 层号 0,1,3 跳过 2 -> LAYER_GAP (WARNING)
        wp = np.array(
            [[0, 0, 10], [1, 0, 10], [0, 0, 11], [1, 0, 11], [0, 0, 13], [1, 0, 13]],
            dtype=np.float32,
        )
        layers = np.array([0, 0, 1, 1, 3, 3])
        result = validate_toolpath(wp, layer_indices=layers)
        assert "LAYER_GAP" in _codes(result)

    def test_layer_count_mismatch_warning(self):
        # 检测到 2 层, 期望 3 层 -> LAYER_COUNT_MISMATCH (WARNING)
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 11], [1, 0, 11]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = validate_toolpath(wp, layer_indices=layers, expected_n_layers=3)
        assert "LAYER_COUNT_MISMATCH" in _codes(result)

    def test_layer_height_inconsistent_warning(self):
        # 层 0 z=10, 层 1 z=12, 期望层高 0.5 -> 偏差 > 0.5 -> LAYER_HEIGHT_INCONSISTENT
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 12], [1, 0, 12]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = validate_toolpath(
            wp, layer_indices=layers, expected_layer_height=0.5, max_layer_height_deviation=0.5
        )
        assert "LAYER_HEIGHT_INCONSISTENT" in _codes(result)

    def test_layer_height_consistent_no_warning(self):
        # 层 0 z=10, 层 1 z=10.5, 期望层高 0.5 -> 无 LAYER_HEIGHT_INCONSISTENT
        wp = np.array([[0, 0, 10], [1, 0, 10], [0, 0, 10.5], [1, 0, 10.5]], dtype=np.float32)
        layers = np.array([0, 0, 1, 1])
        result = validate_toolpath(
            wp, layer_indices=layers, expected_layer_height=0.5
        )
        assert "LAYER_HEIGHT_INCONSISTENT" not in _codes(result)

    def test_layer_indices_length_mismatch_skipped(self):
        # layer_indices 长度 != 航点数 -> 跳过所有层检查, 无 warning
        wp = np.array([[0, 0, 10], [1, 0, 10], [2, 0, 10]], dtype=np.float32)
        layers = np.array([0, 1])  # 长度 2 != 3
        result = validate_toolpath(wp, layer_indices=layers, expected_n_layers=5)
        assert "LAYER_GAP" not in _codes(result)
        assert "LAYER_COUNT_MISMATCH" not in _codes(result)


# ================================================================
# 10. ExportValidationResult 属性与 ExportIssue
# ================================================================
@pytest.mark.unit
class TestExportValidationResultAttributes:
    """结果属性 / 数据类。"""

    def test_export_issue_level_enum(self):
        # ExportIssueLevel 枚举值
        assert ExportIssueLevel.INFO.value == "info"
        assert ExportIssueLevel.WARNING.value == "warning"
        assert ExportIssueLevel.BLOCKED.value == "blocked"

    def test_export_issue_dataclass_fields(self):
        # ExportIssue 字段: level / code / message
        issue = ExportIssue(ExportIssueLevel.WARNING, "X", "msg")
        assert issue.level == ExportIssueLevel.WARNING
        assert issue.code == "X"
        assert issue.message == "msg"

    def test_blocking_warning_info_messages_properties(self):
        # 混合三类 issue, 分别归类到对应属性
        issues = [
            ExportIssue(ExportIssueLevel.BLOCKED, "B1", "阻断消息"),
            ExportIssue(ExportIssueLevel.WARNING, "W1", "警告消息"),
            ExportIssue(ExportIssueLevel.INFO, "I1", "信息消息"),
        ]
        result = ExportValidationResult(ok=False, issues=issues)
        assert result.blocking_messages == ["阻断消息"]
        assert result.warning_messages == ["警告消息"]
        assert result.info_messages == ["信息消息"]
        assert result.ok is False

    def test_ok_true_when_no_blocked(self):
        # 仅 WARNING/INFO, ok 为 True
        issues = [
            ExportIssue(ExportIssueLevel.WARNING, "W", "w"),
            ExportIssue(ExportIssueLevel.INFO, "I", "i"),
        ]
        result = ExportValidationResult(ok=True, issues=issues)
        assert result.ok is True
        assert result.blocking_messages == []

    def test_ok_false_from_validate_when_blocked(self):
        # validate_toolpath 产生 BLOCKED 时 ok=False
        wp = np.array([1, 2, 3], dtype=np.float32)  # INVALID_SHAPE
        result = validate_toolpath(wp)
        assert result.ok is False
        assert len(result.blocking_messages) >= 1

    def test_empty_result_properties(self):
        # 空结果, 所有消息列表为空
        result = ExportValidationResult(ok=True, issues=[])
        assert result.blocking_messages == []
        assert result.warning_messages == []
        assert result.info_messages == []


# ================================================================
# 11. generate_report Markdown 报告
# ================================================================
@pytest.mark.unit
class TestGenerateReport:
    """ExportValidationResult.generate_report() 测试。"""

    def test_generate_report_success(self, tmp_path):
        # 生成报告成功, 文件存在且包含 Markdown 结构
        issues = [
            ExportIssue(ExportIssueLevel.BLOCKED, "B1", "阻断问题 A"),
            ExportIssue(ExportIssueLevel.WARNING, "W1", "警告问题 A"),
            ExportIssue(ExportIssueLevel.INFO, "I1", "信息提示 A"),
        ]
        result = ExportValidationResult(ok=False, issues=issues)
        report_path = tmp_path / "report.md"
        ret = result.generate_report(str(report_path))
        assert ret is True
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        # Markdown 标题与章节
        assert "# 路径校验报告" in content
        assert "## 总体结果" in content
        assert "未通过" in content
        assert "## 阻断问题 (BLOCKED)" in content
        assert "## 警告问题 (WARNING)" in content
        assert "## 信息提示 (INFO)" in content
        # 各消息内容
        assert "阻断问题 A" in content
        assert "警告问题 A" in content
        assert "信息提示 A" in content
        # 末尾签名
        assert "冷喷涂缺陷修复软件自动生成" in content

    def test_generate_report_ok_result(self, tmp_path):
        # 校验通过的报告 (无阻断/警告/信息)
        result = ExportValidationResult(ok=True, issues=[])
        report_path = tmp_path / "ok_report.md"
        ret = result.generate_report(str(report_path))
        assert ret is True
        content = report_path.read_text(encoding="utf-8")
        assert "通过" in content
        # 空结果时不输出各问题章节 (注意: 总体结果汇总行仍含 "阻断问题: 0 项")
        assert "## 阻断问题 (BLOCKED)" not in content
        assert "## 警告问题 (WARNING)" not in content
        assert "## 信息提示 (INFO)" not in content
        assert "0 项" in content

    def test_generate_report_only_warnings(self, tmp_path):
        # 仅含警告的报告 (验证章节按需输出)
        issues = [ExportIssue(ExportIssueLevel.WARNING, "W", "仅警告")]
        result = ExportValidationResult(ok=True, issues=issues)
        report_path = tmp_path / "warn_only.md"
        ret = result.generate_report(str(report_path))
        assert ret is True
        content = report_path.read_text(encoding="utf-8")
        assert "## 警告问题 (WARNING)" in content
        assert "## 阻断问题 (BLOCKED)" not in content
        assert "## 信息提示 (INFO)" not in content

    def test_generate_report_invalid_path_returns_false(self, tmp_path):
        # 输出路径所在父目录是一个已存在的文件 (无法写入) -> 返回 False
        blocker_file = tmp_path / "blocker"
        blocker_file.write_text("not a directory", encoding="utf-8")
        invalid_path = blocker_file / "report.md"  # 父路径是文件, open 失败
        result = ExportValidationResult(ok=True, issues=[])
        ret = result.generate_report(str(invalid_path))
        assert ret is False
