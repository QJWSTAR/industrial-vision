"""
feasibility_checker.py — 冷喷涂修复可行性预判模块
Stage 2.2 v2.1：基于缺陷几何特征和材料参数判断修复可行性
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np

from repair_app.core.material_database import MaterialParams, get_material_db


class WarningLevel(Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass
class FeasibilityWarning:
    """单条可行性警告。"""
    level: WarningLevel
    code: str
    message: str
    detail: str = ""
    suggestion: str = ""


@dataclass
class FeasibilityResult:
    """可行性判断结果。"""
    feasible: bool
    overall_level: WarningLevel
    warnings: list[FeasibilityWarning] = field(default_factory=list)
    score: float = 1.0
    summary: str = ""


class FeasibilityChecker:
    """修复可行性预判器。

    判断规则（基于论文结论）：
    - 缺陷最小尺寸 < 喷斑直径 → 警告过度喷涂
    - 缺陷深度 > 临界值（材料相关）→ 警告层间结合
    - 侧壁角度 > 45° → 沉积效率警告
    - 缺陷在垂直壁面/倒角 → 粒子弹开警告
    """

    def __init__(self, material: Optional[MaterialParams] = None) -> None:
        self.material = material or get_material_db().get_default()
        self._thresholds = get_material_db().thresholds

    def check(
        self,
        defect_volume_mm3: float,
        defect_depth_mm: float,
        defect_min_width_mm: float,
        defect_max_width_mm: float,
        sidewall_angle_deg: float,
        nozzle_diameter_mm: float,
        spray_angle_deg: float,
        particle_velocity_ms: float,
    ) -> FeasibilityResult:
        warnings: list[FeasibilityWarning] = []

        # 规则0：空缺陷
        early = self._check_empty_defect(defect_volume_mm3, defect_depth_mm)
        if early is not None:
            return early

        # 规则1：最小尺寸 vs 喷斑直径
        self._check_size_vs_spot(
            defect_min_width_mm, nozzle_diameter_mm, warnings)

        # 规则2：缺陷深度
        self._check_depth(
            defect_depth_mm, defect_max_width_mm, warnings)

        # 规则3：侧壁角度
        self._check_sidewall(sidewall_angle_deg, warnings)

        # 规则4：喷涂角度
        self._check_spray_angle(spray_angle_deg, warnings)

        # 规则5：粒子速度
        self._check_velocity(
            particle_velocity_ms, spray_angle_deg, warnings)

        # 综合判断
        return self._summarize(warnings)

    # ---- 规则子方法 ----

    def _check_empty_defect(
        self, defect_volume_mm3: float, defect_depth_mm: float,
    ) -> Optional[FeasibilityResult]:
        """规则0：空缺陷检查，不通过时返回结果，通过时返回 None。"""
        if defect_volume_mm3 <= 0 or defect_depth_mm <= 0:
            w = FeasibilityWarning(
                WarningLevel.BLOCKED, "EMPTY_DEFECT",
                "未检测到有效缺陷区域",
                detail=f"体积={defect_volume_mm3:.3f} mm³, 深度={defect_depth_mm:.3f} mm",
                suggestion="请重新选取缺陷区域。",
            )
            return FeasibilityResult(
                feasible=False, overall_level=WarningLevel.BLOCKED,
                warnings=[w], score=0.0, summary="无效缺陷区域"
            )
        return None

    def _check_size_vs_spot(
        self, defect_min_width_mm: float, nozzle_diameter_mm: float,
        warnings: list[FeasibilityWarning],
    ) -> None:
        """规则1：最小尺寸 vs 喷斑直径。"""
        spot_width = nozzle_diameter_mm
        ratio = defect_min_width_mm / max(spot_width, 1e-6)
        min_ratio = self._thresholds.get("min_defect_size_to_spot_ratio", 0.8)
        if ratio < min_ratio:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "UNDERSIZED_DEFECT",
                f"缺陷最小宽度({defect_min_width_mm:.1f}mm) 小于喷斑直径的{min_ratio*100:.0f}%",
                detail=f"喷斑直径≈{spot_width:.1f}mm, 比值={ratio:.2f}",
                suggestion="建议换用小口径喷嘴，或接受过度喷涂。",
            ))

        over_spray = defect_min_width_mm / max(spot_width, 1e-6)
        max_over = self._thresholds.get("max_over_spray_ratio", 2.0)
        if over_spray > max_over:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "LARGE_DEFECT",
                f"缺陷最小宽度({defect_min_width_mm:.1f}mm) 超过喷斑直径{max_over:.0f}倍以上",
                suggestion="需多道次搭接填充，建议采用蛇形路径规划。",
            ))

    def _check_depth(
        self, defect_depth_mm: float, defect_max_width_mm: float,
        warnings: list[FeasibilityWarning],
    ) -> None:
        """规则2：缺陷深度与深宽比。"""
        if defect_depth_mm > self.material.max_defect_depth_mm:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "EXCESSIVE_DEPTH",
                f"缺陷深度({defect_depth_mm:.1f}mm) 超过{self.material.name}建议最大深度({self.material.max_defect_depth_mm:.1f}mm)",
                suggestion="建议分层多次修复。",
            ))

        max_dw = self._thresholds.get("max_depth_to_width_ratio", 2.0)
        if defect_max_width_mm > 0 and defect_depth_mm / defect_max_width_mm > max_dw:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "HIGH_ASPECT_RATIO",
                f"缺陷深宽比({defect_depth_mm/defect_max_width_mm:.2f}) 过高",
                suggestion="建议扩大缺陷开口范围，或采用斜喷策略。",
            ))

    def _check_sidewall(
        self, sidewall_angle_deg: float,
        warnings: list[FeasibilityWarning],
    ) -> None:
        """规则3：侧壁角度。"""
        if sidewall_angle_deg > self.material.max_sidewall_angle_deg:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "STEEP_SIDEWALL",
                f"侧壁角度({sidewall_angle_deg:.0f}°) 超过{self.material.name}临界角度({self.material.max_sidewall_angle_deg:.0f}°)",
                detail="陡峭侧壁导致颗粒弹开。",
                suggestion="调整喷涂角度使粒子入射方向尽量垂直于壁面。",
            ))

    def _check_spray_angle(
        self, spray_angle_deg: float,
        warnings: list[FeasibilityWarning],
    ) -> None:
        """规则4：喷涂角度。"""
        min_angle = self._thresholds.get("min_spray_angle_deg", 30)
        if spray_angle_deg < min_angle:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "LOW_SPRAY_ANGLE",
                f"喷涂角度({spray_angle_deg:.0f}°) 低于最小建议角度({min_angle:.0f}°)",
                suggestion="调整喷嘴方向，使入射角≥30°。",
            ))

    def _check_velocity(
        self, particle_velocity_ms: float, spray_angle_deg: float,
        warnings: list[FeasibilityWarning],
    ) -> None:
        """规则5：粒子速度 vs 临界速度。"""
        v_cr_eff = self.material.v_cr_at_angle(spray_angle_deg)
        if particle_velocity_ms < v_cr_eff * 0.9:
            warnings.append(FeasibilityWarning(
                WarningLevel.BLOCKED, "INSUFFICIENT_VELOCITY",
                f"粒子速度({particle_velocity_ms:.0f}m/s) 远低于有效临界速度({v_cr_eff:.0f}m/s)",
                suggestion="提高气体压力/温度，或选择低 v_cr 材料。",
            ))
        elif particle_velocity_ms < v_cr_eff:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "MARGINAL_VELOCITY",
                f"粒子速度({particle_velocity_ms:.0f}m/s) 略低于有效临界速度({v_cr_eff:.0f}m/s)",
                suggestion="可尝试提高粒子速度或预热基体。",
            ))
        elif particle_velocity_ms > v_cr_eff * 2.5:
            warnings.append(FeasibilityWarning(
                WarningLevel.WARNING, "EXCESSIVE_VELOCITY",
                f"粒子速度({particle_velocity_ms:.0f}m/s) 远超临界速度({v_cr_eff:.0f}m/s)",
                detail="过高速度可能导致基体冲蚀。",
                suggestion="适当降低粒子速度。",
            ))

    def _summarize(
        self, warnings: list[FeasibilityWarning],
    ) -> FeasibilityResult:
        """汇总所有规则结果，生成最终判断。"""
        blocked = any(w.level == WarningLevel.BLOCKED for w in warnings)
        has_warnings = any(w.level == WarningLevel.WARNING for w in warnings)

        if blocked:
            overall = WarningLevel.BLOCKED
            feasible = False
        elif has_warnings:
            overall = WarningLevel.WARNING
            feasible = True
        else:
            overall = WarningLevel.OK
            feasible = True

        n_block = sum(1 for w in warnings if w.level == WarningLevel.BLOCKED)
        n_warn = sum(1 for w in warnings if w.level == WarningLevel.WARNING)
        score = max(0.0, 1.0 - n_block * 0.5 - n_warn * 0.1)

        parts = []
        if feasible:
            parts.append(f"{self.material.name} 修复可行性：{'有条件通过' if overall == WarningLevel.WARNING else '通过'}")
        else:
            parts.append(f"{self.material.name} 修复不可行")
        if len(warnings) > 0:
            parts.append(f"共{len(warnings)}条注意事项")
        summary = "；".join(parts)

        return FeasibilityResult(
            feasible=feasible, overall_level=overall,
            warnings=warnings, score=score, summary=summary
        )

    def check_from_cloud(
        self,
        selected_points: np.ndarray,
        nozzle_diameter_mm: float,
        spray_angle_deg: float,
        particle_velocity_ms: float,
    ) -> FeasibilityResult:
        """从选中点云自动提取几何特征并判断可行性。"""
        if len(selected_points) < 3:
            return FeasibilityResult(
                feasible=False, overall_level=WarningLevel.BLOCKED,
                warnings=[FeasibilityWarning(
                    WarningLevel.BLOCKED, "TOO_FEW_POINTS",
                    f"选中点云点数({len(selected_points)})不足，至少需要3个点",
                    suggestion="请扩大缺陷选取范围。"
                )],
                score=0.0, summary="点云数据不足"
            )

        xyz = selected_points[:, :3]
        z = xyz[:, 2]

        z_min = float(np.min(z))
        z_max = float(np.max(z))
        defect_depth_mm = max(z_max - z_min, 0.01)

        xy = xyz[:, :2]
        spread = np.ptp(xy, axis=0)
        max_width = float(np.max(spread))
        min_width = float(np.min(spread))

        defect_volume_mm3 = max_width * min_width * defect_depth_mm * 0.5

        sidewall_angle_deg = 0.0
        if selected_points.shape[1] >= 6:
            normals = selected_points[:, 3:6]
            norm_mag = np.linalg.norm(normals, axis=1)
            valid = norm_mag > 0.1
            if np.any(valid):
                avg_normal = normals[valid].mean(axis=0)
                avg_normal /= np.linalg.norm(avg_normal)
                z_axis = np.array([0, 0, 1])
                sidewall_angle_deg = float(np.degrees(
                    np.arccos(np.clip(np.abs(np.dot(avg_normal, z_axis)), -1, 1))
                ))

        return self.check(
            defect_volume_mm3=defect_volume_mm3,
            defect_depth_mm=defect_depth_mm,
            defect_min_width_mm=min_width,
            defect_max_width_mm=max_width,
            sidewall_angle_deg=sidewall_angle_deg,
            nozzle_diameter_mm=nozzle_diameter_mm,
            spray_angle_deg=spray_angle_deg,
            particle_velocity_ms=particle_velocity_ms,
        )
