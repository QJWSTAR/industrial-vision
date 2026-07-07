"""Domain models — unified data structures for the repair workflow.

These dataclasses replace scattered dict/ndarray/tuple usage across the codebase,
providing type safety and a single source of truth.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np


# ---- Workflow State ----

class WorkflowState(Enum):
    """Explicit workflow state machine for the repair pipeline."""
    IDLE = "idle"
    DATA_LOADED = "data_loaded"
    PATH_PLANNING = "path_planning"
    PATH_READY = "path_ready"
    MORPHOLOGY_RUNNING = "morphology_running"
    MORPHOLOGY_DONE = "morphology_done"
    EXPORT_READY = "export_ready"


# ---- Core Domain Objects ----

@dataclass
class PointCloud:
    """Immutable point cloud with optional normals."""
    xyz: np.ndarray   # (N, 3) float32
    normals: Optional[np.ndarray] = None  # (N, 3) float32

    def __post_init__(self) -> None:
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3:
            raise ValueError(f"xyz must be (N,3), got {self.xyz.shape}")

    @property
    def point_count(self) -> int:
        return len(self.xyz)

    def has_normals(self) -> bool:
        return self.normals is not None and len(self.normals) == len(self.xyz)


@dataclass
class DefectRegion:
    """Defect region defined by a boolean mask on the point cloud."""
    mask: np.ndarray  # (N,) bool
    point_count: int = 0

    def __post_init__(self) -> None:
        self.point_count = int(np.sum(self.mask))

    @property
    def is_empty(self) -> bool:
        return self.point_count == 0


@dataclass
class ProcessParams:
    """Unified process parameters for path planning and cold spray."""
    # Path planning
    layer_height_mm: float = 2.0
    scanning_angle_deg: float = -45.0
    scanning_step_mm: float = 2.0
    edge_step_size_mm: float = 2.0
    tilt_angle_deg: float = 60.0
    buffer_additive_mm: float = 2.0
    buffer_repairing_mm: float = 0.0
    link_free_dist_mm: float = 20.0
    obstacle_resolution_mm: float = 2.0
    num_layers: int = 5
    depth_compensation: float = 1.0

    # Cold spray
    particle_velocity_ms: float = 500.0
    critical_velocity_ms: float = 400.0
    nozzle_diameter_mm: float = 6.0
    spray_angle_deg: float = 90.0
    standoff_distance_mm: float = 30.0
    particle_size_um: float = 25.0
    traversing_speed_mms: float = 500.0
    gas_temperature_c: float = 800.0
    gas_pressure_bar: float = 40.0
    powder_feed_rate_gmin: float = 30.0

    # Material
    material_name: str = "316L 不锈钢"
    material_code: str = "STEEL_316L"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class RepairJob:
    """A complete repair job that bundles all inputs."""
    scan_id: str
    point_cloud: PointCloud
    defect_region: DefectRegion
    params: ProcessParams = field(default_factory=ProcessParams)
    seed: int = 42


@dataclass
class Waypoint:
    """A single waypoint with position and optional orientation."""
    x: float
    y: float
    z: float
    nx: float = 0.0
    ny: float = 0.0
    nz: float = 1.0
    feed_rate: float = 0.0
    layer_index: int = 0

    @staticmethod
    def from_array(arr: np.ndarray) -> list[Waypoint]:
        """Convert (N, 3+) ndarray to list of Waypoints."""
        waypoints = []
        for row in arr:
            wp = Waypoint(
                x=float(row[0]), y=float(row[1]), z=float(row[2]),
            )
            if len(row) >= 6:
                wp.nx = float(row[3])
                wp.ny = float(row[4])
                wp.nz = float(row[5])
            if len(row) >= 7:
                wp.feed_rate = float(row[6])
            if len(row) >= 8:
                wp.layer_index = int(row[7])
            waypoints.append(wp)
        return waypoints

    @staticmethod
    def to_array(waypoints: list[Waypoint]) -> np.ndarray:
        """Convert list of Waypoints to (N, 7) ndarray."""
        return np.array([
            [w.x, w.y, w.z, w.nx, w.ny, w.nz, w.feed_rate]
            for w in waypoints
        ], dtype=np.float32)


@dataclass
class RepairResult:
    """Result of a repair operation (path planning + morphology)."""
    waypoints: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    repair_xyz: Optional[np.ndarray] = None
    layers: Optional[list[np.ndarray]] = None
    path_length_mm: float = 0.0
    estimated_time_s: float = 0.0
    defect_point_count: int = 0
    fill_point_count: int = 0
    uniformity_score: float = 0.0
    is_feasible: bool = True
    feasibility_reason: str = ""
    status_code: int = 0