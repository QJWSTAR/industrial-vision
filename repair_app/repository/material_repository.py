"""Material repository — unified access to material parameter data.

Wraps MaterialDatabase with a repository pattern for consistent access
across different layers.
"""

from __future__ import annotations
from typing import Optional

from repair_app.core.material_database import (
    MaterialDatabase,
    MaterialParams,
    get_material_db,
)


class MaterialRepository:
    """Repository for material parameter data access.

    Provides a single entry point for material queries, decoupling
    UI and business logic from the underlying JSON file storage.
    """

    def __init__(self, db: Optional[MaterialDatabase] = None) -> None:
        self._db = db or get_material_db()

    def get(self, key: str) -> MaterialParams:
        """Get material parameters by key (e.g. 'STEEL_316L')."""
        return self._db.get(key)

    def get_default(self) -> MaterialParams:
        """Get the default material parameters."""
        return self._db.get_default()

    @property
    def material_keys(self) -> list[str]:
        """All available material keys."""
        return self._db.material_keys

    @property
    def thresholds(self) -> dict:
        """Feasibility check thresholds."""
        return self._db.thresholds