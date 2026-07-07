"""
material_database.py — 冷喷涂材料参数数据库加载器
Stage 2.3 v2.1：从 material_db.json 加载材料参数
"""

from __future__ import annotations
import json
import os
import threading
from typing import Optional
import numpy as np


class MaterialParams:
    """单种材料的参数封装。"""

    def __init__(self, data: dict) -> None:
        self.name: str = data["name"]
        self.density_kgm3: float = data["density_kgm3"]
        self.v_cr_base_ms: float = data["v_cr_base_ms"]
        self.v_cr_angle_decay: np.ndarray = np.array(data["v_cr_angle_decay"])
        self.max_deposition_efficiency: float = data["max_deposition_efficiency"]
        self.recommend_preheat_temp_c: float = data["recommend_preheat_temp_c"]
        self.single_layer_max_thickness_mm: float = data["single_layer_max_thickness_mm"]
        self.min_spray_spot_width_mm: float = data["min_spray_spot_width_mm"]
        self.max_defect_depth_mm: float = data["max_defect_depth_mm"]
        self.max_sidewall_angle_deg: float = data["max_sidewall_angle_deg"]
        self.thermal_conductivity_wmk: float = data["thermal_conductivity_wmk"]
        self.yield_strength_mpa: float = data["yield_strength_mpa"]
        self.melting_point_c: float = data["melting_point_c"]

    def v_cr_at_angle(self, angle_deg: float) -> float:
        """根据喷涂角度计算有效临界速度（线性插值）。
        angle_deg: 喷涂角度 (0-180)，90°为法向入射。
        """
        deviation = abs(90.0 - angle_deg)  # 偏离法线的角度
        angles = self.v_cr_angle_decay[:, 0]
        factors = self.v_cr_angle_decay[:, 1]
        factor = np.interp(deviation, angles, factors)
        return self.v_cr_base_ms * float(factor)


class MaterialDatabase:
    """材料参数数据库加载与查询。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "material_db.json")
        self._db_path = db_path
        with open(db_path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)
        self._materials: dict[str, MaterialParams] = {}
        for key, val in self._raw["materials"].items():
            self._materials[key] = MaterialParams(val)
        self._default_key: str = self._raw.get("default_material", "STEEL_316L")
        self._thresholds: dict = self._raw.get("feasibility_thresholds", {})

    @property
    def material_keys(self) -> list[str]:
        return list(self._materials.keys())

    @property
    def default_key(self) -> str:
        return self._default_key

    @property
    def thresholds(self) -> dict:
        return dict(self._thresholds)

    def get(self, key: str) -> MaterialParams:
        """获取材料参数，key 不存在时返回默认材料。"""
        if key not in self._materials:
            key = self._default_key
        return self._materials[key]

    def get_default(self) -> MaterialParams:
        return self._materials[self._default_key]


_G_DB: Optional[MaterialDatabase] = None
_G_DB_LOCK = threading.Lock()


def get_material_db() -> MaterialDatabase:
    global _G_DB
    if _G_DB is None:
        with _G_DB_LOCK:
            if _G_DB is None:
                _G_DB = MaterialDatabase()
    return _G_DB
