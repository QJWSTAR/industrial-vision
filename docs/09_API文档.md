# API 文档

> 本文档说明 CSAM 修复平台所有公开接口，包括 UI 层中介服务、通信客户端、引擎门面、引擎接口、工厂、异常层次、通信配置、MATLAB Server API，以及协议 v3.0 消息定义。
>
> 相关文档：
> - 算法清单与说明见 [04_工业算法说明.md](./04_工业算法说明.md)
> - 系统分层与调用流程见 [10_架构文档.md](./10_架构文档.md)
> - Bridge 架构设计见 [BRIDGE_ARCHITECTURE.md](./BRIDGE_ARCHITECTURE.md)

---

## 目录

- [1. CoordinationService](#1-coordinationservice)
- [2. LegacyZmqClient](#2-legacyzmqclient)
- [3. BridgeClient](#3-bridgeclient)
- [4. MatlabService（门面）](#4-matlabservice门面)
- [5. MatlabEngine](#5-matlabengine)
- [6. IEngine 接口](#6-iengine-接口)
- [7. EngineFactory](#7-enginefactory)
- [8. 异常类层次](#8-异常类层次)
- [9. BridgeConfig](#9-bridgeconfig)
- [10. MATLAB Server API](#10-matlab-server-api)
- [11. 协议 v3.0 消息](#11-协议-v30-消息)

---

## 1. CoordinationService

- **源文件**：`repair_app/service/coordination_service.py`（第 50 行）
- **角色**：静态中介服务，UI 层唯一入口。所有方法为 `@staticmethod`。
- **约束**：UI 层不得直接调用 `core/` 或 `communication/` 模块，必须通过本服务访问。

> 架构定位见 [10_架构文档.md - 系统架构图](./10_架构文档.md#系统架构图)。

### 1.1 属性 / 能力查询

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `zmq_available -> bool` | `bool` | bridge 适配器或旧版 `ZmqRepairClient` 任一可用即为 `True` |
| `bridge_active -> bool` | `bool` | bridge 适配器是否为当前生产路径 |
| `proto_material_map -> dict` | `dict` | 材料名 → protobuf 枚举（`MaterialType`） |

### 1.2 样本与法向量

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `generate_sample_defect(defect_types: list[str], seed: int = 42, n_points: int = 8000) -> tuple` | `tuple` | 生成缺陷样本点云 |
| `estimate_normals(xyz: np.ndarray, k: int = 30) -> np.ndarray` | `np.ndarray` | 估计点云法向量 |

### 1.3 可行性与材料

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `create_feasibility_checker(material=None) -> FeasibilityChecker` | `FeasibilityChecker` | 创建可行性检查器 |
| `get_material_database() -> MaterialDatabase` | `MaterialDatabase` | 获取材料数据库 |

### 1.4 修复请求构造与解析

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `build_repair_request(xyz: np.ndarray, normals: np.ndarray, **kwargs) -> RepairRequest` | `RepairRequest` | 构造修复请求 |
| `parse_repair_result(result_bytes: bytes) -> dict` | `dict` | 解析修复结果字节为字典 |
| `is_repair_success(result: dict) -> bool` | `bool` | 判断修复结果是否成功 |

### 1.5 客户端创建

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `create_zmq_client() -> Optional[LegacyZmqClient \| ZmqRepairClient]` | 客户端或 `None` | 优先返回 bridge 适配器 `LegacyZmqClient`，不可用时回退旧版 `ZmqRepairClient`，均不可用返回 `None` |

---

## 2. LegacyZmqClient

- **源文件**：`repair_app/bridge/adapters/legacy_adapter.py`（第 25 行）
- **角色**：bridge 适配器，封装旧版 ZMQ 协议，由 `CoordinationService.create_zmq_client()` 优先返回。

### 构造

| 签名 | 说明 |
| --- | --- |
| `__init__(address: Optional[str] = None, timeout_ms: int = 30000)` | 构造客户端，默认地址与超时由配置决定 |

### 属性

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `is_connected -> bool` | `bool` | 是否已连接 |
| `zmq_available -> bool` | `bool` | ZMQ 是否可用 |

### 方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `request_repair(request: RepairRequest, on_result: Callable[[RepairResult], None], on_error: Optional[Callable[[str], None]] = None) -> None` | `None` | 异步发起修复请求，结果通过回调返回 |
| `check_health(on_health: Callable[[bool, str], None]) -> None` | `None` | 异步健康检查 |
| `close(wait_ms: int = 4000) -> None` | `None` | 关闭连接 |
| `start_heartbeat()` | — | 启动心跳 |
| `stop_heartbeat()` | — | 停止心跳 |

---

## 3. BridgeClient

- **源文件**：`repair_app/bridge/communication/zmq_client.py`（第 148 行）
- **角色**：bridge 通信层 ZMQ 客户端，被 `LegacyZmqClient` 持有与委托。

### 构造

| 签名 | 说明 |
| --- | --- |
| `__init__(config: Optional[BridgeConfig] = None)` | 以 `BridgeConfig` 构造，默认读取环境变量 |

### 属性

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `is_connected -> bool` | `bool` | 是否已连接 |
| `zmq_available -> bool` | `bool` | ZMQ 是否可用 |
| `config -> BridgeConfig` | `BridgeConfig` | 当前配置 |
| `address -> str` | `str` | 连接地址 |

### 方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `request_repair(request, on_result, on_error: Optional[Callable[[BridgeError], None]] = None) -> str` | `str`（`request_id`） | 异步发起请求，返回请求 ID 用于跟踪/取消 |
| `check_health(on_health)` | — | 异步健康检查 |
| `start_heartbeat()` | — | 启动心跳 |
| `stop_heartbeat()` | — | 停止心跳 |
| `close(wait_ms: int = 4000)` | — | 关闭连接 |

> ⚠️ 已知问题：`zmq_client.py` 第 279 行附近存在异常类型丢失问题，底层异常未被翻译为结构化 `BridgeError`。详见 [10_架构文档.md - 已知架构问题](./10_架构文档.md#已知架构问题)。

---

## 4. MatlabService（门面）

- **源文件**：`repair_app/bridge/services/matlab_service.py`（第 87 行）
- **角色**：bridge 服务门面，简化 MATLAB 引擎调用。

> ⚠️ **注意**：GUI 当前**未使用**此门面。生产路径仍为 `CoordinationService → LegacyZmqClient`。详见 [10_架构文档.md - 已知架构问题](./10_架构文档.md#已知架构问题)。

### 构造

| 签名 | 说明 |
| --- | --- |
| `__init__(config=None, client=None)` | 以配置与可选客户端构造 |

### 属性

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `config -> BridgeConfig` | `BridgeConfig` | 当前配置 |
| `is_connected -> bool` | `bool` | 是否已连接 |
| `address -> str` | `str` | 连接地址 |

### 方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `check_health(on_health)` | — | 异步健康检查 |
| `start_heartbeat()` / `stop_heartbeat()` | — | 心跳控制 |
| `request_path_planning(xyz, normals, params: dict, on_success, on_error=None, scan_id="BRIDGE") -> str` | `str`（`request_id`） | 请求路径规划 |
| `close(wait_ms: int = 4000)` | — | 关闭 |

### 硬编码默认参数

`request_path_planning` 内置 **21 个硬编码默认参数**，当 `params` 未提供时使用。关键默认值：

| 参数 | 默认值 |
| --- | --- |
| `material` | `STEEL_316L` |
| `particle_velocity_ms` | `700.0` |
| `gas_temperature_c` | `500.0` |
| `tilt_angle_deg` | `0.0` |
| ……（共 21 项） | …… |

> 其余 17 项默认值见源文件 `matlab_service.py`。

---

## 5. MatlabEngine

- **源文件**：`repair_app/engine/matlab_engine.py`（第 279 行）
- **角色**：实现 `IEngine` 接口，通过 TCP v3.0 与 MATLAB Server 通信。

> ⚠️ **注意**：GUI 当前**未使用**此引擎（对应路径 B 处于设计阶段）。详见 [10_架构文档.md - 通信流程图](./10_架构文档.md#通信流程图)。

### 构造

| 签名 | 说明 |
| --- | --- |
| `__init__(host="", port=0, timeout_ms=30000, max_retries=3)` | `host` 默认取 `CSAM_MATLAB_HOST` 或 `127.0.0.1`；`port` 默认取 `CSAM_MATLAB_PORT` 或 `5570` |

### 属性

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `name -> str` | `"MATLAB Production Engine"` | 引擎名 |
| `is_available -> bool` | `bool` | 引擎是否可用 |

### 通用算法执行

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `execute(algorithm_name: str, params: dict, inputs: dict, timeout_ms: int = 60000, assets=None) -> AlgorithmResult` | `AlgorithmResult` | 执行任意已注册算法（v3.0 通用协议） |
| `list_algorithms() -> list[dict]` | `list[dict]` | 列出所有已注册算法 |
| `get_algorithm_metadata(name) -> Optional[dict]` | `Optional[dict]` | 查询单个算法元数据 |

### 健康与生命周期

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `check_health() -> bool` | `bool` | 健康检查（布尔） |
| `get_health_status() -> dict` | `dict` | 健康状态详情 |
| `heartbeat()` | — | 发送心跳 |
| `shutdown_server(reason="client", grace_ms=5000) -> dict` | `dict` | 关闭远端 Server |

### 业务方法（映射到 workflow）

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `plan_path(point_cloud, defect_region, params, is_additive=False) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 映射到 `workflow.path_planning` |
| `predict_morphology(point_cloud, defect_region, waypoints, params) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 映射到 `workflow.morphology_prediction` |
| `close()` | — | 关闭引擎 |

---

## 6. IEngine 接口

- **源文件**：`repair_app/domain/interfaces.py`（第 64 行）
- **角色**：引擎抽象接口，`MatlabEngine` 与 `LocalEngine` 均实现此接口。

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `name -> str` | `str` | 引擎名 |
| `is_available -> bool` | `bool` | 引擎是否可用 |
| `plan_path(point_cloud, defect_region, params, is_additive=False) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 生成修复路径（流式） |
| `predict_morphology(point_cloud, defect_region, waypoints, params) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 预测形貌（流式） |
| `check_health() -> bool` | `bool` | 健康检查 |

---

## 7. EngineFactory

- **源文件**：`repair_app/engine/factory.py`（第 37 行）
- **角色**：按偏好创建引擎实例。

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `create_engine(preference: str = "auto") -> IEngine` | `IEngine` | 按偏好创建引擎，可选值：`"auto"` / `"matlab"` / `"python"` |

`preference` 取值：

| 值 | 行为 |
| --- | --- |
| `"auto"` | 自动选择（优先 MATLAB，不可用回退 Python） |
| `"matlab"` | 强制使用 `MatlabEngine` |
| `"python"` | 强制使用 `LocalEngine`（Python 原型） |

---

## 8. 异常类层次

- **源文件**：`repair_app/bridge/communication/exceptions.py`
- **原则**：所有通信层异常继承自 `BridgeError`，业务层只需捕获 `BridgeError`，永不接触原始 ZMQ/Protobuf 异常。

### 8.1 类层次

```
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

### 8.2 关键字段

| 异常类 | 附加字段 |
| --- | --- |
| `BridgeError` | `request_id: str` |
| `ConnectionTimeoutError` | `timeout_ms: int` |
| `InvalidParameterError` | `parameter: str` |
| `AlgorithmError` | `algorithm: str` |
| `ProtocolError` | `expected_version: str`、`actual_version: str` |

### 8.3 翻译函数

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `translate_zmq_error(exc: Exception, request_id: str = "") -> BridgeError` | `BridgeError` | 将底层 ZMQ/Python 异常翻译为结构化 `BridgeError`，业务层永不接触原始异常 |

---

## 9. BridgeConfig

- **源文件**：`repair_app/bridge/communication/config.py`（第 31 行）
- **角色**：`@dataclass(frozen=True)` 不可变配置，所有通信参数集中于此，无硬编码值，支持环境变量覆盖。

### 9.1 字段

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `address` | `str` | `get_zmq_address_from_env()` | ZMQ 绑定/连接地址（读 `CSAM_ZMQ_ADDRESS`） |
| `request_timeout_ms` | `int` | `30000` | 请求超时（`CSAM_BRIDGE_TIMEOUT_MS`） |
| `connect_timeout_ms` | `int` | `5000` | 连接超时（`CSAM_BRIDGE_CONNECT_MS`） |
| `health_check_timeout_ms` | `int` | `3000` | 健康检查超时（`CSAM_BRIDGE_HEALTH_MS`） |
| `heartbeat_interval_ms` | `int` | `5000` | 心跳间隔（`CSAM_BRIDGE_HEARTBEAT_MS`） |
| `heartbeat_miss_threshold` | `int` | `3` | 心跳丢失阈值（`CSAM_BRIDGE_HEARTBEAT_MISS`） |
| `max_retries` | `int` | `3` | 最大重试次数（`CSAM_BRIDGE_MAX_RETRIES`） |
| `retry_interval_ms` | `int` | `2000` | 重试间隔（`CSAM_BRIDGE_RETRY_MS`） |
| `protocol_version` | `str` | `"2.1"` | 协议版本 |
| `client_version` | `str` | `"bridge-1.0.0"` | 客户端版本 |
| `log_level` | `str` | `"INFO"` | 日志级别（`CSAM_LOG_LEVEL`） |
| `log_latency_threshold_ms` | `int` | `1000` | 延迟告警阈值（`CSAM_BRIDGE_LATENCY_LOG_MS`） |
| `poll_interval_ms` | `int` | `200` | 协作式中断 poll 间隔 |
| `large_array_warn_threshold` | `int` | `1000000` | 大数组告警阈值 |

### 9.2 方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `from_env() -> BridgeConfig` | `BridgeConfig` | 从环境变量加载配置（类方法） |
| `request_timeout_s -> float`（property） | `float` | 超时秒数（便捷访问） |

---

## 10. MATLAB Server API

- **源目录**：`matlab_server/`
- **角色**：MATLAB 侧算法服务器，基于 `java.net.ServerSocket`（无 ZMQ 依赖）。

### 10.1 registry（注册表）

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `register(descriptor)` | — | 注册算法描述符 |
| `lookup(name, version) -> [desc, found]` | `[desc, found]` | 按名称与版本查找算法 |
| `list() -> cell` | `cell` | 列出全部已注册算法 |
| `list_metadata(category) -> struct 数组` | `struct 数组` | 按类别列出元数据 |
| `count() -> int` | `int` | 已注册算法数量 |

### 10.2 算法描述符字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | string | — | 算法全名（如 `path_planning.generate_path`） |
| `version` | string | — | 算法版本 |
| `fn_handle` | function_handle | — | 算法函数句柄 |
| `input_schema` | struct | — | 输入模式 |
| `output_schema` | struct | — | 输出模式 |
| `dependencies` | cell | — | 依赖工具箱列表（如 `{"Map_Toolbox"}`） |
| `timeout_ms` | int | `60000` | 默认超时 |
| `idempotent` | bool | `false` | 是否可安全重试 |
| `streaming` | bool | `false` | 是否支持流式进度 |
| `tags` | cell | — | 标签 |
| `description` | string | — | 人类可读描述 |
| `category` | string | `"general"` | 类别 |

### 10.3 dispatcher 消息类型

| 消息类型 | 说明 |
| --- | --- |
| `ALGORITHM_REQUEST` | 算法调用请求 |
| `HEARTBEAT` | 心跳 |
| `HEALTH_CHECK` | 健康检查 |
| `LIST_ALGORITHMS` | 列出算法 |
| `VERSION_NEGOTIATE` | 版本协商 |
| `CANCELLATION` | 取消请求 |
| `SHUTDOWN_REQUEST` | 关闭服务器 |

### 10.4 错误码

| 错误码 | 触发条件 |
| --- | --- |
| `UNKNOWN` | 未知错误 |
| `ERR_INVALID` | `bad_frame` / `json_decode` 解析失败 |
| `ERR_NOT_FOUND` | `algorithm_not_found` 算法未注册 |
| `ERR_DEPS` | `missing_toolbox` 依赖工具箱缺失 |
| `ERR_ALGORITHM` | `err.identifier` 算法内部异常 |

> 算法清单见 [04_工业算法说明.md](./04_工业算法说明.md)。

---

## 11. 协议 v3.0 消息

- **源文件**：`repair_app/bridge/protocol_v3/algorithm_protocol_v3.proto`
- **package**：`csam.algorithm.v3`
- **设计目标**：算法无关的通用通信协议，不绑定业务；算法输入输出由 `AlgorithmMetadata` 自描述；支持流式进度、取消、心跳、健康检查、版本协商。

### 11.1 Envelope（信封）

所有请求/响应的传输外壳。

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `request_id` | `string` | 1 | 全局唯一，UUID |
| `timestamp_ms` | `int64` | 2 | UTC 毫秒 |
| `message_type` | `string` | 3 | `"ALGORITHM_REQUEST"` \| `"HEARTBEAT"` \| ... |
| `protocol_ver` | `string` | 4 | `"3.0"` |
| `payload` | `bytes` | 5 | 具体消息的序列化字节 |

### 11.2 AlgorithmRequest

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `algorithm_name` | `string` | 1 | 如 `"path_planning.generate_path"` |
| `algorithm_ver` | `string` | 2 | `"1.0.0"` 或 `"latest"` |
| `timeout_ms` | `int32` | 3 | `0` = 用算法默认 |
| `stream_progress` | `bool` | 4 | 是否启用流式进度 |
| `params` | `map<string, Value>` | 10 | 标量/小数组参数 |
| `inputs` | `map<string, Tensor>` | 11 | 大块数组（点云/网格） |
| `assets` | `map<string, bytes>` | 12 | 二进制资产（STL/PNG） |
| `client_version` | `string` | 20 | 客户端版本 |

### 11.3 AlgorithmResponse

含 `Status` 枚举。

**Status 枚举**

| 值 | 序号 | 说明 |
| --- | --- | --- |
| `OK` | 0 | 成功 |
| `ERR_INVALID` | 1 | 输入参数无效 |
| `ERR_TIMEOUT` | 2 | 执行超时 |
| `ERR_ALGORITHM` | 3 | 算法内部异常 |
| `ERR_DEPS` | 4 | 依赖（工具箱）缺失 |
| `ERR_NOT_FOUND` | 5 | 算法未注册 |
| `ERR_CANCELLED` | 6 | 被取消 |
| `ERR_VERSION` | 7 | 版本不兼容 |
| `UNKNOWN` | 99 | 未知 |

**字段**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `status` | `Status` | 1 | 状态枚举 |
| `error_code` | `string` | 2 | 细分错误码字符串 |
| `error_message` | `string` | 3 | 人类可读错误信息 |
| `error_stack` | `string` | 4 | 堆栈跟踪（调试用） |
| `compute_time_ms` | `int64` | 5 | 算法计算耗时 |
| `results` | `map<string, Value>` | 10 | 标量/小数组结果 |
| `artifacts` | `map<string, Tensor>` | 11 | 大块数组（航点/网格） |
| `assets` | `map<string, bytes>` | 12 | 二进制资产（PNG/STL） |
| `algorithm_ver` | `string` | 20 | 实际执行的算法版本 |
| `request_id` | `string` | 21 | 回显请求 ID |

### 11.4 AlgorithmMetadata（自描述）

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `name` | `string` | 1 | 算法全名 |
| `version` | `string` | 2 | 版本 |
| `description` | `string` | 3 | 人类可读描述 |
| `category` | `string` | 4 | `"path_planning"` \| `"morphology"` \| ... |
| `input_schema` | `FieldSchema` | 5 | 输入模式 |
| `output_schema` | `FieldSchema` | 6 | 输出模式 |
| `dependencies` | `repeated string` | 7 | 如 `["Map_Toolbox"]` |
| `timeout_default_ms` | `int32` | 8 | 默认超时 |
| `streaming` | `bool` | 9 | 是否支持流式进度 |
| `idempotent` | `bool` | 10 | 是否可安全重试 |
| `tags` | `repeated string` | 11 | 如 `["cpu_heavy","path_planning"]` |

> 辅助消息 `FieldSchema`（`map<string, FieldSpec> fields`）与 `FieldSpec`（`type`/`shape`/`units`/`range`/`required`/`description`）用于自描述字段模式。

### 11.5 ProgressUpdate（流式进度）

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `request_id` | `string` | 1 | 请求 ID |
| `stage_index` | `int32` | 2 | 阶段序号 |
| `stage_name` | `string` | 3 | 如 `"slicing"` \| `"searching"` |
| `progress` | `float` | 4 | `[0,1]` |
| `message` | `string` | 5 | 面向 UI 的状态说明 |
| `partial_artifacts` | `map<string, Tensor>` | 6 | 增量结果 |

### 11.6 Heartbeat / Pong

**Heartbeat**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `request_id` | `string` | 1 | 请求 ID |
| `client_ts_ms` | `int64` | 2 | 客户端时间戳 |

**Pong**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `request_id` | `string` | 1 | 请求 ID |
| `server_ts_ms` | `int64` | 2 | 服务端时间戳 |
| `pending` | `int32` | 3 | 当前排队请求数 |

### 11.7 HealthCheckRequest / HealthStatus

**HealthCheckRequest**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `client_version` | `string` | 1 | 客户端版本 |

**HealthStatus**（含 `State` 枚举）

| State 值 | 序号 | 说明 |
| --- | --- | --- |
| `OK` | 0 | 正常 |
| `DEGRADED` | 1 | 部分算法不可用 |
| `DOWN` | 2 | 宕机 |

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `state` | `State` | 1 | 状态枚举 |
| `server_version` | `string` | 2 | 服务端版本 |
| `matlab_version` | `string` | 3 | MATLAB 版本 |
| `memory_mb` | `float` | 4 | 内存占用 |
| `uptime_s` | `int64` | 5 | 运行时长 |
| `pending_reqs` | `int32` | 6 | 排队请求数 |
| `toolbox_available` | `map<string, bool>` | 7 | 如 `{"Map_Toolbox": true}` |
| `error_rate_1m` | `float` | 8 | 最近 1 分钟错误率 |
| `total_requests` | `int32` | 9 | 累计请求数 |
| `last_error_ts` | `int64` | 10 | 最近错误时间戳 |

### 11.8 Cancellation

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `request_id` | `string` | 1 | 请求 ID |
| `reason` | `string` | 2 | 取消原因 |

### 11.9 VersionNegotiate / VersionResult

**VersionNegotiate**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `client_protocol` | `string` | 1 | 客户端协议版本 |
| `client_app` | `string` | 2 | 客户端应用名 |
| `want_algorithms` | `repeated string` | 3 | 客户端期望的算法 |

**VersionResult**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `server_protocol` | `string` | 1 | 服务端协议版本 |
| `server_app` | `string` | 2 | 服务端应用名 |
| `protocol_compatible` | `bool` | 3 | 协议是否兼容 |
| `available_algorithms` | `repeated string` | 4 | 可用算法列表 |
| `algorithm_count` | `int32` | 5 | 算法数量 |

### 11.10 ListAlgorithmsRequest / Response

**ListAlgorithmsRequest**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `category` | `string` | 1 | 按类别过滤，空 = 全部 |

**ListAlgorithmsResponse**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `algorithms` | `repeated AlgorithmMetadata` | 1 | 算法元数据列表 |

### 11.11 ShutdownRequest / ShutdownAck

**ShutdownRequest**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `reason` | `string` | 1 | 关闭原因 |
| `grace_period_ms` | `int32` | 2 | 宽限期 |

**ShutdownAck**

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `accepted` | `bool` | 1 | 是否接受 |
| `pending_count` | `int32` | 2 | 仍在处理的请求数 |
| `estimated_drain_ms` | `int64` | 3 | 预计排空耗时 |

### 11.12 Value / Tensor（通用值类型）

**Value**（`oneof kind`）

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `num` | `double` | 1 | 浮点 |
| `intval` | `int64` | 2 | 整数 |
| `str` | `string` | 3 | 字符串 |
| `flag` | `bool` | 4 | 布尔 |
| `tensor` | `Tensor` | 5 | 张量 |

**Tensor**（含 `DType` 枚举）

| DType 值 | 序号 |
| --- | --- |
| `F32` | 0 |
| `F64` | 1 |
| `I32` | 2 |
| `I64` | 3 |
| `U8` | 4 |

| 字段 | 类型 | 序号 | 说明 |
| --- | --- | --- | --- |
| `dtype` | `DType` | 1 | 数据类型 |
| `shape` | `repeated int32` | 2 | 形状，行主序 |
| `data` | `bytes` | 3 | 原始字节 |
| `units` | `string` | 4 | 如 `"mm"`、`"m/s"` |

---

## 12. 交叉引用

| 主题 | 文档 |
| --- | --- |
| 19 个算法的输入/输出/流程 | [04_工业算法说明.md](./04_工业算法说明.md) |
| 工具箱依赖与 `ERR_DEPS` | [04_工业算法说明.md - 工具箱依赖](./04_工业算法说明.md#3-工具箱依赖) |
| 系统分层与接口在架构中的位置 | [10_架构文档.md - 系统架构图](./10_架构文档.md#系统架构图) |
| 通信流程（路径 A / 路径 B） | [10_架构文档.md - 通信流程图](./10_架构文档.md#通信流程图) |
| 异常类型丢失等已知问题 | [10_架构文档.md - 已知架构问题](./10_架构文档.md#已知架构问题) |
| Bridge 架构设计 | [BRIDGE_ARCHITECTURE.md](./BRIDGE_ARCHITECTURE.md) |
| MATLAB Server 部署 | [MATLAB_DEPLOYMENT_GUIDE.md](./MATLAB_DEPLOYMENT_GUIDE.md) |
