"""Experiment management — orchestrate and record validation experiments.

Each experiment is a self-contained run with:
- Input parameters and dataset
- Execution results (Python + optional MATLAB)
- Validation metrics
- Metadata for reproducibility

Usage:
    manager = ExperimentManager()
    exp = manager.create_experiment("morph_validation_001", params)
    manager.record_result(exp_id, "python_morph", py_result)
    manager.record_result(exp_id, "matlab_morph", matlab_result)
    manager.finalize(exp_id)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import json
import os
import uuid

import numpy as np

from repair_app.utils.logger_config import info, warning, error as log_error
from repair_app.utils.resource_path import get_data_dir


@dataclass
class ExperimentRecord:
    """A single experiment run."""
    id: str
    name: str
    created_at: str
    status: str  # "running", "completed", "failed"
    params: dict[str, Any] = field(default_factory=dict)
    dataset: dict[str, str] = field(default_factory=dict)  # {name, version}
    results: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    validation_results: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "status": self.status,
            "params": self.params,
            "dataset": self.dataset,
            "results": {k: _serialize_value(v) for k, v in self.results.items()},
            "metrics": self.metrics,
            "validation_results": self.validation_results,
            "logs": self.logs,
            "duration_s": self.duration_s,
            "tags": self.tags,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExperimentRecord:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _serialize_value(v: Any) -> Any:
    """Serialize a value for JSON storage."""
    if isinstance(v, np.ndarray):
        return {"_type": "ndarray", "shape": list(v.shape), "dtype": str(v.dtype)}
    if isinstance(v, (int, float, str, bool, list, dict, type(None))):
        return v
    return str(v)


class ExperimentManager:
    """Manages validation experiments.

    Directory structure:
        experiments/
        └── {name}/
            └── {id}/
                ├── record.json
                ├── results/
                │   ├── python_waypoints.npy
                │   ├── matlab_waypoints.npy
                │   └── ...
                └── ...
    """

    def __init__(self, exp_dir: Optional[str] = None) -> None:
        if exp_dir is None:
            exp_dir = os.path.join(str(get_data_dir()), "experiments")
        self._exp_dir = exp_dir
        os.makedirs(self._exp_dir, exist_ok=True)

    def create_experiment(
        self,
        name: str,
        params: dict[str, Any],
        dataset_name: str = "",
        dataset_version: str = "v1",
        tags: Optional[list[str]] = None,
        extra: Optional[dict] = None,
    ) -> ExperimentRecord:
        """Create a new experiment.

        Args:
            name: Experiment name (e.g. "morph_validation_001").
            params: Process parameters dict.
            dataset_name: Reference dataset name.
            dataset_version: Dataset version.
            tags: Optional tags.
            extra: Optional extra metadata.

        Returns:
            ExperimentRecord with generated ID.
        """
        exp_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        # 路径遍历防护：清理 name 中的危险字符
        safe_name = name.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        if not safe_name:
            raise ValueError("实验名称不能为空或仅包含路径分隔符")
        exp_dir = os.path.join(self._exp_dir, safe_name, exp_id)
        os.makedirs(exp_dir, exist_ok=True)
        os.makedirs(os.path.join(exp_dir, "results"), exist_ok=True)

        record = ExperimentRecord(
            id=exp_id,
            name=name,
            created_at=datetime.now().isoformat(),
            status="running",
            params=params,
            dataset={"name": dataset_name, "version": dataset_version} if dataset_name else {},
            tags=tags or [],
            extra=extra or {},
        )

        self._save_record(record)
        info(f"Experiment created: {name}/{exp_id}")
        return record

    def record_result(
        self,
        record: ExperimentRecord,
        key: str,
        data: np.ndarray,
        save: bool = True,
    ) -> None:
        """Record a result (e.g. waypoints, morphology point cloud).

        Args:
            record: Experiment record to update.
            key: Result key (e.g. "python_waypoints", "matlab_morph").
            data: The result data array.
            save: Whether to save to disk.
        """
        record.results[key] = data
        if save:
            exp_dir = self._get_exp_dir(record)
            np.save(os.path.join(exp_dir, "results", f"{key}.npy"), data.astype(np.float32))
        record.logs.append(f"[{datetime.now().isoformat()}] Result recorded: {key} ({len(data)} entries)")
        self._save_record(record)

    def record_metrics(self, record: ExperimentRecord, metrics: dict[str, float]) -> None:
        """Record validation metrics."""
        record.metrics.update(metrics)
        record.logs.append(f"[{datetime.now().isoformat()}] Metrics: {metrics}")
        self._save_record(record)

    def record_validation(
        self,
        record: ExperimentRecord,
        validation_result: Any,  # ValidationResult
    ) -> None:
        """Record a validation result."""
        record.validation_results.append(validation_result.to_dict() if hasattr(validation_result, "to_dict") else validation_result)
        record.logs.append(f"[{datetime.now().isoformat()}] Validation: {getattr(validation_result, 'name', '')} - {'PASS' if getattr(validation_result, 'passed', False) else 'FAIL'}")
        self._save_record(record)

    def finalize(
        self,
        record: ExperimentRecord,
        status: str = "completed",
        duration_s: float = 0.0,
    ) -> None:
        """Finalize an experiment."""
        record.status = status
        record.duration_s = duration_s
        record.logs.append(f"[{datetime.now().isoformat()}] Experiment {status}")
        self._save_record(record)
        info(f"Experiment finalized: {record.name}/{record.id} ({status})")

    def load_experiment(self, name: str, exp_id: str) -> ExperimentRecord:
        """Load an experiment record."""
        record_path = os.path.join(self._exp_dir, name, exp_id, "record.json")
        if not os.path.exists(record_path):
            raise FileNotFoundError(f"Experiment not found: {name}/{exp_id}")
        with open(record_path, "r", encoding="utf-8") as f:
            return ExperimentRecord.from_dict(json.load(f))

    def list_experiments(self, name: Optional[str] = None) -> list[dict]:
        """List experiments. If name is None, list all."""
        exp_dir = self._exp_dir
        if name:
            exp_dir = os.path.join(exp_dir, name)
        if not os.path.exists(exp_dir):
            return []

        result = []
        if name:
            for exp_id in sorted(os.listdir(exp_dir)):
                exp_path = os.path.join(exp_dir, exp_id)
                if os.path.isdir(exp_path):
                    try:
                        record = self.load_experiment(name, exp_id)
                        result.append({"name": name, "id": exp_id, "status": record.status, "created_at": record.created_at})
                    except Exception:
                        pass
        else:
            for d in sorted(os.listdir(exp_dir)):
                sub = os.path.join(exp_dir, d)
                if os.path.isdir(sub):
                    result.extend(self.list_experiments(d))
        return result

    def _get_exp_dir(self, record: ExperimentRecord) -> str:
        return os.path.join(self._exp_dir, record.name, record.id)

    def _save_record(self, record: ExperimentRecord) -> None:
        exp_dir = self._get_exp_dir(record)
        os.makedirs(exp_dir, exist_ok=True)
        record_path = os.path.join(exp_dir, "record.json")
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, ensure_ascii=False, default=str)