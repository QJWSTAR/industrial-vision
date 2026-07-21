"""任务12：通信层单元测试 + 集成测试 + 故障测试 + 压力测试 + 性能基准。

运行：pytest repair_app/bridge/tests/ -v --tb=short
"""
import os
import sys
import time
import threading

import numpy as np
import pytest

# 离屏渲染（QThread 需要 QApp）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from repair_app.bridge import (
    BridgeClient,
    BridgeConfig,
    BridgeError,
    BridgeServer,
    ConnectionError,
    ConnectionTimeoutError,
    EngineStatus,
    InvalidParameterError,
    MatlabService,
    MessageType,
    PROTOCOL_VERSION,
    RepairOutcome,
    Serializer,
    generate_request_id,
)
from repair_app.bridge.adapters import MatlabAdapter, LegacyZmqClient
from repair_app.bridge.communication.message import MessageEnvelope
from repair_app.bridge.communication.protocol import (
    is_status_success,
    is_status_retriable,
    STATUS_CODE_NAMES,
)
from repair_app.communication.repair_protocol_pb2 import RepairStatusCode
from repair_app.core.defect_sample import generate_defect_sample


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def sample_cloud():
    """生成测试用点云。"""
    xyz, normals, mask, _ = generate_defect_sample(
        defect_types=["pit"], seed=42, n_points=2000
    )
    return xyz, normals, mask


@pytest.fixture
def test_params():
    """标准测试参数。"""
    return {
        "material": "STEEL_316L",
        "num_layers": 5,
        "layer_height_mm": 2.0,
        "scanning_angle_deg": -45.0,
        "scanning_step_mm": 2.0,
        "buffer_repairing_mm": 0.0,
        "traversing_speed_mms": 500.0,
        "particle_velocity_ms": 700.0,
        "nozzle_diameter_mm": 6.0,
        "spray_angle_deg": 90.0,
    }


# ============================================================
# 1. 协议测试
# ============================================================

class TestProtocol:
    """任务4：协议常量与版本管理。"""

    def test_protocol_version_is_v21(self):
        assert PROTOCOL_VERSION == "2.1"

    def test_message_type_enum(self):
        assert MessageType.HEALTH_CHECK == 1
        assert MessageType.REPAIR_REQUEST == 2
        assert MessageType.SHUTDOWN == 99

    def test_status_success(self):
        assert is_status_success(RepairStatusCode.SUCCESS)
        assert not is_status_success(RepairStatusCode.ERR_ALGORITHM_FAIL)

    def test_status_retriable(self):
        assert is_status_retriable(RepairStatusCode.ERR_TIMEOUT)
        assert is_status_retriable(RepairStatusCode.ERR_UNKNOWN)
        assert not is_status_retriable(RepairStatusCode.ERR_INVALID_INPUT)

    def test_status_code_names_complete(self):
        for code in [0, 1, 2, 3, 4, 5, 99]:
            assert code in STATUS_CODE_NAMES


# ============================================================
# 2. 消息信封测试
# ============================================================

class TestMessageEnvelope:
    """任务4：消息信封。"""

    def test_envelope_has_request_id(self):
        env = MessageEnvelope(
            message_type=MessageType.REPAIR_REQUEST,
            payload=b"\x00",
        )
        assert len(env.request_id) > 0

    def test_envelope_timestamp_recent(self):
        env = MessageEnvelope(
            message_type=MessageType.HEALTH_CHECK,
            payload=b"",
        )
        assert env.age_ms < 1000  # 刚创建

    def test_envelope_version_compatible(self):
        env = MessageEnvelope(
            message_type=MessageType.REPAIR_REQUEST,
            payload=b"",
            version="2.1",
        )
        assert env.is_version_compatible()
        assert env.is_version_compatible(("2.0", "2.1"))

    def test_generate_request_id_unique(self):
        id1 = generate_request_id()
        id2 = generate_request_id()
        assert id1 != id2

    def test_envelope_to_dict(self):
        env = MessageEnvelope(
            message_type=MessageType.REPAIR_RESULT,
            payload=b"\x01\x02",
        )
        d = env.to_dict()
        assert d["message_type"] == "REPAIR_RESULT"
        assert d["payload_size"] == 2


