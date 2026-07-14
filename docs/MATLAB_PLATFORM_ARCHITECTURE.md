# MATLAB 执行平台架构文档

> 版本：1.0.0 | 协议 v3.0 | 2026-07-10
> 状态：生产就绪（MATLAB Server 独立部署 + Python MatlabEngine 客户端）

## 1. 概述

MATLAB 执行平台将 MATLAB 从"Python 宿主附属"提升为**独立长驻的工业算法服务器**。
GUI 只作为应用层，通过 `IAlgorithmEngine` 抽象调用 MATLAB 算法，永远不感知后端实现。

### 目标架构

```
GUI (MainWindow)
  ↓
CoordinationService
  ↓
EngineFactory
  ↓
MatlabEngine (IAlgorithmEngine 实现)
  ↓ TcpChannel (JSON-over-TCP, 4-byte length framing)
MATLAB Server (matlab_server/startup.m)
  ↓
Algorithm Registry (声明式注册表)
  ↓
MATLAB Algorithms (路径规划/*.m, 形貌预测/*.m)
  ↓
Structured Results (JSON → Tensor → numpy)
  ↓
GUI
```

## 2. 组件清单

### Python 侧 (`repair_app/`)

| 组件 | 文件 | 职责 |
|------|------|------|
| Protocol v3.0 | `bridge/protocol_v3/algorithm_protocol_v3.proto` | 算法无关通用协议定义 |
| Protocol 序列化 | `bridge/protocol_v3/serialization.py` | numpy↔Tensor, Python↔Value 转换 |
| MatlabEngine | `engine/matlab_engine.py` | IEngine 实现，TCP 通信，算法执行 |
| EngineFactory | `engine/factory.py` | 引擎选择（MATLAB 优先，Python 降级） |
| LifecycleSupervisor | `engine/lifecycle.py` | 心跳、重连、断路器、崩溃恢复 |
| LocalEngine | `engine/local_engine.py` | Python 原型引擎（降级用） |

### MATLAB 侧 (`matlab_server/`)

| 组件 | 文件 | 职责 |
|------|------|------|
| 启动入口 | `startup.m` | 环境初始化、路径配置、启动服务 |
| 主服务器 | `server.m` | TCP ServerSocket、accept/dispatch 循环 |
| 配置管理 | `config.m` | 环境变量读取、默认值 |
| 算法注册表 | `registry.m` | 声明式注册、查找、列表 |
| 算法注册 | `register_algorithms.m` | 注册 18 个 MATLAB 算法 |
| 请求分发 | `dispatcher.m` | 消息路由、算法调用、crash guard |
| 健康检查 | `health.m` | 内存、运行时间、工具箱可用性 |
| 心跳 | `heartbeat.m` | 即时响应心跳 |
| 生命周期 | `lifecycle.m` | 请求计数、错误统计 |
| 资源清理 | `resource_cleanup.m` | 定期 clear vars、pack |
| 日志 | `logger.m` | JSONL 结构化日志 |
| JSON 编解码 | `json_codec.m` | MATLAB↔JSON 转换、base64 Tensor |
| 说明 | `README.md` | 部署指南 |

## 3. 通信协议 v3.0

### 设计原则

- **算法无关**：协议层不绑定任何业务字段
- **自描述**：算法元数据通过 `AlgorithmMetadata` 运行期发现
- **可扩展**：新增算法零协议改动
- **双格式**：Protobuf（Python 内部）+ JSON-over-TCP（MATLAB 通信）

### 消息类型

| 消息 | 方向 | 用途 |
|------|------|------|
| `AlgorithmRequest` | C→S | 调用算法 |
| `AlgorithmResponse` | S→C | 返回结果/错误 |
| `Heartbeat`/`Pong` | 双向 | 心跳 |
| `HealthCheckRequest`/`HealthStatus` | C→S/S→C | 健康检查 |
| `ListAlgorithmsRequest`/`Response` | C→S/S→C | 算法发现 |
| `VersionNegotiate`/`VersionResult` | C→S/S→C | 版本协商 |
| `Cancellation` | C→S | 请求取消 |
| `ShutdownRequest`/`ShutdownAck` | C→S/S→C | 优雅关闭 |
| `ProgressUpdate` | S→C | 流式进度 |

### 传输格式

MATLAB 侧使用 **JSON-over-TCP**（避免 ZMQ/Protobuf 依赖）：
- 4 字节大端长度前缀 + UTF-8 JSON 负载
- Tensor 数据 base64 编码
- 由 `java.net.ServerSocket` 提供 TCP 传输

Python 侧 `MatlabEngine` 使用相同的 JSON-over-TCP 协议直连 MATLAB Server。

## 4. 算法注册表

### 已注册算法（18 个）

