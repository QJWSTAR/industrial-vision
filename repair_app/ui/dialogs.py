"""
dialogs.py — 统一对话框组件
MF-2: LoadingDialog — MATLAB 启动进度对话框（Progress / Cancel / Timeout）
MF-4: ErrorDialog   — 统一错误提示（发生了什么 / 为什么 / 如何解决 / 日志展开）
"""

from __future__ import annotations
import traceback
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame, QMessageBox, QApplication,
    QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QListWidget,
    QGroupBox, QGridLayout, QFileDialog,
)
from PySide6.QtGui import QFont, QIcon

from repair_app.utils.logger_config import error as log_error, info as log_info
from repair_app.ui.toast import Toast
from repair_app.config import schema_loader as _schema
from repair_app.utils.error_manager import ErrorCode, ErrorManager
from repair_app.ui.theme_manager import ThemeManager

# ============================================================
# 模块常量（避免 Magic Number 散落）
# ============================================================
# 对话框最小宽度
DIALOG_MIN_WIDTH_ERROR = 520  # ErrorDialog
DIALOG_MIN_WIDTH_LOADING = 460  # LoadingDialog
DIALOG_MIN_WIDTH_ROBOT = 420  # RobotExportDialog
DIALOG_MIN_WIDTH_CALIBRATION = 520  # CalibrationDialog
DIALOG_MIN_WIDTH_COORD = 420  # CoordinateSystemDialog
DIALOG_MIN_WIDTH_PRESET = 520  # ParameterPresetDialog
DIALOG_MIN_WIDTH_BATCH = 560  # BatchValidationDialog
DIALOG_MIN_WIDTH_VALIDATOR = 560  # ParameterValidatorDialog
DIALOG_MIN_WIDTH_LICENSE = 480  # LicenseActivationDialog
DIALOG_FIXED_HEIGHT_LICENSE = 340  # LicenseActivationDialog 固定高度

# 通用布局参数
DIALOG_LAYOUT_MARGIN_H = 20  # 对话框左右内边距
DIALOG_LAYOUT_MARGIN_V_TOP = 18  # 对话框上内边距
DIALOG_LAYOUT_MARGIN_V_BOTTOM = 16  # 对话框下内边距
DIALOG_LAYOUT_SPACING = 12  # 对话框主布局间距
DIALOG_LAYOUT_SPACING_TIGHT = 10  # 紧凑布局间距
GRID_LAYOUT_SPACING = 6  # 网格布局间距

# 按钮
DIALOG_BTN_MIN_WIDTH = 90  # 普通按钮最小宽度
DIALOG_BTN_MIN_WIDTH_MEDIUM = 100  # 中等按钮最小宽度
DIALOG_BTN_MIN_WIDTH_LONG = 120  # 较长按钮最小宽度
DIALOG_BTN_MIN_WIDTH_EXTRALONG = 130  # 长按钮最小宽度
DIALOG_BTN_MIN_WIDTH_CALIBRATION_SAVE = 160  # 标定保存按钮
DIALOG_BTN_PADDING_H = 16  # 按钮左右内边距
DIALOG_BTN_PADDING_V = 8  # 按钮上下内边距

# 字号
DIALOG_TITLE_FONT_SIZE_PX = 15  # 对话框标题字号
DIALOG_H1_FONT_SIZE_PX = 16  # 一级标题字号（ErrorDialog 标题）
DIALOG_DESC_FONT_SIZE_PX = 12  # 描述文字字号
DIALOG_LABEL_FONT_SIZE_PX = 11  # 小标签字号
DIALOG_LOG_FONT_SIZE_PX = 11  # 日志字号
DIALOG_ICON_FONT_SIZE_PX = 28  # 图标字号

# 颜色 / 圆角
DIALOG_BORDER_RADIUS_PX = 4  # 圆角半径
DIALOG_LEFT_BORDER_WIDTH_PX = 3  # 左侧色条宽度
DIALOG_GROUP_BOX_MARGIN_TOP_PX = 8  # GroupBox 顶部外边距
DIALOG_GROUP_BOX_PADDING_TOP_PX = 8  # GroupBox 顶部内边距
DIALOG_GROUP_BOX_PADDING_TOP_LICENSE_PX = 12  # License GroupBox 顶部内边距

# 计时器
LOADING_DIALOG_TICK_MS = 1000  # LoadingDialog 倒计时定时器间隔

# 日志 / 列表
DIALOG_LOG_VIEW_MAX_HEIGHT_PX = 160  # 日志视图最大高度
PRESET_LIST_MIN_HEIGHT_PX = 160  # 预设列表最小高度
BATCH_INPUT_MIN_HEIGHT_PX = 180  # 批量输入区最小高度
BATCH_RESULT_MIN_HEIGHT_PX = 120  # 批量结果区最小高度
VALIDATOR_RESULT_MIN_HEIGHT_PX = 280  # 校验器结果区最小高度

# 进度条
LOADING_PROG_MIN_HEIGHT_PX = 22  # LoadingDialog 进度条最小高度

# SpinBox
CALIBRATION_SPIN_MIN_WIDTH_PX = 100  # 标定对话框 SpinBox 最小宽度
LICENSE_IMPORT_BTN_MIN_HEIGHT_PX = 36  # License 导入按钮最小高度


