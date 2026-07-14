"""Validation module — scientific validation pipeline.

Provides unified interfaces for comparing Python vs MATLAB results,
managing datasets, running experiments, and generating validation reports.
"""

from repair_app.validation.validator import (
    ValidationResult,
    ComparisonMetric,
    PointCloudValidator,
    WaypointValidator,
    MorphologyValidator,
)
from repair_app.validation.metrics import (
    compute_rmse,
    compute_chamfer_distance,
    compute_hausdorff_distance,
    compute_iou_3d,
    compute_waypoint_deviation,
)
from repair_app.validation.dataset import DatasetManager, DatasetMetadata
from repair_app.validation.experiment import ExperimentManager, ExperimentRecord
from repair_app.validation.result_manager import ResultManager, ResultSummary

__all__ = [
    # Validators
    "ValidationResult",
    "ComparisonMetric",
    "PointCloudValidator",
    "WaypointValidator",
    "MorphologyValidator",
    # Metrics
    "compute_rmse",
    "compute_chamfer_distance",
    "compute_hausdorff_distance",
    "compute_iou_3d",
    "compute_waypoint_deviation",
    # Dataset
    "DatasetManager",
    "DatasetMetadata",
    # Experiment
    "ExperimentManager",
    "ExperimentRecord",
    # Result
    "ResultManager",
    "ResultSummary",
]