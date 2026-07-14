"""Repository layer: data access abstraction for file I/O and persistence."""

from repair_app.repository.file_repository import FileRepository
from repair_app.repository.material_repository import MaterialRepository

__all__ = ["FileRepository", "MaterialRepository"]