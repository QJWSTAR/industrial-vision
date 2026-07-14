"""bridge.adapters.matlab_engine_proxy — MATLAB 引擎代理

封装 matlab.engine，提供与 MatlabAdapter._algorithm_fn 兼容的调用接口。

策略：
1. 优先连接由 matlab_bridge_server.m 共享的 MATLAB 会话（connect_matlab）
2. 若无共享会话，尝试 start_matlab（独立启动，较慢）
3. 全部失败则抛出异常，由上层降级到 Python 算法

数据流：
  Python (xyz ndarray + meta dict)
    → 写临时 STL 文件
    → eng.run_path_planning(stl_path, params)  [MATLAB 内存执行]
    → 返回 (pointlist M×6, feed_rates M×1, layer_indices M×1)
    → 组装为 (M, 8) waypoints ndarray
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("csam.bridge.matlab_engine")

# 共享会话名称（与 matlab_bridge_server.m 中的 shareEngine 一致）
DEFAULT_SHARED_NAME = "matlab_bridge"


class MatlabEngineProxy:
    """matlab.engine 单例封装，符合 _algorithm_fn 签名。

    用法：
        proxy = MatlabEngineProxy()
        waypoints = proxy(xyz, meta)  # 等价于 _algorithm_fn(xyz, meta)
    """

    _instance: Optional["MatlabEngineProxy"] = None
    _eng = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        shared_name: str = DEFAULT_SHARED_NAME,
        algo_dir: Optional[str] = None,
        call_timeout_s: float = 60.0,
        connect_retry: int = 3,
        connect_interval_s: float = 2.0,
    ) -> None:
        # __init__ 可能因单例被多次调用，只初始化一次
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._shared_name = shared_name or os.environ.get(
            "CSAM_MATLAB_SHARED_NAME", DEFAULT_SHARED_NAME
        )
        self._algo_dir = algo_dir or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "形貌预测"
        )
        self._algo_dir = os.path.abspath(self._algo_dir)
        self._call_timeout = call_timeout_s
        self._connect_retry = connect_retry
        self._connect_interval = connect_interval_s
        self._connected = False
        self._started_independently = False

    # ================================================================
    # 引擎连接
    # ================================================================

    def _ensure_connected(self) -> None:
        """连接到 MATLAB 引擎（共享会话优先）。"""
        if self._connected and self._eng is not None:
            return

        with self._lock:
            if self._connected and self._eng is not None:
                return

            import matlab.engine as me

            # 策略 1：连接共享会话（生产路径，由 matlab_bridge_server.m 共享）
            last_err: Optional[Exception] = None
            for attempt in range(1, self._connect_retry + 1):
                try:
                    sessions = me.find_matlab()
                    if self._shared_name in sessions:
                        logger.info(
                            "连接共享 MATLAB 会话 '%s' (尝试 %d/%d)",
                            self._shared_name, attempt, self._connect_retry,
                        )
                        self._eng = me.connect_matlab(self._shared_name)
                        self._connected = True
                        logger.info("已连接共享 MATLAB 会话")
                        break
                    else:
                        logger.debug(
                            "未找到共享会话 '%s'，可用: %s",
                            self._shared_name, sessions,
                        )
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        "连接共享会话失败 (尝试 %d/%d): %s",
                        attempt, self._connect_retry, exc,
                    )

                if attempt < self._connect_retry:
                    time.sleep(self._connect_interval)

            # 策略 2：连接默认共享会话（无名称）
            if not self._connected:
                try:
                    logger.info("尝试连接默认 MATLAB 会话")
                    self._eng = me.connect_matlab()
                    self._connected = True
                    logger.info("已连接默认 MATLAB 会话")
                except Exception as exc:
                    last_err = exc
                    logger.warning("连接默认会话失败: %s", exc)

            # 策略 3：独立启动新引擎（最慢，仅强制 matlab 模式或独立测试使用）
            # auto 模式下跳过：独立启动耗时 30-60s 且无算法路径，应降级到 Python
            engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
            allow_standalone = engine_mode == "matlab" or os.environ.get(
                "CSAM_MATLAB_ALLOW_STANDALONE", "0"
            ) == "1"
            if not self._connected and allow_standalone:
                try:
                    logger.info("尝试独立启动 MATLAB 引擎（可能需要 30-60s）")
                    self._eng = me.start_matlab()
                    self._connected = True
                    self._started_independently = True
                    logger.info("MATLAB 引擎已独立启动")
                except Exception as exc:
                    last_err = exc
                    logger.error("MATLAB 引擎启动失败: %s", exc)
                    raise RuntimeError(
                        f"无法连接 MATLAB 引擎: {last_err}"
                    ) from last_err

            if not self._connected:
                raise RuntimeError(
                    f"无可用 MATLAB 共享会话（auto 模式跳过独立启动）: {last_err}"
                )

            # 添加算法路径（仅独立启动时需要；共享会话由 matlab_bridge_server.m 已 addpath）
            # 注意：matlab.engine 跨语言传中文路径会触发 "Unknown exception"，
            # 因此共享会话模式下跳过 addpath（由 MATLAB 侧负责）。
            if self._started_independently and self._algo_dir and os.path.isdir(self._algo_dir):
                try:
                    self._eng.addpath(self._algo_dir, nargout=0)
                    logger.debug("addpath: %s", self._algo_dir)
                except Exception as exc:
                    logger.warning("addpath 失败（共享会话应已预加载）: %s", exc)

    # ================================================================
    # _algorithm_fn 签名实现
    # ================================================================

    def __call__(self, xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """符合 _algorithm_fn 签名：xyz + meta → waypoints(M,8)。

        流程：
        1. 将点云写为临时 STL 文件
        2. 构造 MATLAB params struct
        3. 调用 eng.run_path_planning(stl_path, params)
        4. 将返回值组装为 (M, 8) ndarray
        """
        self._ensure_connected()

        stl_path = self._write_xyz_as_stl(xyz)
        params = self._meta_to_matlab_struct(meta)

        try:
            result = self._eng.run_path_planning(
                stl_path, params, nargout=4,
            )
            pointlist, feed_rates, layer_indices, meta_out = result
            waypoints = self._assemble_waypoints(
                pointlist, feed_rates, layer_indices
            )
            compute_time = 0.0
            try:
                compute_time = float(meta_out.get("compute_time_s", 0)) if isinstance(meta_out, dict) else 0.0
            except Exception:
                pass
            logger.info(
                "MATLAB 路径规划完成: %d 航点, 耗时 %.2fs",
                len(waypoints), compute_time,
            )
            return waypoints
        finally:
            # 清理临时 STL
            try:
                os.remove(stl_path)
            except OSError:
                pass

    # ================================================================
    # 形貌预测（run_profile_prediction）
    # ================================================================

    def call_profile_prediction(
        self, xyz: np.ndarray, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """调用 MATLAB run_profile_prediction，返回形貌预测完整结果。

        流程：
        1. 将点云写为临时 STL 文件
        2. 构造 MATLAB params struct
        3. 调用 eng.run_profile_prediction(stl_path, excel_path, params)
        4. 将返回的 struct 解析为 Python dict（含 mesh、layer_profiles、
           particle_distribution、uniformity、estimated_mass_g、estimated_time_s、
           warnings）
        """
        self._ensure_connected()

        stl_path = self._write_xyz_as_stl(xyz)
        params = self._meta_to_profile_params(meta)
        # CFD Excel 路径：优先用 meta 中的 cfd_excel_path，否则传空让 MATLAB 自动查找
        excel_path = str(meta.get("cfd_excel_path", ""))

        try:
            raw = self._eng.run_profile_prediction(
                stl_path, excel_path, params, nargout=1,
            )
            result = self._parse_profile_result(raw)
            logger.info(
                "MATLAB 形貌预测完成: mesh=%d 三角形, 航点=%d, 耗时 %.2fs",
                len(result.get("mesh", [])),
                result.get("waypoint_count", 0),
                result.get("compute_time_s", 0.0),
            )
            return result
        finally:
            try:
                os.remove(stl_path)
            except OSError:
                pass

    def _meta_to_profile_params(self, meta: dict[str, Any]) -> dict:
        """将 Python meta dict 转为 MATLAB run_profile_prediction 兼容的 struct dict。"""
        def safe_float(val, default):
            try:
                return float(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        # 路径规划相关参数复用 _meta_to_matlab_struct 的映射
        base = self._meta_to_matlab_struct(meta)

        # 形貌预测特有参数
        base["standoff_distance_mm"] = safe_float(
            meta.get("standoff_distance_mm"), 30.0
        )
        base["spot_step_size_mm"] = safe_float(
            meta.get("spot_step_size_mm"),
            safe_float(meta.get("scanning_step_mm"), 2.0),
        )
        base["subdivide_max_edge"] = safe_float(
            meta.get("subdivide_max_edge"), 5.0
        )
        base["improve_short_edge"] = safe_float(
            meta.get("improve_short_edge"), 1.5
        )
        base["octree_max_depth"] = safe_float(
            meta.get("octree_max_depth"), 6.0
        )
        base["octree_max_tris"] = safe_float(
            meta.get("octree_max_tris"), 8.0
        )
        base["nozzle_diameter_mm"] = safe_float(
            meta.get("nozzle_diameter_mm"), 6.0
        )
        base["material_density_gcm3"] = safe_float(
            meta.get("material_density_gcm3"), 7.99
        )
        base["particle_velocity_ms"] = safe_float(
            meta.get("particle_velocity_ms"), 500.0
        )
        base["critical_velocity_ms"] = safe_float(
            meta.get("critical_velocity_ms"), 400.0
        )
        base["particle_size_um"] = safe_float(
            meta.get("particle_size_um"), 25.0
        )
        base["num_layers"] = safe_float(
            meta.get("num_layers"), 3.0
        )
        return base

    @staticmethod
    def _parse_profile_result(raw: Any) -> dict[str, Any]:
        """将 MATLAB 返回的 struct（Python dict）解析为标准化 dict。

        处理 matlab.double → numpy.ndarray 转换，处理空数组与嵌套 struct。
        """
        def to_np(val) -> np.ndarray:
            if val is None:
                return np.zeros((0,), dtype=np.float32)
            arr = np.asarray(val, dtype=np.float64)
            return arr.astype(np.float32)

        def to_list(val) -> list:
            if val is None:
                return []
            if isinstance(val, (list, tuple)):
                return [str(v) for v in val]
            return [str(val)]

        result: dict[str, Any] = {
            "mesh": to_np(raw.get("mesh", [])),
            "substrate_triangles": to_np(raw.get("substrate_triangles", [])),
            "layer_profiles": to_np(raw.get("layer_profiles", [])),
            "uniformity": float(raw.get("uniformity", 0.78) or 0.78),
            "estimated_mass_g": float(raw.get("estimated_mass_g", 0.0) or 0.0),
            "estimated_time_s": float(raw.get("estimated_time_s", 0.0) or 0.0),
            "predicted_volume_mm3": float(raw.get("predicted_volume_mm3", 0.0) or 0.0),
            "compute_time_s": float(raw.get("compute_time_s", 0.0) or 0.0),
            "waypoint_count": int(raw.get("waypoint_count", 0) or 0),
            "warnings": to_list(raw.get("warnings", [])),
        }

        # 解析嵌套的 particle_distribution struct
        pd_raw = raw.get("particle_distribution", None)
        if pd_raw is not None:
            result["particle_distribution"] = {
                "px": to_np(pd_raw.get("px", [])),
                "py": to_np(pd_raw.get("py", [])),
                "vx": to_np(pd_raw.get("vx", [])),
                "vy": to_np(pd_raw.get("vy", [])),
                "vz": to_np(pd_raw.get("vz", [])),
                "vcr": to_np(pd_raw.get("vcr", [])),
                "dep_efficiency": float(pd_raw.get("dep_efficiency", 0.0) or 0.0),
                "diameter": to_np(pd_raw.get("diameter", [])),
                "temperature": to_np(pd_raw.get("temperature", [])),
            }
        else:
            result["particle_distribution"] = None

        # 将 mesh（N×9）转为二进制 STL bytes
        mesh = result["mesh"]
        if mesh.ndim == 2 and mesh.shape[1] == 9 and len(mesh) > 0:
            result["mesh_stl_bytes"] = _triangles_to_binary_stl(mesh)
        else:
            result["mesh_stl_bytes"] = b""

        return result

    # ================================================================
    # 数据转换
    # ================================================================

    @staticmethod
    def _write_xyz_as_stl(xyz: np.ndarray) -> str:
        """将点云写为 ASCII STL 文件（轻量 I/O，非算法）。

        使用 Delaunay 三角化生成网格，写入临时 STL。
        """
        from scipy.spatial import Delaunay

        xyz = np.asarray(xyz, dtype=np.float64)
        if len(xyz) < 3:
            raise ValueError(f"点云太少，无法三角化: {len(xyz)} 点")

        # XY 平面 Delaunay 三角化
        pts2d = xyz[:, :2]
        tri = Delaunay(pts2d)
        triangles = tri.simplices  # (N, 3) 顶点索引

        # 计算法向量
        v1 = xyz[triangles[:, 1]] - xyz[triangles[:, 0]]
        v2 = xyz[triangles[:, 2]] - xyz[triangles[:, 0]]
        normals = np.cross(v1, v2)
        norm_len = np.linalg.norm(normals, axis=1, keepdims=True)
        norm_len[norm_len < 1e-12] = 1e-12
        normals = normals / norm_len

        # 写 ASCII STL
        fd, stl_path = tempfile.mkstemp(suffix=".stl", prefix="csam_cloud_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("solid csam_substrate\n")
                for i in range(len(triangles)):
                    n = normals[i]
                    p0, p1, p2 = xyz[triangles[i, 0]], xyz[triangles[i, 1]], xyz[triangles[i, 2]]
                    f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
                    f.write("    outer loop\n")
                    f.write(f"      vertex {p0[0]:.6e} {p0[1]:.6e} {p0[2]:.6e}\n")
                    f.write(f"      vertex {p1[0]:.6e} {p1[1]:.6e} {p1[2]:.6e}\n")
                    f.write(f"      vertex {p2[0]:.6e} {p2[1]:.6e} {p2[2]:.6e}\n")
                    f.write("    endloop\n")
                    f.write("  endfacet\n")
                f.write("endsolid csam_substrate\n")
        except Exception:
            os.remove(stl_path)
            raise

        return stl_path

    def _meta_to_matlab_struct(self, meta: dict[str, Any]) -> dict:
        """将 Python meta dict 转为 MATLAB struct 兼容的 dict。

        matlab.engine 会自动将 Python dict 转为 MATLAB struct。
        所有值必须是 float（MATLAB double 兼容）。
        """
        def safe_float(val, default):
            try:
                return float(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        return {
            "base_plane": safe_float(meta.get("base_plane_mm"), 5.0),
            "layer_height": safe_float(meta.get("layer_height_mm"), 2.0),
            "buffer_additive": safe_float(meta.get("buffer_additive_mm"), 2.0),
            "buffer_repairing": safe_float(meta.get("buffer_repairing_mm"), 0.0),
            "scanning_angle": safe_float(meta.get("scanning_angle_deg"), -45.0),
            "scanning_step": safe_float(meta.get("scanning_step_mm"), 2.0),
            "edge_step_size": safe_float(meta.get("edge_step_size_mm"), 2.0),
            "tilt_angle": safe_float(meta.get("tilt_angle_deg"), 60.0),
            "link_path_free_dist": safe_float(meta.get("link_path_free_dist_mm"), 20.0),
            "resolution": safe_float(meta.get("obstacle_resolution_mm"), 2.0),
            "traversing_speed_mms": safe_float(meta.get("traversing_speed_mms"), 500.0),
        }

    @staticmethod
    def _assemble_waypoints(
        pointlist: Any,
        feed_rates: Any,
        layer_indices: Any,
    ) -> np.ndarray:
        """将 MATLAB 返回的数组组装为 (M, 8) waypoints ndarray。

        pointlist: matlab.double (M×6) [x, y, z, nx, ny, nz]
        feed_rates: matlab.double (M×1)
        layer_indices: matlab.double (M×1)
        """
        pts = np.asarray(pointlist, dtype=np.float32)  # (M, 6) 或 (6, M)
        feeds = np.asarray(feed_rates, dtype=np.float32).reshape(-1, 1)
        layers = np.asarray(layer_indices, dtype=np.float32).reshape(-1, 1)

        # matlab.double 转 numpy 后形状可能是 (M, 6) 或转置
        if pts.ndim == 1:
            pts = pts.reshape(1, -1)
        if pts.shape[0] == 6 and pts.shape[1] != 6:
            pts = pts.T  # MATLAB 列优先可能导致转置

        M = pts.shape[0]
        if feeds.shape[0] != M:
            feeds = feeds[:M].reshape(-1, 1) if feeds.size >= M else np.zeros((M, 1), dtype=np.float32)
        if layers.shape[0] != M:
            layers = layers[:M].reshape(-1, 1) if layers.size >= M else np.zeros((M, 1), dtype=np.float32)

        # 组装 (M, 8): x, y, z, nx, ny, nz, feed_rate, layer_index
        waypoints = np.hstack([pts, feeds, layers])
        return waypoints.astype(np.float32)

    # ================================================================
    # 生命周期
    # ================================================================

    def shutdown(self) -> None:
        """断开 MATLAB 引擎连接（不退出 MATLAB 进程）。"""
        if self._eng is not None:
            try:
                # 注意：不调用 eng.quit()，因为共享会话由 MATLAB 侧管理
                # 只断开 Python 侧的连接
                self._eng = None
                self._connected = False
                logger.info("MATLAB 引擎连接已断开")
            except Exception:
                pass

    @classmethod
    def reset_singleton(cls) -> None:
        """重置单例（仅用于测试）。"""
        if cls._instance is not None:
            cls._instance.shutdown()
        cls._instance = None


def _triangles_to_binary_stl(triangles: np.ndarray) -> bytes:
    """将 N×9 三角形矩阵转换为二进制 STL bytes。

    每行格式：[x1,y1,z1, x2,y2,z2, x3,y3,z3]
    输出符合二进制 STL 规范：80 字节头 + 三角面数 + 每面 50 字节。
    """
    import struct

    triangles = np.asarray(triangles, dtype=np.float32)
    if triangles.ndim != 2 or triangles.shape[1] != 9:
        return b""

    n = triangles.shape[0]
    if n == 0:
        return b""

    # 80 字节头 + 4 字节三角形数
    buf = bytearray(b"\x00" * 80)
    buf += struct.pack("<I", n)

    for i in range(n):
        v0 = triangles[i, 0:3]
        v1 = triangles[i, 3:6]
        v2 = triangles[i, 6:9]

        # 计算法向量
        e1 = v1 - v0
        e2 = v2 - v0
        normal = np.cross(e1, e2)
        norm_len = float(np.linalg.norm(normal))
        if norm_len > 1e-12:
            normal = normal / norm_len
        else:
            normal = np.zeros(3, dtype=np.float32)

        # 50 字节：12(法向) + 12*3(三顶点) + 2(属性)
        buf += struct.pack("<3f", float(normal[0]), float(normal[1]), float(normal[2]))
        buf += struct.pack("<3f", float(v0[0]), float(v0[1]), float(v0[2]))
        buf += struct.pack("<3f", float(v1[0]), float(v1[1]), float(v1[2]))
        buf += struct.pack("<3f", float(v2[0]), float(v2[1]), float(v2[2]))
        buf += struct.pack("<H", 0)

    return bytes(buf)
