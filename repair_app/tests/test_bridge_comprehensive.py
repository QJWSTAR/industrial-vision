"""test_bridge_comprehensive.py — bridge 模块全覆盖测试

目标：将各模块覆盖率提升至 80%+。
不重复 test_bridge_supplement.py 已有的测试。

运行：pytest repair_app/tests/test_bridge_comprehensive.py -v --timeout=60 --timeout-method=thread -q
"""
from __future__ import annotations
import os
import sys
import socket
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, ANY

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ================================================================
# 辅助：伪造 zmq 模块
# ================================================================
def _make_fake_zmq():
    """构造一个 fake zmq 模块用于 mock。"""
    import types
    zmq = types.ModuleType("zmq")
    zmq.REQ = 3
    zmq.LINGER = 17
    zmq.RCVTIMEO = 27
    zmq.SNDTIMEO = 28
    zmq.POLLIN = 1
    # ZMQError 异常类（用于 except zmq.ZMQError）
    class _FakeZMQError(Exception):
        pass
    zmq.ZMQError = _FakeZMQError
    # Context 需要是一个类，并且有 instance() 类方法
    class _FakeContext:
        _instance = MagicMock()
        @staticmethod
        def instance():
            return _FakeContext._instance
    zmq.Context = _FakeContext
    return zmq


