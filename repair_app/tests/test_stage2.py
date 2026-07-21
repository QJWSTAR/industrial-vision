"""
test_stage2.py — Stage 2 集成自检 v2.1
验证：MaterialDatabase / FeasibilityChecker / DefectSelector / 主界面集成

运行：
    python3 -m pytest test_stage2.py -v
"""

from __future__ import annotations
import sys, os, json
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from repair_app.core.material_database import MaterialDatabase, MaterialParams, get_material_db
from repair_app.core.feasibility_checker import (
    FeasibilityChecker, FeasibilityResult, FeasibilityWarning, WarningLevel,
)
from repair_app.core.defect_sample import generate_defect_sample


# ================================================================
# 1. MaterialDatabase 测试
# ================================================================
class TestMaterialDatabase:
    def test_load_all_materials(self):
        db = MaterialDatabase()
        keys = db.material_keys
        assert len(keys) >= 5
        for k in ["COPPER", "ALUMINUM_6061", "STEEL_316L", "TITANIUM_TI64", "INCONEL_718"]:
            assert k in keys

    def test_default_material(self):
        db = MaterialDatabase()
        assert db.default_key == "STEEL_316L"
        mat = db.get_default()
        assert mat.name == "316L 不锈钢"
        assert abs(mat.density_kgm3 - 7980) < 10

    def test_get_known_material(self):
        db = MaterialDatabase()
        mat = db.get("COPPER")
        assert mat.name == "纯铜 (Cu)"
        assert abs(mat.v_cr_base_ms - 340) < 10

    def test_get_unknown_fallback(self):
        db = MaterialDatabase()
        mat = db.get("NONEXISTENT")
        assert mat.name == "316L 不锈钢"

    def test_v_cr_angle_normal_incidence(self):
        db = MaterialDatabase()
        mat = db.get("STEEL_316L")
        v90 = mat.v_cr_at_angle(90)
        assert abs(v90 - mat.v_cr_base_ms) < 5

    def test_v_cr_angle_glancing(self):
        db = MaterialDatabase()
        mat = db.get("STEEL_316L")
        v45 = mat.v_cr_at_angle(45)
        v90 = mat.v_cr_at_angle(90)
        assert v45 > v90

    def test_thresholds_present(self):
        db = MaterialDatabase()
        t = db.thresholds
        assert "min_defect_size_to_spot_ratio" in t
        assert "min_spray_angle_deg" in t

    def test_all_materials_valid_params(self):
        db = MaterialDatabase()
        for key in db.material_keys:
            mat = db.get(key)
            assert mat.density_kgm3 > 0
            assert mat.v_cr_base_ms > 0
            assert mat.min_spray_spot_width_mm > 0
            assert mat.max_defect_depth_mm > 0

    def test_singleton(self):
        import repair_app.core.material_database as md
        md._G_DB = None
        db1 = get_material_db()
        db2 = get_material_db()
        assert db1 is db2


# ================================================================
# 2. FeasibilityChecker 测试
# ================================================================
class TestFeasibilityChecker:
    def setup_method(self):
        self.fc = FeasibilityChecker()

    def test_normal_case_passes(self):
        r = self.fc.check(
            defect_volume_mm3=50, defect_depth_mm=2.0,
            defect_min_width_mm=5, defect_max_width_mm=8,
            sidewall_angle_deg=30, nozzle_diameter_mm=6,
            spray_angle_deg=90, particle_velocity_ms=700,
        )
        assert r.feasible
        assert r.overall_level == WarningLevel.OK
        assert r.score >= 0.9

    def test_empty_defect_blocked(self):
        r = self.fc.check(0, 0, 0, 0, 0, 6, 90, 700)
        assert not r.feasible
        assert r.overall_level == WarningLevel.BLOCKED

    def test_undersized_defect_warns(self):
        r = self.fc.check(10, 1, 0.5, 5, 30, 10, 90, 700)
        assert r.feasible
        assert any(w.code == "UNDERSIZED_DEFECT" for w in r.warnings)

    def test_excessive_depth_warns(self):
        r = self.fc.check(100, 8, 10, 10, 30, 6, 90, 700)
        assert any(w.code == "EXCESSIVE_DEPTH" for w in r.warnings)

    def test_steep_sidewall_warns(self):
        r = self.fc.check(50, 2, 5, 5, 60, 6, 90, 700)
        assert any(w.code == "STEEP_SIDEWALL" for w in r.warnings)

    def test_insufficient_velocity_blocked(self):
        r = self.fc.check(50, 2, 5, 5, 30, 6, 90, 100)
        assert any(w.code == "INSUFFICIENT_VELOCITY" for w in r.warnings)
        assert not r.feasible

    def test_check_from_cloud_normal(self):
        pts, normals, mask, info = generate_defect_sample(
            defect_types=["pit"], seed=1, n_points=3000
        )
        cloud = np.hstack([pts, normals])
        z_vals = pts[:, 2]
        sel = cloud[z_vals > np.median(z_vals)]
        r = self.fc.check_from_cloud(
            sel, nozzle_diameter_mm=6,
            spray_angle_deg=90, particle_velocity_ms=700,
        )
        assert r.feasible
        assert r.score > 0

    def test_check_from_cloud_too_few_points(self):
        r = self.fc.check_from_cloud(np.array([[0, 0, 0]]), 6, 90, 700)
        assert not r.feasible
        assert any(w.code == "TOO_FEW_POINTS" for w in r.warnings)

    def test_warning_has_suggestion(self):
        r = self.fc.check(50, 2, 1, 5, 60, 10, 90, 700)
        for w in r.warnings:
            assert w.suggestion

    def test_score_bounded_0_1(self):
        r = self.fc.check(50, 2, 5, 5, 30, 6, 90, 200)
        assert 0.0 <= r.score <= 1.0

    def test_copper_low_vcr(self):
        db = MaterialDatabase()
        mat = db.get("COPPER")
        fc = FeasibilityChecker(mat)
        r = fc.check(50, 2, 5, 5, 30, 6, 90, 500)
        assert r.feasible
        assert r.overall_level == WarningLevel.OK


