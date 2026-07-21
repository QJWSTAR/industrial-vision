"""test_pipeline.py — Export Pipeline 与内置导出器测试。

覆盖：
- repair_app/export/pipeline.py：BaseExporter / ExporterRegistry / ExportResult / @register
- repair_app/export/builtin_exporters.py：6 个内置导出器（GCode/Robot/PDF/CSV/JSON/Project）

运行：pytest -m "unit or export" -v
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path（与 conftest.py 保持一致）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import csv
import numpy as np
import pytest
from pathlib import Path

from repair_app.core.repair_session import RepairSession
from repair_app.export.pipeline import BaseExporter, ExporterRegistry, ExportResult, register
from repair_app.export import builtin_exporters  # 触发注册

# 检测 reportlab 是否可用（PDF 测试在缺失时 skip）
try:
    import reportlab  # noqa: F401
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


# ============================================================
# 辅助函数 / fixtures
# ============================================================

def make_session_with_waypoints() -> RepairSession:
    """构造含点云/选区/航点/形貌/指标的完整 session（供多数测试复用）。"""
    session = RepairSession()
    session.point_cloud.xyz = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32)
    session.selection.mask = np.array([False, True, True, False])
    session.waypoint.mock = np.array([[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.float32)
    session.waypoint.layers = np.array([0, 0, 1, 1])
    session.morphology.repair_xyz = np.array([[0.5, 0.5, 2], [0.5, 0.5, 2.5]], dtype=np.float32)
    session.report.parameters = {"layer_height_mm": 2.0, "traversing_speed_mms": 500.0}
    session.metrics.defect = {"point_count": 2, "volume_mm3": 4.0, "area_mm2": 2.0}
    session.metrics.path = {"path_length_mm": 100.0, "estimated_time_s": 10.0}
    return session


def make_session_full() -> RepairSession:
    """构造含全部 metrics + report 字段的完整 session（覆盖所有 if 分支）。"""
    session = make_session_with_waypoints()
    # metrics 全部填充
    session.metrics.defect = {
        "point_count": 2, "volume_mm3": 4.0, "area_mm2": 2.0, "depth_mm": 1.0,
    }
    session.metrics.path = {"path_length_mm": 100.0, "estimated_time_s": 10.0}
    session.metrics.statistics = {"mean": 1.5, "min": 0.5, "max": 2.5, "std": 0.8}
    session.metrics.quality = {"uniformity_score": 0.92, "coverage_rate": 0.88, "overspray_ratio": 0.05}
    session.metrics.layers = [
        {"points": 50, "avg_height": 0.5, "mass_g": 0.12},
        {"points": 30, "avg_height": 1.0, "mass_g": 0.08},
    ]
    # report 全部填充（与 RepairReport 6 个 dict 字段 1:1 对应）
    session.report.scan_info = {
        "scan_id": "SCAN-001", "points": 4,
        "defect_volume_mm3": 4.0, "defect_depth_mm": 1.0, "material": "Cu",
    }
    session.report.parameters = {"layer_height_mm": 2.0, "traversing_speed_mms": 500.0}
    session.report.results = {"path_length_mm": 100.0, "estimated_time_s": 10.0}
    session.report.layers = [
        {"points": 50, "avg_height": 0.5, "mass_g": 0.12},
    ]
    session.report.statistics = {"mean": 1.5, "min": 0.5, "max": 2.5, "std": 0.8}
    session.report.quality = {"uniformity_score": 0.92, "coverage_rate": 0.88}
    return session


@pytest.fixture
def path_manager(tmp_path, monkeypatch):
    """创建指向 tmp_path 的 PathManager（隔离用户目录）。

    PathManager 默认无 root 参数，通过 CSAM_USER_DATA 环境变量重定向到 tmp_path，
    并重置单例确保新建实例使用临时目录。
    """
    monkeypatch.setenv("CSAM_USER_DATA", str(tmp_path))
    from repair_app.software.path_manager import PathManager
    PathManager._instance = None  # 重置单例
    pm = PathManager()
    yield pm
    PathManager._instance = None  # 清理单例，避免污染后续测试


@pytest.fixture
def restore_registry():
    """保存并恢复注册表状态（防止测试间相互污染）。"""
    saved_exporters = dict(ExporterRegistry._exporters)
    saved_order = list(ExporterRegistry._order)
    yield
    ExporterRegistry._exporters = saved_exporters
    ExporterRegistry._order = saved_order


class _DummyExporter(BaseExporter):
    """用于测试的具象导出器（覆写 export 记录调用）。"""

    name = "dummy"
    display_name = "Dummy"
    icon = "🧪"
    extension = ".dummy"
    filter = "Dummy (*.dummy)"
    requires = ("waypoint.mock",)
    sort_order = 999

    def __init__(self):
        self.export_called = False
        self.last_config = None
        self.last_output_path = None

    def export(self, session, output_path, **config):
        self.export_called = True
        self.last_config = config
        self.last_output_path = output_path
        return ExportResult(ok=True, output_path=output_path)


# ============================================================
# 1. ExportResult 数据类
# ============================================================
@pytest.mark.unit
class TestExportResult:
    """ExportResult 数据类测试。"""

    def test_default_values(self):
        """ok 必填，其余字段默认为空。"""
        r = ExportResult(ok=True)
        assert r.ok is True
        assert r.output_path == ""
        assert r.error == ""
        assert r.warnings == []

    def test_custom_values(self):
        """自定义全部字段。"""
        r = ExportResult(ok=False, output_path="/x.nc", error="失败", warnings=["w1", "w2"])
        assert r.ok is False
        assert r.output_path == "/x.nc"
        assert r.error == "失败"
        assert r.warnings == ["w1", "w2"]

    def test_warnings_default_independent(self):
        """默认 warnings 列表互不影响（field default_factory）。"""
        r1 = ExportResult(ok=True)
        r2 = ExportResult(ok=True)
        r1.warnings.append("x")
        assert r2.warnings == []
        assert r1.warnings == ["x"]

    def test_equality(self):
        """dataclass 默认 __eq__。"""
        a = ExportResult(ok=True, output_path="/a")
        b = ExportResult(ok=True, output_path="/a")
        assert a == b


# ============================================================
# 2. BaseExporter 抽象基类
# ============================================================
@pytest.mark.unit
class TestBaseExporter:
    """BaseExporter 抽象基类测试。"""

    def test_cannot_instantiate_abstract(self):
        """含抽象方法 export，不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseExporter()

    def test_default_class_attributes(self):
        """基类默认类属性值。"""
        assert BaseExporter.icon == "📤"
        assert BaseExporter.sort_order == 100
        assert BaseExporter.requires == ()
        assert BaseExporter.name == ""
        assert BaseExporter.extension == ""

    def test_get_config_default_returns_empty_dict(self):
        """get_config 默认返回空 dict（无配置）。"""
        exp = _DummyExporter()
        assert exp.get_config(None, RepairSession()) == {}

    def test_default_path_no_point_cloud(self):
        """default_path 无点云路径时用 'repair' 做基名。"""
        exp = _DummyExporter()
        assert exp.default_path(RepairSession(), None) == "repair.dummy"

    def test_default_path_with_point_cloud(self):
        """default_path 有点云路径时用文件名（去扩展名）做基名。"""
        exp = _DummyExporter()
        session = RepairSession()
        session.point_cloud.path = "/data/scan_model.xyz"
        assert exp.default_path(session, None) == "scan_model.dummy"

    def test_is_ready_empty_session(self):
        """空 session 不满足 requires。"""
        exp = _DummyExporter()
        assert exp.is_ready(RepairSession()) is False

    def test_is_ready_filled_session(self):
        """填充航点后 is_ready 为 True。"""
        exp = _DummyExporter()
        assert exp.is_ready(make_session_with_waypoints()) is True

    def test_is_ready_empty_list(self):
        """requires 字段为空 list 时 is_ready 为 False。"""
        exp = _DummyExporter()
        session = RepairSession()
        session.waypoint.mock = []
        assert exp.is_ready(session) is False

    def test_is_ready_empty_ndarray(self):
        """requires 字段为空 ndarray 时 is_ready 为 False。"""
        exp = _DummyExporter()
        session = RepairSession()
        session.waypoint.mock = np.array([])
        assert exp.is_ready(session) is False

    def test_is_ready_none_attribute(self):
        """requires 字段链路中途为 None 时 is_ready 为 False。"""
        class _NestedReq(BaseExporter):
            name = "nested_req"
            requires = ("morphology.repair_xyz",)

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        exp = _NestedReq()
        assert exp.is_ready(RepairSession()) is False
        session = RepairSession()
        session.morphology.repair_xyz = np.array([[1, 2, 3]])
        assert exp.is_ready(session) is True

    def test_get_output_path_uses_filedialog(self, qapp, monkeypatch):
        """get_output_path 默认使用 QFileDialog.getSaveFileName。"""
        from PySide6.QtWidgets import QFileDialog
        captured = {}

        def fake_get_save(*args, **kwargs):
            captured["args"] = args
            return ("/tmp/fake_output.dummy", "")

        monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save)
        exp = _DummyExporter()
        path = exp.get_output_path(RepairSession(), None)
        assert path == "/tmp/fake_output.dummy"
        # 验证传给 QFileDialog 的标题含 display_name
        assert "Dummy" in captured["args"][1]

    def test_get_output_path_cancel_returns_none(self, qapp, monkeypatch):
        """用户在文件对话框点取消（返回空串）→ 返回 None。"""
        from PySide6.QtWidgets import QFileDialog
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
        exp = _DummyExporter()
        assert exp.get_output_path(RepairSession(), None) is None

    def test_run_not_ready(self):
        """run 数据不完整时返回失败。"""
        exp = _DummyExporter()
        result = exp.run(None, RepairSession(), None)
        assert result.ok is False
        assert "数据不完整" in result.error

    def test_run_config_cancelled(self):
        """get_config 返回 None → 用户取消。"""
        class _CancelConfig(_DummyExporter):
            name = "cancel_config"
            display_name = "CancelConfig"

            def get_config(self, parent, session):
                return None

        exp = _CancelConfig()
        result = exp.run(None, make_session_with_waypoints(), None)
        assert result.ok is False
        assert result.error == "用户取消"

    def test_run_path_cancelled(self, qapp, monkeypatch):
        """get_output_path 返回空 → 用户取消。"""
        from PySide6.QtWidgets import QFileDialog
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
        exp = _DummyExporter()
        result = exp.run(None, make_session_with_waypoints(), None)
        assert result.ok is False
        assert result.error == "用户取消"

    def test_run_happy_path(self, qapp, monkeypatch, tmp_path):
        """完整流程：get_config → get_output_path → export。"""
        from PySide6.QtWidgets import QFileDialog
        out = str(tmp_path / "out.dummy")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))
        exp = _DummyExporter()
        result = exp.run(None, make_session_with_waypoints(), None)
        assert result.ok is True
        assert result.output_path == out
        assert exp.export_called is True


