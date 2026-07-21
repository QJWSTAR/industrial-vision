"""ui.realtime_stats — 实时统计信息面板

显示 MATLAB 计算过程中的实时统计：
- 耗时（秒）
- Layer 数（当前/总）
- Point 数（航点数）
- Mesh 数（三角网格数）
- 进度百分比

由 ProgressSubscriber 的 stats_updated 信号驱动。
纯展示组件，弹性布局，支持 DPI 缩放。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QProgressBar,
    QSizePolicy,
)


class _StatCard(QFrame):
    """单个统计指标卡片。"""

    def __init__(self, title: str, unit: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(
            "QFrame#StatCard{"
            "  background:#0F172A;"
            "  border:1px solid #1E293B;"
            "  border-radius:8px;"
            "  padding:4px 8px;"
            "}"
        )
        self._unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("color:#64748B; font-size:10px;")
        self._title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title_label)

        self._value_label = QLabel("—")
        self._value_label.setStyleSheet(
            "color:#E2E8F0; font-size:16px; font-weight:bold;"
        )
        self._value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value_label)

    def set_value(self, value: str) -> None:
        """设置显示值。"""
        self._value_label.setText(value)


class RealtimeStatsPanel(QWidget):
    """实时统计信息面板。

    用法：
        panel = RealtimeStatsPanel()
        panel.update_stats({"elapsed_s": 12.5, "layer_index": 3,
                            "total_layers": 10, "waypoint_count": 150,
                            "mesh_triangle_count": 1200, "progress": 0.35})
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("RealtimeStatsPanel")
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建统计面板布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 标题
        title = QLabel("📊 实时统计")
        title.setStyleSheet("color:#93C5FD; font-size:12px; font-weight:bold;")
        layout.addWidget(title)

        # 4 个指标卡片（水平排列）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(6)

        self._card_time = _StatCard("耗时", "s")
        self._card_layers = _StatCard("Layer", "")
        self._card_points = _StatCard("Point", "")
        self._card_mesh = _StatCard("Mesh", "")

        for card in (self._card_time, self._card_layers,
                     self._card_points, self._card_mesh):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            cards_row.addWidget(card, 1)

        layout.addLayout(cards_row)

        # 进度条
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setTextVisible(True)
        self._prog.setFormat("%p%")
        self._prog.setStyleSheet(
            "QProgressBar{"
            "  background:#1E293B;"
            "  border:1px solid #334155;"
            "  border-radius:4px;"
            "  text-align:center;"
            "  color:#E2E8F0;"
            "  font-size:11px;"
            "}"
            "QProgressBar::chunk{"
            "  background:#3B82F6;"
            "  border-radius:3px;"
            "}"
        )
        layout.addWidget(self._prog)

        # 状态消息
        self._lb_message = QLabel("等待计算...")
        self._lb_message.setStyleSheet("color:#64748B; font-size:11px;")
        self._lb_message.setWordWrap(True)
        layout.addWidget(self._lb_message)

    def update_stats(self, stats: dict) -> None:
        """更新统计信息。

        Args:
            stats: 包含以下键的字典：
                - elapsed_s: 已耗时（秒）
                - layer_index: 当前层号
                - total_layers: 总层数
                - waypoint_count: 航点数
                - mesh_triangle_count: 三角网格数
                - progress: 进度 0.0-1.0
                - stage_name: 阶段名称
                - message: 状态消息
        """
        elapsed = stats.get("elapsed_s", 0.0)
        self._card_time.set_value(f"{elapsed:.1f}s")

        layer_idx = stats.get("layer_index", 0)
        total_layers = stats.get("total_layers", 0)
        self._card_layers.set_value(f"{layer_idx + 1}/{total_layers}")

        wp_count = stats.get("waypoint_count", 0)
        self._card_points.set_value(f"{wp_count}")

        mesh_count = stats.get("mesh_triangle_count", 0)
        self._card_mesh.set_value(f"{mesh_count}")

        progress = stats.get("progress", 0.0)
        self._prog.setValue(int(progress * 100))

        message = stats.get("message", "")
        stage = stats.get("stage_name", "")
        if message:
            self._lb_message.setText(f"[{stage}] {message}")
        elif stage:
            self._lb_message.setText(f"[{stage}]")

    def reset(self) -> None:
        """重置统计。"""
        self._card_time.set_value("—")
        self._card_layers.set_value("—")
        self._card_points.set_value("—")
        self._card_mesh.set_value("—")
        self._prog.setValue(0)
        self._lb_message.setText("等待计算...")
