"""Memory profiling and benchmark suite.

Usage:
    python3 repair_app/tools/benchmark.py
"""

from __future__ import annotations
import time
import sys
import os
import tracemalloc
import gc
from typing import Callable

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _generate_test_data(n: int) -> dict:
    rng = np.random.default_rng(42)
    xyz = rng.uniform(-50, 50, (n, 3)).astype(np.float32)
    normals = rng.normal(0, 1, (n, 3)).astype(np.float32)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    mask = np.zeros(n, dtype=bool)
    mask[n // 3 : 2 * n // 3] = True
    return {"xyz": xyz, "normals": normals, "mask": mask}


def measure_memory(func: Callable, *args, **kwargs) -> dict:
    """Measure peak memory usage of a function."""
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "time_s": elapsed,
        "current_mb": current / 1024 / 1024,
        "peak_mb": peak / 1024 / 1024,
    }


def benchmark_path_planning():
    """Benchmark path planning at different scales."""
    from repair_app.core.path_planner import iter_path_from_cloud
    from repair_app.domain.models import ProcessParams

    print("\n=== Path Planning Benchmark ===")
    print(f"{'Size':>10} | {'Time(s)':>8} | {'Peak(MB)':>8} | {'Waypoints':>10}")
    print("-" * 50)

    params = ProcessParams(num_layers=5)
    for n in [1000, 5000, 10000, 50000, 100000]:
        data = _generate_test_data(n)
        waypoints = None

        def _run():
            nonlocal waypoints
            for wp in iter_path_from_cloud(
                xyz=data["xyz"], defect_mask=data["mask"],
                layer_height=params.layer_height_mm,
                scanning_angle=params.scanning_angle_deg,
                scanning_step=params.scanning_step_mm,
                buffer_mm=params.buffer_additive_mm,
                n_layers=params.num_layers,
            ):
                waypoints = wp

        stats = measure_memory(_run)
        n_wp = len(waypoints) if waypoints is not None else 0
        print(f"{n:>10,} | {stats['time_s']:>8.3f} | {stats['peak_mb']:>8.1f} | {n_wp:>10,}")


def benchmark_morphology():
    """Benchmark morphology prediction at different scales."""
    from repair_app.core.morphology_predictor import iter_repair_mesh_layers
    from repair_app.core.path_planner import iter_path_from_cloud
    from repair_app.domain.models import ProcessParams

    print("\n=== Morphology Benchmark ===")
    print(f"{'Size':>10} | {'Time(s)':>8} | {'Peak(MB)':>8} | {'Layers':>8}")
    print("-" * 50)

    params = ProcessParams(num_layers=3)
    for n in [1000, 5000, 10000, 50000]:
        data = _generate_test_data(n)

        waypoints = None
        for wp in iter_path_from_cloud(
            xyz=data["xyz"], defect_mask=data["mask"],
            layer_height=params.layer_height_mm,
            scanning_angle=params.scanning_angle_deg,
            scanning_step=params.scanning_step_mm,
            buffer_mm=params.buffer_additive_mm,
            n_layers=3,
        ):
            waypoints = wp

        if waypoints is None:
            continue

        def _run():
            list(iter_repair_mesh_layers(
                base_pts=data["xyz"], defect_mask=data["mask"],
                waypoints=waypoints,
                particle_velocity_ms=500, critical_velocity_ms=400,
                nozzle_diameter_mm=6, n_layers=3,
            ))

        stats = measure_memory(_run)
        print(f"{n:>10,} | {stats['time_s']:>8.3f} | {stats['peak_mb']:>8.1f} | {3:>8}")


def benchmark_full_pipeline():
    """Benchmark the full pipeline."""
    from repair_app.engine.local_engine import LocalEngine
    from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams

    print("\n=== Full Pipeline Benchmark ===")
    print(f"{'Size':>10} | {'Time(s)':>8} | {'Peak(MB)':>8}")
    print("-" * 40)

    engine = LocalEngine()
    params = ProcessParams(num_layers=5)
    for n in [1000, 5000, 10000]:
        data = _generate_test_data(n)
        pc = PointCloud(xyz=data["xyz"], normals=data["normals"])
        dr = DefectRegion(mask=data["mask"])

        def _run():
            wp = None
            for w in engine.plan_path(pc, dr, params):
                wp = w
            if wp is not None:
                list(engine.predict_morphology(pc, dr, wp, params))

        stats = measure_memory(_run)
        print(f"{n:>10,} | {stats['time_s']:>8.3f} | {stats['peak_mb']:>8.1f}")


def main():
    print("Cold Spray Repair - Performance Benchmark")
    print("=" * 50)
    benchmark_path_planning()
    benchmark_morphology()
    benchmark_full_pipeline()


if __name__ == "__main__":
    main()