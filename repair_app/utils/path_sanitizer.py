"""Path sanitizer — replace sensitive paths with placeholders in error reports.

Ensures user home directories, project paths, and temp directories are
not leaked in crash logs, error messages, or tracebacks.

Usage:
    from repair_app.utils.path_sanitizer import PathSanitizer

    sanitized = PathSanitizer.sanitize(tb_text, project_root=PROJECT_ROOT)
"""

from __future__ import annotations

import os
import re
from typing import Optional


class PathSanitizer:
    """路径脱敏工具 - 将敏感路径替换为占位符。"""

    # 占位符常量
    USER_HOME = "<USER_HOME>"
    PROJECT_DIR = "<PROJECT_DIR>"
    TEMP_DIR = "<TEMP_DIR>"

    # ---- 内部缓存 ----
    _home_path: Optional[str] = None
    _temp_paths: Optional[list[str]] = None

    @classmethod
    def _get_home_path(cls) -> str:
        """获取用户主目录路径（已规范化）。"""
        if cls._home_path is None:
            cls._home_path = os.path.normpath(os.path.expanduser("~"))
        return cls._home_path

    @classmethod
    def _get_temp_paths(cls) -> list[str]:
        """获取系统临时目录列表（已规范化）。"""
        if cls._temp_paths is None:
            paths = []
            # Windows temp
            for env_var in ("TEMP", "TMP"):
                val = os.environ.get(env_var)
                if val:
                    paths.append(os.path.normpath(val))
            # Linux/Mac temp
            for p in ("/tmp", "/var/tmp"):
                if os.path.isdir(p):
                    paths.append(p)
            cls._temp_paths = paths
        return cls._temp_paths

    @classmethod
    def _escape_path(cls, path: str) -> str:
        """转义路径中的正则特殊字符，同时处理正斜杠和反斜杠。"""
        escaped = re.escape(path)
        # 允许 \ 和 / 互换匹配
        escaped = escaped.replace(r"\\", r"[\\/]")
        return escaped

    @classmethod
    def sanitize(cls, text: Optional[str], project_root: Optional[str] = None) -> Optional[str]:
        """替换文本中的敏感路径为占位符。

        - C:\\Users\\<username>... → <USER_HOME>...
        - /home/<username>...     → <USER_HOME>...
        - project_root...         → <PROJECT_DIR>...
        - 临时目录...              → <TEMP_DIR>...

        Args:
            text: 待脱敏的文本（None 直接返回 None）
            project_root: 项目根目录（可选，用于替换为 <PROJECT_DIR>）

        Returns:
            脱敏后的文本；输入为 None 时返回 None
        """
        if text is None:
            return None
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        if not isinstance(text, str):
            return text

        # 收集所有待替换的路径，按长度降序排列（避免短路径先匹配覆盖长路径）
        replacements: list[tuple[str, str]] = []

        home = cls._get_home_path()
        if home:
            replacements.append((cls._escape_path(home), cls.USER_HOME))

        if project_root:
            norm_root = os.path.normpath(project_root)
            replacements.append((cls._escape_path(norm_root), cls.PROJECT_DIR))

        for tmp in cls._get_temp_paths():
            replacements.append((cls._escape_path(tmp), cls.TEMP_DIR))

        # 按路径长度降序排列，确保长路径优先替换
        replacements.sort(key=lambda x: len(x[0]), reverse=True)

        result = text
        for pattern, placeholder in replacements:
            result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)

        return result
