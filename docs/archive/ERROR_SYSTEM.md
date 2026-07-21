# 异常处理系统重构报告（ERROR_SYSTEM）

> 任务 K 产出物 · 用户永远不看到 Python Traceback
> 日期：2026-07-15

---

## 一、目标

用户永远不看到 Python Traceback。
所有异常走统一流程：try → log → friendly → detail → recover → continue。
错误必须分类：License / MATLAB / File / Mesh / Network / Export / Unknown。

---

## 二、四大核心组件

### 2.1 架构图

```
┌────────────────────────────────────────────────────┐
│  异常发生                                            │
└─────────────────────┬──────────────────────────────┘
                      ▼
            ┌─────────────────────┐
            │   ErrorManager      │  编排中心
            │   .handle(exc)      │
            └─────────┬───────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐
   │classify │  │  log     │  │ friendly │
   │ ErrorCode│ │ LogManager│  │ message  │
   └─────────┘  └──────────┘  └──────────┘
                      │             │
                      ▼             ▼
                ┌──────────┐  ┌────────────┐
                │ error.log│  │ ErrorDialog│  用户界面
                │crash.log │  │ What/Why/  │
                │exception │  │ How + 详情 │
                └──────────┘  └────────────┘
                                    │
                                    ▼
                            ┌────────────┐
                            │ Recovery   │  恢复策略
                            │ Strategy   │
                            └────────────┘
                                    │
                                    ▼
                            ┌────────────┐
                            │ continue   │  继续使用
                            └────────────┘
```

### 2.2 组件职责

| 组件 | 文件位置 | 职责 |
|------|---------|------|
| **ErrorCode** | [error_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/error_manager.py) | 7 类错误码枚举 |
| **ErrorManager** | [error_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/error_manager.py) | 异常处理编排中心（分类/记录/显示/恢复） |
| **LogManager** | [error_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/error_manager.py) | 日志管理器（封装 logger_config） |
| **ErrorDialog** | [dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) | 用户界面（三段式 + 可展开技术日志） |

统一入口文件：[repair_app/utils/error_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/error_manager.py)

---

## 三、ErrorCode — 7 类错误码

```python
class ErrorCode(Enum):
    LICENSE = "license"      # License 授权无效 / 过期 / 缺失
    MATLAB = "matlab"        # MATLAB 引擎崩溃 / 算法异常 / 启动失败
    FILE = "file"            # 文件读写 / 路径 / 权限 / 磁盘空间
    MESH = "mesh"            # STL 读取 / 点云形状 / 三角化失败
    NETWORK = "network"      # ZMQ 连接 / 超时 / 协议 / 序列化
    EXPORT = "export"        # G-code / 机器人轨迹 / PDF 报告导出
    UNKNOWN = "unknown"      # 兜底：未分类异常
```

### 3.1 自动分类规则

ErrorManager.classify 按优先级顺序分类：

1. **显式指定**：调用方传 `code=ErrorCode.MATLAB` 则直接使用
2. **异常类型**：
   - `FileNotFoundError` / `PermissionError` / `IsADirectoryError` → FILE
   - `TimeoutError` → NETWORK
   - `MemoryError` → UNKNOWN
   - `BridgeError` 体系（模块名或类名含 "bridge"）→ NETWORK
   - `MatlabAlgorithmError`（类名含 "matlab"）→ MATLAB
3. **关键字匹配**（异常类型名 + 消息文本）：
   - license / 授权 / 签名 / hmac → LICENSE
   - matlab / engine / 算法 → MATLAB
   - timeout / connection / zmq / bridge / serializ / protocol → NETWORK
   - file / path / permission / 文件 / 权限 → FILE
   - stl / mesh / 点云 / triangle / 三角化 → MESH
   - export / gcode / robot / pdf / 导出 → EXPORT
4. **上下文推断**：context 参数中含 "license"/"matlab"/"导出" 等关键字
5. **兜底**：UNKNOWN

### 3.2 分类验证结果

| 异常 | 预期 | 实际 | 状态 |
|------|------|------|------|
| RuntimeError("MATLAB engine crashed") | matlab | matlab | ✓ |
| TimeoutError("ZMQ recv timeout") | network | network | ✓ |
| FileNotFoundError("test.stl") | file | file | ✓ |
| ValueError("xyz must be (N,3)") | mesh | mesh | ✓ |
| ValueError("gcode export failed") | export | export | ✓ |
| RuntimeError("License invalid") | license | license | ✓ |
| RuntimeError("unknown error") | unknown | unknown | ✓ |

---

## 四、LogManager — 日志管理器

### 4.1 职责

