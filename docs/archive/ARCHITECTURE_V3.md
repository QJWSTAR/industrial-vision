# CSAM 修复软件 — 下一代 MATLAB 集成架构设计文档

> 角色：首席架构师 (Lead Architect)
> 状态：设计阶段（Release Candidate 之后的架构演进）
> 约束：仅设计，不修改任何仓库文件
> 语言：中文（沿用项目约定）

---

## 0. 执行摘要 (Executive Summary)

当前仓库已达到 RC 质量：成熟的 PySide6 桌面应用、桥接层 (`bridge/`)、ZMQ 基础设施、Protobuf v2.1 协议、Windows/macOS 支持、CI/CD、自动化测试齐备。但 MATLAB 集成仍处于**原型形态**：

1. **MATLAB 仅作为 Python 宿主的子进程**（`pyenv` 反向调用），并非真正的"MATLAB 作为算法服务器"。
2. 现有协议 `RepairRequest` 是**业务专用、强耦合**的，无法承载未来算法扩展。
3. `IEngine` 抽象仅存在 `LocalEngine` 一个实现，MATLAB 通道未抽象为可插拔引擎。
4. 形貌预测（`形貌预测/`）没有 ZMQ 通道，仅路径规划有。
5. 两套通信层并存（旧 `communication/` + 新 `bridge/`），MainWindow 尚未集成 bridge。

本设计将 MATLAB 从"Python 宿主的附属"提升为**独立的、长驻的、可远程部署的工业算法引擎**，并建立**与具体算法解耦的通用协议**与**引擎抽象层 `IAlgorithmEngine`**，使 GUI 永远不知道是哪个引擎在执行。

目标拓扑：

```
Python GUI  →  Service Layer  →  IAlgorithmEngine  →  ZeroMQ  →  Native MATLAB Server  →  MATLAB Algorithms  →  Structured Results  →  Python GUI
```

---

## 1. 现状架构 (Current Architecture)

### 1.1 现状依赖图 (Dependency Map)

```
                       ┌──────────────────────────────────────────┐
                       │            repair_app/ui/main_window.py  │  ← God Class (1703 行, 11% 覆盖)
                       │   直接协调工作流，未集成 bridge 层         │
                       └───────────────┬──────────────────────────┘
                                       │ 直接调用
                       ┌───────────────▼──────────────────────────┐
                       │   repair_app/core/path_planner.py         │
                       │   repair_app/core/morphology_predictor.py │  ← 纯 Python 原型算法
                       └───────────────┬──────────────────────────┘
                                       │
                       ┌───────────────▼──────────────────────────┐
                       │   repair_app/engine/local_engine.py       │  ← IEngine 唯一实现
                       │   (LocalEngine 包装 Python 原型)          │
                       └──────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────────┐
   │  旧通信层 (communication/)  ←  ZmqRepairClient (QThread)      │
   │  repair_app/communication/zmq_client.py                      │
   │  repair_app/communication/zmq_server.py                      │
   └──────────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────────┐
   │  新桥接层 (bridge/)  ←  Phase 5 交付，未集成                  │
   │  bridge/communication/zmq_client.py   (BridgeClient)          │
   │  bridge/communication/zmq_server.py   (BridgeServer)          │
   │  bridge/communication/heartbeat.py    (HeartbeatMonitor)      │
   │  bridge/communication/protocol.py     (MessageType v2.1)      │
   │  bridge/communication/serializer.py   (Serializer facade)     │
   │  bridge/services/matlab_service.py    (MatlabService 门面)    │
   │  bridge/adapters/matlab_adapter.py    (MatlabAdapter)         │
   │  bridge/adapters/legacy_adapter.py    (LegacyZmqClient)       │
   └──────────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────────┐
   │  MATLAB 侧 (原型)                                             │
   │  matlab_bridge_server.m  ← 用 pyenv 反向调用 MatlabAdapter    │
   │  路径规划/  (8 个 .m，main.m 是脚本)                          │
   │  形貌预测/  (15 个 .m，main.m 是脚本)                         │
   └──────────────────────────────────────────────────────────────┘
```

### 1.2 现状问题清单

| 编号 | 问题 | 影响 |
|---|---|---|
| C1 | MATLAB 通过 `pyenv` 反向被 Python 宿主调用 | 不是真正的 MATLAB 服务器，无法独立部署/远程化/多实例 |
| C2 | 协议 `RepairRequest` 字段全部硬编码业务语义 | 新增算法必须改 proto + 重新生成 + 改两端代码 |
| C3 | `IEngine` 只有 `LocalEngine`，无 MATLAB 实现 | 引擎抽象名存实亡，GUI 仍绑定 Python 算法 |
| C4 | 形貌预测无 ZMQ 通道 | 两个 MATLAB 模块一个能远程一个不能 |
| C5 | `main.m` 是脚本（带 `clear all`） | 无法作为函数式 API 调用 |
| C6 | MainWindow 未集成 bridge | 两套通信层并存，架构割裂 |
| C7 | `point_interpretaion.m` 第 54 行 bug (`y_rotaxis` 应为 `z_rotaxis`) | 路径点姿态计算错误 |
| C8 | MATLAB 算法依赖 Mapping Toolbox / Curve Fitting Toolbox | 部署需许可证，需在启动期校验 |

### 1.3 MATLAB 算法源文件分析结论（Task 2 回顾）

**路径规划（`路径规划/`）— 8 文件：**

| 文件 | 类型 | 可作公开 API | 关键点 |
|---|---|---|---|
| `generate_path.m` | 纯函数 | ✅ | 14 参数，依赖 Mapping Toolbox `polyxpoly` |
| `layer_slice.m` | 纯函数 | ✅ | 分层切片，无工具箱依赖 |
| `model_process.m` | 纯函数 | ✅ | STL 预处理，无工具箱依赖 |
| `aStarSearch.m` | 纯函数 | ✅ | A* 搜索，O(n²) 优先队列待优化 |
| `point_interpretaion.m` | 纯函数 | ⚠️ | 第 54 行 bug 需先修 |
| `read_stl_file.m` | 纯函数 | ✅ | STL 读取 |
| `robot_command_output.m` | 纯函数 | ✅ | ABB RAPID 输出 |
| `main.m` | 脚本 | ❌ | 带 `clear all`，需函数化封装 |

**形貌预测（`形貌预测/`）— 15 文件：**

| 文件 | 类型 | 可作公开 API | 关键点 |
|---|---|---|---|
| `profilePredict.m` | 纯函数 | ✅ | 需 14 个预计算参数 |
| `particleFitting.m` | 纯函数 | ⚠️ | 依赖 Curve Fitting Toolbox `fit/fittype` |
| `spotInterp.m` | 纯函数 | ✅ | **路径规划↔形貌预测的桥梁**，消费 pointlist/velocitylist 产出 spotsList |
| `buildOctree.m` | 纯函数 | ✅ | 八叉树构建 |
| `batchOctreeFilter.m` | 纯函数 | ✅ | 八叉树过滤 |
| `classifyRemovedTriangles.m` | 纯函数 | ✅ | 三角形分类 |
| `createTriangulationFromMatrix.m` | 纯函数 | ✅ | 三角化 |
| `improveShortEdges.m` | 纯函数 | ✅ | 短边优化 |
| `rayMove.m` | 纯函数 | ✅ | 射线推进 |
| `ray_triangle_intersection.m` | 纯函数 | ✅ | Möller-Trumbore 交点 |
| `recursiveSubdivide.m` | 纯函数 | ✅ | 递归细分 |
| `read_STLfile.m` | 纯函数 | ✅ | STL 读取 |
| `createfigures.m` | 脚本/函数 | ⚠️ | 可视化，非算法核心 |
| `createvideo.m` | 脚本/函数 | ⚠️ | 可视化，非算法核心 |
| `main.m` | 脚本 | ❌ | 硬编码参数，需函数化封装 |

**结论：13 个 MATLAB 函数适合作为独立公开 API**（`main.m` 与可视化脚本除外，由 MATLAB Server 内部编排）。

---

## 2. 目标架构 (Future Architecture)

### 2.1 分层总览

```
┌─────────────────────────────────────────────────────────────┐
│  L1  表现层 (Presentation)                                   │
│      repair_app/ui/  —— PySide6 MainWindow / Panels         │
│      职责：渲染、用户输入、进度展示。不感知引擎。            │
├─────────────────────────────────────────────────────────────┤
│  L2  业务层 (Business / Service)                            │
│      repair_app/services/ —— PathPlanningService,          │
│      MorphologyService, CalibrationService, ExportService   │
│      职责：用例编排、参数校验、领域模型转换。               │
│      只依赖 IAlgorithmEngine，不依赖具体引擎。              │
├─────────────────────────────────────────────────────────────┤
│  L3  引擎抽象层 (Engine Abstraction)                        │
│      repair_app/engine/abc.py —— IAlgorithmEngine          │
│      实现类：PythonEngine / MatlabEngine /                 │
│              CppEngine(未来) / RemoteEngine(未来)           │
│      职责：以统一 API 调度任意后端。                         │
├─────────────────────────────────────────────────────────────┤
│  L4  通信层 (Transport)                                     │
│      engine/matlab/zmq_channel.py —— ZMQ REQ/DEALER        │
│      engine/matlab/protocol_v3/ —— Protobuf v3.0            │
│      职责：序列化、传输、心跳、重连。                        │
├─────────────────────────────────────────────────────────────┤
│  L5  算法层 (Algorithm Engine) —— MATLAB Server (独立进程) │
│      matlab_server/ (独立 MATLAB 工程)                      │
│      启动器 / 注册表 / 分发器 / 生命周期 / 日志 / 心跳       │
│      职责：长驻工业服务，托管所有 MATLAB 算法。             │
├─────────────────────────────────────────────────────────────┤
│  L6  算法实现层 (Algorithm Implementation)                  │
│      路径规划/*.m  形貌预测/*.m  —— 原始算法函数            │
│      职责：纯计算，无 I/O、无网络、无全局状态。             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

1. **算法即服务 (Algorithm-as-a-Service)**：每个 MATLAB 函数注册为一个命名 API，自描述输入输出。
2. **协议与业务解耦**：协议层只认识 `AlgorithmRequest/Response`，不认识"路径规划"或"形貌预测"。
3. **引擎可插拔**：GUI 与业务层只面向 `IAlgorithmEngine` 接口编程，引擎切换零代码改动。
4. **MATLAB 长驻无状态**：请求间通过"工作区清理协议"保证无状态，支持复用与水平扩展。
5. **优雅降级**：MATLAB 不可用时自动回退 Python 引擎（受控的降级，非静默）。
6. **工业级可观测**：结构化日志、心跳、健康检查、超时、指标贯穿全链路。

---

## 3. Task 3 — 生产级 MATLAB Server 设计

### 3.1 组件图 (Component Diagram)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     MATLAB Server (独立 MATLAB 进程)                 │
│                                                                     │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────┐  │
│  │  BootStrap   │──▶│  Config Loader │──▶│  Environment Check   │  │
│  │  (startup.m) │   │  (env + yaml)  │   │  (Toolbox/License)   │  │
│  └──────────────┘   └────────────────┘   └──────────┬───────────┘  │
│                                                     │              │
│                              ┌──────────────────────▼───────────┐  │
│                              │       Algorithm Registry          │  │
│                              │  name → AlgorithmDescriptor       │  │
│                              │  (fn, version, schema, timeout)   │  │
│                              └──────────────────┬───────────────┘  │
│                                                     │              │
│  ┌──────────────┐   ┌────────────────┐   ┌────────▼─────────┐    │
│  │  ZMQ Socket  │──▶│  Request       │──▶│  Dispatcher       │    │
│  │  (ROUTER/    │   │  Decoder       │   │  (lookup+invoke)  │    │
│  │   REP)       │   │  (protobuf)    │   │                   │    │
│  └──────┬───────┘   └────────────────┘   └────────┬──────────┘    │
│         ▲                                           │              │
│         │            ┌──────────────────────────────┼──────────┐  │
│         │            ▼                              ▼          │  │
│  ┌──────┴───────┐ ┌──────────────┐  ┌────────────────┐ ┌──────┴──┐ │
│  │  Response    │ │  Timeout     │  │  Resource      │ │ Worker  │ │
│  │  Encoder     │ │  Manager     │  │  Cleaner       │ │ Pool    │ │
│  │  (protobuf)  │ │  (timer)     │  │  (clear/pack)  │ │ (reuse) │ │
│  └──────────────┘ └──────────────┘  └────────────────┘ └─────────┘ │
│                                                                     │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────┐  │
│  │  Heartbeat   │   │  Health Check  │   │  Logger              │  │
│  │  Responder   │   │  (mem/uptime)  │   │  (structured JSONL)  │  │
│  └──────────────┘   └────────────────┘   └──────────────────────┘  │
│                                                                     │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────┐  │
│  │  Version Mgr │   │  Crash Guard   │   │  Shutdown Hook       │  │
│  │  (proto/srv) │   │  (try/catch)   │   │  (graceful drain)    │  │
│  └──────────────┘   └────────────────┘   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 启动流程 (Startup Sequence)

```
1. startup.m 入口
2. 解析环境变量: CSAM_MATLAB_BIND, CSAM_MATLAB_LOG_DIR, CSAM_MATLAB_HEARTBEAT_MS, ...
3. 加载 config.yaml (可选覆盖)
4. 环境自检:
   - license('test','Map_Toolbox') → 记录可用性
   - license('test','Curve_Fitting_Toolbox') → 记录可用性
   - ver → 记录 MATLAB 版本
