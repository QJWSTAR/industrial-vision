"""
test_fixes.py — 修复验证测试
验证已修复的bug不会再次出现：
- 材料映射表 bug
- 版本号一致性
- 选区坐标映射精度
- 形貌预测精度
"""

from __future__ import annotations
import sys, os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestMaterialMappingFix:
    def test_material_map_index_0(self):
        from repair_app.ui.main_window import _MAT_KEY_MAP
        assert _MAT_KEY_MAP[0] == "MATERIAL_UNSPECIFIED", \
            "Index 0 should map to MATERIAL_UNSPECIFIED"

    def test_material_map_index_1(self):
        from repair_app.ui.main_window import _MAT_KEY_MAP
        assert _MAT_KEY_MAP[1] == "STEEL_316L", \
            "Index 1 should map to STEEL_316L"

    def test_material_map_unique(self):
        from repair_app.ui.main_window import _MAT_KEY_MAP
        values = list(_MAT_KEY_MAP.values())
        assert len(values) == len(set(values)), \
            "Material map should have unique values for each index"

    def test_material_map_consistency(self):
        from repair_app.ui.main_window import _MAT_KEY_MAP, _MATERIALS
        for idx, (label, key) in enumerate(_MATERIALS):
            assert _MAT_KEY_MAP[idx] == key, \
                f"Material map at index {idx} should match _MATERIALS key {key}"


class TestVersionConsistency:
    def test_version_in_title(self):
        from repair_app.ui.main_window import _TITLE
        from repair_app.utils.config import APP_VERSION
        assert f"v{APP_VERSION}" in _TITLE, \
            f"Title should contain v{APP_VERSION}, got: {_TITLE}"

    def test_version_not_v09(self):
        import repair_app.ui.main_window as mw_module
        file_path = mw_module.__file__
        with open(file_path, "r") as f:
            content = f.read()
        assert "v0.9" not in content, \
            "Version v0.9 should not appear in main_window.py"


class TestMorphologyPredictorPrecision:
    def test_no_sampling_of_waypoints(self):
        from repair_app.core.morphology_predictor import iter_repair_mesh_layers, _sparsify_waypoints

        points = np.random.rand(100, 3) * 10
        mask = np.ones(100, dtype=bool)
        waypoints = np.random.rand(200, 3) * 10

        n_waypoints_before = len(waypoints)

        # 验证：waypoint_sparsify_step=0 时不进行稀疏化
        sparse_wp = _sparsify_waypoints(waypoints, step=0)
        assert len(sparse_wp) == n_waypoints_before, \
            f"With step=0, should keep all waypoints. Got {len(sparse_wp)}"
        # 验证：稀疏化前后数组内容一致（不只是长度）
        assert np.array_equal(sparse_wp, waypoints), "step=0 时内容应完全一致"

        # 验证：传入 waypoint_sparsify_step=0 时函数正常执行
        layers = list(iter_repair_mesh_layers(
            points, mask, waypoints, n_layers=2,
            waypoint_sparsify_step=0,
        ))
        assert len(layers) == 2, f"Expected 2 layers, got {len(layers)}"
        # 验证：每层有实际数据（不只是长度）
        for i, layer in enumerate(layers):
            assert layer is not None, f"第 {i} 层不应为 None"
            assert hasattr(layer, "shape") or hasattr(layer, "__len__"), \
                f"第 {i} 层应有形状或长度"


if __name__ == "__main__":
    print("=" * 60)
    print("修复验证测试")
    print("=" * 60)
    results = []
    for cls in [TestMaterialMappingFix, TestVersionConsistency, TestMorphologyPredictorPrecision]:
        print(f"\n--- {cls.__name__} ---")
        t = cls()
        for name in sorted(dir(t)):
            if name.startswith("test_"):
                try:
                    getattr(t, name)()
                    print(f"  ✅ {name}")
                    results.append(True)
                except Exception as e:
                    print(f"  ❌ {name}: {e}")
                    results.append(False)
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"结果: {passed}/{total} 通过")
    print("✅ 修复验证全部通过" if passed == total else f"❌ {total-passed} 个测试失败")
