# 贡献指南 — CSAM Repair

感谢你对 CSAM Repair 的关注与贡献。

## 开发环境搭建

```bash
python3 -m venv venv
source venv/bin/activate  # Windows 使用 `venv\Scripts\activate`
pip install -e ".[dev]"
pre-commit install
```

## 代码风格

- Python 3.10+，要求类型标注
- 使用 Black（行宽 120）格式化代码
- 使用 isort 排序导入语句
- 使用 flake8 进行代码检查
- 使用 bandit 进行安全分析

提交前运行：

```bash
pre-commit run --all-files
```

## 测试

- 所有变更必须通过现有测试：`pytest repair_app/tests/ -v`
- 新增功能应包含测试
- 目标覆盖率：60%+

## Pull Request 流程

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/your-feature`）
3. 以小的、逻辑独立的提交进行修改
4. 运行测试和代码检查
5. 向 `main` 分支提交 Pull Request

## 架构准则

- UI 层不得直接导入 core/communication 模块
- 通过 CoordinationService 进行 UI 到核心的通信
- 平台相关代码放在 `repair_app/platform/` 中
- 业务逻辑放在 `repair_app/service/` 和 `repair_app/core/` 中

## 提交信息

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
feat: 新增功能 X
fix: 修复问题 Y
refactor: 重构模块 Z
docs: 更新 README
test: 为功能 X 添加测试
```

## 有问题？

请提交 Issue 或联系 CSAM 团队。