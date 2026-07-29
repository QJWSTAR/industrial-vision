"""
calibration_wizard.py — 单道沉积标定向导
Stage 5.3 v2.1：沉积测量 / 效率更新 / 校准记录 / 配置持久化
"""

from __future__ import annotations
import logging
import os
import json
import time
from typing import Optional
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np

from repair_app.config import schema_loader as _schema

logger = logging.getLogger(__name__)

try:
    from repair_app.utils.resource_path import get_config_dir
except ImportError:
    get_config_dir = None


CALIBRATION_DB = "calibration_db.json"


# 默认值从 schema process_parameters 读取（消除双源冲突）
def _pp_default(key: str) -> float:
    return float(_schema.get_process_default(key))


@dataclass
class CalibrationRecord:
    """单次标定记录。所有默认值从 parameter_schema.json 派生。"""
    timestamp: str = ""
    material: str = ""
    nozzle_diameter_mm: float = field(default_factory=lambda: _pp_default("nozzle_diameter_mm"))
    standoff_distance_mm: float = field(default_factory=lambda: _pp_default("standoff_distance_mm"))
    spray_angle_deg: float = field(default_factory=lambda: _pp_default("spray_angle_deg"))
    particle_velocity_ms: float = field(default_factory=lambda: _pp_default("particle_velocity_ms"))
    traversing_speed_mms: float = field(default_factory=lambda: _pp_default("traversing_speed_mms"))
    particle_size_um: float = field(default_factory=lambda: _pp_default("particle_size_um"))
    preheat_temp_c: float = field(default_factory=lambda: _pp_default("preheat_temp_c"))

    # 测量结果
    measured_width_mm: float = 0.0
    measured_height_mm: float = 0.0
    measured_deposition_efficiency: float = 0.0

    # 修正系数
    width_correction: float = 1.0
    height_correction: float = 1.0
    efficiency_correction: float = 1.0

    notes: str = ""


class CalibrationWizard:
    """单道沉积标定向导。

    流程：
    1. 设置标定参数（材料、喷嘴、速度等）
    2. 执行单道喷涂
    3. 测量沉积宽度、高度
    4. 自动计算修正系数
    5. 保存到 calibration_db.json

    所有默认参数从 parameter_schema.json 读取，禁止硬编码。
    """

    def __init__(self) -> None:
        self._records: list[CalibrationRecord] = []
        self._current: Optional[CalibrationRecord] = None
        self._load()

    # ===== Step 1: 配置参数 =====
    def start_calibration(
        self,
        material: str = "STEEL_316L",
        nozzle_diameter_mm: Optional[float] = None,
        standoff_distance_mm: Optional[float] = None,
        spray_angle_deg: Optional[float] = None,
        particle_velocity_ms: Optional[float] = None,
        traversing_speed_mms: Optional[float] = None,
        particle_size_um: Optional[float] = None,
        preheat_temp_c: Optional[float] = None,
    ) -> CalibrationRecord:
        # 未传入参数时从 schema 读取默认值
        if nozzle_diameter_mm is None:
            nozzle_diameter_mm = _pp_default("nozzle_diameter_mm")
        if standoff_distance_mm is None:
            standoff_distance_mm = _pp_default("standoff_distance_mm")
        if spray_angle_deg is None:
            spray_angle_deg = _pp_default("spray_angle_deg")
        if particle_velocity_ms is None:
            particle_velocity_ms = _pp_default("particle_velocity_ms")
        if traversing_speed_mms is None:
            traversing_speed_mms = _pp_default("traversing_speed_mms")
        if particle_size_um is None:
            particle_size_um = _pp_default("particle_size_um")
        if preheat_temp_c is None:
            preheat_temp_c = _pp_default("preheat_temp_c")
        self._current = CalibrationRecord(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            material=material,
            nozzle_diameter_mm=nozzle_diameter_mm,
            standoff_distance_mm=standoff_distance_mm,
            spray_angle_deg=spray_angle_deg,
            particle_velocity_ms=particle_velocity_ms,
            traversing_speed_mms=traversing_speed_mms,
            particle_size_um=particle_size_um,
            preheat_temp_c=preheat_temp_c,
        )
        return self._current

    # ===== Step 2: 录入测量结果 =====
    def record_measurement(
        self,
        width_mm: float,
        height_mm: float,
        deposition_efficiency: Optional[float] = None,
        notes: str = "",
    ) -> None:
        if self._current is None:
            raise RuntimeError("请先调用 start_calibration()")

        self._current.measured_width_mm = width_mm
        self._current.measured_height_mm = height_mm

        # 理论值估计（简化模型）
        # 扩展系数 / 速度因子 / 修正下限全部从 schema export_parameters 读取
        _wf = float(_schema.get_export_value("calibration_width_factor"))
        _hf = float(_schema.get_export_value("calibration_height_factor"))
        _cmin = float(_schema.get_export_value("calibration_correction_min"))
        # 喷斑宽度 ≈ 喷嘴直径 * 扩展系数
        theoretical_width = self._current.nozzle_diameter_mm * _wf
        self._current.width_correction = max(_cmin, width_mm / max(theoretical_width, 1e-6))

        # 理论高度 ≈ 粒径/1000 * 速度因子
        theoretical_height = self._current.particle_size_um / 1000.0 * _hf
        self._current.height_correction = max(_cmin, height_mm / max(theoretical_height, 1e-6))

        # 沉积效率
        if deposition_efficiency is not None:
            self._current.measured_deposition_efficiency = deposition_efficiency
            from repair_app.core.material_database import get_material_db
            db = get_material_db()
            mat = db.get(self._current.material)
            theoretical_eff = mat.max_deposition_efficiency
            self._current.efficiency_correction = max(_cmin, deposition_efficiency / max(theoretical_eff, 1e-6))

        self._current.notes = notes

    # ===== Step 3: 保存 =====
    def save(self) -> str:
        if self._current is None:
            raise RuntimeError("无标定数据可保存")

        self._records.append(self._current)
        self._persist()
        return self._current.timestamp

    def _get_db_path(self) -> Optional[str]:
        """获取标定数据库路径，兼容打包环境和开发环境。"""
        if get_config_dir is not None:
            return str(get_config_dir() / CALIBRATION_DB)
        # 回退：repair_app/utils -> repository root/config
        return str(Path(__file__).resolve().parents[2] / "config" / CALIBRATION_DB)

    def _load(self) -> None:
        path = self._get_db_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            allowed_fields = {item.name for item in fields(CalibrationRecord)}
            for item in data.get("records", []):
                if not isinstance(item, dict):
                    continue
                filtered = {k: v for k, v in item.items() if k in allowed_fields}
                self._records.append(CalibrationRecord(**filtered))
        except Exception as e:
            logger.warning(f"加载标定数据库失败: {e}")

    def _persist(self) -> None:
        path = self._get_db_path()
        if path is None:
            logger.warning("无法确定标定数据库路径，数据未保存")
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "version": "2026-06-v2.1",
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "records": [
                {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
                for r in self._records
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ===== 查询 =====
    @property
    def records(self) -> list[CalibrationRecord]:
        return list(self._records)

    def get_latest_for_material(self, material: str) -> Optional[CalibrationRecord]:
        for r in reversed(self._records):
            if r.material == material:
                return r
        return None

    def get_correction_factors(self, material: str) -> dict[str, float]:
        """获取某材料的最新修正系数。"""
        r = self.get_latest_for_material(material)
        if r is None:
            return {"width": 1.0, "height": 1.0, "efficiency": 1.0}
        return {
            "width": r.width_correction,
            "height": r.height_correction,
            "efficiency": r.efficiency_correction,
        }
