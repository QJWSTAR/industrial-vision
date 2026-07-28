"""
schema_loader.py — 全局唯一配置中心读取器

所有模块通过此文件读取 parameter_schema.json，禁止直接读取 JSON 或硬编码参数。
提供四类访问接口：
  - get_process_param(key)        → 工艺参数（默认值/范围/步长/单位/tooltip/材料覆盖）
  - get_ui_param(key)             → UI 专用参数（笔刷半径/机器人/TCP 等）
  - get_export_param(key)         → 导出参数（G-code/标定）
  - get_network_param(key)        → 网络参数（ZMQ 地址/超时）
  - get_system_param(key)         → 系统参数（窗口尺寸/License 告警天数）
  - get_material_override(key, material) → 材料覆盖值
"""

from __future__ import annotations
import json
import os
import threading
from typing import Any, Optional


_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parameter_schema.json")
_G_SCHEMA: Optional[dict] = None
_G_LOCK = threading.Lock()

PATH_PLANNING_GROUP = "path_planning"
COLD_SPRAY_GROUP = "cold_spray"
REQUIRED_UI_PROCESS_GROUPS = (PATH_PLANNING_GROUP, COLD_SPRAY_GROUP)


class SchemaValidationError(ValueError):
    """Raised when the parameter schema cannot satisfy the UI contract."""


def _load_schema() -> dict:
    """加载 schema（线程安全单例）。"""
    global _G_SCHEMA
    if _G_SCHEMA is None:
        with _G_LOCK:
            if _G_SCHEMA is None:
                with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
                    _G_SCHEMA = json.load(f)
    return _G_SCHEMA


def get_schema() -> dict:
    """返回完整 schema dict。"""
    return _load_schema()


def get_schema_version() -> str:
    """返回 schema 版本号。"""
    return _load_schema().get("schema_version", "unknown")


def validate_required_ui_groups(
    required_groups: tuple[str, ...] = REQUIRED_UI_PROCESS_GROUPS,
) -> None:
    """Validate the canonical process groups required by the main UI.

    Group identifiers are UI metadata only.  This validation deliberately
    does not change the flat ``RepairRequest`` protobuf contract used by the
    MATLAB bridge.
    """
    params = _load_schema().get("process_parameters")
    if not isinstance(params, dict):
        raise SchemaValidationError(
            "parameter_schema.json missing object 'process_parameters'"
        )

    available = {
        str(spec.get("group", ""))
        for spec in params.values()
        if isinstance(spec, dict) and spec.get("ui_key")
    }
    missing = [group for group in required_groups if group not in available]
    if missing:
        missing_text = "', '".join(missing)
        available_text = ", ".join(sorted(available)) or "<none>"
        raise SchemaValidationError(
            f"Schema group '{missing_text}' missing in UI parameter definitions "
            f"(available: {available_text})"
        )


# ============================================================
# 工艺参数（process_parameters）
# ============================================================
def get_process_param(key: str) -> dict:
    """返回工艺参数完整定义。

    Returns: {default, min, max, step, unit, group, ui_key, label_zh, label_en,
              tooltip, description, read_only, validation_rule, material_override}
    """
    params = _load_schema()["process_parameters"]
    if key not in params:
        raise KeyError(f"parameter_schema.json 中未找到工艺参数: {key}")
    return params[key]


def get_process_default(key: str) -> float:
    """返回工艺参数默认值。"""
    return get_process_param(key)["default"]


def get_process_bounds(key: str) -> tuple:
    """返回工艺参数 (min, max)。"""
    p = get_process_param(key)
    return (p["min"], p["max"])


def get_process_step(key: str) -> float:
    """返回工艺参数步长。"""
    return get_process_param(key)["step"]


def get_process_unit(key: str) -> str:
    """返回工艺参数单位。"""
    return get_process_param(key)["unit"]


def get_process_tooltip(key: str) -> str:
    """返回工艺参数 tooltip。"""
    return get_process_param(key)["tooltip"]


def get_process_label(key: str, lang: str = "zh") -> str:
    """返回工艺参数标签。"""
    return get_process_param(key)[f"label_{lang}"]


def all_process_params() -> dict:
    """返回所有工艺参数定义。"""
    return _load_schema()["process_parameters"]


def all_process_keys() -> list:
    """返回所有工艺参数 key 列表。"""
    return list(_load_schema()["process_parameters"].keys())


# ============================================================
# UI 参数（ui_parameters）
# ============================================================
def get_ui_param(key: str) -> dict:
    """返回 UI 专用参数定义。"""
    params = _load_schema()["ui_parameters"]
    if key not in params:
        raise KeyError(f"parameter_schema.json 中未找到 UI 参数: {key}")
    return params[key]


