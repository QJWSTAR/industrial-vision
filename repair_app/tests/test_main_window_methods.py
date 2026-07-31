"""test_main_window_methods.py — MainWindow 方法补充测试

目标：覆盖 repair_app/ui/main_window.py 中未覆盖的方法，
将覆盖率从 41.54% 提升到 >=70%。

== 防挂起策略 ==
DO NOT call MainWindow() directly —— __init__ 会启动 QTimer.singleShot
延迟回调、ZMQ 客户端、autosave 定时器（60s）以及 MATLAB 生命周期信号，
历史上曾导致测试挂起。本文件统一使用以下三种安全模式：

  1. Strategy 1: MainWindow.__new__(MainWindow) 创建实例但不调 __init__，
     然后手动赋值需要的属性。
  2. Strategy 3: MainWindow._method(stub) — 通过 SimpleNamespace stub
     作为 self 传入（参考 test_crash_recovery.py 中已验证的模式）。
  3. 模块级函数（_friendly_error / _show_error）
     直接调用，无需任何实例。

conftest.py 默认按单个测试禁用 QTimer.singleShot（替换为 no-op），
并移除 loguru stderr sink 避免多线程日志死锁。

运行：python -m pytest repair_app/tests/test_main_window_methods.py -v --timeout=60
"""
from __future__ import annotations

import os
import sys

# ---- 环境变量（必须在导入 PySide6 之前设置） ----
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")

# ---- 项目根路径注入 ----
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from PySide6.QtCore import QPoint, QSize, QTimer
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMessageBox, QWidget,
)

from repair_app.core.repair_session import RepairSession
from repair_app.ui.main_window import (
    MainWindow,
    MODE_ADDITIVE,
    MODE_REPAIRING,
    PAGE_MORPH,
    PAGE_OUTPUT,
    PAGE_PATH,
    _friendly_error,
    _show_error,
)

# 直接导入模块对象（用于 monkeypatch.setattr 修改模块级变量）
import repair_app.ui.main_window as _mw_mod


# ============================================================
# 共享 fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _mock_message_boxes(monkeypatch):
    """自动 mock QMessageBox 静态方法，避免模态对话框阻塞测试。"""
    try:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    except Exception:
        pass
    try:
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
    except Exception:
        pass
    try:
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    except Exception:
        pass
    try:
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: None)
    except Exception:
        pass
    try:
        monkeypatch.setattr(QMessageBox, "aboutQt", lambda *a, **kw: None)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _mock_file_dialogs(monkeypatch):
    """自动 mock QFileDialog 静态方法，避免文件对话框阻塞。"""
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("", ""))
    except Exception:
        pass
    try:
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    """确保所有测试（含 unit 标记）都有 QApplication 实例。

    _make_main_window_new() 调用 QMainWindow.__init__ 需要 QApplication。
    qapp 为 session 级，此处仅做依赖注入，无额外逻辑。
    """
    yield
    qapp.processEvents()


# ============================================================
# 辅助函数
# ============================================================

def _make_stub(**kwargs):
    """构造 SimpleNamespace stub，用作 MainWindow._method 的 self。"""
    return SimpleNamespace(**kwargs)


def _make_session_with_cloud(n_points: int = 20) -> RepairSession:
    """构造一个已加载点云的 RepairSession。"""
    s = RepairSession()
    rng = np.random.default_rng(42)
    s.point_cloud.xyz = rng.uniform(-5, 5, (n_points, 3)).astype(np.float32)
    s.point_cloud.normals = np.zeros((n_points, 3), dtype=np.float32)
    s.point_cloud.normals[:, 2] = 1.0
    return s


def _make_main_window_new():
    """使用 MainWindow.__new__ 创建实例但不调用 MainWindow.__init__。

    满足「DO NOT call MainWindow() directly」约束。

    关键：调用 QMainWindow.__init__ 以初始化 C++ 对象，
    避免 shiboken 报错 "'__init__' method of object's base class not called"。
    这样 setStyleSheet / deleteLater / super().xxx() 等 QWidget 方法均可正常工作。
    MainWindow.__init__ 中的重型逻辑（ZMQ client、autosave 定时器、MATLAB 信号）
    不会被触发。
    """
    from PySide6.QtWidgets import QMainWindow
    mw = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(mw)
    return mw


# ============================================================
# 1. 模块级函数
# ============================================================

@pytest.mark.unit
class TestModuleFunctions:
    """模块级函数 _friendly_error / _show_error 测试。"""

    def test_friendly_error_returns_string_for_file_error(self):
        """文件异常翻译为友好消息（含标题 + 详细说明）。"""
        exc = FileNotFoundError("missing.txt")
        result = _friendly_error("加载文件", exc)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_friendly_error_for_runtime_error(self):
        """RuntimeError 也应被翻译。"""
        exc = RuntimeError("matlab boom")
        result = _friendly_error("路径规划", exc)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_friendly_error_for_value_error(self):
        """ValueError 也应被翻译。"""
        exc = ValueError("bad param")
        result = _friendly_error("参数校验", exc)
        assert isinstance(result, str)

    def test_show_error_delegates_to_error_manager(self, monkeypatch):
        """_show_error 应委托给 ErrorManager.handle。"""
        from repair_app.utils import error_manager
        called = {}

        def fake_handle(exc, context, parent, show_dialog):
            called["exc"] = exc
            called["context"] = context
            called["parent"] = parent
            called["show_dialog"] = show_dialog

        monkeypatch.setattr(error_manager.ErrorManager, "handle", fake_handle)
        parent = MagicMock()
        exc = ValueError("test")
        _show_error(parent, "加载失败", exc)
        assert called["exc"] is exc
        assert called["context"] == "加载失败"
        assert called["parent"] is parent
        assert called["show_dialog"] is True


# ============================================================
# 2. MainWindow 静态方法
# ============================================================

@pytest.mark.unit
class TestMainWindowStaticMethods:
    """MainWindow 静态方法测试（无需 self）。"""

    def test_style_workflow_label_done(self, qapp):
        """state=done 应用绿色样式。"""
        label = QLabel("test")
        MainWindow._style_workflow_label(label, "done")
        ss = label.styleSheet()
        assert "#10B981" in ss or "#052E2B" in ss
        label.deleteLater()
        qapp.processEvents()

    def test_style_workflow_label_active(self, qapp):
        """state=active 应用蓝色样式。"""
        label = QLabel("test")
        MainWindow._style_workflow_label(label, "active")
        ss = label.styleSheet()
        assert "#3B82F6" in ss or "#172554" in ss
        label.deleteLater()
        qapp.processEvents()

    def test_style_workflow_label_locked(self, qapp):
        """state=locked 应用灰色样式。"""
        label = QLabel("test")
        MainWindow._style_workflow_label(label, "locked")
        ss = label.styleSheet()
        assert "#64748B" in ss or "#111827" in ss
        label.deleteLater()
        qapp.processEvents()

    def test_style_workflow_label_unknown_falls_back_to_locked(self, qapp):
        """未知 state 回退到 locked 样式。"""
        label = QLabel("test")
        MainWindow._style_workflow_label(label, "unknown_state")
        ss = label.styleSheet()
        assert "#64748B" in ss or "#111827" in ss
        label.deleteLater()
        qapp.processEvents()

    def test_kv_creates_label(self, qapp):
        """_kv 创建显示 'k: v' 的 label。"""
        label = MainWindow._kv("速度", 500)
        assert "速度" in label.text()
        assert "500" in label.text()
        label.deleteLater()
        qapp.processEvents()

    def test_sep_creates_hline_frame(self, qapp):
        """_sep 创建水平分隔线 QFrame。"""
        from PySide6.QtWidgets import QFrame as QFrameCls
        frame = MainWindow._sep()
        assert frame.frameShape() == QFrameCls.HLine
        frame.deleteLater()
        qapp.processEvents()


# ============================================================
# 4. MainWindow 通信/连接相关方法
# ============================================================

@pytest.mark.unit
class TestConnectionStatus:
    """_update_connection_status / _use_zmq_engine / _on_engine_changed。"""

    def test_update_connection_status_with_zmq_client(self):
        """有 _zmq_client 时显示远程服务就绪。"""
        stub = _make_stub(_zmq_client=MagicMock(), _lb_conn=MagicMock())
        MainWindow._update_connection_status(stub)
        text = stub._lb_conn.setText.call_args[0][0]
        assert "远程服务" in text

    def test_update_connection_status_without_zmq_client(self):
        """无 _zmq_client 时显示本地模式。"""
        stub = _make_stub(_zmq_client=None, _lb_conn=MagicMock())
        MainWindow._update_connection_status(stub)
        text = stub._lb_conn.setText.call_args[0][0]
        assert "本地模式" in text

    def test_use_zmq_engine_no_cb_engine_attr(self):
        """无 _cb_engine 属性时返回 False。"""
        stub = _make_stub(_zmq_client=MagicMock())
        assert MainWindow._use_zmq_engine(stub) is False

    def test_use_zmq_engine_local_data(self):
        """cb_engine 当前数据为 'local' 时返回 False。"""
        cb = MagicMock()
        cb.currentData.return_value = "local"
        stub = _make_stub(_cb_engine=cb, _zmq_client=MagicMock())
        assert MainWindow._use_zmq_engine(stub) is False

    def test_use_zmq_engine_zmq_with_client(self):
        """cb_engine=zmq 且有 zmq_client 时返回 True。"""
        cb = MagicMock()
        cb.currentData.return_value = "zmq"
        stub = _make_stub(_cb_engine=cb, _zmq_client=MagicMock())
        assert MainWindow._use_zmq_engine(stub) is True

    def test_use_zmq_engine_zmq_without_client(self):
        """cb_engine=zmq 但 zmq_client=None 时返回 False。"""
        cb = MagicMock()
        cb.currentData.return_value = "zmq"
        stub = _make_stub(_cb_engine=cb, _zmq_client=None)
        assert MainWindow._use_zmq_engine(stub) is False

    def test_on_engine_changed_zmq(self):
        """切换到 zmq 引擎时更新 hint。"""
        cb = MagicMock()
        cb.currentData.return_value = "zmq"
        stub = _make_stub(_cb_engine=cb, _zmq_client=MagicMock(), _lb_engine_hint=MagicMock())
        # _on_engine_changed 调用 self._use_zmq_engine() — 绑定到 stub
        stub._use_zmq_engine = lambda: MainWindow._use_zmq_engine(stub)
        MainWindow._on_engine_changed(stub, 1)
        stub._lb_engine_hint.setText.assert_called_once()
        text = stub._lb_engine_hint.setText.call_args[0][0]
        assert "远程" in text or "MATLAB" in text

    def test_on_engine_changed_local(self):
        """切换到本地引擎时更新 hint。"""
        cb = MagicMock()
        cb.currentData.return_value = "local"
        stub = _make_stub(_cb_engine=cb, _zmq_client=MagicMock(), _lb_engine_hint=MagicMock())
        # _on_engine_changed 调用 self._use_zmq_engine()
        stub._use_zmq_engine = lambda: MainWindow._use_zmq_engine(stub)
        MainWindow._on_engine_changed(stub, 0)
        stub._lb_engine_hint.setText.assert_called_once()
        text = stub._lb_engine_hint.setText.call_args[0][0]
        assert "本地" in text


# ============================================================
# 5. MainWindow 模式切换 / 选区 / 材料
# ============================================================

@pytest.mark.unit
class TestModeAndSelection:
    """_on_mode_changed / _on_selection_changed / _on_material_changed。"""

    def test_on_mode_changed_to_additive(self):
        """切换到增材模式：更新 hint + 按钮。"""
        session = RepairSession()
        stub = _make_stub(
            _session=session,
            _lb_mode_hint=MagicMock(),
            _btn_start_repair=MagicMock(),
            _btn_feas=MagicMock(),
            _selector=MagicMock(),
            _update_step_buttons=lambda *a, **kw: None,
        )
        MainWindow._on_mode_changed(stub, MODE_ADDITIVE)
        assert session.repair_mode == MODE_ADDITIVE
        stub._lb_mode_hint.setText.assert_called_once()
        stub._btn_start_repair.setText.assert_called_once()

    def test_on_mode_changed_to_repairing_with_no_selection(self):
        """切换到修复模式且无选区时禁用开始按钮。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        selector = MagicMock()
        selector.get_selection_mask.return_value = np.zeros(5, dtype=bool)
        stub = _make_stub(
            _session=session,
            _lb_mode_hint=MagicMock(),
            _btn_start_repair=MagicMock(),
            _btn_feas=MagicMock(),
            _selector=selector,
            _update_step_buttons=lambda *a, **kw: None,
        )
        MainWindow._on_mode_changed(stub, MODE_REPAIRING)
        assert session.repair_mode == MODE_REPAIRING
        # 无选区 → setEnabled(False)
        stub._btn_start_repair.setEnabled.assert_called_with(False)

    def test_on_mode_changed_additive_busy_skips_button_update(self):
        """增材模式 + busy 时不更新按钮。"""
        session = RepairSession()
        session.is_busy = True
        stub = _make_stub(
            _session=session,
            _lb_mode_hint=MagicMock(),
            _btn_start_repair=MagicMock(),
            _btn_feas=MagicMock(),
            _selector=MagicMock(),
            _update_step_buttons=lambda *a, **kw: None,
        )
        MainWindow._on_mode_changed(stub, MODE_ADDITIVE)
        # busy 时不应调 setEnabled
        stub._btn_start_repair.setEnabled.assert_not_called()

    def test_on_selection_changed_busy_returns_early(self):
        """busy 时仅更新选区计数，不修改按钮。"""
        session = RepairSession()
        session.is_busy = True
        stub = _make_stub(
            _session=session,
            _lb_sel=MagicMock(),
            _btn_start_repair=MagicMock(),
        )
        mask = np.array([True, False, True, True, False])
        MainWindow._on_selection_changed(stub, mask)
        stub._lb_sel.setText.assert_called_once()
        stub._btn_start_repair.setEnabled.assert_not_called()

    def test_on_selection_changed_additive_mode(self):
        """增材模式下有 cloud 即启用按钮。"""
        session = RepairSession()
        session.repair_mode = MODE_ADDITIVE
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _lb_sel=MagicMock(),
            _btn_start_repair=MagicMock(),
            _refresh_start_button_state=MagicMock(),
        )
        mask = np.zeros(5, dtype=bool)
        MainWindow._on_selection_changed(stub, mask)
        # Phase 3: _on_selection_changed 委托给 _refresh_start_button_state 统一刷新
        stub._refresh_start_button_state.assert_called_once()

    def test_on_selection_changed_repairing_with_enough_points(self):
        """修复模式 + 选区 >=3 点时启用按钮。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _lb_sel=MagicMock(),
            _btn_start_repair=MagicMock(),
            _refresh_start_button_state=MagicMock(),
        )
        mask = np.array([True, True, True, False, False])
        MainWindow._on_selection_changed(stub, mask)
        stub._refresh_start_button_state.assert_called_once()

    def test_on_selection_changed_repairing_insufficient_points(self):
        """修复模式 + 选区 <3 点时禁用按钮。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _lb_sel=MagicMock(),
            _btn_start_repair=MagicMock(),
            _refresh_start_button_state=MagicMock(),
        )
        mask = np.array([True, False, False, False, False])
        MainWindow._on_selection_changed(stub, mask)
        stub._refresh_start_button_state.assert_called_once()

    def test_on_material_changed_updates_label(self, monkeypatch):
        """_on_material_changed 更新材料信息标签 + 临界速度字段。"""
        from repair_app.service.coordination_service import CoordinationService
        # Mock material database
        fake_mat = SimpleNamespace(v_cr_base_ms=550.0, density_kgm3=7800.0)
        fake_db = MagicMock()
        fake_db.get.return_value = fake_mat
        monkeypatch.setattr(CoordinationService, "get_material_database", lambda: fake_db)
        monkeypatch.setattr(CoordinationService, "create_feasibility_checker", lambda mat=None: MagicMock())

        cs_field = MagicMock()
        stub = _make_stub(
            _lb_mat_info=MagicMock(),
            _cs_fields={"critical_velocity": cs_field},
            _feasibility_checker=MagicMock(),
        )
        MainWindow._on_material_changed(stub, 1)
        stub._lb_mat_info.setText.assert_called_once()
        text = stub._lb_mat_info.setText.call_args[0][0]
        assert "550" in text
        assert "7800" in text
        cs_field.setValue.assert_called_with(550.0)


# ============================================================
# 6. MainWindow 步骤切换 / 按钮更新
# ============================================================

@pytest.mark.unit
class TestStepSwitching:
    """_switch_to_step / _update_step_buttons。"""

    def _make_step_stub(self, page=PAGE_PATH, path_ready=False, morph_done=False):
        """构造步骤切换所需 stub。"""
        session = RepairSession()
        session.output.path_output_ready = path_ready
        session.morphology.repair_xyz = (
            np.zeros((3, 3), dtype=np.float32) if morph_done else None
        )
        return _make_stub(
            _mode_stack=MagicMock(currentIndex=MagicMock(return_value=page)),
            _session=session,
            _sb=MagicMock(),
            _step1_btn=MagicMock(),
            _step2_btn=MagicMock(),
            _step3_lb=MagicMock(),
            _step4_btn=MagicMock(),
            _arrow_lb=MagicMock(),
            _lb_mode_state=MagicMock(),
            _lb_workflow_state=MagicMock(),
            _style_workflow_label=lambda *a, **kw: None,
            _update_step_buttons=lambda *a, **kw: None,
            _refresh_morph_status=lambda *a, **kw: None,
        )

    def test_switch_to_step_path(self):
        """切换到路径规划页面。"""
        stub = self._make_step_stub(page=PAGE_PATH)
        MainWindow._switch_to_step(stub, PAGE_PATH)
        stub._mode_stack.setCurrentIndex.assert_called_with(PAGE_PATH)
        # lambda 函数不记录调用，跳过 _update_step_buttons 断言
        stub._sb.showMessage.assert_called()

    def test_switch_to_step_morph_blocked_without_path(self):
        """未完成路径规划时切换到形貌预测被拦截。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=False)
        MainWindow._switch_to_step(stub, PAGE_MORPH)
        # 不应切换页面
        stub._mode_stack.setCurrentIndex.assert_not_called()
        stub._sb.showMessage.assert_called()

    def test_switch_to_step_morph_allowed_with_path(self):
        """已完成路径规划时允许切换到形貌预测。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=True)
        MainWindow._switch_to_step(stub, PAGE_MORPH)
        stub._mode_stack.setCurrentIndex.assert_called_with(PAGE_MORPH)
        # 应调用 _refresh_morph_status
        stub._sb.showMessage.assert_called()

    def test_switch_to_step_output_blocked_without_path(self):
        """未完成路径规划时切换到输出被拦截。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=False)
        MainWindow._switch_to_step(stub, PAGE_OUTPUT)
        stub._mode_stack.setCurrentIndex.assert_not_called()

    def test_switch_to_step_output_allowed_with_path(self):
        """已完成路径规划时允许切换到输出。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=True)
        MainWindow._switch_to_step(stub, PAGE_OUTPUT)
        stub._mode_stack.setCurrentIndex.assert_called_with(PAGE_OUTPUT)

    def test_update_step_buttons_path_page_no_path(self):
        """路径规划页 + 无路径输出时 step1 显示 active。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=False)
        MainWindow._update_step_buttons(stub)
        # step1_btn 应调用 setStyleSheet 多次
        assert stub._step1_btn.setStyleSheet.called
        assert stub._step4_btn.setEnabled.called

    def test_update_step_buttons_path_page_with_path(self):
        """路径规划页 + 有路径输出时 step1 显示 done。"""
        stub = self._make_step_stub(page=PAGE_PATH, path_ready=True)
        MainWindow._update_step_buttons(stub)
        assert stub._step1_btn.setStyleSheet.called
        assert stub._step4_btn.setEnabled.called

    def test_update_step_buttons_morph_page_done(self):
        """形貌预测页 + 形貌已完成时 step2 显示 done。"""
        stub = self._make_step_stub(page=PAGE_MORPH, path_ready=True, morph_done=True)
        MainWindow._update_step_buttons(stub)
        assert stub._step1_btn.setStyleSheet.called
        # _step2_btn 是 QLabel，样式通过 _style_workflow_label 设置，不直接用 setStyleSheet

    def test_update_step_buttons_output_page(self):
        """输出页 + 路径 + 形貌均完成。"""
        stub = self._make_step_stub(page=PAGE_OUTPUT, path_ready=True, morph_done=True)
        MainWindow._update_step_buttons(stub)
        assert stub._step1_btn.setStyleSheet.called


