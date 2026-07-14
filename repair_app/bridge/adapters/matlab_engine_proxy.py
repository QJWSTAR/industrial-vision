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

            # 策略 3：独立启动新引擎（最慢，仅用于独立测试）
            if not self._connected:
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
