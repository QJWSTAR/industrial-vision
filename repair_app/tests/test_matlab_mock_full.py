"""test_matlab_mock_full.py — MATLAB Mock 与 Bridge 通信完整测试

被测模块:
  - repair_app/tests/mocks/matlab_mock.py: deterministic_algorithm /
    MockMatlabAdapter / make_mock_repair_request / make_empty_request
  - repair_app/bridge/adapters/matlab_engine_proxy.py: MatlabEngineProxy 单例
    （_is_running_in_matlab / _ensure_connected / __call__ /
     call_profile_prediction / call_full_pipeline / disconnect / reset_singleton）
  - repair_app/bridge/communication/exceptions.py: BridgeError 层次 +
    translate_zmq_error

运行: pytest -m mock -v test_matlab_mock_full.py

目标覆盖: MatlabEngineProxy 70%+, exceptions 80%+。
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest


def _make_future(result_or_exception):
    """创建一个模拟 FutureResult 对象，用于 mock MATLAB background=True 调用。

    Args:
        result_or_exception:
            - 如果是 Exception 实例，.result() 会抛出它
            - 否则 .result() 返回它
    """
    class _MockFuture:
        def __init__(self, value):
            self._value = value

        def result(self, timeout=None):
            if isinstance(self._value, Exception):
                raise self._value
            return self._value

        def cancel(self):
            return False

        def done(self):
            return True

    return _MockFuture(result_or_exception)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def mock_matlab_engine(monkeypatch):
    """Mock matlab.engine 模块 + 重置 MatlabEngineProxy 单例。

    通过 monkeypatch.setitem 注入 sys.modules，测试结束自动恢复。
    关键：mock_matlab.engine 必须显式指向 mock_me，否则 import matlab.engine
    在 matlab 也是 MagicMock 时会解析到 mock_matlab.engine 自动子 mock，
    而非 sys.modules["matlab.engine"]。
    """
    mock_me = MagicMock()
    mock_matlab = MagicMock()
    mock_matlab.engine = mock_me  # 关键：让属性访问与 sys.modules 返回同一 mock
    monkeypatch.setitem(sys.modules, "matlab", mock_matlab)
    monkeypatch.setitem(sys.modules, "matlab.engine", mock_me)

    from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
    MatlabEngineProxy.reset_singleton()
    yield mock_me, mock_matlab
    MatlabEngineProxy.reset_singleton()


@pytest.fixture
def mock_zmq(monkeypatch):
    """Mock zmq 模块（含 Again / ZMQError 异常类）用于 translate_zmq_error 测试。"""

    class Again(Exception):
        def __init__(self, msg: str = "", **kwargs):
            super().__init__(msg)
            self._attrs = kwargs

        def get(self, key, default=None):
            return self._attrs.get(key, default)

    class ZMQError(Exception):
        pass

    mock = ModuleType("zmq")
    mock.Again = Again
    mock.ZMQError = ZMQError
    monkeypatch.setitem(sys.modules, "zmq", mock)
    return mock


def _clear_matlab_env(monkeypatch):
    """清除影响连接策略的环境变量。"""
    for var in ("CSAM_BRIDGE_IN_MATLAB", "CSAM_ALGORITHM_ENGINE", "CSAM_MATLAB_ALLOW_STANDALONE"):
        monkeypatch.delenv(var, raising=False)


# ============================================================
# 1. MATLAB Mock 体系测试 (matlab_mock.py)
# ============================================================
@pytest.mark.mock
class TestMatlabMockFull:
    """MATLAB Mock 体系完整测试。"""

    # ---- Mock 引擎连接 ----
    def test_mock_adapter_no_engine_required(self):
        """MockMatlabAdapter 构造不依赖 matlab.engine。"""
        from repair_app.tests.mocks.matlab_mock import MockMatlabAdapter
        adapter = MockMatlabAdapter()
        assert adapter.call_count == 0
        assert adapter.calls == []
        assert adapter.SERVICE_VERSION == "mock-matlab-1.0.0"

    def test_mock_adapter_custom_algorithm_fn(self):
        """自定义 algorithm_fn 被正确调用。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        called = {"count": 0}

        def custom_algo(xyz, meta):
            called["count"] += 1
            return np.zeros((5, 3), dtype=np.float32)

        adapter = MockMatlabAdapter(algorithm_fn=custom_algo)
        req = make_mock_repair_request(n_points=10)
        result = adapter.handle_repair(req)
        assert called["count"] == 1
        assert result["waypoints"].shape == (5, 3)
        assert result["waypoint_count"] == 5

    # ---- Mock 路径规划返回航点 ----
    def test_path_planning_returns_waypoints(self):
        """handle_repair 路径规划返回 10x10 网格航点。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        req = make_mock_repair_request(n_points=50, request_id="pp-001")
        result = adapter.handle_repair(req)

        assert result["status_code"] == 0
        assert result["error_message"] == ""
        assert result["request_id"] == "pp-001"
        assert result["waypoints"].shape == (100, 3)
        assert result["waypoint_count"] == 100
        assert result["point_count"] == 50
        assert result["compute_time_ms"] >= 0.0
        # call_count 与 calls 记录
        assert adapter.call_count == 1
        assert len(adapter.calls) == 1
        assert adapter.calls[0]["request_id"] == "pp-001"
        assert adapter.calls[0]["point_count"] == 50

    # ---- Mock 形貌预测返回修复点云 ----
    def test_profile_prediction_returns_repair_cloud(self):
        """自定义算法函数模拟形貌预测，返回修复点云（高于原始 Z）。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )

        def profile_algorithm(xyz, meta):
            z_max = float(np.max(xyz[:, 2]))
            n = len(xyz)
            repair_z = z_max + 1.5  # 修复层在原始最高点上方 1.5mm
            return np.column_stack([
                xyz[:, 0], xyz[:, 1], np.full(n, repair_z, dtype=np.float32),
            ]).astype(np.float32)

        adapter = MockMatlabAdapter(algorithm_fn=profile_algorithm)
        req = make_mock_repair_request(n_points=30)
        result = adapter.handle_repair(req)

        assert result["status_code"] == 0
        repair_cloud = result["waypoints"]
        assert repair_cloud.shape == (30, 3)
        # 原始 Z 最大值
        orig_xyz = np.column_stack([req.x, req.y, req.z])
        orig_z_max = float(np.max(orig_xyz[:, 2]))
        # 修复点云 Z 应全部高于原始最大 Z
        assert np.all(repair_cloud[:, 2] > orig_z_max)
        assert np.all(repair_cloud[:, 2] == orig_z_max + 1.5)

    # ---- Mock 完整管线 ----
    def test_full_pipeline_chained(self):
        """完整管线：路径规划 + 形貌预测链式调用（两次 handle_repair）。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()

        # 阶段 1：路径规划
        req1 = make_mock_repair_request(n_points=20, request_id="stage-1")
        pp_result = adapter.handle_repair(req1)
        assert pp_result["status_code"] == 0
        waypoints = pp_result["waypoints"]
        assert len(waypoints) == 100

        # 阶段 2：形貌预测（用路径规划输出作为输入）
        req2 = make_mock_repair_request(n_points=100, request_id="stage-2")
        morph_result = adapter.handle_repair(req2)
        assert morph_result["status_code"] == 0
        assert len(morph_result["waypoints"]) == 100

        # 两次调用均被记录
        assert adapter.call_count == 2
        assert len(adapter.calls) == 2
        assert adapter.calls[0]["request_id"] == "stage-1"
        assert adapter.calls[1]["request_id"] == "stage-2"

    def test_latency_simulation(self):
        """latency_ms 参数模拟延迟。"""
        import time
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter(latency_ms=50)
        req = make_mock_repair_request(n_points=10)
        t0 = time.time()
        adapter.handle_repair(req)
        elapsed_ms = (time.time() - t0) * 1000.0
        assert elapsed_ms >= 40.0  # 允许 10ms 误差

    def test_check_health_fields(self):
        """check_health 返回完整字段。"""
        from repair_app.tests.mocks.matlab_mock import MockMatlabAdapter
        adapter = MockMatlabAdapter()
        health = adapter.check_health()
        assert health["status"] == "OK"
        assert health["service_version"] == "mock-matlab-1.0.0"
        assert health["memory_usage_mb"] == 128.0
        assert health["uptime_s"] == 60.0
        assert health["pending_requests"] == 0

    def test_shutdown_blocks_handle_repair(self):
        """shutdown 后 handle_repair 抛 RuntimeError。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        adapter.shutdown()
        req = make_mock_repair_request(n_points=10)
        with pytest.raises(RuntimeError, match="已关闭"):
            adapter.handle_repair(req)

    def test_empty_request_returns_error_status(self):
        """空点云请求返回 status_code=1。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_empty_request,
        )
        adapter = MockMatlabAdapter()
        result = adapter.handle_repair(make_empty_request("empty-1"))
        assert result["status_code"] == 1
        assert len(result["waypoints"]) == 0
        assert "空点云" in result["error_message"]
        assert result["request_id"] == "empty-1"


@pytest.mark.mock
class TestDeterministicAlgorithmFull:
    """deterministic_algorithm 确定性算法测试。"""

    def test_returns_100_grid_points(self):
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[0, 0, 0], [10, 10, 5]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        assert result.shape == (100, 3)
        assert result.dtype == np.float32

    def test_z_is_max_z_plus_two(self):
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[0, 0, 0], [10, 10, 5]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        expected_z = float(np.max(xyz[:, 2])) + 2.0
        assert np.all(result[:, 2] == expected_z)

    def test_deterministic_same_output(self):
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        rng = np.random.default_rng(99)
        xyz = rng.uniform(-5, 5, (20, 3)).astype(np.float32)
        r1 = deterministic_algorithm(xyz, {})
        r2 = deterministic_algorithm(xyz, {})
        assert np.array_equal(r1, r2)

    def test_zigzag_scan_pattern(self):
        """Zig-Zag 扫描：奇偶行 X 方向相反。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[0, 0, 0], [9, 9, 0]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        # 10 点/行，第一行（i=0）X 递增，第二行（i=1）X 递减
        row0 = result[0:10]
        row1 = result[10:20]
        assert row0[0, 0] < row0[-1, 0]   # 递增
        assert row1[0, 0] > row1[-1, 0]   # 递减

    def test_empty_input_returns_empty(self):
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        result = deterministic_algorithm(np.zeros((0, 3), dtype=np.float32), {})
        assert result.shape == (0, 3)


