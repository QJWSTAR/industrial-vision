"""test_ui_medium_coverage.py — 中等覆盖 UI 模块补充测试

覆盖以下 7 个模块，目标各 90%+ 覆盖率：
  1. repair_app/ui/repair_visualizer.py  — 3D 修复可视化
  2. repair_app/ui/defect_selector.py    — 缺陷区域选取（补充未覆盖分支）
  3. repair_app/ui/layer_player.py       — 逐层播放控制
  4. repair_app/ui/realtime_stats.py     — 实时统计面板
  5. repair_app/ui/busy_indicator.py     — 忙碌指示器
  6. repair_app/ui/undo_framework.py     — 撤销/重做框架
  7. repair_app/ui/pipeline_indicator.py — 管线进度指示器

约定：
  - 使用 conftest.py 的 session 级 qapp fixture（offscreen 模式）
  - 模块按需懒导入，避免 collection-time 副作用
  - QWidget 实例在 fixture 中 close + deleteLater 清理
  - 不使用 time.sleep，不等待定时器/线程
"""
from __future__ import annotations

import os
import sys

# 必须在导入 PySide6 / matplotlib 之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CSAM_ALGORITHM_ENGINE", "python")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import struct

import numpy as np
import pytest

from PySide6.QtCore import QPointF, Qt, QEvent, QRect
from PySide6.QtGui import QMouseEvent, QPaintEvent


# ============================================================
# 通用辅助
# ============================================================
def _cleanup(widget, qapp) -> None:
    """关闭并清理 widget，避免泄漏。"""
    try:
        widget.close()
    except Exception:
        pass
    widget.deleteLater()
    qapp.processEvents()


def _make_stl_bytes(n_faces: int = 2) -> bytes:
    """构造最小有效的二进制 STL 字节串。"""
    header = b"\x00" * 80
    count = struct.pack("<I", n_faces)
    faces = b""
    for i in range(n_faces):
        normal = struct.pack("<3f", 0.0, 0.0, 1.0)
        v1 = struct.pack("<3f", float(i), 0.0, 0.0)
        v2 = struct.pack("<3f", float(i + 1), 1.0, 0.1)
        v3 = struct.pack("<3f", float(i), 1.0, 0.0)
        attr = b"\x00\x00"
        faces += normal + v1 + v2 + v3 + attr
    return header + count + faces