5. 初始化 Algorithm Registry:
   - 注册 path_planning.generate_path   (v1.0, deps=[Map_Toolbox])
   - 注册 path_planning.layer_slice     (v1.0, deps=[])
   - 注册 path_planning.model_process   (v1.0, deps=[])
   - 注册 path_planning.a_star_search   (v1.0, deps=[])
   - 注册 morphology.profile_predict    (v1.0, deps=[])
   - 注册 morphology.particle_fitting   (v1.0, deps=[Curve_Fitting])
   - 注册 morphology.spot_interp        (v1.0, deps=[])   ← 桥接 API
   - 注册 morphology.build_octree ... 等
   - 注册 workflow.full_repair          (v1.0, 编排型，调用上述)
6. 初始化 ZMQ 上下文与 ROUTER socket，bind 到 CSAM_MATLAB_BIND
7. 启动 Heartbeat 定时器 (default 1000ms)
8. 启动 Resource Cleaner 定时器 (每 N 个请求 clear 一次工作区)
9. 发送 READY 信号 (stdout 日志 + 可选 IPC)
10. 进入 serve_loop (poll 200ms, 可被 shutdown 中断)
```

### 3.3 算法注册表 (Algorithm Registry)

每个注册项是一个 `AlgorithmDescriptor` 结构：

```
AlgorithmDescriptor:
  name:           string         # 命名空间风格 "path_planning.generate_path"
  version:        string         # 语义化版本 "1.0.0"
  fn_handle:      function_handle
  input_schema:   SchemaSpec     # 字段名/类型/形状/单位/范围
  output_schema:  SchemaSpec
  dependencies:   cell<string>   # ["Map_Toolbox", ...]
  timeout_ms:     int32          # 算法级默认超时
  idempotent:     bool           # 是否可安全重试
  streaming:      bool           # 是否产出 ProgressUpdate 流
  tags:           cell<string>   # ["path_planning","cpu_heavy"]
```

**关键点**：注册表是**声明式**的，新增算法只需在 `register_algorithms.m` 追加一条注册，**协议、分发器、Python 侧零改动**。Python 侧通过 `list_algorithms()` 元 API 动态发现。

### 3.4 请求分发器 (Request Dispatcher)

```
dispatch(request_bytes):
    envelope = decode_envelope(request_bytes)        # 拆信封
    log(req_id, algorithm, t0)

    switch envelope.message_type
        case ALGORITHM_REQUEST
            desc = registry.lookup(envelope.algorithm, envelope.version)
            if desc == null
                resp = error(UNKNOWN_ALGORITHM); send(resp); return
            if !deps_available(desc.dependencies)
                resp = error(DEPS_MISSING); send(resp); return
            validate(envelope.payload, desc.input_schema)   # 结构校验
            args = coerce(envelope.payload, desc.input_schema)

            timer = start_timer(envelope.timeout_ms or desc.timeout_ms)
            try
                result = with_crash_guard(() -> desc.fn_handle(args), timer)
                resp = build_response(SUCCESS, result, desc.output_schema)
            catch err
                if is_timeout(err)   resp = error(ERR_TIMEOUT)
                else                 resp = error(ERR_ALGORITHM_FAIL, err)
            end
            resource_cleaner.tick()
            send(resp)

        case HEARTBEAT          send(pong())
        case HEALTH_CHECK       send(health_snapshot())
        case CANCEL             cancel_token.signal(envelope.request_id)
        case VERSION_NEGOTIATE  send(negotiate(envelope.client_versions))
        case SHUTDOWN           initiate_graceful_shutdown()
    end
    log(req_id, status, t1, dt_ms)
