"""RepairSession — 统一 Repair 数据结构（单一真相源）。

设计原则：
1. 整个软件只维护一份 RepairSession 实例
2. 所有模块（MainWindow/Worker/Export/Report/Validation）共享同一 Session 引用
3. 禁止重复缓存：数据只在 Session 中存储一次
4. 禁止重复计算：派生指标（Metrics/Report）在主数据变更时由主线程统一更新
5. 禁止 .copy()：Worker 接收 Session 引用，只读不写，通过信号回传结果

线程安全：
- Worker 线程只读 Session 中的 ndarray（ndarray 读操作线程安全）
- 主线程在 Worker 结束后写入 Session（通过信号槽回到主线程）
- 计算期间主线程 is_busy=True，不会修改被 Worker 读取的数据

9 个组成部分（用户指定）：
- point_cloud: 点云 + 法向量 + 源文件路径
- selection: 选区掩码
- waypoint: 航点（mock/full/velocity/layers）
- layer: 层数据缓存
- morphology: 形貌预测结果 + mock 标记
- metrics: 派生指标（缺陷/路径/层/统计/质量）
- validation: 验证结果
- output: 输出文件状态
- report: 报告字段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class PointCloudData:
    """点云数据（原始输入）。"""
    xyz: Optional[np.ndarray] = None        # (N, 3) 基材点云坐标
    normals: Optional[np.ndarray] = None     # (N, 3) 法向量
    path: Optional[str] = None               # 源文件路径


@dataclass
class SelectionData:
    """选区数据（用户交互）。"""
    mask: Optional[np.ndarray] = None        # (N,) bool 选区掩码


@dataclass
class WaypointData:
    """航点数据（路径规划输出）。"""
    mock: Optional[np.ndarray] = None         # (M, >=3) 简化航点（G-code/Report 用）
    full: Optional[np.ndarray] = None         # (M, >=6) 含法向量的完整航点（远程结果，可视化用）
    velocity_list: Optional[list] = None      # (M,) str 速度标签
    layers: Optional[np.ndarray] = None       # (M,) int 层号


@dataclass
class LayerDataCache:
    """层号 → 该层 mesh/waypoints 数据缓存。"""
    by_layer: dict = field(default_factory=dict)


@dataclass
class MorphologyData:
    """形貌预测数据。"""
    # Composite visualization cloud kept for backward compatibility.
    repair_xyz: Optional[np.ndarray] = None  # (N+K, 3) 基材 + 修复点
    # Canonical deposited points. Consumers must not infer these by comparing
    # array lengths because a morphology result may legitimately contain fewer
    # points than the substrate.
    repair_only_xyz: Optional[np.ndarray] = None  # (K, 3) 仅修复/沉积点
    is_mock: bool = False                    # True=本地启发式 mock，False=MATLAB 真实结果

    def set_repair_points(
        self,
        substrate_xyz: Optional[np.ndarray],
        repair_only_xyz: np.ndarray,
    ) -> None:
        """Store explicit repair points and derive the visualization cloud."""
        repair = np.asarray(repair_only_xyz)
        if repair.ndim != 2 or repair.shape[1] != 3:
            raise ValueError(
                f"repair_only_xyz must have shape (K, 3), got {repair.shape}"
            )
        self.repair_only_xyz = repair
        if substrate_xyz is None:
            self.repair_xyz = repair
            return
        substrate = np.asarray(substrate_xyz)
        if substrate.ndim != 2 or substrate.shape[1] != 3:
            raise ValueError(
                f"substrate_xyz must have shape (N, 3), got {substrate.shape}"
            )
        self.repair_xyz = np.vstack([substrate, repair])

    def get_repair_points(
        self,
        substrate_xyz: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """Return repair-only points, with one centralized legacy fallback."""
        if self.repair_only_xyz is not None:
            return self.repair_only_xyz
        # Compatibility for older project snapshots/tests that populate only
        # repair_xyz. New producers must use set_repair_points().
        if self.repair_xyz is None:
            return None
        if substrate_xyz is not None:
            substrate = np.asarray(substrate_xyz)
            composite = np.asarray(self.repair_xyz)
            if (
                substrate.ndim == 2
                and composite.ndim == 2
                and substrate.shape[1:] == composite.shape[1:]
                and len(composite) >= len(substrate)
                and np.array_equal(composite[:len(substrate)], substrate)
            ):
                return composite[len(substrate):]
        return self.repair_xyz

    def clear(self) -> None:
        self.repair_xyz = None
        self.repair_only_xyz = None
        self.is_mock = False


@dataclass
class MetricsData:
    """派生指标（由主线程在主数据变更时统一计算，禁止重复计算）。"""
    defect: dict = field(default_factory=dict)       # point_count/depth_mm/area_mm2/volume_mm3
    path: dict = field(default_factory=dict)         # path_length_mm/estimated_time_s
    layers: list = field(default_factory=list)       # 逐层沉积数据
    statistics: dict = field(default_factory=dict)   # 统计信息
    quality: dict = field(default_factory=dict)      # 质量评估


@dataclass
class ValidationData:
    """验证数据。"""
    result: Any = None                             # ExportValidationResult
    expected_n_layers: Optional[int] = None
    expected_layer_height: Optional[float] = None


@dataclass
class OutputData:
    """输出文件状态。"""
    files_saved: bool = False
    path_output_ready: bool = False
    last_gcode_path: Optional[str] = None
    last_pdf_path: Optional[str] = None
    last_validation_report_path: Optional[str] = None
    last_robot_path: Optional[str] = None
    last_csv_path: Optional[str] = None
    last_json_path: Optional[str] = None
    last_project_path: Optional[str] = None


@dataclass
class ReportData:
    """报告字段（与 RepairReport 6 个 dict 字段 1:1 对应，禁止重复同步）。"""
    scan_info: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    layers: list = field(default_factory=list)
    statistics: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)


class RepairSession:
    """统一 Repair 数据结构 — 全软件唯一数据源。

    用法：
        session = RepairSession()
        session.point_cloud.xyz = pts            # 主线程写入
        worker = PathPlanningWorker(session, ...) # Worker 只读
        session.waypoint.mock = result           # 主线程在 Worker 完成后写入
    """

    def __init__(self) -> None:
        self.point_cloud = PointCloudData()
        self.selection = SelectionData()
        self.waypoint = WaypointData()
        self.layer = LayerDataCache()
        self.morphology = MorphologyData()
        self.metrics = MetricsData()
        self.validation = ValidationData()
        self.output = OutputData()
        self.report = ReportData()
        # 辅助状态（非 Repair 数据，但需统一管理）
        self.latest_seed: int = 42
        self.repair_mode: str = "repairing"
        self.is_busy: bool = False
        self.feas_result: Any = None  # 可行性检查结果
        self.license_id: str = ""     # 授权 ID（G-code 追溯元数据用）

    def reset(self) -> None:
        """完全重置（新项目加载）。保留 latest_seed 和 repair_mode。"""
        seed = self.latest_seed
        mode = self.repair_mode
        self.point_cloud = PointCloudData()
        self.selection = SelectionData()
        self.waypoint = WaypointData()
        self.layer = LayerDataCache()
        self.morphology = MorphologyData()
        self.metrics = MetricsData()
        self.validation = ValidationData()
        self.output = OutputData()
        self.report = ReportData()
        self.is_busy = False
        self.feas_result = None
        self.latest_seed = seed
        self.repair_mode = mode

    def reset_pipeline(self) -> None:
        """仅重置管线数据（保留点云和选区，用于重新计算）。"""
        self.waypoint = WaypointData()
        self.layer = LayerDataCache()
        self.morphology = MorphologyData()
        self.metrics = MetricsData()
        self.validation = ValidationData()
        self.output = OutputData()
        self.report = ReportData()
        self.feas_result = None

    # ================================================================
    # 状态查询（供 UI 判断就绪状态，避免在各处重复写 None 检查）
    # ================================================================

    def has_point_cloud(self) -> bool:
        return self.point_cloud.xyz is not None and len(self.point_cloud.xyz) > 0

    def has_selection(self) -> bool:
        return self.selection.mask is not None and bool(np.any(self.selection.mask))

    def has_waypoints(self) -> bool:
        return self.waypoint.mock is not None and len(self.waypoint.mock) > 0

    def has_morphology(self) -> bool:
        repair = self.morphology.get_repair_points(self.point_cloud.xyz)
        return repair is not None and len(repair) > 0

    def summary(self) -> str:
        """返回数据状态摘要（用于日志）。"""
        pts = len(self.point_cloud.xyz) if self.has_point_cloud() else 0
        sel = int(np.sum(self.selection.mask)) if self.has_selection() else 0
        wp = len(self.waypoint.mock) if self.has_waypoints() else 0
        if self.has_morphology():
            morph = "mock" if self.morphology.is_mock else "real"
        else:
            morph = "none"
        return (
            f"RepairSession("
            f"pts={pts}, sel={sel}, wp={wp}, "
            f"morph={morph}, ready={self.output.path_output_ready})"
        )
