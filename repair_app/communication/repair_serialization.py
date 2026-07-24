"""
repair_serialization.py — 冷喷涂缺陷修复软件 Protobuf 序列化工具模块
协议版本: 2026-06-v2.1
依赖: repair_protocol_pb2.py
"""

from __future__ import annotations

import time, json, os
from typing import Optional, Tuple, Dict, Any, List

import numpy as np

from repair_app.communication.repair_protocol_pb2 import (  # type: ignore[import-untyped]
    RepairRequest,
    RepairResult,
    HealthCheckRequest,
    HealthCheckResponse,
    MaterialType,
    RepairStatusCode,
    ParticleDistribution,
    LayerProfile,
    MaterialParams,
    CalibrationData,
    GCodeOutput,
    ProgressUpdate,
    ProgressEnvelope,
    ProgressEventType,
    MeshFrameKind,
)

# Protocol version for ZMQ communication with MATLAB server.
# Independent of application version (see config.py:APP_VERSION).
CLIENT_VERSION = "0.2.0"
MAX_ARRAY_LENGTH_WARN = 1_000_000


# ================================================================
# NumPy → RepairRequest（发送端）
# ================================================================

def build_repair_request(
    xyz: np.ndarray,
    normals: np.ndarray,
    scan_id: str,
    *,
    depth_compensation: float = 1.0,
    smooth_threshold: float = 0.5,
    max_layers: int = 5,
    material: "MaterialType.ValueType" = MaterialType.MATERIAL_UNSPECIFIED,
    # ---- v2.1 冷喷涂工艺参数 ----
    particle_velocity_ms: float = 500.0,
    critical_velocity_ms: float = 400.0,
    nozzle_diameter_mm: float = 6.0,
    spray_angle_deg: float = 90.0,
    standoff_distance_mm: float = 30.0,
    particle_size_um: float = 25.0,
    track_overlap_ratio: float = 0.5,
    traversing_speed_mms: float = 500.0,
    material_id: str = "",
    num_layers: int = 3,
    # ---- v2.1 路径规划参数 ----
    layer_height_mm: float = 2.0,
    scanning_angle_deg: float = -45.0,
    scanning_step_mm: float = 2.0,
    edge_step_size_mm: float = 2.0,
    tilt_angle_deg: float = 60.0,
    buffer_additive_mm: float = 2.0,
    buffer_repairing_mm: float = 0.0,
    link_path_free_dist_mm: float = 20.0,
    obstacle_resolution_mm: float = 2.0,
    request_id: Optional[str] = None,
) -> RepairRequest:
    """将 NumPy 点云数组构建为 RepairRequest 消息（v2.1 完整参数）。"""
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz 必须为 (N, 3) 形状，当前 = {xyz.shape}")
    if normals.ndim != 2 or normals.shape[1] != 3:
        raise ValueError(f"normals 必须为 (N, 3) 形状，当前 = {normals.shape}")
    if xyz.shape[0] != normals.shape[0]:
        raise ValueError(f"xyz 与 normals 行数不一致: {xyz.shape[0]} vs {normals.shape[0]}")
    N = xyz.shape[0]
    xyz = np.asarray(xyz, dtype=np.float32)
    normals = np.asarray(normals, dtype=np.float32)
    if N > MAX_ARRAY_LENGTH_WARN:
        import warnings
        warnings.warn(f"点云点数较大 ({N} 点)，序列化可能较慢", stacklevel=2)

    msg = RepairRequest()
    msg.x.extend(xyz[:, 0].tolist())
    msg.y.extend(xyz[:, 1].tolist())
    msg.z.extend(xyz[:, 2].tolist())
    msg.nx.extend(normals[:, 0].tolist())
    msg.ny.extend(normals[:, 1].tolist())
    msg.nz.extend(normals[:, 2].tolist())

    msg.scan_id = scan_id
    msg.timestamp_ms = int(time.time() * 1000)
    msg.depth_compensation = depth_compensation
    msg.smooth_threshold = smooth_threshold
    msg.max_layers = max_layers
    msg.material = material

    # v2.1 冷喷涂参数
    msg.particle_velocity_ms = particle_velocity_ms
    msg.critical_velocity_ms = critical_velocity_ms
    msg.nozzle_diameter_mm = nozzle_diameter_mm
    msg.spray_angle_deg = spray_angle_deg
    msg.standoff_distance_mm = standoff_distance_mm
    msg.particle_size_um = particle_size_um
    msg.track_overlap_ratio = track_overlap_ratio
    msg.traversing_speed_mms = traversing_speed_mms
    msg.material_id = material_id
    msg.num_layers = num_layers

    # v2.1 路径规划参数
    msg.layer_height_mm = layer_height_mm
    msg.scanning_angle_deg = scanning_angle_deg
    msg.scanning_step_mm = scanning_step_mm
    msg.edge_step_size_mm = edge_step_size_mm
    msg.tilt_angle_deg = tilt_angle_deg
    msg.buffer_additive_mm = buffer_additive_mm
    msg.buffer_repairing_mm = buffer_repairing_mm
    msg.link_path_free_dist_mm = link_path_free_dist_mm
    msg.obstacle_resolution_mm = obstacle_resolution_mm

    if request_id is None:
        request_id = f"{scan_id}-{msg.timestamp_ms}"
    msg.request_id = request_id
    msg.client_version = CLIENT_VERSION

    return msg


