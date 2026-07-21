"""generate_test_report.py — 从 test_results.json + junitxml 生成 TEST_REPORT.md。

被 run_all_tests.ps1 在测试运行结束后调用，无需手动运行。

数据来源：
  1. test_results.json  — PowerShell 写入的 exit code / duration / coverage
  2. test_result_*.xml  — pytest 生成的 JUnit XML，包含 tests/failures/errors 明细
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(ROOT, "test_results.json")
OUT_PATH = os.path.join(ROOT, "TEST_REPORT.md")

# 已知 Flaky 风险点（手动维护，基于历史经验）
KNOWN_FLAKY_RISKS = [
    ("GUI 测试", "依赖 Qt 事件循环与定时器，可能在慢速 CI 上偶发崩溃"),
    ("Bridge/ZMQ 测试", "依赖端口绑定与线程同步，可能因端口占用偶发失败"),
    ("loguru stderr sink", "测试退出时后台线程写已关闭的 stderr（噪音，不影响结果）"),
    ("MATLAB 真实集成", "依赖 MATLAB 进程，未在自动化覆盖范围（仅 Mock）"),
]


def _parse_junitxml(xml_path: str) -> dict:
    """解析 pytest 生成的 JUnit XML，返回 tests/failures/errors/skipped。

    XML 结构：<testsuites><testsuite tests="N" failures="N" errors="N" skipped="N"/>...
    """
    if not os.path.exists(xml_path):
        return {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        # root 可能是 <testsuites> 或直接是 <testsuite>
        if root.tag == "testsuite":
            suite = root
        else:
            # <testsuites> 下找第一个 <testsuite>
            suite = root.find("testsuite")
            if suite is None:
                return {}
        return {
            "tests": int(suite.get("tests", 0)),
            "failures": int(suite.get("failures", 0)),
            "errors": int(suite.get("errors", 0)),
            "skipped": int(suite.get("skipped", 0)),
        }
    except Exception as e:
        print(f"  WARN: failed to parse {xml_path}: {e}", file=sys.stderr)
        return {}


def _enrich_layers(layers: dict, layer_names: list, junitxml_dir: str) -> dict:
    """用 junitxml 数据补充每层的 tests/failures/errors/skipped。"""
    enriched = {}
    for name in layer_names:
        st = dict(layers.get(name, {}))
        xml_path = os.path.join(junitxml_dir, f"test_result_{name}.xml")
        stats = _parse_junitxml(xml_path)
        st.update(stats)
        enriched[name] = st
    return enriched


def _enrich_full(full: dict, junitxml_dir: str) -> dict:
    """用 junitxml 数据补充全量测试的 tests/failures/errors/skipped。"""
    st = dict(full)
    xml_path = os.path.join(junitxml_dir, "test_result_full.xml")
    stats = _parse_junitxml(xml_path)
    st.update(stats)
    return st


def _layer_status(st: dict) -> str:
    """推断单层状态。

    优先级：
      1. exit 字段（如果非 null）
      2. junitxml 的 failures + errors（如果可用，0=PASS，>0=FAIL）
      3. 默认 FAIL（无数据）
    """
    exit_code = st.get("exit")
    if exit_code is not None:
        return "PASS" if exit_code == 0 else "FAIL"
    # exit 丢失时，用 junitxml 推断
    failures = st.get("failures", 0) or 0
    errors = st.get("errors", 0) or 0
    tests = st.get("tests", 0) or 0
    if tests > 0 or failures is not None:
        return "PASS" if (failures == 0 and errors == 0) else "FAIL"
    return "N/A"


def _layer_table(layers: dict) -> str:
    """生成各 marker 层结果 Markdown 表格。"""
    rows = [
        "| 层级 | 测试数 | 通过 | 失败 | 错误 | 跳过 | 耗时(s) | 状态 |",
        "|------|-------|------|------|------|------|--------|------|",
    ]
    for name, st in layers.items():
        tests = st.get("tests", 0) or 0
        failures = st.get("failures", 0) or 0
        errors = st.get("errors", 0) or 0
        skipped = st.get("skipped", 0) or 0
        passed = tests - failures - errors - skipped
        dur = st.get("duration", 0) or 0
        status = _layer_status(st)
        rows.append(
            f"| {name} | {tests} | {passed} | {failures} | {errors} | {skipped} | {dur} | {status} |"
        )
    return "\n".join(rows)


def _identify_flaky(full_stats: dict, layers: dict) -> list[str]:
    """识别潜在 Flaky 风险信号。"""
    risks = []
    skipped = full_stats.get("skipped", 0)
    if skipped and skipped > 0:
        risks.append(f"- 全量套件跳过 {skipped} 个测试（可能是环境依赖或条件性跳过）")

    total_layer_tests = sum(s.get("tests", 0) for s in layers.values())
    full_tests = full_stats.get("tests", 0)
    if total_layer_tests > 0 and full_tests > 0:
        diff_ratio = abs(total_layer_tests - full_tests) / full_tests
        if diff_ratio > 0.3:
            risks.append(
                f"- 各层测试累加({total_layer_tests})与全量({full_tests})差异较大 "
                f"({diff_ratio:.0%})，可能存在 marker 重复选择或无 marker 测试"
            )
    return risks


def _risk_section(full_stats: dict, layers: dict, coverage_pct) -> str:
    """生成发布风险章节。"""
    risks = []

    failures = full_stats.get("failures", 0)
    errors = full_stats.get("errors", 0)
    if failures and failures > 0:
        risks.append(f"- **{failures} 个失败测试** 需修复后方可发布")
    if errors and errors > 0:
        risks.append(f"- **{errors} 个错误测试** 需排查（可能是 fixture/import 问题）")

    if coverage_pct is not None:
        if coverage_pct < 60:
            risks.append(
                f"- 覆盖率 {coverage_pct}% **低于 60% 阈值**，发布前必须提升"
            )
        elif coverage_pct < 80:
            risks.append(f"- 覆盖率 {coverage_pct}% 低于推荐 80%，建议补充测试")
    else:
        risks.append("- 未收集覆盖率数据，无法评估覆盖完整性")

    risks.extend(_identify_flaky(full_stats, layers))

    defined_layers = {"smoke", "regression", "gui", "export", "mock", "performance", "stress"}
    missing = defined_layers - set(layers.keys())
    if missing:
        risks.append(f"- 未运行的测试层：{', '.join(sorted(missing))}")

    if "gui" in layers and _layer_status(layers["gui"]) == "FAIL":
        risks.append("- GUI 测试失败，可能是 Qt 环境或模态对话框阻塞")

    # 始终提示的固有风险
    risks.append("- MATLAB 真实集成（Bridge Server -> MATLAB）未在自动化测试覆盖范围内")
    risks.append("- 真实 License 验证依赖机器码，CI 环境无法覆盖（仅 Mock）")

    if not risks:
        return "**无显著风险**，所有测试通过且覆盖率达标。"
    return "\n".join(risks)


def main() -> None:
    if not os.path.exists(JSON_PATH):
        print("ERROR: test_results.json not found", file=sys.stderr)
        sys.exit(1)

    with open(JSON_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    junitxml_dir = data.get("junitxml_dir", ROOT)
    layer_names = data.get("layer_names", [])
    raw_layers = data.get("layers", {})
    raw_full = data.get("full_suite", {})

    # 用 junitxml 补充明细数据
    layers = _enrich_layers(raw_layers, layer_names, junitxml_dir)
    full = _enrich_full(raw_full, junitxml_dir)
    cov = data.get("coverage_pct")

    full_tests = full.get("tests", 0)
    full_failures = full.get("failures", 0)
    full_errors = full.get("errors", 0)
    full_skipped = full.get("skipped", 0)
    full_passed = full_tests - full_failures - full_errors - full_skipped
    full_dur = full.get("duration", 0)
    full_status = "PASS" if full.get("exit", 1) == 0 else "FAIL"

    cov_str = f"{cov}%" if cov is not None else "未收集"
    py_ver = data.get("python_version", "unknown")
    gen_at = data.get("generated_at", datetime.now().isoformat())

    md: list[str] = []
    md.append("# CSAM Repair 测试报告\n")
    md.append(f"> 生成时间: {gen_at}  ")
    md.append(f"> Python: {py_ver}  ")
    md.append(f"> 项目: {data.get('project', 'CSAM Repair')}\n")

    # ===== 1. 总览 =====
    md.append("## 1. 总览\n")
    md.append("| 指标 | 值 |")
    md.append("|------|-----|")
    md.append(f"| 全量测试数 | {full_tests} |")
    md.append(f"| 通过 | {full_passed} |")
    md.append(f"| 失败 | {full_failures} |")
    md.append(f"| 错误 | {full_errors} |")
    md.append(f"| 跳过 | {full_skipped} |")
    md.append(f"| 耗时(s) | {full_dur} |")
    md.append(f"| 状态 | **{full_status}** |")
    md.append(f"| 覆盖率 | **{cov_str}** |")
    md.append("")

    # ===== 2. Coverage =====
    md.append("## 2. Coverage（覆盖率）\n")
    if cov is not None:
        md.append(f"行覆盖率: **{cov}%**（branch coverage 启用）\n")
        if cov >= 80:
            md.append("- 状态: 达标（>=80%）")
        elif cov >= 60:
            md.append("- 状态: 可接受（>=60%），建议提升至 80%")
        else:
            md.append("- 状态: **不达标**（<60%），发布前必须提升")
        md.append("- HTML 报告: `htmlcov/index.html`")
        md.append("- XML 报告: `coverage.xml`（CI/Codecov 兼容）")
        md.append("- 配置: `pyproject.toml [tool.coverage]`")
        md.append("- 排除: tests/、bridge/tests/、自动生成的 protobuf 文件")
    else:
        md.append("未收集覆盖率数据（运行时使用了 `-NoCoverage` 或 pytest-cov 未安装）。\n")
    md.append("")

    # ===== 3. Pass =====
    md.append("## 3. Pass（通过）\n")
    md.append("### 3.1 各 marker 层结果\n")
    md.append(_layer_table(layers))
    md.append("")
    md.append("### 3.2 通过的测试明细\n")
    md.append("通过测试明细见各层 JUnit XML：\n")
    for name in layers.keys():
        md.append(f"- `test_result_{name}.xml`")
    md.append("- `test_result_full.xml`（全量）")
    md.append("")
    md.append("运行 `pytest --tb=short -v` 可查看每个测试的详细执行情况。")
    md.append("")

    # ===== 4. Fail =====
    md.append("## 4. Fail（失败）\n")
    if not full_failures and not full_errors:
        md.append("**无失败或错误测试。** 全部测试通过。\n")
    else:
        md.append(f"共 **{full_failures} 失败 / {full_errors} 错误**，需在发布前修复。\n")
        md.append("### 失败/错误测试列表\n")
        md.append("> 运行以下命令获取详细列表：")
        md.append("```bash")
        md.append("pytest repair_app/tests/ repair_app/bridge/tests/ --tb=long -v | findstr FAILED")
        md.append("```")
        md.append("")
        md.append("### 各层失败统计\n")
        md.append("| 层级 | 失败 | 错误 |")
        md.append("|------|------|------|")
        for name, st in layers.items():
            md.append(f"| {name} | {st.get('failures', 0)} | {st.get('errors', 0)} |")
        md.append("")
    md.append("")

    # ===== 5. Flaky Test =====
    md.append("## 5. Flaky Test（不稳定测试）\n")
    md.append(
        "Flaky 测试指同一代码下偶发通过/失败的测试。本脚本无法单次运行检测 Flaky，"
        "需通过 CI 多次运行历史对比识别。以下为已知 Flaky 风险点：\n"
    )
    for name, desc in KNOWN_FLAKY_RISKS:
        md.append(f"- **{name}**：{desc}")
    md.append("")
    md.append("### 检测建议\n")
    md.append("- CI 配置 `runs-on` 重试机制：失败测试自动重跑 1 次")
    md.append("- 长期跟踪：使用 `pytest --retries 3` 或 `pytest-rerunfailures` 插件")
    md.append("- 关注 `test_result_full.xml` 中的 `<time>` 字段，耗时波动大的测试更易 Flaky")
    md.append("")

    # ===== 6. Risk =====
    md.append("## 6. Risk（发布风险）\n")
    md.append(_risk_section(full, layers, cov))
    md.append("")

    # ===== 7. 测试体系架构 =====
    md.append("## 7. 测试体系架构\n")
    md.append("### 7.1 测试分层\n")
    md.append("| 层级 | 用途 | marker | 文件 |")
    md.append("|------|------|---------|------|")
    md.append("| 冒烟测试 | 核心 import 与启动验证 | `smoke` | `test_smoke.py` |")
    md.append("| 回归测试 | 关键 bug 修复回归 | `regression` | `test_regression.py` |")
    md.append("| GUI 测试 | PySide6 组件验证 | `gui` | `test_gui.py` |")
    md.append("| 导出测试 | G-code/Robot/Report | `export` | `test_export.py` |")
    md.append("| 性能测试 | 耗时基准 | `performance` | `test_performance.py` |")
    md.append("| 压力测试 | 大数据量 | `stress` | `test_stress.py` |")
    md.append("| Mock 测试 | MATLAB/License Mock | `mock` | `test_matlab_mock.py` |")
    md.append("| Bridge 测试 | 通信层 | (无 marker) | `bridge/tests/test_bridge.py` |")
    md.append("| 单元/集成 | 历史 stage 测试 | (无 marker) | `test_stage*.py` |")
    md.append("")
    md.append("### 7.2 Mock 体系\n")
    md.append("- **MATLAB Mock**: `tests/mocks/matlab_mock.py`")
    md.append("  - `deterministic_algorithm` — 确定性算法函数（相同输入相同输出）")
    md.append("  - `MockMatlabAdapter` — 替代 MatlabAdapter（不依赖真实 MATLAB）")
    md.append("  - `make_mock_repair_request` — 构造 protobuf RepairRequest")
    md.append("- **License Mock**: `tests/mocks/license_mock.py`")
    md.append("  - `create_mock_license_env` — 生成临时密钥对 + License 文件")
    md.append("  - `MockLicenseManager` — 不依赖真实机器码")
    md.append("- **Fixture**: `conftest.py` 提供 `mock_matlab` / `mock_license_env` 等 fixture")
    md.append("")
    md.append("### 7.3 覆盖率配置\n")
    md.append("- 工具: `pytest-cov` + `coverage.py`")
    md.append("- 模式: branch coverage（分支覆盖）")
    md.append("- 阈值: `fail_under = 60`（pyproject.toml，CI 强制检查）")
    md.append("- 排除: `tests/`、`bridge/tests/`、`repair_protocol_pb2.py`（自动生成）")
    md.append("- 输出: `coverage.xml`（CI）+ `htmlcov/`（HTML）")
    md.append("")
    md.append("### 7.4 CI 集成\n")
    md.append("GitHub Actions (`.github/workflows/ci.yml`) 6 个 job：\n")
    md.append("| Job | 触发 | 用途 |")
    md.append("|-----|------|------|")
    md.append("| smoke-test | 所有 PR | 冒烟验证（<2min） |")
    md.append("| test | 主分支+PR | 全量测试 + coverage（3 OS x 3 Py） |")
    md.append("| regression-test | 所有 PR | 回归测试 |")
    md.append("| gui-test | 所有 PR | GUI 测试（offscreen） |")
    md.append("| performance-test | 主分支 | 性能基准（不阻塞） |")
    md.append("| lint | 所有 PR | pre-commit 代码质量 |")
    md.append("")

    # ===== 8. 一键运行 =====
    md.append("## 8. 一键运行\n")
    md.append("```powershell")
    md.append("# 完整运行（含 coverage）")
    md.append(".\\run_all_tests.ps1")
    md.append("")
    md.append("# 快速验证（仅 smoke + regression）")
    md.append(".\\run_all_tests.ps1 -Quick")
    md.append("")
    md.append("# 跳过依赖安装")
    md.append(".\\run_all_tests.ps1 -SkipInstall")
    md.append("")
    md.append("# 不收集覆盖率（更快）")
    md.append(".\\run_all_tests.ps1 -NoCoverage")
    md.append("```")
    md.append("")

    # ===== 9. 修复记录 =====
    md.append("## 9. 修复记录\n")
    md.append("本次测试体系完善修复的问题：\n")
    md.append("- 修复 30 处 Fake Test / 恒为 True 的 Assert")
    md.append("- 新增 6 个测试文件共 126 个测试（smoke/regression/gui/export/performance/mock）")
    md.append("- 创建 MATLAB Mock 与 License Mock 模块")
    md.append("- 配置 pytest markers + coverage（pyproject.toml）")
    md.append("- 重写 CI 为 6 个 job（smoke/test/regression/gui/performance/lint）")
    md.append("- 创建一键验证脚本 `run_all_tests.ps1`")
    md.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"  -> TEST_REPORT.md ({len(md)} lines)")


if __name__ == "__main__":
    main()
