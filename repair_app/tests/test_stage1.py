"""
test_stage1.py — Stage 1 集成自检 v2.1
验证：v2.1 协议一致性 / 多种缺陷假数据 / 序列化往返 / ParticleDistribution / MaterialParams / UI

运行：
    python3 -m pytest test_stage1.py -v
"""

from __future__ import annotations
import sys, os, tempfile, time
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from repair_app.core.defect_sample import (
    generate_defect_sample, generate_mock_particle_distribution, generate_mock_repair_result,
)
from repair_app.communication.repair_serialization import (
    build_repair_request, parse_point_cloud, parse_repair_result,
    serialize_request, deserialize_request, serialize_result, deserialize_result,
    build_health_check_request, parse_health_check_response,
    build_particle_distribution, parse_particle_distribution, load_material_params,
    build_progress_update, parse_progress_update,
)
from repair_app.communication.repair_protocol_pb2 import RepairStatusCode, RepairResult, ParticleDistribution, ProgressUpdate

N_SMALL = 5000


# ================================================================
# 1. 协议一致性（含 v2.1 参数）
# ================================================================

class TestProtocolRoundtrip:
    def test_cloud_roundtrip_precision(self) -> None:
        rng = np.random.default_rng(42)
        xyz = (rng.random((N_SMALL, 3), dtype=np.float32) * 200 - 100)
        normals = rng.random((N_SMALL, 3), dtype=np.float32)
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        req = build_repair_request(xyz, normals, scan_id="TEST-001")
        raw = serialize_request(req)
        recovered = deserialize_request(raw)
        xyz2, normals2, meta = parse_point_cloud(recovered)
        assert xyz2.shape == (N_SMALL, 3)
        np.testing.assert_array_almost_equal(xyz, xyz2, decimal=5)
        np.testing.assert_array_almost_equal(normals, normals2, decimal=5)

    def test_empty_point_cloud(self) -> None:
        req = build_repair_request(np.empty((0,3), dtype=np.float32),
                                    np.empty((0,3), dtype=np.float32), scan_id="EMPTY")
        xyz, normals, meta = parse_point_cloud(req)
        assert xyz.shape == (0, 3)
        assert meta["point_count"] == 0

    def test_single_point(self) -> None:
        xyz = np.array([[10.,20.,30.]], dtype=np.float32)
        n = np.array([[0.,0.,1.]], dtype=np.float32)
        req = build_repair_request(xyz, n, scan_id="SINGLE")
        xyz2, n2, _ = parse_point_cloud(req)
        np.testing.assert_array_equal(xyz, xyz2)

    def test_parameter_preservation(self) -> None:
        xyz = np.random.randn(100, 3).astype(np.float32)
        n = np.zeros_like(xyz); n[:,2] = 1.0
        req = build_repair_request(xyz, n, scan_id="PARAM-TEST",
            depth_compensation=1.5, smooth_threshold=0.8, max_layers=7,
            particle_velocity_ms=550.0, critical_velocity_ms=420.0,
            layer_height_mm=2.0, scanning_angle_deg=-45.0, material_id="Cu")
        _, _, meta = parse_point_cloud(req)
        assert abs(meta["particle_velocity_ms"] - 550.0) < 1e-6
        assert abs(meta["critical_velocity_ms"] - 420.0) < 1e-6
        assert abs(meta["layer_height_mm"] - 2.0) < 1e-6
        assert abs(meta["scanning_angle_deg"] + 45.0) < 1e-6
        assert meta["material_id"] == "Cu"
        assert meta["max_layers"] == 7

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="行数不一致"):
            build_repair_request(
                np.random.randn(100,3).astype(np.float32),
                np.random.randn(99,3).astype(np.float32), scan_id="BAD")

    def test_wrong_shape_raises(self) -> None:
        with pytest.raises(ValueError, match="形状"):
            build_repair_request(
                np.random.randn(100).astype(np.float32),
                np.random.randn(100,3).astype(np.float32), scan_id="BAD")

    def test_health_check(self) -> None:
        req = build_health_check_request()
        from repair_app.communication.repair_protocol_pb2 import HealthCheckResponse
        resp = HealthCheckResponse()
        resp.status = HealthCheckResponse.OK
        resp.service_version = "0.2.0"
        result = parse_health_check_response(resp)
        assert result["status"] == "OK"
        assert result["service_version"] == "0.2.0"

    # ---- v2.1 新增 ----
    def test_particle_distribution_roundtrip(self) -> None:
        pd = build_particle_distribution(
            px=np.array([0.,1.,2.], dtype=np.float32),
            py=np.array([0.,0.5,1.], dtype=np.float32),
            vx=np.array([100.,200.,300.], dtype=np.float32),
            vy=np.zeros(3, dtype=np.float32),
            vz=np.array([500.,500.,500.], dtype=np.float32),
            temperature=np.array([600.,620.,580.], dtype=np.float32),
            diameter=np.array([25.,30.,20.], dtype=np.float32),
            vcr=np.array([1.,1.,0.], dtype=np.float32),
            dep_efficiency=0.75,
        )
        raw = pd.SerializeToString()
        pd2 = ParticleDistribution()
        pd2.ParseFromString(raw)
        parsed = parse_particle_distribution(pd2)
        assert parsed["total_particles"] == 3
        assert abs(parsed["dep_efficiency"] - 0.75) < 1e-6
        assert parsed["vcr"].tolist() == [1., 1., 0.]

    def test_material_params_loading(self) -> None:
        mp = load_material_params("Cu")
        assert mp.material_id == "Cu"
        assert mp.density_gcm3 > 0
        assert mp.critical_velocity_ms > 0

    def test_repair_result_status_codes(self) -> None:
        for code, name in [
            (RepairStatusCode.SUCCESS, "SUCCESS"),
            (RepairStatusCode.ERR_NOT_FEASIBLE, "ERR_NOT_FEASIBLE"),
        ]:
            msg = RepairResult()
            msg.status_code = code
            msg.error_message = f"test: {name}"
            result = parse_repair_result(msg)
            assert result["status_name"] == name

    def test_progress_update_roundtrip(self) -> None:
        wp = np.array([[0, 0, 1], [1, 0, 1]], dtype=np.float32)
        msg = build_progress_update(
            "REQ-1",
            ProgressUpdate.PATH_PLANNING,
            layer_index=1,
            total_layers=3,
            progress=0.33,
            message="layer 1",
            waypoints=wp,
        )
        parsed = parse_progress_update(msg)
        assert parsed["request_id"] == "REQ-1"
        assert parsed["stage_name"] == "PATH_PLANNING"
        assert parsed["waypoints"].shape == (2, 7)
        assert parsed["layer_index"] == 1


