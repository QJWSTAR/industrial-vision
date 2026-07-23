"""
compute_controller.py — 计算控制器

从 MainWindow 中提取 MATLAB 计算编排逻辑，管理：
- MATLAB 启动 (ensure_ready)
- 防重复计算守卫
- 请求构建
- Worker (ComputePipelineWorker) 创建与生命周期
- 进度订阅器管理
- 结果处理 (成功/失败)
- 操作 ID 生成
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from repair_app.service.coordination_service import CoordinationService as _Coord
from repair_app.ui.workers import ComputePipelineWorker
from repair_app.ui.progress_subscriber import ProgressSubscriber
from repair_app.bridge.services.matlab_service import MatlabService
from repair_app.utils.error_manager import ErrorManager, ErrorCode
from repair_app.config import schema_loader

logger = logging.getLogger("csam.ui.compute")

_PROGRESS_ADDRESS = schema_loader.get_network_value("zmq_progress_address")


class ComputeController(QObject):
    """MATLAB 计算编排控制器。

    MainWindow 创建实例，连接信号，调用 start_computation()。

    信号：
        stage_changed           : 阶段进度更新
        result_ready            : 计算结果 (waypoints, metrics, etc.)
        computation_failed      : 计算失败 (error_code, friendly, detail)
        matlab_startup_started  : MATLAB 启动开始
        matlab_startup_done     : MATLAB 启动成功
        matlab_startup_failed   : MATLAB 启动失败 (title, message)
        operation_id_ready      : 操作 ID，用于 ProgressSubscriber 过滤
    """

    stage_changed = Signal(str)
    result_ready = Signal(dict)
    computation_failed = Signal(str, str, str)  # (error_code, friendly, detail)
    matlab_startup_started = Signal()
    matlab_startup_done = Signal()
    matlab_startup_failed = Signal(str, str)  # (title, message)
    operation_id_ready = Signal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        project_root: str = "",
        session=None,
        license_manager=None,
        params_collector: Optional[Callable[[], dict]] = None,
        request_builder: Optional[Callable[..., bytes]] = None,
        selector=None,
        zmq_address: str = "",
        matlab_timeout: float = 600.0,
    ) -> None:
        super().__init__(parent)
        self._project_root = project_root or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self._session = session
        self._license_manager = license_manager
        self._params_collector = params_collector
        self._request_builder = request_builder
        self._selector = selector
        self._zmq_address = zmq_address or _PROGRESS_ADDRESS
        self._matlab_timeout = matlab_timeout

        self._matlab_service: Optional[MatlabService] = None
        self._compute_thread: Optional[QThread] = None
        self._compute_worker: Optional[ComputePipelineWorker] = None
        self._progress_subscriber: Optional[ProgressSubscriber] = None
        self._operation_id: str = ""
        self._busy: bool = False

    # ---- 属性 ----

    @property
    def progress_subscriber(self) -> Optional[ProgressSubscriber]:
        """进度订阅器实例，供 MainWindow 连接 UI 信号。"""
        return self._progress_subscriber

    # ---- 公共 API ----

    def is_busy(self) -> bool:
        """检查是否正在计算。"""
        return self._busy

    def start_computation(self, repair_mode: str = "", mode_additive: str = "",
                          mode_repairing: str = "") -> bool:
        """主入口：开始计算（完整流程，包含 MATLAB 启动）。

        由 MainWindow 在用户点击"开始修复"时调用。

        Args:
            repair_mode: 当前修复模式（用于判断选区策略）
            mode_additive: 增材模式常量值
            mode_repairing: 修复模式常量值

        Returns:
            True 表示计算已启动，False 表示启动被阻止（防重复/校验失败等）。
        """
        # 1. 防重复计算守卫
        if self._busy:
            logger.warning("ComputeController: 计算已在进行中，忽略重复请求")
            return False

        # 2. 许可证校验
        if self._license_manager is not None and not self._license_manager.is_valid:
            logger.warning(
                "ComputeController: License 无效: %s",
                getattr(self._license_manager, "error", "未知"),
            )
            return False

        # 3. 点云数据校验
        if self._session is None:
            logger.error("ComputeController: session 未设置")
            self.computation_failed.emit(
                ErrorCode.UNKNOWN.value,
                "内部错误：会话未初始化",
                "ComputeController.start_computation: session is None",
            )
            return False

        if self._session.point_cloud.xyz is None:
            logger.warning("ComputeController: 点云数据为空")
            return False

        # 4. 获取选区掩码
        if repair_mode == mode_repairing:
            if self._selector is None:
                logger.error("ComputeController: selector 未设置")
                self.computation_failed.emit(
                    ErrorCode.UNKNOWN.value,
                    "内部错误：选区选择器未初始化",
                    "ComputeController.start_computation: selector is None",
                )
                return False
            sel_mask = self._selector.get_selection_mask()
            if not np.any(sel_mask):
                logger.warning("ComputeController: 未选取缺陷区域")
                return False
        else:
            sel_mask = np.ones(len(self._session.point_cloud.xyz), dtype=bool)

        self._session.selection.mask = sel_mask

        # 5. 生成操作 ID
        self._operation_id = str(uuid.uuid4())
        self.operation_id_ready.emit(self._operation_id)

        # 6. 构建修复请求
        try:
            if self._request_builder is not None:
                request_bytes = self._request_builder(
                    self._session, sel_mask, self._operation_id
                )
            else:
                request_bytes = self._build_repair_request_internal(
                    sel_mask, self._operation_id
                )
        except Exception as exc:
            logger.error("ComputeController: 请求构建失败: %s", exc)
            self.computation_failed.emit(
                ErrorCode.UNKNOWN.value,
                f"请求构建失败：{exc}",
                f"ComputeController._build_repair_request: {exc}",
            )
            return False

        # 7. MATLAB 启动开始
        self.matlab_startup_started.emit()
        self._busy = True

        # 8. 确保 MATLAB 就绪
        try:
            self._matlab_service = MatlabService()
            ready = self._matlab_service.ensure_ready(self._project_root)
            if not ready:
                self._busy = False
                self.matlab_startup_failed.emit(
                    "MATLAB 不可用",
                    "软件无法启动 MATLAB 计算服务。",
                )
                return False
        except Exception as exc:
            self._busy = False
            logger.error("ComputeController: MATLAB 启动异常: %s", exc)
            self.matlab_startup_failed.emit(
                "MATLAB 启动异常",
                f"MATLAB 启动过程中发生错误：{exc}",
            )
            return False

        self.matlab_startup_done.emit()

        # 9. 启动进度订阅器
        self._start_progress_subscriber()

        # 10. 创建 Worker 和线程
        self._start_worker(request_bytes)

        return True

    def build_request(
        self,
        session,
        sel_mask: np.ndarray,
        repair_mode: str = "",
        mode_repairing: str = "",
    ) -> Optional[bytes]:
        """构建修复请求（不启动 MATLAB，不创建 Worker）。

        由 MainWindow 在 MATLAB 就绪后调用，将请求构建逻辑从 UI 分离。

        Args:
            session: RepairSession 实例
            sel_mask: 选区掩码
            repair_mode: 当前修复模式
            mode_repairing: 修复模式常量值

        Returns:
            序列化后的 protobuf 字节，失败返回 None
        """
        self._session = session
        self._operation_id = str(uuid.uuid4())
        self.operation_id_ready.emit(self._operation_id)

        try:
            if self._request_builder is not None:
                return self._request_builder(
                    self._session, sel_mask, self._operation_id
                )
            return self._build_repair_request_internal(sel_mask, self._operation_id)
        except Exception as exc:
            logger.error("ComputeController: 请求构建失败: %s", exc)
            self.computation_failed.emit(
                ErrorCode.UNKNOWN.value,
                f"请求构建失败：{exc}",
                f"ComputeController.build_request: {exc}",
            )
            return None

    def execute_computation(
        self,
        request_bytes: bytes,
        matlab_service=None,
    ) -> bool:
        """执行计算（创建 Worker 并启动）。

        由 MainWindow 在 MATLAB 就绪且请求已构建后调用。

        Args:
            request_bytes: 序列化后的 protobuf RepairRequest 字节
            matlab_service: MatlabService 实例（可选，如已创建）

        Returns:
            True 表示 Worker 已启动
        """
        if self._busy:
            logger.warning("ComputeController: 计算已在进行中")
            return False

        if matlab_service is not None:
            self._matlab_service = matlab_service

        self._busy = True
        self._start_progress_subscriber()
        self._start_worker(request_bytes)
        return True

    def cancel_computation(self) -> None:
        """取消正在进行的计算。"""
        if not self._busy:
            return
        logger.info("ComputeController: 取消计算")
        self._stop_progress_subscriber()
        if self._compute_thread is not None and self._compute_thread.isRunning():
            self._compute_thread.requestInterruption()
            self._compute_thread.quit()
            self._compute_thread.wait(5000)
        self._cleanup_worker()
        self._busy = False

    def cleanup(self) -> None:
        """清理资源（停止进度订阅器、清理 Worker）。"""
        logger.info("ComputeController: 清理资源")
        self._stop_progress_subscriber()
        if self._compute_thread is not None and self._compute_thread.isRunning():
            self._compute_thread.requestInterruption()
            self._compute_thread.quit()
            self._compute_thread.wait(5000)
        self._cleanup_worker()
        self._busy = False

    # ---- 内部：请求构建 ----

    def _build_repair_request_internal(
        self, sel_mask: np.ndarray, request_id: str
    ) -> bytes:
        """内部构建修复请求，使用 _Coord.build_repair_request()。

        Args:
            sel_mask: 选区掩码
            request_id: 操作 ID

        Returns:
            序列化后的 protobuf RepairRequest 字节

        Raises:
            ValueError: params_collector 未设置
        """
        if self._params_collector is None:
            raise ValueError("params_collector 未设置，无法构建请求参数")

        params = self._params_collector()
        request_xyz = self._session.point_cloud.xyz[sel_mask]
        request_normals = (
            self._session.point_cloud.normals[sel_mask]
            if self._session.point_cloud.normals is not None
            else _Coord.estimate_normals(request_xyz, k=30)
        )

        material = params.get("material", "")
        scan_id = f"SCAN-{getattr(self._session, 'latest_seed', 0):04d}"

        request = _Coord.build_repair_request(
            request_xyz,
            request_normals,
            scan_id=scan_id,
            request_id=request_id,
            depth_compensation=params.get("depth_compensation", 1.0),
            smooth_threshold=0.5,
            max_layers=params.get("max_layers", 5),
            material=material,
            particle_velocity_ms=params.get("particle_velocity_ms", 500.0),
            critical_velocity_ms=params.get("critical_velocity_ms", 400.0),
            nozzle_diameter_mm=params.get("nozzle_diameter_mm", 6.0),
            spray_angle_deg=params.get("spray_angle_deg", 90.0),
            standoff_distance_mm=params.get("standoff_distance_mm", 30.0),
            particle_size_um=params.get("particle_size_um", 25.0),
            traversing_speed_mms=params.get("traversing_speed_mms", 500.0),
            material_id=material,
            num_layers=params.get("num_layers", 5),
            layer_height_mm=params.get("layer_height_mm", 2.0),
            scanning_angle_deg=params.get("scanning_angle_deg", -45.0),
            scanning_step_mm=params.get("scanning_step_mm", 2.0),
            edge_step_size_mm=params.get("edge_step_size_mm", 2.0),
            tilt_angle_deg=params.get("tilt_angle_deg", 60.0),
            buffer_additive_mm=params.get("buffer_additive_mm", 2.0),
            buffer_repairing_mm=params.get("buffer_repairing_mm", 0.0),
            link_path_free_dist_mm=params.get("link_path_free_dist_mm", 20.0),
            obstacle_resolution_mm=params.get("obstacle_resolution_mm", 2.0),
        )
        return request.SerializeToString()

    # ---- 内部：Worker 管理 ----

    def _start_worker(self, request_bytes: bytes) -> None:
        """创建并启动 ComputePipelineWorker。"""
        # 防御性检查：确保前一个计算线程已完成
        if self._compute_thread is not None and self._compute_thread.isRunning():
            logger.warning("ComputeController: 上一次计算线程仍在运行，强制清理")
            self._compute_thread.requestInterruption()
            self._compute_thread.quit()
            self._compute_thread.wait(5000)

        matlab_service = self._matlab_service
        self._compute_thread = QThread(self)
        self._compute_worker = ComputePipelineWorker(
            matlab_service=matlab_service,
            request_bytes=request_bytes,
            operation_id=self._operation_id,
            zmq_timeout=self._matlab_timeout,
        )
        self._compute_worker.moveToThread(self._compute_thread)

        # 连接 Worker 信号
        self._compute_thread.started.connect(self._compute_worker.run)
        self._compute_worker.stage.connect(self._on_worker_stage)
        self._compute_worker.result.connect(self._on_worker_result)
        self._compute_worker.failed.connect(self._on_worker_failed)
        self._compute_worker.operation_id.connect(self._on_worker_operation_id)
        self._compute_worker.result.connect(self._compute_thread.quit)
        self._compute_worker.failed.connect(self._compute_thread.quit)
        self._compute_thread.finished.connect(self._compute_worker.deleteLater)
        self._compute_thread.finished.connect(self._compute_thread.deleteLater)
        self._compute_thread.finished.connect(self._on_thread_finished)

        self._compute_thread.start()
        logger.info(
            "ComputeController: Worker 已启动 (operation_id=%s)", self._operation_id
        )

    def _cleanup_worker(self) -> None:
        """清理 Worker 和线程引用。"""
        self._compute_thread = None
        self._compute_worker = None

    # ---- 内部：Worker 信号槽 ----

    def _on_worker_stage(self, stage: str) -> None:
        """Worker 阶段进度更新 → 转发给 MainWindow。"""
        self.stage_changed.emit(stage)

    def _on_worker_result(self, result: dict) -> None:
        """Worker 计算成功 → 转发给 MainWindow。"""
        self._busy = False
        self._stop_progress_subscriber()
        self.result_ready.emit(result)

    def _on_worker_failed(self, error_code: str, friendly: str, detail: str) -> None:
        """Worker 计算失败 → 转发给 MainWindow。"""
        self._busy = False
        self._stop_progress_subscriber()
        self.computation_failed.emit(error_code, friendly, detail)

    def _on_worker_operation_id(self, operation_id: str) -> None:
        """Worker 发出 operation_id → 配置 ProgressSubscriber 过滤。"""
        if self._progress_subscriber is not None:
            self._progress_subscriber.set_operation_id(operation_id)
            logger.info(
                "ComputeController: ProgressSubscriber 操作 ID 已设置: %s",
                operation_id,
            )

    def _on_thread_finished(self) -> None:
        """计算线程结束 → 清理引用。"""
        self._cleanup_worker()
        self._stop_progress_subscriber()

    # ---- 内部：进度订阅器管理 ----

    def _start_progress_subscriber(self) -> None:
        """启动实时进度订阅器。"""
        try:
            if self._progress_subscriber is None:
                self._progress_subscriber = ProgressSubscriber(self)
            if not self._progress_subscriber.is_running:
                self._progress_subscriber.start(self._zmq_address)
                logger.info(
                    "ComputeController: 进度订阅器已启动 (ZMQ SUB %s)",
                    self._zmq_address,
                )
        except Exception as exc:
            logger.error("ComputeController: 启动进度订阅器失败: %s", exc)

    def _stop_progress_subscriber(self) -> None:
        """停止实时进度订阅器。"""
        try:
            if self._progress_subscriber is not None and self._progress_subscriber.is_running:
                self._progress_subscriber.stop()
                logger.info("ComputeController: 进度订阅器已停止")
        except Exception as exc:
            logger.error("ComputeController: 停止进度订阅器失败: %s", exc)