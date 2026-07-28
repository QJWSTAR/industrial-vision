"""
license_manager.py — RSA License 管理系统
Stage 4.1 v2.1：RSA-2048 公钥验证 / 机器码绑定 / 到期提醒 / HMAC 防篡改
"""

from __future__ import annotations
import os
import json
import hashlib
import hmac
import uuid
import platform
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

try:
    from repair_app.utils.logger_config import warning as _log_warning, error as _log_error
except ImportError:
    _log_warning = lambda msg: None
    _log_error = lambda msg: None

try:
    from repair_app.utils.resource_path import get_config_dir, get_builtin_config_file, is_frozen
except ImportError:
    is_frozen = lambda: False
    def get_config_dir():
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.parent / 'config'
    def get_builtin_config_file(filename):
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / 'config' / filename
        return p if p.exists() else None


LICENSE_FILE = "license.key"
PUBLIC_KEY_FILE = "public_key.pem"
PRIVATE_KEY_FILE = "private_key.pem"
_DEV_HMAC_FALLBACK = "csam_dev_secret_2026"
_DEFAULT_HMAC_SECRET = os.environ.get("CSAM_HMAC_SECRET")
if _DEFAULT_HMAC_SECRET is None:
    if is_frozen():
        _DEFAULT_HMAC_SECRET = ""
    else:
        _DEFAULT_HMAC_SECRET = _DEV_HMAC_FALLBACK
        # 开发模式使用回退密钥时输出显著警告
        import logging as _stdlog
        _stdlog.getLogger("csam.license").warning(
            "CSAM_HMAC_SECRET 未设置，使用开发模式回退密钥。"
            "生产环境必须设置此环境变量或使用 RSA 签名。"
        )


def get_machine_id() -> str:
    """获取机器唯一标识（公开 API）。

    基于 MAC 地址 (uuid.getnode) 与主机名的组合哈希，比纯 hostname 方案
    更稳定且更难伪造。异常时退化为 UNKNOWN_MACHINE。

    终端用户可通过此函数获取机器码，用于向管理员申请 License。
    """
    try:
        node = uuid.getnode()
        raw = f"{node}:{platform.node()}"
        return str(uuid.UUID(bytes=hashlib.sha256(raw.encode()).digest()[:16]))
    except Exception as e:
        _log_warning(f"get_machine_id failed: {e}")
        return "UNKNOWN_MACHINE"


# 向后兼容别名
_get_machine_id = get_machine_id