# ================================================================
# RepairRequest → NumPy（接收端 / MATLAB 黑盒侧）
# ================================================================

def parse_point_cloud(msg: RepairRequest) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """从 RepairRequest 消息中提取点云、元数据和所有 v2.1 参数。"""
    x = np.asarray(msg.x, dtype=np.float32)
    y = np.asarray(msg.y, dtype=np.float32)
    z = np.asarray(msg.z, dtype=np.float32)
    nx = np.asarray(msg.nx, dtype=np.float32)
    ny = np.asarray(msg.ny, dtype=np.float32)
    nz = np.asarray(msg.nz, dtype=np.float32)
    N = len(x)
    xyz = np.column_stack([x, y, z]) if N > 0 else np.empty((0, 3), dtype=np.float32)
    normals = np.column_stack([nx, ny, nz]) if N > 0 else np.empty((0, 3), dtype=np.float32)

    meta: Dict[str, Any] = {
        "scan_id": msg.scan_id,
        "timestamp_ms": msg.timestamp_ms,
        "point_count": N,
        "depth_compensation": msg.depth_compensation,
        "smooth_threshold": msg.smooth_threshold,
        "max_layers": msg.max_layers,
        "material": MaterialType.Name(msg.material),
        "request_id": msg.request_id,
        "client_version": msg.client_version,
        # v2.1 冷喷涂
        "particle_velocity_ms": msg.particle_velocity_ms,
        "critical_velocity_ms": msg.critical_velocity_ms,
        "nozzle_diameter_mm": msg.nozzle_diameter_mm,
        "spray_angle_deg": msg.spray_angle_deg,
        "standoff_distance_mm": msg.standoff_distance_mm,
        "particle_size_um": msg.particle_size_um,
        "track_overlap_ratio": msg.track_overlap_ratio,
        "traversing_speed_mms": msg.traversing_speed_mms,
        "material_id": msg.material_id,
        "num_layers": msg.num_layers,
        # v2.1 路径规划
        "layer_height_mm": msg.layer_height_mm,
        "scanning_angle_deg": msg.scanning_angle_deg,
        "scanning_step_mm": msg.scanning_step_mm,
        "edge_step_size_mm": msg.edge_step_size_mm,
        "tilt_angle_deg": msg.tilt_angle_deg,
        "buffer_additive_mm": msg.buffer_additive_mm,
        "buffer_repairing_mm": msg.buffer_repairing_mm,
        "link_path_free_dist_mm": msg.link_path_free_dist_mm,
        "obstacle_resolution_mm": msg.obstacle_resolution_mm,
    }
    return xyz, normals, meta


# ================================================================
# v2.1: ParticleDistribution 转换
# ================================================================

