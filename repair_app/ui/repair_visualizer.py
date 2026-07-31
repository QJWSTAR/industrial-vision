"""
repair_visualizer.py — 论文级修复结果可视化
v3.0: 增材/修复双模式色系 + 实时同步逐步渲染
"""

from __future__ import annotations
from enum import Enum, auto
from typing import Optional
import numpy as np

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from repair_app.platform.fonts import get_matplotlib_fonts
from repair_app.utils.logger_config import debug as log_debug, warning as log_warning
plt.rcParams["font.sans-serif"] = get_matplotlib_fonts()
plt.rcParams["axes.unicode_minus"] = False

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSlider, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer

# ---- 色温图 ----
# 默认色温图（用于基体）
_COLORMAP = LinearSegmentedColormap.from_list(
    "deposit_height",
    ["#1E40AF", "#3B82F6", "#10B981", "#F59E0B", "#EF4444"],
    N=256,
)
# 修复模式专用色温图（暖色系：橙-红）
_COLORMAP_REPAIR = LinearSegmentedColormap.from_list(
    "repair_height",
    ["#F59E0B", "#F97316", "#EF4444", "#DC2626", "#991B1B"],
    N=256,
)
# 增材模式专用色温图（冷色系：绿-青-蓝）
_COLORMAP_ADDITIVE = LinearSegmentedColormap.from_list(
    "additive_height",
    ["#10B981", "#06B6D4", "#3B82F6", "#6366F1", "#8B5CF6"],
    N=256,
)

# 暗色主题色
_BG = "#0F172A"
_GRID = "#1E293B"
_TEXT = "#94A3B8"


class ViewMode(Enum):
    ISOMETRIC = "isometric"
    TOP = "top"
    SIDE = "side"
    FRONT = "front"


class RepairMode(Enum):
    ADDITIVE = auto()
    REPAIRING = auto()


def _triangulate_xy(pts: np.ndarray, max_pts: int = 3000) -> Optional[tuple]:
    """用 matplotlib.tri 对点云 XY 投影做 Delaunay 三角剖分。"""
    if len(pts) < 3:
        return None
    if len(pts) > max_pts:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(pts), max_pts, replace=False)
        pts = pts[idx]
    try:
        tri = mtri.Triangulation(pts[:, 0], pts[:, 1])
        return tri.triangles, pts
    except Exception as exc:
        log_debug(f"实时 STL 解析失败: {exc}")
        return None


def _parse_binary_stl_to_points(
    stl_bytes: bytes,
    max_triangles: int = 10000,
) -> Optional[np.ndarray]:
    """解析二进制 STL bytes 为 N×3 点云数组（用于实时 mesh 刷新）。

    二进制 STL 结构：
      - 80 字节 header
      - 4 字节 uint32 三角形数量
      - 每个三角形 50 字节：3×float32 法向量 + 3×3×float32 顶点 + 2 字节属性
    """
    import struct
    if len(stl_bytes) < 84:
        return None
    try:
        n_tri = struct.unpack_from("<I", stl_bytes, 80)[0]
        if n_tri <= 0 or len(stl_bytes) < 84 + n_tri * 50:
            return None
        record_dtype = np.dtype([
            ("normal", "<f4", (3,)),
            ("vertices", "<f4", (3, 3)),
            ("attribute", "<u2"),
        ])
        records = np.frombuffer(
            stl_bytes,
            dtype=record_dtype,
            count=n_tri,
            offset=84,
        )
        if n_tri > max_triangles:
            stride = int(np.ceil(n_tri / max_triangles))
            records = records[::stride]
        return np.asarray(records["vertices"], dtype=np.float32).reshape(-1, 3).copy()
    except Exception:
        return None


