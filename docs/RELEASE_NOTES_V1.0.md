# Release Notes — CSAM 修复软件 V1.0.0

**发布日期**：2026-07-10
**版本**：1.0.0 (Production Release)
**协议版本**：v2.1 (生产) + v3.0 (MATLAB 平台)
**支持平台**：Windows 10/11、macOS 10.14+

## 概述

V1.0.0 是首个生产发布版本。本版本完成了从原型到工业级平台的转变：
- 通信层迁移至 bridge 架构（单一生产通信路径）
- MATLAB 执行平台上线（独立长驻算法服务器）
- 通用协议 v3.0（算法无关，支持未来扩展）
- 完整工程审计与清理

## 新功能

### 1. MATLAB 执行平台
MATLAB 从"Python 宿主附属"升级为**独立长驻工业算法服务器**。
- 18 个 MATLAB 算法声明式注册，零协议改动可扩展
- 心跳、健康检查、自动重连、断路器、崩溃恢复
- TCP 传输（无 ZMQ 依赖），JSON-over-TCP 帧格式
- 工具箱许可证探测与降级

### 2. Bridge 通信层（生产路径）
MainWindow → CoordinationService → LegacyZmqClient → BridgeClient → ZMQ → Engine
- 结构化异常层级（BridgeError 及子类）
- 心跳监控（QThread，协作式中断）
- 配置全环境变量驱动

### 3. 协议 v3.0
算法无关通用协议，支持：AlgorithmRequest/Response、ProgressUpdate、Heartbeat、AlgorithmMetadata、Cancellation、VersionNegotiation。

### 4. 引擎抽象
`IAlgorithmEngine` 接口 + EngineFactory 自动选择（MATLAB 优先，Python 降级）。

## 已知问题

| ID | 严重度 | 描述 | 影响 | 缓解 |
|----|--------|------|------|------|
| SEC-1 | 中 | ZMQ 传输未使用 CURVE 加密或 PLAIN 认证 | 单用户工作站：可接受；多用户主机：本地进程可伪装服务端 | V1.1 配置 CURVE/ZAP 认证；当前部署于单用户工作站 |
| TD-1 | 低 | MainWindow 为 God Class（1227 语句，54% 覆盖） | 可维护性 | V1.1 拆分为 Toolbar/Canvas/Dock/Workflow/Dialogs/Status 组件（需先提升测试覆盖） |
| TD-2 | 低 | `workflow.path_planning` / `workflow.morphology_prediction` 编排算法待在 MATLAB Server 实现 | MatlabEngine.plan_path/predict_morphology 调用编排名，Server 需补充注册 | 当前 18 个原子算法已可用 |
| TD-3 | 低 | `point_interpretaion.m` 第 54 行 bug（`y_rotaxis` 应为 `z_rotaxis`） | 路径点姿态计算可能错误 | 受"不修改算法源"约束，需单独授权修复 |
| TD-4 | 低 | 旧版 communication/ 已弃用但未删除 | 仓库噪音 | 下一大版本清理 |

## 系统要求

### Python GUI
- Windows 10/11 或 macOS 10.14+
- Python 3.10-3.12
- 依赖：PySide6, numpy, scipy, matplotlib, shapely, pyzmq, protobuf, reportlab, cryptography

### MATLAB Server（可选，生产算法后端）
- MATLAB R2020b+（推荐 R2024b）
- Mapping Toolbox（generate_path、profile_predict 需要）
- Curve Fitting Toolbox（particle_fitting 需要）

## 安装

### 从源码运行
```powershell
git clone <repo>
cd industrial-vision
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
python -m repair_app
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

## 升级说明
- 从 0.10 升级：直接替换文件，配置无需变更
- 旧版 ZmqRepairClient 仍可用（发出 DeprecationWarning）
- 新部署推荐使用 bridge 路径（默认已启用）

## 致谢
感谢所有参与架构设计、实现、测试与审计的工程师。