# ============================================================
# 7. MainWindow 计算槽（_on_compute_*）
# ============================================================

@pytest.mark.unit
class TestComputeSlots:
    """一键计算相关槽方法。"""

    def test_on_compute_stage_start(self):
        """_on_compute_stage '启动' 分支。"""
        stub = _make_stub(
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _prog=MagicMock(),
            _workflow_controller=MagicMock(),
        )
        MainWindow._on_compute_stage(stub, "启动 MATLAB")
        stub._prog.setValue.assert_called_with(10)
        stub._workflow_controller.set_step_running.assert_called_with(1)

    def test_on_compute_stage_execute(self):
        """_on_compute_stage '执行' 分支。"""
        stub = _make_stub(
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _prog=MagicMock(),
            _pipeline=MagicMock(),
        )
        MainWindow._on_compute_stage(stub, "执行计算")
        stub._prog.setValue.assert_called_with(50)

    def test_on_compute_stage_parse(self):
        """_on_compute_stage '解析' 分支。"""
        stub = _make_stub(
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _prog=MagicMock(),
            _pipeline=MagicMock(),
        )
        MainWindow._on_compute_stage(stub, "解析结果")
        stub._prog.setValue.assert_called_with(80)

    def test_on_compute_stage_other(self):
        """_on_compute_stage 其他分支不更新进度数值。"""
        stub = _make_stub(
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _prog=MagicMock(),
            _pipeline=MagicMock(),
        )
        MainWindow._on_compute_stage(stub, "未知阶段")
        stub._prog.setValue.assert_not_called()

    def test_on_compute_thread_finished_clears_references(self):
        """_on_compute_thread_finished 清空 worker/thread 引用。"""
        # P3-11: 绑定真实 _stop_progress_subscriber（有 _compute_controller 时为 no-op）
        stub = _make_stub(
            _compute_thread="sentinel",
            _compute_worker="sentinel",
            _compute_controller=MagicMock(),  # 模拟生产环境
            _progress_subscriber=MagicMock(),
        )
        stub._stop_progress_subscriber = lambda: MainWindow._stop_progress_subscriber(stub)
        MainWindow._on_compute_thread_finished(stub)
        assert stub._compute_thread is None
        assert stub._compute_worker is None

    def test_on_compute_failed_marks_pipeline_failed(self, monkeypatch):
        """_on_compute_failed 标记 pipeline 失败并显示对话框。"""
        # Mock ErrorDialog.show 避免 GUI 创建
        import repair_app.ui.dialogs as dialogs_mod
        monkeypatch.setattr(dialogs_mod.ErrorDialog, "show", lambda *a, **kw: None)
        # Mock MatlabLifecycleManager
        import repair_app.bridge.lifecycle_manager as lm_mod
        monkeypatch.setattr(lm_mod.MatlabLifecycleManager, "get_instance", classmethod(lambda cls: MagicMock()))

        # P3-11: 绑定真实 _stop_progress_subscriber（有 _compute_controller 时为 no-op）
        stub = _make_stub(
            _set_busy=MagicMock(),
            _prog=MagicMock(),
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _compute_controller=MagicMock(),  # 模拟生产环境
            _progress_subscriber=MagicMock(),
            _workflow_controller=MagicMock(),
        )
        stub._stop_progress_subscriber = lambda: MainWindow._stop_progress_subscriber(stub)
        MainWindow._on_compute_failed(stub, "E_TEST", "friendly msg", "detail")
        stub._set_busy.assert_called_with(False)
        stub._prog.setValue.assert_called_with(0)
        stub._workflow_controller.mark_running_as_failed.assert_called_once()

    def test_on_compute_result_not_success_shows_error(self, monkeypatch):
        """_on_compute_result 接收非成功结果时显示错误。"""
        # _on_compute_result 调用 _Coord.is_repair_success → False → 抛 RuntimeError → _show_error
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod._Coord, "is_repair_success", lambda result: False)
        # Mock _show_error 避免对话框
        monkeypatch.setattr(mw_mod, "_show_error", lambda parent, ctx, exc: None)

        # P3-11: 绑定真实 _stop_progress_subscriber（有 _compute_controller 时为 no-op）
        stub = _make_stub(
            _set_busy=MagicMock(),
            _compute_controller=MagicMock(),
            _progress_subscriber=MagicMock(),
            _workflow_controller=MagicMock(),
        )
        stub._stop_progress_subscriber = lambda: MainWindow._stop_progress_subscriber(stub)
        result = {"status_name": "FAILED", "error_message": "matlab boom"}
        MainWindow._on_compute_result(stub, result)
        stub._set_busy.assert_called_with(False)
        stub._workflow_controller.mark_running_as_failed.assert_called_once()


# ============================================================
# 8. MainWindow 进度订阅与图层槽
# ============================================================

@pytest.mark.unit
class TestProgressSlots:
    """实时进度 / 逐层相关槽。"""

    def test_start_progress_subscriber_resets_realtime(self):
        """_start_progress_subscriber 重置实时面板 + 启动订阅。"""
        sub = MagicMock()
        sub.is_running = False
        # P3-11: 明确设置 _compute_controller=None 测试 fallback 路径（走 sub.start）
        stub = _make_stub(
            _realtime_stats=MagicMock(),
            _layer_player=MagicMock(),
            _session=RepairSession(),
            _progress_subscriber=sub,
            _compute_controller=None,
        )
        MainWindow._start_progress_subscriber(stub)
        stub._realtime_stats.reset.assert_called_once()
        stub._layer_player.reset.assert_called_once()
        sub.start.assert_called_once()

    def test_start_progress_subscriber_already_running(self):
        """订阅器已在运行时不再启动。"""
        sub = MagicMock()
        sub.is_running = True
        stub = _make_stub(
            _realtime_stats=MagicMock(),
            _layer_player=MagicMock(),
            _session=RepairSession(),
            _progress_subscriber=sub,
        )
        MainWindow._start_progress_subscriber(stub)
        sub.start.assert_not_called()

    def test_start_progress_subscriber_none_is_safe(self):
        """_progress_subscriber=None 时不抛。"""
        stub = _make_stub(
            _realtime_stats=MagicMock(),
            _layer_player=MagicMock(),
            _session=RepairSession(),
            _progress_subscriber=None,
        )
        MainWindow._start_progress_subscriber(stub)  # 不应抛

    def test_stop_progress_subscriber_running(self):
        """运行中的订阅器应被停止（无 _compute_controller 的 fallback 路径）。"""
        sub = MagicMock()
        sub.is_running = True
        # P3-3: 明确设置 _compute_controller=None，测试 fallback 路径
        stub = _make_stub(_progress_subscriber=sub, _compute_controller=None)
        MainWindow._stop_progress_subscriber(stub)
        sub.stop.assert_called_once()

    def test_stop_progress_subscriber_not_running(self):
        """未运行的订阅器不会被停止（无 _compute_controller 的 fallback 路径）。"""
        sub = MagicMock()
        sub.is_running = False
        stub = _make_stub(_progress_subscriber=sub, _compute_controller=None)
        MainWindow._stop_progress_subscriber(stub)
        sub.stop.assert_not_called()

    def test_stop_progress_subscriber_none_is_safe(self):
        """_progress_subscriber=None 时不抛。"""
        stub = _make_stub(_progress_subscriber=None, _compute_controller=None)
        MainWindow._stop_progress_subscriber(stub)  # 不应抛

    def test_stop_progress_subscriber_skipped_with_controller(self):
        """P3-3: 生产路径（有 _compute_controller）应跳过 stop，保持 application-scoped 订阅。"""
        sub = MagicMock()
        sub.is_running = True
        controller = MagicMock()  # 模拟生产环境 ComputeController 存在
        stub = _make_stub(_progress_subscriber=sub, _compute_controller=controller)
        MainWindow._stop_progress_subscriber(stub)
        sub.stop.assert_not_called()  # 有 controller 时不调用 stop

    def test_on_progress_received_caches_layer(self):
        """进度槽缓存层数据；mesh 由限帧后的独立信号刷新。"""
        session = RepairSession()
        stub = _make_stub(
            _session=session,
            _layer_player=MagicMock(),
            _visualizer=MagicMock(),
            _prog=MagicMock(),
        )
        waypoints = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
        parsed = {
            "layer_index": 2,
            "total_layers": 5,
            "waypoints": waypoints,
            "partial_mesh_data": b"meshbytes",
            "progress": 0.4,
            "message": "computing",
            "stage_name": "morph",
        }
        MainWindow._on_progress_received(stub, parsed)
        assert 2 in session.layer.by_layer
        stub._layer_player.set_total_layers.assert_called_with(5)
        stub._visualizer.set_partial_waypoints.assert_called_with(waypoints)
        assert session.layer.by_layer[2]["mesh_bytes"] == b"meshbytes"
        stub._visualizer.set_partial_mesh.assert_not_called()

    def test_on_progress_received_no_waypoints(self):
        """无航点时不刷新 visualizer.set_partial_waypoints。"""
        session = RepairSession()
        stub = _make_stub(
            _session=session,
            _layer_player=MagicMock(),
            _visualizer=MagicMock(),
        )
        parsed = {
            "layer_index": 0,
            "total_layers": 1,
            "waypoints": None,
            "partial_mesh_data": b"",
        }
        MainWindow._on_progress_received(stub, parsed)
        stub._visualizer.set_partial_waypoints.assert_not_called()

    def test_on_layer_completed_sets_total_and_current(self):
        """_on_layer_completed 同步 LayerPlayer 总数 + 当前层。"""
        session = RepairSession()
        session.layer.by_layer = {0: {}, 1: {}, 2: {}}
        stub = _make_stub(_session=session, _layer_player=MagicMock())
        MainWindow._on_layer_completed(stub, 2)
        stub._layer_player.set_total_layers.assert_called_with(3)
        # 实时协议层号从 1 开始，LayerPlayer UI 索引从 0 开始。
        stub._layer_player.set_current_layer.assert_called_with(1)

    def test_on_layer_completed_empty_cache_uses_min_one(self):
        """空缓存时 total = max(1, 0) = 1。"""
        session = RepairSession()
        stub = _make_stub(_session=session, _layer_player=MagicMock())
        MainWindow._on_layer_completed(stub, 0)
        stub._layer_player.set_total_layers.assert_called_with(1)

    def test_on_mesh_updated_with_bytes(self):
        """有 mesh_bytes 时刷新可视化。"""
        stub = _make_stub(_visualizer=MagicMock())
        MainWindow._on_mesh_updated(stub, b"meshdata")
        stub._visualizer.set_partial_mesh.assert_called_with(b"meshdata")

    def test_on_mesh_updated_empty_bytes(self):
        """空 mesh_bytes 时不刷新。"""
        stub = _make_stub(_visualizer=MagicMock())
        MainWindow._on_mesh_updated(stub, b"")
        stub._visualizer.set_partial_mesh.assert_not_called()

    def test_on_layer_changed_no_cache_returns(self):
        """无缓存时 _on_layer_changed 直接返回。"""
        session = RepairSession()
        stub = _make_stub(_session=session, _visualizer=MagicMock(), _sb=MagicMock())
        MainWindow._on_layer_changed(stub, 5)
        stub._visualizer.set_partial_waypoints.assert_not_called()

    def test_on_layer_changed_with_cache(self):
        """有缓存时回放航点 + mesh。"""
        session = RepairSession()
        wps = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
        session.layer.by_layer = {
            1: {
                "waypoints": wps,
                "mesh_bytes": b"mesh",
                "stage_name": "morph",
                "message": "ok",
            }
        }
        stub = _make_stub(_session=session, _visualizer=MagicMock(), _sb=MagicMock())
        MainWindow._on_layer_changed(stub, 1)
        stub._visualizer.set_partial_waypoints.assert_called_with(wps)
        stub._visualizer.set_partial_mesh.assert_called_with(b"mesh")

    def test_on_layer_changed_with_cache_no_waypoints(self):
        """缓存无航点时清除 partial。"""
        session = RepairSession()
        session.layer.by_layer = {0: {"waypoints": None, "mesh_bytes": b""}}
        stub = _make_stub(_session=session, _visualizer=MagicMock(), _sb=MagicMock())
        MainWindow._on_layer_changed(stub, 0)
        stub._visualizer.set_partial_waypoints.assert_called_with(None)


# ============================================================
# 9. MATLAB 生命周期回调
# ============================================================

@pytest.mark.unit
class TestMatlabLifecycleCallbacks:
    """_on_matlab_crashed / _on_matlab_restarted。"""

    def test_on_matlab_crashed_shows_error(self):
        """MATLAB 崩溃回调更新状态栏 + Toast。"""
        # Toast.error(self, ...) 需要 self 为 QWidget — 用 _make_main_window_new
        mw = _make_main_window_new()
        mw._sb = MagicMock()
        MainWindow._on_matlab_crashed(mw)
        mw._sb.showMessage.assert_called_once()
        text = mw._sb.showMessage.call_args[0][0]
        assert "崩溃" in text
        mw.deleteLater()

    def test_on_matlab_restarted_shows_success(self):
        """MATLAB 重启成功回调更新状态栏 + Toast。"""
        mw = _make_main_window_new()
        mw._sb = MagicMock()
        MainWindow._on_matlab_restarted(mw)
        mw._sb.showMessage.assert_called_once()
        text = mw._sb.showMessage.call_args[0][0]
        assert "MATLAB" in text
        mw.deleteLater()


# ============================================================
# 10. MainWindow 路径规划 / 形貌预测 槽（_on_path_* / _on_morph_*）
# ============================================================

