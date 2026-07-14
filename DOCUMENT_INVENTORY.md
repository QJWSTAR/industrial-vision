# 文档清单（Document Inventory）

> 扫描日期：2026-07-14 | 仓库版本：1.0.0 RC | 协议版本：v2.1

本文件记录仓库中所有 Markdown 文档的当前状态评估，作为文档重构的依据。

---

## 1. 根目录文档

| # | 文件路径 | 当前用途 | 是否最新 | 是否重复 | 是否过时 | 建议操作 |
|---|----------|----------|----------|----------|----------|----------|
| 1 | `README.md` | 项目入口、快速开始、架构概览 | 部分 | 否 | 部分（引用 DEVELOPER.md） | 重写 |
| 2 | `CHANGELOG.md` | 版本变更记录 | 否 | 是（与 docs/CHANGELOG.md 重复） | 是（引用 matlab_server/、protocol_v3/ 等已删除组件） | 删除（保留 docs/CHANGELOG.md） |
| 3 | `ARCHITECTURE.md` | 系统架构概述 | 否 | 是（与 docs/10_架构文档.md 重复） | 是（引用 controller/ 已删除） | 删除（合并到 docs/05_软件架构.md） |
| 4 | `CONTRIBUTING.md` | 贡献指南 | 是 | 否 | 否 | 保留（内容合并到 docs/07_开发指南.md） |
| 5 | `PROJECT_FINAL_REPORT.md` | 项目最终交付报告 | 是 | 否 | 否 | 保留（归档参考） |

## 2. docs/ 顶层文档

| # | 文件路径 | 当前用途 | 是否最新 | 是否重复 | 是否过时 | 建议操作 |
|---|----------|----------|----------|----------|----------|----------|
| 6 | `docs/README.md` | 文档中心导航 | 否 | 是（与根 README.md 重复） | 是（引用已删除的 01_快速开始.md 等） | 删除 |
| 7 | `docs/04_工业算法说明.md` | 算法清单与工作流 | 是 | 否 | 否 | 合并到 `docs/04_MATLAB算法说明.md` |
| 8 | `docs/07_开发者文档.md` | 项目结构、模块职责 | 是 | 部分（与 09/10 重叠） | 否 | 合并到 `docs/07_开发指南.md` |
| 9 | `docs/08_运维手册.md` | 日志、备份、升级 | 是 | 否 | 否 | 合并到 `docs/02_安装部署.md` 和 `docs/11_故障排查.md` |
| 10 | `docs/09_API文档.md` | 公开接口签名 | 是 | 否 | 否 | 重命名为 `docs/08_API接口.md` |
| 11 | `docs/10_架构文档.md` | 系统架构图 | 是 | 是（与 ARCHITECTURE.md、BRIDGE_ARCHITECTURE.md 重叠） | 否 | 合并到 `docs/05_软件架构.md` |
| 12 | `docs/BRIDGE_ARCHITECTURE.md` | Bridge 层详细架构 | 是 | 部分（与 COMMUNICATION.md 重叠） | 否 | 合并到 `docs/06_通信协议.md` |
| 13 | `docs/COMMUNICATION.md` | 通信架构决策 | 是 | 部分（与 BRIDGE_ARCHITECTURE.md 重叠） | 否 | 合并到 `docs/06_通信协议.md` |
| 14 | `docs/MATLAB_INTEGRATION.md` | MATLAB 集成指南 | 是 | 部分（与 04_工业算法说明.md 重叠） | 否 | 合并到 `docs/04_MATLAB算法说明.md` |
| 15 | `docs/MATLAB_CALL_GRAPH.md` | .m 文件依赖关系 | 是 | 否 | 否 | 合并到 `docs/04_MATLAB算法说明.md` |
| 16 | `docs/MATLAB_R2025B_Validation_Playbook.md` | MATLAB 验证手册（19 章） | 是 | 否 | 否 | 移到 `docs/archive/` |
| 17 | `docs/PACKAGING_GUIDE.md` | 打包指南 | 是 | 部分（与 UserManual/02 重叠） | 否 | 合并到 `docs/02_安装部署.md` |
| 18 | `docs/CHANGELOG.md` | 版本变更记录 | 是 | 是（与根 CHANGELOG.md 重复） | 否 | 保留（删除根 CHANGELOG.md） |
| 19 | `docs/RELEASE_NOTES_V1.0.md` | V1.0 发布说明 | 是 | 否 | 否 | 重命名为 `docs/RELEASE_NOTES.md` |
| 20 | `docs/RELEASE_CHECKLIST.md` | 发布检查清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |

## 3. docs/UserManual/（11 篇）

