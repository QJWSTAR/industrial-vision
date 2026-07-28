"""builtin_exporters — 6 个内置导出器（GCode/Robot/PDF/CSV/JSON/Project）。

所有导出器通过 @register 装饰器自动注册到 ExporterRegistry。
MainWindow import 本模块即可发现全部导出格式。

新增导出格式只需在本文件（或新文件）中添加一个 @register 类，
无需修改 MainWindow / ExportService / 任何现有代码。
"""

from __future__ import annotations

import csv
import json
import os
import datetime
from typing import Any, Optional

import numpy as np

from repair_app.core.repair_session import RepairSession
from repair_app.export.pipeline import BaseExporter, ExportResult, register
from repair_app.utils.logger_config import info, error as log_error, warning


# ================================================================
# 1. G-code 导出器
# ================================================================
@register
class GCodeExporter(BaseExporter):
    """G-code 数控加工文件导出。

    复用现有 GCodeExporter，含安全验证（Collision/Boundary/Height/Layer）。
    """
    name = "gcode"
    display_name = "G-code"
    icon = "📤"
    tooltip = "导出标准 G-code 数控加工文件（.nc），含 Lead-in/Lead-out/分层"
    extension = ".nc"
    filter = "G-code (*.nc *.gcode *.txt);;所有文件 (*)"
    requires = ("waypoint.mock",)
    sort_order = 10

    def get_config(self, parent: Any, session: RepairSession) -> Optional[dict]:
        """从 session 获取验证参数和元数据。"""
        params = session.report.parameters or {}
        return {
            "feed_rate": float(params.get("traversing_speed_mms", 500.0)) * 60,
            "expected_n_layers": session.validation.expected_n_layers,
            "expected_layer_height": session.validation.expected_layer_height,
            "metadata": {
                "model_version": os.path.basename(session.point_cloud.path) if session.point_cloud.path else "unknown",
                "material": params.get(
                    "material_name", params.get("material", "未指定")
                ),
                "parameters": params,
                "license_id": session.license_id,
            },
        }

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        return str(path_manager.gcode_path("repair"))

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        try:
            from repair_app.export.gcode_exporter import GCodeExporter as _GCodeExp
            from repair_app.export.export_validator import validate_toolpath

            waypoints = session.waypoint.mock
            if waypoints is None or len(waypoints) == 0:
                return ExportResult(ok=False, error="航点为空")

            safe_z = max(10.0, float(np.max(waypoints[:, 2])) + 5.0)

            # 安全验证
            validation = validate_toolpath(
                waypoints,
                safe_z=safe_z,
                substrate_xyz=session.point_cloud.xyz,
                layer_indices=session.waypoint.layers,
                expected_n_layers=config.get("expected_n_layers"),
                expected_layer_height=config.get("expected_layer_height"),
            )
            session.validation.result = validation

            if not validation.ok:
                return ExportResult(
                    ok=False,
                    error="安全检查未通过: " + "; ".join(validation.blocking_messages),
                    warnings=validation.warning_messages,
                )

            # 导出 G-code
            feed_rate = config.get("feed_rate", 500.0)
            exporter = _GCodeExp(feed_rate=feed_rate, safe_z=safe_z)
            metadata = config.get("metadata", {})
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
                validate=False,  # already validated above with full session context
            )
            session.output.last_gcode_path = output_path
            return ExportResult(
                ok=True, output_path=output_path,
                warnings=validation.warning_messages,
            )
        except Exception as e:
            return ExportResult(ok=False, error=str(e))


# ================================================================
# 2. Robot Trajectory 导出器
# ================================================================
@register
class RobotTrajectoryExporter(BaseExporter):
    """工业机器人轨迹导出（KUKA KRL / ABB Rapid）。

    重写 run()：复用现有 RobotExportDialog（含配置 + 文件对话框 + 导出）。
    """
    name = "robot"
    display_name = "机器人轨迹"
    icon = "🤖"
    tooltip = "导出 KUKA KRL / ABB Rapid 工业机器人指令文件"
    extension = ".krl"
    filter = "机器人轨迹文件 (*.krl *.mod);;所有文件 (*)"
    requires = ("waypoint.mock",)
    sort_order = 20

    def run(self, parent: Any, session: RepairSession, path_manager: Any) -> ExportResult:
        """完整流程：显示 RobotExportDialog（内部处理配置+文件+导出）。"""
        if not self.is_ready(session):
            return ExportResult(ok=False, error="航点为空，请先完成路径规划")
        try:
            from repair_app.ui.dialogs import RobotExportDialog
            dlg = RobotExportDialog(parent, waypoints=session.waypoint.mock)
            if dlg.exec():
                session.output.last_robot_path = dlg.result_path
                return ExportResult(ok=True, output_path=dlg.result_path)
            return ExportResult(ok=False, error="用户取消")
        except Exception as e:
            return ExportResult(ok=False, error=str(e))

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        """直接导出（程序化调用，不经对话框）。"""
        try:
            from repair_app.export.robot_exporter import RobotExporter, RobotType
            rtype_str = config.get("robot_type", "kuka")
            rtype = RobotType.KUKA if rtype_str == "kuka" else RobotType.ABB
            exporter = RobotExporter(
                robot_type=rtype,
                tcp_speed=config.get("tcp_speed"),
                tool_frame=config.get("tool_frame"),
                base_frame=config.get("base_frame"),
                zone=config.get("zone", "fine"),
            )
            exporter.export(
                session.waypoint.mock,
                output_path=output_path,
                normals=session.point_cloud.normals,
            )
            return ExportResult(ok=True, output_path=output_path)
        except Exception as e:
            return ExportResult(ok=False, error=str(e))


