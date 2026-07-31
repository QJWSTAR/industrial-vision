"""
workers.py — UI工作线程模块

异常处理重构（任务K）：所有 Worker 的 failed 信号改为传递结构化错误信息：
  failed = Signal(str, str, str)
  - 参数 1: error_code (ErrorCode.value 字符串，如 "matlab" / "network")
  - 参数 2: friendly message（用户可读）
  - 参数 3: detail（技术详情，含 traceback）

主线程在 _on_*_failed 槽中通过 ErrorManager.handle 显示对话框。
"""

from __future__ import annotations
import logging
import os
import time
import traceback
from typing import Any
import numpy as np
from PySide6.QtCore import QObject, QThread, Slot, Signal

from repair_app.core.path_planner import iter_path_from_cloud
from repair_app.core.morphology_predictor import iter_repair_mesh_layers
from repair_app.core.repair_session import RepairSession
from repair_app.utils.error_manager import ErrorCode, ErrorManager
from repair_app.ui.worker_base import BaseWorker

logger = logging.getLogger("csam.ui.workers")


def _validated_cloud_selection(
    session: RepairSession,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a finite point cloud and a non-empty, aligned boolean mask."""
    xyz = np.asarray(session.point_cloud.xyz)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) == 0:
        raise ValueError(f"point cloud must have shape (N, 3), got {xyz.shape}")
    if not np.all(np.isfinite(xyz)):
        raise ValueError("point cloud contains NaN or Inf")
    defect_mask = np.asarray(session.selection.mask)
    if defect_mask.ndim != 1 or len(defect_mask) != len(xyz):
        raise ValueError(
            f"selection mask must have shape ({len(xyz)},), got {defect_mask.shape}"
        )
    defect_mask = defect_mask.astype(bool, copy=False)
    if not np.any(defect_mask):
        raise ValueError("selection mask is empty")
    return xyz, defect_mask


def _pack_error(exc: BaseException, code: ErrorCode = ErrorCode.UNKNOWN,
                context: str = "") -> tuple[str, str, str]:
    """将异常打包为 (code_value, friendly_msg, detail) 三元组。

    friendly_msg: 用户可读消息（含 What + Why + How，不含 traceback）
    detail: 完整 traceback 文本（供技术员排查）
    """
    friendly = ErrorManager.get_friendly_message(exc, code, context)
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # 同时记录日志
    ErrorManager.handle(exc, code, context, show_dialog=False)
    # 完整传递三段式消息：What / Why / How
    parts = [f"{friendly.title}\n\n{friendly.what}"]
    if friendly.why:
        parts.append(f"\n原因：{friendly.why}")
    if friendly.how:
        parts.append(f"\n建议：{friendly.how}")
    return (code.value, "".join(parts), detail)


class PathPlanningWorker(BaseWorker):
    """路径规划工作线程。

    P4-4: 接收 RepairSession 引用，只读 point_cloud.xyz / selection.mask，
    禁止 .copy()（数据只在 Session 中存储一份）。计算期间主线程保证不修改这两项。
    """
    partial = Signal(object, int, int)
    finished = Signal(object)
    # 结构化错误信号: (error_code, friendly_message, detail)
    failed = Signal(str, str, str)

    def __init__(
        self,
        session: RepairSession,
        params: dict,
        n_layers: int,
        buffer_mm: float,
        timeout_s: float | None = 300.0,  # P3-1: 5 分钟总超时
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self._session = session  # P4-4: 共享 Session，只读不写
        self._params = params
        self._n_layers = n_layers
        self._buffer_mm = buffer_mm

    @Slot()
    def run(self) -> None:
        self._mark_start()  # P3-1: 启动计时
        try:
            xyz, defect_mask = _validated_cloud_selection(self._session)
            if self._n_layers <= 0:
                raise ValueError("n_layers must be positive")
            last_waypoints = np.zeros((0, 3))
            for layer_idx, waypoints in enumerate(
                iter_path_from_cloud(
                    xyz=xyz,
                    defect_mask=defect_mask,
                    layer_height=self._params.get("layer_height_mm", 2.0),
                    scanning_angle=self._params.get("scanning_angle_deg", -45.0),
                    scanning_step=self._params.get("scanning_step_mm", 2.0),
                    buffer_mm=self._buffer_mm,
                    n_layers=self._n_layers,
                ),
                start=1,
            ):
                if self.check_interruption():  # P3-1: 统一中断+超时检查
                    return
                last_waypoints = waypoints
                self.partial.emit(waypoints, layer_idx, self._n_layers)
            self.finished.emit(last_waypoints)
        except Exception as exc:
            code = ErrorManager.classify(exc, context="路径规划")
            self.failed.emit(*_pack_error(exc, code, "路径规划"))


class MorphologyWorker(BaseWorker):
    """形貌预测工作线程。

    P4-4: 接收 RepairSession 引用，只读 point_cloud.xyz / selection.mask / waypoint.mock，
    禁止 .copy()（数据只在 Session 中存储一份）。
    """
    partial = Signal(object, int, int)
    finished = Signal(object, bool)  # P2-3: (repair_pts, is_mock)
    # 结构化错误信号: (error_code, friendly_message, detail, repair_data)
    failed = Signal(str, str, str, object)

    def __init__(
        self,
        session: RepairSession,
        params: dict,
        n_layers: int,
        seed: int,
        timeout_s: float | None = 600.0,  # P3-1: 10 分钟总超时
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self._session = session  # P4-4: 共享 Session，只读不写
        self._params = params
        self._n_layers = n_layers
        self._seed = seed

    @Slot()
    def run(self) -> None:
        self._mark_start()  # P3-1: 启动计时
        repair = np.zeros((0, 3))
        is_mock = True  # P2-3: 默认标记为 mock，仅当真实算法成功输出才置 False
        try:
            xyz, defect_mask = _validated_cloud_selection(self._session)
            waypoints = np.asarray(self._session.waypoint.mock)
            if waypoints.ndim != 2 or waypoints.shape[1] < 3 or len(waypoints) == 0:
                raise ValueError(
                    f"waypoints must have shape (M, 3+), got {waypoints.shape}"
                )
            if not np.all(np.isfinite(waypoints[:, :3])):
                raise ValueError("waypoints contain NaN or Inf")
            if self._n_layers <= 0:
                raise ValueError("n_layers must be positive")
            # P2-3: mock 兜底数据（明确标记，仅用于算法失败时的 fallback）
            base = xyz[defect_mask]
            n_pts = min(int(np.sum(defect_mask) * 0.4), 5000)
            rng = np.random.default_rng(self._seed + 1)
            z_base = np.max(base[:, 2])
            repair = np.column_stack([
                rng.uniform(np.min(base[:, :2], axis=0), np.max(base[:, :2], axis=0), (n_pts, 2)),
                z_base + np.abs(rng.normal(0, 0.3, n_pts)),
            ])

            base_pts = np.vstack([xyz, repair])
            combined_mask = np.concatenate([defect_mask, np.ones(len(repair), dtype=bool)])
            last_pts = base_pts
            for layer_idx, full_pts in enumerate(
                iter_repair_mesh_layers(
                    base_pts=base_pts,
                    defect_mask=combined_mask,
                    waypoints=waypoints,
                    particle_velocity_ms=self._params.get("particle_velocity_ms", 500),
                    critical_velocity_ms=self._params.get("critical_velocity_ms", 400),
                    nozzle_diameter_mm=self._params.get("nozzle_diameter_mm", 6),
                    n_layers=self._n_layers,
                ),
                start=1,
            ):
                if self.check_interruption():  # P3-1: 统一中断+超时检查
                    return
                last_pts = full_pts
                repair_only = full_pts[len(xyz):] if len(full_pts) > len(xyz) else repair
                self.partial.emit(repair_only, layer_idx, self._n_layers)

            # P2-3: 真实算法成功输出 → 标记为非 mock
            repair_only = last_pts[len(xyz):] if len(last_pts) > len(xyz) else repair
            is_mock = len(repair_only) == 0  # 空输出仍视为 mock
            self.finished.emit(repair_only, is_mock)
        except Exception as exc:
            code = ErrorManager.classify(exc, context="形貌预测")
            code_val, friendly, detail = _pack_error(exc, code, "形貌预测")
            # P2-3: 失败时传递 mock 标记的兜底数据
            self.failed.emit(code_val, friendly, detail, repair)


class ComputePipelineWorker(BaseWorker):
    """一键计算管线工作线程。

    在后台 QThread 中通过 MatlabService 调用 MATLAB 完整管线。
    不再直接操作 ZMQ / Launcher / protobuf。

    信号：
        stage        (str)  : 阶段进度提示
        result       (dict) : 完整计算结果
        failed       (str, str, str) : 结构化错误 (code, friendly, detail)
        operation_id (str)  : 当前计算操作 ID（UUID），用于 Progress 过滤
    """
    stage = Signal(str)
    result = Signal(dict)
    # 结构化错误信号: (error_code, friendly_message, detail)
    failed = Signal(str, str, str)
    operation_id = Signal(str)

    def __init__(
        self,
        matlab_service,  # MatlabService 实例
        request_bytes: bytes,
        operation_id: str = "",
        zmq_timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout_s=None)
        self._matlab_service = matlab_service
        self._request_bytes = request_bytes
        self._operation_id = operation_id
        self._zmq_timeout = zmq_timeout

    @Slot()
    def run(self) -> None:
        self._mark_start()
        # 发出 operation_id，让 MainWindow 配置 ProgressSubscriber 过滤
        if self._operation_id:
            self.operation_id.emit(self._operation_id)
        try:
            self.stage.emit("正在执行路径规划 + 形貌预测...")

            # P0-12: 把 QThread 的中断标志透传到 ZMQ poll 循环，
            # 600s 长计算期间点取消能立即中断并抛 MatlabCallCancelledError。
            # BaseWorker 是 QObject（非 QThread），通过 currentThread() 获取
            # 实际承载线程来查询中断标志（与 check_interruption 内部一致）。
            from PySide6.QtCore import QThread

            def _is_cancelled() -> bool:
                t = QThread.currentThread()
                return t is not None and t.isInterruptionRequested()

            parsed = self._matlab_service.run_full_pipeline_blocking(
                self._request_bytes,
                timeout_s=self._zmq_timeout,
                is_cancelled=_is_cancelled,
            )

            if self.check_interruption():
                return

            self.stage.emit("正在解析 MATLAB 计算结果...")
            self.result.emit(parsed)

        except Exception as exc:
            # P0-12: 用户取消走 cancelled 语义而非 failed，避免弹出错误对话框
            from repair_app.bridge.communication.exceptions import (
                MatlabCallCancelledError,
            )
            if isinstance(exc, MatlabCallCancelledError):
                # 发出结构化取消信息，由 _on_compute_cancelled 处理
                logger.info("ComputePipelineWorker: 计算被用户取消")
                # 复用 failed 信号传递取消标记（error_code="CANCELLED"），
                # MainWindow._on_compute_failed 据此走取消路径
                self.failed.emit("CANCELLED", "计算已取消", str(exc))
                return
            code = ErrorManager.classify(exc, context="一键计算")
            self.failed.emit(*_pack_error(exc, code, "一键计算"))


class PointCloudLoadWorker(BaseWorker):
    """点云加载工作线程（P0-1/P0-4）。

    在后台线程执行文件读取 + 法向量估计，避免大文件阻塞 UI。
    纯数据操作，无 UI 交互，线程安全。
    """
    progress = Signal(str)
    finished = Signal(object, object, str)  # xyz, normals, file_path
    failed = Signal(str, str, str)

    def __init__(
        self,
        file_path: str,
        file_service: Any,
        timeout_s: float | None = 120.0,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self._file_path = file_path
        self._file_service = file_service

    @Slot()
    def run(self) -> None:
        self._mark_start()
        try:
            self.progress.emit("正在加载点云文件...")
            xyz, normals = self._file_service.load_point_cloud(self._file_path)
            if self.check_interruption():
                return
            if normals is None:
                self.progress.emit("正在估计法向量...")
                from repair_app.core.coordination_system import CoordinateSystem
                normals = CoordinateSystem.estimate_normals(xyz, k=30)
            if self.check_interruption():
                return
            self.finished.emit(xyz, normals, self._file_path)
        except Exception as exc:
            code = ErrorManager.classify(exc, context="加载点云")
            self.failed.emit(*_pack_error(exc, code, "加载点云"))


class ExportWorker(BaseWorker):
    """导出工作线程（P0-2）。

    在后台线程执行实际导出操作（export），避免 PDF/G-code 生成阻塞 UI。
    UI 交互（配置对话框、文件对话框）在主线程完成后再启动此 Worker。
    """
    finished = Signal(object)  # ExportResult
    failed = Signal(str, str, str)

    def __init__(
        self,
        exporter: Any,
        session: RepairSession,
        output_path: str,
        config: dict,
        timeout_s: float | None = 180.0,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self._exporter = exporter
        self._session = session
        self._output_path = output_path
        self._config = config

    @Slot()
    def run(self) -> None:
        self._mark_start()
        try:
            result = self._exporter.export(
                self._session, self._output_path, **self._config
            )
            if self.check_interruption():
                return
            self.finished.emit(result)
        except Exception as exc:
            code = ErrorManager.classify(exc, context="导出")
            self.failed.emit(*_pack_error(exc, code, "导出"))


class ReportWorker(BaseWorker):
    """报告生成工作线程（P0-3）。

    在后台线程执行指标计算 + PDF 生成，避免 matplotlib 渲染阻塞 UI。
    所有计算数据在主线程预收集，Worker 只做计算和文件写入。
    """
    progress = Signal(str)
    finished = Signal(str)  # output_path
    failed = Signal(str, str, str)

    def __init__(
        self,
        report_data: dict,
        export_service: Any,
        session: RepairSession,
        output_path: str,
        timeout_s: float | None = 120.0,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self._report_data = report_data
        self._export_service = export_service
        self._session = session
        self._output_path = output_path

    @Slot()
    def run(self) -> None:
        self._mark_start()
        try:
            self.progress.emit("正在计算统计指标...")
            # 将预收集的数据写入 session
            self._session.report.scan_info = self._report_data["scan_info"]
            self._session.report.parameters = self._report_data["parameters"]
            self._session.report.results = self._report_data["results"]
            self._session.report.layers = self._report_data["layers"]
            self._session.report.statistics = self._report_data["statistics"]
            self._session.report.quality = self._report_data["quality"]
            self._session.metrics.defect = self._report_data["defect_metrics"]
            self._session.metrics.path = self._report_data["path_metrics"]
            self._session.metrics.layers = self._report_data["layers"]
            self._session.metrics.statistics = self._report_data["statistics"]
            self._session.metrics.quality = self._report_data["quality"]
            if self.check_interruption():
                return
            self.progress.emit("正在生成 PDF 报告...")
            ok = self._export_service.export_pdf_report(
                self._session, output_path=self._output_path
            )
            if self.check_interruption():
                return
            if ok:
                self.finished.emit(self._output_path)
            else:
                from repair_app.utils.error_manager import ErrorCode
                raise RuntimeError("PDF 报告生成失败")
        except Exception as exc:
            code = ErrorManager.classify(exc, context="报告生成")
            self.failed.emit(*_pack_error(exc, code, "报告生成"))