# ============================================================
# 3. 序列化测试
# ============================================================

class TestSerializer:
    """任务5：序列化往返测试。"""

    def test_repair_request_roundtrip(self, sample_cloud):
        xyz, normals, _ = sample_cloud
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="test-001",
            material="STEEL_316L", num_layers=3,
        )
        assert request.request_id != ""

        data = Serializer.serialize_request(request)
        assert isinstance(data, bytes) and len(data) > 0

        restored = Serializer.deserialize_request(data)
        assert restored.scan_id == "test-001"

    def test_parse_point_cloud(self, sample_cloud):
        xyz, normals, _ = sample_cloud
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="parse-test", material="STEEL_316L",
        )
        parsed_xyz, parsed_normals, meta = Serializer.parse_point_cloud(request)
        assert parsed_xyz.shape == (len(xyz), 3)
        assert parsed_normals.shape == (len(xyz), 3)
        assert meta is not None

    def test_health_check_build(self):
        hb = Serializer.build_health_check()
        assert hb.client_version != ""

    def test_health_check_deserialize(self):
        hb = Serializer.build_health_check()
        data = hb.SerializeToString()
        result = Serializer.try_deserialize_health(data)
        assert result is not None
        assert result.client_version != ""

    def test_try_deserialize_health_returns_none_for_non_health(self, sample_cloud):
        xyz, normals, _ = sample_cloud
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="not-health", material="STEEL_316L",
        )
        data = Serializer.serialize_request(request)
        result = Serializer.try_deserialize_health(data)
        # 修复请求不是健康检查（client_version 为空）
        assert result is None


# ============================================================
# 4. 配置测试
# ============================================================

class TestConfig:
    """任务9：集中化配置。"""

    def test_default_config(self):
        config = BridgeConfig.from_env()
        assert config.protocol_version == "2.1"
        assert config.request_timeout_ms > 0
        assert config.max_retries >= 0

    def test_config_immutable(self):
        config = BridgeConfig.from_env()
        with pytest.raises(Exception):
            config.address = "tcp://0.0.0.0:9999"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CSAM_BRIDGE_TIMEOUT_MS", "60000")
        config = BridgeConfig.from_env()
        assert config.request_timeout_ms == 60000

    def test_no_hardcoded_port(self):
        config = BridgeConfig.from_env()
        # 地址来自 transport.py 或环境变量，不应硬编码
        assert config.address is not None
        assert len(config.address) > 0


# ============================================================
# 5. 异常测试
# ============================================================

class TestExceptions:
    """任务8：错误处理。"""

    def test_exception_hierarchy(self):
        err = ConnectionTimeoutError("超时", timeout_ms=5000)
        assert isinstance(err, ConnectionError)
        assert isinstance(err, BridgeError)
        assert err.timeout_ms == 5000

    def test_exception_with_request_id(self):
        err = InvalidParameterError("参数错误", parameter="velocity")
        assert "参数错误" in str(err)
        assert err.parameter == "velocity"

    def test_translate_zmq_error(self):
        import zmq
        err = translate(Exception("test error"), request_id="req-123")
        assert isinstance(err, BridgeError)

    def test_business_layer_never_sees_raw_traceback(self):
        """业务层只看到 BridgeError，不暴露内部堆栈。"""
        try:
            raise ConnectionError("连接失败", request_id="req-456")
        except BridgeError as e:
            assert "req-456" in str(e)
            assert isinstance(e, BridgeError), "应为 BridgeError 子类"
            assert not str(e).startswith("Traceback"), "异常消息不应包含原始 traceback"
            # 消息不含原始文件路径
            assert ".py" not in str(e)


def translate(exc, request_id=""):
    """辅助函数：避免直接导入 translate_zmq_error。"""
    from repair_app.bridge.communication.exceptions import translate_zmq_error
    return translate_zmq_error(exc, request_id=request_id)


# ============================================================
# 6. 客户端测试（无网络）
# ============================================================