def _mouse_event(event_type: QEvent.Type, x: float, y: float) -> QMouseEvent:
    """构造 QMouseEvent（用于直接调用事件处理方法）。"""
    return QMouseEvent(
        event_type,
        QPointF(float(x), float(y)),
        QPointF(float(x), float(y)),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


# ============================================================
# 1. repair_visualizer.py
# ============================================================
def _small_points(n: int = 20, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-5, 5, (n, 2))
    z = rng.uniform(0, 1, n)
    return np.column_stack([xy, z]).astype(np.float32)


@pytest.fixture
def visualizer(qapp):
    from repair_app.ui.repair_visualizer import RepairVisualizer
    w = RepairVisualizer()
    yield w
    if getattr(w, "_anim_timer", None) is not None:
        try:
            w._anim_timer.stop()
        except Exception:
            pass
    try:
        w.cleanup()
    except Exception:
        pass
    _cleanup(w, qapp)


class TestRepairVisualizerHelpers:
    """模块级辅助函数：_triangulate_xy / _parse_binary_stl_to_points。"""

    def test_triangulate_normal(self, qapp):
        from repair_app.ui.repair_visualizer import _triangulate_xy
        pts = _small_points(20)
        result = _triangulate_xy(pts)
        assert result is not None
        tris, verts = result
        assert len(tris) > 0
        assert verts.shape[1] == 3

    def test_triangulate_too_few_points(self, qapp):
        from repair_app.ui.repair_visualizer import _triangulate_xy
        assert _triangulate_xy(_small_points(2)) is None

    def test_triangulate_collinear_returns_none(self, qapp):
        from repair_app.ui.repair_visualizer import _triangulate_xy
        # 共线点无法三角剖分
        pts = np.array([[0, 0, 0], [1, 1, 0], [2, 2, 0], [3, 3, 0]], dtype=float)
        assert _triangulate_xy(pts) is None

    def test_triangulate_subsamples_large(self, qapp):
        from repair_app.ui.repair_visualizer import _triangulate_xy
        pts = _small_points(3500, seed=5)
        result = _triangulate_xy(pts, max_pts=500)
        assert result is not None
        _, verts = result
        assert len(verts) <= 500

    def test_parse_stl_valid(self, qapp):
        from repair_app.ui.repair_visualizer import _parse_binary_stl_to_points
        pts = _parse_binary_stl_to_points(_make_stl_bytes(3))
        assert pts is not None
        assert pts.shape == (9, 3)

    def test_parse_stl_too_short(self, qapp):
        from repair_app.ui.repair_visualizer import _parse_binary_stl_to_points
        assert _parse_binary_stl_to_points(b"\x00" * 10) is None

    def test_parse_stl_zero_triangles(self, qapp):
        from repair_app.ui.repair_visualizer import _parse_binary_stl_to_points
        data = b"\x00" * 80 + struct.pack("<I", 0)
        assert _parse_binary_stl_to_points(data) is None

    def test_parse_stl_truncated(self, qapp):
        from repair_app.ui.repair_visualizer import _parse_binary_stl_to_points
        data = b"\x00" * 80 + struct.pack("<I", 10) + b"\x00" * 30
        assert _parse_binary_stl_to_points(data) is None


class TestRepairVisualizerSetters:
    def test_set_data_with_full_payload(self, visualizer):
        substrate = _small_points(30, seed=1)
        mask = np.zeros(30, dtype=bool)
        mask[:10] = True
        repair = _small_points(15, seed=2)
        waypoints = _small_points(12, seed=3)
        layers = [_small_points(10, seed=4), _small_points(10, seed=5), _small_points(10, seed=6)]
        visualizer.set_data(substrate, mask, repair, waypoints, layers)
        assert visualizer._substrate_pts is not None
        assert visualizer._current_layer == 2

    def test_set_data_without_layers(self, visualizer):
        visualizer.set_data(_small_points(15))
        assert visualizer._layer_data is None
        assert visualizer._current_layer == 0

    def test_set_mode_additive(self, visualizer):
        from repair_app.ui.repair_visualizer import RepairMode
        visualizer.set_data(_small_points(15))
        visualizer.set_mode(RepairMode.ADDITIVE)
        assert visualizer.mode == RepairMode.ADDITIVE

    def test_set_mode_repairing(self, visualizer):
        from repair_app.ui.repair_visualizer import RepairMode
        visualizer.set_data(_small_points(15))
        visualizer.set_mode(RepairMode.REPAIRING)
        assert visualizer.mode == RepairMode.REPAIRING

    def test_set_partial_waypoints(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer.set_partial_waypoints(_small_points(8))
        assert visualizer._partial_waypoints is not None
        assert len(visualizer._partial_waypoints) == 8

    def test_set_partial_repair(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer.set_partial_repair(_small_points(8))
        assert visualizer._partial_repair is not None

    def test_set_partial_mesh_valid(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer.set_partial_mesh(_make_stl_bytes(2))
        assert visualizer._partial_repair is not None

    def test_set_partial_mesh_empty(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._partial_repair = None
        visualizer.set_partial_mesh(b"")
        assert visualizer._partial_repair is None

    def test_set_partial_mesh_invalid(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._partial_repair = None
        visualizer.set_partial_mesh(b"\x00" * 10)
        assert visualizer._partial_repair is None

    def test_set_nozzle_orientations(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(10))
        pos = _small_points(10, seed=7)
        nrm = _small_points(10, seed=8)
        visualizer.set_nozzle_orientations(pos, nrm)
        assert visualizer._nozzle_positions is not None
        assert visualizer._nozzle_normals is not None

    def test_set_nozzle_orientations_none(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer.set_nozzle_orientations(None, None)
        assert visualizer._nozzle_positions is None


class TestRepairVisualizerToggles:
    def test_toggle_mesh(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._on_toggle_mesh(False)
        assert visualizer._show_mesh is False
        visualizer._on_toggle_mesh(True)
        assert visualizer._show_mesh is True

    def test_toggle_before(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._on_toggle_before(False)
        assert visualizer._show_before is False

    def test_toggle_waypoints(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(12))
        visualizer._on_toggle_waypoints(False)
        assert visualizer._show_waypoints is False

    def test_toggle_nozzle(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(12))
        visualizer._on_toggle_nozzle(True)
        assert visualizer._show_nozzle is True

    def test_toggle_colormap(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._on_toggle_colormap(False)
        assert visualizer._show_colormap is False

    def test_view_change_all_modes(self, visualizer):
        visualizer.set_data(_small_points(20))
        for idx in range(4):
            visualizer._on_view_changed(idx)
        # 越界索引不崩溃
        visualizer._on_view_changed(99)


class TestRepairVisualizerLayerAndAnimation:
    def test_layer_slider_with_data(self, visualizer):
        layers = [_small_points(10, seed=s) for s in range(4)]
        visualizer.set_data(_small_points(20), layers=layers)
        visualizer._on_layer_slider(50)
        assert visualizer._current_layer >= 0

    def test_layer_slider_single_layer(self, visualizer):
        visualizer.set_data(_small_points(20), layers=[_small_points(10)])
        visualizer._on_layer_slider(50)
        assert visualizer._current_layer == 0

    def test_layer_slider_without_data(self, visualizer):
        visualizer.set_data(_small_points(20))
        # 无 layer_data 时不应崩溃
        visualizer._on_layer_slider(50)

    def test_animation_start_and_stop(self, visualizer):
        layers = [_small_points(10, seed=s) for s in range(3)]
        visualizer.set_data(_small_points(20), layers=layers)
        # 启动动画
        visualizer._toggle_animation()
        assert visualizer._animating is True
        # 停止动画
        visualizer._toggle_animation()
        assert visualizer._animating is False

    def test_animation_no_layers_noop(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._toggle_animation()
        assert visualizer._animating is False

    def test_animation_single_layer_noop(self, visualizer):
        visualizer.set_data(_small_points(20), layers=[_small_points(10)])
        visualizer._toggle_animation()
        assert visualizer._animating is False

    def test_animation_step_advances_and_stops(self, visualizer):
        layers = [_small_points(10, seed=s) for s in range(3)]
        visualizer.set_data(_small_points(20), layers=layers)
        visualizer._toggle_animation()
        # 手动触发 timeout 信号以执行 _step（前进）
        visualizer._anim_timer.timeout.emit()
        assert visualizer._current_layer == 1
        # 再次触发到最后一层
        visualizer._anim_timer.timeout.emit()
        assert visualizer._current_layer == 2
        # 到最后一层后 _step 应停止动画
        visualizer._anim_timer.timeout.emit()
        assert visualizer._animating is False


class TestRepairVisualizerRenderPaths:
    def test_render_defect_mask_repairing(self, visualizer):
        from repair_app.ui.repair_visualizer import RepairMode
        substrate = _small_points(30, seed=1)
        mask = np.zeros(30, dtype=bool)
        mask[:15] = True
        visualizer.set_data(substrate, mask, repair=_small_points(10, seed=2))
        visualizer.set_mode(RepairMode.REPAIRING)

    def test_render_defect_mask_additive(self, visualizer):
        from repair_app.ui.repair_visualizer import RepairMode
        substrate = _small_points(30, seed=1)
        mask = np.zeros(30, dtype=bool)
        mask[:15] = True
        visualizer.set_data(substrate, mask, repair=_small_points(10, seed=2))
        visualizer.set_mode(RepairMode.ADDITIVE)

    def test_render_no_defect_mask(self, visualizer):
        visualizer.set_data(_small_points(20), repair=_small_points(12))

    def test_render_hide_before(self, visualizer):
        substrate = _small_points(30, seed=1)
        mask = np.zeros(30, dtype=bool)
        mask[:10] = True
        visualizer.set_data(substrate, mask, repair=_small_points(10))
        visualizer._on_toggle_before(False)
        assert visualizer._show_before is False

    def test_render_no_colormap_fallback(self, visualizer):
        substrate = _small_points(30, seed=1)
        mask = np.zeros(30, dtype=bool)
        mask[:10] = True
        visualizer.set_data(substrate, mask, repair=_small_points(12))
        visualizer._on_toggle_colormap(False)

    def test_render_scatter_few_points(self, visualizer):
        # 少于 3 点走散点回退
        visualizer.set_data(np.array([[0, 0, 0], [1, 1, 0.5]], dtype=float),
                            repair=np.array([[0, 0, 1], [1, 1, 1.5]], dtype=float))

    def test_render_waypoints_path(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(15))

    def test_render_partial_waypoints(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(15))
        visualizer.set_partial_waypoints(_small_points(8))

    def test_render_nozzle_with_waypoints(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(12))
        visualizer._on_toggle_nozzle(True)

    def test_render_nozzle_with_orientations(self, visualizer):
        visualizer.set_data(_small_points(20), waypoints=_small_points(12))
        pos = _small_points(10, seed=7)
        nrm = _small_points(10, seed=8)
        visualizer.set_nozzle_orientations(pos, nrm)
        visualizer._on_toggle_nozzle(True)


class TestRepairVisualizerConvenience:
    def test_reset_view(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer._on_view_changed(1)  # 切到俯视图
        visualizer.reset_view()
        assert visualizer._view_mode.value == "isometric"

    def test_fit_to_view_with_data(self, visualizer):
        visualizer.set_data(_small_points(20), repair=_small_points(10),
                            waypoints=_small_points(8))
        visualizer.fit_to_view()

    def test_fit_to_view_without_data(self, visualizer):
        visualizer.fit_to_view()

    def test_toggle_axes(self, visualizer):
        visualizer.set_data(_small_points(20))
        visualizer.toggle_axes()
        visualizer.toggle_axes()

    def test_cleanup(self, qapp):
        from repair_app.ui.repair_visualizer import RepairVisualizer
        w = RepairVisualizer()
        w.set_data(_small_points(20))
        w.cleanup()
        assert w._fig is None
        assert w._ax is None
        _cleanup(w, qapp)


# ============================================================
# 2. defect_selector.py — 补充未覆盖分支
# ============================================================
@pytest.fixture
def selector(qapp):
    from repair_app.ui.defect_selector import DefectSelector
    w = DefectSelector()
    pts = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 2.0, 0.0],
        ],
        dtype=float,
    )
    w.set_points(pts)
    yield w
    _cleanup(w, qapp)


class TestDefectSelectorEventFilter:
    def test_event_filter_non_canvas_object(self, selector, qapp):
        from PySide6.QtWidgets import QLabel
        other = QLabel()
        ev = _mouse_event(QEvent.MouseButtonPress, 1, 1)
        # 非 canvas 对象直接走 super
        result = selector.eventFilter(other, ev)
        assert result is False
        _cleanup(other, qapp)

    def test_event_filter_not_selecting(self, selector):
        selector._selecting = False
        ev = _mouse_event(QEvent.MouseButtonPress, 1, 1)
        result = selector.eventFilter(selector._canvas, ev)
        assert result is False

    def test_event_filter_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._selecting = True
        w._points = None
        ev = _mouse_event(QEvent.MouseButtonPress, 1, 1)
        result = w.eventFilter(w._canvas, ev)
        assert result is False
        _cleanup(w, qapp)

    def test_event_filter_unknown_event_type(self, selector):
        # 未知事件类型走 super（line 152）
        ev = _mouse_event(QEvent.MouseButtonDblClick, 1, 1)
        result = selector.eventFilter(selector._canvas, ev)
        assert result is False


class TestDefectSelectorMouseHandlers:
    def test_rect_press_move_release(self, selector):
        # 用迭代器控制 _screen_to_data 返回值
        coords = iter([(0.0, 0.0), (1.5, 1.5), (1.5, 1.5)])
        selector._screen_to_data = lambda sx, sy: next(coords)
        selector._mode = "rect"
        selector._selecting = True
        # press
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonPress, 10, 10))
        assert selector._is_dragging is True
        # move（设置 rubber_rect）
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseMove, 20, 20))
        assert selector._rubber_rect is not None
        # release（应用矩形选区）
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonRelease, 20, 20))
        assert selector._is_dragging is False
        assert selector._rubber_rect is None

    def test_lasso_press_move_release(self, selector):
        coords = iter([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)])
        selector._screen_to_data = lambda sx, sy: next(coords)
        selector._mode = "lasso"
        selector._selecting = True
        selector._on_brush_radius_changed  # noqa
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonPress, 10, 10))
        assert len(selector._lasso_verts) == 1
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseMove, 20, 20))
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseMove, 30, 30))
        assert len(selector._lasso_verts) >= 3
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonRelease, 30, 30))
        assert selector._lasso_verts == []

    def test_brush_press_move_release(self, selector):
        coords = iter([(0.5, 0.5), (1.0, 1.0), (0.0, 0.0)])
        selector._screen_to_data = lambda sx, sy: next(coords)
        selector._mode = "brush"
        selector._selecting = True
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonPress, 10, 10))
        assert selector._is_dragging is True
        assert len(selector._mask_history) == 1
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseMove, 20, 20))
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonRelease, 30, 30))

    def test_erase_mode(self, selector):
        # 先选中部分点，再用 erase 模式擦除
        selector._mask = np.array([True, True, False, False, False])
        coords = iter([(0.5, 0.5), (0.5, 0.5)])
        selector._screen_to_data = lambda sx, sy: next(coords)
        selector._mode = "erase"
        selector._selecting = True
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonPress, 10, 10))
        assert len(selector._mask_history) == 1
        selector.eventFilter(selector._canvas, _mouse_event(QEvent.MouseButtonRelease, 20, 20))

    def test_move_when_not_dragging_returns_false(self, selector):
        selector._is_dragging = False
        result = selector._qt_mouse_move(_mouse_event(QEvent.MouseMove, 10, 10))
        assert result is False

    def test_release_when_not_dragging_returns_false(self, selector):
        selector._is_dragging = False
        result = selector._qt_mouse_release(_mouse_event(QEvent.MouseButtonRelease, 10, 10))
        assert result is False

    def test_screen_to_data_returns_tuple(self, selector):
        result = selector._screen_to_data(10, 10)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestDefectSelectorSelectionLogic:
    def test_apply_rect_select(self, selector):
        selector._rubber_rect = (0.0, 0.0, 1.5, 1.5)
        selector._apply_rect_select()
        # 4 个点在矩形内
        assert int(np.sum(selector._mask)) == 4

    def test_apply_rect_select_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._rubber_rect = (0.0, 0.0, 1.0, 1.0)
        w._apply_rect_select()  # 不应崩溃
        _cleanup(w, qapp)

    def test_apply_lasso_select(self, selector):
        selector._lasso_verts = [(0.0, 0.0), (2.5, 0.0), (2.5, 2.5), (0.0, 2.5)]
        selector._apply_lasso_select()
        assert int(np.sum(selector._mask)) >= 1

    def test_apply_lasso_select_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._lasso_verts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        w._apply_lasso_select()
        _cleanup(w, qapp)

    def test_apply_brush_selects_points(self, selector):
        selector._mode = "brush"
        selector._apply_brush(0.5, 0.5)
        assert np.any(selector._mask)

    def test_apply_brush_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._mode = "brush"
        w._apply_brush(0.5, 0.5)
        _cleanup(w, qapp)

    def test_apply_brush_already_selected_noop(self, selector):
        selector._mode = "brush"
        selector._apply_brush(0.5, 0.5)
        before = selector._mask.copy()
        selector._apply_brush(0.5, 0.5)  # 已选中的点不再触发
        np.testing.assert_array_equal(selector._mask, before)

    def test_apply_brush_out_of_range_noop(self, selector):
        selector._mode = "brush"
        selector._apply_brush(100.0, 100.0)
        assert not np.any(selector._mask)

    def test_apply_erase_removes_points(self, selector):
        selector._mode = "brush"
        selector._apply_brush(0.5, 0.5)
        assert np.any(selector._mask)
        selector._mode = "erase"
        selector._apply_brush(0.5, 0.5)
        assert not np.any(selector._mask[:2])

    def test_apply_erase_no_overlap_noop(self, selector):
        selector._mode = "erase"
        selector._mask = np.array([True, True, False, False, False])
        before = selector._mask.copy()
        selector._apply_brush(100.0, 100.0)
        np.testing.assert_array_equal(selector._mask, before)


