"""test_exception_recovery.py — 异常处理与恢复流程测试

被测对象: repair_app/utils/error_manager.py
    1. ErrorManager 编排中心
       - classify(exc, code, context) 异常自动分类
       - get_friendly_message(exc, code, context) 友好消息生成
       - handle(exc, code, context, parent, show_dialog) 统一处理入口
       - guard 装饰器 / context 上下文管理器
       - install_global_hooks 全局异常钩子（sys.excepthook + threading.excepthook）
    2. ErrorCode 枚举（7 类）/ FriendlyMessage 数据类 / RecoveryStrategy
    3. LogManager 日志缓存
    4. 便捷别名 handle_error / classify_exception

分类规则覆盖（classify）:
    - 显式 code 优先
    - 异常类型：FileNotFoundError/PermissionError/IsADirectoryError → FILE
                TimeoutError → NETWORK ; MemoryError → UNKNOWN
                类型名含 matlab → MATLAB ; 含 bridge → NETWORK
    - 关键字映射：license/matlab/network/file/mesh/export
    - 上下文推断：授权/导出/路径规划/文件/点云 等
    - 兜底 → UNKNOWN

运行:
    pytest -m "unit or regression" tests/test_exception_recovery.py -v
"""
from __future__ import annotations

import os
import sys
import types
import threading
from types import SimpleNamespace
from unittest.mock import Mock

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest

from repair_app.utils.error_manager import (
    ErrorManager,
    ErrorCode,
    FriendlyMessage,
    RecoveryStrategy,
    LogManager,
    handle_error,
    classify_exception,
)


# ============================================================
# 共享 fixtures
# ============================================================
@pytest.fixture
def restore_hooks():
    """保存并恢复 sys.excepthook 与 threading.excepthook。"""
    orig_sys = sys.excepthook
    orig_thread = getattr(threading, "excepthook", None)
    yield
    sys.excepthook = orig_sys
    if orig_thread is not None:
        threading.excepthook = orig_thread


@pytest.fixture(autouse=True)
def _clear_last_error():
    """每个测试前后清理 LogManager 最近错误缓存，避免相互污染。"""
    LogManager.clear_last_error()
    yield
    LogManager.clear_last_error()


