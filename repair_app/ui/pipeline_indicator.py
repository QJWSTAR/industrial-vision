"""ui.pipeline_indicator — 计算管线可视化指示器

显示 5 个阶段的流水线状态：
  导入点云 → 路径规划 → 形貌预测 → 结果生成 → 导出

每个阶段 4 种状态：等待 / 执行中 / 完成 / 失败

纯展示组件，不包含业务逻辑。状态由外部 set_stage_status() 驱动。
采用 Layout + Stretch，无固定尺寸，支持 DPI 缩放。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame, QSizePolicy,
)


class PipelineStage:
    """单个管线阶段的状态常量。"""
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# 阶段状态 → (背景色, 文字色, 图标)
_STAGE_STYLE = {
    PipelineStage.WAITING: ("#1E293B", "#64748B", "○"),
    PipelineStage.RUNNING: ("#1D4ED8", "#BFDBFE", "◐"),
    PipelineStage.DONE:    ("#15803D", "#BBF7D0", "✓"),
    PipelineStage.FAILED:  ("#B91C1C", "#FECACA", "✗"),
}


class PipelineIndicator(QWidget):
    """计算管线可视化指示器。

    用法：
        pipe = PipelineIndicator()
        pipe.set_stage_status(0, PipelineStage.DONE)      # 导入点云完成
        pipe.set_stage_status(1, PipelineStage.RUNNING)    # 路径规划执行中
        pipe.reset()                                        # 全部重置为等待
    """

    # 5 个阶段的名称
    STAGE_NAMES = ["导入点云", "路径规划", "形貌预测", "结果生成", "导出"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PipelineIndicator")
        self._stage_labels: list[QLabel] = []
        self._arrow_labels: list[QLabel] = []
        self._stage_statuses: list[str] = [
            PipelineStage.WAITING for _ in self.STAGE_NAMES
        ]
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建水平管线布局：阶段 → 箭头 → 阶段 → ..."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        for i, name in enumerate(self.STAGE_NAMES):
            if i > 0:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet("color:#475569; font-size:16px; font-weight:bold;")
                arrow.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                layout.addWidget(arrow)
                self._arrow_labels.append(arrow)

            stage_label = QLabel(f"  {name}")
            stage_label.setAlignment(Qt.AlignCenter)
            stage_label.setMinimumWidth(80)
            stage_label.setMinimumHeight(32)
            stage_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout.addWidget(stage_label, 1)
            self._stage_labels.append(stage_label)

        self._refresh_styles()

    def set_stage_status(self, index: int, status: str) -> None:
        """设置指定阶段的状态。

        Args:
            index: 阶段索引 (0-4)
            status: PipelineStage.WAITING / RUNNING / DONE / FAILED
        """
        if not (0 <= index < len(self.STAGE_NAMES)):
            return
        self._stage_statuses[index] = status
        self._refresh_styles()

    def set_running(self, index: int) -> None:
        """便捷方法：标记某阶段为执行中。"""
        self.set_stage_status(index, PipelineStage.RUNNING)

    def set_done(self, index: int) -> None:
        """便捷方法：标记某阶段为完成。"""
        self.set_stage_status(index, PipelineStage.DONE)

    def set_failed(self, index: int) -> None:
        """便捷方法：标记某阶段为失败。"""
        self.set_stage_status(index, PipelineStage.FAILED)

    def mark_running_as_failed(self) -> None:
        """将当前执行中的阶段标记为失败（无 RUNNING 则不操作）。"""
        for i, status in enumerate(self._stage_statuses):
            if status == PipelineStage.RUNNING:
                self.set_failed(i)
                return

    def reset(self) -> None:
        """重置所有阶段为等待状态。"""
        self._stage_statuses = [
            PipelineStage.WAITING for _ in self.STAGE_NAMES
        ]
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        """刷新所有阶段的样式。"""
        for i, label in enumerate(self._stage_labels):
            status = self._stage_statuses[i]
            bg, fg, icon = _STAGE_STYLE[status]
            name = self.STAGE_NAMES[i]
            label.setText(f"  {icon}  {name}")
            label.setStyleSheet(
                f"QLabel {{"
                f"  background:{bg};"
                f"  color:{fg};"
                f"  border-radius:8px;"
                f"  font-size:12px;"
                f"  font-weight:600;"
                f"  padding:4px 8px;"
                f"}}"
            )
