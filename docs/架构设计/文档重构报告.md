# 文档重构报告（Document Refactor Report）

> 日期：2026-07-14 | 版本：1.0.0 RC | 执行人：Technical Writer + Software Architect

---

## 1. 删除文档列表

以下文档已被删除（原因：重复、过时、或内容已合并到新文档）：

| # | 文件路径 | 删除原因 |
|---|----------|----------|
| 1 | `CHANGELOG.md`（根目录） | 严重过时（引用 matlab_server/、protocol_v3/ 等已删除组件），与 docs/CHANGELOG.md 重复 |
| 2 | `ARCHITECTURE.md`（根目录） | 引用已删除的 controller/ 层，与 docs/10_架构文档.md 重复 |
| 3 | `docs/README.md` | 引用已删除的 01_快速开始.md 等文件，与根 README.md 重复 |
| 4 | `docs/04_工业算法说明.md` | 内容合并到 `docs/04_MATLAB算法说明.md` |
| 5 | `docs/07_开发者文档.md` | 内容合并到 `docs/07_开发指南.md` |
| 6 | `docs/08_运维手册.md` | 内容合并到 `docs/02_安装部署.md` 和 `docs/11_故障排查.md` |
| 7 | `docs/09_API文档.md` | 重命名为 `docs/08_API接口.md`（并删除 v3.0 章节） |
| 8 | `docs/10_架构文档.md` | 内容合并到 `docs/05_软件架构.md` |
| 9 | `docs/BRIDGE_ARCHITECTURE.md` | 内容合并到 `docs/06_通信协议.md` |
| 10 | `docs/COMMUNICATION.md` | 内容合并到 `docs/06_通信协议.md` |
| 11 | `docs/MATLAB_INTEGRATION.md` | 内容合并到 `docs/04_MATLAB算法说明.md` |
| 12 | `docs/MATLAB_CALL_GRAPH.md` | 内容合并到 `docs/04_MATLAB算法说明.md` |
| 13 | `docs/PACKAGING_GUIDE.md` | 内容合并到 `docs/02_安装部署.md` |
| 14 | `docs/RELEASE_CHECKLIST.md` | 内容合并到 `docs/09_测试验证.md` |
| 15-25 | `docs/UserManual/00-10_*.md`（11 篇） | 内容合并到 `docs/01-03_*.md`、`docs/10_FAQ.md`、`docs/11_故障排查.md` |
| 26-30 | `docs/checklists/*.md`（5 篇） | 内容合并到 `docs/09_测试验证.md` |

**删除总数**：30 个文件

---

## 2. 合并文档列表

以下文档由多个源文档合并而成：

| 新文档 | 合并自 |
|--------|--------|
| `docs/01_快速开始.md` | README.md（快速开始章节）+ UserManual/03_第一次使用.md |
| `docs/02_安装部署.md` | UserManual/02_安装指南.md + PACKAGING_GUIDE.md + 08_运维手册.md（日志/升级章节） |
| `docs/03_用户使用手册.md` | UserManual/04_完整操作手册.md + 05_典型工作流程.md + 06_案例教程.md + 09_使用技巧.md |
| `docs/04_MATLAB算法说明.md` | 04_工业算法说明.md + MATLAB_INTEGRATION.md + MATLAB_CALL_GRAPH.md |
| `docs/05_软件架构.md` | 10_架构文档.md + ARCHITECTURE.md（根目录） |
| `docs/06_通信协议.md` | COMMUNICATION.md + BRIDGE_ARCHITECTURE.md |
| `docs/07_开发指南.md` | 07_开发者文档.md + CONTRIBUTING.md |
| `docs/08_API接口.md` | 09_API文档.md（删除 v3.0 章节，新增 MatlabAdapter/Proxy） |
| `docs/09_测试验证.md` | RELEASE_CHECKLIST.md + checklists/（5 篇）+ 07_开发者文档.md（测试章节） |
| `docs/10_FAQ.md` | UserManual/07_常见问题.md + 01_软件简介.md + 10_术语解释.md |
| `docs/11_故障排查.md` | UserManual/08_故障排查.md + 08_运维手册.md（恢复章节） |

---

## 3. 更新文档列表

以下文档已更新（内容修改但未重命名）：

| 文件 | 更新内容 |
|------|----------|
| `README.md` | 完全重写：5 分钟快速开始、新文档导航表、准确的目录结构（标注目录名互换）、移除所有旧文档引用 |
| `docs/CHANGELOG.md` | 确认无 v3.0 引用（上一轮已清理） |
| `docs/02_安装部署.md` | 修复 1 处旧文档引用（07_开发者文档 → 07_开发指南） |

---

## 4. 新建文档列表

以下文档为本次新建：

| # | 文件路径 | 说明 |
|---|----------|------|
| 1 | `docs/01_快速开始.md` | 5 分钟快速开始指南 |
| 2 | `docs/02_安装部署.md` | Windows/macOS/Linux/MATLAB 安装部署 |
| 3 | `docs/03_用户使用手册.md` | 完整操作手册 |
| 4 | `docs/04_MATLAB算法说明.md` | MATLAB 算法、调用图、连接指南 |
| 5 | `docs/05_软件架构.md` | 分层架构、数据流、降级策略 |
| 6 | `docs/06_通信协议.md` | ZeroMQ + Protobuf v2.1 + Bridge 组件 |
| 7 | `docs/07_开发指南.md` | 开发环境、编码规范、贡献流程 |
| 8 | `docs/08_API接口.md` | 公开接口签名、异常层次 |
| 9 | `docs/09_测试验证.md` | 测试运行、检查清单 |
| 10 | `docs/10_FAQ.md` | 常见问题、术语表 |
| 11 | `docs/11_故障排查.md` | 故障诊断、恢复操作 |
| 12 | `DOCUMENT_INVENTORY.md` | 文档清单（扫描结果） |
| 13 | `DOCUMENT_REFACTOR_REPORT.md` | 本报告 |
| 14 | `DOCUMENT_CODE_CONSISTENCY_REPORT.md` | 文档与代码一致性报告 |

