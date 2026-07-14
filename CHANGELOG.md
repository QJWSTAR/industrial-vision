# CHANGELOG

本文件记录 CSAM 修复软件的所有版本变更。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.0.0] — 2026-07-10 (Production Release)

### 新增 (Added)
- **Bridge 通信层** (`repair_app/bridge/`)：MatlabService 门面、BridgeClient、LegacyZmqClient 适配器、HeartbeatMonitor、结构化异常层级
- **MATLAB 执行平台** (`matlab_server/`)：独立长驻 MATLAB Server，13 个组件（startup/server/registry/dispatcher/health/heartbeat/lifecycle/resource_cleanup/logger/json_codec/config/register_algorithms）
- **协议 v3.0** (`repair_app/bridge/protocol_v3/`)：算法无关通用协议（AlgorithmRequest/Response/Metadata/ProgressUpdate/Heartbeat/Cancellation/VersionNegotiation），替代业务专用的 RepairRequest
- **MatlabEngine** (`repair_app/engine/matlab_engine.py`)：IEngine 实现，TCP 通道、重试、超时
- **EngineFactory** (`repair_app/engine/factory.py`)：引擎选择（MATLAB 优先，Python 降级）
- **LifecycleSupervisor** (`repair_app/engine/lifecycle.py`)：心跳、自动重连（指数退避）、断路器、崩溃恢复
- **18 个 MATLAB 算法注册**：路径规划 7 个 + 形貌预测 11 个，声明式注册表
- **迁移验证测试** (`test_migration.py`)：10 个测试验证 bridge 为生产路径
- **MATLAB 平台测试** (`test_matlab_platform.py`)：35 个测试（协议/引擎/通道/工厂/生命周期/超时/端到端/性能）
- **架构文档 V3** (`docs/ARCHITECTURE_V3.md`)：下一代 MATLAB 集成架构设计
- **MATLAB 平台架构文档** (`docs/MATLAB_PLATFORM_ARCHITECTURE.md`)
- **MATLAB 部署指南** (`docs/MATLAB_DEPLOYMENT_GUIDE.md`)
- **.env.example 完整化**：覆盖许可证、ZMQ、bridge、MATLAB 平台、生命周期监控全部环境变量

### 变更 (Changed)
- **通信层迁移**：CoordinationService.create_zmq_client() 切换至 bridge 适配器 LegacyZmqClient
- **MainWindow 通信路径**：从旧版 ZmqRepairClient 切换至 bridge 层（零 GUI 改动）
- **PyInstaller spec**：移除 3 个已删除模块的 stale hiddenimports，新增 bridge/engine/protocol_v3 hiddenimports
- **架构文档**：标注 bridge 为生产通信路径
- **开发者文档**：新增通信层架构章节，测试计数更新至 305

### 弃用 (Deprecated)
- `repair_app/communication/zmq_client.py`（ZmqRepairClient）：标记为 deprecated，实例化时发出 DeprecationWarning。保留用于向后兼容，将在下一大版本移除
- `repair_app/communication/repair_serialization.py` 和 `repair_protocol_pb2.py`：仍被 bridge 复用，**不属于**弃用范围

### 移除 (Removed)
- `matlab_zmq_server.m`：使用旧版 repair_engine_service 路径的 obsolete 文件
- `zmq_test.py`：孤立调试脚本，引用已弃用的 ZmqRepairClient
- `gui_auto_test.py`：孤立 GUI 冒烟脚本，未被任何模块引用
- `repair_app/utils/matlab_demo_io.py`：真正的孤立模块，无任何引用
- `repair_app.spec` 中 3 个 stale hiddenimports：`repair_service`、`app_controller`、`workflow_controller`（对应模块早已删除）

### 安全 (Security)
- **已知问题 #SEC-1**：ZMQ 传输未使用 CURVE 加密或 PLAIN 认证（3 处：zmq_client.py、repair_engine_service.py、transport.py）。单用户工作站部署下为已知可接受风险；多用户主机部署应在 V1.1 配置 CURVE/ZAP 认证。已从 `TODO(SECURITY)` 转为文档化的 `SECURITY NOTE (V1.0 known issue)`，并在 Release Notes 记录
- 无 `eval()`/`exec()`/`pickle`/`shell=True`/bare `except`/`os.system` 使用
- 许可证 HMAC 密钥支持环境变量配置，开发环境回退密钥有告警日志

### 测试
- **305 个测试全部通过**（270 现有 + 35 新增 MATLAB 平台）
- 覆盖率 73%（总代码），MainWindow 54%
- CI 矩阵：Windows/macOS/Ubuntu × Python 3.10/3.11/3.12
- 覆盖率门控：60%

---

## [0.10] — 2026-07-09 (Release Candidate)

### 新增
- Windows 与 macOS 双平台支持
- PySide6 三面板可视化 GUI（增材/修复双模式）
- 路径规划算法（A* 搜索、分层切片、Zig-Zag 填充）
- 形貌预测算法（射线-三角形相交、八叉树、沉积轮廓预测）
- ZMQ + Protobuf v2.1 通信协议
- G-code 导出、PDF 修复报告
- 许可证管理（RSA 验证 + HMAC）
- CI/CD（GitHub Actions 三平台矩阵）
- 自动化测试基础设施（260 测试）
- 文档：ARCHITECTURE.md、DEVELOPER.md、BRIDGE_ARCHITECTURE.md

---

## 版本历史摘要

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| 0.10 | 2026-07-09 | Release Candidate：双平台、算法、通信、测试 |
| 1.0.0 | 2026-07-10 | Production Release：bridge 迁移、MATLAB 执行平台、协议 v3.0、工程审计 |