# ============================================================
# 3. ExporterRegistry 注册中心
# ============================================================
@pytest.mark.unit
class TestExporterRegistry:
    """ExporterRegistry 单例注册中心测试。"""

    def test_list_contains_all_builtins(self):
        """list 返回 6 个内置导出器。"""
        names = [e.name for e in ExporterRegistry.list()]
        for n in ("gcode", "robot", "pdf", "csv", "json", "project"):
            assert n in names, f"{n} 未注册"

    def test_get_existing(self):
        """get 返回已注册导出器。"""
        exp = ExporterRegistry.get("gcode")
        assert exp is not None
        assert exp.name == "gcode"
        assert exp.display_name == "G-code"

    def test_get_unknown_returns_none(self):
        """get 未知名称返回 None。"""
        assert ExporterRegistry.get("nonexistent_xyz") is None

    def test_register_instance(self, restore_registry):
        """register 注册实例并可取出。"""
        exp = _DummyExporter()
        ExporterRegistry.register(exp)
        assert ExporterRegistry.get("dummy") is exp

    def test_register_returns_exporter(self, restore_registry):
        """register 返回被注册的导出器实例。"""
        exp = _DummyExporter()
        returned = ExporterRegistry.register(exp)
        assert returned is exp

    def test_register_empty_name_raises(self, restore_registry):
        """register 空 name 抛 ValueError。"""
        class _NoName(BaseExporter):
            name = ""

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        with pytest.raises(ValueError):
            ExporterRegistry.register(_NoName())

    def test_register_updates_order(self, restore_registry):
        """register 后名称加入 _order。"""
        class _Ordered(BaseExporter):
            name = "test_ordered"
            sort_order = 100

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        ExporterRegistry.register(_Ordered())
        assert "test_ordered" in ExporterRegistry._order

    def test_register_same_name_overwrites(self, restore_registry):
        """同名注册覆盖旧实例（_order 不重复）。"""
        class _V1(BaseExporter):
            name = "overwrite_test"
            display_name = "V1"

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        class _V2(BaseExporter):
            name = "overwrite_test"
            display_name = "V2"

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        ExporterRegistry.register(_V1())
        ExporterRegistry.register(_V2())
        assert ExporterRegistry.get("overwrite_test").display_name == "V2"
        # _order 中只出现一次
        assert ExporterRegistry._order.count("overwrite_test") == 1

    def test_list_ready_empty_session(self):
        """list_ready 空 session 只返回 requires=() 的导出器。"""
        ready_names = [e.name for e in ExporterRegistry.list_ready(RepairSession())]
        assert "project" in ready_names  # requires=()
        assert "gcode" not in ready_names
        assert "pdf" not in ready_names
        assert "json" not in ready_names
        assert "csv" not in ready_names
        assert "robot" not in ready_names

    def test_list_ready_filled_session(self):
        """list_ready 完整 session 返回全部内置导出器。"""
        session = make_session_with_waypoints()
        ready_names = [e.name for e in ExporterRegistry.list_ready(session)]
        for n in ("gcode", "robot", "csv", "pdf", "json", "project"):
            assert n in ready_names, f"{n} 应就绪"

    def test_run_unknown_format(self):
        """run 未知格式返回失败。"""
        result = ExporterRegistry.run("unknown_format", None, RepairSession(), None)
        assert result.ok is False
        assert "未知导出格式" in result.error

    def test_run_dispatches_to_exporter(self, restore_registry, qapp, monkeypatch, tmp_path):
        """run 按名称调用对应导出器的 run 方法。"""
        from PySide6.QtWidgets import QFileDialog
        out = str(tmp_path / "reg_out.dummy")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))
        exp = _DummyExporter()
        ExporterRegistry.register(exp)
        result = ExporterRegistry.run("dummy", None, make_session_with_waypoints(), None)
        assert result.ok is True
        assert exp.export_called is True

    def test_reset(self, restore_registry):
        """reset 清空注册表。"""
        ExporterRegistry.reset()
        assert ExporterRegistry.list() == []
        assert ExporterRegistry.get("gcode") is None
        assert ExporterRegistry._order == []


