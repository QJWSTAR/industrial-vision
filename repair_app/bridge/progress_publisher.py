"""bridge.progress_publisher — 实时进度发布/订阅

ZMQ PUB/SUB 模式实现 MATLAB 计算过程中的实时进度推送。

架构：
  MATLAB (run_profile_prediction.m)
    ↓ py.repair_app.bridge.progress_publisher.publish_progress(...)
  Bridge (ProgressPublisher, ZMQ PUB port 5556)
    ↓ ProgressUpdate protobuf bytes
  GUI (ProgressSubscriber, ZMQ SUB port 5556)
    ↓ Qt Signal
  MainWindow → LayerPlayer / StatsPanel / Visualizer

设计要点：
- PUB/SUB 解耦：MATLAB 发布，GUI 订阅，互不阻塞
- protobuf 序列化：复用 ProgressUpdate 消息
- 线程安全：publisher 在 Bridge 线程，subscriber 在 GUI 线程
- 容错：MATLAB 中 py 调用失败不影响算法执行
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("csam.bridge.progress")

# 默认 PUB 端口（REP 在 5555，PUB 在 5556）
DEFAULT_PUB_PORT = 5556
DEFAULT_PUB_ADDRESS = f"tcp://127.0.0.1:{DEFAULT_PUB_PORT}"


# ================================================================
# Publisher（Bridge 侧，运行在 MATLAB pyenv 内）
# ================================================================

class ProgressPublisher:
    """ZMQ PUB 发布器，运行在 Bridge 进程内。

    MATLAB 算法通过 py. 调用 publish_progress() 发布进度。
    GUI 通过 ProgressSubscriber 订阅。
    """

    _instance: Optional["ProgressPublisher"] = None
    _lock = threading.Lock()

    def __init__(self, address: str = DEFAULT_PUB_ADDRESS) -> None:
        self._address = address
        self._sock = None
        self._ctx = None
        self._enabled = False
        self._send_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProgressPublisher":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self) -> bool:
        """启动 PUB socket（幂等：已启动时直接返回 True）。"""
        with self._lock:
            if self._enabled and self._sock is not None:
                return True
            try:
                import zmq
                self._ctx = zmq.Context()
                self._sock = self._ctx.socket(zmq.PUB)
                self._sock.setsockopt(zmq.LINGER, 0)
                self._sock.bind(self._address)
                self._enabled = True
                logger.info("ProgressPublisher 已启动: %s", self._address)
                return True
            except Exception as exc:
                logger.warning("ProgressPublisher 启动失败: %s", exc)
                self._enabled = False
                return False

    def stop(self) -> None:
        """停止 PUB socket。"""
        with self._lock:
            self._enabled = False
            try:
                if self._sock is not None:
                    self._sock.close(0)
                if self._ctx is not None:
                    self._ctx.term()
            except Exception as exc:
                logger.warning("ProgressPublisher 停止异常: %s", exc)
            finally:
                self._sock = None
                self._ctx = None

    def publish_progress(
        self,
        request_id: str,
        stage: int,
        layer_index: int = 0,
        total_layers: int = 0,
        progress: float = 0.0,
        message: str = "",
        waypoints: Optional[object] = None,
        layer_max_height: float = 0.0,
        layer_avg_height: float = 0.0,
        layer_dep_eff: float = 0.0,
        mesh_triangles: Optional[object] = None,
        elapsed_s: float = 0.0,
    ) -> None:
        """发布进度更新（供 MATLAB py. 调用）。

        Args:
            request_id: 请求 ID
            stage: ProgressUpdate.Stage 枚举值
            layer_index: 当前层号
            total_layers: 总层数
            progress: 进度 0.0-1.0
            message: 状态消息
            waypoints: matlab.double (N×7) 航点
            layer_max_height: 当前层最大高度
            layer_avg_height: 当前层平均高度
            layer_dep_eff: 当前层沉积效率
            mesh_triangles: matlab.double (N×9) 三角网格
            elapsed_s: 已耗时（秒）
        """
        if not self._enabled or self._sock is None:
            return

        with self._send_lock:
            if not self._enabled or self._sock is None:
                return

            try:
                from repair_app.communication.repair_protocol_pb2 import (
                    ProgressUpdate, LayerProfile, Waypoint,
                )
                from repair_app.communication.repair_serialization import (
                    build_progress_update, build_layer_profile,
                )

                # 转换 waypoints
                wp_np = None
                if waypoints is not None and len(waypoints) > 0:
                    wp_np = np.asarray(waypoints, dtype=np.float32)
                    if wp_np.ndim == 2 and wp_np.shape[1] >= 3:
                        pass
                    else:
                        wp_np = None

                # 转换 mesh → STL bytes
                partial_mesh = b""
                mesh_format = ""
                mesh_count = 0
                if mesh_triangles is not None and len(mesh_triangles) > 0:
                    tris = np.asarray(mesh_triangles, dtype=np.float32)
                    if tris.ndim == 2 and tris.shape[1] >= 9:
                        partial_mesh = _triangles_to_stl_bytes(tris)
                        mesh_format = "stl_binary"
                        mesh_count = len(tris)

                # 构建 LayerProfile
                layer_profiles = None
                if total_layers > 0:
                    layer_profiles = [build_layer_profile(
                        layer_index,
                        max_height_mm=float(layer_max_height),
                        avg_height_mm=float(layer_avg_height),
                        dep_efficiency=float(layer_dep_eff),
                    )]

                msg = build_progress_update(
                    request_id=str(request_id),
                    stage=int(stage),
                    layer_index=int(layer_index),
                    total_layers=int(total_layers),
                    progress=float(progress),
                    message=str(message),
                    waypoints=wp_np,
                    layer_profiles=layer_profiles,
                    partial_mesh_data=partial_mesh,
                    partial_mesh_format=mesh_format,
                )

                # 附加统计信息到 message
                stats = f" | layers={layer_index+1}/{total_layers} mesh={mesh_count} elapsed={elapsed_s:.1f}s"
                msg.message = str(message) + stats

                data = msg.SerializeToString()
                self._sock.send(data)
                logger.debug("进度已发布: layer=%d/%d progress=%.1f%%",
                             layer_index, total_layers, progress * 100)
            except Exception as exc:
                logger.debug("发布进度异常（不影响算法）: %s", exc)


def publish_progress(**kwargs) -> None:
    """模块级便捷函数，供 MATLAB py. 调用。

    MATLAB 中调用方式：
        py.repair_app.bridge.progress_publisher.publish_progress(...
            'request_id', requestId, ...
            'stage', 3, ...
            'layer_index', i, ...
        )
    """
    try:
        pub = ProgressPublisher.get_instance()
        pub.publish_progress(**kwargs)
    except Exception as exc:
        logger.debug("publish_progress 异常（不影响算法）: %s", exc)


def _triangles_to_stl_bytes(triangles: np.ndarray) -> bytes:
    """将 N×9 三角形数组转为二进制 STL bytes。"""
    import struct
    n = len(triangles)
    # STL header (80 bytes) + triangle count (4 bytes)
    header = b'\0' * 80
    body = [header, struct.pack('<I', n)]
    for tri in triangles:
        v1 = tri[0:3]; v2 = tri[3:6]; v3 = tri[6:9]
        # 法向量 = (v2-v1) × (v3-v1)
        e1 = v2 - v1; e2 = v3 - v1
        nx = e1[1]*e2[2] - e1[2]*e2[1]
        ny = e1[2]*e2[0] - e1[0]*e2[2]
        nz = e1[0]*e2[1] - e1[1]*e2[0]
        nl = (nx*nx + ny*ny + nz*nz) ** 0.5
        if nl > 0: nx /= nl; ny /= nl; nz /= nl
        body.append(struct.pack('<fff', nx, ny, nz))
        body.append(struct.pack('<fff', *v1))
        body.append(struct.pack('<fff', *v2))
        body.append(struct.pack('<fff', *v3))
        body.append(struct.pack('<H', 0))  # attribute byte count
    return b''.join(body)
