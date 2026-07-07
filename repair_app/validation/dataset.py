"""Dataset management — versioned dataset loading and metadata.

Provides a unified interface for loading, versioning, and tracking
datasets used in validation experiments. Each dataset is identified
by a unique name and version, with metadata stored in JSON.

Usage:
    manager = DatasetManager()
    dataset = manager.load("defect_001", version="v1")
    xyz, normals, mask = dataset["xyz"], dataset["normals"], dataset["mask"]
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import hashlib

import numpy as np

from repair_app.utils.logger_config import info, warning, error as log_error
from repair_app.utils.resource_path import get_data_dir


@dataclass
class DatasetMetadata:
    """Metadata for a dataset version."""
    name: str
    version: str
    created_at: str = ""
    description: str = ""
    source: str = ""  # e.g. "MATLAB export", "3D scanner"
    point_count: int = 0
    defect_point_count: int = 0
    bbox: list[float] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    checksum: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "created_at": self.created_at,
            "description": self.description,
            "source": self.source,
            "point_count": self.point_count,
            "defect_point_count": self.defect_point_count,
            "bbox": self.bbox,
            "checksum": self.checksum,
            "tags": self.tags,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DatasetMetadata:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class DatasetManager:
    """Manages versioned datasets for validation experiments.

    Directory structure:
        datasets/
        └── {name}/
            ├── metadata.json
            ├── {version}/
            │   ├── metadata.json
            │   ├── xyz.npy
            │   ├── normals.npy
            │   ├── mask.npy
            │   └── waypoints.npy (optional)
            └── ...
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir is None:
            data_dir = os.path.join(str(get_data_dir()), "datasets")
        self._data_dir = data_dir
        os.makedirs(self._data_dir, exist_ok=True)

    def create(
        self,
        name: str,
        version: str,
        xyz: np.ndarray,
        normals: Optional[np.ndarray] = None,
        mask: Optional[np.ndarray] = None,
        waypoints: Optional[np.ndarray] = None,
        description: str = "",
        source: str = "",
        tags: Optional[list[str]] = None,
        extra: Optional[dict] = None,
    ) -> DatasetMetadata:
        """Create a new dataset version.

        Args:
            name: Dataset name.
            version: Version string (e.g. "v1").
            xyz: Point cloud coordinates (N, 3).
            normals: Optional normals (N, 3).
            mask: Optional defect mask (N,).
            waypoints: Optional repair waypoints (M, >=3).
            description: Optional description.
            source: Optional source info.
            tags: Optional tags list.
            extra: Optional extra metadata.

        Returns:
            DatasetMetadata for the created version.
        """
        # 路径遍历防护
        safe_name = name.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        safe_version = version.replace("..", "").replace("/", "_").replace("\\", "_").strip()
        if not safe_name or not safe_version:
            raise ValueError("数据集名称和版本不能为空或仅包含路径分隔符")

        version_dir = os.path.join(self._data_dir, safe_name, safe_version)
        os.makedirs(version_dir, exist_ok=True)

        # Save arrays
        np.save(os.path.join(version_dir, "xyz.npy"), xyz.astype(np.float32))
        if normals is not None:
            np.save(os.path.join(version_dir, "normals.npy"), normals.astype(np.float32))
        if mask is not None:
            np.save(os.path.join(version_dir, "mask.npy"), mask.astype(bool))
        if waypoints is not None:
            np.save(os.path.join(version_dir, "waypoints.npy"), waypoints.astype(np.float32))

        # Compute metadata
        checksum = hashlib.md5(xyz.tobytes()).hexdigest()[:16]
        bbox = [
            float(np.min(xyz[:, 0])), float(np.min(xyz[:, 1])), float(np.min(xyz[:, 2])),
            float(np.max(xyz[:, 0])), float(np.max(xyz[:, 1])), float(np.max(xyz[:, 2])),
        ]

        meta = DatasetMetadata(
            name=name,
            version=version,
            created_at=datetime.now().isoformat(),
            description=description,
            source=source,
            point_count=len(xyz),
            defect_point_count=int(np.sum(mask)) if mask is not None else 0,
            bbox=bbox,
            checksum=checksum,
            tags=tags or [],
            extra=extra or {},
        )

        # Save metadata
        meta_path = os.path.join(version_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.to_dict(), f, indent=2, ensure_ascii=False)

        info(f"Dataset created: {name}/{version} ({meta.point_count:,} points)")
        return meta

    def load(self, name: str, version: str = "v1") -> dict:
        """Load a dataset version.

        Returns:
            Dict with keys: 'xyz', 'normals' (optional), 'mask' (optional),
            'waypoints' (optional), 'metadata'.
        """
        version_dir = os.path.join(self._data_dir, name, version)
        if not os.path.exists(version_dir):
            raise FileNotFoundError(f"Dataset not found: {name}/{version}")

        data = {}

        # Load arrays
        xyz_path = os.path.join(version_dir, "xyz.npy")
        if os.path.exists(xyz_path):
            data["xyz"] = np.load(xyz_path)

        for key in ["normals", "mask", "waypoints"]:
            path = os.path.join(version_dir, f"{key}.npy")
            if os.path.exists(path):
                data[key] = np.load(path)

        # Load metadata
        meta_path = os.path.join(version_dir, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                data["metadata"] = DatasetMetadata.from_dict(json.load(f))

        info(f"Dataset loaded: {name}/{version} ({data.get('xyz', np.zeros(0)).shape[0]:,} points)")
        return data

    def list_datasets(self) -> list[str]:
        """List all dataset names."""
        if not os.path.exists(self._data_dir):
            return []
        return sorted([
            d for d in os.listdir(self._data_dir)
            if os.path.isdir(os.path.join(self._data_dir, d))
        ])

    def list_versions(self, name: str) -> list[str]:
        """List all versions of a dataset."""
        dataset_dir = os.path.join(self._data_dir, name)
        if not os.path.exists(dataset_dir):
            return []
        return sorted([
            d for d in os.listdir(dataset_dir)
            if os.path.isdir(os.path.join(dataset_dir, d))
        ])

    def get_metadata(self, name: str, version: str = "v1") -> Optional[DatasetMetadata]:
        """Get dataset metadata without loading the data."""
        meta_path = os.path.join(self._data_dir, name, version, "metadata.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            return DatasetMetadata.from_dict(json.load(f))

    def compare_versions(self, name: str, v1: str, v2: str) -> dict:
        """Compare two versions of the same dataset.

        Returns:
            Dict with comparison metrics.
        """
        data1 = self.load(name, v1)
        data2 = self.load(name, v2)

        from repair_app.validation.metrics import compute_chamfer_distance

        xyz1 = data1.get("xyz", np.zeros((0, 3)))
        xyz2 = data2.get("xyz", np.zeros((0, 3)))

        return {
            "name": name,
            "version_a": v1,
            "version_b": v2,
            "points_a": len(xyz1),
            "points_b": len(xyz2),
            "chamfer": compute_chamfer_distance(xyz1, xyz2) if len(xyz1) > 0 and len(xyz2) > 0 else None,
        }