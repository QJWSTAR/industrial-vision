# CHANGELOG

本文件记录 CSAM 修复软件的所有版本变更。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.0.0] — 2026-07-14 (Release Candidate)

### 新增 (Added)
- **MATLAB 工业路径规划算法接入**（`run_path_planning.m`）
- **MATLAB 工业形貌预测算法接入**（`run_profile_prediction.m`）
- **Python GUI 原生渲染 MATLAB 计算结果**：`ProfileResultPanel` 支持沉积网格、逐层轮廓、粒子分布、均匀性仪表盘四种可视化视图
- **Bridge 通信层**：基于 ZeroMQ REP/REQ + Protobuf v2.1 协议
- **MatlabEngineProxy 单例代理**：共享 MATLAB 会话 + 自动降级
- **工业可靠性降级策略**：MATLAB 不可用时自动降级到 Python 启发式算法
- **G-code 导出 + PDF 报告生成**
- **完整用户手册**：11 篇文档，面向无编程经验操作员

### 修复 (Fixed)
- 修复 `auto` 模式下独立启动 MATLAB 导致的 51 秒延迟
- 修复 `handle_repair` 算法失败时未降级到 Python 的问题
- 修复 Python 降级路径不生成 mesh 数据的问题
- 修复 `_try_profile_prediction` 重复尝试 MATLAB 连接的问题

### 删除 (Removed) — RC 清理
- 移除废弃的 v3.0 TCP/JSON 通信路径：`matlab_server/`、`bridge/protocol_v3/`、`engine/matlab_engine.py`、`factory.py`、`lifecycle.py`
- 移除 Demo MATLAB 入口：`main.m`、`createfigures.m`、`createvideo.m`
- 移除调试快照：`*.mat` 调试文件、`*.scdoc` CAD 源文件
- 移除重复数据文件：`路径规划/` 下的孤儿数据
- 移除 9 份重复文档
- 移除空目录 `repair_app/controller/`
- 移除所有 `__pycache__` 缓存

### 测试
- 276 个单元测试全部通过
- 27 项端到端验证全部通过

---

## [0.10.0] — GUI 升级

### 新增 (Added)
- 三面板可视化 GUI（增材/修复双模式）
- 暗色工业主题
- 实时同步逐步渲染

---

## [0.9.0] — Bridge 架构

### 新增 (Added)
- ZeroMQ REP/REQ 通信
- Protobuf v2.1 协议
- LegacyZmqClient 兼容层

---

## [0.8.0] — 跨平台迁移

### 新增 (Added)
- macOS 到 Windows 跨平台支持
- 平台抽象层

---

## [0.7.0] — 核心算法

### 新增 (Added)
- Python 路径规划原型
- Python 形貌预测原型
- STL 读取 / 法向量估计

---

## 版本历史摘要

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| 0.7.0 | — | 核心算法：Python 原型、STL 读取 |
| 0.8.0 | — | 跨平台迁移：macOS → Windows |
| 0.9.0 | — | Bridge 架构：ZeroMQ + Protobuf v2.1 |
| 0.10.0 | — | GUI 升级：三面板、暗色主题 |
| 1.0.0 | 2026-07-14 | Release Candidate：MATLAB 接入、降级策略、用户手册 |
