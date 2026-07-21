"""validation.diff_report_generator — Diff Report 自动生成

生成 Markdown 格式的比对报告，包含：
- 验证概览（时间戳、测试输入、系统信息）
- 算法版本（MATLAB / Python）
- MATLAB Runtime 版本
- 耗时对比
- 6 维度误差表（pointlist/velocitylist/Layer/Mesh/Volume/Uniformity）
- 总结（通过/失败统计）

报告保存到统一日志目录（PathManager.logs_dir）或指定路径。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from datetime import datetime

from repair_app.validation.algorithm_validator import (
    ValidationResult, VALIDATION_FRAMEWORK_VERSION,
    MATLAB_ALGORITHM_VERSION, PYTHON_ALGORITHM_VERSION,
)
from repair_app.validation.result_comparator import ComparisonReport


class DiffReportGenerator:
    """Diff Report 生成器。"""

    def generate(
        self,
        validation_result: ValidationResult,
        comparison_report: ComparisonReport,
        output_path: Optional[Path] = None,
    ) -> Path:
        """生成 Markdown 报告并保存。

        Args:
            validation_result: 验证结果（双引擎输出）
            comparison_report: 比对报告（6 维度）
            output_path: 输出路径，None 则自动保存到 logs 目录
        Returns:
            报告文件路径
        """
        if output_path is None:
            output_path = self._default_output_path()

        content = self._build_markdown(validation_result, comparison_report)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def _default_output_path(self) -> Path:
        """默认输出路径：logs/algorithm_diff_YYYYMMDD_HHMMSS.md。"""
        try:
            from repair_app.software.path_manager import PathManager
            logs_dir = PathManager.get_instance().logs_dir
        except Exception:
            logs_dir = Path(".")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"algorithm_diff_{ts}.md"

    def _build_markdown(
        self,
        vr: ValidationResult,
        cr: ComparisonReport,
    ) -> str:
        """构建完整 Markdown 报告。"""
        lines = []
        mr = vr.matlab_result
        pr = vr.python_result

        # ---- 标题 ----
        lines.append("# 算法验证 Diff Report")
        lines.append("")
        lines.append(f"> 自动生成于 {vr.validation_timestamp}")
        lines.append(f"> 验证框架版本 v{vr.framework_version}")
        lines.append("")

        # ---- 1. 验证概览 ----
        lines.append("## 1. 验证概览")
        lines.append("")
        overall_icon = "✅ 通过" if cr.overall_passed else "❌ 存在差异"
        lines.append(f"- **总体结论**：{overall_icon}")
        lines.append(f"- **指标统计**：{cr.passed_metrics}/{cr.total_metrics} 项通过，{cr.failed_metrics} 项失败")
        lines.append("")
        lines.append("### 测试输入")
        ti = vr.test_input_summary
        lines.append(f"- 随机种子：{ti.get('seed')}")
        lines.append(f"- 缺陷类型：{', '.join(ti.get('defect_types', []))}")
        lines.append(f"- 点云点数：{ti.get('n_points')}")
        lines.append(f"- 缺陷点数：{ti.get('defect_point_count')}")
        lines.append("")

        # ---- 2. 算法版本 ----
        lines.append("## 2. 算法版本")
        lines.append("")
        lines.append("| 引擎 | 算法版本 | MATLAB Runtime |")
        lines.append("|------|----------|----------------|")
        matlab_rt = mr.matlab_runtime_version or "—"
        lines.append(f"| MATLAB | {mr.algorithm_version} | {matlab_rt} |")
        lines.append(f"| Python | {pr.algorithm_version} | — |")
        lines.append("")

        # ---- 3. 系统信息 ----
        lines.append("## 3. 系统信息")
        lines.append("")
        si = vr.system_info
        lines.append(f"- Python：{si.get('python')}")
        lines.append(f"- 平台：{si.get('platform')}")
        lines.append(f"- NumPy：{si.get('numpy')}")
        lines.append("")

        # ---- 4. 耗时对比 ----
        lines.append("## 4. 耗时对比")
        lines.append("")
        lines.append("| 引擎 | 执行耗时 | 状态 |")
        lines.append("|------|----------|------|")
        m_status = "✅ 成功" if mr.success else "❌ 失败"
        p_status = "✅ 成功" if pr.success else "❌ 失败"
        lines.append(f"| MATLAB | {mr.elapsed_s:.3f}s | {m_status} |")
        lines.append(f"| Python | {pr.elapsed_s:.3f}s | {p_status} |")
        if mr.success and pr.success and mr.elapsed_s > 0 and pr.elapsed_s > 0:
            speedup = mr.elapsed_s / pr.elapsed_s
            lines.append("")
            lines.append(f"- MATLAB / Python 耗时比：**{speedup:.2f}x**")
            if speedup > 1:
                lines.append(f"- Python 比 MATLAB 快 {speedup:.1f} 倍（MATLAB 计算更复杂）")
            else:
                lines.append(f"- MATLAB 比 Python 快 {1/speedup:.1f} 倍")
        lines.append("")

        # ---- 5. 六维度比对 ----
        lines.append("## 5. 六维度结果比对")
        lines.append("")

        for idx, dim in enumerate(cr.dimensions):
            lines.append(f"### 5.{idx+1} {dim.dimension} {dim.status_icon}")
            lines.append("")
            lines.append(f"- {dim.summary}")
            if not dim.matlab_available or not dim.python_available:
                lines.append("- ⚠️ 一方或双方无数据，跳过比对")
                lines.append("")
                continue
            lines.append("")
            lines.append("| 指标 | MATLAB | Python | 绝对误差 | 相对误差 | 结果 |")
            lines.append("|------|--------|--------|----------|----------|------|")
            for m in dim.metrics:
                lines.append(
                    f"| {m.name} | {m.matlab_value:.4f} | {m.python_value:.4f} | "
                    f"{m.abs_error:.4f} | {m.rel_error:.2f}% | {m.status_icon} |"
                )
            lines.append("")

        # ---- 6. 失败项详情 ----
        failed_metrics = []
        for dim in cr.dimensions:
            for m in dim.metrics:
                if not m.passed:
                    failed_metrics.append((dim.dimension, m))
        if failed_metrics:
            lines.append("## 6. 失败项详情")
            lines.append("")
            for dim_name, m in failed_metrics:
                lines.append(f"- **{dim_name} / {m.name}**：MATLAB={m.matlab_value:.4f}，Python={m.python_value:.4f}，相对误差 {m.rel_error:.2f}%")
                if m.note:
                    lines.append(f"  - {m.note}")
            lines.append("")
        else:
            lines.append("## 6. 失败项详情")
            lines.append("")
            lines.append("无失败项，所有指标均在容差范围内。")
            lines.append("")

        # ---- 7. 引擎异常 ----
        if not mr.success or not pr.success:
            lines.append("## 7. 引擎执行异常")
            lines.append("")
            if not mr.success:
                lines.append(f"- **MATLAB 引擎失败**：{mr.error_message}")
            if not pr.success:
                lines.append(f"- **Python 引擎失败**：{pr.error_message}")
            lines.append("")

        # ---- 8. 警告信息 ----
        all_warnings = list(mr.warnings) + list(pr.warnings)
        if all_warnings:
            lines.append("## 8. 警告信息")
            lines.append("")
            if mr.warnings:
                lines.append("**MATLAB 警告**：")
                for w in mr.warnings[:10]:
                    lines.append(f"- {w}")
            if pr.warnings:
                lines.append("**Python 警告**：")
                for w in pr.warnings[:10]:
                    lines.append(f"- {w}")
            lines.append("")

        # ---- 9. 工艺参数 ----
        lines.append("## 9. 工艺参数")
        lines.append("")
        params = vr.test_input_summary.get("params", {})
        lines.append("| 参数 | 值 |")
        lines.append("|------|----|")
        for k, v in sorted(params.items()):
            lines.append(f"| {k} | {v} |")
        lines.append("")

        # ---- 页脚 ----
        lines.append("---")
        lines.append(f"*由算法验证框架 v{VALIDATION_FRAMEWORK_VERSION} 自动生成*")

        return "\n".join(lines)

    def generate_console_summary(
        self,
        validation_result: ValidationResult,
        comparison_report: ComparisonReport,
    ) -> str:
        """生成控制台摘要（简短）。"""
        mr = validation_result.matlab_result
        pr = validation_result.python_result
        lines = [
            "=" * 60,
            "算法验证结果摘要",
            "=" * 60,
            f"MATLAB: {'✅' if mr.success else '❌'} {mr.elapsed_s:.3f}s | "
            f"Python: {'✅' if pr.success else '❌'} {pr.elapsed_s:.3f}s",
            f"MATLAB Runtime: {mr.matlab_runtime_version or 'unknown'}",
            f"算法版本: MATLAB={mr.algorithm_version} Python={pr.algorithm_version}",
            "-" * 60,
            f"总体: {comparison_report.passed_metrics}/{comparison_report.total_metrics} 项通过 "
            f"({'✅ 全部通过' if comparison_report.overall_passed else '❌ 存在差异'})",
            "",
        ]
        for dim in comparison_report.dimensions:
            lines.append(f"  {dim.status_icon} {dim.dimension:15s} — {dim.summary}")
        lines.append("=" * 60)
        return "\n".join(lines)
