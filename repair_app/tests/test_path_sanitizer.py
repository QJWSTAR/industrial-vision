"""test_path_sanitizer.py — PathSanitizer 路径脱敏工具单元测试

被测模块: repair_app/utils/path_sanitizer.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from repair_app.utils.path_sanitizer import PathSanitizer


class TestPathSanitizerBasics:
    """基础功能测试"""

    def test_none_input(self):
        """None 输入应返回 None"""
        assert PathSanitizer.sanitize(None) is None

    def test_empty_string(self):
        """空字符串应返回空字符串"""
        result = PathSanitizer.sanitize("")
        assert result == ""

    def test_no_sensitive_paths(self):
        """不含敏感路径的文本应保持不变"""
        text = "This is a normal error message without any paths."
        result = PathSanitizer.sanitize(text)
        assert result == text

    def test_non_string_input(self):
        """非字符串输入应原样返回"""
        assert PathSanitizer.sanitize(123) == 123


class TestHomePathSanitization:
    """用户主目录脱敏测试"""

    def test_windows_home_path(self, monkeypatch):
        """Windows 主目录: C:\\Users\\john\\file.txt → <USER_HOME>\\file.txt"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\john")
        # 重置缓存
        PathSanitizer._home_path = None
        text = r"Error in C:\Users\john\file.txt at line 42"
        result = PathSanitizer.sanitize(text)
        assert r"<USER_HOME>\file.txt" in result
        assert r"C:\Users\john" not in result

    def test_linux_home_path(self, monkeypatch):
        """Linux 主目录: /home/john/file.txt → <USER_HOME>/file.txt"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: "/home/john")
        PathSanitizer._home_path = None
        text = "Error in /home/john/file.txt at line 42"
        result = PathSanitizer.sanitize(text)
        assert "<USER_HOME>/file.txt" in result
        assert "/home/john" not in result

    def test_home_path_with_backslash_in_text(self, monkeypatch):
        """Windows 主目录 + 文本中混合反斜杠"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\john")
        PathSanitizer._home_path = None
        text = r"File \"C:\Users\john\app\main.py\", line 10"
        result = PathSanitizer.sanitize(text)
        assert r"<USER_HOME>\app\main.py" in result
        assert r"C:\Users\john" not in result


class TestProjectRootSanitization:
    """项目根目录脱敏测试"""

    def test_project_root_replacement(self):
        """项目根目录应被替换为 <PROJECT_DIR>"""
        project_root = r"D:\work\demo"
        text = r"File D:\work\demo\repair_app\utils\crash_handler.py, line 50"
        result = PathSanitizer.sanitize(text, project_root=project_root)
        assert r"<PROJECT_DIR>\repair_app\utils\crash_handler.py" in result
        assert r"D:\work\demo" not in result

    def test_project_root_linux(self):
        """Linux 风格项目根目录"""
        project_root = "/opt/industrial-vision"
        text = "File /opt/industrial-vision/repair_app/main.py, line 42"
        result = PathSanitizer.sanitize(text, project_root=project_root)
        assert "<PROJECT_DIR>/repair_app/main.py" in result
        assert "/opt/industrial-vision" not in result

    def test_no_project_root(self):
        """未提供 project_root 时，文本中的项目路径不应被替换"""
        text = r"D:\work\demo\repair_app\main.py"
        result = PathSanitizer.sanitize(text)
        # 不提供 project_root 时，只能匹配 home 和 temp
        assert result == text


