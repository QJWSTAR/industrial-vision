"""
workers.py — UI工作线程模块
"""

from __future__ import annotations
import numpy as np
from PySide6.QtCore import QObject, QThread, Slot, Signal

from repair_app.core.path_planner import iter_path_from_cloud
from repair_app.core.morphology_predictor import iter_repair_mesh_layers


class PathPlanningWorker(QObject):
    partial = Signal(object, int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        xyz: np.ndarray,
        defect_mask: np.ndarray,
        params: dict,
        n_layers: int,
        buffer_mm: float,
    ) -> None:
        super().__init__()
        self._xyz = xyz.copy()
        self._defect_mask = defect_mask.copy()
        self._params = dict(params)
        self._n_layers = n_layers
        self._buffer_mm = buffer_mm

    @Slot()
    def run(self) -> None:
        try:
            last_waypoints = np.zeros((0, 3))
            for layer_idx, waypoints in enumerate(
                iter_path_from_cloud(
                    xyz=self._xyz,
                    defect_mask=self._defect_mask,
                    layer_height=self._params.get("layer_height_mm", 2.0),
                    scanning_angle=self._params.get("scanning_angle_deg", -45.0),
                    scanning_step=self._params.get("scanning_step_mm", 2.0),
                    buffer_mm=self._buffer_mm,
                    n_layers=self._n_layers,
                ),
                start=1,
            ):
                if QThread.currentThread().isInterruptionRequested():
                    return
                last_waypoints = waypoints
                self.partial.emit(waypoints, layer_idx, self._n_layers)
            self.finished.emit(last_waypoints)
        except Exception as exc:
            self.failed.emit(str(exc))


class MorphologyWorker(QObject):
    partial = Signal(object, int, int)
    finished = Signal(object)
    failed = Signal(str, object)

    def __init__(
        self,
        xyz: np.ndarray,
        defect_mask: np.ndarray,
        waypoints: np.ndarray,
        params: dict,
        n_layers: int,
        seed: int,
    ) -> None:
        super().__init__()
        self._xyz = xyz.copy()
        self._defect_mask = defect_mask.copy()
        self._waypoints = waypoints.copy()
        self._params = dict(params)
        self._n_layers = n_layers
        self._seed = seed

    @Slot()
    def run(self) -> None:
        repair = np.zeros((0, 3))
        try:
            base = self._xyz[self._defect_mask]
            n_pts = min(int(np.sum(self._defect_mask) * 0.4), 5000)
            rng = np.random.default_rng(self._seed + 1)
            z_base = np.max(base[:, 2])
            repair = np.column_stack([
                rng.uniform(np.min(base[:, :2], axis=0), np.max(base[:, :2], axis=0), (n_pts, 2)),
                z_base + np.abs(rng.normal(0, 0.3, n_pts)),
            ])

            base_pts = np.vstack([self._xyz, repair])
            combined_mask = np.concatenate([self._defect_mask, np.ones(len(repair), dtype=bool)])
            last_pts = base_pts
            for layer_idx, full_pts in enumerate(
                iter_repair_mesh_layers(
                    base_pts=base_pts,
                    defect_mask=combined_mask,
                    waypoints=self._waypoints,
                    particle_velocity_ms=self._params.get("particle_velocity_ms", 500),
                    critical_velocity_ms=self._params.get("critical_velocity_ms", 400),
                    nozzle_diameter_mm=self._params.get("nozzle_diameter_mm", 6),
                    n_layers=self._n_layers,
                ),
                start=1,
            ):
                if QThread.currentThread().isInterruptionRequested():
                    return
                last_pts = full_pts
                repair_only = full_pts[len(self._xyz):] if len(full_pts) > len(self._xyz) else repair
                self.partial.emit(repair_only, layer_idx, self._n_layers)

            repair_only = last_pts[len(self._xyz):] if len(last_pts) > len(self._xyz) else repair
            self.finished.emit(repair_only)
        except Exception as exc:
            self.failed.emit(str(exc), repair)