# ================================================================
# 2. 假数据生成（v2.1 扩展）
# ================================================================

class TestDefectSample:
    def test_generate_returns_valid_data(self) -> None:
        xyz, normals, mask, info = generate_defect_sample(n_points=10000, seed=42)
        assert xyz.shape == (10000, 3)
        assert normals.shape == (10000, 3)
        assert mask.shape == (10000,)
        assert mask.dtype == bool
        assert mask.sum() > 0, "应有缺陷点"
        assert isinstance(info, dict)
        assert "defects" in info
        assert info["total_defect_points"] == mask.sum()

    def test_generate_is_deterministic(self) -> None:
        xyz1, n1, m1, _ = generate_defect_sample(n_points=5000, seed=42)
        xyz2, n2, m2, _ = generate_defect_sample(n_points=5000, seed=42)
        np.testing.assert_array_equal(xyz1, xyz2)
        np.testing.assert_array_equal(m1, m2)

    def test_all_defect_types(self) -> None:
        for dtype in ["pit", "groove", "scratch", "irregular"]:
            xyz, normals, mask, info = generate_defect_sample(
                n_points=30000, seed=42, defect_types=[dtype])
            assert mask.sum() > 0, f"缺陷类型 {dtype} 应产生缺陷点"
            types_found = [d["type"] for d in info["defects"]]
            assert dtype in types_found

    def test_multi_defect_types(self) -> None:
        _, _, mask, info = generate_defect_sample(
            n_points=30000, seed=42, defect_types=["pit","groove","scratch","irregular"])
        assert mask.sum() > 500, "多种缺陷应产生足够多缺陷点"
        types_found = [d["type"] for d in info["defects"]]
        assert len(types_found) == 4

    def test_mock_particle_distribution(self) -> None:
        pd = generate_mock_particle_distribution(n_particles=5000, seed=42)
        assert pd.total_particles == 5000
        assert 0 < pd.dep_efficiency <= 1.0

    def test_mock_repair_result(self) -> None:
        rr = generate_mock_repair_result(n_waypoints=200, seed=42)
        assert len(rr.waypoints) == 200
        assert rr.predicted_volume_mm3 > 0
        assert rr.is_feasible
        assert rr.uniformity_score > 0
        assert len(rr.layer_profiles) > 0


