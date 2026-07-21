"""test_crash_recovery.py — 崩溃恢复与异常恢复流程测试

被测对象:
    1. AutoRecovery (repair_app/software/project_manager.py:127)
       - __init__(path_manager) / save(state) / load() / has_pending_recovery / clear()
       - maybe_save(state, force=False) 定时保存
    2. install_crash_handler (repair_app/utils/crash_handler.py) 增强覆盖
       - 崩溃日志含完整 traceback
       - 崩溃日志含线程信息（线程名 + ident）
    3. MainWindow._check_recovery (repair_app/ui/main_window.py:3024)
       - 有恢复文件时触发恢复 / 无恢复文件时跳过

隔离策略:
    - PathManager 无 root= 参数，通过 CSAM_USER_DATA 环境变量 + monkeypatch
      将用户数据根目录重定向到 tmp_path，做到测试间完全隔离。
    - sys.excepthook 在 fixture 中保存/恢复，避免污染 pytest 自身异常处理。

运行:
    pytest -m "unit or regression" tests/test_crash_recovery.py -v
"""
from __future__ import annotations

import os
import sys
import time
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest

from repair_app.software.project_manager import (
    AutoRecovery,
    ProjectManager,
    AUTO_SAVE_INTERVAL_S,
    PROJECT_FILE_VERSION,
)
from repair_app.software.path_manager import PathManager
from repair_app.utils.crash_handler import install_crash_handler


# ============================================================
# MainWindow 可选导入（重 GUI，导入失败则跳过 _check_recovery 测试）
# ============================================================
try:
    from repair_app.ui.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    _HAS_MAINWINDOW = True
except Exception:  # pragma: no cover - 环境依赖
    MainWindow = None  # type: ignore[assignment]
    QMessageBox = None  # type: ignore[assignment]
    _HAS_MAINWINDOW = False


# ============================================================
# 共享 fixtures
# ============================================================
@pytest.fixture
def pm(tmp_path, monkeypatch):
    """隔离的 PathManager：根目录指向 tmp_path。

    PathManager.__init__ 不接受 root 参数，通过 CSAM_USER_DATA 环境变量
    让 _get_user_root() 返回临时目录。
    """
    monkeypatch.setenv("CSAM_USER_DATA", str(tmp_path))
    return PathManager()


@pytest.fixture
def recovery(pm):
    """干净的 AutoRecovery 实例（无残留快照）。"""
    ar = AutoRecovery(pm)
    ar.clear()
    return ar


@pytest.fixture
def restore_excepthook():
    """保存并恢复 sys.excepthook，避免污染 pytest 自身异常处理。"""
    original = sys.excepthook
    yield
    sys.excepthook = original


def _raise_and_capture(exc_type, *args):
    """抛出指定异常并返回 (exc_type, exc_value, exc_tb) 三元组。"""
    try:
        raise exc_type(*args)
    except exc_type:
        return sys.exc_info()


def _sample_state() -> dict:
    """构造一份与会话状态等价的字典。"""
    return {
        "point_cloud_path": "/data/sample.xyz",
        "repair_mode": 1,
        "material_index": 2,
        "params": {"layer_height": 0.5},
        "selection_summary": {"point_count": 1234, "volume_mm3": 5.6},
    }


# ============================================================
# 1. AutoRecovery — 构造与属性
# ============================================================
@pytest.mark.unit
class TestAutoRecoveryInit:
    """AutoRecovery 构造与基础属性。"""

    def test_init_with_explicit_path_manager(self, pm):
        ar = AutoRecovery(pm)
        assert ar.autosave_path == pm.auto_save_path("auto")
        assert ar.autosave_path.name == "auto.autosave"
        assert ar.autosave_path.parent == pm.recovery_dir

    def test_init_last_save_timestamp_starts_zero(self, pm):
        ar = AutoRecovery(pm)
        assert ar._last_save_ts == 0.0

    def test_init_falls_back_to_singleton(self, pm, monkeypatch):
        """path_manager=None 时使用 PathManager.get_instance()。"""
        monkeypatch.setattr(PathManager, "get_instance", classmethod(lambda cls: pm))
        ar = AutoRecovery(None)
        assert ar.autosave_path == pm.auto_save_path("auto")

    def test_autosave_path_under_recovery_dir(self, pm):
        ar = AutoRecovery(pm)
        assert pm.recovery_dir in ar.autosave_path.parents


