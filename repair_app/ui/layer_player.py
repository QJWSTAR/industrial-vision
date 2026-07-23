"""ui.layer_player — 逐层播放控制组件

功能：
- Layer Slider：拖拽查看任意层
- 播放/暂停：自动逐层播放
- 逐层查看：上一步/下一步按钮
- 速度控制：播放速度调节

纯展示+控制组件，不含业务逻辑。
通过 layer_changed 信号通知外部更新可视化。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSlider, QPushButton,
    QLabel, QSpinBox, QSizePolicy,
)

from repair_app.ui.theme_manager import ThemeManager


class LayerPlayer(QWidget):
    """逐层播放控制器。

    信号：
        layer_changed(int)  : 当前选中的层号（0-based）
        play_state(bool)    : 播放状态变更（True=播放中）
    """

    layer_changed = Signal(int)
    play_state = Signal(bool)

    # 默认播放间隔（毫秒）
    DEFAULT_PLAY_INTERVAL_MS = 500
    MIN_PLAY_INTERVAL_MS = 100
    MAX_PLAY_INTERVAL_MS = 3000

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LayerPlayer")
        self._total_layers = 0
        self._current_layer = 0
        self._is_playing = False
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建播放控制布局。"""
        p = ThemeManager.get_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 标题行
        title = QLabel("🎬 逐层查看")
        title.setStyleSheet(f"color:{p.title_accent}; font-size:12px; font-weight:bold;")
        layout.addWidget(title)

        # 控制按钮行
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        self._btn_prev = QPushButton("◀")
        self._btn_prev.setMinimumWidth(32)
        self._btn_prev.setToolTip("上一层")
        self._btn_prev.clicked.connect(self._on_prev)
        ctrl_row.addWidget(self._btn_prev)

        self._btn_play = QPushButton("▶ 播放")
        self._btn_play.setMinimumWidth(60)
        self._btn_play.setToolTip("自动逐层播放")
        self._btn_play.clicked.connect(self._on_play_pause)
        self._btn_play.setStyleSheet(
            f"QPushButton{{background:{p.accent_hover};color:#FFF;border:none;border-radius:4px;"
            f"font-weight:bold;padding:4px 8px;}}"
            f"QPushButton:hover{{background:{p.accent};}}"
        )
        ctrl_row.addWidget(self._btn_play)

        self._btn_next = QPushButton("▶")
        self._btn_next.setMinimumWidth(32)
        self._btn_next.setToolTip("下一层")
        self._btn_next.clicked.connect(self._on_next)
        ctrl_row.addWidget(self._btn_next)

        # 层号显示
        self._lb_layer = QLabel("Layer: 0 / 0")
        self._lb_layer.setStyleSheet(f"color:{p.text_secondary}; font-size:11px; min-width:90px;")
        self._lb_layer.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self._lb_layer)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # Slider 行
        slider_row = QHBoxLayout()
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.setToolTip("拖拽查看任意层")
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        slider_row.addWidget(self._slider, 1)

        # 速度控制
        speed_label = QLabel("速度:")
        speed_label.setStyleSheet(f"color:{p.text_disabled}; font-size:11px;")
        slider_row.addWidget(speed_label)

        self._sp_speed = QSpinBox()
        self._sp_speed.setRange(self.MIN_PLAY_INTERVAL_MS, self.MAX_PLAY_INTERVAL_MS)
        self._sp_speed.setValue(self.DEFAULT_PLAY_INTERVAL_MS)
        self._sp_speed.setSingleStep(100)
        self._sp_speed.setSuffix(" ms")
        self._sp_speed.setMinimumWidth(80)
        self._sp_speed.setToolTip("播放间隔（毫秒）")
        self._sp_speed.valueChanged.connect(self._on_speed_changed)
        slider_row.addWidget(self._sp_speed)

        layout.addLayout(slider_row)

        self._update_controls()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def set_total_layers(self, total: int) -> None:
        """设置总层数。"""
        self._total_layers = max(0, total)
        self._slider.setMaximum(max(0, self._total_layers - 1))
        if self._current_layer >= self._total_layers:
            self._current_layer = max(0, self._total_layers - 1)
            self._slider.setValue(self._current_layer)
        self._update_controls()

    def set_current_layer(self, layer: int) -> None:
        """设置当前层号（外部进度更新时调用）。"""
        if 0 <= layer < self._total_layers:
            self._current_layer = layer
            self._slider.setValue(layer)
            self._update_controls()

    def reset(self) -> None:
        """重置到第 0 层。"""
        self.stop_play()
        self._current_layer = 0
        self._slider.setValue(0)
        self._update_controls()

    def stop_play(self) -> None:
        """停止播放。"""
        if self._is_playing:
            self._is_playing = False
            self._play_timer.stop()
            self._btn_play.setText("▶ 播放")
            self.play_state.emit(False)

    # ------------------------------------------------------------------
    # 内部槽
    # ------------------------------------------------------------------
    def _on_slider_changed(self, value: int) -> None:
        """Slider 拖拽时触发。"""
        self._current_layer = value
        self._update_controls()
        self.layer_changed.emit(value)

    def _on_prev(self) -> None:
        """上一层。"""
        if self._current_layer > 0:
            self._slider.setValue(self._current_layer - 1)

    def _on_next(self) -> None:
        """下一层。"""
        if self._current_layer < self._total_layers - 1:
            self._slider.setValue(self._current_layer + 1)

    def _on_play_pause(self) -> None:
        """播放/暂停切换。"""
        if self._is_playing:
            self.stop_play()
        else:
            if self._total_layers <= 1:
                return
            self._is_playing = True
            self._play_timer.start(self._sp_speed.value())
            self._btn_play.setText("⏸ 暂停")
            self.play_state.emit(True)

    def _on_play_tick(self) -> None:
        """播放定时器触发：自动前进一层。"""
        if self._current_layer < self._total_layers - 1:
            self._slider.setValue(self._current_layer + 1)
        else:
            # 播放到最后一层，自动停止
            self.stop_play()

    def _on_speed_changed(self, value: int) -> None:
        """播放速度变更。"""
        if self._is_playing:
            self._play_timer.setInterval(value)

    # ------------------------------------------------------------------
    # UI 更新
    # ------------------------------------------------------------------
    def _update_controls(self) -> None:
        """更新控件状态。"""
        self._lb_layer.setText(
            f"Layer: {self._current_layer + 1} / {max(1, self._total_layers)}"
        )
        self._btn_prev.setEnabled(self._current_layer > 0)
        self._btn_next.setEnabled(self._current_layer < self._total_layers - 1)
        self._btn_play.setEnabled(self._total_layers > 1)
