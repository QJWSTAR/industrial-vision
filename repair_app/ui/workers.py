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

    在后台 QThread 中执行完整流程：
      1. 启动 MATLAB + Bridge（MatlabBridgeLauncher）
      2. 通过 ZMQ 发送修复请求（MATLABPipeline 自动串联路径规划 + 形貌预测）
      3. 返回完整结果 dict

    P3-1: 继承 BaseWorker，统一取消/timeout/cleanup。
    P3-2: ZMQ 阶段添加总超时（默认 600s），防止永久阻塞。

    信号：
        stage   (str)  : 阶段进度提示（如"正在启动 MATLAB..."）
        result  (dict) : 完整计算结果
        failed  (str, str, str) : 结构化错误 (code, friendly, detail)
    """
    stage = Signal(str)
    result = Signal(dict)
    # 结构化错误信号: (error_code, friendly_message, detail)
    failed = Signal(str, str, str)

    def __init__(
        self,
        project_root: str,
        request_bytes: bytes,
        bridge_address: str = "tcp://127.0.0.1:5555",
        startup_timeout: float = 120.0,
        zmq_timeout: float = 600.0,  # P3-2: ZMQ 请求总超时（10 分钟）
    ) -> None:
        super().__init__(timeout_s=None)  # 总超时由各阶段自行管理
        self._project_root = project_root
        self._request_bytes = request_bytes
        self._bridge_address = bridge_address
        self._startup_timeout = startup_timeout
        self._zmq_timeout = zmq_timeout
        self._launcher = None

    @Slot()
    def run(self) -> None:
        self._mark_start()
        try:
            # ---- 阶段 1：启动 MATLAB + Bridge ----
            self.stage.emit("正在启动 MATLAB + Bridge...")
            from repair_app.bridge.launcher import MatlabBridgeLauncher
            self._launcher = MatlabBridgeLauncher(self._project_root)
            if not self._launcher.start(timeout=self._startup_timeout):
                # 启动失败视为 MATLAB 错误（不是异常，但需要结构化提示）
                from repair_app.utils.error_manager import FriendlyMessage
                friendly = ErrorManager.get_friendly_message(
                    RuntimeError("MATLAB 启动失败"), ErrorCode.MATLAB, "MATLAB 启动"
                )
                self.failed.emit(
                    ErrorCode.MATLAB.value,
                    f"{friendly.title}\n\n{friendly.what}",
                    "MATLAB + Bridge 启动失败（详见日志）",
                )
                return

            if self.check_interruption():
                return

            # ---- 阶段 2：通过 ZMQ 发送计算请求（P3-2: 含总超时） ----
            self.stage.emit("正在执行路径规划 + 形貌预测...")
            import zmq
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(self._bridge_address)
            try:
                sock.send(self._request_bytes)
                # 使用 Poller 轮询，每 500ms 检查一次中断请求
                poller = zmq.Poller()
                poller.register(sock, zmq.POLLIN)
                reply = b""
                zmq_start = time.monotonic()
                while not QThread.currentThread().isInterruptionRequested():
                    # P3-2: ZMQ 总超时检查
                    elapsed = time.monotonic() - zmq_start
                    if elapsed > self._zmq_timeout:
                        from repair_app.utils.logger_config import warning
                        warning(f"ZMQ 请求总超时 {self._zmq_timeout}s，放弃等待")
                        self.failed.emit(
                            ErrorCode.NETWORK.value,
                            "MATLAB 计算超时",
                            f"ZMQ 请求超过 {self._zmq_timeout}s 未响应",
                        )
                        return
                    events = dict(poller.poll(500))  # 500ms 超时
                    if sock in events:
                        reply = sock.recv()
                        break
                else:
                    # 被中断
                    return
            finally:
                sock.close(0)

            if self.check_interruption():
                return

            # ---- 阶段 3：解析结果 ----
            self.stage.emit("正在解析 MATLAB 计算结果...")
            from repair_app.communication.repair_serialization import (
                deserialize_result,
                parse_repair_result,
            )
            msg = deserialize_result(reply)
            parsed = parse_repair_result(msg)
            self.result.emit(parsed)

        except Exception as exc:
            code = ErrorManager.classify(exc, context="一键计算")
            self.failed.emit(*_pack_error(exc, code, "一键计算"))
        finally:
            # 不在此关闭 MATLAB，保留会话供后续计算复用
            # MATLAB 在 GUI 退出时由 closeEvent 清理
            pass

    def stop_launcher(self) -> None:
        """供 GUI 在退出时调用，关闭 MATLAB 子进程。"""
        if self._launcher is not None:
            self._launcher.stop()

    def cleanup(self) -> None:
        """P3-1: 统一 cleanup 钩子。"""
        # 不在此关闭 MATLAB（保留会话），仅清理 socket 引用
        pass