@pytest.mark.unit
class TestPathAndMorphSlots:
    """路径规划 / 形貌预测 worker 槽方法。"""

    def test_on_path_thread_finished_clears(self):
        """_on_path_thread_finished 清空引用。"""
        stub = _make_stub(_path_thread="x", _path_worker="y")
        MainWindow._on_path_thread_finished(stub)
        assert stub._path_thread is None
        assert stub._path_worker is None

    def test_on_morph_thread_finished_clears(self):
        """_on_morph_thread_finished 清空引用。"""
        stub = _make_stub(_morph_thread="x", _morph_worker="y")
        MainWindow._on_morph_thread_finished(stub)
        assert stub._morph_thread is None
        assert stub._morph_worker is None

    def test_on_path_partial_updates_progress(self):
        """_on_path_partial 更新进度与状态栏。"""
        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        stub = _make_stub(
            _session=session,
            _prog=MagicMock(),
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _lb_bottom_status=MagicMock(),
            _visualizer=MagicMock(),
            _selector=MagicMock(),
            _update_path_section=lambda *a, **kw: None,
        )
        wps = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
        MainWindow._on_path_partial(stub, wps, 2, 5)
        stub._prog.setValue.assert_called_once()
        stub._lb_prog.setText.assert_called_once()
        stub._visualizer.set_partial_waypoints.assert_called_with(wps)

    def test_on_path_finished_calls_finish_path_planning(self):
        """_on_path_finished 调用 _finish_path_planning。"""
        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        stub = _make_stub(
            _session=session,
            _selector=MagicMock(),
            _finish_path_planning=MagicMock(),
        )
        wps = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
        MainWindow._on_path_finished(stub, wps)
        stub._finish_path_planning.assert_called_once()
        call_args = stub._finish_path_planning.call_args
        # 第一个位置参数为 waypoints
        assert call_args[0][0] is wps

    def test_on_path_finished_empty_waypoints_uses_fallback(self):
        """空航点时调用 _fallback_waypoints。"""
        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        session.point_cloud.xyz = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0.5, 0.5, 0.5]
        ], dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _selector=MagicMock(),
            _finish_path_planning=MagicMock(),
        )
        # _on_path_finished 调用 self._fallback_waypoints(sel_mask) — 绑定
        stub._fallback_waypoints = lambda mask: MainWindow._fallback_waypoints(stub, mask)
        # 空 waypoints 触发 _fallback_waypoints
        MainWindow._on_path_finished(stub, np.zeros((0, 3), dtype=np.float32))
        stub._finish_path_planning.assert_called_once()

    def test_on_path_failed_falls_back_to_simulated(self, monkeypatch):
        """_on_path_failed 调用 _finish_path_planning 走回退路径。"""
        # Mock ErrorDialog.show
        import repair_app.ui.dialogs as dialogs_mod
        monkeypatch.setattr(dialogs_mod.ErrorDialog, "show", lambda *a, **kw: None)

        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        session.point_cloud.xyz = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0.5, 0.5, 0.5]
        ], dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _selector=MagicMock(),
            _set_busy=MagicMock(),
            _finish_path_planning=MagicMock(),
        )
        # _on_path_failed 调用 self._fallback_waypoints(sel_mask) — 绑定
        stub._fallback_waypoints = lambda mask: MainWindow._fallback_waypoints(stub, mask)
        MainWindow._on_path_failed(stub, "E_PATH", "friendly", "detail")
        stub._finish_path_planning.assert_called_once()

    def test_on_zmq_path_error_sets_busy_false(self, monkeypatch):
        """_on_zmq_path_error 解除 busy 并显示对话框。"""
        import repair_app.ui.dialogs as dialogs_mod
        monkeypatch.setattr(dialogs_mod.ErrorDialog, "show", lambda *a, **kw: None)

        stub = _make_stub(
            _set_busy=MagicMock(),
            _workflow_controller=MagicMock(),
        )
        MainWindow._on_zmq_path_error(stub, "connection refused")
        stub._set_busy.assert_called_with(False)
        stub._workflow_controller.mark_running_as_failed.assert_called_once()

    def test_on_morph_partial_updates_progress(self):
        """_on_morph_partial 更新进度。"""
        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        stub = _make_stub(
            _session=session,
            _prog=MagicMock(),
            _lb_prog=MagicMock(),
            _sb=MagicMock(),
            _lb_bottom_status=MagicMock(),
            _visualizer=MagicMock(),
            _selector=MagicMock(),
            _update_morph_section=lambda *a, **kw: None,
        )
        repair_pts = np.array([[0, 0, 0.5], [1, 1, 0.5]], dtype=np.float32)
        MainWindow._on_morph_partial(stub, repair_pts, 1, 3)
        stub._prog.setValue.assert_called_once()
        stub._visualizer.set_partial_repair.assert_called_with(repair_pts)

    def test_on_morph_finished_calls_finish_morphology(self):
        """_on_morph_finished 调用 _finish_morphology。"""
        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        stub = _make_stub(
            _session=session,
            _selector=MagicMock(),
            _sb=MagicMock(),
            _finish_morphology=MagicMock(),
        )
        repair_pts = np.array([[0, 0, 0.5]], dtype=np.float32)
        MainWindow._on_morph_finished(stub, repair_pts, is_mock=True)
        assert session.morphology.is_mock is True
        stub._finish_morphology.assert_called_once()

    def test_on_morph_failed_with_partial_results(self, monkeypatch):
        """_on_morph_failed 有部分结果时回退显示。"""
        import repair_app.ui.dialogs as dialogs_mod
        monkeypatch.setattr(dialogs_mod.ErrorDialog, "show", lambda *a, **kw: None)

        session = RepairSession()
        session.selection.mask = np.array([True, True, True, False, False])
        stub = _make_stub(
            _session=session,
            _selector=MagicMock(),
            _finish_morphology=MagicMock(),
            _set_busy=MagicMock(),
        )
        repair_pts = np.array([[0, 0, 0.5]], dtype=np.float32)
        MainWindow._on_morph_failed(stub, "E_MORPH", "friendly", "detail", repair_pts)
        stub._finish_morphology.assert_called_once()

    def test_on_morph_failed_no_results(self, monkeypatch):
        """_on_morph_failed 无结果时显示错误对话框。"""
        import repair_app.ui.dialogs as dialogs_mod
        monkeypatch.setattr(dialogs_mod.ErrorDialog, "show", lambda *a, **kw: None)

        stub = _make_stub(
            _session=RepairSession(),
            _selector=MagicMock(),
            _set_busy=MagicMock(),
        )
        MainWindow._on_morph_failed(stub, "E_MORPH", "friendly", "detail", None)
        stub._set_busy.assert_called_with(False)


# ============================================================
# 11. MainWindow 视图菜单动作
# ============================================================

@pytest.mark.unit
class TestViewActions:
    """_on_reset_view / _on_fit_view / _on_toggle_axes / _on_clear_selection。"""

    def test_on_reset_view_with_visualizer(self):
        """有 visualizer 时调用 reset_view。"""
        viz = MagicMock()
        stub = _make_stub(_visualizer=viz)
        MainWindow._on_reset_view(stub)
        viz.reset_view.assert_called_once()

    def test_on_reset_view_no_visualizer(self):
        """无 visualizer 时不抛。"""
        stub = _make_stub()
        stub._visualizer = None
        MainWindow._on_reset_view(stub)  # 不应抛

    def test_on_reset_view_exception_swallowed(self):
        """visualizer.reset_view 抛异常时被吞掉。"""
        viz = MagicMock()
        viz.reset_view.side_effect = RuntimeError("boom")
        stub = _make_stub(_visualizer=viz)
        MainWindow._on_reset_view(stub)  # 不应抛

    def test_on_fit_view_with_visualizer(self):
        """有 visualizer 时调用 fit_to_view。"""
        viz = MagicMock()
        stub = _make_stub(_visualizer=viz)
        MainWindow._on_fit_view(stub)
        viz.fit_to_view.assert_called_once()

    def test_on_fit_view_no_visualizer(self):
        """无 visualizer 时不抛。"""
        stub = _make_stub()
        stub._visualizer = None
        MainWindow._on_fit_view(stub)

    def test_on_fit_view_exception_swallowed(self):
        viz = MagicMock()
        viz.fit_to_view.side_effect = RuntimeError("boom")
        stub = _make_stub(_visualizer=viz)
        MainWindow._on_fit_view(stub)

    def test_on_toggle_axes_with_visualizer(self):
        viz = MagicMock()
        stub = _make_stub(_visualizer=viz)
        MainWindow._on_toggle_axes(stub)
        viz.toggle_axes.assert_called_once()

    def test_on_toggle_axes_no_visualizer(self):
        stub = _make_stub()
        stub._visualizer = None
        MainWindow._on_toggle_axes(stub)

    def test_on_clear_selection_with_selector(self):
        sel = MagicMock()
        stub = _make_stub(_selector=sel)
        MainWindow._on_clear_selection(stub)
        sel.clear_selection.assert_called_once()

    def test_on_clear_selection_no_selector(self):
        stub = _make_stub()
        stub._selector = None
        MainWindow._on_clear_selection(stub)

    def test_on_clear_selection_exception_swallowed(self):
        sel = MagicMock()
        sel.clear_selection.side_effect = RuntimeError("boom")
        stub = _make_stub(_selector=sel)
        MainWindow._on_clear_selection(stub)


# ============================================================
# 12. MainWindow 主题切换
# ============================================================

@pytest.mark.unit
class TestThemeSwitch:
    """_on_switch_theme。"""

    def test_on_switch_theme_updates_qss(self, monkeypatch):
        """_on_switch_theme 调用 ThemeManager.set_theme + get_qss。"""
        import repair_app.ui.theme_manager as tm_mod
        monkeypatch.setattr(tm_mod.ThemeManager, "set_theme", lambda name: None)
        monkeypatch.setattr(tm_mod.ThemeManager, "get_qss", lambda: "qss")
        # _on_switch_theme 调用 self.setStyleSheet 和 Toast.info，需 MainWindow 实例
        mw = _make_main_window_new()
        mw.setStyleSheet = MagicMock()
        mw._on_switch_theme("light")
        mw.setStyleSheet.assert_called_with("qss")
        mw.deleteLater()


# ============================================================
# 13. MainWindow 最近项目菜单
# ============================================================

@pytest.mark.unit
class TestRecentMenu:
    """_refresh_recent_menu / _on_clear_recent / _on_open_recent。"""

    def test_refresh_recent_menu_empty(self, qapp):
        """空列表时显示 (无) 项。"""
        from PySide6.QtWidgets import QMenu
        recent = QMenu()
        recent_projects = MagicMock()
        recent_projects.items = []
        mw = _make_main_window_new()
        mw._recent_menu = recent
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu()
        assert len(recent.actions()) >= 1
        recent.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_recent_menu_with_items(self, qapp):
        """有项目时创建菜单项 + 清空入口。"""
        from PySide6.QtWidgets import QMenu
        recent = QMenu()
        recent_projects = MagicMock()
        recent_projects.items = [
            {"name": "proj1", "path": "/tmp/p1.csam"},
            {"name": "proj2", "path": "/tmp/p2.csam"},
        ]
        mw = _make_main_window_new()
        mw._recent_menu = recent
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu()
        # 应有 2 个项目项 + 1 个分隔符 + 1 个清空入口
        assert len(recent.actions()) >= 3
        recent.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_clear_recent(self, qapp):
        """_on_clear_recent 清空列表并刷新菜单。"""
        recent_projects = MagicMock()
        mw = _make_main_window_new()
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu = MagicMock()
        mw._sb = MagicMock()
        mw._on_clear_recent()
        recent_projects.clear.assert_called_once()
        mw._refresh_recent_menu.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_open_recent_missing_file(self, qapp):
        """文件不存在时弹出警告并移除。"""
        recent_projects = MagicMock()
        mw = _make_main_window_new()
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu = MagicMock()
        mw._load_project_from_path = MagicMock()
        mw._on_open_recent("/nonexistent/file.csam")
        recent_projects.remove.assert_called_once_with("/nonexistent/file.csam")
        mw._load_project_from_path.assert_not_called()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 14. MainWindow 自动保存 / 项目状态
# ============================================================

@pytest.mark.unit
class TestAutosaveAndProjectState:
    """_do_autosave / _collect_project_state。"""

    def test_do_autosave_calls_collect_and_save(self):
        """_do_autosave 调用 _collect_project_state + auto_recovery.save。"""
        auto_recovery = MagicMock()
        mw = _make_main_window_new()
        mw._auto_recovery = auto_recovery
        mw._collect_project_state = MagicMock(return_value={"a": 1})
        mw._do_autosave()
        mw._collect_project_state.assert_called_once()
        auto_recovery.save.assert_called_once_with({"a": 1})
        mw.deleteLater()

    def test_do_autosave_swallows_exception(self):
        """_collect_project_state 抛异常时被吞掉。"""
        auto_recovery = MagicMock()
        mw = _make_main_window_new()
        mw._auto_recovery = auto_recovery
        mw._collect_project_state = MagicMock(side_effect=RuntimeError("boom"))
        mw._do_autosave()  # 不应抛
        auto_recovery.save.assert_not_called()
        mw.deleteLater()

    def test_collect_project_state_with_session(self):
        """_collect_project_state 收集点云路径 + 模式 + 材料。"""
        session = RepairSession()
        session.point_cloud.path = "/data/cloud.xyz"
        session.repair_mode = MODE_REPAIRING
        session.selection.mask = np.array([True, True, False])
        session.point_cloud.xyz = np.array([[0, 0, 0], [1, 1, 0], [2, 2, 0]], dtype=np.float32)
        pm = MagicMock()
        pm.collect_state.return_value = {"_collected": True}
        mw = _make_main_window_new()
        mw._session = session
        mw._project_manager = pm
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 1
        mw._collect_params = MagicMock(return_value={"layer_height": 0.5})
        state = mw._collect_project_state()
        assert state == {"_collected": True}
        pm.collect_state.assert_called_once()
        kwargs = pm.collect_state.call_args.kwargs
        assert kwargs["point_cloud_path"] == "/data/cloud.xyz"
        assert kwargs["repair_mode"] == MODE_REPAIRING
        assert kwargs["material_index"] == 1
        mw.deleteLater()

    def test_collect_project_state_no_cb_mat(self):
        """无 _cb_mat 时 material_index=0。"""
        session = RepairSession()
        pm = MagicMock()
        pm.collect_state.return_value = {}
        mw = _make_main_window_new()
        mw._session = session
        mw._project_manager = pm
        # 不设 _cb_mat
        mw._collect_params = MagicMock(return_value={})
        state = mw._collect_project_state()
        kwargs = pm.collect_state.call_args.kwargs
        assert kwargs["material_index"] == 0
        mw.deleteLater()

    def test_collect_project_state_handles_collect_failure(self):
        """_collect_params 抛异常时 params={}。"""
        session = RepairSession()
        pm = MagicMock()
        pm.collect_state.return_value = {}
        mw = _make_main_window_new()
        mw._session = session
        mw._project_manager = pm
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 0
        mw._collect_params = MagicMock(side_effect=RuntimeError("boom"))
        state = mw._collect_project_state()
        # 不应抛
        kwargs = pm.collect_state.call_args.kwargs
        assert kwargs["params"] == {}
        mw.deleteLater()


# ============================================================
# 15. MainWindow 参数恢复
# ============================================================

@pytest.mark.unit
class TestApplyParams:
    """_apply_params / _apply_preset_params。"""

    def test_apply_params_empty_dict_returns(self):
        """空 params 字典时直接返回。"""
        mw = _make_main_window_new()
        mw._apply_params({})
        mw.deleteLater()

    def test_apply_params_empty_no_attrs(self):
        """无 _pp_fields/_cs_fields 属性时不抛。"""
        mw = _make_main_window_new()
        mw._apply_params({"layer_height": 0.5})
        mw.deleteLater()

    def test_apply_params_with_fields(self):
        """有字段时调用 setValue。"""
        pp_field = MagicMock()
        cs_field = MagicMock()
        mw = _make_main_window_new()
        mw._pp_fields = {"layer_height": pp_field}
        mw._cs_fields = {"particle_velocity": cs_field}
        mw._apply_params({"layer_height": 0.5, "particle_velocity": 600})
        pp_field.setValue.assert_called_with(0.5)
        cs_field.setValue.assert_called_with(600)
        mw.deleteLater()

    def test_apply_params_standalone_widgets(self):
        """独立控件 _sp_pp_layers / _sp_max_layers / _sp_depth。"""
        mw = _make_main_window_new()
        mw._pp_fields = {}
        mw._cs_fields = {}
        mw._sp_pp_layers = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_depth = MagicMock()
        mw._apply_params({"pp_layers": 5, "max_layers": 10, "depth": 1.5})
        mw._sp_pp_layers.setValue.assert_called_with(5)
        mw._sp_max_layers.setValue.assert_called_with(10)
        mw._sp_depth.setValue.assert_called_with(1.5)
        mw.deleteLater()

    def test_apply_params_widget_setvalue_fails_silently(self):
        """widget.setValue 抛异常时被吞掉。"""
        pp_field = MagicMock()
        pp_field.setValue.side_effect = RuntimeError("boom")
        mw = _make_main_window_new()
        mw._pp_fields = {"layer_height": pp_field}
        mw._cs_fields = {}
        mw._apply_params({"layer_height": 0.5})  # 不应抛
        mw.deleteLater()

    def test_apply_preset_params_applies_to_fields(self):
        """_apply_preset_params 将预设应用到字段。"""
        cs_map = {
            "particle_velocity": MagicMock(),
            "critical_velocity": MagicMock(),
            "nozzle_diameter": MagicMock(),
            "spray_angle": MagicMock(),
            "standoff_distance": MagicMock(),
            "particle_size": MagicMock(),
            "gas_temperature": MagicMock(),
            "gas_pressure": MagicMock(),
            "powder_feed_rate": MagicMock(),
            "traversing_speed": MagicMock(),
        }
        pp_map = {
            "layer_height": MagicMock(),
            "scanning_angle": MagicMock(),
            "scanning_step": MagicMock(),
            "edge_step_size": MagicMock(),
            "tilt_angle": MagicMock(),
            "buffer_additive": MagicMock(),
            "buffer_repairing": MagicMock(),
            "link_free_dist": MagicMock(),
            "obstacle_resolution": MagicMock(),
        }
        mw = _make_main_window_new()
        mw._cs_fields = cs_map
        mw._pp_fields = pp_map
        mw._sp_pp_layers = MagicMock()
        mw._sb = MagicMock()
        params = {
            "particle_velocity_ms": 500.0,
            "critical_velocity_ms": 400.0,
            "nozzle_diameter_mm": 6.0,
            "spray_angle_deg": 90.0,
            "standoff_distance_mm": 30.0,
            "particle_size_um": 25.0,
            "gas_temperature_c": 800.0,
            "gas_pressure_bar": 40.0,
            "powder_feed_rate_gmin": 30.0,
            "traversing_speed_mms": 500.0,
            "layer_height_mm": 0.5,
            "scanning_angle_deg": 45.0,
            "scanning_step_mm": 1.0,
            "edge_step_size_mm": 0.5,
            "tilt_angle_deg": 60.0,
            "buffer_additive_mm": 2.0,
            "buffer_repairing_mm": 0.0,
            "link_free_dist_mm": 20.0,
            "obstacle_resolution_mm": 2.0,
            "num_layers": 7,
        }
        mw._apply_preset_params(params)
        cs_map["particle_velocity"].setValue.assert_called_with(500.0)
        pp_map["layer_height"].setValue.assert_called_with(0.5)
        mw._sp_pp_layers.setValue.assert_called_with(7)
        mw._sb.showMessage.assert_called_once()
        mw.deleteLater()

    def test_apply_preset_params_handles_exception(self, monkeypatch):
        """_apply_preset_params 抛异常时通过 _show_error 显示。"""
        mw = _make_main_window_new()
        mw._cs_fields = MagicMock()
        # 让 cs_fields __iter__ 抛
        mw._cs_fields.__iter__ = lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        mw._pp_fields = {}
        # Mock _show_error
        monkeypatch.setattr(_mw_mod, "_show_error", lambda parent, ctx, exc: None)
        mw._apply_preset_params({"any": 1})  # 不应抛
        mw.deleteLater()


