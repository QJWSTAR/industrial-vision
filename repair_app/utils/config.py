"""
config.py — 集中配置管理
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from repair_app.utils.resource_path import get_data_dir
from repair_app import __version__ as APP_VERSION
APP_TITLE = f"冷喷涂缺陷修复软件 v{APP_VERSION}"


@dataclass
class WindowConfig:
    left_panel_width: int = 340
    right_panel_width: int = 320
    window_width: int = 1700
    window_height: int = 950


@dataclass
class RepairMode:
    additive: int = 0
    repairing: int = 1


@dataclass
class PageIndex:
    path: int = 0
    morph: int = 1


@dataclass
class StepButtonStyle:
    active: str = (
        "QPushButton{{background:{c};color:#F8FAFC;border:1px solid {b};"
        "border-radius:12px;padding:10px 12px;font-size:13px;font-weight:bold;"
        "text-align:left;}}"
        "QPushButton:hover{{background:{h};}}"
    )
    done: str = (
        "QPushButton{background:#052E2B;color:#A7F3D0;border:1px solid #10B981;"
        "border-radius:12px;padding:10px 12px;font-size:13px;font-weight:bold;"
        "text-align:left;}"
    )
    locked: str = (
        "QPushButton{background:#111827;color:#64748B;border:1px solid #273449;"
        "border-radius:12px;padding:10px 12px;font-size:13px;font-weight:bold;"
        "text-align:left;}"
        "QPushButton:hover{background:#172033;color:#94A3B8;}"
    )
    arrow_normal: str = "QLabel{color:#475569;font-size:16px;font-weight:bold;}"
    arrow_ready: str = "QLabel{color:#10B981;font-size:16px;font-weight:bold;}"


MATERIALS: List[Tuple[str, str]] = [
    ("未指定", "MATERIAL_UNSPECIFIED"),
    ("316L 不锈钢", "STEEL_316L"),
    ("Inconel 718", "INCONEL_718"),
    ("Ti-6Al-4V", "TITANIUM_TI64"),
    ("6061 铝合金", "ALUMINUM_6061"),
    ("纯铜", "COPPER"),
]

MAT_KEY_MAP: Dict[int, str] = {
    idx: key for idx, (_, key) in enumerate(MATERIALS)
}

# --- Data directory resolution with ASCII alias + Chinese fallback ---
# 新安装优先使用 ASCII 目录名；旧版中文目录若已存在则回退使用，保持向后兼容。
_PROJECT_ROOT = str(get_data_dir())
_MORPH_DIR_ASCII = "morphology_prediction"
_MORPH_DIR_LEGACY = "形貌预测"
_P1_FRAME_DIR_ASCII = "matlab_frames"
_P1_FRAME_DIR_LEGACY = "Matlab图片保存"


def get_morph_dir() -> str:
    """返回形貌预测数据目录路径。

    若旧版中文目录 (形貌预测) 已存在则回退使用，否则使用 ASCII 目录名
    (morphology_prediction)，避免新安装环境下中文路径编码问题。
    """
    legacy = os.path.join(_PROJECT_ROOT, _MORPH_DIR_LEGACY)
    if os.path.isdir(legacy):
        return legacy
    return os.path.join(_PROJECT_ROOT, _MORPH_DIR_ASCII)


def get_pointlist_file() -> str:
    return os.path.join(get_morph_dir(), "pointlist.npz")


def get_velocitylist_file() -> str:
    return os.path.join(get_morph_dir(), "velocitylist.npz")


def get_p1_frame_dir() -> str:
    """返回 P1 动画帧图片目录路径。

    若旧版中文目录 (Matlab图片保存) 已存在则回退使用，否则使用 ASCII 目录名
    (matlab_frames)。
    """
    legacy = os.path.join(_PROJECT_ROOT, _P1_FRAME_DIR_LEGACY)
    if os.path.isdir(legacy):
        return legacy
    return os.path.join(_PROJECT_ROOT, _P1_FRAME_DIR_ASCII)


# Single source of truth for all process parameter specifications.
# Format: (key, label, lo, hi, default, step)
# - label is None for params not shown in UI (validation-only).
PARAM_SPECS = [
    # Path Planning
    ("layer_height_mm",        "Layer Height (mm)",      0.1,  20.0,   2.0,  0.1),
    ("scanning_angle_deg",     "Scanning Angle (°)",     -360.0,  360.0, -45.0,  1.0),
    ("scanning_step_mm",       "Scanning Step (mm)",     0.1,  50.0,   2.0,  0.1),
    ("edge_step_size_mm",      "Edge Step (mm)",         0.1,  50.0,   2.0,  0.1),
    ("tilt_angle_deg",         "Tilt Angle (°)",         0.0,  90.0,  60.0,  1.0),
    ("buffer_additive_mm",     "Buffer-Additive (mm)",   0.0, 100.0,   2.0,  0.1),
    ("buffer_repairing_mm",    "Buffer-Repairing (mm)",  0.0, 100.0,   0.0,  0.1),
    ("num_layers",             "Layers",                 1,   200,     5,    1),
    ("depth_compensation",     "Depth Comp. (mm)",       0.0,  20.0,   1.0,  0.1),
    # Cold Spray
    ("particle_velocity_ms",   "Particle Velocity (m/s)", 100.0, 2000.0, 500.0, 10.0),
    ("critical_velocity_ms",   "Critical Velocity (m/s)", 100.0, 2000.0, 400.0, 10.0),
    ("nozzle_diameter_mm",     "Nozzle Diameter (mm)",    1.0,   20.0,   6.0,  0.1),
    ("spray_angle_deg",        "Spray Angle (°)",         0.0,  180.0,  90.0,  1.0),
    ("standoff_distance_mm",   "Standoff Distance (mm)",  5.0,  100.0,  30.0,  0.5),
    ("particle_size_um",       "Particle Size (um)",      1.0,  200.0,  25.0,  1.0),
    ("traversing_speed_mms",   "Traversing Speed (mm/s)", 10.0, 2000.0, 500.0, 10.0),
    ("gas_temperature_c",      "Gas Temperature (°C)",    20.0, 1200.0, 800.0, 10.0),
    ("gas_pressure_bar",       "Gas Pressure (bar)",      1.0,  100.0,  40.0,  0.5),
    ("powder_feed_rate_gmin",  "Feed Rate (g/min)",       1.0,  200.0,  30.0,  1.0),
    # Validation-only (no UI widget)
    ("link_free_dist_mm",      None,                      0.0,  200.0,  20.0,  0.1),
    ("obstacle_resolution_mm", None,                      0.1,   50.0,   2.0,  0.1),
]

# Derived: {key: (lo, hi)} for validation use
PARAM_BOUNDS = {key: (lo, hi) for key, _label, lo, hi, _def, _step in PARAM_SPECS}


window = WindowConfig()
mode = RepairMode()
page = PageIndex()
style = StepButtonStyle()
