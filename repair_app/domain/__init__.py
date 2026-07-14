"""Domain layer: unified data models and engine interfaces."""

from repair_app.domain.models import (
    PointCloud,
    DefectRegion,
    RepairJob,
    Waypoint,
    RepairResult,
    ProcessParams,
    WorkflowState,
)
from repair_app.domain.interfaces import (
    IPathPlanner,
    IMorphologyPredictor,
    IEngine,
)

__all__ = [
    "PointCloud",
    "DefectRegion",
    "RepairJob",
    "Waypoint",
    "RepairResult",
    "ProcessParams",
    "WorkflowState",
    "IPathPlanner",
    "IMorphologyPredictor",
    "IEngine",
]