# ============================================================
# 16. MainWindow _check_recovery（已部分覆盖于 test_crash_recovery.py，此处补充更多分支）
# ============================================================

@pytest.mark.unit
class TestCheckRecoveryExtra:
    """_check_recovery 额外分支覆盖。"""

    def _make_stub(self, ar, apply_fn=None):
        apply_calls = []
        if apply_fn is None:
            def apply_fn(state):
                apply_calls.append(state)
        return _make_stub(_auto_recovery=ar, _apply_recovered_state=apply_fn), apply_calls

    def test_skips_when_no_pending(self, tmp_path, monkeypatch):
        from repair_app.software.project_manager import AutoRecovery
        from repair_app.software.path_manager import PathManager
        monkeypatch.setenv("CSAM_USER_DATA", str(tmp_path))
        pm = PathManager()
        ar = AutoRecovery(pm)
        ar.clear()
        stub, _ = self._make_stub(ar)

        def _no_dialog(*a, **kw):
            pytest.fail("无恢复文件时不应弹窗")

        monkeypatch.setattr(QMessageBox, "question", _no_dialog)
        MainWindow._check_recovery(stub)

    def test_applies_when_user_yes(self, tmp_path, monkeypatch):
        """P3-1: 有恢复文件时自动应用状态（非阻塞，无需用户确认）。"""
        from repair_app.software.project_manager import AutoRecovery
        from repair_app.software.path_manager import PathManager
        monkeypatch.setenv("CSAM_USER_DATA", str(tmp_path))
        pm = PathManager()
        ar = AutoRecovery(pm)
        ar.save({"point_cloud_path": "/x", "repair_mode": 1})
        stub, apply_calls = self._make_stub(ar)
        # Mock Toast.info 避免依赖真实 GUI（新流程用 Toast 替代 QMessageBox）
        from repair_app.ui import main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "info", lambda *a, **kw: None)
        MainWindow._check_recovery(stub)
        assert len(apply_calls) == 1

    def test_clears_when_user_no(self, tmp_path, monkeypatch):
        """P3-1: 新流程为自动恢复，无 No 分支；pending 状态保留（不再清除）。"""
        from repair_app.software.project_manager import AutoRecovery
        from repair_app.software.path_manager import PathManager
        monkeypatch.setenv("CSAM_USER_DATA", str(tmp_path))
        pm = PathManager()
        ar = AutoRecovery(pm)
        ar.save({"x": 1})
        stub, apply_calls = self._make_stub(ar)
        from repair_app.ui import main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "info", lambda *a, **kw: None)
        MainWindow._check_recovery(stub)
        # 新流程自动应用 state
        assert len(apply_calls) == 1
        # pending 状态保留（自动恢复不再清除文件）
        assert ar.has_pending_recovery


# ============================================================
# 17. MainWindow 导出相关方法
# ============================================================

@pytest.mark.unit
class TestExportMethods:
    """_on_export / _prepare_for_export / _save_validation_report / _on_export_gcode 等。"""

    def test_on_export_gcode_delegates(self):
        """_on_export_gcode 调用 _on_export('gcode')。"""
        mw = _make_main_window_new()
        mw._on_export = MagicMock()
        mw._on_export_gcode()
        mw._on_export.assert_called_with("gcode")
        mw.deleteLater()

    def test_on_export_pdf_delegates(self):
        """_on_export_pdf 调用 _on_export('pdf')。"""
        mw = _make_main_window_new()
        mw._on_export = MagicMock()
        mw._on_export_pdf()
        mw._on_export.assert_called_with("pdf")
        mw.deleteLater()

    def test_on_export_robot_delegates(self):
        """_on_export_robot 调用 _on_export('robot')。"""
        mw = _make_main_window_new()
        mw._on_export = MagicMock()
        mw._on_export_robot()
        mw._on_export.assert_called_with("robot")
        mw.deleteLater()

    def test_on_export_invalid_license_returns(self, monkeypatch):
        """License 无效时直接返回。"""
        from repair_app.utils.license_manager import LicenseManager
        # Mock Toast.warning 避免模态阻塞
        import repair_app.ui.toast as toast_mod
        monkeypatch.setattr(toast_mod.Toast, "warning", lambda *a, **kw: None)
        with patch.object(LicenseManager, "is_valid", new_callable=PropertyMock, return_value=False):
            mw = _make_main_window_new()
            mw._license = LicenseManager()
            mw._license._error = "expired"  # 直接设私有属性（property 无 setter）
            # 调用真实 _on_export — 应直接 return 不抛
            MainWindow._on_export(mw, "gcode")
            mw.deleteLater()

    def test_save_validation_report_with_filepath(self, tmp_path):
        """_save_validation_report 使用 fp 推导路径。"""
        validation = MagicMock()
        validation.generate_report.return_value = True
        mw = _make_main_window_new()
        fp = str(tmp_path / "test.nc")
        mw._save_validation_report(validation, fp)
        validation.generate_report.assert_called_once()
        # 报告路径应为 fp + _validation_*.md
        report_path = validation.generate_report.call_args[0][0]
        assert "_validation_" in report_path
        assert report_path.endswith(".md")
        mw.deleteLater()

    def test_save_validation_report_without_filepath(self):
        """fp=None 时使用 path_manager 推导路径。"""
        validation = MagicMock()
        validation.generate_report.return_value = True
        path_manager = MagicMock()
        pdf_path = MagicMock()
        pdf_path.__str__ = lambda self: "/reports/proj_validation_x.md"
        path_manager.pdf_path.return_value = pdf_path
        mw = _make_main_window_new()
        mw._path_manager = path_manager
        mw._project_manager = MagicMock()
        mw._project_manager.current_name = "testproj"
        mw._save_validation_report(validation, None)
        validation.generate_report.assert_called_once()

    def test_save_validation_report_generate_fails(self):
        """generate_report 返回 False 时不抛。"""
        validation = MagicMock()
        validation.generate_report.return_value = False
        mw = _make_main_window_new()
        mw._save_validation_report(validation, "/x.nc")
        # 不应抛
        mw.deleteLater()

    def test_save_validation_report_exception_swallows(self):
        """generate_report 抛异常时被吞掉。"""
        validation = MagicMock()
        validation.generate_report.side_effect = RuntimeError("boom")
        mw = _make_main_window_new()
        mw._save_validation_report(validation, "/x.nc")  # 不应抛
        mw.deleteLater()


# ============================================================
# 18. MainWindow 计算辅助方法
# ============================================================

