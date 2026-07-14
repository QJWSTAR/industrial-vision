# Python-MATLAB 通信桥接层架构文档

> Bridge Layer v1.0.0 | 协议版本 v2.1 | 适用于 CSAM Repair 项目
> **状态：生产通信路径（2026-07-10 起）** — MainWindow 已通过 `LegacyZmqClient` 适配器接入 bridge。
> 旧版 `repair_app/communication/zmq_client.py` 已标记 deprecated。

## 目录

1. [通信架构](#1-通信架构)
2. [ZeroMQ 模式选型](#2-zeromq-模式选型)
3. [协议规范](#3-协议规范)
4. [序列化方案](#4-序列化方案)
5. [MATLAB 服务端](#5-matlab-服务端)
6. [Python 客户端](#6-python-客户端)
7. [错误处理](#7-错误处理)
8. [配置指南](#8-配置指南)
9. [日志系统](#9-日志系统)
10. [性能优化](#10-性能优化)
11. [部署指南](#11-部署指南)
12. [调试指南](#12-调试指南)
13. [故障排查](#13-故障排查)
14. [时序图](#14-时序图)

---

## 1. 通信架构

### 1.1 分层设计

```
┌─────────────────────────────────────────────────┐
│              业务层 (UI / Service)                │
│         MatlabService (唯一入口)                  │
├─────────────────────────────────────────────────┤
│              适配器层 (Adapters)                  │
│    MatlabAdapter    LegacyZmqClient              │
├─────────────────────────────────────────────────┤
│            通信层 (Communication)                 │
│  BridgeClient  BridgeServer  Serializer          │
│  HeartbeatMonitor  MessageEnvelope               │
├─────────────────────────────────────────────────┤
│           基础设施 (Infrastructure)               │
│      ZeroMQ  +  Protobuf  +  NumPy               │
└─────────────────────────────────────────────────┘
```

### 1.2 目录结构

```
repair_app/bridge/
├── __init__.py                      # 公共 API 导出
├── communication/
│   ├── config.py                    # 集中化配置（无硬编码）
│   ├── exceptions.py                # 结构化异常层次
│   ├── message.py                   # 消息信封（request_id + 追踪）
│   ├── protocol.py                  # 协议常量与版本管理
│   ├── serializer.py                # 序列化门面（复用 Protobuf）
│   ├── heartbeat.py                 # 心跳监控（QThread）
│   ├── zmq_client.py                # 异步客户端（QThread + 协作中断）
│   └── zmq_server.py                # 服务端基类（poll 可中断）
├── services/
│   └── matlab_service.py            # 业务层唯一入口
├── adapters/
│   ├── matlab_adapter.py            # MATLAB 算法适配器
│   └── legacy_adapter.py            # 向后兼容 ZmqRepairClient
└── tests/
    └── test_bridge.py               # 41 项测试（单元+集成+压力+性能）
```

### 1.3 设计原则

- **业务层隔离**：业务模块只通过 `MatlabService` 访问 MATLAB，不直接导入通信层
- **向后兼容**：`LegacyZmqClient` 保持与现有 `ZmqRepairClient` API 完全兼容
- **不破坏现有功能**：新 `bridge/` 包独立于现有 `communication/`，零侵入
- **SOLID 原则**：单一职责（每个模块一个功能）、依赖倒置（业务层依赖抽象接口）

---

## 2. ZeroMQ 模式选型

### 2.1 模式评估

| 模式 | 适用性 | 评估 |
|------|--------|------|
| **REQ/REP** | ✅ 采用 | 同步请求-回复，匹配修复请求语义。简单可靠，MATLAB 易实现 |
| DEALER/ROUTER | ❌ 不采用 | 异步多路复用，复杂度高。当前单客户端单服务端无需 |
| PUSH/PULL | ❌ 不采用 | 单向管道，不适合请求-回复模式。适合日志收集场景 |
| PUB/SUB | 🔜 预留 | 适合进度推送（逐层路径规划）。当前一次性返回，未来扩展用 |

### 2.2 选型理由

**REQ/REP** 是最佳选择：
1. 修复请求是严格的请求-回复语义（一发一收）
2. MATLAB 原生 ZMQ 绑定对 REQ/REP 支持最好
3. 协议已有 HealthCheckRequest/RepairRequest 两种消息类型，REQ/REP 可自然分发
4. 同步模型降低调试难度，符合工业软件可靠性要求

### 2.3 未来扩展

当需要逐层进度推送时，可采用 **REQ/REP + PUB/SUB 混合**：
- REP 5555：修复请求/回复
- PUB 5556：进度推送（ProgressUpdate 消息已定义）

---

## 3. 协议规范

### 3.1 版本

- 当前版本：**v2.1**
- 兼容版本：v2.0, v2.1
- 协议定义文件：`repair_protocol.proto`（不可修改）

### 3.2 消息类型

| 类型 | 方向 | Protobuf 消息 | 用途 |
|------|------|--------------|------|
| 健康检查 | C→S | HealthCheckRequest | 探活 |
| 健康响应 | S→C | HealthCheckResponse | 返回引擎状态 |
| 修复请求 | C→S | RepairRequest | 点云 + 工艺参数 |
| 修复结果 | S→C | RepairResult | 航点 + 指标 |
| 进度更新 | S→C | ProgressUpdate | 逐层推送（预留） |

### 3.3 消息信封

每条消息附加元数据：
```python
MessageEnvelope(
    message_type=MessageType.REPAIR_REQUEST,
    payload=<protobuf bytes>,
    request_id="path-1234567890-abc123",  # 全链路追踪
    timestamp=1719900000.0,                # 延迟分析
    version="2.1",                         # 兼容性检查
    algorithm="path_planner",              # 算法标识
    processing_time_ms=50,                 # 服务端耗时
)
```

### 3.4 状态码

| 码值 | 名称 | 含义 | 可重试 |
|------|------|------|--------|
| 0 | SUCCESS | 成功 | - |
| 1 | ERR_INVALID_INPUT | 参数错误 | 否 |
| 2 | ERR_NO_DEFECT_FOUND | 未发现缺陷 | 否 |
| 3 | ERR_ALGORITHM_FAIL | 算法失败 | 否 |
| 4 | ERR_TIMEOUT | 超时 | 是 |
| 5 | ERR_NOT_FEASIBLE | 不可修复 | 否 |
| 99 | ERR_UNKNOWN | 未知错误 | 是 |

---

## 4. 序列化方案

### 4.1 选型结论

**Protocol Buffers**（已采用，v2.1 协议固定）

### 4.2 方案对比

| 方案 | 体积 | 速度 | 跨语言 | Schema | 选型 |
|------|------|------|--------|--------|------|
| Protobuf | 最小 | 快 | ✅ Python/MATLAB/Java | ✅ 强类型 | ✅ 采用 |
| JSON | 3-5x | 慢 | ✅ | ❌ 无 | 仅日志 |
| MessagePack | 中 | 快 | ⚠️ 类型歧义 | ❌ 无 | 不采用 |
| NumPy binary | 最小 | 最快 | ❌ 仅 Python | ❌ 无 | 不采用 |
| MAT files | 大 | 慢 | ⚠️ 需 scipy | ❌ 无 | 不采用 |

### 4.3 数据布局

- **点云**：SoA (Struct of Arrays) — `x[], y[], z[], nx[], ny[], nz[]` 各为 repeated float
- **航点**：AoS (Array of Structs) — `repeated Waypoint {x, y, z, nx, ny, nz, feed_rate, layer_index}`

---

## 5. MATLAB 服务端

### 5.1 架构

```matlab
% matlab_bridge_server.m
pyenv('Version', venvPython);                    % 设置 Python 环境
adapter = py.importlib.import_module(...)
    .MatlabAdapter(address=address);             % 创建适配器
adapter.install_signal_handlers();               % 安装信号处理
adapter.serve();                                 % 阻塞服务（poll 可中断）
```

### 5.2 职责

| 职责 | 实现位置 |
|------|----------|
| 初始化 ZMQ | `BridgeServer.serve()` — 创建 REP socket + bind |
| 接收请求 | `BridgeServer._dispatch()` — 消息分发 |
| 参数校验 | `MatlabAdapter.handle_repair()` — 空点云检测 |
| 算法调用 | `MatlabAdapter._invoke_algorithm()` — 可注入算法函数 |
| 异常捕获 | `BridgeServer._dispatch()` — try/except 包裹 |
| 结构化响应 | `Serializer.build_repair_result()` — 统一结果格式 |
| 优雅关闭 | `BridgeServer.stop()` + poll 循环 — 200ms 内退出 |

### 5.3 自定义算法

```python
# 替换默认算法为 MATLAB 原生函数
def matlab_algorithm(xyz, meta):
    import matlab.engine
    eng = matlab.engine.start_matlab()
    result = eng.plan_path(matlab.double(xyz.tolist()))
    return np.array(result)

adapter = MatlabAdapter(algorithm_fn=matlab_algorithm)
```

---

## 6. Python 客户端

### 6.1 MatlabService（业务层入口）

```python
from repair_app.bridge import MatlabService, RepairOutcome

service = MatlabService()
service.start_heartbeat()  # 后台心跳

service.request_path_planning(
    xyz=point_cloud,
    normals=normals,
    params=workflow_params,
    on_success=lambda outcome: print(f"{len(outcome.waypoints)} 航点"),
    on_error=lambda msg: print(f"错误: {msg}"),
)

service.close()
```

### 6.2 特性

| 特性 | 实现 |
|------|------|
| 连接管理 | `BridgeClient` — QThread 封装，自动清理 |
| 请求生成 | `MatlabService.request_path_planning()` — 参数校验 + 请求构建 |
| 超时处理 | `BridgeConfig.request_timeout_ms` — poll 循环 + 协作中断 |
| 心跳 | `HeartbeatMonitor` — 周期性健康检查，miss 阈值告警 |
| 异常翻译 | `translate_zmq_error()` — ZMQ 异常 → BridgeError |
| 日志 | 延迟超阈值告警 + 请求/响应/错误全记录 |
| 资源清理 | `close()` — 停止心跳 + 中断 worker + 关闭 socket |

---

## 7. 错误处理

### 7.1 异常层次

```
BridgeError (基类)
├── ConnectionError (连接问题)
│   ├── ConnectionTimeoutError (超时，含 timeout_ms)
│   ├── EngineUnavailableError (引擎不可达)
│   └── EngineCrashError (引擎崩溃)
├── SerializationError (编解码失败)
├── InvalidParameterError (参数错误，含 parameter 名)
├── AlgorithmError (算法失败，含 algorithm 名)
├── ProtocolError (协议不兼容，含版本信息)
└── ShutdownError (通信层已关闭)
```

### 7.2 错误处理原则

- **业务层永不接触原始异常**：所有 ZMQ/Protobuf 异常经 `translate_zmq_error()` 翻译
- **不返回原始堆栈**：异常消息只含可读描述 + request_id
- **结构化错误**：每个异常携带上下文信息（timeout_ms、parameter、algorithm 等）
- **可重试判断**：`is_status_retriable()` 区分可重试错误（超时/未知）与不可重试错误（参数错误）

---

## 8. 配置指南

### 8.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_ZMQ_ADDRESS` | 平台默认 | ZMQ 地址（Windows: tcp://127.0.0.1:5555） |
| `CSAM_BRIDGE_TIMEOUT_MS` | 30000 | 请求超时（毫秒） |
| `CSAM_BRIDGE_CONNECT_MS` | 5000 | 连接超时 |
| `CSAM_BRIDGE_HEALTH_MS` | 3000 | 健康检查超时 |
| `CSAM_BRIDGE_HEARTBEAT_MS` | 5000 | 心跳间隔 |
| `CSAM_BRIDGE_HEARTBEAT_MISS` | 3 | 心跳丢失阈值 |
| `CSAM_BRIDGE_MAX_RETRIES` | 3 | 最大重试次数 |
| `CSAM_BRIDGE_RETRY_MS` | 2000 | 重试间隔 |
| `CSAM_LOG_LEVEL` | INFO | 日志级别 |

### 8.2 代码配置

```python
from repair_app.bridge import BridgeConfig, MatlabService

config = BridgeConfig(
    address="tcp://192.168.1.100:5555",
    request_timeout_ms=60000,
    heartbeat_interval_ms=3000,
)
service = MatlabService(config=config)
```

---

## 9. 日志系统

### 9.1 日志点

| 事件 | 级别 | 内容 |
|------|------|------|
| 服务启动 | INFO | 地址 + 版本 |
| 请求发起 | INFO | request_id + 点数 + 地址 |
| 请求完成 | INFO | request_id + 状态 + 航点数 + 耗时 |
| 延迟告警 | WARNING | request_id + 耗时 + 阈值 |
| 请求失败 | ERROR | request_id + 错误消息 |
| 心跳启动 | INFO | 间隔 |
| 心跳失联 | WARNING | 连续 miss 次数 |
| 服务停止 | INFO | 统计（handled/health/errors） |

### 9.2 日志格式

复用项目现有 `logger_config.py`（loguru / logging 回退）：
```
2026-07-09 14:30:00 | INFO | csam.bridge.service:request_path_planning:120 | 路径规划完成 [path-123]: SUCCESS, 90 航点, 152ms
```

---

## 10. 性能优化

### 10.1 大数组传输

- 点云使用 **SoA 布局**（Protobuf repeated float），比 AoS 减少 20% 序列化体积
- 5 万点序列化往返 < 1 秒（基准测试验证）
- 超过 100 万点触发警告日志

### 10.2 内存优化

- `zmq.Context.instance()` 共享上下文，避免重复创建
- `LINGER=0` 确保 socket 即时释放
- QThread worker 用完即销毁，不持有引用

### 10.3 并发优化

- 客户端使用协作式中断（200ms poll），不阻塞 Qt 事件循环
- 服务端使用 poll 循环（200ms），可被 `stop()` 中断
- 心跳独立 QThread，不影响请求处理

### 10.4 性能基准

| 操作 | 数据量 | 耗时 | 吞吐 |
|------|--------|------|------|
| 序列化请求 | 5 万点 | < 1s | > 5 万点/s |
| 反序列化往返 | 2000 点 | < 100ms | - |
| 构建结果 | 500 航点 | < 100ms | - |
| 端到端请求 | 2000 点 | ~150ms | - |

---

## 11. 部署指南

### 11.1 Python 端

```bash
# 1. 激活虚拟环境
cd industrial-vision
venv\Scripts\activate

# 2. 配置地址（可选）
set CSAM_ZMQ_ADDRESS=tcp://127.0.0.1:5555

# 3. 启动 GUI
python run_app.py
```

### 11.2 MATLAB 端

```matlab
% 在 MATLAB 命令行
cd('D:\work\demo\industrial-vision')
matlab_bridge_server                           % 默认地址
matlab_bridge_server('tcp://127.0.0.1:5555')  % 指定地址
```

### 11.3 纯 Python 服务端（无需 MATLAB）

```bash
python -c "from repair_app.bridge.adapters import MatlabAdapter; MatlabAdapter().serve()"
```

---

## 12. 调试指南

### 12.1 开启调试日志

```bash
set CSAM_LOG_LEVEL=DEBUG
```

### 12.2 自检

```python
from repair_app.bridge.communication.serializer import Serializer
Serializer.self_test()  # 序列化自检
```

### 12.3 连通性测试

```python
from repair_app.bridge import MatlabService

service = MatlabService()
service.check_health(lambda ok, msg: print(f"引擎: {'在线' if ok else '离线'} - {msg}"))
```

---

## 13. 故障排查

| 症状 | 可能原因 | 解决方案 |
|------|----------|----------|
| 健康检查超时 | 服务端未启动 | 启动 `matlab_bridge_server` |
| `Address in use` | 端口被占用 | 更改 `CSAM_ZMQ_ADDRESS` 端口 |
| 序列化失败 | 点云形状不对 | 确保 xyz 为 (N,3) float32 |
| `pyzmq 未安装` | 依赖缺失 | `pip install pyzmq` |
| 心跳频繁丢失 | 网络不稳定 | 增大 `CSAM_BRIDGE_HEARTBEAT_MISS` |
| 请求无响应 | 服务端阻塞 | 检查算法是否死循环 |

---

## 14. 时序图

### 14.1 路径规划请求

```
GUI (MainWindow)         MatlabService         BridgeClient         ZMQ REP Server
     │                        │                     │                      │
     │ request_path_planning  │                     │                      │
     │───────────────────────>│                     │                      │
     │                        │ build_repair_request│                      │
     │                        │ serialize_request   │                      │
     │                        │───────────────────>│                      │
     │                        │                     │ ZMQ REQ send         │
     │                        │                     │─────────────────────>│
     │                        │                     │                      │ handle_repair
     │                        │                     │                      │ plan_path_from_cloud
     │                        │                     │                      │ build_repair_result
     │                        │                     │<─────────────────────│
     │                        │                     │ deserialize_result   │
     │                        │                     │ emit result_ready    │
     │                        │<───────────────────│                      │
     │                        │ RepairOutcome       │                      │
     │<───────────────────────│                     │                      │
     │ update UI              │                     │                      │
```

### 14.2 心跳监控

```
HeartbeatMonitor          BridgeClient         ZMQ REP Server
     │                        │                     │
     │ ── loop ──>            │                     │
     │   check_health         │                     │
     │───────────────────────>│                     │
     │                        │ HealthCheckRequest  │
     │                        │────────────────────>│
     │                        │<────────────────────│
     │                        │ HealthCheckResponse │
     │<───────────────────────│                     │
     │   ok=True, latency=5ms │                     │
     │   emit latency_updated │                     │
     │                        │                     │
     │   sleep(5000ms)        │                     │
     │   ── loop ──>          │                     │
```

### 14.3 错误处理流程

```
BridgeClient              ZMQ Server (crashed)
     │                        │
     │ REQ send               │
     │───────────────────────>│ X (no response)
     │                        │
     │ poll(200ms) x N        │
     │ timeout (30000ms)      │
     │                        │
     │ emit error_occurred    │
     │ translate_zmq_error    │
     │   → ConnectionTimeout  │
     │<───────────────────────│
     │ on_error(BridgeError)  │
```