| # | 文件路径 | 当前用途 | 是否最新 | 是否重复 | 是否过时 | 建议操作 |
|---|----------|----------|----------|----------|----------|----------|
| 21 | `docs/UserManual/00_索引.md` | 用户手册索引 | 是 | 否 | 否 | 删除（新结构自带导航） |
| 22 | `docs/UserManual/01_软件简介.md` | 软件简介 | 是 | 否 | 否 | 合并到 `docs/10_FAQ.md` 和 README |
| 23 | `docs/UserManual/02_安装指南.md` | 安装指南 | 是 | 部分（与 PACKAGING_GUIDE 重叠） | 否 | 合并到 `docs/02_安装部署.md` |
| 24 | `docs/UserManual/03_第一次使用.md` | 第一次使用 | 是 | 部分（与 README 快速开始重叠） | 否 | 合并到 `docs/01_快速开始.md` |
| 25 | `docs/UserManual/04_完整操作手册.md` | 完整操作手册 | 是 | 否 | 否 | 合并到 `docs/03_用户使用手册.md` |
| 26 | `docs/UserManual/05_典型工作流程.md` | 典型工作流程 | 是 | 部分（与 04 重叠） | 否 | 合并到 `docs/03_用户使用手册.md` |
| 27 | `docs/UserManual/06_案例教程.md` | 案例教程 | 是 | 否 | 否 | 合并到 `docs/03_用户使用手册.md` |
| 28 | `docs/UserManual/07_常见问题.md` | 常见问题 | 是 | 否 | 否 | 合并到 `docs/10_FAQ.md` |
| 29 | `docs/UserManual/08_故障排查.md` | 故障排查 | 是 | 否 | 否 | 合并到 `docs/11_故障排查.md` |
| 30 | `docs/UserManual/09_使用技巧.md` | 使用技巧 | 是 | 否 | 否 | 合并到 `docs/03_用户使用手册.md` |
| 31 | `docs/UserManual/10_术语解释.md` | 术语解释 | 是 | 否 | 否 | 合并到 `docs/10_FAQ.md` |

## 4. docs/checklists/（5 篇）

| # | 文件路径 | 当前用途 | 是否最新 | 是否重复 | 是否过时 | 建议操作 |
|---|----------|----------|----------|----------|----------|----------|
| 32 | `docs/checklists/ACCEPTANCE.md` | 验收清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |
| 33 | `docs/checklists/COMPATIBILITY.md` | 兼容性清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |
| 34 | `docs/checklists/DEPLOYMENT.md` | 部署清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |
| 35 | `docs/checklists/REGRESSION.md` | 回归清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |
| 36 | `docs/checklists/SMOKE_TEST.md` | 冒烟测试清单 | 是 | 否 | 否 | 合并到 `docs/09_测试验证.md` |

## 5. docs/archive/（10 篇，历史归档）

| # | 文件路径 | 当前用途 | 是否最新 | 建议操作 |
|---|----------|----------|----------|----------|
| 37 | `docs/archive/ARCHITECTURE_V3.md` | V3 架构设计（历史） | 否 | 保留（标注 Deprecated） |
| 38 | `docs/archive/MIGRATION_REPORT.md` | 迁移报告（历史） | 否 | 保留 |
| 39 | `docs/archive/PATH_PLANNING_INTEGRATION_REPORT.md` | 路径规划集成报告 | 否 | 保留 |
| 40 | `docs/archive/PROFILE_PREDICTION_INTEGRATION_REPORT.md` | 形貌预测集成报告 | 否 | 保留 |
| 41 | `docs/archive/RELEASE_CANDIDATE_REPORT_V1.0.md` | RC 报告 V1.0 | 否 | 保留 |
| 42 | `docs/archive/RELEASE_VALIDATION_REPORT.md` | 发布验证报告 | 否 | 保留 |
| 43 | `docs/archive/MATLAB_INTEGRATION_ARCHITECTURE.md` | MATLAB 集成架构（历史） | 否 | 保留 |
| 44 | `docs/archive/GUI_VISUALIZATION_DESIGN.md` | GUI 可视化设计 | 否 | 保留 |
| 45 | `docs/archive/06_故障排查.md` | 旧版故障排查 | 否 | 保留 |
| 46 | `docs/archive/端到端仿真验证报告.md` | 端到端仿真验证 | 否 | 保留 |

## 6. .github/ 模板（3 篇）

| # | 文件路径 | 当前用途 | 建议操作 |
|---|----------|----------|----------|
| 47 | `.github/pull_request_template.md` | PR 模板 | 保留 |
| 48 | `.github/ISSUE_TEMPLATE/bug_report.md` | Bug 报告模板 | 保留 |
| 49 | `.github/ISSUE_TEMPLATE/feature_request.md` | 功能请求模板 | 保留 |

---

## 统计摘要

| 指标 | 数量 |
|------|------|
| 扫描文档总数 | 49 |
| 保留文档 | 16（含 10 篇归档 + 3 篇 GitHub 模板 + CONTRIBUTING + PROJECT_FINAL_REPORT + docs/CHANGELOG） |
| 合并文档 | 25 |
| 删除文档 | 8（根 CHANGELOG/ARCHITECTURE + docs/README + UserManual/00_索引 + UserManual/01_软件简介 等） |
| 新建文档 | 11（01_快速开始 ~ 11_故障排查） + 1（RELEASE_NOTES.md 重命名） |
| 最终活跃文档 | 15（11 篇编号 + CHANGELOG + RELEASE_NOTES + README + CONTRIBUTING） |