- 统一记录 ERROR 级别日志（带完整 traceback）
- 提供错误专用通道（带 ErrorCode 标签）
- 维护"最近错误"缓存（供 ErrorDialog 展示）
- 线程安全

### 4.2 接口

| 方法 | 用途 |
|------|------|
| `LogManager.log_error(exc, code, context)` | 记录错误日志，返回 traceback 文本 |
| `LogManager.log_warning(msg, *args)` | 记录警告 |
| `LogManager.log_info(msg, *args)` | 记录信息 |
| `LogManager.get_last_error()` | 返回最近错误 dict |
| `LogManager.clear_last_error()` | 清除缓存 |

### 4.3 日志输出格式

```
ERROR | [MATLAB] MATLAB engine crashed | context=路径规划
Traceback (most recent call last):
  File "main_window.py", line 2150, in _on_compute
    ...
RuntimeError: MATLAB engine crashed
```

日志文件：
- `app_YYYY-MM-DD.log` — 全量日志（10MB 滚动，保留 30 天）
- `error_YYYY-MM-DD.log` — 仅 ERROR+（10MB 滚动，保留 60 天）
- `crash_YYYYMMDD_HHMMSS.log` — 崩溃日志（crash_handler 写入）
- `exception_YYYYMMDD_HHMMSS.log` — 结构化异常报告（exception_reporter 写入）

---

## 五、ErrorManager — 异常处理编排中心

### 5.1 异常处理流程

```
try
  ↓
log          LogManager.log_error 记录完整 traceback 到 error.log
  ↓
friendly     ErrorManager.get_friendly_message 生成 What/Why/How
  ↓
detail       保留 exc 对象和 traceback 文本供技术员展开
  ↓
recover      ErrorManager.get_recovery_strategy 返回恢复策略
  ↓
continue     ErrorDialog 显示对话框，用户确认后继续
```

### 5.2 核心 API

#### `ErrorManager.handle(exc, code, context, parent, show_dialog)`

统一异常处理入口。

```python
try:
    risky_operation()
except Exception as exc:
    ErrorManager.handle(
        exc,
        code=ErrorCode.MATLAB,        # None 则自动分类
        context="路径规划",            # 操作上下文
        parent=self,                  # 父窗口
        show_dialog=True,             # 是否显示 GUI 对话框
    )
```

返回 `(ErrorCode, traceback_text)`。

#### `ErrorManager.guard(code, context, parent_getter, show_dialog, reraise)`

装饰器：自动捕获函数异常。

```python
@ErrorManager.guard(ErrorCode.FILE, context="导出 G-code")
def export_gcode():
    ...
```

#### `ErrorManager.context(code, context, parent, show_dialog)`

上下文管理器：自动捕获 with 块内异常。

```python
with ErrorManager.context(ErrorCode.NETWORK, "ZMQ 请求"):
    reply = sock.recv()
```

#### `ErrorManager.classify(exc, code, context)`

自动分类异常，返回 ErrorCode。

#### `ErrorManager.get_friendly_message(exc, code, context)`

生成 FriendlyMessage（title/what/why/how）。

#### `ErrorManager.get_recovery_strategy(code)`

返回 RecoveryStrategy（action + fallback_hint）。

### 5.3 恢复策略

| ErrorCode | action | 含义 |
|-----------|--------|------|
| LICENSE | fatal | 致命错误，软件无法运行 |
| MATLAB | retry | 可重试或检查 MATLAB 状态 |
| FILE | continue | 文件操作失败，可继续其他操作 |
| MESH | continue | 网格处理失败，可重新加载模型 |
| NETWORK | retry | 可重试或检查 Bridge 服务 |
| EXPORT | continue | 导出失败，可继续计算其他结果 |
| UNKNOWN | continue | 未预期错误，建议重启软件 |

---

## 六、ErrorDialog — 用户界面

文件：[repair_app/ui/dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py)

### 6.1 三段式信息

用户只看到：
- **发生了什么**（What）— 一句话说明
- **为什么**（Why）— 可能原因
- **如何解决**（How）— 具体步骤

技术日志默认折叠，点击"▸ 展开技术日志"按钮可查看完整 traceback。

### 6.2 ErrorCode 驱动

重构后 ErrorDialog 支持两种构造方式：

```python
# 方式 1：显式传 what/why/how（向后兼容）
ErrorDialog.show(parent, title="导出失败", what="...", why="...", how="...", exc=exc)

# 方式 2：传 ErrorCode + exc，自动生成（推荐）
ErrorDialog.show(parent, code=ErrorCode.EXPORT, exc=exc, context="导出 G-code")
```

