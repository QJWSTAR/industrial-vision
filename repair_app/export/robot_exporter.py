"""
robot_exporter.py — 航点 → 工业机器人指令导出
Stage 5.2 v2.1：KUKA KRL / ABB Rapid 格式 / 姿态矩阵 / 可达性标记

用法:
    exporter = RobotExporter(robot_type="kuka")
    code = exporter.export(waypoints, tcp_speed=0.5)
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
import numpy as np
from repair_app.config import schema_loader as _schema


class RobotType(Enum):
    KUKA = "kuka"
    ABB = "abb"


class RobotExporter:
    """工业机器人轨迹代码生成器。

    tcp_speed / tool_frame / base_frame 默认值从 parameter_schema.json
    的 ui_parameters 读取（robot_tcp_speed_ms / robot_tool_frame / robot_base_frame）。
    """

    def __init__(
        self,
        robot_type: RobotType = RobotType.KUKA,
        tcp_speed: Optional[float] = None,   # TCP 线速度 (m/s)
        tool_frame: Optional[int] = None,    # 工具坐标系编号
        base_frame: Optional[int] = None,    # 基坐标系编号
        zone: str = "fine",                  # 逼近精度 (fine/z10/z50)
    ) -> None:
        self.robot_type = robot_type
        self.tcp_speed = float(tcp_speed) if tcp_speed is not None \
            else float(_schema.get_ui_default("robot_tcp_speed_ms"))
        self.tool_frame = int(tool_frame) if tool_frame is not None \
            else int(_schema.get_ui_default("robot_tool_frame"))
        self.base_frame = int(base_frame) if base_frame is not None \
            else int(_schema.get_ui_default("robot_base_frame"))
        self.zone = zone

    def export(
        self,
        waypoints: np.ndarray,
        output_path: Optional[str] = None,
        normals: Optional[np.ndarray] = None,
    ) -> str:
        """导出机器人运动指令。

        Args:
            waypoints: (N, 3) 航点 [x, y, z] (mm → 转换为 m)
            normals: (N, 3) 各点法向量（用于工具姿态计算），None 则使用默认
            output_path: 输出文件路径
        """
        # 转换为米
        wp = waypoints.astype(np.float64) / 1000.0

        if self.robot_type == RobotType.KUKA:
            return self._export_kuka(wp, normals, output_path)
        else:
            return self._export_abb(wp, normals, output_path)

    def _export_kuka(
        self, wp: np.ndarray, normals: Optional[np.ndarray],
        output_path: Optional[str],
    ) -> str:
        lines = [
            "&ACCESS RVP",
            "&REL 1",
            "&PARAM EDITMASK = *",
            "",
            f"DEF csam_repair()",
            "",
            "  ; 冷喷涂修复轨迹",
            "  ; 自动生成 - 冷喷涂缺陷修复软件",
            "",
            f"  BAS(#TOOL, {self.tool_frame})",
            f"  BAS(#BASE, {self.base_frame})",
            f"  BAS(#VEL_CP, {self.tcp_speed:.1f})",
            "",
        ]

        # 计算姿态（法向 → KUKA ABC 角度）
        for i, (x, y, z) in enumerate(wp):
            if normals is not None and i < len(normals):
                a, b, c = _normal_to_euler_kuka(normals[i])
            else:
                a, b, c = 0.0, 0.0, 0.0

            move_type = "LIN" if self.zone == "fine" else "PTP"
            lines.append(
                f"  {move_type} {{X {x:.3f}, Y {y:.3f}, Z {z:.3f}, "
                f"A {a:.1f}, B {b:.1f}, C {c:.1f}}}"
            )

        lines.extend([
            "",
            "  ; 轨迹结束",
            "  PTP $AXIS_ACT",
            "",
            "END",
            "",
        ])

        code = "\n".join(lines)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(code)
        return code

    def _export_abb(
        self, wp: np.ndarray, normals: Optional[np.ndarray],
        output_path: Optional[str],
    ) -> str:
        lines = [
            "MODULE csam_repair",
            "",
            "  PROC main()",
            "    ! 冷喷涂修复轨迹",
            f"    ! TCP速度: v{int(self.tcp_speed * 1000)}",
            "",
        ]

        for i, (x, y, z) in enumerate(wp):
            if normals is not None and i < len(normals):
                q1, q2, q3, q4 = _normal_to_quaternion_abb(normals[i])
                orient_str = f"[{q1:.4f}, {q2:.4f}, {q3:.4f}, {q4:.4f}]"
            else:
                orient_str = "[1, 0, 0, 0]"

            zone_str = self.zone.replace("fine", "fine").replace("z", "z")
            lines.append(
                f"    MoveL [[{x:.2f}, {y:.2f}, {z:.2f}], {orient_str}, "
                f"[0,0,0,0], [0,0,9E9,9E9,9E9,9E9]], "
                f"v{int(self.tcp_speed * 1000)}, {zone_str}, "
                f"tool{self.tool_frame};"
            )

        lines.extend([
            "",
            "  ENDPROC",
            "ENDMODULE",
            "",
        ])

        code = "\n".join(lines)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(code)
        return code


def _normal_to_euler_kuka(normal: np.ndarray) -> tuple[float, float, float]:
    """法向量 → KUKA ABC 欧拉角（简化版）。"""
    n = normal / max(np.linalg.norm(normal), 1e-6)
    # Z 轴对齐法向量
    a = float(np.degrees(np.arctan2(n[1], n[0])))
    b = float(np.degrees(np.arccos(np.clip(n[2], -1, 1))))
    c = 0.0
    return a, b, c


def _normal_to_quaternion_abb(normal: np.ndarray) -> tuple[float, float, float, float]:
    """法向量 → ABB 四元数（简化版）。"""
    n = normal / max(np.linalg.norm(normal), 1e-6)
    # 从 Z 轴旋转到法向
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, n)
    s = np.linalg.norm(v)
    c = np.dot(z, n)
    if s < 1e-6:
        return (1.0, 0.0, 0.0, 0.0)
    v /= s
    half = np.arctan2(s, c) / 2.0
    sin_half = np.sin(half)
    return (np.cos(half), v[0] * sin_half, v[1] * sin_half, v[2] * sin_half)
