"""Engine interfaces — abstract base classes for algorithm and engine abstraction.

These interfaces enable switching between local Python prototype and MATLAB
black-box backend without modifying UI code.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator, Optional

import numpy as np

from repair_app.domain.models import PointCloud, DefectRegion, ProcessParams, RepairResult


class IPathPlanner(ABC):
    """Abstract interface for path planning algorithms.

    Implementations:
        - LocalPathPlanner: uses repair_app.core.path_planner
        - MatlabPathPlanner: sends request via ZMQ to MATLAB engine
    """

    @abstractmethod
    def plan(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        params: ProcessParams,
        is_additive: bool = False,
    ) -> Iterator[np.ndarray]:
        """Generate repair waypoints layer by layer.

        Yields:
            Cumulative waypoints array (N, 3) after each layer.
        """
        ...


class IMorphologyPredictor(ABC):
    """Abstract interface for morphology prediction algorithms.

    Implementations:
        - LocalMorphologyPredictor: uses repair_app.core.morphology_predictor
        - MatlabMorphologyPredictor: sends request via ZMQ to MATLAB engine
    """

    @abstractmethod
    def predict(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        waypoints: np.ndarray,
        params: ProcessParams,
    ) -> Iterator[np.ndarray]:
        """Predict deposition morphology layer by layer.

        Yields:
            Cumulative point cloud (N, 3) after each deposition layer.
        """
        ...


class IEngine(ABC):
    """Abstract interface for the repair computation engine.

    A single engine may provide both path planning and morphology prediction,
    or they may be separate. The engine is the top-level abstraction that
    the Controller layer interacts with.

    Implementations:
        - LocalEngine: Python prototype (path_planner + morphology_predictor)
        - MatlabEngine: ZMQ-based MATLAB black-box engine
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this engine is currently reachable."""
        ...

    @abstractmethod
    def plan_path(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        params: ProcessParams,
        is_additive: bool = False,
    ) -> Iterator[np.ndarray]:
        """Generate repair waypoints. See IPathPlanner.plan."""
        ...

    @abstractmethod
    def predict_morphology(
        self,
        point_cloud: PointCloud,
        defect_region: DefectRegion,
        waypoints: np.ndarray,
        params: ProcessParams,
    ) -> Iterator[np.ndarray]:
        """Predict deposition morphology. See IMorphologyPredictor.predict."""
        ...

    @abstractmethod
    def check_health(self) -> bool:
        """Check if the engine is healthy and responsive."""
        ...