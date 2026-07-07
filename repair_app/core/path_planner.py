"""
path_planner.py — 冷喷涂路径规划（Python 原型）
基于路径规划 MATLAB 代码翻译：model_process → layer_slice → generate_path
"""

from __future__ import annotations
import numpy as np
from typing import Iterator

try:
    from shapely.geometry import Polygon, Point, MultiPolygon
    from shapely.ops import unary_union
    _SHAPELY = True
except ImportError:
    _SHAPELY = False
    Polygon = None


def model_process(
    triangles: np.ndarray,
    model_scale: float = 1.0,
    tol: float = 1e-8,
    base_plane: float = 5.0,
):
    """模型预处理：缩放 → 计算属性 → 分类 additive/repairing。

    triangles: N×12 [x1,y1,z1, x2,y2,z2, x3,y3,z3, nx,ny,nz]
    返回: (all_triangles(N×15), additive_cluster, repairing_clusters, x_min, x_max, y_min, y_max)
    """
    tris = triangles.copy()
    if model_scale != 1.0:
        tris = tris * model_scale

    # 计算 min_z, max_z
    min_z = np.min(tris[:, [2, 5, 8]], axis=1)
    max_z = np.max(tris[:, [2, 5, 8]], axis=1)

    tris = np.column_stack([tris, min_z, max_z])

    # 移除平行于切片平面的三角面
    parallel = (max_z - min_z) <= tol
    tris = tris[~parallel]

    min_z = tris[:, 12]
    max_z = tris[:, 13]

    # 计算面倾角
    nx, ny, nz = tris[:, 9], tris[:, 10], tris[:, 11]
    angle = np.degrees(np.arctan2(np.sqrt(nx**2 + ny**2), np.abs(nz) + 1e-10))
    all_tris = np.column_stack([tris, angle])

    # 包围盒
    x_min = float(np.min(tris[:, [0, 3, 6]]))
    x_max = float(np.max(tris[:, [0, 3, 6]]))
    y_min = float(np.min(tris[:, [1, 4, 7]]))
    y_max = float(np.max(tris[:, [1, 4, 7]]))

    # 分类
    additive = all_tris[all_tris[:, 13] >= base_plane]
    repairing = all_tris[all_tris[:, 12] <= base_plane]

    return all_tris, additive, repairing, x_min, x_max, y_min, y_max


def layer_slice(
    tris: np.ndarray,
    layer_height: float = 2.0,
    base_plane: float = 5.0,
    mode: str = "additive",
):
    """对三角面集进行切片，返回每层的截面多边形。

    返回: list of (z_height, polygon_2d_contour)
    """
    if len(tris) == 0:
        return []

    min_z = float(np.min(tris[:, 12])) + 1e-4
    max_z = float(np.max(tris[:, 13])) + 1e-4

    eps = 1e-9
    if mode == "repairing":
        slices = np.arange(min_z, base_plane - layer_height + 1e-4 + eps, layer_height)
    else:
        slices = np.arange(base_plane + 1e-4, max_z - layer_height + 1e-4 + eps, layer_height)

    layers = []
    for z in slices:
        contour = _intersect_triangles_with_plane(tris, z)
        if contour is not None and len(contour) >= 3:
            layers.append((z, contour))
    return layers


def _intersect_triangles_with_plane(tris: np.ndarray, z: float):
    """三角面与水平面 z 求交 → 截面轮廓点（向量化实现）。"""
    p = tris[:, 0:3]
    q = tris[:, 3:6]
    r = tris[:, 6:9]

    edges = [(p, q), (q, r), (r, p)]
    all_points = []
    for a, b in edges:
        za, zb = a[:, 2], b[:, 2]
        mask = (za - z) * (zb - z) < 0
        if np.any(mask):
            t = (z - za[mask]) / (zb[mask] - za[mask] + 1e-12)
            t = t[:, np.newaxis]
            pts = a[mask] + t * (b[mask] - a[mask])
            all_points.append(pts[:, :2])

    if len(all_points) == 0:
        return None
    pts = np.vstack(all_points)
    if len(pts) < 3:
        return None
    return pts[np.unique(pts.round(decimals=6), axis=0, return_index=True)[1]]


def generate_path(
    layerlist: list,
    buffer: float = 2.0,
    scanning_angle: float = -45.0,
    scanning_step: float = 2.0,
    edge_step_size: float = 2.0,
    tilt_angle: float = 60.0,
):
    """生成 Zig-Zag 填充路径 + 边缘补偿路径。

    layerlist: [(z_height, contour_2d), ...]
    返回: pointlist (N×6), velocitylist (N,)
    """
    pointlist = []
    velocitylist = []

    for layer_idx, (z_slice, contour) in enumerate(layerlist):
        pts, vels = _process_layer(
            z_slice, contour, buffer, scanning_angle,
            scanning_step, edge_step_size, tilt_angle,
        )
        if len(pts) > 0:
            pointlist.append(pts)
            velocitylist.extend(vels)

    if len(pointlist) == 0:
        return np.zeros((0, 6)), np.array([])

    result = np.vstack(pointlist)
    return result, np.array(velocitylist)