```

### 3.5 治理能力清单

| 能力 | 实现要点 |
|---|---|
| **启动** | 声明式启动序列 + 环境自检 + READY 信号 |
| **关闭** | `SHUTDOWN` 消息 → 停止接受新请求 → 等待在途请求（grace period）→ close socket → clear 工作区 → flush 日志 → 退出 |
| **算法注册表** | 命名空间 + 版本 + schema + 依赖 + 超时，声明式注册 |
| **请求分发** | 类型 switch + lookup + validate + invoke + crash guard |
| **配置** | 环境变量优先 + config.yaml 兜底，零硬编码 |
| **日志** | JSONL 结构化日志：`{ts, level, req_id, algorithm, event, dt_ms, ...}` |
| **错误处理** | dispatcher 全包 try/catch，任何算法异常都转为结构化 `AlgorithmResponse.error`，**服务进程永不因单请求崩溃** |
| **心跳** | 1000ms 默认，`HEARTBEAT` 即时回 `PONG`，附带轻量状态 |
| **健康检查** | 内存占用 / 运行时长 / 排队数 / 工具箱可用性 / 最近错误率 |
| **资源清理** | 每 N 请求 `clear vars` + 周期性 `pack`；大数组显式 `clear` |
| **超时管理** | 双层：传输级（ZMQ poll）+ 算法级（timer + cancel token） |
| **多算法支持** | 注册表原生支持，命名空间隔离 |
| **版本管理** | 服务器版本 + 协议版本 + 每算法独立版本；`VERSION_NEGOTIATE` 协商 |

---

## 4. Task 4 — 通用通信协议 v3.0 设计

### 4.1 设计目标

> **明确约束：不以 `RepairRequest` 作为长期协议。**

`RepairRequest` 是业务专用消息（字段全部硬编码路径/形貌语义）。v3.0 改为**算法无关的通用信封 + 自描述负载**：协议层只懂"调用某算法"，算法的输入输出 schema 由 `AlgorithmMetadata` 在运行期声明。

### 4.2 消息总览 (Communication Diagram)

```
        Python GUI / Service                    MATLAB Server
              │                                       │
              │── VERSION_NEGOTIATE ─────────────────▶│  (启动后先协商)
              │◀────────── VersionResult ─────────────│
              │                                       │
              │── LIST_ALGORITHMS ───────────────────▶│  (发现可用算法)
              │◀────── AlgorithmMetadata[] ───────────│
              │                                       │
              │── AlgorithmRequest ──────────────────▶│  (调用)
              │◀──── ProgressUpdate* (流式) ──────────│  (可选)
              │◀──── AlgorithmResponse ───────────────│
              │                                       │
              │── Heartbeat (周期) ──────────────────▶│
              │◀────────── Pong ──────────────────────│
              │                                       │
              │── HealthCheck ────────────────────────▶│
              │◀────────── HealthStatus ──────────────│
              │                                       │
              │── Cancellation(req_id) ───────────────▶│  (取消)
              │◀──── AlgorithmResponse(cancelled) ────│
              │                                       │
              │── Shutdown ───────────────────────────▶│  (运维)
              │◀────────── ShutdownAck ────────────────│
```

### 4.3 消息定义（proto3 概要）

```protobuf
syntax = "proto3";
package csam.algorithm.v3;

// ====== 信封：所有请求/响应的传输外壳 ======
message Envelope {
  string  request_id    = 1;   // 全局唯一，UUID
  int64   timestamp_ms  = 2;   // UTC 毫秒
  string  message_type  = 3;   // "ALGORITHM_REQUEST" | "HEARTBEAT" | ...
  string  protocol_ver  = 4;   // "3.0"
  bytes   payload       = 5;   // 具体消息的序列化字节
}

// ====== 算法调用 ======
message AlgorithmRequest {
  string algorithm_name  = 1;  // "path_planning.generate_path"
  string algorithm_ver   = 2;  // "1.0.0" 或 "latest"
  int32  timeout_ms      = 3;  // 0=用算法默认
  bool   stream_progress = 4;
  map<string, Value> params   = 10;  // 自描述参数表
  map<string, Tensor> inputs  = 11;  // 大块数组（点云/网格）
  string client_version  = 20;
}

message AlgorithmResponse {
  enum Status { OK=0; ERR_INVALID=1; ERR_TIMEOUT=2;
                ERR_ALGORITHM=3; ERR_DEPS=4; CANCELLED=5; UNKNOWN=99; }
  Status status           = 1;
  string error_code       = 2;   // 细分错误码
  string error_message    = 3;
  int64  compute_time_ms  = 4;
  map<string, Value>  results   = 10;  // 标量/小数组结果
  map<string, Tensor> artifacts = 11;  // 大块数组（航点/网格）
  map<string, bytes>  assets    = 12;  // PNG/STL 等二进制资产
  string algorithm_ver   = 20;  // 实际执行的算法版本
}

// ====== 算法元数据（自描述） ======
message AlgorithmMetadata {
  string name             = 1;
  string version          = 2;
  string description      = 3;
  FieldSchema input_schema  = 4;   // 字段→类型/形状/单位/范围
  FieldSchema output_schema = 5;
  repeated string dependencies = 6; // ["Map_Toolbox"]
  int32  timeout_default_ms = 7;
  bool   streaming          = 8;
  repeated string tags      = 9;
}

// ====== 进度（流式） ======
message ProgressUpdate {
  string request_id   = 1;
  int32  stage_index  = 2;
  string stage_name   = 3;
  float  progress     = 4;   // [0,1]
  string message      = 5;
  map<string, Tensor> partial_artifacts = 6;  // 增量结果
}

