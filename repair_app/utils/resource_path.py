"""
resource_path.py — PyInstaller 打包资源路径解析

在 PyInstaller --onefile 模式下，数据文件被解压到 sys._MEIPASS 临时目录。
此模块提供统一的资源路径解析，兼容开发环境和打包环境。
"""

import sys
import os
from pathlib import Path
from typing import Optional


def is_frozen() -> bool:
    """检测是否运行在 PyInstaller 打包环境中。"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_bundle_dir() -> Path:
    """获取资源根目录。

    打包环境: sys._MEIPASS（临时解压目录）
    开发环境: 项目根目录（此文件向上回溯 3 层）
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """获取资源文件的完整路径。

    Args:
        relative_path: 相对于项目根目录的路径，如 'config/calibration_db.json'

    Returns:
        Path 对象，指向资源文件。
    """
    return get_bundle_dir() / relative_path


def get_config_dir() -> Path:
    """获取配置目录路径。

    打包环境: 优先使用 exe 同级目录的 config/（用户可修改），
             回退到 _MEIPASS/config/（打包内置默认值）
    开发环境: 项目根目录的 config/
    """
    if is_frozen():
        # 用户可修改的配置目录（exe 同级）
        user_config = Path(sys.executable).parent / 'config'
        if user_config.is_dir():
            return user_config
        # 打包内置的默认配置
        return Path(sys._MEIPASS) / 'config'
    return Path(__file__).resolve().parent.parent.parent / 'config'


def get_config_file(filename: str) -> Optional[Path]:
    """获取配置文件的完整路径，不存在则返回 None。"""
    p = get_config_dir() / filename
    return p if p.exists() else None


def get_data_dir() -> Path:
    """获取数据目录路径（用户数据，如生成的航点文件）。

    打包环境: exe 同级目录
    开发环境: 项目根目录
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent
