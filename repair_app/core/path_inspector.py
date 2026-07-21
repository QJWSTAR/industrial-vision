"""
path_inspector.py — 路径规划结果检查器

P2-2: 检查路径规划输出的工程合理性，确保结果可直接用于 G-code 导出。
检查项：
  1. Waypoint 连续性（相邻点间距无异常跳变）
  2. 法向稳定性（若提供法向量，检查方向一致性）
  3. Layer 正确性（层数/层高/层号一致性）

纯检查模块，不修改路径规划算法。返回 PathInspectionResult 供调用方决策。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class PathIssue:
    """路径检查问题。"""
    level: str  # "warning" | "error"
    code: str
    message: str


@dataclass
class PathInspectionResult:
    """路径检查结果。"""
    ok: bool
    issues: list[PathIssue] = field(default_factory=list)
    n_waypoints: int = 0
    n_layers: int = 0
    max_gap_mm: float = 0.0
    mean_gap_mm: float = 0.0

    @property
    def error_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.level == "error"]

    @property
    def warning_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.level == "warning"]


def inspect_path(
    waypoints: np.ndarray,
    *,
    normals: Optional[np.ndarray] = None,
    layer_indices: Optional[np.ndarray] = None,
    expected_n_layers: Optional[int] = None,
    expected_layer_height: Optional[float] = None,
    max_gap_mm: float = 80.0,
    normal_consistency_threshold: float = 0.3,
) -> PathInspectionResult:
    """检查路径规划输出的工程合理性。

    Args:
        waypoints: (N, 3+) 航点坐标
        normals: (N, 3) 法向量数组（可选，来自 MATLAB 远程结果）
        layer_indices: (N,) 层号数组（可选）
        expected_n_layers: 期望层数（可选）
        expected_layer_height: 期望层高 mm（可选）
        max_gap_mm: 最大允许段间距，超过则警告
        normal_consistency_threshold: 法向量方向变化阈值（余弦距离）

    Returns:
        PathInspectionResult
    """
    issues: list[PathIssue] = []
    wp = np.asarray(waypoints)

    if wp.ndim != 2 or wp.shape[1] < 3:
        issues.append(PathIssue("error", "INVALID_SHAPE",
            f"航点形状异常: {wp.shape}，期望 (N, 3+)"))
        return PathInspectionResult(ok=False, issues=issues)

    n = len(wp)
    if n < 2:
        issues.append(PathIssue("error", "TOO_FEW_WAYPOINTS",
            f"航点数 {n} < 2，无法形成连续轨迹"))
        return PathInspectionResult(ok=False, issues=issues)

    # === 1. Waypoint 连续性检查 ===
    diffs = np.diff(wp[:, :3], axis=0)
    seg_lengths = np.linalg.norm(diffs, axis=1)
    max_gap = float(np.max(seg_lengths))
    mean_gap = float(np.mean(seg_lengths))

    # 检测异常跳变（超过 max_gap_mm 的段）
    long_segs = int(np.sum(seg_lengths > max_gap_mm))
    if long_segs > 0:
        issues.append(PathIssue("warning", "GAP_TOO_LARGE",
            f"存在 {long_segs} 段间距超过 {max_gap_mm:.1f} mm（最大 {max_gap:.2f} mm），"
            f"可能导致空行程或路径断裂"))

    # 检测零距离重复点
    zero_segs = int(np.sum(seg_lengths < 1e-6))
    if zero_segs > 0:
        issues.append(PathIssue("warning", "DUPLICATE_POINTS",
            f"存在 {zero_segs} 个重复航点，可能导致局部过喷"))

    # === 2. 法向稳定性检查 ===
    if normals is not None:
        normals_arr = np.asarray(normals)
        if len(normals_arr) == n and normals_arr.shape[1] >= 3:
            # 计算相邻法向量的余弦距离（1 = 完全一致, -1 = 完全反向）
            norm_products = np.sum(normals_arr[:-1, :3] * normals_arr[1:, :3], axis=1)
            # 检测法向量突变（余弦距离 < threshold 表示方向剧变）
            abrupt_changes = int(np.sum(norm_products < normal_consistency_threshold))
            if abrupt_changes > 0:
                issues.append(PathIssue("warning", "NORMAL_INSTABILITY",
                    f"存在 {abrupt_changes} 处法向量方向突变（余弦 < {normal_consistency_threshold}），"
                    f"可能导致喷嘴姿态不稳定"))
        else:
            issues.append(PathIssue("warning", "NORMAL_LENGTH_MISMATCH",
                f"法向量数组长度 {len(normals_arr)} 与航点数 {n} 不一致，跳过法向检查"))
    # normals 为 None 时不报错（本地路径无法向量是已知限制）

    # === 3. Layer 正确性检查 ===
    n_layers_detected = 1
    if layer_indices is not None:
        layers_arr = np.asarray(layer_indices, dtype=int)
        if len(layers_arr) == n:
            unique_layers = np.unique(layers_arr)
            n_layers_detected = len(unique_layers)

            # 检查层号是否连续（无跳层）
            expected_sequence = np.arange(unique_layers.min(), unique_layers.max() + 1)
            if len(unique_layers) != len(expected_sequence):
                issues.append(PathIssue("warning", "LAYER_GAP",
                    f"层号不连续: 检测到 {n_layers_detected} 层，"
                    f"但层号范围 {unique_layers.min()}-{unique_layers.max()} 应有 "
                    f"{len(expected_sequence)} 层"))

            # 检查层高一致性（通过 Z 坐标推断）
            if expected_layer_height is not None and n_layers_detected > 1:
                layer_z_means = []
                for lid in unique_layers:
                    mask = layers_arr == lid
                    if np.any(mask):
                        layer_z_means.append(float(np.mean(wp[mask, 2])))
                if len(layer_z_means) >= 2:
                    z_diffs = np.diff(sorted(layer_z_means))
                    inconsistent = int(np.sum(np.abs(z_diffs - expected_layer_height) > 0.5))
                    if inconsistent > 0:
                        issues.append(PathIssue("warning", "LAYER_HEIGHT_INCONSISTENT",
                            f"存在 {inconsistent} 处层高与期望值 {expected_layer_height:.2f} mm 偏差超过 0.5 mm"))

            # 检查期望层数
            if expected_n_layers is not None and n_layers_detected != expected_n_layers:
                issues.append(PathIssue("warning", "LAYER_COUNT_MISMATCH",
                    f"检测到 {n_layers_detected} 层，期望 {expected_n_layers} 层"))

    ok = not any(i.level == "error" for i in issues)
    return PathInspectionResult(
        ok=ok,
        issues=issues,
        n_waypoints=n,
        n_layers=n_layers_detected,
        max_gap_mm=max_gap,
        mean_gap_mm=mean_gap,
    )
