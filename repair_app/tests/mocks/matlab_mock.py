"""matlab_mock.py — MATLAB Bridge Mock 体系。

提供三层 Mock：
1. deterministic_algorithm: 确定性算法函数（替代真实 MATLAB 算法）
2. MockMatlabAdapter: 替代 MatlabAdapter（不依赖 matlab.engine）
3. MockBridgeServer: 模拟 ZMQ Bridge 服务端（响应 RepairRequest）

设计原则：
- 确定性：相同输入永远产生相同输出（便于断言）
- 快速：纯 numpy 计算，无 I/O 阻塞
- 可观测：记录所有调用参数（便于验证）
- 不联网：不发起真实 ZMQ 连接
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import numpy as np


# ============================================================
# 1. 确定性算法函数
# ============================================================
def deterministic_algorithm(
    xyz: np.ndarray, meta: dict[str, Any]
) -> np.ndarray:
    """确定性 MATLAB 算法 Mock。

    根据输入点云生成确定的航点序列：
    - 取缺陷区域中心
    - 生成 10x10 网格航点
    - Z 坐标 = 缺陷最大 Z + 层高

    相同输入永远产生相同输出（无随机性）。
    """
    if len(xyz) == 0:
        return np.zeros((0, 3), dtype=np.float32)

    # 取点云 XY 范围
    xmin, ymin = float(np.min(xyz[:, 0])), float(np.min(xyz[:, 1]))
    xmax, ymax = float(np.max(xyz[:, 0])), float(np.max(xyz[:, 1]))
    z_max = float(np.max(xyz[:, 2]))

    # 10x10 网格航点
    n = 10
    xs = np.linspace(xmin, xmax, n)
    ys = np.linspace(ymin, ymax, n)

    # Zig-Zag 扫描
    waypoints = []
    z_layer = z_max + 2.0  # 层高 2mm
    for i, y in enumerate(ys):
        row_xs = xs if i % 2 == 0 else xs[::-1]
        for x in row_xs:
            waypoints.append([float(x), float(y), z_layer])

    return np.array(waypoints, dtype=np.float32)


# ============================================================
# 2. MockMatlabAdapter — 替代 MatlabAdapter
# ============================================================
class MockMatlabAdapter:
    """MATLAB 适配器 Mock。

    模拟 MatlabAdapter 的核心接口，但：
    - 不启动 matlab.engine
    - 不发起 ZMQ 连接
    - handle_repair 返回确定结果
    - 记录所有调用（便于断言）

    用法：
        adapter = MockMatlabAdapter()
        result = adapter.handle_repair(request)
        assert adapter.call_count == 1
    """

    SERVICE_VERSION = "mock-matlab-1.0.0"

    def __init__(
        self,
        algorithm_fn: Optional[Callable[..., np.ndarray]] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self._algorithm_fn = algorithm_fn or deterministic_algorithm
        self._latency_ms = latency_ms
        self._call_count = 0
        self._calls: list[dict[str, Any]] = []
        self._shutdown = False

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def calls(self) -> list[dict[str, Any]]:
        """所有调用的记录（含参数）。"""
        return list(self._calls)

    def handle_repair(self, request: Any) -> dict[str, Any]:
        """模拟 MatlabAdapter.handle_repair。

        返回 dict（而非 RepairResult），便于不依赖 protobuf 的测试使用。
        """
        if self._shutdown:
            raise RuntimeError("MockMatlabAdapter 已关闭")

        self._call_count += 1
        call_record = {
            "request_id": getattr(request, "request_id", "unknown"),
            "timestamp": time.time(),
            "point_count": 0,
        }

        # 模拟延迟
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)

        # 解析点云
        try:
            from repair_app.bridge.communication.serializer import Serializer
            xyz, normals, meta = Serializer.parse_point_cloud(request)
            call_record["point_count"] = len(xyz)
        except Exception:
            xyz = np.zeros((0, 3), dtype=np.float32)
            meta = {}

        self._calls.append(call_record)

        # 空点云 → 错误
        if len(xyz) == 0:
            return {
                "waypoints": np.zeros((0, 3), dtype=np.float32),
                "status_code": 1,  # ERR_INVALID_INPUT
                "error_message": "空点云",
                "request_id": call_record["request_id"],
                "compute_time_ms": 0.0,
            }

        # 调用确定性算法
        t0 = time.time()
        waypoints = self._algorithm_fn(xyz, meta)
        elapsed_ms = (time.time() - t0) * 1000.0

        return {
            "waypoints": waypoints,
            "status_code": 0,  # SUCCESS
            "error_message": "",
            "request_id": call_record["request_id"],
            "compute_time_ms": elapsed_ms,
            "point_count": len(xyz),
            "waypoint_count": len(waypoints),
        }

    def check_health(self) -> dict[str, Any]:
        """模拟健康检查。"""
        return {
            "status": "OK",
            "service_version": self.SERVICE_VERSION,
            "memory_usage_mb": 128.0,
            "uptime_s": 60.0,
            "pending_requests": 0,
        }

    def shutdown(self) -> None:
        """关闭 Mock。"""
        self._shutdown = True


# ============================================================
# 3. make_mock_repair_request — 构造测试请求
# ============================================================
def make_mock_repair_request(
    n_points: int = 100,
    request_id: str = "test-req-001",
    include_normals: bool = True,
) -> "RepairRequest":
    """构造测试用 RepairRequest（protobuf 消息）。

    Args:
        n_points: 点云数量
        request_id: 请求 ID
        include_normals: 是否包含法向量
    """
    from repair_app.communication.repair_protocol_pb2 import RepairRequest

    rng = np.random.default_rng(42)
    xyz = rng.uniform(-5, 5, (n_points, 3)).astype(np.float32)

    req = RepairRequest()
    req.x.extend(xyz[:, 0].tolist())
    req.y.extend(xyz[:, 1].tolist())
    req.z.extend(xyz[:, 2].tolist())

    if include_normals:
        normals = np.zeros((n_points, 3), dtype=np.float32)
        normals[:, 2] = 1.0  # 默认 Z 方向
        req.nx.extend(normals[:, 0].tolist())
        req.ny.extend(normals[:, 1].tolist())
        req.nz.extend(normals[:, 2].tolist())

    req.request_id = request_id
    req.client_version = "test-1.0"
    req.scan_id = "test-scan-001"
    req.timestamp_ms = int(time.time() * 1000)
    req.max_layers = 3

    return req


def make_empty_request(request_id: str = "empty-req") -> "RepairRequest":
    """构造空点云请求（用于错误路径测试）。"""
    from repair_app.communication.repair_protocol_pb2 import RepairRequest
    req = RepairRequest()
    req.request_id = request_id
    return req
