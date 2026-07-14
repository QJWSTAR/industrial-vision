"""Performance profiling tool for cold spray repair application.

Usage:
    python3 -m repair_app.tools.profiler [--mode path|morph|full] [--size small|medium|large]
"""

from __future__ import annotations
import cProfile
import pstats
import io
import time
import os
import sys
import argparse
from typing import Callable

import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _generate_test_data(size: str = "medium") -> dict:
    """Generate test data for profiling."""
    sizes = {
        "small": 1000,
        "medium": 10000,
        "large": 100000,
    }
    n = sizes.get(size, 10000)

    rng = np.random.default_rng(42)
    xyz = rng.uniform(-50, 50, (n, 3)).astype(np.float32)
    xyz[:, 2] = rng.uniform(0, 20, n).astype(np.float32)
    normals = rng.normal(0, 1, (n, 3)).astype(np.float32)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)

    mask = np.zeros(n, dtype=bool)
    mask[n // 3 : 2 * n // 3] = True

    return {"xyz": xyz, "normals": normals, "mask": mask, "n": n}


def profile_path_planning(data: dict) -> None:
    """Profile path planning."""
    from repair_app.core.path_planner import iter_path_from_cloud
    from repair_app.domain.models import ProcessParams

    params = ProcessParams(num_layers=5)

    def _run():
        list(iter_path_from_cloud(
            xyz=data["xyz"],
            defect_mask=data["mask"],
            layer_height=params.layer_height_mm,
            scanning_angle=params.scanning_angle_deg,
            scanning_step=params.scanning_step_mm,
            buffer_mm=params.buffer_additive_mm,
            n_layers=params.num_layers,
        ))

    print(f"\n=== Path Planning Profile (n={data['n']:,}, layers=5) ===")
    _run_with_profile(_run, "path_planning")


def profile_morphology(data: dict) -> None:
    """Profile morphology prediction."""
    from repair_app.core.morphology_predictor import iter_repair_mesh_layers
    from repair_app.core.path_planner import iter_path_from_cloud
    from repair_app.domain.models import ProcessParams

    params = ProcessParams(num_layers=3)
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

    def _run():
        if waypoints is not None:
            list(iter_repair_mesh_layers(
                base_pts=data["xyz"],
                defect_mask=data["mask"],
                waypoints=waypoints,
                particle_velocity_ms=500,
                critical_velocity_ms=400,
                nozzle_diameter_mm=6,
                n_layers=3,
            ))

    print(f"\n=== Morphology Profile (n={data['n']:,}, layers=3, waypoints={len(waypoints) if waypoints is not None else 0}) ===")
    _run_with_profile(_run, "morphology")


def _run_with_profile(func: Callable, label: str):
    """Run a function with cProfile and print results."""
    profiler = cProfile.Profile()
    profiler.enable()

    t0 = time.perf_counter()
    func()
    elapsed = time.perf_counter() - t0

    profiler.disable()
    s = io.StringIO()
    sortby = "cumulative"
    ps = pstats.Stats(profiler, stream=s).sort_stats(sortby)
    ps.print_stats(20)

    print(f"  Wall time: {elapsed:.3f}s")
    print(s.getvalue())


def print_memory_usage(data: dict):
    """Print memory usage of data structures."""
    def _sizeof(arr):
        if isinstance(arr, np.ndarray):
            return arr.nbytes / 1024 / 1024
        return 0

    print(f"\n=== Memory Usage ===")
    for key in ["xyz", "normals", "mask"]:
        if key in data:
            print(f"  {key}: {_sizeof(data[key]):.2f} MB")


def main():
    parser = argparse.ArgumentParser(description="Performance profiler")
    parser.add_argument("--mode", choices=["path", "morph", "full", "all"], default="all")
    parser.add_argument("--size", choices=["small", "medium", "large"], default="medium")
    args = parser.parse_args()

    data = _generate_test_data(args.size)
    print(f"Test data: {data['n']:,} points")
    print_memory_usage(data)

    if args.mode in ("path", "all"):
        profile_path_planning(data)
    if args.mode in ("morph", "all"):
        profile_morphology(data)


if __name__ == "__main__":
    main()