# ============================================================
# 1. ErrorCode 枚举
# ============================================================
@pytest.mark.unit
class TestErrorCode:
    def test_has_seven_categories(self):
        codes = set(ErrorCode)
        assert codes == {
            ErrorCode.LICENSE, ErrorCode.MATLAB, ErrorCode.FILE,
            ErrorCode.MESH, ErrorCode.NETWORK, ErrorCode.EXPORT, ErrorCode.UNKNOWN,
        }
        assert len(codes) == 7

    def test_values_are_strings(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_distinct_values(self):
        values = [c.value for c in ErrorCode]
        assert len(set(values)) == len(values)


# ============================================================
# 2. FriendlyMessage 数据类
# ============================================================
@pytest.mark.unit
class TestFriendlyMessage:
    def test_default_values(self):
        fm = FriendlyMessage()
        assert fm.title == "操作失败"
        assert fm.what == ""
        assert fm.why == ""
        assert fm.how == ""

    def test_custom_values(self):
        fm = FriendlyMessage(title="T", what="W", why="Y", how="H")
        assert (fm.title, fm.what, fm.why, fm.how) == ("T", "W", "Y", "H")

    def test_partial_construction(self):
        fm = FriendlyMessage(what="仅 what")
        assert fm.what == "仅 what"
        assert fm.title == "操作失败"  # 默认


# ============================================================
# 3. RecoveryStrategy 数据类
# ============================================================
@pytest.mark.unit
class TestRecoveryStrategy:
    def test_default_action_is_continue(self):
        rs = RecoveryStrategy()
        assert rs.action == "continue"
        assert rs.fallback_hint == ""

    def test_custom_action(self):
        rs = RecoveryStrategy(action="fatal", fallback_hint="不可恢复")
        assert rs.action == "fatal"
        assert rs.fallback_hint == "不可恢复"

    def test_get_recovery_strategy_for_each_code(self):
        expectations = {
            ErrorCode.LICENSE: "fatal",
            ErrorCode.MATLAB: "retry",
            ErrorCode.NETWORK: "retry",
            ErrorCode.FILE: "continue",
            ErrorCode.MESH: "continue",
            ErrorCode.EXPORT: "continue",
            ErrorCode.UNKNOWN: "continue",
        }
        for code, action in expectations.items():
            assert ErrorManager.get_recovery_strategy(code).action == action, code

    def test_license_strategy_has_hint(self):
        rs = ErrorManager.get_recovery_strategy(ErrorCode.LICENSE)
        assert "License" in rs.fallback_hint


# ============================================================
# 4. classify — 异常分类
# ============================================================
@pytest.mark.unit
class TestClassify:
    """ErrorManager.classify 分类规则覆盖。"""

    def test_explicit_code_takes_precedence(self):
        """显式传入 code 时直接返回，忽略异常类型与上下文。"""
        exc = FileNotFoundError("x")
        assert ErrorManager.classify(exc, code=ErrorCode.MATLAB) == ErrorCode.MATLAB
        assert ErrorManager.classify(exc, code=ErrorCode.LICENSE) == ErrorCode.LICENSE

    # ---- 4.1 异常类型分类 ----
    def test_file_not_found_error_classified_as_file(self):
        assert ErrorManager.classify(FileNotFoundError("/missing.xyz")) == ErrorCode.FILE

    def test_permission_error_classified_as_file(self):
        assert ErrorManager.classify(PermissionError("denied")) == ErrorCode.FILE

    def test_is_a_directory_error_classified_as_file(self):
        assert ErrorManager.classify(IsADirectoryError("is dir")) == ErrorCode.FILE

    def test_timeout_error_classified_as_network(self):
        assert ErrorManager.classify(TimeoutError("timed out")) == ErrorCode.NETWORK

    def test_memory_error_classified_as_unknown(self):
        assert ErrorManager.classify(MemoryError("oom")) == ErrorCode.UNKNOWN

    def test_value_error_classified_as_unknown(self):
        assert ErrorManager.classify(ValueError("invalid input")) == ErrorCode.UNKNOWN

    def test_runtime_error_classified_as_unknown(self):
        assert ErrorManager.classify(RuntimeError("unexpected failure")) == ErrorCode.UNKNOWN

    def test_connection_error_classified_as_network(self):
        """ConnectionError 类型名含 'connection' 关键字 → NETWORK。"""
        assert ErrorManager.classify(ConnectionError("refused")) == ErrorCode.NETWORK

    # ---- 4.2 自定义异常分类 ----
    def test_custom_matlab_exception_classified_as_matlab(self):
        class MatlabAlgorithmError(Exception):
            pass

        assert ErrorManager.classify(MatlabAlgorithmError("algo fail")) == ErrorCode.MATLAB

    def test_custom_bridge_error_classified_as_network(self):
        class BridgeError(Exception):
            pass

        assert ErrorManager.classify(BridgeError("bridge down")) == ErrorCode.NETWORK

    # ---- 4.3 关键字分类 ----
    def test_keyword_license(self):
        assert ErrorManager.classify(Exception("license expired")) == ErrorCode.LICENSE

    def test_keyword_matlab(self):
        assert ErrorManager.classify(Exception("matlab engine crash")) == ErrorCode.MATLAB

    def test_keyword_network_zmq(self):
        assert ErrorManager.classify(Exception("zmq request failed")) == ErrorCode.NETWORK

    def test_keyword_file_permission_denied(self):
        assert ErrorManager.classify(Exception("permission denied")) == ErrorCode.FILE

    def test_keyword_mesh_stl(self):
        assert ErrorManager.classify(Exception("invalid stl mesh")) == ErrorCode.MESH

    def test_keyword_export_gcode(self):
        assert ErrorManager.classify(Exception("gcode export error")) == ErrorCode.EXPORT

    # ---- 4.4 上下文分类 ----
    def test_context_license(self):
        assert ErrorManager.classify(Exception("x"), context="License 校验") == ErrorCode.LICENSE

    def test_context_matlab(self):
        assert ErrorManager.classify(Exception("x"), context="MATLAB 计算") == ErrorCode.MATLAB

    def test_context_path_planning(self):
        assert ErrorManager.classify(Exception("x"), context="路径规划") == ErrorCode.MATLAB

    def test_context_export(self):
        assert ErrorManager.classify(Exception("x"), context="导出 G-code") == ErrorCode.EXPORT

    def test_context_file_load(self):
        assert ErrorManager.classify(Exception("x"), context="加载文件") == ErrorCode.FILE

    def test_context_mesh(self):
        assert ErrorManager.classify(Exception("x"), context="点云处理") == ErrorCode.MESH

    # ---- 4.5 兜底 ----
    def test_unknown_when_no_match(self):
        assert ErrorManager.classify(Exception("zzz"), context="") == ErrorCode.UNKNOWN


# ============================================================
# 5. get_friendly_message — 友好消息生成
# ============================================================
@pytest.mark.unit
class TestGetFriendlyMessage:
    def test_returns_friendly_message_instance(self):
        fm = ErrorManager.get_friendly_message(Exception("x"), ErrorCode.UNKNOWN)
        assert isinstance(fm, FriendlyMessage)

    @pytest.mark.parametrize("code", list(ErrorCode))
    def test_template_for_each_error_code(self, code):
        """每个 ErrorCode 都有对应模板且返回其 title。"""
        fm = ErrorManager.get_friendly_message(Exception("plain"), code, context="")
        expected = ErrorManager._MESSAGE_TEMPLATES[code].title
        assert fm.title == expected

    @pytest.mark.parametrize("code", list(ErrorCode))
    def test_all_fields_non_empty_for_each_code(self, code):
        """每个模板的 what/why/how 均非空。"""
        fm = ErrorManager.get_friendly_message(Exception("plain"), code, context="")
        assert fm.what.strip(), f"{code} what 为空"
        assert fm.why.strip(), f"{code} why 为空"
        assert fm.how.strip(), f"{code} how 为空"

    def test_timeout_specialization(self):
        fm = ErrorManager.get_friendly_message(
            TimeoutError("operation timeout"), ErrorCode.NETWORK, context="路径规划"
        )
        assert "超时" in fm.title
        assert "路径规划" in fm.what
        assert "超时" in fm.why or "耗时" in fm.why

    def test_connection_specialization(self):
        fm = ErrorManager.get_friendly_message(
            ConnectionError("Connection refused"), ErrorCode.NETWORK, context="ZMQ 请求"
        )
        assert "无法连接" in fm.title
        assert "ZMQ 请求" in fm.what
        assert "MATLAB" in fm.why or "Bridge" in fm.why

    def test_memory_specialization(self):
        fm = ErrorManager.get_friendly_message(
            MemoryError("out of memory"), ErrorCode.UNKNOWN, context="大数据计算"
        )
        assert "内存" in fm.title
        assert "大数据计算" in fm.what
        assert "内存" in fm.why

    def test_context_added_to_title_for_known_code(self):
        """已知 code + context（且无超时/连接/内存特化）时 title 为 '{context}失败'。"""
        fm = ErrorManager.get_friendly_message(
            Exception("plain"), ErrorCode.FILE, context="加载文件"
        )
        assert fm.title == "加载文件失败"
        # what/why/how 沿用模板
        assert fm.what == ErrorManager._MESSAGE_TEMPLATES[ErrorCode.FILE].what

    def test_unknown_code_with_context_uses_template_title(self):
        """UNKNOWN + context 时不改 title（仍为模板 '操作失败'）。"""
        fm = ErrorManager.get_friendly_message(
            Exception("plain"), ErrorCode.UNKNOWN, context="某操作"
        )
        assert fm.title == "操作失败"

    def test_no_context_no_specialization_returns_template(self):
        fm = ErrorManager.get_friendly_message(Exception("plain"), ErrorCode.MATLAB, context="")
        assert fm.title == "MATLAB 计算失败"
        assert fm == ErrorManager._MESSAGE_TEMPLATES[ErrorCode.MATLAB]


# ============================================================
# 6. handle — 统一处理入口
# ============================================================
@pytest.mark.unit
class TestHandle:
    def test_handle_returns_code_and_traceback(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        exc = ValueError("handle-me")
        code, tb = ErrorManager.handle(exc, code=ErrorCode.FILE, context="ctx", show_dialog=False)
        assert code == ErrorCode.FILE
        assert isinstance(tb, str)
        assert "ValueError" in tb
        assert "handle-me" in tb

    def test_handle_classifies_when_code_none(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        code, _ = ErrorManager.handle(FileNotFoundError("x"), code=None, show_dialog=False)
        assert code == ErrorCode.FILE

    def test_handle_uses_explicit_code(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        code, _ = ErrorManager.handle(ValueError("x"), code=ErrorCode.MATLAB, show_dialog=False)
        assert code == ErrorCode.MATLAB

    def test_handle_show_dialog_false_skips_dialog(self, monkeypatch):
        mock_show = Mock()
        monkeypatch.setattr(ErrorManager, "_show_dialog", mock_show)
        ErrorManager.handle(ValueError("off"), code=ErrorCode.FILE, show_dialog=False)
        mock_show.assert_not_called()

    def test_handle_show_dialog_true_calls_dialog(self, monkeypatch):
        mock_show = Mock()
        monkeypatch.setattr(ErrorManager, "_show_dialog", mock_show)
        exc = ValueError("dialog-on")
        code, tb = ErrorManager.handle(exc, code=ErrorCode.FILE, context="ctx", show_dialog=True)
        assert code == ErrorCode.FILE
        mock_show.assert_called_once()
        args = mock_show.call_args.args
        assert args[0] is None  # parent
        assert isinstance(args[1], FriendlyMessage)  # friendly
        assert args[2] == tb  # traceback text
        assert args[3] is exc  # exc

    def test_handle_logs_to_log_manager(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        LogManager.clear_last_error()
        ErrorManager.handle(
            RuntimeError("logged-exc"), code=ErrorCode.NETWORK, context="ZMQ", show_dialog=False
        )
        last = LogManager.get_last_error()
        assert last is not None
        assert last["code"] == "network"
        assert last["message"] == "logged-exc"
        assert "RuntimeError" in last["traceback"]
        assert last["context"] == "ZMQ"

    def test_handle_returns_traceback_with_full_stack(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        try:
            raise ValueError("stack-marker")
        except ValueError as exc:
            code, tb = ErrorManager.handle(exc, code=ErrorCode.UNKNOWN, show_dialog=False)
        assert "Traceback (most recent call last)" in tb
        assert "stack-marker" in tb


# ============================================================
# 7. _show_dialog — 内部对话框调度（覆盖 try/except 两分支）
# ============================================================
@pytest.mark.unit
class TestShowDialogInternal:
    def test_show_dialog_success_path_calls_error_dialog(self, monkeypatch):
        """注入 fake ErrorDialog，覆盖 _show_dialog 的 try 分支。"""
        calls = []

        class _FakeDialog:
            @staticmethod
            def show(parent=None, title="", what="", why="", how="", exc=None):
                calls.append(dict(parent=parent, title=title, what=what, why=why, how=how, exc=exc))

        fake_mod = types.ModuleType("repair_app.ui.dialogs")
        fake_mod.ErrorDialog = _FakeDialog
        monkeypatch.setitem(sys.modules, "repair_app.ui.dialogs", fake_mod)

        friendly = FriendlyMessage(title="T", what="W", why="Y", how="H")
        exc = ValueError("e")
        ErrorManager._show_dialog(None, friendly, "tb-text", exc)

        assert len(calls) == 1
        assert calls[0]["title"] == "T"
        assert calls[0]["what"] == "W"
        assert calls[0]["why"] == "Y"
        assert calls[0]["how"] == "H"
        assert calls[0]["exc"] is exc

    def test_show_dialog_falls_back_to_stderr_on_import_error(self, monkeypatch):
        """repair_app.ui.dialogs 不可导入时退化到 stderr，不应抛出。"""
        monkeypatch.setitem(sys.modules, "repair_app.ui.dialogs", None)
        friendly = FriendlyMessage(title="降级", what="what", why="why", how="how")
        # 不应抛出
        ErrorManager._show_dialog(None, friendly, "tb", ValueError("e"))


# ============================================================
# 8. guard 装饰器
# ============================================================
@pytest.mark.unit
class TestGuardDecorator:
    def test_guard_swallows_exception_returns_none(self):
        @ErrorManager.guard(ErrorCode.FILE, context="导出", show_dialog=False)
        def boom():
            raise ValueError("nope")

        assert boom() is None

    def test_guard_reraise_when_requested(self):
        @ErrorManager.guard(ErrorCode.FILE, context="x", show_dialog=False, reraise=True)
        def boom():
            raise ValueError("reraise-me")

        with pytest.raises(ValueError, match="reraise-me"):
            boom()

    def test_guard_returns_value_on_success(self):
        @ErrorManager.guard(ErrorCode.FILE, show_dialog=False)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_guard_calls_handle(self, monkeypatch):
        """guard 捕获异常后应走 ErrorManager.handle（通过 LogManager 验证）。"""
        LogManager.clear_last_error()

        @ErrorManager.guard(ErrorCode.MESH, context="三角化", show_dialog=False)
        def boom():
            raise RuntimeError("mesh fail")

        boom()
        last = LogManager.get_last_error()
        assert last is not None
        assert last["code"] == "mesh"
        assert last["context"] == "三角化"

    def test_guard_parent_getter(self):
        """parent_getter 返回的对象应传给 handle（通过 show_dialog=False 不弹窗验证不抛）。"""
        parent = object()

        @ErrorManager.guard(ErrorCode.FILE, show_dialog=False, parent_getter=lambda: parent)
        def boom():
            raise ValueError("with-parent")

        assert boom() is None


# ============================================================
# 9. context 上下文管理器
# ============================================================
@pytest.mark.unit
class TestContextManager:
    def test_context_swallows_exception(self):
        with ErrorManager.context(ErrorCode.NETWORK, context="ZMQ", show_dialog=False):
            raise ConnectionError("inside")
        # 未传播即通过

    def test_context_no_exception(self):
        result = []
        with ErrorManager.context(ErrorCode.FILE, context="x", show_dialog=False):
            result.append("ran")
        assert result == ["ran"]

    def test_context_logs_error(self):
        LogManager.clear_last_error()
        with ErrorManager.context(ErrorCode.EXPORT, context="导出", show_dialog=False):
            raise RuntimeError("export fail")
        last = LogManager.get_last_error()
        assert last is not None
        assert last["code"] == "export"
        assert last["context"] == "导出"


# ============================================================
# 10. 全局异常钩子（sys.excepthook / threading.excepthook）
# ============================================================
@pytest.mark.regression
class TestGlobalHooks:
    """install_global_hooks 安装主线程与子线程异常钩子。"""

    def test_install_sets_sys_excepthook(self, restore_hooks):
        before = sys.excepthook
        ErrorManager.install_global_hooks(show_dialog=False)
        assert sys.excepthook is not before

    def test_install_sets_threading_excepthook(self, restore_hooks):
        before = threading.excepthook
        ErrorManager.install_global_hooks(show_dialog=False)
        assert threading.excepthook is not before

    def test_main_thread_hook_calls_handle(self, restore_hooks):
        LogManager.clear_last_error()
        # 让 prev_excepthook 成为 noop，避免噪声
        sys.excepthook = lambda *a: None
        ErrorManager.install_global_hooks(show_dialog=False)

        try:
            raise ValueError("hook-main")
        except ValueError:
            sys.excepthook(*sys.exc_info())

        last = LogManager.get_last_error()
        assert last is not None
        assert "主线程" in last["context"]
        assert last["message"] == "hook-main"

    def test_main_thread_hook_skips_keyboard_interrupt(self, restore_hooks):
        LogManager.clear_last_error()
        sys.excepthook = lambda *a: None
        ErrorManager.install_global_hooks(show_dialog=False)

        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())

        # KeyboardInterrupt 不应触发 handle
        assert LogManager.get_last_error() is None

    def test_thread_hook_calls_handle(self, restore_hooks):
        LogManager.clear_last_error()
        ErrorManager.install_global_hooks(show_dialog=False)

        try:
            raise RuntimeError("thread-exc")
        except RuntimeError as e:
            exc_val = e
            tb = e.__traceback__

        args = SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=exc_val,
            exc_traceback=tb,
            thread=threading.current_thread(),
        )
        threading.excepthook(args)

        last = LogManager.get_last_error()
        assert last is not None
        assert "子线程" in last["context"]
        assert last["message"] == "thread-exc"
        # 子线程异常不应弹 GUI 对话框（show_dialog=False）
        assert "子线程" in last["context"]

    def test_thread_hook_skips_keyboard_interrupt(self, restore_hooks):
        LogManager.clear_last_error()
        ErrorManager.install_global_hooks(show_dialog=False)

        args = SimpleNamespace(
            exc_type=KeyboardInterrupt,
            exc_value=KeyboardInterrupt(),
            exc_traceback=None,
            thread=threading.current_thread(),
        )
        threading.excepthook(args)

        assert LogManager.get_last_error() is None

    def test_main_thread_hook_swallows_handle_failure(self, restore_hooks):
        """handle 自身抛异常时主线程钩子不应传播。"""
        sys.excepthook = lambda *a: None

        def boom_handle(*a, **kw):
            raise RuntimeError("handle broken")

        ErrorManager.install_global_hooks(show_dialog=False)
        # 替换 handle 为抛异常版本，验证钩子内 try/except 兜底
        original_handle = ErrorManager.handle
        ErrorManager.handle = boom_handle  # type: ignore[assignment]
        try:
            try:
                raise ValueError("x")
            except ValueError:
                sys.excepthook(*sys.exc_info())  # 不应抛出
        finally:
            ErrorManager.handle = original_handle  # type: ignore[assignment]


# ============================================================
# 11. 便捷别名
# ============================================================
@pytest.mark.unit
class TestConvenienceAliases:
    def test_handle_error_alias(self, monkeypatch):
        monkeypatch.setattr(ErrorManager, "_show_dialog", Mock())
        code, tb = handle_error(ValueError("alias"), code=ErrorCode.UNKNOWN, show_dialog=False)
        assert code == ErrorCode.UNKNOWN
        assert "ValueError" in tb

    def test_classify_exception_alias(self):
        assert classify_exception(FileNotFoundError("x")) == ErrorCode.FILE
        assert classify_exception(Exception("license x")) == ErrorCode.LICENSE
