"""Stress test — validates system stability under extreme conditions.

Usage:
    python3 repair_app/tests/test_stress.py
"""

from __future__ import annotations
import time
import sys
import os
import gc
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestStressPathPlanning(unittest.TestCase):
    """Stress test path planning with extreme parameters."""

    def test_large_point_cloud(self):
        """100K points should complete without error."""
        from repair_app.core.path_planner import iter_path_from_cloud
        from repair_app.domain.models import ProcessParams

        n = 100000
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-100, 100, (n, 3)).astype(np.float32)
        mask = np.zeros(n, dtype=bool)
        mask[n // 3 : 2 * n // 3] = True

        params = ProcessParams(num_layers=5)
        t0 = time.perf_counter()
        waypoints = None
        for wp in iter_path_from_cloud(
            xyz=xyz, defect_mask=mask,
            layer_height=params.layer_height_mm,
            scanning_angle=params.scanning_angle_deg,
            scanning_step=params.scanning_step_mm,
            buffer_mm=params.buffer_additive_mm,
            n_layers=params.num_layers,
        ):
            waypoints = wp
        elapsed = time.perf_counter() - t0
        self.assertIsNotNone(waypoints)
        self.assertGreater(len(waypoints), 0)
        self.assertLess(elapsed, 5.0, f"Path planning too slow: {elapsed:.2f}s")

    def test_many_layers(self):
        """50 layers should complete without error."""
        from repair_app.core.path_planner import iter_path_from_cloud
        from repair_app.domain.models import ProcessParams

        n = 1000
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-10, 10, (n, 3)).astype(np.float32)
        mask = np.ones(n, dtype=bool)

        params = ProcessParams(num_layers=50)
        waypoints = None
        for wp in iter_path_from_cloud(
            xyz=xyz, defect_mask=mask,
            layer_height=params.layer_height_mm,
            scanning_angle=params.scanning_angle_deg,
            scanning_step=params.scanning_step_mm,
            buffer_mm=params.buffer_additive_mm,
            n_layers=params.num_layers,
        ):
            waypoints = wp
        self.assertIsNotNone(waypoints)
        self.assertGreater(len(waypoints), 0)

    def test_empty_defect(self):
        """Empty defect mask should return immediately."""
        from repair_app.core.path_planner import iter_path_from_cloud
        from repair_app.domain.models import ProcessParams

        xyz = np.random.rand(100, 3).astype(np.float32)
        mask = np.zeros(100, dtype=bool)

        params = ProcessParams()
        results = list(iter_path_from_cloud(
            xyz=xyz, defect_mask=mask,
            n_layers=params.num_layers,
        ))
        self.assertEqual(len(results), 0)


class TestStressMorphology(unittest.TestCase):
    """Stress test morphology prediction."""

    def test_large_waypoints(self):
        """50K points with 40K waypoints should complete."""
        from repair_app.core.morphology_predictor import iter_repair_mesh_layers

        n = 50000
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-50, 50, (n, 3)).astype(np.float32)
        mask = np.zeros(n, dtype=bool)
        mask[n // 4 : 3 * n // 4] = True
        waypoints = rng.uniform(-50, 50, (1000, 3)).astype(np.float32)

        t0 = time.perf_counter()
        layers = list(iter_repair_mesh_layers(
            base_pts=xyz, defect_mask=mask, waypoints=waypoints,
            n_layers=3,
        ))
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(layers), 3)
        self.assertLess(elapsed, 10.0, f"Morphology too slow: {elapsed:.2f}s")

    def test_zero_waypoints(self):
        """Zero waypoints should return immediately."""
        from repair_app.core.morphology_predictor import iter_repair_mesh_layers

        xyz = np.random.rand(100, 3).astype(np.float32)
        mask = np.ones(100, dtype=bool)
        waypoints = np.zeros((0, 3), dtype=np.float32)

        results = list(iter_repair_mesh_layers(
            base_pts=xyz, defect_mask=mask, waypoints=waypoints,
        ))
        self.assertEqual(len(results), 0)


class TestStressMemory(unittest.TestCase):
    """Stress test memory usage."""

    def test_rapid_allocation(self):
        """Rapid allocation/deallocation of large arrays."""
        from repair_app.core.path_planner import iter_path_from_cloud
        from repair_app.domain.models import ProcessParams

        total_waypoints = 0
        iterations = 10
        for _ in range(iterations):
            n = 10000
            rng = np.random.default_rng()
            xyz = rng.uniform(-50, 50, (n, 3)).astype(np.float32)
            mask = np.zeros(n, dtype=bool)
            mask[n // 3 : 2 * n // 3] = True

            params = ProcessParams(num_layers=3)
            result = list(iter_path_from_cloud(
                xyz=xyz, defect_mask=mask, n_layers=params.num_layers,
            ))
            # 验证：每次迭代都有产出
            assert len(result) > 0, "每次迭代应产生至少一层航点"
            total_waypoints += sum(len(wp) for wp in result)
            gc.collect()
        # 验证：10 次迭代累计产出非零
        assert total_waypoints > 0, f"10 次迭代应累计产出航点，实际 {total_waypoints}"

    def test_lod_memory(self):
        """LOD should not blow up memory."""
        from repair_app.utils.lod import LODManager

        n = 100000
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-100, 100, (n, 3)).astype(np.float32)

        manager = LODManager(xyz, max_levels=5)
        self.assertGreater(manager.level_count, 1)
        for level in range(manager.level_count):
            lvl_xyz, _, _ = manager.get_level(level)
            self.assertGreater(len(lvl_xyz), 0)
            self.assertLessEqual(len(lvl_xyz), n)


if __name__ == "__main__":
    unittest.main()