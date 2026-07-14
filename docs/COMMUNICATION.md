# 通信架构文档（最终版）

> **状态：已定稿（FINALIZED）** | 更新日期：2026-07-10
> 通信架构已收敛为唯一生产路径。本文档记录最终决策、模块分类与弃用说明。

---

## 1. 最终生产通信路径

本仓库**唯一**的生产通信路径如下，不允许存在旁路或并行路径：

```
GUI (MainWindow)
    ↓  _Coord.create_zmq_client()
CoordinationService
    ↓  返回 LegacyZmqClient
LegacyZmqClient (bridge/adapters/legacy_adapter.py)
    ↓  委托
BridgeClient (bridge/communication/zmq_client.py)
    ↓  ZMQ REQ
ZeroMQ (tcp://127.0.0.1:5555)
    ↓  Protobuf 二进制
matlab_bridge_server.m
    ↓  pyenv 调用 Python
MatlabAdapter (bridge/adapters/matlab_adapter.py)
    ↓  继承 BridgeServer
BridgeServer (bridge/communication/zmq_server.py, zmq.REP)
    ↓  调用 MATLAB 函数
MATLAB R2025b 算法
    ↓  结果
RepairResult (Protobuf) → 原路返回 → GUI
```

### 1.1 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 传输层 | ZeroMQ REQ/REP | 同步请求-应答模式 |
| 端口 | 5555 | 生产端口，可通过 `CSAM_ZMQ_ADDRESS` 配置 |
| 协议 | Protocol Buffers v2.1 | `repair_protocol.proto` |
| 消息类型 | `RepairRequest` / `RepairResult` | 业务专用消息 |
| 序列化 | Protobuf 二进制 | 由 `repair_protocol_pb2.py` 提供 |
| MATLAB 入口 | `matlab_bridge_server.m` | 通过 `pyenv` 调用 Python 的 `MatlabAdapter` |

### 1.2 代码证据

| 节点 | 文件 | 行号 | 代码 |
|------|------|------|------|
| GUI 获取客户端 | `repair_app/ui/main_window.py` | 434 | `self._zmq_client = _Coord.create_zmq_client()` |
| GUI 发送请求 | `repair_app/ui/main_window.py` | 1598 | `self._zmq_client.request_repair(...)` |
| CoordinationService 返回 bridge 适配器 | `repair_app/service/coordination_service.py` | 134-135 | `if _BRIDGE_AVAILABLE: return LegacyZmqClient()` |
| LegacyZmqClient 委托 BridgeClient | `repair_app/bridge/adapters/legacy_adapter.py` | 39 | `self._client = BridgeClient(config)` |
| BridgeConfig 协议版本 | `repair_app/bridge/communication/config.py` | - | `protocol_version = "2.1"` |
| MATLAB 服务入口 | `matlab_bridge_server.m` | 31 | `py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter')` |

---

## 2. 模块分类

### 2.1 ACTIVE（生产活跃）

| 模块 | 路径 | 说明 |
|------|------|------|
| BridgeClient | `bridge/communication/zmq_client.py` | ZMQ REQ 客户端，GUI 经由 LegacyZmqClient 使用 |
| BridgeConfig | `bridge/communication/config.py` | 通信配置，protocol_version="2.1" |
| BridgeServer | `bridge/communication/zmq_server.py` | ZMQ REP 服务端，MatlabAdapter 继承此类 |
| Serializer | `bridge/communication/serializer.py` | Protobuf 序列化 |
| protocol | `bridge/communication/protocol.py` | PROTOCOL_VERSION="2.1"，状态码定义 |
| message | `bridge/communication/message.py` | MessageEnvelope，request_id 生成 |
| heartbeat | `bridge/communication/heartbeat.py` | HeartbeatMonitor |
| exceptions | `bridge/communication/exceptions.py` | BridgeError 等异常 |
| LegacyZmqClient | `bridge/adapters/legacy_adapter.py` | GUI 实际使用的客户端适配器 |
| MatlabAdapter | `bridge/adapters/matlab_adapter.py` | MATLAB 端适配器，继承 BridgeServer |
| repair_protocol.proto | 项目根 | v2.1 proto 源文件 |
| repair_protocol_pb2.py | `communication/repair_protocol_pb2.py` | 生成的 Protobuf 绑定 |
| repair_serialization.py | `communication/repair_serialization.py` | Protobuf 序列化辅助（bridge 复用） |
| matlab_bridge_server.m | 项目根 | 生产 MATLAB 服务入口 |

### 2.2 EXPERIMENTAL（实验性，未接入 GUI）

| 模块 | 路径 | 说明 |
|------|------|------|
| MatlabService | `bridge/services/matlab_service.py` | MATLAB 服务门面，已实现但 GUI 未使用。GUI 当前通过 LegacyZmqClient 直接访问 BridgeClient。这是已知技术债务，未来可接入。 |

### 2.3 DEPRECATED（已弃用，保留向后兼容）