class TestDefectSelectorUndoAndOps:
    def test_push_history_enables_undo(self, selector):
        selector._push_history()
        assert selector._btn_undo.isEnabled() is True

    def test_undo_restores_mask(self, selector):
        selector._mask = np.array([True, False, False, False, False])
        selector._push_history()
        selector._mask = np.array([True, True, True, True, True])
        received = []
        selector.selection_changed.connect(lambda m: received.append(m))
        selector._undo()
        assert np.array_equal(selector._mask, [True, False, False, False, False])
        assert len(received) == 1

    def test_undo_empty_history_noop(self, selector):
        selector._mask_history.clear()
        selector._btn_undo.setEnabled(False)
        selector._undo()
        assert len(selector._mask_history) == 0

    def test_invert_selection_private(self, selector):
        received = []
        selector.selection_changed.connect(lambda m: received.append(m))
        selector._invert_selection()
        assert np.all(selector._mask)
        assert len(received) == 1

    def test_invert_selection_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._invert_selection()
        _cleanup(w, qapp)

    def test_clear_selection_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._clear_selection()
        _cleanup(w, qapp)


class TestDefectSelectorPublicAPI:
    def test_set_selection_mask_valid(self, selector):
        new_mask = np.array([True, False, True, False, True])
        selector.set_selection_mask(new_mask)
        np.testing.assert_array_equal(selector.get_selection_mask(), new_mask)
        assert len(selector._mask_history) == 1

    def test_set_selection_mask_wrong_shape(self, selector):
        before = selector.get_selection_mask()
        selector.set_selection_mask(np.array([True, False]))
        np.testing.assert_array_equal(selector.get_selection_mask(), before)

    def test_set_selection_mask_none(self, selector):
        before = selector.get_selection_mask()
        selector.set_selection_mask(None)
        np.testing.assert_array_equal(selector.get_selection_mask(), before)

    def test_public_clear_selection(self, selector):
        selector._mask = np.array([True, True, False, False, False])
        selector.clear_selection()
        assert not np.any(selector._mask)
        assert len(selector._mask_history) == 1

    def test_public_invert_selection(self, selector):
        selector._mask = np.array([True, False, False, False, False])
        selector.invert_selection()
        np.testing.assert_array_equal(
            selector._mask, [False, True, True, True, True])

    def test_get_selected_points_empty(self, selector):
        sel = selector.get_selected_points()
        assert sel.shape == (0,)