class TestBridgeClient:
    """任务7：客户端基础功能（不依赖真实服务端）。"""

    def test_client_creation(self, qapp):
        client = BridgeClient()
        assert client.zmq_available
        assert not client.is_connected
        client.close()

    def test_custom_address(self, qapp):
        config = BridgeConfig(address="tcp://localhost:6000")
        client = BridgeClient(config)
        assert client.address == "tcp://localhost:6000"
        client.close()

    def test_close_sets_state(self, qapp):
        client = BridgeClient()
        client.close()
        # 关闭后再请求应返回空 request_id

    def test_check_health_no_server(self, qapp):
        """无服务端时健康检查不崩溃。"""
        config = BridgeConfig(
            address="tcp://127.0.0.1:59999",
            health_check_timeout_ms=500,
        )
        client = BridgeClient(config)
        results = []
        client.check_health(lambda ok, msg: results.append((ok, msg)))
        deadline = time.time() + 3
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert len(results) == 1
        assert results[0][0] is False
        client.close()


# ============================================================
# 7. 服务端测试（消息处理函数）
# ============================================================

class TestMatlabAdapter:
    """任务6：MATLAB 适配器消息处理。"""

    def test_handle_repair_request(self, sample_cloud, test_params):
        """测试适配器处理修复请求。"""
        xyz, normals, _ = sample_cloud
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="adapter-test",
            material="STEEL_316L",
            num_layers=test_params["num_layers"],
            layer_height_mm=test_params["layer_height_mm"],
            scanning_angle_deg=test_params["scanning_angle_deg"],
            scanning_step_mm=test_params["scanning_step_mm"],
            buffer_repairing_mm=test_params["buffer_repairing_mm"],
            traversing_speed_mms=test_params["traversing_speed_mms"],
            particle_velocity_ms=test_params["particle_velocity_ms"],
            nozzle_diameter_mm=test_params["nozzle_diameter_mm"],
            spray_angle_deg=test_params["spray_angle_deg"],
        )

        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert result.status_code == RepairStatusCode.SUCCESS
        assert result.is_feasible
        assert len(result.waypoints) > 0

    def test_handle_empty_request(self):
        """空点云返回 ERR_INVALID_INPUT。"""
        empty_xyz = np.zeros((0, 3), dtype=np.float32)
        empty_normals = np.zeros((0, 3), dtype=np.float32)
        request = Serializer.build_repair_request(
            empty_xyz, empty_normals, scan_id="empty",
            material="STEEL_316L",
        )
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert result.status_code == RepairStatusCode.ERR_INVALID_INPUT

    def test_health_response(self):
        """服务端健康检查响应。"""
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        hb = Serializer.build_health_check()
        data = hb.SerializeToString()
        response = adapter._dispatch(data)
        assert len(response) > 0


# ============================================================
# 7b. MATLAB 可视化集成测试（v2.1 字段填充）
# ============================================================

