"""
profile_result_panel.py — MATLAB 形貌预测结果原生可视化面板

完全基于 matplotlib + PySide6 原生渲染 MATLAB 返回的数值数据：
- mesh (二进制 STL)        → 3D 三角网格曲面（按 Z 着色）
- layer_profiles            → 逐层最大/平均高度 + 沉积效率双轴曲线
- particle_distribution     → XY 散点 + 速度大小热力图
- uniformity                → 半圆仪表盘
- estimated_mass/time       → 顶部指标卡片

不依赖 PyVista / VTK，不读取 PNG / 视频 / MATLAB Figure。
所有图形继承 matplotlib NavigationToolbar2QT：缩放、平移、旋转、刷新、导出 PNG。
"""

from __future__ import annotations
import struct
from typing import Any, Optional

import numpy as np

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Wedge, Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QTabWidget,
    QPushButton, QFrame,
)
from PySide6.QtCore import Qt

from repair_app.platform.fonts import get_matplotlib_fonts
from repair_app.utils.logger_config import debug as log_debug
plt.rcParams["font.sans-serif"] = get_matplotlib_fonts()
plt.rcParams["axes.unicode_minus"] = False

# 工业暗色主题
_BG = "#0F172A"
_PANEL = "#111827"
_GRID = "#1E293B"
_TEXT = "#94A3B8"
_TEXT_HI = "#E2E8F0"
_ACCENT = "#3B82F6"
_OK = "#10B981"
_WARN = "#F59E0B"
_ERR = "#EF4444"

# 沉积高度色温图（蓝 → 绿 → 黄 → 红）
_CMAP_HEIGHT = LinearSegmentedColormap.from_list(
    "deposit_height",
    ["#1E40AF", "#3B82F6", "#10B981", "#F59E0B", "#EF4444"],
    N=256,
)
# 速度热力图（青 → 黄 → 红）
_CMAP_VELOCITY = LinearSegmentedColormap.from_list(
    "particle_velocity",
    ["#06B6D4", "#10B981", "#F59E0B", "#EF4444"],
    N=256,
)


# =====================================================================
# 二进制 STL 解码
# =====================================================================
def decode_binary_stl(data: bytes) -> Optional[np.ndarray]:
    """解析二进制 STL，返回 (N, 9) 三角形顶点矩阵。

    每行 = [x1,y1,z1, x2,y2,z2, x3,y3,z3]。
    格式：80 字节头 + 4 字节面数 + 每面 50 字节（12 法向 + 36 顶点 + 2 属性）。
    """
    if not data or len(data) < 84:
        return None
    try:
        n_faces = struct.unpack("<I", data[80:84])[0]
        expected = 84 + n_faces * 50
        if len(data) < expected:
            return None
        tris = np.empty((n_faces, 9), dtype=np.float32)
        offset = 84
        for i in range(n_faces):
            # 跳过 12 字节法向
            v = struct.unpack_from("<9f", data, offset + 12)
            tris[i] = v
            offset += 50
        return tris
    except (struct.error, ValueError) as exc:
        log_debug(f"二进制 STL 解码失败: {exc}")
        return None


