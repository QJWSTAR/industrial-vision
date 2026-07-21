"""app_config.py — 应用级统一配置入口（Developer Mode 的唯一 Truth Source）。

设计目标
========
1. 整个项目**只通过 AppConfig 获取** Developer Mode 状态，禁止散落的 if 判断。
2. 配置优先级（高 → 低）：
   - 环境变量 ``CSAM_DEVELOPER_MODE`` （临时覆盖，不改文件）
   - ``config/app_config.json`` 的 ``developer_mode`` 字段（持久化）
   - 默认值 ``False`` （安全默认：生产模式）
3. License 架构完全保留：``AppConfig`` 只决定是否**调用** License 校验，
   不修改 License 校验算法本身。
4. 恢复商业授权：把 ``developer_mode`` 改为 ``false``（或删除环境变量），
   无需修改任何业务代码。

用法
====
    from repair_app.utils.app_config import AppConfig

    if AppConfig.is_developer_mode():
        # 开发者模式分支
        ...
    else:
        # 生产模式分支
        ...

线程安全
========
``AppConfig`` 使用模块级单例，首次调用时线程安全地加载配置并缓存。
测试时可通过 ``AppConfig.reload()`` 强制重新加载，或用 ``AppConfig.override()``
临时覆盖（contextmanager）。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

try:
    from repair_app.utils.resource_path import get_config_dir, get_builtin_config_file
except ImportError:  # pragma: no cover - 开发环境回退
    def get_config_dir() -> Path:
        return Path(__file__).resolve().parent.parent.parent / "config"

    def get_builtin_config_file(filename: str) -> Optional[Path]:
        p = Path(__file__).resolve().parent.parent.parent / "config" / filename
        return p if p.exists() else None


CONFIG_FILENAME = "app_config.json"
ENV_VAR = "CSAM_DEVELOPER_MODE"

# 真值集合：环境变量 / JSON 中这些值被视为 True
_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def _parse_bool(value) -> bool:
    """宽松解析布尔值（支持 str/bool/int）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _TRUE_VALUES:
            return True
        if s in _FALSE_VALUES:
            return False
    return False


class _AppConfig:
    """AppConfig 单例实现（内部类，外部请使用 AppConfig 别名）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._developer_mode: bool = False
        self._config: dict = {}

    # ---- 加载 ----
    def _load(self) -> None:
        """加载配置（线程安全，仅首次执行）。"""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:  # double-check
                return
            self._config = self._read_config_file()
            # 环境变量优先级最高
            env_val = os.environ.get(ENV_VAR)
            if env_val is not None and env_val.strip() != "":
                self._developer_mode = _parse_bool(env_val)
            else:
                self._developer_mode = _parse_bool(
                    self._config.get("developer_mode", False)
                )
            self._loaded = True

    def _read_config_file(self) -> dict:
        """读取 app_config.json（优先用户 config 目录，回退打包内置）。"""
        candidates = [
            get_config_dir() / CONFIG_FILENAME,
            get_builtin_config_file(CONFIG_FILENAME),
        ]
        for path in candidates:
            if path is None:
                continue
            try:
                p = Path(path)
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except (json.JSONDecodeError, OSError):
                continue
        return {}

    # ---- 公开接口 ----
    def is_developer_mode(self) -> bool:
        """是否处于开发者模式。

        Returns:
            True 表示跳过 License 验证（开发/测试用途）；
            False 表示执行完整商业 License 校验（生产模式）。
        """
        self._load()
        return self._developer_mode

    def get(self, key: str, default=None):
        """读取任意配置项（透传 JSON 字段，带下划线前缀的为文档字段）。"""
        self._load()
        return self._config.get(key, default)

    def reload(self) -> None:
        """强制重新加载配置（测试用）。

        清除缓存并重新读取文件 + 环境变量。
        """
        with self._lock:
            self._loaded = False
            self._config = {}
            self._developer_mode = False
        self._load()

    # ---- 测试辅助 ----
    def override(self, developer_mode: bool):
        """返回一个 contextmanager，临时覆盖 Developer Mode 状态。

        用法：
            with AppConfig.override(developer_mode=True):
                assert AppConfig.is_developer_mode()
            # 退出后恢复原值
        """
        return _OverrideContext(self, developer_mode)


class _OverrideContext:
    """临时覆盖 AppConfig 状态的上下文管理器（仅测试用）。"""

    def __init__(self, config: _AppConfig, developer_mode: bool) -> None:
        self._config = config
        self._override_value = developer_mode
        self._saved_loaded: bool = False
        self._saved_mode: bool = False

    def __enter__(self):
        self._config._load()
        self._saved_loaded = self._config._loaded
        self._saved_mode = self._config._developer_mode
        # 直接设置（绕过 _load）
        with self._config._lock:
            self._config._developer_mode = self._override_value
            self._config._loaded = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with self._config._lock:
            self._config._developer_mode = self._saved_mode
            self._config._loaded = self._saved_loaded
        return False


# 模块级单例（外部统一使用 AppConfig）
AppConfig = _AppConfig()


__all__ = ["AppConfig"]