def build_particle_distribution(
    px: np.ndarray,
    py: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    temperature: Optional[np.ndarray] = None,
    diameter: Optional[np.ndarray] = None,
    vcr: Optional[np.ndarray] = None,
    dep_efficiency: float = 0.7,
) -> ParticleDistribution:
    """从 NumPy 数组构建 ParticleDistribution 消息。"""
    msg = ParticleDistribution()
    msg.px.extend(np.asarray(px, dtype=np.float32).tolist())
    msg.py.extend(np.asarray(py, dtype=np.float32).tolist())
    msg.vx.extend(np.asarray(vx, dtype=np.float32).tolist())
    msg.vy.extend(np.asarray(vy, dtype=np.float32).tolist())
    msg.vz.extend(np.asarray(vz, dtype=np.float32).tolist())
    if temperature is not None:
        msg.temperature.extend(np.asarray(temperature, dtype=np.float32).tolist())
    if diameter is not None:
        msg.diameter.extend(np.asarray(diameter, dtype=np.float32).tolist())
    if vcr is not None:
        msg.vcr.extend(np.asarray(vcr, dtype=np.float32).tolist())
    msg.dep_efficiency = dep_efficiency
    msg.total_particles = len(px)
    return msg


def parse_particle_distribution(msg: ParticleDistribution) -> Dict[str, Any]:
    """从 ParticleDistribution 消息提取 NumPy 数组。"""
    return {
        "px": np.asarray(msg.px, dtype=np.float32),
        "py": np.asarray(msg.py, dtype=np.float32),
        "vx": np.asarray(msg.vx, dtype=np.float32),
        "vy": np.asarray(msg.vy, dtype=np.float32),
        "vz": np.asarray(msg.vz, dtype=np.float32),
        "temperature": np.asarray(msg.temperature, dtype=np.float32),
        "diameter": np.asarray(msg.diameter, dtype=np.float32),
        "vcr": np.asarray(msg.vcr, dtype=np.float32),
        "dep_efficiency": msg.dep_efficiency,
        "total_particles": msg.total_particles,
    }


# ================================================================
# v2.1: LayerProfile 转换
# ================================================================

def build_layer_profile(
    layer_index: int,
    *,
    max_height_mm: float = 0.0,
    avg_height_mm: float = 0.0,
    dep_efficiency: float = 0.0,
    heightmap_png: bytes = b"",
    contour_geojson: bytes = b"",
) -> LayerProfile:
    """构建单层沉积轮廓消息（标量指标；图像/GeoJSON 可选）。"""
    msg = LayerProfile()
    msg.layer_index = int(layer_index)
    msg.max_height_mm = float(max_height_mm)
    msg.avg_height_mm = float(avg_height_mm)
    msg.dep_efficiency = float(dep_efficiency)
    if heightmap_png:
        msg.heightmap_png = heightmap_png
    if contour_geojson:
        msg.contour_geojson = contour_geojson
    return msg


def parse_layer_profiles(msg: RepairResult) -> List[Dict[str, Any]]:
    """从 RepairResult 中提取逐层轮廓列表。"""
    profiles = []
    for lp in msg.layer_profiles:
        profiles.append({
            "layer_index": lp.layer_index,
            "heightmap_png": lp.heightmap_png,
            "contour_geojson": lp.contour_geojson,
            "max_height_mm": lp.max_height_mm,
            "avg_height_mm": lp.avg_height_mm,
            "dep_efficiency": lp.dep_efficiency,
        })
    return profiles


# ================================================================
# v2.1: ProgressUpdate 转换
# ================================================================

def build_progress_update(
    request_id: str,
    stage: "ProgressUpdate.Stage.ValueType",
    *,
    layer_index: int = 0,
    total_layers: int = 0,
    progress: float = 0.0,
    message: str = "",
    waypoints: Optional[np.ndarray] = None,
    layer_profiles: Optional[List[LayerProfile]] = None,
    partial_mesh_data: bytes = b"",
    partial_mesh_format: str = "",
) -> ProgressUpdate:
    """构建计算中间态消息，用于 UI 实时刷新。"""
    msg = ProgressUpdate()
    msg.request_id = request_id
    msg.stage = stage
    msg.layer_index = layer_index
    msg.total_layers = total_layers
    msg.progress = float(np.clip(progress, 0.0, 1.0))
    msg.message = message
    if partial_mesh_data:
        msg.partial_mesh_data = partial_mesh_data
        msg.partial_mesh_format = partial_mesh_format

    if waypoints is not None:
        wp_arr = np.asarray(waypoints, dtype=np.float32)
        for row in wp_arr:
            wp = msg.partial_waypoints.add()
            wp.x = float(row[0])
            wp.y = float(row[1])
            wp.z = float(row[2])
            if len(row) >= 6:
                wp.nx = float(row[3])
                wp.ny = float(row[4])
                wp.nz = float(row[5])
            else:
                wp.nz = 1.0
            if len(row) >= 7:
                wp.feed_rate = float(row[6])
            wp.layer_index = layer_index

    if layer_profiles:
        msg.layer_profiles.extend(layer_profiles)
    return msg


