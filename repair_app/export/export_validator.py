"""
export_validator.py — 导出前路径安全检查
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
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


def validate_toolpath(
    waypoints: np.ndarray,
    *,
    velocities: Optional[np.ndarray] = None,
    safe_z: Optional[float] = None,
    max_segment_mm: float = 80.0,
    min_feed_rate: float = 1.0,
    max_feed_rate: float = 60000.0,
) -> ExportValidationResult:
    """校验导出路径的基础工程安全性。"""
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

    ok = not any(i.level == ExportIssueLevel.BLOCKED for i in issues)
    return ExportValidationResult(ok, issues)
