"""
platform.transport — ZMQ 传输地址选择

根据操作系统选择合适的 ZMQ 传输协议:
  - Windows: tcp://127.0.0.1:5555 (ipc:// 在 Windows 上不受 libzmq 支持)
  - POSIX:   ipc:///tmp/csam_engine (Unix-domain socket)

支持通过环境变量 CSAM_ZMQ_ADDRESS 覆盖默认地址。
"""

from __future__ import annotations

import os

from repair_app.platform import is_windows


def get_default_zmq_address() -> str:
    """返回当前平台的默认 ZMQ 地址。

    Windows 使用 TCP 回环地址 (ipc:// 不受 libzmq 支持),
    POSIX 系统 (macOS/Linux) 使用 Unix-domain socket。
    """
    if is_windows():
        return "tcp://127.0.0.1:5555"
    address = "ipc:///tmp/csam_engine"
    # 限制 IPC socket 权限为 0600（仅所有者可读写）
    if address.startswith("ipc://"):
        ipc_path = address[6:]
        try:
            os.chmod(ipc_path, 0o600)
        except (OSError, IOError):
            pass  # 文件不存在或平台不支持 chmod
    return address


def get_zmq_address_from_env() -> str:
    """从环境变量读取 ZMQ 地址，未设置时返回平台默认值。

    环境变量: CSAM_ZMQ_ADDRESS
    """
    return os.environ.get("CSAM_ZMQ_ADDRESS", get_default_zmq_address())