class TestTempPathSanitization:
    """临时目录脱敏测试"""

    def test_windows_temp_path(self, monkeypatch):
        """Windows TEMP 目录应被替换为 <TEMP_DIR>"""
        monkeypatch.setenv("TEMP", r"C:\Users\john\AppData\Local\Temp")
        PathSanitizer._temp_paths = None
        text = r"Temporary file at C:\Users\john\AppData\Local\Temp\file.tmp"
        result = PathSanitizer.sanitize(text)
        assert r"<TEMP_DIR>\file.tmp" in result
        assert r"C:\Users\john\AppData\Local\Temp" not in result

    def test_linux_tmp_path(self, monkeypatch):
        """Linux /tmp 目录应被替换为 <TEMP_DIR>"""
        # 清除 Windows TEMP 环境变量
        monkeypatch.delenv("TEMP", raising=False)
        monkeypatch.delenv("TMP", raising=False)
        PathSanitizer._temp_paths = None
        # 在 Windows 上 /tmp 可能不存在，使用 monkeypatch 模拟
        # 直接测试 /tmp 路径替换（仅当 /tmp 存在时）
        if os.path.isdir("/tmp"):
            text = "Cache file at /tmp/cache_123.tmp"
            result = PathSanitizer.sanitize(text)
            assert "<TEMP_DIR>/cache_123.tmp" in result


class TestComplexSanitization:
    """复杂场景测试"""

    def test_traceback_with_multiple_paths(self, monkeypatch):
        """Traceback 中包含多个路径类型"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\john")
        monkeypatch.setenv("TEMP", r"C:\Users\john\AppData\Local\Temp")
        PathSanitizer._home_path = None
        PathSanitizer._temp_paths = None

        project_root = r"D:\work\demo"
        text = (
            r'Traceback (most recent call last):' "\n"
            r'  File "D:\work\demo\repair_app\main.py", line 10, in <module>' "\n"
            r'  File "C:\Users\john\Documents\script.py", line 5, in helper' "\n"
            r'OSError: [Errno 2] No such file: C:\Users\john\AppData\Local\Temp\tmp123.tmp'
        )
        result = PathSanitizer.sanitize(text, project_root=project_root)
        assert "<PROJECT_DIR>" in result
        assert "<USER_HOME>" in result
        assert "<TEMP_DIR>" in result
        assert r"D:\work\demo" not in result
        assert r"C:\Users\john\AppData\Local\Temp" not in result
        assert r"C:\Users\john\Documents" not in result

    def test_mixed_paths_single_string(self, monkeypatch):
        """混合路径在单行字符串中"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\admin")
        monkeypatch.setenv("TEMP", r"C:\Users\admin\AppData\Local\Temp")
        PathSanitizer._home_path = None
        PathSanitizer._temp_paths = None

        project_root = r"D:\work\demo"
        text = (
            r"Config: D:\work\demo\config.ini, "
            r"Home: C:\Users\admin\.ssh, "
            r"Temp: C:\Users\admin\AppData\Local\Temp\log.txt"
        )
        result = PathSanitizer.sanitize(text, project_root=project_root)
        assert "<PROJECT_DIR>" in result
        assert "<USER_HOME>" in result
        assert "<TEMP_DIR>" in result
        assert r"D:\work\demo" not in result
        assert r"C:\Users\admin" not in result

    def test_no_sensitive_data_unchanged(self):
        """无敏感数据时文本应完全不变"""
        text = "TypeError: 'NoneType' object is not iterable"
        result = PathSanitizer.sanitize(text)
        assert result == text


class TestIdempotency:
    """幂等性测试"""

    def test_sanitize_twice_same_result(self, monkeypatch):
        """两次脱敏应产生相同结果"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\john")
        monkeypatch.setenv("TEMP", r"C:\Users\john\AppData\Local\Temp")
        PathSanitizer._home_path = None
        PathSanitizer._temp_paths = None

        project_root = r"D:\work\demo"
        text = r"Error at D:\work\demo\repair_app\utils\crash_handler.py:50"
        first = PathSanitizer.sanitize(text, project_root=project_root)
        second = PathSanitizer.sanitize(first, project_root=project_root)
        assert first == second

    def test_placeholder_not_replaced(self, monkeypatch):
        """占位符自身不应被再次替换"""
        monkeypatch.setattr(os.path, "expanduser", lambda x: r"C:\Users\john")
        PathSanitizer._home_path = None
        text = r"File <USER_HOME>\script.py"
        result = PathSanitizer.sanitize(text)
        # 确保占位符不会再被替换
        assert result.count("<USER_HOME>") <= 1