"""
repair_engine_service.py — Python 黑盒服务端原型

用途：在 MATLAB 服务端完成前，提供与 UI/ZMQ 相同协议的端到端联调服务。
"""

from __future__ import annotations
import argparse
import logging
import time
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

from repair_app.core.path_planner import plan_path_from_cloud
from repair_app.communication.repair_protocol_pb2 import (
    HealthCheckRequest,
    HealthCheckResponse,
    RepairRequest,
    RepairStatusCode,
)
from repair_app.communication.repair_serialization import (
    build_repair_result,
    deserialize_request,
    parse_point_cloud,
    serialize_result,
)

try:
    import zmq
    _ZMQ_AVAILABLE = True
except ImportError:
    _ZMQ_AVAILABLE = False
    zmq = None


from repair_app.platform.transport import get_zmq_address_from_env
DEFAULT_ADDRESS = get_zmq_address_from_env()


@dataclass
class EngineStats:
    started_at: float
    handled_requests: int = 0


def _try_parse_health(data: bytes) -> HealthCheckRequest | None:
    msg = HealthCheckRequest()
    try:
        msg.ParseFromString(data)
    except Exception as e:
        from repair_app.utils.logger_config import warning as _log_warning
        _log_warning(f"Protobuf 健康检查解析失败: {e}")
        return None
    return msg if msg.client_version else None


def _build_health_response(stats: EngineStats) -> bytes:
    msg = HealthCheckResponse()
    msg.status = HealthCheckResponse.OK
    msg.service_version = "python-prototype-0.1"
    msg.memory_usage_mb = 0.0
    msg.uptime_s = int(time.time() - stats.started_at)
    msg.pending_requests = 0
    return msg.SerializeToString()


def _selection_mask_from_request(xyz: np.ndarray) -> np.ndarray:
    if len(xyz) == 0:
        return np.zeros((0,), dtype=bool)
    return np.ones(len(xyz), dtype=bool)


def handle_repair_request(request: RepairRequest) -> bytes:
    started = time.time()
    try:
        xyz, _normals, meta = parse_point_cloud(request)
        if len(xyz) == 0:
            result = build_repair_result(
                np.zeros((0, 3), dtype=np.float32),
                request_id=request.request_id,
                status_code=RepairStatusCode.ERR_INVALID_INPUT,
                error_message="空点云请求",
                is_feasible=False,
                feasibility_reason="输入点云为空",
            )
            return serialize_result(result)

        defect_mask = _selection_mask_from_request(xyz)
        waypoints = plan_path_from_cloud(
            xyz=xyz,
            defect_mask=defect_mask,
            layer_height=meta.get("layer_height_mm", 2.0),
            scanning_angle=meta.get("scanning_angle_deg", -45.0),
            scanning_step=meta.get("scanning_step_mm", 2.0),
            buffer_mm=meta.get("buffer_repairing_mm", 0.0),
            n_layers=max(int(meta.get("num_layers", 5) or 5), 1),
        )

        if len(waypoints) == 0:
            result = build_repair_result(
                waypoints,
                request_id=request.request_id,
                status_code=RepairStatusCode.ERR_NO_DEFECT_FOUND,
                error_message="未生成航点",
                is_feasible=False,
                feasibility_reason="路径规划输出为空",
            )
            return serialize_result(result)

        path_length = float(np.sum(np.linalg.norm(np.diff(waypoints[:, :3], axis=0), axis=1)))
        speed = max(float(meta.get("traversing_speed_mms", 500.0)), 1e-6)
        elapsed_ms = int((time.time() - started) * 1000)
        result = build_repair_result(
            waypoints,
            request_id=request.request_id,
            status_code=RepairStatusCode.SUCCESS,
            estimated_time_s=path_length / speed,
            compute_time_ms=elapsed_ms,
            uniformity_score=0.75,
            is_feasible=True,
            feasibility_reason="Python prototype path generated",
        )
        return serialize_result(result)
    except Exception as exc:
        result = build_repair_result(
            np.zeros((0, 3), dtype=np.float32),
            request_id=request.request_id,
            status_code=RepairStatusCode.ERR_ALGORITHM_FAIL,
            error_message=str(exc),
            is_feasible=False,
            feasibility_reason=str(exc),
            compute_time_ms=int((time.time() - started) * 1000),
        )
        return serialize_result(result)


def handle_message(data: bytes, stats: EngineStats) -> bytes:
    health = _try_parse_health(data)
    if health is not None:
        return _build_health_response(stats)
    request = deserialize_request(data)
    stats.handled_requests += 1
    return handle_repair_request(request)


def serve(address: str = DEFAULT_ADDRESS) -> None:
    if not _ZMQ_AVAILABLE:
        raise RuntimeError("pyzmq 未安装，无法启动服务")
    stats = EngineStats(started_at=time.time())
    context = zmq.Context.instance()
    socket = context.socket(zmq.REP)
    # SECURITY NOTE (V1.0 known issue #SEC-1): bind() 未设置访问控制，本地任意进程可连接此 socket。
    # 单用户工作站部署下为已知可接受风险；多用户主机应在 V1.1 配置 ZAP 域认证。详见 Release Notes。
    socket.bind(address)
    logger.info("Python repair engine listening at %s", address)
    try:
        while True:
            data = socket.recv()
            socket.send(handle_message(data, stats))
    finally:
        socket.close(linger=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Python repair engine prototype")
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    args = parser.parse_args()
    serve(args.address)


if __name__ == "__main__":
    main()