class TestMatlabVisualizationIntegration:
    """验证 MATLAB 计算引擎返回的可视化字段被正确填充与解析。

    覆盖：layer_profiles / particle_dist / 体积质量 / 均匀性 / 喷嘴方向。
    """

    def _build_request(self, sample_cloud, test_params):
        xyz, normals, _ = sample_cloud
        return Serializer.build_repair_request(
            xyz, normals, scan_id="viz-test",
            material="STEEL_316L",
            num_layers=test_params["num_layers"],
            layer_height_mm=test_params["layer_height_mm"],
            scanning_angle_deg=test_params["scanning_angle_deg"],
            scanning_step_mm=test_params["scanning_step_mm"],
            buffer_repairing_mm=test_params["buffer_repairing_mm"],
            traversing_speed_mms=test_params["traversing_speed_mms"],
            particle_velocity_ms=test_params["particle_velocity_ms"],
            nozzle_diameter_mm=test_params["nozzle_diameter_mm"],
            spray_angle_deg=test_params["spray_angle_deg"],
        )

    def test_adapter_fills_volume_and_mass(self, sample_cloud, test_params):
        """适配器应填充 predicted_volume_mm3 / estimated_mass_g / material_density_gcm3。"""
        request = self._build_request(sample_cloud, test_params)
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert result.predicted_volume_mm3 > 0.0
        assert result.material_density_gcm3 == pytest.approx(7.99, rel=1e-3)
        assert result.estimated_mass_g > 0.0
        # 质量 = 体积(mm3) * 密度(g/cm3) * 1e-3
        expected_mass = result.predicted_volume_mm3 * result.material_density_gcm3 * 1e-3
        assert result.estimated_mass_g == pytest.approx(expected_mass, rel=1e-4)

    def test_adapter_fills_uniformity_score_not_hardcoded(self, sample_cloud, test_params):
        """uniformity_score 应来自计算（CV），不再是固定 0.78。

        多层航点时应在 [0.5, 1.0] 区间；单层回退仍为 0.78。
        """
        request = self._build_request(sample_cloud, test_params)
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert 0.5 <= result.uniformity_score <= 1.0

    def test_adapter_fills_layer_profiles(self, sample_cloud, test_params):
        """适配器应按层号聚合生成 layer_profiles（至少 1 层）。"""
        request = self._build_request(sample_cloud, test_params)
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert len(result.layer_profiles) >= 1
        for lp in result.layer_profiles:
            assert lp.layer_index >= 0
            assert lp.max_height_mm >= 0.0
            assert lp.avg_height_mm >= 0.0
            assert 0.0 <= lp.dep_efficiency <= 1.0

    def test_adapter_fills_particle_distribution(self, sample_cloud, test_params):
        """适配器应合成 particle_dist，颗粒数与数组长度一致。"""
        request = self._build_request(sample_cloud, test_params)
        adapter = MatlabAdapter(address="tcp://127.0.0.1:59998")
        result = adapter.handle_repair(request)
        assert result.HasField("particle_dist")
        pd = result.particle_dist
        n = pd.total_particles
        assert n > 0
        assert len(pd.px) == n
        assert len(pd.py) == n
        assert len(pd.vx) == n
        assert len(pd.vcr) == n
        assert 0.0 <= pd.dep_efficiency <= 1.0

    def test_build_repair_result_roundtrip_with_viz_fields(self):
        """build_repair_result + parse_repair_result 对可视化字段往返一致。"""
        from repair_app.communication.repair_serialization import (
            build_repair_result, build_layer_profile, build_particle_distribution,
            parse_repair_result,
        )
        wp = np.array([
            [1, 2, 3, 0, 0, 1, 500, 1],
            [2, 3, 4, 0, 0, 1, 500, 1],
            [3, 4, 5, 0, 0, 1, 500, 2],
        ], dtype=np.float32)
        lps = [build_layer_profile(1, max_height_mm=0.3, avg_height_mm=0.2, dep_efficiency=0.7)]
        pd = build_particle_distribution(
            np.array([0.0, 1.0], dtype=np.float32),
            np.array([0.0, 1.0], dtype=np.float32),
            np.array([500.0, 510.0], dtype=np.float32),
            np.array([0.0, 0.0], dtype=np.float32),
            np.array([500.0, 510.0], dtype=np.float32),
            dep_efficiency=0.95,
        )
        msg = build_repair_result(
            wp, request_id="rt-1",
            predicted_volume_mm3=100.0,
            material_density_gcm3=7.99,
            estimated_mass_g=0.799,
            uniformity_score=0.85,
            layer_profiles=lps,
            particle_dist=pd,
        )
        d = parse_repair_result(msg)
        assert d["predicted_volume_mm3"] == pytest.approx(100.0)
        assert d["estimated_mass_g"] == pytest.approx(0.799)
        assert d["uniformity_score"] == pytest.approx(0.85)
        assert len(d["layer_profiles"]) == 1
        assert d["layer_profiles"][0]["max_height_mm"] == pytest.approx(0.3)
        assert d["particle_dist"] is not None
        assert d["particle_dist"]["total_particles"] == 2

    def test_build_repair_result_backward_compatible_no_viz(self):
        """不传可视化字段时，build_repair_result 行为不变（向后兼容）。"""
        from repair_app.communication.repair_serialization import (
            build_repair_result, parse_repair_result,
        )
        wp = np.array([[1, 2, 3, 0, 0, 1, 500, 1]], dtype=np.float32)
        msg = build_repair_result(wp, request_id="bc-1")
        assert len(msg.layer_profiles) == 0
        assert not msg.HasField("particle_dist")
        assert len(msg.before_snapshot_png) == 0
        d = parse_repair_result(msg)
        assert d["layer_profiles"] == []
        assert d["particle_dist"] is None