# ============================================================
# 4. @register 装饰器
# ============================================================
@pytest.mark.unit
class TestRegisterDecorator:
    """@register 类装饰器测试。"""

    def test_decorator_registers_instance(self, restore_registry):
        """@register 实例化并注册导出器。"""
        @register
        class _CustomExp(BaseExporter):
            name = "custom_decorator_test"
            display_name = "Custom"

            def export(self, session, output_path, **config):
                return ExportResult(ok=True, output_path=output_path)

        exp = ExporterRegistry.get("custom_decorator_test")
        assert exp is not None
        assert exp.display_name == "Custom"
        assert isinstance(exp, BaseExporter)

    def test_decorator_returns_original_class(self, restore_registry):
        """@register 返回原类（非实例），可继续实例化。"""
        @register
        class _ReturnsClass(BaseExporter):
            name = "returns_class_test"
            display_name = "ReturnsClass"

            def export(self, session, output_path, **config):
                return ExportResult(ok=True)

        # 装饰后名称仍指向类
        assert isinstance(_ReturnsClass, type)
        inst = _ReturnsClass()
        assert inst.name == "returns_class_test"

    def test_decorator_with_run(self, restore_registry, qapp, monkeypatch, tmp_path):
        """@register 注册的导出器可通过 Registry.run 调用。"""
        from PySide6.QtWidgets import QFileDialog
        out = str(tmp_path / "deco_out.dummy")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))

        @register
        class _Runnable(BaseExporter):
            name = "runnable_test"
            display_name = "Runnable"
            requires = ("waypoint.mock",)

            def export(self, session, output_path, **config):
                return ExportResult(ok=True, output_path=output_path)

        result = ExporterRegistry.run("runnable_test", None, make_session_with_waypoints(), None)
        assert result.ok is True
        assert result.output_path == out


