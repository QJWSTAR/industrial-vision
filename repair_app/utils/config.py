"""
config.py — 集中配置管理

【MF-8 / 任务J】所有参数 Truth Source 已迁移至：
    repair_app/config/parameter_schema.json
本模块仅作为向后兼容层，从 schema_loader 读取所有定义，
不再保留任何 Magic Number / 硬编码参数范围。
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from repair_app.utils.resource_path import get_data_dir
from repair_app.config import schema_loader
from repair_app import __version__ as APP_VERSION
APP_TITLE = f"冷喷涂缺陷修复软件 v{APP_VERSION}"


# ============================================================
# WindowConfig — 从 schema 系统参数读取
# ============================================================
@dataclass
class WindowConfig:
    """主窗口尺寸配置（默认值从 schema system_parameters 读取）。"""
    left_panel_width: int = int(schema_loader.get_system_value("left_panel_width"))
    right_panel_width: int = int(schema_loader.get_system_value("right_panel_width"))
    window_width: int = int(schema_loader.get_system_value("window_width"))
    window_height: int = int(schema_loader.get_system_value("window_height"))


@dataclass
class RepairMode:
    additive: int = 0
    repairing: int = 1


@dataclass
class PageIndex:
    path: int = 0
    morph: int = 1
    output: int = 2


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


# ============================================================
# 材料列表 — 从 schema.materials 读取（按 material_list_order 顺序）
# ============================================================
MATERIALS: List[Tuple[str, str]] = schema_loader.get_material_items()

MAT_KEY_MAP: Dict[int, str] = {
    idx: key for idx, (_, key) in enumerate(MATERIALS)
}

# --- Data directory resolution with ASCII alias + Chinese fallback ---
# 新安装优先使用 ASCII 目录名；旧版中文目录若已存在则回退使用，保持向后兼容。
_PROJECT_ROOT = str(get_data_dir())
_MORPH_DIR_ASCII = "morphology_prediction"
_MORPH_DIR_LEGACY = "形貌预测"


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
    """返回 pointlist.npz 缓存路径（系统临时目录）。

    V1.0 变更：不再写入项目目录，改用系统临时目录，软件退出自动清理。
    """
    from repair_app.repository.file_repository import _get_cache_dir
    return os.path.join(_get_cache_dir(), "pointlist.npz")


def get_velocitylist_file() -> str:
    """返回 velocitylist.npz 缓存路径（系统临时目录）。"""
    from repair_app.repository.file_repository import _get_cache_dir
    return os.path.join(_get_cache_dir(), "velocitylist.npz")


# ============================================================
# PARAM_SPECS / PARAM_BOUNDS / PARAM_DEFAULTS — 全部从 schema 派生
# ============================================================
# Single source of truth = repair_app/config/parameter_schema.json
# Format: (key, label_en, lo, hi, default, step)
# - label_en 为 None 表示该参数仅用于校验（不出现在 UI 自动生成的 spinbox 中）。
# - schema 中 ui_key 为空字符串的参数视为"仅校验"参数，label_en 强制为 None
#   以保持与旧代码行为一致（main_window.py 已为它们提供专用 SpinBox）。
PARAM_SPECS: List[Tuple] = []
for _key, _p in schema_loader.all_process_params().items():
    _label = _p.get("label_en") if _p.get("ui_key") else None
    PARAM_SPECS.append((_key, _label, _p["min"], _p["max"], _p["default"], _p["step"]))
del _key, _p, _label

# Derived: {key: (lo, hi)} for validation use
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = schema_loader.get_param_bounds()

# Derived: {key: default} for initialization
PARAM_DEFAULTS: Dict[str, float] = schema_loader.get_param_defaults()


# ============================================================
# UI_PARAM_SPECS — PARAM_SPECS → UI spinbox 的唯一桥梁
# ============================================================
# 格式: (spec_key, ui_short_key, chinese_label, suffix, tooltip, group, read_only)
# 仅包含 schema 中 ui_key 非空的工艺参数。
UI_PARAM_SPECS: List[Tuple] = schema_loader.get_ui_param_specs()

# 构建查找索引：spec_key → (lo, hi, default, step)
_SPEC_INDEX: Dict[str, Tuple[float, float, float, float]] = {
    key: (lo, hi, default, step)
    for key, _label, lo, hi, default, step in PARAM_SPECS
}


def get_ui_param(spec_key: str) -> tuple:
    """根据 spec_key 返回 (lo, hi, default, step, chinese_label, suffix, tooltip, read_only)。

    用于 UI spinbox 动态生成，确保范围/默认值/步长全部来自 schema（唯一权威源）。
    """
    lo, hi, default, step = _SPEC_INDEX[spec_key]
    for sk, _usk, label, suffix, tip, _grp, ro in UI_PARAM_SPECS:
        if sk == spec_key:
            return (lo, hi, default, step, label, suffix, tip, ro)
    raise KeyError(f"UI_PARAM_SPECS 中未找到 spec_key={spec_key}")


window = WindowConfig()
mode = RepairMode()
page = PageIndex()
style = StepButtonStyle()