# ============================================================
# 2. AutoRecovery — save / load 往返
# ============================================================
@pytest.mark.unit
class TestAutoRecoverySaveLoad:
    """save() 写入与 load() 读取的往返一致性。"""

    def test_save_creates_autosave_file(self, recovery):
        assert not recovery.has_pending_recovery
        recovery.save(_sample_state())
        assert recovery.has_pending_recovery
        assert recovery.autosave_path.exists()

    def test_save_writes_valid_json_payload(self, recovery):
        recovery.save(_sample_state())
        payload = json.loads(recovery.autosave_path.read_text(encoding="utf-8"))
        assert payload["version"] == PROJECT_FILE_VERSION
        assert "saved_at" in payload
        assert payload["state"]["point_cloud_path"] == "/data/sample.xyz"
        assert payload["state"]["repair_mode"] == 1

    def test_save_sets_last_save_timestamp(self, recovery):
        assert recovery._last_save_ts == 0.0
        before = time.time()
        recovery.save(_sample_state())
        assert recovery._last_save_ts >= before

    def test_save_returns_none(self, recovery):
        """save 返回 None（不是 bool）；仅 maybe_save 返回 bool。"""
        assert recovery.save(_sample_state()) is None

    def test_load_returns_state_after_save(self, recovery):
        state = _sample_state()
        recovery.save(state)
        loaded = recovery.load()
        assert loaded is not None
        assert loaded["point_cloud_path"] == state["point_cloud_path"]
        assert loaded["params"] == state["params"]

    def test_load_returns_none_when_no_file(self, recovery):
        assert recovery.load() is None

    def test_load_returns_none_when_file_corrupt(self, recovery):
        """损坏的 autosave 文件应被吞掉，返回 None。"""
        recovery.autosave_path.write_text("{ not valid json ", encoding="utf-8")
        assert recovery.load() is None

    def test_load_returns_empty_state_when_missing_key(self, recovery):
        """payload 无 state 键时返回 {}。"""
        recovery.autosave_path.write_text(
            json.dumps({"version": PROJECT_FILE_VERSION, "saved_at": "x"}),
            encoding="utf-8",
        )
        assert recovery.load() == {}


# ============================================================
# 3. AutoRecovery — has_pending_recovery / clear
# ============================================================
@pytest.mark.unit
class TestAutoRecoveryPendingAndClear:
    """has_pending_recovery 属性与 clear() 行为。"""

    def test_has_pending_recovery_false_initially(self, recovery):
        assert recovery.has_pending_recovery is False

    def test_has_pending_recovery_true_after_save(self, recovery):
        recovery.save(_sample_state())
        assert recovery.has_pending_recovery is True

    def test_has_pending_recovery_false_after_clear(self, recovery):
        recovery.save(_sample_state())
        recovery.clear()
        assert recovery.has_pending_recovery is False

    def test_clear_removes_autosave_file(self, recovery):
        recovery.save(_sample_state())
        assert recovery.autosave_path.exists()
        recovery.clear()
        assert not recovery.autosave_path.exists()

    def test_clear_when_no_file_is_noop(self, recovery):
        assert not recovery.autosave_path.exists()
        recovery.clear()  # 不应抛出
        assert not recovery.autosave_path.exists()

    def test_clear_swallows_unlink_error(self, pm):
        """unlink 抛异常时 clear() 不应传播（仅记 warning）。"""
        ar = AutoRecovery(pm)
        broken = Mock()
        broken.exists.return_value = True
        broken.unlink.side_effect = OSError("file locked")
        ar._autosave_path = broken
        ar.clear()  # 不应抛出


# ============================================================
# 4. AutoRecovery — save 异常吞掉
# ============================================================
@pytest.mark.unit
class TestAutoRecoverySaveErrorHandling:
    """save() 内部异常不应影响主流程。"""

    def test_save_swallows_write_failure(self, pm):
        """目标目录不存在时 write_text 抛异常，save 应吞掉。"""
        ar = AutoRecovery(pm)
        ar._autosave_path = pm.root / "nonexistent_subdir" / "auto.autosave"
        assert not ar._autosave_path.parent.exists()
        # 不应抛出
        ar.save({"a": 1})
        # 写入失败时 _last_save_ts 不应更新
        assert ar._last_save_ts == 0.0
        assert not ar.has_pending_recovery