class TestDefectSelectorNavAndMode:
    def test_nav_toggle_on(self, selector):
        selector._on_nav_toggled(True)
        assert selector._selecting is False
        assert selector._cb_mode.isEnabled() is False

    def test_nav_toggle_off(self, selector):
        selector._on_nav_toggled(False)
        assert selector._selecting is True
        assert selector._cb_mode.isEnabled() is True

    def test_submode_change_brush(self, selector):
        selector._on_nav_toggled(False)
        selector._on_submode_changed(2)  # brush
        assert selector._mode == "brush"
        assert selector._sp_brush.isEnabled() is True

    def test_submode_change_erase(self, selector):
        selector._on_nav_toggled(False)
        selector._on_submode_changed(3)  # erase
        assert selector._mode == "erase"

    def test_submode_change_rect(self, selector):
        selector._on_nav_toggled(False)
        selector._on_submode_changed(0)  # rect
        assert selector._mode == "rect"

    def test_submode_change_lasso(self, selector):
        selector._on_nav_toggled(False)
        selector._on_submode_changed(1)  # lasso
        assert selector._mode == "lasso"

    def test_submode_change_invalid_index(self, selector):
        selector._on_submode_changed(99)
        # 不崩溃即可

    def test_update_info_with_points(self, selector):
        selector._mask = np.array([True, False, True, False, False])
        selector._update_info()
        assert "2 / 5" in selector._lb_info.text()

    def test_update_info_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._update_info()
        assert w._lb_info.text() == "未加载点云"
        _cleanup(w, qapp)