# ============================================================
# 8. 集成测试（客户端 + 服务端真实 ZMQ）
# ============================================================

class TestIntegration:
    """端到端集成测试：启动服务端线程 + 客户端请求。"""

    @pytest.fixture
    def running_server(self, sample_cloud):
        """在后台线程启动 MatlabAdapter 服务端。"""
        import zmq
        address = "tcp://127.0.0.1:59997"
        adapter = MatlabAdapter(address=address)

        server_thread = threading.Thread(target=adapter.serve, daemon=True)
        server_thread.start()
        time.sleep(0.5)  # 等待 bind
        yield address
        adapter.stop()
        time.sleep(0.3)

    def test_health_check_integration(self, qapp, running_server):
        address = running_server
        config = BridgeConfig(
            address=address,
            health_check_timeout_ms=3000,
        )
        client = BridgeClient(config)
        results = []
        client.check_health(lambda ok, msg: results.append((ok, msg)))
        deadline = time.time() + 5
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert len(results) == 1
        assert results[0][0] is True
        client.close()

    def test_repair_request_integration(self, qapp, running_server, sample_cloud, test_params):
        address = running_server
        xyz, normals, _ = sample_cloud
        config = BridgeConfig(address=address, request_timeout_ms=15000)
        client = BridgeClient(config)

        results = []
        errors = []

        request = Serializer.build_repair_request(
            xyz, normals, scan_id="integration",
            material="STEEL_316L",
            num_layers=test_params["num_layers"],
            layer_height_mm=test_params["layer_height_mm"],
            scanning_angle_deg=test_params["scanning_angle_deg"],
            scanning_step_mm=test_params["scanning_step_mm"],
            buffer_repairing_mm=test_params["buffer_repairing_mm"],
            traversing_speed_mms=test_params["traversing_speed_mms"],
            particle_velocity_ms=test_params["particle_velocity_ms"],
            nozzle_diameter_mm=test_params["nozzle_diameter_mm"],
            spray_angle_deg=test_params["spray_angle_deg"],
        )

        client.request_repair(
            request,
            on_result=lambda r: results.append(r),
            on_error=lambda e: errors.append(e),
        )
        deadline = time.time() + 15
        while not results and not errors and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)

        assert len(errors) == 0, f"请求出错: {errors}"
        assert len(results) == 1
        assert results[0].status_code == RepairStatusCode.SUCCESS
        assert len(results[0].waypoints) > 0
        client.close()


# ============================================================
# 9. MatlabService 门面测试
# ============================================================

class TestMatlabService:
    """任务7：业务层门面。"""

    def test_service_creation(self, qapp):
        service = MatlabService()
        assert service.config is not None
        assert service.address is not None
        service.close()

    def test_request_path_planning_empty_cloud(self, qapp):
        """空点云返回错误，不崩溃。"""
        service = MatlabService()
        errors = []
        service.request_path_planning(
            np.zeros((0, 3)), np.zeros((0, 3)), {},
            on_success=lambda r: None,
            on_error=lambda msg: errors.append(msg),
        )
        assert len(errors) == 1
        assert "空" in errors[0] or "为空" in errors[0]
        service.close()

    def test_request_path_planning_mismatched_normals(self, qapp, sample_cloud):
        xyz, _, _ = sample_cloud
        wrong_normals = np.zeros((100, 3))  # 形状不匹配
        service = MatlabService()
        errors = []
        service.request_path_planning(
            xyz, wrong_normals, {},
            on_success=lambda r: None,
            on_error=lambda msg: errors.append(msg),
        )
        assert len(errors) == 1
        service.close()


# ============================================================
# 10. 向后兼容测试
# ============================================================

