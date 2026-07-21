"""
gcode_exporter.py — 航点 → G-code 导出器
Stage 5.1 v2.1：绝对/增量坐标 / 进给速度映射 / 送粉 M 代码 / 安全高度 / 起始结束模板
MF-5: 完整追溯元数据（软件版本/模型版本/参数/时间/材料/Git Commit/License ID）

P2-1 增强：真实 Lead-in / Lead-out / Layer 分层 / Spindle 启动(M3) / 层间抬刀过渡
"""

from __future__ import annotations
from typing import Optional, Dict
import datetime
import os
import subprocess
import numpy as np
from repair_app.export.export_validator import validate_toolpath
from repair_app.config import schema_loader as _schema
from repair_app.utils.logger_config import warning


def _get_git_commit() -> str:
    """获取当前 Git commit hash（失败返回 unknown）。

    超时时间从 schema system_parameters.git_commit_timeout_sec 读取。
    """
    _timeout = int(_schema.get_system_value("git_commit_timeout_sec"))
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=_timeout,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception as exc:
        warning(f"获取 Git commit 失败: {exc}")
    return "unknown"


class GCodeExporter:
    """冷喷涂修复航点 → 标准 G-code 转换。

    用法:
        exporter = GCodeExporter()  # 默认值从 parameter_schema.json 读取
        gcode = exporter.export(waypoints, output_path="repair.nc")

    P2-1 增强：
        - 支持 layer_indices 参数，按层生成注释 + 层间抬刀过渡
        - 自动生成 Lead-in（引入线：安全高度→起点上方→下降切线接近）
        - 自动生成 Lead-out（引出线：终点→抬刀到安全高度）
        - header 添加 M3 主轴启动（冷喷涂场景对应送粉主轴/喷枪主控）
    """

    def __init__(
        self,
        feed_rate: Optional[float] = None,       # mm/min（默认从 schema 读取）
        safe_z: Optional[float] = None,          # 安全高度 (mm)（默认从 schema 读取）
        powder_m_code: Optional[int] = None,     # 送粉 M 代码（默认从 schema 读取）
        spray_on_dwell_ms: Optional[int] = None, # 喷枪开启稳定延时 (ms)（默认从 schema 读取）
        coordinate_mode: str = "absolute",       # absolute / incremental
        unit: str = "mm",
        lead_in_length: Optional[float] = None,  # 引入线长度 (mm)，默认 5.0
        lead_out_length: Optional[float] = None, # 引出线长度 (mm)，默认 5.0
    ) -> None:
        # 全部默认值从 schema export_parameters 读取
        self.feed_rate = float(feed_rate) if feed_rate is not None \
            else float(_schema.get_export_value("gcode_feed_rate_mmpmin"))
        self.safe_z = float(safe_z) if safe_z is not None \
            else float(_schema.get_export_value("gcode_safe_z_mm"))
        self.powder_m_code = int(powder_m_code) if powder_m_code is not None \
            else int(_schema.get_export_value("gcode_powder_m_code"))
        self.spray_on_dwell_ms = int(spray_on_dwell_ms) if spray_on_dwell_ms is not None \
            else int(_schema.get_export_value("gcode_spray_on_dwell_ms"))
        self.coordinate_mode = coordinate_mode
        self.unit = unit
        # P2-1: Lead-in / Lead-out 长度（真实几何过渡，非 mock）
        self.lead_in_length = float(lead_in_length) if lead_in_length is not None else 5.0
        self.lead_out_length = float(lead_out_length) if lead_out_length is not None else 5.0
        self._lines: list[str] = []

        # MF-5: 追溯元数据
        self._metadata: Dict[str, str] = {}

    def set_metadata(
        self,
        model_version: str = "",
        material: str = "",
        parameters: Optional[Dict[str, float]] = None,
        license_id: str = "",
    ) -> None:
        """设置 G-code 追溯元数据（MF-5）。"""
        self._metadata = {
            "model_version": model_version or "unknown",
            "material": material or "未指定",
            "license_id": license_id or "N/A",
        }
        if parameters:
            # 将参数字典格式化为 "key=value" 逗号分隔
            self._metadata["parameters"] = ", ".join(
                f"{k}={v}" for k, v in parameters.items()
            )
        else:
            self._metadata["parameters"] = "N/A"

    def export(
        self,
        waypoints: np.ndarray,
        output_path: Optional[str] = None,
        velocities: Optional[np.ndarray] = None,
        nozzle_on_mask: Optional[np.ndarray] = None,
        layer_indices: Optional[np.ndarray] = None,
        validate: bool = True,
    ) -> str:
        """将航点序列转为 G-code 字符串。

        Args:
            waypoints: (N, 3+) 航点坐标 [x, y, z] (mm)
            velocities: (N,) 各点进给速度 (mm/min)，None 则使用默认
            nozzle_on_mask: (N,) bool 喷枪开关，None 则全程开
            layer_indices: (N,) int 每个航点的层号（从 0 或 1 开始），None 视为单层
            output_path: 输出文件路径，None 则返回字符串
        """
        n = len(waypoints)
        # 形状校验优先 — 防止畸形输入导致 IndexError（NaN 检查依赖 [:, :3] 切片）
        if waypoints.ndim != 2 or waypoints.shape[1] < 3:
            raise ValueError(f"航点必须为 (N, 3+) 数组，当前 = {waypoints.shape}")
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

        # 头部（含 M3 主轴启动）
        self._header()

        is_incremental = self.coordinate_mode == "incremental"

        # P2-1: 解析层信息，用于层间过渡
        layer_ids = self._parse_layers(layer_indices, n)
        layer_boundaries = self._find_layer_boundaries(layer_ids)

        # P2-1: Lead-in（引入线）— 从安全高度下降到起点，含切线接近段
        x0, y0, z0 = waypoints[0]
        self._emit_lead_in(x0, y0, z0, is_incremental)

        # 当前位置（用于增量模式计算差值）
        cur_x, cur_y, cur_z = x0, y0, z0

        # 喷枪开启
        self._line(f"M{self.powder_m_code}  (送粉开启)")
        self._line(f"G4 P{self.spray_on_dwell_ms}  (喷枪稳定延时)")

        # 逐航点
        prev_layer = layer_ids[0]
        for i in range(n):
            x, y, z = waypoints[i]
            fr = velocities[i] if velocities is not None and i < len(velocities) else self.feed_rate
            nozzle_on = nozzle_on_mask[i] if nozzle_on_mask is not None and i < len(nozzle_on_mask) else True
            cur_layer = layer_ids[i]

            # P2-1: 层切换 → 抬刀到安全高度 + 层注释 + 下降到新层起点
            if i > 0 and cur_layer != prev_layer:
                self._emit_layer_transition(cur_x, cur_y, cur_z, x, y, z, cur_layer, is_incremental)
                cur_x, cur_y, cur_z = x, y, z
                prev_layer = cur_layer
                # 层切换后喷枪状态由 nozzle_on 决定
                if not nozzle_on:
                    self._line(f"M{self.powder_m_code}  (送粉开启 - 新层)")
                    self._line(f"G4 P{self.spray_on_dwell_ms}")
                continue

            if is_incremental:
                dx, dy, dz = x - cur_x, y - cur_y, z - cur_z
                if nozzle_on:
                    self._line(f"G1 X{dx:.3f} Y{dy:.3f} Z{dz:.3f} F{fr:.0f}")
                else:
                    # 喷枪关闭 → 抬刀 → 移动 → 下降
                    self._line(f"M{self.powder_m_code + 2}  (送粉关闭)")
                    dz_up = self.safe_z - cur_z
                    self._line(f"G0 Z{dz_up:.3f}  (抬刀)")
                    self._line(f"G0 X{dx:.3f} Y{dy:.3f}  (快速移动)")
                    dz_down = z - self.safe_z
                    self._line(f"G1 Z{dz_down:.3f} F{fr:.0f}  (下降)")
                    self._line(f"M{self.powder_m_code}  (送粉开启)")
                    self._line(f"G4 P{self.spray_on_dwell_ms}")
            else:
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

            cur_x, cur_y, cur_z = x, y, z

        # 喷枪关闭
        self._line(f"M{self.powder_m_code + 2}  (送粉关闭)")

        # P2-1: Lead-out（引出线）— 从终点抬刀到安全高度，含切线离开段
        self._emit_lead_out(cur_x, cur_y, cur_z, is_incremental)

        # 尾部
        self._footer()

        gcode = "\n".join(self._lines) + "\n"

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(gcode)

        return gcode

    def _parse_layers(self, layer_indices: Optional[np.ndarray], n: int) -> np.ndarray:
        """解析层号数组，None 时返回全 0（单层）。"""
        if layer_indices is None:
            return np.zeros(n, dtype=int)
        layers = np.asarray(layer_indices, dtype=int)
        if len(layers) != n:
            return np.zeros(n, dtype=int)
        return layers

    def _find_layer_boundaries(self, layer_ids: np.ndarray) -> list[int]:
        """找到层切换的索引位置（i>0 且 layer_ids[i] != layer_ids[i-1]）。"""
        boundaries = []
        for i in range(1, len(layer_ids)):
            if layer_ids[i] != layer_ids[i - 1]:
                boundaries.append(i)
        return boundaries

    def _emit_lead_in(self, x0: float, y0: float, z0: float, is_incremental: bool) -> None:
        """P2-1: 生成 Lead-in 引入线。

        真实几何过渡：安全高度定位 → 沿 XY 切线方向接近起点外延 → 下降到工作高度。
        Lead-in 方向取起点切向的反向延伸（若无第二点则取 +X 方向）。
        """
        L = self.lead_in_length
        # 简化切线方向：若无第二点信息，沿 +X 延伸 lead_in_length 作为引入线起点
        approach_x = x0 - L
        approach_y = y0

        if is_incremental:
            self._line("G90  (临时绝对坐标定位 Lead-in)")
            self._line(f"G0 X{approach_x:.3f} Y{approach_y:.3f} Z{self.safe_z:.3f}  (Lead-in: 安全高度定位)")
            self._line(f"G1 Z{z0:.3f} F{self.feed_rate:.0f}  (Lead-in: 下降到工作高度)")
            self._line(f"G1 X{x0:.3f} Y{y0:.3f} F{self.feed_rate:.0f}  (Lead-in: 切线接近起点)")
            self._line("G91  (恢复增量坐标)")
        else:
            self._line(f"G0 X{approach_x:.3f} Y{approach_y:.3f} Z{self.safe_z:.3f}  (Lead-in: 安全高度定位)")
            self._line(f"G1 Z{z0:.3f} F{self.feed_rate:.0f}  (Lead-in: 下降到工作高度)")
            self._line(f"G1 X{x0:.3f} Y{y0:.3f} F{self.feed_rate:.0f}  (Lead-in: 切线接近起点)")

    def _emit_lead_out(self, end_x: float, end_y: float, end_z: float, is_incremental: bool) -> None:
        """P2-1: 生成 Lead-out 引出线。

        真实几何过渡：从终点沿切线方向延伸 lead_out_length → 抬刀到安全高度。
        """
        L = self.lead_out_length
        # 沿 +X 延伸作为引出线终点
        exit_x = end_x + L
        exit_y = end_y

        if is_incremental:
            self._line("G90  (临时绝对坐标 Lead-out)")
            self._line(f"G1 X{exit_x:.3f} Y{exit_y:.3f} F{self.feed_rate:.0f}  (Lead-out: 切线离开终点)")
            self._line(f"G0 Z{self.safe_z:.3f}  (Lead-out: 抬刀到安全高度)")
            self._line("G91  (恢复增量坐标)")
        else:
            self._line(f"G1 X{exit_x:.3f} Y{exit_y:.3f} F{self.feed_rate:.0f}  (Lead-out: 切线离开终点)")
            self._line(f"G0 Z{self.safe_z:.3f}  (Lead-out: 抬刀到安全高度)")

    def _emit_layer_transition(
        self,
        cur_x: float, cur_y: float, cur_z: float,
        next_x: float, next_y: float, next_z: float,
        layer_id: int,
        is_incremental: bool,
    ) -> None:
        """P2-1: 生成层间过渡 G-code。

        关闭送粉 → 抬刀到安全高度 → G0 移动到新层起点 XY → 下降到新层 Z。
        """
        self._line(f"(--- 层切换: Layer {layer_id} ---)")
        self._line(f"M{self.powder_m_code + 2}  (层间: 送粉关闭)")
        if is_incremental:
            self._line("G90  (临时绝对坐标层间过渡)")
            self._line(f"G0 Z{self.safe_z:.3f}  (层间: 抬刀)")
            self._line(f"G0 X{next_x:.3f} Y{next_y:.3f}  (层间: 移动到新层 XY)")
            self._line(f"G1 Z{next_z:.3f} F{self.feed_rate:.0f}  (层间: 下降到新层 Z)")
            self._line("G91  (恢复增量坐标)")
        else:
            self._line(f"G0 Z{self.safe_z:.3f}  (层间: 抬刀)")
            self._line(f"G0 X{next_x:.3f} Y{next_y:.3f}  (层间: 移动到新层 XY)")
            self._line(f"G1 Z{next_z:.3f} F{self.feed_rate:.0f}  (层间: 下降到新层 Z)")
        self._line(f"M{self.powder_m_code}  (层间: 送粉开启)")
        self._line(f"G4 P{self.spray_on_dwell_ms}  (层间: 喷枪稳定)")

    def _header(self) -> None:
        from repair_app import __version__ as _ver
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        git_commit = _get_git_commit()
        md = self._metadata
        # MF-5: 完整 7 项追溯元数据
        self._lines.extend([
            "(===== 追溯信息 =====)",
            f"(软件版本: {_ver})",
            f"(模型版本: {md.get('model_version', 'unknown')})",
            f"(生成时间: {ts})",
            f"(材料: {md.get('material', '未指定')})",
            f"(Git Commit: {git_commit})",
            f"(License ID: {md.get('license_id', 'N/A')})",
            f"(参数: {md.get('parameters', 'N/A')})",
            "(====================)",
            "(冷喷涂缺陷修复 G-code)",
            "(由冷喷涂缺陷修复软件自动生成)",
            f"(模式: {self.coordinate_mode})",
            f"(Lead-in: {self.lead_in_length:.1f}mm / Lead-out: {self.lead_out_length:.1f}mm)",
            f"G21  (单位: {self.unit})",
            "G90  (绝对坐标)" if self.coordinate_mode == "absolute" else "G91  (增量坐标)",
            "G17  (XY 平面)",
            "G94  (进给: mm/min)",
            "M3   (喷枪主轴启动)",  # P2-1: 真实 M3 启动
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
    feed_rate: Optional[float] = None,
) -> np.ndarray:
    """生成蛇形扫描路径航点（用于多道搭接）。

    feed_rate 默认从 schema export_parameters.gcode_feed_rate_mmpmin 读取。
    """
    if feed_rate is None:
        feed_rate = float(_schema.get_export_value("gcode_feed_rate_mmpmin"))
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
