# MATLAB 环境测试详细步骤

> 目标：在真实 MATLAB 环境中验证 MATLAB Server 全链路（启动 → 通信 → 算法 → 关闭）
> 对应 RC Report P0 项：V1.0.1 验证

---

## 测试前置条件

### 软件要求

| 组件 | 版本 | 用途 |
|------|------|------|
| MATLAB | R2018b+（推荐 R2024b） | 算法运行 |
| Mapping Toolbox | 任意 | generate_path / profile_predict / layer_slice 等 7 个算法 |
| Curve Fitting Toolbox | 任意 | particle_fitting |
| Python | 3.10-3.12 | 客户端验证 |
| Java | 11+（MATLAB R2019a+ 自带） | ServerSocket 传输 |

### 端口要求
- TCP 5570（默认）必须未被占用

### 文件准备
确认以下目录存在且可访问：
```
d:\work\demo\industrial-vision\
├── matlab_server\          ← Server 代码（13 文件）
├── 路径规划\                ← 8 个 .m 算法文件
├── 形貌预测\                ← 15 个 .m 算法文件
└── repair_app\             ← Python 客户端
```

---

## 阶段 1：环境预检（MATLAB 启动前）

### 步骤 1.1 — 检查端口占用

在 Windows PowerShell 中执行：
```powershell
netstat -ano | findstr ":5570"
```
**预期**：无输出（端口空闲）。若有输出，需先释放端口或改用其他端口。

### 步骤 1.2 — 检查 Python 环境
```powershell
cd d:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "from repair_app.engine.matlab_engine import MatlabEngine; print('OK')"
```
**预期**：输出 `OK`

### 步骤 1.3 — 预检 MATLAB 许可证（可选，在 MATLAB 中执行）

打开 MATLAB，在命令窗口执行：
```matlab
fprintf('MATLAB 版本: %s\n', version);
fprintf('Map Toolbox: %d\n', license('test', 'Map_Toolbox'));
fprintf('Curve Fitting: %d\n', license('test', 'Curve_Fitting_Toolbox'));
fprintf('Java 版本: %s\n', version('-java'));
```
**预期输出**：
```
MATLAB 版本: 24.2.0.xxxxxxxx (R2024b)
Map Toolbox: 1
Curve Fitting: 1
Java 版本: Java 11.x.x ...
```
- `1` = 可用，`0` = 不可用
- Java 必须为 11+（R2019a+ 默认满足）
- 若工具箱为 0，对应算法会返回 `ERR_DEPS`，但不影响其他算法

---

## 阶段 2：启动 MATLAB Server

### 步骤 2.1 — 启动 Server

在 MATLAB 命令窗口执行：
```matlab
cd('D:\work\demo\industrial-vision\matlab_server')
startup
```

**预期输出**：
```
  addpath: D:\work\demo\industrial-vision\路径规划
  addpath: D:\work\demo\industrial-vision\形貌预测
CSAM MATLAB Server starting on tcp://*:5570 (port 5570), protocol v3.0
[info] server.startup request_id= ts=... event=server_starting bind=tcp://*:5570
[info] server.run request_id= ts=... event=listening port=5570
[info] server.run request_id= ts=... event=ready algorithms=19
```

**关键确认**：
- `addpath` 两行都出现（路径规划和形貌预测目录都被加载）
- `event=ready` 出现（Server 就绪）
- `algorithms=19`（19 个算法注册成功）
- 命令窗口**阻塞**（Server 在运行，这是正常的）

### 步骤 2.2 — 排查启动失败

| 症状 | 原因 | 解决 |
|------|------|------|
| `Path-planning directory not found` | 目录名编码问题 | 确认 `路径规划\layer_slice.m` 存在 |
| `Morphology directory not found` | 同上 | 确认 `形貌预测\profilePredict.m` 存在 |
| `Port 5570 already in use` | 端口被占 | `setenv('CSAM_MATLAB_BIND','tcp://*:5571')` 后重新 `startup` |
| `algorithms=0` | 注册失败 | 检查 `register_algorithms.m` 是否有语法错误 |

### 步骤 2.3 — 自定义端口（如需）

若 5570 被占用，在启动前设置环境变量：
```matlab
setenv('CSAM_MATLAB_BIND', 'tcp://*:5571');
setenv('CSAM_MATLAB_LOG_LEVEL', 'debug');  % 调试时用 debug
startup
```

---

## 阶段 3：连通性验证（Python → MATLAB）

### 步骤 3.1 — 健康检查