class TestDefectSelectorRedraw:
    def test_redraw_with_selected_points(self, selector):
        selector._mask = np.array([True, True, False, False, False])
        selector._redraw()

    def test_redraw_with_rubber_rect(self, selector):
        selector._rubber_rect = (0.0, 0.0, 1.0, 1.0)
        selector._redraw()

    def test_redraw_with_lasso_verts(self, selector):
        selector._lasso_verts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        selector._redraw()

    def test_redraw_no_points(self, qapp):
        from repair_app.ui.defect_selector import DefectSelector
        w = DefectSelector()
        w._points = None
        w._redraw()
        _cleanup(w, qapp)


# ============================================================
# 3. layer_player.py
# ============================================================
@pytest.fixture
def player(qapp):
    from repair_app.ui.layer_player import LayerPlayer
    w = LayerPlayer()
    yield w
    try:
        w.stop_play()
    except Exception:
        pass
    _cleanup(w, qapp)


class TestLayerPlayerBasics:
    def test_initial_state(self, player):
        assert player._total_layers == 0
        assert player._current_layer == 0
        assert player._is_playing is False
        assert player._btn_play.isEnabled() is False

    def test_set_total_layers(self, player):
        player.set_total_layers(5)
        assert player._total_layers == 5
        assert player._slider.maximum() == 4
        assert player._btn_play.isEnabled() is True

    def test_set_total_layers_zero(self, player):
        player.set_total_layers(5)
        player.set_total_layers(0)
        assert player._total_layers == 0
        assert player._slider.maximum() == 0

    def test_set_total_layers_shrinks_current(self, player):
        player.set_total_layers(10)
        player.set_current_layer(8)
        player.set_total_layers(3)
        assert player._current_layer <= 2

    def test_set_current_layer(self, player):
        player.set_total_layers(5)
        player.set_current_layer(3)
        assert player._current_layer == 3
        assert player._slider.value() == 3

    def test_set_current_layer_out_of_range(self, player):
        player.set_total_layers(3)
        player.set_current_layer(99)
        assert player._current_layer == 0

    def test_set_current_layer_negative(self, player):
        player.set_total_layers(3)
        player.set_current_layer(-1)
        assert player._current_layer == 0


