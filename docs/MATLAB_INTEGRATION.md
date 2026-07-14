# MATLAB R2025b 集成指南

> 本文档指导如何将 MATLAB R2025b 接入 CSAM Repair 的生产通信路径。
> 通信架构已定稿，详见 [COMMUNICATION.md](COMMUNICATION.md)。

---

## 1. 生产通信路径

```
GUI → CoordinationService → LegacyZmqClient → BridgeClient
    → ZeroMQ (tcp://127.0.0.1:5555) → matlab_bridge_server.m
    → MatlabAdapter (Python) → BridgeServer (zmq.REP)
    → MATLAB R2025b 算法 → RepairResult → 原路返回 → GUI
```

**唯一生产入口**：`matlab_bridge_server.m`（项目根目录）。
**不要**使用旧的 `matlab_server/` 目录（已删除，原 TCP/JSON/v3.0/5570 路径已废弃）。

---

## 2. 前置条件

### 2.1 MATLAB 侧

- MATLAB R2025b（或 R2024b+）
- Java 已启用（`usejava('jvm')` 返回 1）— MATLAB 默认启用
- 可选工具箱：
  - **Mapping Toolbox**：`generate_path`、`profile_predict` 需要（`polyxpoly`）
  - **Curve Fitting Toolbox**：`particle_fitting` 需要（`fit`/`fittype`）
  - 其余算法仅依赖基础 MATLAB（`containers.Map`、`graph`、`conncomp` 等）

### 2.2 Python 侧

MATLAB 通过 `pyenv` 调用 Python 的 BridgeServer，因此 MATLAB 必须能访问项目的 Python 环境：

```matlab
% 在 MATLAB 中配置 Python 环境（指向项目 venv）
pyenv('Version', 'D:\work\demo\industrial-vision\venv\Scripts\python.exe');
```

验证：

```matlab
pyenv          % 应显示 Python 版本与可执行路径
py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter')
```

### 2.3 依赖库

Python 侧需安装（项目 venv 已包含）：

- `pyzmq`（ZeroMQ 绑定）
- `protobuf`（Protocol Buffers 运行时）
- `numpy`

---

## 3. 启动 MATLAB 服务

### 3.1 启动步骤

1. 启动 MATLAB R2025b。
2. 配置 Python 环境（如 2.2 节）。
3. 切换到项目根目录并启动服务：

```matlab
cd('D:\work\demo\industrial-vision')
matlab_bridge_server
```

4. 服务将监听 `tcp://127.0.0.1:5555`，MATLAB 命令窗口会显示：

```
[matlab_bridge_server] Bridge server started on tcp://127.0.0.1:5555
```

5. 服务阻塞 MATLAB 命令窗口，直到收到 SHUTDOWN 或 Ctrl+C。

### 3.2 配置环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_ZMQ_ADDRESS` | `tcp://127.0.0.1:5555` | ZMQ 绑定地址 |
| `CSAM_ZMQ_TIMEOUT_MS` | `30000` | 请求超时（毫秒） |

可在启动前于 MATLAB 中设置：

```matlab
setenv('CSAM_ZMQ_ADDRESS', 'tcp://127.0.0.1:5555');
```

---

## 4. 验证清单

启动 MATLAB 服务后，按以下清单逐项验证：

### 4.1 MATLAB 工作目录与搜索路径

```matlab
pwd                          % 应为 D:\work\demo\industrial-vision
exist('matlab_bridge_server', 'file')   % 应返回 2（文件存在）
```

### 4.2 Python 连通性

```matlab
pyenv
py.sys.version               % 应显示 Python 3.x
```

### 4.3 算法文件加载

```matlab
% 路径规划算法（7 个）
exist('generate_path', 'file')          % 应返回 2
exist('layer_slice', 'file')            % 应返回 2
exist('aStarSearch', 'file')            % 应返回 2

% 形貌预测算法（12 个）
exist('particle_fitting', 'file')       % 应返回 2
exist('profile_predict', 'file')        % 应返回 2
```