# ============================================================
# MF-4: 统一 Error Dialog（ErrorCode 驱动）
# ============================================================
class ErrorDialog(QDialog):
    """统一错误提示对话框（ErrorCode 驱动）。

    用户看到的三段式信息：
      - 发生了什么（What）
      - 为什么发生（Why）
      - 如何解决（How）

    底部可展开"技术日志"区域，供技术员排查（默认折叠）。

    可通过两种方式构造：
    1. 显式传 what/why/how
    2. 传 ErrorCode + exc，由 ErrorManager.get_friendly_message 自动生成
    """

    def __init__(
        self,
        parent=None,
        title: str = "操作失败",
        what: str = "",
        why: str = "",
        how: str = "",
        log_text: str = "",
        code: Optional[ErrorCode] = None,
        exc: Optional[Exception] = None,
        context: str = "",
    ) -> None:
        # 若提供 code + exc，则通过 ErrorManager 自动生成友好消息
        if code is not None and exc is not None:
            friendly = ErrorManager.get_friendly_message(exc, code, context)
            if not title or title == "操作失败":
                title = friendly.title
            if not what:
                what = friendly.what
            if not why:
                why = friendly.why
            if not how:
                how = friendly.how
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(DIALOG_MIN_WIDTH_ERROR)
        self.setModal(True)

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP,
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM,
        )
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        # 标题行（图标 + 标题）
        head = QHBoxLayout()
        icon_lb = QLabel("⚠")
        icon_lb.setStyleSheet(f"font-size:{DIALOG_ICON_FONT_SIZE_PX}px; color:{p.error};")
        head.addWidget(icon_lb)
        title_lb = QLabel(title)
        title_lb.setStyleSheet(f"font-size:{DIALOG_H1_FONT_SIZE_PX}px; font-weight:bold; color:{p.error_bg};")
        head.addWidget(title_lb)
        head.addStretch()
        layout.addLayout(head)

        # 三段式信息
        if what:
            layout.addWidget(self._section("发生了什么", what, p.error))
        if why:
            layout.addWidget(self._section("为什么", why, p.warning))
        if how:
            layout.addWidget(self._section("如何解决", how, p.success))

        # 技术日志（可展开）
        if log_text:
            log_frame = QFrame()
            log_frame.setStyleSheet(
                f"QFrame{{background:{p.bg_panel}; border:1px solid {p.border_strong}; border-radius:4px;}}"
            )
            log_layout = QVBoxLayout(log_frame)
            log_layout.setContentsMargins(8, 6, 8, 6)
            log_layout.setSpacing(4)

            toggle_btn = QPushButton("▸ 展开技术日志（供技术员排查）")
            toggle_btn.setFlat(True)
            toggle_btn.setStyleSheet(
                f"QPushButton{{color:{p.text_muted}; text-align:left; padding:2px;}}"
                f"QPushButton:hover{{color:{p.text_secondary};}}"
            )
            log_layout.addWidget(toggle_btn)

            self._log_view = QTextEdit()
            self._log_view.setReadOnly(True)
            self._log_view.setPlainText(log_text)
            self._log_view.setStyleSheet(
                f"QTextEdit{{background:{p.bg_input}; color:{p.accent_pale}; "
                f"font-family:Consolas, 'Courier New', monospace; font-size:{DIALOG_LOG_FONT_SIZE_PX}px; "
                "border:none;}}"
            )
            self._log_view.setMaximumHeight(DIALOG_LOG_VIEW_MAX_HEIGHT_PX)
            self._log_view.setVisible(False)
            log_layout.addWidget(self._log_view)

            toggle_btn.clicked.connect(
                lambda: self._toggle_log(toggle_btn, self._log_view)
            )
            layout.addWidget(log_frame)

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("知道了")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}}")

    def _section(self, heading: str, body: str, color: str) -> QFrame:
        p = ThemeManager.get_palette()
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{p.bg_panel}; border-left:{DIALOG_LEFT_BORDER_WIDTH_PX}px solid {color}; "
            f"border-radius:3px;}}"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.setSpacing(2)
        h = QLabel(heading)
        h.setStyleSheet(f"color:{color}; font-size:{DIALOG_LABEL_FONT_SIZE_PX}px; font-weight:bold;")
        fl.addWidget(h)
        b = QLabel(body)
        b.setStyleSheet(f"color:{p.text_body}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        b.setWordWrap(True)
        fl.addWidget(b)
        return frame

    def _toggle_log(self, btn: QPushButton, view: QTextEdit) -> None:
        if view.isVisible():
            view.setVisible(False)
            btn.setText("▸ 展开技术日志（供技术员排查）")
        else:
            view.setVisible(True)
            btn.setText("▾ 收起技术日志")

    @staticmethod
    def show(
        parent=None,
        title: str = "操作失败",
        what: str = "",
        why: str = "",
        how: str = "",
        exc: Optional[Exception] = None,
        code: Optional[ErrorCode] = None,
        context: str = "",
        log_text: str = "",
    ) -> None:
        """便捷调用：自动生成日志文本并弹出对话框。

        优先使用 ErrorManager.handle 统一编排（log → friendly → detail → dialog）。
        若显式传了 what/why/how，则跳过 ErrorManager 自动分类，直接使用传入的文案。
        若显式传了 log_text，则直接使用；否则从 exc 自动生成 traceback 文本。
        """
        # 路径 A：显式传 what/why/how，直接用（向后兼容旧调用）
        if what or why or how:
            if not log_text and exc is not None:
                log_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if log_text:
                log_error(f"[ErrorDialog] {title}: {exc or log_text}")
            dlg = ErrorDialog(parent, title=title, what=what, why=why, how=how, log_text=log_text)
            dlg.exec()
            return

        # 路径 B：走 ErrorManager 统一编排（推荐）
        if exc is not None:
            ErrorManager.handle(exc, code, context, parent=parent, show_dialog=True)
            return

        # 路径 C：无异常对象，直接弹出（仅传文案时）
        dlg = ErrorDialog(parent, title=title, what=what, why=why, how=how, log_text=log_text)
        dlg.exec()


# ============================================================
# 兼容层：classify_error（保留以避免破坏旧调用，内部委托给 ErrorManager）
# ============================================================
def classify_error(category: str, exc: Exception) -> dict:
    """将原始异常分类为 {title, what, why, how} 字典。

    已委托给 ErrorManager.get_friendly_message。
    保留此函数仅为向后兼容（main_window._show_error 等旧调用路径）。
    """
    code = ErrorManager.classify(exc, context=category)
    friendly = ErrorManager.get_friendly_message(exc, code, context=category)
    return {
        "title": friendly.title,
        "what": friendly.what,
        "why": friendly.why,
        "how": friendly.how,
    }


# ============================================================
# MF-2: MATLAB Loading Dialog（Progress / Cancel / Timeout）
# ============================================================
class _EnsureReadyWorker(QThread):
    """后台执行 ensure_ready 任务。

    支持两种输入：
    - callable（返回 bool）：直接调用
    - 带 ensure_ready() 方法的对象（如 MatlabLifecycleManager）：调用 .ensure_ready()
    """
    finished_ok = Signal(bool)
    finished_msg = Signal(str)

    def __init__(self, task) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            if callable(self._task):
                ok = self._task()
                self.finished_ok.emit(ok)
            else:
                ok = self._task.ensure_ready()
                self.finished_ok.emit(ok)
                self.finished_msg.emit(getattr(self._task, "message", ""))
        except Exception as exc:
            log_error(f"ensure_ready worker 异常: {exc}")
            self.finished_ok.emit(False)
            self.finished_msg.emit(str(exc))


class LoadingDialog(QDialog):
    """MATLAB 启动进度对话框。

    特性：
      - 不确定进度条（MATLAB 启动时间难以精确预估）
      - Cancel 按钮（点击后中止等待，返回失败）
      - Timeout 计时器（默认 180 秒自动失败）
      - 实时状态文字更新
    """

    def __init__(
        self,
        parent=None,
        title: str = "正在启动 MATLAB",
        timeout_sec: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(DIALOG_MIN_WIDTH_LOADING)
        self.setModal(True)
        self._cancelled = False
        # 从 schema 读取默认超时（network_parameters.matlab_loading_timeout_sec）
        if timeout_sec is None:
            from repair_app.config import schema_loader as _sl
            timeout_sec = int(_sl.get_network_value("matlab_loading_timeout_sec"))
        self._timeout_sec = timeout_sec
        self._elapsed = 0

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP,
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM,
        )
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        # 标题
        title_lb = QLabel("🔧 正在启动 MATLAB + Bridge 服务")
        title_lb.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title_lb)

        # 状态文字
        self._status_lb = QLabel("正在检测 MATLAB 安装并启动桥接服务...\n预计需要 60-120 秒，请耐心等待。")
        self._status_lb.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        self._status_lb.setWordWrap(True)
        layout.addWidget(self._status_lb)

        # 进度条（不确定模式）
        self._prog = QProgressBar()
        self._prog.setMinimum(0)
        self._prog.setMaximum(0)  # 不确定模式（滚动动画）
        self._prog.setMinimumHeight(LOADING_PROG_MIN_HEIGHT_PX)
        self._prog.setTextVisible(False)
        layout.addWidget(self._prog)

        # 倒计时
        self._countdown_lb = QLabel(f"剩余等待时间：{timeout_sec} 秒")
        self._countdown_lb.setStyleSheet(f"color:{p.text_disabled}; font-size:{DIALOG_LABEL_FONT_SIZE_PX}px;")
        layout.addWidget(self._countdown_lb)

        # 取消按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        self._cancel_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}}")

        # 超时计时器（每秒更新）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        # 结果
        self._result_ok: bool = False
        self._result_msg: str = ""

    def start(self, task) -> None:
        """启动后台 ensure_ready 任务并开始计时。

        task 可以是：
        - callable（返回 bool）：直接调用
        - 带 ensure_ready() 方法的对象：调用 .ensure_ready()
        """
        self._worker = _EnsureReadyWorker(task)
        self._worker.finished_ok.connect(self._on_worker_ok)
        self._worker.finished_msg.connect(self._on_worker_msg)
        self._worker.start()
        self._timer.start(LOADING_DIALOG_TICK_MS)

    def _on_tick(self) -> None:
        self._elapsed += 1
        remaining = max(0, self._timeout_sec - self._elapsed)
        self._countdown_lb.setText(f"剩余等待时间：{remaining} 秒")
        # 滚动状态文字（给用户反馈"还在工作"）
        dots = "." * ((self._elapsed % 3) + 1)
        if remaining > 0:
            self._status_lb.setText(
                f"正在启动 MATLAB + Bridge 服务{dots}\n"
                f"预计需要 60-120 秒，请耐心等待。"
            )
        if self._elapsed >= self._timeout_sec:
            self._on_timeout()

    def _on_worker_ok(self, ok: bool) -> None:
        if self._cancelled:
            return
        self._result_ok = ok
        self._timer.stop()
        self.accept()

    def _on_worker_msg(self, msg: str) -> None:
        self._result_msg = msg

    def _on_cancel(self) -> None:
        self._cancelled = True
        self._timer.stop()
        self._result_ok = False
        self._result_msg = "用户取消了 MATLAB 启动"
        log_info("用户取消了 MATLAB 启动等待")
        # P3-5: 停止后台 worker，非阻塞方式（requestInterruption 后立即 reject）
        # worker 作为 daemon 线程会在后台自行退出，避免 UI 阻塞最多 3 秒
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.requestInterruption()
        self.reject()

    def _on_timeout(self) -> None:
        self._timer.stop()
        self._result_ok = False
        self._result_msg = f"MATLAB 启动超时（等待 {self._timeout_sec} 秒未就绪）"
        log_error(self._result_msg)
        self.reject()

    @property
    def result_ok(self) -> bool:
        return self._result_ok

    @property
    def result_msg(self) -> str:
        return self._result_msg

    @property
    def cancelled(self) -> bool:
        return self._cancelled