class TestLayerPlayerControls:
    def test_prev_button(self, player):
        player.set_total_layers(5)
        player.set_current_layer(2)
        player._on_prev()
        assert player._current_layer == 1

    def test_prev_at_zero_noop(self, player):
        player.set_total_layers(5)
        player._on_prev()
        assert player._current_layer == 0

    def test_next_button(self, player):
        player.set_total_layers(5)
        player.set_current_layer(1)
        player._on_next()
        assert player._current_layer == 2

    def test_next_at_last_noop(self, player):
        player.set_total_layers(5)
        player.set_current_layer(4)
        player._on_next()
        assert player._current_layer == 4

    def test_slider_changed_emits_signal(self, player):
        received = []
        player.layer_changed.connect(lambda v: received.append(v))
        player.set_total_layers(5)
        player._slider.setValue(3)
        assert 3 in received

    def test_play_pause_toggle(self, player):
        player.set_total_layers(4)
        states = []
        player.play_state.connect(lambda s: states.append(s))
        player._on_play_pause()  # 开始播放
        assert player._is_playing is True
        assert states == [True]
        player._on_play_pause()  # 暂停
        assert player._is_playing is False
        assert states == [True, False]

    def test_play_single_layer_noop(self, player):
        player.set_total_layers(1)
        player._on_play_pause()
        assert player._is_playing is False

    def test_play_tick_advances(self, player):
        player.set_total_layers(4)
        player.set_current_layer(0)
        player._on_play_tick()
        assert player._current_layer == 1

    def test_play_tick_at_last_stops(self, player):
        player.set_total_layers(4)
        player.set_current_layer(3)
        player._is_playing = True
        player._on_play_tick()
        assert player._is_playing is False

    def test_speed_change_while_playing(self, player):
        player.set_total_layers(4)
        player._on_play_pause()
        player._on_speed_changed(200)
        assert player._is_playing is True
        player.stop_play()

    def test_speed_change_while_not_playing(self, player):
        player._on_speed_changed(300)
        assert player._is_playing is False

    def test_reset(self, player):
        player.set_total_layers(5)
        player.set_current_layer(3)
        player._on_play_pause()
        player.reset()
        assert player._current_layer == 0
        assert player._is_playing is False

    def test_stop_play_when_not_playing(self, player):
        player.stop_play()
        assert player._is_playing is False

    def test_layer_label_updates(self, player):
        player.set_total_layers(5)
        player.set_current_layer(2)
        assert "3 / 5" in player._lb_layer.text()

    def test_prev_next_enabled_states(self, player):
        player.set_total_layers(3)
        player.set_current_layer(0)
        assert player._btn_prev.isEnabled() is False
        assert player._btn_next.isEnabled() is True
        player.set_current_layer(2)
        assert player._btn_next.isEnabled() is False
        assert player._btn_prev.isEnabled() is True


# ============================================================
# 4. realtime_stats.py
# ============================================================
@pytest.fixture
def stats_panel(qapp):
    from repair_app.ui.realtime_stats import RealtimeStatsPanel
    w = RealtimeStatsPanel()
    yield w
    _cleanup(w, qapp)


class TestRealtimeStats:
    def test_update_stats_full(self, stats_panel):
        stats_panel.update_stats({
            "elapsed_s": 12.5,
            "layer_index": 3,
            "total_layers": 10,
            "waypoint_count": 150,
            "mesh_triangle_count": 1200,
            "progress": 0.35,
            "stage_name": "路径规划",
            "message": "计算中",
        })
        assert "12.5s" in stats_panel._card_time._value_label.text()
        assert "4/10" in stats_panel._card_layers._value_label.text()
        assert "150" in stats_panel._card_points._value_label.text()
        assert "1200" in stats_panel._card_mesh._value_label.text()
        assert stats_panel._prog.value() == 35
        assert "路径规划" in stats_panel._lb_message.text()
        assert "计算中" in stats_panel._lb_message.text()

    def test_update_stats_empty_dict(self, stats_panel):
        stats_panel.update_stats({})
        assert "0.0s" in stats_panel._card_time._value_label.text()
        assert "1/0" in stats_panel._card_layers._value_label.text()
        assert stats_panel._prog.value() == 0

    def test_update_stats_stage_only(self, stats_panel):
        stats_panel.update_stats({"stage_name": "形貌预测"})
        text = stats_panel._lb_message.text()
        assert "形貌预测" in text
        # 无 message 时只显示 [stage]
        assert text.startswith("[形貌预测]")

    def test_update_stats_progress_clamp(self, stats_panel):
        stats_panel.update_stats({"progress": 1.0})
        assert stats_panel._prog.value() == 100

    def test_reset(self, stats_panel):
        stats_panel.update_stats({"elapsed_s": 5.0, "progress": 0.5})
        stats_panel.reset()
        assert stats_panel._card_time._value_label.text() == "—"
        assert stats_panel._card_layers._value_label.text() == "—"
        assert stats_panel._card_points._value_label.text() == "—"
        assert stats_panel._card_mesh._value_label.text() == "—"
        assert stats_panel._prog.value() == 0
        assert stats_panel._lb_message.text() == "等待计算..."

    def test_stat_card_set_value(self, stats_panel):
        stats_panel._card_time.set_value("42.0s")
        assert stats_panel._card_time._value_label.text() == "42.0s"


