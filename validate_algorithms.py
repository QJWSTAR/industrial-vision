#!/usr/bin/env python3
"""
validate_algorithms.py — 算法验证 CLI 入口

对同一输入点云，分别执行 MATLAB 和 Python 算法，
自动比对 6 维度结果（pointlist/velocitylist/Layer/Mesh/Volume/Uniformity），
生成 Diff Report（Markdown）。

用法：
    python validate_algorithms.py                    # 默认 seed=42, pit 缺陷
    python validate_algorithms.py --seed 100         # 指定种子
    python validate_algorithms.py --defect pit groove  # 多缺陷类型
    python validate_algorithms.py --output report.md # 指定输出路径
    python validate_algorithms.py --no-matlab        # 仅 Python（MATLAB 不可用时）

不开发新算法，只验证现有 MATLAB 与 Python 算法的一致性。
"""
from __future__ import annotations

import argparse
import os
import sys

# 确保项目根在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="算法验证：MATLAB vs Python 双引擎比对",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python validate_algorithms.py
  python validate_algorithms.py --seed 100 --defect pit groove
  python validate_algorithms.py --output my_report.md
        """,
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="随机种子（默认 42，确定性可复现）",
    )
    parser.add_argument(
        "--defect", nargs="+", default=["pit"],
        choices=["pit", "groove", "scratch", "irregular"],
        help="缺陷类型（默认 pit）",
    )
    parser.add_argument(
        "--n-points", type=int, default=8000,
        help="点云点数（默认 8000）",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="报告输出路径（默认 logs/algorithm_diff_YYYYMMDD_HHMMSS.md）",
    )
    parser.add_argument(
        "--no-matlab", action="store_true",
        help="跳过 MATLAB 引擎（MATLAB 不可用时，仅生成 Python 结果）",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="静默模式，只输出摘要",
    )
    args = parser.parse_args()

    # ---- 导入验证模块 ----
    from repair_app.validation.algorithm_validator import AlgorithmValidator
    from repair_app.validation.result_comparator import ResultComparator
    from repair_app.validation.diff_report_generator import DiffReportGenerator

    if not args.quiet:
        print("=" * 60)
        print("算法验证体系 — MATLAB vs Python 双引擎比对")
        print("=" * 60)
        print(f"种子: {args.seed}")
        print(f"缺陷类型: {', '.join(args.defect)}")
        print(f"点云点数: {args.n_points}")
        if args.no_matlab:
            print("模式: 仅 Python（跳过 MATLAB）")
        print("-" * 60)

    # ---- 1. 执行双引擎验证 ----
    validator = AlgorithmValidator()
    if not args.quiet and not args.no_matlab:
        print("正在执行 MATLAB 引擎...")
    validation_result = validator.validate(
        seed=args.seed,
        defect_types=args.defect,
        n_points=args.n_points,
        skip_matlab=args.no_matlab,
    )

    # 如果 MATLAB 失败且未指定 --no-matlab，提示但仍继续
    if not validation_result.matlab_result.success and not args.no_matlab:
        if not args.quiet:
            print(f"⚠️ MATLAB 引擎失败: {validation_result.matlab_result.error_message}")
            print("  将继续生成报告（MATLAB 部分标记为失败）")

    if not args.quiet:
        print(f"MATLAB: {'✅' if validation_result.matlab_result.success else '❌'} "
              f"{validation_result.matlab_result.elapsed_s:.3f}s")
        print("正在执行 Python 引擎...")
        print(f"Python: {'✅' if validation_result.python_result.success else '❌'} "
              f"{validation_result.python_result.elapsed_s:.3f}s")
        print("-" * 60)
        print("正在比对 6 维度结果...")

    # ---- 2. 6 维度比对 ----
    comparator = ResultComparator()
    comparison_report = comparator.compare(validation_result)

    # ---- 3. 生成 Diff Report ----
    generator = DiffReportGenerator()
    output_path = generator.generate(
        validation_result,
        comparison_report,
        output_path=args.output if args.output else None,
    )

    # ---- 4. 输出摘要 ----
    summary = generator.generate_console_summary(validation_result, comparison_report)
    print(summary)
    print(f"\n报告已保存: {output_path}")

    # ---- 5. 退出码 ----
    return 0 if comparison_report.overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