# ============================================================
# MF-UI-1: Robot Export Dialog（工业机器人指令导出）
# ============================================================
class RobotExportDialog(QDialog):
    """工业机器人轨迹导出对话框。

    Backend: repair_app/export/robot_exporter.py — RobotExporter
    支持 KUKA KRL / ABB Rapid 两种格式。
    """

    def __init__(self, parent=None, waypoints=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出工业机器人轨迹")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_ROBOT)
        self._waypoints = waypoints
        self._result_path = ""

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP,
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM,
        )
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        title = QLabel("🤖 工业机器人轨迹导出")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("将修复航点转换为 KUKA KRL 或 ABB Rapid 机器人指令文件。")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 机器人类型
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("机器人类型:"))
        self._cb_type = QComboBox()
        self._cb_type.addItem("KUKA (KRL)", "kuka")
        self._cb_type.addItem("ABB (Rapid)", "abb")
        self._cb_type.setToolTip("选择目标机器人品牌。KUKA 使用 KRL 格式，ABB 使用 Rapid 格式。")
        row1.addWidget(self._cb_type)
        row1.addStretch()
        layout.addLayout(row1)

        # TCP 速度（schema: ui_parameters.robot_tcp_speed_ms）
        _tcp = _schema.get_ui_param("robot_tcp_speed_ms")
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("TCP 速度 (m/s):"))
        self._sp_speed = QDoubleSpinBox()
        self._sp_speed.setRange(_tcp["min"], _tcp["max"])
        self._sp_speed.setValue(_tcp["default"])
        self._sp_speed.setSingleStep(_tcp["step"])
        self._sp_speed.setToolTip(_tcp["tooltip"])
        row2.addWidget(self._sp_speed)
        row2.addStretch()
        layout.addLayout(row2)

        # 工具坐标系（schema: ui_parameters.robot_tool_frame）
        _tf = _schema.get_ui_param("robot_tool_frame")
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("工具坐标系编号:"))
        self._sp_tool = QSpinBox()
        self._sp_tool.setRange(int(_tf["min"]), int(_tf["max"]))
        self._sp_tool.setValue(int(_tf["default"]))
        self._sp_tool.setToolTip(_tf["tooltip"])
        row3.addWidget(self._sp_tool)
        row3.addStretch()
        layout.addLayout(row3)

        # 基坐标系（schema: ui_parameters.robot_base_frame）
        _bf = _schema.get_ui_param("robot_base_frame")
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("基坐标系编号:"))
        self._sp_base = QSpinBox()
        self._sp_base.setRange(int(_bf["min"]), int(_bf["max"]))
        self._sp_base.setValue(int(_bf["default"]))
        self._sp_base.setToolTip(_bf["tooltip"])
        row4.addWidget(self._sp_base)
        row4.addStretch()
        layout.addLayout(row4)

        # 逼近精度
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("逼近精度:"))
        self._cb_zone = QComboBox()
        self._cb_zone.addItem("fine (精确停靠)", "fine")
        self._cb_zone.addItem("z10 (±10mm)", "z10")
        self._cb_zone.addItem("z50 (±50mm)", "z50")
        self._cb_zone.setToolTip("运动逼近精度。fine 为精确停靠，z10/z50 为圆弧过渡。")
        row5.addWidget(self._cb_zone)
        row5.addStretch()
        layout.addLayout(row5)

        # 航点状态提示
        self._lb_wp = QLabel()
        self._update_waypoint_status()
        layout.addWidget(self._lb_wp)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        export_btn = QPushButton("导出")
        export_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        export_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}}")

    def _update_waypoint_status(self) -> None:
        p = ThemeManager.get_palette()
        if self._waypoints is not None and len(self._waypoints) > 0:
            self._lb_wp.setText(f"✓ 已加载 {len(self._waypoints)} 个航点")
            self._lb_wp.setStyleSheet(f"color:{p.success}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        else:
            self._lb_wp.setText("⚠ 未加载航点，请先完成路径规划")
            self._lb_wp.setStyleSheet(f"color:{p.warning}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")

    def _on_export(self) -> None:
        if self._waypoints is None or len(self._waypoints) == 0:
            Toast.warning(self, "请先完成路径规划生成航点。")
            return
        default_ext = ".krl" if self._cb_type.currentData() == "kuka" else ".mod"
        fp, _ = QFileDialog.getSaveFileName(
            self, "保存机器人轨迹", f"robot_repair{default_ext}",
            "机器人轨迹文件 (*.krl *.mod);;所有文件 (*)",
        )
        if not fp:
            return
        try:
            from repair_app.export.robot_exporter import RobotExporter, RobotType
            rtype = RobotType.KUKA if self._cb_type.currentData() == "kuka" else RobotType.ABB
            exporter = RobotExporter(
                robot_type=rtype,
                tcp_speed=self._sp_speed.value(),
                tool_frame=self._sp_tool.value(),
                base_frame=self._sp_base.value(),
                zone=self._cb_zone.currentData(),
            )
            exporter.export(self._waypoints, output_path=fp)
            self._result_path = fp
            Toast.success(self, f"机器人轨迹已导出到：\n{fp}")
            self.accept()
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.EXPORT, "机器人轨迹导出")
            ErrorDialog.show(
                self, title=_fm.title,
                what=_fm.what or "无法生成机器人轨迹文件。",
                why=_fm.why,
                how=_fm.how or "1. 确认航点数据有效\n2. 检查输出路径是否有写入权限\n3. 重试",
                exc=exc,
            )

    @property
    def result_path(self) -> str:
        return self._result_path