def get_ui_default(key: str) -> float:
    return get_ui_param(key)["default"]


def get_ui_bounds(key: str) -> tuple:
    p = get_ui_param(key)
    return (p["min"], p["max"])


# ============================================================
# 导出参数（export_parameters）
# ============================================================
def get_export_param(key: str) -> dict:
    """返回导出参数定义。"""
    params = _load_schema()["export_parameters"]
    if key not in params:
        raise KeyError(f"parameter_schema.json 中未找到导出参数: {key}")
    return params[key]


def get_export_value(key: str) -> Any:
    """返回导出参数值。"""
    return get_export_param(key)["default"]


# ============================================================
# 网络参数（network_parameters）
# ============================================================
def get_network_param(key: str) -> dict:
    """返回网络参数定义。"""
    params = _load_schema()["network_parameters"]
    if key not in params:
        raise KeyError(f"parameter_schema.json 中未找到网络参数: {key}")
    return params[key]


def get_network_value(key: str) -> Any:
    """返回网络参数值（优先读环境变量）。"""
    p = get_network_param(key)
    env_var = p.get("env_var")
    if env_var and env_var in os.environ:
        val = os.environ[env_var]
        # 尝试转为数值
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val
    return p.get("value")


# ============================================================
# 系统参数（system_parameters）
# ============================================================
def get_system_param(key: str) -> dict:
    """返回系统参数定义。"""
    params = _load_schema()["system_parameters"]
    if key not in params:
        raise KeyError(f"parameter_schema.json 中未找到系统参数: {key}")
    return params[key]


def get_system_value(key: str) -> Any:
    """返回系统参数值。"""
    return get_system_param(key).get("value")


# ============================================================
# 材料覆盖（materials）
# ============================================================
def get_material_override(material_key: str, param_key: str) -> Optional[float]:
    """返回某材料对某参数的覆盖值。

    若材料不存在或未覆盖该参数，返回 None（调用方应使用默认值）。
    """
    materials = _load_schema()["materials"]
    if material_key not in materials:
        return None
    overrides = materials[material_key].get("overrides", {})
    return overrides.get(param_key)


def get_material_label(material_key: str, lang: str = "zh") -> str:
    """返回材料标签。"""
    materials = _load_schema()["materials"]
    if material_key not in materials:
        return material_key
    return materials[material_key].get(f"label_{lang}", material_key)


def get_material_list() -> list:
    """返回材料列表（按 schema 定义的顺序）。"""
    return _load_schema().get("material_list_order", [])


def get_material_items() -> list:
    """返回 (label_zh, key) 元组列表，用于 UI ComboBox。"""
    items = []
    for key in get_material_list():
        items.append((get_material_label(key, "zh"), key))
    return items


# ============================================================
# 派生查找表（兼容旧代码 PARAM_SPECS / PARAM_BOUNDS / PARAM_DEFAULTS）
# ============================================================
def get_param_specs() -> list:
    """返回 PARAM_SPECS 兼容列表：[(key, label_en, min, max, default, step), ...]"""
    specs = []
    for key, p in _load_schema()["process_parameters"].items():
        specs.append((key, p.get("label_en"), p["min"], p["max"], p["default"], p["step"]))
    return specs


def get_param_bounds() -> dict:
    """返回 {key: (min, max)} 字典（兼容 PARAM_BOUNDS）。"""
    return {key: (p["min"], p["max"])
            for key, p in _load_schema()["process_parameters"].items()}


def get_param_defaults() -> dict:
    """返回 {key: default} 字典（兼容 PARAM_DEFAULTS）。"""
    return {key: p["default"]
            for key, p in _load_schema()["process_parameters"].items()}


def get_ui_param_specs() -> list:
    """返回 UI_PARAM_SPECS 兼容列表：
    [(spec_key, ui_key, label_zh, suffix, tooltip, group, read_only), ...]
    仅包含有 ui_key 的工艺参数（用于动态生成 spinbox）。
    """
    specs = []
    for key, p in _load_schema()["process_parameters"].items():
        ui_key = p.get("ui_key")
        if not ui_key:
            continue
        specs.append((
            key, ui_key,
            p.get("label_zh", key),
            p.get("unit", ""),
            p.get("tooltip", ""),
            p.get("group", ""),
            p.get("read_only", False),
        ))
    return specs


def get_ui_param_value(spec_key: str) -> tuple:
    """根据 spec_key 返回 (min, max, default, step, label_zh, unit, tooltip, read_only)。
    用于 UI spinbox 动态生成。
    """
    p = get_process_param(spec_key)
    return (p["min"], p["max"], p["default"], p["step"],
            p.get("label_zh", spec_key), p.get("unit", ""),
            p.get("tooltip", ""), p.get("read_only", False))