# ================================================================
# 3. DefectSelector 选区操作测试（通过真实组件验证）
# ================================================================
class TestDefectSelectorLogic:
    """通过真实 DefectSelector 组件验证选区操作。

    不再测试 numpy 基础操作，而是调用 DefectSelector 的公开 API：
    set_selection_mask / clear_selection / invert_selection / get_selection_mask
    """

    def _make_selector_with_points(self, n: int = 100):
        """构造已加载点云的 DefectSelector（不渲染）。"""
        from repair_app.ui.defect_selector import DefectSelector
        # 跳过 QWidget 初始化（避免依赖 QApplication）
        selector = DefectSelector()
        rng = np.random.default_rng(42)
        pts = rng.uniform(-5, 5, (n, 3)).astype(np.float32)
        selector.set_points(pts)
        return selector

    def test_set_selection_mask(self, qapp):
        """set_selection_mask 应正确设置掩码。"""
        selector = self._make_selector_with_points(100)
        try:
            mask = np.zeros(100, dtype=bool)
            mask[:30] = True
            selector.set_selection_mask(mask)
            result = selector.get_selection_mask()
            assert np.sum(result) == 30
            # 验证返回的是副本（修改不影响内部状态）
            result[:] = False
            assert np.sum(selector.get_selection_mask()) == 30
        finally:
            selector.deleteLater()

    def test_clear_selection(self, qapp):
        """clear_selection 应清空所有选区。"""
        selector = self._make_selector_with_points(100)
        try:
            mask = np.zeros(100, dtype=bool)
            mask[:50] = True
            selector.set_selection_mask(mask)
            assert np.sum(selector.get_selection_mask()) == 50
            selector.clear_selection()
            assert not np.any(selector.get_selection_mask())
        finally:
            selector.deleteLater()

    def test_invert_selection(self, qapp):
        """invert_selection 应反转选区。"""
        selector = self._make_selector_with_points(100)
        try:
            mask = np.zeros(100, dtype=bool)
            mask[:25] = True
            selector.set_selection_mask(mask)
            selector.invert_selection()
            result = selector.get_selection_mask()
            assert np.sum(result) == 75  # 100 - 25
        finally:
            selector.deleteLater()

    def test_get_selected_points(self, qapp):
        """get_selected_points 应返回选中点坐标。"""
        selector = self._make_selector_with_points(100)
        try:
            mask = np.zeros(100, dtype=bool)
            mask[:10] = True
            selector.set_selection_mask(mask)
            selected = selector.get_selected_points()
            assert selected.shape == (10, 3)
            assert np.array_equal(selected, selector._points[:10])
        finally:
            selector.deleteLater()


# ================================================================
# 4. 端到端模块数据流
# ================================================================
class TestEndToEndFlow:
    def test_load_material_then_check_feasibility(self):
        import repair_app.core.material_database as md
        md._G_DB = None
        db = get_material_db()
        mat = db.get("TITANIUM_TI64")
        fc = FeasibilityChecker(mat)

        pts, normals, mask, info = generate_defect_sample(
            defect_types=["pit"], seed=42, n_points=3000
        )
        cloud = np.hstack([pts, normals])
        z_vals = pts[:, 2]
        sel = cloud[z_vals > np.median(z_vals) + 0.3]

        r = fc.check_from_cloud(
            sel, nozzle_diameter_mm=6,
            spray_angle_deg=90, particle_velocity_ms=750,
        )
        assert r.feasible
        assert r.score > 0.5
        assert len(r.summary) > 0
