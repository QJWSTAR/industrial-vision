"""bridge.adapters.matlab_adapter — MATLAB 适配器（任务6）

将 MATLAB 算法执行适配到 BridgeServer 接口。
支持两种模式：
1. 原生 MATLAB 模式（默认）：通过 matlab.engine 调用 MATLAB .m 算法
2. Python 桥接模式（降级）：MATLAB 不可用时回退到 Python 原型算法

设计要点：
- 业务层永不直接调用 MATLAB
- 所有 MATLAB 交互封装于此
- 算法异常翻译为结构化错误
- 自动降级保证生产连续性
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

import numpy as np

from repair_app.communication.repair_protocol_pb2 import (
    RepairRequest,
    RepairResult,
    RepairStatusCode,
)
from repair_app.communication.repair_serialization import (
    build_layer_profile,
    build_particle_distribution,
)
from ..communication.config import BridgeConfig
from ..communication.serializer import Serializer
from ..communication.zmq_server import BridgeServer

logger = logging.getLogger("csam.bridge.matlab")


class MatlabAlgorithmError(Exception):
    """MATLAB 算法执行错误。"""


class MatlabAdapter(BridgeServer):
    """MATLAB 算法适配器：将修复请求路由到 MATLAB 算法。

    模式 1（默认）：原生 MATLAB —— 通过 matlab.engine 调用 .m 算法
    模式 2（降级）：Python 桥接 —— 调用 repair_app.core 原型算法
    """

    SERVICE_VERSION = "matlab-adapter-2.0.0"

    def __init__(
        self,
        address: Optional[str] = None,
        config: Optional[BridgeConfig] = None,
        algorithm_fn: Optional[Callable[..., np.ndarray]] = None,
    ) -> None:
        super().__init__(address, config)
        if algorithm_fn is not None:
            self._algorithm_fn = algorithm_fn
        else:
            self._algorithm_fn = self._select_algorithm()

    def handle_repair(self, request: RepairRequest) -> RepairResult:
        """处理修复请求：解析 → 调用算法 → 构建结果（含可视化字段）。"""
        started = time.time()
        request_id = request.request_id

        try:
            xyz, _normals, meta = Serializer.parse_point_cloud(request)

            if len(xyz) == 0:
                return self._build_error_result(
                    request_id, RepairStatusCode.ERR_INVALID_INPUT,
                    "空点云请求", "输入点云为空",
                )

            # 调用算法（MATLAB 作为计算引擎，返回航点+法向量+层号）
            waypoints = self._invoke_algorithm(xyz, meta)

            if len(waypoints) == 0:
                return self._build_error_result(
                    request_id, RepairStatusCode.ERR_NO_DEFECT_FOUND,
                    "未生成航点", "路径规划输出为空",
                )

            elapsed_ms = int((time.time() - started) * 1000)
            path_length = self._compute_path_length(waypoints)
            speed = max(float(meta.get("traversing_speed_mms", 500.0)), 1e-6)
            estimated_time_s = path_length / speed

            # ---- 可视化数据：由计算结果派生，GUI 原生渲染 ----
            density_gcm3 = self._material_density_gcm3(meta)
            volume_mm3 = self._estimate_volume_mm3(waypoints, meta)
            mass_g = volume_mm3 * density_gcm3 * 1e-3  # mm3*g/cm3 -> g
            uniformity = self._compute_uniformity(waypoints)
            layer_profiles = self._build_layer_profiles(waypoints, meta)
            particle_dist = self._build_particle_distribution(meta)

            return Serializer.build_repair_result(
                waypoints,
                request_id=request_id,
                status_code=RepairStatusCode.SUCCESS,
                predicted_volume_mm3=volume_mm3,
                material_density_gcm3=density_gcm3,
                estimated_mass_g=mass_g,
                estimated_time_s=estimated_time_s,
                compute_time_ms=elapsed_ms,
                uniformity_score=uniformity,
                is_feasible=True,
                feasibility_reason="MATLAB adapter path generated",
                layer_profiles=layer_profiles,
                particle_dist=particle_dist,
            )

        except MatlabAlgorithmError as exc:
            logger.exception("MATLAB 算法失败: %s", exc)
            return self._build_error_result(
                request_id, RepairStatusCode.ERR_ALGORITHM_FAIL,
                str(exc), str(exc),
            )
        except Exception as exc:
            logger.exception("未预期错误")
            return self._build_error_result(
                request_id, RepairStatusCode.ERR_UNKNOWN,
                str(exc), str(exc),
            )

    # ====== 可视化数据派生 ======

    @staticmethod
    def _material_density_gcm3(meta: dict[str, Any]) -> float:
        """从 meta 中的材料标识查密度 (g/cm3)，失败回退 7.99 (钢)。"""
        material = str(meta.get("material", "")).upper()
        # 常见冷喷涂材料密度 (g/cm3)
        densities = {
            "STEEL_316L": 7.99, "STEEL_316": 7.99, "CU": 8.96, "COPPER": 8.96,
            "AL6061": 2.70, "AL": 2.70, "ALUMINUM": 2.70,
            "TI64": 4.43, "TI": 4.51, "TITANIUM": 4.51,
            "NI": 8.90, "NICKEL": 8.90, "WC_CO": 14.90,
        }
        for key, val in densities.items():
            if key in material:
                return float(val)
        return 7.99

    @staticmethod
    def _estimate_volume_mm3(waypoints: np.ndarray, meta: dict[str, Any]) -> float:
        """由航点路径长度 × 单道截面积估算填充体积 (mm3)。"""
        if len(waypoints) < 2:
            return 0.0
        path_len = float(np.sum(
            np.linalg.norm(np.diff(waypoints[:, :3], axis=0), axis=1)
        ))
        # 单道截面积 ≈ (道宽) × (单层厚度)；道宽≈喷嘴直径×搭接系数
        nozzle_d = float(meta.get("nozzle_diameter_mm", 3.0)) or 3.0
        overlap = float(meta.get("track_overlap_ratio", 0.5)) or 0.5
        track_width = nozzle_d * (1.0 - overlap)
        layer_h = float(meta.get("layer_height_mm", 0.3)) or 0.3
        cross_section = max(track_width * layer_h, 1e-6)
        return path_len * cross_section

    @staticmethod
    def _compute_uniformity(waypoints: np.ndarray) -> float:
        """由每层 Z 高度变异系数派生均匀性评分 ∈ [0,1]。

        层间 Z 标准差越小 → 均匀性越高。
        """
        if len(waypoints) < 8:
            return 0.78
        layers_col = waypoints[:, 7].astype(int) if waypoints.shape[1] >= 8 else np.zeros(len(waypoints), dtype=int)
        z = waypoints[:, 2]
        means = []
        for li in np.unique(layers_col):
            mask = layers_col == li
            if np.sum(mask) >= 2:
                means.append(float(np.mean(z[mask])))
        if len(means) < 2:
            return 0.78
        m = float(np.mean(means))
        std = float(np.std(means))
        if m < 1e-6:
            return 0.78
        cv = std / m  # 变异系数
        # cv=0 → 1.0；cv>=0.3 → 0.5
        score = float(np.clip(1.0 - cv / 0.6, 0.5, 1.0))
        return score

    @staticmethod
    def _build_layer_profiles(
        waypoints: np.ndarray, meta: dict[str, Any]
    ) -> list:
        """按层号聚合航点，生成逐层沉积轮廓（标量指标，供 GUI 原生动画/面板）。"""
        if len(waypoints) == 0:
            return []
        layers_col = (
            waypoints[:, 7].astype(int)
            if waypoints.shape[1] >= 8
            else np.zeros(len(waypoints), dtype=int)
        )
        z = waypoints[:, 2]
        dep_eff_base = float(meta.get("max_deposition_efficiency", 0.7)) or 0.7
        profiles = []
        for li in sorted(np.unique(layers_col).tolist()):
            mask = layers_col == li
            if not np.any(mask):
                continue
            z_layer = z[mask]
            z_min = float(np.min(z_layer))
            z_max = float(np.max(z_layer))
            # 该层沉积高度 ≈ 层内 Z 极差（相对层底）
            max_h = max(z_max - z_min, 0.0)
            avg_h = max(float(np.mean(z_layer) - z_min), 0.0)
            # 逐层沉积效率轻微衰减（工程经验模型）
            dep_eff = max(dep_eff_base * (1.0 - 0.02 * int(li)), 0.3)
            profiles.append(
                build_layer_profile(
                    int(li),
                    max_height_mm=max_h,
                    avg_height_mm=avg_h,
                    dep_efficiency=dep_eff,
                )
            )
        return profiles

    @staticmethod
    def _build_particle_distribution(meta: dict[str, Any]):
        """由工艺参数合成代表性颗粒分布（CFD 查表的工程近似）。

        返回 ParticleDistribution，供 GUI 可选可视化。基于：
        - particle_velocity_ms / critical_velocity_ms → vcr 判定
        - particle_size_um → 粒径分布
        - spray_angle_deg / nozzle_diameter_mm → 位置散布
        """
        v_p = float(meta.get("particle_velocity_ms", 500.0)) or 500.0
        v_cr = float(meta.get("critical_velocity_ms", 300.0)) or 300.0
        d_um = float(meta.get("particle_size_um", 25.0)) or 25.0
        nozzle_d = float(meta.get("nozzle_diameter_mm", 3.0)) or 3.0
        angle = float(meta.get("spray_angle_deg", 10.0)) or 10.0
        rng = np.random.default_rng(42)
        n = 256
        # 位置：喷嘴直径范围内的散布
        r = nozzle_d * 0.5 * np.sqrt(rng.random(n))
        theta = rng.random(n) * 2.0 * np.pi
        px = (r * np.cos(theta)).astype(np.float32)
        py = (r * np.sin(theta)).astype(np.float32)
        # 速度：围绕 v_p 的高斯分布
        vx = (v_p * rng.normal(0.95, 0.05, n)).astype(np.float32)
        vy = (v_p * np.deg2rad(angle) * rng.normal(0.0, 1.0, n)).astype(np.float32)
        vz = (v_p * rng.normal(0.99, 0.02, n)).astype(np.float32)
        # 温度：300~600 K
        temperature = (rng.normal(450.0, 60.0, n)).astype(np.float32)
        # 粒径：对数正态近似
        diameter = (rng.lognormal(np.log(d_um), 0.25, n)).astype(np.float32)
        # 临界速度判定：v > v_cr → 沉积(1)
        speed = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
        vcr = (speed >= v_cr).astype(np.float32)
        dep_eff = float(np.mean(vcr))
        return build_particle_distribution(
            px, py, vx, vy, vz,
            temperature=temperature, diameter=diameter, vcr=vcr,
            dep_efficiency=dep_eff,
        )

    def _invoke_algorithm(self, xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """调用算法函数（可被子类/配置覆盖）。"""
        try:
            return self._algorithm_fn(xyz=xyz, meta=meta)
        except Exception as exc:
            raise MatlabAlgorithmError(f"算法执行失败: {exc}") from exc

    def _select_algorithm(self) -> Callable[..., np.ndarray]:
        """选择算法实现：MATLAB 引擎优先，不可用时降级到 Python。"""
        engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()

        if engine_mode == "python":
            logger.info("算法引擎：Python（手动指定）")
            return self._default_algorithm

        # 尝试 MATLAB 引擎
        if engine_mode in ("matlab", "auto"):
            try:
                from .matlab_engine_proxy import MatlabEngineProxy
                proxy = MatlabEngineProxy()
                # 预连接验证（失败时 auto 模式降级）
                proxy._ensure_connected()
                logger.info("算法引擎：MATLAB（matlab.engine → run_path_planning）")
                return proxy
            except Exception as exc:
                if engine_mode == "matlab":
                    raise MatlabAlgorithmError(
                        f"MATLAB 引擎不可用（强制模式）: {exc}"
                    ) from exc
                logger.warning(
                    "MATLAB 引擎不可用，降级到 Python 原型: %s", exc
                )
                return self._default_algorithm

        return self._default_algorithm

    @staticmethod
    def _default_algorithm(xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """默认算法：调用项目核心路径规划器。"""
        from repair_app.core.path_planner import plan_path_from_cloud

        defect_mask = np.ones(len(xyz), dtype=bool)
        return plan_path_from_cloud(
            xyz=xyz,
            defect_mask=defect_mask,
            layer_height=meta.get("layer_height_mm", 2.0),
            scanning_angle=meta.get("scanning_angle_deg", -45.0),
            scanning_step=meta.get("scanning_step_mm", 2.0),
            buffer_mm=meta.get("buffer_repairing_mm", 0.0),
            n_layers=max(int(meta.get("num_layers", 5) or 5), 1),
        )

    @staticmethod
    def _compute_path_length(waypoints: np.ndarray) -> float:
        if len(waypoints) < 2:
            return 0.0
        return float(np.sum(np.linalg.norm(np.diff(waypoints[:, :3], axis=0), axis=1)))

    @staticmethod
    def _build_error_result(
        request_id: str,
        status_code: int,
        error_message: str,
        feasibility_reason: str,
    ) -> RepairResult:
        return Serializer.build_repair_result(
            np.zeros((0, 3), dtype=np.float32),
            request_id=request_id,
            status_code=status_code,
            error_message=error_message,
            is_feasible=False,
            feasibility_reason=feasibility_reason,
        )


def create_matlab_adapter(
    address: Optional[str] = None,
    config: Optional[BridgeConfig] = None,
) -> MatlabAdapter:
    """工厂函数：创建 MATLAB 适配器实例。"""
    return MatlabAdapter(address=address, config=config)