# ============================================================
# 5. busy_indicator.py
# ============================================================
@pytest.fixture
def busy_indicator(qapp):
    from repair_app.ui.busy_indicator import BusyIndicator
    w = BusyIndicator()
    yield w
    try:
        w.stop()
    except Exception:
        pass
    _cleanup(w, qapp)


class TestBusyIndicator:
    def test_initial_state(self, busy_indicator):
        assert busy_indicator._running is False
        assert busy_indicator._angle == 0

    def test_start(self, busy_indicator):
        busy_indicator.start()
        assert busy_indicator._running is True
        assert busy_indicator._timer.isActive() is True

    def test_start_idempotent(self, busy_indicator):
        busy_indicator.start()
        timer1 = busy_indicator._timer.timerId()
        busy_indicator.start()
        assert busy_indicator._running is True

    def test_stop(self, busy_indicator):
        busy_indicator.start()
        busy_indicator.stop()
        assert busy_indicator._running is False
        assert busy_indicator._timer.isActive() is False

    def test_set_color(self, busy_indicator):
        busy_indicator.set_color("#FF0000")
        from PySide6.QtGui import QColor
        assert busy_indicator._color == QColor("#FF0000")

    def test_rotate_increments_angle(self, busy_indicator):
        busy_indicator._rotate()
        assert busy_indicator._angle == 30
        busy_indicator._rotate()
        assert busy_indicator._angle == 60

    def test_rotate_wraps(self, busy_indicator):
        busy_indicator._angle = 330
        busy_indicator._rotate()
        assert busy_indicator._angle == 0

    def test_paint_event_when_running(self, busy_indicator):
        busy_indicator.start()
        event = QPaintEvent(QRect(0, 0, 16, 16))
        # 直接调用 paintEvent 覆盖绘制逻辑
        busy_indicator.paintEvent(event)

    def test_paint_event_when_not_running(self, busy_indicator):
        event = QPaintEvent(QRect(0, 0, 16, 16))
        # 未运行时 paintEvent 立即返回
        busy_indicator.paintEvent(event)


class TestBusyLabel:
    def test_set_busy_true(self, qapp):
        from repair_app.ui.busy_indicator import BusyLabel
        w = BusyLabel()
        w.set_busy(True, "正在计算...")
        assert w._indicator._running is True
        assert "正在计算" in w._label.text()
        w.set_busy(False)
        _cleanup(w, qapp)

    def test_set_busy_false_default_text(self, qapp):
        from repair_app.ui.busy_indicator import BusyLabel
        w = BusyLabel()
        w.set_busy(True)
        w.set_busy(False)
        assert w._label.text() == "就绪"
        assert w._indicator._running is False
        _cleanup(w, qapp)

    def test_set_busy_true_default_text(self, qapp):
        from repair_app.ui.busy_indicator import BusyLabel
        w = BusyLabel()
        w.set_busy(True)
        assert w._indicator._running is True
        assert w._label.text() == "处理中..."
        w.set_busy(False)
        _cleanup(w, qapp)


# ============================================================
# 6. undo_framework.py
# ============================================================
@pytest.fixture
def undo_stack(qapp):
    from repair_app.ui.undo_framework import UndoStack
    UndoStack.reset()
    stack = UndoStack.instance()
    yield stack
    try:
        stack.clear()
    except Exception:
        pass
    UndoStack.reset()


class TestUndoableAction:
    def test_undoable_action_init(self, qapp):
        from repair_app.ui.undo_framework import UndoableAction
        cmd = UndoableAction("测试动作")
        assert cmd.text() == "测试动作"