**新开**一个 PowerShell 窗口（保持 MATLAB 运行）：
```powershell
cd d:\work\demo\industrial-vision
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=5000)
print('连接:', eng.check_health())
print('健康详情:', eng.get_health_status())
eng.close()
"
```

**预期输出**：
```
连接: True
健康详情: {'state': 0, 'server_version': 'matlab-server-3.0.0', 'matlab_version': '24.2.0...', 'memory_mb': xxx, 'uptime_s': x, 'pending_reqs': 0, 'toolbox_available': {'Map_Toolbox': True, 'Curve_Fitting_Toolbox': True}, 'error_rate_1m': 0.0, 'total_requests': 1}
```

**验证点**：
- `连接: True`
- `state: 0`（OK）
- `toolbox_available` 两个工具箱都为 `True`（若为 False，对应算法将不可用）

### 步骤 3.2 — 心跳验证
```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570)
pong = eng.heartbeat()
print('心跳响应:', pong)
eng.close()
"
```
**预期**：`心跳响应: {'request_id': '...', 'server_ts_ms': xxxx, 'pending': 0}`

### 步骤 3.3 — 算法列表发现
```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570)
algos = eng.list_algorithms()
print(f'算法总数: {len(algos)}')
for a in algos:
    print(f'  {a[\"name\"]:45s} v{a.get(\"version\",\"?\")} [{a.get(\"category\",\"\")}]')
eng.close()
"
```
**预期**：列出 19 个算法（path_planning.* 7 个 + morphology.* 12 个）

### 步骤 3.4 — 版本协商
```powershell
.\venv\Scripts\python.exe -c "
import json, socket, struct
env = {'request_id':'t1','timestamp_ms':0,'message_type':'VERSION_NEGOTIATE','protocol_ver':'3.0','payload':{'client_protocol':'3.0','client_app':'test','want_algorithms':[]}}
sock = socket.create_connection(('127.0.0.1',5570), timeout=5)
sock.sendall(struct.pack('>I', len(json.dumps(env).encode())) + json.dumps(env).encode())
hdr = sock.recv(4); n = struct.unpack('>I', hdr)[0]
print(json.loads(sock.recv(n)))
sock.close()
"
```
**预期**：`protocol_compatible: True`，`algorithm_count: 19`

---

## 阶段 4：算法功能验证

### 步骤 4.1 — 简单算法：read_stl_file（无工具箱依赖）

准备一个 STL 文件（仓库自带 `路径规划\part.stl`）：
```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=30000)
result = eng.execute(
    'path_planning.read_stl_file',
    params={'filename': r'D:\work\demo\industrial-vision\路径规划\part.stl'}
)
print('状态:', result.status, '(0=成功)')
print('耗时:', result.compute_time_ms, 'ms')
if result.ok:
    for k, v in result.artifacts.items():
        print(f'  {k}: shape={v.shape}')
else:
    print('错误:', result.error_message)
eng.close()
"
```
**预期**：`状态: 0`，输出 triangles 数组的 shape（如 `(N, 9)`）

### 步骤 4.2 — 中等算法：ray_triangle_intersection（无工具箱依赖）

```powershell
.\venv\Scripts\python.exe -c "
import numpy as np
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=30000)

# 构造一个三角形和一条射线
triangles = np.array([[0,0,0, 1,0,0, 0,1,0, 0,0,0, 1,0,0, 0,1,0, 0,0,0, 1,0,0, 0,1,0]], dtype=np.float64)
rays_origins = np.array([[0.1, 0.1, 1.0]], dtype=np.float64)
rays_directions = np.array([[0, 0, -1.0]], dtype=np.float64)
rays_indices = np.array([1], dtype=np.int32)
tri_candidates = {0: [1]}  # cell 格式由 Server 侧处理

result = eng.execute(
    'morphology.ray_triangle_intersection',
    inputs={
        'rays_indices': rays_indices,
        'rays_origins': rays_origins,
        'rays_directions': rays_directions,
        'triangles': triangles,
    }
)
print('状态:', result.status)
print('耗时:', result.compute_time_ms, 'ms')
if result.ok:
    for k, v in result.artifacts.items():
        print(f'  {k}: {v}')
else:
    print('错误:', result.error_message, result.error_stack[:200] if result.error_stack else '')
eng.close()
"
```
**预期**：`状态: 0`，返回交点信息

### 步骤 4.3 — 工具箱依赖算法：layer_slice（需 Mapping Toolbox）

