"""bridge.adapters.legacy_adapter — 向后兼容适配器

将新的 BridgeClient 适配为现有 ZmqRepairClient 接口，
使现有 UI 代码无需修改即可使用新通信层。

现有 UI 调用：
    client = ZmqRepairClient(address=...)
    client.request_repair(request, on_result, on_error)
    client.check_health(on_health)

适配后：
    from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient
    client = LegacyZmqClient(address=...)
    # API 完全兼容
"""
from __future__ import annotations

from typing import Callable, Optional

from repair_app.communication.repair_protocol_pb2 import RepairRequest, RepairResult
from ..communication.config import BridgeConfig
from ..communication.zmq_client import BridgeClient


class LegacyZmqClient:
    """兼容现有 ZmqRepairClient 接口的适配器。

    内部委托给 BridgeClient，对外保持 API 兼容。
    """

    def __init__(
        self,
        address: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> None:
        config = BridgeConfig.from_env()
        if address:
            config = BridgeConfig(address=address, request_timeout_ms=timeout_ms)
        self._client = BridgeClient(config)

    # ---- 兼容属性 ----
    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def zmq_available(self) -> bool:
        return self._client.zmq_available

    # ---- 兼容方法 ----
    def request_repair(
        self,
        request: RepairRequest,
        on_result: Callable[[RepairResult], None],
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """发送修复请求（与 ZmqRepairClient 签名兼容）。

        注意：on_error 在旧 API 中接收 str，新 API 接收 BridgeError。
        此适配器将 BridgeError 转回 str 以保持兼容。
        """
        def _error_adapter(err):
            if on_error:
                on_error(str(err))

        self._client.request_repair(request, on_result, _error_adapter)

    def check_health(self, on_health: Callable[[bool, str], None]) -> None:
        self._client.check_health(on_health)

    def close(self, wait_ms: int = 4000) -> None:
        self._client.close(wait_ms)

    def start_heartbeat(self) -> None:
        """新功能：启动心跳（旧 API 无此方法，为增强功能）。"""
        self._client.start_heartbeat()

    def stop_heartbeat(self) -> None:
        self._client.stop_heartbeat()
