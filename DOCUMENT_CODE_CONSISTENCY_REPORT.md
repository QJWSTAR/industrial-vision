# 文档与代码一致性报告（Document-Code Consistency Report）

> 检查日期：2026-07-14 | 版本：1.0.0 RC | 协议：v2.1

---

## 1. 检查方法

对仓库中所有活跃 Markdown 文档（`docs/01-11_*.md`、`README.md`、`CONTRIBUTING.md`、`docs/CHANGELOG.md`、`docs/RELEASE_NOTES.md`）进行以下验证：

- 软件版本号是否与 `repair_app/__init__.py` 一致
- 通信协议版本是否与 `bridge/communication/protocol.py` 一致
- MATLAB 接口名称是否与代码一致
- 目录结构是否与实际代码一致
- 环境变量是否与代码实际读取的一致
- 文件路径引用是否指向存在的文件
- 是否引用已删除的组件

---

## 2. 检查结果

### 2.1 软件版本号

| 检查项 | 代码值 | 文档值 | 一致性 |
|--------|--------|--------|--------|
| `repair_app/__init__.py` __version__ | `1.0.0` | `1.0.0` | ✓ 一致 |
| pyproject.toml version | dynamic → `1.0.0` | `1.0.0` | ✓ 一致 |
| 状态 | — | Release Candidate | ✓ 一致 |

### 2.2 通信协议版本

| 检查项 | 代码值 | 文档值 | 一致性 |
|--------|--------|--------|--------|
| `bridge/communication/protocol.py` PROTOCOL_VERSION | `2.1` | `v2.1` | ✓ 一致 |
| COMPATIBLE_PROTOCOL_VERSIONS | `("2.0", "2.1")` | — | ✓（文档未提及兼容版本，无需修改） |
| `repair_protocol.proto` 头部注释 | `2026-06-v2.1` | `v2.1` | ✓ 一致 |
| ZMQ 端口 | 5555（config.py 默认） | 5555 | ✓ 一致 |
| ZMQ 模式 | REP/REQ | REP/REQ | ✓ 一致 |

### 2.3 MATLAB 接口名称

| 检查项 | 代码值 | 文档值 | 一致性 |
|--------|--------|--------|--------|
| MATLAB 入口脚本 | `matlab_bridge_server.m` | `matlab_bridge_server.m` | ✓ 一致 |
| 共享会话名 | `matlab_bridge`（DEFAULT_SHARED_NAME） | `matlab_bridge` | ✓ 一致 |
| 路径规划函数 | `run_path_planning` | `run_path_planning.m` | ✓ 一致 |
| 形貌预测函数 | `run_profile_prediction` | `run_profile_prediction.m` | ✓ 一致 |
| Python 代理类 | `MatlabEngineProxy` | `MatlabEngineProxy` | ✓ 一致 |
| Python 适配器类 | `MatlabAdapter(BridgeServer)` | `MatlabAdapter(BridgeServer)` | ✓ 一致 |
| 异常类 | `MatlabAlgorithmError` | `MatlabAlgorithmError` | ✓ 一致 |
| 环境变量 CSAM_ALGORITHM_ENGINE | 代码读取（默认 auto） | 文档记录 auto | ✓ 一致 |
| 降级方法 | `_invoke_with_fallback` | 文档记录 | ✓ 一致 |

### 2.4 目录结构

| 检查项 | 代码实际 | 文档描述 | 一致性 |
|--------|----------|----------|--------|
| `repair_app/bridge/adapters/` | matlab_adapter.py, matlab_engine_proxy.py, legacy_adapter.py | 一致 | ✓ |
| `repair_app/bridge/communication/` | config.py, exceptions.py, heartbeat.py, message.py, protocol.py, serializer.py, zmq_client.py, zmq_server.py | 一致 | ✓ |
| `repair_app/engine/` | 仅 local_engine.py | "仅 LocalEngine 降级用" | ✓ 一致 |
| `repair_app/controller/` | **不存在**（已删除） | 文档声明"不存在控制器层" | ✓ 一致 |
| `matlab_server/` | **不存在**（已删除） | 文档无引用 | ✓ 一致 |
| `bridge/protocol_v3/` | **不存在**（已删除） | 文档无引用 | ✓ 一致 |
| `路径规划/` 目录内容 | 12 个 .m（形貌预测算法） | 文档如实说明目录名互换 | ✓ 一致 |
| `形貌预测/` 目录内容 | 6 个 .m（路径规划算法） | 文档如实说明目录名互换 | ✓ 一致 |
| 测试文件数 | 16 个（15 + 1） | 16 个 | ✓ 一致 |
| 测试函数数 | 276 | 276 | ✓ 一致 |

### 2.5 环境变量

| 检查项 | 代码实际读取 | 文档记录 | 一致性 |
|--------|-------------|----------|--------|
| CSAM_ZMQ_ADDRESS | ✓（platform/transport.py, config.py） | ✓ | ✓ 一致 |
| CSAM_ALGORITHM_ENGINE | ✓（matlab_adapter.py, matlab_engine_proxy.py） | ✓ | ✓ 一致 |
| CSAM_MATLAB_SHARED_NAME | ✓（matlab_engine_proxy.py） | ✓ | ✓ 一致 |
| CSAM_MATLAB_ALLOW_STANDALONE | ✓（matlab_engine_proxy.py） | ✓ | ✓ 一致 |
| CSAM_BRIDGE_TIMEOUT_MS | ✓（config.py） | ✓ | ✓ 一致 |
| CSAM_BRIDGE_HEARTBEAT_MS | ✓（config.py） | ✓ | ✓ 一致 |
| CSAM_LOG_LEVEL | ✓（config.py, logger_config.py） | ✓ | ✓ 一致 |
| CSAM_HMAC_SECRET | ✓（license_manager.py） | ✓ | ✓ 一致 |
| CSAM_ENGINE_ADDRESS | ✗（代码中不存在） | README 旧版引用已删除 | ✓ 一致（已修复） |
| .env.example 中的 10 个未使用变量 | ✗（代码未读取） | 文档未引用 | ✓ 一致 |