| 命名空间 | 算法名 | 源文件 | 工具箱依赖 |
|----------|--------|--------|-----------|
| path_planning | layer_slice | layer_slice.m | 无 |
| path_planning | model_process | model_process.m | 无 |
| path_planning | generate_path | generate_path.m | Mapping Toolbox |
| path_planning | a_star_search | aStarSearch.m | 无 |
| path_planning | point_interpretaion | point_interpretaion.m | 无 |
| path_planning | read_stl_file | read_stl_file.m | 无 |
| path_planning | robot_command_output | robot_command_output.m | 无 |
| morphology | spot_interp | spotInterp.m | 无 |
| morphology | ray_triangle_intersection | ray_triangle_intersection.m | 无 |
| morphology | build_octree | buildOctree.m | 无 |
| morphology | batch_octree_filter | batchOctreeFilter.m | 无 |
| morphology | classify_removed_triangles | classifyRemovedTriangles.m | 无 |
| morphology | create_triangulation_from_matrix | createTriangulationFromMatrix.m | 无 |
| morphology | improve_short_edges | improveShortEdges.m | 无 |
| morphology | ray_move | rayMove.m | 无 |
| morphology | recursive_subdivide | recursiveSubdivide.m | 无 |
| morphology | profile_predict | profilePredict.m | Mapping Toolbox |
| morphology | particle_fitting | particleFitting.m | Curve Fitting Toolbox |
| morphology | read_stlfile | read_STLfile.m | 无 |

### 新增算法

在 `register_algorithms.m` 中追加一条 `registry.register(...)` 调用即可，**分发器、协议、客户端零改动**。

## 5. 工业稳定性

| 能力 | 实现 |
|------|------|
| 心跳 | LifecycleSupervisor 周期探测（默认 2s） |
| 自动重连 | 指数退避（1s→2s→4s→...→30s 上限） |
| 崩溃恢复 | 心跳丢失 N 次 → RECONNECTING → 成功则 READY |
| 断路器 | 连续失败 5 次 → OPEN（拒绝请求）→ 30s 后 HALF_OPEN（探测）→ CLOSED |
| 超时 | 三层：传输 poll、请求级 timeout_ms、算法级 timer |
| 优雅降级 | MATLAB 不可用 → EngineFactory 自动回退 LocalEngine |
| 资源清理 | MATLAB 侧每 N 请求 clear vars + 周期 pack |
| Crash Guard | dispatcher 全包 try/catch，单请求失败不影响服务 |

## 6. 部署

### 单机部署

```
# 1. 启动 MATLAB Server（MATLAB 中）
cd matlab_server
startup  % 监听 tcp://*:5570

# 2. 启动 Python GUI
python -m repair_app  % 自动探测 MATLAB，失败则降级
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_MATLAB_BIND` | `tcp://*:5570` | MATLAB Server 监听地址 |
| `CSAM_MATLAB_HOST` | `127.0.0.1` | MatlabEngine 连接主机 |
| `CSAM_MATLAB_PORT` | `5570` | MatlabEngine 连接端口 |
| `CSAM_MATLAB_LOG_DIR` | `./logs` | MATLAB 日志目录 |
| `CSAM_MATLAB_HEARTBEAT_MS` | `1000` | 心跳间隔 |
| `CSAM_ENGINE_DISABLE_MATLAB` | `0` | 禁用 MATLAB 引擎（强制 Python） |
| `CSAM_HEARTBEAT_INTERVAL_MS` | `2000` | 客户端心跳间隔 |
| `CSAM_HEARTBEAT_MISS_THRESHOLD` | `3` | 心跳丢失阈值 |
| `CSAM_RECONNECT_MAX_ATTEMPTS` | `10` | 最大重连次数 |

## 7. 测试

| 测试集 | 测试数 | 范围 |
|--------|--------|------|
| `test_matlab_platform.py` | 35 | 协议、引擎、通道、工厂、生命周期、超时、端到端、性能 |
| 现有测试 | 270 | 全部回归通过 |
| **总计** | **305** | **全部通过** |

## 8. 故障排除

| 症状 | 可能原因 | 解决方案 |
|------|---------|---------|
| `MatlabEngine not reachable` | MATLAB Server 未启动 | 在 MATLAB 中运行 `startup` |
| `circuit breaker OPEN` | 连续失败超阈值 | 检查 MATLAB Server 日志，重启服务 |
| `ERR_DEPS` | 工具箱许可证缺失 | 检查 `license('test','Map_Toolbox')` |
| 内存持续增长 | MATLAB 工作区泄漏 | 调小 `cleanup_interval`，或重启 Server |
| 超时频繁 | 算法计算时间长 | 增大 `timeout_ms` 参数 |