# =====================================================================
# 指标卡片
# =====================================================================
class _MetricCard(QFrame):
    """小型指标卡片（标题 + 数值 + 单位）。"""

    def __init__(self, title: str, value: str = "—", unit: str = "",
                 color: str = _TEXT_HI, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setStyleSheet(f"""
            QFrame#MetricCard {{
                background:{_PANEL};
                border:1px solid {_GRID};
                border-radius:8px;
                padding:6px 10px;
            }}
        """)
        g = QGridLayout(self)
        g.setContentsMargins(10, 6, 10, 6)
        g.setVerticalSpacing(0)

        self._lb_title = QLabel(title)
        self._lb_title.setStyleSheet(f"color:{_TEXT}; font-size:11px;")
        g.addWidget(self._lb_title, 0, 0, 1, 2)

        self._lb_value = QLabel(value)
        self._lb_value.setStyleSheet(
            f"color:{color}; font-size:18px; font-weight:700;"
        )
        g.addWidget(self._lb_value, 1, 0)

        self._lb_unit = QLabel(unit)
        self._lb_unit.setStyleSheet(f"color:{_TEXT}; font-size:11px;")
        g.addWidget(self._lb_unit, 1, 1)
        g.setColumnStretch(0, 1)

    def set_value(self, value: str, unit: str = "", color: str = _TEXT_HI) -> None:
        self._lb_value.setText(value)
        self._lb_value.setStyleSheet(
            f"color:{color}; font-size:18px; font-weight:700;"
        )
        self._lb_unit.setText(unit)


# =====================================================================
# 主面板
# =====================================================================
class ProfileResultPanel(QWidget):
    """MATLAB 形貌预测结果原生可视化面板。

    工业软件风格：顶部指标卡片区 + 下方 Tab 多视图（mesh / 层轮廓 / 粒子分布 / 均匀性）。
    所有 matplotlib 图形自带 NavigationToolbar（缩放、平移、旋转、刷新、导出 PNG）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[dict[str, Any]] = None
        self._cleaned_up = False
        self._init_ui()

    # ---------- UI ----------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ---- 顶部指标卡片行 ----
        cards = QFrame()
        cards.setObjectName("MetricRow")
        cl = QHBoxLayout(cards)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        self._card_mass = _MetricCard("材料用量", "—", "g", _WARN)
        self._card_time = _MetricCard("预计耗时", "—", "s", _ACCENT)
        self._card_vol = _MetricCard("沉积体积", "—", "mm³", _OK)
        self._card_unif = _MetricCard("均匀性", "—", "%", _OK)
        self._card_pd = _MetricCard("粒子总数", "—", "pts", _TEXT_HI)
        self._card_warn = _MetricCard("警告数", "—", "条", _WARN)

        for card in (self._card_mass, self._card_time, self._card_vol,
                     self._card_unif, self._card_pd, self._card_warn):
            cl.addWidget(card, 1)
        layout.addWidget(cards)

        # ---- Tab 多视图区 ----
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(self._tab_qss())

        self._tab_mesh = self._build_mesh_tab()
        self._tab_layers = self._build_layers_tab()
        self._tab_particles = self._build_particles_tab()
        self._tab_uniformity = self._build_uniformity_tab()

        self._tabs.addTab(self._tab_mesh, "沉积网格 (Mesh)")
        self._tabs.addTab(self._tab_layers, "逐层轮廓")
        self._tabs.addTab(self._tab_particles, "粒子分布")
        self._tabs.addTab(self._tab_uniformity, "均匀性仪表")
        layout.addWidget(self._tabs, 1)

        # ---- 底部刷新按钮 ----
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("🔄 刷新所有视图")
        self._btn_refresh.setMinimumHeight(32)
        self._btn_refresh.clicked.connect(self.refresh)
        self._btn_refresh.setStyleSheet(self._btn_qss())
        btn_row.addWidget(self._btn_refresh)
        btn_row.addStretch()

        self._lb_status = QLabel("等待 MATLAB 形貌预测结果...")
        self._lb_status.setStyleSheet(f"color:{_TEXT}; font-size:11px;")
        btn_row.addWidget(self._lb_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def cleanup(self) -> None:
        """Release all matplotlib figures/canvases exactly once."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        for name in ("mesh", "layers", "particles", "unif"):
            fig = getattr(self, f"_fig_{name}", None)
            if fig is not None:
                try:
                    fig.clear()
                    plt.close(fig)
                except Exception:
                    pass
                setattr(self, f"_fig_{name}", None)
            canvas = getattr(self, f"_canvas_{name}", None)
            if canvas is not None:
                try:
                    canvas.close()
                    canvas.deleteLater()
                except RuntimeError:
                    pass
                setattr(self, f"_canvas_{name}", None)

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)

    def _tab_qss(self) -> str:
        return f"""
            QTabWidget::pane {{
                border:1px solid {_GRID};
                border-radius:8px;
                background:{_BG};
                top:-1px;
            }}
            QTabBar::tab {{
                background:{_PANEL};
                color:{_TEXT};
                padding:6px 14px;
                margin-right:2px;
                border:1px solid {_GRID};
                border-bottom:none;
                border-top-left-radius:6px;
                border-top-right-radius:6px;
                font-weight:600;
            }}
            QTabBar::tab:selected {{
                background:{_ACCENT};
                color:#FFFFFF;
            }}
            QTabBar::tab:hover:!selected {{
                background:#1E293B;
                color:{_TEXT_HI};
            }}
        """

    def _btn_qss(self) -> str:
        return f"""
            QPushButton {{
                background:{_PANEL};
                color:{_TEXT_HI};
                border:1px solid {_GRID};
                border-radius:6px;
                padding:6px 14px;
                font-weight:600;
            }}
            QPushButton:hover {{
                background:#1E293B;
                border-color:{_ACCENT};
            }}
        """

    # ---------- 各 Tab 构建 ----------
    def _build_mesh_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(2)

        self._fig_mesh = Figure(figsize=(7, 5), dpi=100)
        self._fig_mesh.set_facecolor(_BG)
        self._canvas_mesh = FigureCanvas(self._fig_mesh)
        self._toolbar_mesh = NavigationToolbar(self._canvas_mesh, w)
        l.addWidget(self._toolbar_mesh)
        l.addWidget(self._canvas_mesh, 1)
        return w

    def _build_layers_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(2)

        self._fig_layers = Figure(figsize=(7, 5), dpi=100)
        self._fig_layers.set_facecolor(_BG)
        self._canvas_layers = FigureCanvas(self._fig_layers)
        self._toolbar_layers = NavigationToolbar(self._canvas_layers, w)
        l.addWidget(self._toolbar_layers)
        l.addWidget(self._canvas_layers, 1)
        return w

    def _build_particles_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(2)

        self._fig_particles = Figure(figsize=(7, 5), dpi=100)
        self._fig_particles.set_facecolor(_BG)
        self._canvas_particles = FigureCanvas(self._fig_particles)
        self._toolbar_particles = NavigationToolbar(self._canvas_particles, w)
        l.addWidget(self._toolbar_particles)
        l.addWidget(self._canvas_particles, 1)
        return w

    def _build_uniformity_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(2)

        self._fig_unif = Figure(figsize=(7, 5), dpi=100)
        self._fig_unif.set_facecolor(_BG)
        self._canvas_unif = FigureCanvas(self._fig_unif)
        self._toolbar_unif = NavigationToolbar(self._canvas_unif, w)
        l.addWidget(self._toolbar_unif)
        l.addWidget(self._canvas_unif, 1)
        return w

    # ---------- 数据接收 ----------
    def set_profile_result(self, result: dict[str, Any]) -> None:
        """接收 MATLAB 形貌预测完整结果 dict。

        预期字段（来自 parse_repair_result）：
        - mesh_bytes (bytes) + mesh_format ("stl_binary")
        - layer_profiles (List[dict])
        - particle_dist (dict | None)
        - uniformity_score (float)
        - estimated_mass_g, estimated_time_s, predicted_volume_mm3
        """
        self._profile = result
        self._update_metric_cards()
        self._render_mesh()
        self._render_layers()
        self._render_particles()
        self._render_uniformity()
        self._lb_status.setText(
            f"已加载 MATLAB 形貌预测结果 · "
            f"{len(result.get('layer_profiles') or [])} 层 · "
            f"uniformity={result.get('uniformity_score', 0):.1%}"
        )
        self._lb_status.setStyleSheet(f"color:{_OK}; font-size:11px;")

    # ---------- 指标卡片 ----------
    def _update_metric_cards(self) -> None:
        if not self._profile:
            return
        p = self._profile
        mass = float(p.get("estimated_mass_g", 0.0) or 0.0)
        time_s = float(p.get("estimated_time_s", 0.0) or 0.0)
        vol = float(p.get("predicted_volume_mm3", 0.0) or 0.0)
        unif = float(p.get("uniformity_score", 0.0) or 0.0)

        self._card_mass.set_value(f"{mass:.3f}", "g", _WARN if mass > 0 else _TEXT)
        self._card_time.set_value(f"{time_s:.2f}", "s", _ACCENT if time_s > 0 else _TEXT)
        self._card_vol.set_value(f"{vol:.2f}", "mm³", _OK if vol > 0 else _TEXT)

        unif_color = _OK if unif >= 0.85 else (_WARN if unif >= 0.7 else _ERR)
        self._card_unif.set_value(f"{unif*100:.1f}", "%", unif_color)

        pd = p.get("particle_dist")
        if pd is not None:
            n = int(pd.get("total_particles", 0) or len(pd.get("px", [])))
            self._card_pd.set_value(f"{n:,}", "pts", _TEXT_HI)
        else:
            self._card_pd.set_value("—", "pts", _TEXT)

        warnings = p.get("warnings") or []
        if isinstance(warnings, (list, tuple)):
            n_warn = len(warnings)
        else:
            n_warn = 0
        wc = _OK if n_warn == 0 else (_WARN if n_warn < 3 else _ERR)
        self._card_warn.set_value(f"{n_warn}", "条", wc)

    # ---------- 渲染：Mesh ----------
    def _render_mesh(self) -> None:
        self._fig_mesh.clear()
        ax = self._fig_mesh.add_subplot(111, projection="3d")
        ax.set_facecolor(_BG)
        for pane in (ax.xaxis, ax.yaxis, ax.zaxis):
            pane.set_pane_color(_BG)
        ax.grid(color=_GRID, alpha=0.3)

        if not self._profile:
            self._render_empty(ax, "等待 MATLAB mesh 数据")
            self._canvas_mesh.draw_idle()
            return

        tris = None
        mesh_bytes = self._profile.get("mesh_bytes") or b""
        if mesh_bytes:
            tris = decode_binary_stl(mesh_bytes)

        if tris is None or len(tris) == 0:
            self._render_empty(ax, "无 mesh 数据（降级模式）")
            self._canvas_mesh.draw_idle()
            return

        # 顶点 = (3N, 3)
        verts = tris.reshape(-1, 3)
        # 按三角形平均 Z 着色
        tri_z = verts.reshape(-1, 3, 3)[:, :, 2].mean(axis=1)
        norm = Normalize(vmin=tri_z.min(), vmax=tri_z.max())
        colors = _CMAP_HEIGHT(norm(tri_z))

        collection = Poly3DCollection(
            verts.reshape(-1, 3, 3),
            facecolors=colors,
            edgecolors="none",
            linewidths=0.2,
            alpha=0.92,
        )
        ax.add_collection3d(collection)

        # 自适应坐标范围
        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        center = (mins + maxs) / 2
        extent = (maxs - mins).max() / 2 * 1.1
        ax.set_xlim(center[0] - extent, center[0] + extent)
        ax.set_ylim(center[1] - extent, center[1] + extent)
        ax.set_zlim(center[2] - extent, center[2] + extent)

        ax.set_xlabel("X (mm)", color=_TEXT, fontsize=9)
        ax.set_ylabel("Y (mm)", color=_TEXT, fontsize=9)
        ax.set_zlabel("Z (mm)", color=_TEXT, fontsize=9)
        ax.tick_params(colors=_TEXT, labelsize=8)
        ax.set_title(
            f"MATLAB 沉积网格 · {len(tris):,} 个三角面",
            color=_TEXT_HI, fontsize=11
        )
        ax.view_init(elev=30, azim=-60)

        # 色条
        mappable = plt.cm.ScalarMappable(norm=norm, cmap=_CMAP_HEIGHT)
        mappable.set_array(tri_z)
        cb = self._fig_mesh.colorbar(mappable, ax=ax, shrink=0.6, pad=0.1)
        cb.set_label("沉积高度 Z (mm)", color=_TEXT, fontsize=9)
        cb.ax.tick_params(colors=_TEXT, labelsize=8)
        cb.outline.set_edgecolor(_GRID)

        self._fig_mesh.tight_layout()
        self._canvas_mesh.draw_idle()

    # ---------- 渲染：逐层轮廓 ----------
    def _render_layers(self) -> None:
        self._fig_layers.clear()
        fig = self._fig_layers
        ax1 = fig.add_subplot(111)
        ax1.set_facecolor(_BG)

        lps = self._profile.get("layer_profiles") if self._profile else None
        if not lps:
            self._render_empty_2d(ax1, "等待 layer_profiles 数据")
            fig.tight_layout()
            self._canvas_layers.draw_idle()
            return

        layers = [int(lp.get("layer_index", i)) for i, lp in enumerate(lps)]
        max_h = [float(lp.get("max_height_mm", 0.0)) for lp in lps]
        avg_h = [float(lp.get("avg_height_mm", 0.0)) for lp in lps]
        dep_eff = [float(lp.get("dep_efficiency", 0.0)) for lp in lps]

        x = np.arange(len(layers))
        # 左轴：高度
        ax1.bar(x - 0.2, max_h, width=0.4, color=_ACCENT, alpha=0.85,
                label="最大高度", edgecolor="none")
        ax1.bar(x + 0.2, avg_h, width=0.4, color=_OK, alpha=0.85,
                label="平均高度", edgecolor="none")
        ax1.set_xlabel("层号", color=_TEXT, fontsize=9)
        ax1.set_ylabel("高度 (mm)", color=_TEXT, fontsize=9)
        ax1.set_xticks(x)
        ax1.set_xticklabels(layers, fontsize=8)
        ax1.tick_params(colors=_TEXT, labelsize=8)
        for spine in ax1.spines.values():
            spine.set_color(_GRID)
        ax1.grid(True, color=_GRID, alpha=0.4, axis="y")
        ax1.set_title(
            f"逐层沉积高度与效率 · 共 {len(layers)} 层",
            color=_TEXT_HI, fontsize=11
        )

        # 右轴：沉积效率
        ax2 = ax1.twinx()
        ax2.plot(x, dep_eff, "o-", color=_WARN, linewidth=2.0,
                 markersize=6, label="沉积效率")
        ax2.set_ylabel("沉积效率", color=_WARN, fontsize=9)
        ax2.set_ylim(0, 1.05)
        ax2.tick_params(colors=_WARN, labelsize=8)
        for spine in ax2.spines.values():
            spine.set_color(_GRID)

        # 合并图例
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8,
                   facecolor=_PANEL, edgecolor=_GRID, labelcolor=_TEXT_HI)

        fig.tight_layout()
        self._canvas_layers.draw_idle()

    # ---------- 渲染：粒子分布 ----------
    def _render_particles(self) -> None:
        self._fig_particles.clear()
        fig = self._fig_particles

        pd = self._profile.get("particle_dist") if self._profile else None
        if not pd or len(pd.get("px", [])) == 0:
            ax = fig.add_subplot(111)
            ax.set_facecolor(_BG)
            self._render_empty_2d(ax, "等待 particle_distribution 数据")
            fig.tight_layout()
            self._canvas_particles.draw_idle()
            return

        px = np.asarray(pd.get("px", []), dtype=np.float32)
        py = np.asarray(pd.get("py", []), dtype=np.float32)
        vx = np.asarray(pd.get("vx", []), dtype=np.float32)
        vy = np.asarray(pd.get("vy", []), dtype=np.float32)
        vz = np.asarray(pd.get("vz", []), dtype=np.float32)

        # 速度大小
        v_mag = np.sqrt(vx**2 + vy**2 + vz**2) if len(vx) > 0 else np.zeros(len(px))

        gs = fig.add_gridspec(1, 2, width_ratios=[2, 1], wspace=0.3)

        # 左：XY 散点 + 速度热力
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor(_BG)
        sc = ax1.scatter(px, py, c=v_mag, cmap=_CMAP_VELOCITY,
                         s=12, alpha=0.75, edgecolors="none")
        ax1.set_xlabel("X (mm)", color=_TEXT, fontsize=9)
        ax1.set_ylabel("Y (mm)", color=_TEXT, fontsize=9)
        ax1.tick_params(colors=_TEXT, labelsize=8)
        for spine in ax1.spines.values():
            spine.set_color(_GRID)
        ax1.grid(True, color=_GRID, alpha=0.4)
        ax1.set_title("粒子 XY 分布（颜色=速度大小）",
                      color=_TEXT_HI, fontsize=10)
        cb1 = fig.colorbar(sc, ax=ax1, shrink=0.85, pad=0.02)
        cb1.set_label("速度 (m/s)", color=_TEXT, fontsize=9)
        cb1.ax.tick_params(colors=_TEXT, labelsize=8)
        cb1.outline.set_edgecolor(_GRID)

        # 右：速度直方图
        ax2 = fig.add_subplot(gs[1])
        ax2.set_facecolor(_BG)
        if len(v_mag) > 0:
            ax2.hist(v_mag, bins=20, color=_ACCENT, alpha=0.85,
                     edgecolor=_PANEL)
        ax2.set_xlabel("速度 (m/s)", color=_TEXT, fontsize=9)
        ax2.set_ylabel("粒子数", color=_TEXT, fontsize=9)
        ax2.tick_params(colors=_TEXT, labelsize=8)
        for spine in ax2.spines.values():
            spine.set_color(_GRID)
        ax2.grid(True, color=_GRID, alpha=0.4, axis="y")
        ax2.set_title("速度分布直方图", color=_TEXT_HI, fontsize=10)

        n = len(px)
        dep_eff = float(pd.get("dep_efficiency", 0.0) or 0.0)
        fig.suptitle(
            f"粒子分布 · 总数 {n:,} · 平均沉积效率 {dep_eff:.1%}",
            color=_TEXT_HI, fontsize=11, y=0.98
        )
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        self._canvas_particles.draw_idle()

    # ---------- 渲染：均匀性仪表盘 ----------
    def _render_uniformity(self) -> None:
        self._fig_unif.clear()
        fig = self._fig_unif
        ax = fig.add_subplot(111)
        ax.set_facecolor(_BG)
        ax.set_aspect("equal")
        ax.axis("off")

        if not self._profile:
            ax.text(0.5, 0.5, "等待 uniformity 数据",
                    ha="center", va="center", color=_TEXT, fontsize=12,
                    transform=ax.transAxes)
            self._canvas_unif.draw_idle()
            return

        unif = float(self._profile.get("uniformity_score", 0.0) or 0.0)
        unif_pct = max(0.0, min(1.0, unif))

        # 半圆仪表盘：180° = 100%
        angle_start = 180
        angle_end = 0
        # 背景弧
        ax.add_patch(Wedge((0.5, 0.3), 0.38, angle_start, angle_end,
                           width=0.06, facecolor=_PANEL,
                           edgecolor=_GRID, linewidth=1.5))
        # 数值弧
        val_angle = angle_start - unif_pct * 180
        # 默认颜色（unif_pct=0 时不绘制数值弧，但仍需颜色用于中心数值）
        val_color = _ERR
        if unif_pct > 0:
            if unif_pct >= 0.85:
                val_color = _OK
            elif unif_pct >= 0.7:
                val_color = _WARN
            else:
                val_color = _ERR
            ax.add_patch(Wedge((0.5, 0.3), 0.38, angle_start, val_angle,
                               width=0.06, facecolor=val_color,
                               edgecolor="none"))

        # 中心数值
        ax.text(0.5, 0.32, f"{unif_pct*100:.1f}%",
                ha="center", va="center", color=val_color,
                fontsize=28, fontweight="bold")
        ax.text(0.5, 0.18, "均匀性评分",
                ha="center", va="center", color=_TEXT, fontsize=11)

        # 刻度标签
        for frac, label in [(0, "0"), (0.5, "50"), (1.0, "100")]:
            theta = np.radians(180 - frac * 180)
            x = 0.5 + 0.44 * np.cos(theta)
            y = 0.3 + 0.44 * np.sin(theta)
            ax.text(x, y, label, ha="center", va="center",
                    color=_TEXT, fontsize=9)

        # 评价文字
        if unif_pct >= 0.9:
            verdict, vcolor = "优秀 · 沉积均匀", _OK
        elif unif_pct >= 0.85:
            verdict, vcolor = "良好 · 可接受", _OK
        elif unif_pct >= 0.7:
            verdict, vcolor = "一般 · 建议优化", _WARN
        else:
            verdict, vcolor = "较差 · 需调整", _ERR
        ax.text(0.5, 0.08, verdict, ha="center", va="center",
                color=vcolor, fontsize=12, fontweight="bold")

        # 警告列表
        warnings = self._profile.get("warnings") or []
        if warnings:
            warn_text = "警告: " + "; ".join(str(w)[:50] for w in warnings[:3])
            if len(warnings) > 3:
                warn_text += f" ... (+{len(warnings)-3})"
            ax.text(0.5, 0.02, warn_text, ha="center", va="center",
                    color=_WARN, fontsize=9, wrap=True,
                    transform=ax.transAxes)

        ax.set_xlim(0, 1)
        ax.set_ylim(0, 0.85)
        fig.tight_layout()
        self._canvas_unif.draw_idle()

    # ---------- 辅助 ----------
    def _render_empty(self, ax, msg: str) -> None:
        ax.set_title(msg, color=_TEXT, fontsize=11)
        ax.text2D(0.5, 0.5, msg, transform=ax.transAxes,
                  ha="center", va="center", color=_TEXT, fontsize=12)

    def _render_empty_2d(self, ax, msg: str) -> None:
        ax.set_title(msg, color=_TEXT, fontsize=11)
        ax.text(0.5, 0.5, msg, transform=ax.transAxes,
                ha="center", va="center", color=_TEXT, fontsize=12)
        for spine in ax.spines.values():
            spine.set_color(_GRID)

    def refresh(self) -> None:
        """刷新所有视图（外部按钮调用）。"""
        if self._profile:
            self.set_profile_result(self._profile)

    def clear(self) -> None:
        """清空所有结果。"""
        self._profile = None
        for canvas in (self._canvas_mesh, self._canvas_layers,
                       self._canvas_particles, self._canvas_unif):
            fig = canvas.figure
            fig.clear()
            if canvas is self._canvas_mesh:
                ax = fig.add_subplot(111, projection="3d")
                ax.set_facecolor(_BG)
                self._render_empty(ax, "已清空")
            else:
                ax = fig.add_subplot(111)
                ax.set_facecolor(_BG)
                self._render_empty_2d(ax, "已清空")
            canvas.draw_idle()
        self._lb_status.setText("已清空结果")
        self._lb_status.setStyleSheet(f"color:{_TEXT}; font-size:11px;")