# ================================================================
# 3. PDF Report 导出器
# ================================================================
@register
class PDFReportExporter(BaseExporter):
    """PDF 修复报告导出。

    复用现有 RepairReport，从 session.report 读取字段。
    如果 session.report 为空（未生成报告），自动填充默认值。
    """
    name = "pdf"
    display_name = "PDF 报告"
    icon = "📄"
    tooltip = "生成包含修复参数、对比图和结果摘要的 PDF 报告"
    extension = ".pdf"
    filter = "PDF 文件 (*.pdf);;所有文件 (*)"
    requires = ("morphology.repair_xyz",)
    sort_order = 30

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(path_manager.pdf_path(f"repair_report_{ts}"))

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        try:
            from repair_app.export.report_generator import RepairReport

            report = RepairReport()
            scan_info = session.report.scan_info
            if scan_info:
                report.set_scan_info(**scan_info)
            if session.report.parameters:
                report.set_parameters(session.report.parameters)
            if session.report.results:
                report.set_results(session.report.results)
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
                session.output.last_pdf_path = output_path
                return ExportResult(ok=True, output_path=output_path)
            return ExportResult(ok=False, error="PDF 生成失败（reportlab 可能未安装）")
        except Exception as e:
            return ExportResult(ok=False, error=str(e))


# ================================================================
# 4. CSV 导出器
# ================================================================
@register
class CSVExporter(BaseExporter):
    """CSV 导出：航点表 + 指标摘要。

    格式：
    - Waypoints 区块：x, y, z, layer, velocity
    - Metrics 区块：defect/path/statistics/quality
    """
    name = "csv"
    display_name = "CSV"
    icon = "📊"
    tooltip = "导出航点坐标与修复指标为 CSV 文件（可用 Excel 打开）"
    extension = ".csv"
    filter = "CSV 文件 (*.csv);;所有文件 (*)"
    requires = ("waypoint.mock",)
    sort_order = 40

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(path_manager.exports_dir / f"repair_{ts}.csv")

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        try:
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)

                # ---- 航点表 ----
                writer.writerow(["# Waypoints"])
                writer.writerow(["index", "x_mm", "y_mm", "z_mm", "layer", "velocity"])
                wp = session.waypoint.mock
                layers = session.waypoint.layers
                vel = session.waypoint.velocity_list
                for i in range(len(wp)):
                    layer = int(layers[i]) if layers is not None and i < len(layers) else 0
                    v = vel[i] if vel is not None and i < len(vel) else ""
                    writer.writerow([i, f"{wp[i, 0]:.4f}", f"{wp[i, 1]:.4f}", f"{wp[i, 2]:.4f}", layer, v])
                writer.writerow([])

                # ---- 缺陷指标 ----
                if session.metrics.defect:
                    writer.writerow(["# Defect Metrics"])
                    for k, v in session.metrics.defect.items():
                        writer.writerow([k, v])
                    writer.writerow([])

                # ---- 路径指标 ----
                if session.metrics.path:
                    writer.writerow(["# Path Metrics"])
                    for k, v in session.metrics.path.items():
                        writer.writerow([k, v])
                    writer.writerow([])

                # ---- 统计信息 ----
                if session.metrics.statistics:
                    writer.writerow(["# Statistics"])
                    for k, v in session.metrics.statistics.items():
                        writer.writerow([k, v])
                    writer.writerow([])

                # ---- 质量评估 ----
                if session.metrics.quality:
                    writer.writerow(["# Quality"])
                    for k, v in session.metrics.quality.items():
                        writer.writerow([k, v])
                    writer.writerow([])

                # ---- 逐层数据 ----
                if session.metrics.layers:
                    writer.writerow(["# Layer Data"])
                    writer.writerow(["layer", "points", "avg_height_mm", "mass_g"])
                    for i, layer in enumerate(session.metrics.layers):
                        writer.writerow([
                            i,
                            layer.get("points", 0),
                            layer.get("avg_height", 0.0),
                            layer.get("mass_g", 0.0),
                        ])
                    writer.writerow([])

            session.output.last_csv_path = output_path
            return ExportResult(ok=True, output_path=output_path)
        except Exception as e:
            return ExportResult(ok=False, error=str(e))


