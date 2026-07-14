"""
platform — 平台抽象层 (Platform Abstraction Layer)

所有平台相关逻辑的唯一入口。仅依赖 Python 标准库，
不导入任何内部或第三方包，避免循环依赖。

公共 API:
    is_windows() -> bool
    is_macos() -> bool
    is_linux() -> bool
    platform_name() -> str
"""

from __future__ import annotations

import sys


def is_windows() -> bool:
    """当前是否运行在 Windows 上。"""
    return sys.platform == "win32"


def is_macos() -> bool:
    """当前是否运行在 macOS 上。"""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """当前是否运行在 Linux 上。"""
    return sys.platform.startswith("linux")


def platform_name() -> str:
    """返回标准化平台名称: 'windows', 'macos', 'linux', 或 sys.platform 原始值。"""
    if is_windows():
        return "windows"
    if is_macos():
        return "macos"
    if is_linux():
        return "linux"
    return sys.platform