def parse_progress_update(msg: ProgressUpdate) -> Dict[str, Any]:
    """从 ProgressUpdate 提取 UI 可用的中间态数据。"""
    n_wp = len(msg.partial_waypoints)
    waypoints = np.empty((n_wp, 7), dtype=np.float32)
    waypoint_layers = np.empty((n_wp,), dtype=np.int32)
    for i, wp in enumerate(msg.partial_waypoints):
        waypoints[i] = [wp.x, wp.y, wp.z, wp.nx, wp.ny, wp.nz, wp.feed_rate]
        waypoint_layers[i] = wp.layer_index

    return {
        "request_id": msg.request_id,
        "stage": msg.stage,
        "stage_name": ProgressUpdate.Stage.Name(msg.stage),
        "layer_index": msg.layer_index,
        "total_layers": msg.total_layers,
        "progress": msg.progress,
        "message": msg.message,
        "waypoints": waypoints,
        "waypoint_layers": waypoint_layers,
        "partial_mesh_data": msg.partial_mesh_data,
        "partial_mesh_format": msg.partial_mesh_format,
        "layer_profiles": [
            {
                "layer_index": lp.layer_index,
                "heightmap_png": lp.heightmap_png,
                "contour_geojson": lp.contour_geojson,
                "max_height_mm": lp.max_height_mm,
                "avg_height_mm": lp.avg_height_mm,
                "dep_efficiency": lp.dep_efficiency,
            }
            for lp in msg.layer_profiles
        ],
    }


def build_progress_envelope(
    operation_id: str,
    event_type: "ProgressEventType.ValueType",
    sequence_number: int,
    *,
    layer_index: int = 0,
    total_layers: int = 0,
    progress: float = 0.0,
    message: str = "",
    elapsed_s: float = 0.0,
    waypoints: Optional[np.ndarray] = None,
    segment_index: int = 0,
    mesh_data: bytes = b"",
    mesh_format: str = "stl_binary",
    mesh_frame_kind: "MeshFrameKind.ValueType" = MeshFrameKind.MESH_FRAME_UNSPECIFIED,
    triangle_count: int = 0,
    layer_max_height_mm: float = 0.0,
    layer_avg_height_mm: float = 0.0,
    layer_dep_efficiency: float = 0.0,
    error_code: str = "",
    error_message: str = "",
    retryable: bool = False,
) -> ProgressEnvelope:
    """Build the v3 realtime event envelope.

    Preview mesh messages are complete, independently decodable snapshots.
    Path-layer payloads are incremental and must be accumulated by layer index.
    """
    msg = ProgressEnvelope()
    msg.schema_version = 3
    msg.operation_id = str(operation_id)
    msg.sequence_number = max(0, int(sequence_number))
    msg.timestamp_ms = int(time.time() * 1000)
    msg.event_type = int(event_type)
    msg.layer_index = int(layer_index)
    msg.total_layers = int(total_layers)
    msg.progress = float(np.clip(progress, 0.0, 1.0))
    msg.message = str(message)
    msg.elapsed_s = float(elapsed_s)

    if error_code or error_message:
        msg.error.code = str(error_code)
        msg.error.message = str(error_message)
        msg.error.retryable = bool(retryable)

    if mesh_data:
        snapshot = msg.mesh_snapshot
        snapshot.mesh_data = bytes(mesh_data)
        snapshot.mesh_format = str(mesh_format or "stl_binary")
        snapshot.frame_kind = int(mesh_frame_kind)
        snapshot.triangle_count = max(0, int(triangle_count))
        snapshot.layer_max_height_mm = float(layer_max_height_mm)
        snapshot.layer_avg_height_mm = float(layer_avg_height_mm)
        snapshot.layer_dep_efficiency = float(layer_dep_efficiency)
    elif waypoints is not None:
        target = (
            msg.path_segment.waypoints
            if event_type == ProgressEventType.PROGRESS_PATH_SEGMENT_READY
            else msg.path_layer.waypoints
        )
        if event_type == ProgressEventType.PROGRESS_PATH_SEGMENT_READY:
            msg.path_segment.segment_index = int(segment_index)
        wp_arr = np.asarray(waypoints, dtype=np.float32)
        if wp_arr.ndim == 1 and wp_arr.size:
            wp_arr = wp_arr.reshape(1, -1)
        for row in wp_arr:
            wp = target.add()
            wp.x = float(row[0])
            wp.y = float(row[1])
            wp.z = float(row[2])
            wp.nx = float(row[3]) if len(row) >= 4 else 0.0
            wp.ny = float(row[4]) if len(row) >= 5 else 0.0
            wp.nz = float(row[5]) if len(row) >= 6 else 1.0
            wp.feed_rate = float(row[6]) if len(row) >= 7 else 0.0
            wp.layer_index = int(layer_index)
    else:
        msg.status.message = str(message)
        msg.status.elapsed_s = float(elapsed_s)

    return msg