def _process_layer(
    z_slice: float,
    contour,
    buffer: float,
    scanning_angle: float,
    scanning_step: float,
    edge_step_size: float,
    tilt_angle: float,
) -> tuple[np.ndarray, list[str]]:
    """处理单层截面：内缩 buffer 后生成扫描填充和边缘补偿。"""
    if _SHAPELY:
        try:
            poly = Polygon(contour)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                return np.zeros((0, 6)), []
        except Exception:
            return np.zeros((0, 6)), []
    else:
        poly = contour  # 直接使用 numpy 数组

    # 内缩 buffer
    if _SHAPELY:
        inner = poly.buffer(-buffer)
        if inner.is_empty:
            inner = poly
    else:
        inner = poly  # numpy: 直接使用原始轮廓

    pointlist = []
    velocitylist = []

    # Zig-Zag 扫描线
    infill_pts = _generate_zigzag(inner, scanning_angle, scanning_step, z_slice)
    if len(infill_pts) > 0:
        pointlist.append(infill_pts)
        velocitylist.extend(["v500"] * len(infill_pts))

    # 边缘补偿（additive 层）
    edge_pts = _generate_edge(inner, poly, edge_step_size, z_slice, tilt_angle)
    if len(edge_pts) > 0:
        pointlist.append(edge_pts)
        velocitylist.extend(["v300"] * len(edge_pts))

    if not pointlist:
        return np.zeros((0, 6)), []
    return np.vstack(pointlist), velocitylist


def _generate_zigzag(
    poly,
    angle_deg: float,
    step: float,
    z: float,
) -> np.ndarray:
    """Zig-Zag 扫描线填充。"""
    if _SHAPELY and hasattr(poly, 'is_empty') and poly.is_empty:
        return np.zeros((0, 6))
    if not _SHAPELY and len(poly) < 3:
        return np.zeros((0, 6))

    # 旋转多边形使扫描方向对齐 X 轴
    rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(rad), np.sin(rad)

    # 获取旋转后的包围盒
    if _SHAPELY:
        coords = np.array(poly.exterior.coords)
    else:
        coords = np.array(poly)
    rx = cos_a * coords[:, 0] + sin_a * coords[:, 1]
    ry = -sin_a * coords[:, 0] + cos_a * coords[:, 1]

    y_min, y_max = np.min(ry), np.max(ry)

    points_all = []
    y = y_min + step / 2
    reverse = False

    while y < y_max:
        scanline = _intersect_scanline(poly, angle_deg, y)
        if scanline is not None and len(scanline) >= 2:
            xs = sorted(scanline)
            n_pts = max(2, int((xs[-1] - xs[0]) / step * 3))
            line_x = np.linspace(xs[0], xs[-1], n_pts)
            if reverse:
                line_x = line_x[::-1]

            # 旋转回原坐标系
            for x in line_x:
                world_x = cos_a * x - sin_a * y
                world_y = sin_a * x + cos_a * y
                points_all.append([world_x, world_y, z, 0, 0, 1])

            reverse = not reverse
        y += step

    return np.array(points_all) if points_all else np.zeros((0, 6))


def _intersect_scanline(poly: Polygon, angle_deg: float, y: float):
    """计算旋转后扫描线 y=const 与多边形的交点。"""
    rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(rad), np.sin(rad)

    if _SHAPELY:
        coords = np.array(poly.exterior.coords)
    else:
        coords = np.array(poly)
    rx = cos_a * coords[:, 0] + sin_a * coords[:, 1]
    ry = -sin_a * coords[:, 0] + cos_a * coords[:, 1]

    hits = []
    for i in range(len(ry) - 1):
        y1, y2 = ry[i], ry[i + 1]
        if (y1 - y) * (y2 - y) < 0:
            t = (y - y1) / (y2 - y1 + 1e-12)
            hits.append(rx[i] + t * (rx[i + 1] - rx[i]))

    return sorted(hits) if hits else None


def _generate_edge(
    inner_poly: Polygon,
    outer_poly: Polygon,
    step_size: float,
    z: float,
    tilt_angle: float,
) -> np.ndarray:
    """边缘补偿路径：沿外轮廓偏移。"""
    if _SHAPELY and outer_poly.is_empty:
        return np.zeros((0, 6))

    if _SHAPELY:
        coords = np.array(outer_poly.exterior.coords)
        n = max(3, int(outer_poly.length / step_size))
    else:
        coords = np.array(outer_poly)
        length = np.sum(np.sqrt(np.sum(np.diff(coords, axis=0)**2, axis=1)))
        n = max(3, int(length / step_size))
    sampled = _resample_contour(coords, n)

    pts = []
    tilt_norm = np.tan(np.radians(tilt_angle))
    for x, y in sampled:
        pts.append([x, y, z, 0, 0, 1])
    return np.array(pts) if pts else np.zeros((0, 6))


