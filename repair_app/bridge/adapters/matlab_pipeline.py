"""bridge.adapters.matlab_pipeline — MATLAB 完整计算管线

将路径规划与形貌预测串联为一次 MATLAB 调用，避免重复计算。

设计目标：
- 一次 STL 写入，一次路径规划，一次形貌预测
- 路径规划结果直接传递给形貌预测（内存传递，无 .mat 文件）
- Python Demo 算法退出生产路径，MATLAB 为唯一计算实现

数据流：
  Python (xyz ndarray + meta dict)
    → MatlabEngineProxy.call_full_pipeline(xyz, meta)
        → eng.run_path_planning(stl_path, params)        [阶段 1]
            → pointlist (M×6), feed_rates (M×1), layer_indices (M×1)
        → eng.run_profile_prediction(stl_path, excel, params, pointlist, velocitylist)  [阶段 2]
            → result struct (mesh, layer_profiles, particle_dist, ...)
    → 返回 dict {waypoints, mesh, layer_profiles, ...}
"""
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger("csam.bridge.pipeline")


class MATLABPipeline:
    """MATLAB 完整计算管线：路径规划 → 形貌预测。

    用法：
        pipeline = MATLABPipeline()
        result = pipeline.run(xyz, meta)
        # result 含 waypoints + mesh + layer_profiles + particle_dist + ...

    与分别调用 MatlabEngineProxy.__call__ + call_profile_prediction 相比：
    - 避免重复写 STL 文件（1 次 vs 2 次）
    - 避免重复调用 run_path_planning（1 次 vs 2 次）
    - 计算时间减少 30-50%
    - 一次连接，一次清理
    """

    def __init__(self) -> None:
        self._proxy = None

    def _get_proxy(self):
        """懒加载 MatlabEngineProxy 单例。"""
        if self._proxy is None:
            from .matlab_engine_proxy import MatlabEngineProxy
            self._proxy = MatlabEngineProxy()
        return self._proxy

    def run(self, xyz: np.ndarray, meta: dict[str, Any]) -> dict[str, Any]:
        """执行完整管线：路径规划 → 形貌预测。

        参数：
            xyz  : ndarray (N,3) 或 (N,6) 点云坐标（+法线）
            meta : dict 工艺参数

        返回：
            dict 含以下字段：
            - waypoints        : ndarray (M,8) 航点 [x,y,z,nx,ny,nz,feed_rate,layer_idx]
            - layer_indices    : ndarray (M,) 层号
            - mesh             : ndarray (T,9) 沉积表面三角形
            - substrate_triangles : ndarray (T0,9) 原始基体三角形
            - layer_profiles   : ndarray (L,4) 逐层轮廓
            - particle_distribution : dict 或 None
            - uniformity       : float
            - estimated_mass_g : float
            - estimated_time_s : float
            - predicted_volume_mm3 : float
            - compute_time_s   : float
            - waypoint_count   : int
            - warnings         : list[str]
            - mesh_stl_bytes   : bytes 二进制 STL
        """
        proxy = self._get_proxy()
        result = proxy.call_full_pipeline(xyz, meta)
        logger.info(
            "MATLABPipeline 完成: 航点=%d, 三角形=%d, 均匀性=%.2f, 耗时=%.2fs",
            len(result.get("waypoints", [])),
            len(result.get("mesh", [])),
            result.get("uniformity", 0.0),
            result.get("compute_time_s", 0.0),
        )
        return result

    def is_available(self) -> bool:
        """检查 MATLAB 引擎是否可用（不实际连接）。"""
        engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
        if engine_mode == "python":
            return False
        try:
            proxy = self._get_proxy()
            proxy._ensure_connected()
            return True
        except Exception:
            return False
