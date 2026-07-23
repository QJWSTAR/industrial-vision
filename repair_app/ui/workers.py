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
import os
import time
import traceback
import numpy as np
from PySide6.QtCore import QObject, QThread, Slot, Signal

from repair_app.core.path_planner import iter_path_from_cloud
from repair_app.core.morphology_predictor import iter_repair_mesh_layers
from repair_app.core.repair_session import RepairSession
from repair_app.utils.error_manager import ErrorCode, ErrorManager
from repair_app.ui.worker_base import BaseWorker


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
            xyz = self._session.point_cloud.xyz
            defect_mask = self._session.selection.mask
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
            xyz = self._session.point_cloud.xyz
            defect_mask = self._session.selection.mask
            waypoints = self._session.waypoint.mock
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

            parsed = self._matlab_service.run_full_pipeline_blocking(
                self._request_bytes, timeout_s=self._zmq_timeout
            )

            if self.check_interruption():
                return

            self.stage.emit("正在解析 MATLAB 计算结果...")
            self.result.emit(parsed)

        except Exception as exc:
            code = ErrorManager.classify(exc, context="一键计算")
            self.failed.emit(*_pack_error(exc, code, "一键计算"))