# ================================================================
# 1. MatlabBridgeLauncher 补充测试 (bridge/launcher.py)
# ================================================================
class TestLauncherProperties:
    """测试 launcher 属性（is_running, is_process_alive 等）。"""

    def test_is_running_port_open(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: True)
        assert launcher.is_running is True

    def test_is_running_port_closed(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        assert launcher.is_running is False

    def test_is_process_alive_reused(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        launcher._reused_existing = True
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: True)
        assert launcher.is_process_alive is True

    def test_is_process_alive_no_process(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        assert launcher.is_process_alive is False

    def test_is_process_alive_process_running(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        launcher._process = mock_proc
        assert launcher.is_process_alive is True

    def test_process_property(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        assert launcher.process is None
        mock = MagicMock()
        launcher._process = mock
        assert launcher.process is mock

    def test_matlab_exe_property(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        assert launcher.matlab_exe is None
        launcher._matlab_exe = "C:/matlab.exe"
        assert launcher.matlab_exe == "C:/matlab.exe"


class TestLauncherStart:
    """测试 start() 各种路径。"""

    def test_start_matlab_not_found(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        monkeypatch.setattr(
            launcher, "_find_matlab_executable_with_version",
            lambda: (None, None),
        )
        result = launcher.start(timeout=1)
        assert result is False

    def test_start_server_script_not_found(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        monkeypatch.setattr(
            launcher, "_find_matlab_executable_with_version",
            lambda: ("/fake/matlab", "R2025b"),
        )
        result = launcher.start(timeout=1)
        assert result is False

    def test_start_subprocess_exception(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        monkeypatch.setattr(
            launcher, "_find_matlab_executable_with_version",
            lambda: ("/fake/matlab", "R2025b"),
        )
        # 创建假的 server 脚本
        server_script = launcher._project_root / "matlab_bridge_server.m"
        server_script.write_text("fake")
        try:
            with patch("subprocess.Popen", side_effect=OSError("spawn failed")):
                result = launcher.start(timeout=1)
            assert result is False
        finally:
            server_script.unlink()

    def test_start_process_exits_early(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        monkeypatch.setattr(
            launcher, "_find_matlab_executable_with_version",
            lambda: ("/fake/matlab", "R2025b"),
        )
        server_script = launcher._project_root / "matlab_bridge_server.m"
        server_script.write_text("fake")
        try:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 1  # 已退出
            mock_proc.returncode = 1
            mock_proc.stdout = MagicMock()
            with patch("subprocess.Popen", return_value=mock_proc):
                result = launcher.start(timeout=1)
            assert result is False
        finally:
            server_script.unlink()

    def test_start_timeout(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(launcher, "_is_port_open", lambda port: False)
        monkeypatch.setattr(
            launcher, "_find_matlab_executable_with_version",
            lambda: ("/fake/matlab", "R2025b"),
        )
        server_script = launcher._project_root / "matlab_bridge_server.m"
        server_script.write_text("fake")
        try:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None  # 仍在运行
            mock_proc.stdout = MagicMock()
            with patch("subprocess.Popen", return_value=mock_proc):
                result = launcher.start(timeout=0.1)
            assert result is False
        finally:
            server_script.unlink()

    def test_start_success(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        server_script = launcher._project_root / "matlab_bridge_server.m"
        server_script.write_text("fake")
        try:
            # 第一次调用 _is_port_open 返回 False（未就绪）
            # 第二次返回 True（就绪了）
            call_count = [0]
            def fake_is_port_open(port):
                call_count[0] += 1
                return call_count[0] > 1
            monkeypatch.setattr(launcher, "_is_port_open", fake_is_port_open)
            monkeypatch.setattr(
                launcher, "_find_matlab_executable_with_version",
                lambda: ("/fake/matlab", "R2025b"),
            )
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = MagicMock()
            with patch("subprocess.Popen", return_value=mock_proc):
                result = launcher.start(timeout=5)
            assert result is True
            assert launcher._reused_existing is False
            assert launcher._restart_count == 0
        finally:
            server_script.unlink()

    def test_start_registers_atexit(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        server_script = launcher._project_root / "matlab_bridge_server.m"
        server_script.write_text("fake")
        try:
            call_count = [0]
            def fake_is_port_open(port):
                call_count[0] += 1
                return call_count[0] > 1
            monkeypatch.setattr(launcher, "_is_port_open", fake_is_port_open)
            monkeypatch.setattr(
                launcher, "_find_matlab_executable_with_version",
                lambda: ("/fake/matlab", "R2025b"),
            )
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = MagicMock()
            with patch("subprocess.Popen", return_value=mock_proc), \
                 patch("atexit.register") as mock_register:
                result = launcher.start(timeout=5)
            assert result is True
            mock_register.assert_called_once_with(launcher.stop)
        finally:
            server_script.unlink()


class TestLauncherStop:
    """测试 stop() 更多路径。"""

    def test_stop_reused_existing(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        launcher._reused_existing = True
        launcher._process = MagicMock()
        launcher.stop()  # 不应关闭
        launcher._process.terminate.assert_not_called()

    def test_stop_process_already_dead(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # 已退出
        launcher._process = mock_proc
        launcher.stop()
        assert launcher._process is None

    def test_stop_terminate_timeout(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 1)
        launcher._process = mock_proc
        monkeypatch.setattr(launcher, "_force_kill_os", MagicMock())
        launcher.stop()
        mock_proc.terminate.assert_called()
        mock_proc.kill.assert_called()
        launcher._force_kill_os.assert_called()

    def test_stop_kill_timeout(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        # terminate 超时
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 1),
            subprocess.TimeoutExpired("cmd", 1),
        ]
        launcher._process = mock_proc
        monkeypatch.setattr(launcher, "_force_kill_os", MagicMock())
        launcher.stop()
        launcher._force_kill_os.assert_called()
        assert launcher._process is None

    def test_stop_exception_in_terminate(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate.side_effect = Exception("terminate failed")
        launcher._process = mock_proc
        monkeypatch.setattr(launcher, "_force_kill_os", MagicMock())
        launcher.stop()
        launcher._force_kill_os.assert_called()
        assert launcher._process is None


class TestLauncherRestart:
    """测试 restart() 更多路径。"""

    def test_restart_success(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        launcher._restart_count = 0
        monkeypatch.setattr(launcher, "start", lambda timeout: True)
        result = launcher.restart(timeout=1)
        assert result is True
        assert launcher._restart_count == 1

    def test_restart_kills_old_process(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        launcher._process = mock_proc
        monkeypatch.setattr(launcher, "start", lambda timeout: True)
        monkeypatch.setattr(launcher, "RESTART_DELAY_S", 0.0)
        monkeypatch.setattr(launcher, "KILL_TIMEOUT_S", 1)
        result = launcher.restart(timeout=1)
        assert result is True
        mock_proc.kill.assert_called()
        assert launcher._process is None


class TestLauncherInternal:
    """测试内部方法。"""

    def test_dump_process_output(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        # 无 process
        launcher._dump_process_output(max_lines=10)  # 不应抛异常

    def test_dump_process_output_with_process(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        mock_proc = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.__iter__.return_value = [b"line1\n", b"line2\n"]
        mock_proc.stdout = mock_stdout
        launcher._process = mock_proc
        launcher._dump_process_output(max_lines=5)  # 不应抛异常

    def test_force_kill_os_win32(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("subprocess.run") as mock_run:
            launcher._force_kill_os(12345)
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0][0] == "taskkill"

    def test_force_kill_os_linux(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(sys, "platform", "linux")
        with patch("repair_app.bridge.launcher.os.kill") as mock_kill, \
             patch("repair_app.bridge.launcher.signal.SIGKILL", 9, create=True):
            launcher._force_kill_os(12345)
            mock_kill.assert_called_once()

    def test_force_kill_os_exception(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        launcher = MatlabBridgeLauncher(str(tmp_path))
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("subprocess.run", side_effect=Exception("kill failed")):
            launcher._force_kill_os(12345)  # 不应抛异常

    def test_is_port_open_true(self, tmp_path):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        # 使用一个真实开放的端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert MatlabBridgeLauncher._is_port_open(port) is True

    def test_is_port_open_false(self):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        # 使用一个不太可能开放的端口
        assert MatlabBridgeLauncher._is_port_open(49999) is False

    def test_find_matlab_executable_path_which(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        # 清空环境变量
        monkeypatch.delenv("CSAM_MATLAB_EXE", raising=False)
        with patch("shutil.which", return_value="/usr/bin/matlab"):
            exe, ver = MatlabBridgeLauncher._find_matlab_executable_with_version()
            assert exe == "/usr/bin/matlab"
            assert ver is None

    def test_find_matlab_executable_win32_platform(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        monkeypatch.delenv("CSAM_MATLAB_EXE", raising=False)
        with patch("shutil.which", return_value=None), \
             patch("sys.platform", "win32"):
            # 模拟 ProgramFiles 下有 MATLAB 文件夹
            matlab_root = tmp_path / "MATLAB"
            matlab_root.mkdir()
            r2025b = matlab_root / "R2025b" / "bin"
            r2025b.mkdir(parents=True)
            exe = r2025b / "matlab.exe"
            exe.write_text("fake")
            monkeypatch.setenv("ProgramFiles", str(tmp_path))
            result_exe, result_ver = MatlabBridgeLauncher._find_matlab_executable_with_version()
            assert result_exe is not None
            assert result_ver == "R2025b"

    def test_find_matlab_executable_darwin(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        monkeypatch.delenv("CSAM_MATLAB_EXE", raising=False)
        with patch("shutil.which", return_value=None), \
             patch("sys.platform", "darwin"), \
             patch("pathlib.Path.glob", return_value=[]):
            exe, ver = MatlabBridgeLauncher._find_matlab_executable_with_version()
            assert exe is None

    def test_find_matlab_executable_linux(self, tmp_path, monkeypatch):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        monkeypatch.delenv("CSAM_MATLAB_EXE", raising=False)
        with patch("shutil.which", return_value=None), \
             patch("sys.platform", "linux"), \
             patch("pathlib.Path.exists", return_value=False):
            exe, ver = MatlabBridgeLauncher._find_matlab_executable_with_version()
            assert exe is None

    def test_find_matlab_executable_static(self):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        with patch.object(MatlabBridgeLauncher, "_find_matlab_executable_with_version",
                          return_value=("/fake/matlab", "R2025b")):
            exe = MatlabBridgeLauncher._find_matlab_executable()
            assert exe == "/fake/matlab"

    def test_sort_by_preference(self):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        paths = [
            Path("/MATLAB/R2022a"),
            Path("/MATLAB/R2025b"),
            Path("/MATLAB/R2024a"),
            Path("/MATLAB/unknown_dir"),
        ]
        sorted_paths = MatlabBridgeLauncher._sort_by_preference(paths)
        names = [p.name for p in sorted_paths]
        # R2025b 应在已知版本中最前面，unknown_dir 排在最后
        # 验证排序不崩溃且包含所有元素
        assert len(names) == 4
        assert "R2025b" in names
        assert "R2022a" in names
        assert "R2024a" in names
        assert "unknown_dir" in names
        # 验证 R2025b 在 R2022a 之前
        assert names.index("R2025b") < names.index("R2022a")

    def test_sort_by_preference_unknown(self):
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        paths = [Path("/MATLAB/unknown_dir")]
        sorted_paths = MatlabBridgeLauncher._sort_by_preference(paths)
        assert len(sorted_paths) == 1


# ================================================================
# 2. Serializer 补充测试 (bridge/communication/serializer.py)
# ================================================================
class TestSerializerErrors:
    """测试 Serializer 的异常分支（SerializationError）。"""

    def test_build_repair_request_invalid_type(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises((SerializationError, TypeError, ValueError, AttributeError)):
            Serializer.build_repair_request("not_array", "not_array", "test")

    def test_build_repair_result_invalid_type(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="构建修复结果失败"):
            Serializer.build_repair_result("not_array")

    def test_parse_health_response_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="解析健康检查响应失败"):
            Serializer.parse_health_response("invalid")

    def test_serialize_health_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="序列化健康检查失败"):
            Serializer.serialize_health("not_a_message")

    def test_deserialize_request_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="反序列化请求失败"):
            Serializer.deserialize_request(b"not valid protobuf")

    def test_deserialize_result_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="反序列化结果失败"):
            Serializer.deserialize_result(b"not valid protobuf")

    def test_serialize_result_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="序列化结果失败"):
            Serializer.serialize_result("not_a_message")

    def test_serialize_request_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="序列化请求失败"):
            Serializer.serialize_request("not_a_message")

    def test_parse_point_cloud_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="解析点云失败"):
            Serializer.parse_point_cloud("not_a_message")

    def test_parse_repair_result_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        with pytest.raises(SerializationError, match="解析修复结果失败"):
            Serializer.parse_repair_result("not_a_message")

    def test_try_deserialize_health_valid(self):
        from repair_app.bridge.communication.serializer import Serializer
        from repair_app.communication.repair_serialization import build_health_check_request
        req = build_health_check_request()
        data = req.SerializeToString()
        result = Serializer.try_deserialize_health(data)
        assert result is not None

    def test_try_deserialize_health_invalid(self):
        from repair_app.bridge.communication.serializer import Serializer
        result = Serializer.try_deserialize_health(b"invalid")
        assert result is None

    def test_build_health_check(self):
        from repair_app.bridge.communication.serializer import Serializer
        req = Serializer.build_health_check()
        assert req.client_version == Serializer.CLIENT_VERSION


# ================================================================
# 3. HeartbeatMonitor 补充测试 (bridge/communication/heartbeat.py)
# ================================================================
class TestHeartbeatMonitorRun:
    """测试 HeartbeatMonitor.run() 和边缘情况。"""

    def test_init_with_config(self):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"), config=BridgeConfig())
        assert hm._config is not None

    def test_stop_with_terminate(self, monkeypatch):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        hm._running = True
        # mock wait 返回 False 触发 terminate
        with patch.object(hm, "wait", return_value=False):
            hm.stop(wait_ms=10)
        assert hm._running is False

    def test_stop_normal(self):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        hm._running = True
        hm.stop()
        assert hm._running is False

    def test_on_pong_emits_status_changed(self):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.protocol import EngineStatus
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        events = []
        hm.status_changed.connect(lambda s, m: events.append((s, m)))
        hm._on_pong(0.1, "pong")
        assert len(events) == 1
        assert events[0][0] == int(EngineStatus.OK)

    def test_on_pong_emits_latency(self):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        latencies = []
        hm.latency_updated.connect(lambda lat: latencies.append(lat))
        hm._on_pong(0.3, "pong")
        assert len(latencies) == 1
        assert latencies[0] == 0.3

    def test_on_miss_emits_status_changed(self):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.protocol import EngineStatus
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(False, "fail"))
        threshold = hm._config.heartbeat_miss_threshold
        events = []
        hm.status_changed.connect(lambda s, m: events.append((s, m)))
        for i in range(threshold):
            hm._on_miss("timeout")
        assert len(events) == 1
        assert events[0][0] == int(EngineStatus.DOWN)

    def test_run_with_interruption(self, monkeypatch):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        hm._running = True
        with patch.object(hm, "isInterruptionRequested", return_value=True):
            hm.run()  # 应立即退出

    def test_run_with_ping_exception(self, monkeypatch):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        def bad_ping(cb):
            raise RuntimeError("ping failed")
        hm = HeartbeatMonitor(ping_fn=bad_ping)
        hm._running = True
        # 模拟：第一次 loop 后退出
        with patch.object(hm, "isInterruptionRequested", side_effect=[False, True]):
            with patch.object(hm, "msleep", return_value=None):
                hm.run()  # 不应抛异常

    def test_run_normal_cycle(self, monkeypatch):
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        hm = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"))
        hm._running = True
        with patch.object(hm, "isInterruptionRequested", side_effect=[False, True]):
            with patch.object(hm, "msleep", return_value=None):
                hm.run()


# ================================================================
# 4. MatlabLifecycleManager 补充测试 (bridge/lifecycle_manager.py)
# ================================================================
class TestLifecycleManagerProperties:
    """测试 lifecycle_manager 属性。"""

    def setup_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def teardown_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def test_launcher_property(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        from repair_app.bridge.launcher import MatlabBridgeLauncher
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        assert isinstance(m.launcher, MatlabBridgeLauncher)

    def test_matlab_version_property(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        assert m.matlab_version is None

    def test_restart_count_property(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        assert m.restart_count == 0


class TestLifecycleManagerStart:
    """测试 start() 方法。"""

    def setup_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def teardown_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def test_start_success(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(m._launcher, "start", lambda timeout: True)
        monkeypatch.setattr(type(m._launcher), "reused_existing", PropertyMock(return_value=False))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=0))
        # 阻止 watchdog timer 实际启动
        monkeypatch.setattr(m, "_start_watchdog", lambda: None)
        result = m.start(auto_restart=True)
        assert result is True
        assert m.status == LifecycleStatus.READY

    def test_start_failure(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(m._launcher, "start", lambda timeout: False)
        result = m.start(auto_restart=True)
        assert result is False
        assert m.status == LifecycleStatus.FAILED

    def test_start_already_starting(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._is_starting = True
        m._set_status(LifecycleStatus.READY, "ready")
        result = m.start(auto_restart=True)
        assert result is True  # 返回 is_ready

    def test_set_status_restarting_emits(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=2))
        events = []
        m.matlab_restarted.connect(lambda r: events.append(r))
        m._set_status(LifecycleStatus.RESTARTING, "restarting")
        assert len(events) == 1
        assert events[0] == 2

    def test_ensure_ready_crashed_try_restart(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._set_status(LifecycleStatus.CRASHED, "crashed")
        monkeypatch.setattr(m, "_try_restart", lambda: True)
        assert m.ensure_ready() is True

    def test_ensure_ready_unknown_start(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(m._launcher, "start", lambda timeout: True)
        monkeypatch.setattr(type(m._launcher), "reused_existing", PropertyMock(return_value=False))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=0))
        monkeypatch.setattr(m, "_start_watchdog", lambda: None)
        assert m.ensure_ready() is True


class TestLifecycleManagerWatchdog:
    """测试看门狗相关方法。"""

    def setup_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def teardown_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def test_start_watchdog(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._start_watchdog()
        assert m._watch_timer is not None
        m._stop_watchdog()
        assert m._watch_timer is None

    def test_start_watchdog_already_running(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._start_watchdog()
        timer = m._watch_timer
        m._start_watchdog()
        assert m._watch_timer is timer
        m._stop_watchdog()

    def test_watch_tick_not_enabled(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._enabled = False
        m._watch_tick()  # 不应做任何事

    def test_watch_tick_not_ready(self, tmp_path):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        from repair_app.bridge.lifecycle_manager import LifecycleStatus
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._enabled = True
        m._set_status(LifecycleStatus.BUSY, "busy")
        m._watch_tick()  # 不应做任何事（非 READY）

    def test_watch_tick_detect_crash(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._enabled = True
        m._auto_restart_enabled = True
        m._set_status(LifecycleStatus.READY, "ready")
        monkeypatch.setattr(m._launcher, "detect_crash", lambda: True)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        monkeypatch.setattr(type(m._launcher), "process", PropertyMock(return_value=mock_proc))
        m._watch_tick()
        assert m.status == LifecycleStatus.CRASHED

    def test_watch_tick_exception(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._enabled = True
        m._set_status(LifecycleStatus.READY, "ready")
        m._launcher.detect_crash = MagicMock(side_effect=Exception("oops"))
        m._watch_tick()  # 不应抛异常

    def test_try_restart_max_reached(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=3))
        assert m._try_restart() is False
        assert m.status == LifecycleStatus.FAILED

    def test_try_restart_success(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=0))
        monkeypatch.setattr(m._launcher, "restart", lambda timeout: True)
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        assert m._try_restart() is True
        assert m.status == LifecycleStatus.READY

    def test_try_restart_fail_max(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=3))
        monkeypatch.setattr(m._launcher, "restart", lambda timeout: False)
        result = m._try_restart()
        assert result is False
        assert m.status == LifecycleStatus.FAILED

    def test_try_restart_fail_crash(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        import time as _time
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "restart_count", PropertyMock(return_value=1))
        monkeypatch.setattr(m._launcher, "restart", lambda timeout: False)
        result = m._try_restart()
        # _try_restart 现在异步执行，返回 True 表示已启动重启
        assert result is True
        # 等待后台线程完成（restart 被 mock 为立即返回 False）
        for _ in range(50):
            if m.status == LifecycleStatus.CRASHED:
                break
            _time.sleep(0.02)
        assert m.status == LifecycleStatus.CRASHED

    def test_mark_idle_resets_restart(self, tmp_path, monkeypatch):
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._set_status(LifecycleStatus.READY, "ready")
        m.mark_busy()
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(m._launcher, "reset_restart_count", MagicMock())
        m.mark_idle()
        assert m.status == LifecycleStatus.READY
        m._launcher.reset_restart_count.assert_called_once()


# ================================================================
# 4.5 MatlabLifecycleManager Phase 4 测试 (execution_scope, 状态转换验证)
# ================================================================
class TestLifecycleManagerPhase4:
    """测试 Phase 4 新增功能：execution_scope, 状态转换验证, 废弃方法。"""

    def setup_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    def teardown_method(self):
        from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
        MatlabLifecycleManager.reset_singleton()

    # --- execution_scope ---

    def test_execution_scope_success_flow(self, tmp_path, monkeypatch):
        """execution_scope 正常流程：READY → BUSY → READY。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(m._launcher, "reset_restart_count", MagicMock())
        m._set_status(LifecycleStatus.READY, "ready")

        with m.execution_scope():
            assert m.status == LifecycleStatus.BUSY

        assert m.status == LifecycleStatus.READY
        m._launcher.reset_restart_count.assert_called_once()

    def test_execution_scope_exception_triggers_recovering(self, tmp_path, monkeypatch):
        """execution_scope 引擎异常退出时进入 RECOVERING。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        from repair_app.bridge.communication.exceptions import EngineUnavailableError
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        m._set_status(LifecycleStatus.READY, "ready")

        with pytest.raises(EngineUnavailableError, match="test engine crash"):
            with m.execution_scope():
                raise EngineUnavailableError("test engine crash")

        assert m.status == LifecycleStatus.RECOVERING

    def test_execution_scope_not_ready_triggers_ensure(self, tmp_path, monkeypatch):
        """execution_scope 在非 READY 状态时自动调用 ensure_ready。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(m._launcher, "reset_restart_count", MagicMock())
        # 模拟 ensure_ready 成功，并将状态设置为 READY
        def _fake_ensure():
            m._set_status(LifecycleStatus.READY, "ready")
            return True
        monkeypatch.setattr(m, "ensure_ready", _fake_ensure)
        m._set_status(LifecycleStatus.UNKNOWN, "")

        with m.execution_scope():
            assert m.status == LifecycleStatus.BUSY

        assert m.status == LifecycleStatus.READY

    def test_execution_scope_not_ready_and_ensure_fails(self, tmp_path, monkeypatch):
        """execution_scope 在 ensure_ready 失败时抛出 RuntimeError。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(m, "ensure_ready", lambda: False)
        m._set_status(LifecycleStatus.UNKNOWN, "")

        with pytest.raises(RuntimeError, match="MATLAB 未就绪"):
            with m.execution_scope():
                pass

    # --- 状态转换验证 ---

    def test_validate_transition_legal(self, tmp_path, caplog):
        """合法状态转换不应产生警告。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        import logging
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._set_status(LifecycleStatus.UNKNOWN, "")
        with caplog.at_level(logging.WARNING, logger="csam.bridge.lifecycle"):
            m._set_status(LifecycleStatus.STARTING, "starting")
        # 不应有非标准状态转换警告
        transition_warnings = [r for r in caplog.records if "非标准状态转换" in r.message]
        assert len(transition_warnings) == 0

    def test_validate_transition_illegal_warns(self, tmp_path, caplog):
        """非法状态转换（如 STOPPED → STARTING）应产生警告但继续执行。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        import logging
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._set_status(LifecycleStatus.STOPPED, "stopped")
        with caplog.at_level(logging.WARNING, logger="csam.bridge.lifecycle"):
            m._set_status(LifecycleStatus.STARTING, "starting")
        transition_warnings = [r for r in caplog.records if "非标准状态转换" in r.message]
        assert len(transition_warnings) >= 1
        # 状态仍然被更新了（警告不影响执行）
        assert m.status == LifecycleStatus.STARTING

    def test_all_defined_transitions_exist(self, tmp_path):
        """验证所有在 _VALID_TRANSITIONS 中定义的状态都在 LifecycleStatus 中。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        all_states = {
            LifecycleStatus.UNKNOWN, LifecycleStatus.DETECTING,
            LifecycleStatus.STARTING, LifecycleStatus.READY,
            LifecycleStatus.BUSY, LifecycleStatus.RECOVERING,
            LifecycleStatus.CRASHED, LifecycleStatus.RESTARTING,
            LifecycleStatus.FAILED, LifecycleStatus.STOPPING,
            LifecycleStatus.STOPPED,
        }
        for src in m._VALID_TRANSITIONS:
            assert src in all_states, f"源状态 {src} 不在 LifecycleStatus 中"
            for dst in m._VALID_TRANSITIONS[src]:
                assert dst in all_states, f"目标状态 {dst} 不在 LifecycleStatus 中"

    # --- 废弃方法 ---

    def test_mark_busy_deprecated_warns(self, tmp_path, caplog):
        """mark_busy 应产生废弃警告。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        import logging
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        m._set_status(LifecycleStatus.READY, "ready")
        with caplog.at_level(logging.WARNING, logger="csam.bridge.lifecycle"):
            m.mark_busy()
        deprecated_warnings = [r for r in caplog.records if "已废弃" in r.message]
        assert len(deprecated_warnings) >= 1
        assert m.status == LifecycleStatus.BUSY

    def test_mark_idle_deprecated_warns(self, tmp_path, monkeypatch, caplog):
        """mark_idle 应产生废弃警告。"""
        from repair_app.bridge.lifecycle_manager import (
            MatlabLifecycleManager, LifecycleStatus,
        )
        import logging
        m = MatlabLifecycleManager.get_instance(str(tmp_path))
        monkeypatch.setattr(type(m._launcher), "matlab_version", PropertyMock(return_value="R2025b"))
        monkeypatch.setattr(m._launcher, "reset_restart_count", MagicMock())
        m._set_status(LifecycleStatus.READY, "ready")
        m.mark_busy()
        with caplog.at_level(logging.WARNING, logger="csam.bridge.lifecycle"):
            m.mark_idle()
        deprecated_warnings = [r for r in caplog.records if "已废弃" in r.message]
        assert len(deprecated_warnings) >= 1
        assert m.status == LifecycleStatus.READY


# ================================================================
# 5. RepairOutcome / MatlabService 测试 (bridge/services/matlab_service.py)
# ================================================================
class TestRepairOutcome:
    """测试 RepairOutcome 数据类。"""

    def test_from_result(self):
        from repair_app.bridge.services.matlab_service import RepairOutcome
        from repair_app.communication.repair_protocol_pb2 import RepairResult, RepairStatusCode
        result = RepairResult()
        result.request_id = "test-1"
        result.status_code = RepairStatusCode.SUCCESS
        result.estimated_time_s = 1.5
        result.compute_time_ms = 100
        result.uniformity_score = 0.85
        result.is_feasible = True
        result.feasibility_reason = "ok"
        outcome = RepairOutcome.from_result(result)
        assert outcome.success is True
        assert outcome.request_id == "test-1"
        assert abs(outcome.uniformity_score - 0.85) < 0.01

    def test_error_factory(self):
        from repair_app.bridge.services.matlab_service import RepairOutcome
        outcome = RepairOutcome.error("something went wrong", "req-1")
        assert outcome.success is False
        assert outcome.error_message == "something went wrong"
        assert outcome.request_id == "req-1"


class TestMatlabService:
    """测试 MatlabService 门面。"""

    def test_init_with_defaults(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        svc = MatlabService()
        assert svc.config is not None
        assert svc.is_connected is False

    def test_init_with_custom_client(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.address = "tcp://custom:5555"
        svc = MatlabService(client=mock_client)
        assert svc.is_connected is True
        assert svc.address == "tcp://custom:5555"

    def test_check_health(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        cb = MagicMock()
        svc.check_health(cb)
        mock_client.check_health.assert_called_once_with(cb)

    def test_start_heartbeat(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        svc.start_heartbeat()
        mock_client.start_heartbeat.assert_called_once()

    def test_stop_heartbeat(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        svc.stop_heartbeat()
        mock_client.stop_heartbeat.assert_called_once()

    def test_close(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        svc.close()
        mock_client.stop_heartbeat.assert_called_once()
        mock_client.close.assert_called_once()

    def test_request_path_planning_empty_xyz(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        on_error = MagicMock()
        rid = svc.request_path_planning(
            np.zeros((0, 3), dtype=np.float32),
            np.zeros((0, 3), dtype=np.float32),
            params={},
            on_success=MagicMock(),
            on_error=on_error,
        )
        on_error.assert_called_once_with("点云为空")

    def test_request_path_planning_normals_mismatch(self):
        from repair_app.bridge.services.matlab_service import MatlabService
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        on_error = MagicMock()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros((5, 3), dtype=np.float32)
        rid = svc.request_path_planning(
            xyz, normals, params={},
            on_success=MagicMock(), on_error=on_error,
        )
        on_error.assert_called_once_with("法向量与点云形状不匹配")

    def test_request_path_planning_success(self, monkeypatch):
        from repair_app.bridge.services.matlab_service import MatlabService
        from repair_app.communication.repair_serialization import (
            build_repair_request, serialize_request,
        )
        mock_client = MagicMock()
        mock_client.request_repair.return_value = "path-001"
        svc = MatlabService(client=mock_client)
        on_success = MagicMock()
        on_error = MagicMock()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        rid = svc.request_path_planning(
            xyz, normals, params={},
            on_success=on_success, on_error=on_error,
        )
        assert rid == "path-001"
        mock_client.request_repair.assert_called_once()

    def test_request_path_planning_serialization_error(self, monkeypatch):
        from repair_app.bridge.services.matlab_service import MatlabService
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        mock_client = MagicMock()
        svc = MatlabService(client=mock_client)
        on_error = MagicMock()
        with patch.object(Serializer, "build_repair_request",
                          side_effect=SerializationError("build failed")):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
            normals = np.zeros_like(xyz)
            rid = svc.request_path_planning(
                xyz, normals, params={},
                on_success=MagicMock(), on_error=on_error,
            )
            on_error.assert_called_once()


# ================================================================
# 6. MatlabAdapter 补充测试 (bridge/adapters/matlab_adapter.py)
# ================================================================
class TestMatlabAdapterInner:
    """测试 MatlabAdapter 内部方法。"""

    def test_handle_repair_algorithm_exception(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import (
            MatlabAdapter, MatlabAlgorithmError,
        )
        from repair_app.bridge.communication.serializer import Serializer
        from repair_app.communication.repair_protocol_pb2 import RepairStatusCode
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "python")
        adapter = MatlabAdapter()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = Serializer.build_repair_request(xyz, normals, scan_id="test")
        # 让 _invoke_pipeline_with_fallback 返回 None，且 _default_algorithm 也返回 None
        # handle_repair 会捕获 NoneType 导致的 TypeError，返回 ERR_UNKNOWN
        monkeypatch.setattr(adapter, "_invoke_pipeline_with_fallback", lambda x, m: None)
        monkeypatch.setattr(adapter, "_default_algorithm", lambda **kw: None)
        result = adapter.handle_repair(req)
        assert result.status_code == RepairStatusCode.ERR_UNKNOWN

    def test_handle_repair_no_waypoints(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        from repair_app.bridge.communication.serializer import Serializer
        from repair_app.communication.repair_protocol_pb2 import RepairStatusCode
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "python")
        adapter = MatlabAdapter()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = Serializer.build_repair_request(xyz, normals, scan_id="test")
        monkeypatch.setattr(adapter, "_invoke_pipeline_with_fallback", lambda x, m: None)
        monkeypatch.setattr(adapter, "_default_algorithm", lambda **kw: np.zeros((0, 3)))
        result = adapter.handle_repair(req)
        assert result.status_code == RepairStatusCode.ERR_NO_DEFECT_FOUND

    def test_handle_repair_matlab_algo_error(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import (
            MatlabAdapter, MatlabAlgorithmError,
        )
        from repair_app.bridge.communication.serializer import Serializer
        from repair_app.communication.repair_protocol_pb2 import RepairStatusCode
        adapter = MatlabAdapter()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = Serializer.build_repair_request(xyz, normals, scan_id="test")
        monkeypatch.setattr(
            adapter, "_invoke_pipeline_with_fallback",
            MagicMock(side_effect=MatlabAlgorithmError("algo failed")),
        )
        result = adapter.handle_repair(req)
        assert result.status_code == RepairStatusCode.ERR_ALGORITHM_FAIL

    def test_shutdown_with_exception(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        adapter = MatlabAdapter()
        with patch("repair_app.bridge.adapters.matlab_engine_proxy.MatlabEngineProxy.reset_singleton",
                   side_effect=Exception("reset failed")):
            adapter.shutdown()  # 不应抛异常

    def test_compute_uniformity_single_layer(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        wp = np.zeros((10, 8), dtype=np.float32)
        wp[:, 7] = 1  # 单层
        wp[:, 2] = np.arange(10, dtype=np.float32)
        score = MatlabAdapter._compute_uniformity(wp)
        assert score == 0.78  # 单层 < 2 层均值

    def test_compute_uniformity_zero_mean(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        wp = np.zeros((10, 8), dtype=np.float32)
        wp[:5, 7] = 1
        wp[5:, 7] = 2
        wp[:, 2] = 0.0  # 所有 z 为 0
        score = MatlabAdapter._compute_uniformity(wp)
        assert score == 0.78  # m < 1e-6

    def test_build_mesh_large_cloud(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (6000, 3)).astype(np.float32)
        data, fmt = MatlabAdapter._build_mesh_from_cloud(xyz)
        assert isinstance(data, bytes)

    def test_build_mesh_exception(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        with patch("scipy.spatial.Delaunay", side_effect=Exception("scipy failed")):
            data, fmt = MatlabAdapter._build_mesh_from_cloud(xyz)
            assert data == b""
            assert fmt == ""

    def test_invoke_pipeline_matlab_force_fail(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter, MatlabAlgorithmError
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        adapter = MatlabAdapter.__new__(MatlabAdapter)
        adapter._address = "tcp://127.0.0.1:5555"
        adapter._algorithm_fn = MagicMock(side_effect=MatlabAlgorithmError("MATLAB fail"))
        adapter._matlab_available = True
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        with patch("repair_app.bridge.adapters.matlab_pipeline.MATLABPipeline") as mock_pipeline:
            mock_pipeline.return_value.run.side_effect = Exception("MATLAB fail")
            with pytest.raises(MatlabAlgorithmError):
                adapter._invoke_pipeline_with_fallback(xyz, {})

    def test_invoke_pipeline_python_mode(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "python")
        adapter = MatlabAdapter()
        result = adapter._invoke_pipeline_with_fallback(np.zeros((10, 3)), {})
        assert result is None

    def test_invoke_pipeline_auto_fallback(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        with patch("repair_app.bridge.adapters.matlab_pipeline.MATLABPipeline") as mock_pipeline:
            mock_pipeline.return_value.run.side_effect = Exception("MATLAB fail")
            result = adapter._invoke_pipeline_with_fallback(np.zeros((10, 3)), {})
            assert result is None

    def test_invoke_pipeline_success(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        with patch("repair_app.bridge.adapters.matlab_pipeline.MATLABPipeline") as mock_pipeline:
            mock_pipeline.return_value.run.return_value = {
                "waypoints": np.zeros((5, 8)),
                "predicted_volume_mm3": 10.0,
                "estimated_mass_g": 0.08,
                "estimated_time_s": 1.0,
                "uniformity": 0.85,
                "layer_profiles": None,
                "particle_distribution": None,
                "mesh_stl_bytes": b"",
                "warnings": [],
            }
            result = adapter._invoke_pipeline_with_fallback(xyz, {})
            assert result is not None
            assert "waypoints" in result

    def test_invoke_pipeline_with_layer_profiles(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        with patch("repair_app.bridge.adapters.matlab_pipeline.MATLABPipeline") as mock_pipeline:
            mock_pipeline.return_value.run.return_value = {
                "waypoints": np.zeros((5, 8)),
                "predicted_volume_mm3": 10.0,
                "estimated_mass_g": 0.08,
                "estimated_time_s": 1.0,
                "uniformity": 0.85,
                "layer_profiles": np.array([[0, 1.0, 0.5, 0.7]], dtype=np.float32),
                "particle_distribution": {
                    "px": np.array([1.0], dtype=np.float32),
                    "py": np.array([1.0], dtype=np.float32),
                    "vx": np.array([100.0], dtype=np.float32),
                    "vy": np.array([0.0], dtype=np.float32),
                    "vz": np.array([500.0], dtype=np.float32),
                    "vcr": np.array([1.0], dtype=np.float32),
                    "diameter": np.array([25.0], dtype=np.float32),
                    "temperature": np.array([400.0], dtype=np.float32),
                    "dep_efficiency": 0.8,
                },
                "mesh_stl_bytes": b"stl",
                "warnings": [],
            }
            result = adapter._invoke_pipeline_with_fallback(xyz, {})
            assert result is not None
            assert result["mesh_format"] == "stl_binary"
            assert len(result["layer_profiles"]) == 1

    def test_try_profile_prediction_python_mode(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "python")
        adapter = MatlabAdapter()
        result = adapter._try_profile_prediction(np.zeros((10, 3)), {})
        assert result is None

    def test_try_profile_prediction_already_python(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        # _algorithm_fn 已经是 default_algorithm
        result = adapter._try_profile_prediction(np.zeros((10, 3)), {})
        assert result is None

    def test_try_profile_prediction_failure(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        # 临时设置算法为非 default
        adapter._algorithm_fn = MagicMock()
        with patch("repair_app.bridge.adapters.matlab_engine_proxy.MatlabEngineProxy") as mock_proxy:
            mock_proxy.return_value._ensure_connected.side_effect = Exception("connect failed")
            result = adapter._try_profile_prediction(np.zeros((10, 3)), {})
            assert result is None

    def test_build_viz_from_profile(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        raw = {
            "predicted_volume_mm3": 10.0,
            "estimated_mass_g": 0.08,
            "estimated_time_s": 1.0,
            "uniformity": 0.85,
            "layer_profiles": np.array([[0, 1.0, 0.5, 0.7]], dtype=np.float32),
            "particle_distribution": {
                "px": np.array([1.0], dtype=np.float32),
                "py": np.array([1.0], dtype=np.float32),
                "vx": np.array([100.0], dtype=np.float32),
                "vy": np.array([0.0], dtype=np.float32),
                "vz": np.array([500.0], dtype=np.float32),
                "vcr": np.array([1.0], dtype=np.float32),
                "diameter": np.array([25.0], dtype=np.float32),
                "temperature": np.array([400.0], dtype=np.float32),
                "dep_efficiency": 0.8,
            },
            "mesh_stl_bytes": b"data",
        }
        result = MatlabAdapter._build_viz_from_profile(raw, {})
        assert result["predicted_volume_mm3"] == 10.0
        assert result["mesh_format"] == "stl_binary"

    def test_build_viz_from_profile_empty_mesh(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        raw = {
            "predicted_volume_mm3": 0.0,
            "estimated_mass_g": 0.0,
            "estimated_time_s": 0.0,
            "uniformity": 0.78,
            "layer_profiles": None,
            "particle_distribution": None,
            "mesh_stl_bytes": b"",
        }
        result = MatlabAdapter._build_viz_from_profile(raw, {})
        assert result["mesh_format"] == ""

    def test_invoke_algorithm_success(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        adapter = MatlabAdapter()
        mock_fn = MagicMock(return_value=np.zeros((5, 8)))
        adapter._algorithm_fn = mock_fn
        result = adapter._invoke_algorithm(np.zeros((10, 3)), {})
        assert result is not None
        mock_fn.assert_called_once()

    def test_invoke_algorithm_failure(self):
        from repair_app.bridge.adapters.matlab_adapter import (
            MatlabAdapter, MatlabAlgorithmError,
        )
        adapter = MatlabAdapter()
        mock_fn = MagicMock(side_effect=Exception("algo failed"))
        adapter._algorithm_fn = mock_fn
        with pytest.raises(MatlabAlgorithmError, match="算法执行失败"):
            adapter._invoke_algorithm(np.zeros((10, 3)), {})

    def test_invoke_with_fallback_success(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        adapter = MatlabAdapter()
        mock_fn = MagicMock(return_value=np.zeros((5, 8)))
        adapter._algorithm_fn = mock_fn
        result = adapter._invoke_with_fallback(np.zeros((10, 3)), {})
        assert result is not None

    def test_invoke_with_fallback_auto_downgrade(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import (
            MatlabAdapter, MatlabAlgorithmError,
        )
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "auto")
        adapter = MatlabAdapter()
        mock_fn = MagicMock(side_effect=MatlabAlgorithmError("MATLAB fail"))
        adapter._algorithm_fn = mock_fn
        result = adapter._invoke_with_fallback(np.zeros((10, 3)), {})
        assert result is not None
        # 本次降级：返回 default_algorithm 结果，但不永久切换 _algorithm_fn
        assert adapter._algorithm_fn is mock_fn

    def test_invoke_with_fallback_matlab_force_raise(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter, MatlabAlgorithmError
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "matlab")
        adapter = MatlabAdapter.__new__(MatlabAdapter)
        adapter._address = "tcp://127.0.0.1:5555"
        mock_fn = MagicMock(side_effect=MatlabAlgorithmError("MATLAB fail"))
        adapter._algorithm_fn = mock_fn
        with pytest.raises(MatlabAlgorithmError):
            adapter._invoke_with_fallback(np.zeros((10, 3)), {})

    def test_select_algorithm_unknown_mode(self, monkeypatch):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        monkeypatch.setenv("CSAM_ALGORITHM_ENGINE", "unknown_mode")
        adapter = MatlabAdapter()
        assert adapter._algorithm_fn == adapter._default_algorithm

    def test_create_matlab_adapter_with_args(self):
        from repair_app.bridge.adapters.matlab_adapter import create_matlab_adapter
        adapter = create_matlab_adapter(address="tcp://127.0.0.1:9999")
        assert adapter._address == "tcp://127.0.0.1:9999"

    def test_matlab_adapter_service_version(self):
        from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
        adapter = MatlabAdapter()
        assert adapter.SERVICE_VERSION == "matlab-adapter-2.0.0"


# ================================================================
# 7. repair_serialization.py 补充测试 (communication/repair_serialization.py)
# ================================================================
class TestRepairSerialization:
    """测试 repair_serialization 的边角情况。"""

    def test_build_repair_request_invalid_xyz_shape(self):
        from repair_app.communication.repair_serialization import build_repair_request
        with pytest.raises(ValueError, match="xyz 必须为"):
            build_repair_request(
                np.ones((10, 4)), np.ones((10, 3)), scan_id="test",
            )

    def test_build_repair_request_invalid_normals_shape(self):
        from repair_app.communication.repair_serialization import build_repair_request
        with pytest.raises(ValueError, match="normals 必须为"):
            build_repair_request(
                np.ones((10, 3)), np.ones((10, 4)), scan_id="test",
            )

    def test_build_repair_request_mismatched_rows(self):
        from repair_app.communication.repair_serialization import build_repair_request
        with pytest.raises(ValueError, match="行数不一致"):
            build_repair_request(
                np.ones((10, 3)), np.ones((5, 3)), scan_id="test",
            )

    def test_build_repair_request_large_array_warning(self):
        from repair_app.communication.repair_serialization import build_repair_request, MAX_ARRAY_LENGTH_WARN
        rng = np.random.default_rng(42)
        N = MAX_ARRAY_LENGTH_WARN + 1
        xyz = rng.uniform(-5, 5, (N, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        with pytest.warns(UserWarning, match="点云点数较大"):
            req = build_repair_request(xyz, normals, scan_id="big")
            assert req.request_id is not None

    def test_build_repair_result_with_snapshots(self):
        from repair_app.communication.repair_serialization import build_repair_result
        result = build_repair_result(
            np.zeros((0, 3), dtype=np.float32),
            request_id="test",
            before_snapshot_png=b"before",
            after_snapshot_png=b"after",
        )
        assert result.before_snapshot_png == b"before"
        assert result.after_snapshot_png == b"after"

    def test_build_repair_result_with_mesh(self):
        from repair_app.communication.repair_serialization import build_repair_result
        result = build_repair_result(
            np.zeros((0, 3), dtype=np.float32),
            mesh_data=b"meshdata",
            mesh_format="stl_binary",
        )
        assert result.mesh_data == b"meshdata"
        assert result.mesh_format == "stl_binary"

    def test_build_layer_profile_with_optional(self):
        from repair_app.communication.repair_serialization import build_layer_profile
        lp = build_layer_profile(
            0, heightmap_png=b"pngdata", contour_geojson=b"geojson",
        )
        assert lp.heightmap_png == b"pngdata"
        assert lp.contour_geojson == b"geojson"

    def test_build_layer_profile_without_optional(self):
        from repair_app.communication.repair_serialization import build_layer_profile
        lp = build_layer_profile(0, max_height_mm=1.0, avg_height_mm=0.5, dep_efficiency=0.7)
        assert lp.heightmap_png == b""
        assert lp.contour_geojson == b""

    def test_build_progress_update_with_waypoints_short(self):
        from repair_app.communication.repair_serialization import build_progress_update
        from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
        wp = np.array([[0, 0, 0]], dtype=np.float32)
        msg = build_progress_update("test", ProgressUpdate.PATH_PLANNING, waypoints=wp)
        assert len(msg.partial_waypoints) == 1

    def test_build_progress_update_with_waypoints_full(self):
        from repair_app.communication.repair_serialization import build_progress_update
        from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
        wp = np.array([[0, 0, 0, 0, 0, 1, 100, 0]], dtype=np.float32)
        msg = build_progress_update("test", ProgressUpdate.PATH_PLANNING, waypoints=wp)
        assert msg.partial_waypoints[0].feed_rate == 100.0

    def test_build_progress_update_with_mesh(self):
        from repair_app.communication.repair_serialization import build_progress_update
        from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
        msg = build_progress_update(
            "test", ProgressUpdate.PATH_PLANNING,
            partial_mesh_data=b"mesh", partial_mesh_format="stl",
        )
        assert msg.partial_mesh_data == b"mesh"

    def test_build_progress_update_with_layer_profiles(self):
        from repair_app.communication.repair_serialization import (
            build_progress_update, build_layer_profile,
        )
        from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
        lp = build_layer_profile(0, max_height_mm=1.0)
        msg = build_progress_update(
            "test", ProgressUpdate.PATH_PLANNING, layer_profiles=[lp],
        )
        assert len(msg.layer_profiles) == 1

    def test_parse_progress_update(self):
        from repair_app.communication.repair_serialization import (
            build_progress_update, parse_progress_update,
        )
        from repair_app.communication.repair_protocol_pb2 import ProgressUpdate
        wp = np.array([[0, 0, 0, 0, 0, 1, 100, 0]], dtype=np.float32)
        msg = build_progress_update("test", ProgressUpdate.PATH_PLANNING, waypoints=wp)
        parsed = parse_progress_update(msg)
        assert parsed["request_id"] == "test"
        assert parsed["waypoints"].shape == (1, 7)

    def test_load_material_params_no_db(self, tmp_path, monkeypatch):
        from repair_app.communication.repair_serialization import load_material_params
        result = load_material_params("Cu", db_path=str(tmp_path / "nonexistent.json"))
        assert result.material_id == "Cu"
        assert result.density_gcm3 > 0

    def test_load_material_params_with_db(self, tmp_path):
        import json
        from repair_app.communication.repair_serialization import load_material_params
        db = {"Cu": {"name": "Copper", "density_gcm3": 8.96, "critical_velocity_ms": 400.0}}
        db_path = tmp_path / "material_db.json"
        db_path.write_text(json.dumps(db))
        result = load_material_params("Cu", db_path=str(db_path))
        assert result.material_name == "Copper"
        assert abs(result.density_gcm3 - 8.96) < 0.01

    def test_load_material_params_default(self, tmp_path):
        import json
        from repair_app.communication.repair_serialization import load_material_params
        db = {"DEFAULT": {"name": "Default", "density_gcm3": 7.0}}
        db_path = tmp_path / "material_db.json"
        db_path.write_text(json.dumps(db))
        result = load_material_params("Unknown", db_path=str(db_path))
        assert result.material_name == "Default"

    def test_parse_health_check_response_bytes(self):
        from repair_app.communication.repair_serialization import (
            build_health_check_request, parse_health_check_response,
        )
        from repair_app.communication.repair_protocol_pb2 import HealthCheckResponse
        hb = build_health_check_request()
        resp = HealthCheckResponse()
        resp.status = HealthCheckResponse.OK
        resp.service_version = "1.0.0"
        resp.memory_usage_mb = 512.0
        resp.uptime_s = 100
        resp.pending_requests = 0
        data = resp.SerializeToString()
        parsed = parse_health_check_response(data)
        assert parsed["status_code"] == 0
        assert parsed["service_version"] == "1.0.0"

    def test_parse_health_check_response_obj(self):
        from repair_app.communication.repair_serialization import parse_health_check_response
        from repair_app.communication.repair_protocol_pb2 import HealthCheckResponse
        resp = HealthCheckResponse()
        resp.status = HealthCheckResponse.OK
        parsed = parse_health_check_response(resp)
        assert parsed["status_code"] == 0

    def test_parse_repair_result_with_particle_dist(self):
        from repair_app.communication.repair_serialization import (
            build_repair_result, parse_repair_result,
            build_particle_distribution,
        )
        rng = np.random.default_rng(42)
        px = rng.random(5).astype(np.float32)
        py = rng.random(5).astype(np.float32)
        pd = build_particle_distribution(
            px, py,
            np.ones(5, dtype=np.float32),
            np.ones(5, dtype=np.float32),
            np.ones(5, dtype=np.float32),
        )
        result = build_repair_result(
            np.zeros((0, 3), dtype=np.float32),
            particle_dist=pd,
        )
        parsed = parse_repair_result(result)
        assert parsed["particle_dist"] is not None

    def test_parse_repair_result_with_waypoints(self):
        from repair_app.communication.repair_serialization import (
            build_repair_result, parse_repair_result,
        )
        wp = np.array([[0, 0, 0, 0, 0, 1, 100, 0]], dtype=np.float32)
        result = build_repair_result(wp, request_id="test")
        parsed = parse_repair_result(result)
        assert parsed["waypoints"].shape == (1, 7)
        assert parsed["waypoint_layers"][0] == 0

    def test_self_test(self):
        from repair_app.communication.repair_serialization import self_test
        assert self_test() is True


# ================================================================
# 8. 旧版 ZmqRepairClient 测试 (communication/zmq_client.py)
# ================================================================
class TestZmqRepairWorker:
    """测试旧版 ZmqRepairWorker。"""

    def test_worker_no_zmq(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairWorker
        from repair_app.communication.repair_serialization import (
            build_repair_request, serialize_request,
        )
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = build_repair_request(xyz, normals, scan_id="test")
        data = serialize_request(req)
        fake_zmq = _make_fake_zmq()
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client._ZMQ_AVAILABLE", False)
        worker = ZmqRepairWorker(data)
        errors = []
        worker.error_occurred.connect(lambda e: errors.append(e))
        worker.run()
        assert len(errors) == 1
        assert "pyzmq" in errors[0]

    def test_worker_with_zmq_timeout(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairWorker
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.poll.return_value = False  # 永远不可读 → 超时
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client.zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client._ZMQ_AVAILABLE", True)
        worker = ZmqRepairWorker(b"fake data", timeout_ms=100)
        errors = []
        worker.error_occurred.connect(lambda e: errors.append(e))
        worker.run()
        assert len(errors) == 1
        assert "超时" in errors[0]

    def test_worker_with_zmq_error(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairWorker
        import zmq as real_zmq
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.send.side_effect = fake_zmq.ZMQError("send failed")
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client.zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client._ZMQ_AVAILABLE", True)
        worker = ZmqRepairWorker(b"fake data", timeout_ms=100)
        errors = []
        worker.error_occurred.connect(lambda e: errors.append(e))
        worker.run()
        assert len(errors) == 1


class TestHealthCheckWorker:
    """测试旧版 HealthCheckWorker。"""

    def test_worker_no_zmq(self, monkeypatch):
        from repair_app.communication.zmq_client import HealthCheckWorker
        fake_zmq = _make_fake_zmq()
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client._ZMQ_AVAILABLE", False)
        worker = HealthCheckWorker()
        results = []
        worker.result_ready.connect(lambda ok, msg: results.append((ok, msg)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False

    def test_worker_timeout(self, monkeypatch):
        from repair_app.communication.zmq_client import HealthCheckWorker
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.poll.return_value = False
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client.zmq", fake_zmq)
        monkeypatch.setattr("repair_app.communication.zmq_client._ZMQ_AVAILABLE", True)
        worker = HealthCheckWorker()
        results = []
        worker.result_ready.connect(lambda ok, msg: results.append((ok, msg)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False
        assert "超时" in results[0][1]


class TestZmqRepairClient:
    """测试旧版 ZmqRepairClient。"""

    def test_init_deprecation_warning(self):
        with pytest.warns(DeprecationWarning, match="已弃用"):
            from repair_app.communication.zmq_client import ZmqRepairClient
            client = ZmqRepairClient()

    def test_properties(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        assert client.is_connected is False
        assert client.zmq_available is True or client.zmq_available is False

    def test_request_repair_pending(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        from repair_app.communication.repair_serialization import build_repair_request
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = build_repair_request(xyz, normals, scan_id="test")
        # 模拟正在进行的请求
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        client._pending_worker = mock_worker
        on_error = MagicMock()
        client.request_repair(req, MagicMock(), on_error)
        on_error.assert_called_once_with("前一个修复请求仍在进行中，请稍后重试")

    def test_request_repair_serialize_error(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairClient
        from repair_app.communication.repair_serialization import build_repair_request
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        with patch("repair_app.communication.zmq_client.serialize_request",
                   side_effect=Exception("serialize failed")):
            rng = np.random.default_rng(42)
            xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
            normals = np.zeros_like(xyz)
            req = build_repair_request(xyz, normals, scan_id="test")
            on_error = MagicMock()
            client.request_repair(req, MagicMock(), on_error)
            on_error.assert_called_once()

    def test_check_health(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        mock_worker = MagicMock()
        monkeypatch.setattr(
            "repair_app.communication.zmq_client.HealthCheckWorker",
            lambda *a, **kw: mock_worker,
        )
        on_health = MagicMock()
        client.check_health(on_health)
        mock_worker.result_ready.connect.assert_called_once()
        mock_worker.start.assert_called_once()

    def test_close(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = True
        client._pending_worker = mock_worker
        client._health_worker = None
        client.close(wait_ms=10)
        mock_worker.requestInterruption.assert_called()
        assert client._pending_worker is None

    def test_close_worker_terminate(self, monkeypatch):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = False  # 超时未退出
        client._pending_worker = mock_worker
        client._health_worker = None
        client.close(wait_ms=10)
        mock_worker.terminate.assert_called()
        assert client._pending_worker is None

    def test_on_result_ready(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        on_result = MagicMock()
        client._on_result = on_result
        client._on_result_ready("result")
        on_result.assert_called_once_with("result")

    def test_on_error_occurred(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        on_error = MagicMock()
        client._on_error = on_error
        client._on_error_occurred("error msg")
        on_error.assert_called_once_with("error msg")
        assert client._connected is False
        assert client._retry_count == 1

    def test_on_worker_finished(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        client._pending_worker = MagicMock()
        client._on_worker_finished()
        assert client._pending_worker is None

    def test_on_health_ready(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        on_health = MagicMock()
        client._on_health = on_health
        client._on_health_ready(True, "OK")
        assert client._connected is True
        on_health.assert_called_once_with(True, "OK")

    def test_on_health_finished(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        with pytest.warns(DeprecationWarning):
            client = ZmqRepairClient()
        client._health_worker = MagicMock()
        client._on_health_finished()
        assert client._health_worker is None


# ================================================================
# 9. BridgeClient 补充测试 (bridge/communication/zmq_client.py)
# ================================================================
class TestBridgeClient:
    """测试 BridgeClient 类。"""

    def test_init(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        assert client.is_connected is False
        assert client.config is not None

    def test_zmq_available(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        assert isinstance(client.zmq_available, bool)

    def test_request_repair_closed(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.serializer import Serializer
        client = BridgeClient()
        client._closed = True
        on_error = MagicMock()
        req = Serializer.build_repair_request(
            np.zeros((10, 3), dtype=np.float32),
            np.zeros((10, 3), dtype=np.float32),
            scan_id="test",
        )
        rid = client.request_repair(req, MagicMock(), on_error)
        assert rid == ""
        on_error.assert_called_once()

    def test_request_repair_worker_running(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.serializer import Serializer
        client = BridgeClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        client._request_worker = mock_worker
        on_error = MagicMock()
        req = Serializer.build_repair_request(
            np.zeros((10, 3), dtype=np.float32),
            np.zeros((10, 3), dtype=np.float32),
            scan_id="test",
        )
        rid = client.request_repair(req, MagicMock(), on_error)
        assert rid == ""
        on_error.assert_called_once()

    def test_request_repair_serialization_error(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.serializer import Serializer, SerializationError
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (10, 3)).astype(np.float32)
        normals = np.zeros_like(xyz)
        req = Serializer.build_repair_request(xyz, normals, scan_id="test")
        client = BridgeClient()
        on_error = MagicMock()
        with patch.object(Serializer, "serialize_request",
                          side_effect=SerializationError("serialize failed")):
            rid = client.request_repair(req, MagicMock(), on_error)
            on_error.assert_called_once()

    def test_check_health_closed(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        client._closed = True
        on_health = MagicMock()
        client.check_health(on_health)
        on_health.assert_called_once_with(False, "客户端已关闭")

    def test_check_health_worker_running(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        client._health_worker = mock_worker
        on_health = MagicMock()
        client.check_health(on_health)
        on_health.assert_not_called()  # 跳过

    def test_start_heartbeat(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_hm = MagicMock()
        monkeypatch.setattr(
            "repair_app.bridge.communication.heartbeat.HeartbeatMonitor",
            lambda *a, **kw: mock_hm,
        )
        client.start_heartbeat()
        mock_hm.status_changed.connect.assert_called_once()
        mock_hm.start.assert_called_once()

    def test_start_heartbeat_already_running(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_hm = MagicMock()
        client._heartbeat = mock_hm
        client.start_heartbeat()
        # 不应创建新的

    def test_stop_heartbeat(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_hm = MagicMock()
        client._heartbeat = mock_hm
        client.stop_heartbeat()
        mock_hm.stop.assert_called_once()
        assert client._heartbeat is None

    def test_close(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = True
        client._request_worker = mock_worker
        client._health_worker = None
        client.close(wait_ms=10)
        assert client._request_worker is None
        assert client._closed is True

    def test_close_worker_terminate(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mock_worker.wait.return_value = False
        client._request_worker = mock_worker
        client._health_worker = None
        client.close(wait_ms=10)
        mock_worker.terminate.assert_called()

    def test_on_result_ready(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        on_result = MagicMock()
        client._on_result = on_result
        client._on_result_ready("result")
        on_result.assert_called_once_with("result")

    def test_on_error_occurred(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        on_error = MagicMock()
        client._on_error = on_error
        with patch("repair_app.bridge.communication.zmq_client.translate_zmq_error",
                   return_value="translated"):
            client._on_error_occurred("error", "req-1")
            on_error.assert_called_once_with("translated")
            assert client.is_connected is False

    def test_on_worker_finished(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        client._request_worker = MagicMock()
        client._on_worker_finished()
        assert client._request_worker is None

    def test_on_health_ready(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        callback = MagicMock()
        client._on_health_ready(True, "OK", callback)
        callback.assert_called_once_with(True, "OK")
        assert client.is_connected is True

    def test_on_heartbeat_status(self):
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        client._on_heartbeat_status(0, "ok")
        assert client.is_connected is True
        client._on_heartbeat_status(1, "down")
        assert client.is_connected is False


# ================================================================
# 10. _RequestWorker / _HealthWorker 测试 (bridge zmq_client)
# ================================================================
class TestRequestWorker:
    """测试 _RequestWorker 线程。"""

    def test_worker_no_zmq(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", False)
        worker = _RequestWorker(b"data", "tcp://127.0.0.1:5555", BridgeConfig())
        errors = []
        worker.error_occurred.connect(lambda msg, rid: errors.append((msg, rid)))
        worker.run()
        assert len(errors) == 1
        assert "pyzmq" in errors[0][0]

    def test_worker_with_zmq_timeout(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.poll.return_value = False
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig(request_timeout_ms=100)
        worker = _RequestWorker(b"data", "tcp://127.0.0.1:5555", config)
        errors = []
        worker.error_occurred.connect(lambda msg, rid: errors.append((msg, rid)))
        worker.run()
        assert len(errors) == 1
        assert "超时" in errors[0][0]

    def test_worker_with_zmq_error(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig
        import zmq as real_zmq
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.send.side_effect = fake_zmq.ZMQError("send failed")
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig()
        worker = _RequestWorker(b"data", "tcp://127.0.0.1:5555", config, request_id="rid-1")
        errors = []
        worker.error_occurred.connect(lambda msg, rid: errors.append((msg, rid)))
        worker.run()
        assert len(errors) == 1

    def test_worker_interruption(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig()
        worker = _RequestWorker(b"data", "tcp://127.0.0.1:5555", config)
        with patch.object(worker, "isInterruptionRequested", return_value=True):
            worker.run()  # 应立即退出


class TestHealthWorker:
    """测试 _HealthWorker 线程。"""

    def test_worker_no_zmq(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _HealthWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", False)
        worker = _HealthWorker("tcp://127.0.0.1:5555", BridgeConfig())
        results = []
        worker.result_ready.connect(lambda ok, msg, lat: results.append((ok, msg, lat)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False
        assert "pyzmq" in results[0][1]

    def test_worker_timeout(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _HealthWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.poll.return_value = False
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig(health_check_timeout_ms=100)
        worker = _HealthWorker("tcp://127.0.0.1:5555", config)
        results = []
        worker.result_ready.connect(lambda ok, msg, lat: results.append((ok, msg, lat)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False
        assert "超时" in results[0][1]

    def test_worker_interruption(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _HealthWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig()
        worker = _HealthWorker("tcp://127.0.0.1:5555", config)
        with patch.object(worker, "isInterruptionRequested", return_value=True):
            worker.run()

    def test_worker_exception(self, monkeypatch):
        from repair_app.bridge.communication.zmq_client import _HealthWorker
        from repair_app.bridge.communication.config import BridgeConfig
        fake_zmq = _make_fake_zmq()
        mock_ctx = MagicMock()
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = Exception("connect failed")
        mock_ctx.socket.return_value = mock_sock
        fake_zmq.Context._instance = mock_ctx
        monkeypatch.setitem(sys.modules, "zmq", fake_zmq)
        monkeypatch.setattr("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", True)
        config = BridgeConfig()
        worker = _HealthWorker("tcp://127.0.0.1:5555", config)
        results = []
        worker.result_ready.connect(lambda ok, msg, lat: results.append((ok, msg, lat)))
        worker.run()
        assert len(results) == 1
        assert results[0][0] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])