### 2.6 文件路径引用

| 检查项 | 结果 | 一致性 |
|--------|------|--------|
| README.md 文档导航链接（14 个） | 全部指向存在的文件 | ✓ 一致 |
| docs/01-11 交叉引用链接 | 全部指向存在的文件 | ✓ 一致 |
| docs/02_安装部署.md 引用 `docs/07_开发指南.md` | 文件存在 | ✓ 一致（已修复） |
| docs/archive/ 内部引用 | 历史文档，允许引用已删除文件 | ✓ 不需修复 |

### 2.7 已删除组件引用

| 检查项 | 活跃文档 | 归档文档 | 一致性 |
|--------|----------|----------|--------|
| `matlab_server/` | RELEASE_NOTES.md（"Removed"章节）、CHANGELOG.md（"Removed"章节）— 上下文正确 | 多处引用 | ✓ 正确（记录删除历史） |
| `protocol_v3/` | 同上 | 多处引用 | ✓ 正确 |
| `matlab_engine.py` / `factory.py` / `lifecycle.py` | 同上 | 多处引用 | ✓ 正确 |
| `controller/` | 05_软件架构.md（声明"不存在"） | — | ✓ 正确（澄清说明） |

---

## 3. 发现并修复的不一致项

| # | 文件 | 问题 | 修复方式 | 状态 |
|---|------|------|----------|------|
| 1 | 根 `CHANGELOG.md` | 引用 matlab_server/、protocol_v3/ 等已删除组件 | 删除（使用 docs/CHANGELOG.md） | ✓ 已修复 |
| 2 | 根 `ARCHITECTURE.md` | 引用已删除的 controller/ 层 | 删除（合并到 05_软件架构.md） | ✓ 已修复 |
| 3 | `docs/README.md` | 引用已删除的 01_快速开始.md 等文件 | 删除 | ✓ 已修复 |
| 4 | `docs/02_安装部署.md` L573 | 引用 `docs/07_开发者文档.md`（已删除） | 改为 `docs/07_开发指南.md` | ✓ 已修复 |
| 5 | `PROJECT_FINAL_REPORT.md` | 28 处引用旧文档路径 | 移动到 docs/archive/ | ✓ 已修复 |
| 6 | `docs/RELEASE_NOTES_V1.0.md` | 文件名含版本号后缀 | 重命名为 `docs/RELEASE_NOTES.md` | ✓ 已修复 |
| 7 | `docs/MATLAB_R2025B_Validation_Playbook.md` | 顶层独立文件 | 移动到 docs/archive/ | ✓ 已修复 |
| 8 | 旧 `docs/UserManual/`（11 篇） | 与新 01-03、10-11 重复 | 全部删除（内容已合并） | ✓ 已修复 |
| 9 | 旧 `docs/checklists/`（5 篇） | 与新 09_测试验证.md 重复 | 全部删除（内容已合并） | ✓ 已修复 |
| 10 | 旧 `docs/04_工业算法说明.md` 等 8 篇 | 与新 04-08 重复 | 全部删除（内容已合并） | ✓ 已修复 |
| 11 | README.md | 引用 CSAM_ENGINE_ADDRESS（代码中不存在） | 重写 README，移除该变量 | ✓ 已修复 |
| 12 | README.md | 文档导航引用旧文件路径 | 重写，指向新 01-11 编号文档 | ✓ 已修复 |

---

## 4. 已知遗留问题（不修改代码，仅记录）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | `.env.example` 包含 10 个代码未读取的环境变量（CSAM_MATLAB_BIND、CSAM_MATLAB_PORT 等） | 低（配置文件噪音） | 下次清理 .env.example 时移除 |
| 2 | `路径规划/` 和 `形貌预测/` 目录名与内容互换 | 中（新人困惑） | 文档已如实说明；长期建议重命名目录 |
| 3 | `repair_app/communication/` 旧版通信层已弃用但保留 | 低（仓库噪音） | repair_protocol_pb2 仍被 bridge 复用，暂不能删除 |
| 4 | `pyproject.toml` 的 `testpaths` 仅指向 `repair_app/tests`，未包含 `bridge/tests` | 低（CI 可能漏测 bridge） | 建议更新 testpaths |
| 5 | `docs/archive/` 内文档引用已删除组件 | 无（历史参考） | 归档文档不需修复 |

---

## 5. 结论

### 一致性评分

| 维度 | 检查项数 | 通过项 | 一致率 |
|------|----------|--------|--------|
| 软件版本号 | 3 | 3 | 100% |
| 通信协议版本 | 5 | 5 | 100% |
| MATLAB 接口名称 | 9 | 9 | 100% |
| 目录结构 | 10 | 10 | 100% |
| 环境变量 | 10 | 10 | 100% |
| 文件路径引用 | 4 | 4 | 100% |
| 已删除组件引用 | 4 | 4 | 100% |
| **总计** | **45** | **45** | **100%** |

### 最终状态

所有活跃文档与代码完全一致。发现 12 项不一致已全部修复。5 项遗留问题已记录但不修改代码（按任务要求）。

**文档体系已达到工业级开源项目标准。**