| 模块 | 路径 | 弃用原因 | 替代方案 |
|------|------|----------|----------|
| ZmqRepairClient | `communication/zmq_client.py` | 旧版 ZMQ 客户端，已被 bridge 取代 | LegacyZmqClient |
| MatlabEngine | `engine/matlab_engine.py` | TCP/JSON/v3.0/5570 客户端 | LegacyZmqClient → BridgeClient |
| create_engine | `engine/factory.py` | 构建 MatlabEngine 的工厂 | CoordinationService.create_zmq_client() |
| LifecycleSupervisor | `engine/lifecycle.py` | 管理 MatlabEngine 的生命周期 | bridge HeartbeatMonitor |
| protocol_v3 包 | `bridge/protocol_v3/` | v3.0 通用算法协议 | Protobuf v2.1 (repair_protocol.proto) |
| algorithm_protocol_v3.proto | `bridge/protocol_v3/` | v3.0 proto 源文件 | repair_protocol.proto |
| matlab_server/ 目录 | `matlab_server/` | TCP/JSON/v3.0/5570 MATLAB 服务端 | matlab_bridge_server.m |
| LocalEngine | `engine/local_engine.py` | Python 原型引擎 | MATLAB 生产引擎（仅 benchmark/测试使用） |
| IEngine 接口 | `domain/interfaces.py` | 仅 engine 子树使用 | 由 LocalEngine/MatlabEngine 实现 |

### 2.4 弃用警告策略

| 模块 | 警告触发时机 | 警告类型 |
|------|-------------|----------|
| ZmqRepairClient | 实例化时 | DeprecationWarning |
| MatlabEngine | `__init__` 时 | DeprecationWarning |
| create_engine | 调用时 | DeprecationWarning |
| protocol_v3 包 | import 时 | DeprecationWarning |

测试套件运行时使用 `-W "ignore::DeprecationWarning"` 抑制这些警告，避免噪音。

---

## 3. 为什么 TCP + JSON + Protocol v3.0 被弃用

### 3.1 历史背景

项目曾并行存在两条通信路径：

- **路径 A（ZMQ v2.1 Protobuf，端口 5555）**：GUI → CoordinationService → LegacyZmqClient → BridgeClient → ZMQ → matlab_bridge_server.m。**生产路径，GUI 实际使用。**
- **路径 B（TCP v3.0 JSON，端口 5570）**：EngineFactory → MatlabEngine → TcpChannel → java.net.ServerSocket → matlab_server/server.m。**未接入 GUI。**

### 3.2 弃用原因

1. **架构收敛要求**：工业生产软件不允许存在两条并行通信路径。两条路径增加维护成本、测试矩阵和故障排查复杂度。
2. **GUI 实际只使用路径 A**：路径 B 从未接入 GUI，`EngineFactory.create_engine()` 仅被测试和 benchmark 调用。
3. **协议设计阶段冲突**：v3.0 协议（通用 AlgorithmRequest/Response）与 v2.1 协议（业务专用 RepairRequest/Result）设计目标不同。v3.0 旨在"算法无关"，但在当前阶段业务耦合的 v2.1 已满足需求且已稳定运行。
4. **传输层依赖差异**：路径 A 使用 ZeroMQ（工业级消息队列，成熟稳定）；路径 B 使用 `java.net.ServerSocket`（裸 TCP，需自行处理 framing/retry/heartbeat）。ZeroMQ 提供更好的连接管理和故障恢复。
5. **序列化效率**：Protobuf 二进制（路径 A）比 JSON + base64（路径 B）更紧凑、解析更快，适合工业场景的大矩阵传输。
6. **MATLAB 端实现复杂度**：路径 A 的 `matlab_bridge_server.m` 通过 `pyenv` 调用 Python 的 BridgeServer，复用 Python 侧的全部通信逻辑；路径 B 的 `matlab_server/` 需在 MATLAB 中重新实现 framing、heartbeat、registry 等，维护负担重。

### 3.3 弃用决策

- **保留代码，不删除**：为保持向后兼容和测试覆盖，所有弃用模块保留在仓库中，但添加 `DEPRECATED` 标记和 `DeprecationWarning`。
- **禁止生产使用**：弃用模块不得接入 GUI 或任何生产代码路径。
- **测试保留**：`test_matlab_platform.py` 继续测试弃用的 v3.0 栈（使用 mock server），确保弃用代码不退化。
- **未来移除**：在下一个大版本（2.0.0）中评估是否彻底移除弃用代码。

---

## 4. 验证记录

### 4.1 生产路径验证

| 验证项 | 结果 | 证据 |
|--------|------|------|
| GUI 调用 CoordinationService | ✅ | `main_window.py:434` `_Coord.create_zmq_client()` |
| CoordinationService 返回 LegacyZmqClient | ✅ | `coordination_service.py:134-135` `_BRIDGE_AVAILABLE → LegacyZmqClient()` |
| LegacyZmqClient 委托 BridgeClient | ✅ | `legacy_adapter.py:39` `BridgeClient(config)` |
| BridgeClient 使用 ZMQ 5555 | ✅ | `config.py` 默认端口 5555，protocol_version="2.1" |
| GUI 发送请求 | ✅ | `main_window.py:1598` `request_repair(...)` |
| 无旁路路径 | ✅ | Grep 确认无生产代码 import matlab_engine/factory/protocol_v3 |
| 全部测试通过 | ✅ | 264 项测试通过（20.43s） |

