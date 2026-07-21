"""conftest.py — 测试体系共享 fixtures 与 marker 注册。

测试体系分层（按 marker）：
  - smoke       : 冒烟测试（核心 import + 启动验证，<2s）
  - regression  : 回归测试（关键 bug 修复回归）
  - unit        : 单元测试（函数/类级别）
  - integration : 集成测试（模块间协作）
  - gui         : GUI 测试（QtBot/QTest）
  - export      : 导出测试（G-code/Robot/Report）
  - performance : 性能测试（pytest-benchmark）
  - stress      : 压力测试（大数据量/极端参数）
  - mock        : Mock 测试（MATLAB Mock / License Mock）

运行方式：
  pytest -m smoke              # 仅冒烟
  pytest -m "not slow"         # 排除慢测试
  pytest -m "export or gui"    # 导出或 GUI
  pytest --cov=repair_app      # 覆盖率
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any

import numpy as np
import pytest

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 强制 Qt 离屏模式（CI/无显示环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 测试模式：允许 Python Demo 引擎
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")
# 测试模式：使用开发 License 密钥
os.environ.setdefault("CSAM_HMAC_SECRET", "csam_test_secret_2026")


# ============================================================
# Marker 注册（避免 pytest未知 marker 警告）
# ============================================================
def pytest_configure(config: pytest.Config) -> None:
    markers = [
        "smoke: 冒烟测试 — 核心 import 与启动验证（<2s）",
        "regression: 回归测试 — 关键 bug 修复回归",
        "unit: 单元测试 — 函数/类级别",
        "integration: 集成测试 — 模块间协作",
        "gui: GUI 测试 — QtBot/QTest",
        "export: 导出测试 — G-code/Robot/Report",
        "performance: 性能测试 — pytest-benchmark",
        "stress: 压力测试 — 大数据量/极端参数",
        "mock: Mock 测试 — MATLAB Mock / License Mock",
        "slow: 慢测试 — 运行时间 >2s",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)


# ============================================================
# QApplication fixture（全局共享）
# ============================================================
@pytest.fixture(scope="session")
def qapp():
    """提供全局 QApplication 实例（offscreen 模式）。

    session 级别共享，避免每个测试新建 QApplication 导致崩溃。
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ============================================================
# 线程安全日志 fixture（session 级 autouse）
# ------------------------------------------------------------
# 根因：loguru 默认 sink 直接写 sys.stderr（非 enqueue 模式）。
# pytest 输出捕获将 sys.stderr 替换为非线程安全的 buffer。
# Worker 线程（BaseWorker._mark_start / check_interruption 等）
# 调用 logger.info/warning 时，从非主线程写入 pytest buffer，
# 触发死锁（表现为组合运行时卡在 ZMQ/Worker 线程测试）。
#
# 修复：session 开始时移除所有 loguru sink（包括默认 stderr sink）。
# 文件日志（如需）应由 setup_logging() 以 enqueue=True 添加。
# 测试中不需要控制台日志输出。
# ============================================================
@pytest.fixture(autouse=True, scope="session")
def _disable_loguru_console_sink():
    """移除 loguru 默认 stderr sink，避免 pytest 捕获与多线程日志死锁。"""
    try:
        from loguru import logger
        logger.remove()
    except ImportError:
        pass
    yield


# ============================================================
# 防止 QTimer.singleShot 延迟回调泄漏（session 级 autouse）
# ------------------------------------------------------------
# 根因：MainWindow.__init__ 调用 QTimer.singleShot(500, self._check_recovery)
# 等延迟回调。测试中 MainWindow 在 500ms 内即被销毁，但 QTimer 仍挂起。
# 后续测试调用 processEvents() 时定时器触发，访问已销毁的 C++ 对象，
# 导致 Windows 堆损坏（STATUS_HEAP_CORRUPTION 0xC0000374）。
#
# 修复：在测试中将 QTimer.singleShot 替换为空操作，阻止延迟回调注册。
# _check_recovery 等方法由各自的专项测试（test_crash_recovery.py）直接验证。
# ============================================================
@pytest.fixture(autouse=True, scope="session")
def _disable_qtimer_singleshot():
    """测试中禁用 QTimer.singleShot，防止延迟回调泄漏到后续测试。"""
    try:
        from PySide6.QtCore import QTimer
        QTimer.singleShot = lambda *args, **kwargs: None
    except ImportError:
        pass
    yield


