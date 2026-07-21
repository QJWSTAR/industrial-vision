"""test_performance.py — 性能测试

验证核心算法/导出/序列化在大数据量下的响应时间。
使用手动 time.perf_counter 计时（不依赖 pytest-benchmark）。

覆盖：
- path_planner 1000 点 <1s
- morphology_predictor 500 点 3 层 <2s
- gcode_exporter 1000 航点 <0.1s
- robot_exporter 1000 航点 <0.1s
- STL 解析
- 序列化 1000 点 RepairRequest <0.05s
- schema_loader 首次加载 <0.5s

运行：pytest -m performance -v
"""
from __future__ import annotations

import os
import sys
import time

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest


# ================================================================
# 1. path_planner 1000 点 <1s
# ================================================================
@pytest.mark.performance
class TestPathPlannerPerformance:
    """路径规划性能测试。"""

    def test_path_planner_1000_points(self, sample_points):
        """1000 点路径规划应在 1s 内完成。"""
        from repair_app.core.path_planner import plan_path_from_cloud
        # 构造 1000 点点云
        rng = np.random.default_rng(42)
        xy = rng.uniform(-10, 10, (1000, 2))
        z = rng.uniform(0, 1, 1000)
        xyz = np.column_stack([xy, z]).astype(np.float32)
        mask = np.zeros(1000, dtype=bool)
        mask[300:700] = True  # 中间 40% 为缺陷

        start = time.perf_counter()
        waypoints = plan_path_from_cloud(xyz, mask, n_layers=2)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"1000 点路径规划耗时 {elapsed:.3f}s，应 <1s"
        assert isinstance(waypoints, np.ndarray), "应返回 np.ndarray"
        assert waypoints.ndim == 2, "航点应为 2D 数组"

    def test_iter_path_from_cloud_yields_progress(self, sample_points):
        """逐层路径规划应能迭代返回部分结果。"""
        from repair_app.core.path_planner import iter_path_from_cloud
        xyz = sample_points
        mask = np.zeros(len(xyz), dtype=bool)
        mask[len(xyz) // 3: 2 * len(xyz) // 3] = True

        start = time.perf_counter()
        layers = list(iter_path_from_cloud(xyz, mask, n_layers=3))
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"逐层路径规划耗时 {elapsed:.3f}s"
        assert len(layers) == 3, f"应有 3 层结果，实际 {len(layers)}"


# ================================================================
# 2. morphology_predictor 500 点 3 层 <2s
# ================================================================
@pytest.mark.performance
class TestMorphologyPredictorPerformance:
    """形貌预测性能测试。"""

    def test_morphology_500_points_3_layers(self):
        """500 点 3 层形貌预测应在 2s 内完成。"""
        from repair_app.core.morphology_predictor import iter_repair_mesh_layers
        rng = np.random.default_rng(42)
        base_pts = rng.uniform(-5, 5, (500, 3)).astype(np.float32)
        defect_mask = np.zeros(500, dtype=bool)
        defect_mask[150:350] = True
        waypoints = rng.uniform(-3, 3, (50, 3)).astype(np.float32)

        start = time.perf_counter()
        layers = list(iter_repair_mesh_layers(
            base_pts=base_pts,
            defect_mask=defect_mask,
            waypoints=waypoints,
            n_layers=3,
        ))
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"500 点 3 层形貌预测耗时 {elapsed:.3f}s，应 <2s"
        assert len(layers) == 3, f"应有 3 层结果，实际 {len(layers)}"
        # 验证每层有数据
        for i, layer in enumerate(layers):
            assert isinstance(layer, np.ndarray), f"第 {i} 层应为 np.ndarray"
            assert len(layer) == 500, f"第 {i} 层点数应不变"


# ================================================================
# 3. gcode_exporter 1000 航点 <0.1s
# ================================================================
@pytest.mark.performance
class TestGCodeExporterPerformance:
    """G-code 导出性能测试。"""

    def test_gcode_export_1000_waypoints(self):
        """1000 航点 G-code 导出应在 0.1s 内完成。"""
        from repair_app.export.gcode_exporter import GCodeExporter
        rng = np.random.default_rng(42)
        # Z 坐标较小，避免 safe_z 校验失败
        waypoints = np.column_stack([
            rng.uniform(0, 50, 1000),
            rng.uniform(0, 50, 1000),
            np.full(1000, 1.0),
        ]).astype(np.float32)

        exporter = GCodeExporter(safe_z=10.0)
        start = time.perf_counter()
        gcode = exporter.export(waypoints, validate=False)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"1000 航点 G-code 导出耗时 {elapsed:.4f}s，应 <0.1s"
        assert isinstance(gcode, str), "应返回字符串"
        assert len(gcode) > 0, "输出不应为空"
        assert "G1" in gcode, "应包含 G1 指令"


# ================================================================
# 4. robot_exporter 1000 航点 <0.1s
# ================================================================
@pytest.mark.performance
class TestRobotExporterPerformance:
    """机器人轨迹导出性能测试。"""

    def test_kuka_export_1000_waypoints(self):
        """1000 航点 KUKA 导出应在 0.1s 内完成。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        rng = np.random.default_rng(42)
        waypoints = rng.uniform(0, 100, (1000, 3)).astype(np.float32)

        exporter = RobotExporter(robot_type=RobotType.KUKA)
        start = time.perf_counter()
        code = exporter.export(waypoints)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"1000 航点 KUKA 导出耗时 {elapsed:.4f}s，应 <0.1s"
        assert isinstance(code, str), "应返回字符串"
        assert "DEF" in code, "KUKA 代码应包含 DEF"

    def test_abb_export_1000_waypoints(self):
        """1000 航点 ABB 导出应在 0.1s 内完成。"""
        from repair_app.export.robot_exporter import RobotExporter, RobotType
        rng = np.random.default_rng(42)
        waypoints = rng.uniform(0, 100, (1000, 3)).astype(np.float32)

        exporter = RobotExporter(robot_type=RobotType.ABB)
        start = time.perf_counter()
        code = exporter.export(waypoints)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"1000 航点 ABB 导出耗时 {elapsed:.4f}s，应 <0.1s"
        assert isinstance(code, str), "应返回字符串"
        assert "MoveL" in code, "ABB 代码应包含 MoveL"


# ================================================================
# 5. STL 解析
# ================================================================
@pytest.mark.performance
class TestStlParsingPerformance:
    """STL 文件解析性能测试。"""

    def test_stl_parsing(self):
        """STL 文件解析应在 1s 内完成。"""
        from repair_app.core.stl_reader import read_stl_file
        stl_path = os.path.join(_PROJECT_ROOT, "path_planning", "substrate.stl")
        if not os.path.exists(stl_path):
            pytest.skip(f"STL 文件不存在: {stl_path}")

        start = time.perf_counter()
        triangles = read_stl_file(stl_path)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"STL 解析耗时 {elapsed:.3f}s，应 <1s"
        assert isinstance(triangles, np.ndarray), "应返回 np.ndarray"
        assert triangles.ndim == 2, "应为 2D 数组"
        assert triangles.shape[1] == 12, f"列数应为 12，实际 {triangles.shape[1]}"
        assert len(triangles) > 0, "三角形数量不应为空"


# ================================================================
# 6. 序列化 1000 点 RepairRequest <0.05s
# ================================================================
@pytest.mark.performance
class TestSerializationPerformance:
    """Protobuf 序列化性能测试。"""

    def test_serialize_1000_points(self):
        """1000 点 RepairRequest 序列化应在 0.05s 内完成。"""
        from repair_app.communication.repair_serialization import build_repair_request
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (1000, 3)).astype(np.float32)
        normals = np.zeros((1000, 3), dtype=np.float32)
        normals[:, 2] = 1.0

        start = time.perf_counter()
        req = build_repair_request(xyz, normals, "test-scan")
        data = req.SerializeToString()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, f"1000 点序列化耗时 {elapsed:.4f}s，应 <0.05s"
        assert isinstance(data, bytes), "序列化结果应为 bytes"
        assert len(data) > 0, "序列化数据不应为空"
        # 验证数据量合理（1000 点 × 3 坐标 × 4 字节 ≈ 12KB 最小）
        assert len(data) > 1000, f"序列化数据过小: {len(data)} bytes"


# ================================================================
# 7. schema_loader 首次加载 <0.5s
# ================================================================
@pytest.mark.performance
class TestSchemaLoaderPerformance:
    """schema_loader 首次加载性能测试。"""

    def test_first_load_under_500ms(self):
        """schema 首次加载应在 0.5s 内完成。"""
        import repair_app.config.schema_loader as sl
        # 清除缓存以模拟首次加载
        sl._G_SCHEMA = None

        start = time.perf_counter()
        schema = sl.get_schema()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"schema 首次加载耗时 {elapsed:.3f}s，应 <0.5s"
        assert isinstance(schema, dict), "schema 应为 dict"
        assert "process_parameters" in schema, "应包含 process_parameters"
        assert "export_parameters" in schema, "应包含 export_parameters"
        assert len(schema["process_parameters"]) > 0, "工艺参数不应为空"
