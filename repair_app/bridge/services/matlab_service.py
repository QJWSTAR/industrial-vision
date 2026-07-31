"""bridge.services.matlab_service — MATLAB 服务门面（任务7）

业务层通过此服务与 MATLAB 交互，永不直接接触通信层。
职责：
- 连接管理
- 请求构建
- 结果解析
- 异常翻译为业务可读结果
- 心跳监控
- 日志记录（任务10）
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from repair_app.communication.repair_protocol_pb2 import (
    RepairRequest,
    RepairResult,
    RepairStatusCode,
)
from ..communication import (
    BridgeClient,
    BridgeConfig,
    BridgeError,
    BridgeConnectionError,
    DEFAULT_CONFIG,
    EngineStatus,
    Serializer,
    generate_request_id,
)
from ..communication.protocol import is_status_success, STATUS_CODE_NAMES

logger = logging.getLogger("csam.bridge.service")


@dataclass
class RepairOutcome:
    """修复结果（业务层数据结构，不暴露 Protobuf）。"""
    success: bool
    waypoints: np.ndarray          # (N, 7) 或 (0,)
    request_id: str
    status_name: str
    estimated_time_s: float
    compute_time_ms: int
    uniformity_score: float
    is_feasible: bool
    feasibility_reason: str
    error_message: str = ""

    @classmethod
    def from_result(cls, result: RepairResult) -> "RepairOutcome":
        parsed = Serializer.parse_repair_result(result)
        return cls(
            success=is_status_success(result.status_code),
            waypoints=parsed.get("waypoints", np.zeros((0, 7), dtype=np.float32)),
            request_id=result.request_id,
            status_name=STATUS_CODE_NAMES.get(result.status_code, "UNKNOWN"),
            estimated_time_s=result.estimated_time_s,
            compute_time_ms=result.compute_time_ms,
            uniformity_score=result.uniformity_score,
            is_feasible=result.is_feasible,
            feasibility_reason=result.feasibility_reason,
            error_message=result.error_message,
        )

    @classmethod
    def error(cls, message: str, request_id: str = "") -> "RepairOutcome":
        return cls(
            success=False,
            waypoints=np.zeros((0, 7), dtype=np.float32),
            request_id=request_id,
            status_name="ERROR",
            estimated_time_s=0.0,
            compute_time_ms=0,
            uniformity_score=0.0,
            is_feasible=False,
            feasibility_reason=message,
            error_message=message,
        )


class MatlabService:
    """MATLAB 服务门面：业务层唯一的 MATLAB 交互入口。

    用法：
        service = MatlabService()
        service.start_heartbeat()
        service.request_path_planning(xyz, normals, params, on_success, on_error)
        service.close()
    """

    def __init__(
        self,
        config: Optional[BridgeConfig] = None,
        client: Optional[BridgeClient] = None,
    ) -> None:
        self._config = config or DEFAULT_CONFIG
        self._client = client or BridgeClient(self._config)
        self._latency_log_threshold = self._config.log_latency_threshold_ms

    # ---- 属性 ----
    @property
    def config(self) -> BridgeConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def address(self) -> str:
        return self._client.address

    @property
    def message(self) -> str:
        """获取 LifecycleManager 的当前状态消息。"""
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        try:
            manager = MatlabLifecycleManager.get_instance()
            return manager.message
        except Exception:
            return ""

    # ---- 健康检查 ----
    def check_health(self, on_health: Callable[[bool, str], None]) -> None:
        """检查引擎健康状态。"""
        logger.debug("发起健康检查 -> %s", self.address)
        self._client.check_health(on_health)

    def start_heartbeat(self) -> None:
        """启动后台心跳。"""
        self._client.start_heartbeat()
        logger.info("心跳监控已启动 (间隔=%dms)", self._config.heartbeat_interval_ms)

    def stop_heartbeat(self) -> None:
        self._client.stop_heartbeat()

    # ---- 生命周期管理 ----
    def ensure_ready(self, project_root: str = None) -> bool:
        """确保 MATLAB + Bridge 服务就绪。

        Args:
            project_root: 项目根目录（用于查找 matlab_bridge_server.m）

        Returns:
            True if MATLAB is ready for computation
        """
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager

        if project_root is None:
            import os
            project_root = os.environ.get("CSAM_PROJECT_ROOT", "")

        if not project_root:
            logger.error("project_root 为空，无法定位 matlab_bridge_server.m")
            return False

        manager = MatlabLifecycleManager.get_instance(project_root)
        return manager.ensure_ready()

    def health_check(self) -> dict:
        """执行 MATLAB 服务健康检查。"""
        try:
            if not self._client.is_connected:
                return {"status": "unhealthy", "error": "Bridge 未连接"}
            from repair_app.communication.repair_protocol_pb2 import EngineStatus
            return {"status": "healthy", "engine": "connected"}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}

    def shutdown(self) -> None:
        """关闭 MATLAB 服务（停止 Bridge + MATLAB 进程）。"""
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        try:
            manager = MatlabLifecycleManager.get_instance()
            manager.stop()
        except Exception as exc:
            logger.warning("MatlabService shutdown 异常: %s", exc)
        self.close()

    # ---- 路径规划请求 ----
    def request_path_planning(
        self,
        xyz: np.ndarray,
        normals: np.ndarray,
        params: dict[str, Any],
        on_success: Callable[[RepairOutcome], None],
        on_error: Optional[Callable[[str], None]] = None,
        scan_id: str = "BRIDGE",
    ) -> str:
        """请求路径规划（异步）。

        Args:
            xyz: (N, 3) 点云坐标
            normals: (N, 3) 法向量
            params: 工艺参数字典（与 _collect_params 格式一致）
            on_success: 成功回调，接收 RepairOutcome
            on_error: 错误回调，接收错误消息字符串
            scan_id: 扫描标识

        Returns:
            request_id
        """
        request_id = generate_request_id("path")
        started = time.time()

        # 参数校验
        if xyz is None or len(xyz) == 0:
            if on_error:
                on_error("点云为空")
            return request_id
        if normals is None or normals.shape != xyz.shape:
            if on_error:
                on_error("法向量与点云形状不匹配")
            return request_id

        try:
            request = Serializer.build_repair_request(
                xyz, normals, scan_id=scan_id,
                request_id=request_id,
                material=params.get("material", "STEEL_316L"),
                depth_compensation=params.get("depth_compensation", 1.0),
                max_layers=params.get("max_layers", 5),
                particle_velocity_ms=params.get("particle_velocity_ms", 700.0),
                critical_velocity_ms=params.get("critical_velocity_ms", 400.0),
                nozzle_diameter_mm=params.get("nozzle_diameter_mm", 6.0),
                spray_angle_deg=params.get("spray_angle_deg", 90.0),
                standoff_distance_mm=params.get("standoff_distance_mm", 30.0),
                particle_size_um=params.get("particle_size_um", 25.0),
                traversing_speed_mms=params.get("traversing_speed_mms", 500.0),
                num_layers=params.get("num_layers", 5),
                layer_height_mm=params.get("layer_height_mm", 2.0),
                scanning_angle_deg=params.get("scanning_angle_deg", -45.0),
                scanning_step_mm=params.get("scanning_step_mm", 2.0),
                edge_step_size_mm=params.get("edge_step_size_mm", 1.5),
                tilt_angle_deg=params.get("tilt_angle_deg", 0.0),
                buffer_additive_mm=params.get("buffer_additive_mm", 2.0),
                buffer_repairing_mm=params.get("buffer_repairing_mm", 0.0),
                link_path_free_dist_mm=params.get("link_path_free_dist_mm", 10.0),
                obstacle_resolution_mm=params.get("obstacle_resolution_mm", 1.0),
            )
        except BridgeError as exc:
            logger.error("构建请求失败 [%s]: %s", request_id, exc)
            if on_error:
                on_error(str(exc))
            return request_id

        def _on_result(result: RepairResult) -> None:
            elapsed_ms = int((time.time() - started) * 1000)
            outcome = RepairOutcome.from_result(result)
            if elapsed_ms > self._latency_log_threshold:
                logger.warning(
                    "路径规划延迟高 [%s]: %dms (阈值=%dms)",
                    request_id, elapsed_ms, self._latency_log_threshold,
                )
            else:
                logger.info(
                    "路径规划完成 [%s]: %s, %d 航点, %dms",
                    request_id, outcome.status_name,
                    len(outcome.waypoints), elapsed_ms,
                )
            on_success(outcome)

        def _on_error(err: BridgeError) -> None:
            logger.error("路径规划失败 [%s]: %s", request_id, err)
            if on_error:
                on_error(str(err))

        logger.info("发起路径规划 [%s]: %d 点 -> %s", request_id, len(xyz), self.address)
        return self._client.request_repair(request, _on_result, _on_error)

    # ---- 完整管线计算（阻塞，任务7 Phase 1） ----
    def run_full_pipeline_blocking(
        self,
        request_bytes: bytes,
        timeout_s: float = 600.0,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """阻塞执行完整计算管线（路径规划 + 形貌预测）。

        自动管理 MATLAB 生命周期状态（BUSY → READY/RECOVERING）。

        Args:
            request_bytes: 序列化后的 protobuf RepairRequest 字节
            timeout_s: 超时（秒），默认 600s
            is_cancelled: 可选取消检查回调（P0-12）。在 ZMQ poll 循环中周期调用，
                返回 True 时抛出 MatlabCallCancelledError，让长计算期间取消按钮生效。

        Returns:
            解析后的结果 dict（与旧版 parse_repair_result 格式一致）

        Raises:
            BridgeError: 通信失败
            MatlabCallCancelledError: 用户取消
            RuntimeError: 结果解析失败
        """
        import time as _time
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        from repair_app.communication.repair_serialization import (
            deserialize_result,
            parse_repair_result,
        )

        started = _time.time()
        logger.info("发起完整管线计算 -> %s", self.address)

        manager = MatlabLifecycleManager.get_instance()
        with manager.execution_scope():
            try:
                reply_bytes = self._client.request_blocking(
                    request_bytes,
                    timeout_ms=int(timeout_s * 1000),
                    is_cancelled=is_cancelled,
                )
            except BridgeError as exc:
                logger.error("完整管线计算通信失败: %s", exc)
                raise

            elapsed_ms = int((_time.time() - started) * 1000)

            try:
                msg = deserialize_result(reply_bytes)
                parsed = parse_repair_result(msg)
            except Exception as exc:
                logger.error("完整管线计算解析失败: %s", exc)
                raise RuntimeError(f"MATLAB 结果解析失败: {exc}") from exc

            if elapsed_ms > self._latency_log_threshold:
                logger.warning(
                    "完整管线计算延迟高: %dms (阈值=%dms)",
                    elapsed_ms, self._latency_log_threshold
                )
            else:
                logger.info(
                    "完整管线计算完成: %s, %d 航点, %dms",
                    parsed.get("status_name", "UNKNOWN"),
                    len(parsed.get("waypoints", [])),
                    elapsed_ms,
                )

            return parsed

    # ---- 清理 ----
    def abort_active_request(self) -> None:
        """Abort the client-side wait without claiming MATLAB was cancelled."""
        self._client.close(wait_ms=1000)

    def close(self, wait_ms: int = 4000) -> None:
        """停止服务并清理资源。"""
        self.stop_heartbeat()
        self._client.close(wait_ms)
        logger.info("MatlabService 已关闭")
