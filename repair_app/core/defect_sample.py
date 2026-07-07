"""
defect_sample.py — 冷喷涂缺陷假数据生成（v2.1 工业零件风格）
矩形平板基体 + 凸台 + 坑洞/沟槽/划痕缺陷
"""

from __future__ import annotations
import numpy as np
from typing import Tuple, Optional


def generate_defect_sample(
    n_points: int = 12000,
    seed: int = 42,
    defect_types: Optional[list[str]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """生成矩形工业零件点云（论文配图风格）。

    零件：100×60mm 矩形平板基体 + 中央 40×30mm 凸台（h=8mm）
    缺陷：
    - "pit": 凸台表面圆形坑洞 (Φ10mm, d=3mm)
    - "groove": 凸台表面矩形沟槽 (8×15mm, d=4mm)
    - "scratch": 凸台表面划痕 (2×20mm)
    - "irregular": 凸台边缘不规则缺损

    Returns: (xyz, normals, defect_mask, defect_info)
    """
    if defect_types is None:
        defect_types = ["pit", "groove", "scratch"]

    rng = np.random.default_rng(seed)

    # 基体尺寸
    plate_w, plate_l = 100.0, 60.0   # X, Y
    boss_w, boss_l = 40.0, 30.0       # 凸台
    boss_h = 8.0                       # 凸台高度
    grid_step = 0.8                    # 点云间距

    # 1) 底板顶面（排除凸台区域）
    xs_base = np.arange(-plate_w/2, plate_w/2 + grid_step, grid_step)
    ys_base = np.arange(-plate_l/2, plate_l/2 + grid_step, grid_step)
    xx_b, yy_b = np.meshgrid(xs_base, ys_base)
    zz_b = np.zeros_like(xx_b)

    in_boss = (np.abs(xx_b) < boss_w/2) & (np.abs(yy_b) < boss_l/2)
    xx_b = xx_b[~in_boss]; yy_b = yy_b[~in_boss]; zz_b = zz_b[~in_boss]
    xyz_base = np.column_stack([xx_b.ravel(), yy_b.ravel(), zz_b.ravel()])

    # 添加噪声
    xyz_base[:, :2] += rng.normal(0, 0.03, xyz_base[:, :2].shape)

    # 2) 凸台顶面
    xs_boss = np.arange(-boss_w/2, boss_w/2 + grid_step, grid_step)
    ys_boss = np.arange(-boss_l/2, boss_l/2 + grid_step, grid_step)
    xx_t, yy_t = np.meshgrid(xs_boss, ys_boss)
    zz_t = np.full_like(xx_t, boss_h)
    xyz_boss = np.column_stack([xx_t.ravel(), yy_t.ravel(), zz_t.ravel()])

    # 3) 凸台侧面（四条边采样）
    side_points = []
    n_side = 200
    # 上边
    side_points.append(np.column_stack([
        np.linspace(-boss_w/2, boss_w/2, n_side),
        np.full(n_side, boss_l/2),
        rng.uniform(0, boss_h, n_side),
    ]))
    # 下边
    side_points.append(np.column_stack([
        np.linspace(-boss_w/2, boss_w/2, n_side),
        np.full(n_side, -boss_l/2),
        rng.uniform(0, boss_h, n_side),
    ]))
    # 左边
    side_points.append(np.column_stack([
        np.full(n_side, -boss_w/2),
        np.linspace(-boss_l/2, boss_l/2, n_side),
        rng.uniform(0, boss_h, n_side),
    ]))
    # 右边
    side_points.append(np.column_stack([
        np.full(n_side, boss_w/2),
        np.linspace(-boss_l/2, boss_l/2, n_side),
        rng.uniform(0, boss_h, n_side),
    ]))
    xyz_side = np.vstack(side_points)

    # 合并
    xyz = np.vstack([xyz_base, xyz_boss, xyz_side]).astype(np.float32)

    # 下采样到目标点数
    if len(xyz) > n_points:
        idx = rng.choice(len(xyz), n_points, replace=False)
        xyz = xyz[idx]

    # 噪声
    xyz += rng.normal(0, 0.02, xyz.shape).astype(np.float32)

    # 法向量：矩形平板全部朝上
    normals = np.full_like(xyz, [0, 0, 1], dtype=np.float32)

    # ---- 制造缺陷 ----
    defect_mask = np.zeros(len(xyz), dtype=bool)
    defect_info: dict = {"defects": [], "total_defect_points": 0}

    # 缺陷板定位：凸台顶面的中心区域
    boss_top = xyz[:, 2] > boss_h * 0.8  # 凸台顶面

    # 缺陷 #1：圆形坑洞
    if "pit" in defect_types:
        cx, cy = 5.0, 5.0
        radius = 5.0
        depth = 3.0
        n_before = int(defect_mask.sum())
        for i in np.where(boss_top)[0]:
            dx = xyz[i, 0] - cx
            dy = xyz[i, 1] - cy
            dist = np.sqrt(dx**2 + dy**2)
            if dist < radius:
                d_factor = np.cos(np.pi * dist / (2 * radius + 1e-6))
                xyz[i, 2] -= d_factor * depth
                defect_mask[i] = True
        defect_info["defects"].append({
            "type": "pit", "size_mm": [10.0, 10.0],
            "max_depth_mm": depth,
            "points": int(defect_mask.sum()) - n_before,
        })

    # 缺陷 #2：矩形沟槽
    if "groove" in defect_types:
        gx, gy = -10.0, -5.0
        gw, gl, gd = 8.0, 15.0, 4.0
        n_before = int(defect_mask.sum())
        for i in np.where(boss_top)[0]:
            dx = abs(xyz[i, 0] - gx)
            dy = abs(xyz[i, 1] - gy)
            if dx < gw/2 and dy < gl/2:
                df = (1 - dx/(gw/2)) * (1 - dy/(gl/2))
                xyz[i, 2] -= df * gd
                defect_mask[i] = True
        defect_info["defects"].append({
            "type": "groove", "size_mm": [gw, gl],
            "max_depth_mm": gd,
            "points": int(defect_mask.sum()) - n_before,
        })

    # 缺陷 #3：划痕
    if "scratch" in defect_types:
        sx0, sy0 = 8.0, -10.0
        sx1, sy1 = -8.0, -10.0
        sw = 2.0
        sd = 2.0
        n_before = int(defect_mask.sum())
        sdx = sx1 - sx0; sdy = sy1 - sy0
        slen = np.sqrt(sdx**2 + sdy**2)
        for i in np.where(boss_top)[0]:
            px, py = xyz[i, 0] - sx0, xyz[i, 1] - sy0
            t = (px * sdx + py * sdy) / (slen**2 + 1e-6)
            t = np.clip(t, 0, 1)
            px_proj = t * sdx
            py_proj = t * sdy
            pdist = np.sqrt((px - px_proj)**2 + (py - py_proj)**2)
            if pdist < sw/2:
                df = np.cos(np.pi * pdist / (sw + 1e-6))
                xyz[i, 2] -= df * sd
                defect_mask[i] = True
        defect_info["defects"].append({
            "type": "scratch", "size_mm": [sw, int(slen)],
            "max_depth_mm": sd,
            "points": int(defect_mask.sum()) - n_before,
        })

    # 缺陷 #4：不规则缺损
    if "irregular" in defect_types:
        ix, iy = -8.0, 8.0
        ir = 6.0
        n_before = int(defect_mask.sum())
        for i in np.where(boss_top)[0]:
            dx = xyz[i, 0] - ix
            dy = xyz[i, 1] - iy
            dist = np.sqrt(dx**2 + dy**2)
            if dist < ir:
                noise_scale = rng.uniform(0.3, 1.0)
                df = noise_scale * np.cos(np.pi * dist / (2 * ir + 1e-6))
                xyz[i, 2] -= df * 3.5
                defect_mask[i] = True
        defect_info["defects"].append({
            "type": "irregular", "size_mm": [ir*2, ir*2],
            "max_depth_mm": 3.5,
            "points": int(defect_mask.sum()) - n_before,
        })

    defect_info["total_defect_points"] = int(defect_mask.sum())
    return xyz, normals, defect_mask, defect_info


def _estimate_normals(xyz: np.ndarray, indices: np.ndarray, k: int = 30) -> np.ndarray:
    """PCA 法向量估计（仅对指定索引）。"""
    n = len(indices)
    result = np.zeros((n, 3), dtype=np.float32)
    for j, i in enumerate(indices):
        dists = np.sum((xyz - xyz[i])**2, axis=1)
        n_neighbors = min(k + 1, len(xyz))
        if n_neighbors < 3:
            result[j] = [0, 0, 1]
            continue
        knn = np.argpartition(dists, n_neighbors - 1)[:n_neighbors]
        nb = xyz[knn] - xyz[knn].mean(axis=0)
        cov = nb.T @ nb
        if cov.shape[0] < 3 or np.allclose(cov, 0):
            result[j] = [0, 0, 1]
            continue
        try:
            _, _, vh = np.linalg.svd(cov)
            n_vec = vh[2].astype(np.float32)
            if n_vec[2] < 0:
                n_vec = -n_vec
            result[j] = n_vec
        except Exception:
            result[j] = [0, 0, 1]
    return result


def generate_mock_particle_distribution(
    n_particles: int = 5000,
    nozzle_diameter_mm: float = 6.0,
    seed: int = 42,
):
    """生成模拟颗粒分布。"""
    from repair_app.communication.repair_serialization import build_particle_distribution
    rng = np.random.default_rng(seed)
    radius = nozzle_diameter_mm / 2
    px = rng.normal(0, radius * 0.3, n_particles).astype(np.float32)
    py = rng.normal(0, radius * 0.3, n_particles).astype(np.float32)
    vx = rng.normal(0, 30, n_particles).astype(np.float32)
    vy = rng.normal(0, 30, n_particles).astype(np.float32)
    vz = rng.normal(500, 50, n_particles).astype(np.float32)
    temperature = rng.normal(600, 80, n_particles).astype(np.float32)
    diameter = rng.normal(25, 8, n_particles).astype(np.float32)
    diameter = np.clip(diameter, 5, 60)
    vcr = (vz > 400).astype(np.float32)
    dep_efficiency = float(vcr.sum()) / max(n_particles, 1)
    return build_particle_distribution(
        px=px, py=py, vx=vx, vy=vy, vz=vz,
        temperature=temperature, diameter=diameter, vcr=vcr,
        dep_efficiency=dep_efficiency,
    )


def generate_mock_repair_result(
    n_waypoints: int = 200,
    volume_mm3: float = 1250.0,
    seed: int = 42,
):
    """生成模拟修复结果。"""
    from repair_app.communication.repair_protocol_pb2 import RepairResult, RepairStatusCode
    rng = np.random.default_rng(seed)
    msg = RepairResult()
    msg.status_code = RepairStatusCode.SUCCESS
    msg.request_id = f"MOCK-{seed}"
    msg.compute_time_ms = 850
    msg.predicted_volume_mm3 = volume_mm3
    msg.material_density_gcm3 = 8.96
    msg.estimated_mass_g = volume_mm3 * 8.96 / 1000.0
    msg.estimated_time_s = n_waypoints * 0.15
    for i in range(n_waypoints):
        wp = msg.waypoints.add()
        t = i / n_waypoints * 4 * np.pi
        wp.x = 20 * np.cos(t)
        wp.y = 20 * np.sin(t)
        wp.z = 2.0 * (i // 50)
        wp.nx = 0; wp.ny = 0; wp.nz = 1
        wp.feed_rate = 500.0
        wp.layer_index = (i // 50) + 1
    # 逐层轮廓
    n_layers = (n_waypoints // 50) + 1
    for li in range(n_layers):
        lp = msg.layer_profiles.add()
        lp.layer_index = li + 1
        lp.max_height_mm = 2.0 + 0.2 * li
        lp.avg_height_mm = 1.8 + 0.15 * li
        lp.dep_efficiency = 0.75 - 0.03 * li

    msg.uniformity_score = 0.82
    msg.is_feasible = True
    msg.feasibility_reason = "缺陷尺寸在可修复范围内"
    return msg
