"""Service layer — business logic orchestration.

Services coordinate between Repository and Engine layers,
providing the Controller with a clean API for the repair workflow.

Note: RepairService was removed as dead code (was only referenced by
the also-removed AppController). FileService and ValidationService
remain as active services.
"""

from repair_app.service.file_service import FileService
from repair_app.service.validation_service import ValidationService
from repair_app.service.coordination_service import CoordinationService

__all__ = ["FileService", "ValidationService", "ExportService", "CoordinationService"]


def __getattr__(name):
    """PEP 562 lazy import — ExportService 依赖 matplotlib，延迟导入避免时序冲突。"""
    if name == "ExportService":
        from repair_app.service.export_service import ExportService
        return ExportService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
