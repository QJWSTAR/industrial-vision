# CSAM Repair 测试报告

> 生成时间: 2026-07-15 19:48:49  
> Python: Python 3.12.9  
> 项目: CSAM Repair

## 1. 总览

| 指标 | 值 |
|------|-----|
| 全量测试数 | 402 |
| 通过 | 402 |
| 失败 | 0 |
| 错误 | 0 |
| 跳过 | 0 |
| 耗时(s) | 59.49 |
| 状态 | **PASS** |
| 覆盖率 | **49.97%** |

## 2. Coverage（覆盖率）

行覆盖率: **49.97%**（branch coverage 启用）

- 状态: **不达标**（<60%），发布前必须提升
- HTML 报告: `htmlcov/index.html`
- XML 报告: `coverage.xml`（CI/Codecov 兼容）
- 配置: `pyproject.toml [tool.coverage]`
- 排除: tests/、bridge/tests/、自动生成的 protobuf 文件

## 3. Pass（通过）

### 3.1 各 marker 层结果

| 层级 | 测试数 | 通过 | 失败 | 错误 | 跳过 | 耗时(s) | 状态 |
|------|-------|------|------|------|------|--------|------|
| smoke | 15 | 15 | 0 | 0 | 0 | 3.41 | PASS |
| regression | 34 | 34 | 0 | 0 | 0 | 3.5 | PASS |
| gui | 24 | 24 | 0 | 0 | 0 | 6.55 | PASS |
| export | 22 | 22 | 0 | 0 | 0 | 5.02 | PASS |
| mock | 22 | 22 | 0 | 0 | 0 | 3.8 | PASS |
| performance | 9 | 9 | 0 | 0 | 0 | 2.9 | PASS |
| stress | 0 | 0 | 0 | 0 | 0 | 2.79 | PASS |

### 3.2 通过的测试明细

通过测试明细见各层 JUnit XML：

- `test_result_smoke.xml`
- `test_result_regression.xml`
- `test_result_gui.xml`
- `test_result_export.xml`
- `test_result_mock.xml`
- `test_result_performance.xml`
- `test_result_stress.xml`
- `test_result_full.xml`（全量）

运行 `pytest --tb=short -v` 可查看每个测试的详细执行情况。

## 4. Fail（失败）

**无失败或错误测试。** 全部测试通过。


## 5. Flaky Test（不稳定测试）

Flaky 测试指同一代码下偶发通过/失败的测试。本脚本无法单次运行检测 Flaky，需通过 CI 多次运行历史对比识别。以下为已知 Flaky 风险点：

- **GUI 测试**：依赖 Qt 事件循环与定时器，可能在慢速 CI 上偶发崩溃
- **Bridge/ZMQ 测试**：依赖端口绑定与线程同步，可能因端口占用偶发失败
- **loguru stderr sink**：测试退出时后台线程写已关闭的 stderr（噪音，不影响结果）
- **MATLAB 真实集成**：依赖 MATLAB 进程，未在自动化覆盖范围（仅 Mock）

### 检测建议

- CI 配置 `runs-on` 重试机制：失败测试自动重跑 1 次
- 长期跟踪：使用 `pytest --retries 3` 或 `pytest-rerunfailures` 插件
- 关注 `test_result_full.xml` 中的 `<time>` 字段，耗时波动大的测试更易 Flaky

## 6. Risk（发布风险）

- 覆盖率 49.97% **低于 60% 阈值**，发布前必须提升
- 各层测试累加(126)与全量(402)差异较大 (69%)，可能存在 marker 重复选择或无 marker 测试
- MATLAB 真实集成（Bridge Server -> MATLAB）未在自动化测试覆盖范围内
- 真实 License 验证依赖机器码，CI 环境无法覆盖（仅 Mock）

## 7. 测试体系架构

### 7.1 测试分层

| 层级 | 用途 | marker | 文件 |
|------|------|---------|------|
| 冒烟测试 | 核心 import 与启动验证 | `smoke` | `test_smoke.py` |
| 回归测试 | 关键 bug 修复回归 | `regression` | `test_regression.py` |
| GUI 测试 | PySide6 组件验证 | `gui` | `test_gui.py` |
| 导出测试 | G-code/Robot/Report | `export` | `test_export.py` |
| 性能测试 | 耗时基准 | `performance` | `test_performance.py` |
| 压力测试 | 大数据量 | `stress` | `test_stress.py` |
| Mock 测试 | MATLAB/License Mock | `mock` | `test_matlab_mock.py` |
| Bridge 测试 | 通信层 | (无 marker) | `bridge/tests/test_bridge.py` |
| 单元/集成 | 历史 stage 测试 | (无 marker) | `test_stage*.py` |

### 7.2 Mock 体系

- **MATLAB Mock**: `tests/mocks/matlab_mock.py`
  - `deterministic_algorithm` — 确定性算法函数（相同输入相同输出）
  - `MockMatlabAdapter` — 替代 MatlabAdapter（不依赖真实 MATLAB）
  - `make_mock_repair_request` — 构造 protobuf RepairRequest
- **License Mock**: `tests/mocks/license_mock.py`
  - `create_mock_license_env` — 生成临时密钥对 + License 文件
  - `MockLicenseManager` — 不依赖真实机器码
- **Fixture**: `conftest.py` 提供 `mock_matlab` / `mock_license_env` 等 fixture

### 7.3 覆盖率配置

- 工具: `pytest-cov` + `coverage.py`
- 模式: branch coverage（分支覆盖）
- 阈值: `fail_under = 60`（pyproject.toml，CI 强制检查）
- 排除: `tests/`、`bridge/tests/`、`repair_protocol_pb2.py`（自动生成）
- 输出: `coverage.xml`（CI）+ `htmlcov/`（HTML）

### 7.4 CI 集成

GitHub Actions (`.github/workflows/ci.yml`) 6 个 job：

| Job | 触发 | 用途 |
|-----|------|------|
| smoke-test | 所有 PR | 冒烟验证（<2min） |
| test | 主分支+PR | 全量测试 + coverage（3 OS x 3 Py） |
| regression-test | 所有 PR | 回归测试 |
| gui-test | 所有 PR | GUI 测试（offscreen） |
| performance-test | 主分支 | 性能基准（不阻塞） |
| lint | 所有 PR | pre-commit 代码质量 |

## 8. 一键运行

```powershell
# 完整运行（含 coverage）
.\run_all_tests.ps1

# 快速验证（仅 smoke + regression）
.\run_all_tests.ps1 -Quick

# 跳过依赖安装
.\run_all_tests.ps1 -SkipInstall

# 不收集覆盖率（更快）
.\run_all_tests.ps1 -NoCoverage
```

## 9. 修复记录

本次测试体系完善修复的问题：

- 修复 30 处 Fake Test / 恒为 True 的 Assert
- 新增 6 个测试文件共 126 个测试（smoke/regression/gui/export/performance/mock）
- 创建 MATLAB Mock 与 License Mock 模块
- 配置 pytest markers + coverage（pyproject.toml）
- 重写 CI 为 6 个 job（smoke/test/regression/gui/performance/lint）
- 创建一键验证脚本 `run_all_tests.ps1`