```powershell
.\venv\Scripts\python.exe -c "
import numpy as np
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=60000)

# 构造简易三角面片簇（实际应用应从 STL 读取）
# 此测试验证工具箱可用性 + 参数传递
result = eng.execute(
    'path_planning.layer_slice',
    params={
        'layer_height': 0.5,
        'base_plane': 0.0,
    },
    inputs={
        'additive_triangles_cluster': np.zeros((1,9), dtype=np.float64),
        'repairing_triangles_cluster': np.zeros((1,9), dtype=np.float64),
    }
)
print('状态:', result.status, '(0=成功, 4=工具箱缺失)')
print('耗时:', result.compute_time_ms, 'ms')
if not result.ok:
    print('错误码:', result.error_code)
    print('错误:', result.error_message)
eng.close()
"
```
**预期**：
- 工具箱可用时：`状态: 0`
- 工具箱缺失时：`状态: 4`（ERR_DEPS），这是预期降级行为

### 步骤 4.4 — 错误处理验证：调用不存在的算法

```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine, AlgorithmEngineError
eng = MatlabEngine(host='127.0.0.1', port=5570)
result = eng.execute('nonexistent.algorithm')
print('状态:', result.status, '(5=未找到)')
print('错误:', result.error_message)
assert result.status == 5
print('错误处理验证通过')
eng.close()
"
```
**预期**：`状态: 5`，Server 未崩溃

### 步骤 4.5 — 异常隔离验证：传入非法参数

```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570)
# 传错参数类型，算法应报错但 Server 不崩
result = eng.execute('path_planning.read_stl_file', params={'filename': 12345})
print('状态:', result.status)
print('错误:', result.error_message)
# 再发一个正常请求，确认 Server 仍可用
result2 = eng.heartbeat()
print('Server 仍可用:', 'server_ts_ms' in result2)
eng.close()
"
```
**预期**：算法报错，但后续心跳正常（Server 未崩溃）

---

## 阶段 5：稳定性验证

### 步骤 5.1 — 连续请求压力测试

```powershell
.\venv\Scripts\python.exe -c "
import time
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=10000)

# 连续 50 次心跳
t0 = time.perf_counter()
for i in range(50):
    pong = eng.heartbeat()
    assert 'server_ts_ms' in pong, f'第 {i} 次心跳失败'
elapsed = time.perf_counter() - t0
print(f'50 次心跳: {elapsed*1000:.0f}ms, 平均 {elapsed/50*1000:.1f}ms/次')

# 检查健康状态（内存不应暴涨）
health = eng.get_health_status()
print(f'内存: {health.get(\"memory_mb\",0):.0f} MB')
print(f'总请求数: {health.get(\"total_requests\",0)}')
print(f'错误率: {health.get(\"error_rate_1m\",0):.2%}')
eng.close()
"
```
**验证点**：
- 50 次心跳全部成功
- 平均延迟 < 10ms（loopback）
- 内存无暴涨（应 < 500 MB）
- 错误率 0%

### 步骤 5.2 — 资源清理验证

连续发送 100+ 请求，观察内存是否周期性下降：
```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570)

for i in range(60):  # 超过 cleanup_interval=50
    eng.heartbeat()

health = eng.get_health_status()
print(f'60 请求后内存: {health.get(\"memory_mb\",0):.0f} MB')
print(f'总请求数: {health.get(\"total_requests\",0)}')
# 内存应在 cleanup 后稳定（不持续增长）
eng.close()
"
```

### 步骤 5.3 — 超时验证

```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine, AlgorithmEngineError
# 设置极短超时
eng = MatlabEngine(host='127.0.0.1', port=5570, timeout_ms=100, max_retries=1)
try:
    result = eng.execute('path_planning.read_stl_file', params={'filename':'test.stl'})
    print('意外成功（不应发生）')
except AlgorithmEngineError as e:
    print(f'超时触发: {e}')
    print(f'状态码: {e.status} (2=TIMEOUT)')
eng.close()
"
```
**预期**：触发超时异常，状态码 2

---

## 阶段 6：日志验证

### 步骤 6.1 — 检查 MATLAB 控制台日志

MATLAB 命令窗口应输出 JSONL 格式日志：
```
[info] server.run request_id= ts=2026-07-10T... event=request message_type=HEALTH_CHECK
[info] server.run request_id= ts=2026-07-10T... event=response status=0 dt_ms=2
```

### 步骤 6.2 — 检查日志文件