// ====== 心跳与健康 ======
message Heartbeat { int64 client_ts_ms = 1; }
message Pong { int64 server_ts_ms = 1; int32 pending = 2; }

message HealthStatus {
  enum State { OK=0; DEGRADED=1; DOWN=2; }
  State state            = 1;
  string server_version  = 2;
  float  memory_mb       = 3;
  int64  uptime_s        = 4;
  int32  pending_reqs    = 5;
  map<string,bool> toolbox_available = 6;
  float  error_rate_1m   = 7;
}

// ====== 取消 ======
message Cancellation { string request_id = 1; string reason = 2; }

// ====== 版本协商 ======
message VersionNegotiate {
  string client_protocol = 1;
  string client_app      = 2;
  repeated string want_algorithms = 3;
}
message VersionResult {
  string server_protocol      = 1;
  string server_app           = 2;
  bool   protocol_compatible  = 3;
  repeated string available_algorithms = 4;
}

// ====== 通用值类型（参数表用） ======
message Value {
  oneof kind {
    double  num    = 1;
    int64   intval = 2;
    string  str    = 3;
    bool    flag   = 4;
    Tensor  tensor = 5;
  }
}
message Tensor {
  enum DType { F32=0; F64=1; I32=2; I64=3; U8=4; }
  DType dtype        = 1;
  repeated int32 shape = 2;   // 行主序
  bytes  data        = 3;     // 原始字节
  string units       = 4;     // "mm","m/s"...
}
message FieldSchema { map<string, FieldSpec> fields = 1; }
message FieldSpec {
  string type     = 1;   // "Value"|"Tensor"|"bytes"
  repeated int32 shape = 2;
  string units    = 3;
  string range    = 4;   // "[0,1]"
  bool   required = 5;
}
```

### 4.4 协议设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 消息封装 | `Envelope` + `payload` bytes | 信封稳定，负载可演进，向后兼容 |
| 参数传递 | `map<string,Value>` | 算法自描述 schema，协议层不感知业务字段 |
| 大数组 | `Tensor`（dtype+shape+raw bytes） | 比 SoA repeated float 更通用，支持任意类型/维度 |
| 算法发现 | `LIST_ALGORITHMS` + `AlgorithmMetadata` | 运行期动态发现，新增算法零协议改动 |
| 流式进度 | `ProgressUpdate` 带 `partial_artifacts` | 长任务可边算边返回，UX 友好 |
| 取消 | `Cancellation` + response `CANCELLED` | 协作式取消，服务端检测 token |
| 版本协商 | `VersionNegotiate` 启动期执行 | 客户端/服务端能力对齐，避免运行期失败 |
| ZMQ 模式 | **ROUTER/DEALER**（替代当前 REP/REQ） | 支持流式 ProgressUpdate、并发请求、取消；REP/REQ 严格锁步无法满足 |
| 序列化 | Protobuf（保持） | 跨语言、紧凑、有 schema 演进规则 |

> **与 v2.1 的关系**：v3.0 不立即废弃 v2.1。MATLAB Server 同时监听两个端口（或同端口按 `protocol_ver` 路由），过渡期 Python 侧用 `MatlabEngine(v3)` 与旧 `LegacyZmqClient(v2.1)` 并存，最后下线 v2.1。

---

## 5. Task 5 — 算法抽象层 `IAlgorithmEngine`

### 5.1 接口设计

```python
# repair_app/engine/abc.py  (概念，不写入仓库)
class IAlgorithmEngine(ABC):
    """统一算法引擎接口。GUI/Service 层只依赖此接口。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_algorithms(self) -> list[AlgorithmMetadata]: ...

    @abstractmethod
    def execute(
        self,
        algorithm_name: str,
        params: dict[str, Any],
        inputs: dict[str, np.ndarray] | None = None,
        *,
        version: str = "latest",
        timeout_ms: int | None = None,
        on_progress: Callable[[ProgressUpdate], None] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> AlgorithmResult: ...

    @abstractmethod
    def check_health(self) -> HealthStatus: ...

    @abstractmethod
    def shutdown(self) -> None: ...
```

### 5.2 实现矩阵

```
                    IAlgorithmEngine
                          ▲
        ┌─────────────────┼─────────────────┬──────────────┐
        │                 │                 │              │
   PythonEngine      MatlabEngine       CppEngine      RemoteEngine
  (LocalEngine重构)  (ZMQ→MATLAB Server) (未来SWIG)   (未来HTTP/gRPC)
        │                 │
        │                 └─engine/matlab/zmq_channel.py
        │                   engine/matlab/protocol_v3/
        │                   engine/matlab/lifecycle.py
        │
        └─core/path_planner.py
          core/morphology_predictor.py
```

### 5.3 引擎选择策略

业务层不直接 new 引擎，而是通过 `EngineFactory`：

```
EngineFactory.create(preference=["matlab","python"]) ->
    1. 尝试 MatlabEngine（探测健康检查，超时 2s）
    2. 成功 → 返回 MatlabEngine
    3. 失败且允许降级 → 返回 PythonEngine + 记录降级告警
    4. 不允许降级 → 抛 EngineUnavailableError
```

**关键不变量**：`PathPlanningService` 代码里只有 `self.engine.execute("path_planning.generate_path", params, inputs)`，它永远不知道是 Python 还是 MATLAB 在算。

### 5.4 算法命名空间规约

```
path_planning.*         路径规划族
morphology.*            形貌预测族
calibration.*           标定族（未来）
material.*              材料库（未来）
export.*                导出族（gcode/rapid）
workflow.*              编排族（组合多个原子算法）
```

---

## 6. Task 6 — MATLAB 生命周期管理

### 6.1 生命周期状态机

```
        ┌──────────┐  start()   ┌──────────┐  READY信号  ┌──────────┐
        │  STOPPED │───────────▶│ STARTING │────────────▶│  READY   │
        └──────────┘            └────┬─────┘             └────┬─────┘
             ▲                       │ 超时/崩溃              │ execute()
             │ shutdown()            ▼                        ▼
        ┌────┴──────┐          ┌──────────┐            ┌──────────┐
        │  STOPPING │◀─────────│  FAILED  │            │  BUSY    │
        └───────────┘ shutdown │ (可恢复) │            └────┬─────┘
             │                 └──────────┘                 │ 完成
             │                       │ 重连退避               │
             │                       └─ RECONNECTING ────────┘
             ▼
        ┌──────────┐
        │  DEAD    │  (不可恢复，需人工)
        └──────────┘
```

### 6.2 关键机制

| 场景 | 机制 |
|---|---|
| **启动** | 进程拉起 → 等待 READY 信号（带总超时 60s）→ 版本协商 → 健康检查通过才标记 READY |
| **关闭** | 发 `SHUTDOWN` → 服务端 graceful drain（默认 10s）→ 超时则 SIGTERM → 再超时 SIGKILL → 清理 socket/context |
| **崩溃恢复** | 心跳连续丢失 N 次（默认 3）判定崩溃 → 进入 RECONNECTING → 指数退避重试（1s,2s,4s,...,30s 上限）→ 成功则恢复，失败达上限进 DEAD |
| **重连** | 退避重试 + 断路器（半开探测）；重连成功后自动 `VERSION_NEGOTIATE` + `LIST_ALGORITHMS` 刷新缓存 |
| **资源清理** | 服务端：每请求后 `clear` 局部变量，每 50 请求 `pack` 内存；客户端：请求结束释放 bytes |
| **超时** | 三层：①传输 poll ②请求级 `timeout_ms` ③算法级 timer；任一触发发 `Cancellation` 并返回 `ERR_TIMEOUT` |
| **未预期异常** | 服务端 dispatcher 全包 try/catch → 返回 `ERR_ALGORITHM` + 堆栈；服务进程不退出；连续错误率超阈值触发自动重启 |
| **内存清理** | 监控 `memory()`，超阈值（默认 2GB）触发 `pack`，仍超则重启进程（worker recycle） |
| **Worker 复用** | MATLAB 会话长驻；算法无状态执行（禁用 `clear all`，改用局部函数作用域）；多请求复用同一会话避免冷启动 |
| **请求幂等** | `AlgorithmDescriptor.idempotent=true` 的算法可安全自动重试（如纯计算类）；有副作用的（如文件导出）不重试 |

### 6.3 客户端侧生命周期守护

```
MatlabEngine 内部:
  - LifecycleSupervisor(QThread): 监听 HeartbeatMonitor 信号
  - engine_lost → 触发 RECONNECTING 流程
  - 重连成功 → emit engine_recovered
  - 重连失败达上限 → emit engine_dead + 自动降级到 PythonEngine（若策略允许）
```

---

## 7. Task 7 — 部署架构

### 7.1 部署拓扑演进

**阶段 A — 单机（当前目标）**

```
┌─────────────── 单台工作站 ───────────────┐
│  Python GUI  ←tcp://127.0.0.1:5570→  MATLAB Server (本地进程)
│                                         (路径规划/* + 形貌预测/*)
└──────────────────────────────────────────┘
```

**阶段 B — 远程执行（未来，零业务改动）**

```
┌──── 操作员 PC ────┐        ┌──── 算法工作站 ────┐
│  Python GUI       │ tcp:// │  MATLAB Server     │
│  RemoteEngine     │────────│  (GPU/大内存)      │
└───────────────────┘        └────────────────────┘
```
切换方式：仅改配置 `CSAM_ENGINE_ENDPOINT=tcp://algo-ws:5570`，业务代码不变。

**阶段 C — 分布式（未来）**

```
                    ┌─────────────────┐
                    │  Engine Router  │  ← 按算法路由 / 负载均衡
                    └────────┬────────┘
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ MATLAB#1 │   │ MATLAB#2 │   │ MATLAB#3 │
        │ (路径规划)│   │ (形貌预测)│   │ (备用)   │
        └──────────┘   └──────────┘   └──────────┘
```

**阶段 D — 云端（未来）**

```
MATLAB Production Server 容器化 / MATLAB as a Service
RemoteEngine 改用 HTTP/gRPC 适配，IAlgorithmEngine 接口不变
```

### 7.2 可部署性设计要点

1. **端点可配置**：所有连接地址走环境变量/配置文件，无硬编码。
2. **引擎无状态假设**：业务层不假设引擎本地有文件，大块数据走 `Tensor`/`assets` 在线传输（阶段 B 起 STL/点云不落盘共享）。
3. **能力探测**：启动期 `VERSION_NEGOTIATE` + `LIST_ALGORITHMS`，客户端据此决定可用功能集，远程缺算法时优雅禁用对应 UI。
4. **健康门控**：Service 层调用前先 `check_health()`，降级/熔断由统一中间件处理。

---

## 8. Task 8 — 实施路线图（增量里程碑）

> 原则：每个里程碑独立可交付、可验证、可回滚。不写生产代码于本设计阶段。

### M1 — 协议 v3.0 定义与代码生成
- **目标**：定稿 `algorithm_protocol_v3.proto`，Python/MATLAB 双端生成桩代码。
- **涉及文件（新增）**：`repair_app/engine/protocol_v3/algorithm_protocol_v3.proto`、生成产物。
- **依赖**：无。
- **风险**：低。纯协议设计，不影响现有功能。
- **验证**：proto 编译通过；单元测试序列化/反序列化往返。
- **回滚**：删除新文件，v2.1 继续运行。

### M2 — `IAlgorithmEngine` 抽象与 PythonEngine 重构
- **目标**：抽出 `IAlgorithmEngine`，把现有 `LocalEngine` 重构为符合新接口的 `PythonEngine`，保留旧接口为兼容包装。
- **涉及文件**：`engine/abc.py`、`engine/python_engine.py`、`engine/local_engine.py`（兼容层）。
- **依赖**：M1。
- **风险**：中。触及现有引擎，需保证 219 旧测试全绿。
- **验证**：全部现有测试 + 新引擎抽象测试通过。
- **回滚**：恢复 `LocalEngine` 原状。

### M3 — MATLAB Server 核心骨架
- **目标**：实现 startup/registry/dispatcher/heartbeat/health/shutdown，注册 1 个冒烟算法（如 `morphology.ray_triangle_intersection`，无工具箱依赖）。
- **涉及文件（新增）**：`matlab_server/startup.m`、`registry.m`、`dispatcher.m`、`lifecycle.m`、`register_algorithms.m`、`config.m`、`logger.m`。
- **依赖**：M1。
- **风险**：中。首次建立真实 MATLAB 服务器，需验证 ZMQ+Protobuf 在 MATLAB 侧可行。
- **验证**：Python 客户端能协商版本、列出算法、调用冒烟算法、收到正确结果、心跳/健康正常。
- **回滚**：停止 MATLAB Server，回退到 PythonEngine。

### M4 — 算法包装（13 个 MATLAB 函数）
- **目标**：将 13 个适用函数注册为 API，包括函数化 `main.m`（参数 struct 化），修复 `point_interpretaion.m` bug。
- **涉及文件**：`matlab_server/wrappers/*.m`、`register_algorithms.m`（追加注册）、`路径规划/`与`形貌预测/`内 bug 修复。
- **依赖**：M3。
- **风险**：中高。需处理工具箱依赖、参数 schema、大数组传输；`main.m` 脚本函数化。
- **验证**：每个算法一个黄金样本用例（输入→期望输出对比）；`LIST_ALGORITHMS` 返回全部 13 个。
- **回滚**：逐算法回滚注册，不影响已注册算法。

### M5 — `MatlabEngine` 客户端
- **目标**：实现 `MatlabEngine(IAlgorithmEngine)`，含 ZMQ ROUTER/DEALER 通道、ProgressUpdate 流、Cancellation。
- **涉及文件**：`engine/matlab/zmq_channel.py`、`engine/matlab/matlab_engine.py`、`engine/matlab/protocol_v3/`。
- **依赖**：M1、M3。
- **风险**：中。异步流式 + 取消语义复杂。
- **验证**：集成测试：PythonEngine 与 MatlabEngine 对相同算法输出一致（数值容差内）。
- **回滚**：`EngineFactory` 回退 PythonEngine。

### M6 — 生命周期管理
- **目标**：实现 LifecycleSupervisor、心跳、崩溃恢复、重连退避、自动降级、内存监控重启。
- **涉及文件**：`engine/matlab/lifecycle.py`、`engine/matlab/heartbeat.py`、`engine/matlab/circuit_breaker.py`。
- **依赖**：M5。
- **风险**：中高。并发/时序问题、恢复正确性。
- **验证**：故障注入测试（kill MATLAB 进程、网络断开、超时）→ 自动恢复或优雅降级。
- **回滚**：关闭自动恢复，改为手动重启策略。

### M7 — 业务层与 MainWindow 集成
- **目标**：引入 `PathPlanningService`/`MorphologyService`，通过 `EngineFactory` 调用；MainWindow 改为消费 Service，下线对 `core/*` 的直接依赖；集成进度流到 UI。
- **涉及文件**：`services/*.py`、`ui/main_window.py`（重构调用点，不动 UI 布局）。
- **依赖**：M2、M5、M6。
- **风险**：高。触及 God Class，需小步重构。
- **验证**：22 项 GUI 自动化测试 + 全量回归；MATLAB 在线/离线两种场景。
- **回滚**：MainWindow 保留双路径（feature flag 切换新旧调用）。

### M8 — 旧通信层与 bridge 收敛
- **目标**：下线旧 `communication/` 与 `bridge/`（v2.1），统一到 v3.0 通道；删除 dead code（`controller/`、`ui/panels/`）。
- **依赖**：M7 稳定运行。
- **风险**：中。删除代码需确认无引用。
- **验证**：grep 无残留引用；测试覆盖率不降。
- **回滚**：从 M7 提交点恢复。

### M9 — 远程部署支持
- **目标**：验证跨机部署；`RemoteEngine` 与 `MatlabEngine` 共用抽象；配置化端点；能力探测驱动 UI 降级。
- **依赖**：M7。
- **风险**：中。网络可靠性、大文件传输。
- **验证**：跨机集成测试。
- **回滚**：配置改回 127.0.0.1。

---

## 9. 风险评估 (Risk Assessment)

| 风险 | 等级 | 影响 | 缓解 |
|---|---|---|---|
| MATLAB ZMQ/Protobuf 绑定不稳定 | 高 | Server 无法运行 | M3 冒烟算法先行验证；保留 Python 原型引擎作降级 |
| 工具箱许可证在部署机缺失 | 中 | 部分算法不可用 | 启动期探测 + `AlgorithmMetadata.dependencies` + UI 降级 |
| MATLAB 单会话内存累积 | 中 | 长跑后 OOM | 周期 `pack` + 内存阈值重启 + 无状态化 |
| `main.m` 脚本 `clear all` 破坏长驻会话 | 高 | 会话状态丢失 | M4 函数化包装，禁止 `clear all`，改局部作用域 |
| 数值一致性 Python vs MATLAB | 中 | 引擎切换结果不一致 | M5 黄金样本对比 + 容差断言 |
| MainWindow 重构破坏 UI | 高 | 回归 | M7 feature flag 双路径 + 22 项 GUI 自动化 |
| 协议演进破坏兼容 | 中 | 客户端/服务端失配 | Envelope+payload 设计 + 版本协商 + 过渡期 v2.1/v3.0 并存 |
| 远程网络抖动 | 中 | 请求失败 | 超时 + 重试（幂等算法）+ 断路器 + 降级 |
| 取消语义竞态 | 中 | 资源泄漏 | 协作式 cancel token + 服务端资源清理兜底 |

---

## 10. 关键技术决策 (Technical Decisions)

1. **MATLAB Server 独立进程，而非 pyenv 反向调用** — 真正的服务化，支持远程/多实例/独立部署，脱离 Python 宿主。
2. **ROUTER/DEALER 替代 REP/REQ** — 支持流式进度、并发、取消；当前 bridge 的 REP/REQ 锁步模型无法满足工业长任务。
3. **通用 `AlgorithmRequest` 替代 `RepairRequest`** — 协议与业务解耦，新增算法零协议改动，靠 `AlgorithmMetadata` 自描述。
4. **`IAlgorithmEngine` 作为唯一引擎抽象** — GUI/Service 永不感知后端，Python/MATLAB/C++/Remote 可互换。
5. **声明式算法注册表** — 新增算法只改注册文件，分发器/协议/客户端不动。
6. **优雅降级优先** — MATLAB 不可用时回退 Python 引擎（受控），保证可用性。
7. **MATLAB 会话无状态化 + 长驻复用** — 兼顾性能（避免冷启动）与稳定性（无状态可重启）。
8. **版本协商 + 双协议过渡期** — v3.0 与 v2.1 并存，平滑迁移，最后下线旧协议。
9. **端点全配置化** — 单机→远程→分布式→云，业务零改动。
10. **不重写 UI，只重构调用点** — MainWindow 改为消费 Service，保留现有布局，降低回归风险。

---

## 11. 结论

本设计将 MATLAB 从"Python 宿主的附属子进程"重构为**独立长驻的工业算法服务器**，并以**通用协议 v3.0 + `IAlgorithmEngine` 抽象**解除业务层与具体算法/引擎的耦合。GUI 将只作为应用层，MATLAB 成为唯一的算法层（当可用时）。9 个增量里程碑保证每步可独立交付、验证、回滚，整体风险可控。下一步建议从 **M1（协议 v3.0）** 启动。

---

## 附录 A — 算法生命周期时序图（文本）

```
GUI                 Service            EngineFactory       MatlabEngine          ZMQ Channel         MATLAB Server        Algorithm fn
 │                     │                    │                    │                     │                      │                     │
 │ user_click_plan     │                    │                    │                     │                      │                     │
 ├────────────────────▶│                    │                    │                     │                      │                     │
 │                     │ create(["matlab"]) │                    │                     │                      │                     │
 │                     ├───────────────────▶│                    │                     │                      │                     │
 │                     │                    │ health_check(2s)   │                     │                      │                     │
 │                     │                    ├───────────────────▶│ VERSION_NEGOTIATE ──────────────────────────▶│                     │
 │                     │                    │                    │◀──────────── VersionResult ────────────────│                     │
 │                     │                    │                    │ LIST_ALGORITHMS ────────────────────────────▶│                     │
 │                     │                    │                    │◀──────── AlgorithmMetadata[] ──────────────│                     │
 │                     │                    │ MatlabEngine ready │                     │                      │                     │
 │                     │◀───────────────────┤                    │                     │                      │                     │
 │                     │ execute("path_planning.generate_path", params, inputs)         │                      │                     │
 │                     ├────────────────────────────────────────▶│                     │                      │                     │
 │                     │                    │                    │ AlgorithmRequest ──────────────────────────▶│ lookup+validate     │
 │                     │                    │                    │                     │                      ├────────────────────▶│
 │                     │                    │                    │◀──── ProgressUpdate (stage=1, 0.2) ─────────│                     │
 │                     │◀───────────────────┤                    │                     │                      │                     │
 │ progress 20%        │                    │                    │                     │                      │                     │
 │◀────────────────────┤                    │                    │                     │                      │                     │
 │                     │                    │                    │◀──── ProgressUpdate (stage=1, 0.8) ─────────│                     │
 │                     │                    │                    │◀──── AlgorithmResponse (OK, artifacts) ─────│                     │
 │                     │◀───────────────────┤                    │                     │                      │                     │
 │ render result       │                    │                    │                     │                      │                     │
 │◀────────────────────┤                    │                    │                     │                      │                     │
```

## 附录 B — 术语表

| 术语 | 含义 |
|---|---|
| CSAM | Cold Spray Additive Manufacturing，冷喷涂增材制造 |
| IAlgorithmEngine | 算法引擎统一抽象接口（v3.0 新增） |
| MATLAB Server | 独立长驻的 MATLAB 算法服务进程（v3.0 新增） |
| AlgorithmDescriptor | 算法注册表中的声明式描述项 |
| Envelope | v3.0 协议的传输信封，封装所有消息 |
| Tensor | v3.0 协议的通用多维数组类型 |
| AlgorithmMetadata | 算法自描述元数据，供运行期发现 |
| LifecycleSupervisor | 客户端侧 MATLAB 生命周期守护线程 |
| EngineFactory | 引擎选择工厂，支持偏好与降级策略 |
| CancelToken | 协作式取消令牌，用于中断长任务 |
