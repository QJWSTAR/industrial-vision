"""Local engine — wraps Python prototype path_planner and morphology_predictor.

Implements IEngine interface, providing a unified entry point for the
local Python algorithm implementation. Serves as the reference engine
and can be swapped with a MATLAB ZMQ engine via the same interface.
"""

from __future__ import annotations
from typing import Iterator

import numpy as np

from repair_app.domain.interfaces import IEngine
from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams
from repair_app.core.path_planner import iter_path_from_cloud
from repair_app.core.morphology_predictor import iter_repair_mesh_layers


class LocalEngine(IEngine):
    """Local Python engine using pure-Python implementation."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "Local Python Engine"

    @property
    def is_available(self) -> bool:
        return True

    def plan_path(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        params: ProcessParams,
        is_additive: bool = False,
    ) -> Iterator[np.ndarray]:
        """Generate repair waypoints layer by layer.

        Yields cumulative waypoints after each layer.
        """
        buffer_mm = params.buffer_additive_mm if is_additive else params.buffer_repairing_mm
        yield from iter_path_from_cloud(
            xyz=point_cloud.xyz,
            defect_mask=defect_region.mask,
            layer_height=params.layer_height_mm,
            scanning_angle=params.scanning_angle_deg,
            scanning_step=params.scanning_step_mm,
            buffer_mm=buffer_mm,
            n_layers=params.num_layers,
        )

    def predict_morphology(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        waypoints: np.ndarray,
        params: ProcessParams,
    ) -> Iterator[np.ndarray]:
        """Predict deposition morphology layer by layer.

        Yields cumulative point cloud after each deposition layer.
        """
        yield from iter_repair_mesh_layers(
            base_pts=point_cloud.xyz,
            defect_mask=defect_region.mask,
            waypoints=waypoints,
            particle_velocity_ms=params.particle_velocity_ms,
            critical_velocity_ms=params.critical_velocity_ms,
            nozzle_diameter_mm=params.nozzle_diameter_mm,
            n_layers=params.num_layers,
        )

    def check_health(self) -> bool:
        return True