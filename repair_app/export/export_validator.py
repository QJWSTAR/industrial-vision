"""
export_validator.py — 导出前路径安全检查

P2-5 增强：新增 Collision Check / Boundary Check / Height Check / Layer Check
            + generate_validation_report() 报告落盘
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import datetime
import os
import numpy as np


class ExportIssueLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass
class ExportIssue:
    level: ExportIssueLevel
    code: str
    message: str


@dataclass
class ExportValidationResult:
    ok: bool
    issues: list[ExportIssue]

    @property
    def blocking_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.level == ExportIssueLevel.BLOCKED]

    @property
    def warning_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.level == ExportIssueLevel.WARNING]

    @property
    def info_messages(self) -> list[str]:
        return [i.message for i in self.issues if i.level == ExportIssueLevel.INFO]

    def generate_report(self, output_path: str) -> bool:
        """P2-5: 生成 Validation Report（Markdown 格式）。

        Args:
            output_path: 报告输出路径（.md）

        Returns:
            True 成功
        """
        try:
            lines = [
                "# 路径校验报告 (Validation Report)",
                "",
                f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 总体结果",
                "",
                f"- **状态**: {'通过' if self.ok else '未通过'}",
                f"- **阻断问题**: {len(self.blocking_messages)} 项",
                f"- **警告问题**: {len(self.warning_messages)} 项",
                f"- **信息提示**: {len(self.info_messages)} 项",
                "",
            ]
            if self.blocking_messages:
                lines.append("## 阻断问题 (BLOCKED)")
                lines.append("")
                for msg in self.blocking_messages:
                    lines.append(f"- {msg}")
                lines.append("")
            if self.warning_messages:
                lines.append("## 警告问题 (WARNING)")
                lines.append("")
                for msg in self.warning_messages:
                    lines.append(f"- {msg}")
                lines.append("")
            if self.info_messages:
                lines.append("## 信息提示 (INFO)")
                lines.append("")
                for msg in self.info_messages:
                    lines.append(f"- {msg}")
                lines.append("")
            lines.append("---")
            lines.append("本报告由冷喷涂缺陷修复软件自动生成")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return True
        except Exception:
            return False


def validate_toolpath(
    waypoints: np.ndarray,
    *,
    velocities: Optional[np.ndarray] = None,
    safe_z: Optional[float] = None,
    max_segment_mm: float = 80.0,
    min_feed_rate: float = 1.0,
    max_feed_rate: float = 60000.0,
    # P2-5 新增参数
    substrate_xyz: Optional[np.ndarray] = None,
    collision_threshold_mm: float = 0.5,
    build_volume: Optional[tuple] = None,
    layer_indices: Optional[np.ndarray] = None,
    expected_n_layers: Optional[int] = None,
    expected_layer_height: Optional[float] = None,
    max_layer_height_deviation: float = 0.5,
) -> ExportValidationResult:
    """校验导出路径的基础工程安全性。

    P2-5 新增检查项：
      - Collision Check: 航点与基板点云的最小距离检测（防碰撞）
      - Boundary Check: 航点是否在构建体积范围内
      - Height Check: Z 坐标合理性（非负、不超过安全高度）
      - Layer Check: 层数/层高/层号一致性
    """
    issues: list[ExportIssue] = []
    wp = np.asarray(waypoints)

    if wp.ndim != 2 or wp.shape[1] < 3:
        issues.append(ExportIssue(
            ExportIssueLevel.BLOCKED,
            "INVALID_SHAPE",
            f"航点必须为 (N, 3+) 数组，当前形状为 {wp.shape}",
        ))
        return ExportValidationResult(False, issues)

    if len(wp) < 2:
        issues.append(ExportIssue(
            ExportIssueLevel.BLOCKED,
            "TOO_FEW_WAYPOINTS",
            "航点数量少于 2，无法导出连续轨迹",
        ))

    if not np.all(np.isfinite(wp[:, :3])):
        issues.append(ExportIssue(
            ExportIssueLevel.BLOCKED,
            "NON_FINITE_COORD",
            "航点包含 NaN 或 Inf 坐标",
        ))

    if len(wp) >= 2 and np.all(np.isfinite(wp[:, :3])):
        seg = np.linalg.norm(np.diff(wp[:, :3], axis=0), axis=1)
        if np.any(seg <= 1e-9):
            issues.append(ExportIssue(
                ExportIssueLevel.WARNING,
                "DUPLICATE_POINTS",
                "路径中存在重复航点，可能造成停顿或局部过喷",
            ))
        long_count = int(np.sum(seg > max_segment_mm))
        if long_count > 0:
            issues.append(ExportIssue(
                ExportIssueLevel.WARNING,
                "LONG_SEGMENT",
                f"存在 {long_count} 段路径长度超过 {max_segment_mm:.1f} mm，建议检查是否缺少过渡路径",
            ))

    if safe_z is not None and len(wp) > 0 and np.all(np.isfinite(wp[:, 2])):
        z_max = float(np.max(wp[:, 2]))
        if safe_z <= z_max:
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "UNSAFE_Z",
                f"安全高度 {safe_z:.3f} mm 不高于路径最高点 {z_max:.3f} mm",
            ))

    if velocities is not None:
        v = np.asarray(velocities, dtype=float)
        if len(v) != len(wp):
            issues.append(ExportIssue(
                ExportIssueLevel.WARNING,
                "VELOCITY_LENGTH",
                "速度数组长度与航点数量不一致，缺失部分将使用默认进给速度",
            ))
        finite_v = v[np.isfinite(v)]
        if len(finite_v) != len(v):
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "NON_FINITE_FEED",
                "速度数组包含 NaN 或 Inf",
            ))
        elif np.any((finite_v < min_feed_rate) | (finite_v > max_feed_rate)):
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "FEED_OUT_OF_RANGE",
                f"进给速度超出 [{min_feed_rate:.0f}, {max_feed_rate:.0f}] mm/min 范围",
            ))

    # === P2-5: Collision Check（碰撞检查） ===
    if substrate_xyz is not None and len(wp) > 0 and np.all(np.isfinite(wp[:, :3])):
        sub = np.asarray(substrate_xyz)
        if sub.ndim == 2 and sub.shape[1] >= 3 and len(sub) > 0:
            # 采样基板点以加速（最多 1000 点）
            if len(sub) > 1000:
                idx = np.random.default_rng(42).choice(len(sub), 1000, replace=False)
                sub_sample = sub[idx]
            else:
                sub_sample = sub
            # 计算每个航点到最近基板点的距离。SciPy 是正式依赖，
            # 但损坏/裁剪过度的部署不应让整个导出流程直接崩溃。
            try:
                from scipy.spatial import cKDTree
            except ImportError:
                issues.append(ExportIssue(
                    ExportIssueLevel.WARNING,
                    "COLLISION_CHECK_SKIPPED",
                    "SciPy 不可用，已跳过基板碰撞检查；请修复安装后重新校验",
                ))
            else:
                tree = cKDTree(sub_sample[:, :3])
                dists, _ = tree.query(wp[:, :3], k=1)
                collision_count = int(np.sum(dists < collision_threshold_mm))
                if collision_count > 0:
                    issues.append(ExportIssue(
                        ExportIssueLevel.WARNING,
                        "COLLISION_RISK",
                        f"存在 {collision_count} 个航点距基板表面小于 {collision_threshold_mm:.1f} mm，存在碰撞风险",
                    ))

    # === P2-5: Boundary Check（边界检查） ===
    if build_volume is not None and len(wp) > 0:
        bounds = np.asarray(build_volume, dtype=float)
        if bounds.shape != (6,) or not np.all(np.isfinite(bounds)):
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "INVALID_BUILD_VOLUME",
                "构建体积必须包含 6 个有限值 (xmin, ymin, zmin, xmax, ymax, zmax)",
            ))
            return ExportValidationResult(False, issues)
        x_min_b, y_min_b, z_min_b, x_max_b, y_max_b, z_max_b = bounds
        lower = bounds[:3]
        upper = bounds[3:]
        if np.any(lower > upper):
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "INVALID_BUILD_VOLUME",
                "构建体积下界不能高于上界",
            ))
            return ExportValidationResult(False, issues)
        out_of_bounds = int(np.sum(np.any(
            (wp[:, :3] < lower) | (wp[:, :3] > upper),
            axis=1,
        )))
        if out_of_bounds > 0:
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "OUT_OF_BOUNDS",
                f"存在 {out_of_bounds} 个航点坐标超出构建体积范围 "
                f"[{x_min_b:.1f},{y_min_b:.1f},{z_min_b:.1f}]-"
                f"[{x_max_b:.1f},{y_max_b:.1f},{z_max_b:.1f}]",
            ))

    # === P2-5: Height Check（高度检查） ===
    if len(wp) > 0 and np.all(np.isfinite(wp[:, 2])):
        z_vals = wp[:, 2]
        # Z 坐标非负检查
        negative_z = int(np.sum(z_vals < 0))
        if negative_z > 0:
            issues.append(ExportIssue(
                ExportIssueLevel.BLOCKED,
                "NEGATIVE_HEIGHT",
                f"存在 {negative_z} 个航点 Z 坐标为负值，可能导致碰撞基板",
            ))
        # Z 坐标不超过安全高度（若提供）
        if safe_z is not None:
            over_safe = int(np.sum(z_vals > safe_z))
            if over_safe > 0:
                issues.append(ExportIssue(
                    ExportIssueLevel.WARNING,
                    "HEIGHT_OVER_SAFE_Z",
                    f"存在 {over_safe} 个航点 Z 坐标超过安全高度 {safe_z:.1f} mm",
                ))

    # === P2-5: Layer Check（层检查） ===
    if layer_indices is not None and len(wp) > 0:
        layers_arr = np.asarray(layer_indices, dtype=int)
        if len(layers_arr) == len(wp):
            unique_layers = np.unique(layers_arr)
            n_layers = len(unique_layers)
            # 层号连续性检查
            expected_seq = np.arange(unique_layers.min(), unique_layers.max() + 1)
            if len(unique_layers) != len(expected_seq):
                issues.append(ExportIssue(
                    ExportIssueLevel.WARNING,
                    "LAYER_GAP",
                    f"层号不连续: 检测到 {n_layers} 层，但范围 {unique_layers.min()}-"
                    f"{unique_layers.max()} 应有 {len(expected_seq)} 层",
                ))
            # 期望层数检查
            if expected_n_layers is not None and n_layers != expected_n_layers:
                issues.append(ExportIssue(
                    ExportIssueLevel.WARNING,
                    "LAYER_COUNT_MISMATCH",
                    f"检测到 {n_layers} 层，期望 {expected_n_layers} 层",
                ))
            # 层高一致性检查
            if expected_layer_height is not None and n_layers > 1:
                layer_z_means = []
                for lid in unique_layers:
                    mask = layers_arr == lid
                    if np.any(mask):
                        layer_z_means.append(float(np.mean(wp[mask, 2])))
                if len(layer_z_means) >= 2:
                    z_diffs = np.diff(sorted(layer_z_means))
                    inconsistent = int(np.sum(np.abs(z_diffs - expected_layer_height) > max_layer_height_deviation))
                    if inconsistent > 0:
                        issues.append(ExportIssue(
                            ExportIssueLevel.WARNING,
                            "LAYER_HEIGHT_INCONSISTENT",
                            f"存在 {inconsistent} 处层高偏差超过 {max_layer_height_deviation:.1f} mm",
                        ))

    ok = not any(i.level == ExportIssueLevel.BLOCKED for i in issues)
    return ExportValidationResult(ok, issues)
