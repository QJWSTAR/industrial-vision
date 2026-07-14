"""Coordination service — mediates between UI and core/communication layers.

UI 层不得直接调用 core/communication 模块，所有调用必须通过此 Service。
这是 H1-H3 架构违规修复的中介层。
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Any

from repair_app.core.defect_sample import generate_defect_sample
from repair_app.core.normal_estimator import estimate_normals
from repair_app.core.feasibility_checker import FeasibilityChecker, WarningLevel
from repair_app.core.material_database import get_material_db
from repair_app.communication.repair_serialization import (
    build_repair_request,
    parse_repair_result,
)
from repair_app.communication.repair_protocol_pb2 import MaterialType, RepairStatusCode

# 通信层迁移：优先使用 bridge 适配器（LegacyZmqClient），旧版 ZmqRepairClient 仅作回退。
# 详见 docs/MIGRATION_REPORT.md
try:
    from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient
    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False
    LegacyZmqClient = None

try:
    from repair_app.communication.zmq_client import ZmqRepairClient  # noqa: F401  (旧版回退)
    _ZMQ_AVAILABLE = True
except ImportError:
    _ZMQ_AVAILABLE = False
    ZmqRepairClient = None


# 材料名到 protobuf 枚举的映射（从 main_window.py 迁移）
_PROTO_MATERIAL_MAP = {
    "MATERIAL_UNSPECIFIED": MaterialType.MATERIAL_UNSPECIFIED,
    "STEEL_316L": MaterialType.STEEL_316L,
    "INCONEL_718": MaterialType.INCONEL_718,
    "TITANIUM_TI64": MaterialType.TITANIUM_TI64,
    "ALUMINUM_6061": MaterialType.ALUMINUM_6061,
    "COPPER": MaterialType.COPPER,
}


class CoordinationService:
    """UI 层与 core/communication 层之间的中介服务。

    UI 层通过此服务访问算法和通信功能，不直接导入 core/communication 模块。
    """

    # 枚举透传（UI 层需要用于比较和字典映射）
    WarningLevel = WarningLevel
    MaterialType = MaterialType
    RepairStatusCode = RepairStatusCode

    @property
    def zmq_available(self) -> bool:
        """ZMQ 通信模块是否可用（bridge 或旧版任一可用即视为可用）。"""
        return _BRIDGE_AVAILABLE or _ZMQ_AVAILABLE

    @property
    def bridge_active(self) -> bool:
        """bridge 通信层是否为当前生产路径。"""
        return _BRIDGE_AVAILABLE

    @property
    def proto_material_map(self) -> dict[str, Any]:
        """材料名到 protobuf 枚举的映射字典。"""
        return _PROTO_MATERIAL_MAP

    @staticmethod
    def generate_sample_defect(
        defect_types: list[str],
        seed: int = 42,
        n_points: int = 8000,
    ) -> tuple:
        """生成缺陷样本点云。"""
        return generate_defect_sample(
            defect_types=defect_types, seed=seed, n_points=n_points
        )

    @staticmethod
    def estimate_normals(xyz: np.ndarray, k: int = 30) -> np.ndarray:
        """估计点云法向量。"""
        return estimate_normals(xyz, k=k)

    @staticmethod
    def create_feasibility_checker(material=None) -> FeasibilityChecker:
        """创建可行性检查器实例。"""
        return FeasibilityChecker(material) if material else FeasibilityChecker()

    @staticmethod
    def get_material_database():
        """获取材料数据库单例。"""
        return get_material_db()

    @staticmethod
    def build_repair_request(
        xyz: np.ndarray,
        normals: np.ndarray,
        **kwargs,
    ):
        """构建修复请求（序列化为 protobuf）。"""
        mat_code = kwargs.pop("material", None)
        if isinstance(mat_code, str):
            kwargs["material"] = _PROTO_MATERIAL_MAP.get(
                mat_code, MaterialType.MATERIAL_UNSPECIFIED
            )
        return build_repair_request(xyz, normals, **kwargs)

    @staticmethod
    def parse_repair_result(result_bytes: bytes) -> dict:
        """解析修复结果。"""
        return parse_repair_result(result_bytes)

    @staticmethod
    def is_repair_success(result: dict) -> bool:
        """检查修复结果是否成功。"""
        return result.get("status_code") == RepairStatusCode.SUCCESS

    @staticmethod
    def create_zmq_client():
        """创建 ZMQ 修复客户端实例。

        返回 bridge 适配器 LegacyZmqClient（生产路径）；
        bridge 不可用时回退到旧版 ZmqRepairClient；
        两者均不可用时返回 None。
        """
        if _BRIDGE_AVAILABLE:
            return LegacyZmqClient()
        if _ZMQ_AVAILABLE:
            return ZmqRepairClient()
        return None