def _resample_contour(coords: np.ndarray, n: int) -> np.ndarray:
    """等弧长重采样轮廓。"""
    if len(coords) < 2:
        return coords
    dists = np.sqrt(np.sum(np.diff(coords, axis=0)**2, axis=1))
    cum = np.concatenate([[0], np.cumsum(dists)])
    total = cum[-1]
    if total < 1e-6:
        return coords[:n]
    new_u = np.linspace(0, total, n, endpoint=False)
    new_x = np.interp(new_u, cum, coords[:, 0])
    new_y = np.interp(new_u, cum, coords[:, 1])
    return np.column_stack([new_x, new_y])


def plan_path_from_stl(
    stl_path: str,
    layer_height: float = 2.0,
    scanning_angle: float = -45.0,
    scanning_step: float = 2.0,
    buffer_additive: float = 2.0,
    buffer_repairing: float = 0.0,
    edge_step_size: float = 2.0,
    tilt_angle: float = 60.0,
    base_plane: float = 5.0,
) -> tuple[np.ndarray, np.ndarray]:
    """从 STL 文件直接生成修复路径航点。

    返回: (pointlist(N×6), velocitylist(N,))
    """
    from repair_app.core.stl_reader import read_stl_file
    triangles = read_stl_file(stl_path)
    all_tris, additive, repairing, xmin, xmax, ymin, ymax = model_process(
        triangles, tol=1e-8, base_plane=base_plane
    )

    # 切片
    add_layers = layer_slice(additive, layer_height, base_plane, "additive")
    rep_layers = layer_slice(repairing, layer_height, base_plane, "repairing")

    # 合并层（先 repair 后 additive）
    all_layers = rep_layers + add_layers
    is_repair = [True] * len(rep_layers) + [False] * len(add_layers)

    pointlist_all = []
    velocitylist_all = []

    for i, (z, contour) in enumerate(all_layers):
        buf = buffer_repairing if is_repair[i] else buffer_additive
        pl, vl = generate_path(
            [(z, contour)], buffer=buf,
            scanning_angle=scanning_angle,
            scanning_step=scanning_step,
            edge_step_size=edge_step_size,
            tilt_angle=tilt_angle,
        )
        if len(pl) > 0:
            pointlist_all.append(pl)
            velocitylist_all.extend(vl)

    if len(pointlist_all) == 0:
        return np.zeros((0, 6)), np.array([])

    return np.vstack(pointlist_all), np.array(velocitylist_all)


def plan_path_from_cloud(
    xyz: np.ndarray,
    defect_mask: np.ndarray,
    layer_height: float = 2.0,
    scanning_angle: float = -45.0,
    scanning_step: float = 2.0,
    buffer_mm: float = 2.0,
    n_layers: int = 5,
) -> np.ndarray:
    """从点云 + 缺陷 mask 直接生成修复路径（简化版，不需要 STL）。

    返回: waypoints (N×3)
    """
    last_waypoints = np.zeros((0, 3))
    for partial_waypoints in iter_path_from_cloud(
        xyz=xyz,
        defect_mask=defect_mask,
        layer_height=layer_height,
        scanning_angle=scanning_angle,
        scanning_step=scanning_step,
        buffer_mm=buffer_mm,
        n_layers=n_layers,
    ):
        last_waypoints = partial_waypoints
    return last_waypoints


def iter_path_from_cloud(
    xyz: np.ndarray,
    defect_mask: np.ndarray,
    layer_height: float = 2.0,
    scanning_angle: float = -45.0,
    scanning_step: float = 2.0,
    buffer_mm: float = 2.0,
    n_layers: int = 5,
) -> Iterator[np.ndarray]:
    """逐层生成路径，并在每层完成后返回当前累计航点。"""
    if not np.any(defect_mask):
        return

    defect_pts = xyz[defect_mask]
    x_min, y_min = np.min(defect_pts[:, :2], axis=0)
    x_max, y_max = np.max(defect_pts[:, :2], axis=0)
    z_base = float(np.max(defect_pts[:, 2]))

    x_min -= buffer_mm; x_max += buffer_mm
    y_min -= buffer_mm; y_max += buffer_mm

    contour = np.array([
        [x_min, y_min], [x_max, y_min],
        [x_max, y_max], [x_min, y_max], [x_min, y_min],
    ])

    all_wp = []
    for layer in range(n_layers):
        z = z_base + layer * layer_height
        pl, _ = generate_path(
            [(z, contour)],
            buffer=0.0,
            scanning_angle=scanning_angle,
            scanning_step=scanning_step,
            edge_step_size=scanning_step,
        )
        if len(pl) > 0:
            all_wp.append(pl[:, :3])
            yield np.vstack(all_wp)
