"""software.project_manager — 项目持久化 + 自动保存 + 自动恢复 + 最近项目

功能：
1. ProjectManager：把当前会话状态（点云路径、参数、模式、选区）保存为 .csam 工程文件
2. AutoRecovery：定时把当前状态写入 recovery/auto.autosave，崩溃后启动提示恢复
3. RecentProjects：维护最近 10 个项目列表，保存到 recent_projects.json

工程文件格式（.csam，JSON）：
{
  "version": "1.0.0",
  "name": "my_project",
  "created_at": "...",
  "updated_at": "...",
  "state": {
    "point_cloud_path": "/path/to/cloud.xyz",
    "repair_mode": 1,
    "material_index": 1,
    "params": {...},
    "selection_summary": {"point_count": 1234, "volume_mm3": 5.6}
  }
}
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from repair_app.software.path_manager import PathManager
from repair_app.utils.logger_config import warning


PROJECT_FILE_VERSION = "1.0.0"
RECENT_PROJECTS_FILE = "recent_projects.json"
RECENT_MAX = 10
AUTO_SAVE_INTERVAL_S = 60  # 默认 60 秒自动保存一次


class ProjectManager:
    """项目文件读写（.csam）。

    .csam 文件本质是 JSON，保存软件会话状态，不含点云数据本身（仅保存路径）。
    """

    def __init__(self, path_manager: Optional[PathManager] = None) -> None:
        self._pm = path_manager or PathManager.get_instance()
        self._current_project_path: Optional[Path] = None
        self._current_name: str = "未命名"

    @property
    def current_path(self) -> Optional[Path]:
        return self._current_project_path

    @property
    def current_name(self) -> str:
        return self._current_name

    def new_project(self, name: str = "未命名") -> None:
        """新建项目（清空当前路径，不写文件）。"""
        self._current_project_path = None
        self._current_name = name

    def save_project(self, state: dict, name: Optional[str] = None) -> Path:
        """保存项目到 .csam 文件。

        Args:
            state: 会话状态字典
            name: 项目名（不传则用当前名）
        Returns:
            保存的文件路径
        """
        if name:
            self._current_name = name
        path = self._pm.project_path(self._current_name)
        payload = {
            "version": PROJECT_FILE_VERSION,
            "name": self._current_name,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "state": state,
        }
        # 若文件已存在，保留原 created_at
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                payload["created_at"] = old.get("created_at", payload["created_at"])
            except Exception as exc:
                warning(f"读取旧项目 created_at 失败，使用新时间戳: {exc}")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._current_project_path = path
        return path

    def load_project(self, path: Path) -> dict:
        """加载 .csam 工程文件，返回状态字典。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"项目文件不存在: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != PROJECT_FILE_VERSION:
            # 版本不匹配时仍尝试加载 state，但记录警告
            pass
        self._current_project_path = path
        self._current_name = payload.get("name", path.stem)
        return payload.get("state", {})

    def collect_state(
        self,
        point_cloud_path: Optional[str] = None,
        repair_mode: int = 1,
        material_index: int = 1,
        params: Optional[dict] = None,
        selection_summary: Optional[dict] = None,
    ) -> dict:
        """收集当前会话状态。"""
        return {
            "point_cloud_path": point_cloud_path,
            "repair_mode": repair_mode,
            "material_index": material_index,
            "params": params or {},
            "selection_summary": selection_summary or {},
        }


class AutoRecovery:
    """自动保存与崩溃恢复。

    - 定时把当前状态写入 recovery/auto.autosave
    - 启动时检查是否存在 autosave 文件，存在则返回待恢复状态
    - 恢复后或用户主动放弃后，删除 autosave 文件
    """

    def __init__(self, path_manager: Optional[PathManager] = None) -> None:
        self._pm = path_manager or PathManager.get_instance()
        self._autosave_path = self._pm.auto_save_path("auto")
        self._last_save_ts: float = 0.0

    @property
    def autosave_path(self) -> Path:
        return self._autosave_path

    @property
    def has_pending_recovery(self) -> bool:
        """是否存在可恢复的自动保存。"""
        return self._autosave_path.exists()

    def save(self, state: dict) -> None:
        """保存当前状态到 autosave 文件。"""
        payload = {
            "version": PROJECT_FILE_VERSION,
            "saved_at": datetime.now().isoformat(),
            "state": state,
        }
        try:
            self._autosave_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._last_save_ts = time.time()
        except Exception:
            # 自动保存失败不应影响主流程
            pass

    def load(self) -> Optional[dict]:
        """加载 autosave 状态，不存在返回 None。"""
        if not self._autosave_path.exists():
            return None
        try:
            payload = json.loads(self._autosave_path.read_text(encoding="utf-8"))
            return payload.get("state", {})
        except Exception:
            return None

    def clear(self) -> None:
        """清除 autosave 文件（恢复完成或用户放弃后调用）。"""
        try:
            if self._autosave_path.exists():
                self._autosave_path.unlink()
        except Exception as exc:
            warning(f"清除 autosave 文件失败: {exc}")

    def maybe_save(self, state: dict, force: bool = False) -> bool:
        """根据时间间隔决定是否保存。

        Args:
            state: 当前状态
            force: 强制保存（忽略时间间隔）
        Returns:
            是否实际执行了保存
        """
        now = time.time()
        if force or (now - self._last_save_ts) >= AUTO_SAVE_INTERVAL_S:
            self.save(state)
            return True
        return False


class RecentProjects:
    """最近项目列表管理。

    持久化到 recent_projects.json，保留最近 10 个项目。
    """

    def __init__(self, path_manager: Optional[PathManager] = None) -> None:
        self._pm = path_manager or PathManager.get_instance()
        self._file = self._pm.root / RECENT_PROJECTS_FILE
        self._items: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._file.exists():
            self._items = []
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            self._items = data.get("items", [])
        except Exception:
            self._items = []

    def _save(self) -> None:
        try:
            payload = {"version": "1.0", "items": self._items}
            self._file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            warning(f"保存最近项目列表失败: {exc}")

    @property
    def items(self) -> list[dict]:
        """返回最近项目列表（最新在前）。

        每项格式：{"name": str, "path": str, "updated_at": str}
        """
        return list(self._items)

    def add(self, name: str, path: str) -> None:
        """添加/更新一个项目到最近列表。"""
        # 去重：同名同路径的移除旧的
        self._items = [
            it for it in self._items
            if not (it.get("name") == name and it.get("path") == path)
        ]
        self._items.insert(0, {
            "name": name,
            "path": path,
            "updated_at": datetime.now().isoformat(),
        })
        # 截断到 RECENT_MAX
        self._items = self._items[:RECENT_MAX]
        self._save()

    def remove(self, path: str) -> None:
        """从最近列表移除一个项目。"""
        self._items = [it for it in self._items if it.get("path") != path]
        self._save()

    def clear(self) -> None:
        """清空最近列表。"""
        self._items = []
        self._save()
