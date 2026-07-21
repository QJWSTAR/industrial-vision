"""test_developer_mode.py — Developer Mode 自动测试。

验证场景：
1. AppConfig 配置加载（环境变量优先 / JSON 文件 / 默认值）
2. Developer Mode: 启动成功（4 个子场景）
   - License 文件不存在
   - License 文件损坏
   - License 文件为空
   - License 文件正常（Developer Mode 仍跳过）
3. Release Mode: 继续执行原 License 流程（回归）
4. Developer Mode 不影响 Release Mode（隔离性）

运行：
    python -m pytest repair_app/tests/test_developer_mode.py -v
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ================================================================
# 1. AppConfig 单元测试
# ================================================================
class TestAppConfig:
    """AppConfig 配置加载与优先级测试。"""

    def test_default_is_developer_mode_from_project_config(self):
        """项目 config/app_config.json 默认 developer_mode=true（开发阶段）。

        本测试验证 AppConfig 能正确读取项目配置文件。
        """
        from repair_app.utils.app_config import AppConfig
        AppConfig.reload()
        # 项目 config/app_config.json 设置 developer_mode=true
        assert AppConfig.is_developer_mode() is True

    def test_env_var_overrides_json(self, monkeypatch):
        """环境变量 CSAM_DEVELOPER_MODE 优先级高于 JSON 文件。"""
        from repair_app.utils.app_config import AppConfig
        # JSON 中 developer_mode=true，环境变量设为 false
        monkeypatch.setenv("CSAM_DEVELOPER_MODE", "false")
        AppConfig.reload()
        assert AppConfig.is_developer_mode() is False

    def test_env_var_true_values(self, monkeypatch):
        """环境变量接受 true/1/yes/on。"""
        from repair_app.utils.app_config import AppConfig
        for val in ["true", "1", "yes", "on", "TRUE", "True"]:
            monkeypatch.setenv("CSAM_DEVELOPER_MODE", val)
            AppConfig.reload()
            assert AppConfig.is_developer_mode() is True, f"Failed for value: {val}"

    def test_env_var_false_values(self, monkeypatch):
        """环境变量接受 false/0/no/off。"""
        from repair_app.utils.app_config import AppConfig
        for val in ["false", "0", "no", "off", "FALSE", "False"]:
            monkeypatch.setenv("CSAM_DEVELOPER_MODE", val)
            AppConfig.reload()
            assert AppConfig.is_developer_mode() is False, f"Failed for value: {val}"

    def test_env_var_empty_falls_back_to_json(self, monkeypatch):
        """环境变量为空字符串时回退到 JSON 配置。"""
        from repair_app.utils.app_config import AppConfig
        monkeypatch.setenv("CSAM_DEVELOPER_MODE", "")
        AppConfig.reload()
        # JSON 中 developer_mode=true
        assert AppConfig.is_developer_mode() is True

    def test_override_context_manager(self):
        """override() 上下文管理器临时覆盖状态。"""
        from repair_app.utils.app_config import AppConfig
        AppConfig.reload()
        original = AppConfig.is_developer_mode()

        with AppConfig.override(developer_mode=False):
            assert AppConfig.is_developer_mode() is False

        # 退出后恢复
        assert AppConfig.is_developer_mode() is original

    def test_override_restores_on_exception(self):
        """override() 在异常时也能恢复原值。"""
        from repair_app.utils.app_config import AppConfig
        AppConfig.reload()
        original = AppConfig.is_developer_mode()

        with pytest.raises(RuntimeError):
            with AppConfig.override(developer_mode=False):
                assert AppConfig.is_developer_mode() is False
                raise RuntimeError("test exception")

        assert AppConfig.is_developer_mode() is original

    def test_reload_refreshes_config(self, monkeypatch):
        """reload() 强制重新读取配置。"""
        from repair_app.utils.app_config import AppConfig
        monkeypatch.setenv("CSAM_DEVELOPER_MODE", "true")
        AppConfig.reload()
        assert AppConfig.is_developer_mode() is True

        monkeypatch.setenv("CSAM_DEVELOPER_MODE", "false")
        AppConfig.reload()
        assert AppConfig.is_developer_mode() is False

    def test_get_arbitrary_key(self):
        """get() 读取任意配置项。"""
        from repair_app.utils.app_config import AppConfig
        AppConfig.reload()
        # 项目配置中应有 _developer_mode_doc 文档字段
        doc = AppConfig.get("_developer_mode_doc")
        assert doc is not None
        assert isinstance(doc, str)

    def test_get_missing_key_returns_default(self):
        """get() 读取不存在的键返回默认值。"""
        from repair_app.utils.app_config import AppConfig
        AppConfig.reload()
        assert AppConfig.get("nonexistent_key", "default_val") == "default_val"


# ================================================================
# 2. LicenseStatus 数据类测试
# ================================================================
class TestLicenseStatus:
    """LicenseStatus 数据封装测试。"""

    def test_developer_status(self):
        from repair_app.utils.license_manager import LicenseStatus
        s = LicenseStatus(valid=True, mode="developer", message="skipped")
        assert s.valid is True
        assert s.is_developer is True
        assert s.mode == "developer"
        assert s.days_remaining == 0  # 默认

    def test_commercial_valid_status(self):
        from repair_app.utils.license_manager import LicenseStatus
        s = LicenseStatus(valid=True, mode="commercial", days_remaining=365)
        assert s.valid is True
        assert s.is_developer is False
        assert s.days_remaining == 365

    def test_commercial_invalid_status(self):
        from repair_app.utils.license_manager import LicenseStatus
        s = LicenseStatus(valid=False, mode="commercial", message="expired")
        assert s.valid is False
        assert s.is_developer is False
        assert s.message == "expired"

    def test_repr(self):
        from repair_app.utils.license_manager import LicenseStatus
        s = LicenseStatus(valid=True, mode="developer", days_remaining=-1)
        r = repr(s)
        assert "LicenseStatus" in r
        assert "developer" in r


# ================================================================
# 3. LicenseManager.verify_runtime() — Developer Mode 测试
# ================================================================
class TestVerifyRuntimeDeveloperMode:
    """Developer Mode 下 verify_runtime() 的 4 个场景。"""

    def test_developer_mode_license_file_missing(self, monkeypatch):
        """场景1: Developer Mode + License 文件不存在 → 启动成功。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        with AppConfig.override(developer_mode=True):
            # 确保 license.key 不存在（使用临时空目录）
            with tempfile.TemporaryDirectory() as tmpdir:
                # LicenseManager 从 get_config_dir() 读取 license.key
                # 在开发环境，get_config_dir() 返回项目根/config/
                # Developer Mode 下不会读取 license.key，所以不影响
                lm = LicenseManager()
                status = lm.verify_runtime()

                assert status.valid is True
                assert status.is_developer is True
                assert lm.is_developer_mode is True
                assert "skipped" in status.message.lower() or "developer" in status.message.lower()

    def test_developer_mode_license_file_corrupted(self, monkeypatch, tmp_path):
        """场景2: Developer Mode + License 文件损坏 → 启动成功。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        # 写入损坏的 license.key
        corrupt_license = tmp_path / "license.key"
        corrupt_license.write_text("{ this is not valid json !!!", encoding="utf-8")

        # Monkeypatch get_config_dir 指向临时目录
        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            with AppConfig.override(developer_mode=True):
                lm = LicenseManager()
                status = lm.verify_runtime()

                assert status.valid is True
                assert status.is_developer is True
                # Developer Mode 下 _error 应为空
                assert lm.error == ""
        finally:
            lm_module.get_config_dir = original_get_config_dir

    def test_developer_mode_license_file_empty(self, monkeypatch, tmp_path):
        """场景3: Developer Mode + License 文件为空 → 启动成功。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        # 写入空的 license.key
        empty_license = tmp_path / "license.key"
        empty_license.write_text("", encoding="utf-8")

        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            with AppConfig.override(developer_mode=True):
                lm = LicenseManager()
                status = lm.verify_runtime()

                assert status.valid is True
                assert status.is_developer is True
                assert lm.error == ""
        finally:
            lm_module.get_config_dir = original_get_config_dir

    def test_developer_mode_license_file_valid(self, monkeypatch):
        """场景4: Developer Mode + License 文件正常 → 仍跳过校验，启动成功。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        with AppConfig.override(developer_mode=True):
            lm = LicenseManager()
            status = lm.verify_runtime()

            assert status.valid is True
            assert status.is_developer is True
            assert status.days_remaining == -1  # 开发者模式视为永久

    def test_developer_mode_does_not_call_load_license(self, monkeypatch):
        """Developer Mode 下不调用 load_license()（验证跳过逻辑）。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        call_count = {"count": 0}
        original_load = LicenseManager.load_license

        def counting_load(self):
            call_count["count"] += 1
            return original_load(self)

        monkeypatch.setattr(LicenseManager, "load_license", counting_load)

        with AppConfig.override(developer_mode=True):
            lm = LicenseManager()
            lm.verify_runtime()

        assert call_count["count"] == 0, "Developer Mode 不应调用 load_license()"


