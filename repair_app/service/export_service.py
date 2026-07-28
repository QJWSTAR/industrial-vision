"""Export service — G-code and PDF report export operations.

P4-5: 所有方法接收 RepairSession 引用，从 Session 统一读取数据，
禁止重复缓存/重复同步。导出结果（路径/验证结果）回写 Session。

Encapsulates export logic that was previously inlined in MainWindow,
providing a clean service-layer API for the UI to call.
"""

from __future__ import annotations
from typing import Optional, Dict, Any
import numpy as np

from repair_app.core.repair_session import RepairSession
from repair_app.export.gcode_exporter import GCodeExporter
from repair_app.export.export_validator import validate_toolpath
from repair_app.export.report_generator import RepairReport
from repair_app.utils.logger_config import info, error as log_error


class ExportService:
    """Service for exporting repair results to G-code and PDF reports.

    P4-5: 所有方法接收 RepairSession，从 Session 读取数据，禁止重复缓存。
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

    def validate_toolpath(
        self,
        session: RepairSession,
        *,
        build_volume: Optional[tuple] = None,
    ) -> tuple:
        """Validate waypoints before G-code export.

        P4-5: 从 session 读取 waypoint.mock / point_cloud.xyz / waypoint.layers /
        validation.expected_n_layers / validation.expected_layer_height。
        验证结果回写 session.validation.result。

        Returns:
            (ok, validation_result) tuple.
        """
        waypoints = session.waypoint.mock
        self._validate_waypoints(waypoints)
        safe_z = self._compute_safe_z(waypoints)
        result = validate_toolpath(
            waypoints,
            safe_z=safe_z,
            substrate_xyz=session.point_cloud.xyz,
            build_volume=build_volume,
            layer_indices=session.waypoint.layers,
            expected_n_layers=session.validation.expected_n_layers,
            expected_layer_height=session.validation.expected_layer_height,
        )
        # P4-5: 验证结果回写 Session（单一真相源）
        session.validation.result = result
        return result.ok, result

    def export_gcode(
        self,
        session: RepairSession,
        output_path: str,
        feed_rate: float = 500.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Export waypoints to G-code file.

        P4-5: 从 session 读取 waypoint.mock / waypoint.layers。
        导出路径回写 session.output.last_gcode_path。

        Args:
            session: RepairSession（数据源）。
            output_path: Output file path.
            feed_rate: Traversing speed in mm/min.
            metadata: MF-5 追溯元数据 dict，含 model_version/material/parameters/license_id.

        Returns:
            True if export succeeded.
        """
        try:
            waypoints = session.waypoint.mock
            self._validate_waypoints(waypoints)
            safe_z = self._compute_safe_z(waypoints)
            exporter = GCodeExporter(
                feed_rate=feed_rate,
                safe_z=safe_z,
            )
            # MF-5: 设置追溯元数据
            if metadata:
                exporter.set_metadata(
                    model_version=metadata.get("model_version", ""),
                    material=metadata.get("material", ""),
                    parameters=metadata.get("parameters"),
                    license_id=metadata.get("license_id", ""),
                )
            exporter.export(
                waypoints, output_path=output_path,
                layer_indices=session.waypoint.layers,
            )
            # P4-5: 导出路径回写 Session
            session.output.last_gcode_path = output_path
            info(f"G-code exported: {output_path}")
            return True
        except Exception as e:
            log_error(f"G-code export failed: {e}")
            return False

    def export_pdf_report(
        self,
        session: RepairSession,
        output_path: str,
    ) -> bool:
        """Generate a PDF repair report.

        P4-5: 从 session.report 读取 scan_info/parameters/results/layers/statistics/quality，
        从 session.point_cloud.xyz / selection.mask / morphology.repair_xyz 读取可视化数据。
        禁止重复同步 — 报告字段由 MainWindow 统一写入 session.report。
        导出路径回写 session.output.last_pdf_path。

        Args:
            session: RepairSession（数据源，含 report 字段）。
            output_path: Output PDF file path.

        Returns:
            True if report generation succeeded.
        """
        try:
            report = RepairReport()
            report.set_scan_info(**session.report.scan_info)
            report.set_parameters(session.report.parameters)
            report.set_results(session.report.results)
            # P2-4: 填充新增章节
            if session.report.layers:
                report.set_layers(session.report.layers)
            if session.report.statistics:
                report.set_statistics(session.report.statistics)
            if session.report.quality:
                report.set_quality(session.report.quality)

            xyz = session.point_cloud.xyz
            repair_only = session.morphology.get_repair_points(xyz)
            if xyz is not None and repair_only is not None:
                report.add_comparison_figure(xyz, session.selection.mask, repair_only)
                report.add_height_colormap(repair_only)

            ok = report.generate(output_path)
            if ok:
                # P4-5: 导出路径回写 Session
                session.output.last_pdf_path = output_path
                info(f"PDF report exported: {output_path}")
            return ok
        except Exception as e:
            log_error(f"PDF report export failed: {e}")
            return False