# ============================================================
# 5. AutoRecovery — maybe_save 定时保存
# ============================================================
@pytest.mark.unit
class TestAutoRecoveryMaybeSave:
    """maybe_save(state, force=False) 时间间隔决策。"""

    def test_maybe_save_force_returns_true_and_saves(self, recovery):
        assert recovery._last_save_ts == 0.0
        saved = recovery.maybe_save(_sample_state(), force=True)
        assert saved is True
        assert recovery.has_pending_recovery
        assert recovery._last_save_ts > 0.0

    def test_maybe_save_within_interval_returns_false(self, recovery):
        """刚保存过、未到间隔时返回 False 且不写入。"""
        recovery.save(_sample_state())
        ts_after_save = recovery._last_save_ts
        saved = recovery.maybe_save(_sample_state(), force=False)
        assert saved is False
        # 时间戳不应推进
        assert recovery._last_save_ts == ts_after_save

    def test_maybe_save_after_interval_returns_true(self, recovery):
        """超过 AUTO_SAVE_INTERVAL_S 后应触发保存。"""
        recovery._last_save_ts = time.time() - AUTO_SAVE_INTERVAL_S - 5
        saved = recovery.maybe_save(_sample_state(), force=False)
        assert saved is True
        assert recovery.has_pending_recovery

    def test_maybe_save_force_overrides_recent_save(self, recovery):
        """force=True 即使刚保存也立即再保存。"""
        recovery.save(_sample_state())
        ts_after_save = recovery._last_save_ts
        saved = recovery.maybe_save(_sample_state(), force=True)
        assert saved is True
        assert recovery._last_save_ts >= ts_after_save

    def test_maybe_save_force_false_at_zero_timestamp_saves(self, recovery):
        """_last_save_ts=0.0 时（now - 0) 远大于间隔，应保存。"""
        assert recovery._last_save_ts == 0.0
        saved = recovery.maybe_save(_sample_state(), force=False)
        assert saved is True
        assert recovery.has_pending_recovery


# ============================================================
# 6. AutoRecovery — 与 ProjectManager 协作（回归）
# ============================================================
@pytest.mark.regression
@pytest.mark.unit
class TestAutoRecoveryWithProjectManager:
    """AutoRecovery 保存 ProjectManager.collect_state 产出的状态可完整往返。"""

    def test_collect_state_roundtrip_through_autorecovery(self, recovery):
        pm = ProjectManager.__new__(ProjectManager)
        state = pm.collect_state(
            point_cloud_path="/data/p.xyz",
            repair_mode=0,
            material_index=3,
            params={"speed": 1.2},
            selection_summary={"point_count": 10},
        )
        recovery.save(state)
        loaded = recovery.load()
        assert loaded == state
        assert loaded["repair_mode"] == 0
        assert loaded["material_index"] == 3


# ============================================================
# 7. crash_handler — 增强覆盖（traceback + 线程信息）
# ============================================================
@pytest.mark.regression
class TestCrashHandlerEnhanced:
    """crash_handler 崩溃日志内容增强覆盖。"""

    def test_crash_log_contains_full_traceback(self, tmp_path, restore_excepthook):
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(ValueError, "tb-marker-123")
        sys.excepthook(*exc_info)

        logs = list(tmp_path.glob("crash_*.log"))
        assert len(logs) == 1
        content = logs[0].read_text(encoding="utf-8")
        assert "Traceback (most recent call last)" in content
        assert "ValueError" in content
        assert "tb-marker-123" in content

    def test_crash_log_traceback_includes_source_file(self, tmp_path, restore_excepthook):
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(RuntimeError, "src-marker")
        sys.excepthook(*exc_info)

        content = list(tmp_path.glob("crash_*.log"))[0].read_text(encoding="utf-8")
        # traceback 应包含本测试文件路径
        assert __file__ in content or "test_crash_recovery" in content
        assert "RuntimeError" in content

    def test_crash_log_contains_thread_info(self, tmp_path, restore_excepthook):
        """崩溃日志应包含线程信息（线程名 + ident）。"""
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(ValueError, "thread-info-test")
        sys.excepthook(*exc_info)

        content = list(tmp_path.glob("crash_*.log"))[0].read_text(encoding="utf-8")
        assert "Thread:" in content
        # 主线程调用时应记录 MainThread
        assert "MainThread" in content
        assert "ident=" in content

    def test_crash_log_records_worker_thread_name(self, tmp_path, restore_excepthook):
        """子线程内崩溃时日志应记录该线程名。"""
        install_crash_handler(log_dir=str(tmp_path))
        done = {"flag": False}

        def worker():
            try:
                raise RuntimeError("from-worker-xyz")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
            done["flag"] = True

        t = threading.Thread(target=worker, name="csam-worker-42")
        t.start()
        t.join(timeout=5)
        assert done["flag"] is True
        assert not t.is_alive()

        content = list(tmp_path.glob("crash_*.log"))[0].read_text(encoding="utf-8")
        assert "Thread:" in content
        assert "csam-worker-42" in content
        assert "from-worker-xyz" in content

    def test_crash_log_contains_environment_header(self, tmp_path, restore_excepthook):
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(ValueError, "env")
        sys.excepthook(*exc_info)

        content = list(tmp_path.glob("crash_*.log"))[0].read_text(encoding="utf-8")
        assert "Crash Report" in content
        assert "Python:" in content
        assert "Platform:" in content


