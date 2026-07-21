"""software.path_manager — 统一路径管理

集中管理软件所有用户数据目录：
- 项目目录（保存 .csam 工程文件）
- 导出目录（G-code / PDF 报告 / STL）
- 日志目录（app.log / error.log / crash_*.log / exception_*.log）
- 恢复目录（auto_save / 自动恢复快照）
- 缓存目录（临时文件）

目录结构（用户主目录下 CSAM_Repair/）：
    ~/CSAM_Repair/
    ├── projects/         项目文件
    ├── exports/          导出文件（gcode/ pdf/ stl/）
    │   ├── gcode/
    │   ├── pdf/
    │   └── stl/
    ├── logs/             日志（app.log, error.log, crash_*.log）
    ├── recovery/         自动保存与恢复
    └── cache/            临时缓存

Windows 默认：%USERPROFILE%\\CSAM_Repair
打包环境优先 %APPDATA%\\CSAM_Repair（标准用户数据目录）
开发环境优先项目根的 user_data/（避免污染用户主目录）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from repair_app.utils.resource_path import is_frozen


APP_DIR_NAME = "CSAM_Repair"


def _get_user_root() -> Path:
    """返回用户数据根目录。

    优先级：
    1. 环境变量 CSAM_USER_DATA（用户自定义）
    2. 打包环境：%APPDATA%/CSAM_Repair（Windows 标准）
    3. 开发环境：项目根/user_data/
    """
    # 1. 环境变量覆盖
    env_dir = os.environ.get("CSAM_USER_DATA")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    # 2. 打包环境：使用 %APPDATA%
    if is_frozen():
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_DIR_NAME

    # 3. Windows 打包但无 APPDATA：回退到 exe 同级
    if is_frozen():
        return Path(sys.executable).parent / "user_data"

    # 4. 开发环境：项目根/user_data
    return Path(__file__).resolve().parent.parent.parent / "user_data"


class PathManager:
    """统一路径管理器（单例）。

    所有目录首次访问时自动创建。
    """

    _instance: "PathManager | None" = None

    def __init__(self) -> None:
        self._root = _get_user_root()
        # 子目录定义
        self._projects_dir = self._root / "projects"
        self._exports_dir = self._root / "exports"
        self._gcode_dir = self._exports_dir / "gcode"
        self._pdf_dir = self._exports_dir / "pdf"
        self._stl_dir = self._exports_dir / "stl"
        self._logs_dir = self._root / "logs"
        self._recovery_dir = self._root / "recovery"
        self._cache_dir = self._root / "cache"
        # 确保所有目录存在
        for d in (
            self._projects_dir, self._exports_dir,
            self._gcode_dir, self._pdf_dir, self._stl_dir,
            self._logs_dir, self._recovery_dir, self._cache_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "PathManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ---- 根目录 ----
    @property
    def root(self) -> Path:
        return self._root

    # ---- 项目目录 ----
    @property
    def projects_dir(self) -> Path:
        return self._projects_dir

    def project_path(self, name: str) -> Path:
        """返回项目文件完整路径（自动加 .csam 扩展名）。"""
        if not name.endswith(".csam"):
            name = name + ".csam"
        return self._projects_dir / name

    # ---- 导出目录 ----
    @property
    def exports_dir(self) -> Path:
        return self._exports_dir

    @property
    def gcode_dir(self) -> Path:
        return self._gcode_dir

    @property
    def pdf_dir(self) -> Path:
        return self._pdf_dir

    @property
    def stl_dir(self) -> Path:
        return self._stl_dir

    def gcode_path(self, name: str) -> Path:
        if not name.endswith((".nc", ".gcode", ".txt")):
            name = name + ".nc"
        return self._gcode_dir / name

    def pdf_path(self, name: str) -> Path:
        if not name.endswith(".pdf"):
            name = name + ".pdf"
        return self._pdf_dir / name

    def stl_path(self, name: str) -> Path:
        if not name.endswith(".stl"):
            name = name + ".stl"
        return self._stl_dir / name

    # ---- 日志目录 ----
    @property
    def logs_dir(self) -> Path:
        return self._logs_dir

    def crash_log_path(self, timestamp: str) -> Path:
        return self._logs_dir / f"crash_{timestamp}.log"

    def exception_log_path(self, timestamp: str) -> Path:
        return self._logs_dir / f"exception_{timestamp}.log"

    # ---- 恢复目录 ----
    @property
    def recovery_dir(self) -> Path:
        return self._recovery_dir

    def auto_save_path(self, project_name: str = "auto") -> Path:
        return self._recovery_dir / f"{project_name}.autosave"

    # ---- 缓存目录 ----
    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    # ---- 路径信息字符串（用于状态栏 / About 对话框） ----
    def describe(self) -> str:
        return (
            f"用户数据目录: {self._root}\n"
            f"  项目: {self._projects_dir}\n"
            f"  导出: {self._exports_dir}\n"
            f"  日志: {self._logs_dir}\n"
            f"  恢复: {self._recovery_dir}\n"
            f"  缓存: {self._cache_dir}"
        )