def parse_progress_envelope(msg: ProgressEnvelope) -> Dict[str, Any]:
    """Convert a v3 realtime envelope into the UI's stable dictionary shape."""
    payload_name = msg.WhichOneof("payload") or ""
    mesh_data = b""
    mesh_format = ""
    mesh_frame_kind = MeshFrameKind.MESH_FRAME_UNSPECIFIED
    triangle_count = 0
    message = msg.message
    elapsed_s = msg.elapsed_s
    waypoints = np.empty((0, 7), dtype=np.float32)
    waypoint_layers = np.empty((0,), dtype=np.int32)

    if payload_name == "mesh_snapshot":
        mesh_data = msg.mesh_snapshot.mesh_data
        mesh_format = msg.mesh_snapshot.mesh_format
        mesh_frame_kind = msg.mesh_snapshot.frame_kind
        triangle_count = msg.mesh_snapshot.triangle_count
    elif payload_name in {"path_layer", "path_segment"}:
        payload = msg.path_layer if payload_name == "path_layer" else msg.path_segment
        n_wp = len(payload.waypoints)
        waypoints = np.empty((n_wp, 7), dtype=np.float32)
        waypoint_layers = np.full((n_wp,), msg.layer_index, dtype=np.int32)
        for i, wp in enumerate(payload.waypoints):
            waypoints[i] = [
                wp.x, wp.y, wp.z, wp.nx, wp.ny, wp.nz, wp.feed_rate,
            ]
    elif payload_name == "status":
        message = msg.status.message or message
        elapsed_s = msg.status.elapsed_s or elapsed_s

    return {
        "schema_version": int(msg.schema_version),
        "request_id": msg.operation_id,
        "operation_id": msg.operation_id,
        "sequence_number": int(msg.sequence_number),
        "timestamp_ms": int(msg.timestamp_ms),
        "event_type": int(msg.event_type),
        "event_name": ProgressEventType.Name(msg.event_type),
        "stage": int(msg.event_type),
        "stage_name": ProgressEventType.Name(msg.event_type),
        "layer_index": int(msg.layer_index),
        "total_layers": int(msg.total_layers),
        "progress": float(msg.progress),
        "message": message,
        "elapsed_s": float(elapsed_s),
        "waypoints": waypoints,
        "waypoint_layers": waypoint_layers,
        "partial_mesh_data": mesh_data,
        "partial_mesh_format": mesh_format,
        "mesh_frame_kind": int(mesh_frame_kind),
        "mesh_triangle_count": int(triangle_count),
        "layer_profiles": [],
        "error_code": msg.error.code,
        "error_message": msg.error.message,
        "retryable": bool(msg.error.retryable),
        "is_heartbeat": msg.event_type == ProgressEventType.PROGRESS_HEARTBEAT,
        "is_terminal": msg.event_type in {
            ProgressEventType.PROGRESS_COMPLETED,
            ProgressEventType.PROGRESS_FAILED,
            ProgressEventType.PROGRESS_CANCELLED,
        },
        "payload_name": payload_name,
    }