# ============================================================
# 8. MainWindow._check_recovery 流程（轻量 stub，不构造完整窗口）
# ============================================================
@pytest.mark.skipif(not _HAS_MAINWINDOW, reason="MainWindow / PySide6 不可导入")
@pytest.mark.unit
class TestMainWindowCheckRecovery:
    """MainWindow._check_recovery 决策流程。

    通过 SimpleNamespace 构造轻量 self（仅需 _auto_recovery 与
    _apply_recovered_state），避免构造完整 MainWindow。QMessageBox.question
    被 monkeypatch 以控制用户选择且避免模态对话框阻塞。
    """

    def _make_stub(self, ar, apply_fn=None):
        apply_calls: list = []
        if apply_fn is None:
            def apply_fn(state):  # type: ignore[misc]
                apply_calls.append(state)
        return SimpleNamespace(_auto_recovery=ar, _apply_recovered_state=apply_fn), apply_calls

    def test_skips_when_no_pending(self, pm, monkeypatch):
        ar = AutoRecovery(pm)
        ar.clear()
        stub, apply_calls = self._make_stub(ar)

        def _no_dialog(*a, **kw):
            pytest.fail("无恢复文件时不应弹窗")

        monkeypatch.setattr(QMessageBox, "question", _no_dialog)
        MainWindow._check_recovery(stub)
        assert apply_calls == []

    def test_applies_state_when_user_yes(self, pm, monkeypatch):
        ar = AutoRecovery(pm)
        ar.save(_sample_state())
        stub, apply_calls = self._make_stub(ar)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.Yes)

        MainWindow._check_recovery(stub)
        assert len(apply_calls) == 1
        assert apply_calls[0]["point_cloud_path"] == "/data/sample.xyz"

    def test_clears_when_user_no(self, pm, monkeypatch):
        ar = AutoRecovery(pm)
        ar.save(_sample_state())
        stub, apply_calls = self._make_stub(ar)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.No)

        MainWindow._check_recovery(stub)
        assert apply_calls == []  # 未应用
        assert not ar.has_pending_recovery  # 已清除

    def test_skips_when_state_empty(self, pm, monkeypatch):
        """state 为空字典（falsy）时应提前返回，不弹窗。"""
        ar = AutoRecovery(pm)
        ar.save({})  # state={}
        stub, apply_calls = self._make_stub(ar)

        def _no_dialog(*a, **kw):
            pytest.fail("空状态不应弹窗")

        monkeypatch.setattr(QMessageBox, "question", _no_dialog)
        MainWindow._check_recovery(stub)
        assert apply_calls == []

    def test_reads_saved_at_into_prompt(self, pm, monkeypatch):
        """弹窗文案应包含自动保存时间戳。"""
        ar = AutoRecovery(pm)
        ar.save(_sample_state())
        stub, _ = self._make_stub(ar)
        captured: dict = {}

        def _capture(parent, title, text, *a, **kw):
            captured["text"] = text
            return QMessageBox.No

        monkeypatch.setattr(QMessageBox, "question", _capture)
        MainWindow._check_recovery(stub)
        # 文案应包含自动保存时间戳与恢复提示
        assert "自动保存" in captured["text"]
        assert "恢复" in captured["text"]

    def test_swallows_internal_exception(self, monkeypatch):
        """_auto_recovery 访问异常时不应传播（外层 try 兜底）。"""

        class BoomRecovery:
            @property
            def has_pending_recovery(self):
                raise RuntimeError("boom")

            def load(self):
                return {}

            def clear(self):
                pass

            @property
            def autosave_path(self):
                return Path(".")

        stub = SimpleNamespace(
            _auto_recovery=BoomRecovery(),
            _apply_recovered_state=lambda s: None,
        )
        # 不应抛出
        MainWindow._check_recovery(stub)
