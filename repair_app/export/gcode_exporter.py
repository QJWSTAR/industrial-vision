"""
gcode_exporter.py — 航点 → G-code 导出器
Stage 5.1 v2.1：绝对/增量坐标 / 进给速度映射 / 送粉 M 代码 / 安全高度 / 起始结束模板
"""

from __future__ import annotations
from typing import Optional
import numpy as np
from repair_app.export.export_validator import validate_toolpath


class GCodeExporter:
    """冷喷涂修复航点 → 标准 G-code 转换。

    用法:
        exporter = GCodeExporter(feed_rate=500, safe_z=10.0)
        gcode = exporter.export(waypoints, output_path="repair.nc")
    """

    def __init__(
        self,
        feed_rate: float = 500.0,      # mm/min
        safe_z: float = 10.0,           # 安全高度 (mm)
        powder_m_code: int = 7,         # 送粉 M 代码
        spray_on_dwell_ms: int = 200,   # 喷枪开启稳定延时 (ms)
        coordinate_mode: str = "absolute",  # absolute / incremental
        unit: str = "mm",
    ) -> None:
        self.feed_rate = feed_rate
        self.safe_z = safe_z
        self.powder_m_code = powder_m_code
        self.spray_on_dwell_ms = spray_on_dwell_ms
        self.coordinate_mode = coordinate_mode
        self.unit = unit
        self._lines: list[str] = []

    def export(
        self,
        waypoints: np.ndarray,
        output_path: Optional[str] = None,
        velocities: Optional[np.ndarray] = None,
        nozzle_on_mask: Optional[np.ndarray] = None,
        validate: bool = True,
    ) -> str:
        """将航点序列转为 G-code 字符串。

        Args:
            waypoints: (N, 3) 航点坐标 [x, y, z] (mm)
            velocities: (N,) 各点进给速度 (mm/min)，None 则使用默认
            nozzle_on_mask: (N,) bool 喷枪开关，None 则全程开
            output_path: 输出文件路径，None 则返回字符串
        """
        n = len(waypoints)
        # NaN/Inf 检查 — 防止异常值写入 G-code 导致设备事故
        if np.any(~np.isfinite(waypoints[:, :3])):
            bad_idx = np.where(~np.all(np.isfinite(waypoints[:, :3]), axis=1))[0]
            raise ValueError(
                f"航点包含 NaN/Inf 值，行号: {bad_idx[:5].tolist()}"
                f"{'...' if len(bad_idx) > 5 else ''}"
            )
        if validate:
            result = validate_toolpath(waypoints, velocities=velocities, safe_z=self.safe_z)
            if not result.ok:
                raise ValueError("; ".join(result.blocking_messages))

        self._lines = []

        # 头部
        self._header()

        # 移动到第一个航点上方
        x0, y0, z0 = waypoints[0]
        self._line(f"G0 X{x0:.3f} Y{y0:.3f} Z{self.safe_z:.3f}  (快速移动到起点上方)")
        self._line(f"G1 Z{z0:.3f} F{self.feed_rate:.0f}  (下降到工作高度)")

        # 喷枪开启
        self._line(f"M{self.powder_m_code}  (送粉开启)")
        self._line(f"G4 P{self.spray_on_dwell_ms}  (喷枪稳定延时)")

        # 逐航点
        for i in range(n):
            x, y, z = waypoints[i]
            fr = velocities[i] if velocities is not None and i < len(velocities) else self.feed_rate
            nozzle_on = nozzle_on_mask[i] if nozzle_on_mask is not None and i < len(nozzle_on_mask) else True

            if nozzle_on:
                self._line(f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F{fr:.0f}")
            else:
                # 喷枪关闭 → 抬刀 → 移动 → 下降
                self._line(f"M{self.powder_m_code + 2}  (送粉关闭)")
                self._line(f"G0 Z{self.safe_z:.3f}  (抬刀)")
                self._line(f"G0 X{x:.3f} Y{y:.3f}  (快速移动)")
                self._line(f"G1 Z{z:.3f} F{fr:.0f}  (下降)")
                self._line(f"M{self.powder_m_code}  (送粉开启)")
                self._line(f"G4 P{self.spray_on_dwell_ms}")

        # 喷枪关闭
        self._line(f"M{self.powder_m_code + 2}  (送粉关闭)")

        # 抬刀回安全高度
        self._line(f"G0 Z{self.safe_z:.3f}  (抬刀到安全高度)")

        # 尾部
        self._footer()

        gcode = "\n".join(self._lines) + "\n"

        if output_path:
            with open(output_path, "w") as f:
                f.write(gcode)

        return gcode

    def _header(self) -> None:
        self._lines.extend([
            "(冷喷涂缺陷修复 G-code)",
            "(由冷喷涂缺陷修复软件自动生成)",
            f"(模式: {self.coordinate_mode})",
            f"G21  (单位: {self.unit})",
            "G90  (绝对坐标)" if self.coordinate_mode == "absolute" else "G91  (增量坐标)",
            "G17  (XY 平面)",
            "G94  (进给: mm/min)",
            "",
        ])

    def _footer(self) -> None:
        self._lines.extend([
            "",
            "M5   (主轴停)",
            "M30  (程序结束并复位)",
        ])

    def _line(self, s: str) -> None:
        self._lines.append(s)


def export_snake_path(
    x_min: float, x_max: float,
    y_min: float, y_max: float,
    z: float,
    n_passes: int = 5,
    pts_per_pass: int = 20,
    feed_rate: float = 500.0,
) -> np.ndarray:
    """生成蛇形扫描路径航点（用于多道搭接）。"""
    waypoints = []
    for i in range(n_passes):
        y = y_min + (y_max - y_min) * i / max(n_passes - 1, 1)
        if i % 2 == 0:
            xs = np.linspace(x_min, x_max, pts_per_pass)
        else:
            xs = np.linspace(x_max, x_min, pts_per_pass)
        ys = np.full(pts_per_pass, y)
        zs = np.full(pts_per_pass, z)
        waypoints.append(np.column_stack([xs, ys, zs]))
    return np.vstack(waypoints)