class RepairVisualizer(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._substrate_pts: Optional[np.ndarray] = None
        self._defect_mask: Optional[np.ndarray] = None
        self._repair_pts: Optional[np.ndarray] = None
        self._waypoints: Optional[np.ndarray] = None
        self._layer_data: Optional[list[np.ndarray]] = None
        self._current_layer: int = 0
        self._view_mode: ViewMode = ViewMode.ISOMETRIC
        self._anim_timer: Optional[QTimer] = None
        self._animating: bool = False
        self._show_before: bool = True
        self._show_mesh: bool = True
        self._show_waypoints: bool = True
        self._show_nozzle: bool = False
        self._show_colormap: bool = True
        self._repair_mode: RepairMode = RepairMode.REPAIRING
        # 实时同步: 部分航点和部分沉积点
        self._partial_waypoints: Optional[np.ndarray] = None
        self._partial_repair: Optional[np.ndarray] = None
        # 喷嘴方向向量（来自航点法向量 nx,ny,nz），用于 quiver3 可视化
        self._nozzle_normals: Optional[np.ndarray] = None
        self._nozzle_positions: Optional[np.ndarray] = None
        self._init_ui()

    def set_mode(self, mode: RepairMode) -> None:
        """设置修复模式（增材/修复），自动切换色系。"""
        self._repair_mode = mode
        self._render()

    @property
    def mode(self) -> RepairMode:
        return self._repair_mode

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self._cb_view = QComboBox()
        self._cb_view.addItems(["等距视图", "俯视图", "侧视图", "正视图"])
        self._cb_view.setToolTip("切换3D视图视角")
        self._cb_view.currentIndexChanged.connect(self._on_view_changed)
        toolbar.addWidget(QLabel("视角:"))
        toolbar.addWidget(self._cb_view)

        self._chk_mesh = QCheckBox("曲面")
        self._chk_mesh.setChecked(True)
        self._chk_mesh.setToolTip("显示/隐藏基体曲面")
        self._chk_mesh.toggled.connect(self._on_toggle_mesh)
        toolbar.addWidget(self._chk_mesh)

        self._chk_before = QCheckBox("缺陷")
        self._chk_before.setChecked(True)
        self._chk_before.setToolTip("高亮显示缺陷区域")
        self._chk_before.toggled.connect(self._on_toggle_before)
        toolbar.addWidget(self._chk_before)

        self._chk_waypoints = QCheckBox("路径")
        self._chk_waypoints.setChecked(True)
        self._chk_waypoints.setToolTip("显示/隐藏喷涂路径航点")
        self._chk_waypoints.toggled.connect(self._on_toggle_waypoints)
        toolbar.addWidget(self._chk_waypoints)

        self._chk_nozzle = QCheckBox("喷嘴")
        self._chk_nozzle.setChecked(False)
        self._chk_nozzle.setToolTip("在路径中点显示喷嘴锥体示意")
        self._chk_nozzle.toggled.connect(self._on_toggle_nozzle)
        toolbar.addWidget(self._chk_nozzle)

        self._chk_colormap = QCheckBox("色温")
        self._chk_colormap.setChecked(True)
        self._chk_colormap.setToolTip("按高度着色显示沉积层")
        self._chk_colormap.toggled.connect(self._on_toggle_colormap)
        toolbar.addWidget(self._chk_colormap)

        toolbar.addStretch()

        self._btn_anim = QPushButton("▶ 逐层动画")
        self._btn_anim.setToolTip("逐层播放沉积动画，查看每层修复效果")
        self._btn_anim.clicked.connect(self._toggle_animation)
        toolbar.addWidget(self._btn_anim)

        self._slider_layer = QSlider(Qt.Horizontal)
        self._slider_layer.setRange(0, 100)
        self._slider_layer.setValue(100)
        self._slider_layer.valueChanged.connect(self._on_layer_slider)
        self._slider_layer.setFixedWidth(120)
        toolbar.addWidget(QLabel("层:"))
        toolbar.addWidget(self._slider_layer)
        self._lb_layer = QLabel("全部")
        self._lb_layer.setFixedWidth(40)
        toolbar.addWidget(self._lb_layer)

        # 模式标签
        self._lb_mode = QLabel("🔧 修复模式")
        self._lb_mode.setStyleSheet(
            "color:#F59E0B; font-size:12px; font-weight:bold; "
            "padding:2px 8px; background:#1E293B; border-radius:4px;"
        )
        toolbar.addWidget(self._lb_mode)

        layout.addLayout(toolbar)

        self._fig = Figure(figsize=(7, 5), dpi=100)
        self._fig.set_facecolor(_BG)
        self._canvas = FigureCanvas(self._fig)
        # matplotlib 原生工具栏：缩放、平移、旋转、刷新、导出 PNG
        self._toolbar = NavigationToolbar(self._canvas, self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas)
        self._ax = self._fig.add_subplot(111, projection="3d")
        self._ax.set_facecolor(_BG)
        for pane in [self._ax.xaxis, self._ax.yaxis, self._ax.zaxis]:
            pane.set_pane_color(_BG)
        self._ax.grid(color=_GRID, alpha=0.3)

    # ========== 槽 ==========
    def _on_view_changed(self, idx: int) -> None:
        views = [ViewMode.ISOMETRIC, ViewMode.TOP, ViewMode.SIDE, ViewMode.FRONT]
        if idx < len(views):
            self._view_mode = views[idx]
            self._render()

    def _on_toggle_mesh(self, checked: bool) -> None:
        self._show_mesh = checked
        self._render()

    def _on_toggle_before(self, checked: bool) -> None:
        self._show_before = checked
        self._render()

    def _on_toggle_waypoints(self, checked: bool) -> None:
        self._show_waypoints = checked
        self._render()

    def _on_toggle_nozzle(self, checked: bool) -> None:
        self._show_nozzle = checked
        self._render()

    def _on_toggle_colormap(self, checked: bool) -> None:
        self._show_colormap = checked
        self._render()

    def _on_layer_slider(self, val: int) -> None:
        if self._layer_data:
            n = len(self._layer_data) - 1
            if n > 0:
                self._current_layer = int(val / 100 * n)
                self._lb_layer.setText(str(self._current_layer + 1))
            else:
                self._current_layer = 0
                self._lb_layer.setText("全部")
            self._render()

    def _toggle_animation(self) -> None:
        if self._animating:
            self._destroy_anim_timer()
            self._animating = False
            self._btn_anim.setText("▶ 逐层动画")
            return
        if not self._layer_data or len(self._layer_data) < 2:
            return
        self._animating = True
        self._btn_anim.setText("⏸ 停止")
        self._current_layer = 0
        self._render()
        self._anim_timer = QTimer(self)
        def _step():
            if self._current_layer < len(self._layer_data) - 1:
                self._current_layer += 1
                self._lb_layer.setText(str(self._current_layer + 1))
                self._render()
            else:
                self._destroy_anim_timer()
                self._animating = False
                self._btn_anim.setText("▶ 逐层动画")
        self._anim_timer.timeout.connect(_step)
        self._anim_timer.start(400)

    # ========== 数据设置 ==========
    def set_data(
        self,
        substrate: np.ndarray,
        defect_mask: Optional[np.ndarray] = None,
        repair: Optional[np.ndarray] = None,
        waypoints: Optional[np.ndarray] = None,
        layers: Optional[list[np.ndarray]] = None,
    ) -> None:
        self._substrate_pts = substrate
        self._defect_mask = defect_mask
        self._repair_pts = repair
        self._waypoints = waypoints
        self._layer_data = layers
        self._current_layer = len(layers) - 1 if layers else 0
        self._partial_waypoints = None
        self._partial_repair = None
        self._render()

    def set_partial_waypoints(self, waypoints: np.ndarray) -> None:
        """设置部分航点（用于实时同步显示）。"""
        self._partial_waypoints = waypoints
        self._render()

    def set_partial_repair(self, repair_pts: np.ndarray) -> None:
        """设置部分沉积点（用于实时同步显示）。"""
        self._partial_repair = repair_pts
        self._render()

    def set_partial_mesh(self, mesh_bytes: bytes) -> None:
        """设置实时 mesh（二进制 STL），用于逐层沉积表面刷新。

        将二进制 STL 解析为点云后赋值到 _partial_repair，
        复用现有的 _render_repair_result 渲染逻辑。
        """
        if not mesh_bytes:
            return
        try:
            # The full-resolution keyframe remains cached by MainWindow, while
            # realtime rendering uses a bounded LOD to keep matplotlib smooth.
            pts = _parse_binary_stl_to_points(mesh_bytes, max_triangles=3000)
            if pts is not None and len(pts) > 0:
                self._partial_repair = pts
                self._render()
        except Exception as exc:
            log_warning(f"实时 mesh 刷新失败: {exc}")

    def set_nozzle_orientations(
        self,
        positions: Optional[np.ndarray],
        normals: Optional[np.ndarray],
    ) -> None:
        """设置喷嘴位置与方向向量（来自航点 XYZ + 法向量 nx,ny,nz）。

        供 quiver3 等价可视化：在 GUI 内原生绘制喷嘴行进方向箭头，
        替代 MATLAB createfigures.m 中的 quiver3。
        """
        self._nozzle_positions = positions
        self._nozzle_normals = normals
        self._render()

    # ========== 内部渲染 ==========
    def _render(self) -> None:
        self._ax.clear()
        self._ax.set_title(
            "增材制造 3D 预览" if self._repair_mode == RepairMode.ADDITIVE else "缺陷修复 3D 预览",
            color=_TEXT, fontsize=11
        )
        legend_items: list = []

        self._render_substrate_and_defect(legend_items)
        self._render_repair_result(legend_items)
        self._render_path_and_waypoints(legend_items)
        self._render_nozzle_if_needed()
        self._update_mode_label()
        self._render_axes_and_legend(legend_items)

        self._canvas.draw_idle()

    def _render_substrate_and_defect(self, legend_items: list) -> None:
        """渲染基体曲面和缺陷区域高亮。"""
        if self._substrate_pts is None or not self._show_before:
            return
        if self._defect_mask is not None and np.any(self._defect_mask):
            base = self._substrate_pts[~self._defect_mask]
        else:
            base = self._substrate_pts
        if len(base) >= 3:
            if self._show_colormap:
                legend_items.append(self._render_surface(base, "基体", None, 0.55, colormap=True))
            else:
                legend_items.append(self._render_surface(base, "基体", "#64748B", 0.55))

        if self._defect_mask is not None and np.any(self._defect_mask):
            dp = self._substrate_pts[self._defect_mask]
            if len(dp) > 3:
                if self._repair_mode == RepairMode.REPAIRING:
                    color, label = "#EF4444", "缺陷区域"
                else:
                    color, label = "#10B981", "增材目标区"
                l2, = self._ax.plot(dp[:, 0], dp[:, 1], dp[:, 2],
                                    'o', color=color, markersize=2.0, alpha=0.6)
                legend_items.append((l2, label))

    def _render_repair_result(self, legend_items: list) -> None:
        """渲染修复/增材结果。"""
        display_repair = (
            self._partial_repair
            if self._partial_repair is not None and len(self._partial_repair) > 0
            else self._repair_pts
        )
        if display_repair is None or len(display_repair) == 0:
            return
        if self._repair_mode == RepairMode.ADDITIVE:
            cmap, label, plain_color = _COLORMAP_ADDITIVE, "增材层", "#10B981"
        else:
            cmap, label, plain_color = _COLORMAP_REPAIR, "修复填充", "#F59E0B"
        if self._show_colormap:
            legend_items.append(
                self._render_surface(display_repair, label, None, 0.85, colormap=True, custom_cmap=cmap))
        else:
            legend_items.append(
                self._render_surface(display_repair, label, plain_color, 0.85))

    def _render_path_and_waypoints(self, legend_items: list) -> None:
        """渲染路径线和航点标记。"""
        display_wp = (
            self._partial_waypoints
            if self._partial_waypoints is not None and len(self._partial_waypoints) > 1
            else self._waypoints
        )
        if not self._show_waypoints or display_wp is None or len(display_wp) <= 1:
            return
        wp = display_wp
        path_color = "#10B981" if self._repair_mode == RepairMode.ADDITIVE else "#F59E0B"
        path_label = "增材路径" if self._repair_mode == RepairMode.ADDITIVE else "修复路径"
        l1, = self._ax.plot(wp[:, 0], wp[:, 1], wp[:, 2],
                            path_color, linewidth=2.0, alpha=0.9)
        legend_items.append((l1, path_label))
        step = max(1, len(wp) // 30)
        self._ax.scatter(wp[::step, 0], wp[::step, 1], wp[::step, 2],
                         s=20, c="#EF4444", marker="o", alpha=0.9, zorder=5)
        self._ax.scatter(wp[0, 0], wp[0, 1], wp[0, 2], s=60, c="#10B981", marker="s",
                         edgecolors="white", linewidth=0.8, zorder=6)
        self._ax.scatter(wp[-1, 0], wp[-1, 1], wp[-1, 2], s=60, c="#8B5CF6", marker="s",
                         edgecolors="white", linewidth=0.8, zorder=6)

    def _render_nozzle_if_needed(self) -> None:
        """需要时渲染喷嘴位置指示 + 方向箭头（quiver3 等价）。"""
        if not self._show_nozzle:
            return
        # 1) 喷嘴锥体示意（中点）
        if self._waypoints is not None and len(self._waypoints) > 1:
            self._render_nozzle(self._waypoints[len(self._waypoints) // 2])
        # 2) quiver3：来自航点法向量的喷嘴方向箭头
        if (self._nozzle_positions is not None
                and self._nozzle_normals is not None
                and len(self._nozzle_positions) > 0
                and len(self._nozzle_normals) == len(self._nozzle_positions)):
            pos = self._nozzle_positions
            nrm = self._nozzle_normals
            # 下采样：最多 40 个箭头，避免视觉拥挤
            step = max(1, len(pos) // 40)
            self._ax.quiver(
                pos[::step, 0], pos[::step, 1], pos[::step, 2],
                nrm[::step, 0], nrm[::step, 1], nrm[::step, 2],
                length=4.0, normalize=True, color="#38BDF8",
                alpha=0.85, linewidth=1.2, arrow_length_ratio=0.3,
            )

    def _update_mode_label(self) -> None:
        """更新模式标签文本和样式。"""
        if self._repair_mode == RepairMode.ADDITIVE:
            self._lb_mode.setText("🏗️ 增材模式")
            self._lb_mode.setStyleSheet(
                "color:#10B981; font-size:12px; font-weight:bold; "
                "padding:2px 8px; background:#1E293B; border-radius:4px;"
            )
        else:
            self._lb_mode.setText("🔧 修复模式")
            self._lb_mode.setStyleSheet(
                "color:#F59E0B; font-size:12px; font-weight:bold; "
                "padding:2px 8px; background:#1E293B; border-radius:4px;"
            )

    def _render_axes_and_legend(self, legend_items: list) -> None:
        """设置坐标轴样式和图例。"""
        self._apply_view()
        self._ax.set_xlabel("X (mm)", color=_TEXT)
        self._ax.set_ylabel("Y (mm)", color=_TEXT)
        self._ax.set_zlabel("Z (mm)", color=_TEXT)
        self._ax.tick_params(colors=_TEXT, labelsize=8)

        if legend_items:
            handles = [h for h, _ in legend_items]
            labels = [l for _, l in legend_items]
            self._ax.legend(handles, labels, loc="upper right",
                            fontsize=7, markerscale=0.6, ncol=2,
                            facecolor=_BG, edgecolor="#334155",
                            labelcolor="#E2E8F0")

    def _render_surface(self, pts: np.ndarray, label: str,
                         color: Optional[str],
                         alpha: float,
                         colormap: bool = False,
                         custom_cmap=None):
        """渲染点云：优先三角网格曲面，退化为散点。"""
        if self._show_mesh and len(pts) >= 3:
            result = _triangulate_xy(pts)
            if result is not None:
                tris, verts = result
                if colormap:
                    h = verts[:, 2]
                    norm = plt.Normalize(h.min(), h.max())
                    cm = custom_cmap if custom_cmap is not None else _COLORMAP
                    fc = cm(norm(h))
                    avg = np.mean(fc[tris], axis=1)
                    mesh = Poly3DCollection(verts[tris], alpha=alpha,
                                            edgecolor="none", facecolor=avg)
                else:
                    mesh = Poly3DCollection(verts[tris], alpha=alpha,
                                            edgecolor="none", facecolor=color)
                self._ax.add_collection3d(mesh)
                from matplotlib.lines import Line2D
                if colormap:
                    c = matplotlib.colors.to_hex(cm(0.65))
                else:
                    c = color or "#10B981"
                return Line2D([0], [0], color=c, lw=4, alpha=alpha), label

        # 散点回退
        s = max(0.5, min(3, 2000 / max(len(pts), 1)))
        if colormap:
            h = pts[:, 2]
            cm = custom_cmap if custom_cmap is not None else _COLORMAP
            sc = self._ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2],
                                  s=s, c=h, cmap=cm, alpha=alpha)
        else:
            sc = self._ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2],
                                  s=s, c=color, alpha=alpha)
        return sc, label

    def _render_nozzle(self, center: np.ndarray) -> None:
        """喷嘴锥体示意。"""
        r, h = 3.0, 15.0
        n = np.array([0, 0, 1])
        n_theta = 20
        theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
        v1 = np.array([1, 0, 0]) if abs(n[0]) < 0.8 else np.array([0, 1, 0])
        v1 = v1 - np.dot(v1, n) * n
        v1 = v1 / np.linalg.norm(v1)
        v2 = np.cross(n, v1)
        disk = np.array([center + r * (np.cos(t) * v1 + np.sin(t) * v2) for t in theta])
        tip = center - h * n
        for i in range(n_theta):
            j = (i + 1) % n_theta
            tri = np.array([disk[i], disk[j], tip])
            self._ax.add_collection3d(
                Poly3DCollection([tri], alpha=0.25, facecolor="#3B82F6", edgecolor="none"))
        self._ax.add_collection3d(
            Poly3DCollection([disk], alpha=0.4, facecolor="#EF4444", edgecolor="#FCA5A5"))

    def _apply_view(self) -> None:
        mode = self._view_mode
        if mode == ViewMode.TOP:
            self._ax.view_init(elev=90, azim=-90)
        elif mode == ViewMode.SIDE:
            self._ax.view_init(elev=0, azim=-90)
        elif mode == ViewMode.FRONT:
            self._ax.view_init(elev=0, azim=0)
        else:
            self._ax.view_init(elev=30, azim=-60)

    # ============================================================
    # 便捷方法（供 ContextMenu / 菜单 / 工具栏调用）
    # ============================================================
    def reset_view(self) -> None:
        """重置视角到等距视图。"""
        self._view_mode = ViewMode.ISOMETRIC
        if hasattr(self, "_cb_view"):
            self._cb_view.setCurrentIndex(0)
        if hasattr(self, "_ax") and self._ax is not None:
            self._ax.view_init(elev=30, azim=-60)
            self._canvas.draw_idle()

    def fit_to_view(self) -> None:
        """适应窗口（重新计算数据范围）。"""
        if not hasattr(self, "_ax") or self._ax is None:
            return
        try:
            # 重新计算各轴范围
            all_pts = []
            if self._substrate_pts is not None:
                all_pts.append(self._substrate_pts)
            if self._repair_pts is not None and len(self._repair_pts) > 0:
                all_pts.append(self._repair_pts)
            if self._waypoints is not None and len(self._waypoints) > 0:
                all_pts.append(self._waypoints[:, :3] if self._waypoints.ndim == 2 and self._waypoints.shape[1] >= 3 else self._waypoints)
            if all_pts:
                import numpy as np
                combined = np.vstack(all_pts)
                margin = 0.1
                x_range = combined[:, 0].max() - combined[:, 0].min()
                y_range = combined[:, 1].max() - combined[:, 1].min()
                z_range = combined[:, 2].max() - combined[:, 2].min()
                self._ax.set_xlim(
                    combined[:, 0].min() - x_range * margin,
                    combined[:, 0].max() + x_range * margin,
                )
                self._ax.set_ylim(
                    combined[:, 1].min() - y_range * margin,
                    combined[:, 1].max() + y_range * margin,
                )
                self._ax.set_zlim(
                    combined[:, 2].min() - z_range * margin,
                    combined[:, 2].max() + z_range * margin,
                )
                self._canvas.draw_idle()
        except Exception as exc:
            # P3-7: 绘图异常需记录，避免掩盖真实 bug
            import logging
            logging.getLogger("csam.ui.repair_visualizer").warning(
                "update_view 绘图失败: %s", exc
            )

    def cleanup(self) -> None:
        """清理 matplotlib 资源，防止 Figure 内存泄漏。

        应在 MainWindow closeEvent 中调用。
        """
        # 停止动画定时器
        self._destroy_anim_timer()
        # 清理 matplotlib Figure
        if hasattr(self, "_fig") and self._fig is not None:
            try:
                self._fig.clf()
            except Exception as exc:
                import logging
                logging.getLogger("csam.ui.repair_visualizer").debug(
                    "fig.clf 失败: %s", exc
                )
            self._fig = None
        if hasattr(self, "_ax") and self._ax is not None:
            self._ax = None
        if hasattr(self, "_canvas") and self._canvas is not None:
            try:
                self._canvas.deleteLater()
            except Exception as exc:
                import logging
                logging.getLogger("csam.ui.repair_visualizer").debug(
                    "canvas.deleteLater 失败: %s", exc
                )
            self._canvas = None

    def _destroy_anim_timer(self) -> None:
        timer = getattr(self, "_anim_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
            timer.deleteLater()
        except RuntimeError:
            pass
        self._anim_timer = None

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)

    def toggle_axes(self) -> None:
        """显示/隐藏坐标轴。"""
        if not hasattr(self, "_ax") or self._ax is None:
            return
        try:
            # 切换坐标轴可见性
            visible = self._ax.get_axis_off()
            if visible:
                self._ax.set_axis_on()
            else:
                self._ax.set_axis_off()
            self._canvas.draw_idle()
        except Exception as exc:
            # P3-7: 切换坐标轴异常需记录，避免掩盖真实 bug
            import logging
            logging.getLogger("csam.ui.repair_visualizer").warning(
                "toggle_axes 失败: %s", exc
            )