# ============================================================
# MF-UI-2: Calibration Dialog（单道沉积标定向导）
# ============================================================
class CalibrationDialog(QDialog):
    """单道沉积标定向导对话框。

    Backend: repair_app/utils/calibration_wizard.py — CalibrationWizard
    流程：设置参数 → 录入测量 → 计算修正系数 → 保存。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("单道沉积标定向导")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_CALIBRATION)
        self._wizard = None

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP,
            DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM,
        )
        layout.setSpacing(DIALOG_LAYOUT_SPACING_TIGHT)

        title = QLabel("🎯 单道沉积标定向导")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("通过实际单道喷涂测量结果，计算宽度/高度/效率修正系数，用于提高后续形貌预测精度。")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Step 1: 标定参数（全部从 schema process_parameters 读取，消除双源冲突）
        grp1 = QGroupBox("步骤 1：设置标定参数")
        g1 = QGridLayout(grp1)
        g1.setSpacing(GRID_LAYOUT_SPACING)
        _p = lambda k: _schema.get_process_param(k)
        self._sp_nozzle = self._add_param(g1, 0, "喷嘴直径 (mm):",
            _p("nozzle_diameter_mm")["default"], _p("nozzle_diameter_mm")["min"],
            _p("nozzle_diameter_mm")["max"], _p("nozzle_diameter_mm")["step"])
        self._sp_standoff = self._add_param(g1, 1, "喷涂距离 (mm):",
            _p("standoff_distance_mm")["default"], _p("standoff_distance_mm")["min"],
            _p("standoff_distance_mm")["max"], _p("standoff_distance_mm")["step"])
        self._sp_angle = self._add_param(g1, 2, "喷涂角度 (°):",
            _p("spray_angle_deg")["default"], _p("spray_angle_deg")["min"],
            _p("spray_angle_deg")["max"], _p("spray_angle_deg")["step"])
        self._sp_velocity = self._add_param(g1, 3, "粒子速度 (m/s):",
            _p("particle_velocity_ms")["default"], _p("particle_velocity_ms")["min"],
            _p("particle_velocity_ms")["max"], _p("particle_velocity_ms")["step"])
        self._sp_traverse = self._add_param(g1, 4, "移动速度 (mm/s):",
            _p("traversing_speed_mms")["default"], _p("traversing_speed_mms")["min"],
            _p("traversing_speed_mms")["max"], _p("traversing_speed_mms")["step"])
        self._sp_psize = self._add_param(g1, 5, "粉末粒径 (μm):",
            _p("particle_size_um")["default"], _p("particle_size_um")["min"],
            _p("particle_size_um")["max"], _p("particle_size_um")["step"])
        self._sp_preheat = self._add_param(g1, 6, "预热温度 (°C):",
            _p("preheat_temp_c")["default"], _p("preheat_temp_c")["min"],
            _p("preheat_temp_c")["max"], _p("preheat_temp_c")["step"])
        layout.addWidget(grp1)

        # Step 2: 测量结果（从 schema ui_parameters 读取范围）
        grp2 = QGroupBox("步骤 2：录入测量结果")
        g2 = QGridLayout(grp2)
        g2.setSpacing(GRID_LAYOUT_SPACING)
        _mw = _schema.get_ui_param("calib_measured_width_mm")
        _mh = _schema.get_ui_param("calib_measured_height_mm")
        _me = _schema.get_ui_param("calib_measured_efficiency")
        self._sp_width = self._add_param(g2, 0, "实测沉积宽度 (mm):",
            _mw["default"], _mw["min"], _mw["max"], _mw["step"])
        self._sp_height = self._add_param(g2, 1, "实测沉积高度 (mm):",
            _mh["default"], _mh["min"], _mh["max"], _mh["step"])
        self._sp_eff = self._add_param(g2, 2, "实测沉积效率 (0-1):",
            _me["default"], _me["min"], _me["max"], _me["step"])
        layout.addWidget(grp2)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("计算修正系数并保存")
        save_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_CALIBRATION_SAVE)
        save_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}} QGroupBox{{color:{p.text_secondary}; border:1px solid {p.border_strong}; border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_PX}px;}}")

    def _add_param(self, grid, row, label, default, lo, hi, step):
        grid.addWidget(QLabel(label), row, 0)
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(default)
        sp.setSingleStep(step)
        sp.setMinimumWidth(CALIBRATION_SPIN_MIN_WIDTH_PX)
        grid.addWidget(sp, row, 1)
        return sp

    def _on_save(self) -> None:
        try:
            from repair_app.utils.calibration_wizard import CalibrationWizard
            wz = CalibrationWizard()
            wz.start_calibration(
                material="STEEL_316L",
                nozzle_diameter_mm=self._sp_nozzle.value(),
                standoff_distance_mm=self._sp_standoff.value(),
                spray_angle_deg=self._sp_angle.value(),
                particle_velocity_ms=self._sp_velocity.value(),
                traversing_speed_mms=self._sp_traverse.value(),
                particle_size_um=self._sp_psize.value(),
                preheat_temp_c=self._sp_preheat.value(),
            )
            wz.record_measurement(
                width_mm=self._sp_width.value(),
                height_mm=self._sp_height.value(),
                deposition_efficiency=self._sp_eff.value() if self._sp_eff.value() > 0 else None,
            )
            ts = wz.save()
            corr = wz.get_correction_factors("STEEL_316L")
            Toast.success(
                self,
                f"标定记录已保存（时间戳：{ts}）。\n\n"
                f"修正系数：\n"
                f"  宽度修正：{corr['width']:.3f}\n"
                f"  高度修正：{corr['height']:.3f}\n"
                f"  效率修正：{corr['efficiency']:.3f}",
            )
            self.accept()
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.FILE, "标定")
            ErrorDialog.show(
                self, title=_fm.title,
                what=_fm.what or "无法保存标定记录。",
                why=_fm.why,
                how=_fm.how or "1. 检查参数是否合理\n2. 确认 config 目录可写\n3. 重试",
                exc=exc,
            )


# ============================================================
# MF-UI-3: Coordinate System Dialog（坐标系变换）
# ============================================================
class CoordinateSystemDialog(QDialog):
    """坐标系变换对话框。

    Backend: repair_app/service/coordination_service.py — CoordinationService
    提供平移/旋转/缩放变换，将点云从测量坐标系转换到加工坐标系。
    """

    def __init__(self, parent=None, points=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("坐标系变换")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_COORD)
        self._points = points
        self._transformed = None

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP, DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM)
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        title = QLabel("📐 坐标系变换")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("将点云从测量坐标系变换到加工坐标系。支持平移、旋转、缩放。")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 平移（schema: ui_parameters.coord_translate_range_mm）
        _tr = _schema.get_ui_param("coord_translate_range_mm")
        grp_t = QGroupBox("平移 (mm)")
        gt = QHBoxLayout(grp_t)
        self._sp_tx = QDoubleSpinBox()
        self._sp_tx.setRange(_tr["min"], _tr["max"]); self._sp_tx.setValue(_tr["default"])
        self._sp_tx.setSingleStep(_tr["step"])
        self._sp_ty = QDoubleSpinBox()
        self._sp_ty.setRange(_tr["min"], _tr["max"]); self._sp_ty.setValue(_tr["default"])
        self._sp_ty.setSingleStep(_tr["step"])
        self._sp_tz = QDoubleSpinBox()
        self._sp_tz.setRange(_tr["min"], _tr["max"]); self._sp_tz.setValue(_tr["default"])
        self._sp_tz.setSingleStep(_tr["step"])
        gt.addWidget(QLabel("X:")); gt.addWidget(self._sp_tx)
        gt.addWidget(QLabel("Y:")); gt.addWidget(self._sp_ty)
        gt.addWidget(QLabel("Z:")); gt.addWidget(self._sp_tz)
        layout.addWidget(grp_t)

        # 旋转（schema: ui_parameters.coord_rotate_range_deg）
        _rr = _schema.get_ui_param("coord_rotate_range_deg")
        grp_r = QGroupBox("旋转 (°)")
        gr = QHBoxLayout(grp_r)
        self._sp_rx = QDoubleSpinBox()
        self._sp_rx.setRange(_rr["min"], _rr["max"]); self._sp_rx.setValue(_rr["default"])
        self._sp_rx.setSingleStep(_rr["step"])
        self._sp_ry = QDoubleSpinBox()
        self._sp_ry.setRange(_rr["min"], _rr["max"]); self._sp_ry.setValue(_rr["default"])
        self._sp_ry.setSingleStep(_rr["step"])
        self._sp_rz = QDoubleSpinBox()
        self._sp_rz.setRange(_rr["min"], _rr["max"]); self._sp_rz.setValue(_rr["default"])
        self._sp_rz.setSingleStep(_rr["step"])
        gr.addWidget(QLabel("绕X:")); gr.addWidget(self._sp_rx)
        gr.addWidget(QLabel("绕Y:")); gr.addWidget(self._sp_ry)
        gr.addWidget(QLabel("绕Z:")); gr.addWidget(self._sp_rz)
        layout.addWidget(grp_r)

        # 缩放（schema: ui_parameters.coord_scale_range）
        _sr = _schema.get_ui_param("coord_scale_range")
        grp_s = QGroupBox("缩放")
        gs = QHBoxLayout(grp_s)
        self._sp_sx = QDoubleSpinBox()
        self._sp_sx.setRange(_sr["min"], _sr["max"]); self._sp_sx.setValue(_sr["default"])
        self._sp_sx.setSingleStep(_sr["step"])
        self._sp_sy = QDoubleSpinBox()
        self._sp_sy.setRange(_sr["min"], _sr["max"]); self._sp_sy.setValue(_sr["default"])
        self._sp_sy.setSingleStep(_sr["step"])
        self._sp_sz = QDoubleSpinBox()
        self._sp_sz.setRange(_sr["min"], _sr["max"]); self._sp_sz.setValue(_sr["default"])
        self._sp_sz.setSingleStep(_sr["step"])
        gs.addWidget(QLabel("X:")); gs.addWidget(self._sp_sx)
        gs.addWidget(QLabel("Y:")); gs.addWidget(self._sp_sy)
        gs.addWidget(QLabel("Z:")); gs.addWidget(self._sp_sz)
        layout.addWidget(grp_s)

        # 点云状态
        self._lb_pc = QLabel()
        self._update_status()
        layout.addWidget(self._lb_pc)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        apply_btn = QPushButton("应用变换")
        apply_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_LONG)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}} QGroupBox{{color:{p.text_secondary}; border:1px solid {p.border_strong}; border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_PX}px;}}")

    def _update_status(self) -> None:
        p = ThemeManager.get_palette()
        if self._points is not None and len(self._points) > 0:
            self._lb_pc.setText(f"✓ 已加载 {len(self._points)} 个点")
            self._lb_pc.setStyleSheet(f"color:{p.success}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        else:
            self._lb_pc.setText("⚠ 未加载点云，请先加载点云文件")
            self._lb_pc.setStyleSheet(f"color:{p.warning}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")

    def _on_apply(self) -> None:
        if self._points is None or len(self._points) == 0:
            Toast.warning(self, "请先加载点云。")
            return
        try:
            import numpy as np
            pts = np.asarray(self._points, dtype=np.float64).copy()
            # 缩放
            pts[:, 0] *= self._sp_sx.value()
            pts[:, 1] *= self._sp_sy.value()
            pts[:, 2] *= self._sp_sz.value()
            # 旋转（角度转弧度）
            rx = np.radians(self._sp_rx.value())
            ry = np.radians(self._sp_ry.value())
            rz = np.radians(self._sp_rz.value())
            # 绕 X 轴
            if rx != 0:
                y2 = pts[:, 1] * np.cos(rx) - pts[:, 2] * np.sin(rx)
                z2 = pts[:, 1] * np.sin(rx) + pts[:, 2] * np.cos(rx)
                pts[:, 1], pts[:, 2] = y2, z2
            # 绕 Y 轴
            if ry != 0:
                x2 = pts[:, 0] * np.cos(ry) + pts[:, 2] * np.sin(ry)
                z2 = -pts[:, 0] * np.sin(ry) + pts[:, 2] * np.cos(ry)
                pts[:, 0], pts[:, 2] = x2, z2
            # 绕 Z 轴
            if rz != 0:
                x2 = pts[:, 0] * np.cos(rz) - pts[:, 1] * np.sin(rz)
                y2 = pts[:, 0] * np.sin(rz) + pts[:, 1] * np.cos(rz)
                pts[:, 0], pts[:, 1] = x2, y2
            # 平移
            pts[:, 0] += self._sp_tx.value()
            pts[:, 1] += self._sp_ty.value()
            pts[:, 2] += self._sp_tz.value()
            self._transformed = pts
            Toast.success(
                self,
                f"坐标系变换已完成。\n变换后点数：{len(pts)}",
            )
            self.accept()
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.MESH, "坐标系变换")
            ErrorDialog.show(
                self, title=_fm.title,
                what=_fm.what or "坐标系变换过程中发生错误。",
                why=_fm.why,
                how=_fm.how or "1. 确认点云数据有效\n2. 检查变换参数\n3. 重试",
                exc=exc,
            )

    @property
    def transformed_points(self):
        return self._transformed


# ============================================================
# MF-UI-4: Parameter Preset Dialog（参数预设管理）
# ============================================================
class ParameterPresetDialog(QDialog):
    """参数预设管理对话框。

    Backend: repair_app/utils/config.py — PARAM_SPECS / PARAM_DEFAULTS
    允许保存/加载/删除参数预设组合（JSON 文件持久化）。
    """

    PRESET_DIR = "param_presets"

    def __init__(self, parent=None, current_params=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("参数预设管理")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_PRESET)
        self._current_params = current_params or {}
        self._result_params = None
        self._pending_delete_item: str | None = None

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP, DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM)
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        title = QLabel("⚙️ 参数预设管理")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("保存当前参数组合为预设，方便下次快速加载。适合不同材料/工艺的常用配置。")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 预设列表
        grp_list = QGroupBox("已保存的预设")
        gl = QVBoxLayout(grp_list)
        self._lst_presets = QListWidget()
        self._lst_presets.setMinimumHeight(PRESET_LIST_MIN_HEIGHT_PX)
        self._lst_presets.setStyleSheet(f"QListWidget{{background:{p.bg_panel}; color:{p.text_body}; border:1px solid {p.border_strong};}}")
        self._lst_presets.itemDoubleClicked.connect(self._on_load)
        gl.addWidget(self._lst_presets)
        self._refresh_list()
        layout.addWidget(grp_list)

        # 保存新预设
        grp_save = QGroupBox("保存新预设")
        gs = QHBoxLayout(grp_save)
        gs.addWidget(QLabel("名称:"))
        self._le_name = QLineEdit()
        self._le_name.setPlaceholderText("例如：316L_标准工艺")
        gs.addWidget(self._le_name)
        save_btn = QPushButton("保存当前参数")
        save_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:6px 12px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        save_btn.clicked.connect(self._on_save)
        gs.addWidget(save_btn)
        layout.addWidget(grp_save)

        # 按钮
        btn_row = QHBoxLayout()
        load_btn = QPushButton("加载选中")
        load_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_MEDIUM)
        load_btn.setStyleSheet(
            f"QPushButton{{background:{p.success}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.success};}}"
        )
        load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(load_btn)
        del_btn = QPushButton("删除选中")
        del_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_MEDIUM)
        del_btn.setStyleSheet(
            f"QPushButton{{background:{p.error}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.error};}}"
        )
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}} QGroupBox{{color:{p.text_secondary}; border:1px solid {p.border_strong}; border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_PX}px;}}")

    def _get_preset_dir(self) -> str:
        import os
        from repair_app.utils.resource_path import get_data_dir
        d = os.path.join(str(get_data_dir()), self.PRESET_DIR)
        os.makedirs(d, exist_ok=True)
        return d

    def _refresh_list(self) -> None:
        import os, json
        self._lst_presets.clear()
        d = self._get_preset_dir()
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                self._lst_presets.addItem(fn[:-5])

    def _on_save(self) -> None:
        import os, json
        name = self._le_name.text().strip()
        if not name:
            Toast.warning(self, "请输入预设名称。")
            return
        fp = os.path.join(self._get_preset_dir(), f"{name}.json")
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(self._current_params, f, indent=2, ensure_ascii=False)
            Toast.success(self, f"预设 '{name}' 已保存。")
            self._refresh_list()
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.FILE, "保存预设")
            ErrorDialog.show(self, title=_fm.title, what=_fm.what or "无法保存预设。",
                             why=_fm.why, how=_fm.how or "检查目录权限后重试。", exc=exc)

    def _on_load(self) -> None:
        import os, json
        item = self._lst_presets.currentItem()
        if not item:
            Toast.warning(self, "请先选择一个预设。")
            return
        fp = os.path.join(self._get_preset_dir(), f"{item.text()}.json")
        try:
            with open(fp, "r", encoding="utf-8") as f:
                self._result_params = json.load(f)
            Toast.success(self, f"预设 '{item.text()}' 已加载，点击关闭应用参数。")
            self.accept()
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.FILE, "加载预设")
            ErrorDialog.show(self, title=_fm.title, what=_fm.what or "无法加载预设。",
                             why=_fm.why, how=_fm.how or "检查文件是否损坏。", exc=exc)

    def _on_delete(self) -> None:
        import os
        item = self._lst_presets.currentItem()
        if not item:
            Toast.warning(self, "请先选择一个预设。")
            return
        item_text = item.text()
        # 二次点击确认（非阻塞，替代 QMessageBox.question）
        if self._pending_delete_item != item_text:
            self._pending_delete_item = item_text
            Toast.warning(self, f"再次点击「删除」以确认移除预设「{item_text}」")
            return
        self._pending_delete_item = None
        fp = os.path.join(self._get_preset_dir(), f"{item_text}.json")
        try:
            os.remove(fp)
            self._refresh_list()
            Toast.success(self, f"预设「{item_text}」已删除")
        except Exception as exc:
            _fm = ErrorManager.get_friendly_message(exc, ErrorCode.FILE, "删除预设")
            ErrorDialog.show(self, title=_fm.title, what=_fm.what or "无法删除预设。",
                             why=_fm.why, how=_fm.how or "检查文件权限。", exc=exc)

    @property
    def result_params(self):
        return self._result_params


# ============================================================
# MF-UI-5: Batch Validation Dialog（批量验证）
# ============================================================
class BatchValidationDialog(QDialog):
    """批量验证对话框。

    Backend: repair_app/service/validation_service.py — ValidationService
    对多个参数组合批量执行可行性检查，输出对比报告。
    """

    def __init__(self, parent=None, base_params=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量验证")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_BATCH)
        self._base_params = base_params or {}

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP, DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM)
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        title = QLabel("🔬 批量验证")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("对多组参数批量执行可行性检查，对比不同参数组合的可行性结果。\n每行一组参数，格式：particle_velocity=500, gas_temperature=800, ...")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 参数输入区
        grp = QGroupBox("参数组合（每行一组）")
        gv = QVBoxLayout(grp)
        self._txt = QTextEdit()
        self._txt.setMinimumHeight(BATCH_INPUT_MIN_HEIGHT_PX)
        self._txt.setStyleSheet(f"QTextEdit{{background:{p.bg_panel}; color:{p.text_body}; border:1px solid {p.border_strong}; font-family:Consolas, monospace; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;}}")
        # 预填基础参数
        if self._base_params:
            import json
            self._txt.setPlainText(json.dumps(self._base_params, indent=2, ensure_ascii=False))
        gv.addWidget(self._txt)
        layout.addWidget(grp)

        # 结果输出区
        self._txt_result = QTextEdit()
        self._txt_result.setReadOnly(True)
        self._txt_result.setMinimumHeight(BATCH_RESULT_MIN_HEIGHT_PX)
        self._txt_result.setStyleSheet(f"QTextEdit{{background:{p.bg_input}; color:{p.success}; border:1px solid {p.border_strong}; font-family:Consolas, monospace; font-size:{DIALOG_LABEL_FONT_SIZE_PX}px;}}")
        self._txt_result.setPlaceholderText("验证结果将显示在这里...")
        layout.addWidget(self._txt_result)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        run_btn = QPushButton("运行批量验证")
        run_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_EXTRALONG)
        run_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(run_btn)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}} QGroupBox{{color:{p.text_secondary}; border:1px solid {p.border_strong}; border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_PX}px;}}")

    def _on_run(self) -> None:
        import json
        text = self._txt.toPlainText().strip()
        if not text:
            Toast.warning(self, "请输入至少一组参数。")
            return
        try:
            # 尝试解析为 JSON（单个 dict 或 list）
            data = json.loads(text)
            if isinstance(data, dict):
                param_sets = [data]
            elif isinstance(data, list):
                param_sets = data
            else:
                raise ValueError("输入必须是 JSON 对象或数组")
        except Exception:
            # 回退：按行解析 key=value 格式
            param_sets = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                params = {}
                for kv in line.split(","):
                    kv = kv.strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        try:
                            params[k.strip()] = float(v.strip())
                        except ValueError:
                            params[k.strip()] = v.strip()
                if params:
                    param_sets.append(params)

        if not param_sets:
            Toast.warning(self, "未解析到任何参数组合。")
            return

        results = []
        for i, params in enumerate(param_sets):
            try:
                from repair_app.service.validation_service import ValidationService
                from repair_app.domain.models import ProcessParams
                svc = ValidationService()
                pp = ProcessParams(**{k: v for k, v in params.items()
                                      if k in ProcessParams.__dataclass_fields__})
                ok, errors = svc.validate_params(pp)
                results.append((i + 1, ok, errors, params))
            except Exception as exc:
                results.append((i + 1, False, [str(exc)], params))

        # 输出结果
        out = []
        out.append("=" * 60)
        out.append(f"批量验证结果（共 {len(results)} 组）")
        out.append("=" * 60)
        for idx, ok, errors, params in results:
            status = "✓ 通过" if ok else "✗ 失败"
            out.append(f"\n[组 {idx}] {status}")
            out.append(f"  参数：{params}")
            if errors:
                for e in errors:
                    out.append(f"  - {e}")
        out.append("\n" + "=" * 60)
        n_pass = sum(1 for _, ok, _, _ in results if ok)
        out.append(f"通过：{n_pass} / {len(results)}")
        self._txt_result.setPlainText("\n".join(out))


# ============================================================
# MF-UI-6: Parameter Validator Dialog（参数校验器）
# ============================================================
class ParameterValidatorDialog(QDialog):
    """参数校验器对话框。

    Backend: repair_app/service/validation_service.py — ValidationService
    实时校验当前 UI 参数是否在合法范围内，显示通过/失败的详细列表。
    """

    def __init__(self, parent=None, current_params=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("参数校验器")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_VALIDATOR)
        self._current_params = current_params or {}

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP, DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM)
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        title = QLabel("✓ 参数校验器")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel("校验当前所有工艺参数是否在合法范围内（基于 PARAM_SPECS 唯一权威源）。")
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 结果区
        self._txt_result = QTextEdit()
        self._txt_result.setReadOnly(True)
        self._txt_result.setMinimumHeight(VALIDATOR_RESULT_MIN_HEIGHT_PX)
        self._txt_result.setStyleSheet(f"QTextEdit{{background:{p.bg_input}; color:{p.text_body}; border:1px solid {p.border_strong}; font-family:Consolas, monospace; font-size:{DIALOG_LABEL_FONT_SIZE_PX}px;}}")
        layout.addWidget(self._txt_result)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        check_btn = QPushButton("立即校验")
        check_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH_LONG)
        check_btn.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        check_btn.clicked.connect(self._on_check)
        btn_row.addWidget(check_btn)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(DIALOG_BTN_MIN_WIDTH)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{p.border_strong}; color:{p.text_primary}; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"QDialog{{background:{p.bg_hover};}} QLabel{{color:{p.text_body};}}")

        # 首次自动校验
        self._on_check()

    def _on_check(self) -> None:
        from repair_app.utils.config import PARAM_BOUNDS, PARAM_SPECS
        from repair_app.service.validation_service import ValidationService
        from repair_app.domain.models import ProcessParams

        lines = ["=" * 60, "参数校验报告", "=" * 60, ""]

        if not self._current_params:
            lines.append("⚠ 未获取到参数，请先在主界面设置参数。")
            self._txt_result.setPlainText("\n".join(lines))
            return

        # 逐项检查范围
        all_ok = True
        lines.append(f"{'参数名':<30} {'当前值':>12} {'范围':>20} {'状态':>6}")
        lines.append("-" * 72)
        for key, (lo, hi) in PARAM_BOUNDS.items():
            val = self._current_params.get(key)
            if val is None:
                # 尝试从 UI short key 推断
                for ui_key in ["layer_height", "scanning_angle", "scanning_step",
                               "edge_step_size", "tilt_angle", "buffer_additive",
                               "buffer_repairing", "link_free_dist", "obstacle_resolution",
                               "particle_velocity", "critical_velocity", "nozzle_diameter",
                               "spray_angle", "standoff_distance", "particle_size",
                               "gas_temperature", "gas_pressure", "powder_feed_rate",
                               "traversing_speed"]:
                    ui_to_spec = {
                        "layer_height": "layer_height_mm",
                        "scanning_angle": "scanning_angle_deg",
                        "scanning_step": "scanning_step_mm",
                        "edge_step_size": "edge_step_size_mm",
                        "tilt_angle": "tilt_angle_deg",
                        "buffer_additive": "buffer_additive_mm",
                        "buffer_repairing": "buffer_repairing_mm",
                        "link_free_dist": "link_free_dist_mm",
                        "obstacle_resolution": "obstacle_resolution_mm",
                        "particle_velocity": "particle_velocity_ms",
                        "critical_velocity": "critical_velocity_ms",
                        "nozzle_diameter": "nozzle_diameter_mm",
                        "spray_angle": "spray_angle_deg",
                        "standoff_distance": "standoff_distance_mm",
                        "particle_size": "particle_size_um",
                        "gas_temperature": "gas_temperature_c",
                        "gas_pressure": "gas_pressure_bar",
                        "powder_feed_rate": "powder_feed_rate_gmin",
                        "traversing_speed": "traversing_speed_mms",
                    }
                    if ui_to_spec.get(ui_key) == key:
                        val = self._current_params.get(ui_key)
                        break
            if val is None:
                lines.append(f"{key:<30} {'N/A':>12} [{lo}, {hi}] {'—':>6}")
                continue
            ok = lo <= val <= hi
            if not ok:
                all_ok = False
            status = "✓" if ok else "✗"
            lines.append(f"{key:<30} {val:>12.3f} [{lo}, {hi}] {status:>6}")

        lines.append("-" * 72)
        lines.append(f"\n总结：{'✓ 所有参数在合法范围内' if all_ok else '✗ 存在参数超出范围，请修正'}")

        self._txt_result.setPlainText("\n".join(lines))


# ============================================================
# License 激活对话框
# ============================================================
class LicenseActivationDialog(QDialog):
    """License 激活对话框。

    显示本机机器码，支持复制机器码和导入 license.key 文件。
    终端用户获取机器码后发送给管理员，管理员签发 license.key，
    用户通过本对话框导入即可激活软件。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("License 激活")
        self.setMinimumWidth(DIALOG_MIN_WIDTH_LICENSE)
        self.setFixedHeight(DIALOG_FIXED_HEIGHT_LICENSE)

        p = ThemeManager.get_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_TOP, DIALOG_LAYOUT_MARGIN_H, DIALOG_LAYOUT_MARGIN_V_BOTTOM)
        layout.setSpacing(DIALOG_LAYOUT_SPACING)

        # 标题
        title = QLabel("License 激活")
        title.setStyleSheet(f"font-size:{DIALOG_TITLE_FONT_SIZE_PX}px; font-weight:bold; color:{p.text_body};")
        layout.addWidget(title)

        desc = QLabel(
            "请将本机机器码发送给管理员以获取 License 文件。\n"
            "收到 license.key 后，点击下方按钮导入即可激活软件。"
        )
        desc.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 机器码显示
        grp_mid = QGroupBox("本机机器码")
        grp_mid.setStyleSheet(
            f"QGroupBox{{color:{p.text_body}; font-weight:bold; border:1px solid {p.border_strong};"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_LICENSE_PX}px;}}"
            f"QGroupBox::title{{subcontrol-origin:margin; left:10px; padding:0 4px;}}"
        )
        gl = QVBoxLayout(grp_mid)
        gl.setContentsMargins(12, 16, 12, 12)

        from repair_app.utils.license_manager import get_machine_id
        mid = get_machine_id()

        self._le_mid = QLineEdit(mid)
        self._le_mid.setReadOnly(True)
        self._le_mid.setStyleSheet(
            f"QLineEdit{{background:{p.bg_panel}; color:{p.accent};"
            f"border:1px solid {p.border_strong}; border-radius:{DIALOG_BORDER_RADIUS_PX}px;"
            "padding:6px 10px; font-family:Consolas,monospace; font-size:13px;"
            f"selection-background-color:{p.accent};}}"
        )
        gl.addWidget(self._le_mid)

        btn_copy = QPushButton("复制机器码")
        btn_copy.setStyleSheet(
            f"QPushButton{{background:{p.accent}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:5px 12px; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;}}"
            f"QPushButton:hover{{background:{p.accent_hover};}}"
        )
        btn_copy.clicked.connect(self._on_copy_machine_id)
        gl.addWidget(btn_copy)

        layout.addWidget(grp_mid)

        # 导入 License
        grp_import = QGroupBox("导入 License 文件")
        grp_import.setStyleSheet(
            f"QGroupBox{{color:{p.text_body}; font-weight:bold; border:1px solid {p.border_strong};"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; margin-top:{DIALOG_GROUP_BOX_MARGIN_TOP_PX}px; padding-top:{DIALOG_GROUP_BOX_PADDING_TOP_LICENSE_PX}px;}}"
            f"QGroupBox::title{{subcontrol-origin:margin; left:10px; padding:0 4px;}}"
        )
        gi = QHBoxLayout(grp_import)
        gi.setContentsMargins(12, 16, 12, 12)

        btn_import = QPushButton("选择并导入 license.key...")
        btn_import.setMinimumHeight(LICENSE_IMPORT_BTN_MIN_HEIGHT_PX)
        btn_import.setStyleSheet(
            f"QPushButton{{background:{p.success}; color:#FFFFFF; border:none;"
            f"border-radius:{DIALOG_BORDER_RADIUS_PX}px; padding:{DIALOG_BTN_PADDING_V}px {DIALOG_BTN_PADDING_H}px; font-weight:bold; font-size:13px;}}"
            f"QPushButton:hover{{background:{p.success};}}"
        )
        btn_import.clicked.connect(self._on_import_license)
        gi.addWidget(btn_import)

        layout.addWidget(grp_import)

        # 状态提示
        self._lb_status = QLabel("")
        self._lb_status.setStyleSheet(f"color:{p.text_muted}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        self._lb_status.setWordWrap(True)
        layout.addWidget(self._lb_status)

        layout.addStretch()

    def _on_copy_machine_id(self) -> None:
        """复制机器码到剪贴板。"""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._le_mid.text())
        p = ThemeManager.get_palette()
        self._lb_status.setStyleSheet(f"color:{p.success}; font-size:{DIALOG_DESC_FONT_SIZE_PX}px;")
        self._lb_status.setText("机器码已复制到剪贴板")

    def _on_import_license(self) -> None:
        """选择并导入 license.key 文件。"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from repair_app.utils.license_manager import install_license

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 License 文件", "",
            "License 文件 (license.key);;所有文件 (*.*)",
        )
        if not file_path:
            return

        p = ThemeManager.get_palette()
        success, msg = install_license(file_path)

        if success:
            self._lb_status.setStyleSheet(
                f"color:{p.success}; font-size:13px; font-weight:bold;"
            )
            self._lb_status.setText(f"✅ {msg}\n请重启软件以应用新 License。")
            Toast.success(
                self,
                f"License 已成功安装。\n\n{msg}\n\n请重启软件以完成激活。",
            )
        else:
            self._lb_status.setStyleSheet(
                f"color:{p.error}; font-size:13px; font-weight:bold;"
            )
            self._lb_status.setText(f"❌ {msg}")
