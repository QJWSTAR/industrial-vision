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
    # SECURITY NOTE (V1.0 known issue #SEC-1): IPC socket 在 /tmp 公共目录，未设权限限制。
    # 单用户工作站部署下为已知可接受风险；多用户主机应在 V1.1 用 os.chmod 限制为 0600
    # 或改用用户私有运行时目录 (XDG_RUNTIME_DIR)。详见 Release Notes。
    return "ipc:///tmp/csam_engine"


def get_zmq_address_from_env() -> str:
    """从环境变量读取 ZMQ 地址，未设置时返回平台默认值。

    环境变量: CSAM_ZMQ_ADDRESS
    """
    return os.environ.get("CSAM_ZMQ_ADDRESS", get_default_zmq_address())