def install_license(source_path: str) -> tuple[bool, str]:
    """将 License 文件安装到配置目录。

    从用户指定的路径复制 license.key 到 config 目录，供后续运行时验证使用。

    Args:
        source_path: 用户提供的 license.key 文件路径。

    Returns:
        (success, message): 是否成功及说明信息。
    """
    from pathlib import Path
    import shutil

    src = Path(source_path)
    if not src.exists():
        return False, f"License 文件不存在: {source_path}"
    if not src.is_file():
        return False, f"路径不是文件: {source_path}"

    try:
        # 验证文件是否为有效 JSON（基本格式检查）
        with open(src, "r", encoding="utf-8") as f:
            json.load(f)
    except json.JSONDecodeError as e:
        return False, f"License 文件格式错误: {e}"

    dst = get_config_dir() / LICENSE_FILE
    try:
        os.makedirs(str(get_config_dir()), exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return True, f"License 已安装到 {dst}"
    except OSError as e:
        return False, f"安装失败: {e}"


def _get_machine_id_legacy() -> str:
    """旧版机器码算法 — 仅用于向后兼容已签发 license 的校验。

    基于 platform.node() + platform.machine() 的哈希，稳定性较差，
    保留此函数以支持过渡期内已有 license 的平滑迁移。
    """
    try:
        return str(uuid.UUID(bytes=hashlib.sha256(
            (platform.node() + platform.machine()).encode()
        ).digest()[:16]))
    except Exception as e:
        _log_warning(f"_get_machine_id_legacy failed: {e}")
        return "UNKNOWN_MACHINE"


class LicenseData:
    """License 数据封装。"""

    def __init__(self, raw: dict) -> None:
        self.machine_id: str = raw.get("machine_id", "")
        self.issued_to: str = raw.get("issued_to", "Unknown")
        self.issued_at: str = raw.get("issued_at", "")
        self.expires_at: str = raw.get("expires_at", "")
        self.features: list[str] = raw.get("features", ["basic"])
        self.max_layers: int = raw.get("max_layers", 20)
        self.signature: str = raw.get("signature", "")

    @property
    def expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = _parse_iso_datetime(self.expires_at)
            return _now_for(exp) > exp
        except (TypeError, ValueError):
            return True

    @property
    def days_remaining(self) -> int:
        if not self.expires_at:
            return -1  # -1 表示永久授权（无到期日）
        try:
            exp = _parse_iso_datetime(self.expires_at)
            return max(0, (exp - _now_for(exp)).days)
        except (TypeError, ValueError):
            return 0

    @property
    def expiring_soon(self) -> bool:
        return 0 < self.days_remaining <= 7


def _parse_iso_datetime(value: str) -> datetime:
    """Parse ISO-8601 timestamps on every supported Python version.

    Python 3.10 does not consistently accept the common trailing ``Z`` form,
    so normalize it to an explicit UTC offset first.
    """
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _now_for(value: datetime) -> datetime:
    """Return a comparable current time for naive or timezone-aware values."""
    if value.tzinfo is None:
        return datetime.now()
    return datetime.now(timezone.utc).astimezone(value.tzinfo)


class LicenseStatus:
    """License 运行时校验结果（verify_runtime 的返回值）。

    封装"软件是否可以启动"的统一答案，解耦"如何判定"的细节。

    Attributes:
        valid: 是否允许进入软件主界面。
        mode: 校验模式。"developer"=开发者模式跳过；
              "commercial"=完整商业 License 校验通过。
        message: 人类可读的说明（用于日志/状态栏）。
        days_remaining: 剩余有效天数（开发者模式返回 -1 表示永久）。
    """

    def __init__(
        self,
        valid: bool,
        mode: str = "commercial",
        message: str = "",
        days_remaining: int = 0,
    ) -> None:
        self.valid = valid
        self.mode = mode
        self.message = message
        self.days_remaining = days_remaining

    @property
    def is_developer(self) -> bool:
        """是否为开发者模式（跳过商业 License 校验）。"""
        return self.mode == "developer"

    def __repr__(self) -> str:
        return (
            f"LicenseStatus(valid={self.valid}, mode={self.mode!r}, "
            f"days_remaining={self.days_remaining})"
        )


class LicenseManager:
    """License 验证管理器。"""

    def __init__(self) -> None:
        self._public_key = self._load_public_key()
        self._license: Optional[LicenseData] = None
        self._valid: bool = False
        self._error: str = ""
        self._runtime_mode: str = ""  # "developer" / "commercial"

    # ---- 运行时统一校验入口（启动流程唯一调用点） ----
    def verify_runtime(self) -> LicenseStatus:
        """运行时统一校验：决定软件是否可以启动。

        逻辑：
        - Developer Mode（AppConfig.is_developer_mode() == True）：
          直接返回 valid=True, mode="developer"，跳过商业 License 校验。
          不修改任何 License 文件/签名/机器码逻辑。
        - Release Mode（默认）：
          调用 load_license() 执行完整商业 License 校验（机器码 + 过期 + 签名）。

        Returns:
            LicenseStatus: 封装校验结果（valid / mode / message / days_remaining）。

        注意：
            本方法是启动流程的**唯一调用点**。业务代码不应直接调用
            load_license() 判断是否启动，而应通过本方法统一决策。
        """
        # 延迟导入避免循环依赖
        from repair_app.utils.app_config import AppConfig

        if AppConfig.is_developer_mode():
            self._runtime_mode = "developer"
            self._valid = True  # 允许进入主界面
            self._error = ""
            return LicenseStatus(
                valid=True,
                mode="developer",
                message="Developer Mode: License verification skipped",
                days_remaining=-1,  # 开发者模式视为永久
            )

        # Release Mode: 执行完整商业 License 校验
        self._runtime_mode = "commercial"
        ok = self.load_license()
        if ok:
            return LicenseStatus(
                valid=True,
                mode="commercial",
                message=f"License verified ({self.days_remaining} days remaining)",
                days_remaining=self.days_remaining,
            )
        return LicenseStatus(
            valid=False,
            mode="commercial",
            message=self._error or "License verification failed",
            days_remaining=0,
        )

    @property
    def runtime_mode(self) -> str:
        """当前运行时模式："developer" / "commercial" / ""（未调用 verify_runtime）。"""
        return self._runtime_mode

    @property
    def is_developer_mode(self) -> bool:
        """当前是否运行在开发者模式（需先调用 verify_runtime）。"""
        return self._runtime_mode == "developer"

    def _load_public_key(self):
        if not _CRYPTO_AVAILABLE:
            return None
        # 安全关键：公钥始终从打包内置只读目录（_MEIPASS）加载，
        # 防止用户目录替换攻击
        pub_path_obj = get_builtin_config_file(PUBLIC_KEY_FILE)
        if pub_path_obj is None:
            # 回退到用户配置目录（开发环境）
            pub_path_obj = get_config_dir() / PUBLIC_KEY_FILE
        pub_path = str(pub_path_obj)
        if not os.path.exists(pub_path):
            return None
        try:
            with open(pub_path, "rb") as f:
                return serialization.load_pem_public_key(f.read(), backend=default_backend())
        except Exception as e:
            _log_warning(f"Failed to load public key: {e}")
            return None

    def load_license(self) -> bool:
        """加载并验证 License 文件。"""
        lic_path = str(get_config_dir() / LICENSE_FILE)
        if not os.path.exists(lic_path):
            self._error = "License 文件不存在"
            return False

        try:
            with open(lic_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError:
            self._error = "License 文件格式错误"
            return False

        lic = LicenseData(raw)

        # 机器码校验 — 接受新版 (uuid.getnode) 或旧版 (platform.node) 机器码
        mid = _get_machine_id()
        legacy_mid = _get_machine_id_legacy()
        if lic.machine_id and lic.machine_id != mid and lic.machine_id != legacy_mid:
            self._error = f"机器码不匹配 (license: {lic.machine_id[:8]}..., 本机: {mid[:8]}...)"
            return False

        # 过期检查
        if lic.expired:
            self._error = f"License 已过期 ({lic.expires_at})"
            return False

        # 签名验证
        if not self._verify_signature(raw):
            self._error = "License 签名验证失败（可能被篡改）"
            return False

        self._license = lic
        self._valid = True
        self._error = ""
        return True

    def _verify_signature(self, raw: dict) -> bool:
        """RSA 签名验证 + HMAC 完整性校验。"""
        signature = raw.pop("signature", None)
        if not signature:
            raw["signature"] = None
            return False

        if not _CRYPTO_AVAILABLE or self._public_key is None:
            raw["signature"] = signature
            if is_frozen():
                _log_error("生产环境缺少 cryptography 或公钥，HMAC 退化校验不安全")
            return self._verify_hmac(raw, signature)

        try:
            payload = json.dumps({k: v for k, v in raw.items() if k != "signature"},
                                 sort_keys=True).encode()
            self._public_key.verify(
                bytes.fromhex(signature),
                payload,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                           salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256(),
            )
            raw["signature"] = signature
            return True
        except Exception as e:
            _log_warning(f"RSA signature verification failed: {e}")
            raw["signature"] = signature
            return False

    def _verify_hmac(self, raw: dict, signature: str) -> bool:
        """退化 HMAC 校验（开发/测试用途）。

        生产环境（is_frozen）下空密钥直接拒绝，防止伪造。
        """
        if is_frozen() and not _DEFAULT_HMAC_SECRET:
            _log_error("生产环境 HMAC 密钥为空，拒绝验证")
            return False
        secret = _DEFAULT_HMAC_SECRET.encode() if isinstance(_DEFAULT_HMAC_SECRET, str) else _DEFAULT_HMAC_SECRET
        if not secret:
            return False
        payload = json.dumps({k: v for k, v in raw.items() if k != "signature"},
                             sort_keys=True).encode()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @property
    def is_valid(self) -> bool:
        return self._valid

    @property
    def error(self) -> str:
        return self._error

    @property
    def license_data(self) -> Optional[LicenseData]:
        return self._license

    @property
    def expiring_soon(self) -> bool:
        return self._license is not None and self._license.expiring_soon

    @property
    def days_remaining(self) -> int:
        return self._license.days_remaining if self._license else 0


def _load_private_key():
    """加载 RSA 私钥（仅用于签发 License）。"""
    if not _CRYPTO_AVAILABLE:
        return None
    key_path = str(get_config_dir() / PRIVATE_KEY_FILE)
    if not os.path.exists(key_path):
        return None
    try:
        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
    except Exception as e:
        _log_warning(f"Failed to load private key: {e}")
        return None


def generate_keypair(output_dir: Optional[str] = None) -> tuple[str, str]:
    """生成 RSA-2048 密钥对，写入 public_key.pem 和 private_key.pem。

    Args:
        output_dir: 输出目录，默认为 config 目录。

    Returns:
        (public_key_path, private_key_path)
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography 未安装，无法生成密钥对")

    out = output_dir or str(get_config_dir())
    os.makedirs(out, exist_ok=True)

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    pub_path = os.path.join(out, PUBLIC_KEY_FILE)
    priv_path = os.path.join(out, PRIVATE_KEY_FILE)

    with open(priv_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    if os.name == "posix":
        os.chmod(priv_path, 0o600)

    with open(pub_path, "wb") as f:
        f.write(private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))

    print(f"密钥对已生成:")
    print(f"  公钥: {pub_path}")
    if os.name == "posix":
        print(f"  私钥: {priv_path} (权限 0600)")
    else:
        print(f"  私钥: {priv_path} (请使用 Windows ACL 限制访问)")
    return pub_path, priv_path


def generate_license(
    output_path: str,
    machine_id: str,
    issued_to: str = "User",
    days_valid: int = 365,
    features: Optional[list[str]] = None,
) -> None:
    """签发 License 文件。

    优先使用 RSA 私钥签名（与验证端算法匹配）；
    无私钥时退化为 HMAC 签名（仅限开发模式）。

    Args:
        output_path: License 文件输出路径。
        machine_id: 目标机器的机器码（必填，通过 get_machine_id() 获取）。
                    必须由终端用户提供，不能使用签发机器的机器码。
        issued_to: 授权对象名称。
        days_valid: 有效天数。
        features: 功能列表。
    """
    mid = machine_id
    now = datetime.now()

    payload = {
        "machine_id": mid,
        "issued_to": issued_to,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days_valid)).isoformat(),
        "features": features or ["basic"],
        "max_layers": 50,
    }

    msg = json.dumps(payload, sort_keys=True).encode()

    private_key = _load_private_key()
    if _CRYPTO_AVAILABLE and private_key is not None:
        signature = private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        ).hex()
        sign_mode = "RSA-PSS"
    else:
        if not _CRYPTO_AVAILABLE:
            print("⚠️ cryptography 未安装，使用 HMAC 签名（开发模式）")
        else:
            print("⚠️ 未找到私钥文件，使用 HMAC 签名（开发模式）")
            print(f"   生成密钥对: python -m repair_app.utils.license_manager keygen")
        secret = _DEFAULT_HMAC_SECRET.encode() if isinstance(_DEFAULT_HMAC_SECRET, str) else _DEFAULT_HMAC_SECRET
        signature = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        sign_mode = "HMAC"

    payload["signature"] = signature

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"License 已签发 [{sign_mode}]: {output_path}")
    print(f"  机器码: {mid}")
    print(f"  到期: {payload['expires_at']}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "keygen":
        generate_keypair()
    elif len(sys.argv) > 1 and sys.argv[1] == "machine-id":
        mid = get_machine_id()
        print(f"机器码: {mid}")
        print()
        print("将此机器码发送给管理员以获取 License 文件。")
    elif len(sys.argv) > 1 and sys.argv[1] == "issue":
        if len(sys.argv) < 3:
            print("用法: python -m repair_app.utils.license_manager issue <machine_id> [issued_to] [days]")
            print()
            print("  获取机器码: python -m repair_app.utils.license_manager machine-id")
            sys.exit(1)
        generate_license(
            str(get_config_dir() / LICENSE_FILE),
            machine_id=sys.argv[2],
            issued_to=sys.argv[3] if len(sys.argv) > 3 else "Developer",
            days_valid=int(sys.argv[4]) if len(sys.argv) > 4 else 365,
        )
    else:
        lm = LicenseManager()
        ok = lm.load_license()
        if ok:
            days = lm.days_remaining
            if days < 0:
                print(f"✅ License 有效 (永久授权)")
            else:
                print(f"✅ License 有效 ({days} 天后到期)")
        else:
            print(f"❌ {lm.error}")
