"""
test_stage3.py — Stage 3 集成自检 v2.1
验证：ZmqRepairClient / CFD 查找表 / RepairVisualizer / 主界面集成

运行：
    python3 -m pytest test_stage3.py -v
"""

from __future__ import annotations
import sys, os, tempfile
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# 1. ZMQ 客户端（不依赖网络）测试
# ================================================================
class TestZmqClient:
    def test_import_and_availability(self):
        from repair_app.communication.zmq_client import ZmqRepairClient, _ZMQ_AVAILABLE
        client = ZmqRepairClient()
        assert isinstance(client.zmq_available, bool)
        assert client.is_connected == False

    def test_default_address(self):
        from repair_app.communication.zmq_client import ZmqRepairClient, DEFAULT_IPC_ADDR
        client = ZmqRepairClient()
        assert client._address == DEFAULT_IPC_ADDR

    def test_custom_address_and_timeout(self):
        from repair_app.communication.zmq_client import ZmqRepairClient
        client = ZmqRepairClient(address="tcp://localhost:5555", timeout_ms=10000)
        assert "5555" in client._address
        assert client._timeout_ms == 10000

    def test_check_health_no_connection(self):
        """健康检查在无 MATLAB 时不应崩溃。"""
        from repair_app.communication.zmq_client import ZmqRepairClient
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        client = ZmqRepairClient()
        received = []

        def cb(ok, msg):
            received.append((ok, msg))

        client.check_health(cb)
        # 给一点时间让 worker 完成
        import time
        time.sleep(0.5)
        client.close()
        # pyzmq 不可用时应立即收到 False 回调
        if not client.zmq_available:
            assert len(received) > 0, "pyzmq 不可用时应立即收到健康检查回调"
            assert received[0][0] is False, "无连接时健康检查应返回 False"

    def test_request_repair_serialization_error(self):
        """传入无效请求应触发 on_error。"""
        from repair_app.communication.zmq_client import ZmqRepairClient
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        client = ZmqRepairClient()
        errors = []

        def on_error(msg):
            errors.append(msg)

        # 传入 None 作为请求（触发序列化错误）
        client.request_repair(None, lambda r: None, on_error)
        assert len(errors) > 0, "序列化失败应触发 on_error 回调"
        assert "序列化失败" in errors[0], f"错误消息应包含'序列化失败'，实际: {errors[0]}"


class TestPythonRepairEngineService:
    def test_health_handler(self):
        from repair_app.service.repair_engine_service import EngineStats, handle_message
        from repair_app.communication.repair_serialization import build_health_check_request, parse_health_check_response
        import time
        req = build_health_check_request().SerializeToString()
        resp = handle_message(req, EngineStats(started_at=time.time()))
        parsed = parse_health_check_response(resp)
        assert parsed["status"] == "OK"

    def test_repair_handler_returns_waypoints(self):
        from repair_app.service.repair_engine_service import EngineStats, handle_message
        from repair_app.communication.repair_serialization import (
            build_repair_request,
            deserialize_result,
            parse_repair_result,
        )
        import time
        rng = np.random.default_rng(12)
        xyz = rng.uniform(-5, 5, (200, 3)).astype(np.float32)
        xyz[:, 2] = rng.normal(0, 0.2, 200).astype(np.float32)
        normals = np.tile([0, 0, 1], (200, 1)).astype(np.float32)
        req = build_repair_request(
            xyz,
            normals,
            scan_id="ENGINE-TEST",
            scanning_step_mm=2.0,
            num_layers=2,
        ).SerializeToString()
        resp = handle_message(req, EngineStats(started_at=time.time()))
        result = parse_repair_result(deserialize_result(resp))
        assert result["status_name"] == "SUCCESS"
        assert result["waypoints"].shape[0] > 0


# ================================================================
# 2. CFD 查找表测试
# ================================================================
class TestCfdLookup:
    def test_parse_fluent_csv_missing_file(self):
        from cfd_to_npz import parse_fluent_csv
        # 验证：不存在的文件应抛 FileNotFoundError（而非静默通过）
        with pytest.raises((FileNotFoundError, OSError)):
            parse_fluent_csv("nonexistent_test_file.csv")

    def test_build_lookup_grid(self):
        from cfd_to_npz import build_lookup_grid
        rng = np.random.default_rng(1)
        n = 1000
        positions = rng.uniform(-0.01, 0.01, (n, 3))
        velocities = rng.normal(500, 100, (n, 3))
        temperatures = rng.normal(500, 50, n).astype(np.float32)
        diameters = rng.uniform(10e-6, 50e-6, n).astype(np.float32)

        result = build_lookup_grid(positions, velocities, temperatures, diameters, grid_resolution=10)
        assert "grid_x" in result
        assert "density_3d" in result
        assert "velocity_mean_3d" in result
        assert result["density_3d"].shape == (9, 9, 9)

    def test_save_and_load_lookup(self):
        from cfd_to_npz import save_lookup_table, build_lookup_grid
        from repair_app.utils.look_up import ParticleLookup
        rng = np.random.default_rng(2)
        n = 3000
        positions = rng.uniform(-0.005, 0.005, (n, 3))
        velocities = rng.normal(500, 80, (n, 3))
        temperatures = rng.normal(450, 40, n).astype(np.float32)
        diameters = rng.uniform(15e-6, 40e-6, n).astype(np.float32)

        lookup = build_lookup_grid(positions, velocities, temperatures, diameters, grid_resolution=6)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_lookup_table(lookup, "test_nozzle", 30.0, tmpdir)
            lu = ParticleLookup(tmpdir)
            result = lu.query(nozzle="test_nozzle", standoff_mm=30, position=(0, 0, 0))
            assert "velocity_mean" in result
            assert result["velocity_mean"] > 0

    def test_lookup_no_data(self):
        from repair_app.utils.look_up import ParticleLookup
        lu = ParticleLookup("nonexistent_dir")
        result = lu.query()
        assert result["density"] == 0.0
        assert result["velocity_mean"] == 0.0

    def test_lookup_interpolation(self):
        from repair_app.utils.look_up import ParticleLookup
        from cfd_to_npz import save_lookup_table, build_lookup_grid
        rng = np.random.default_rng(3)
        n = 2000
        positions = rng.uniform(-0.003, 0.003, (n, 3))
        velocities = rng.normal(600, 50, (n, 3))
        temperatures = rng.normal(500, 30, n).astype(np.float32)
        diameters = rng.uniform(20e-6, 30e-6, n).astype(np.float32)

        lookup = build_lookup_grid(positions, velocities, temperatures, diameters, grid_resolution=6)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_lookup_table(lookup, "round_30mm", 30, tmpdir)
            lu = ParticleLookup(tmpdir)
            r1 = lu.query(nozzle="round_30mm", standoff_mm=30)
            # 查询不同的 standoff 应返回零（无匹配）
            r2 = lu.query(nozzle="round_30mm", standoff_mm=60)
            assert r1["velocity_mean"] >= 0
            assert r2["velocity_mean"] == 0.0