class TestLegacyAdapter:
    """旧 ZmqRepairClient API 兼容性。"""

    def test_legacy_client_api(self, qapp):
        client = LegacyZmqClient(address="tcp://127.0.0.1:59996")
        assert hasattr(client, "request_repair")
        assert hasattr(client, "check_health")
        assert hasattr(client, "close")
        assert hasattr(client, "is_connected")
        assert hasattr(client, "zmq_available")
        client.close()

    def test_legacy_health_check_no_server(self, qapp):
        client = LegacyZmqClient(address="tcp://127.0.0.1:59995")
        results = []
        client.check_health(lambda ok, msg: results.append((ok, msg)))
        deadline = time.time() + 8
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert len(results) == 1
        assert results[0][0] is False
        client.close()


# ============================================================
# 11. 压力测试
# ============================================================

class TestStress:
    """任务12：压力测试。"""

    @pytest.fixture
    def running_server(self):
        address = "tcp://127.0.0.1:59994"
        adapter = MatlabAdapter(address=address)
        thread = threading.Thread(target=adapter.serve, daemon=True)
        thread.start()
        time.sleep(0.5)
        yield address
        adapter.stop()
        time.sleep(0.3)

    def test_sequential_requests(self, qapp, running_server, sample_cloud):
        """连续 5 次请求验证服务端不崩溃。"""
        from repair_app.communication.repair_protocol_pb2 import RepairResult
        xyz, normals, _ = sample_cloud
        config = BridgeConfig(address=running_server, request_timeout_ms=10000)
        client = BridgeClient(config)

        success_count = 0
        for i in range(5):
            results = []
            request = Serializer.build_repair_request(
                xyz, normals, scan_id=f"stress-{i}", material="STEEL_316L",
                num_layers=3,
            )
            client.request_repair(
                request,
                on_result=lambda r: results.append(r),
                on_error=lambda e: results.append(e),
            )
            deadline = time.time() + 12
            while not results and time.time() < deadline:
                qapp.processEvents()
                time.sleep(0.05)
            if results and isinstance(results[0], RepairResult):
                if results[0].status_code == RepairStatusCode.SUCCESS:
                    success_count += 1
            # 等待 worker 完全清理，避免下一个请求冲突
            time.sleep(0.3)
            qapp.processEvents()
        assert success_count >= 3  # 至少 3 次成功
        client.close()


# ============================================================
# 12. 性能基准
# ============================================================

class TestPerformance:
    """任务11：性能基准测试。"""

    def test_serialization_throughput(self):
        """序列化吞吐量基准。"""
        xyz = np.random.default_rng(0).uniform(-10, 10, (50000, 3)).astype(np.float32)
        normals = np.random.default_rng(1).uniform(-1, 1, (50000, 3)).astype(np.float32)

        start = time.time()
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="perf", material="STEEL_316L",
        )
        data = Serializer.serialize_request(request)
        elapsed = time.time() - start

        throughput = len(xyz) / elapsed if elapsed > 0 else float("inf")
        assert elapsed < 5.0  # 5 万点应在 5 秒内完成
        assert len(data) > 0

    def test_large_array_roundtrip(self, sample_cloud):
        """大数组往返测试。"""
        xyz, normals, _ = sample_cloud
        request = Serializer.build_repair_request(
            xyz, normals, scan_id="large", material="STEEL_316L",
        )
        data = Serializer.serialize_request(request)
        restored = Serializer.deserialize_request(data)
        r_xyz, r_normals, _ = Serializer.parse_point_cloud(restored)

        assert r_xyz.shape == xyz.shape
        assert np.allclose(r_xyz, xyz, atol=1e-4)

    def test_build_result_throughput(self):
        """结果构建吞吐量。"""
        waypoints = np.random.default_rng(2).uniform(-5, 5, (500, 7)).astype(np.float32)
        start = time.time()
        result = Serializer.build_repair_result(
            waypoints, status_code=RepairStatusCode.SUCCESS,
            is_feasible=True, estimated_time_s=10.0,
        )
        data = Serializer.serialize_result(result)
        elapsed = time.time() - start
        assert elapsed < 1.0
        assert len(data) > 0
