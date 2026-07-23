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
from ..communication.exceptions import MatlabCallTimeoutError
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

    def shutdown(self) -> None:
        """关闭适配器，释放 MATLAB 引擎引用。

        在 BridgeServer._cleanup 之后调用，确保单例状态清空，
        下次启动不会残留旧连接。
        """
        try:
            from .matlab_engine_proxy import MatlabEngineProxy
            MatlabEngineProxy.reset_singleton()
            logger.info("MatlabAdapter 已关闭，MATLAB 引擎引用已释放")
        except Exception as exc:
            logger.warning("MatlabAdapter 关闭异常: %s", exc)

    def handle_repair(self, request: RepairRequest) -> RepairResult:
        """处理修复请求：解析 → 调用 MATLABPipeline → 构建结果。

        生产路径：MATLABPipeline 一次调用完成路径规划 + 形貌预测
        降级路径：MATLAB 不可用时回退到 Python 启发式
        """
        started = time.time()
        request_id = request.request_id

        # 启动 ProgressPublisher（实时进度推送，供 GUI 订阅）
        try:
            from repair_app.bridge.progress_publisher import ProgressPublisher
            pub = ProgressPublisher.get_instance()
            pub.start()
        except Exception as exc:
            logger.debug("ProgressPublisher 启动失败（不影响计算）: %s", exc)

        try:
            xyz, _normals, meta = Serializer.parse_point_cloud(request)

            if len(xyz) == 0:
                return self._build_error_result(
                    request_id, RepairStatusCode.ERR_INVALID_INPUT,
                    "空点云请求", "输入点云为空",
                )

            # ---- 生产路径：MATLABPipeline 完整管线 ----
            pipeline_result = self._invoke_pipeline_with_fallback(xyz, meta)

            if pipeline_result is not None:
                # MATLAB 管线成功：使用真实计算结果
                waypoints = pipeline_result["waypoints"]
                elapsed_ms = int((time.time() - started) * 1000)
                density_gcm3 = float(meta.get("material_density_gcm3", 7.99)) or 7.99

                # 将 MATLAB warnings 附加到 feasibility_reason（Protobuf 无独立 warnings 字段）
                warnings_list = pipeline_result.get("warnings", [])
                reason = "MATLAB pipeline completed (path planning + profile prediction)"
                if warnings_list:
                    reason += " | Warnings: " + "; ".join(str(w) for w in warnings_list[:5])

                return Serializer.build_repair_result(
                    waypoints,
                    request_id=request_id,
                    status_code=RepairStatusCode.SUCCESS,
                    predicted_volume_mm3=pipeline_result["predicted_volume_mm3"],
                    material_density_gcm3=density_gcm3,
                    estimated_mass_g=pipeline_result["estimated_mass_g"],
                    estimated_time_s=pipeline_result["estimated_time_s"],
                    compute_time_ms=elapsed_ms,
                    uniformity_score=pipeline_result["uniformity"],
                    is_feasible=True,
                    feasibility_reason=reason,
                    layer_profiles=pipeline_result["layer_profiles"],
                    particle_dist=pipeline_result["particle_dist"],
                    mesh_data=pipeline_result["mesh_data"],
                    mesh_format=pipeline_result["mesh_format"],
                )

            # ---- 降级路径：仅 engine_mode=python 时启用 Python 原型 ----
            engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
            if engine_mode != "python":
                # 生产路径：MATLAB 不可用时直接报错，不降级到 Python Demo
                elapsed_ms = int((time.time() - started) * 1000)
                return self._build_error_result(
                    request_id, RepairStatusCode.ERR_ALGORITHM_FAIL,
                    "MATLAB 算法引擎不可用",
                    "MATLAB 管线调用失败。生产路径要求 MATLAB 原始算法，"
                    "不再降级到 Python Demo。请启动 MATLAB Bridge "
                    "（运行 matlab_bridge_server.m）或设置 "
                    "CSAM_ALGORITHM_ENGINE=python 以启用测试模式。",
                )

            logger.warning("测试模式（CSAM_ALGORITHM_ENGINE=python）：使用 Python 启发式算法")
            waypoints = self._default_algorithm(xyz=xyz, meta=meta)

            if len(waypoints) == 0:
                return self._build_error_result(
                    request_id, RepairStatusCode.ERR_NO_DEFECT_FOUND,
                    "未生成航点", "路径规划输出为空",
                )

            elapsed_ms = int((time.time() - started) * 1000)
            path_length = self._compute_path_length(waypoints)
            speed = max(float(meta.get("traversing_speed_mms", 500.0)), 1e-6)
            estimated_time_s = path_length / speed

            density_gcm3 = self._material_density_gcm3(meta)
            volume_mm3 = self._estimate_volume_mm3(waypoints, meta)
            mass_g = volume_mm3 * density_gcm3 * 1e-3
            uniformity = self._compute_uniformity(waypoints)
            layer_profiles = self._build_layer_profiles(waypoints, meta)
            particle_dist = self._build_particle_distribution(meta)
            mesh_data, mesh_format = self._build_mesh_from_cloud(xyz)

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
                feasibility_reason="Python heuristic (test mode: CSAM_ALGORITHM_ENGINE=python)",
                layer_profiles=layer_profiles,
                particle_dist=particle_dist,
                mesh_data=mesh_data,
                mesh_format=mesh_format,
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

    def _invoke_pipeline_with_fallback(
        self, xyz: np.ndarray, meta: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """调用 MATLABPipeline，失败时返回 None 触发降级。

        与 _invoke_with_fallback 不同：
        - 一次调用完成路径规划 + 形貌预测
        - 不分步调用，避免重复计算
        - 降级后不再重试 MATLAB
        """
        engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()

        if engine_mode == "python":
            logger.info("算法引擎：Python（手动指定），跳过 MATLAB 管线")
            return None

        try:
            from .matlab_pipeline import MATLABPipeline
            pipeline = MATLABPipeline()
            result = pipeline.run(xyz, meta)
            # 转换为 build_repair_result 所需的格式
            from repair_app.communication.repair_serialization import (
                build_layer_profile,
                build_particle_distribution,
            )

            # layer_profiles
            layer_profiles = []
            lp_arr = result.get("layer_profiles")
            if lp_arr is not None and len(lp_arr) > 0:
                lp = np.asarray(lp_arr, dtype=np.float32)
                if lp.ndim == 2 and lp.shape[1] >= 4:
                    for row in lp:
                        layer_profiles.append(
                            build_layer_profile(
                                int(row[0]),
                                max_height_mm=float(row[1]),
                                avg_height_mm=float(row[2]),
                                dep_efficiency=float(row[3]),
                            )
                        )

            # particle_distribution
            pd_raw = result.get("particle_distribution")
            particle_dist = None
            if pd_raw is not None:
                px = np.asarray(pd_raw.get("px", []), dtype=np.float32)
                py = np.asarray(pd_raw.get("py", []), dtype=np.float32)
                vx = np.asarray(pd_raw.get("vx", []), dtype=np.float32)
                vy = np.asarray(pd_raw.get("vy", []), dtype=np.float32)
                vz = np.asarray(pd_raw.get("vz", []), dtype=np.float32)
                vcr = np.asarray(pd_raw.get("vcr", []), dtype=np.float32)
                diameter = np.asarray(pd_raw.get("diameter", []), dtype=np.float32)
                temperature = np.asarray(pd_raw.get("temperature", []), dtype=np.float32)
                dep_eff = float(pd_raw.get("dep_efficiency", 0.0) or 0.0)
                if len(px) > 0:
                    particle_dist = build_particle_distribution(
                        px, py, vx, vy, vz,
                        temperature=temperature if len(temperature) == len(px) else None,
                        diameter=diameter if len(diameter) == len(px) else None,
                        vcr=vcr if len(vcr) == len(px) else None,
                        dep_efficiency=dep_eff,
                    )

            mesh_data = result.get("mesh_stl_bytes", b"")
            mesh_format = "stl_binary" if mesh_data else ""

            return {
                "waypoints": result["waypoints"],
                "predicted_volume_mm3": float(result.get("predicted_volume_mm3", 0.0) or 0.0),
                "estimated_mass_g": float(result.get("estimated_mass_g", 0.0) or 0.0),
                "estimated_time_s": float(result.get("estimated_time_s", 0.0) or 0.0),
                "uniformity": float(result.get("uniformity", 0.78) or 0.78),
                "layer_profiles": layer_profiles,
                "particle_dist": particle_dist,
                "mesh_data": mesh_data,
                "mesh_format": mesh_format,
                "warnings": list(result.get("warnings", []) or []),
            }

        except MatlabCallTimeoutError as exc:
            logger.error("MATLAB 管线超时: %s", exc)
            if engine_mode == "matlab":
                raise MatlabAlgorithmError(f"MATLAB 管线超时 ({exc.timeout_s}s)") from exc
            logger.warning("MATLAB 管线超时，降级到 Python: %s", exc)
            return None
        except Exception as exc:
            if engine_mode == "matlab":
                logger.warning("MATLAB 管线失败（强制模式）: %s", exc)
                raise MatlabAlgorithmError(f"MATLAB 管线失败: {exc}") from exc
            logger.warning("MATLAB 管线不可用，将降级到 Python: %s", exc)
            return None

    # ====== MATLAB 形貌预测 ======

    def _try_profile_prediction(
        self, xyz: np.ndarray, meta: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """尝试调用 MATLAB run_profile_prediction 填充可视化字段。

        成功返回 dict（含 layer_profiles/particle_dist/mesh_data 等），
        失败返回 None（调用方降级到 Python 启发式）。
        """
        engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
        if engine_mode == "python":
            return None
        # 若路径规划已降级到 Python（MATLAB 不可用），跳过形貌预测避免重复连接延迟
        if self._algorithm_fn is self._default_algorithm:
            return None

        try:
            from .matlab_engine_proxy import MatlabEngineProxy
            proxy = MatlabEngineProxy()
            proxy._ensure_connected()
            raw = proxy.call_profile_prediction(xyz, meta)
            return self._build_viz_from_profile(raw, meta)
        except Exception as exc:
            if engine_mode == "matlab":
                logger.warning("MATLAB 形貌预测失败（强制模式，降级到启发式）: %s", exc)
            else:
                logger.info("MATLAB 形貌预测不可用，降级到 Python 启发式: %s", exc)
            return None

    @staticmethod
    def _build_viz_from_profile(
        raw: dict[str, Any], meta: dict[str, Any]
    ) -> dict[str, Any]:
        """将 MATLAB 形貌预测结果转换为 RepairResult 可视化字段。"""
        from repair_app.communication.repair_serialization import (
            build_layer_profile,
            build_particle_distribution,
        )

        # layer_profiles: N×4 [layer_idx, max_h, avg_h, dep_eff] → List[LayerProfile]
        lp_arr = raw.get("layer_profiles")
        layer_profiles = []
        if lp_arr is not None and len(lp_arr) > 0:
            lp = np.asarray(lp_arr, dtype=np.float32)
            if lp.ndim == 2 and lp.shape[1] >= 4:
                for row in lp:
                    layer_profiles.append(
                        build_layer_profile(
                            int(row[0]),
                            max_height_mm=float(row[1]),
                            avg_height_mm=float(row[2]),
                            dep_efficiency=float(row[3]),
                        )
                    )

        # particle_distribution: dict → ParticleDistribution
        pd_raw = raw.get("particle_distribution")
        particle_dist = None
        if pd_raw is not None:
            px = np.asarray(pd_raw.get("px", []), dtype=np.float32)
            py = np.asarray(pd_raw.get("py", []), dtype=np.float32)
            vx = np.asarray(pd_raw.get("vx", []), dtype=np.float32)
            vy = np.asarray(pd_raw.get("vy", []), dtype=np.float32)
            vz = np.asarray(pd_raw.get("vz", []), dtype=np.float32)
            vcr = np.asarray(pd_raw.get("vcr", []), dtype=np.float32)
            diameter = np.asarray(pd_raw.get("diameter", []), dtype=np.float32)
            temperature = np.asarray(pd_raw.get("temperature", []), dtype=np.float32)
            dep_eff = float(pd_raw.get("dep_efficiency", 0.0) or 0.0)
            if len(px) > 0:
                particle_dist = build_particle_distribution(
                    px, py, vx, vy, vz,
                    temperature=temperature if len(temperature) == len(px) else None,
                    diameter=diameter if len(diameter) == len(px) else None,
                    vcr=vcr if len(vcr) == len(px) else None,
                    dep_efficiency=dep_eff,
                )

        # mesh_data: 二进制 STL bytes
        mesh_data = raw.get("mesh_stl_bytes", b"")
        mesh_format = "stl_binary" if mesh_data else ""

        return {
            "predicted_volume_mm3": float(raw.get("predicted_volume_mm3", 0.0) or 0.0),
            "estimated_mass_g": float(raw.get("estimated_mass_g", 0.0) or 0.0),
            "estimated_time_s": float(raw.get("estimated_time_s", 0.0) or 0.0),
            "uniformity": float(raw.get("uniformity", 0.78) or 0.78),
            "layer_profiles": layer_profiles,
            "particle_dist": particle_dist,
            "mesh_data": mesh_data,
            "mesh_format": mesh_format,
        }

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

    @staticmethod
    def _build_mesh_from_cloud(xyz: np.ndarray) -> tuple[bytes, str]:
        """从点云生成 Delaunay 三角网格，编码为二进制 STL bytes。

        降级路径使用：MATLAB 不可用时仍为 GUI 提供 mesh 数据。
        """
        if len(xyz) < 3:
            return b"", ""
        try:
            from scipy.spatial import Delaunay
            from .matlab_engine_proxy import _triangles_to_binary_stl

            pts = np.asarray(xyz, dtype=np.float32)
            # 限制点数避免大网格性能问题
            if len(pts) > 5000:
                rng = np.random.default_rng(42)
                idx = rng.choice(len(pts), 5000, replace=False)
                pts = pts[idx]
            # XY 投影 Delaunay
            tri = Delaunay(pts[:, :2])
            triangles = pts[tri.simplices].reshape(-1, 9)  # (N, 9)
            stl_bytes = _triangles_to_binary_stl(triangles)
            return stl_bytes, "stl_binary" if stl_bytes else ""
        except Exception as exc:
            logger.warning("Python 降级 mesh 生成失败: %s", exc)
            return b"", ""

    def _invoke_algorithm(self, xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """调用算法函数（可被子类/配置覆盖）。"""
        try:
            return self._algorithm_fn(xyz=xyz, meta=meta)
        except Exception as exc:
            raise MatlabAlgorithmError(f"算法执行失败: {exc}") from exc

    def _invoke_with_fallback(self, xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """调用算法，auto 模式下 MATLAB 失败时自动降级到 Python 原型。

        工业可靠性保证：MATLAB 不可用或算法异常时，生产连续性优先，
        降级到 Python 本地路径规划器，不中断服务。
        降级后切换 _algorithm_fn 到 Python，避免后续请求重复尝试 MATLAB。
        """
        try:
            return self._invoke_algorithm(xyz, meta)
        except MatlabAlgorithmError as exc:
            engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
            # 仅当当前算法不是 Python 默认算法时才降级（避免无限递归）
            if engine_mode == "auto" and self._algorithm_fn is not self._default_algorithm:
                logger.warning(
                    "MATLAB 算法失败，auto 模式降级到 Python 原型: %s", exc
                )
                # 切换到 Python，后续请求（含 _try_profile_prediction）直接跳过 MATLAB
                self._algorithm_fn = self._default_algorithm
                return self._default_algorithm(xyz=xyz, meta=meta)
            raise

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
