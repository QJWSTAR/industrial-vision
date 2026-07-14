# API 文档

> 本文档说明 CSAM 修复平台所有公开接口，包括 UI 层中介服务、通信客户端、引擎门面、MatlabAdapter、引擎接口、MatlabEngineProxy、异常层次、通信配置。
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
- [5. MatlabAdapter](#5-matlabadapter)
- [6. IEngine 接口](#6-iengine-接口)
- [7. MatlabEngineProxy](#7-matlabengineproxy)
- [8. 异常类层次](#8-异常类层次)
- [9. BridgeConfig](#9-bridgeconfig)
- [10. 交叉引用](#10-交叉引用)

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

## 5. MatlabAdapter

- **源文件**：`repair_app/bridge/adapters/matlab_adapter.py`
- **角色**：`BridgeServer` 子类，处理修复请求，调用 MATLAB 算法或降级到 Python。运行于 MATLAB 宿主进程内（通过 `pyenv` 调用 Python）。
- **服务版本**：`matlab-adapter-2.0.0`

### 关键方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `handle_repair(request: RepairRequest) -> RepairResult` | `RepairResult` | 处理修复请求，调用 MATLAB 算法或降级到 Python 原型 |

### 降级策略

`_invoke_with_fallback` 在 MATLAB 调用失败时自动切换到 `LocalEngine` 的 Python 原型算法，保证生产连续性。降级行为由 `CSAM_ALGORITHM_ENGINE` 环境变量控制：

| 值 | 行为 |
| --- | --- |
| `auto` | 优先 MATLAB，不可用降级 Python（默认） |
| `matlab` | 强制使用 MATLAB，不可用报错 |
| `python` | 强制使用 Python 原型 |

### MATLAB 共享会话

`MatlabAdapter` 通过 `MatlabEngineProxy` 连接 MATLAB 共享引擎会话（`matlab.engine.connect_matlab('matlab_bridge')`），调用 `eng.run_path_planning()` / `eng.call_profile_prediction()` 等算法函数。

---

## 6. IEngine 接口

- **源文件**：`repair_app/domain/interfaces.py`（第 64 行）
- **角色**：引擎抽象接口，当前仅 `LocalEngine` 实现此接口（降级用）。MATLAB 算法通过 `MatlabAdapter` 走 Bridge 通信路径，不实现此接口。

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `name -> str` | `str` | 引擎名 |
| `is_available -> bool` | `bool` | 引擎是否可用 |
| `plan_path(point_cloud, defect_region, params, is_additive=False) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 生成修复路径（流式） |
| `predict_morphology(point_cloud, defect_region, waypoints, params) -> Iterator[np.ndarray]` | `Iterator[np.ndarray]` | 预测形貌（流式） |
| `check_health() -> bool` | `bool` | 健康检查 |

---

## 7. MatlabEngineProxy

- **源文件**：`repair_app/bridge/adapters/matlab_engine_proxy.py`
- **角色**：`matlab.engine` 单例封装，符合 `_algorithm_fn` 签名，供 `MatlabAdapter` 调用 MATLAB 算法函数。

### 连接策略

按优先级依次尝试：

| 顺序 | 策略 | 说明 |
| --- | --- | --- |
| 1 | 共享会话 | `matlab.engine.connect_matlab('matlab_bridge')` 连接已共享的 MATLAB 会话 |
| 2 | 默认共享会话 | 连接默认共享会话（无名称） |
| 3 | 独立启动 | 仅 `matlab` 模式下启动独立 MATLAB 引擎实例 |

### 关键方法

| 签名 | 返回 | 说明 |
| --- | --- | --- |
| `__call__(xyz, meta) -> waypoints` | `waypoints` | 路径规划算法调用（符合 `_algorithm_fn` 签名），内部调用 `eng.run_path_planning()` |
| `call_profile_prediction(xyz, meta) -> dict` | `dict` | 形貌预测算法调用，内部调用 `eng.call_profile_prediction()` |

### 共享会话管理

`MatlabEngineProxy` 依赖 MATLAB 侧通过 `matlab.engine.shareEngine('matlab_bridge')` 共享的会话。`matlab_bridge_server.m` 启动时自动执行共享。

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

## 10. 交叉引用

| 主题 | 文档 |
| --- | --- |
| 19 个算法的输入/输出/流程 | [04_工业算法说明.md](./04_工业算法说明.md) |
| 工具箱依赖与 `ERR_DEPS` | [04_工业算法说明.md - 工具箱依赖](./04_工业算法说明.md#3-工具箱依赖) |
| 系统分层与接口在架构中的位置 | [10_架构文档.md - 系统架构图](./10_架构文档.md#系统架构图) |
| 通信流程 | [10_架构文档.md - 通信流程图](./10_架构文档.md#通信流程图) |
| 异常类型丢失等已知问题 | [10_架构文档.md - 已知架构问题](./10_架构文档.md#已知架构问题) |
| Bridge 架构设计 | [BRIDGE_ARCHITECTURE.md](./BRIDGE_ARCHITECTURE.md) |
| MATLAB 集成指南 | [MATLAB_INTEGRATION.md](./MATLAB_INTEGRATION.md) |
