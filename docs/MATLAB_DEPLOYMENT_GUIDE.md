# MATLAB 平台部署指南

## 单机部署（推荐）

### 前置条件

- MATLAB R2020b+（推荐 R2024b）
- Mapping Toolbox（路径规划 generate_path、形貌预测 profile_predict 需要）
- Curve Fitting Toolbox（形貌预测 particle_fitting 需要）
- Python 3.10-3.12 + venv（项目已配置）

### 步骤 1：启动 MATLAB Server

```matlab
% 在 MATLAB 命令窗口中
cd 'd:\work\demo\industrial-vision\matlab_server'
startup
```

服务器将在 `tcp://*:5570` 监听。日志输出到控制台和 `logs/` 目录。

### 步骤 2：启动 Python GUI

```powershell
cd d:\work\demo\industrial-vision
.\venv\Scripts\python.exe -m repair_app
```

GUI 启动时 `EngineFactory` 会自动探测 MATLAB Server（2s 超时），
成功则使用 `MatlabEngine`，失败则降级到 `LocalEngine`（Python 原型）。

### 步骤 3：验证连接

```python
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine()
print(eng.check_health())        # True
print(eng.list_algorithms())     # 18 个算法
```

## 远程部署

### MATLAB Server 端

```matlab
% 设置监听地址为所有接口
setenv('CSAM_MATLAB_BIND', 'tcp://*:5570');
startup
```

### Python GUI 端

```powershell
$env:CSAM_MATLAB_HOST = "192.168.1.100"
$env:CSAM_MATLAB_PORT = "5570"
.\venv\Scripts\python.exe -m repair_app
```

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_MATLAB_BIND` | `tcp://*:5570` | MATLAB Server 监听地址 |
| `CSAM_MATLAB_HOST` | `127.0.0.1` | 客户端连接主机 |
| `CSAM_MATLAB_PORT` | `5570` | 客户端连接端口 |
| `CSAM_MATLAB_LOG_DIR` | `./logs` | MATLAB 日志目录 |
| `CSAM_MATLAB_HEARTBEAT_MS` | `1000` | 服务端心跳间隔 |
| `CSAM_ENGINE_DISABLE_MATLAB` | `0` | 设为 `1` 强制使用 Python 引擎 |
| `CSAM_HEARTBEAT_INTERVAL_MS` | `2000` | 客户端心跳间隔 |
| `CSAM_HEARTBEAT_MISS_THRESHOLD` | `3` | 心跳丢失阈值（触发重连） |
| `CSAM_RECONNECT_MAX_ATTEMPTS` | `10` | 最大重连次数 |

## 强制使用 Python 引擎（调试用）

```powershell
$env:CSAM_ENGINE_DISABLE_MATLAB = "1"
.\venv\Scripts\python.exe -m repair_app
```

## 关闭 MATLAB Server

```python
# 从 Python 端优雅关闭
from repair_app.engine.matlab_engine import MatlabEngine
eng = MatlabEngine()
eng.shutdown_server(reason="maintenance", grace_ms=5000)
```

或在 MATLAB 命令窗口发送 `Ctrl+C`。