def parse_progress_message(data: bytes) -> Dict[str, Any]:
    """Decode v3 envelopes with a v2 ``ProgressUpdate`` fallback."""
    envelope = ProgressEnvelope()
    try:
        envelope.ParseFromString(data)
        if envelope.schema_version >= 3 and envelope.operation_id:
            return parse_progress_envelope(envelope)
    except Exception:
        pass

    legacy = ProgressUpdate()
    legacy.ParseFromString(data)
    if not legacy.request_id:
        raise ValueError("progress message has no operation/request id")
    parsed = parse_progress_update(legacy)
    parsed.update({
        "schema_version": 2,
        "operation_id": legacy.request_id,
        "sequence_number": 0,
        "event_type": 0,
        "event_name": "LEGACY_PROGRESS",
        "is_heartbeat": False,
        "is_terminal": legacy.stage == ProgressUpdate.COMPLETE,
        "payload_name": "legacy",
    })
    return parsed


# ================================================================
# v2.1: MaterialParams 加载器
# ================================================================

def load_material_params(material_id: str, db_path: Optional[str] = None) -> MaterialParams:
    """从 material_db.json 加载指定材料的参数。

    Args:
        material_id: 材料标识符，如 "Cu", "Al6061", "Ti64"
        db_path: 数据库 JSON 文件路径，默认项目根目录 material_db.json

    Returns:
        MaterialParams 消息对象。
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "material_db.json")

    if not os.path.exists(db_path):
        # 返回默认参数（铜）
        msg = MaterialParams()
        msg.material_id = material_id
        msg.material_name = material_id
        msg.density_gcm3 = 8.96
        msg.critical_velocity_ms = 400.0
        msg.dep_efficiency_max = 0.85
        msg.preheat_temp_c = 25.0
        msg.max_single_layer_mm = 3.0
        msg.min_track_width_mm = 2.0
        return msg

    with open(db_path, 'r', encoding='utf-8') as f:
        db = json.load(f)

    entry = db.get(material_id, db.get("DEFAULT", {}))
    msg = MaterialParams()
    msg.material_id = material_id
    msg.material_name = entry.get("name", material_id)
    msg.density_gcm3 = entry.get("density_gcm3", 8.96)
    msg.critical_velocity_ms = entry.get("critical_velocity_ms", 400.0)
    msg.dep_efficiency_max = entry.get("dep_efficiency_max", 0.85)
    msg.preheat_temp_c = entry.get("preheat_temp_c", 25.0)
    msg.max_single_layer_mm = entry.get("max_single_layer_mm", 3.0)
    msg.min_track_width_mm = entry.get("min_track_width_mm", 2.0)
    for angle in entry.get("vcr_curve_angle", []):
        msg.vcr_curve_angle.append(angle)
    for val in entry.get("vcr_curve_value", []):
        msg.vcr_curve_value.append(val)
    return msg


# ================================================================
# RepairResult 解析
# ================================================================

def build_repair_result(
    waypoints: np.ndarray,
    *,
    request_id: str = "",
    status_code: "RepairStatusCode.ValueType" = RepairStatusCode.SUCCESS,
    error_message: str = "",
    predicted_volume_mm3: float = 0.0,
    material_density_gcm3: float = 0.0,
    estimated_mass_g: float = 0.0,
    estimated_time_s: float = 0.0,
    compute_time_ms: int = 0,
    uniformity_score: float = 0.0,
    is_feasible: bool = True,
    feasibility_reason: str = "",
    layer_profiles: Optional[List[LayerProfile]] = None,
    particle_dist: Optional[ParticleDistribution] = None,
    before_snapshot_png: bytes = b"",
    after_snapshot_png: bytes = b"",
    mesh_data: bytes = b"",
    mesh_format: str = "",
) -> RepairResult:
    """从 NumPy 航点数组构建 RepairResult（含 v2.1 可视化字段）。

    可视化字段（layer_profiles / particle_dist / snapshots / mesh）为可选；
    传入时填充，不传则保持空，向后兼容。
    """
    msg = RepairResult()
    msg.request_id = request_id
    msg.status_code = status_code
    msg.error_message = error_message
    msg.predicted_volume_mm3 = predicted_volume_mm3
    msg.material_density_gcm3 = material_density_gcm3
    msg.estimated_mass_g = estimated_mass_g
    msg.estimated_time_s = estimated_time_s
    msg.compute_time_ms = int(compute_time_ms)
    msg.uniformity_score = uniformity_score
    msg.is_feasible = is_feasible
    msg.feasibility_reason = feasibility_reason

    # v2.1 可视化字段（仅在提供时填充）
    if layer_profiles:
        msg.layer_profiles.extend(layer_profiles)
    if particle_dist is not None:
        msg.particle_dist.CopyFrom(particle_dist)
    if before_snapshot_png:
        msg.before_snapshot_png = before_snapshot_png
    if after_snapshot_png:
        msg.after_snapshot_png = after_snapshot_png
    if mesh_data:
        msg.mesh_data = mesh_data
        msg.mesh_format = mesh_format or "stl_binary"

    wp_arr = np.asarray(waypoints, dtype=np.float32)
    for i, row in enumerate(wp_arr):
        wp = msg.waypoints.add()
        wp.x = float(row[0])
        wp.y = float(row[1])
        wp.z = float(row[2])
        if len(row) >= 6:
            wp.nx = float(row[3])
            wp.ny = float(row[4])
            wp.nz = float(row[5])
        else:
            wp.nz = 1.0
        wp.feed_rate = float(row[6]) if len(row) >= 7 else 0.0
        wp.layer_index = int(row[7]) if len(row) >= 8 else 0
    return msg

def parse_repair_result(msg: RepairResult) -> Dict[str, Any]:
    """从 RepairResult 消息提取所有字段（含 v2.1 新增）。"""
    N = len(msg.waypoints)
    if N > 0:
        waypoints = np.empty((N, 7), dtype=np.float32)
        layers = np.empty((N,), dtype=np.int32)
        for i, wp in enumerate(msg.waypoints):
            waypoints[i, 0] = wp.x
            waypoints[i, 1] = wp.y
            waypoints[i, 2] = wp.z
            waypoints[i, 3] = wp.nx
            waypoints[i, 4] = wp.ny
            waypoints[i, 5] = wp.nz
            waypoints[i, 6] = wp.feed_rate
            layers[i] = wp.layer_index
    else:
        waypoints = np.empty((0, 7), dtype=np.float32)
        layers = np.empty((0,), dtype=np.int32)

    result: Dict[str, Any] = {
        "status_code": msg.status_code,
        "status_name": RepairStatusCode.Name(msg.status_code),
        "error_message": msg.error_message,
        "compute_time_ms": msg.compute_time_ms,
        "request_id": msg.request_id,
        "waypoints": waypoints,
        "waypoint_layers": layers,
        "predicted_volume_mm3": msg.predicted_volume_mm3,
        "material_density_gcm3": msg.material_density_gcm3,
        "estimated_mass_g": msg.estimated_mass_g,
        "estimated_time_s": msg.estimated_time_s,
        "mesh_bytes": msg.mesh_data,
        "mesh_format": msg.mesh_format,
        # v2.1 新增
        "layer_profiles": parse_layer_profiles(msg),
        "particle_dist": parse_particle_distribution(msg.particle_dist) if msg.HasField("particle_dist") else None,
        "before_snapshot_png": msg.before_snapshot_png,
        "after_snapshot_png": msg.after_snapshot_png,
        "uniformity_score": msg.uniformity_score,
        "is_feasible": msg.is_feasible,
        "feasibility_reason": msg.feasibility_reason,
    }
    return result


# ================================================================
# 序列化 / 反序列化
# ================================================================

def serialize_request(msg: RepairRequest) -> bytes:
    return msg.SerializeToString()

def deserialize_request(data: bytes) -> RepairRequest:
    msg = RepairRequest()
    msg.ParseFromString(data)
    return msg

def serialize_result(msg: RepairResult) -> bytes:
    return msg.SerializeToString()

def deserialize_result(data: bytes) -> RepairResult:
    msg = RepairResult()
    msg.ParseFromString(data)
    return msg


# ================================================================
# 健康检查
# ================================================================

def build_health_check_request() -> HealthCheckRequest:
    msg = HealthCheckRequest()
    msg.client_version = CLIENT_VERSION
    return msg

def parse_health_check_response(msg_or_data) -> Dict[str, Any]:
    if isinstance(msg_or_data, (bytes, bytearray)):
        msg = HealthCheckResponse()
        msg.ParseFromString(bytes(msg_or_data))
    else:
        msg = msg_or_data
    return {
        "status": HealthCheckResponse.Status.Name(msg.status),
        "status_code": msg.status,
        "service_version": msg.service_version,
        "protocol_version": getattr(msg, "protocol_version", ""),
        "memory_usage_mb": msg.memory_usage_mb,
        "uptime_s": msg.uptime_s,
        "pending_requests": msg.pending_requests,
    }


# ================================================================
# 自检
# ================================================================

def self_test() -> bool:
    """验证 NumPy ↔ Protobuf 往返 + v2.1 新字段。"""
    N = 10_000
    rng = np.random.default_rng(42)

    xyz = (rng.random((N, 3), dtype=np.float32) * 200.0 - 100.0)
    normals = rng.random((N, 3), dtype=np.float32)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)

    # NumPy → Proto（含 v2.1 参数）
    request = build_repair_request(
        xyz, normals, scan_id="SELF_TEST-001",
        depth_compensation=1.2, smooth_threshold=0.3, max_layers=3,
        particle_velocity_ms=550.0, critical_velocity_ms=420.0,
        layer_height_mm=2.0, scanning_angle_deg=-45.0,
        material_id="Cu",
    )

    # Proto → Bytes → Proto
    raw = serialize_request(request)
    assert len(raw) > 0, "序列化结果为空"
    recovered = deserialize_request(raw)

    # Proto → NumPy
    xyz2, normals2, meta = parse_point_cloud(recovered)
    assert xyz2.shape == (N, 3)
    assert normals2.shape == (N, 3)
    np.testing.assert_array_almost_equal(xyz, xyz2, decimal=5)
    np.testing.assert_array_almost_equal(normals, normals2, decimal=5)
    assert meta["scan_id"] == "SELF_TEST-001"
    assert abs(meta["depth_compensation"] - 1.2) < 1e-6
    assert abs(meta["particle_velocity_ms"] - 550.0) < 1e-6
    assert abs(meta["critical_velocity_ms"] - 420.0) < 1e-6
    assert abs(meta["layer_height_mm"] - 2.0) < 1e-6
    assert abs(meta["scanning_angle_deg"] + 45.0) < 1e-6
    assert meta["material_id"] == "Cu"

    # v2.1: ParticleDistribution 往返
    pd = build_particle_distribution(
        px=np.array([0.0, 1.0, 2.0], dtype=np.float32),
        py=np.array([0.0, 0.5, 1.0], dtype=np.float32),
        vx=np.array([100.0, 200.0, 300.0], dtype=np.float32),
        vy=np.zeros(3, dtype=np.float32),
        vz=np.array([500.0, 500.0, 500.0], dtype=np.float32),
        dep_efficiency=0.75,
    )
    pd_raw = pd.SerializeToString()
    pd2 = ParticleDistribution()
    pd2.ParseFromString(pd_raw)
    parsed_pd = parse_particle_distribution(pd2)
    assert parsed_pd["total_particles"] == 3
    assert abs(parsed_pd["dep_efficiency"] - 0.75) < 1e-6

    # v2.1: MaterialParams 加载
    mp = load_material_params("Cu")
    assert mp.material_id == "Cu"
    assert mp.density_gcm3 > 0

    # 空点云边界
    empty_req = build_repair_request(
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        scan_id="EMPTY",
    )
    empty_xyz, empty_n, _ = parse_point_cloud(empty_req)
    assert empty_xyz.shape == (0, 3)

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("repair_serialization v2.1 自检")
    print("=" * 60)
    try:
        ok = self_test()
        print(f"\n✅ 全部通过 —— v2.1 协议往返精度无损（含冷喷涂+路径规划参数 + ParticleDistribution + MaterialParams）")
    except AssertionError as e:
        print(f"\n❌ 自检失败: {e}")
        raise
    except ImportError as e:
        print(f"\n⚠️  导入失败: {e}")
        print("   请确认 repair_protocol_pb2.py 已编译")
