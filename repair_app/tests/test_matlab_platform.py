"""test_matlab_platform.py — MATLAB Execution Platform test suite.

Covers:
- Protocol v3.0 serialization (Tensor/Value round-trip)
- TcpChannel framing & retry
- MatlabEngine algorithm execution (mock server)
- EngineFactory selection logic
- LifecycleSupervisor (heartbeat, reconnect, circuit breaker)
- End-to-end mock server integration
- Timeout & failure handling
- Performance benchmarks

These tests use an in-process mock MATLAB server (Python) that speaks the
same JSON-over-TCP protocol, so they run without MATLAB installed.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# Mock MATLAB Server (for integration tests)
# ================================================================

class MockMatlabServer:
    """Minimal Python server that speaks the v3.0 JSON-over-TCP protocol."""

    def __init__(self, host="127.0.0.1", port=0):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(5)
        self.host, self.port = self._sock.getsockname()
        self._running = False
        self._thread = None
        self._handlers = {
            "HEALTH_CHECK": self._handle_health,
            "HEARTBEAT": self._handle_heartbeat,
            "ALGORITHM_REQUEST": self._handle_algorithm,
            "LIST_ALGORITHMS": self._handle_list,
            "VERSION_NEGOTIATE": self._handle_version,
            "SHUTDOWN_REQUEST": self._handle_shutdown,
        }
        self.request_count = 0
        self._delay_ms = 0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass

    def set_delay(self, ms: int):
        self._delay_ms = ms

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket):
        try:
            while self._running:
                header = self._recv_exact(conn, 4)
                if header is None:
                    break
                (length,) = struct.unpack(">I", header)
                payload = self._recv_exact(conn, length)
                if payload is None:
                    break
                env = json.loads(payload.decode("utf-8"))
                if self._delay_ms > 0:
                    time.sleep(self._delay_ms / 1000.0)
                resp = self._dispatch(env)
                self._send_framed(conn, resp)
        except (OSError, ConnectionError):
            pass
        finally:
            conn.close()

    def _dispatch(self, env: dict) -> dict:
        self.request_count += 1
        mt = env.get("message_type", "")
        handler = self._handlers.get(mt)
        if handler is None:
            payload = {"status": 99, "error_message": f"unknown message type: {mt}"}
            return self._envelope("ALGORITHM_RESPONSE", payload, env)
        return handler(env)

    def _handle_health(self, env):
        return self._envelope("HEALTH_STATUS", {
            "state": 0, "server_version": "mock/1.0", "matlab_version": "R2024b",
            "memory_mb": 256.0, "uptime_s": 100, "pending_reqs": 0,
            "toolbox_available": {"Map_Toolbox": True, "Curve_Fitting_Toolbox": True},
            "error_rate_1m": 0.0, "total_requests": self.request_count,
        }, env)

    def _handle_heartbeat(self, env):
        return self._envelope("PONG", {
            "request_id": env.get("request_id", ""),
            "server_ts_ms": int(time.time() * 1000),
            "pending": 0,
        }, env)

    def _handle_algorithm(self, env):
        p = env.get("payload", {})
        name = p.get("algorithm_name", "")
        if name == "echo":
            params = p.get("params", {})
            results = {}
            for k, v in params.items():
                results[k] = v
            return self._envelope("ALGORITHM_RESPONSE", {
                "status": 0, "results": results, "compute_time_ms": 5,
                "algorithm_ver": "1.0.0", "request_id": env.get("request_id"),
            }, env)
        if name == "add_arrays":
            inputs = p.get("inputs", {})
            a = self._tensor_to_np(inputs.get("a", {}))
            b = self._tensor_to_np(inputs.get("b", {}))
            c = a + b
            return self._envelope("ALGORITHM_RESPONSE", {
                "status": 0,
                "artifacts": {"result": self._np_to_tensor(c)},
                "compute_time_ms": 1,
            }, env)
        if name == "fail":
            return self._envelope("ALGORITHM_RESPONSE", {
                "status": 3, "error_code": "TEST_FAILURE",
                "error_message": "simulated algorithm failure",
            }, env)
        if name == "slow":
            time.sleep(2.0)
            return self._envelope("ALGORITHM_RESPONSE", {"status": 0}, env)
        return self._envelope("ALGORITHM_RESPONSE", {
            "status": 5, "error_code": "NOT_FOUND",
            "error_message": f"algorithm '{name}' not registered",
        }, env)

    def _handle_list(self, env):
        return self._envelope("LIST_ALGORITHMS_RESPONSE", {
            "algorithms": [
                {"name": "echo", "version": "1.0.0", "category": "test"},
                {"name": "add_arrays", "version": "1.0.0", "category": "test"},
            ]
        }, env)

    def _handle_version(self, env):
        return self._envelope("VERSION_RESULT", {
            "server_protocol": "3.0", "server_app": "mock/1.0",
            "protocol_compatible": True,
            "available_algorithms": ["echo", "add_arrays"],
            "algorithm_count": 2,
        }, env)

    def _handle_shutdown(self, env):
        return self._envelope("SHUTDOWN_ACK", {
            "accepted": True, "pending_count": 0, "estimated_drain_ms": 0,
        }, env)

    @staticmethod
    def _envelope(msg_type, payload, req_env):
        return {
            "request_id": req_env.get("request_id", ""),
            "timestamp_ms": int(time.time() * 1000),
            "message_type": msg_type,
            "protocol_ver": "3.0",
            "payload": payload,
        }

    @staticmethod
    def _recv_exact(conn, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _send_framed(conn, obj):
        payload = json.dumps(obj).encode("utf-8")
        conn.sendall(struct.pack(">I", len(payload)) + payload)

    @staticmethod
    def _np_to_tensor(arr):
        import base64
        arr = np.ascontiguousarray(arr)
        return {
            "dtype": "F64", "shape": list(arr.shape),
            "data": base64.b64encode(arr.tobytes()).decode("ascii"),
            "units": "",
        }

    @staticmethod
    def _tensor_to_np(d):
        import base64
        raw = base64.b64decode(d.get("data", ""))
        arr = np.frombuffer(raw, dtype=np.float64)
        shape = tuple(d.get("shape", [])) or (arr.size,)
        return arr.reshape(shape)


@pytest.fixture
def mock_server():
    srv = MockMatlabServer()
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def engine(mock_server):
    from repair_app.engine.matlab_engine import MatlabEngine
    eng = MatlabEngine(host=mock_server.host, port=mock_server.port, timeout_ms=5000, max_retries=2)
    yield eng
    eng.close()


# ================================================================
# 1. Protocol v3.0 Serialization Tests
# ================================================================

class TestProtocolV3Serialization:
    def test_tensor_f64_roundtrip(self):
        from repair_app.bridge.protocol_v3.serialization import numpy_to_tensor, tensor_to_numpy
        arr = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float64)
        t = numpy_to_tensor(arr, units="mm")
        assert t.dtype == t.F64
        assert list(t.shape) == [2, 3]
        assert t.units == "mm"
        back = tensor_to_numpy(t)
        np.testing.assert_array_equal(back, arr)

    def test_tensor_i32_roundtrip(self):
        from repair_app.bridge.protocol_v3.serialization import numpy_to_tensor, tensor_to_numpy
        arr = np.array([1, 2, 3, 4], dtype=np.int32)
        t = numpy_to_tensor(arr)
        assert t.dtype == t.I32
        back = tensor_to_numpy(t)
        np.testing.assert_array_equal(back, arr)

    def test_tensor_f32_roundtrip(self):
        from repair_app.bridge.protocol_v3.serialization import numpy_to_tensor, tensor_to_numpy
        arr = np.array([1.5, 2.5], dtype=np.float32)
        t = numpy_to_tensor(arr)
        assert t.dtype == t.F32
        back = tensor_to_numpy(t)
        np.testing.assert_allclose(back, arr)

    def test_value_int(self):
        from repair_app.bridge.protocol_v3.serialization import py_to_value, value_to_py
        v = py_to_value(42)
        assert value_to_py(v) == 42

    def test_value_float(self):
        from repair_app.bridge.protocol_v3.serialization import py_to_value, value_to_py
        v = py_to_value(3.14)
        assert abs(value_to_py(v) - 3.14) < 1e-10

    def test_value_bool(self):
        from repair_app.bridge.protocol_v3.serialization import py_to_value, value_to_py
        v = py_to_value(True)
        assert value_to_py(v) is True

    def test_value_str(self):
        from repair_app.bridge.protocol_v3.serialization import py_to_value, value_to_py
        v = py_to_value("hello")
        assert value_to_py(v) == "hello"

    def test_value_tensor(self):
        from repair_app.bridge.protocol_v3.serialization import py_to_value, value_to_py
        arr = np.array([1.0, 2.0, 3.0])
        v = py_to_value(arr)
        back = value_to_py(v)
        np.testing.assert_array_equal(back, arr)

    def test_build_params(self):
        from repair_app.bridge.protocol_v3.serialization import build_params, parse_params
        params = build_params(layer_height=0.5, num_layers=10, name="test")
        parsed = parse_params(params)
        assert parsed["layer_height"] == 0.5
        assert parsed["num_layers"] == 10
        assert parsed["name"] == "test"

    def test_build_inputs(self):
        from repair_app.bridge.protocol_v3.serialization import build_inputs, parse_inputs
        inputs = build_inputs(cloud=np.zeros((100, 3)))
        parsed = parse_inputs(inputs)
        assert parsed["cloud"].shape == (100, 3)


# ================================================================
# 2. MatlabEngine Algorithm Execution Tests
# ================================================================

class TestMatlabEngineExecution:
    def test_health_check(self, engine):
        assert engine.check_health() is True
        assert engine.is_available is True

    def test_execute_echo(self, engine):
        result = engine.execute("echo", params={"message": "hello", "count": 5})
        assert result.ok
        assert result.results["message"] == "hello"
        assert result.results["count"] == 5

    def test_execute_add_arrays(self, engine):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        result = engine.execute("add_arrays", inputs={"a": a, "b": b})
        assert result.ok
        np.testing.assert_array_equal(result.artifacts["result"], [5.0, 7.0, 9.0])

    def test_execute_unknown_algorithm(self, engine):
        result = engine.execute("nonexistent_algo")
        assert not result.ok
        assert result.status == 5  # ERR_NOT_FOUND

    def test_execute_algorithm_failure(self, engine):
        result = engine.execute("fail")
        assert not result.ok
        assert result.status == 3  # ERR_ALGORITHM
        assert "simulated" in result.error_message

    def test_execute_raises_on_error(self, engine):
        from repair_app.engine.matlab_engine import AlgorithmEngineError
        with pytest.raises(AlgorithmEngineError):
            result = engine.execute("fail")
            result.raise_for_error()

    def test_list_algorithms(self, engine):
        algos = engine.list_algorithms()
        assert len(algos) == 2
        names = [a["name"] for a in algos]
        assert "echo" in names
        assert "add_arrays" in names

    def test_get_algorithm_metadata(self, engine):
        meta = engine.get_algorithm_metadata("echo")
        assert meta is not None
        assert meta["version"] == "1.0.0"

    def test_get_algorithm_metadata_not_found(self, engine):
        meta = engine.get_algorithm_metadata("nonexistent")
        assert meta is None

    def test_heartbeat(self, engine):
        pong = engine.heartbeat()
        assert "server_ts_ms" in pong


# ================================================================
# 3. TcpChannel Tests
# ================================================================

class TestTcpChannel:
    def test_connect_disconnect(self, mock_server):
        from repair_app.engine.matlab_engine import TcpChannel
        ch = TcpChannel(mock_server.host, mock_server.port, timeout_ms=2000)
        ch.connect()
        assert ch.is_connected
        ch.disconnect()
        assert not ch.is_connected

    def test_request_reply(self, mock_server):
        from repair_app.engine.matlab_engine import TcpChannel, MessageType, PROTOCOL_VERSION
        ch = TcpChannel(mock_server.host, mock_server.port, timeout_ms=2000)
        env = {
            "request_id": "test-1", "timestamp_ms": 0,
            "message_type": MessageType.HEARTBEAT, "protocol_ver": PROTOCOL_VERSION,
            "payload": {},
        }
        resp = ch.request(env)
        assert resp["message_type"] == "PONG"
        ch.close()

    def test_retry_on_connection_failure(self):
        from repair_app.engine.matlab_engine import TcpChannel, AlgorithmEngineError
        # Connect to a port with no server — should retry then fail
        ch = TcpChannel("127.0.0.1", 59999, timeout_ms=500, max_retries=2)
        with pytest.raises(AlgorithmEngineError):
            ch.request({"message_type": "HEARTBEAT", "payload": {}})


# ================================================================
# 4. EngineFactory Tests
# ================================================================

class TestEngineFactory:
    def test_create_python_forced(self):
        from repair_app.engine.factory import create_engine
        from repair_app.engine.local_engine import LocalEngine
        eng = create_engine("python")
        assert isinstance(eng, LocalEngine)

    def test_create_auto_falls_back_to_python(self, monkeypatch):
        from repair_app.engine.factory import create_engine
        from repair_app.engine.local_engine import LocalEngine
        monkeypatch.setenv("CSAM_ENGINE_DISABLE_MATLAB", "1")
        eng = create_engine("auto")
        assert isinstance(eng, LocalEngine)

    def test_create_matlab_required_raises(self, monkeypatch):
        from repair_app.engine.factory import create_engine
        monkeypatch.setenv("CSAM_ENGINE_DISABLE_MATLAB", "1")
        with pytest.raises(RuntimeError):
            create_engine("matlab")


# ================================================================
# 5. LifecycleSupervisor Tests
# ================================================================

class TestLifecycleSupervisor:
    def test_state_transitions(self, engine):
        from repair_app.engine.lifecycle import LifecycleSupervisor, EngineState, LifecycleConfig
        cfg = LifecycleConfig(heartbeat_interval_ms=100, miss_threshold=2, reconnect_max_attempts=1)
        sup = LifecycleSupervisor(engine, cfg)
        states = []
        sup.on_state_change(lambda s: states.append(s))
        sup.start()
        time.sleep(0.5)
        assert sup.state in (EngineState.READY, EngineState.DEGRADED)
        sup.stop()

    def test_heartbeat_recovery(self, engine, mock_server):
        from repair_app.engine.lifecycle import LifecycleSupervisor, EngineState, LifecycleConfig
        cfg = LifecycleConfig(heartbeat_interval_ms=100, miss_threshold=3, reconnect_max_attempts=5)
        sup = LifecycleSupervisor(engine, cfg)
        sup.start()
        time.sleep(0.3)
        assert sup.state == EngineState.READY
        sup.stop()

    def test_circuit_breaker(self, engine):
        from repair_app.engine.lifecycle import LifecycleSupervisor, CircuitState, LifecycleConfig
        cfg = LifecycleConfig(heartbeat_interval_ms=100, circuit_failure_threshold=3)
        sup = LifecycleSupervisor(engine, cfg)
        assert sup.allow_request is True
        sup.record_failure()
        sup.record_failure()
        assert sup.allow_request is True  # not yet
        sup.record_failure()
        assert sup.circuit_state == CircuitState.OPEN


# ================================================================
# 6. Timeout & Failure Tests
# ================================================================

class TestTimeoutAndFailure:
    def test_timeout_on_slow_algorithm(self, mock_server):
        from repair_app.engine.matlab_engine import MatlabEngine, AlgorithmEngineError
        mock_server.set_delay(2000)  # 2s delay
        eng = MatlabEngine(host=mock_server.host, port=mock_server.port,
                          timeout_ms=500, max_retries=1)
        with pytest.raises(AlgorithmEngineError):
            eng.execute("echo", params={"x": 1})
        eng.close()

    def test_connection_refused(self):
        from repair_app.engine.matlab_engine import MatlabEngine
        eng = MatlabEngine(host="127.0.0.1", port=59998, timeout_ms=300, max_retries=1)
        assert eng.check_health() is False
        assert eng.is_available is False
        eng.close()


# ================================================================
# 7. End-to-End Integration (GUI → Engine flow simulation)
# ================================================================

class TestEndToEndIntegration:
    def test_full_algorithm_lifecycle(self, engine):
        """Simulate: connect → health → list → execute → heartbeat → shutdown."""
        assert engine.check_health()

        algos = engine.list_algorithms()
        assert len(algos) >= 1

        result = engine.execute("echo", params={"test": True})
        assert result.ok

        pong = engine.heartbeat()
        assert "server_ts_ms" in pong

        ack = engine.shutdown_server(reason="test_complete")
        assert ack.get("accepted") is True

    def test_concurrent_requests(self, mock_server):
        """Stress test: 20 concurrent requests."""
        from repair_app.engine.matlab_engine import MatlabEngine
        results = []
        errors = []

        def worker():
            try:
                eng = MatlabEngine(host=mock_server.host, port=mock_server.port,
                                  timeout_ms=5000, max_retries=1)
                r = eng.execute("echo", params={"x": 1})
                results.append(r.ok)
                eng.close()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"errors: {errors[:3]}"
        assert len(results) == 20
        assert all(results)


# ================================================================
# 8. Performance Benchmarks
# ================================================================

class TestPerformance:
    def test_tensor_serialization_throughput(self):
        from repair_app.bridge.protocol_v3.serialization import numpy_to_tensor, tensor_to_numpy
        arr = np.random.randn(10000, 3).astype(np.float64)
        t0 = time.perf_counter()
        for _ in range(100):
            t = numpy_to_tensor(arr)
            _ = tensor_to_numpy(t)
        elapsed = time.perf_counter() - t0
        per_op_ms = elapsed / 100 * 1000
        assert per_op_ms < 50, f"serialization too slow: {per_op_ms:.1f}ms/op"

    def test_algorithm_request_latency(self, engine):
        """Single-request latency should be < 50ms over loopback."""
        t0 = time.perf_counter()
        for _ in range(50):
            r = engine.execute("echo", params={"x": 1})
            assert r.ok
        elapsed = time.perf_counter() - t0
        avg_ms = elapsed / 50 * 1000
        assert avg_ms < 50, f"avg latency too high: {avg_ms:.1f}ms"
