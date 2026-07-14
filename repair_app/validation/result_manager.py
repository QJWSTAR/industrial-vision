"""Result manager — store, compare, and report validation results.

Provides result storage, comparison between runs, and automatic
report generation for validation experiments.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import json
import os
import csv
import io

import numpy as np

from repair_app.utils.logger_config import info


@dataclass
class ResultSummary:
    """Summary of validation results across multiple experiments."""
    total_experiments: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    avg_duration_s: float = 0.0
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)  # metric_name → {mean, min, max, std}
    experiments: list[dict] = field(default_factory=list)
    generated_at: str = ""


class ResultManager:
    """Manages validation results: storage, comparison, and reporting."""

    def __init__(self, exp_manager=None) -> None:
        from repair_app.validation.experiment import ExperimentManager
        self._exp_manager = exp_manager or ExperimentManager()

    def summarize(self, name: str) -> ResultSummary:
        """Generate a summary of all experiments with the given name.

        Args:
            name: Experiment name to summarize.

        Returns:
            ResultSummary with aggregate statistics.
        """
        experiments = self._exp_manager.list_experiments(name)
        summary = ResultSummary(
            total_experiments=len(experiments),
            generated_at=datetime.now().isoformat(),
        )

        all_metrics: dict[str, list[float]] = {}
        durations: list[float] = []

        for exp_info in experiments:
            try:
                record = self._exp_manager.load_experiment(name, exp_info["id"])
            except Exception:
                continue

            summary.experiments.append({
                "id": exp_info["id"],
                "status": record.status,
                "created_at": record.created_at,
                "duration_s": record.duration_s,
                "metrics": record.metrics,
                "validation_count": len(record.validation_results),
            })

            if record.status == "completed":
                summary.passed += 1
            else:
                summary.failed += 1

            if record.duration_s > 0:
                durations.append(record.duration_s)

            for k, v in record.metrics.items():
                if k not in all_metrics:
                    all_metrics[k] = []
                all_metrics[k].append(v)

        # Compute aggregate statistics
        if summary.total_experiments > 0:
            summary.pass_rate = summary.passed / summary.total_experiments * 100

        if durations:
            summary.avg_duration_s = float(np.mean(durations))

        for k, vals in all_metrics.items():
            arr = np.array(vals)
            summary.metrics[k] = {
                "mean": float(np.mean(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "std": float(np.std(arr)),
            }

        return summary

    def generate_report(self, name: str, format: str = "markdown") -> str:
        """Generate a validation report.

        Args:
            name: Experiment name.
            format: "markdown" or "csv".

        Returns:
            Report string.
        """
        summary = self.summarize(name)

        if format == "markdown":
            return self._generate_markdown_report(name, summary)
        elif format == "csv":
            return self._generate_csv_report(name, summary)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def save_report(self, name: str, output_dir: str, format: str = "markdown") -> str:
        """Save a report to disk.

        Returns:
            Path to the saved report file.
        """
        report = self.generate_report(name, format)
        ext = "md" if format == "markdown" else "csv"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"validation_report_{name}_{timestamp}.{ext}"
        filepath = os.path.join(output_dir, filename)
        os.makedirs(output_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        info(f"Report saved: {filepath}")
        return filepath

    def _generate_markdown_report(self, name: str, summary: ResultSummary) -> str:
        """Generate a Markdown validation report."""
        lines = [
            f"# Validation Report: {name}",
            f"",
            f"**Generated**: {summary.generated_at}",
            f"",
            f"## Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Experiments | {summary.total_experiments} |",
            f"| Passed | {summary.passed} |",
            f"| Failed | {summary.failed} |",
            f"| Pass Rate | {summary.pass_rate:.1f}% |",
            f"| Avg Duration | {summary.avg_duration_s:.2f}s |",
            f"",
        ]

        if summary.metrics:
            lines.append("## Aggregate Metrics")
            lines.append("")
            lines.append("| Metric | Mean | Min | Max | Std |")
            lines.append("|--------|------|-----|-----|-----|")
            for k, v in summary.metrics.items():
                lines.append(
                    f"| {k} | {v['mean']:.4f} | {v['min']:.4f} | {v['max']:.4f} | {v['std']:.4f} |"
                )
            lines.append("")

        if summary.experiments:
            lines.append("## Experiment Details")
            lines.append("")
            lines.append("| ID | Status | Duration | Validation Count |")
            lines.append("|----|--------|----------|------------------|")
            for exp in summary.experiments:
                lines.append(
                    f"| {exp['id']} | {exp['status']} | {exp['duration_s']:.2f}s | {exp['validation_count']} |"
                )
            lines.append("")

        return "\n".join(lines)

    def _generate_csv_report(self, name: str, summary: ResultSummary) -> str:
        """Generate a CSV validation report."""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["name", "total_experiments", "passed", "failed", "pass_rate", "avg_duration_s"])
        writer.writerow([name, summary.total_experiments, summary.passed, summary.failed, summary.pass_rate, summary.avg_duration_s])

        if summary.experiments:
            writer.writerow([])
            writer.writerow(["exp_id", "status", "duration_s", "validation_count"])
            for exp in summary.experiments:
                writer.writerow([exp["id"], exp["status"], exp["duration_s"], exp["validation_count"]])

        return output.getvalue()