# ================================================================
# 4. LicenseManager.verify_runtime() — Release Mode 回归测试
# ================================================================
class TestVerifyRuntimeReleaseMode:
    """Release Mode 下 verify_runtime() 执行完整 License 流程。"""

    def test_release_mode_no_license_file_fails(self, monkeypatch, tmp_path):
        """Release Mode + 无 License 文件 → 校验失败。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        # 指向空临时目录（无 license.key）
        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            with AppConfig.override(developer_mode=False):
                lm = LicenseManager()
                status = lm.verify_runtime()

                assert status.valid is False
                assert status.is_developer is False
                assert status.mode == "commercial"
                assert "不存在" in status.message or "failed" in status.message.lower()
        finally:
            lm_module.get_config_dir = original_get_config_dir

    def test_release_mode_calls_load_license(self, monkeypatch):
        """Release Mode 下调用 load_license()（验证不跳过）。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        call_count = {"count": 0}
        original_load = LicenseManager.load_license

        def counting_load(self):
            call_count["count"] += 1
            return original_load(self)

        monkeypatch.setattr(LicenseManager, "load_license", counting_load)

        with AppConfig.override(developer_mode=False):
            lm = LicenseManager()
            lm.verify_runtime()

        assert call_count["count"] == 1, "Release Mode 应调用 load_license() 一次"

    def test_release_mode_runtime_mode_property(self, monkeypatch):
        """Release Mode 下 runtime_mode 属性为 'commercial'。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        with AppConfig.override(developer_mode=False):
            lm = LicenseManager()
            # 未调用 verify_runtime 前 runtime_mode 为空
            assert lm.runtime_mode == ""
            lm.verify_runtime()
            assert lm.runtime_mode == "commercial"
            assert lm.is_developer_mode is False


# ================================================================
# 5. 隔离性测试 — Developer Mode 不影响 Release Mode
# ================================================================
class TestModeIsolation:
    """验证 Developer Mode 与 Release Mode 完全隔离。"""

    def test_switching_from_developer_to_release(self, monkeypatch, tmp_path):
        """从 Developer Mode 切换到 Release Mode 后，License 校验恢复。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        # 指向空临时目录（无 license.key）
        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            # 1. Developer Mode: 启动成功
            with AppConfig.override(developer_mode=True):
                lm = LicenseManager()
                status = lm.verify_runtime()
                assert status.valid is True
                assert status.is_developer is True

            # 2. Release Mode: 启动失败（无 license.key）
            with AppConfig.override(developer_mode=False):
                lm2 = LicenseManager()
                status2 = lm2.verify_runtime()
                assert status2.valid is False
                assert status2.is_developer is False
        finally:
            lm_module.get_config_dir = original_get_config_dir

    def test_license_algorithm_unchanged_in_release_mode(self, monkeypatch, tmp_path):
        """Release Mode 下 License 算法未被修改（机器码/签名/过期校验完整）。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import (
            LicenseManager, generate_license, _get_machine_id,
        )

        # 生成有效 License（HMAC 签名，因为临时目录无私钥）
        lic_path = tmp_path / "license.key"
        generate_license(str(lic_path), issued_to="TestUser", days_valid=30)

        # 指向临时目录 + 禁用 builtin 公钥（强制 HMAC 校验路径）
        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        original_get_builtin = lm_module.get_builtin_config_file
        lm_module.get_config_dir = lambda: tmp_path
        lm_module.get_builtin_config_file = lambda filename: None

        try:
            with AppConfig.override(developer_mode=False):
                lm = LicenseManager()
                status = lm.verify_runtime()

                # 应通过完整商业 License 校验（HMAC 路径）
                assert status.valid is True
                assert status.is_developer is False
                assert status.mode == "commercial"
                assert status.days_remaining >= 29  # 至少 29 天
        finally:
            lm_module.get_config_dir = original_get_config_dir
            lm_module.get_builtin_config_file = original_get_builtin

    def test_developer_mode_does_not_modify_license_file(self, tmp_path):
        """Developer Mode 不会修改或创建 license.key 文件。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        # 确保临时目录无 license.key
        assert not (tmp_path / "license.key").exists()

        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            with AppConfig.override(developer_mode=True):
                lm = LicenseManager()
                lm.verify_runtime()

            # Developer Mode 不应创建 license.key
            assert not (tmp_path / "license.key").exists()
        finally:
            lm_module.get_config_dir = original_get_config_dir


