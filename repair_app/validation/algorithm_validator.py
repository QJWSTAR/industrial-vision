"""validation.algorithm_validator — 双引擎算法验证执行器

对同一输入点云，分别调用 MATLAB 算法和 Python 算法，
收集各自的完整输出（waypoints/layer_profiles/mesh/volume/uniformity），
记录耗时，供 ResultComparator 逐项比对。

设计要点：
- 不修改任何算法代码，只调用现有入口
- MATLAB 路径：MATLABPipeline.run(xyz, meta) → 完整 dict
- Python 路径：_default_algorithm(xyz, meta) + matlab_adapter 辅助方法合成完整 dict
- 统一测试输入：generate_defect_sample(seed=42) 确定性可复现
- 两种引擎独立计时，互不干扰
"""
from __future__ import annotations

import os
import time
import platform
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from repair_app.utils.logger_config import warning


# 算法版本（硬编码，因为 MATLAB/Python 算法本身未定义版本号）
MATLAB_ALGORITHM_VERSION = "matlab-2.0.0"
PYTHON_ALGORITHM_VERSION = "python-heuristic-1.0.0"
VALIDATION_FRAMEWORK_VERSION = "1.0.0"


@dataclass
class EngineResult:
    """单个引擎的执行结果。"""

    engine_name: str  # "matlab" / "python"
    algorithm_version: str
    success: bool
    error_message: str = ""
    elapsed_s: float = 0.0
    # 完整输出
    waypoints: Optional[np.ndarray] = None  # (N, 3or6or8)
    velocitylist: Optional[np.ndarray] = None  # feed_rate 列
    layer_indices: Optional[np.ndarray] = None
    layer_profiles: Optional[np.ndarray] = None  # (L, 4)
    mesh: Optional[np.ndarray] = None  # (T, 9) 三角形
    mesh_stl_bytes: bytes = b""
    predicted_volume_mm3: float = 0.0
    estimated_mass_g: float = 0.0
    estimated_time_s: float = 0.0
    uniformity: float = 0.0
    waypoint_count: int = 0
    warnings: list = field(default_factory=list)
    matlab_runtime_version: str = ""  # 仅 MATLAB 引擎有


@dataclass
class ValidationResult:
    """验证结果（两个引擎 + 元信息）。"""

    matlab_result: EngineResult
    python_result: EngineResult
    test_input_summary: dict
    validation_timestamp: str = ""
    framework_version: str = VALIDATION_FRAMEWORK_VERSION
    system_info: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.validation_timestamp:
            from datetime import datetime
            self.validation_timestamp = datetime.now().isoformat()
        if not self.system_info:
            self.system_info = {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "numpy": np.__version__,
            }