---

## 5. 重命名/移动列表

| 原路径 | 新路径 | 操作 |
|--------|--------|------|
| `docs/RELEASE_NOTES_V1.0.md` | `docs/RELEASE_NOTES.md` | 重命名（去掉版本号后缀） |
| `docs/MATLAB_R2025B_Validation_Playbook.md` | `docs/archive/MATLAB_R2025B_Validation_Playbook.md` | 移动到归档 |
| `PROJECT_FINAL_REPORT.md` | `docs/archive/PROJECT_FINAL_REPORT.md` | 移动到归档（历史快照） |

---

## 6. 当前最终文档结构

```
industrial-vision/
├── README.md                          # 项目入口（重写）
├── CONTRIBUTING.md                    # 贡献指南（保留）
├── LICENSE                            # MIT 许可证
├── DOCUMENT_INVENTORY.md              # 文档清单
├── DOCUMENT_REFACTOR_REPORT.md        # 本报告
├── DOCUMENT_CODE_CONSISTENCY_REPORT.md # 一致性报告
│
├── docs/
│   ├── 01_快速开始.md                  # 5 分钟快速开始
│   ├── 02_安装部署.md                  # Windows/macOS/Linux/MATLAB 安装
│   ├── 03_用户使用手册.md              # 完整操作手册
│   ├── 04_MATLAB算法说明.md            # MATLAB 算法 + 调用图 + 连接
│   ├── 05_软件架构.md                  # 分层架构 + 数据流 + 降级
│   ├── 06_通信协议.md                  # ZMQ + Protobuf + Bridge 组件
│   ├── 07_开发指南.md                  # 开发环境 + 编码规范 + 贡献
│   ├── 08_API接口.md                   # 公开接口 + 异常层次
│   ├── 09_测试验证.md                  # 测试 + 检查清单
│   ├── 10_FAQ.md                       # 常见问题 + 术语表
│   ├── 11_故障排查.md                  # 故障诊断 + 恢复
│   ├── CHANGELOG.md                    # 版本变更记录
│   ├── RELEASE_NOTES.md               # 发布说明
│   └── archive/                        # 历史归档（12 篇）
│       ├── ARCHITECTURE_V3.md
│       ├── GUI_VISUALIZATION_DESIGN.md
│       ├── MATLAB_INTEGRATION_ARCHITECTURE.md
│       ├── MATLAB_R2025B_Validation_Playbook.md
│       ├── MIGRATION_REPORT.md
│       ├── PATH_PLANNING_INTEGRATION_REPORT.md
│       ├── PROFILE_PREDICTION_INTEGRATION_REPORT.md
│       ├── PROJECT_FINAL_REPORT.md
│       ├── RELEASE_CANDIDATE_REPORT_V1.0.md
│       ├── RELEASE_VALIDATION_REPORT.md
│       ├── 06_故障排查.md
│       └── 端到端仿真验证报告.md
│
├── .github/
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       └── feature_request.md
```

### 文档分类

| 分类 | 文档 | 数量 |
|------|------|------|
| ① 用户文档 | 01_快速开始、02_安装部署、03_用户使用手册、10_FAQ、11_故障排查 | 5 |
| ② 开发文档 | 04_MATLAB算法说明、05_软件架构、06_通信协议、07_开发指南、08_API接口、09_测试验证 | 6 |
| ③ 项目管理文档 | README、CONTRIBUTING、CHANGELOG、RELEASE_NOTES | 4 |
| ④ 历史文档 | docs/archive/（12 篇） | 12 |
| **合计** | | **27** |

---

## 7. 后续维护建议

### 7.1 文档更新规则

1. **代码变更时同步文档**：修改接口、新增环境变量、更改目录结构时，必须同步更新对应文档
2. **版本号一致性**：`repair_app/__init__.py` 的 `__version__` 是唯一版本源，所有文档引用此值
3. **协议版本一致性**：`bridge/communication/protocol.py` 的 `PROTOCOL_VERSION` 是唯一协议版本源
4. **环境变量单一来源**：`bridge/communication/config.py` 是环境变量的权威定义，文档引用时以代码为准

### 7.2 新增文档规则

1. 用户文档放在 `docs/` 下，使用 `编号_中文名.md` 格式
2. 历史文档移入 `docs/archive/`，文件头标注 `> Deprecated — Historical Only`
3. 不在根目录创建新的 .md 文件（除 README、CONTRIBUTING、LICENSE 外）

### 7.3 定期检查

1. **每季度**：运行 `Grep` 搜索已删除组件引用（controller/、matlab_server/、protocol_v3/ 等）
2. **每次发版**：更新 CHANGELOG.md 和 RELEASE_NOTES.md
3. **每次 PR**：检查文档引用的文件路径是否存在

### 7.4 已知技术债务

1. **目录名互换**：`路径规划/` 实存形貌预测算法，`形貌预测/` 实存路径规划算法（历史命名，已在文档中说明）
2. **旧版 communication/ 仍在代码中**：已弃用但保留兼容（repair_protocol_pb2 被 bridge 复用）
3. **.env.example 包含未使用变量**：10 个环境变量在 .env.example 中声明但代码未实际读取