### 4.4 工具箱可用性

```matlab
license('test', 'MAP_Toolbox')          % Mapping Toolbox
license('test', 'Curve_Fitting_Toolbox') % Curve Fitting Toolbox
```

### 4.5 ZeroMQ 连通性（从 Python 侧）

在另一个终端运行：

```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "import zmq; ctx=zmq.Context(); s=ctx.socket(zmq.REQ); s.connect('tcp://127.0.0.1:5555'); print('connected'); s.close()"
```

应输出 `connected`。

### 4.6 健康检查

```powershell
.\venv\Scripts\python.exe -c "from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient; c=LegacyZmqClient(); c.check_health(lambda ok,msg: print(f'health={ok} {msg}')); c.close()"
```

应输出 `health=True ...`。

### 4.7 算法调用（端到端）

```powershell
.\venv\Scripts\python.exe -c "from repair_app.service.coordination_service import CoordinationService; import numpy as np; svc=CoordinationService(); client=svc.create_zmq_client(); xyz=np.random.rand(100,3).astype(np.float32); n=np.random.rand(100,3).astype(np.float32); req=svc.build_repair_request(xyz,n,material='STEEL_316L',max_layers=1); client.request_repair(req, lambda r: print('status=',r.status_code,'waypoints=',len(r.waypoints))); client.close()"
```

应输出非空航点数。

---

## 5. MATLAB R2025b 已知问题

### 5.1 非法文本字符（"文本字符无效"）

MATLAB R2025b 解析器对 `.m` 文件中的非 ASCII 字符极其严格，即使在注释中也会报错。已修复的字符包括：

- em-dash（—）、en-dash（–）→ ASCII 连字符（-）
- `ö`、`σ`、`×`、`√` → ASCII 等价物
- 全角标点（，（）：）→ 半角标点

**规则**：可执行代码行禁止任何非 ASCII 字符；注释中仅允许 CJK 字符（中文）。

### 5.2 "Java is not enabled" 提示

R2025b 的 `version('-java')` 输出中包含 "Java is not enabled" 字样，这是显示文本而非实际状态。验证 Java 是否真正可用：

```matlab
usejava('jvm')                          % 应返回 1（逻辑真）
exist('java.net.ServerSocket', 'class') % 应返回 8（类存在）
```

### 5.3 禁止的命令

服务上下文中禁止使用以下命令（会导致工作区/数据丢失）：

- `clear all`
- `close all`
- `fclose all`

---

## 6. 故障排查

| 症状 | 可能原因 | 解决方案 |
|------|----------|----------|
| MATLAB 启动时报"文本字符无效" | `.m` 文件含非 ASCII 字符 | 检查算法文件，替换为 ASCII 等价物 |
| Python 连接 ZMQ 超时 | MATLAB 服务未启动 / 端口被占 | 确认 `matlab_bridge_server` 已运行；检查 5555 端口 |
| `pyenv` 报错找不到模块 | Python 路径未配置或依赖缺失 | 重新设置 `pyenv`，确认 venv 已安装 pyzmq/protobuf |
| 算法返回 ERR_DEPS | 缺少工具箱 | 安装 Mapping Toolbox / Curve Fitting Toolbox |
| 健康检查返回 DEGRADED | 部分工具箱缺失或内存高 | 检查 `license('test', ...)`，执行 `pack` 释放内存 |
| MATLAB 找不到 matlab_bridge_server | 工作目录错误 | 在 MATLAB 中 cd 到项目根目录后再运行 matlab_bridge_server |

---

## 7. 相关文档

- [COMMUNICATION.md](COMMUNICATION.md) — 通信架构最终版
- [BRIDGE_ARCHITECTURE.md](BRIDGE_ARCHITECTURE.md) — Bridge 层架构
- [MATLAB_CALL_GRAPH.md](MATLAB_CALL_GRAPH.md) — MATLAB 算法调用图
- [archive/](archive/) — 历史文档归档