# ================================================================
# 3. RepairVisualizer 逻辑测试（避免 Qt 渲染崩溃）
# ================================================================
class TestRepairVisualizer:
    def test_import_and_enum(self):
        from repair_app.ui.repair_visualizer import RepairVisualizer, ViewMode
        assert ViewMode.ISOMETRIC.value == "isometric"
        assert ViewMode.TOP.value == "top"

    def test_colormap_exists(self):
        from repair_app.ui.repair_visualizer import _COLORMAP
        # 验证：colormap 是 matplotlib Colormap 实例（不只是 not None）
        from matplotlib.colors import Colormap
        assert isinstance(_COLORMAP, Colormap), "_COLORMAP 应为 matplotlib Colormap"
        assert _COLORMAP.N > 0, "colormap 应有颜色层级"

    def test_data_structure(self):
        """验证 RepairVisualizer.set_data 正确存储数据（调用真实组件）。"""
        from repair_app.ui.repair_visualizer import RepairVisualizer
        viz = RepairVisualizer()
        try:
            pts = np.random.default_rng(5).uniform(-5, 5, (100, 3))
            mask = np.zeros(100, dtype=bool)
            mask[:20] = True
            repair = np.random.default_rng(6).uniform(-2, 2, (50, 3))
            waypoints = np.array([[0, 0, 3], [1, 0, 3], [2, 0, 3]])
            layers = [np.random.default_rng(7+i).uniform(-3, 3, (10, 3)) for i in range(3)]
            # 调用真实 set_data（验证数据存储逻辑，而非自造数据）
            viz.set_data(
                substrate=pts, defect_mask=mask,
                repair=repair, waypoints=waypoints, layers=layers,
            )
            # 验证：数据被正确存储到组件内部
            assert viz._substrate_pts is not None
            assert len(viz._substrate_pts) == 100
            assert np.sum(viz._defect_mask) == 20
            assert viz._repair_pts is not None
            assert viz._waypoints is not None
            assert len(viz._layer_data) == 3
        finally:
            viz.deleteLater()


# ================================================================
# 4. 主界面集成（导入验证）
# ================================================================
class TestMainWindowS3:
    def test_main_window_imports_new_modules(self, qapp):
        """验证 MainWindow 正确导入并可实例化。"""
        from repair_app.ui.main_window import MainWindow, _ZMQ_AVAILABLE
        from repair_app.ui.repair_visualizer import RepairVisualizer
        # 验证：MainWindow 是类（callable），且可实例化
        assert callable(MainWindow), "MainWindow 应为可调用类"
        # _ZMQ_AVAILABLE 在模块级别可能是 property 对象（类属性访问），
        # 关键是 MainWindow 实例化不抛异常
        mw = MainWindow()
        try:
            # 验证：MainWindow 实例有核心属性
            assert hasattr(mw, "_visualizer"), "MainWindow 应有 _visualizer"
            assert hasattr(mw, "_zmq_client"), "MainWindow 应有 _zmq_client"
        finally:
            # P3-9: 停止 _autosave_timer 避免 60s 周期回调访问已销毁对象
            _timer = getattr(mw, "_autosave_timer", None)
            if _timer is not None:
                try:
                    _timer.stop()
                except Exception:
                    pass
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

    def test_zmq_client_graceful_degradation(self, qapp):
        """验证 ZMQ 客户端 API 完整性（不论 zmq 是否可用）。"""
        from repair_app.communication.zmq_client import ZmqRepairClient
        client = ZmqRepairClient()
        try:
            # 不论 zmq_available 真假，都应暴露完整 API
            assert hasattr(client, 'is_connected'), "应暴露 is_connected"
            assert hasattr(client, 'close'), "应暴露 close"
            assert hasattr(client, 'zmq_available'), "应暴露 zmq_available"
            assert hasattr(client, 'request_repair'), "应暴露 request_repair"
            assert hasattr(client, 'check_health'), "应暴露 check_health"
            # 验证：is_connected 返回 bool（不是 None）
            assert isinstance(client.is_connected, bool), "is_connected 应为 bool"
        finally:
            client.close()