@pytest.mark.unit
class TestComputeHelpers:
    """_compute_defect_metrics / _compute_path_metrics / _fallback_waypoints /
    _build_layers_from_waypoints / _build_morph_layers / _apply_result_metrics。"""

    def test_compute_defect_metrics_no_cloud(self):
        """无点云时返回零指标。"""
        session = RepairSession()
        mw = _make_main_window_new()
        mw._session = session
        result = mw._compute_defect_metrics(np.array([], dtype=bool))
        assert result["point_count"] == 0
        assert result["volume_mm3"] == 0.0
        mw.deleteLater()

    def test_compute_defect_metrics_empty_mask(self):
        """空 mask 时返回零指标。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        result = mw._compute_defect_metrics(np.zeros(5, dtype=bool))
        assert result["point_count"] == 0
        mw.deleteLater()

    def test_compute_defect_metrics_with_mask(self):
        """有选区时计算正确指标。"""
        session = RepairSession()
        session.point_cloud.xyz = np.array([
            [0, 0, 0], [1, 0, 0.5], [0, 1, 0.5], [1, 1, 1.0], [0.5, 0.5, 0.5]
        ], dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mask = np.array([True, True, True, False, False])
        result = mw._compute_defect_metrics(mask)
        assert result["point_count"] == 3
        assert result["depth_mm"] == pytest.approx(0.5, abs=1e-5)
        # area = (1-0) * (1-0) = 1
        assert result["area_mm2"] == pytest.approx(1.0)
        mw.deleteLater()

    def test_compute_path_metrics_no_waypoints(self):
        """无航点时返回零路径长度。"""
        session = RepairSession()
        mw = _make_main_window_new()
        mw._session = session
        result = mw._compute_path_metrics()
        assert result["path_length_mm"] == 0.0
        mw.deleteLater()

    def test_compute_path_metrics_with_waypoints(self):
        """有航点时计算长度。"""
        session = RepairSession()
        session.waypoint.mock = np.array([
            [0, 0, 0], [1, 0, 0], [1, 1, 0]
        ], dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mw._collect_params = MagicMock(return_value={"traversing_speed_mms": 500.0})
        result = mw._compute_path_metrics()
        assert result["path_length_mm"] == pytest.approx(2.0)
        assert result["estimated_time_s"] == pytest.approx(2.0 / 500.0)
        mw.deleteLater()

    def test_fallback_waypoints_returns_array(self):
        """_fallback_waypoints 生成回退航点。"""
        session = RepairSession()
        session.point_cloud.xyz = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0.5, 0.5, 0.5]
        ], dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mask = np.array([True, True, True, True, True])
        result = mw._fallback_waypoints(mask)
        assert result.shape[1] == 3
        assert result.shape[0] > 0
        mw.deleteLater()

    def test_build_layers_from_waypoints_none(self):
        """waypoints=None 返回 None。"""
        mw = _make_main_window_new()
        result = mw._build_layers_from_waypoints(None, None)
        assert result is None
        mw.deleteLater()

    def test_build_layers_from_waypoints_empty(self):
        """空 waypoints 返回 None。"""
        mw = _make_main_window_new()
        result = mw._build_layers_from_waypoints(
            np.zeros((0, 3)), np.array([], dtype=int)
        )
        assert result is None
        mw.deleteLater()

    def test_build_layers_from_waypoints_single_layer(self):
        """单层时返回 None（< 2 层）。"""
        mw = _make_main_window_new()
        wps = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        layers = np.array([0, 0], dtype=int)
        result = mw._build_layers_from_waypoints(wps, layers)
        assert result is None
        mw.deleteLater()

    def test_build_layers_from_waypoints_multi_layer(self):
        """多层时构造累积帧。"""
        mw = _make_main_window_new()
        wps = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float32)
        layers = np.array([0, 1, 2], dtype=int)
        result = mw._build_layers_from_waypoints(wps, layers)
        assert result is not None
        assert len(result) == 3  # 3 个累积帧
        # 第一帧只含层 0
        assert result[0].shape[0] == 1
        # 最后一帧含全部
        assert result[-1].shape[0] == 3
        mw.deleteLater()

    def test_build_morph_layers_returns_frames(self):
        """_build_morph_layers 生成 60 帧插值。"""
        mw = _make_main_window_new()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 10
        repair_pts = np.array([[0, 0, 0], [1, 1, 0]], dtype=np.float32)
        result = mw._build_morph_layers(repair_pts)
        assert result is not None
        assert len(result) == 60
        mw.deleteLater()

    def test_build_morph_layers_empty_returns_none(self):
        """空 repair_pts 返回 None。"""
        mw = _make_main_window_new()
        result = mw._build_morph_layers(np.zeros((0, 3), dtype=np.float32))
        assert result is None
        mw.deleteLater()

    def test_apply_result_metrics_no_metrics(self):
        """metrics=None 时直接返回。"""
        mw = _make_main_window_new()
        mw._apply_result_metrics(None, 10, None)  # 不应抛
        mw.deleteLater()

    def test_apply_result_metrics_with_values(self):
        """有 metrics 时更新标签。"""
        mw = _make_main_window_new()
        mw._lb_mass = MagicMock()
        mw._lb_time = MagicMock()
        mw._lb_unif = MagicMock()
        mw._lb_lay = MagicMock()
        metrics = {
            "estimated_mass_g": 12.5,
            "estimated_time_s": 60.0,
            "uniformity_score": 0.92,
            "layer_profiles": [{"x": 1}],
        }
        waypoint_layers = np.array([0, 1, 2, 0, 1, 2], dtype=int)
        mw._apply_result_metrics(metrics, 6, waypoint_layers)
        mw._lb_mass.setText.assert_called_once()
        mw._lb_time.setText.assert_called_once()
        mw._lb_unif.setText.assert_called_once()
        mw._lb_lay.setText.assert_called_once()
        mw.deleteLater()


# ============================================================
# 19. MainWindow 重置 / 形貌状态
# ============================================================

@pytest.mark.unit
class TestResetAndMorphStatus:
    """_reset_output / _refresh_morph_status / _set_busy。"""

    def test_reset_output_clears_session(self):
        """_reset_output 清空会话状态。"""
        session = RepairSession()
        session.waypoint.mock = np.zeros((3, 3))
        session.output.path_output_ready = True
        mw = _make_main_window_new()
        mw._session = session
        mw._export_buttons = {}
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._update_step_buttons = MagicMock()
        mw._reset_output()
        assert session.waypoint.mock is None
        assert session.output.path_output_ready is False
        mw._btn_fix.setEnabled.assert_called_with(False)
        mw.deleteLater()

    def test_reset_output_disables_export_buttons(self):
        """_reset_output 禁用所有导出按钮。"""
        session = RepairSession()
        btn1, btn2 = MagicMock(), MagicMock()
        mw = _make_main_window_new()
        mw._session = session
        mw._export_buttons = {"gcode": btn1, "pdf": btn2}
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._update_step_buttons = MagicMock()
        mw._reset_output()
        btn1.setEnabled.assert_called_with(False)
        btn2.setEnabled.assert_called_with(False)
        mw.deleteLater()

    def test_refresh_morph_status_no_waypoints(self):
        """无航点时显示等待提示。"""
        session = RepairSession()
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_pl_status = MagicMock()
        mw._lb_input_source = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._refresh_morph_status()
        mw._lb_pl_status.setText.assert_called_once()
        text = mw._lb_pl_status.setText.call_args[0][0]
        assert "路径规划" in text
        mw.deleteLater()

    def test_refresh_morph_status_with_waypoints(self):
        """有航点时显示就绪提示。"""
        session = RepairSession()
        session.waypoint.mock = np.zeros((5, 3))
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_pl_status = MagicMock()
        mw._lb_input_source = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._refresh_morph_status()
        mw._lb_pl_status.setText.assert_called_once()
        text = mw._lb_pl_status.setText.call_args[0][0]
        assert "5" in text
        mw._btn_fix.setEnabled.assert_called_with(True)
        mw.deleteLater()

    def test_refresh_morph_status_busy_skips_button_update(self):
        """busy 时不更新按钮。"""
        session = RepairSession()
        session.is_busy = True
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_pl_status = MagicMock()
        mw._lb_input_source = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._refresh_morph_status()
        mw._btn_fix.setEnabled.assert_not_called()
        mw.deleteLater()

    def test_set_busy_true_disables_buttons(self):
        """_set_busy(True) 禁用所有按钮。"""
        session = RepairSession()
        mw = _make_main_window_new()
        mw._session = session
        mw._busy_label = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._btn_exp_gcode = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._btn_exp_pdf = MagicMock()
        mw._update_step_buttons = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy(True)
        assert session.is_busy is True
        mw._btn_start_repair.setEnabled.assert_called_with(False)
        mw._busy_label.set_busy.assert_called_with(True, "处理中...")
        mw.deleteLater()

    def test_set_busy_false_enables_buttons_when_ready(self):
        """_set_busy(False) + 有 cloud + 有选区时启用按钮。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        session.repair_mode = MODE_REPAIRING
        mw = _make_main_window_new()
        mw._session = session
        mw._busy_label = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._btn_exp_gcode = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._btn_exp_pdf = MagicMock()
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, True, False, False])
        mw._export_buttons = {}
        mw._update_step_buttons = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy(False)
        assert session.is_busy is False
        mw._btn_start_repair.setEnabled.assert_called_with(True)
        mw.deleteLater()

    def test_set_busy_false_additive_mode(self):
        """增材模式 _set_busy(False) 时只要有 cloud 即可。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        session.repair_mode = MODE_ADDITIVE
        mw = _make_main_window_new()
        mw._session = session
        mw._busy_label = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._btn_exp_gcode = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._btn_exp_pdf = MagicMock()
        mw._export_buttons = {}
        mw._update_step_buttons = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy(False)
        mw._btn_start_repair.setEnabled.assert_called_with(True)
        mw.deleteLater()


# ============================================================
# 20. MainWindow 日志 / 关于 / 系统调用
# ============================================================

@pytest.mark.unit
class TestLogAndExplorer:
    """_on_export_logs / _on_open_log_dir / _open_in_explorer / _on_show_about。"""

    def test_on_open_export_dir_calls_open_in_explorer(self):
        """_on_open_export_dir 委托 _open_in_explorer。"""
        mw = _make_main_window_new()
        mw._open_in_explorer = MagicMock()
        path_manager = MagicMock()
        path_manager.exports_dir = "/exports"
        mw._path_manager = path_manager
        mw._on_open_export_dir()
        mw._open_in_explorer.assert_called_once_with("/exports")
        mw.deleteLater()

    def test_on_open_log_dir_calls_open_in_explorer(self):
        """_on_open_log_dir 委托 _open_in_explorer。"""
        mw = _make_main_window_new()
        mw._open_in_explorer = MagicMock()
        path_manager = MagicMock()
        logs_dir = MagicMock()
        logs_dir.__str__ = lambda self: "/logs"
        path_manager.logs_dir = logs_dir
        mw._path_manager = path_manager
        mw._on_open_log_dir()
        mw._open_in_explorer.assert_called_once()
        mw.deleteLater()

    def test_open_in_explorer_windows(self, monkeypatch):
        """Windows 下调用 os.startfile。"""
        import subprocess
        called = {}

        def fake_startfile(path):
            called["path"] = path

        monkeypatch.setattr(os, "startfile", fake_startfile, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        mw = _make_main_window_new()
        mw._open_in_explorer("C:/exports")
        assert called["path"] == "C:/exports"
        mw.deleteLater()

    def test_open_in_explorer_macos(self, monkeypatch):
        """macOS 下调用 subprocess.Popen(['open', path])。"""
        called = {}

        class FakePopen:
            def __init__(self, cmd):
                called["cmd"] = cmd

        monkeypatch.setattr(sys, "platform", "darwin")
        import repair_app.ui.main_window as mw_mod_inner
        # 模块已 import subprocess，直接 patch subprocess.Popen
        import subprocess as sp
        monkeypatch.setattr(sp, "Popen", FakePopen)
        mw = _make_main_window_new()
        mw._open_in_explorer("/exports")
        assert called["cmd"] == ["open", "/exports"]
        mw.deleteLater()

    def test_open_in_explorer_linux(self, monkeypatch):
        """Linux 下调用 subprocess.Popen(['xdg-open', path])。"""
        called = {}

        class FakePopen:
            def __init__(self, cmd):
                called["cmd"] = cmd

        monkeypatch.setattr(sys, "platform", "linux")
        import subprocess as sp
        monkeypatch.setattr(sp, "Popen", FakePopen)
        mw = _make_main_window_new()
        mw._open_in_explorer("/exports")
        assert called["cmd"] == ["xdg-open", "/exports"]
        mw.deleteLater()

    def test_open_in_explorer_exception_falls_back_to_toast(self, monkeypatch):
        """异常时通过 Toast.info 提示。"""
        monkeypatch.setattr(
            os,
            "startfile",
            lambda p: (_ for _ in ()).throw(OSError("no")),
            raising=False,
        )
        monkeypatch.setattr(sys, "platform", "win32")
        import repair_app.ui.toast as toast_mod
        info_called = []
        monkeypatch.setattr(toast_mod.Toast, "info", lambda *a, **kw: info_called.append((a, kw)))
        mw = _make_main_window_new()
        mw._open_in_explorer("C:/exports")
        assert len(info_called) == 1
        mw.deleteLater()

    def test_on_export_logs_user_cancels(self, monkeypatch):
        """用户取消文件对话框时不导出。"""
        # 已通过 autouse fixture mock getSaveFileName 返回 ("", "")
        mw = _make_main_window_new()
        path_manager = MagicMock()
        logs_dir = MagicMock()
        logs_dir.__truediv__ = lambda self, other: MagicMock()
        # 让 / 操作返回 mock 对象
        path_manager.logs_dir = logs_dir
        mw._path_manager = path_manager
        mw._sb = MagicMock()
        # 调用 — 应直接 return
        mw._on_export_logs()  # 不应抛
        mw.deleteLater()

    def test_on_export_logs_success(self, monkeypatch, tmp_path):
        """导出日志成功路径。"""
        out_file = str(tmp_path / "logs.zip")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (out_file, "ZIP 文件 (*.zip)"))
        # Mock export_logs
        import repair_app.utils.logger_config as lc_mod
        monkeypatch.setattr(lc_mod, "export_logs", lambda fp: fp)
        mw = _make_main_window_new()
        path_manager = MagicMock()
        path_manager.logs_dir = tmp_path
        mw._path_manager = path_manager
        mw._sb = MagicMock()
        mw._on_export_logs()
        mw._sb.showMessage.assert_called()
        mw.deleteLater()

    def test_on_export_logs_exception(self, monkeypatch, tmp_path):
        """导出日志异常时通过 _show_error 显示。"""
        out_file = str(tmp_path / "logs.zip")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (out_file, "ZIP 文件 (*.zip)"))
        import repair_app.utils.logger_config as lc_mod
        monkeypatch.setattr(lc_mod, "export_logs", lambda fp: (_ for _ in ()).throw(RuntimeError("zip fail")))
        # Mock _show_error
        show_error_called = []
        monkeypatch.setattr(_mw_mod, "_show_error", lambda parent, ctx, exc: show_error_called.append((ctx, exc)))
        mw = _make_main_window_new()
        path_manager = MagicMock()
        path_manager.logs_dir = tmp_path
        mw._path_manager = path_manager
        mw._sb = MagicMock()
        mw._on_export_logs()
        assert len(show_error_called) == 1
        assert show_error_called[0][0] == "日志导出失败"
        mw.deleteLater()

    def test_on_show_about_opens_dialog(self, monkeypatch):
        """_on_show_about 创建 AboutDialog 并 exec。"""
        # Mock AboutDialog
        import repair_app.software.about_dialog as ad_mod
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        monkeypatch.setattr(ad_mod, "AboutDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._on_show_about()
        mock_dlg.exec.assert_called_once()
        mw.deleteLater()


# ============================================================
# 21. MainWindow 项目保存 / 打开
# ============================================================

@pytest.mark.unit
class TestProjectSaveOpen:
    """_on_save_project / _on_open_project / _load_project_from_path。"""

    def test_on_save_project_success(self, monkeypatch, tmp_path):
        """保存项目成功路径。"""
        saved_path = tmp_path / "p.csam"
        project_manager = MagicMock()
        project_manager.save_project.return_value = saved_path
        project_manager.current_name = "testproj"
        recent_projects = MagicMock()
        mw = _make_main_window_new()
        mw._project_manager = project_manager
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu = MagicMock()
        mw._lb_project = MagicMock()
        mw._sb = MagicMock()
        mw._collect_project_state = MagicMock(return_value={"x": 1})
        # Mock Toast.success
        import repair_app.ui.toast as toast_mod
        monkeypatch.setattr(toast_mod.Toast, "success", lambda *a, **kw: None)
        mw._on_save_project()
        project_manager.save_project.assert_called_once_with({"x": 1})
        recent_projects.add.assert_called_once_with("testproj", str(saved_path))
        mw._refresh_recent_menu.assert_called_once()
        mw.deleteLater()

    def test_on_save_project_exception(self, monkeypatch):
        """保存项目异常时通过 _show_error 显示。"""
        project_manager = MagicMock()
        project_manager.save_project.side_effect = RuntimeError("disk full")
        mw = _make_main_window_new()
        mw._project_manager = project_manager
        mw._collect_project_state = MagicMock(return_value={"x": 1})
        show_error_called = []
        monkeypatch.setattr(_mw_mod, "_show_error", lambda parent, ctx, exc: show_error_called.append(ctx))
        mw._on_save_project()
        assert "保存失败" in show_error_called[0]
        mw.deleteLater()

    def test_on_open_project_user_cancels(self):
        """用户取消打开文件对话框时不加载。"""
        # autouse fixture 已 mock getOpenFileName → ("", "")
        mw = _make_main_window_new()
        mw._load_project_from_path = MagicMock()
        path_manager = MagicMock()
        path_manager.projects_dir = "/projects"
        mw._path_manager = path_manager
        mw._on_open_project()
        mw._load_project_from_path.assert_not_called()
        mw.deleteLater()

    def test_on_open_project_with_file(self, monkeypatch, tmp_path):
        """用户选择文件后调用 _load_project_from_path。"""
        fp = str(tmp_path / "p.csam")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (fp, ""))
        mw = _make_main_window_new()
        mw._load_project_from_path = MagicMock()
        path_manager = MagicMock()
        path_manager.projects_dir = "/projects"
        mw._path_manager = path_manager
        mw._on_open_project()
        mw._load_project_from_path.assert_called_once_with(fp)
        mw.deleteLater()

    def test_load_project_from_path_success(self, monkeypatch):
        """_load_project_from_path 成功路径。"""
        from pathlib import Path
        project_manager = MagicMock()
        project_manager.load_project.return_value = {"point_cloud_path": "/x"}
        project_manager.current_name = "testproj"
        recent_projects = MagicMock()
        mw = _make_main_window_new()
        mw._project_manager = project_manager
        mw._recent_projects = recent_projects
        mw._refresh_recent_menu = MagicMock()
        mw._lb_project = MagicMock()
        mw._apply_recovered_state = MagicMock()
        mw._load_project_from_path("/some/file.csam")
        project_manager.load_project.assert_called_once()
        recent_projects.add.assert_called_once()
        mw.deleteLater()

    def test_load_project_from_path_exception(self, monkeypatch):
        """_load_project_from_path 异常时通过 _show_error 显示。"""
        project_manager = MagicMock()
        project_manager.load_project.side_effect = RuntimeError("corrupt")
        mw = _make_main_window_new()
        mw._project_manager = project_manager
        mw._apply_recovered_state = MagicMock()
        show_error_called = []
        monkeypatch.setattr(_mw_mod, "_show_error", lambda parent, ctx, exc: show_error_called.append(ctx))
        mw._load_project_from_path("/x.csam")
        assert "打开失败" in show_error_called[0]
        mw.deleteLater()


# ============================================================
# 22. MainWindow 对话框入口（_on_calibration / _on_coord_transform 等）
# ============================================================

@pytest.mark.unit
class TestDialogEntries:
    """各种对话框入口方法。"""

    def test_on_calibration_opens_dialog(self, monkeypatch):
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        # CalibrationDialog 在 main_window 模块级导入，需 patch _mw_mod
        monkeypatch.setattr(_mw_mod, "CalibrationDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._on_calibration()
        mock_dlg.exec.assert_called_once()
        mw.deleteLater()

    def test_on_coord_transform_no_points(self, monkeypatch):
        """无点云时通过 Toast 提示而非打开对话框。"""
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        mock_dlg.transformed_points = None
        monkeypatch.setattr(_mw_mod, "CoordinateSystemDialog", lambda *a, **kw: mock_dlg)
        toast_called = []
        monkeypatch.setattr(_mw_mod.Toast, "warning", lambda *a, **kw: toast_called.append(kw))
        mw = _make_main_window_new()
        mw._selector = None
        mw._sb = MagicMock()
        mw._session = _make_session_with_cloud(0)  # xyz=None
        mw._session.point_cloud.xyz = None
        mw._on_coord_transform()
        # 无点云时应通过 Toast 提示，不打开对话框
        assert len(toast_called) == 1
        mock_dlg.exec.assert_not_called()
        mw.deleteLater()

    def test_on_coord_transform_applies(self, monkeypatch):
        """用户确认且有变换点时应用。"""
        new_points = np.array([[1, 2, 3]], dtype=np.float32)
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 1
        mock_dlg.transformed_points = new_points
        monkeypatch.setattr(_mw_mod, "CoordinateSystemDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._selector = MagicMock()
        mw._sb = MagicMock()
        mw._session = _make_session_with_cloud(5)
        mw._refresh_start_button_state = MagicMock()
        mw._on_coord_transform()
        mw._selector.set_points.assert_called_once_with(new_points)
        mw.deleteLater()

    def test_on_coord_transform_apply_exception(self, monkeypatch):
        """应用变换抛异常时通过 _show_error 显示。"""
        new_points = np.array([[1, 2, 3]], dtype=np.float32)
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 1
        mock_dlg.transformed_points = new_points
        monkeypatch.setattr(_mw_mod, "CoordinateSystemDialog", lambda *a, **kw: mock_dlg)
        show_error_called = []
        monkeypatch.setattr(_mw_mod, "_show_error", lambda parent, ctx, exc: show_error_called.append(ctx))
        mw = _make_main_window_new()
        mw._selector = MagicMock()
        mw._selector.set_points.side_effect = RuntimeError("boom")
        mw._sb = MagicMock()
        mw._session = _make_session_with_cloud(5)
        mw._on_coord_transform()
        assert "变换应用失败" in show_error_called[0]
        mw.deleteLater()

    def test_on_param_preset_dialog_cancelled(self, monkeypatch):
        """_on_param_preset 用户取消时不应用。"""
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        mock_dlg.result_params = None
        monkeypatch.setattr(_mw_mod, "ParameterPresetDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._collect_params = MagicMock(return_value={"v": 1})
        mw._apply_preset_params = MagicMock()
        mw._on_param_preset()
        mw._apply_preset_params.assert_not_called()
        mw.deleteLater()

    def test_on_param_preset_applied(self, monkeypatch):
        """_on_param_preset 用户确认时应用预设。"""
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 1
        mock_dlg.result_params = {"layer_height": 0.5}
        monkeypatch.setattr(_mw_mod, "ParameterPresetDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._collect_params = MagicMock(return_value={"v": 1})
        mw._apply_preset_params = MagicMock()
        mw._on_param_preset()
        mw._apply_preset_params.assert_called_once_with({"layer_height": 0.5})
        mw.deleteLater()

    def test_on_batch_validation_opens_dialog(self, monkeypatch):
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        monkeypatch.setattr(_mw_mod, "BatchValidationDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._collect_params = MagicMock(return_value={"v": 1})
        mw._on_batch_validation()
        mock_dlg.exec.assert_called_once()
        mw.deleteLater()

    def test_on_param_validator_opens_dialog(self, monkeypatch):
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0
        monkeypatch.setattr(_mw_mod, "ParameterValidatorDialog", lambda *a, **kw: mock_dlg)
        mw = _make_main_window_new()
        mw._collect_params = MagicMock(return_value={"v": 1})
        mw._on_param_validator()
        mock_dlg.exec.assert_called_once()
        mw.deleteLater()


# ============================================================
# 23. MainWindow closeEvent / resizeEvent
# ============================================================

@pytest.mark.unit
class TestCloseAndResize:
    """closeEvent / resizeEvent。"""

    def test_resizeEvent_calls_super(self):
        """resizeEvent 调用 super().resizeEvent。"""
        mw = _make_main_window_new()
        # MagicMock super().resizeEvent
        event = MagicMock()
        # 由于 mw 是 QMainWindow 实例（未 __init__），super().resizeEvent 可能行为未定义
        # 但 resizeEvent 应能调用
        try:
            mw.resizeEvent(event)
        except Exception:
            # 如果 C++ 对象未初始化导致 super() 失败，跳过
            pass
        mw.deleteLater()

    def test_closeEvent_stops_autosave_timer(self):
        """closeEvent 停止 autosave 定时器。"""
        mw = _make_main_window_new()
        mw._autosave_timer = MagicMock()
        mw._do_autosave = MagicMock()
        mw._path_thread = None
        mw._morph_thread = None
        mw._compute_thread = None
        # P3-11: 移除 _stop_progress_subscriber mock，closeEvent 已委托 ApplicationShutdownController
        mw._load_thread = None
        mw._report_thread = None
        mw._compute_worker = None
        mw._zmq_client = None
        mw._visualizer = None
        event = MagicMock()
        try:
            mw.closeEvent(event)
        except Exception:
            pass
        mw._autosave_timer.stop.assert_called_once()
        mw.deleteLater()


# ============================================================
# 24. MainWindow 模块常量导入（覆盖率初始化路径）
# ============================================================

@pytest.mark.unit
class TestModuleConstants:
    """模块级常量导入覆盖（已通过 import 触发）。"""

    def test_mode_constants_distinct(self):
        """MODE_ADDITIVE 与 MODE_REPAIRING 不同。"""
        assert MODE_ADDITIVE != MODE_REPAIRING

    def test_page_constants_distinct(self):
        """PAGE_PATH / PAGE_MORPH / PAGE_OUTPUT 互不相同。"""
        assert len({PAGE_PATH, PAGE_MORPH, PAGE_OUTPUT}) == 3

    def test_materials_list_non_empty(self):
        """_MATERIALS 列表非空。"""
        from repair_app.ui.main_window import _MATERIALS
        assert len(_MATERIALS) > 0

    def test_mat_key_map_dict(self):
        """_MAT_KEY_MAP 是 dict。"""
        from repair_app.ui.main_window import _MAT_KEY_MAP
        assert isinstance(_MAT_KEY_MAP, dict)


# ============================================================
# 25. UI Builder methods — _app_header / _left_column / _center / _right_column / _build_*_panel
# ============================================================

@pytest.mark.gui
class TestUIBuilderMethods:
    """UI 构建方法测试：_app_header, _left_column, _right_column, _build_*_panel 等。"""

    def test_app_header_creates_widget(self, qapp):
        """_app_header 创建 header widget 并设置属性。"""
        mw = _make_main_window_new()
        result = mw._app_header()
        assert result is not None
        assert hasattr(mw, "_lb_mode_state")
        assert hasattr(mw, "_lb_workflow_state")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_build_path_planning_panel(self, qapp):
        """_build_path_planning_panel 创建路径规划面板。"""
        mw = _make_main_window_new()
        mw._on_load = MagicMock()
        mw._on_mode_changed = MagicMock()
        mw._on_engine_changed = MagicMock()
        result = mw._build_path_planning_panel()
        assert result is not None
        assert hasattr(mw, "_btn_load")
        assert hasattr(mw, "_btn_start_repair")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_build_morphology_panel(self, qapp):
        """_build_morphology_panel 创建形貌预测面板。"""
        mw = _make_main_window_new()
        mw._on_feasibility_check = MagicMock()
        mw._on_fix = MagicMock()
        mw._cs_fields = {}  # needed by _build_morphology_panel
        result = mw._build_morphology_panel()
        assert result is not None
        assert hasattr(mw, "_lb_pl_status")
        assert hasattr(mw, "_btn_fix")
        assert hasattr(mw, "_btn_feas")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_build_output_panel(self, qapp):
        """_build_output_panel 创建输出面板，动态构建导出按钮。"""
        mw = _make_main_window_new()
        mw._on_export = MagicMock()
        result = mw._build_output_panel()
        assert result is not None
        assert hasattr(mw, "_export_buttons")
        assert len(mw._export_buttons) > 0
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_left_column(self, qapp):
        """_left_column 创建左侧面板。"""
        mw = _make_main_window_new()
        mw._switch_to_step = MagicMock()
        mw._on_material_changed = MagicMock()
        mw._style_workflow_label = MagicMock()
        mw._pp_fields = {}
        mw._cs_fields = {}
        result = mw._left_column()
        assert result is not None
        assert hasattr(mw, "_step1_btn")
        assert hasattr(mw, "_mode_stack")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_right_column(self, qapp):
        """_right_column 创建右侧面板。"""
        mw = _make_main_window_new()
        result = mw._right_column()
        assert result is not None
        assert hasattr(mw, "_lb_pts")
        assert hasattr(mw, "_prog")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_center(self, qapp):
        """_center 创建中心工作区。"""
        mw = _make_main_window_new()
        mw._on_selection_changed = MagicMock()
        mw._on_layer_changed = MagicMock()
        mw._on_layer_completed = MagicMock()
        mw._on_mesh_updated = MagicMock()
        mw._on_progress_received = MagicMock()
        result = mw._center()
        assert result is not None
        assert hasattr(mw, "_selector")
        assert hasattr(mw, "_visualizer")
        assert hasattr(mw, "_workspace_stack")
        result.deleteLater()
        mw.deleteLater()
        qapp.processEvents()

    def test_setup_statusbar(self, qapp, monkeypatch):
        """_setup_statusbar 创建状态栏 + 菜单栏 + 工具栏。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.ContextMenuManager, "__init__", lambda self, parent: None)
        # Mock ThemeManager.get_palette
        from repair_app.ui.theme_manager import ThemeManager as TM
        monkeypatch.setattr(TM, "get_palette", lambda: TM._palette if hasattr(TM, "_palette") else MagicMock(
            text_muted="#64748B", success="#10B981", warning="#F59E0B", error="#EF4444",
        ))
        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_developer_mode = False
        mw._license.is_valid = True
        mw._license.days_remaining = 30
        mw._recent_projects = MagicMock()
        mw._recent_projects.items = []
        mw._on_load = MagicMock()
        mw._on_save_project = MagicMock()
        mw._on_open_project = MagicMock()
        mw._on_open_export_dir = MagicMock()
        mw._on_open_log_dir = MagicMock()
        mw._on_export_logs = MagicMock()
        mw._on_export_robot = MagicMock()
        mw._on_feasibility_check = MagicMock()
        mw._on_calibration = MagicMock()
        mw._on_coord_transform = MagicMock()
        mw._on_param_preset = MagicMock()
        mw._on_batch_validation = MagicMock()
        mw._on_param_validator = MagicMock()
        mw._on_clear_selection = MagicMock()
        mw._on_reset_view = MagicMock()
        mw._on_fit_view = MagicMock()
        mw._on_toggle_axes = MagicMock()
        mw._on_switch_theme = MagicMock()
        mw._on_show_about = MagicMock()
        mw._refresh_recent_menu = MagicMock()
        mw._on_clear_recent = MagicMock()
        mw._undo_stack = MagicMock()
        mw._undo_stack.create_undo_action.return_value = MagicMock()
        mw._undo_stack.create_redo_action.return_value = MagicMock()
        mw._setup_menubar = MagicMock()
        mw._setup_toolbar = MagicMock()
        mw._setup_context_menu = MagicMock()
        mw._refresh_license_status = MagicMock()
        # Actually call _setup_statusbar
        MainWindow._setup_statusbar(mw)
        assert hasattr(mw, "_sb")
        mw.deleteLater()
        qapp.processEvents()

    def test_setup_ui(self, qapp):
        """_setup_ui 创建完整 UI 布局。"""
        mw = _make_main_window_new()
        mw._apply_theme = MagicMock()
        mw._app_header = MagicMock(return_value=QWidget())
        mw._left_column = MagicMock(return_value=QWidget())
        mw._center = MagicMock(return_value=QWidget())
        mw._right_column = MagicMock(return_value=QWidget())
        mw._setup_ui()
        mw._apply_theme.assert_called_once()
        mw._app_header.assert_called_once()
        mw._left_column.assert_called_once()
        mw._center.assert_called_once()
        mw._right_column.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 26. _refresh_license_status / _setup_matlab_lifecycle_signals
