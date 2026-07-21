# API 接口

> 版本：1.0.0 (Release Candidate) | 协议版本：v2.1 | 更新日期：2026-07-14 | 文档语言：简体中文

本文档说明 CSAM Repair 所有公开接口，包括领域模型、引擎接口、MatlabAdapter、MatlabEngineProxy、BridgeServer、BridgeClient、LegacyZmqClient、Service 层、异常层次与环境变量参考。

---

## 目录

- [1. 概述](#1-概述)
- [2. 领域模型](#2-领域模型)
- [3. IEngine 接口](#3-iengine-接口)
- [4. MatlabAdapter](#4-matlabadapter)
- [5. MatlabEngineProxy](#5-matlabengineproxy)
- [6. BridgeServer](#6-bridgeserver)
- [7. BridgeClient](#7-bridgeclient)
- [8. LegacyZmqClient](#8-legacyzmqclient)
- [9. Service 层](#9-service-层)
- [10. 异常层次](#10-异常层次)
- [11. 环境变量参考](#11-环境变量参考)

---

## 1. 概述

本文档覆盖以下公开接口：

- **领域模型**：`PointCloud`、`DefectRegion`、`ProcessParams`、`RepairRequest`、`RepairResult`
- **引擎接口**：`IEngine`（仅 `LocalEngine` 实现，降级用）
- **MATLAB 适配器**：`MatlabAdapter`（`BridgeServer` 子类）、`MatlabEngineProxy`（单例）
- **通信层**：`BridgeServer`（REP 端）、`BridgeClient`（REQ 端）、`LegacyZmqClient`（UI 适配器）
- **服务层**：`CoordinationService`、`FileService`、`ExportService`
- **异常层次**：`BridgeError` 及子类
- **配置**：`BridgeConfig` 与环境变量

> MATLAB 算法通过 `MatlabAdapter` 走 Bridge 通信路径，不实现 `IEngine` 接口。`IEngine` 仅由 `LocalEngine` 实现（降级用）。

---

## 2. 领域模型

- **源文件**：`repair_app/domain/models.py`
- **角色**：核心数据结构与值对象，替代分散的字典

### 2.1 PointCloud（点云）

| 字段 | 类型 | 说明 |
|------|------|------|
| `xyz` | `np.ndarray` (N,3) | 点云坐标 |
| `normals` | `np.ndarray` (N,3) | 点云法向量 |
| `colors` | `np.ndarray` (N,3)，可选 | 点云颜色 |

### 2.2 DefectRegion（缺陷区域）

| 字段 | 类型 | 说明 |
|------|------|------|
| `indices` | `np.ndarray` | 缺陷点索引 |
| `bbox` | `tuple` | 包围盒 |

### 2.3 ProcessParams（工艺参数）

| 字段 | 类型 | 说明 |
|------|------|------|
| `material` | `str` | 材料类型（如 `STEEL_316L`） |
| `particle_velocity_ms` | `float` | 粒子速度（m/s） |
| `gas_temperature_c` | `float` | 气体温度（℃） |
| `tilt_angle_deg` | `float` | 倾角（度） |
| `...` | `...` | 其余工艺参数（共 21 项，详见 `utils/config.py` 的 `PARAM_SPECS`） |

### 2.4 RepairRequest（修复请求）

Protobuf 消息，定义于 `repair_protocol.proto`：

| 字段 | 类型 | 说明 |
|------|------|------|
| 点云坐标 | `repeated float x/y/z` | SoA 布局 |
| 法向量 | `repeated float nx/ny/nz` | 点云法向量 |
| 工艺参数 | `ProcessParams` | 材料类型、粒子速度、气体温度、倾角等 |
| 材料类型 | `MaterialType` 枚举 | 材料标识 |
| 请求 ID | `string` | 全链路追踪 |

### 2.5 RepairResult（修复结果）

Protobuf 消息，定义于 `repair_protocol.proto`：

| 字段 | 类型 | 说明 |
|------|------|------|
| 航点 | `repeated Waypoint` | AoS 布局 |
| 状态码 | `int32` | 见状态码表 |
| 错误信息 | `string` | 失败时的可读描述 |
| `compute_time_ms` | `float` | 算法真实计算耗时 |
| `estimated_time_s` | `float` | 基于路径长度与速度计算 |
| `uniformity_score` | `float` | 路径均匀性指标 |
| `is_feasible` | `bool` | 修复可行性结论 |
| `feasibility_reason` | `string` | 可行性结论说明 |

### 2.6 Waypoint（航点）

| 字段 | 类型 | 说明 |
|------|------|------|
| `x/y/z` | `float` | 航点空间坐标 |
| `nx/ny/nz` | `float` | 航点法向量 |
| `feed_rate` | `float` | 进给速度 |
| `layer_index` | `int32` | 所属层 |

---

## 3. IEngine 接口

- **源文件**：`repair_app/domain/interfaces.py`（第 64 行）
- **角色**：引擎抽象接口，当前仅 `LocalEngine` 实现此接口（降级用）。MATLAB 算法通过 `MatlabAdapter` 走 Bridge 通信路径，不实现此接口。

### 3.1 方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `name -> str` | `str` | 引擎名 |
| `is_available -> bool` | `bool` | 引擎是否可用 |
| `plan_path(point_cloud, defect_region, params, is_additive=False) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 生成修复路径（流式） |
| `predict_morphology(point_cloud, defect_region, waypoints, params) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 预测形貌（流式） |
| `check_health() -> bool` | `bool` | 健康检查 |

### 3.2 LocalEngine

- **源文件**：`repair_app/engine/local_engine.py`
- **角色**：`IEngine` 唯一实现，封装 `core/` 中的 Python 原型算法（`PathPlanner`、`MorphologyPredictor`），用于 MATLAB 不可用时的降级

---

## 4. MatlabAdapter

- **源文件**：`repair_app/bridge/adapters/matlab_adapter.py`
- **类**：`MatlabAdapter(BridgeServer)`
- **角色**：`BridgeServer` 子类，处理修复请求，调用 MATLAB 算法或降级到 Python。运行于 MATLAB 宿主进程内（通过 `pyenv` 调用 Python）。
- **服务版本**：`matlab-adapter-2.0.0`

### 4.1 关键方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `handle_repair(request: RepairRequest) -> RepairResult` | `RepairResult` | 处理修复请求，调用 MATLAB 算法或降级到 Python 原型 |

### 4.2 降级策略

`_invoke_with_fallback` 在 MATLAB 调用失败时自动切换到 `LocalEngine` 的 Python 原型算法，保证生产连续性。降级行为由 `CSAM_ALGORITHM_ENGINE` 环境变量控制：

| 值 | 行为 |
|-----|------|
| `auto` | 优先 MATLAB，不可用降级 Python（默认） |
| `matlab` | 强制使用 MATLAB，不可用报错 |
| `python` | 强制使用 Python 原型 |

### 4.3 降级流程

```text
MatlabAdapter.handle_repair(request)
    │
    ▼
_invoke_with_fallback()
    │
    ├── MATLAB 调用成功 → 返回 RepairResult
    │
    └── MATLAB 调用失败
            │
            ├── auto 模式 → 降级到 LocalEngine（Python 原型）
            │
            └── matlab 模式 → 抛出 MatlabAlgorithmError
```

### 4.4 异常

`MatlabAlgorithmError(Exception)`：表示 MATLAB 算法执行失败。定义于 `bridge/adapters/matlab_adapter.py`。

- 在 `matlab` 模式下，该异常会向上抛出
- 在 `auto` 模式下，触发降级到 `LocalEngine`

### 4.5 MATLAB 共享会话

`MatlabAdapter` 通过 `MatlabEngineProxy` 连接 MATLAB 共享引擎会话（`matlab.engine.connect_matlab('matlab_bridge')`），调用 `eng.run_path_planning()` / `eng.call_profile_prediction()` 等算法函数。

---

## 5. MatlabEngineProxy

- **源文件**：`repair_app/bridge/adapters/matlab_engine_proxy.py`
- **角色**：`matlab.engine` 单例封装，符合 `_algorithm_fn` 签名，供 `MatlabAdapter` 调用 MATLAB 算法函数

### 5.1 单例模式

`MatlabEngineProxy` 采用单例模式，确保整个进程共享一个 MATLAB 引擎连接，避免重复建立会话。

### 5.2 连接策略

按优先级依次尝试：

| 顺序 | 策略 | 说明 |
|------|------|------|
| 1 | 共享会话 | `matlab.engine.connect_matlab('matlab_bridge')` 连接已共享的 MATLAB 会话 |
| 2 | 默认共享会话 | 连接默认共享会话（无名称） |
| 3 | 独立启动 | 仅 `matlab` 模式下启动独立 MATLAB 引擎实例 |

### 5.3 关键方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `__call__(xyz, meta) -> waypoints` | `waypoints` | 路径规划算法调用（符合 `_algorithm_fn` 签名），内部调用 `eng.run_path_planning()` |
| `call_profile_prediction(xyz, meta) -> dict` | `dict` | 形貌预测算法调用，内部调用 `eng.call_profile_prediction()` |

### 5.4 共享会话管理

`MatlabEngineProxy` 依赖 MATLAB 侧通过 `matlab.engine.shareEngine('matlab_bridge')` 共享的会话。`matlab_bridge_server.m` 启动时自动执行共享。共享会话名称由环境变量 `CSAM_MATLAB_SHARED_NAME` 控制（默认 `matlab_bridge`）。

---

## 6. BridgeServer

- **源文件**：`repair_app/communication/zmq_server.py`
- **角色**：ZMQ REP 服务端基类，`MatlabAdapter` 继承此类

### 6.1 关键方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `start()` / `serve()` | — | 启动服务，创建 REP socket + bind，阻塞 poll 循环（200ms 可中断） |
| `handle_request(request)` | — | 由子类 `MatlabAdapter` 实现 `handle_repair`，处理修复请求 |
| `stop()` | — | 优雅关闭，200ms 内退出 |

### 6.2 职责

| 职责 | 实现位置 |
|------|----------|
| 初始化 ZMQ | `BridgeServer.serve()` — 创建 REP socket + bind |
| 接收请求 | `BridgeServer._dispatch()` — 消息分发 |
| 参数校验 | `MatlabAdapter.handle_repair()` — 空点云检测 |
| 算法调用 | `MatlabAdapter._invoke_with_fallback()` — 可注入算法函数 |
| 异常捕获 | `BridgeServer._dispatch()` — try/except 包裹 |
| 结构化响应 | `Serializer.build_repair_result()` — 统一结果格式 |
| 优雅关闭 | `BridgeServer.stop()` + poll 循环 — 200ms 内退出 |

---

## 7. BridgeClient

- **源文件**：`repair_app/bridge/communication/zmq_client.py`（第 148 行）
- **角色**：bridge 通信层 ZMQ 客户端，被 `LegacyZmqClient` 持有与委托

### 7.1 构造

| 签名 | 说明 |
|------|------|
| `__init__(config: Optional[BridgeConfig] = None)` | 以 `BridgeConfig` 构造，默认读取环境变量 |

### 7.2 属性

| 签名 | 返回 | 说明 |
|------|------|------|
| `is_connected -> bool` | `bool` | 是否已连接 |
| `zmq_available -> bool` | `bool` | ZMQ 是否可用 |
| `config -> BridgeConfig` | `BridgeConfig` | 当前配置 |
| `address -> str` | `str` | 连接地址 |

### 7.3 方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `request_repair(request, on_result, on_error: Optional[Callable[[BridgeError], None]] = None) -> str` | `str`（`request_id`） | 异步发起请求，返回请求 ID 用于跟踪/取消 |
| `send_request(...)` | — | 底层请求发送（由 `request_repair` 封装） |
| `check_health(on_health)` | — | 异步健康检查 |
| `start_heartbeat()` | — | 启动心跳 |
| `stop_heartbeat()` | — | 停止心跳 |
| `close(wait_ms: int = 4000)` | — | 关闭连接 |

### 7.4 配置参数

`BridgeClient` 的行为由 `BridgeConfig` 控制（详见 [11. 环境变量参考](#11-环境变量参考)）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `request_timeout_ms` | 30000 | 请求超时（毫秒） |
| `connect_timeout_ms` | 5000 | 连接超时 |
| `max_retries` | 3 | 最大重试次数 |
| `retry_interval_ms` | 2000 | 重试间隔 |
| `poll_interval_ms` | 200 | 协作式中断 poll 间隔 |

### 7.5 已知问题

`zmq_client.py` 第 279 行附近存在异常类型丢失问题，底层异常未被翻译为结构化 `BridgeError`。

---

## 8. LegacyZmqClient

- **源文件**：`repair_app/bridge/adapters/legacy_adapter.py`（第 25 行）
- **角色**：bridge 适配器，封装旧版 ZMQ 协议，由 `CoordinationService.create_zmq_client()` 优先返回。API 与旧版 `ZmqRepairClient` 完全兼容，保证调用方零改动迁移。

### 8.1 构造

| 签名 | 说明 |
|------|------|
| `__init__(address: Optional[str] = None, timeout_ms: int = 30000)` | 构造客户端，默认地址与超时由配置决定 |

### 8.2 属性

| 签名 | 返回 | 说明 |
|------|------|------|
| `is_connected -> bool` | `bool` | 是否已连接 |
| `zmq_available -> bool` | `bool` | ZMQ 是否可用 |

### 8.3 方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `request_repair(request: RepairRequest, on_result: Callable[[RepairResult], None], on_error: Optional[Callable[[str], None]] = None) -> None` | `None` | 异步发起修复请求，结果通过回调返回 |
| `check_health(on_health: Callable[[bool, str], None]) -> None` | `None` | 异步健康检查 |
| `close(wait_ms: int = 4000) -> None` | `None` | 关闭连接 |
| `start_heartbeat()` | — | 启动心跳 |
| `stop_heartbeat()` | — | 停止心跳 |

---

## 9. Service 层

### 9.1 CoordinationService

- **源文件**：`repair_app/service/coordination_service.py`（第 50 行）
- **角色**：静态中介服务，UI 层唯一入口。所有方法为 `@staticmethod`。
- **约束**：UI 层不得直接调用 `core/` 或 `communication/` 模块，必须通过本服务访问。

#### 属性 / 能力查询

| 签名 | 返回 | 说明 |
|------|------|------|
| `zmq_available -> bool` | `bool` | bridge 适配器或旧版 `ZmqRepairClient` 任一可用即为 `True` |
| `bridge_active -> bool` | `bool` | bridge 适配器是否为当前生产路径 |
| `proto_material_map -> dict` | `dict` | 材料名 → protobuf 枚举（`MaterialType`） |

#### 样本与法向量

| 签名 | 返回 | 说明 |
|------|------|------|
| `generate_sample_defect(defect_types: list[str], seed: int = 42, n_points: int = 8000) -> tuple` | `tuple` | 生成缺陷样本点云 |
| `estimate_normals(xyz: np.ndarray, k: int = 30) -> np.ndarray` | `np.ndarray` | 估计点云法向量 |

#### 可行性与材料

| 签名 | 返回 | 说明 |
|------|------|------|
| `create_feasibility_checker(material=None) -> FeasibilityChecker` | `FeasibilityChecker` | 创建可行性检查器 |
| `get_material_database() -> MaterialDatabase` | `MaterialDatabase` | 获取材料数据库 |

#### 修复请求构造与解析

| 签名 | 返回 | 说明 |
|------|------|------|
| `build_repair_request(xyz: np.ndarray, normals: np.ndarray, **kwargs) -> RepairRequest` | `RepairRequest` | 构造修复请求 |
| `parse_repair_result(result_bytes: bytes) -> dict` | `dict` | 解析修复结果字节为字典 |
| `is_repair_success(result: dict) -> bool` | `bool` | 判断修复结果是否成功 |

#### 客户端创建

| 签名 | 返回 | 说明 |
|------|------|------|
| `create_zmq_client() -> Optional[LegacyZmqClient \| ZmqRepairClient]` | 客户端或 `None` | 优先返回 bridge 适配器 `LegacyZmqClient`，不可用时回退旧版 `ZmqRepairClient`，均不可用返回 `None` |

### 9.2 FileService

- **源文件**：`repair_app/service/file_service.py`
- **角色**：文件 I/O 服务，负责点云加载（CSV/TXT/XYZ）与路径点持久化

### 9.3 ExportService

- **源文件**：`repair_app/service/export_service.py`
- **角色**：导出编排服务，协调 G-code、机器人指令、PDF 报告导出

### 9.4 ValidationService

- **源文件**：`repair_app/service/validation_service.py`
- **角色**：参数与数据校验服务

### 9.5 MatlabService（门面，未接入 GUI）

- **源文件**：`repair_app/bridge/services/matlab_service.py`（第 87 行）
- **角色**：bridge 服务门面，简化 MATLAB 引擎调用

> ⚠️ **注意**：GUI 当前**未使用**此门面。生产路径仍为 `CoordinationService → LegacyZmqClient`。

#### 构造

| 签名 | 说明 |
|------|------|
| `__init__(config=None, client=None)` | 以配置与可选客户端构造 |

#### 方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `check_health(on_health)` | — | 异步健康检查 |
| `start_heartbeat()` / `stop_heartbeat()` | — | 心跳控制 |
| `request_path_planning(xyz, normals, params: dict, on_success, on_error=None, scan_id="BRIDGE") -> str` | `str`（`request_id`） | 请求路径规划 |
| `close(wait_ms: int = 4000)` | — | 关闭 |

#### 硬编码默认参数

`request_path_planning` 内置 **21 个硬编码默认参数**，当 `params` 未提供时使用。关键默认值：

| 参数 | 默认值 |
|------|--------|
| `material` | `STEEL_316L` |
| `particle_velocity_ms` | `700.0` |
| `gas_temperature_c` | `500.0` |
| `tilt_angle_deg` | `0.0` |
| ……（共 21 项） | …… |

> 其余 17 项默认值见源文件 `matlab_service.py`。

---

## 10. 异常层次

- **源文件**：`repair_app/bridge/communication/exceptions.py`
- **原则**：所有通信层异常继承自 `BridgeError`，业务层只需捕获 `BridgeError`，永不接触原始 ZMQ/Protobuf 异常。

### 10.1 类层次

```text
BridgeError(Exception)                 # 基类，含 request_id: str
├── ConnectionError(BridgeError)       # 连接失败/中断
│   ├── ConnectionTimeoutError         # 超时，含 timeout_ms: int
│   └── EngineUnavailableError         # MATLAB 引擎未启动/不可达
│       └── EngineCrashError           # 引擎处理中崩溃
├── SerializationError(BridgeError)    # 序列化/反序列化失败
├── InvalidParameterError(BridgeError) # 参数校验失败，含 parameter: str
├── AlgorithmError(BridgeError)        # 算法执行异常，含 algorithm: str
├── ProtocolError(BridgeError)         # 协议版本不兼容，含 expected_version/actual_version
└── ShutdownError(BridgeError)         # 通信层正在关闭/已关闭
```

### 10.2 关键字段

| 异常类 | 附加字段 |
|--------|----------|
| `BridgeError` | `request_id: str` |
| `ConnectionTimeoutError` | `timeout_ms: int` |
| `InvalidParameterError` | `parameter: str` |
| `AlgorithmError` | `algorithm: str` |
| `ProtocolError` | `expected_version: str`、`actual_version: str` |

### 10.3 翻译函数

| 签名 | 返回 | 说明 |
|------|------|------|
| `translate_zmq_error(exc: Exception, request_id: str = "") -> BridgeError` | `BridgeError` | 将底层 ZMQ/Python 异常翻译为结构化 `BridgeError`，业务层永不接触原始异常 |

### 10.4 MATLAB 适配器异常

`MatlabAlgorithmError(Exception)`：定义于 `bridge/adapters/matlab_adapter.py`，表示 MATLAB 算法执行失败。在 `matlab` 模式下向上抛出；在 `auto` 模式下触发降级到 `LocalEngine`。

---

## 11. 环境变量参考

### 11.1 环境变量清单

以下为代码实际读取的 16 个环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_ZMQ_ADDRESS` | 平台默认 | ZMQ 地址（Windows: `tcp://127.0.0.1:5555`，POSIX: `ipc:///tmp/csam_engine`） |
| `CSAM_BRIDGE_TIMEOUT_MS` | 30000 | 请求超时（毫秒） |
| `CSAM_BRIDGE_CONNECT_MS` | 5000 | 连接超时 |
| `CSAM_BRIDGE_HEALTH_MS` | 3000 | 健康检查超时 |
| `CSAM_BRIDGE_HEARTBEAT_MS` | 5000 | 心跳间隔 |
| `CSAM_BRIDGE_HEARTBEAT_MISS` | 3 | 心跳丢失阈值 |
| `CSAM_BRIDGE_MAX_RETRIES` | 3 | 最大重试次数 |
| `CSAM_BRIDGE_RETRY_MS` | 2000 | 重试间隔 |
| `CSAM_BRIDGE_LATENCY_LOG_MS` | 1000 | 延迟告警阈值 |
| `CSAM_LOG_LEVEL` | INFO | 日志级别 |
| `CSAM_ALGORITHM_ENGINE` | auto | 算法引擎模式（auto / matlab / python） |
| `CSAM_MATLAB_SHARED_NAME` | matlab_bridge | MATLAB 共享会话名称 |
| `CSAM_MATLAB_ALLOW_STANDALONE` | — | 是否允许独立启动 MATLAB 引擎 |
| `CSAM_HMAC_SECRET` | — | HMAC 密钥（生产环境必须配置，不硬编码） |
| `CSAM_UPDATE_URL` | — | 自动更新检查 URL |
| `CSAM_UPDATE_TIMEOUT` | — | 自动更新超时 |

### 11.2 BridgeConfig 字段映射

`BridgeConfig`（`bridge/communication/config.py`，`@dataclass(frozen=True)`）字段与环境变量的对应关系：

| 字段 | 类型 | 默认值 | 对应环境变量 |
|------|------|--------|-------------|
| `address` | `str` | `get_zmq_address_from_env()` | `CSAM_ZMQ_ADDRESS` |
| `request_timeout_ms` | `int` | `30000` | `CSAM_BRIDGE_TIMEOUT_MS` |
| `connect_timeout_ms` | `int` | `5000` | `CSAM_BRIDGE_CONNECT_MS` |
| `health_check_timeout_ms` | `int` | `3000` | `CSAM_BRIDGE_HEALTH_MS` |
| `heartbeat_interval_ms` | `int` | `5000` | `CSAM_BRIDGE_HEARTBEAT_MS` |
| `heartbeat_miss_threshold` | `int` | `3` | `CSAM_BRIDGE_HEARTBEAT_MISS` |
| `max_retries` | `int` | `3` | `CSAM_BRIDGE_MAX_RETRIES` |
| `retry_interval_ms` | `int` | `2000` | `CSAM_BRIDGE_RETRY_MS` |
| `protocol_version` | `str` | `"2.1"` | — |
| `client_version` | `str` | `"bridge-1.0.0"` | — |
| `log_level` | `str` | `"INFO"` | `CSAM_LOG_LEVEL` |
| `log_latency_threshold_ms` | `int` | `1000` | `CSAM_BRIDGE_LATENCY_LOG_MS` |
| `poll_interval_ms` | `int` | `200` | 协作式中断 poll 间隔 |
| `large_array_warn_threshold` | `int` | `1000000` | 大数组告警阈值 |

### 11.3 BridgeConfig 方法

| 签名 | 返回 | 说明 |
|------|------|------|
| `from_env() -> BridgeConfig` | `BridgeConfig` | 从环境变量加载配置（类方法） |
| `request_timeout_s -> float`（property） | `float` | 超时秒数（便捷访问） |

### 11.4 配置示例

```python
from repair_app.bridge import BridgeConfig

# 从环境变量加载（推荐生产用法）
config = BridgeConfig.from_env()

# 自定义配置
config = BridgeConfig(
    address="tcp://192.168.1.100:5555",
    request_timeout_ms=60000,
    heartbeat_interval_ms=3000,
)
```

---

## 12. 状态码参考

定义于 `bridge/communication/protocol.py`：

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

## 13. 相关文档

| 主题 | 文档 |
|------|------|
| 系统架构与分层 | [软件架构.md](../架构设计/软件架构.md) |
| 通信协议与 Bridge 组件 | [通信协议.md](./通信协议.md) |
| 开发环境与模块职责 | [开发指南.md](../开发文档/开发指南.md) |
| 算法清单与工作流 | [算法说明.md](../MATLAB集成/算法说明.md) |

---

*本文档最后更新于 2026-07-14。*