# ============================================================
# 5. 内置导出器类属性
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestBuiltinExportersAttributes:
    """6 个内置导出器类属性测试。"""

    @pytest.mark.parametrize("name,display,icon,ext,requires,sort_order", [
        ("gcode", "G-code", "📤", ".nc", ("waypoint.mock",), 10),
        ("robot", "机器人轨迹", "🤖", ".krl", ("waypoint.mock",), 20),
        ("pdf", "PDF 报告", "📄", ".pdf", ("morphology.repair_xyz",), 30),
        ("csv", "CSV", "📊", ".csv", ("waypoint.mock",), 40),
        ("json", "JSON", "📋", ".json", ("point_cloud.xyz",), 50),
        ("project", "项目保存", "💾", ".csam", (), 60),
    ])
    def test_class_attributes(self, name, display, icon, ext, requires, sort_order):
        """验证每个内置导出器的类属性。"""
        exp = ExporterRegistry.get(name)
        assert exp is not None, f"导出器 {name} 未注册"
        assert exp.name == name
        assert exp.display_name == display
        assert exp.icon == icon
        assert exp.extension == ext
        assert exp.requires == requires
        assert exp.sort_order == sort_order

    def test_all_have_nonempty_filter(self):
        """所有内置导出器 filter 非空。"""
        for name in ("gcode", "robot", "pdf", "csv", "json", "project"):
            exp = ExporterRegistry.get(name)
            assert exp.filter, f"{name} filter 为空"

    def test_all_have_nonempty_tooltip(self):
        """所有内置导出器 tooltip 非空。"""
        for name in ("gcode", "robot", "pdf", "csv", "json", "project"):
            exp = ExporterRegistry.get(name)
            assert exp.tooltip, f"{name} tooltip 为空"


# ============================================================
# 6. 内置导出器 is_ready
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestBuiltinExportersIsReady:
    """内置导出器 is_ready 测试（空 session vs 填充 session）。"""

    @pytest.mark.parametrize("name", ["gcode", "robot", "csv"])
    def test_waypoint_exporters_not_ready_empty(self, name):
        """依赖 waypoint.mock 的导出器在空 session 不就绪。"""
        assert ExporterRegistry.get(name).is_ready(RepairSession()) is False

    @pytest.mark.parametrize("name", ["gcode", "robot", "csv"])
    def test_waypoint_exporters_ready_filled(self, name):
        """依赖 waypoint.mock 的导出器在填充 session 就绪。"""
        assert ExporterRegistry.get(name).is_ready(make_session_with_waypoints()) is True

    def test_pdf_not_ready_empty(self):
        """PDF 依赖 morphology.repair_xyz，空 session 不就绪。"""
        assert ExporterRegistry.get("pdf").is_ready(RepairSession()) is False

    def test_pdf_ready_filled(self):
        """PDF 在填充 session 就绪。"""
        assert ExporterRegistry.get("pdf").is_ready(make_session_with_waypoints()) is True

    def test_json_not_ready_empty(self):
        """JSON 依赖 point_cloud.xyz，空 session 不就绪。"""
        assert ExporterRegistry.get("json").is_ready(RepairSession()) is False

    def test_json_ready_filled(self):
        """JSON 在填充 session 就绪。"""
        assert ExporterRegistry.get("json").is_ready(make_session_with_waypoints()) is True

    def test_project_ready_empty(self):
        """project requires=() → 空 session 也就绪。"""
        assert ExporterRegistry.get("project").is_ready(RepairSession()) is True

    def test_project_ready_filled(self):
        """project 在填充 session 就绪。"""
        assert ExporterRegistry.get("project").is_ready(make_session_with_waypoints()) is True