class TestCallbackAction:
    def test_callback_first_redo_skips(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        do_calls = []
        undo_calls = []
        cmd = CallbackAction("修改", lambda: do_calls.append(1),
                             lambda: undo_calls.append(1))
        undo_stack.push(cmd)
        # 首次 push 的 redo 不执行 do_callback
        assert do_calls == []
        assert undo_stack.can_undo() is True

    def test_callback_undo_then_redo_executes(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        do_calls = []
        undo_calls = []
        cmd = CallbackAction("修改", lambda: do_calls.append(1),
                             lambda: undo_calls.append(1))
        undo_stack.push(cmd)
        undo_stack.undo()
        assert undo_calls == [1]
        # redo 再次执行 do
        undo_stack.redo()
        assert do_calls == [1]


class TestSelectionAction:
    def test_selection_action_redo_and_undo(self, qapp):
        from repair_app.ui.undo_framework import SelectionAction, UndoStack
        UndoStack.reset()
        stack = UndoStack.instance()

        class FakeSelector:
            def __init__(self):
                self.mask = np.array([False, False, False])

            def set_selection_mask(self, mask):
                self.mask = mask

        sel = FakeSelector()
        old = np.array([False, False, False])
        new = np.array([True, True, False])
        cmd = SelectionAction(sel, old, new, "修改选区")
        stack.push(cmd)
        # redo 应用 new_mask
        np.testing.assert_array_equal(sel.mask, new)
        stack.undo()
        np.testing.assert_array_equal(sel.mask, old)
        stack.clear()
        UndoStack.reset()

    def test_selection_action_none_masks(self, qapp):
        from repair_app.ui.undo_framework import SelectionAction
        cmd = SelectionAction(None, None, None, "空操作")
        # redo/undo 不崩溃
        cmd.redo()
        cmd.undo()


class TestUndoStack:
    def test_can_undo_redo_initially_false(self, undo_stack):
        assert undo_stack.can_undo() is False
        assert undo_stack.can_redo() is False

    def test_push_and_undo(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        log = []
        undo_stack.push(CallbackAction("op1", lambda: log.append("do1"),
                                       lambda: log.append("undo1")))
        assert undo_stack.can_undo() is True
        undo_stack.undo()
        assert "undo1" in log
        assert undo_stack.can_redo() is True

    def test_clear(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        undo_stack.push(CallbackAction("op", lambda: None, lambda: None))
        undo_stack.clear()
        assert undo_stack.can_undo() is False
        assert undo_stack.can_redo() is False

    def test_create_undo_action(self, undo_stack):
        action = undo_stack.create_undo_action(None, "撤销")
        assert "Ctrl+Z" in [s.toString() for s in action.shortcuts()]

    def test_create_redo_action(self, undo_stack):
        action = undo_stack.create_redo_action(None, "重做")
        shortcuts = [s.toString() for s in action.shortcuts()]
        assert "Ctrl+Y" in shortcuts

    def test_undo_text_empty(self, undo_stack):
        assert undo_stack.undo_text() == "撤销"

    def test_redo_text_empty(self, undo_stack):
        assert undo_stack.redo_text() == "重做"

    def test_undo_text_with_command(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        undo_stack.push(CallbackAction("修改层高", lambda: None, lambda: None))
        assert "修改层高" in undo_stack.undo_text()

    def test_redo_text_with_command(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        undo_stack.push(CallbackAction("修改层高", lambda: None, lambda: None))
        undo_stack.undo()
        assert "修改层高" in undo_stack.redo_text()

    def test_instance_singleton(self, undo_stack):
        from repair_app.ui.undo_framework import UndoStack
        assert UndoStack.instance() is UndoStack.instance()

    def test_reset(self, qapp):
        from repair_app.ui.undo_framework import UndoStack
        s1 = UndoStack.instance()
        UndoStack.reset()
        s2 = UndoStack.instance()
        assert s1 is not s2
        UndoStack.reset()

    def test_changed_signal(self, undo_stack):
        from repair_app.ui.undo_framework import CallbackAction
        emitted = []
        undo_stack.changed.connect(lambda: emitted.append(1))
        undo_stack.push(CallbackAction("op", lambda: None, lambda: None))
        assert len(emitted) >= 1


# ============================================================
# 7. pipeline_indicator.py
# ============================================================
@pytest.fixture
def pipeline(qapp):
    from repair_app.ui.pipeline_indicator import PipelineIndicator
    w = PipelineIndicator()
    yield w
    _cleanup(w, qapp)


class TestPipelineIndicator:
    def test_initial_all_waiting(self, pipeline):
        assert len(pipeline._stage_statuses) == 5
        for status in pipeline._stage_statuses:
            assert status == "waiting"

    def test_set_stage_status_valid(self, pipeline):
        from repair_app.ui.pipeline_indicator import PipelineStage
        pipeline.set_stage_status(0, PipelineStage.DONE)
        assert pipeline._stage_statuses[0] == "done"

    def test_set_stage_status_invalid_index(self, pipeline):
        from repair_app.ui.pipeline_indicator import PipelineStage
        pipeline.set_stage_status(-1, PipelineStage.DONE)
        pipeline.set_stage_status(99, PipelineStage.DONE)
        # 越界索引不改变状态
        for status in pipeline._stage_statuses:
            assert status == "waiting"

    def test_set_running(self, pipeline):
        pipeline.set_running(1)
        assert pipeline._stage_statuses[1] == "running"

    def test_set_done(self, pipeline):
        pipeline.set_done(2)
        assert pipeline._stage_statuses[2] == "done"

    def test_set_failed(self, pipeline):
        pipeline.set_failed(3)
        assert pipeline._stage_statuses[3] == "failed"

    def test_mark_running_as_failed(self, pipeline):
        from repair_app.ui.pipeline_indicator import PipelineStage
        pipeline.set_running(1)
        pipeline.mark_running_as_failed()
        assert pipeline._stage_statuses[1] == "failed"

    def test_mark_running_as_failed_noop(self, pipeline):
        # 无 running 阶段时不操作
        pipeline.mark_running_as_failed()
        for status in pipeline._stage_statuses:
            assert status == "waiting"

    def test_reset(self, pipeline):
        from repair_app.ui.pipeline_indicator import PipelineStage
        for i in range(5):
            pipeline.set_stage_status(i, PipelineStage.DONE)
        pipeline.reset()
        for status in pipeline._stage_statuses:
            assert status == "waiting"

    def test_all_status_styles(self, pipeline):
        from repair_app.ui.pipeline_indicator import PipelineStage
        # 遍历所有状态，确保 _refresh_styles 对每种状态都能正常渲染
        for status in [PipelineStage.WAITING, PipelineStage.RUNNING,
                       PipelineStage.DONE, PipelineStage.FAILED]:
            pipeline.set_stage_status(0, status)
        # 验证标签文本包含图标
        pipeline.set_stage_status(0, PipelineStage.DONE)
        assert "✓" in pipeline._stage_labels[0].text()

    def test_stage_names_count(self, pipeline):
        assert len(pipeline.STAGE_NAMES) == 5
        assert len(pipeline._stage_labels) == 5
        assert len(pipeline._arrow_labels) == 4