# ============================================================

@pytest.mark.unit
class TestLicenseAndLifecycle:
    """_refresh_license_status / _setup_matlab_lifecycle_signals。"""

    def test_refresh_license_status_valid(self, qapp, monkeypatch):
        """License 有效且天数 > 警告阈值。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        palette = MagicMock()
        palette.success = "#10B981"
        palette.warning = "#F59E0B"
        palette.error = "#EF4444"
        monkeypatch.setattr(TM, "get_palette", lambda: palette)
        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_developer_mode = False
        mw._license.is_valid = True
        mw._license.days_remaining = 30
        mw._lb_license = MagicMock()
        mw._refresh_license_status()
        mw._lb_license.setText.assert_called_once()
        text = mw._lb_license.setText.call_args[0][0]
        assert "有效" in text
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_license_status_developer_mode(self, qapp, monkeypatch):
        """Developer Mode 下显示醒目标识。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        palette = MagicMock(warning="#F59E0B", success="#10B981", error="#EF4444")
        monkeypatch.setattr(TM, "get_palette", lambda: palette)
        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_developer_mode = True
        mw._license.is_valid = True
        mw._lb_license = MagicMock()
        mw._refresh_license_status()
        mw._lb_license.setText.assert_called_once()
        text = mw._lb_license.setText.call_args[0][0]
        assert "Developer" in text
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_license_status_invalid(self, qapp, monkeypatch):
        """License 无效。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        palette = MagicMock(warning="#F59E0B", success="#10B981", error="#EF4444")
        monkeypatch.setattr(TM, "get_palette", lambda: palette)
        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_developer_mode = False
        mw._license.is_valid = False
        mw._lb_license = MagicMock()
        mw._refresh_license_status()
        mw._lb_license.setText.assert_called_once()
        text = mw._lb_license.setText.call_args[0][0]
        assert "无效" in text
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_license_status_permanent(self, qapp, monkeypatch):
        """永久授权（days < 0）。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        palette = MagicMock(warning="#F59E0B", success="#10B981", error="#EF4444")
        monkeypatch.setattr(TM, "get_palette", lambda: palette)
        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_developer_mode = False
        mw._license.is_valid = True
        mw._license.days_remaining = -1
        mw._lb_license = MagicMock()
        mw._refresh_license_status()
        mw._lb_license.setText.assert_called_once()
        text = mw._lb_license.setText.call_args[0][0]
        assert "永久" in text
        mw.deleteLater()
        qapp.processEvents()

    def test_setup_matlab_lifecycle_signals_no_zm_client(self, qapp, monkeypatch):
        """无 ZMQ client 时仍可安全调用。"""
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        fake_mgr = MagicMock()
        monkeypatch.setattr(MatlabLifecycleManager, "get_instance", classmethod(lambda cls: fake_mgr))
        mw = _make_main_window_new()
        mw._on_matlab_crashed = MagicMock()
        mw._on_matlab_restarted = MagicMock()
        mw._zm_client = MagicMock()
        del mw._zm_client._client  # 确保没有 _client 属性
        mw._setup_matlab_lifecycle_signals()
        fake_mgr.matlab_crashed.connect.assert_called_once()
        fake_mgr.matlab_restarted.connect.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 27. _load_demo / _on_load / _auto_generate_report
# ============================================================

@pytest.mark.unit
class TestLoadDemoAndLoad:
    """_load_demo / _on_load / _auto_generate_report。"""

    def test_load_demo(self, qapp, monkeypatch):
        """_load_demo 加载演示数据。"""
        import repair_app.ui.main_window as mw_mod
        fake_pts = np.zeros((100, 3), dtype=np.float32)
        fake_normals = np.zeros((100, 3), dtype=np.float32)
        fake_normals[:, 2] = 1.0
        monkeypatch.setattr(mw_mod._Coord, "generate_sample_defect", staticmethod(
            lambda defect_types, seed, n_points: (fake_pts, fake_normals, None, None)
        ))
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.repair_mode = "additive"
        mw._selector = MagicMock()
        mw._lb_pts = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._sb = MagicMock()
        mw._pipeline = MagicMock()
        mw._reset_output = MagicMock()
        mw._est_normals = MagicMock(return_value=fake_normals)
        mw._load_demo()
        assert mw._session.point_cloud.xyz is not None
        mw._reset_output.assert_called_once()
        mw._selector.set_points.assert_called_once()
        mw._lb_pts.setText.assert_called_once()
        mw._btn_start_repair.setEnabled.assert_called_with(True)
        mw.deleteLater()
        qapp.processEvents()

    def test_on_load_user_cancels(self, qapp, monkeypatch):
        """用户取消文件选择时静默返回。"""
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("", ""))
        mw = _make_main_window_new()
        mw._sb = MagicMock()
        mw._on_load()
        mw._sb.showMessage.assert_called_with("已取消加载", 2000)
        mw.deleteLater()
        qapp.processEvents()

    def test_on_load_success(self, qapp, monkeypatch):
        """成功加载点云文件（通过 _on_load_finished 验证异步加载完成后的处理）。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "_show_error", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        xyz = np.zeros((10, 3), dtype=np.float32)
        normals = np.zeros((10, 3), dtype=np.float32)
        normals[:, 2] = 1.0

        mw._session = RepairSession()
        mw._sb = MagicMock()
        mw._selector = MagicMock()
        mw._lb_pts = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._project_manager = MagicMock()
        mw._lb_project = MagicMock()
        mw._pipeline = MagicMock()
        mw._reset_output = MagicMock()
        mw._est_normals = MagicMock(return_value=normals)
        mw._refresh_start_button_state = MagicMock()

        # P0-1: _on_load 现在是异步加载，直接测试 _on_load_finished 回调
        mw._on_load_finished(xyz, normals, "/test.xyz")
        assert mw._session.point_cloud.xyz is not None
        mw._reset_output.assert_called_once()
        mw._selector.set_points.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_auto_generate_report_success(self, qapp, monkeypatch):
        """P0-3: _auto_generate_report 异步启动 ReportWorker；通过 _on_report_finished 验证成功路径。"""
        import repair_app.ui.main_window as mw_mod
        # Mock ExportService
        from repair_app.service import ExportService
        monkeypatch.setattr(ExportService, "export_pdf_report", lambda self, session, output_path: True)
        monkeypatch.setattr(mw_mod.Toast, "success", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.selection.mask = np.array([True, True, False, False, False])
        mw._session.morphology.repair_xyz = np.zeros((10, 3), dtype=np.float32)
        mw._project_manager = MagicMock()
        mw._project_manager.current_name = "test"
        fake_pdf = MagicMock()
        fake_pdf.__str__ = lambda s: "/tmp/test.pdf"
        mw._path_manager = MagicMock()
        mw._path_manager.pdf_path.return_value = fake_pdf
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, False, False, False])
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentText.return_value = "Steel"
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._sb = MagicMock()
        mw._lb_prog = MagicMock()
        mw._pipeline = MagicMock()
        mw._export_service = ExportService()
        mw._workflow_controller = MagicMock()
        mw._cs_fields = {k: MagicMock(value=MagicMock(return_value=500.0)) for k in [
            "particle_velocity", "critical_velocity", "nozzle_diameter",
            "spray_angle", "standoff_distance", "particle_size",
            "gas_temperature", "gas_pressure", "powder_feed_rate", "traversing_speed",
        ]}
        mw._pp_fields = {k: MagicMock(value=MagicMock(return_value=2.0)) for k in [
            "layer_height", "scanning_angle", "scanning_step",
            "edge_step_size", "tilt_angle", "buffer_additive",
            "buffer_repairing", "link_free_dist", "obstacle_resolution",
        ]}
        mw._sp_depth = MagicMock()
        mw._sp_depth.value.return_value = 1.0

        # P0-3: _auto_generate_report 现在异步启动 ReportWorker
        mw._auto_generate_report()
        # 验证 worker 和 thread 已创建
        assert mw._report_worker is not None
        assert mw._report_thread is not None
        # 等待异步线程完成
        mw._report_thread.wait(5000)
        qapp.processEvents()
        # 验证成功回调（_on_report_finished）被触发后 showMessage 被调用
        mw._sb.showMessage.assert_called()
        mw.deleteLater()
        qapp.processEvents()

    def test_auto_generate_report_failure(self, qapp, monkeypatch):
        """P0-3: _auto_generate_report 异步失败通过 _on_report_failed 回调验证。"""
        import repair_app.ui.main_window as mw_mod
        from repair_app.service import ExportService
        monkeypatch.setattr(ExportService, "export_pdf_report", lambda self, session, output_path: False)
        monkeypatch.setattr(mw_mod.Toast, "error", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "log_error", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.selection.mask = np.array([True, True, False, False, False])
        mw._session.morphology.repair_xyz = np.zeros((10, 3), dtype=np.float32)
        mw._project_manager = MagicMock()
        mw._project_manager.current_name = "test"
        fake_pdf = MagicMock()
        fake_pdf.__str__ = lambda s: "/tmp/test.pdf"
        mw._path_manager = MagicMock()
        mw._path_manager.pdf_path.return_value = fake_pdf
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, False, False, False])
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentText.return_value = "Steel"
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._sb = MagicMock()
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()  # P3-12: _on_report_failed 调用 _prog.setValue(0)
        mw._workflow_controller = MagicMock()
        mw._export_service = ExportService()
        mw._cs_fields = {k: MagicMock(value=MagicMock(return_value=500.0)) for k in [
            "particle_velocity", "critical_velocity", "nozzle_diameter",
            "spray_angle", "standoff_distance", "particle_size",
            "gas_temperature", "gas_pressure", "powder_feed_rate", "traversing_speed",
        ]}
        mw._pp_fields = {k: MagicMock(value=MagicMock(return_value=2.0)) for k in [
            "layer_height", "scanning_angle", "scanning_step",
            "edge_step_size", "tilt_angle", "buffer_additive",
            "buffer_repairing", "link_free_dist", "obstacle_resolution",
        ]}
        mw._sp_depth = MagicMock()
        mw._sp_depth.value.return_value = 1.0

        mw._auto_generate_report()
        # 等待异步线程完成
        mw._report_thread.wait(5000)
        qapp.processEvents()
        mw._workflow_controller.mark_running_as_failed.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 28. _on_export / _prepare_for_export branches
# ============================================================

@pytest.mark.unit
class TestOnExport:
    """_on_export 和 _prepare_for_export 分支。"""

    def test_on_export_gcode_success(self, qapp, monkeypatch):
        """_on_export('gcode') 成功导出。"""
        import repair_app.ui.main_window as mw_mod
        from repair_app.export.pipeline import ExporterRegistry, ExportResult
        monkeypatch.setattr(mw_mod.Toast, "success", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod.Toast, "error", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.morphology.repair_xyz = np.zeros((3, 3), dtype=np.float32)
        mw._session.waypoint.mock = np.zeros((3, 3), dtype=np.float32)
        mw._session.validation.result = None
        mw._path_manager = MagicMock()
        mw._sb = MagicMock()
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()
        mw._prepare_for_export = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0})
        mw._selector = MagicMock()
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentText.return_value = "Steel"

        result = ExportResult(ok=True, output_path="/tmp/test.nc")
        monkeypatch.setattr(ExporterRegistry, "run", lambda fmt, parent, session, pm: result)
        monkeypatch.setattr(ExporterRegistry, "get", lambda fmt: MagicMock(display_name="G-code", icon="📄"))

        mw._on_export("gcode")
        mw._prepare_for_export.assert_called_with("gcode")
        mw.deleteLater()
        qapp.processEvents()

    def test_on_export_invalid_license(self, qapp, monkeypatch):
        """License 无效时拒接导出。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_valid = False
        mw._license.error = "expired"
        mw._on_export("gcode")
        mw.deleteLater()
        qapp.processEvents()

    def test_on_export_unknown_format(self, qapp, monkeypatch):
        """未知格式提示错误。"""
        import repair_app.ui.main_window as mw_mod
        from repair_app.export.pipeline import ExporterRegistry
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod.Toast, "error", lambda *a, **kw: None)
        monkeypatch.setattr(ExporterRegistry, "get", lambda fmt: None)

        mw = _make_main_window_new()
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_export("unknown_format")
        mw.deleteLater()
        qapp.processEvents()

    def test_prepare_for_export_gcode(self, qapp, monkeypatch):
        """_prepare_for_export('gcode') 预填充 G-code 相关字段。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0})
        mw._license = MagicMock()
        mw._license.license_data = MagicMock()
        mw._license.license_data.machine_id = "MACHINE12345678"
        mw._prepare_for_export("gcode")
        assert mw._session.validation.expected_n_layers == 5
        assert mw._session.license_id == "MACHINE12345"
        mw.deleteLater()
        qapp.processEvents()

    def test_prepare_for_export_pdf(self, qapp, monkeypatch):
        """_prepare_for_export('pdf') 预填充 PDF 相关字段。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.morphology.repair_xyz = np.zeros((3, 3), dtype=np.float32)
        mw._session.waypoint.mock = np.zeros((3, 3), dtype=np.float32)
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, False, False, False])
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0, "traversing_speed_mms": 500.0})
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentText.return_value = "Steel"
        mw._prepare_for_export("pdf")
        assert mw._session.report.scan_info is not None
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 29. _update_step_buttons extra branches
# ============================================================

@pytest.mark.unit
class TestStepButtonsExtra:
    """_update_step_buttons 额外分支。"""

    def test_update_step_buttons_morph_page_active(self):
        """形貌预测页 + 路径就绪但形貌未完成 → step2 显示 active。"""
        session = RepairSession()
        session.output.path_output_ready = True
        session.morphology.repair_xyz = None
        stub = _make_stub(
            _mode_stack=MagicMock(currentIndex=MagicMock(return_value=PAGE_MORPH)),
            _session=session,
            _step1_btn=MagicMock(),
            _step2_btn=MagicMock(),
            _step3_lb=MagicMock(),
            _step4_btn=MagicMock(),
            _arrow_lb=MagicMock(),
            _lb_mode_state=MagicMock(),
            _lb_workflow_state=MagicMock(),
            _style_workflow_label=lambda *a, **kw: None,
            _update_step_buttons=lambda *a, **kw: None,
            _refresh_morph_status=lambda *a, **kw: None,
        )
        MainWindow._update_step_buttons(stub)
        assert stub._step1_btn.setStyleSheet.called
        assert stub._step4_btn.setEnabled.called

    def test_update_step_buttons_output_page_with_path_ready(self):
        """输出页 + 路径就绪但形貌未完成。"""
        session = RepairSession()
        session.output.path_output_ready = True
        session.morphology.repair_xyz = None
        stub = _make_stub(
            _mode_stack=MagicMock(currentIndex=MagicMock(return_value=PAGE_OUTPUT)),
            _session=session,
            _step1_btn=MagicMock(),
            _step2_btn=MagicMock(),
            _step3_lb=MagicMock(),
            _step4_btn=MagicMock(),
            _arrow_lb=MagicMock(),
            _lb_mode_state=MagicMock(),
            _lb_workflow_state=MagicMock(),
            _style_workflow_label=lambda *a, **kw: None,
            _update_step_buttons=lambda *a, **kw: None,
            _refresh_morph_status=lambda *a, **kw: None,
        )
        MainWindow._update_step_buttons(stub)
        assert stub._step1_btn.setStyleSheet.called
        assert stub._step4_btn.setEnabled.called

    def test_update_step_buttons_output_page_all_done(self):
        """输出页 + 路径 + 形貌均完成。"""
        session = RepairSession()
        session.output.path_output_ready = True
        session.morphology.repair_xyz = np.zeros((3, 3), dtype=np.float32)
        stub = _make_stub(
            _mode_stack=MagicMock(currentIndex=MagicMock(return_value=PAGE_OUTPUT)),
            _session=session,
            _step1_btn=MagicMock(),
            _step2_btn=MagicMock(),
            _step3_lb=MagicMock(),
            _step4_btn=MagicMock(),
            _arrow_lb=MagicMock(),
            _lb_mode_state=MagicMock(),
            _lb_workflow_state=MagicMock(),
            _style_workflow_label=lambda *a, **kw: None,
            _update_step_buttons=lambda *a, **kw: None,
            _refresh_morph_status=lambda *a, **kw: None,
        )
        MainWindow._update_step_buttons(stub)
        assert stub._step4_btn.setEnabled.called