# ================================================================
# 3. 性能测试
# ================================================================

class TestSerializationPerformance:
    def test_serialize_speed(self) -> None:
        rng = np.random.default_rng(42)
        xyz = (rng.random((10000, 3), dtype=np.float32) * 200 - 100)
        n = np.zeros_like(xyz); n[:, 2] = 1.0
        req = build_repair_request(xyz, n, scan_id="PERF-TEST",
            particle_velocity_ms=500.0, layer_height_mm=2.0)
        t0 = time.perf_counter()
        raw = serialize_request(req)
        t1 = time.perf_counter()
        recovered = deserialize_request(raw)
        t2 = time.perf_counter()
        assert (t1 - t0) * 1000 < 50, f"序列化过慢"
        assert (t2 - t1) * 1000 < 50, f"反序列化过慢"


# ================================================================
# 4. 二进制文件格式
# ================================================================

class TestBinaryFormat:
    def test_write_read_file(self) -> None:
        rng = np.random.default_rng(99)
        xyz = (rng.random((1000,3), dtype=np.float32) * 200 - 100)
        n = np.zeros_like(xyz); n[:,2] = 1.0
        req = build_repair_request(xyz, n, scan_id="FILE-TEST",
            material_id="Cu", layer_height_mm=2.0)
        raw = serialize_request(req)
        with tempfile.NamedTemporaryFile(suffix=".repair", delete=False) as f:
            f.write(raw); tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                loaded_raw = f.read()
            assert loaded_raw == raw
            recovered = deserialize_request(loaded_raw)
            xyz2, n2, meta = parse_point_cloud(recovered)
            np.testing.assert_array_almost_equal(xyz, xyz2, decimal=5)
            assert meta["material_id"] == "Cu"
        finally:
            os.unlink(tmp_path)


# ================================================================
# 5. UI 结构验证
# ================================================================

class TestUIStructure:
    def test_main_window_import(self, qapp) -> None:
        """验证 MainWindow 可导入且可实例化（不只是 callable）。"""
        import repair_app.ui.main_window
        assert hasattr(repair_app.ui.main_window, "MainWindow")
        assert callable(repair_app.ui.main_window.MainWindow)
        # 进一步验证：实例化不抛异常
        mw = repair_app.ui.main_window.MainWindow()
        try:
            assert mw is not None
            # 验证核心组件存在
            assert hasattr(mw, "_visualizer") or hasattr(mw, "_defect_selector"), \
                "MainWindow 应有可视化或选区组件"
        finally:
            if hasattr(mw, "_zmq_client") and mw._zmq_client is not None:
                mw._zmq_client.close()
            mw.deleteLater()

    def test_defect_sample_import(self) -> None:
        """验证 defect_sample 函数可调用且返回有效数据。"""
        import repair_app.core.defect_sample as defect_sample
        assert callable(defect_sample.generate_defect_sample)
        assert callable(defect_sample.generate_mock_particle_distribution)
        assert callable(defect_sample.generate_mock_repair_result)
        # 进一步验证：调用 generate_defect_sample 返回真实数据
        result = defect_sample.generate_defect_sample(n_points=50)
        assert result is not None
        # 结果应有形状/长度属性
        if hasattr(result, "shape"):
            assert result.shape[0] > 0, "应返回非空数据"
        elif hasattr(result, "__len__"):
            assert len(result) > 0, "应返回非空数据"


if __name__ == "__main__":
    print("=" * 60)
    print("Stage 1 v2.1 集成自检")
    print("=" * 60)
    results = []
    for cls in [TestProtocolRoundtrip, TestDefectSample, TestSerializationPerformance,
                TestBinaryFormat, TestUIStructure]:
        print(f"\n--- {cls.__name__} ---")
        t = cls()
        for name in sorted(dir(t)):
            if name.startswith("test_"):
                try:
                    getattr(t, name)()
                    print(f"  ✅ {name}")
                    results.append(True)
                except Exception as e:
                    print(f"  ❌ {name}: {e}")
                    results.append(False)
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"结果: {passed}/{total} 通过")
    print("✅ Stage 1 v2.1 自检全部通过" if passed == total else f"❌ {total-passed} 个测试失败")
