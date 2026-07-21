# 配置中心重构报告（CONFIG_REFACTOR）

> 任务 J 产出物 · 唯一 Truth Source · 消除全部 Magic Number
> 版本：schema 3.0.0 · 日期：2026-07-15

---

## 一、目标

整个项目所有参数只有一个权威来源（Truth Source）。
任何模块禁止再写死数字、范围、超时、端口。
全部从 `parameter_schema.json` 读取。

---

## 二、唯一 Truth Source 架构

```
┌─────────────────────────────────────────┐
│  parameter_schema.json （唯一权威源）    │
│  5 大类参数 + 材料库 + 验证规则           │
└─────────────────┬───────────────────────┘
                  │ 只读
                  ▼
┌─────────────────────────────────────────┐
│  schema_loader.py （唯一读取器）         │
│  线程安全单例 + 5 类访问接口             │
└─────────────────┬───────────────────────┘
                  │ 对外 API
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   utils/config  ui/*    bridge/*  export/*  core/*
   （兼容层）   （GUI） （通信）  （导出）  （算法）
```

规则：
- 任何模块**不得**直接 `json.load` 读 schema。
- 任何模块**不得**写死数字。
- 全部通过 `schema_loader` 的函数访问。

---

## 三、parameter_schema.json 结构

文件位置：[repair_app/config/parameter_schema.json](file:///d:/work/demo/industrial-vision/repair_app/config/parameter_schema.json)

### 3.1 五大类参数

| 类别 | 字段名 | 数量 | 用途 |
|------|--------|------|------|
| 工艺参数 | `process_parameters` | 23 | 路径规划 / 形貌 / 冷喷涂 / 标定 |
| UI 参数 | `ui_parameters` | 10 | 笔刷 / 机器人 / 坐标系 / 标定测量 |
| 导出参数 | `export_parameters` | 7 | G-code / 标定系数 |
| 网络参数 | `network_parameters` | 23 | ZMQ / Bridge / Launcher |
| 系统参数 | `system_parameters` | 8 | 窗口 / License / Git / 计时器 |

### 3.2 每个参数字段（工艺参数示例）

```json
"layer_height_mm": {
  "default": 2.0,
  "min": 0.1,
  "max": 20.0,
  "step": 0.1,
  "unit": "mm",
  "group": "path_planning",
  "ui_key": "layer_height",
  "label_zh": "层高",
  "label_en": "Layer Height",
  "tooltip": "每层喷涂的高度（mm）。值越小表面越精细...",
  "description": "路径规划中每层沉积的厚度。",
  "read_only": false,
  "validation_rule": "range",
  "material_override": false
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `default` | 默认值 |
| `min` / `max` | 最小 / 最大值 |
| `step` | 步长 |
| `unit` | 单位 |
| `group` | 分组（path_planning / cold_spray 等） |
| `ui_key` | UI 短键名，空字符串表示不进入 UI_PARAM_SPECS |
| `label_zh` / `label_en` | 中英文标签 |
| `tooltip` | 鼠标悬停提示 |
| `description` | 详细说明 |
| `read_only` | 是否只读（如临界速度） |
| `validation_rule` | 验证规则（range / range_int / range_gt:xxx） |
| `material_override` | 是否允许材料覆盖 |

### 3.3 网络参数特殊字段

```json
"bridge_timeout_ms": {
  "value": 30000,
  "env_var": "CSAM_BRIDGE_TIMEOUT_MS",
  "min": 1000, "max": 600000,
  "unit": "ms", ...
}
```

- `value`：默认值（不是 `default`）
- `env_var`：环境变量名，优先级**高于** schema 默认值

### 3.4 材料库（Material Library）

```json
"materials": {
  "STEEL_316L": {
    "label_zh": "316L 不锈钢",
    "label_en": "316L Stainless Steel",
    "overrides": {
      "critical_velocity_ms": 600.0,
      "preheat_temp_c": 200.0
    }
  },
  ...
}
```

- 共 6 种材料（含 `MATERIAL_UNSPECIFIED`）
- `material_list_order` 指定 UI 下拉框顺序
- 只覆盖 `material_override: true` 的参数（临界速度、预热温度）

### 3.5 验证规则（Validation Rule）

```json
"validation_rules": {
  "range": "min <= value <= max",
  "range_int": "min <= value <= max 且 value 为整数",
  "range_gt:critical_velocity_ms": "value > critical_velocity_ms"
}
```

---

## 四、schema_loader.py 接口

文件位置：[repair_app/config/schema_loader.py](file:///d:/work/demo/industrial-vision/repair_app/config/schema_loader.py)

### 4.1 核心特性

- **线程安全单例**：`_load_schema()` 使用双重检查锁
- **一次加载**：schema 在首次访问时读入内存，后续直接返回
- **统一入口**：所有模块只能通过此文件访问 schema

### 4.2 五类访问接口

| 接口 | 用途 |
|------|------|
| `get_process_param(key)` | 返回工艺参数完整定义 dict |
| `get_process_default(key)` | 返回工艺参数默认值 |
| `get_process_bounds(key)` | 返回 (min, max) |
| `get_ui_param(key)` | 返回 UI 参数定义 |
| `get_ui_default(key)` | 返回 UI 参数默认值 |
| `get_export_value(key)` | 返回导出参数值 |
| `get_network_value(key)` | 返回网络参数值（**优先读环境变量**） |
| `get_system_value(key)` | 返回系统参数值 |
| `get_material_override(mat, param)` | 返回材料覆盖值 |
| `get_material_items()` | 返回 [(label, key)] 供 ComboBox 使用 |

### 4.3 兼容函数（向后兼容旧代码）

| 函数 | 替代的旧常量 |
|------|-------------|
| `get_param_specs()` | `PARAM_SPECS` |
| `get_param_bounds()` | `PARAM_BOUNDS` |
| `get_param_defaults()` | `PARAM_DEFAULTS` |
| `get_ui_param_specs()` | `UI_PARAM_SPECS` |

---

## 五、各文件重构明细

### 5.1 utils/config.py（兼容层）

文件：[repair_app/utils/config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py)

**重构前**（硬编码）：
```python
@dataclass
class WindowConfig:
    left_panel_width: int = 340
    right_panel_width: int = 320
    window_width: int = 1700
    window_height: int = 950

MATERIALS = [("未指定", "MATERIAL_UNSPECIFIED"), ...]
PARAM_SPECS = [("layer_height_mm", "Layer Height", 0.1, 20.0, 2.0, 0.1), ...]
```

**重构后**（从 schema 派生）：
```python
@dataclass
class WindowConfig:
    left_panel_width: int = int(schema_loader.get_system_value("left_panel_width"))
    right_panel_width: int = int(schema_loader.get_system_value("right_panel_width"))
    window_width: int = int(schema_loader.get_system_value("window_width"))
    window_height: int = int(schema_loader.get_system_value("window_height"))

MATERIALS = schema_loader.get_material_items()
PARAM_SPECS = []  # 循环从 schema_loader.all_process_params() 派生
PARAM_BOUNDS = schema_loader.get_param_bounds()
PARAM_DEFAULTS = schema_loader.get_param_defaults()
UI_PARAM_SPECS = schema_loader.get_ui_param_specs()
```

验证结果：`PARAM_SPECS=23, UI_PARAM_SPECS=19, MATERIALS=6, WindowConfig=340/320/1700/950`

### 5.2 ui/main_window.py

文件：[repair_app/ui/main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)

| 位置 | 重构前（Magic Number） | 重构后（从 schema 读取） |
|------|----------------------|------------------------|
| 通信地址 | `tcp://127.0.0.1:5555` 硬编码 | `schema_loader.get_network_value("zmq_default_address")` |
| 进度地址 | `tcp://127.0.0.1:5556` | `get_network_value("zmq_progress_address")` |
| 线程等待 | `5000` ms | `get_network_value("thread_wait_ms")` |
| 线程终止 | `2000` ms | `get_network_value("thread_terminate_wait_ms")` |
| pp_layers 范围 | `setRange(1, 200)` | `get_process_param("num_layers")["min/max"]` |
| depth 范围 | `setRange(0, 2)` | `get_process_param("depth_compensation")` |
| max_layers 范围 | `setRange(1, 20)` | `get_process_param("max_morphology_layers")` |
| License 告警 | `days <= 7` | `get_system_value("license_warning_days")` |
| Loading 超时 | `timeout_sec=180` | `get_network_value("matlab_loading_timeout_sec")` |

### 5.3 ui/dialogs.py

文件：[repair_app/ui/dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py)

| 对话框 | 重构前 | 重构后 |
|--------|--------|--------|
| LoadingDialog | `timeout_sec=180` | `None` 时从 `get_network_value("matlab_loading_timeout_sec")` 读 |
| RobotExportDialog | TCP `0.5` / tool `1` / base `0` 硬编码 | `get_ui_param("robot_tcp_speed_ms")` 等 |
| CalibrationDialog | 7 项标定参数硬编码 | `get_process_param(...)` 读取 |
| CalibrationDialog 测量 | 3 项测量上限硬编码 | `get_ui_param("calib_measured_*")` |
| CoordinateSystemDialog | 平移 `±10000` / 旋转 `±360` / 缩放 `0.01-100` | `get_ui_param("coord_*_range_*")` |

### 5.4 export/gcode_exporter.py

文件：[repair_app/export/gcode_exporter.py](file:///d:/work/demo/industrial-vision/repair_app/export/gcode_exporter.py)

| 参数 | 重构前 | 重构后 |
|------|--------|--------|
| feed_rate | `500.0` | `Optional[float]=None` → `get_export_value("gcode_feed_rate_mmpmin")` |
| safe_z | `10.0` | `get_export_value("gcode_safe_z_mm")` |
| powder_m_code | `7` | `get_export_value("gcode_powder_m_code")` |
| spray_on_dwell_ms | `200` | `get_export_value("gcode_spray_on_dwell_ms")` |
| Git 超时 | `3` 秒 | `get_system_value("git_commit_timeout_sec")` |

### 5.5 export/robot_exporter.py

文件：[repair_app/export/robot_exporter.py](file:///d:/work/demo/industrial-vision/repair_app/export/robot_exporter.py)

| 参数 | 重构前 | 重构后 |
|------|--------|--------|
| tcp_speed | `0.5` | `get_ui_default("robot_tcp_speed_ms")` |
| tool_frame | `1` | `get_ui_default("robot_tool_frame")` |
| base_frame | `0` | `get_ui_default("robot_base_frame")` |

### 5.6 utils/calibration_wizard.py

文件：[repair_app/utils/calibration_wizard.py](file:///d:/work/demo/industrial-vision/repair_app/utils/calibration_wizard.py)

**消除双源冲突**：原 CalibrationRecord 默认值与 start_calibration() 参数默认值是两份独立硬编码。

重构后：
```python
def _pp_default(key: str) -> float:
    return float(_schema.get_process_default(key))

@dataclass
class CalibrationRecord:
    nozzle_diameter_mm: float = field(default_factory=lambda: _pp_default("nozzle_diameter_mm"))
    standoff_distance_mm: float = field(default_factory=lambda: _pp_default("standoff_distance_mm"))
    # ... 7 项全部用 default_factory
```

标定修正系数从 export_parameters 读取：
- `calibration_width_factor` = 1.1
- `calibration_height_factor` = 0.8
- `calibration_correction_min` = 0.1

### 5.7 ui/defect_selector.py

文件：[repair_app/ui/defect_selector.py](file:///d:/work/demo/industrial-vision/repair_app/ui/defect_selector.py)

| 参数 | 重构前 | 重构后 |
|------|--------|--------|
| 笔刷半径 | `2.0` | `get_ui_default("brush_radius_mm")` |
| 笔刷范围 | `setRange(0.5, 20)` | `get_ui_param("brush_radius_mm")` |
| 凸包最小点数 | `3` | `get_system_value("convex_hull_min_points")` |

### 5.8 core/path_planner.py（消除三处重复）

文件：[repair_app/core/path_planner.py](file:///d:/work/demo/industrial-vision/repair_app/core/path_planner.py)

**重构前**：三个入口函数（`plan_path_from_stl` / `plan_path_from_cloud` / `iter_path_from_cloud`）+ `layer_slice` + `generate_path` 各自硬编码相同的默认值，共 5 处重复。

**重构后**：模块级常量统一读取，5 处函数全部引用常量。
```python
def _d(key: str) -> float:
    return float(_schema.get_process_default(key))

_D_LAYER_HEIGHT = _d("layer_height_mm")      # 2.0
_D_SCANNING_ANGLE = _d("scanning_angle_deg") # -45.0
_D_SCANNING_STEP = _d("scanning_step_mm")    # 2.0
_D_BUFFER_ADDITIVE = _d("buffer_additive_mm")# 2.0
_D_BUFFER_REPAIRING = _d("buffer_repairing_mm") # 0.0
_D_EDGE_STEP = _d("edge_step_size_mm")       # 2.0
_D_TILT_ANGLE = _d("tilt_angle_deg")         # 60.0
_D_NUM_LAYERS = int(_d("num_layers"))        # 5
```

### 5.9 bridge/communication/config.py

文件：[repair_app/bridge/communication/config.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/communication/config.py)

**重构前**：BridgeConfig 所有字段硬编码（30000 / 5000 / 3 等）。

**重构后**：环境变量优先，缺失时回退到 schema。
```python
def _env_int(key: str, schema_key: str) -> int:
    val = os.environ.get(key)
    if val is not None:
        return int(val)
    return int(_schema.get_network_value(schema_key))

@dataclass(frozen=True)
class BridgeConfig:
    request_timeout_ms: int = field(
        default_factory=lambda: _env_int("CSAM_BRIDGE_TIMEOUT_MS", "bridge_timeout_ms")
    )
    # ... 全部字段从 schema 读取
```

验证结果：`timeout=30000, heartbeat=5000, retries=3, protocol=2.1, client=bridge-1.0.0`

### 5.10 bridge/launcher.py

文件：[repair_app/bridge/launcher.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/launcher.py)

**重构前**：类常量硬编码（`DEFAULT_PORT=5555` / `STARTUP_TIMEOUT_S=120` 等）。

**重构后**：从 schema network_parameters 读取。
```python
DEFAULT_PORT = _extract_port_from_addr(_schema.get_network_value("zmq_default_address"))
STARTUP_TIMEOUT_S = int(_schema.get_network_value("launcher_startup_timeout_sec"))
MAX_RESTARTS = int(_schema.get_network_value("launcher_max_restarts"))
RESTART_DELAY_S = float(_schema.get_network_value("launcher_restart_delay_sec"))
STOP_TIMEOUT_S = int(_schema.get_network_value("launcher_stop_timeout_sec"))
KILL_TIMEOUT_S = int(_schema.get_network_value("launcher_kill_timeout_sec"))
```

验证结果：`DEFAULT_PORT=5555, STARTUP=120, MAX_RESTARTS=3`

---

## 六、Magic Number 消除清单

共消除 **10+ 文件** 中的硬编码，包括：

| 类型 | 数量 | 示例 |
|------|------|------|
| 工艺参数默认值/范围 | 23 项 | layer_height=2.0, scanning_angle=-45 |
| UI 参数 | 10 项 | brush_radius=2.0, robot_tcp=0.5 |
| 导出参数 | 7 项 | feed_rate=500, safe_z=10 |
| 网络地址/端口 | 2 项 | tcp://127.0.0.1:5555, :5556 |
| Bridge 超时/重试 | 10 项 | timeout=30000, heartbeat=5000 |
| Launcher 超时/重启 | 7 项 | startup=120, max_restarts=3 |
| 系统参数 | 8 项 | window=1700x950, license_warn=7 |
| 材料覆盖 | 6 种材料 × 2 参数 | STEEL_316L: critical=600, preheat=200 |
| 三处函数默认值重复 | 1 处合并 | path_planner 三入口函数 |
| 双源冲突 | 1 处合并 | calibration_wizard Record vs start_calibration |

---

## 七、环境变量优先级

网络参数支持 `env_var` 字段，优先级：

```
环境变量 > schema 默认值
```

支持的环境变量：

| 环境变量 | 用途 | 默认值 |
|---------|------|--------|
| `CSAM_ZMQ_ADDRESS` | ZMQ 通信地址 | tcp://127.0.0.1:5555 |
| `CSAM_BRIDGE_TIMEOUT_MS` | Bridge 请求超时 | 30000 |
| `CSAM_BRIDGE_CONNECT_MS` | Bridge 连接超时 | 5000 |
| `CSAM_BRIDGE_HEALTH_MS` | 健康检查超时 | 3000 |
| `CSAM_BRIDGE_HEARTBEAT_MS` | 心跳间隔 | 5000 |
| `CSAM_BRIDGE_HEARTBEAT_MISS` | 心跳丢失阈值 | 3 |
| `CSAM_BRIDGE_MAX_RETRIES` | 最大重试 | 3 |
| `CSAM_BRIDGE_RETRY_MS` | 重试间隔 | 2000 |
| `CSAM_BRIDGE_LATENCY_LOG_MS` | 延迟日志阈值 | 1000 |
| `CSAM_MATLAB_EXE` | MATLAB 可执行文件路径 | 自动查找 |
| `CSAM_LOG_LEVEL` | 日志级别 | INFO |

---

## 八、ui_key 策略

schema 中 `ui_key` 字段决定参数是否进入 `UI_PARAM_SPECS`（即是否由 UI 自动生成 spinbox）：

| ui_key 值 | 含义 | 处理方式 |
|-----------|------|---------|
| 非空字符串（如 `"layer_height"`） | 进入 UI_PARAM_SPECS | UI 自动生成 spinbox |
| 空字符串 `""` | 不进入 UI_PARAM_SPECS | 由 main_window.py 专用 SpinBox 处理 |

`ui_key` 为空的 4 个参数：
- `num_layers`（规划层数）— main_window 的 pp_layers SpinBox
- `depth_compensation`（深度补偿）— main_window 的 depth SpinBox
- `max_morphology_layers`（预测层数）— main_window 的 max_layers SpinBox
- `preheat_temp_c`（预热温度）— CalibrationDialog 专用 SpinBox

---

## 九、验证结果

### 9.1 默认值一致性验证

运行综合验证脚本，所有默认值与原硬编码值**完全一致**：

```
=== Schema Stats ===
process: 23, ui: 10, export: 7, network: 23, system: 8, materials: 6

=== config.py Derived ===
PARAM_SPECS: 23, UI_PARAM_SPECS: 19, MATERIALS: 6
WindowConfig: 340 / 320 / 1700 / 950

=== BridgeConfig ===
timeout: 30000, heartbeat: 5000, retries: 3
protocol: 2.1, client: bridge-1.0.0
poll: 200, large_array: 1000000

=== Launcher ===
DEFAULT_PORT: 5555, STARTUP_TIMEOUT_S: 120, MAX_RESTARTS: 3

=== PathPlanner Defaults ===
layer_h: 2.0, angle: -45.0, step: 2.0, num_layers: 5, tilt: 60.0

=== Exporters ===
GCode: feed=500.0, safe_z=10.0, powder=7, dwell=200
Robot: tcp=0.5, tool=1, base=0

=== Calibration ===
nozzle: 6.0, standoff: 30.0, preheat: 200.0

=== main_window Constants ===
_BRIDGE_ADDRESS: tcp://127.0.0.1:5555
_PROGRESS_ADDRESS: tcp://127.0.0.1:5556
_THREAD_WAIT_MS: 5000
_THREAD_TERMINATE_WAIT_MS: 2000
```

### 9.2 测试套件结果

```
python -m pytest repair_app/tests/ --tb=short -q

============================== 229 passed, 6 warnings in 14.91s ==============================
```

- **229 项测试全部通过**
- 6 个警告全部来自遗留 `zmq_client` 模块的预期弃用提示
- **零回归**

---

## 十、修改文件清单

| 文件 | 修改类型 |
|------|---------|
| `repair_app/config/parameter_schema.json` | 新建 + 扩展（5 大类 + 材料 + 验证规则） |
| `repair_app/config/schema_loader.py` | 新建（线程安全单例 + 5 类接口） |
| `repair_app/utils/config.py` | 完全重构（从 schema 派生） |
| `repair_app/ui/main_window.py` | Magic Number 替换（9 处） |
| `repair_app/ui/dialogs.py` | Magic Number 替换（4 个对话框） |
| `repair_app/export/gcode_exporter.py` | 默认参数从 schema 读取 |
| `repair_app/export/robot_exporter.py` | 默认参数从 schema 读取 |
| `repair_app/utils/calibration_wizard.py` | 消除双源冲突 |
| `repair_app/ui/defect_selector.py` | 笔刷半径 / 凸包点数 |
| `repair_app/core/path_planner.py` | 消除三处默认值重复 |
| `repair_app/bridge/communication/config.py` | 完全重构（环境变量 + schema） |
| `repair_app/bridge/launcher.py` | 端口 / 超时从 schema 读取 |

---

## 十一、使用规范（开发约定）

1. **新增参数**：必须先在 `parameter_schema.json` 中定义，再通过 `schema_loader` 读取。
2. **禁止硬编码**：任何 PR 中出现新的 Magic Number 将被拒绝。
3. **环境变量**：仅网络参数支持 `env_var` 字段，其他类别不支持。
4. **材料覆盖**：只有 `material_override: true` 的参数可被材料库覆盖。
5. **UI 参数**：`ui_key` 为空表示由专用 SpinBox 处理，不进入自动生成列表。
6. **修改默认值**：只需改 schema 一处，全项目自动生效。