# ============================================================
# 2. MatlabEngineProxy 测试
# ============================================================
@pytest.mark.mock
class TestMatlabEngineProxyIsRunningInMatlab:
    """_is_running_in_matlab 检测测试。"""

    def test_false_by_default(self, mock_matlab_engine, monkeypatch):
        _clear_matlab_env(monkeypatch)
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        assert proxy._is_running_in_matlab() is False

    def test_true_when_env_set(self, mock_matlab_engine, monkeypatch):
        monkeypatch.setenv("CSAM_BRIDGE_IN_MATLAB", "1")
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        assert proxy._is_running_in_matlab() is True

    def test_false_when_env_zero(self, mock_matlab_engine, monkeypatch):
        monkeypatch.setenv("CSAM_BRIDGE_IN_MATLAB", "0")
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        assert proxy._is_running_in_matlab() is False


@pytest.mark.mock
class TestMatlabEngineProxyEnsureConnected:
    """_ensure_connected 连接策略测试（4 种策略 + 失败）。"""

    # 策略 1：pyenv 宿主模式
    def test_connect_pyenv_mode(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        monkeypatch.setenv("CSAM_BRIDGE_IN_MATLAB", "1")
        mock_eng = MagicMock()
        mock_me.connect_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        proxy._ensure_connected()

        assert proxy._connected is True
        assert proxy._eng is mock_eng
        assert proxy._started_independently is False
        mock_me.connect_matlab.assert_called_once_with()
        # find_matlab 不应被调用（pyenv 模式跳过）
        mock_me.find_matlab.assert_not_called()

    def test_pyenv_mode_fallthrough_on_failure(self, mock_matlab_engine, monkeypatch):
        """pyenv 模式连接失败时降级到策略 2。"""
        mock_me, _ = mock_matlab_engine
        monkeypatch.setenv("CSAM_BRIDGE_IN_MATLAB", "1")
        mock_me.connect_matlab.side_effect = RuntimeError("pyenv fail")
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_eng = MagicMock()
        # 第二次调用（带名称）返回 mock_eng
        mock_me.connect_matlab.side_effect = [RuntimeError("pyenv fail"), mock_eng]

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()
        assert proxy._connected is True
        assert proxy._eng is mock_eng

    # 策略 2：外部模式按名称查找共享会话
    def test_connect_shared_session_by_name(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge", "other"]
        mock_me.connect_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(shared_name="matlab_bridge", connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()

        assert proxy._connected is True
        assert proxy._eng is mock_eng
        mock_me.connect_matlab.assert_called_with("matlab_bridge")

    def test_shared_name_not_found_retries_then_default(self, mock_matlab_engine, monkeypatch):
        """共享会话未找到 → 重试 → 降级到策略 3（默认会话）。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_me.find_matlab.return_value = ["other_session"]
        mock_eng = MagicMock()

        # 带名称调用抛异常，无参数调用返回 mock_eng
        def connect_side_effect(*args):
            if args:
                raise ConnectionError("not found")
            return mock_eng
        mock_me.connect_matlab.side_effect = connect_side_effect

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(shared_name="matlab_bridge", connect_retry=2, connect_interval_s=0)
        proxy._ensure_connected()

        assert proxy._connected is True
        assert proxy._eng is mock_eng

    # 策略 3：默认共享会话
    def test_connect_default_session(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_me.find_matlab.return_value = []
        mock_eng = MagicMock()
        mock_me.connect_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()

        assert proxy._connected is True
        assert proxy._eng is mock_eng
        mock_me.connect_matlab.assert_called_with()

    # 策略 4：独立启动
    def test_connect_standalone(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no session")
        mock_eng = MagicMock()
        mock_me.start_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()

        assert proxy._connected is True
        assert proxy._eng is mock_eng
        assert proxy._started_independently is True
        mock_me.start_matlab.assert_called_once()

    def test_standalone_addpath_called(self, mock_matlab_engine, monkeypatch, tmp_path):
        """独立启动时若 algo_dir 存在则调用 addpath。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no")
        mock_eng = MagicMock()
        mock_me.start_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        algo_dir = str(tmp_path)
        proxy = MatlabEngineProxy(algo_dir=algo_dir, connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()
        mock_eng.addpath.assert_called_once_with(algo_dir, nargout=0)

    # 全部失败 → EngineUnavailableError（auto 模式跳过独立启动）
    def test_all_fail_auto_mode_raises(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no session")

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        from repair_app.bridge.communication.exceptions import EngineUnavailableError
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        with pytest.raises(EngineUnavailableError):
            proxy._ensure_connected()

    # 独立启动也失败 → EngineUnavailableError
    def test_standalone_fail_raises(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no")
        mock_me.start_matlab.side_effect = RuntimeError("start failed")

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        from repair_app.bridge.communication.exceptions import EngineUnavailableError
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        with pytest.raises(EngineUnavailableError):
            proxy._ensure_connected()

    def test_already_connected_idempotent(self, mock_matlab_engine, monkeypatch):
        """已连接时再次调用 _ensure_connected 不重复连接。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        proxy._eng = MagicMock()
        proxy._connected = True
        proxy._ensure_connected()
        mock_me.connect_matlab.assert_not_called()
        mock_me.find_matlab.assert_not_called()


@pytest.mark.mock
class TestMatlabEngineProxyCall:
    """__call__ 路径规划测试。"""

    def test_call_returns_assembled_waypoints(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        pointlist = np.array([
            [0, 0, 1, 0, 0, 1],
            [1, 0, 1, 0, 0, 1],
            [1, 1, 1, 0, 0, 1],
        ], dtype=np.float32)
        feed_rates = np.array([300.0, 500.0, 500.0], dtype=np.float32)
        layer_indices = np.array([0, 0, 1], dtype=np.float32)
        meta_out = {"compute_time_s": 1.5}
        mock_eng.run_path_planning.return_value = _make_future((pointlist, feed_rates, layer_indices, meta_out))

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)

        xyz = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float32)
        meta = {"layer_height_mm": 2.0, "traversing_speed_mms": 500.0}
        waypoints = proxy(xyz, meta)

        assert waypoints.shape == (3, 8)
        assert waypoints.dtype == np.float32
        # x, y, z, nx, ny, nz, feed, layer
        assert waypoints[0, 0] == 0.0
        assert waypoints[1, 0] == 1.0
        assert waypoints[2, 2] == 1.0
        assert waypoints[0, 6] == 300.0  # feed
        assert waypoints[2, 7] == 1.0    # layer
        mock_eng.run_path_planning.assert_called_once()

    def test_call_cleans_temp_stl(self, mock_matlab_engine, monkeypatch):
        """__call__ 完成后清理临时 STL 文件。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        captured_paths = []
        pointlist = np.array([[0, 0, 1, 0, 0, 1]], dtype=np.float32)
        feed_rates = np.array([500.0], dtype=np.float32)
        layer_indices = np.array([0.0], dtype=np.float32)

        def capture(stl_path, params, nargout=4, **kwargs):
            captured_paths.append(stl_path)
            return _make_future((pointlist, feed_rates, layer_indices, {}))
        mock_eng.run_path_planning.side_effect = capture

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        proxy(xyz, {})

        assert len(captured_paths) == 1
        assert not os.path.exists(captured_paths[0]), "临时 STL 应被清理"

    def test_call_translates_meta_to_struct(self, mock_matlab_engine, monkeypatch):
        """__call__ 将 meta 转为 MATLAB struct 并传入 run_path_planning。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        mock_eng.run_path_planning.return_value = _make_future((
            np.zeros((1, 6), dtype=np.float32),
            np.array([500.0], dtype=np.float32),
            np.array([0.0], dtype=np.float32),
            {},
        ))

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        meta = {"layer_height_mm": 3.0, "traversing_speed_mms": 600.0}
        proxy(xyz, meta)

        call_args = mock_eng.run_path_planning.call_args
        params = call_args[0][1]  # 第二个位置参数
        assert params["layer_height"] == 3.0
        assert params["traversing_speed_mms"] == 600.0


@pytest.mark.mock
class TestMatlabEngineProxyProfilePrediction:
    """call_profile_prediction 形貌预测测试。"""

    def test_profile_prediction_returns_parsed_dict(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        raw = {
            "mesh": np.zeros((2, 9), dtype=np.float32),
            "substrate_triangles": np.zeros((1, 9), dtype=np.float32),
            "layer_profiles": np.zeros((3, 3), dtype=np.float32),
            "uniformity": 0.85,
            "estimated_mass_g": 12.5,
            "estimated_time_s": 30.0,
            "predicted_volume_mm3": 100.0,
            "compute_time_s": 2.5,
            "waypoint_count": 50,
            "warnings": ["low_uniformity"],
            "particle_distribution": {
                "px": np.zeros(5), "py": np.zeros(5),
                "vx": np.zeros(5), "vy": np.zeros(5), "vz": np.zeros(5),
                "vcr": np.zeros(5), "dep_efficiency": 0.6,
                "diameter": np.zeros(5), "temperature": np.zeros(5),
            },
        }
        mock_eng.run_profile_prediction.return_value = _make_future(raw)

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)

        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        meta = {"cfd_excel_path": "/tmp/cfd.xlsx", "num_layers": 3}
        result = proxy.call_profile_prediction(xyz, meta)

        assert isinstance(result, dict)
        assert result["uniformity"] == 0.85
        assert result["estimated_mass_g"] == 12.5
        assert result["waypoint_count"] == 50
        assert result["warnings"] == ["low_uniformity"]
        assert result["compute_time_s"] == 2.5
        assert result["particle_distribution"] is not None
        assert result["particle_distribution"]["dep_efficiency"] == 0.6
        # mesh (2, 9) → 二进制 STL bytes 非空
        assert len(result["mesh_stl_bytes"]) > 0

    def test_profile_prediction_empty_raw_uses_defaults(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng
        mock_eng.run_profile_prediction.return_value = _make_future({})

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        result = proxy.call_profile_prediction(xyz, {})

        # 默认值
        assert result["uniformity"] == 0.78
        assert result["estimated_mass_g"] == 0.0
        assert result["estimated_time_s"] == 0.0
        assert result["waypoint_count"] == 0
        assert result["warnings"] == []
        assert result["particle_distribution"] is None
        assert result["mesh_stl_bytes"] == b""

    def test_profile_prediction_cleans_temp_stl(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        captured = []
        def capture(stl_path, excel_path, params, nargout=1, **kwargs):
            captured.append(stl_path)
            return _make_future({})
        mock_eng.run_profile_prediction.side_effect = capture

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        proxy.call_profile_prediction(xyz, {"cfd_excel_path": "/tmp/x.xlsx"})

        assert len(captured) == 1
        assert not os.path.exists(captured[0])


@pytest.mark.mock
class TestMatlabEngineProxyFullPipeline:
    """call_full_pipeline 完整管线测试。"""

    def test_full_pipeline_returns_waypoints_and_profile(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        pointlist = np.array([
            [0, 0, 1, 0, 0, 1],
            [1, 0, 1, 0, 0, 1],
        ], dtype=np.float32)
        feed_rates = np.array([300.0, 500.0], dtype=np.float32)
        layer_indices = np.array([0, 1], dtype=np.float32)
        meta_out = {"compute_time_s": 1.0}
        mock_eng.run_path_planning.return_value = _make_future((pointlist, feed_rates, layer_indices, meta_out))

        raw_profile = {
            "uniformity": 0.9,
            "estimated_mass_g": 5.0,
            "compute_time_s": 3.0,
            "waypoint_count": 2,
            "mesh": np.zeros((1, 9), dtype=np.float32),
        }
        mock_eng.run_profile_prediction.return_value = _make_future(raw_profile)

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)

        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        meta = {"traversing_speed_mms": 500.0, "num_layers": 2}
        result = proxy.call_full_pipeline(xyz, meta)

        assert "waypoints" in result
        assert "layer_indices" in result
        assert result["waypoints"].shape == (2, 8)
        assert result["uniformity"] == 0.9
        assert result["estimated_mass_g"] == 5.0
        # layer_indices 返回 int32 ndarray
        assert result["layer_indices"].dtype == np.int32
        # 两个 MATLAB 函数均被调用
        mock_eng.run_path_planning.assert_called_once()
        mock_eng.run_profile_prediction.assert_called_once()

    def test_full_pipeline_cleans_temp_stl(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        captured = []
        pointlist = np.array([[0, 0, 1, 0, 0, 1]], dtype=np.float32)
        feed_rates = np.array([500.0], dtype=np.float32)
        layer_indices = np.array([0.0], dtype=np.float32)

        def capture_pp(stl_path, params, nargout=4, **kwargs):
            captured.append(stl_path)
            return _make_future((pointlist, feed_rates, layer_indices, {}))
        mock_eng.run_path_planning.side_effect = capture_pp
        mock_eng.run_profile_prediction.return_value = _make_future({})

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        proxy.call_full_pipeline(xyz, {})

        assert len(captured) == 1
        assert not os.path.exists(captured[0])


@pytest.mark.mock
class TestMatlabEngineProxyDisconnect:
    """disconnect / reset_singleton 测试。"""

    def test_disconnect_shared_session(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()
        assert proxy._connected is True

        proxy.disconnect()
        assert proxy._connected is False
        assert proxy._eng is None
        assert proxy._started_independently is False
        # 共享会话不调用 quit()
        mock_eng.quit.assert_not_called()

    def test_disconnect_standalone_calls_quit(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no")
        mock_eng = MagicMock()
        mock_me.start_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()
        assert proxy._started_independently is True

        proxy.disconnect()
        assert proxy._connected is False
        assert proxy._eng is None
        mock_eng.quit.assert_called_once()

    def test_disconnect_without_engine_no_error(self, mock_matlab_engine):
        """未连接时 disconnect 不抛异常。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        proxy.disconnect()  # 不应抛异常
        assert proxy._eng is None
        assert proxy._connected is False

    def test_disconnect_handles_quit_exception(self, mock_matlab_engine, monkeypatch):
        """quit() 抛异常时 disconnect 捕获并清理状态。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        mock_me.find_matlab.return_value = []
        mock_me.connect_matlab.side_effect = ConnectionError("no")
        mock_eng = MagicMock()
        mock_eng.quit.side_effect = RuntimeError("quit failed")
        mock_me.start_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()
        # 不应抛异常
        proxy.disconnect()
        assert proxy._eng is None
        assert proxy._connected is False

    def test_reset_singleton_clears_instance(self, mock_matlab_engine, monkeypatch):
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = MagicMock()

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()

        MatlabEngineProxy.reset_singleton()
        assert MatlabEngineProxy._instance is None

        # 新实例应为全新状态
        proxy2 = MatlabEngineProxy()
        assert proxy2._connected is False
        assert proxy2._eng is None

    def test_singleton_returns_same_instance(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        p1 = MatlabEngineProxy()
        p2 = MatlabEngineProxy()
        assert p1 is p2

    def test_reset_disconnects_existing(self, mock_matlab_engine, monkeypatch):
        """reset_singleton 调用 disconnect 释放旧连接。"""
        mock_me, _ = mock_matlab_engine
        _clear_matlab_env(monkeypatch)
        mock_eng = MagicMock()
        mock_me.find_matlab.return_value = ["matlab_bridge"]
        mock_me.connect_matlab.return_value = mock_eng

        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy(connect_retry=1, connect_interval_s=0)
        proxy._ensure_connected()

        MatlabEngineProxy.reset_singleton()
        # 旧实例已被 disconnect
        assert proxy._eng is None
        assert proxy._connected is False


@pytest.mark.mock
class TestMatlabEngineProxyDataConversion:
    """数据转换辅助方法测试。"""

    def test_assemble_waypoints_normal(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        pointlist = np.array([[1, 2, 3, 0, 0, 1], [4, 5, 6, 0, 0, 1]], dtype=np.float32)
        feeds = np.array([100.0, 200.0], dtype=np.float32)
        layers = np.array([0.0, 1.0], dtype=np.float32)
        wp = MatlabEngineProxy._assemble_waypoints(pointlist, feeds, layers)
        assert wp.shape == (2, 8)
        assert wp[0, 0] == 1.0 and wp[0, 1] == 2.0 and wp[0, 2] == 3.0
        assert wp[1, 5] == 1.0  # nz
        assert wp[0, 6] == 100.0  # feed
        assert wp[1, 7] == 1.0    # layer

    def test_assemble_waypoints_transposed(self, mock_matlab_engine):
        """MATLAB 列优先导致 (6, M) 形状应被转置为 (M, 6)。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        pointlist = np.array([
            [1, 4], [2, 5], [3, 6], [0, 0], [0, 0], [1, 1]
        ], dtype=np.float32)
        feeds = np.array([100.0, 200.0], dtype=np.float32)
        layers = np.array([0.0, 1.0], dtype=np.float32)
        wp = MatlabEngineProxy._assemble_waypoints(pointlist, feeds, layers)
        assert wp.shape == (2, 8)
        assert wp[0, 0] == 1.0
        assert wp[1, 0] == 4.0

    def test_assemble_waypoints_single_row(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        pointlist = np.array([1, 2, 3, 0, 0, 1], dtype=np.float32)  # 1D
        feeds = np.array([500.0], dtype=np.float32)
        layers = np.array([0.0], dtype=np.float32)
        wp = MatlabEngineProxy._assemble_waypoints(pointlist, feeds, layers)
        assert wp.shape == (1, 8)

    def test_assemble_waypoints_mismatched_feed_length(self, mock_matlab_engine):
        """feed_rates 长度不匹配时截取或补零。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        pointlist = np.array([[1, 2, 3, 0, 0, 1], [4, 5, 6, 0, 0, 1]], dtype=np.float32)
        feeds = np.array([100.0], dtype=np.float32)  # 仅 1 个，但需要 2 个
        layers = np.array([0.0, 1.0], dtype=np.float32)
        wp = MatlabEngineProxy._assemble_waypoints(pointlist, feeds, layers)
        assert wp.shape == (2, 8)

    def test_meta_to_matlab_struct_defaults(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        struct = proxy._meta_to_matlab_struct({})
        assert struct["base_plane"] == 5.0
        assert struct["layer_height"] == 2.0
        assert struct["buffer_additive"] == 2.0
        assert struct["scanning_angle"] == -45.0
        assert struct["traversing_speed_mms"] == 500.0
        assert struct["tilt_angle"] == 60.0

    def test_meta_to_matlab_struct_custom(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        meta = {"layer_height_mm": 3.0, "traversing_speed_mms": 600.0, "tilt_angle_deg": 45.0}
        struct = proxy._meta_to_matlab_struct(meta)
        assert struct["layer_height"] == 3.0
        assert struct["traversing_speed_mms"] == 600.0
        assert struct["tilt_angle"] == 45.0

    def test_meta_to_matlab_struct_invalid_uses_default(self, mock_matlab_engine):
        """非法值降级为默认值。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        struct = proxy._meta_to_matlab_struct({"layer_height_mm": "invalid"})
        assert struct["layer_height"] == 2.0  # 默认

    def test_meta_to_profile_params(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy()
        params = proxy._meta_to_profile_params({
            "standoff_distance_mm": 25.0,
            "num_layers": 5,
            "request_id": "req-123",
            "particle_size_um": 30.0,
        })
        assert params["standoff_distance_mm"] == 25.0
        assert params["num_layers"] == 5.0
        assert params["request_id"] == "req-123"
        assert params["particle_size_um"] == 30.0
        # 默认值
        assert params["nozzle_diameter_mm"] == 6.0
        assert params["material_density_gcm3"] == 7.99

    def test_parse_profile_result_with_particle_dist(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        raw = {
            "mesh": np.array([[0, 0, 0, 1, 0, 0, 1, 1, 0]], dtype=np.float32),
            "particle_distribution": {
                "px": [1, 2], "py": [3, 4],
                "dep_efficiency": 0.7,
            },
            "uniformity": 0.8,
        }
        result = MatlabEngineProxy._parse_profile_result(raw)
        assert result["uniformity"] == 0.8
        assert result["particle_distribution"]["dep_efficiency"] == 0.7
        assert len(result["mesh_stl_bytes"]) > 0

    def test_parse_profile_result_empty_mesh_stl(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        raw = {"mesh": np.zeros((0, 9), dtype=np.float32)}
        result = MatlabEngineProxy._parse_profile_result(raw)
        assert result["mesh_stl_bytes"] == b""

    def test_write_xyz_as_stl_creates_file(self, mock_matlab_engine, tmp_path):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        stl_path = MatlabEngineProxy._write_xyz_as_stl(xyz)
        try:
            assert os.path.exists(stl_path)
            with open(stl_path, "r") as f:
                content = f.read()
            assert "solid" in content
            assert "endsolid" in content
        finally:
            os.remove(stl_path)

    def test_write_xyz_as_stl_too_few_points(self, mock_matlab_engine):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        xyz = np.array([[0, 0, 0]], dtype=np.float32)
        with pytest.raises(ValueError, match="点云太少"):
            MatlabEngineProxy._write_xyz_as_stl(xyz)


# ============================================================
# 3. Bridge 异常测试 (exceptions.py)
# ============================================================
@pytest.mark.mock
class TestBridgeExceptions:
    """Bridge 异常层次结构测试。"""

    def test_bridge_error_base(self):
        from repair_app.bridge.communication.exceptions import BridgeError
        err = BridgeError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"
        assert err.request_id == ""

    def test_bridge_error_with_request_id(self):
        from repair_app.bridge.communication.exceptions import BridgeError
        err = BridgeError("test", request_id="req-1")
        assert "[req-1]" in str(err)
        assert err.request_id == "req-1"

    def test_bridge_error_empty_request_id(self):
        from repair_app.bridge.communication.exceptions import BridgeError
        err = BridgeError("msg")
        assert str(err) == "msg"

    def test_connection_error_is_bridge_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, ConnectionError as BridgeConnectionError,
        )
        err = BridgeConnectionError("conn fail")
        assert isinstance(err, BridgeError)

    def test_connection_error_with_request_id(self):
        from repair_app.bridge.communication.exceptions import (
            ConnectionError as BridgeConnectionError,
        )
        err = BridgeConnectionError("fail", request_id="r-2")
        assert err.request_id == "r-2"
        assert "[r-2]" in str(err)

    def test_connection_timeout_error(self):
        from repair_app.bridge.communication.exceptions import (
            ConnectionError as BridgeConnectionError,
            ConnectionTimeoutError,
        )
        err = ConnectionTimeoutError("timeout", timeout_ms=5000)
        assert isinstance(err, BridgeConnectionError)
        assert err.timeout_ms == 5000

    def test_connection_timeout_default_message(self):
        from repair_app.bridge.communication.exceptions import ConnectionTimeoutError
        err = ConnectionTimeoutError()
        assert err.timeout_ms == 0
        assert "超时" in str(err)

    def test_connection_timeout_with_request_id(self):
        from repair_app.bridge.communication.exceptions import ConnectionTimeoutError
        err = ConnectionTimeoutError("t/o", timeout_ms=1000, request_id="r-3")
        assert err.timeout_ms == 1000
        assert err.request_id == "r-3"

    def test_engine_unavailable_error(self):
        from repair_app.bridge.communication.exceptions import (
            ConnectionError as BridgeConnectionError,
            EngineUnavailableError,
        )
        err = EngineUnavailableError("no engine")
        assert isinstance(err, BridgeConnectionError)

    def test_engine_crash_error_is_engine_unavailable(self):
        from repair_app.bridge.communication.exceptions import (
            EngineUnavailableError, EngineCrashError,
        )
        err = EngineCrashError("crash")
        assert isinstance(err, EngineUnavailableError)

    def test_serialization_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, SerializationError,
        )
        err = SerializationError("serialize fail")
        assert isinstance(err, BridgeError)

    def test_shutdown_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, ShutdownError,
        )
        err = ShutdownError("shutting down")
        assert isinstance(err, BridgeError)

    def test_invalid_parameter_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, InvalidParameterError,
        )
        err = InvalidParameterError("bad param", parameter="layer_height")
        assert isinstance(err, BridgeError)
        assert err.parameter == "layer_height"

    def test_algorithm_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, AlgorithmError,
        )
        err = AlgorithmError("algo fail", algorithm="run_path_planning")
        assert isinstance(err, BridgeError)
        assert err.algorithm == "run_path_planning"

    def test_algorithm_error_default_message(self):
        from repair_app.bridge.communication.exceptions import AlgorithmError
        err = AlgorithmError()
        assert "MATLAB" in str(err)

    def test_protocol_error(self):
        from repair_app.bridge.communication.exceptions import (
            BridgeError, ProtocolError,
        )
        err = ProtocolError(
            "version mismatch",
            expected_version="2.1", actual_version="2.0",
        )
        assert isinstance(err, BridgeError)
        assert err.expected_version == "2.1"
        assert err.actual_version == "2.0"

    def test_exception_hierarchy_chain(self):
        """EngineCrashError → EngineUnavailableError → ConnectionError → BridgeError。"""
        from repair_app.bridge.communication.exceptions import (
            BridgeError, ConnectionError as BridgeConnectionError,
            EngineUnavailableError, EngineCrashError,
        )
        err = EngineCrashError("crash")
        assert isinstance(err, EngineUnavailableError)
        assert isinstance(err, BridgeConnectionError)
        assert isinstance(err, BridgeError)


@pytest.mark.mock
class TestTranslateZmqError:
    """translate_zmq_error 函数测试。"""

    def test_translates_zmq_again_to_timeout(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, ConnectionTimeoutError,
        )
        exc = mock_zmq.Again("recv again", timeout=3000)
        result = translate_zmq_error(exc, request_id="req-1")
        assert isinstance(result, ConnectionTimeoutError)
        assert result.timeout_ms == 3000
        assert result.request_id == "req-1"

    def test_translates_zmq_again_without_get_attr(self, mock_zmq):
        """zmq.Again 无 get 方法时 timeout_ms=0。"""
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, ConnectionTimeoutError,
        )

        class AgainNoGet(Exception):
            pass

        mock_zmq.Again = AgainNoGet
        exc = AgainNoGet("again")
        result = translate_zmq_error(exc)
        assert isinstance(result, ConnectionTimeoutError)
        assert result.timeout_ms == 0

    def test_translates_zmq_error_to_connection_error(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, ConnectionError as BridgeConnectionError,
        )
        exc = mock_zmq.ZMQError("zmq error")
        result = translate_zmq_error(exc, request_id="r-5")
        assert isinstance(result, BridgeConnectionError)
        assert result.request_id == "r-5"

    def test_translates_value_error_to_invalid_parameter(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, InvalidParameterError,
        )
        exc = ValueError("bad value")
        result = translate_zmq_error(exc)
        assert isinstance(result, InvalidParameterError)

    def test_translates_type_error_to_invalid_parameter(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, InvalidParameterError,
        )
        exc = TypeError("bad type")
        result = translate_zmq_error(exc)
        assert isinstance(result, InvalidParameterError)

    def test_passes_through_bridge_error(self, mock_zmq):
        """BridgeError 子类直接返回原异常。"""
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, ShutdownError,
        )
        exc = ShutdownError("shutdown")
        result = translate_zmq_error(exc)
        assert result is exc

    def test_translates_unknown_to_bridge_error(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, BridgeError,
        )
        exc = RuntimeError("unknown")
        result = translate_zmq_error(exc, request_id="r-9")
        assert isinstance(result, BridgeError)
        assert not isinstance(result, type(exc))
        assert result.request_id == "r-9"

    def test_translate_preserves_request_id(self, mock_zmq):
        from repair_app.bridge.communication.exceptions import (
            translate_zmq_error, ConnectionError as BridgeConnectionError,
        )
        exc = mock_zmq.ZMQError("err")
        result = translate_zmq_error(exc, request_id="preserve-1")
        assert result.request_id == "preserve-1"
