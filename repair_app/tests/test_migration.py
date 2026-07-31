"""test_migration.py — 通信层迁移验证测试

验证 MainWindow → CoordinationService → MatlabService → Bridge → Engine
端到端通信路径已正确切换至 bridge 层。

运行：
    python -m pytest repair_app/tests/test_migration.py -v
"""

from __future__ import annotations
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# 1. CoordinationService 返回 bridge 适配器
# ================================================================
class TestCoordinationServiceMigration:
    def test_create_zmq_client_returns_bridge_adapter(self):
        """create_zmq_client 应返回 LegacyZmqClient（bridge 适配器）。"""
        from repair_app.service.coordination_service import CoordinationService
        from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient

        client = CoordinationService.create_zmq_client()
        assert client is not None, "client 不应为 None（bridge 应可用）"
        assert isinstance(client, LegacyZmqClient), (
            f"期望 LegacyZmqClient，实际 {type(client).__name__}"
        )

    def test_bridge_active_property(self):
        """bridge_active 应为 True（bridge 已安装）。"""
        from repair_app.service.coordination_service import CoordinationService
        svc = CoordinationService()
        assert svc.bridge_active is True

    def test_zmq_available_still_true(self):
        """zmq_available 应仍为 True。"""
        from repair_app.service.coordination_service import CoordinationService
        svc = CoordinationService()
        assert svc.zmq_available is True

    def test_client_api_compatibility(self):
        """LegacyZmqClient 应暴露与旧版兼容的 API。"""
        from repair_app.service.coordination_service import CoordinationService
        client = CoordinationService.create_zmq_client()
        # 旧版 ZmqRepairClient 的公开 API
        assert hasattr(client, "request_repair")
        assert hasattr(client, "check_health")
        assert hasattr(client, "close")
        assert hasattr(client, "is_connected")
        assert hasattr(client, "zmq_available")
        # bridge 增强功能
        assert hasattr(client, "start_heartbeat")
        assert hasattr(client, "stop_heartbeat")
        client.close()


# ================================================================
# 2. MainWindow 使用 bridge 通信路径
# ================================================================
class TestMainWindowBridgeIntegration:
    def test_main_window_uses_bridge_client(self, qapp):
        """MainWindow 的 _zmq_client 应为 LegacyZmqClient 实例。"""
        from repair_app.ui.main_window import MainWindow
        from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient

        mw = MainWindow()
        try:
            assert isinstance(mw._zmq_client, LegacyZmqClient), (
                f"MainWindow._zmq_client 期望 LegacyZmqClient，实际 {type(mw._zmq_client).__name__}"
            )
        finally:
            # P2-9: 清理 ComputeController（含 ProgressSubscriber 线程），避免 access violation
            cc = getattr(mw, "_compute_controller", None)
            if cc is not None:
                try:
                    cc.cleanup()
                except Exception:
                    pass
            if mw._zmq_client is not None:
                mw._zmq_client.close()
            mw.deleteLater()

    def test_main_window_use_zmq_engine_check(self, qapp):
        """_use_zmq_engine 在有 client 时应正常工作。"""
        from repair_app.ui.main_window import MainWindow

        mw = MainWindow()
        try:
            # 不应抛异常
            result = mw._use_zmq_engine()
            # 验证：返回 bool（_use_zmq_engine 可能因 engine 未就绪返回 False）
            assert isinstance(result, bool)
        finally:
            # P2-9: 清理 ComputeController（含 ProgressSubscriber 线程），避免 access violation
            cc = getattr(mw, "_compute_controller", None)
            if cc is not None:
                try:
                    cc.cleanup()
                except Exception:
                    pass
            if mw._zmq_client is not None:
                mw._zmq_client.close()
            mw.deleteLater()


# ================================================================
# 3. bridge 通信路径端到端（Mock 引擎）
# ================================================================
class TestBridgeEndToEnd:
    def test_request_repair_through_bridge_adapter(self, qapp):
        """LegacyZmqClient.request_repair 应委托给 BridgeClient。

        验证：传入无效请求（None）时，on_error 被调用（序列化失败路径）。
        """
        from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient

        client = LegacyZmqClient()
        errors = []
        client.request_repair(
            None,  # 无效请求 → 序列化失败
            lambda r: None,
            lambda msg: errors.append(msg),
        )
        # 给 worker 时间启动
        import time
        time.sleep(0.3)
        client.close()
        # 验证：序列化失败应触发 on_error（至少有一条错误消息）
        assert len(errors) > 0, "无效请求应触发 on_error 回调"
        assert isinstance(errors[0], str), "error 消息应为字符串"

    def test_check_health_no_crash(self, qapp):
        """LegacyZmqClient.check_health 应回调或优雅降级（无引擎时）。"""
        from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient

        client = LegacyZmqClient()
        results = []

        def cb(ok, msg):
            results.append((ok, msg))

        client.check_health(cb)
        # 给 worker 充分时间启动和回调（异步时序）
        import time
        time.sleep(1.0)
        client.close()
        # 验证：回调被调用 OR 无崩溃（无引擎时可能不回调）
        # 关键是不抛异常。如果回调了，ok 应为 False
        if results:
            ok, msg = results[0]
            assert ok is False, f"无引擎时 ok 应为 False，实际 {ok}"
            assert isinstance(msg, str), "msg 应为字符串"


# ================================================================
# 4. 旧版模块仍可导入（向后兼容）
# ================================================================
class TestLegacyModuleStillAvailable:
    def test_legacy_zmq_client_importable(self):
        """旧版 ZmqRepairClient 仍可导入且可实例化（向后兼容）。"""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from repair_app.communication.zmq_client import ZmqRepairClient
            # 验证：类可调用（不只是 not None）
            assert callable(ZmqRepairClient), "ZmqRepairClient 应为可调用类"
            # 验证：可实例化
            client = ZmqRepairClient()
            assert hasattr(client, "close"), "应暴露 close 方法"
            client.close()

    def test_legacy_module_emits_deprecation_warning(self):
        """实例化旧版 ZmqRepairClient 应发出 DeprecationWarning。"""
        import warnings
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from repair_app.communication.zmq_client import ZmqRepairClient
            client = ZmqRepairClient()
            client.close()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "应发出 DeprecationWarning"


# ================================================================
# Fixtures
# ================================================================
@pytest.fixture
def qapp():
    """提供 QApplication 实例（offscreen）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
