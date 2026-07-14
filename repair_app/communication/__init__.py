"""communication — 旧版通信层（已弃用）。

此包包含 v2.1 协议的旧版 ZMQ 客户端与序列化工具。
生产路径已迁移至 repair_app.bridge 通信层。

迁移指引：
    旧版:  from repair_app.communication.zmq_client import ZmqRepairClient
    新版:  from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient
    门面:  from repair_app.bridge import MatlabService

注意：repair_serialization.py 与 repair_protocol_pb2.py 仍被 bridge 层复用，
不属于弃用范围。详见 docs/MIGRATION_REPORT.md。
"""
