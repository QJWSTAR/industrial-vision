"""
defect_selector.py — 缺陷区域交互选取组件
使用 Qt 事件过滤器拦截鼠标，彻底解决与 matplotlib 旋转冲突
"""

from __future__ import annotations
import numpy as np
from typing import Optional
from repair_app.utils.logger_config import error as log_error

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QToolBar, QSizePolicy, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QEvent
from PySide6.QtGui import QPainterPath, QPolygonF, QMouseEvent

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from repair_app.platform.fonts import get_matplotlib_fonts
plt.rcParams["font.sans-serif"] = get_matplotlib_fonts()
plt.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class DefectSelector(QWidget):

    selection_changed = Signal(object)

    MODES = {
        "rect":  "矩形框选",
        "lasso": "自由选区",
        "brush": "区域选择",
        "erase": "取消选择",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._points: Optional[np.ndarray] = None
        self._mask: np.ndarray = np.array([], dtype=bool)
        self._mask_history: list[np.ndarray] = []
        self._mode: str = "rect"

        self._rubber_rect: Optional[tuple[float, float, float, float]] = None
        self._lasso_verts: list[tuple[float, float]] = []
        self._brush_radius: float = 2.0
        self._is_dragging: bool = False
        self._drag_start: Optional[tuple[float, float]] = None
        self._selecting: bool = False

        self._init_ui()
        self._canvas.installEventFilter(self)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()

        self._btn_undo = QPushButton("↩ 撤销")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip("撤销上一次选区操作")
        self._btn_undo.clicked.connect(self._undo)
        toolbar.addWidget(self._btn_undo)

        self._btn_clear = QPushButton("✕ 清除选区")
        self._btn_clear.setToolTip("清除所有已选区域")
        self._btn_clear.clicked.connect(self._clear_selection)
        toolbar.addWidget(self._btn_clear)

        self._btn_invert = QPushButton("⇄ 反选")
        self._btn_invert.setToolTip("将未选中区域与已选中区域互换")
        self._btn_invert.clicked.connect(self._invert_selection)
        toolbar.addWidget(self._btn_invert)

        toolbar.addStretch()

        self._btn_nav = QPushButton("🧭 导航模式")
        self._btn_nav.setCheckable(True)
        self._btn_nav.setChecked(True)
        self._btn_nav.setToolTip("切换导航/选区模式：导航模式可旋转缩放3D视图；选区模式可框选缺陷")
        self._btn_nav.toggled.connect(self._on_nav_toggled)
        toolbar.addWidget(self._btn_nav)

        toolbar.addStretch()

        toolbar.addWidget(QLabel("模式:"))
        self._cb_mode = QComboBox()
        self._cb_mode.setToolTip("选择缺陷区域选取方式")
        for key, label in self.MODES.items():
            self._cb_mode.addItem(label, key)
        self._cb_mode.setEnabled(False)
        toolbar.addWidget(self._cb_mode)

        toolbar.addWidget(QLabel("笔刷:"))
        self._sp_brush = QDoubleSpinBox()
        self._sp_brush.setRange(0.5, 20.0)
        self._sp_brush.setValue(2.0)
        self._sp_brush.setSingleStep(0.5)
        self._sp_brush.setSuffix(" mm")
        self._sp_brush.setFixedWidth(80)
        self._sp_brush.setToolTip("笔刷半径（仅在区域选择/取消选择模式下生效）")
        self._sp_brush.valueChanged.connect(self._on_brush_radius_changed)
        toolbar.addWidget(self._sp_brush)

        self._lb_info = QLabel("未加载点云")
        toolbar.addWidget(self._lb_info)

        layout.addLayout(toolbar)

        self._fig = Figure(figsize=(6, 5), dpi=100)
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._canvas)

        self._ax = self._fig.add_subplot(111, projection="3d")

    # ========== Qt 事件过滤器 ==========
    def eventFilter(self, obj, event) -> bool:
        if obj is not self._canvas:
            return super().eventFilter(obj, event)

        if not self._selecting or self._points is None:
            return super().eventFilter(obj, event)

        t = event.type()
        if t == QEvent.MouseButtonPress:
            return self._qt_mouse_press(event)
        elif t == QEvent.MouseMove:
            return self._qt_mouse_move(event)
        elif t == QEvent.MouseButtonRelease:
            return self._qt_mouse_release(event)

        return super().eventFilter(obj, event)

    def _qt_mouse_press(self, event: QMouseEvent) -> bool:
        pos = event.pos()
        sx, sy = pos.x(), pos.y()

        # 将屏幕坐标转为数据坐标
        xd, yd = self._screen_to_data(sx, sy)
        if xd is None:
            return False

        self._is_dragging = True
        self._drag_start = (float(xd), float(yd))

        if self._mode == "lasso":
            self._lasso_verts = [(float(xd), float(yd))]
        elif self._mode in ("brush", "erase"):
            self._push_history()
            self._apply_brush(float(xd), float(yd))

        return True  # 吃掉事件，阻止 matplotlib 处理

    def _qt_mouse_move(self, event: QMouseEvent) -> bool:
        if not self._is_dragging:
            return False

        pos = event.pos()
        xd, yd = self._screen_to_data(pos.x(), pos.y())
        if xd is None:
            return False
        x, y = float(xd), float(yd)

        if self._mode == "rect" and self._drag_start:
            x0, y0 = self._drag_start
            self._rubber_rect = (x0, y0, x, y)
            self._redraw()

        elif self._mode == "lasso":
            self._lasso_verts.append((x, y))
            self._redraw()

        elif self._mode in ("brush", "erase"):
            self._apply_brush(x, y)
            self._redraw()

        return True

    def _qt_mouse_release(self, event: QMouseEvent) -> bool:
        if not self._is_dragging:
            return False
        self._is_dragging = False

        if self._mode == "rect" and self._drag_start and self._rubber_rect:
            self._push_history()
            self._apply_rect_select()
            self._rubber_rect = None

        elif self._mode == "lasso" and len(self._lasso_verts) >= 3:
            self._push_history()
            self._apply_lasso_select()
            self._lasso_verts = []

        self._drag_start = None
        self._redraw()
        return True

    # ========== 坐标转换 ==========
    def _screen_to_data(self, sx: int, sy: int):
        """屏幕像素坐标 → 数据坐标（使用 matplotlib transData 变换）。"""
        try:
            fig_w, fig_h = self._fig.get_size_inches() * self._fig.dpi

            if fig_w < 1 or fig_h < 1:
                return None, None

            display_coords = self._fig.transFigure.inverted().transform((sx / fig_w, sy / fig_h))
            data_coords = self._ax.transData.inverted().transform(display_coords)

            return data_coords[0], data_coords[1]
        except Exception as e:
            from repair_app.utils.logger_config import warning as _log_warning
            _log_warning(f"坐标转换失败: {e}")
            return None, None

    # ========== 导航/选取切换 ==========
    def _on_nav_toggled(self, checked: bool) -> None:
        if checked:
            self._btn_nav.setText("🧭 导航模式（旋转/缩放）")
            self._selecting = False
            self._cb_mode.setEnabled(False)
            self._sp_brush.setEnabled(False)
        else:
            self._btn_nav.setText("✂️ 选取模式（框选缺陷）")
            self._selecting = True
            self._cb_mode.setEnabled(True)
            self._sp_brush.setEnabled(self._mode in ("brush", "erase"))

    def _on_brush_radius_changed(self, value: float) -> None:
        self._brush_radius = value

    # ========== 选取逻辑 ==========
    def _apply_rect_select(self) -> None:
        if self._points is None or self._rubber_rect is None:
            return
        x0, y0, x1, y1 = self._rubber_rect
        xmin, xmax = sorted([x0, x1])
        ymin, ymax = sorted([y0, y1])

        xy = self._points[:, :2]
        inside = (xy[:, 0] >= xmin) & (xy[:, 0] <= xmax) & \
                 (xy[:, 1] >= ymin) & (xy[:, 1] <= ymax)
        self._mask = inside
        self._update_info()
        self.selection_changed.emit(self._mask.copy())

    def _apply_lasso_select(self) -> None:
        if self._points is None:
            return
        path = QPainterPath()
        poly = QPolygonF([QPointF(v[0], v[1]) for v in self._lasso_verts])
        path.addPolygon(poly)

        xy = self._points[:, :2]
        inside = np.array([
            path.contains(QPointF(float(x), float(y)))
            for x, y in xy
        ], dtype=bool)
        self._mask = inside
        self._update_info()
        self.selection_changed.emit(self._mask.copy())

    def _apply_brush(self, cx: float, cy: float) -> None:
        if self._points is None:
            return
        xy = self._points[:, :2]
        dists = np.sqrt((xy[:, 0] - cx) ** 2 + (xy[:, 1] - cy) ** 2)
        in_brush = dists <= self._brush_radius

        if self._mode == "brush":
            if np.any(in_brush) and not np.array_equal(self._mask | in_brush, self._mask):
                self._mask = self._mask | in_brush
                self._update_info()
                self.selection_changed.emit(self._mask.copy())
        elif self._mode == "erase":
            if np.any(in_brush & self._mask):
                self._mask = self._mask & ~in_brush
                self._update_info()
                self.selection_changed.emit(self._mask.copy())

    def _push_history(self) -> None:
        self._mask_history.append(self._mask.copy())
        self._btn_undo.setEnabled(True)

    def _undo(self) -> None:
        if not self._mask_history:
            return
        self._mask = self._mask_history.pop()
        self._btn_undo.setEnabled(len(self._mask_history) > 0)
        self._update_info()
        self._redraw()
        self.selection_changed.emit(self._mask.copy())

    def _clear_selection(self) -> None:
        if self._points is None or not np.any(self._mask):
            return
        self._push_history()
        self._mask[:] = False
        self._update_info()
        self._redraw()
        self.selection_changed.emit(self._mask.copy())

    def _invert_selection(self) -> None:
        if self._points is None:
            return
        self._push_history()
        self._mask = ~self._mask
        self._update_info()
        self._redraw()
        self.selection_changed.emit(self._mask.copy())

    # ========== 公开接口 ==========
    def set_points(self, points: np.ndarray) -> None:
        self._points = points
        self._mask = np.zeros(len(points), dtype=bool)
        self._mask_history.clear()
        self._update_info()
        self._redraw()
        # 自动切换到选区模式，方便用户开始选择
        if self._btn_nav.isChecked():
            self._btn_nav.setChecked(False)

    def get_selected_points(self) -> np.ndarray:
        if self._points is None or not np.any(self._mask):
            return np.array([])
        return self._points[self._mask]

    def get_selection_mask(self) -> np.ndarray:
        return self._mask.copy()

    def set_mode(self, mode: str) -> None:
        idx = self._cb_mode.findData(mode)
        if idx >= 0:
            self._cb_mode.setCurrentIndex(idx)

    def _update_info(self) -> None:
        if self._points is None:
            self._lb_info.setText("未加载点云")
            return
        total = len(self._points)
        sel = int(np.sum(self._mask))
        self._lb_info.setText(f"选中: {sel} / {total} 点")

    # ========== 渲染 ==========
    def _redraw(self) -> None:
        self._ax.clear()

        if self._points is None:
            self._canvas.draw_idle()
            return

        unsel = self._points[~self._mask]
        sel = self._points[self._mask]

        if len(unsel) > 0:
            self._ax.scatter(
                unsel[:, 0], unsel[:, 1], unsel[:, 2],
                s=2, c="steelblue", alpha=0.5, label="基体/未选中"
            )

        if len(sel) > 0:
            self._ax.scatter(
                sel[:, 0], sel[:, 1], sel[:, 2],
                s=8, c="red", alpha=0.8, label="缺陷区域（已选）"
            )
            # 绘制选中区域边界
            if len(sel) >= 3:
                try:
                    from scipy.spatial import ConvexHull
                    xy_sel = sel[:, :2]
                    hull = ConvexHull(xy_sel)
                    hull_xy = xy_sel[hull.vertices]
                    hx = list(hull_xy[:, 0]) + [hull_xy[0, 0]]
                    hy = list(hull_xy[:, 1]) + [hull_xy[0, 1]]
                    z_mid = float(np.mean(sel[:, 2]))
                    self._ax.plot(hx, hy, [z_mid]*len(hx),
                                  "r-", linewidth=2.0, alpha=0.7, label="缺陷边界")
                except Exception as e:
                    log_error(f"绘制缺陷边界失败: {e}")

        # 绘制橡胶框
        if self._rubber_rect:
            x0, y0, x1, y1 = self._rubber_rect
            z_mid = float(np.mean(self._points[:, 2]))
            self._ax.plot(
                [x0, x1, x1, x0, x0],
                [y0, y0, y1, y1, y0],
                [z_mid]*5,
                "g--", linewidth=1.5, label="框选范围"
            )

        # 绘制套索路径
        if self._lasso_verts and len(self._lasso_verts) >= 2:
            z_mid = float(np.mean(self._points[:, 2]))
            xs = [v[0] for v in self._lasso_verts] + [self._lasso_verts[0][0]]
            ys = [v[1] for v in self._lasso_verts] + [self._lasso_verts[0][1]]
            self._ax.plot(xs, ys, [z_mid]*len(xs), "g--", linewidth=1.5, label="套索范围")

        self._ax.set_xlabel("X (mm)")
        self._ax.set_ylabel("Y (mm)")
        self._ax.set_zlabel("Z (mm)")
        self._ax.legend(loc="upper right", fontsize=7, markerscale=0.5)
        self._canvas.draw_idle()
