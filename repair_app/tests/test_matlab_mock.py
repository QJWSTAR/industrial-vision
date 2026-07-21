"""test_matlab_mock.py — MATLAB Mock 体系测试

验证 Mock 系统的确定性、可观测性和错误处理。
覆盖 deterministic_algorithm / MockMatlabAdapter /
make_mock_repair_request / License Mock 函数。

运行：pytest -m mock -v
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import pytest


# ================================================================
# 1. deterministic_algorithm 测试
# ================================================================
@pytest.mark.mock
class TestDeterministicAlgorithm:
    """确定性 MATLAB 算法 Mock 测试。"""

    def test_returns_100_points(self):
        """非空输入返回 100 个航点（10x10 网格）。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[0, 0, 0], [10, 10, 5]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        assert result.shape == (100, 3), (
            f"应返回 100 个航点 (10x10 网格)，实际形状 {result.shape}"
        )

    def test_z_coordinate_is_max_z_plus_2(self):
        """Z 坐标 = 输入点云最大 Z + 2.0（层高 2mm）。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[0, 0, 0], [10, 10, 5]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        z_max = float(np.max(xyz[:, 2]))
        expected_z = z_max + 2.0
        assert np.all(result[:, 2] == expected_z), (
            f"所有 Z 坐标应为 {expected_z}，实际 {result[:, 2][:5]}"
        )

    def test_deterministic_same_input_same_output(self):
        """相同输入产生相同输出（确定性）。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        rng = np.random.default_rng(42)
        xyz = rng.uniform(-5, 5, (20, 3)).astype(np.float32)
        result1 = deterministic_algorithm(xyz, {})
        result2 = deterministic_algorithm(xyz, {})
        assert np.array_equal(result1, result2), "相同输入应产生完全相同的输出"

    def test_empty_input_returns_empty_array(self):
        """空点云输入返回空数组。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.zeros((0, 3), dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        assert result.shape == (0, 3), f"空输入应返回 (0,3) 数组，实际 {result.shape}"

    def test_xy_range_matches_input(self):
        """输出 XY 范围与输入点云 XY 范围一致。"""
        from repair_app.tests.mocks.matlab_mock import deterministic_algorithm
        xyz = np.array([[1, 2, 0], [11, 12, 0]], dtype=np.float32)
        result = deterministic_algorithm(xyz, {})
        # X 范围 [1, 11]，Y 范围 [2, 12]
        assert result[:, 0].min() >= 1.0 - 1e-6, "X 最小值应 >= 1"
        assert result[:, 0].max() <= 11.0 + 1e-6, "X 最大值应 <= 11"
        assert result[:, 1].min() >= 2.0 - 1e-6, "Y 最小值应 >= 2"
        assert result[:, 1].max() <= 12.0 + 1e-6, "Y 最大值应 <= 12"


# ================================================================
# 2. MockMatlabAdapter 测试
# ================================================================
@pytest.mark.mock
class TestMockMatlabAdapter:
    """MATLAB 适配器 Mock 测试。"""

    def test_handle_repair_returns_dict(self):
        """handle_repair 返回包含正确字段的 dict。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        request = make_mock_repair_request(n_points=100)
        result = adapter.handle_repair(request)
        assert isinstance(result, dict), "handle_repair 应返回 dict"
        assert "waypoints" in result, "结果应包含 waypoints 键"
        assert "status_code" in result, "结果应包含 status_code 键"
        assert "error_message" in result, "结果应包含 error_message 键"
        assert "request_id" in result, "结果应包含 request_id 键"
        assert "compute_time_ms" in result, "结果应包含 compute_time_ms 键"
        # 成功状态码为 0
        assert result["status_code"] == 0, f"成功时 status_code 应为 0，实际 {result['status_code']}"
        # 航点应为非空数组
        assert len(result["waypoints"]) > 0, "成功时航点不应为空"

    def test_call_count_increments(self):
        """call_count 随 handle_repair 调用递增。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        assert adapter.call_count == 0, "初始 call_count 应为 0"
        request = make_mock_repair_request(n_points=10)
        adapter.handle_repair(request)
        assert adapter.call_count == 1, "调用 1 次后 call_count 应为 1"
        adapter.handle_repair(request)
        assert adapter.call_count == 2, "调用 2 次后 call_count 应为 2"

    def test_calls_record_contains_request_id(self):
        """calls 记录包含 request_id 和 timestamp。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        request = make_mock_repair_request(n_points=50, request_id="test-abc-123")
        adapter.handle_repair(request)
        assert len(adapter.calls) == 1, "应有 1 条调用记录"
        call = adapter.calls[0]
        assert call["request_id"] == "test-abc-123", (
            f"记录的 request_id 应为 test-abc-123，实际 {call['request_id']}"
        )
        assert "timestamp" in call, "记录应包含 timestamp"
        assert call["point_count"] == 50, f"记录的 point_count 应为 50，实际 {call['point_count']}"

    def test_check_health_returns_ok(self):
        """check_health 返回 status=OK 的 dict。"""
        from repair_app.tests.mocks.matlab_mock import MockMatlabAdapter
        adapter = MockMatlabAdapter()
        result = adapter.check_health()
        assert isinstance(result, dict), "check_health 应返回 dict"
        assert result["status"] == "OK", f"status 应为 OK，实际 {result['status']}"
        assert "service_version" in result, "应包含 service_version"
        assert "memory_usage_mb" in result, "应包含 memory_usage_mb"
        assert "uptime_s" in result, "应包含 uptime_s"

    def test_shutdown_raises_on_handle(self):
        """shutdown 后 handle_repair 抛出 RuntimeError。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_mock_repair_request,
        )
        adapter = MockMatlabAdapter()
        adapter.shutdown()
        request = make_mock_repair_request(n_points=10)
        with pytest.raises(RuntimeError, match="已关闭"):
            adapter.handle_repair(request)

    def test_empty_request_returns_error(self):
        """空点云请求返回错误状态码。"""
        from repair_app.tests.mocks.matlab_mock import (
            MockMatlabAdapter, make_empty_request,
        )
        adapter = MockMatlabAdapter()
        request = make_empty_request()
        result = adapter.handle_repair(request)
        assert result["status_code"] == 1, (
            f"空点云 status_code 应为 1 (ERR_INVALID_INPUT)，实际 {result['status_code']}"
        )
        assert len(result["waypoints"]) == 0, "空点云航点应为空"
        assert "空点云" in result["error_message"], "错误消息应包含 '空点云'"


# ================================================================
# 3. make_mock_repair_request 测试
# ================================================================
@pytest.mark.mock
class TestMakeMockRepairRequest:
    """测试请求构造函数测试。"""

    def test_creates_request_with_correct_point_count(self):
        """创建的请求包含指定数量的点。"""
        from repair_app.tests.mocks.matlab_mock import make_mock_repair_request
        req = make_mock_repair_request(n_points=100)
        assert len(req.x) == 100, f"x 数组长度应为 100，实际 {len(req.x)}"
        assert len(req.y) == 100, f"y 数组长度应为 100，实际 {len(req.y)}"
        assert len(req.z) == 100, f"z 数组长度应为 100，实际 {len(req.z)}"

    def test_request_id_set_correctly(self):
        """request_id 正确设置。"""
        from repair_app.tests.mocks.matlab_mock import make_mock_repair_request
        req = make_mock_repair_request(n_points=10, request_id="req-456")
        assert req.request_id == "req-456", (
            f"request_id 应为 'req-456'，实际 '{req.request_id}'"
        )

    def test_normals_included(self):
        """include_normals=True 时包含法向量。"""
        from repair_app.tests.mocks.matlab_mock import make_mock_repair_request
        req = make_mock_repair_request(n_points=20, include_normals=True)
        assert len(req.nx) == 20, f"nx 长度应为 20，实际 {len(req.nx)}"
        assert len(req.ny) == 20, f"ny 长度应为 20，实际 {len(req.ny)}"
        assert len(req.nz) == 20, f"nz 长度应为 20，实际 {len(req.nz)}"
        # 默认法向量为 Z 方向 (0, 0, 1)
        assert all(nz == 1.0 for nz in req.nz), "默认法向量 Z 分量应为 1.0"
        assert all(nx == 0.0 for nx in req.nx), "默认法向量 X 分量应为 0.0"

    def test_normals_excluded(self):
        """include_normals=False 时不含法向量。"""
        from repair_app.tests.mocks.matlab_mock import make_mock_repair_request
        req = make_mock_repair_request(n_points=10, include_normals=False)
        assert len(req.nx) == 0, "include_normals=False 时 nx 应为空"
        assert len(req.ny) == 0, "include_normals=False 时 ny 应为空"
        assert len(req.nz) == 0, "include_normals=False 时 nz 应为空"

    def test_max_layers_set(self):
        """max_layers 默认设为 3。"""
        from repair_app.tests.mocks.matlab_mock import make_mock_repair_request
        req = make_mock_repair_request(n_points=10)
        assert req.max_layers == 3, f"max_layers 应为 3，实际 {req.max_layers}"


# ================================================================
# 4. License Mock 测试
# ================================================================
@pytest.mark.mock
class TestLicenseMock:
    """License Mock 体系测试。"""

    def test_create_mock_license_env(self, tmp_path):
        """create_mock_license_env 生成完整 License 环境。"""
        from repair_app.tests.mocks.license_mock import create_mock_license_env
        env = create_mock_license_env(str(tmp_path), days_valid=365)
        # 验证文件存在
        assert os.path.exists(env["license_path"]), "license.key 应存在"
        assert os.path.exists(env["public_key_path"]), "public_key.pem 应存在"
        # 验证返回信息
        assert env["machine_id"] == "test-machine-001", "machine_id 应为固定值"
        assert env["days_valid"] == 365, "days_valid 应为 365"
        assert env["issued_to"] == "Test User", "issued_to 应为 Test User"

    def test_make_test_license_data(self):
        """make_test_license_data 返回正确 LicenseData。"""
        from repair_app.tests.mocks.license_mock import make_test_license_data
        data = make_test_license_data(days_valid=365)
        assert data.machine_id == "test-machine-001", "machine_id 应为固定值"
        assert data.issued_to == "Test User", "issued_to 应为 Test User"
        assert data.expired is False, "365 天有效的 License 不应过期"
        assert data.days_remaining > 0, "剩余天数应 > 0"

    def test_mock_license_manager_valid(self):
        """MockLicenseManager(valid=True) 行为正确。"""
        from repair_app.tests.mocks.license_mock import MockLicenseManager
        mgr = MockLicenseManager(valid=True, days_remaining=365)
        assert mgr.load_license() is True, "valid=True 时 load_license 应返回 True"
        assert mgr.days_remaining == 365, "days_remaining 应为 365"
        assert mgr.check_expiry() == "valid", "365 天有效期状态应为 valid"

    def test_mock_license_manager_invalid(self):
        """MockLicenseManager(valid=False) 行为正确。"""
        from repair_app.tests.mocks.license_mock import MockLicenseManager
        mgr = MockLicenseManager(valid=False)
        assert mgr.load_license() is False, "valid=False 时 load_license 应返回 False"
        assert mgr.days_remaining == 0, "无效 License days_remaining 应为 0"
        assert mgr.check_expiry() == "expired", "无效 License 状态应为 expired"

    def test_mock_license_manager_verify_feature(self):
        """MockLicenseManager.verify_feature 正确验证功能权限。"""
        from repair_app.tests.mocks.license_mock import MockLicenseManager
        mgr = MockLicenseManager(valid=True)
        # 有效功能应返回 True
        assert mgr.verify_feature("repair") is True, "repair 功能应可用"
        assert mgr.verify_feature("export") is True, "export 功能应可用"
        assert mgr.verify_feature("robot") is True, "robot 功能应可用"
        assert mgr.verify_feature("calibration") is True, "calibration 功能应可用"
        # 无效功能应返回 False
        assert mgr.verify_feature("invalid_feature") is False, "无效功能应返回 False"
        # 无效 License 时所有功能应返回 False
        invalid_mgr = MockLicenseManager(valid=False)
        assert invalid_mgr.verify_feature("repair") is False, "无效 License 时 repair 应不可用"

    def test_mock_license_manager_expiring_soon(self):
        """MockLicenseManager 即将过期状态正确。"""
        from repair_app.tests.mocks.license_mock import MockLicenseManager
        mgr = MockLicenseManager(valid=True, days_remaining=3)
        assert mgr.check_expiry() == "expiring_soon", (
            "days_remaining=3 时状态应为 expiring_soon"
        )