@pytest.fixture
def qapp_events(qapp):
    """处理 Qt 事件循环的 fixture。"""
    qapp.processEvents()
    yield qapp
    qapp.processEvents()


# ============================================================
# 数据 fixtures
# ============================================================
@pytest.fixture
def sample_points() -> np.ndarray:
    """小型平面点云 (100, 3)，用于快速测试。"""
    rng = np.random.default_rng(42)
    xy = rng.uniform(-5, 5, (100, 2))
    z = rng.uniform(0, 0.5, 100)  # 接近平面
    return np.column_stack([xy, z]).astype(np.float32)


@pytest.fixture
def sample_defect_mask(sample_points: np.ndarray) -> np.ndarray:
    """缺陷掩码：中间 30% 的点为缺陷。"""
    n = len(sample_points)
    mask = np.zeros(n, dtype=bool)
    mask[n // 3: 2 * n // 3] = True
    return mask


@pytest.fixture
def sample_waypoints() -> np.ndarray:
    """示例航点 (50, 3)。"""
    rng = np.random.default_rng(7)
    return rng.uniform(-3, 3, (50, 3)).astype(np.float32)


@pytest.fixture
def large_points() -> np.ndarray:
    """大型点云 (10000, 3)，用于性能/压力测试。"""
    rng = np.random.default_rng(123)
    xy = rng.uniform(-50, 50, (10000, 2))
    z = rng.uniform(0, 2, 10000)
    return np.column_stack([xy, z]).astype(np.float32)


# ============================================================
# 临时目录 fixtures
# ============================================================
@pytest.fixture
def tmp_project_dir(tmp_path) -> str:
    """临时项目目录（含 exports/logs 子目录）。"""
    (tmp_path / "exports").mkdir()
    (tmp_path / "logs").mkdir()
    return str(tmp_path)


@pytest.fixture
def tmp_license_dir(tmp_path) -> str:
    """临时 License 目录。"""
    return str(tmp_path)


# ============================================================
# MATLAB Mock fixture
# ============================================================
@pytest.fixture
def mock_matlab():
    """提供 MATLAB Mock 服务（不依赖真实 MATLAB）。

    Mock 行为：
    - request_repair 返回确定性的航点序列
    - check_health 返回 OK
    - 不发起真实 ZMQ 连接
    """
    from repair_app.tests.mocks.matlab_mock import MockMatlabAdapter
    adapter = MockMatlabAdapter()
    yield adapter
    adapter.shutdown()


@pytest.fixture
def mock_matlab_algorithm():
    """提供确定性的 MATLAB 算法 Mock 函数。"""
    from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
    return deterministic_algorithm


# ============================================================
# License Mock fixture
# ============================================================
@pytest.fixture
def mock_license_env(tmp_license_dir: str, monkeypatch):
    """提供有效 License 的 Mock 环境。

    - 生成临时密钥对 + License 文件
    - 指向临时目录
    - License 有效期 365 天
    """
    from repair_app.tests.mocks.license_mock import create_mock_license_env
    env = create_mock_license_env(tmp_license_dir, days_valid=365)
    # 重定向 license_manager 的目录查找
    monkeypatch.setattr(
        "repair_app.utils.license_manager.get_config_dir",
        lambda: tmp_license_dir,
    )
    yield env


@pytest.fixture
def mock_license_expired(tmp_license_dir: str, monkeypatch):
    """提供已过期 License 的 Mock 环境。"""
    from repair_app.tests.mocks.license_mock import create_mock_license_env
    env = create_mock_license_env(tmp_license_dir, days_valid=-1)
    monkeypatch.setattr(
        "repair_app.utils.license_manager.get_config_dir",
        lambda: tmp_license_dir,
    )
    yield env


# ============================================================
# 覆盖率配置（pytest-cov）
# ============================================================
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """自动为慢测试添加 slow marker。"""
    slow_marker = pytest.mark.slow
    for item in items:
        # stress / performance 类自动标记为 slow
        if any(mark.name in ("stress", "performance") for mark in item.iter_markers()):
            item.add_marker(slow_marker)