方式 2 内部走 ErrorManager.handle 统一编排。

---

## 七、全局异常钩子

### 7.1 三层钩子链

```
sys.excepthook（默认）
  ↑ 包装
ErrorManager.main_thread_hook（显示用户友好对话框）
  ↑ 调用前钩子
exception_reporter.wrapped_hook（生成结构化报告 exception_*.log）
  ↑ 调用前钩子
crash_handler._handler（写 crash_*.log + stderr）
```

安装位置：[run_app.py](file:///d:/work/demo/industrial-vision/run_app.py) 第 43-48 行

```python
# 3. 安装异常报告器（生成结构化异常报告）
install_exception_reporter(show_dialog=True)
# 3.1 安装 ErrorManager 全局钩子（覆盖主线程 + 子线程未捕获异常）
ErrorManager.install_global_hooks(show_dialog=True)
```

### 7.2 主线程异常

`sys.excepthook` 捕获主线程未捕获异常：
1. 先调用前一个钩子（exception_reporter 生成报告 + crash_handler 写日志）
2. 再显示用户友好对话框（主线程才能操作 GUI）
3. KeyboardInterrupt 不拦截

### 7.3 子线程异常（新增）

`threading.excepthook` 捕获子线程未捕获异常（Python 3.8+）：
1. 仅记录日志（子线程不能直接弹 GUI 对话框，Qt 限制）
2. 标记 context 为"未捕获异常（子线程 {thread.name}）"
3. KeyboardInterrupt 不拦截

**此前缺口**：项目完全未设置 `threading.excepthook`，任何在工作线程（MATLAB 生命周期监控、ZMQ 接收线程、QThread）中未捕获的异常都不会进入钩子链，仅在控制台输出默认 traceback。现已修复。

---

## 八、Workers 结构化错误传递

文件：[repair_app/ui/workers.py](file:///d:/work/demo/industrial-vision/repair_app/ui/workers.py)

### 8.1 重构前

```python
class PathPlanningWorker(QObject):
    failed = Signal(str)  # 仅传递字符串

    def run(self):
        try:
            ...
        except Exception as exc:
            self.failed.emit(str(exc))  # 丢失结构化信息
```

### 8.2 重构后

```python
class PathPlanningWorker(QObject):
    # 结构化错误信号: (error_code, friendly_message, detail)
    failed = Signal(str, str, str)

    def run(self):
        try:
            ...
        except Exception as exc:
            code = ErrorManager.classify(exc, context="路径规划")
            self.failed.emit(*_pack_error(exc, code, "路径规划"))
```

`_pack_error` 辅助函数：
- 生成友好消息（不含 traceback）
- 生成完整 traceback 文本（供技术员排查）
- 同时记录日志（ErrorManager.handle show_dialog=False）

### 8.3 三个 Worker 的信号签名

| Worker | failed 信号 | 主线程槽 |
|--------|------------|---------|
| PathPlanningWorker | `Signal(str, str, str)` | `_on_path_failed(code, friendly, detail)` |
| MorphologyWorker | `Signal(str, str, str, object)` | `_on_morph_failed(code, friendly, detail, repair_pts)` |
| ComputePipelineWorker | `Signal(str, str, str)` | `_on_compute_failed(code, friendly, detail)` |

---

## 九、main_window.py 错误处理改造

文件：[repair_app/ui/main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)

### 9.1 `_show_error` 函数

**重构前**：
```python
def _show_error(parent, category, exc):
    _e = classify_error(category, exc)  # 旧分类函数
    ErrorDialog.show(parent, title=_e["title"], what=_e["what"], ...)
```

**重构后**：
```python
def _show_error(parent, category, exc):
    # 自动分类 + 显示对话框 + 记录日志（一键编排）
    ErrorManager.handle(exc, context=category, parent=parent, show_dialog=True)
```

### 9.2 三个 Slot 适配结构化信号

- `_on_compute_failed(error_code, friendly, detail)` — 显示 ErrorDialog + 标记 Pipeline 失败
- `_on_path_failed(error_code, friendly, detail)` — 回退模拟航点 + 显示 ErrorDialog
- `_on_morph_failed(error_code, friendly, detail, repair_pts)` — 回退基础沉积点 + 显示 ErrorDialog

### 9.3 旧的 `classify_error` 函数

保留为兼容层（dialogs.py 中），内部委托给 ErrorManager.classify + get_friendly_message。
不再被 `_show_error` 使用，但保留以避免破坏外部调用。

---

## 十、验证结果

### 10.1 单元验证

```
=== ErrorCode ===
  LICENSE = license
  MATLAB = matlab
  FILE = file
  MESH = mesh
  NETWORK = network
  EXPORT = export
  UNKNOWN = unknown

=== Classify Tests ===
  RuntimeError: MATLAB engine crashed -> matlab [OK]
  TimeoutError: ZMQ recv timeout -> network [OK]
  FileNotFoundError: test.stl -> file [OK]
  ValueError: xyz must be (N,3) -> mesh [OK]
  ValueError: gcode export failed -> export [OK]
  RuntimeError: License invalid -> license [OK]
  RuntimeError: unknown error -> unknown [OK]

=== Friendly Message ===
  [license] 测试失败: 软件 License 授权无效或已过期...
  [matlab] 测试失败: MATLAB 算法执行失败...
  [file] 测试失败: 文件读取或写入出错...
  [mesh] 测试失败: STL 模型或点云数据处理失败...
  [network] 测试失败: 软件无法与 MATLAB 计算服务通信...
  [export] 测试失败: 结果导出失败...
  [unknown] 操作失败: 操作过程中发生未预期错误...

=== Recovery Strategy ===
  [license] action=fatal
  [matlab] action=retry
  [file] action=continue
  [mesh] action=continue
  [network] action=retry
  [export] action=continue
  [unknown] action=continue

=== LogManager ===
  log_error returned 25 chars
  last_error code=matlab context=test context

=== Import Chain ===
  ErrorDialog / classify_error / Workers / MainWindow / run_app 全部导入 OK

ALL OK
```

### 10.2 测试套件

```
python -m pytest repair_app/tests/ --tb=short -q

====================== 229 passed, 6 warnings in 14.89s =======================
```

- **229 项测试全部通过**
- 6 个警告全部来自遗留 `zmq_client` 模块的预期弃用提示
- **零回归**

---

## 十一、使用规范（开发约定）

### 11.1 业务层异常处理

**推荐方式**：使用 ErrorManager.handle

```python
from repair_app.utils.error_manager import ErrorManager, ErrorCode

try:
    risky_operation()
except Exception as exc:
    ErrorManager.handle(exc, ErrorCode.FILE, context="导出 G-code", parent=self)
```

### 11.2 装饰器方式

```python
@ErrorManager.guard(ErrorCode.NETWORK, context="ZMQ 请求")
def send_request():
    ...
```

### 11.3 上下文管理器方式

```python
with ErrorManager.context(ErrorCode.MATLAB, "MATLAB 计算"):
    result = matlab_engine.compute(...)
```

### 11.4 Worker 线程

Worker 中捕获异常后通过结构化信号传递：

```python
except Exception as exc:
    code = ErrorManager.classify(exc, context="路径规划")
    self.failed.emit(*_pack_error(exc, code, "路径规划"))
```

### 11.5 禁止事项

- **禁止**直接 `QMessageBox.warning(self, "错误", str(exc))` — 用户会看到原始异常
- **禁止** `except Exception: pass` — 静默吞掉异常
- **禁止** `print(traceback.format_exc())` — 输出到控制台而非日志
- **禁止**各模块自行实现分类逻辑 — 必须走 ErrorManager.classify

---

## 十二、修改文件清单

| 文件 | 修改类型 |
|------|---------|
| `repair_app/utils/error_manager.py` | 新建（ErrorCode + LogManager + ErrorManager） |
| `repair_app/ui/dialogs.py` | 重构 ErrorDialog（ErrorCode 驱动）+ classify_error 委托 |
| `repair_app/ui/workers.py` | 重构（结构化错误信号 + _pack_error） |
| `repair_app/ui/main_window.py` | 重构 _show_error + 3 个 Slot 适配结构化信号 |
| `run_app.py` | 新增 ErrorManager.install_global_hooks |

---

## 十三、与现有基础设施的关系

| 现有组件 | 角色 | 与 ErrorManager 关系 |
|---------|------|---------------------|
| `bridge/communication/exceptions.py` | BridgeError 体系 | ErrorManager.classify 识别 BridgeError → NETWORK |
| `software/exception_reporter.py` | 结构化异常报告 | 钩子链前置：生成 exception_*.log 报告文件 |
| `utils/crash_handler.py` | 崩溃日志 | 钩子链最底层：写 crash_*.log |
| `utils/logger_config.py` | 日志后端 | LogManager 封装此模块，不重新实现 |
| `ui/dialogs.py` ErrorDialog | 用户界面 | ErrorManager.handle 调用 ErrorDialog.show |

**不替代**：BridgeError 体系、exception_reporter、crash_handler、logger_config 均保留。
**新增**：ErrorManager 作为统一编排层，串联上述组件。
