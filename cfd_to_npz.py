"""
cfd_to_npz.py — FLUENT 颗粒数据 → NumPy 查找表
Stage 3.3 v2.1：将 CFD 导出的 CSV/ASCII 预计算为 .npz 查找表

用法：
    python3 cfd_to_npz.py input.csv --nozzle round_30mm --output cfd_data/
"""

from __future__ import annotations
import argparse
import json
import os
from typing import Optional
import numpy as np


def parse_fluent_csv(
    path: str,
    columns: Optional[list[str]] = None,
) -> dict[str, np.ndarray]:
    """解析 FLUENT 导出的 CSV 颗粒数据。

    预期列：
    - x, y, z: 颗粒位置 (m)
    - vx, vy, vz: 速度分量 (m/s)
    - temperature: 温度 (K)
    - diameter: 粒径 (m)
    - v_cr: 临界速度 (m/s)
    """
    if columns is None:
        columns = ["x", "y", "z", "vx", "vy", "vz", "temperature", "diameter"]

    data = np.genfromtxt(
        path, delimiter=",", skip_header=1,
        names=True, dtype=np.float32, encoding="utf-8",
    )
    result = {}
    for col in columns:
        if col in data.dtype.names:
            result[col] = data[col].astype(np.float32)
    return result


def build_lookup_grid(
    positions: np.ndarray,     # (N, 3)
    velocities: np.ndarray,    # (N, 3)
    temperatures: np.ndarray,  # (N,)
    diameters: np.ndarray,     # (N,)
    grid_resolution: int = 50,
) -> dict[str, np.ndarray]:
    """将散点颗粒数据投影到规则网格查找表。

    返回键：
    - grid_x, grid_y, grid_z: 1D 网格坐标
    - density_3d: 颗粒数密度 (grid_res, grid_res, grid_res)
    - velocity_mean_3d: 平均速度 (grid_res, grid_res, grid_res)
    - temperature_mean_3d: 平均温度 (grid_res, grid_res, grid_res)
    - diameter_mean_3d: 平均粒径 (grid_res, grid_res, grid_res)
    """
    x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]
    v_mag = np.linalg.norm(velocities, axis=1)

    # 网格边界
    x_lo, x_hi = float(np.percentile(x, 1)), float(np.percentile(x, 99))
    y_lo, y_hi = float(np.percentile(y, 1)), float(np.percentile(y, 99))
    z_lo, z_hi = float(np.percentile(z, 1)), float(np.percentile(z, 99))
    x_buf, y_buf, z_buf = (x_hi - x_lo) * 0.05, (y_hi - y_lo) * 0.05, (z_hi - z_lo) * 0.05
    x_lo, x_hi = x_lo - x_buf, x_hi + x_buf
    y_lo, y_hi = y_lo - y_buf, y_hi + y_buf
    z_lo, z_hi = z_lo - z_buf, z_hi + z_buf

    x_bins = np.linspace(x_lo, x_hi, grid_resolution)
    y_bins = np.linspace(y_lo, y_hi, grid_resolution)
    z_bins = np.linspace(z_lo, z_hi, grid_resolution)

    # 3D 直方图
    density, _ = np.histogramdd(positions, bins=(x_bins, y_bins, z_bins))

    # 加权平均（速度、温度、粒径）
    v_sum, _ = np.histogramdd(positions, bins=(x_bins, y_bins, z_bins), weights=v_mag)
    t_sum, _ = np.histogramdd(positions, bins=(x_bins, y_bins, z_bins), weights=temperatures)
    d_sum, _ = np.histogramdd(positions, bins=(x_bins, y_bins, z_bins), weights=diameters)

    eps = 1e-10
    v_mean = v_sum / (density + eps)
    t_mean = t_sum / (density + eps)
    d_mean = d_sum / (density + eps)

    return {
        "grid_x": x_bins[:-1],
        "grid_y": y_bins[:-1],
        "grid_z": z_bins[:-1],
        "density_3d": density.astype(np.float32),
        "velocity_mean_3d": v_mean.astype(np.float32),
        "temperature_mean_3d": t_mean.astype(np.float32),
        "diameter_mean_3d": d_mean.astype(np.float32),
    }


def save_lookup_table(
    lookup: dict[str, np.ndarray],
    nozzle_name: str,
    standoff_mm: float,
    output_dir: str,
) -> str:
    """保存查找表为 .npz 文件。"""
    os.makedirs(output_dir, exist_ok=True)
    fname = f"nozzle_{nozzle_name}_{int(standoff_mm)}mm.npz"
    path = os.path.join(output_dir, fname)
    metadata = {
        "nozzle": nozzle_name,
        "standoff_mm": standoff_mm,
        "description": "CFD particle distribution lookup table",
    }
    # 安全存储：数值数组存 npz，元数据存 JSON sidecar（避免 object array 反序列化风险）
    np.savez_compressed(path, **lookup)
    meta_path = os.path.splitext(path)[0] + '.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")
    print(f"Metadata: {meta_path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="FLUENT CSV → 冷喷涂颗粒查找表")
    parser.add_argument("input", help="FLUENT 导出 CSV 文件")
    parser.add_argument("--nozzle", default="round_30mm", help="喷嘴标识")
    parser.add_argument("--standoff", type=float, default=30.0, help="喷涂距离 (mm)")
    parser.add_argument("--output", default="cfd_data", help="输出目录")
    parser.add_argument("--grid", type=int, default=50, help="网格分辨率")
    args = parser.parse_args()

    raw = parse_fluent_csv(args.input)
    positions = np.column_stack([raw["x"], raw["y"], raw["z"]])
    velocities = np.column_stack([raw["vx"], raw["vy"], raw["vz"]])
    lookup = build_lookup_grid(
        positions, velocities, raw["temperature"], raw["diameter"],
        grid_resolution=args.grid,
    )
    save_lookup_table(lookup, args.nozzle, args.standoff, args.output)


if __name__ == "__main__":
    main()
