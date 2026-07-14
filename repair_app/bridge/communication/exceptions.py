"""bridge.exceptions — 结构化异常层次（任务8）

所有通信层异常都继承自 BridgeError，业务层只需捕获 BridgeError 即可。
绝不向业务层抛出原始 ZMQ/Protobuf 异常或堆栈跟踪。
"""
from __future__ import annotations


class BridgeError(Exception):
    """通信层所有异常的基类。"""

    def __init__(self, message: str, *, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id

    def __str__(self) -> str:
        if self.request_id:
            return f"[{self.request_id}] {super().__str__()}"
        return super().__str__()


class ConnectionError(BridgeError):
    """无法建立连接或连接中断。"""


class ConnectionTimeoutError(ConnectionError):
    """连接或请求超时。"""

    def __init__(self, message: str = "请求超时", *, timeout_ms: int = 0, **kwargs):
        super().__init__(message, **kwargs)
        self.timeout_ms = timeout_ms


class EngineUnavailableError(ConnectionError):
    """MATLAB 引擎未启动或不可达。"""


class SerializationError(BridgeError):
    """序列化/反序列化失败。"""


class InvalidParameterError(BridgeError):
    """参数校验失败（业务层传入非法参数）。"""

    def __init__(self, message: str, *, parameter: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.parameter = parameter


class AlgorithmError(BridgeError):
    """MATLAB 算法执行异常。"""

    def __init__(self, message: str = "MATLAB 算法执行失败", *, algorithm: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.algorithm = algorithm


class EngineCrashError(EngineUnavailableError):
    """MATLAB 引擎在处理过程中崩溃。"""


class ProtocolError(BridgeError):
    """协议版本不兼容或消息格式错误。"""

    def __init__(self, message: str, *, expected_version: str = "", actual_version: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.expected_version = expected_version
        self.actual_version = actual_version


class ShutdownError(BridgeError):
    """通信层正在关闭或已关闭。"""


def translate_zmq_error(exc: Exception, *, request_id: str = "") -> BridgeError:
    """将底层 ZMQ/Python 异常翻译为结构化 BridgeError。

    业务层永不接触原始异常。
    """
    import zmq

    if isinstance(exc, zmq.Again):
        timeout = int(exc.get("timeout", 0)) if hasattr(exc, "get") else 0
        return ConnectionTimeoutError("ZMQ 接收超时", timeout_ms=timeout, request_id=request_id)
    if isinstance(exc, zmq.ZMQError):
        return ConnectionError(f"ZMQ 错误: {exc}", request_id=request_id)
    if isinstance(exc, (ValueError, TypeError)):
        return InvalidParameterError(str(exc), request_id=request_id)
    if isinstance(exc, BridgeError):
        return exc
    return BridgeError(f"未预期的通信错误: {exc}", request_id=request_id)