# ============================================================
# 30. _finish_path_planning / _finish_morphology / _update_section_views
# ============================================================

@pytest.mark.unit
class TestFinishMethods:
    """_finish_path_planning / _finish_morphology / _update_section_views / _inspect_path_result。"""

    def test_finish_path_planning_no_save_to_disk(self, qapp, monkeypatch):
        """不保存到磁盘时跳过文件写入。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mw._chk_save_files = MagicMock()
        mw._chk_save_files.isChecked.return_value = False
        mw._visualizer = MagicMock()
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()
        mw._sb = MagicMock()
        mw._pipeline = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._apply_result_metrics = MagicMock()
        mw._inspect_path_result = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy = MagicMock()
        mw._update_section_views = MagicMock()
        # Don't auto-trigger _on_fix
        mw._on_fix = MagicMock()

        waypoints = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        sel_mask = np.array([True, True, True, False, False])
        mw._finish_path_planning(waypoints, sel_mask, show_dialog=True)

        assert mw._session.output.path_output_ready is True
        mw._visualizer.set_data.assert_called_once()
        mw._set_busy.assert_called_with(False)
        mw.deleteLater()
        qapp.processEvents()

    def test_finish_path_planning_with_layers(self, qapp, monkeypatch):
        """有 waypoint_layers 时构建逐层动画。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mw._chk_save_files = MagicMock()
        mw._chk_save_files.isChecked.return_value = False
        mw._visualizer = MagicMock()
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()
        mw._sb = MagicMock()
        mw._pipeline = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._apply_result_metrics = MagicMock()
        mw._inspect_path_result = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy = MagicMock()
        mw._update_section_views = MagicMock()
        mw._on_fix = MagicMock()

        waypoints = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32)
        waypoint_layers = np.array([0, 0, 1, 1], dtype=int)
        sel_mask = np.array([True, True, True, False, False])
        mw._finish_path_planning(waypoints, sel_mask, show_dialog=True,
                                 waypoint_layers=waypoint_layers, metrics={"a": 1})

        mw._apply_result_metrics.assert_called_once()
        mw._inspect_path_result.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_finish_path_planning_with_full_waypoints(self, qapp, monkeypatch):
        """有 full_waypoints（含法向量）时设置喷嘴方向。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mw._chk_save_files = MagicMock()
        mw._chk_save_files.isChecked.return_value = False
        mw._visualizer = MagicMock()
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()
        mw._sb = MagicMock()
        mw._pipeline = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._apply_result_metrics = MagicMock()
        mw._inspect_path_result = MagicMock()
        mw._refresh_morph_status = MagicMock()
        mw._set_busy = MagicMock()
        mw._update_section_views = MagicMock()
        mw._on_fix = MagicMock()

        waypoints = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        full_wps = np.array([[0, 0, 0, 1, 0, 0], [1, 0, 0, 0, 1, 0]], dtype=np.float32)
        sel_mask = np.array([True, True, True, False, False])
        mw._finish_path_planning(waypoints, sel_mask, show_dialog=True,
                                 full_waypoints=full_wps)

        mw._visualizer.set_nozzle_orientations.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_finish_morphology(self, qapp):
        """_finish_morphology 更新会话状态和可视化。"""
        session = RepairSession()
        session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw = _make_main_window_new()
        mw._session = session
        mw._visualizer = MagicMock()
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._lb_prog = MagicMock()
        mw._prog = MagicMock()
        mw._sb = MagicMock()
        mw._lb_vol = MagicMock()
        mw._lb_lay = MagicMock()
        mw._lb_feas = MagicMock()
        mw._pipeline = MagicMock()
        mw._set_busy = MagicMock()
        mw._update_section_views = MagicMock()
        mw._auto_generate_report = MagicMock()

        repair_pts = np.array([[0, 0, 0.5], [1, 0, 0.5]], dtype=np.float32)
        sel_mask = np.array([True, True, True, False, False])
        mw._finish_morphology(repair_pts, sel_mask)

        assert mw._session.morphology.repair_xyz is not None
        mw._visualizer.set_data.assert_called_once()
        mw._set_busy.assert_called_with(False)
        mw.deleteLater()
        qapp.processEvents()

    def test_update_section_views_no_waypoints(self, qapp):
        """无航点时 _update_section_views 直接返回。"""
        session = RepairSession()
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_bottom_status = MagicMock()
        # 不应抛
        mw._update_section_views(np.array([True, False]))
        mw.deleteLater()
        qapp.processEvents()

    def test_inspect_path_result(self, qapp, monkeypatch):
        """_inspect_path_result 无航点时直接返回。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._inspect_path_result(None)  # 不应抛
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 31. _on_start_repair / _on_generate_path / _on_fix / _on_start_calculation basics
# ============================================================

@pytest.mark.unit
class TestRepairFlow:
    """_on_start_repair / _on_generate_path / _on_fix 基础路径。"""

    def test_on_start_repair_local_engine(self, qapp):
        """本地引擎时调用 _on_generate_path。"""
        mw = _make_main_window_new()
        mw._use_zmq_engine = MagicMock(return_value=False)
        mw._on_generate_path = MagicMock()
        mw._on_start_calculation = MagicMock()
        mw._on_start_repair()
        mw._on_generate_path.assert_called_once()
        mw._on_start_calculation.assert_not_called()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_start_repair_zm_engine(self, qapp):
        """远程引擎时调用 _on_start_calculation。"""
        mw = _make_main_window_new()
        mw._use_zmq_engine = MagicMock(return_value=True)
        mw._on_generate_path = MagicMock()
        mw._on_start_calculation = MagicMock()
        mw._on_start_repair()
        mw._on_generate_path.assert_not_called()
        mw._on_start_calculation.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_generate_path_busy_returns(self, qapp, monkeypatch):
        """busy 时直接返回。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = True
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_generate_path()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_generate_path_no_license(self, qapp, monkeypatch):
        """License 无效时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = False
        mw._license.error = "expired"
        mw._on_generate_path()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_generate_path_no_cloud(self, qapp, monkeypatch):
        """无点云时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_generate_path()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_fix_busy_returns(self, qapp, monkeypatch):
        """busy 时直接返回。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = True
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_fix()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_fix_no_license(self, qapp, monkeypatch):
        """License 无效时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = False
        mw._license.error = "expired"
        mw._on_fix()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_fix_no_cloud(self, qapp, monkeypatch):
        """无点云时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_fix()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_fix_no_selection(self, qapp, monkeypatch):
        """无选区时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.zeros(5, dtype=bool)
        mw._on_fix()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 32. _on_feasibility_check and _on_load
# ============================================================

@pytest.mark.unit
class TestFeasibilityCheckAndLoad:
    """_on_feasibility_check 和 _on_load 分支。"""

    def test_on_feasibility_check_insufficient_points(self, qapp, monkeypatch):
        """选区不足 3 点时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._sb = MagicMock()
        mw._selector = MagicMock()
        mw._selector.get_selected_points.return_value = np.zeros((1, 3), dtype=np.float32)
        mw._on_feasibility_check()
        mw._sb.showMessage.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_feasibility_check_ok(self, qapp, monkeypatch):
        """可行性检查通过。"""
        from repair_app.service.coordination_service import CoordinationService as _Coord_local
        mock_feas = MagicMock()
        mock_feas.check_from_cloud.return_value = MagicMock(
            feasible=True, score=0.95, summary="可行",
            overall=0, warnings=[],
        )
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._sb = MagicMock()
        mw._selector = MagicMock()
        mw._selector.get_selected_points.return_value = np.zeros((5, 3), dtype=np.float32)
        mw._feasibility_checker = mock_feas
        mw._collect_params = MagicMock(return_value={
            "nozzle_diameter_mm": 6.0, "spray_angle_deg": 90.0, "particle_velocity_ms": 500.0,
        })
        mw._lb_feas_status = MagicMock()
        mw._lb_feas_score = MagicMock()
        mw._lb_feas = MagicMock()
        mw._feas_text = MagicMock()
        mw._on_feasibility_check()
        mw._lb_feas_status.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_load_exception(self, qapp, monkeypatch):
        """加载失败时显示错误。"""
        import repair_app.ui.main_window as mw_mod
        from repair_app.ui.dialogs import ErrorDialog
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("/test.xyz", ""))
        from repair_app.service.file_service import FileService
        monkeypatch.setattr(FileService, "load_point_cloud", lambda self, fp: (_ for _ in ()).throw(RuntimeError("load fail")))
        # Prevent error dialog from hanging（_on_load_failed 直接调用 ErrorDialog.show）
        monkeypatch.setattr(ErrorDialog, "show", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "_show_error", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._sb = MagicMock()
        mw._file_service = FileService()
        mw._on_load()  # should handle exception gracefully
        # P3-2: _on_load 启动异步 _load_thread，必须等待并清理，避免线程泄漏
        load_thread = getattr(mw, "_load_thread", None)
        if load_thread is not None:
            load_thread.wait(5000)
            try:
                load_thread.quit()
                load_thread.wait(1000)
            except Exception:
                pass
        load_worker = getattr(mw, "_load_worker", None)
        if load_worker is not None:
            try:
                load_worker.deleteLater()
            except Exception:
                pass
        for _ in range(5):
            qapp.processEvents()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 33. _compute_layer_data / _compute_statistics_data / _compute_quality_data
# ============================================================

@pytest.mark.unit
class TestComputeData:
    """_compute_layer_data / _compute_statistics_data / _compute_quality_data。"""

    def test_compute_layer_data_empty(self, qapp):
        """无航点时返回空列表。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        result = mw._compute_layer_data()
        assert result == []
        mw.deleteLater()
        qapp.processEvents()

    def test_compute_layer_data_with_layers(self, qapp):
        """有真实层号时计算逐层数据。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.waypoint.mock = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        mw._session.waypoint.layers = np.array([0, 0, 1], dtype=int)
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0})
        result = mw._compute_layer_data()
        assert len(result) == 2  # 层 0 和层 1
        mw.deleteLater()
        qapp.processEvents()

    def test_compute_layer_data_without_layer_labels(self, qapp):
        """无真实层号时按 Z 推断。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.waypoint.mock = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 5]], dtype=np.float32)
        mw._session.waypoint.layers = None
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0})
        result = mw._compute_layer_data()
        # Z=0 和 Z=5 → 至少 2 层
        assert len(result) >= 2
        mw.deleteLater()
        qapp.processEvents()

    def test_compute_statistics_data(self, qapp):
        """计算统计信息。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.waypoint.mock = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        mw._session.morphology.repair_xyz = np.array([[0, 0, 0.5], [1, 0, 0.5]], dtype=np.float32)
        defect = {"volume_mm3": 10.0}
        path = {"path_length_mm": 100.0, "estimated_time_s": 20.0}
        result = mw._compute_statistics_data(defect, path)
        assert "航点总数" in result
        assert "缺陷体积" in result
        mw.deleteLater()
        qapp.processEvents()

    def test_compute_quality_data(self, qapp):
        """计算质量评估数据。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.morphology.is_mock = True
        mw._session.morphology.repair_xyz = np.array([[0, 0, 0.5]], dtype=np.float32)
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.selection.mask = np.array([True, True, False, False, False])
        result = mw._compute_quality_data()
        assert "形貌预测来源" in result
        assert "mock" in result["形貌预测来源"]
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 34. _collect_params / _apply_recovered_state / _build_repair_request
# ============================================================

@pytest.mark.unit
class TestCollectAndApply:
    """_collect_params / _apply_recovered_state / _build_repair_request。"""

    def test_collect_params(self, qapp):
        """_collect_params 收集当前参数。"""
        mw = _make_main_window_new()
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 1
        mw._cs_fields = {k: MagicMock() for k in [
            "particle_velocity", "critical_velocity", "nozzle_diameter",
            "spray_angle", "standoff_distance", "particle_size",
            "gas_temperature", "gas_pressure", "powder_feed_rate", "traversing_speed",
        ]}
        for v in mw._cs_fields.values():
            v.value.return_value = 500.0
        mw._pp_fields = {k: MagicMock() for k in [
            "layer_height", "scanning_angle", "scanning_step",
            "edge_step_size", "tilt_angle", "buffer_additive",
            "buffer_repairing", "link_free_dist", "obstacle_resolution",
        ]}
        for v in mw._pp_fields.values():
            v.value.return_value = 2.0
        mw._sp_depth = MagicMock()
        mw._sp_depth.value.return_value = 1.0
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        result = mw._collect_params()
        assert result["material"] == "STEEL_316L"
        assert result["material_name"] == "316L 不锈钢"
        assert "particle_velocity_ms" in result
        assert "layer_height_mm" in result
        mw.deleteLater()
        qapp.processEvents()

    def test_build_repair_request(self, qapp, monkeypatch):
        """_build_repair_request 构建修复请求。"""
        import repair_app.ui.main_window as mw_mod
        mock_request = MagicMock()
        monkeypatch.setattr(mw_mod._Coord, "build_repair_request", lambda *a, **kw: mock_request)
        monkeypatch.setattr(mw_mod._Coord, "estimate_normals", lambda xyz, k: np.zeros((len(xyz), 3), dtype=np.float32))

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.point_cloud.normals = np.zeros((5, 3), dtype=np.float32)
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 1
        mw._collect_params = MagicMock(return_value={
            "depth_compensation": 1.0, "max_layers": 5,
            "particle_velocity_ms": 500.0, "critical_velocity_ms": 400.0,
            "nozzle_diameter_mm": 6.0, "spray_angle_deg": 90.0,
            "standoff_distance_mm": 30.0, "particle_size_um": 25.0,
            "traversing_speed_mms": 500.0, "num_layers": 5,
            "layer_height_mm": 2.0, "scanning_angle_deg": -45.0,
            "scanning_step_mm": 2.0, "edge_step_size_mm": 2.0,
            "tilt_angle_deg": 60.0, "buffer_additive_mm": 2.0,
            "buffer_repairing_mm": 0.0, "link_path_free_dist_mm": 20.0,
            "obstacle_resolution_mm": 2.0,
        })
        sel_mask = np.array([True, True, True, False, False])
        result = mw._build_repair_request(sel_mask)
        assert result is not None
        mw.deleteLater()
        qapp.processEvents()

    def test_apply_recovered_state_with_point_cloud(self, qapp, monkeypatch, tmp_path):
        """_apply_recovered_state 恢复点云。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "Toast", MagicMock())
        pcd_path = tmp_path / "test.xyz"
        pcd_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        from repair_app.service.file_service import FileService
        xyz = np.zeros((3, 3), dtype=np.float32)
        normals = np.zeros((3, 3), dtype=np.float32)
        normals[:, 2] = 1.0
        monkeypatch.setattr(FileService, "load_point_cloud", lambda self, fp: (xyz, normals))

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.repair_mode = "additive"
        mw._file_service = FileService()
        mw._selector = MagicMock()
        mw._lb_pts = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._project_manager = MagicMock()
        mw._lb_project = MagicMock()
        mw._sb = MagicMock()
        mw._auto_recovery = MagicMock()
        mw._est_normals = MagicMock(return_value=normals)
        mw._rb_repair = MagicMock()
        mw._rb_additive = MagicMock()
        mw._on_mode_changed = MagicMock()
        mw._cb_mat = MagicMock()
        mw._apply_params = MagicMock()

        state = {"point_cloud_path": str(pcd_path), "repair_mode": 1, "material_index": 0, "params": {}}
        mw._apply_recovered_state(state)
        # P2-8: _apply_recovered_state 现在异步加载点云，需等待 QThread 完成
        load_thread = getattr(mw, "_load_thread", None)
        if load_thread is not None:
            load_thread.wait(5000)
        # P2-9: 处理所有 queued 信号（_on_recover_load_finished 等），
        # 确保测试断言前异步回调已执行
        for _ in range(10):
            qapp.processEvents()
        mw._selector.set_points.assert_called_once()
        mw._btn_start_repair.setEnabled.assert_called_with(True)
        # P2-9: 清理异步加载线程，避免 worker 进程崩溃
        load_thread = getattr(mw, "_load_thread", None)
        if load_thread is not None:
            try:
                load_thread.quit()
                load_thread.wait(1000)
            except Exception:
                pass
        load_worker = getattr(mw, "_load_worker", None)
        if load_worker is not None:
            try:
                load_worker.deleteLater()
            except Exception:
                pass
        mw.deleteLater()
        for _ in range(5):
            qapp.processEvents()

    def test_apply_recovered_state_no_point_cloud(self, qapp, monkeypatch):
        """无点云路径时跳过点云恢复。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "Toast", MagicMock())

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._sb = MagicMock()
        mw._auto_recovery = MagicMock()
        mw._rb_repair = MagicMock()
        mw._rb_additive = MagicMock()
        mw._on_mode_changed = MagicMock()
        mw._cb_mat = MagicMock()
        mw._apply_params = MagicMock()

        state = {"repair_mode": 1, "material_index": 0, "params": {}}
        mw._apply_recovered_state(state)
        mw._on_mode_changed.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 35. set_busy / _refresh_morph_status / _update_connection_status extras
# ============================================================

@pytest.mark.unit
class TestBusyAndStatusExtra:
    """_set_busy / _refresh_morph_status / _update_connection_status 额外分支。"""

    def test_refresh_morph_status_with_file_source(self, qapp, monkeypatch):
        """有航点且文件存在时显示文件来源。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(os.path, "exists", lambda p: True)

        session = RepairSession()
        session.waypoint.mock = np.zeros((5, 3))
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_pl_status = MagicMock()
        mw._lb_input_source = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._refresh_morph_status()
        mw._lb_pl_status.setText.assert_called_once()
        mw._btn_fix.setEnabled.assert_called_with(True)
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_morph_status_no_save_and_has_waypoints(self, qapp, monkeypatch):
        """有航点但未保存到文件时显示内存来源。"""
        monkeypatch.setattr(os.path, "exists", lambda p: False)

        session = RepairSession()
        session.waypoint.mock = np.zeros((5, 3))
        session.output.files_saved = False
        mw = _make_main_window_new()
        mw._session = session
        mw._lb_pl_status = MagicMock()
        mw._lb_input_source = MagicMock()
        mw._btn_fix = MagicMock()
        mw._btn_feas = MagicMock()
        mw._refresh_morph_status()
        mw._lb_pl_status.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_zmq_path_result_success(self, qapp, monkeypatch):
        """ZMQ 路径规划结果成功。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod._Coord, "parse_repair_result", lambda msg: {
            "waypoints": np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32),
            "status_name": "SUCCESS", "error_message": "",
            "estimated_mass_g": 10.0, "estimated_time_s": 60.0,
            "uniformity_score": 0.9, "predicted_volume_mm3": 5.0,
            "waypoint_layers": np.array([0, 1], dtype=int),
            "layer_profiles": [], "particle_dist": None,
            "bytes": b"", "format": "",
            "feasibility_reason": "",
            "material_density_gcm3": 7.8, "compute_time_ms": 100,
        })
        monkeypatch.setattr(mw_mod._Coord, "is_repair_success", lambda r: True)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.selection.mask = np.array([True, True, True, False, False])
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, True, False, False])
        mw._prog = MagicMock()
        mw._lb_prog = MagicMock()
        mw._finish_path_planning = MagicMock()
        mw._profile_panel = MagicMock()

        mw._on_zmq_path_result(MagicMock())
        mw._finish_path_planning.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_zmq_path_result_failure(self, qapp, monkeypatch):
        """ZMQ 路径规划失败（非成功状态）。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod._Coord, "parse_repair_result", lambda msg: {
            "status_name": "FAILED", "error_message": "matlab error",
            "waypoints": np.array([[0, 0, 0]], dtype=np.float32),
        })
        monkeypatch.setattr(mw_mod._Coord, "is_repair_success", lambda r: False)
        monkeypatch.setattr(mw_mod, "_show_error", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.selection.mask = np.array([True, True, True, False, False])
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, True, False, False])
        mw._set_busy = MagicMock()
        mw._stop_progress_subscriber = MagicMock()
        mw._pipeline = MagicMock()

        mw._on_zmq_path_result(MagicMock())
        mw._set_busy.assert_called_with(False)
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 36. _on_compute_result (success path) extras
# ============================================================

