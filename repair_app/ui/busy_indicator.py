"""busy_indicator.py — 状态栏忙碌指示器

参考 Siemens NX / ANSYS 的状态栏转圈动画。
显示在状态栏右侧，软件计算时旋转，空闲时隐藏。

用法：
    self._busy = BusyIndicator(self._sb)
    self._sb.addPermanentWidget(self._busy)
    self._busy.start()  # 开始旋转
    self._busy.stop()   # 停止旋转
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QConicalGradient
from PySide6.QtWidgets import QWidget

from repair_app.ui.theme_manager import ThemeManager


class BusyIndicator(QWidget):
    """状态栏忙碌指示器（旋转圆环）。

    特性：
    - 自定义绘制（不依赖外部图标资源）
    - 12 段渐变圆环，旋转动画
    - 紧凑尺寸（16x16，适合状态栏）
    - 可配置颜色和速度
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 16) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._running = False
        self._color = ThemeManager.get_palette().accent_light

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def start(self) -> None:
        """开始旋转。"""
        if not self._running:
            self._running = True
            self.show()
            self._timer.start(50)  # 50ms = 20fps

    def stop(self) -> None:
        """停止旋转。"""
        self._running = False
        self._timer.stop()
        self.hide()

    def set_color(self, color: str) -> None:
        """设置指示器颜色。"""
        self._color = QColor(color)
        self.update()

    def _rotate(self) -> None:
        """旋转一帧。"""
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:
        """绘制旋转圆环。"""
        if not self._running:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        rect = QRectF(2, 2, w - 4, h - 4)

        # 绘制 12 段圆弧，透明度递增
        n_segments = 12
        for i in range(n_segments):
            # 计算每段的起始和结束角度（0.1 度为单位）
            seg_angle = 360.0 / n_segments
            start_angle = (self._angle + i * seg_angle) % 360.0
            # 透明度：从主角度开始最亮，向后递减
            alpha = int(255 * (1.0 - i / n_segments))
            color = QColor(self._color)
            color.setAlpha(alpha)

            painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
            # drawArc 使用 1/16 度为单位
            painter.drawArc(
                rect,
                int(-start_angle * 16),
                int(-seg_angle * 16 + 4),
            )

        painter.end()


class BusyLabel(QWidget):
    """带文字的忙碌指示器（"● 处理中..."）。

    用法：
        self._busy_label = BusyLabel()
        self._sb.addPermanentWidget(self._busy_label)
        self._busy_label.set_busy(True, "正在计算...")
        self._busy_label.set_busy(False)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)

        self._indicator = BusyIndicator(self, 14)
        layout.addWidget(self._indicator)

        self._label = QLabel("就绪")
        self._label.setStyleSheet(f"color:{ThemeManager.get_palette().text_muted};")
        layout.addWidget(self._label)

        self._indicator.stop()
        self._indicator.hide()

    def set_busy(self, busy: bool, text: str = "") -> None:
        """设置忙碌状态。"""
        if busy:
            self._indicator.start()
            self._label.setText(text or "处理中...")
            self._label.setStyleSheet(
                f"color:{ThemeManager.get_palette().accent_pale}; font-weight:600;"
            )
        else:
            self._indicator.stop()
            self._label.setText(text or "就绪")
            self._label.setStyleSheet(
                f"color:{ThemeManager.get_palette().text_muted};"
            )
