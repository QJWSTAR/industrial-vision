"""Export service — G-code and PDF report export operations.

Encapsulates export logic that was previously inlined in MainWindow,
providing a clean service-layer API for the UI to call.
"""

from __future__ import annotations
from typing import Optional, Dict, Any
import numpy as np

from repair_app.export.gcode_exporter import GCodeExporter
from repair_app.export.export_validator import validate_toolpath
from repair_app.export.report_generator import RepairReport
from repair_app.utils.logger_config import info, error as log_error


class ExportService:
    """Service for exporting repair results to G-code and PDF reports.

    This service isolates the UI layer from direct contact with
    export module internals (GCodeExporter, RepairReport, validate_toolpath).
    """

    @staticmethod
    def _compute_safe_z(waypoints: np.ndarray) -> float:
        """计算安全 Z 高度（最高点 + 5mm，最小 10mm）。"""
        return max(10.0, float(np.max(waypoints[:, 2])) + 5.0)

    @staticmethod
    def _validate_waypoints(waypoints: np.ndarray) -> None:
        """检查航点数组形状，防止 IndexError。"""
        if waypoints is None or len(waypoints) == 0:
            raise ValueError("航点数组为空")
        if waypoints.ndim != 2 or waypoints.shape[1] < 3:
            raise ValueError(
                f"航点形状应为 (N, >=3)，实际为 {waypoints.shape}"
            )

    def validate_toolpath(self, waypoints: np.ndarray) -> tuple:
        """Validate waypoints before G-code export.

        Returns:
            (ok, validation_result) tuple.
        """
        self._validate_waypoints(waypoints)
        safe_z = self._compute_safe_z(waypoints)
        result = validate_toolpath(waypoints, safe_z=safe_z)
        return result.ok, result

    def export_gcode(
        self,
        waypoints: np.ndarray,
        output_path: str,
        feed_rate: float = 500.0,
    ) -> bool:
        """Export waypoints to G-code file.

        Args:
            waypoints: (N, >=3) waypoint array.
            output_path: Output file path.
            feed_rate: Traversing speed in mm/min.

        Returns:
            True if export succeeded.
        """
        try:
            self._validate_waypoints(waypoints)
            safe_z = self._compute_safe_z(waypoints)
            exporter = GCodeExporter(
                feed_rate=feed_rate,
                safe_z=safe_z,
            )
            exporter.export(waypoints, output_path=output_path)
            info(f"G-code exported: {output_path}")
            return True
        except Exception as e:
            log_error(f"G-code export failed: {e}")
            return False

    def export_pdf_report(
        self,
        output_path: str,
        scan_info: Dict[str, Any],
        parameters: Dict[str, Any],
        results: Dict[str, Any],
        xyz: Optional[np.ndarray] = None,
        defect_mask: Optional[np.ndarray] = None,
        repair_xyz: Optional[np.ndarray] = None,
    ) -> bool:
        """Generate a PDF repair report.

        Args:
            output_path: Output PDF file path.
            scan_info: Dict with scan_id, points, defect_volume_mm3, etc.
            parameters: Dict of process parameters.
            results: Dict of result metrics.
            xyz: Original point cloud (optional, for comparison figure).
            defect_mask: Boolean mask of defect region.
            repair_xyz: Repair point cloud (for comparison figure).

        Returns:
            True if report generation succeeded.
        """
        try:
            report = RepairReport()
            report.set_scan_info(**scan_info)
            report.set_parameters(parameters)
            report.set_results(results)

            if xyz is not None and repair_xyz is not None:
                repair_only = repair_xyz[len(xyz):] if len(repair_xyz) > len(xyz) else repair_xyz
                report.add_comparison_figure(xyz, defect_mask, repair_only)
                report.add_height_colormap(repair_only)

            ok = report.generate(output_path)
            if ok:
                info(f"PDF report exported: {output_path}")
            return ok
        except Exception as e:
            log_error(f"PDF report export failed: {e}")
            return False