# ============================================================
# 7. CSVExporter 导出真实 CSV 文件
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestCSVExporter:
    """CSVExporter 测试（航点表 + 指标）。"""

    def test_export_success(self, tmp_path):
        """成功导出 CSV 文件。"""
        exp = ExporterRegistry.get("csv")
        session = make_session_with_waypoints()
        out = tmp_path / "repair.csv"
        result = exp.export(session, str(out))
        assert result.ok is True
        assert result.output_path == str(out)
        assert out.exists()
        assert session.output.last_csv_path == str(out)

    def test_csv_contains_waypoints_section(self, tmp_path):
        """CSV 含航点表表头。"""
        exp = ExporterRegistry.get("csv")
        out = tmp_path / "repair.csv"
        exp.export(make_session_with_waypoints(), str(out))
        content = out.read_text(encoding="utf-8-sig")
        assert "# Waypoints" in content
        assert "x_mm" in content
        assert "y_mm" in content
        assert "z_mm" in content
        assert "layer" in content

    def test_csv_contains_metrics_sections(self, tmp_path):
        """CSV 含缺陷与路径指标区块。"""
        exp = ExporterRegistry.get("csv")
        out = tmp_path / "repair.csv"
        exp.export(make_session_with_waypoints(), str(out))
        content = out.read_text(encoding="utf-8-sig")
        assert "# Defect Metrics" in content
        assert "point_count" in content
        assert "volume_mm3" in content
        assert "# Path Metrics" in content
        assert "path_length_mm" in content

    def test_csv_parse_back_waypoints(self, tmp_path):
        """解析 CSV 验证航点数据正确。"""
        exp = ExporterRegistry.get("csv")
        session = make_session_with_waypoints()
        out = tmp_path / "repair.csv"
        exp.export(session, str(out))
        with open(out, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        # 定位航点表头行
        header_idx = None
        for i, row in enumerate(rows):
            if row and row[0] == "index":
                header_idx = i
                break
        assert header_idx is not None, "未找到航点表头"
        # 后续 4 行为航点数据
        wp_rows = rows[header_idx + 1: header_idx + 5]
        assert len(wp_rows) == 4
        # 第一航点 [0, 0, 1]
        assert wp_rows[0][0] == "0"
        assert float(wp_rows[0][1]) == 0.0  # x
        assert float(wp_rows[0][2]) == 0.0  # y
        assert float(wp_rows[0][3]) == 1.0  # z
        assert int(wp_rows[0][4]) == 0      # layer
        # 第四航点 [0, 1, 1] layer=1
        assert float(wp_rows[3][1]) == 0.0
        assert float(wp_rows[3][2]) == 1.0
        assert int(wp_rows[3][4]) == 1

    def test_csv_default_path(self, path_manager):
        """CSV default_path 指向 exports_dir。"""
        exp = ExporterRegistry.get("csv")
        p = exp.default_path(RepairSession(), path_manager)
        assert p.endswith(".csv")
        assert "exports" in p.replace("\\", "/")

    def test_csv_with_all_metrics_sections(self, tmp_path):
        """CSV 含全部指标区块（statistics/quality/layers）。"""
        exp = ExporterRegistry.get("csv")
        session = make_session_full()  # 含 defect/path/statistics/quality/layers
        out = tmp_path / "repair_full.csv"
        result = exp.export(session, str(out))
        assert result.ok is True
        content = out.read_text(encoding="utf-8-sig")
        # statistics 区块
        assert "# Statistics" in content
        assert "mean" in content
        assert "min" in content
        # quality 区块
        assert "# Quality" in content
        assert "uniformity_score" in content
        # layers 区块
        assert "# Layer Data" in content
        assert "avg_height_mm" in content
        assert "mass_g" in content

    def test_csv_empty_metrics(self, tmp_path):
        """metrics 全部为空 dict 时跳过所有指标区块（覆盖 False 分支）。"""
        exp = ExporterRegistry.get("csv")
        session = make_session_with_waypoints()
        # 清空所有 metrics（保留航点）
        session.metrics.defect = {}
        session.metrics.path = {}
        session.metrics.statistics = {}
        session.metrics.quality = {}
        session.metrics.layers = []
        out = tmp_path / "repair_empty.csv"
        result = exp.export(session, str(out))
        assert result.ok is True
        content = out.read_text(encoding="utf-8-sig")
        # 航点表仍存在
        assert "# Waypoints" in content
        # 指标区块均不存在
        assert "# Defect Metrics" not in content
        assert "# Path Metrics" not in content
        assert "# Statistics" not in content
        assert "# Quality" not in content
        assert "# Layer Data" not in content

    def test_csv_export_exception(self, tmp_path):
        """CSV 导出路径目录不存在时触发异常（except 分支）。"""
        exp = ExporterRegistry.get("csv")
        session = make_session_with_waypoints()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.csv")
        result = exp.export(session, bad_path)
        assert result.ok is False
        assert result.error != ""


# ============================================================
# 8. JSONExporter 导出真实 JSON 文件
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestJSONExporter:
    """JSONExporter 测试（完整 session 快照，ndarray 转 list）。"""

    def test_export_success(self, tmp_path):
        """成功导出 JSON 文件。"""
        exp = ExporterRegistry.get("json")
        session = make_session_with_waypoints()
        out = tmp_path / "session.json"
        result = exp.export(session, str(out))
        assert result.ok is True
        assert result.output_path == str(out)
        assert out.exists()
        assert session.output.last_json_path == str(out)

    def test_json_structure(self, tmp_path):
        """JSON 含完整 session 快照（9 个分区相关字段）。"""
        exp = ExporterRegistry.get("json")
        out = tmp_path / "session.json"
        exp.export(make_session_with_waypoints(), str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["version"] == "1.0.0"
        assert "exported_at" in data
        # 关键分区
        assert "point_cloud" in data
        assert "selection" in data
        assert "waypoint" in data
        assert "morphology" in data
        assert "metrics" in data
        assert "report" in data
        # 子字段
        assert "xyz" in data["point_cloud"]
        assert "mask" in data["selection"]
        assert "mock" in data["waypoint"]
        assert "layers" in data["waypoint"]
        assert "repair_xyz" in data["morphology"]

    def test_json_ndarray_converted_to_list(self, tmp_path):
        """ndarray 转为 list（而非 ndarray repr）。"""
        exp = ExporterRegistry.get("json")
        out = tmp_path / "session.json"
        exp.export(make_session_with_waypoints(), str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
        xyz = data["point_cloud"]["xyz"]
        assert isinstance(xyz, list)
        assert len(xyz) == 4
        assert len(xyz[0]) == 3
        assert xyz[0] == [0.0, 0.0, 0.0]
        assert xyz[1] == [1.0, 0.0, 0.0]
        # 航点
        mock = data["waypoint"]["mock"]
        assert isinstance(mock, list)
        assert mock[1] == [1.0, 0.0, 1.0]
        # 层号
        assert data["waypoint"]["layers"] == [0, 0, 1, 1]
        # 形貌
        assert data["morphology"]["repair_xyz"] == [[0.5, 0.5, 2.0], [0.5, 0.5, 2.5]]
        # 选区掩码
        assert data["selection"]["mask"] == [False, True, True, False]

    def test_ndarray_to_list_static(self):
        """_ndarray_to_list 静态方法递归转换各类型。"""
        from repair_app.export.builtin_exporters import JSONExporter
        # ndarray
        arr = np.array([[1, 2, 3]], dtype=np.float32)
        assert JSONExporter._ndarray_to_list(arr) == [[1.0, 2.0, 3.0]]
        # np.integer → int
        v = JSONExporter._ndarray_to_list(np.int64(5))
        assert v == 5 and isinstance(v, int)
        # np.floating → float
        v = JSONExporter._ndarray_to_list(np.float64(1.5))
        assert v == 1.5 and isinstance(v, float)
        # np.bool_ → bool
        assert JSONExporter._ndarray_to_list(np.bool_(True)) is True
        # dict 递归
        d = {"a": np.array([1, 2]), "b": [np.int64(3)]}
        assert JSONExporter._ndarray_to_list(d) == {"a": [1, 2], "b": [3]}
        # tuple 递归
        assert JSONExporter._ndarray_to_list((np.int64(1), np.float64(2.0))) == [1, 2.0]
        # 其他类型不变
        assert JSONExporter._ndarray_to_list("str") == "str"
        assert JSONExporter._ndarray_to_list(None) is None
        assert JSONExporter._ndarray_to_list(42) == 42

    def test_json_default_path(self, path_manager):
        """JSON default_path 指向 exports_dir。"""
        exp = ExporterRegistry.get("json")
        p = exp.default_path(RepairSession(), path_manager)
        assert p.endswith(".json")
        assert "exports" in p.replace("\\", "/")

    def test_json_export_exception(self, tmp_path):
        """JSON 导出路径目录不存在时触发异常（except 分支）。"""
        exp = ExporterRegistry.get("json")
        session = make_session_with_waypoints()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.json")
        result = exp.export(session, bad_path)
        assert result.ok is False
        assert result.error != ""


# ============================================================
# 9. ProjectSaveExporter 保存 .csam 文件
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestProjectSaveExporter:
    """ProjectSaveExporter 测试（复用 ProjectManager）。"""

    def test_export_creates_csam(self, path_manager):
        """export 使用 ProjectManager 保存 .csam 文件。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        result = exp.export(session, "", path_manager=path_manager)
        assert result.ok is True
        assert result.output_path.endswith(".csam")
        assert Path(result.output_path).exists()
        assert session.output.last_project_path == result.output_path

    def test_export_csam_content(self, path_manager):
        """ .csam 文件含正确状态字段。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        result = exp.export(session, "", path_manager=path_manager)
        data = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
        assert data["version"] == "1.0.0"
        assert "name" in data
        state = data["state"]
        assert state["repair_mode"] == 1  # repair_mode == "repairing"
        assert state["params"] == {"layer_height_mm": 2.0, "traversing_speed_mms": 500.0}
        assert state["selection_summary"]["point_count"] == 2
        assert state["selection_summary"]["volume_mm3"] == 4.0

    def test_export_missing_path_manager(self):
        """缺少 path_manager 返回失败。"""
        exp = ExporterRegistry.get("project")
        result = exp.export(make_session_with_waypoints(), "")
        assert result.ok is False
        assert "path_manager" in result.error

    def test_run(self, path_manager):
        """run 重写：跳过文件对话框，直接用 ProjectManager 决定路径。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        result = exp.run(None, session, path_manager)
        assert result.ok is True
        assert result.output_path.endswith(".csam")
        assert Path(result.output_path).exists()

    def test_default_path(self, path_manager):
        """default_path 指向 projects 目录。"""
        exp = ExporterRegistry.get("project")
        p = exp.default_path(RepairSession(), path_manager)
        assert p.endswith(".csam")
        assert "projects" in p.replace("\\", "/")

    def test_get_output_path_returns_none(self):
        """get_output_path 返回 None（跳过文件对话框）。"""
        exp = ExporterRegistry.get("project")
        assert exp.get_output_path(RepairSession(), None) is None

    def test_export_empty_defect(self, path_manager):
        """metrics.defect 为空时跳过 sel_summary 构建（if False 分支）。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        # 清空 defect，使 if session.metrics.defect 为 False
        session.metrics.defect = {}
        result = exp.export(session, "", path_manager=path_manager)
        assert result.ok is True
        assert result.output_path.endswith(".csam")
        # 验证 .csam 文件中 selection_summary 为空 dict
        data = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
        assert data["state"]["selection_summary"] == {}

    def test_export_non_repairing_mode(self, path_manager):
        """repair_mode 非 'repairing' 时 state.repair_mode=0。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        session.repair_mode = "scanning"  # 非 'repairing'
        result = exp.export(session, "", path_manager=path_manager)
        assert result.ok is True
        data = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
        assert data["state"]["repair_mode"] == 0

    def test_export_exception(self):
        """ProjectManager 抛异常时被捕获（except 分支）。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()

        # 构造一个 project_path 会抛异常的 path_manager
        class _BadPathManager:
            def project_path(self, name):
                raise RuntimeError("路径不可用")

        result = exp.export(session, "", path_manager=_BadPathManager())
        assert result.ok is False
        assert "路径不可用" in result.error

    def test_run_export_failure_logs_error(self):
        """run 中 export 失败时走 log_error 分支（else 分支）。"""
        exp = ExporterRegistry.get("project")
        session = make_session_with_waypoints()
        # 不传 path_manager → export 返回失败 → 走 else 分支
        result = exp.run(None, session, None)
        assert result.ok is False
        assert "path_manager" in result.error


# ============================================================
# 10. GCodeExporter 导出（含验证失败场景）
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestGCodeExporter:
    """GCodeExporter（内置）测试。"""

    def test_get_config(self):
        """get_config 从 session.report.parameters 读取并转换 feed_rate。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        config = exp.get_config(None, session)
        # traversing_speed_mms=500.0 → feed_rate = 500*60 = 30000
        assert config["feed_rate"] == 500.0 * 60
        assert "metadata" in config
        assert config["metadata"]["material"] == "未指定"
        assert config["metadata"]["model_version"] == "unknown"
        assert config["metadata"]["license_id"] == ""

    def test_default_path(self, path_manager):
        """default_path 使用 path_manager.gcode_path。"""
        exp = ExporterRegistry.get("gcode")
        p = exp.default_path(RepairSession(), path_manager)
        assert p.endswith(".nc")
        assert "gcode" in p.replace("\\", "/").lower()

    def test_export_success(self, tmp_path):
        """成功导出 G-code 文件（验证通过）。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        out = tmp_path / "repair.nc"
        config = exp.get_config(None, session)
        result = exp.export(session, str(out), **config)
        assert result.ok is True
        assert result.output_path == str(out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "G90" in content  # 绝对坐标
        assert "M3" in content   # 主轴启动
        assert "G21" in content  # 单位 mm
        # 验证结果写入 session.validation
        assert session.validation.result is not None
        assert session.validation.result.ok is True
        # 输出状态更新
        assert session.output.last_gcode_path == str(out)

    def test_export_validation_failure_negative_z(self, tmp_path):
        """航点 Z 为负 → 安全检查未通过，不生成文件。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        # 设置负 Z 航点（触发 NEGATIVE_HEIGHT 阻断）
        session.waypoint.mock = np.array([[0, 0, -1.0], [1, 0, -1.0]], dtype=np.float32)
        session.waypoint.layers = np.array([0, 0])
        out = tmp_path / "bad.nc"
        config = exp.get_config(None, session)
        result = exp.export(session, str(out), **config)
        assert result.ok is False
        assert "安全检查未通过" in result.error
        assert "负值" in result.error or "碰撞" in result.error
        # 文件不应生成
        assert not out.exists()
        # validation result 写入 session
        assert session.validation.result is not None
        assert session.validation.result.ok is False

    def test_export_empty_waypoints(self):
        """空航点返回失败（航点为空）。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        session.waypoint.mock = np.array([]).reshape(0, 3)
        result = exp.export(session, "/tmp/empty.nc", feed_rate=500.0)
        assert result.ok is False
        assert result.error == "航点为空"

    def test_run_not_ready(self):
        """run 数据不完整返回失败。"""
        exp = ExporterRegistry.get("gcode")
        result = exp.run(None, RepairSession(), None)
        assert result.ok is False
        assert "数据不完整" in result.error

    def test_export_without_metadata(self, tmp_path):
        """不传 metadata 时跳过 set_metadata（if metadata False 分支）。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        out = tmp_path / "no_meta.nc"
        # 只传 feed_rate，不传 metadata
        result = exp.export(session, str(out), feed_rate=500.0)
        assert result.ok is True
        assert out.exists()

    def test_export_invalid_path_triggers_except(self, tmp_path):
        """输出路径目录不存在时触发异常处理（except 分支）。"""
        exp = ExporterRegistry.get("gcode")
        session = make_session_with_waypoints()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.nc")
        config = exp.get_config(None, session)
        result = exp.export(session, bad_path, **config)
        assert result.ok is False
        assert result.error != ""


# ============================================================
# 11. PDFReportExporter 导出
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestPDFReportExporter:
    """PDFReportExporter 测试（reportlab 缺失时 skip）。"""

    def test_default_path(self, path_manager):
        """default_path 指向 pdf 目录并含时间戳。"""
        exp = ExporterRegistry.get("pdf")
        p = exp.default_path(RepairSession(), path_manager)
        assert p.endswith(".pdf")
        assert "pdf" in p.replace("\\", "/").lower()

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_success(self, tmp_path):
        """reportlab 可用时成功导出 PDF。"""
        exp = ExporterRegistry.get("pdf")
        session = make_session_with_waypoints()
        out = tmp_path / "report.pdf"
        result = exp.export(session, str(out))
        assert result.ok is True
        assert result.output_path == str(out)
        assert out.exists()
        assert out.stat().st_size > 0
        assert session.output.last_pdf_path == str(out)

    def test_export_pdf_failure_without_reportlab(self, tmp_path):
        """无 reportlab 时 export 返回失败（验证错误处理路径）。"""
        if _REPORTLAB_AVAILABLE:
            pytest.skip("reportlab 已安装，跳过失败路径测试")
        exp = ExporterRegistry.get("pdf")
        session = make_session_with_waypoints()
        out = tmp_path / "report.pdf"
        result = exp.export(session, str(out))
        assert result.ok is False
        assert "reportlab" in result.error or "PDF" in result.error

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_with_all_report_fields(self, tmp_path):
        """reportlab 可用时填充全部 report 字段导出 PDF（覆盖所有 set_* 分支）。"""
        exp = ExporterRegistry.get("pdf")
        session = make_session_full()  # 含 scan_info/parameters/results/layers/statistics/quality
        out = tmp_path / "report_full.pdf"
        result = exp.export(session, str(out))
        assert result.ok is True
        assert out.exists()
        assert out.stat().st_size > 0
        # 确认输出路径写入 session
        assert session.output.last_pdf_path == str(out)

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_exception(self, tmp_path):
        """PDF 导出路径目录不存在时触发异常（except 分支）。"""
        exp = ExporterRegistry.get("pdf")
        session = make_session_with_waypoints()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.pdf")
        result = exp.export(session, bad_path)
        assert result.ok is False
        assert result.error != ""

    @pytest.mark.skipif(not _REPORTLAB_AVAILABLE, reason="reportlab 未安装")
    def test_export_pdf_minimal_report(self, tmp_path):
        """PDF 导出时 report 字段部分为空（覆盖 if False 分支）且无点云（跳过图表）。"""
        exp = ExporterRegistry.get("pdf")
        session = make_session_with_waypoints()
        # 清空 report 部分 字段（保留 scan_info 触发 set_scan_info，其余为空）
        session.report.parameters = {}
        session.report.results = {}
        session.report.layers = []
        session.report.statistics = {}
        session.report.quality = {}
        # 清空点云（使 xyz is None → 跳过 add_comparison_figure 分支）
        session.point_cloud.xyz = None
        out = tmp_path / "report_minimal.pdf"
        result = exp.export(session, str(out))
        assert result.ok is True
        assert out.exists()


# ============================================================
# 12. RobotTrajectoryExporter 导出
# ============================================================
@pytest.mark.unit
@pytest.mark.export
class TestRobotTrajectoryExporter:
    """RobotTrajectoryExporter 测试。"""

    def test_default_path(self):
        """Robot 未重写 default_path → 用基类逻辑（repair.krl）。"""
        exp = ExporterRegistry.get("robot")
        assert exp.default_path(RepairSession(), None) == "repair.krl"

    def test_run_not_ready(self):
        """run 数据不完整返回失败。"""
        exp = ExporterRegistry.get("robot")
        result = exp.run(None, RepairSession(), None)
        assert result.ok is False
        assert "航点为空" in result.error

    def test_export_kuka(self, tmp_path):
        """导出 KUKA KRL 文件。"""
        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        out = tmp_path / "repair.krl"
        result = exp.export(session, str(out), robot_type="kuka")
        assert result.ok is True
        assert result.output_path == str(out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "DEF" in content
        assert "csam_repair" in content
        assert "END" in content

    def test_export_abb(self, tmp_path):
        """导出 ABB Rapid 文件。"""
        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        out = tmp_path / "repair.mod"
        result = exp.export(session, str(out), robot_type="abb")
        assert result.ok is True
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "MODULE" in content
        assert "MoveL" in content

    def test_export_with_normals(self, tmp_path):
        """提供法向量时导出成功（姿态计算分支）。"""
        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        # 设置法向量
        session.point_cloud.normals = np.array(
            [[0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32,
        )
        out = tmp_path / "repair_with_normals.krl"
        result = exp.export(session, str(out), robot_type="kuka")
        assert result.ok is True
        assert out.exists()

    def test_run_with_dialog_success(self, qapp, monkeypatch, tmp_path):
        """run 通过 RobotExportDialog 成功导出（dlg.exec() 返回 True）。"""
        # 构造模拟对话框
        fake_path = str(tmp_path / "dialog_out.krl")
        # 先创建文件（模拟对话框内部已写入）
        Path(fake_path).write_text("DEF x() END", encoding="utf-8")

        class _FakeDialog:
            def __init__(self, parent=None, waypoints=None):
                self._parent = parent
                self._waypoints = waypoints

            def exec(self):
                return True

            @property
            def result_path(self):
                return fake_path

        # patch 模块内的 RobotExportDialog
        import repair_app.ui.dialogs as _dialogs_mod
        monkeypatch.setattr(_dialogs_mod, "RobotExportDialog", _FakeDialog)

        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        result = exp.run(None, session, None)
        assert result.ok is True
        assert result.output_path == fake_path
        assert session.output.last_robot_path == fake_path

    def test_run_with_dialog_cancelled(self, qapp, monkeypatch):
        """run 中用户取消对话框（dlg.exec() 返回 False）。"""
        class _FakeDialog:
            def __init__(self, parent=None, waypoints=None):
                pass

            def exec(self):
                return False

            @property
            def result_path(self):
                return ""

        import repair_app.ui.dialogs as _dialogs_mod
        monkeypatch.setattr(_dialogs_mod, "RobotExportDialog", _FakeDialog)

        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        result = exp.run(None, session, None)
        assert result.ok is False
        assert "取消" in result.error

    def test_run_with_dialog_exception(self, qapp, monkeypatch):
        """run 中 RobotExportDialog 抛异常时被捕获（except 分支）。"""
        class _FakeDialog:
            def __init__(self, parent=None, waypoints=None):
                raise RuntimeError("对话框初始化失败")

        import repair_app.ui.dialogs as _dialogs_mod
        monkeypatch.setattr(_dialogs_mod, "RobotExportDialog", _FakeDialog)

        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        result = exp.run(None, session, None)
        assert result.ok is False
        assert "对话框初始化失败" in result.error

    def test_export_exception(self, tmp_path):
        """export 输出路径目录不存在时触发异常（except 分支）。"""
        exp = ExporterRegistry.get("robot")
        session = make_session_with_waypoints()
        bad_path = str(tmp_path / "nonexistent_dir" / "bad.krl")
        result = exp.export(session, bad_path, robot_type="kuka")
        assert result.ok is False
        assert result.error != ""


# ============================================================
# 13. 注册顺序与 sort_order 排序
# ============================================================
@pytest.mark.unit
class TestSortOrder:
    """注册顺序与 sort_order 排序测试。"""

    def test_builtins_sorted_by_sort_order(self):
        """list 返回的内置导出器按 sort_order 升序排列。"""
        exporters = ExporterRegistry.list()
        orders = [e.sort_order for e in exporters]
        assert orders == sorted(orders)
        # 内置 6 个相对顺序：gcode < robot < pdf < csv < json < project
        names = [e.name for e in exporters]
        builtin_names = [n for n in names if n in ("gcode", "robot", "pdf", "csv", "json", "project")]
        assert builtin_names == ["gcode", "robot", "pdf", "csv", "json", "project"]

    def test_sort_order_takes_precedence_over_registration(self, restore_registry):
        """sort_order 优先于注册顺序（后注册但 sort_order 小的排前面）。"""
        class _HighOrder(BaseExporter):
            name = "high_order_test"
            sort_order = 5

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        class _LowOrder(BaseExporter):
            name = "low_order_test"
            sort_order = 1

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        ExporterRegistry.register(_HighOrder())  # sort_order=5 先注册
        ExporterRegistry.register(_LowOrder())   # sort_order=1 后注册
        names = [e.name for e in ExporterRegistry.list()]
        assert names.index("low_order_test") < names.index("high_order_test")

    def test_same_sort_order_keeps_registration_order(self, restore_registry):
        """相同 sort_order 时保持注册顺序（Python sort 稳定）。"""
        class _First(BaseExporter):
            name = "same_order_first"
            sort_order = 200

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        class _Second(BaseExporter):
            name = "same_order_second"
            sort_order = 200

            def export(self, s, p, **c):
                return ExportResult(ok=True)

        ExporterRegistry.register(_First())
        ExporterRegistry.register(_Second())
        names = [e.name for e in ExporterRegistry.list()]
        assert names.index("same_order_first") < names.index("same_order_second")

    def test_list_order_matches_sort(self, restore_registry):
        """list 结果与按 sort_order 排序一致。"""
        exporters = ExporterRegistry.list()
        sorted_by_order = sorted(exporters, key=lambda e: e.sort_order)
        assert [e.name for e in exporters] == [e.name for e in sorted_by_order]
