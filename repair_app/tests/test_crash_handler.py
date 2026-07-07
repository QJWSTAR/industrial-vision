"""
test_crash_handler.py — 崩溃处理器 (install_crash_handler) 单元测试

被测模块: repair_app/utils/crash_handler.py

说明:
    源码以模块级函数 install_crash_handler(log_dir, on_crash) 实现,
    不存在 CrashHandler 类, 也没有 install() 方法。测试按实际 API 编写,
    使用 tmp_path fixture 隔离日志目录, 并在结束时恢复 sys.excepthook。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from repair_app.utils.crash_handler import install_crash_handler


@pytest.fixture
def restore_excepthook():
    """保存并恢复 sys.excepthook, 避免污染 pytest 自身的异常处理。"""
    original = sys.excepthook
    yield
    sys.excepthook = original


def _raise_and_capture(exc_type, *args):
    """抛出指定异常并返回 (exc_type, exc_value, exc_tb) 三元组。"""
    try:
        raise exc_type(*args)
    except exc_type:
        return sys.exc_info()


class TestInstallCrashHandler:
    def test_install_sets_excepthook(self, tmp_path, restore_excepthook):
        before = sys.excepthook
        install_crash_handler(log_dir=str(tmp_path))
        assert sys.excepthook is not before

    def test_install_creates_log_dir(self, tmp_path, restore_excepthook):
        log_dir = tmp_path / "crashes"
        assert not log_dir.exists()
        install_crash_handler(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_on_crash_callback_invoked(self, tmp_path, restore_excepthook):
        called = []

        def on_crash(msg):
            called.append(msg)

        install_crash_handler(log_dir=str(tmp_path), on_crash=on_crash)
        exc_info = _raise_and_capture(ValueError, "test crash value")
        sys.excepthook(*exc_info)

        assert len(called) == 1
        assert "ValueError" in called[0]
        assert "test crash value" in called[0]

    def test_log_file_written(self, tmp_path, restore_excepthook):
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(RuntimeError, "boom-crash")
        sys.excepthook(*exc_info)

        log_files = list(tmp_path.glob("crash_*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text(encoding="utf-8")
        assert "Crash Report" in content
        assert "RuntimeError" in content
        assert "boom-crash" in content

    def test_log_file_contains_environment_info(self, tmp_path, restore_excepthook):
        install_crash_handler(log_dir=str(tmp_path))
        exc_info = _raise_and_capture(ValueError, "x")
        sys.excepthook(*exc_info)

        log_files = list(tmp_path.glob("crash_*.log"))
        content = log_files[0].read_text(encoding="utf-8")
        assert "Python:" in content
        assert "Platform:" in content

    def test_on_crash_callback_exception_is_swallowed(self, tmp_path, restore_excepthook):
        """on_crash 回调自身抛异常时不应传播, handler 应继续写日志。"""

        def bad_on_crash(msg):
            raise RuntimeError("callback broken")

        install_crash_handler(log_dir=str(tmp_path), on_crash=bad_on_crash)
        exc_info = _raise_and_capture(ValueError, "original")
        # 不应抛出
        sys.excepthook(*exc_info)
        # 日志仍应写入
        assert len(list(tmp_path.glob("crash_*.log"))) == 1

    def test_default_log_dir_when_none(self, tmp_path, restore_excepthook, monkeypatch):
        """log_dir=None 时应使用 get_data_dir()/logs 默认目录且不报错。"""
        import repair_app.utils.crash_handler as ch

        monkeypatch.setattr(ch, "get_data_dir", lambda: str(tmp_path))
        install_crash_handler(log_dir=None)
        assert (tmp_path / "logs").exists()
