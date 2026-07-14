# Release Notes — CSAM 修复软件 V1.0.0

**发布日期**：2026-07-14
**版本**：1.0.0 (Release Candidate)
**协议版本**：v2.1 (ZeroMQ + Protocol Buffers)
**支持平台**：Windows 10/11、macOS 10.14+
**MATLAB 支持**：R2025b（推荐）/ R2024b+

## 概述

V1.0.0 是 CSAM Repair 的首个 Release Candidate 版本。本版本完成了从原型到工业级平台的转变：

- MATLAB 工业算法正式接入（路径规划 + 形貌预测）
- Python GUI 原生渲染 MATLAB 计算结果（不依赖截图/PNG）
- 工业可靠性降级策略（MATLAB 不可用时自动降级到 Python）
- Bridge 通信架构（ZeroMQ + Protobuf v2.1）作为唯一生产通信路径
- 完整用户手册（11 篇，面向无编程经验操作员）
- 276 个单元测试 + 27 项端到端验证全部通过

## 新功能

### 1. MATLAB 工业路径规划算法
- 接入 `run_path_planning.m`，生成真实修复航点
- 通过 `MatlabEngineProxy` 单例连接共享 MATLAB 会话
- 支持材料参数、扫描参数、层参数完整传递

### 2. MATLAB 工业形貌预测算法
- 接入 `run_profile_prediction.m`，预测沉积形貌
- 返回完整结果：mesh（三角网格）、layer_profiles（逐层轮廓）、particle_distribution（粒子分布）、uniformity（均匀性）、estimated_mass_g、estimated_time_s
- mesh 自动编码为二进制 STL bytes，供 GUI 原生渲染

### 3. Python GUI 原生渲染
- 新增 `ProfileResultPanel`（repair_app/ui/profile_result_panel.py）
- 4 种可视化视图：
  - 沉积网格：Poly3DCollection 3D 三角网格
  - 逐层轮廓：matplotlib 曲线图
  - 粒子分布：热力图
  - 均匀性：仪表盘
- 6 个指标卡片：航点数、计算耗时、预测体积、材料质量、估计时间、均匀性
- NavigationToolbar2QT 支持缩放/平移/导出 PNG

### 4. 工业可靠性降级策略
- `auto` 模式：MATLAB 优先，失败时自动降级到 Python 启发式
- `matlab` 模式：强制 MATLAB，失败时抛出异常
- `python` 模式：强制使用 Python 原型
- 降级后自动切换 `_algorithm_fn`，避免重复尝试 MATLAB 连接
- Python 降级路径通过 scipy Delaunay 生成 mesh

### 5. Bridge 通信架构
- ZeroMQ REP/REQ 通信（端口 5555）
- Protocol Buffers v2.1 序列化
- 结构化异常层次（BridgeError 及子类）
- 心跳监控、健康检查、配置环境变量驱动
- `LegacyZmqClient` 适配器保证 UI 零改动迁移

## 已修复的问题

| ID | 严重度 | 描述 | 修复方式 |
|----|--------|------|----------|
| BUG-1 | 严重 | auto 模式下独立启动 MATLAB 导致 51 秒延迟 | `_ensure_connected` 策略 3 添加 `allow_standalone` 检查 |
| BUG-2 | 严重 | `handle_repair` 算法失败时未降级到 Python | 新增 `_invoke_with_fallback` 方法 |
| BUG-3 | 中等 | Python 降级路径不生成 mesh 数据 | 新增 `_build_mesh_from_cloud` 方法（scipy Delaunay） |
| BUG-4 | 性能 | `_try_profile_prediction` 重复尝试 MATLAB 连接 | 已降级时跳过（检查 `_algorithm_fn` 指向） |

## 已知问题

| ID | 严重度 | 描述 | 影响 | 缓解 |
|----|--------|------|------|------|
| SEC-1 | 中 | ZMQ 传输未使用 CURVE 加密或 PLAIN 认证 | 单用户工作站：可接受；多用户主机：本地进程可伪装服务端 | V1.1 配置 CURVE/ZAP 认证；当前部署于单用户工作站 |
| TD-1 | 低 | MainWindow 为 God Class（约 1898 行） | 可维护性 | V1.1 拆分为 Toolbar/Canvas/Dock/Workflow/Dialogs/Status 组件 |
| TD-2 | 低 | 旧版 communication/ 已弃用但未删除 | 仓库噪音 | 下一大版本清理（repair_protocol_pb2 仍被 bridge 复用） |
| TD-3 | 低 | 路径 A 无自动重连 | 连接断开后需用户重启操作 | V1.1 添加自动重连机制 |
| TD-4 | 低 | HMAC 密钥硬编码回退 | 安全风险 | 生产环境必须通过 CSAM_HMAC_SECRET 覆盖 |

## 系统要求

### Python GUI
- Windows 10/11 或 macOS 10.14+
- Python 3.10-3.12（推荐 3.12）
- 依赖：PySide6, numpy, scipy, matplotlib, shapely, pyzmq, protobuf, reportlab, cryptography

### MATLAB（可选，生产算法后端）
- MATLAB R2025b（推荐）或 R2024b+
- Mapping Toolbox（路径规划算法需要）
- Curve Fitting Toolbox（粒子拟合算法需要）
- MATLAB Engine API for Python（自动随 MATLAB 安装）

## 安装

### 从源码运行
```powershell
git clone <repo>
cd industrial-vision
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
python run_app.py
```

### 从 Windows 安装包运行
1. 获取 `CSAM_Repair.exe`
2. 双击运行（首次启动解压临时文件，约 5-10 秒）
3. 无需安装 Python 环境

### 构建 Windows 安装包
```powershell
.\build_windows.bat
# 输出：dist\CSAM_Repair.exe
```

## 连接 MATLAB

1. 启动 MATLAB R2025b
2. 配置 Python 环境：
   ```matlab
   pyenv('Version', 'D:\work\demo\industrial-vision\venv\Scripts\python.exe');
   ```
3. 切换到项目根目录并启动服务：
   ```matlab
   cd('D:\work\demo\industrial-vision')
   matlab_bridge_server
   ```
4. 服务监听 `tcp://127.0.0.1:5555`，MATLAB 命令窗口会阻塞（正常现象）
5. 启动 Python GUI，执行路径规划时自动连接 MATLAB

> 详细说明请参阅 [MATLAB_INTEGRATION.md](MATLAB_INTEGRATION.md)

## 升级说明

- 从 0.10 升级：直接替换文件，配置无需变更
- 旧版 ZmqRepairClient 仍可用（发出 DeprecationWarning）
- 新部署推荐使用 bridge 路径（默认已启用）
- 已删除 v3.0/TCP 通信路径：如使用过 matlab_server/，需迁移到 matlab_bridge_server.m

## 致谢

感谢所有参与架构设计、实现、测试与审计的工程师。