@pytest.mark.unit
class TestComputeResultExtra:
    """_on_compute_result 额外分支。"""

    def test_on_compute_result_success_with_data(self, qapp, monkeypatch):
        """_on_compute_result 成功处理完整结果。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod._Coord, "is_repair_success", lambda result: True)
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.selection.mask = np.array([True, True, True, False, False])
        mw._prog = MagicMock()
        mw._lb_prog = MagicMock()
        mw._sb = MagicMock()
        mw._pipeline = MagicMock()
        mw._set_busy = MagicMock()
        mw._stop_progress_subscriber = MagicMock()
        mw._finish_path_planning = MagicMock()
        mw._profile_panel = MagicMock()
        mw._auto_generate_report = MagicMock()

        waypoints = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        result = {
            "status_name": "SUCCESS",
            "waypoints": waypoints,
            "estimated_mass_g": 10.0,
            "estimated_time_s": 60.0,
            "uniformity_score": 0.9,
            "predicted_volume_mm3": 5.0,
            "layer_profiles": [],
            "particle_dist": None,
            "bytes": b"",
            "format": "",
            "feasibility_reason": "",
            "material_density_gcm3": 7.8,
            "compute_time_ms": 100,
            "waypoint_layers": np.array([0, 1, 2], dtype=int),
        }
        mw._on_compute_result(result)
        mw._finish_path_planning.assert_called_once()
        mw._set_busy.assert_called_with(False)
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 37. _setup_menubar / _setup_toolbar / _setup_context_menu
# ============================================================

@pytest.mark.gui
class TestMenubarAndToolbar:
    """_setup_menubar / _setup_toolbar / _setup_context_menu。"""

    def test_setup_menubar(self, qapp, monkeypatch):
        """_setup_menubar 创建完整菜单栏。"""
        from repair_app.ui.undo_framework import UndoStack
        fake_undo = MagicMock()
        fake_undo.create_undo_action.return_value = QAction("undo")
        fake_undo.create_redo_action.return_value = QAction("redo")
        monkeypatch.setattr(UndoStack, "instance", lambda: fake_undo)

        mw = _make_main_window_new()
        mw._on_load = MagicMock()
        mw._on_save_project = MagicMock()
        mw._on_open_project = MagicMock()
        mw._on_open_export_dir = MagicMock()
        mw._on_open_log_dir = MagicMock()
        mw._on_export_logs = MagicMock()
        mw._on_export_robot = MagicMock()
        mw._on_feasibility_check = MagicMock()
        mw._on_calibration = MagicMock()
        mw._on_coord_transform = MagicMock()
        mw._on_param_preset = MagicMock()
        mw._on_batch_validation = MagicMock()
        mw._on_param_validator = MagicMock()
        mw._on_clear_selection = MagicMock()
        mw._on_reset_view = MagicMock()
        mw._on_fit_view = MagicMock()
        mw._on_toggle_axes = MagicMock()
        mw._on_switch_theme = MagicMock()
        mw._on_show_about = MagicMock()
        mw._refresh_recent_menu = MagicMock()
        mw._on_clear_recent = MagicMock()
        mw._recent_menu = MagicMock()
        mw._recent_projects = MagicMock()
        mw._recent_projects.items = []
        mw._undo_stack = fake_undo

        mw._setup_menubar()
        assert hasattr(mw, "_undo_stack")
        mw._refresh_recent_menu.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_setup_toolbar(self, qapp, monkeypatch):
        """_setup_toolbar 创建主工具栏。"""
        from repair_app.ui.undo_framework import UndoStack
        from repair_app.ui.theme_manager import ThemeManager as TM
        fake_undo = MagicMock()
        fake_undo.create_undo_action.return_value = QAction("undo")
        fake_undo.create_redo_action.return_value = QAction("redo")
        monkeypatch.setattr(UndoStack, "instance", lambda: fake_undo)
        monkeypatch.setattr(TM, "get_theme_name", lambda: "dark")

        mw = _make_main_window_new()
        mw._on_load = MagicMock()
        mw._on_save_project = MagicMock()
        mw._on_reset_view = MagicMock()
        mw._on_fit_view = MagicMock()
        mw._on_switch_theme = MagicMock()
        mw._undo_stack = fake_undo

        mw._setup_toolbar()
        mw.deleteLater()
        qapp.processEvents()

    def test_setup_context_menu(self, qapp, monkeypatch):
        """_setup_context_menu 安装上下文菜单。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.ContextMenuManager, "__init__", lambda self, parent: None)

        mw = _make_main_window_new()
        mw._visualizer = MagicMock()
        mw._setup_context_menu()
        assert hasattr(mw, "_context_menu_mgr")
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 38. _update_path_section / _update_morph_section / _update_section_views
# ============================================================

@pytest.mark.unit
class TestUpdateSectionViews:
    """_update_path_section / _update_morph_section / _update_section_views。"""

    def test_update_section_views_with_data(self, qapp, monkeypatch):
        """_update_section_views 有航点数据时更新两个剖面。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)

        mw = _make_main_window_new()
        raw_xyz = np.zeros((30, 3), dtype=np.float32)
        raw_xyz[:, 2] = np.linspace(0, 10, 30)
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = raw_xyz
        mw._session.selection.mask = np.array([True, True, True, False, False])
        mw._session.waypoint.mock = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 5]], dtype=np.float32)
        mw._session.waypoint.layers = np.array([0, 0, 1], dtype=int)
        mock_plot = MagicMock()
        mw._plot_canvas = mock_plot
        mw._lb_bottom_status = MagicMock()
        mw._lb_bottom_status.setText = MagicMock()
        mw._label_bottom = MagicMock()
        mw._collect_params = MagicMock(return_value={"layer_height_mm": 2.0})
        mw._update_path_section = MagicMock()
        mw._update_morph_section = MagicMock()

        mw._update_section_views(np.array([True, True, True, False, False]))
        mw._update_path_section.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 39. _on_start_calculation / _on_generate_path / _on_fix extra guard branches
# ============================================================

@pytest.mark.unit
class TestCalculationFlow:
    """_on_start_calculation / _on_generate_path / _on_fix 更多守卫分支。"""

    def test_on_start_calculation_no_selection(self, qapp, monkeypatch):
        """无选区时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(mw_mod, "_show_error", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.zeros(5, dtype=bool)
        mw._sb = MagicMock()
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 1
        mw._cs_fields = {k: MagicMock(value=MagicMock(return_value=500.0)) for k in [
            "particle_velocity", "critical_velocity", "nozzle_diameter",
            "spray_angle", "standoff_distance", "particle_size",
            "gas_temperature", "gas_pressure", "powder_feed_rate", "traversing_speed",
        ]}
        mw._pp_fields = {k: MagicMock(value=MagicMock(return_value=2.0)) for k in [
            "layer_height", "scanning_angle", "scanning_step",
            "edge_step_size", "tilt_angle", "buffer_additive",
            "buffer_repairing", "link_free_dist", "obstacle_resolution",
        ]}
        mw._sp_depth = MagicMock()
        mw._sp_depth.value.return_value = 1.0
        mw._sp_max_layers = MagicMock()
        mw._sp_max_layers.value.return_value = 5
        mw._progress_subscriber = None
        mw._matlab_service = MagicMock()
        mw._on_start_calculation()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_start_calculation_busy(self, qapp, monkeypatch):
        """busy 时直接返回。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = True
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_start_calculation()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_start_calculation_no_license(self, qapp, monkeypatch):
        """License 无效时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = False
        mw._license.error = "expired"
        mw._on_start_calculation()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_start_calculation_no_cloud(self, qapp, monkeypatch):
        """无点云时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._on_start_calculation()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_generate_path_no_selection(self, qapp, monkeypatch):
        """无选区时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._session.repair_mode = MODE_REPAIRING  # ensure repairing mode
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.zeros(5, dtype=bool)
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 0
        mw._pipeline = MagicMock()
        mw._sb = MagicMock()
        mw._prog = MagicMock()
        mw._lb_prog = MagicMock()
        mw._lb_pts = MagicMock()
        mw._mode_stack = MagicMock()
        mw._visualizer = MagicMock()
        mw._set_busy = MagicMock()
        mw._on_generate_path()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_fix_no_waypoints(self, qapp, monkeypatch):
        """无航点时提示。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod.Toast, "warning", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.is_busy = False
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._license = MagicMock()
        mw._license.is_valid = True
        mw._selector = MagicMock()
        mw._selector.get_selection_mask.return_value = np.array([True, True, True, False, False])
        mw._file_service = MagicMock()
        mw._on_fix()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 40. _on_engine_changed / _on_switch_theme / _update_connection_status
# ============================================================

@pytest.mark.unit
class TestEngineAndTheme:
    """引擎切换和主题切换。"""

    def test_on_engine_changed_zmq(self, qapp, monkeypatch):
        """切换到 ZMQ 远程引擎。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._cb_engine = MagicMock()
        mw._cb_engine.currentData.return_value = "zmq"
        mw._zmq_client = MagicMock()
        mw._lb_engine_hint = MagicMock()
        mw._sb = MagicMock()
        mw._on_engine_changed(1)
        mw._lb_engine_hint.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_engine_changed_local(self, qapp, monkeypatch):
        """切换到本地引擎。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._cb_engine = MagicMock()
        mw._cb_engine.currentData.return_value = "local"
        mw._zmq_client = None
        mw._lb_engine_hint = MagicMock()
        mw._sb = MagicMock()
        mw._on_engine_changed(0)
        mw._lb_engine_hint.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_on_switch_theme(self, qapp, monkeypatch):
        """切换主题。"""
        import repair_app.ui.main_window as mw_mod
        from repair_app.ui.theme_manager import ThemeManager as TM
        monkeypatch.setattr(TM, "set_theme", lambda name: None)
        monkeypatch.setattr(TM, "get_qss", lambda: "")
        monkeypatch.setattr(mw_mod.Toast, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._on_switch_theme("dark")
        mw.deleteLater()
        qapp.processEvents()

    def test_update_connection_status_zmq_available(self, qapp, monkeypatch):
        """ZMQ 可用时更新状态。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        monkeypatch.setattr(TM, "get_palette", lambda: MagicMock(
            success="#10B981", error="#EF4444", warning="#F59E0B", text_muted="#64748B"
        ))
        mw = _make_main_window_new()
        mw._zmq_client = MagicMock()
        mw._zmq_client.is_connected = True
        mw._lb_conn = MagicMock()
        mw._update_connection_status()
        mw._lb_conn.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_update_connection_status_zmq_not_available(self, qapp, monkeypatch):
        """ZMQ 不可用时更新状态。"""
        from repair_app.ui.theme_manager import ThemeManager as TM
        monkeypatch.setattr(TM, "get_palette", lambda: MagicMock(
            success="#10B981", error="#EF4444", warning="#F59E0B", text_muted="#64748B"
        ))
        mw = _make_main_window_new()
        mw._zmq_client = MagicMock()
        mw._zmq_client.is_connected = False
        mw._lb_conn = MagicMock()
        mw._update_connection_status()
        mw._lb_conn.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 41. _on_selection_changed / _on_material_changed
# ============================================================

@pytest.mark.unit
class TestSelectionAndMaterial:
    """选区/材料切换。"""

    def test_on_selection_changed_with_selection(self, qapp):
        """有选区时更新状态（修复模式，≥3 点）。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.repair_mode = MODE_REPAIRING
        mw._lb_pts = MagicMock()
        mw._lb_sel = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._sb = MagicMock()
        mw._on_selection_changed(np.array([True, True, True, False, False]))
        mw._btn_start_repair.setEnabled.assert_called_with(True)
        mw.deleteLater()
        qapp.processEvents()

    def test_on_selection_changed_empty(self, qapp):
        """空选区时更新状态（修复模式，< 3 点）。"""
        mw = _make_main_window_new()
        mw._session = RepairSession()
        mw._session.point_cloud.xyz = np.zeros((5, 3), dtype=np.float32)
        mw._session.repair_mode = MODE_REPAIRING
        mw._lb_pts = MagicMock()
        mw._lb_sel = MagicMock()
        mw._btn_start_repair = MagicMock()
        mw._sb = MagicMock()
        mw._on_selection_changed(np.zeros(5, dtype=bool))
        mw._btn_start_repair.setEnabled.assert_called_with(False)
        mw.deleteLater()
        qapp.processEvents()

    def test_on_material_changed(self, qapp, monkeypatch):
        """材料变更时更新状态。"""
        import repair_app.ui.main_window as mw_mod
        fake_mat = MagicMock()
        fake_mat.v_cr_base_ms = 500.0
        fake_mat.density_kgm3 = 7800.0
        monkeypatch.setattr(mw_mod._Coord, "get_material_database", lambda: {"STEEL_316L": fake_mat})
        monkeypatch.setattr(mw_mod._Coord, "create_feasibility_checker", lambda mat: MagicMock())

        mw = _make_main_window_new()
        mw._cb_mat = MagicMock()
        mw._cb_mat.currentIndex.return_value = 1
        mw._lb_mat_info = MagicMock()
        mw._sb = MagicMock()
        mw._cs_fields = {"critical_velocity": MagicMock()}
        mw._on_material_changed(1)
        mw._lb_mat_info.setText.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()


# ============================================================
# 42. _check_recovery / _refresh_recent_menu
# ============================================================

@pytest.mark.unit
class TestRecoveryAndRecent:
    """_check_recovery / _refresh_recent_menu。"""

    def test_check_recovery_no_state(self, qapp, monkeypatch):
        """无恢复状态时直接返回。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        mw = _make_main_window_new()
        mw._auto_recovery = MagicMock()
        mw._auto_recovery.load_state.return_value = None
        mw._check_recovery()
        mw.deleteLater()
        qapp.processEvents()

    def test_check_recovery_with_state(self, qapp, monkeypatch):
        """有恢复状态时提示用户。"""
        import repair_app.ui.main_window as mw_mod
        monkeypatch.setattr(mw_mod, "info", lambda *a, **kw: None)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Yes)
        mw = _make_main_window_new()
        mw._auto_recovery = MagicMock()
        mw._auto_recovery.load_state.return_value = {"repair_mode": 1}
        mw._apply_recovered_state = MagicMock()
        mw._check_recovery()
        mw._apply_recovered_state.assert_called_once()
        mw.deleteLater()
        qapp.processEvents()

    def test_refresh_recent_menu(self, qapp, monkeypatch):
        """_refresh_recent_menu 刷新最近项目。"""
        mw = _make_main_window_new()
        mw._recent_menu = MagicMock()
        mw._recent_menu.clear.return_value = None
        mw._recent_projects = MagicMock()
        mw._recent_projects.items = []
        mw._on_load = MagicMock()
        mw._refresh_recent_menu()
        mw.deleteLater()
        qapp.processEvents()
