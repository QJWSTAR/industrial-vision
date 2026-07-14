"""
test_defect_selector.py — 缺陷区域选取组件 (DefectSelector) 单元测试

被测模块: repair_app/ui/defect_selector.py
被测类:   DefectSelector(QWidget)

说明:
    DefectSelector 继承自 QWidget, 需要 Qt 离屏渲染环境
    (QT_QPA_PLATFORM=offscreen, 在导入 PySide6 之前设置)。
    测试仅验证纯逻辑接口 (set_points / get_selected_points /
    get_selection_mask / 清空选区 / 笔刷半径), 不依赖真实鼠标渲染。
"""
from __future__ import annotations

import os

# 必须在导入 PySide6 之前设置离屏渲染平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from repair_app.ui.defect_selector import DefectSelector


@pytest.fixture(scope="module")
def qapp():
    """提供全局 QApplication (离屏模式)。"""
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def selector(qapp):
    """提供一个已加载 5 个点的 DefectSelector 实例。"""
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
    w.deleteLater()
    qapp.processEvents()


class TestSetPoints:
    def test_set_points_creates_mask_with_correct_length(self, selector):
        assert len(selector.get_selection_mask()) == 5

    def test_set_points_initial_mask_all_false(self, selector):
        mask = selector.get_selection_mask()
        assert mask.dtype == bool
        assert not np.any(mask)

    def test_set_points_stores_points(self, selector):
        assert selector._points is not None
        assert len(selector._points) == 5

    def test_set_points_resets_history(self, selector):
        assert len(selector._mask_history) == 0


class TestGetSelectedPoints:
    def test_empty_selection_returns_empty(self, selector):
        sel = selector.get_selected_points()
        assert isinstance(sel, np.ndarray)
        assert sel.shape == (0,)

    def test_returns_correct_subset(self, selector):
        # 选中第 0、2 个点
        selector._mask = np.array([True, False, True, False, False])
        sel = selector.get_selected_points()
        assert sel.shape == (2, 3)
        assert np.allclose(sel, [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def test_select_all(self, selector):
        selector._mask = np.ones(5, dtype=bool)
        sel = selector.get_selected_points()
        assert sel.shape == (5, 3)


class TestGetSelectionMask:
    def test_returns_correct_mask(self, selector):
        selector._mask = np.array([True, False, False, True, False])
        mask = selector.get_selection_mask()
        assert np.array_equal(mask, [True, False, False, True, False])

    def test_returns_copy(self, selector):
        selector._mask = np.array([True, False, False, False, False])
        mask = selector.get_selection_mask()
        mask[0] = False  # 修改返回值
        # 内部状态不应被影响
        assert selector._mask[0] == True  # noqa: E712

    def test_mask_dtype_is_bool(self, selector):
        assert selector.get_selection_mask().dtype == bool


class TestClearSelection:
    def test_clear_selection_empties_mask(self, selector):
        selector._mask = np.array([True, True, False, True, False])
        selector._clear_selection()
        assert not np.any(selector.get_selection_mask())

    def test_clear_selection_pushes_history(self, selector):
        selector._mask = np.array([True, False, False, False, False])
        selector._clear_selection()
        assert len(selector._mask_history) == 1
        # 历史中保存的是清除前的 mask
        assert np.array_equal(
            selector._mask_history[0], [True, False, False, False, False]
        )

    def test_clear_selection_noop_when_already_empty(self, selector):
        # mask 全 False 时 _clear_selection 直接 return, 不压栈
        selector._clear_selection()
        assert len(selector._mask_history) == 0


class TestBrushRadius:
    def test_default_brush_radius(self, selector):
        assert selector._brush_radius == 2.0
        assert selector._sp_brush.value() == 2.0

    def test_set_brush_radius_via_spinbox(self, selector):
        selector._sp_brush.setValue(5.0)
        assert selector._brush_radius == 5.0
        assert selector._sp_brush.value() == 5.0

    def test_set_brush_radius_via_handler(self, selector):
        selector._on_brush_radius_changed(7.5)
        assert selector._brush_radius == 7.5

    def test_brush_radius_spinbox_range(self, selector):
        # spinbox 范围 0.5 ~ 20.0
        assert selector._sp_brush.minimum() == 0.5
        assert selector._sp_brush.maximum() == 20.0


class TestSetMode:
    def test_set_mode_brush(self, selector):
        selector.set_mode("brush")
        assert selector._cb_mode.currentData() == "brush"

    def test_set_mode_rect(self, selector):
        selector.set_mode("rect")
        assert selector._cb_mode.currentData() == "rect"

    def test_set_invalid_mode_no_change(self, selector):
        selector.set_mode("rect")
        selector.set_mode("nonexistent")
        # 无效模式不应改变当前模式
        assert selector._cb_mode.currentData() == "rect"


class TestSelectionChangedSignal:
    def test_signal_emitted_on_clear(self, selector):
        received = []
        selector.selection_changed.connect(lambda m: received.append(m))
        selector._mask = np.array([True, False, False, False, False])
        selector._clear_selection()
        assert len(received) == 1
        assert not np.any(received[0])
