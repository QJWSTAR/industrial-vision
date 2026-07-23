"""ui.workflow_controller — 工作流状态控制器

管理 5 阶段工作流状态机，协调步骤按钮样式和 PipelineIndicator 可视化更新。
从 MainWindow._update_step_buttons 提取，职责单一、可独立测试。
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from repair_app.ui.pipeline_indicator import PipelineIndicator, PipelineStage


# ═══════════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════════

class StepState(Enum):
    WAITING = auto()
    ACTIVE = auto()
    DONE = auto()
    LOCKED = auto()


class WorkflowStep(Enum):
    IMPORT = 0      # 01 导入点云
    PATH = 1        # 02 路径规划
    MORPH = 2       # 03 形貌预测
    RESULT = 3      # 04 结果校核
    EXPORT = 4      # 05 输出交付


# ═══════════════════════════════════════════════════════════════════
# 步骤按钮样式常量
# ═══════════════════════════════════════════════════════════════════

_STEP_DONE = (
    "QPushButton{background:#052E2B;color:#A7F3D0;border:1px solid #10B981;"
    "border-radius:12px;padding:9px 12px;font-size:13px;font-weight:bold;}"
    "QPushButton:hover{background:#064E3B;}"
)
_STEP_ACTIVE = (
    "QPushButton{{background:{c};color:#EFF6FF;border:1px solid {h};"
    "border-radius:12px;padding:9px 12px;font-size:13px;font-weight:bold;}}"
    "QPushButton:hover{{background:{b};}}"
)
_STEP_LOCKED = (
    "QPushButton{background:#111827;color:#64748B;border:1px solid #273449;"
    "border-radius:12px;padding:9px 12px;font-size:13px;font-weight:bold;}"
)
_ARROW = "color:#334155; font-size:18px; font-weight:bold;"
_ARROW_READY = "color:#10B981; font-size:18px; font-weight:bold;"


# ═══════════════════════════════════════════════════════════════════
# WorkflowController
# ═══════════════════════════════════════════════════════════════════

class WorkflowController(QObject):
    """工作流状态控制器。

    管理 5 阶段工作流（导入 → 路径 → 形貌 → 结果 → 导出）的状态机，
    协调步骤按钮样式和 PipelineIndicator 可视化更新。

    用法::

        controller = WorkflowController(session=session, parent=main_window)
        main_window.layout().addWidget(controller.pipeline_indicator)
        controller.update_all_steps(
            session, session.repair_mode, current_page,
            step1_btn, step2_btn, step3_lb, step4_btn, arrow_lb,
            MODE_ADDITIVE, MODE_REPAIRING,
        )
    """

    # ── 信号 ──────────────────────────────────────────────────────
    step_state_changed = Signal(int, str)  # (step_index, StepState.name)
    workflow_ready = Signal()              # 前 4 步全部 DONE，可导出
    export_started = Signal(str)           # 导出格式名称
    export_finished = Signal(str, bool)    # (format_name, success)

    # ── 构造 ──────────────────────────────────────────────────────

    def __init__(
        self,
        parent: Optional[QObject] = None,
        session=None,
        license_manager=None,
        path_manager=None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._license_manager = license_manager
        self._path_manager = path_manager
        self._pipeline_indicator: Optional[PipelineIndicator] = None
        self._step_states: dict[int, StepState] = {
            i: StepState.WAITING for i in range(5)
        }

    # ── PipelineIndicator ─────────────────────────────────────────

    @property
    def pipeline_indicator(self) -> PipelineIndicator:
        """返回 PipelineIndicator 控件实例（延迟创建）。"""
        if self._pipeline_indicator is None:
            self._pipeline_indicator = PipelineIndicator()
        return self._pipeline_indicator

    # ── 状态管理 ──────────────────────────────────────────────────

    def reset(self) -> None:
        """重置所有步骤为 WAITING 状态。"""
        for i in range(5):
            self._step_states[i] = StepState.WAITING
            self.step_state_changed.emit(i, StepState.WAITING.name)
        if self._pipeline_indicator is not None:
            self._pipeline_indicator.reset()

    def set_step_done(self, step: int) -> None:
        """标记步骤为 DONE。"""
        if not (0 <= step < 5):
            return
        self._step_states[step] = StepState.DONE
        self.step_state_changed.emit(step, StepState.DONE.name)
        if self._pipeline_indicator is not None:
            self._pipeline_indicator.set_done(step)
        self._check_workflow_ready()

    def set_step_running(self, step: int) -> None:
        """标记步骤为 ACTIVE（执行中）。"""
        if not (0 <= step < 5):
            return
        self._step_states[step] = StepState.ACTIVE
        self.step_state_changed.emit(step, StepState.ACTIVE.name)
        if self._pipeline_indicator is not None:
            self._pipeline_indicator.set_running(step)

    def set_step_failed(self, step: int) -> None:
        """标记步骤为 FAILED（同时更新 PipelineIndicator 为 failed）。"""
        if not (0 <= step < 5):
            return
        self._step_states[step] = StepState.LOCKED
        self.step_state_changed.emit(step, StepState.LOCKED.name)
        if self._pipeline_indicator is not None:
            self._pipeline_indicator.set_failed(step)

    def mark_running_as_failed(self) -> None:
        """将当前 ACTIVE 步骤标记为 FAILED（委托 PipelineIndicator）。"""
        if self._pipeline_indicator is not None:
            self._pipeline_indicator.mark_running_as_failed()
        # 同步内部状态
        for i, state in self._step_states.items():
            if state == StepState.ACTIVE:
                self._step_states[i] = StepState.LOCKED
                self.step_state_changed.emit(i, StepState.LOCKED.name)
                return

    def get_step_state(self, step: int) -> StepState:
        """获取当前步骤状态。"""
        return self._step_states.get(step, StepState.WAITING)

    def can_export(self) -> bool:
        """检查是否满足导出条件（前 4 步均为 DONE）。"""
        return all(
            self._step_states.get(i) == StepState.DONE
            for i in range(4)
        )

    def _check_workflow_ready(self) -> None:
        if self.can_export():
            self.workflow_ready.emit()

    # ── 步骤按钮样式 ──────────────────────────────────────────────

    @staticmethod
    def _style_workflow_label(label: QLabel, state: str) -> None:
        """为 QLabel 步骤按钮设置 done / active / locked 样式。"""
        colors = {
            "done": ("#052E2B", "#10B981", "#A7F3D0"),
            "active": ("#172554", "#3B82F6", "#EFF6FF"),
            "locked": ("#111827", "#273449", "#64748B"),
        }
        bg, border, fg = colors.get(state, colors["locked"])
        label.setStyleSheet(
            f"QLabel{{background:{bg};color:{fg};border:1px solid {border};"
            "border-radius:12px;padding:9px 12px;font-size:13px;"
            "font-weight:bold;}}"
        )

    def update_step_button_style(
        self,
        step_index: int,
        label: QLabel | QPushButton,
        repair_mode: str,
        morph_done: bool,
        path_ready: bool,
        current_page: int,
    ) -> None:
        """更新单个步骤按钮的样式和文本。

        Args:
            step_index: 步骤索引 (0=step1, 1=step2, 2=step3, 3=step4)
            label: QLabel 或 QPushButton 控件
            repair_mode: 当前修复模式字符串
            morph_done: 形貌预测是否完成
            path_ready: 路径规划是否就绪
            current_page: 当前页面索引
        """
        if step_index == 0:
            # Step 1: 数据与路径
            if current_page == 0:
                # 当前在路径规划页面
                if path_ready:
                    label.setStyleSheet(_STEP_DONE)
                    label.setText("✓ 01  数据与路径\n路径已生成，可进入预测")
                else:
                    label.setStyleSheet(
                        _STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6")
                    )
                    label.setText("01  数据与路径\n加载点云、选区、生成路径")
            else:
                label.setStyleSheet(_STEP_DONE)
                label.setText("✓ 01  数据与路径\n路径已生成")

        elif step_index == 1:
            # Step 2: 形貌预测（QLabel）
            if current_page == 0:
                if path_ready:
                    self._style_workflow_label(label, "active")
                    label.setText("02  形貌预测\n航点就绪，自动执行中")
                else:
                    self._style_workflow_label(label, "locked")
                    label.setText("02  形貌预测\n等待路径规划输出")
            elif current_page == 1:
                if morph_done:
                    self._style_workflow_label(label, "done")
                    label.setText("✓ 02  形貌预测\n预测已完成")
                else:
                    self._style_workflow_label(label, "active")
                    label.setText("02  形貌预测\n沉积模拟中")
            else:
                self._style_workflow_label(label, "done" if morph_done else "active")
                label.setText(
                    "✓ 02  形貌预测\n预测已完成"
                    if morph_done
                    else "02  形貌预测\n沉积模拟中"
                )

        elif step_index == 2:
            # Step 3: 结果校核（QLabel）
            if morph_done:
                self._style_workflow_label(label, "done")
                label.setText("✓ 03  结果校核\n指标、截面和风险已更新")
            elif path_ready:
                self._style_workflow_label(label, "active")
                label.setText("03  结果校核\n建议先做可行性检查")
            else:
                self._style_workflow_label(label, "locked")
                label.setText("03  结果校核\n等待路径与预测结果")

        elif step_index == 3:
            # Step 4: 输出交付（QPushButton）
            if not path_ready:
                label.setEnabled(False)
                label.setStyleSheet(_STEP_LOCKED)
                label.setText("04  输出交付\n等待路径规划完成")
            elif current_page == 2:
                label.setEnabled(True)
                label.setStyleSheet(
                    _STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6")
                )
                label.setText("04  输出交付\n导出 G-code 与报告")
            elif morph_done:
                label.setEnabled(True)
                label.setStyleSheet(_STEP_DONE)
                label.setText("✓ 04  输出交付\n可导出 G-code 与报告")
            else:
                label.setEnabled(True)
                label.setStyleSheet(
                    _STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6")
                )
                label.setText("04  输出交付\n可导出 G-code 与报告")

    def update_all_steps(
        self,
        session,
        repair_mode: str,
        current_page: int,
        step1_btn: QPushButton,
        step2_btn: QLabel,
        step3_lb: QLabel,
        step4_btn: QPushButton,
        arrow_lb: QLabel,
        mode_additive: str,
        mode_repairing: str,
        lb_mode_state: Optional[QLabel] = None,
    ) -> None:
        """更新所有步骤按钮和箭头的样式与文本。

        完全替代 MainWindow._update_step_buttons，逻辑一致但职责更清晰。

        Args:
            session: RepairSession 实例
            repair_mode: 当前修复模式值
            current_page: 当前页面索引 (0=路径, 1=形貌, 2=输出)
            step1_btn: 步骤 1 QPushButton
            step2_btn: 步骤 2 QLabel
            step3_lb: 步骤 3 QLabel
            step4_btn: 步骤 4 QPushButton
            arrow_lb: 步骤 1→2 之间的箭头 QLabel
            mode_additive: 增材模式常量值
            mode_repairing: 修复模式常量值
            lb_mode_state: 可选，模式状态 QLabel
        """
        morph_done = session.morphology.repair_xyz is not None
        path_ready = session.output.path_output_ready

        # 更新 4 个步骤按钮
        self.update_step_button_style(0, step1_btn, repair_mode, morph_done, path_ready, current_page)
        self.update_step_button_style(1, step2_btn, repair_mode, morph_done, path_ready, current_page)
        self.update_step_button_style(2, step3_lb, repair_mode, morph_done, path_ready, current_page)
        self.update_step_button_style(3, step4_btn, repair_mode, morph_done, path_ready, current_page)

        # 更新箭头
        if current_page == 0 and not path_ready:
            arrow_lb.setStyleSheet(_ARROW)
        else:
            arrow_lb.setStyleSheet(_ARROW_READY)

        # 更新模式状态标签
        if lb_mode_state is not None:
            mode_name = "增材模式" if repair_mode == mode_additive else "修复模式"
            lb_mode_state.setText(mode_name)

    def update_workflow_state_text(self, session, lb_workflow_state: QLabel) -> None:
        """根据会话状态更新工作流状态文本标签。

        Args:
            session: RepairSession 实例
            lb_workflow_state: 工作流状态 QLabel
        """
        morph_done = session.morphology.repair_xyz is not None
        path_ready = session.output.path_output_ready

        if session.is_busy:
            lb_workflow_state.setText("计算中")
        elif morph_done:
            lb_workflow_state.setText("交付就绪")
        elif path_ready:
            lb_workflow_state.setText("等待形貌预测")
        elif session.point_cloud.xyz is not None:
            lb_workflow_state.setText("等待选区/路径")
        else:
            lb_workflow_state.setText("等待数据")