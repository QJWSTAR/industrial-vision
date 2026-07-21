"""license_mock.py — License Mock 体系。

提供：
1. create_mock_license_env: 生成临时密钥对 + License 文件
2. MockLicenseManager: 替代 LicenseManager（不依赖真实机器码）
3. make_test_license_data: 构造测试用 LicenseData

设计原则：
- 隔离：所有文件在临时目录，测试结束自动清理
- 确定性：机器码固定为 "test-machine-001"
- 可控：支持有效/过期/即将过期等多种状态
"""
from __future__ import annotations

import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Any, Optional


TEST_MACHINE_ID = "test-machine-001"


def create_mock_license_env(
    output_dir: str,
    days_valid: int = 365,
    machine_id: str = TEST_MACHINE_ID,
    issued_to: str = "Test User",
) -> dict[str, Any]:
    """生成完整的 Mock License 环境。

    Args:
        output_dir: 输出目录
        days_valid: 有效天数（负数表示已过期）
        machine_id: 机器码（默认固定值）
        issued_to: 授权用户

    Returns:
        dict 包含所有生成文件路径与 License 信息
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. 生成 RSA 密钥对
    pub_key_path = os.path.join(output_dir, "public_key.pem")
    priv_key_path = os.path.join(output_dir, "private_key.pem")

    try:
        from repair_app.utils.license_manager import generate_keypair
        generate_keypair(output_dir)
    except Exception:
        # cryptography 不可用时，创建空文件占位
        with open(pub_key_path, "w") as f:
            f.write("MOCK_PUBLIC_KEY")
        with open(priv_key_path, "w") as f:
            f.write("MOCK_PRIVATE_KEY")

    # 2. 生成 License 文件
    license_path = os.path.join(output_dir, "license.key")

    # 使用 license_manager 的 generate_license（它会用 RSA 签名）
    try:
        from repair_app.utils.license_manager import generate_license
        generate_license(
            output_path=license_path,
            machine_id=machine_id,
            issued_to=issued_to,
            days_valid=days_valid,
        )
    except Exception:
        # 降级：直接写 JSON
        now = datetime.now()
        if days_valid > 0:
            expires = now + timedelta(days=days_valid)
        else:
            expires = now - timedelta(days=abs(days_valid))

        data = {
            "machine_id": machine_id,
            "issued_to": issued_to,
            "issued_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "features": ["repair", "export", "robot"],
            "signature": "mock_signature",
            "hmac": "mock_hmac",
        }
        with open(license_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 3. 验证生成的文件
    files = {}
    for name in ["license.key", "public_key.pem", "private_key.pem"]:
        path = os.path.join(output_dir, name)
        files[name] = path
        assert os.path.exists(path), f"Mock 文件未生成: {path}"

    return {
        "dir": output_dir,
        "license_path": license_path,
        "public_key_path": pub_key_path,
        "private_key_path": priv_key_path,
        "files": files,
        "machine_id": machine_id,
        "issued_to": issued_to,
        "days_valid": days_valid,
    }


def make_test_license_data(
    days_valid: int = 365,
    machine_id: str = TEST_MACHINE_ID,
) -> "LicenseData":
    """构造测试用 LicenseData 对象（不写文件）。

    Args:
        days_valid: 有效天数（负数表示已过期）
        machine_id: 机器码
    """
    from repair_app.utils.license_manager import LicenseData

    now = datetime.now()
    if days_valid > 0:
        expires = now + timedelta(days=days_valid)
    else:
        expires = now - timedelta(days=abs(days_valid))

    return LicenseData({
        "machine_id": machine_id,
        "issued_to": "Test User",
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "features": ["repair", "export", "robot"],
    })


class MockLicenseManager:
    """LicenseManager Mock（不依赖真实机器码/文件系统）。

    用法：
        mgr = MockLicenseManager(valid=True)
        assert mgr.load_license() is True
        assert mgr.days_remaining == 365
    """

    def __init__(
        self,
        valid: bool = True,
        days_remaining: int = 365,
        machine_id: str = TEST_MACHINE_ID,
    ) -> None:
        self._valid = valid
        self._days_remaining = days_remaining
        self._machine_id = machine_id
        self._loaded = False
        self.error: str = "" if valid else "Mock: License 无效"

    @property
    def days_remaining(self) -> int:
        return self._days_remaining if self._valid else 0

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load_license(self) -> bool:
        self._loaded = self._valid
        return self._valid

    def verify_feature(self, feature: str) -> bool:
        if not self._valid:
            return False
        return feature in ["repair", "export", "robot", "calibration"]

    def check_expiry(self) -> str:
        """返回过期状态: valid / expiring_soon / expired."""
        if not self._valid:
            return "expired"
        if self._days_remaining <= 5:
            return "expiring_soon"
        return "valid"