class AlgorithmValidator:
    """双引擎算法验证执行器。

    用法：
        validator = AlgorithmValidator()
        result = validator.validate(seed=42, defect_types=["pit"])
        # result.matlab_result / result.python_result
    """

    def __init__(self) -> None:
        self._matlab_version: str = ""
        self._project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    def validate(
        self,
        seed: int = 42,
        defect_types: Optional[list] = None,
        n_points: int = 8000,
        params: Optional[dict] = None,
        skip_matlab: bool = False,
    ) -> ValidationResult:
        """执行双引擎验证。

        Args:
            seed: 随机种子（确定性可复现）
            defect_types: 缺陷类型列表，默认 ["pit"]
            n_points: 点云点数
            params: 工艺参数覆盖
            skip_matlab: 跳过 MATLAB 引擎（MATLAB 不可用时）
        Returns:
            ValidationResult
        """
        if defect_types is None:
            defect_types = ["pit"]
        if params is None:
            params = {}

        # ---- 1. 生成统一测试输入 ----
        xyz, normals, defect_mask, defect_info = self._generate_test_input(
            seed, defect_types, n_points
        )
        meta = self._build_meta(params)
        test_input_summary = {
            "seed": seed,
            "defect_types": defect_types,
            "n_points": int(len(xyz)),
            "defect_point_count": int(np.sum(defect_mask)) if defect_mask is not None else 0,
            "defect_info": defect_info,
            "params": meta,
        }

        # ---- 2. 执行 MATLAB 引擎 ----
        if skip_matlab:
            matlab_result = EngineResult(
                engine_name="matlab",
                algorithm_version=MATLAB_ALGORITHM_VERSION,
                success=False,
                error_message="skipped (--no-matlab)",
            )
        else:
            matlab_result = self._run_matlab(xyz, normals, defect_mask, meta)

        # ---- 3. 执行 Python 引擎 ----
        python_result = self._run_python(xyz, normals, defect_mask, meta)

        return ValidationResult(
            matlab_result=matlab_result,
            python_result=python_result,
            test_input_summary=test_input_summary,
        )

    # ========== 测试输入生成 ==========

    def _generate_test_input(self, seed, defect_types, n_points):
        """生成确定性测试点云。"""
        from repair_app.service.coordination_service import CoordinationService as _Coord
        return _Coord.generate_sample_defect(
            defect_types=defect_types,
            seed=seed,
            n_points=n_points,
        )

    def _build_meta(self, params: dict) -> dict:
        """构建工艺参数 meta 字典。"""
        defaults = {
            "standoff_distance_mm": 30.0,
            "spot_step_size_mm": 2.0,
            "nozzle_diameter_mm": 6.0,
            "traversing_speed_mms": 500.0,
            "material_density_gcm3": 7.99,
            "particle_velocity_ms": 500.0,
            "critical_velocity_ms": 400.0,
            "particle_size_um": 25.0,
            "layer_height_mm": 2.0,
            "scanning_angle_deg": -45.0,
            "scanning_step_mm": 2.0,
            "edge_step_size_mm": 2.0,
            "tilt_angle_deg": 60.0,
            "buffer_additive_mm": 2.0,
            "buffer_repairing_mm": 0.0,
            "max_layers": 5,
            "num_layers": 3,
        }
        defaults.update(params)
        return defaults

    # ========== MATLAB 引擎执行 ==========

    def _run_matlab(
        self,
        xyz: np.ndarray,
        normals: np.ndarray,
        defect_mask: np.ndarray,
        meta: dict,
    ) -> EngineResult:
        """执行 MATLAB 算法管线。"""
        result = EngineResult(
            engine_name="matlab",
            algorithm_version=MATLAB_ALGORITHM_VERSION,
            success=False,
        )

        try:
            from repair_app.bridge.adapters.matlab_pipeline import MATLABPipeline
            # 获取 MATLAB Runtime 版本
            result.matlab_runtime_version = self._get_matlab_version()

            started = time.time()
            pipeline = MATLABPipeline()
            raw = pipeline.run(xyz, meta)
            elapsed = time.time() - started

            result.success = True
            result.elapsed_s = elapsed
            result.waypoints = np.asarray(raw.get("waypoints", []))
            result.layer_indices = np.asarray(raw.get("layer_indices", []))
            result.layer_profiles = np.asarray(raw.get("layer_profiles", []))
            result.mesh = np.asarray(raw.get("mesh", []))
            result.mesh_stl_bytes = raw.get("mesh_stl_bytes", b"")
            result.predicted_volume_mm3 = float(raw.get("predicted_volume_mm3", 0.0) or 0.0)
            result.estimated_mass_g = float(raw.get("estimated_mass_g", 0.0) or 0.0)
            result.estimated_time_s = float(raw.get("estimated_time_s", 0.0) or 0.0)
            result.uniformity = float(raw.get("uniformity", 0.0) or 0.0)
            result.waypoint_count = int(raw.get("waypoint_count", 0) or 0)
            result.warnings = list(raw.get("warnings", []) or [])
            # 提取 velocitylist（feed_rate 列）
            wp = result.waypoints
            if wp is not None and wp.ndim == 2 and wp.shape[1] >= 7:
                result.velocitylist = wp[:, 6]
        except Exception as exc:
            result.success = False
            result.error_message = f"{type(exc).__name__}: {exc}"
            result.elapsed_s = 0.0

        return result

    def _get_matlab_version(self) -> str:
        """获取 MATLAB Runtime 版本（从安装路径解析）。"""
        if self._matlab_version:
            return self._matlab_version
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            m = MatlabLifecycleManager.get_instance()
            v = m.matlab_version
            if isinstance(v, str) and v:
                self._matlab_version = v
                return v
        except Exception as exc:
            warning(f"通过 MatlabLifecycleManager 获取版本失败: {exc}")
        try:
            from repair_app.bridge.launcher import MatlabBridgeLauncher
            launcher = MatlabBridgeLauncher(str(self._project_root))
            _path, version = launcher._find_matlab_executable_with_version()
            if isinstance(version, str) and version:
                self._matlab_version = version
                return version
        except Exception as exc:
            warning(f"通过 MatlabBridgeLauncher 获取版本失败: {exc}")
        return "unknown"

    # ========== Python 引擎执行 ==========

    def _run_python(
        self,
        xyz: np.ndarray,
        normals: np.ndarray,
        defect_mask: np.ndarray,
        meta: dict,
    ) -> EngineResult:
        """执行 Python 启发式算法 + 辅助方法合成完整输出。"""
        result = EngineResult(
            engine_name="python",
            algorithm_version=PYTHON_ALGORITHM_VERSION,
            success=False,
        )

        try:
            from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
            # 所有辅助方法均为 @staticmethod，无需实例化 adapter

            started = time.time()
            # Python 启发式路径规划（_default_algorithm 是 @staticmethod，无需 self）
            waypoints = MatlabAdapter._default_algorithm(xyz=xyz, meta=meta)
            elapsed_core = time.time() - started

            # 合成可视化字段（与 handle_repair 降级路径一致，均为 @staticmethod）
            layer_profiles_list = MatlabAdapter._build_layer_profiles(waypoints, meta)
            mesh_data, mesh_format = MatlabAdapter._build_mesh_from_cloud(xyz)
            uniformity = MatlabAdapter._compute_uniformity(waypoints)
            volume_mm3 = MatlabAdapter._estimate_volume_mm3(waypoints, meta)
            path_length = MatlabAdapter._compute_path_length(waypoints)
            speed = max(float(meta.get("traversing_speed_mms", 500.0)), 1e-6)
            estimated_time_s = path_length / speed
            density = MatlabAdapter._material_density_gcm3(meta)
            mass_g = volume_mm3 * density * 1e-3
            elapsed_total = time.time() - started

            # 提取 velocitylist（Python 路径无 feed_rate，用默认 traversing_speed）
            velocitylist = np.full(len(waypoints), meta.get("traversing_speed_mms", 500.0))

            result.success = True
            result.elapsed_s = elapsed_total
            result.waypoints = np.asarray(waypoints)
            result.velocitylist = velocitylist
            # Python 路径无显式 layer_indices，从 z 推导
            result.layer_indices = self._derive_layer_indices_from_z(waypoints, meta)
            # layer_profiles 转 ndarray (L, 4)
            if layer_profiles_list:
                lp_arr = np.array([
                    [lp.layer_index, lp.max_height_mm, lp.avg_height_mm, lp.dep_efficiency]
                    for lp in layer_profiles_list
                ], dtype=np.float32)
                result.layer_profiles = lp_arr
            else:
                result.layer_profiles = np.zeros((0, 4), dtype=np.float32)
            result.mesh_stl_bytes = mesh_data if isinstance(mesh_data, bytes) else b""
            result.mesh = self._stl_bytes_to_triangles(result.mesh_stl_bytes)
            result.predicted_volume_mm3 = float(volume_mm3)
            result.estimated_mass_g = float(mass_g)
            result.estimated_time_s = float(estimated_time_s)
            result.uniformity = float(uniformity)
            result.waypoint_count = int(len(waypoints))
            result.warnings = ["Python heuristic (test mode)"]
        except Exception as exc:
            result.success = False
            result.error_message = f"{type(exc).__name__}: {exc}"
            result.elapsed_s = 0.0

        return result

    def _derive_layer_indices_from_z(self, waypoints: np.ndarray, meta: dict) -> np.ndarray:
        """从 Z 值反推层号（与 MATLAB 路径一致）。"""
        if waypoints is None or len(waypoints) == 0:
            return np.zeros(0, dtype=np.int32)
        layer_h = max(float(meta.get("layer_height_mm", 2.0)), 1e-6)
        base = float(meta.get("base_plane", 5.0))
        z = waypoints[:, 2]
        indices = np.maximum(np.floor((z - z.min()) / layer_h).astype(np.int32), 0)
        return indices + 1  # 层号从 1 开始

    def _stl_bytes_to_triangles(self, stl_bytes: bytes) -> np.ndarray:
        """二进制 STL bytes 转 (T, 9) 三角形数组。"""
        if not stl_bytes or len(stl_bytes) < 84:
            return np.zeros((0, 9), dtype=np.float32)
        try:
            import struct
            n_tri = struct.unpack_from("<I", stl_bytes, 80)[0]
            if n_tri <= 0:
                return np.zeros((0, 9), dtype=np.float32)
            tris = np.zeros((n_tri, 9), dtype=np.float32)
            offset = 84
            for i in range(n_tri):
                base = offset + i * 50 + 12  # 跳过法向量
                v1 = struct.unpack_from("<fff", stl_bytes, base)
                v2 = struct.unpack_from("<fff", stl_bytes, base + 12)
                v3 = struct.unpack_from("<fff", stl_bytes, base + 24)
                tris[i] = [*v1, *v2, *v3]
            return tris
        except Exception:
            return np.zeros((0, 9), dtype=np.float32)