```powershell
Get-ChildItem d:\work\demo\industrial-vision\logs\matlab_server_*.log | Select-Object -Last 1 | Get-Content -Tail 10
```
**预期**：JSONL 格式日志文件存在，内容与控制台一致

---

## 阶段 7：优雅关闭验证

### 步骤 7.1 — 从 Python 发送关闭指令

```powershell
.\venv\Scripts\python.exe -c "
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine(host='127.0.0.1', port=5570)
ack = eng.shutdown_server(reason='测试完成', grace_ms=5000)
print('关闭确认:', ack)
"
```
**预期**：
- Python 输出 `关闭确认: {'accepted': True, 'pending_count': 0, 'estimated_drain_ms': 0}`
- MATLAB 命令窗口输出关闭日志并**释放阻塞**（回到 `>>` 提示符）

### 步骤 7.2 — 确认端口已释放

```powershell
netstat -ano | findstr ":5570"
```
**预期**：无输出（端口已释放）

### 步骤 7.3 — 替代关闭方式

若 Python 关闭指令无效，可在 MATLAB 窗口按 `Ctrl+C`（强制中断）。

---

## 阶段 8：GUI 端到端验证（可选）

### 步骤 8.1 — 启动 MATLAB Server（保持运行）

按阶段 2 启动 Server。

### 步骤 8.2 — 启动 GUI

```powershell
cd d:\work\demo\industrial-vision
.\venv\Scripts\python.exe -m repair_app
```

### 步骤 8.3 — 验证引擎选择

观察 GUI 启动日志，应出现：
```
MatlabEngine available and healthy — using as production engine
```
（若出现 `MatlabEngine not reachable — falling back to LocalEngine`，检查端口和防火墙）

### 步骤 8.4 — 功能测试

在 GUI 中执行：
1. 加载点云数据
2. 选择缺陷区域
3. 执行路径规划（此时应通过 MatlabEngine 调用 MATLAB Server）
4. 查看路径规划结果
5. 导出 G-code

---

## 测试结果记录模板

| 阶段 | 测试项 | 预期 | 实际 | 通过 |
|------|--------|------|------|------|
| 1 | 端口 5570 空闲 | 无占用 | | ☐ |
| 1 | MATLAB 版本 ≥ R2018b | 是 | | ☐ |
| 1 | Map Toolbox 可用 | 1 | | ☐ |
| 1 | Curve Fitting 可用 | 1 | | ☐ |
| 2 | Server 启动 | event=ready | | ☐ |
| 2 | 19 算法注册 | algorithms=19 | | ☐ |
| 3 | 健康检查 | state=0 | | ☐ |
| 3 | 心跳响应 | server_ts_ms | | ☐ |
| 3 | 算法列表 | 19 个 | | ☐ |
| 3 | 版本协商 | compatible=True | | ☐ |
| 4 | read_stl_file | status=0 | | ☐ |
| 4 | ray_triangle_intersection | status=0 | | ☐ |
| 4 | layer_slice | status=0 或 4 | | ☐ |
| 4 | 不存在算法 | status=5 | | ☐ |
| 4 | 异常隔离 | Server 不崩 | | ☐ |
| 5 | 50 次心跳 | 全成功 | | ☐ |
| 5 | 内存稳定 | <500MB | | ☐ |
| 5 | 超时触发 | status=2 | | ☐ |
| 6 | 日志文件生成 | JSONL | | ☐ |
| 7 | 优雅关闭 | accepted=True | | ☐ |
| 7 | 端口释放 | 无占用 | | ☐ |
| 8 | GUI 引擎选择 | MatlabEngine | | ☐ |

---

## 常见问题排查

| 问题 | 可能原因 | 排查方法 |
|------|---------|---------|
| 连接被拒绝 | Server 未启动或端口错误 | 确认 MATLAB 窗口显示 `event=ready` |
| 超时 | 防火墙阻止 | `netsh advfirewall firewall add rule name="MATLAB" dir=in action=allow protocol=TCP localport=5570` |
| 算法返回 ERR_DEPS | 工具箱许可证缺失 | 在 MATLAB 中 `license('test','Map_Toolbox')` |
| 中文路径乱码 | 编码问题 | Server 用文件名探测（非硬编码），确认 `.m` 文件存在 |
| 内存持续增长 | cleanup 未触发 | 检查 `CSAM_MATLAB_CLEANUP_INTERVAL` 是否过大 |
| Server 崩溃 | 算法内部错误 | 查看 `logs/matlab_server_*.log` 错误堆栈 |
