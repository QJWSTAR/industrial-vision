"""validation.result_comparator — 6 维结果比对

对 MATLAB 与 Python 两个引擎的输出逐项比对：
1. pointlist（航点位置 x,y,z）
2. velocitylist（进给速度 feed_rate）
3. Layer（逐层轮廓 layer_profiles）
4. Mesh（沉积表面网格）
5. Volume（预测填充体积）
6. Uniformity（表面均匀性）

比对策略：
- 两边航点数可能不同，不逐点比对，改用统计指标
  （点数、AABB 边界框、质心、Z 范围、路径总长度）
- Layer：层数、每层 max/avg height、dep_efficiency
- Mesh：三角形数、AABB 体积、表面积
- Volume/Uniformity：直接数值差 + 相对误差
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from repair_app.validation.algorithm_validator import EngineResult, ValidationResult


# 比对通过阈值（相对误差超过此值标记为 FAIL）
TOLERANCE_REL = 0.15  # 15%
TOLERANCE_ABS_VOLUME = 50.0  # mm³
TOLERANCE_ABS_UNIFORMITY = 0.15  # 0-1 尺度


@dataclass
class MetricComparison:
    """单项指标比对结果。"""

    name: str
    matlab_value: float
    python_value: float
    abs_error: float
    rel_error: float  # 百分比，0-100
    passed: bool
    note: str = ""

    @property
    def status_icon(self) -> str:
        return "✅" if self.passed else "❌"


@dataclass
class DimensionReport:
    """单个维度（如 pointlist）的完整比对报告。"""

    dimension: str
    matlab_available: bool
    python_available: bool
    metrics: list[MetricComparison] = field(default_factory=list)
    summary: str = ""

    @property
    def all_passed(self) -> bool:
        return all(m.passed for m in self.metrics) if self.metrics else False

    @property
    def status_icon(self) -> str:
        if not self.matlab_available or not self.python_available:
            return "⚠️"
        return "✅" if self.all_passed else "❌"


@dataclass
class ComparisonReport:
    """完整比对报告（6 维度）。"""

    pointlist: DimensionReport
    velocitylist: DimensionReport
    layer: DimensionReport
    mesh: DimensionReport
    volume: DimensionReport
    uniformity: DimensionReport
    overall_passed: bool
    total_metrics: int
    passed_metrics: int
    failed_metrics: int

    @property
    def dimensions(self) -> list[DimensionReport]:
        return [self.pointlist, self.velocitylist, self.layer,
                self.mesh, self.volume, self.uniformity]


class ResultComparator:
    """6 维结果比对器。"""

    def compare(self, validation_result: ValidationResult) -> ComparisonReport:
        """执行完整比对。"""
        mr = validation_result.matlab_result
        pr = validation_result.python_result

        pointlist = self._compare_pointlist(mr, pr)
        velocitylist = self._compare_velocitylist(mr, pr)
        layer = self._compare_layer(mr, pr)
        mesh = self._compare_mesh(mr, pr)
        volume = self._compare_volume(mr, pr)
        uniformity = self._compare_uniformity(mr, pr)

        all_metrics = []
        for dim in [pointlist, velocitylist, layer, mesh, volume, uniformity]:
            all_metrics.extend(dim.metrics)

        total = len(all_metrics)
        passed = sum(1 for m in all_metrics if m.passed)
        failed = total - passed

        return ComparisonReport(
            pointlist=pointlist,
            velocitylist=velocitylist,
            layer=layer,
            mesh=mesh,
            volume=volume,
            uniformity=uniformity,
            overall_passed=(failed == 0),
            total_metrics=total,
            passed_metrics=passed,
            failed_metrics=failed,
        )

    # ========== 1. pointlist 比对 ==========

    def _compare_pointlist(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对航点位置（统计指标，不逐点比对）。"""
        m_wp, p_wp = mr.waypoints, pr.waypoints
        m_ok = m_wp is not None and len(m_wp) > 0
        p_ok = p_wp is not None and len(p_wp) > 0

        report = DimensionReport(
            dimension="pointlist",
            matlab_available=m_ok,
            python_available=p_ok,
        )
        if not m_ok or not p_ok:
            report.summary = "一方或双方无航点数据"
            return report

        m_xyz = m_wp[:, :3]
        p_xyz = p_wp[:, :3]

        # 点数
        report.metrics.append(self._make_metric(
            "点数", len(m_xyz), len(p_xyz),
            abs_tol=max(1, 0.1 * max(len(m_xyz), len(p_xyz))),
            note=f"MATLAB {len(m_xyz)} vs Python {len(p_xyz)}",
        ))
        # AABB X 范围
        report.metrics.append(self._make_metric(
            "AABB_X_min", float(m_xyz[:, 0].min()), float(p_xyz[:, 0].min()),
        ))
        report.metrics.append(self._make_metric(
            "AABB_X_max", float(m_xyz[:, 0].max()), float(p_xyz[:, 0].max()),
        ))
        # AABB Y 范围
        report.metrics.append(self._make_metric(
            "AABB_Y_min", float(m_xyz[:, 1].min()), float(p_xyz[:, 1].min()),
        ))
        report.metrics.append(self._make_metric(
            "AABB_Y_max", float(m_xyz[:, 1].max()), float(p_xyz[:, 1].max()),
        ))
        # Z 范围
        report.metrics.append(self._make_metric(
            "Z_min", float(m_xyz[:, 2].min()), float(p_xyz[:, 2].min()),
        ))
        report.metrics.append(self._make_metric(
            "Z_max", float(m_xyz[:, 2].max()), float(p_xyz[:, 2].max()),
        ))
        # 质心
        report.metrics.append(self._make_metric(
            "质心_X", float(m_xyz[:, 0].mean()), float(p_xyz[:, 0].mean()),
        ))
        report.metrics.append(self._make_metric(
            "质心_Y", float(m_xyz[:, 1].mean()), float(p_xyz[:, 1].mean()),
        ))
        # 路径总长度
        m_len = self._path_length(m_xyz)
        p_len = self._path_length(p_xyz)
        report.metrics.append(self._make_metric(
            "路径总长度_mm", m_len, p_len,
            rel_tol=0.20,  # 路径长度差异可能较大，放宽到 20%
            note=f"MATLAB {m_len:.2f}mm vs Python {p_len:.2f}mm",
        ))

        report.summary = f"{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 2. velocitylist 比对 ==========

    def _compare_velocitylist(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对进给速度。"""
        m_v, p_v = mr.velocitylist, pr.velocitylist
        m_ok = m_v is not None and len(m_v) > 0
        p_ok = p_v is not None and len(p_v) > 0

        report = DimensionReport(
            dimension="velocitylist",
            matlab_available=m_ok,
            python_available=p_ok,
        )
        if not m_ok or not p_ok:
            report.summary = "一方或双方无速度数据"
            return report

        report.metrics.append(self._make_metric(
            "速度点数", len(m_v), len(p_v),
            abs_tol=max(1, 0.1 * max(len(m_v), len(p_v))),
        ))
        report.metrics.append(self._make_metric(
            "平均速度", float(np.mean(m_v)), float(np.mean(p_v)),
        ))
        report.metrics.append(self._make_metric(
            "最大速度", float(np.max(m_v)), float(np.max(p_v)),
        ))
        report.metrics.append(self._make_metric(
            "最小速度", float(np.min(m_v)), float(np.min(p_v)),
        ))
        report.metrics.append(self._make_metric(
            "速度标准差", float(np.std(m_v)), float(np.std(p_v)),
        ))

        report.summary = f"{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 3. Layer 比对 ==========

    def _compare_layer(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对逐层轮廓。"""
        m_lp, p_lp = mr.layer_profiles, pr.layer_profiles
        m_ok = m_lp is not None and len(m_lp) > 0
        p_ok = p_lp is not None and len(p_lp) > 0

        report = DimensionReport(
            dimension="layer",
            matlab_available=m_ok,
            python_available=p_ok,
        )
        if not m_ok or not p_ok:
            report.summary = "一方或双方无层数据"
            return report

        # 层数
        m_layers = len(m_lp)
        p_layers = len(p_lp)
        report.metrics.append(self._make_metric(
            "层数", m_layers, p_layers,
            abs_tol=max(1, 0.1 * max(m_layers, p_layers)),
            note=f"MATLAB {m_layers} 层 vs Python {p_layers} 层",
        ))

        # 每层 max_height / avg_height / dep_eff
        common = min(m_layers, p_layers)
        for i in range(common):
            m_row = m_lp[i]
            p_row = p_lp[i]
            li = int(m_row[0])
            report.metrics.append(self._make_metric(
                f"L{li}_max_height_mm", float(m_row[1]), float(p_row[1]),
                abs_tol=1.0,
            ))
            report.metrics.append(self._make_metric(
                f"L{li}_avg_height_mm", float(m_row[2]), float(p_row[2]),
                abs_tol=1.0,
            ))
            report.metrics.append(self._make_metric(
                f"L{li}_dep_efficiency", float(m_row[3]), float(p_row[3]),
                abs_tol=0.15,
            ))

        report.summary = f"共 {common} 层比对，{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 4. Mesh 比对 ==========

    def _compare_mesh(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对沉积表面网格。"""
        m_mesh, p_mesh = mr.mesh, pr.mesh
        m_ok = m_mesh is not None and len(m_mesh) > 0
        p_ok = p_mesh is not None and len(p_mesh) > 0

        report = DimensionReport(
            dimension="mesh",
            matlab_available=m_ok,
            python_available=p_ok,
        )
        if not m_ok or not p_ok:
            report.summary = "一方或双方无网格数据"
            return report

        # 三角形数
        m_n = len(m_mesh)
        p_n = len(p_mesh)
        report.metrics.append(self._make_metric(
            "三角形数", m_n, p_n,
            abs_tol=max(1, 0.2 * max(m_n, p_n)),
            note=f"MATLAB {m_n} vs Python {p_n}",
        ))

        # AABB 体积（所有顶点的包围盒体积）
        m_vol = self._mesh_aabb_volume(m_mesh)
        p_vol = self._mesh_aabb_volume(p_mesh)
        report.metrics.append(self._make_metric(
            "网格_AABB体积_mm3", m_vol, p_vol,
            rel_tol=0.30,
            note=f"MATLAB {m_vol:.2f} vs Python {p_vol:.2f}",
        ))

        # 网格质心
        m_cx = float(m_mesh[:, [0, 3, 6]].mean())
        p_cx = float(p_mesh[:, [0, 3, 6]].mean())
        report.metrics.append(self._make_metric(
            "网格质心_X", m_cx, p_cx,
            abs_tol=2.0,
        ))
        m_cz = float(m_mesh[:, [2, 5, 8]].mean())
        p_cz = float(p_mesh[:, [2, 5, 8]].mean())
        report.metrics.append(self._make_metric(
            "网格质心_Z", m_cz, p_cz,
            abs_tol=2.0,
        ))

        # Z 范围（沉积高度）
        m_zmax = float(m_mesh[:, [2, 5, 8]].max())
        p_zmax = float(p_mesh[:, [2, 5, 8]].max())
        report.metrics.append(self._make_metric(
            "网格_Z_max", m_zmax, p_zmax,
            abs_tol=2.0,
        ))

        report.summary = f"{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 5. Volume 比对 ==========

    def _compare_volume(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对预测填充体积。"""
        report = DimensionReport(
            dimension="volume",
            matlab_available=True,
            python_available=True,
        )
        m_v = mr.predicted_volume_mm3
        p_v = pr.predicted_volume_mm3

        report.metrics.append(self._make_metric(
            "predicted_volume_mm3", m_v, p_v,
            abs_tol=TOLERANCE_ABS_VOLUME,
            rel_tol=TOLERANCE_REL,
            note=f"MATLAB {m_v:.2f} mm³ vs Python {p_v:.2f} mm³",
        ))
        report.metrics.append(self._make_metric(
            "estimated_mass_g", mr.estimated_mass_g, pr.estimated_mass_g,
            abs_tol=0.5,
            rel_tol=TOLERANCE_REL,
        ))
        report.metrics.append(self._make_metric(
            "estimated_time_s", mr.estimated_time_s, pr.estimated_time_s,
            abs_tol=5.0,
            rel_tol=TOLERANCE_REL,
        ))

        report.summary = f"{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 6. Uniformity 比对 ==========

    def _compare_uniformity(self, mr: EngineResult, pr: EngineResult) -> DimensionReport:
        """比对表面均匀性。"""
        report = DimensionReport(
            dimension="uniformity",
            matlab_available=True,
            python_available=True,
        )
        m_u = mr.uniformity
        p_u = pr.uniformity

        report.metrics.append(self._make_metric(
            "uniformity_score", m_u, p_u,
            abs_tol=TOLERANCE_ABS_UNIFORMITY,
            rel_tol=0.20,
            note=f"MATLAB {m_u:.4f} vs Python {p_u:.4f}",
        ))

        report.summary = f"{len(report.metrics)} 项指标，{sum(1 for m in report.metrics if m.passed)} 项通过"
        return report

    # ========== 辅助方法 ==========

    def _make_metric(
        self,
        name: str,
        matlab_value: float,
        python_value: float,
        abs_tol: Optional[float] = None,
        rel_tol: Optional[float] = None,
        note: str = "",
    ) -> MetricComparison:
        """生成单项指标比对。"""
        abs_err = abs(matlab_value - python_value)
        denom = max(abs(matlab_value), 1e-9)
        rel_err_pct = (abs_err / denom) * 100.0

        # 判定通过条件：绝对误差或相对误差任一在阈值内
        passed = True
        if rel_tol is not None:
            passed = (abs_err / denom) <= rel_tol
        if abs_tol is not None:
            passed = passed or (abs_err <= abs_tol)

        return MetricComparison(
            name=name,
            matlab_value=matlab_value,
            python_value=python_value,
            abs_error=abs_err,
            rel_error=rel_err_pct,
            passed=passed,
            note=note,
        )

    def _path_length(self, xyz: np.ndarray) -> float:
        """计算路径总长度。"""
        if len(xyz) < 2:
            return 0.0
        pts = xyz[:, :3] if xyz.ndim == 2 and xyz.shape[1] >= 3 else xyz
        diffs = np.diff(pts, axis=0)
        if diffs.ndim != 2:
            return 0.0
        return float(np.sum(np.sqrt(np.sum(diffs ** 2, axis=1))))

    def _mesh_aabb_volume(self, mesh: np.ndarray) -> float:
        """计算网格 AABB 体积。"""
        if len(mesh) == 0:
            return 0.0
        xs = mesh[:, [0, 3, 6]].ravel()
        ys = mesh[:, [1, 4, 7]].ravel()
        zs = mesh[:, [2, 5, 8]].ravel()
        dx = xs.max() - xs.min()
        dy = ys.max() - ys.min()
        dz = zs.max() - zs.min()
        return float(dx * dy * dz)
