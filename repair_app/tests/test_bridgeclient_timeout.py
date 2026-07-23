"""test_bridgeclient_timeout.py — Phase 3: ZMQ REQ/REP timeout 状态机测试"""
import pytest
from unittest.mock import MagicMock, patch


class TestBridgeClientReconnect:
    """测试 BridgeClient.reconnect() 方法。"""

    def test_reconnect_has_method(self):
        """BridgeClient 必须有 reconnect 方法。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        assert hasattr(client, "reconnect"), "BridgeClient 必须有 reconnect 方法"
        assert callable(client.reconnect), "reconnect 必须可调用"

    def test_reconnect_zmq_not_available(self):
        """pyzmq 未安装时 reconnect 返回 False。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        with patch("repair_app.bridge.communication.zmq_client._ZMQ_AVAILABLE", False):
            result = client.reconnect()
            assert result is False

    def test_reconnect_closed_client(self):
        """已关闭的客户端 reconnect 返回 False。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        client = BridgeClient()
        client._closed = True
        result = client.reconnect()
        assert result is False, "已关闭的客户端 reconnect 应返回 False"


class TestBridgeClientRequestBlocking:
    """测试 request_blocking 的 socket reset 行为。"""

    def test_request_blocking_timeout_resets_socket(self):
        """超时后应调用 reconnect 验证连接。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.exceptions import ConnectionTimeoutError
        import zmq

        client = BridgeClient()
        client._closed = False

        # Mock zmq.Context to simulate timeout
        with patch("repair_app.bridge.communication.zmq_client.zmq") as mock_zmq:
            mock_ctx = MagicMock()
            mock_sock = MagicMock()
            mock_sock.poll.return_value = 0  # Always timeout
            mock_ctx.socket.return_value = mock_sock
            mock_zmq.Context.instance.return_value = mock_ctx
            mock_zmq.REQ = zmq.REQ
            mock_zmq.POLLIN = zmq.POLLIN
            mock_zmq.LINGER = zmq.LINGER
            mock_zmq.RCVTIMEO = zmq.RCVTIMEO
            mock_zmq.SNDTIMEO = zmq.SNDTIMEO

            with pytest.raises(ConnectionTimeoutError):
                client.request_blocking(b"test", timeout_ms=10)

            # Verify socket was created, used, and closed
            mock_ctx.socket.assert_called()
            mock_sock.close.assert_called()

    def test_request_blocking_success_does_not_reset(self):
        """成功返回时不应触发 reconnect（正常流程）。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        import zmq

        client = BridgeClient()
        client._closed = False

        with patch("repair_app.bridge.communication.zmq_client.zmq") as mock_zmq:
            mock_ctx = MagicMock()
            mock_sock = MagicMock()
            mock_sock.poll.return_value = zmq.POLLIN  # Ready to receive
            mock_sock.recv.return_value = b"fake_reply"
            mock_ctx.socket.return_value = mock_sock
            mock_zmq.Context.instance.return_value = mock_ctx
            mock_zmq.REQ = zmq.REQ
            mock_zmq.POLLIN = zmq.POLLIN
            mock_zmq.LINGER = zmq.LINGER
            mock_zmq.RCVTIMEO = zmq.RCVTIMEO
            mock_zmq.SNDTIMEO = zmq.SNDTIMEO

            result = client.request_blocking(b"test", timeout_ms=1000)
            assert result == b"fake_reply"
            mock_sock.close.assert_called()  # Socket is always closed in finally

    def test_request_blocking_shutdown_raises(self):
        """已关闭的客户端应抛出 ShutdownError。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.exceptions import ShutdownError

        client = BridgeClient()
        client._closed = True

        with pytest.raises(ShutdownError):
            client.request_blocking(b"test")

    def test_request_blocking_interrupted_during_poll(self):
        """poll 期间客户端关闭应抛出 ShutdownError。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        from repair_app.bridge.communication.exceptions import ShutdownError
        import zmq

        client = BridgeClient()
        client._closed = False

        with patch("repair_app.bridge.communication.zmq_client.zmq") as mock_zmq:
            mock_ctx = MagicMock()
            mock_sock = MagicMock()
            mock_sock.poll.return_value = 0  # Timeout each poll

            # Simulate client close during poll
            def side_effect_closed(a, b):
                client._closed = True
                return 0
            mock_sock.poll.side_effect = side_effect_closed

            mock_ctx.socket.return_value = mock_sock
            mock_zmq.Context.instance.return_value = mock_ctx
            mock_zmq.REQ = zmq.REQ
            mock_zmq.POLLIN = zmq.POLLIN
            mock_zmq.LINGER = zmq.LINGER
            mock_zmq.RCVTIMEO = zmq.RCVTIMEO
            mock_zmq.SNDTIMEO = zmq.SNDTIMEO

            with pytest.raises(ShutdownError):
                client.request_blocking(b"test", timeout_ms=100)

            mock_sock.close.assert_called()  # Socket must be cleaned up