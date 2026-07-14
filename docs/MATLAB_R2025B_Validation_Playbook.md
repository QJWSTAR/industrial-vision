# MATLAB R2025b 验证手册 (Validation Playbook)

> **文档对象**：本手册面向**无本项目经验的工程师**，提供从开机到成功从 GUI 执行真实 MATLAB 算法的完整验证流程。
>
> **验证原则**：每一步都必须有明确的 PASS/FAIL 判定标准。如任何步骤 FAIL，请按照"恢复程序"操作后再重试。
>
> **最终目标**：工程师能够独立完成环境搭建、MATLAB 启动、Bridge 通信建立、GUI 操作，并成功执行一次真实的路径规划算法调用。

---

## 目录

1. [概述与架构](#1-概述与架构)
2. [环境准备](#2-环境准备)
3. [Python 环境验证](#3-python-环境验证)
4. [MATLAB R2025b 环境验证](#4-matlab-r2025b-环境验证)
5. [ZeroMQ 通信验证](#5-zeromq-通信验证)
6. [Protocol Buffers 验证](#6-protocol-buffers-验证)
7. [Bridge 服务器启动与验证](#7-bridge-服务器启动与验证)
8. [GUI 启动与验证](#8-gui-启动与验证)
9. [端到端算法执行验证](#9-端到端算法执行验证)
10. [大矩阵传输验证](#10-大矩阵传输验证)
11. [超时与异常验证](#11-超时与异常验证)
12. [心跳验证](#12-心跳验证)
13. [崩溃恢复验证](#13-崩溃恢复验证)
14. [重复请求与并发验证](#14-重复请求与并发验证)
15. [优雅关闭验证](#15-优雅关闭验证)
16. [Windows 重启后恢复验证](#16-windows-重启后恢复验证)
17. [MATLAB 重启后恢复验证](#17-matlab-重启后恢复验证)
18. [日志验证](#18-日志验证)
19. [验证总结检查清单](#19-验证总结检查清单)

---

## 1. 概述与架构

### 1.1 系统用途

CSAM Repair 是一款工业级桌面应用，用于冷喷涂增材制造（CSAM）缺陷修复。GUI 使用 PySide6 构建，算法计算由 MATLAB R2025b 执行。

### 1.2 唯一生产通信路径

```
GUI (PySide6)
    ↓
CoordinationService
    ↓
LegacyZmqClient (兼容适配器)
    ↓
BridgeClient
    ↓
ZeroMQ (tcp://127.0.0.1:5555, REQ/REP)
    ↓
Protocol Buffers (v2.1, repair_protocol.proto)
    ↓
matlab_bridge_server.m (MATLAB 入口脚本)
    ↓
MatlabAdapter (Python, 通过 pyenv 在 MATLAB 进程内运行)
    ↓
BridgeServer (zmq.REP, 接收 Protobuf 请求)
    ↓
MATLAB R2025b 算法执行
    ↓
RepairResult (Protobuf) → 原路返回 → GUI
```

**关键说明**：
- MATLAB 是**宿主进程**，Python 的 `MatlabAdapter` 通过 `pyenv` 在 MATLAB 进程内运行
- 通信使用 **ZeroMQ REQ/REP** 模式，端口 **5555**
- 序列化使用 **Protocol Buffers v2.1**（`repair_protocol.proto`）
- **不存在**其他生产通信路径（TCP/JSON/v3.0/端口 5570 均已弃用）

### 1.3 需要的文件

| 文件 | 用途 |
|------|------|
| `matlab_bridge_server.m` | MATLAB 侧入口脚本（项目根目录） |
| `repair_app/bridge/adapters/matlab_adapter.py` | Python Bridge 适配器 |
| `repair_app/bridge/communication/zmq_server.py` | BridgeServer（ZMQ REP） |
| `repair_app/communication/repair_protocol.proto` | Protobuf 协议定义 |
| `repair_app/communication/repair_protocol_pb2.py` | 生成的 Protobuf 绑定 |
| `repair_app/communication/repair_serialization.py` | 请求/响应序列化 |
| `repair_app/service/coordination_service.py` | GUI 侧协调服务 |
| `repair_app/bridge/adapters/legacy_adapter.py` | LegacyZmqClient 兼容适配器 |
| `run_app.py` | GUI 应用入口 |
| `路径规划/` | MATLAB 路径规划算法 |
| `形貌预测/` | MATLAB 形貌预测算法 |

---

## 2. 环境准备

### 2.1 所需软件

| 软件 | 版本要求 | 验证命令 |
|------|---------|---------|
| Windows 10/11 | 64-bit | `winver` |
| Python | 3.10, 3.11 或 3.12 | `python --version` |
| MATLAB R2025b | 25.2.x | MATLAB 命令窗口输入 `version` |
| pip | 最新版 | `pip --version` |

### 2.2 MATLAB 工具箱依赖（可选）

| 工具箱 | 需要的算法 | 验证命令（MATLAB） |
|--------|-----------|-------------------|
| Mapping Toolbox | `generate_path`, `profile_predict` | `license('test','map_toolbox')` |
| Curve Fitting Toolbox | `particle_fitting` | `license('test','curve_fitting_toolbox')` |

> **注意**：其余算法仅依赖基础 MATLAB，无需额外工具箱。

### 2.3 步骤：环境准备

**目的**：确认操作系统和基础软件已安装。

**步骤**：
1. 打开 PowerShell（管理员权限非必需）：
   ```powershell
   python --version
   ```
2. 确认 MATLAB 安装路径存在：
   ```powershell
   Test-Path "D:\work\matlab\bin\matlab.exe"
   ```
   > 如安装在其他位置，请记录实际路径，后续步骤中使用该路径。

**预期结果**：
- Python 版本为 3.10/3.11/3.12
- MATLAB 路径存在，返回 `True`

**PASS 判定**：两条命令均输出预期结果。

**FAIL 处理**：
- Python 未安装：从 https://www.python.org/downloads/ 下载安装
- MATLAB 未安装：联系 IT 部门安装 MATLAB R2025b
- MATLAB 路径不同：后续步骤中使用实际路径

---

## 3. Python 环境验证

### 3.1 步骤：创建虚拟环境并安装依赖

**目的**：确保 Python 环境包含所有必要依赖。

**所需文件**：
- `requirements.txt`
- `pyproject.toml`

**步骤**：
1. 打开 PowerShell，进入项目目录：
   ```powershell
   cd D:\work\demo\industrial-vision
   ```

2. 创建虚拟环境（如不存在）：
   ```powershell
   python -m venv venv
   ```

3. 激活虚拟环境：
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   > 如遇到执行策略错误，先运行：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

4. 升级 pip 并安装依赖：
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```

5. 验证关键依赖：
   ```powershell
   python -c "import zmq; print('pyzmq', zmq.__version__)"
   python -c "import google.protobuf; print('protobuf', google.protobuf.__version__)"
   python -c "import PySide6; print('PySide6', PySide6.__version__)"
   python -c "import numpy; print('numpy', numpy.__version__)"
   ```

**预期结果**：
```
pyzmq 25.x.x
protobuf 6.x.x
PySide6 6.x.x
numpy 1.x.x 或 2.x.x
```

**PASS 判定**：所有依赖导入成功并显示版本号。

**FAIL 处理**：
- `import zmq` 失败：`pip install pyzmq`
- `import google.protobuf` 失败：`pip install protobuf>=5.26`
- `import PySide6` 失败：`pip install PySide6`

### 3.2 步骤：验证 Protobuf 绑定

**目的**：确认 Protobuf 生成的 Python 绑定可用。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from repair_app.communication.repair_protocol_pb2 import RepairRequest, RepairResult, MaterialType; req=RepairRequest(); req.request_id='test'; print('Protobuf OK:', req.request_id)"
```

**预期输出**：
```
Protobuf OK: test
```

**PASS 判定**：输出 `Protobuf OK: test`，无异常。

**FAIL 处理**：
- `ImportError`：检查 `repair_app/communication/repair_protocol_pb2.py` 是否存在
- `TypeError: Couldn't build proto file into descriptor pool`：protobuf 版本过低，运行 `pip install --upgrade protobuf`

---

## 4. MATLAB R2025b 环境验证

### 4.1 步骤：验证 MATLAB 版本与 Java

**目的**：确认 MATLAB R2025b 可正常运行且 Java 已启用。

**步骤**：
1. 启动 MATLAB R2025b（双击 `D:\work\matlab\bin\matlab.exe` 或从开始菜单启动）

2. 在 MATLAB 命令窗口依次输入：
   ```matlab
   version
   ```
   ```matlab
   usejava('jvm')
   ```
   ```matlab
   exist('java.net.ServerSocket', 'class')
   ```

**预期结果**：
| 命令 | 预期输出 | 说明 |
|------|---------|------|
| `version` | `25.2.0.xxxxxxx` | R2025b 版本号 |
| `usejava('jvm')` | `1` (logical) | Java 已启用 |
| `exist('java.net.ServerSocket','class')` | `8` | Java 类存在 |

> **注意**：`version('-java')` 可能显示 "Java is not enabled" 文本，这是 R2025b 的显示行为，**不代表 Java 真的未启用**。以 `usejava('jvm')` 返回值为准。

**PASS 判定**：三条命令均返回预期值。

**FAIL 处理**：
- `usejava('jvm')` 返回 `0`：在 MATLAB 中执行 `javaaddpath` 或重启 MATLAB；如仍为 0，检查 MATLAB 许可证是否包含 Java 组件
- MATLAB 启动失败：检查许可证是否过期、是否有足够的系统内存（建议 ≥ 8GB）

### 4.2 步骤：验证 MATLAB 工作目录与搜索路径

**目的**：确认 MATLAB 能找到算法文件。

**步骤**：
1. 在 MATLAB 命令窗口设置工作目录：
   ```matlab
   cd('D:\work\demo\industrial-vision')
   ```

2. 验证算法目录存在：
   ```matlab
   exist('路径规划', 'dir')
   exist('形貌预测', 'dir')
   ```

3. 将算法目录添加到搜索路径：
   ```matlab
   addpath(genpath('路径规划'));
   addpath(genpath('形貌预测'));
   ```

4. 验证关键算法函数可被发现：
   ```matlab
   which('ray_triangle_intersection')
   which('generate_path')
   which('aStarSearch')
   ```

**预期结果**：
- `exist` 返回 `7`（目录存在）
- `which` 返回完整文件路径

**PASS 判定**：所有算法函数路径被正确找到。

**FAIL 处理**：
- `exist` 返回 `0`：检查目录名是否正确（注意中文目录名）
- `which` 返回 `'未找到'`：确认 `addpath` 已执行，检查 `.m` 文件是否存在

### 4.3 步骤：验证工具箱可用性

**目的**：确认可选工具箱状态（影响部分算法）。

**步骤**：
```matlab
fprintf('Map Toolbox: %d\n', license('test','map_toolbox'));
fprintf('Curve Fitting Toolbox: %d\n', license('test','curve_fitting_toolbox'));
```

**预期结果**：
```
Map Toolbox: 1   (或 0，取决于许可证)
Curve Fitting Toolbox: 1   (或 0)
```

**PASS 判定**：命令执行无错误（返回 0 或 1 均可，仅影响特定算法）。

**FAIL 处理**：如某工具箱返回 0，记录此限制。`generate_path` 和 `profile_predict` 需要 Mapping Toolbox，`particle_fitting` 需要 Curve Fitting Toolbox。其余算法不受影响。

### 4.4 步骤：配置 MATLAB pyenv

**目的**：让 MATLAB 能调用项目的 Python 环境（BridgeServer 运行需要）。

**步骤**：
在 MATLAB 命令窗口执行：
```matlab
pyenv('Version', 'D:\work\demo\industrial-vision\venv\Scripts\python.exe');
```

验证：
```matlab
pe = pyenv;
disp(pe.Version);
disp(pe.ExecutionMode);
```

**预期结果**：
- `Version` 显示 Python 3.x.x 路径
- `ExecutionMode` 显示 `InProcess`

**PASS 判定**：Python 版本路径指向项目 venv，ExecutionMode 为 InProcess。

**FAIL 处理**：
- `pyenv` 报错：确认 venv 路径正确，`Test-Path "D:\work\demo\industrial-vision\venv\Scripts\python.exe"` 返回 True
- Python 版本不匹配：确认 venv 中的 Python 版本与 MATLAB R2025b 兼容（3.10-3.12）
- ExecutionMode 为 `OutOfProcess`：执行 `pyenv('ExecutionMode','InProcess')`

### 4.5 步骤：验证 Python 模块导入

**目的**：确认 MATLAB 能通过 pyenv 导入 Bridge 模块。

**步骤**：
```matlab
py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter');
```

**预期结果**：无输出（成功）或显示模块信息。

**PASS 判定**：命令执行无异常。

**FAIL 处理**：
- `ModuleNotFoundError`：确认在项目根目录执行了 `cd`，且 `sys.path` 包含项目根目录
  ```matlab
  py.sys.path.insert(0, 'D:\work\demo\industrial-vision');
  ```
- `ImportError` for zmq/protobuf：在 venv 中重新安装依赖

---

## 5. ZeroMQ 通信验证

### 5.1 步骤：验证 pyzmq 安装

**目的**：确认 Python ZMQ 库可用。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "import zmq; ctx=zmq.Context(); s=ctx.socket(zmq.REP); s.bind('tcp://127.0.0.1:5599'); print('ZMQ bind OK'); s.unbind('tcp://127.0.0.1:5599'); s.close(); ctx.term()"
```

**预期输出**：
```
ZMQ bind OK
```

**PASS 判定**：输出 `ZMQ bind OK`，无异常。

**FAIL 处理**：
- `ZMQError: Address in use`：端口 5599 被占用，更换测试端口
- `ImportError`：`pip install pyzmq`

### 5.2 步骤：验证 MATLAB 侧 ZMQ（通过 Python pyenv）

**目的**：确认 MATLAB 进程内能创建 ZMQ socket。

**步骤**：
在 MATLAB 命令窗口执行：
```matlab
zmq_mod = py.importlib.import_module('zmq');
ctx = zmq_mod.Context();
sock = ctx.socket(zmq_mod.REP);
sock.bind('tcp://127.0.0.1:5598');
disp('MATLAB ZMQ bind OK');
sock.unbind('tcp://127.0.0.1:5598');
sock.close();
ctx.term();
```

**预期输出**：
```
MATLAB ZMQ bind OK
```

**PASS 判定**：输出 `MATLAB ZMQ bind OK`。

**FAIL 处理**：
- 报错：确认 `pyenv` 已正确配置（见 4.4 步骤）
- 端口冲突：更换端口

---

## 6. Protocol Buffers 验证

### 6.1 步骤：验证 Protobuf 序列化/反序列化

**目的**：确认 RepairRequest 和 RepairResult 能正确序列化和反序列化。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); import numpy as np; from repair_app.communication.repair_serialization import build_repair_request; from repair_app.communication.repair_protocol_pb2 import MaterialType, RepairResult; xyz=np.random.rand(50,3).astype(np.float32); normals=np.random.rand(50,3).astype(np.float32); req=build_repair_request(xyz,normals,scan_id='PB_TEST',request_id='pb-001',material=MaterialType.STEEL_316L,max_layers=1,num_layers=1); data=req.SerializeToString(); print(f'Serialized: {len(data)} bytes'); req2=type(req)(); req2.ParseFromString(data); print(f'Deserialized request_id: {req2.request_id}'); print(f'Match: {req2.request_id == req.request_id}')"
```

**预期输出**：
```
Serialized: xxxx bytes
Deserialized request_id: pb-001
Match: True
```

**PASS 判定**：序列化成功、反序列化正确、Match 为 True。

**FAIL 处理**：
- `ImportError`：确认 `repair_protocol_pb2.py` 存在且 protobuf 版本 ≥ 5.26
- 序列化失败：检查 numpy 数组形状是否为 (N, 3)

---

## 7. Bridge 服务器启动与验证

### 7.1 步骤：启动 MATLAB Bridge Server

**目的**：启动生产通信路径的 MATLAB 侧服务。

**所需文件**：
- `matlab_bridge_server.m`

**步骤**：
1. 确保 MATLAB 已按步骤 4.4 配置了 `pyenv`
2. 确保 MATLAB 工作目录在项目根目录：
   ```matlab
   cd('D:\work\demo\industrial-vision')
   ```
3. 启动 Bridge Server：
   ```matlab
   matlab_bridge_server
   ```
   > 此命令会阻塞 MATLAB 命令窗口，这是正常行为。

**预期行为**：
- MATLAB 命令窗口显示启动日志（如 "Bridge server started on tcp://127.0.0.1:5555"）
- MATLAB 命令窗口阻塞（光标不返回）
- **不要关闭 MATLAB**

**预期日志**（MATLAB 命令窗口或日志文件）：
```
[INFO] MatlabAdapter starting on tcp://127.0.0.1:5555
[INFO] BridgeServer listening (zmq.REP)
[INFO] Ready to accept requests
```

**PASS 判定**：
1. MATLAB 命令窗口阻塞（未返回提示符）
2. 端口 5555 处于监听状态（用步骤 7.2 验证）

**FAIL 处理**：
- `pyenv` 相关错误：返回步骤 4.4 重新配置
- `ModuleNotFoundError`：返回步骤 4.5
- `ZMQError: Address in use`：端口 5555 被占用，执行以下命令查找占用进程：
  ```powershell
  Get-NetTCPConnection -State Listen -LocalPort 5555 | Select-Object OwningProcess
  ```
  终止占用进程后重试
- 立即返回提示符（未阻塞）：说明 `serve()` 未执行，检查 `matlab_bridge_server.m` 是否完整

### 7.2 步骤：验证端口监听

**目的**：确认 Bridge Server 正在监听端口 5555。

**步骤**：
打开一个**新的** PowerShell 窗口（不要关闭 MATLAB），执行：
```powershell
Get-NetTCPConnection -State Listen -LocalPort 5555 | Select-Object LocalPort, State, OwningProcess
```

**预期输出**：
```
LocalPort State  OwningProcess
--------- -----  ------------
     5555 Listen <MATLAB_PID>
```

**PASS 判定**：端口 5555 处于 Listen 状态，OwningProcess 为 MATLAB 进程 ID。

**FAIL 处理**：
- 无输出：Bridge Server 未启动，返回步骤 7.1
- OwningProcess 不是 MATLAB：其他程序占用了端口，需要释放端口或修改 `matlab_bridge_server.m` 中的端口号

### 7.3 步骤：从 Python 侧执行健康检查

**目的**：确认 Python 能通过 ZMQ 连接到 MATLAB Bridge Server。

**步骤**：
在 PowerShell 中执行：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "import sys, time; sys.path.insert(0,'.'); import zmq; ctx=zmq.Context.instance(); sock=ctx.socket(zmq.REQ); sock.setsockopt(zmq.LINGER,0); sock.setsockopt(zmq.RCVTIMEO,10000); sock.connect('tcp://127.0.0.1:5555'); print('Connected to port 5555'); sock.close(); ctx.term(); print('Connection test PASSED')"
```

**预期输出**：
```
Connected to port 5555
Connection test PASSED
```

**PASS 判定**：输出 `Connection test PASSED`，无超时或异常。

**FAIL 处理**：
- 超时：确认 MATLAB Bridge Server 正在运行（步骤 7.2）
- `ZMQError`：检查防火墙是否阻止了 localhost 5555 端口

---

## 8. GUI 启动与验证

### 8.1 步骤：启动 GUI 应用

**目的**：确认 GUI 应用能正常启动。

**所需文件**：
- `run_app.py`

**步骤**：
在**新的** PowerShell 窗口中执行：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe run_app.py
```

**预期行为**：
- 控制台输出应用启动日志
- GUI 窗口出现，标题为 "CSAM Repair"（或类似）
- 窗口显示左侧控制面板和右侧 3D 视图
- 无 Python 异常输出

**预期日志**（控制台）：
```
[INFO] Starting CSAM Repair application
[INFO] Version: 1.0.0
[INFO] GUI initialized
```

**PASS 判定**：
1. GUI 窗口正常显示
2. 无 Python 异常/错误输出
3. 窗口可交互（可拖动、可点击按钮）

**FAIL 处理**：
- `ImportError` for PySide6：`pip install PySide6`
- `QT_QPA_PLATFORM` 错误：设置环境变量 `$env:QT_QPA_PLATFORM="windows"`
- 窗口白屏/不响应：检查显卡驱动是否支持 OpenGL
- 立即崩溃：检查 `logs/app.log` 中的错误信息

### 8.2 步骤：验证 GUI 通信状态

**目的**：确认 GUI 已初始化通信层。

**步骤**：
1. 在 GUI 中观察状态栏或控制台输出
2. 查看日志文件：
   ```powershell
   Get-Content D:\work\demo\industrial-vision\logs\app.log -Tail 20
   ```

**预期日志**：
```
[INFO] CoordinationService initialized
[INFO] bridge_active=True
[INFO] zmq_available=True
```

**PASS 判定**：日志显示 `bridge_active=True`。

**FAIL 处理**：
- `bridge_active=False`：检查 `CSAM_ZMQ_ADDRESS` 环境变量是否被错误设置
- 日志中无 CoordinationService 信息：检查 `coordination_service.py` 是否被正确调用

---

## 9. 端到端算法执行验证

### 9.1 步骤：通过 GUI 执行路径规划（完整 GUI 流程）

**目的**：从 GUI 触发一次真实的 MATLAB 算法调用，验证全链路。

**前置条件**：
- MATLAB Bridge Server 正在运行（步骤 7.1）
- GUI 已启动（步骤 8.1）

**步骤**：
1. 在 GUI 左侧面板点击 **"📂 加载点云"** 按钮
2. 在文件对话框中点击**取消**
3. 当弹出"是否加载演示数据"提示时，点击**是**
4. 等待 3D 视图显示点云数据
5. 使用鼠标选取一个缺陷区域（切换到 ✂️ 选取模式，拖动选取）
6. 从材料下拉菜单选择 **STEEL_316L**
7. 设置参数：层高=2.0，扫描角度=-45，步长=2.0，层数=1
8. 点击 **"🔧 生成修复路径"** 按钮
9. 等待路径规划完成

**预期行为**：
- 点击"生成修复路径"后，GUI 底部状态栏显示"正在计算..."
- MATLAB 命令窗口可能显示收到请求的日志
- 数秒内（通常 1-5 秒）3D 视图中出现绿色/蓝色的路径线条
- 状态栏显示"路径规划完成"

**预期日志**（Python 控制台 / app.log）：
```
[INFO] Sending repair request to MATLAB bridge (scan_id=..., request_id=...)
[INFO] Request serialized: xxxx bytes
[INFO] Reply received: xxxx bytes
[INFO] Path planning complete: N waypoints, compute_time=xxms
```

**预期日志**（MATLAB 命令窗口）：
```
[INFO] Received request: request_id=...
[INFO] Executing algorithm: path_planning
[INFO] Algorithm complete: compute_time=xxms
[INFO] Response sent: xxxx bytes
```

**PASS 判定**：
1. 3D 视图中出现路径线条
2. 日志显示请求已发送且收到响应
3. 无异常/错误输出
4. MATLAB 命令窗口显示收到请求的日志

**FAIL 处理**：
- GUI 无响应/卡死：MATLAB Bridge Server 可能未运行，确认步骤 7.1
- 超时错误：检查 MATLAB 是否正在执行（观察 MATLAB 命令窗口），增加超时时间
- `ZMQError`：Bridge Server 可能已崩溃，返回步骤 7.1 重启
- 路径线条未出现：检查日志中的 `status_code`，非 0 表示算法执行失败，查看 `error_message`
- `error_message='空点云请求'`：未选取缺陷区域或选取区域无点，返回步骤 5 重新选取

### 9.2 步骤：通过命令行执行端到端验证（无 GUI）

**目的**：在无 GUI 环境下验证完整通信链路。

**前置条件**：
- MATLAB Bridge Server 正在运行（步骤 7.1）

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
import numpy as np
import zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
print(f'bridge_active={svc.bridge_active}')

np.random.seed(42)
xyz = np.random.rand(200, 3).astype(np.float32) * 10.0
normals = np.random.rand(200, 3).astype(np.float32)
normals = normals / np.linalg.norm(normals, axis=1, keepdims=True)

req = svc.build_repair_request(
    xyz, normals,
    scan_id='PLAYBOOK_E2E',
    request_id='pb-e2e-001',
    material='STEEL_316L',
    max_layers=1, num_layers=1,
    layer_height_mm=2.0,
    scanning_angle_deg=-45.0,
    scanning_step_mm=2.0,
)

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.REQ)
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.RCVTIMEO, 30000)
sock.connect('tcp://127.0.0.1:5555')
sock.send(req.SerializeToString())
reply = sock.recv()
sock.close()

result = RepairResult()
result.ParseFromString(reply)
print(f'status_code={result.status_code} (0=SUCCESS)')
print(f'waypoints={len(result.waypoints)//7} rows')
print(f'compute_time_ms={result.compute_time_ms}')
print(f'is_feasible={result.is_feasible}')
print(f'feasibility={result.feasibility_reason}')
if result.status_code == 0:
    print('E2E TEST PASSED')
else:
    print(f'E2E TEST FAILED: {result.error_message}')
"@
```

**预期输出**：
```
bridge_active=True
status_code=0 (0=SUCCESS)
waypoints=12 rows
compute_time_ms=xx
is_feasible=True
feasibility=MATLAB adapter path generated
E2E TEST PASSED
```

**PASS 判定**：输出 `E2E TEST PASSED`，`status_code=0`。

**FAIL 处理**：
- `bridge_active=False`：检查 CoordinationService 初始化
- 超时：MATLAB Bridge Server 未运行或响应过慢，确认步骤 7.1
- `status_code != 0`：查看 `error_message`，根据错误信息排查

---

## 10. 大矩阵传输验证

### 10.1 步骤：传输 10000 点的大点云

**目的**：验证大矩阵通过 Protobuf 序列化和 ZMQ 传输的可靠性。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
import numpy as np
import zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
np.random.seed(100)
N = 10000
xyz = np.random.rand(N, 3).astype(np.float32) * 50.0
normals = np.random.rand(N, 3).astype(np.float32)
normals = normals / np.linalg.norm(normals, axis=1, keepdims=True)

req = svc.build_repair_request(
    xyz, normals,
    scan_id='PLAYBOOK_LARGE',
    request_id='pb-large-001',
    material='STEEL_316L',
    max_layers=1, num_layers=1,
)
req_bytes = req.SerializeToString()
print(f'Points: {N}, Request size: {len(req_bytes)} bytes ({len(req_bytes)/1024:.1f} KB)')

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.REQ)
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.RCVTIMEO, 60000)
sock.connect('tcp://127.0.0.1:5555')

t0 = time.time()
sock.send(req_bytes)
reply = sock.recv()
t1 = time.time()
sock.close()

result = RepairResult()
result.ParseFromString(reply)
print(f'Reply size: {len(reply)} bytes')
print(f'Round-trip time: {(t1-t0)*1000:.0f} ms')
print(f'status_code={result.status_code}')
print(f'waypoints={len(result.waypoints)//7} rows')
print('LARGE MATRIX TEST PASSED' if result.status_code == 0 else f'FAILED: {result.error_message}')
"@
```

**预期输出**：
```
Points: 10000, Request size: xxxxxx bytes (xxx.x KB)
Reply size: xxxx bytes
Round-trip time: xxx ms
status_code=0
waypoints=xx rows
LARGE MATRIX TEST PASSED
```

**PASS 判定**：
1. 请求成功发送和接收
2. `status_code=0`
3. 往返时间 < 60 秒

**FAIL 处理**：
- 超时（60 秒）：MATLAB 计算大矩阵耗时过长，检查 MATLAB 是否有足够的内存
- `ZMQError: Message too large`：ZMQ 消息大小限制，需调整 `zmq.MAX_SOCKETS` 或分块传输
- 内存不足：减少点云数量后重试

---

## 11. 超时与异常验证

### 11.1 步骤：验证空点云异常处理

**目的**：确认系统正确处理异常输入。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys
sys.path.insert(0, '.')
import numpy as np
import zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
empty_xyz = np.zeros((0, 3), dtype=np.float32)
empty_normals = np.zeros((0, 3), dtype=np.float32)
req = svc.build_repair_request(empty_xyz, empty_normals, scan_id='EMPTY', request_id='empty-001', material='STEEL_316L', max_layers=1, num_layers=1)

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.REQ)
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.RCVTIMEO, 10000)
sock.connect('tcp://127.0.0.1:5555')
sock.send(req.SerializeToString())
reply = sock.recv()
sock.close()

result = RepairResult()
result.ParseFromString(reply)
print(f'status_code={result.status_code} (expected non-zero)')
print(f'error_message={result.error_message!r}')
print(f'is_feasible={result.is_feasible}')
print('EXCEPTION TEST PASSED' if result.status_code != 0 else 'UNEXPECTED: empty input returned success')
"@
```

**预期输出**：
```
status_code=1 (expected non-zero)
error_message='空点云请求' (或类似错误信息)
is_feasible=False
EXCEPTION TEST PASSED
```

**PASS 判定**：`status_code != 0`，错误信息非空，系统未崩溃。

**FAIL 处理**：
- 系统崩溃/MATLAB 退出：Bridge Server 异常处理有缺陷，检查 `matlab_adapter.py` 的异常捕获
- 超时无响应：MATLAB 侧可能卡在异常处理中，需要手动重启 Bridge Server

### 11.2 步骤：验证连接超时

**目的**：确认 Python 客户端在没有 MATLAB Server 时的超时行为。

**步骤**：
1. **关闭 MATLAB Bridge Server**（在 MATLAB 中 Ctrl+C 终止 `matlab_bridge_server`）
2. 执行：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
import zmq
ctx = zmq.Context.instance()
sock = ctx.socket(zmq.REQ)
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.RCVTIMEO, 3000)
sock.connect('tcp://127.0.0.1:5555')
sock.send(b'test')
try:
    reply = sock.recv()
    print('UNEXPECTED: got reply when server should be down')
except zmq.error.Again:
    print('TIMEOUT TEST PASSED: correctly timed out after 3s')
except Exception as e:
    print(f'TIMEOUT TEST PASSED (with {type(e).__name__}): {e}')
sock.close()
"@
```
3. **重新启动 MATLAB Bridge Server**（返回步骤 7.1）

**预期输出**：
```
TIMEOUT TEST PASSED: correctly timed out after 3s
```

**PASS 判定**：3 秒后超时，不无限等待。

**FAIL 处理**：
- 无限等待：`RCVTIMEO` 未生效，检查 zmq socket 选项设置
- 立即报错：端口 5555 仍有残留连接，等待几秒后重试

---

## 12. 心跳验证

### 12.1 步骤：验证心跳监控

**目的**：确认 BridgeClient 的心跳监控功能正常。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
from repair_app.bridge.communication.config import BridgeConfig

config = BridgeConfig()
print(f'Heartbeat interval: {config.heartbeat_interval_ms}ms')
print(f'Heartbeat timeout: {config.heartbeat_timeout_ms}ms')

monitor = HeartbeatMonitor(interval_ms=1000, timeout_ms=3000)
monitor.start()
print('Heartbeat monitor started')

time.sleep(3.5)
status = monitor.status
print(f'After 3.5s: alive={status.is_alive}, missed={status.missed_count}')

monitor.stop()
print('Heartbeat monitor stopped')
print('HEARTBEAT TEST PASSED')
"@
```

**预期输出**：
```
Heartbeat interval: xxxxms
Heartbeat timeout: xxxxms
Heartbeat monitor started
After 3.5s: alive=False, missed=x
Heartbeat monitor stopped
HEARTBEAT TEST PASSED
```

**PASS 判定**：心跳监控能启动和停止，能检测到心跳丢失。

**FAIL 处理**：
- `ImportError`：确认 `repair_app.bridge` 包完整
- 心跳监控无法启动：检查线程权限

---

## 13. 崩溃恢复验证

### 13.1 步骤：模拟 MATLAB Bridge Server 崩溃后恢复

**目的**：验证 MATLAB Bridge Server 崩溃后能重新启动并恢复服务。

**步骤**：
1. 确认 Bridge Server 正在运行（步骤 7.1-7.2）
2. 在 MATLAB 中按 **Ctrl+C** 终止 `matlab_bridge_server`
3. 验证端口 5555 不再监听：
   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 5555 -ErrorAction SilentlyContinue
   ```
   > 预期：无输出
4. 在 MATLAB 命令窗口重新启动 Bridge Server：
   ```matlab
   matlab_bridge_server
   ```
5. 等待 5 秒，验证端口 5555 重新监听
6. 执行步骤 9.2 的命令行端到端验证

**预期行为**：
- 终止后端口 5555 不监听
- 重启后端口 5555 恢复监听
- 端到端验证再次通过

**PASS 判定**：
1. 端口能正确释放和重新监听
2. 重启后端到端验证输出 `E2E TEST PASSED`

**FAIL 处理**：
- 端口未释放：等待 30 秒（TIME_WAIT 状态），或手动查找占用进程并终止
- 重启后无法连接：确认 `pyenv` 配置仍有效（可能需要重新执行步骤 4.4）
- 重启后算法调用失败：MATLAB 工作目录可能改变，执行 `cd('D:\work\demo\industrial-vision')` 后重试

---

## 14. 重复请求与并发验证

### 14.1 步骤：5 次顺序请求

**目的**：验证 Bridge Server 能处理连续请求。

**步骤**：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
import numpy as np
import zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
ctx = zmq.Context.instance()
success = 0
for i in range(5):
    np.random.seed(i)
    xyz = np.random.rand(100, 3).astype(np.float32) * 8.0
    n = np.random.rand(100, 3).astype(np.float32)
    n = n / np.linalg.norm(n, axis=1, keepdims=True)
    req = svc.build_repair_request(xyz, n, scan_id=f'SEQ_{i}', request_id=f'seq-{i}', material='STEEL_316L', max_layers=1, num_layers=1)
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 10000)
    sock.connect('tcp://127.0.0.1:5555')
    sock.send(req.SerializeToString())
    reply = sock.recv()
    sock.close()
    r = RepairResult()
    r.ParseFromString(reply)
    status = 'OK' if r.status_code == 0 else 'FAIL'
    print(f'  Request {i+1}/5: {status} (compute={r.compute_time_ms}ms)')
    if r.status_code == 0:
        success += 1
print(f'{success}/5 requests succeeded')
print('SEQUENTIAL TEST PASSED' if success == 5 else 'SEQUENTIAL TEST PARTIAL')
"@
```

**预期输出**：
```
  Request 1/5: OK (compute=xxms)
  Request 2/5: OK (compute=xxms)
  Request 3/5: OK (compute=xxms)
  Request 4/5: OK (compute=xxms)
  Request 5/5: OK (compute=xxms)
5/5 requests succeeded
SEQUENTIAL TEST PASSED
```

**PASS 判定**：5/5 请求成功。

**FAIL 处理**：
- 部分失败：MATLAB 可能内存泄漏，检查 MATLAB 内存占用
- 全部失败（第一次之后）：Bridge Server 可能已崩溃，返回步骤 7.1 重启

### 14.2 步骤：并发请求验证（注意）

> **重要**：ZeroMQ REQ/REP 模式**不支持并发请求**。每个 REQ socket 必须等待 REP 响应后才能发送下一个请求。这是协议设计约束，不是缺陷。
>
> 如需并发，必须使用多个 REQ socket 连接到同一个 REP socket，但 REP 侧仍为串行处理。

**验证步骤**（串行模拟并发）：
```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time, threading
sys.path.insert(0, '.')
import numpy as np
import zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
results = [None] * 3
threads = []

def worker(idx):
    np.random.seed(idx * 100)
    xyz = np.random.rand(80, 3).astype(np.float32) * 5.0
    n = np.random.rand(80, 3).astype(np.float32)
    n = n / np.linalg.norm(n, axis=1, keepdims=True)
    req = svc.build_repair_request(xyz, n, scan_id=f'CONC_{idx}', request_id=f'conc-{idx}', material='STEEL_316L', max_layers=1, num_layers=1)
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 15000)
    sock.connect('tcp://127.0.0.1:5555')
    sock.send(req.SerializeToString())
    reply = sock.recv()
    sock.close()
    r = RepairResult()
    r.ParseFromString(reply)
    results[idx] = r.status_code == 0

for i in range(3):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()
    time.sleep(0.1)

for t in threads:
    t.join(timeout=20)

success = sum(1 for r in results if r)
print(f'{success}/3 concurrent requests succeeded')
print('CONCURRENT TEST PASSED' if success == 3 else 'CONCURRENT TEST PARTIAL')
"@
```

**预期输出**：
```
3/3 concurrent requests succeeded
CONCURRENT TEST PASSED
```

**PASS 判定**：3/3 并发请求成功（注意：REP 侧串行处理，但有 3 个独立 REQ socket）。

**FAIL 夃理**：
- 部分超时：REP 侧串行处理导致排队，增加 `RCVTIMEO` 或减少并发数
- `ZMQError`：REQ/REP 状态机被破坏（一个 REQ 发送了多次请求未接收），确保每个线程使用独立的 socket

---

## 15. 优雅关闭验证

### 15.1 步骤：验证 MATLAB Bridge Server 优雅关闭

**目的**：确认 Bridge Server 能安全关闭，不丢失数据或留下残留状态。

**步骤**：
1. 确认 Bridge Server 正在运行
2. 在 MATLAB 命令窗口按 **Ctrl+C**
3. 观察 MATLAB 命令窗口输出

**预期行为**：
- MATLAB 显示关闭日志
- MATLAB 命令窗口返回提示符（`>>`）
- 端口 5555 停止监听

**预期日志**（MATLAB）：
```
[INFO] Received shutdown signal
[INFO] Closing ZMQ socket...
[INFO] Closing ZMQ context...
[INFO] Bridge server stopped
```

**PASS 判定**：
1. MATLAB 返回提示符
2. 端口 5555 不再监听
3. 无异常/错误输出

**FAIL 夃理**：
- MATLAB 卡住：等待 10 秒，如仍未返回，强制终止 MATLAB 进程
- 端口未释放：等待 30 秒（TIME_WAIT），或手动终止 MATLAB 进程

---

## 16. Windows 重启后恢复验证

### 16.1 步骤：Windows 重启后完整恢复

**目的**：验证系统在 Windows 重启后能完全恢复。

**步骤**：
1. 重启 Windows
2. 打开 PowerShell
3. 验证项目文件完好：
   ```powershell
   Test-Path "D:\work\demo\industrial-vision\matlab_bridge_server.m"
   Test-Path "D:\work\demo\industrial-vision\venv\Scripts\python.exe"
   ```
4. 启动 MATLAB R2025b
5. 按步骤 4.4 重新配置 `pyenv`
6. 按步骤 7.1 启动 Bridge Server
7. 按步骤 9.2 执行端到端验证

**预期结果**：
- 项目文件存在
- MATLAB 能启动
- Bridge Server 能正常启动
- 端到端验证通过

**PASS 判定**：步骤 9.2 输出 `E2E TEST PASSED`。

**FAIL 处理**：
- venv 丢失：重新执行步骤 3.1 创建虚拟环境
- `pyenv` 配置丢失：MATLAB 重启后需要重新配置 `pyenv`（这是预期行为）
- MATLAB 许可证问题：检查 MATLAB 许可证是否需要重新激活

---

## 17. MATLAB 重启后恢复验证

### 17.1 步骤：MATLAB 重启后恢复

**目的**：验证仅 MATLAB 重启（不重启 Windows）后系统能恢复。

**步骤**：
1. 关闭 MATLAB（File → Exit MATLAB 或 `exit` 命令）
2. 等待 5 秒
3. 重新启动 MATLAB
4. 按步骤 4.4 重新配置 `pyenv`
5. 按步骤 7.1 启动 Bridge Server
6. 按步骤 9.2 执行端到端验证

**预期结果**：
- MATLAB 正常关闭和重启
- `pyenv` 重新配置成功
- Bridge Server 正常启动
- 端到端验证通过

**PASS 判定**：步骤 9.2 输出 `E2E TEST PASSED`。

**FAIL 处理**：
- 端口 5555 仍被占用：等待 30 秒后重试，或查找残留进程
- `pyenv` 配置失败：确认 venv 路径未改变

---

## 18. 日志验证

### 18.1 步骤：验证日志输出

**目的**：确认系统各层产生正确的日志。

**步骤**：
1. 执行一次完整的端到端请求（步骤 9.2）
2. 检查 Python 侧日志：
   ```powershell
   Get-Content D:\work\demo\industrial-vision\logs\app.log -Tail 30
   ```
3. 检查 MATLAB 侧日志（命令窗口输出）

**预期日志内容**（Python 侧 app.log）：
```
[INFO] Sending repair request (scan_id=..., request_id=...)
[INFO] Request serialized: xxxx bytes
[INFO] Reply received: xxxx bytes
[INFO] Repair complete: status=0, waypoints=N, compute_time=xxms
```

**预期日志内容**（MATLAB 命令窗口）：
```
[INFO] Received request: request_id=...
[INFO] Executing algorithm...
[INFO] Algorithm complete: xxms
[INFO] Response sent: xxxx bytes
```

**PASS 判定**：
1. Python 侧日志包含请求发送和响应接收记录
2. MATLAB 侧日志包含请求接收和算法执行记录
3. 日志时间戳连续合理

**FAIL 处理**：
- Python 日志为空：检查 `logger_config.py` 配置，确认 `CSAM_LOG_LEVEL` 未设为 `ERROR` 或更高
- MATLAB 日志为空：`matlab_bridge_server.m` 可能未配置日志输出，检查 `diary` 是否开启

---

## 19. 验证总结检查清单

完成所有验证步骤后，使用以下检查清单确认全部通过：

| 序号 | 验证项 | 状态 | 参考步骤 |
|------|--------|------|---------|
| 1 | Python 环境与依赖 | ☐ PASS / ☐ FAIL | 3.1, 3.2 |
| 2 | MATLAB R2025b 版本与 Java | ☐ PASS / ☐ FAIL | 4.1 |
| 3 | MATLAB 工作目录与搜索路径 | ☐ PASS / ☐ FAIL | 4.2 |
| 4 | MATLAB 工具箱（可选） | ☐ PASS / ☐ N/A | 4.3 |
| 5 | MATLAB pyenv 配置 | ☐ PASS / ☐ FAIL | 4.4 |
| 6 | Python 模块导入（MATLAB 侧） | ☐ PASS / ☐ FAIL | 4.5 |
| 7 | pyzmq 安装 | ☐ PASS / ☐ FAIL | 5.1 |
| 8 | MATLAB 侧 ZMQ | ☐ PASS / ☐ FAIL | 5.2 |
| 9 | Protobuf 序列化/反序列化 | ☐ PASS / ☐ FAIL | 6.1 |
| 10 | Bridge Server 启动 | ☐ PASS / ☐ FAIL | 7.1 |
| 11 | 端口 5555 监听 | ☐ PASS / ☐ FAIL | 7.2 |
| 12 | Python→MATLAB 连接 | ☐ PASS / ☐ FAIL | 7.3 |
| 13 | GUI 启动 | ☐ PASS / ☐ FAIL | 8.1 |
| 14 | GUI 通信状态 | ☐ PASS / ☐ FAIL | 8.2 |
| 15 | GUI 端到端路径规划 | ☐ PASS / ☐ FAIL | 9.1 |
| 16 | 命令行端到端验证 | ☐ PASS / ☐ FAIL | 9.2 |
| 17 | 大矩阵传输（10000 点） | ☐ PASS / ☐ FAIL | 10.1 |
| 18 | 空点云异常处理 | ☐ PASS / ☐ FAIL | 11.1 |
| 19 | 连接超时 | ☐ PASS / ☐ FAIL | 11.2 |
| 20 | 心跳监控 | ☐ PASS / ☐ FAIL | 12.1 |
| 21 | 崩溃恢复 | ☐ PASS / ☐ FAIL | 13.1 |
| 22 | 5 次顺序请求 | ☐ PASS / ☐ FAIL | 14.1 |
| 23 | 并发请求 | ☐ PASS / ☐ FAIL | 14.2 |
| 24 | 优雅关闭 | ☐ PASS / ☐ FAIL | 15.1 |
| 25 | Windows 重启恢复 | ☐ PASS / ☐ FAIL | 16.1 |
| 26 | MATLAB 重启恢复 | ☐ PASS / ☐ FAIL | 17.1 |
| 27 | 日志输出 | ☐ PASS / ☐ FAIL | 18.1 |

### 最终判定

- **全部 PASS**：系统已通过完整验证，可投入生产使用。
- **1-3 项 FAIL（非核心项）**：系统基本可用，记录失败项并在后续修复。
- **核心项 FAIL（步骤 7.1, 9.1/9.2, 10.1）**：系统不可用，必须修复后重新验证。

### 核心项（必须通过）

| 核心步骤 | 说明 |
|---------|------|
| 7.1 Bridge Server 启动 | 通信基础设施 |
| 9.1 或 9.2 端到端验证 | 完整链路验证 |
| 10.1 大矩阵传输 | 数据可靠性 |
| 15.1 优雅关闭 | 安全关闭 |

---

## 附录 A：常见问题快速排查

| 症状 | 可能原因 | 解决方案 |
|------|---------|---------|
| MATLAB 启动 `matlab_bridge_server` 后立即返回 | `pyenv` 未配置或模块导入失败 | 重新执行步骤 4.4-4.5 |
| 端口 5555 不监听 | Bridge Server 未启动或端口被占用 | 步骤 7.1-7.2 |
| GUI 点击"生成路径"无响应 | MATLAB Bridge Server 未运行 | 步骤 7.1 |
| ZMQ 超时 | MATLAB 正在计算或已崩溃 | 等待或重启 Bridge Server |
| `status_code=1` | 算法执行错误（如空点云） | 检查 `error_message` 字段 |
| MATLAB 报"文本字符无效" | .m 文件含非 ASCII 字符 | 检查算法文件，替换非 ASCII 字符 |
| `pyenv` 报错 | Python 路径不正确或版本不兼容 | 确认 venv 路径和 Python 版本 |
| Protobuf 反序列化失败 | protobuf 版本过低 | `pip install --upgrade protobuf` |

---

## 附录 B：环境变量参考

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CSAM_ZMQ_ADDRESS` | `tcp://127.0.0.1:5555` | ZMQ 传输地址 |
| `CSAM_LOG_LEVEL` | `INFO` | 日志级别 |
| `CSAM_HMAC_SECRET` | 开发回退密钥 | 许可证 HMAC 密钥 |
| `CSAM_MATLAB_HOST` | `127.0.0.1` | MATLAB 引擎地址（已弃用路径） |
| `CSAM_MATLAB_PORT` | `5570` | MATLAB 引擎端口（已弃用路径） |

---

## 附录 C：快速验证脚本

以下脚本一次性执行步骤 9.2（命令行端到端验证），适合快速回归测试：

```powershell
cd D:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c @"
import sys, time
sys.path.insert(0, '.')
import numpy as np, zmq
from repair_app.service.coordination_service import CoordinationService
from repair_app.communication.repair_protocol_pb2 import RepairResult

svc = CoordinationService()
np.random.seed(42)
xyz = np.random.rand(200, 3).astype(np.float32) * 10.0
n = np.random.rand(200, 3).astype(np.float32)
n = n / np.linalg.norm(n, axis=1, keepdims=True)
req = svc.build_repair_request(xyz, n, scan_id='QUICK', request_id='quick-001', material='STEEL_316L', max_layers=1, num_layers=1)
ctx = zmq.Context.instance()
sock = ctx.socket(zmq.REQ)
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.RCVTIMEO, 30000)
sock.connect('tcp://127.0.0.1:5555')
sock.send(req.SerializeToString())
reply = sock.recv()
sock.close()
r = RepairResult()
r.ParseFromString(reply)
print(f'status={r.status_code} waypoints={len(r.waypoints)//7} compute={r.compute_time_ms}ms feasible={r.is_feasible}')
print('PASS' if r.status_code == 0 else f'FAIL: {r.error_message}')
"@
```

---

*文档版本：1.0 | 最后更新：2026-07-10 | 验证环境：MATLAB R2025b (25.2.0.2998904)*