### 4.2 MATLAB R2025b 端到端验证

> **✅ 已执行真实端到端验证**（2026-07-10）

**环境**：
- MATLAB R2025b（版本 25.2.0.2998904），安装路径 `D:\work\matlab\bin\matlab.exe`
- MATLAB 进程 PID 67376，端口 5555 监听中（OwningProcess=67376）
- 启动方式：在 MATLAB 命令窗口执行 `cd('D:\work\demo\industrial-vision'); matlab_bridge_server`

**验证结果**：

| 测试项 | 结果 | 证据 |
|--------|------|------|
| 端口 5555 监听 | ✅ | `Get-NetTCPConnection` 确认 OwningProcess=67376 |
| ZMQ 连接 | ✅ | Python `zmq.REQ.connect('tcp://127.0.0.1:5555')` 成功 |
| RepairRequest 序列化 | ✅ | 4970 bytes（200 点）/ 3775 bytes（150 点） |
| MATLAB 算法执行 | ✅ | 返回 12 行航点，status_code=0（SUCCESS） |
| compute_time_ms | ✅ | 1-53ms（真实计算耗时） |
| estimated_time_s | ✅ | 0.2328s（基于路径长度与速度计算） |
| uniformity_score | ✅ | 0.78（默认值） |
| is_feasible | ✅ | True，feasibility_reason="MATLAB adapter path generated" |
| 空点云异常路径 | ✅ | status_code=1，error_message="空点云请求" |
| 5 次顺序请求稳定性 | ✅ | 5/5 成功 |
| 生产路径（CoordinationService） | ✅ | bridge_active=True，client=LegacyZmqClient |

**结论**：GUI → CoordinationService → LegacyZmqClient → BridgeClient → ZeroMQ(5555) → Protocol Buffers(v2.1) → matlab_bridge_server.m → MatlabAdapter → MATLAB R2025b 全链路真实通信验证通过。

---

## 5. 变更记录

### 2026-07-10 通信架构收敛

| 变更 | 受影响文件 | 原因 | 验证方法 | 风险 |
|------|-----------|------|----------|------|
| 添加 DEPRECATED 标记 | `engine/matlab_engine.py` | TCP/JSON/v3.0/5570 已弃用 | import 触发 DeprecationWarning | 低（仅警告，不改行为） |
| 添加 DEPRECATED 标记 | `engine/factory.py` | 同上 | 调用 create_engine 触发警告 | 低 |
| 添加 DEPRECATED 标记 | `engine/lifecycle.py` | 同上 | 文档标记 | 低 |
| 添加 DEPRECATED 标记 | `bridge/protocol_v3/__init__.py` | v3.0 协议已弃用 | import 触发 DeprecationWarning | 低 |
| 添加 DEPRECATED 标记 | `bridge/protocol_v3/serialization.py` | 同上 | 文档标记 | 低 |
| 添加 DEPRECATED 标记 | `bridge/protocol_v3/algorithm_protocol_v3.proto` | 同上 | 文档标记 | 低 |
| 添加 DEPRECATED 标记 | `matlab_server/README.md` | TCP 服务端已弃用 | 文档标记 | 低 |
| 新建本文档 | `docs/COMMUNICATION.md` | 记录最终通信架构 | 人工审阅 | 无 |
| 新建 MATLAB 集成文档 | `docs/MATLAB_INTEGRATION.md` | 指导 MATLAB 集成 | 人工审阅 | 无 |

---

## 6. 生产就绪阻塞项

1. ~~**[BLOCKER] MATLAB R2025b 未安装/未运行**~~：**已解决**（2026-07-10）。MATLAB R2025b 已安装于 `D:\work\matlab\bin\matlab.exe`，端到端验证通过（见 4.2 节）。
2. **[HIGH] MatlabService 未接入 GUI**：`bridge/services/matlab_service.py` 已实现但 GUI 仍通过 LegacyZmqClient 直接访问。这是技术债务，不阻塞当前生产路径（LegacyZmqClient 同样经由 BridgeClient），但影响架构纯洁性。
3. **[HIGH] 异常类型翻译失效**：`zmq_client.py:279` 处的异常翻译存在缺陷（详见端到端仿真验证报告 F-01）。
4. **[HIGH] 心跳丢失不触发重连**：HeartbeatMonitor 检测到心跳丢失时未触发自动重连（详见 F-05）。

---

## 7. 相关文档

- [BRIDGE_ARCHITECTURE.md](BRIDGE_ARCHITECTURE.md) — Bridge 层详细架构
- [MATLAB_INTEGRATION.md](MATLAB_INTEGRATION.md) — MATLAB R2025b 集成指南
- [MIGRATION_REPORT.md](MIGRATION_REPORT.md) — 通信层迁移报告
- [端到端仿真验证报告.md](端到端仿真验证报告.md) — 全链路验证报告
- [ARCHITECTURE.md](../ARCHITECTURE.md) — 系统分层架构
