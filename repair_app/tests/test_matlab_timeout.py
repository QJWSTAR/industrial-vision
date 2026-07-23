"""test_matlab_timeout.py — Phase 2: MATLAB 超时测试"""
from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import MagicMock, patch, PropertyMock


class TestMatlabTimeoutExceptions:
    """测试超时异常类型。"""

    def test_matlab_call_timeout_error(self):
        from repair_app.bridge.communication.exceptions import MatlabCallTimeoutError
        exc = MatlabCallTimeoutError("test", timeout_s=60.0)
        assert exc.timeout_s == 60.0
        assert isinstance(exc, Exception)

    def test_matlab_engine_unhealthy_error(self):
        from repair_app.bridge.communication.exceptions import MatlabEngineUnhealthyError
        exc = MatlabEngineUnhealthyError("test", reason="timeout")
        assert exc.reason == "timeout"

    def test_matlab_recovery_error(self):
        from repair_app.bridge.communication.exceptions import MatlabRecoveryError
        exc = MatlabRecoveryError("test")
        assert isinstance(exc, Exception)


class TestMatlabEngineProxyTimeout:
    """测试 MatlabEngineProxy 超时行为。"""

    def test_proxy_has_call_timeout(self):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._call_timeout = 60.0
        assert proxy._call_timeout == 60.0

    def test_proxy_is_healthy_initially(self):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._connected = True
        proxy._unhealthy = False
        assert proxy.is_healthy

    def test_proxy_is_unhealthy_after_flag(self):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._connected = True
        proxy._unhealthy = True
        assert not proxy.is_healthy

    def test_check_healthy_raises_when_unhealthy(self):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        from repair_app.bridge.communication.exceptions import MatlabEngineUnhealthyError
        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._unhealthy = True
        with pytest.raises(MatlabEngineUnhealthyError):
            proxy._check_healthy()

    def test_check_healthy_passes_when_healthy(self):
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._connected = True
        proxy._unhealthy = False
        # Should not raise
        proxy._check_healthy()

    def test_call_with_timeout_timeout_marks_unhealthy(self):
        """模拟 timeout 场景：引擎被标记为 unhealthy。"""
        import concurrent.futures
        from unittest.mock import MagicMock
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy
        from repair_app.bridge.communication.exceptions import MatlabCallTimeoutError

        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._connected = True
        proxy._unhealthy = False
        proxy._call_timeout = 0.01  # 10ms timeout

        # Mock eng with a function that returns a Future
        mock_eng = MagicMock()
        mock_func = MagicMock()
        mock_future = MagicMock()
        mock_future.result.side_effect = concurrent.futures.TimeoutError()
        mock_func.return_value = mock_future
        mock_eng.run_path_planning = mock_func

        proxy._eng = mock_eng
        proxy._ensure_connected = MagicMock()
        proxy.disconnect = MagicMock()

        with pytest.raises(MatlabCallTimeoutError):
            proxy._call_with_timeout("run_path_planning", "test.stl", {}, nargout=4)

        assert proxy._unhealthy, "timeout 后应标记为 unhealthy"
        proxy.disconnect.assert_called()

    def test_call_with_timeout_success_clears_nothing(self):
        """正常返回不标记 unhealthy。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy

        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._connected = True
        proxy._unhealthy = False
        proxy._call_timeout = 60.0

        mock_eng = MagicMock()
        mock_func = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "success"
        mock_func.return_value = mock_future
        mock_eng.run_path_planning = mock_func

        proxy._eng = mock_eng
        proxy._ensure_connected = MagicMock()

        result = proxy._call_with_timeout("run_path_planning", "test.stl", {}, nargout=4)
        assert result == "success"
        assert not proxy._unhealthy, "成功调用不应标记 unhealthy"

    def test_recover_when_already_healthy(self):
        """recover() 在 healthy 时直接返回 True。"""
        from repair_app.bridge.adapters.matlab_engine_proxy import MatlabEngineProxy

        proxy = MatlabEngineProxy.__new__(MatlabEngineProxy)
        proxy._initialized = True
        proxy._unhealthy = False
        assert proxy.recover()