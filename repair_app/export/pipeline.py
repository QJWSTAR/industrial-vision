"""Export Pipeline — 统一导出管线（可扩展 / 可注册 / 无需修改 MainWindow）。

架构：
- BaseExporter: 抽象基类，定义 run() 三步流程（get_config → get_output_path → export）
- ExporterRegistry: 单例注册中心，register/list/get/export
- ExportResult: 统一返回类型

设计原则：
1. 新增导出格式只需写一个 BaseExporter 子类并 @register，MainWindow 自动发现
2. 每个 Exporter 控制自己的完整流程（含配置对话框/文件对话框/导出逻辑）
3. MainWindow 只调用 exporter.run(parent, session, path_manager)，不关心具体格式
4. 低层导出器（GCodeExporter/RepairReport/RobotExporter）被 Pipeline 复用，不重写

用法：
    from repair_app.export.pipeline import ExporterRegistry, register

    @register
    class MyExporter(BaseExporter):
        name = "my_format"
        display_name = "My Format"
        ...

    # MainWindow 中：
    for exp in ExporterRegistry.list():
        btn = QPushButton(f"{exp.icon} {exp.display_name}")
        btn.clicked.connect(lambda _, n=exp.name: self._on_export(n))

    def _on_export(self, name):
        ExporterRegistry.run(name, self, self._session, self._path_manager)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from repair_app.core.repair_session import RepairSession
from repair_app.utils.logger_config import info, error as log_error, warning


@dataclass
class ExportResult:
    """统一导出结果。"""
    ok: bool
    output_path: str = ""
    error: str = ""
    warnings: list = field(default_factory=list)


class BaseExporter(ABC):
    """导出器抽象基类。

    子类需设置类属性：name/display_name/icon/tooltip/extension/filter/requires
    子类需实现：export(session, output_path, **config) -> ExportResult

    可选重写：
    - get_config(parent, session) -> Optional[dict]  显示配置对话框
    - get_output_path(session, path_manager, **config) -> Optional[str]  显示文件对话框
    - run(parent, session, path_manager) -> ExportResult  完整流程（robot 重写此方法）
    """

    # ===== 类属性（子类必须设置）=====
    name: str = ""              # 唯一标识符，如 "gcode"
    display_name: str = ""      # UI 显示名，如 "G-code"
    icon: str = "📤"            # UI 图标 emoji
    tooltip: str = ""           # UI 揥示文本
    extension: str = ""         # 默认文件扩展名，如 ".nc"
    filter: str = ""            # QFileDialog 过滤器，如 "G-code (*.nc *.gcode)"
    requires: tuple = ()        # 所需 session 字段路径，如 ("waypoint.mock",)
    sort_order: int = 100       # 排序权重（越小越靠前）

    # ===== 核心流程 =====

    def run(self, parent: Any, session: RepairSession, path_manager: Any) -> ExportResult:
        """主入口：get_config → get_output_path → export。

        大多数导出器使用此默认实现。特殊导出器（如 robot，需自定义对话框）
        可重写此方法。
        """
        if not self.is_ready(session):
            warning(f"[Export:{self.name}] 数据不完整，跳过导出")
            return ExportResult(ok=False, error="数据不完整，无法导出")

        # 1. 配置对话框（默认无配置）
        config = self.get_config(parent, session)
        if config is None:
            return ExportResult(ok=False, error="用户取消")

        # 2. 文件对话框
        output_path = self.get_output_path(session, path_manager, **config)
        if not output_path:
            return ExportResult(ok=False, error="用户取消")

        # 3. 执行导出
        result = self.export(session, output_path, **config)
        if result.ok:
            info(f"[Export:{self.name}] 导出成功: {result.output_path}")
        else:
            log_error(f"[Export:{self.name}] 导出失败: {result.error}")
        return result

    # ===== 可重写方法 =====

    def get_config(self, parent: Any, session: RepairSession) -> Optional[dict]:
        """配置对话框。返回 None 表示用户取消。默认无配置。"""
        return {}

    def get_output_path(
        self,
        session: RepairSession,
        path_manager: Any,
        **config,
    ) -> Optional[str]:
        """文件保存对话框。默认使用 QFileDialog。"""
        from PySide6.QtWidgets import QFileDialog
        default_path = self.default_path(session, path_manager)
        fp, _ = QFileDialog.getSaveFileName(
            None, f"导出 {self.display_name}", default_path, self.filter,
        )
        return fp if fp else None

    def default_path(self, session: RepairSession, path_manager: Any) -> str:
        """默认输出路径。子类可重写。"""
        base = "repair"
        if session.point_cloud.path:
            import os
            base = os.path.splitext(os.path.basename(session.point_cloud.path))[0]
        return f"{base}{self.extension}"

    # ===== 抽象方法 =====

    @abstractmethod
    def export(
        self,
        session: RepairSession,
        output_path: str,
        **config,
    ) -> ExportResult:
        """执行导出。子类必须实现。"""
        ...

    # ===== 辅助方法 =====

    def is_ready(self, session: RepairSession) -> bool:
        """检查所需 session 字段是否已填充。"""
        for field_path in self.requires:
            obj = session
            for attr in field_path.split('.'):
                obj = getattr(obj, attr, None)
                if obj is None:
                    return False
            if isinstance(obj, (list, str)) and len(obj) == 0:
                return False
            try:
                import numpy as np
                if isinstance(obj, np.ndarray) and len(obj) == 0:
                    return False
            except ImportError:
                pass
        return True


class ExporterRegistry:
    """导出器注册中心（单例）。

    用法：
        ExporterRegistry.register(MyExporter())
        ExporterRegistry.list()  → [exporter, ...]
        ExporterRegistry.get("gcode")  → BaseExporter
        ExporterRegistry.run("gcode", parent, session, path_manager)  → ExportResult
    """

    _exporters: dict = {}
    _order: list = []

    @classmethod
    def register(cls, exporter: BaseExporter) -> BaseExporter:
        """注册导出器。可用作装饰器（需实例化后注册）。"""
        if not exporter.name:
            raise ValueError(f"导出器 {type(exporter).__name__} 缺少 name 属性")
        previous = cls._exporters.get(exporter.name)
        if previous is not None and type(previous) is not type(exporter):
            warning(
                f"[ExportRegistry] 名称 {exporter.name!r} 已由 "
                f"{type(previous).__name__} 注册，将替换为 "
                f"{type(exporter).__name__}"
            )
        cls._exporters[exporter.name] = exporter
        if exporter.name not in cls._order:
            cls._order.append(exporter.name)
        info(f"[ExportRegistry] 已注册: {exporter.name} ({exporter.display_name})")
        return exporter

    @classmethod
    def get(cls, name: str) -> Optional[BaseExporter]:
        """按名称获取导出器。"""
        return cls._exporters.get(name)

    @classmethod
    def list(cls) -> list:
        """列出所有已注册导出器（按 sort_order + 注册顺序排序）。"""
        exporters = [cls._exporters[n] for n in cls._order]
        exporters.sort(key=lambda e: e.sort_order)
        return exporters

    @classmethod
    def list_ready(cls, session: RepairSession) -> list:
        """列出当前 session 可用的导出器。"""
        return [e for e in cls.list() if e.is_ready(session)]

    @classmethod
    def run(
        cls,
        name: str,
        parent: Any,
        session: RepairSession,
        path_manager: Any,
    ) -> ExportResult:
        """执行指定格式的完整导出流程。"""
        exporter = cls.get(name)
        if exporter is None:
            return ExportResult(ok=False, error=f"未知导出格式: {name}")
        return exporter.run(parent, session, path_manager)

    @classmethod
    def reset(cls) -> None:
        """重置注册表（仅用于测试）。"""
        cls._exporters.clear()
        cls._order.clear()


def register(exporter_class):
    """类装饰器：实例化并注册导出器。

    用法：
        @register
        class MyExporter(BaseExporter):
            name = "my_format"
            ...
    """
    instance = exporter_class()
    ExporterRegistry.register(instance)
    return exporter_class