# ================================================================
# 5. JSON 导出器
# ================================================================
@register
class JSONExporter(BaseExporter):
    """JSON 导出：完整 Session 快照。

    包含点云/选区/航点/层/形貌/指标/报告等全部数据，ndarray 转为 list。
    """
    name = "json"
    display_name = "JSON"
    icon = "📋"
    tooltip = "导出完整修复会话数据为 JSON 文件（含点云/航点/指标/报告）"
    extension = ".json"
    filter = "JSON 文件 (*.json);;所有文件 (*)"
    requires = ("point_cloud.xyz",)
    sort_order = 50

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(path_manager.exports_dir / f"repair_session_{ts}.json")

    @staticmethod
    def _ndarray_to_list(obj: Any) -> Any:
        """递归转换 ndarray 为 list，保持其他类型不变。"""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, dict):
            return {k: JSONExporter._ndarray_to_list(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [JSONExporter._ndarray_to_list(v) for v in obj]
        return obj

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        try:
            snapshot = {
                "version": "1.0.0",
                "exported_at": datetime.datetime.now().isoformat(),
                "point_cloud": {
                    "xyz": self._ndarray_to_list(session.point_cloud.xyz),
                    "normals": self._ndarray_to_list(session.point_cloud.normals),
                    "path": session.point_cloud.path,
                },
                "selection": {
                    "mask": self._ndarray_to_list(session.selection.mask),
                },
                "waypoint": {
                    "mock": self._ndarray_to_list(session.waypoint.mock),
                    "full": self._ndarray_to_list(session.waypoint.full),
                    "velocity_list": session.waypoint.velocity_list,
                    "layers": self._ndarray_to_list(session.waypoint.layers),
                },
                "morphology": {
                    "repair_xyz": self._ndarray_to_list(session.morphology.repair_xyz),
                    "repair_only_xyz": self._ndarray_to_list(
                        session.morphology.get_repair_points(session.point_cloud.xyz)
                    ),
                    "is_mock": session.morphology.is_mock,
                },
                "metrics": {
                    "defect": self._ndarray_to_list(session.metrics.defect),
                    "path": self._ndarray_to_list(session.metrics.path),
                    "layers": self._ndarray_to_list(session.metrics.layers),
                    "statistics": self._ndarray_to_list(session.metrics.statistics),
                    "quality": self._ndarray_to_list(session.metrics.quality),
                },
                "report": {
                    "scan_info": self._ndarray_to_list(session.report.scan_info),
                    "parameters": self._ndarray_to_list(session.report.parameters),
                    "results": self._ndarray_to_list(session.report.results),
                    "layers": self._ndarray_to_list(session.report.layers),
                    "statistics": self._ndarray_to_list(session.report.statistics),
                    "quality": self._ndarray_to_list(session.report.quality),
                },
            }
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            session.output.last_json_path = output_path
            return ExportResult(ok=True, output_path=output_path)
        except Exception as e:
            return ExportResult(ok=False, error=str(e))


# ================================================================
# 6. Project Save 导出器
# ================================================================
@register
class ProjectSaveExporter(BaseExporter):
    """项目保存：.csam 工程文件（JSON 格式）。

    复用 ProjectManager.save_project，保存会话状态供下次恢复。
    """
    name = "project"
    display_name = "项目保存"
    icon = "💾"
    tooltip = "保存当前修复会话为 .csam 工程文件（含点云路径/参数/选区摘要）"
    extension = ".csam"
    filter = "CSAM 项目 (*.csam);;所有文件 (*)"
    requires = ()  # 项目保存不需要前置数据
    sort_order = 60

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        return str(path_manager.project_path("repair"))

    def get_output_path(
        self,
        session: RepairSession,
        path_manager: Any,
        **config,
    ) -> Optional[str]:
        """项目保存使用目录而非文件对话框（ProjectManager 内部决定路径）。"""
        return None  # 返回 None 跳过文件对话框，export 中用 ProjectManager 决定路径

    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        try:
            from repair_app.software.project_manager import ProjectManager

            path_manager = config.get("path_manager")
            if path_manager is None:
                return ExportResult(ok=False, error="缺少 path_manager")

            pm = ProjectManager(path_manager)
            # 从 session 构建状态字典
            params = session.report.parameters or {}
            sel_summary = {}
            if session.metrics.defect:
                sel_summary = {
                    "point_count": session.metrics.defect.get("point_count", 0),
                    "volume_mm3": session.metrics.defect.get("volume_mm3", 0.0),
                    "area_mm2": session.metrics.defect.get("area_mm2", 0.0),
                }
            state = pm.collect_state(
                point_cloud_path=session.point_cloud.path,
                repair_mode=1 if session.repair_mode == "repairing" else 0,
                material_index=0,
                params=params,
                selection_summary=sel_summary,
            )
            path = pm.save_project(state)
            session.output.last_project_path = str(path)
            return ExportResult(ok=True, output_path=str(path))
        except Exception as e:
            return ExportResult(ok=False, error=str(e))

    def run(self, parent: Any, session: RepairSession, path_manager: Any) -> ExportResult:
        """重写 run：跳过文件对话框，直接用 ProjectManager 决定路径。"""
        if not self.is_ready(session):
            return ExportResult(ok=False, error="数据不完整")

        result = self.export(session, "", path_manager=path_manager)
        if result.ok:
            info(f"[Export:{self.name}] 项目已保存: {result.output_path}")
        else:
            log_error(f"[Export:{self.name}] 保存失败: {result.error}")
        return result