# ================================================================
# 6. 集成测试 — 启动流程模拟
# ================================================================
class TestStartupFlowIntegration:
    """模拟 run_app.py 启动流程的集成测试。"""

    def test_developer_mode_startup_succeeds_without_license(self):
        """模拟启动：Developer Mode 下无 License 也能通过。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        with AppConfig.override(developer_mode=True):
            license_mgr = LicenseManager()
            status = license_mgr.verify_runtime()

            # 模拟 run_app.py 的决策逻辑
            if status.is_developer:
                can_start = True  # Developer Mode 放行
            elif status.valid:
                can_start = True  # Release Mode + License 有效
            else:
                can_start = False  # Release Mode + License 无效 → 拒绝

            assert can_start is True

    def test_release_mode_startup_blocked_without_license(self, tmp_path):
        """模拟启动：Release Mode 下无 License 被拒绝。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import LicenseManager

        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        lm_module.get_config_dir = lambda: tmp_path

        try:
            with AppConfig.override(developer_mode=False):
                license_mgr = LicenseManager()
                status = license_mgr.verify_runtime()

                if status.is_developer:
                    can_start = True
                elif status.valid:
                    can_start = True
                else:
                    can_start = False

                assert can_start is False
        finally:
            lm_module.get_config_dir = original_get_config_dir

    def test_release_mode_startup_succeeds_with_valid_license(self, tmp_path):
        """模拟启动：Release Mode 下有效 License 通过。"""
        from repair_app.utils.app_config import AppConfig
        from repair_app.utils.license_manager import (
            LicenseManager, generate_license,
        )

        generate_license(str(tmp_path / "license.key"), issued_to="Test", days_valid=30)

        # 指向临时目录 + 禁用 builtin 公钥（强制 HMAC 校验路径）
        import repair_app.utils.license_manager as lm_module
        original_get_config_dir = lm_module.get_config_dir
        original_get_builtin = lm_module.get_builtin_config_file
        lm_module.get_config_dir = lambda: tmp_path
        lm_module.get_builtin_config_file = lambda filename: None

        try:
            with AppConfig.override(developer_mode=False):
                license_mgr = LicenseManager()
                status = license_mgr.verify_runtime()

                if status.is_developer:
                    can_start = True
                elif status.valid:
                    can_start = True
                else:
                    can_start = False

                assert can_start is True
        finally:
            lm_module.get_config_dir = original_get_config_dir
            lm_module.get_builtin_config_file = original_get_builtin
