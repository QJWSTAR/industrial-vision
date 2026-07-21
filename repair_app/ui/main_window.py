"""
main_window.py — 冷喷涂缺陷修复软件主界面
v0.10: 三面板可视化 + 增材/修复双模式 + 气体参数
"""

from __future__ import annotations
import os, sys
from typing import Optional
import numpy as np

from repair_app.utils.resource_path import get_data_dir
os.environ.setdefault("MPLCONFIGDIR", os.path.join(str(get_data_dir()), ".matplotlib_cache"))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QComboBox,
    QProgressBar, QGroupBox, QStatusBar, QFrame,
    QFileDialog, QMessageBox, QApplication, QTabWidget, QTextEdit,
    QStackedWidget, QCheckBox, QSplitter, QRadioButton, QButtonGroup,
    QSlider, QSizePolicy, QToolBar, QMenu,
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QSize
from PySide6.QtGui import QPixmap, QAction, QKeySequence

# H1-H3 修复：UI 层通过 CoordinationService 访问 core/communication 模块
from repair_app.service.coordination_service import CoordinationService as _Coord
from repair_app.ui.defect_selector import DefectSelector
from repair_app.ui.repair_visualizer import RepairVisualizer
from repair_app.ui.profile_result_panel import ProfileResultPanel
from repair_app.ui.dialogs import ErrorDialog, classify_error
from repair_app.utils.error_manager import ErrorManager, ErrorCode
from repair_app.ui.dialogs import (
    RobotExportDialog, CalibrationDialog, CoordinateSystemDialog,
    ParameterPresetDialog, BatchValidationDialog, ParameterValidatorDialog,
)
from repair_app.ui.theme_manager import ThemeManager
from repair_app.ui.toast import Toast
from repair_app.ui.busy_indicator import BusyLabel
from repair_app.ui.context_menu import ContextMenuManager
from repair_app.ui.undo_framework import UndoStack

_ZMQ_AVAILABLE = _Coord().zmq_available

from repair_app.utils.license_manager import LicenseManager
from repair_app.utils.app_config import AppConfig
from repair_app.utils.logger_config import setup_logging, info, warning, error as log_error
from repair_app.service import ExportService
from repair_app.export.pipeline import ExporterRegistry, ExportResult
from repair_app.export import builtin_exporters  # noqa: F401 — 触发注册
from repair_app.service.file_service import FileService
from repair_app.utils.calibration_wizard import CalibrationWizard
from repair_app.ui.workers import PathPlanningWorker, MorphologyWorker
from repair_app.core.repair_session import RepairSession
from repair_app.utils.config import (
    APP_TITLE, MATERIALS, MAT_KEY_MAP, window as _win_cfg, mode as _mode_cfg,
    page as _page_cfg, style as _style_cfg,
    get_morph_dir, get_pointlist_file, get_velocitylist_file, get_p1_frame_dir,
    get_ui_param, UI_PARAM_SPECS,
)
from repair_app.config import schema_loader
from repair_app import __version__ as APP_VERSION

_TITLE = APP_TITLE
# Developer Mode 标识：标题栏追加醒目标记，便于区分正式版与开发版
if AppConfig.is_developer_mode():
    _TITLE = f"{APP_TITLE}  【Developer Build】"
_LW, _RW = _win_cfg.left_panel_width, _win_cfg.right_panel_width
_WINDOW_W, _WINDOW_H = _win_cfg.window_width, _win_cfg.window_height

_MATERIALS = MATERIALS
_MAT_KEY_MAP = MAT_KEY_MAP

_PROTO_MATERIAL_MAP = _Coord().proto_material_map


# 修复模式
MODE_ADDITIVE  = _mode_cfg.additive   # 增材模式
MODE_REPAIRING = _mode_cfg.repairing  # 修复模式

_MORPH_DIR = get_morph_dir()
_POINTLIST_FILE = get_pointlist_file()
_VELOCITYLIST_FILE = get_velocitylist_file()
_P1_FRAME_DIR = get_p1_frame_dir()

PAGE_PATH = _page_cfg.path
PAGE_MORPH = _page_cfg.morph
PAGE_OUTPUT = _page_cfg.output

# ===== 错误消息友好化（任务K: 委托给 ErrorManager 统一编排） =====
def _friendly_error(category: str, exc: Exception) -> str:
    """将原始异常翻译为用户可理解的友好消息（兼容旧调用）。

    已委托给 ErrorManager.get_friendly_message。
    """
    code = ErrorManager.classify(exc, context=category)
    friendly = ErrorManager.get_friendly_message(exc, code, context=category)
    return f"{friendly.title}\n\n{friendly.what}"


def _show_error(parent, category: str, exc: Exception) -> None:
    """统一错误对话框 — 用户只看到 发生了什么/为什么/如何解决，日志单独展开。

    已委托给 ErrorManager.handle（统一编排：log → friendly → detail → dialog）。
    """
    # 自动分类 + 显示对话框 + 记录日志
    ErrorManager.handle(exc, context=category, parent=parent, show_dialog=True)

# ===== 通信地址与线程等待常量（从 schema 读取，禁止硬编码）=====
_BRIDGE_ADDRESS = schema_loader.get_network_value("zmq_default_address")
_PROGRESS_ADDRESS = schema_loader.get_network_value("zmq_progress_address")
_THREAD_WAIT_MS = int(schema_loader.get_network_value("thread_wait_ms"))
_THREAD_TERMINATE_WAIT_MS = int(schema_loader.get_network_value("thread_terminate_wait_ms"))

# ===== 工业级主题（从 ThemeManager 读取，禁止硬编码 QSS） =====
# 原 _DARK_THEME_QSS 已由 ThemeManager.get_qss() 替代。
# 调色板 / 排版 / 间距 / 圆角 等设计 token 全部集中在 ThemeManager。
# 颜色值硬编码的魔法字符串已消除，改色只需修改 theme_manager.py。

# 步骤按钮样式（保留，从 config.style 读取）
_STEP_ACTIVE = _style_cfg.active
_STEP_DONE = _style_cfg.done
_STEP_LOCKED = _style_cfg.locked
_ARROW = _style_cfg.arrow_normal
_ARROW_READY = _style_cfg.arrow_ready


def _list_p1_frame_paths() -> list[str]:
    """Return MATLAB-exported P1 JPG frames in numeric order."""
    if not os.path.isdir(_P1_FRAME_DIR):
        return []

    def _frame_no(path: str) -> tuple[int, str]:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            return int(name), path
        except ValueError:
            return 10**9, path

    paths = [
        os.path.join(_P1_FRAME_DIR, name)
        for name in os.listdir(_P1_FRAME_DIR)
        if name.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    return [p for _, p in sorted(_frame_no(p) for p in paths)]


class P1FramePlayer(QWidget):
    """MATLAB P1 composite-frame player for demonstration mode."""

    def __init__(self, frame_dir: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_dir = frame_dir
        self._paths: list[str] = []
        self._idx = 0
        self._current_pixmap: QPixmap | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("P1Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("P1 三视图形貌预测动画")
        title.setStyleSheet("color:#F8FAFC;font-size:16px;font-weight:700;")
        subtitle = QLabel("MATLAB 中间帧演示：喷嘴/射线、TCP 路径、沉积形貌色温图同步播放")
        subtitle.setStyleSheet("color:#94A3B8;font-size:12px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hl.addLayout(title_box, 1)

        self._lb_status = QLabel("未加载")
        self._lb_status.setStyleSheet(
            "background:#111827;color:#BFDBFE;border:1px solid #1E3A8A;"
            "border-radius:12px;padding:6px 10px;font-weight:600;"
        )
        hl.addWidget(self._lb_status)
        layout.addWidget(header)

        self._image = QLabel()
        self._image.setObjectName("P1Image")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(640, 360)
        self._image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image.setStyleSheet(
            "QLabel#P1Image{background:#020617;border:1px solid #1E293B;"
            "border-radius:14px;color:#64748B;font-size:14px;}"
        )
        layout.addWidget(self._image, 1)

        controls = QFrame()
        controls.setObjectName("P1Controls")
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(10)

        self._btn_play = QPushButton("▶ 播放")
        self._btn_play.setMinimumWidth(86)
        self._btn_play.clicked.connect(self.toggle_playback)
        cl.addWidget(self._btn_play)

        self._btn_prev = QPushButton("上一帧")
        self._btn_prev.clicked.connect(lambda: self._jump_relative(-1))
        cl.addWidget(self._btn_prev)

        self._btn_next = QPushButton("下一帧")
        self._btn_next.clicked.connect(lambda: self._jump_relative(1))
        cl.addWidget(self._btn_next)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        cl.addWidget(self._slider, 1)

        self._cb_speed = QComboBox()
        self._cb_speed.addItem("2 fps", 500)
        self._cb_speed.addItem("6 fps", 166)
        self._cb_speed.addItem("12 fps", 83)
        self._cb_speed.setCurrentIndex(1)
        self._cb_speed.currentIndexChanged.connect(self._on_speed_changed)
        cl.addWidget(self._cb_speed)

        self._chk_loop = QCheckBox("循环")
        self._chk_loop.setChecked(True)
        cl.addWidget(self._chk_loop)

        layout.addWidget(controls)
        self.refresh_frames()

    def has_frames(self) -> bool:
        return bool(self._paths)

    def refresh_frames(self) -> bool:
        self._paths = _list_p1_frame_paths()
        self._idx = min(self._idx, max(len(self._paths) - 1, 0))
        self._slider.blockSignals(True)
        self._slider.setRange(0, max(len(self._paths) - 1, 0))
        self._slider.setValue(self._idx)
        self._slider.blockSignals(False)
        enabled = bool(self._paths)
        for widget in (self._btn_play, self._btn_prev, self._btn_next, self._slider, self._cb_speed, self._chk_loop):
            widget.setEnabled(enabled)
        self._render()
        return enabled

    def start(self) -> bool:
        if not self._paths and not self.refresh_frames():
            return False
        self._timer.start(self._cb_speed.currentData())
        self._btn_play.setText("⏸ 暂停")
        return True

    def pause(self) -> None:
        self._timer.stop()
        self._btn_play.setText("▶ 播放")

    @Slot()
    def toggle_playback(self) -> None:
        if self._timer.isActive():
            self.pause()
        else:
            self.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._paint_current_pixmap()

    def _on_speed_changed(self, _idx: int) -> None:
        if self._timer.isActive():
            self._timer.start(self._cb_speed.currentData())

    def _on_slider_changed(self, value: int) -> None:
        self._idx = value
        self._render()

    def _jump_relative(self, step: int) -> None:
        if not self._paths:
            return
        self._idx = max(0, min(len(self._paths) - 1, self._idx + step))
        self._slider.setValue(self._idx)
        self._render()

    def _next_frame(self) -> None:
        if not self._paths:
            self.pause()
            return
        if self._idx >= len(self._paths) - 1:
            if not self._chk_loop.isChecked():
                self.pause()
                return
            self._idx = 0
        else:
            self._idx += 1
        self._slider.setValue(self._idx)
        self._render()

    def _render(self) -> None:
        if not self._paths:
            self._current_pixmap = None
            self._image.setText(f"未找到 MATLAB 图片帧\n{self._frame_dir}")
            self._lb_status.setText("P1 帧: 0")
            return
        path = self._paths[self._idx]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._current_pixmap = None
            self._image.setText(f"图片读取失败\n{os.path.basename(path)}")
        else:
            self._current_pixmap = pixmap
            self._paint_current_pixmap()
        self._lb_status.setText(f"第 {self._idx + 1}/{len(self._paths)} 帧")

    def _paint_current_pixmap(self) -> None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        target = self._image.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self._current_pixmap.scaled(
            target,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image.setPixmap(scaled)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_TITLE)
        self.resize(_WINDOW_W, _WINDOW_H)
        self._session = RepairSession()  # P4-3: 统一数据源（9 分区），禁止重复缓存
        self._session.repair_mode = MODE_REPAIRING
        self._feasibility_checker = _Coord.create_feasibility_checker()
        self._zmq_client = _Coord.create_zmq_client()
        # P3-2/P3-3: 启动 ZMQ 心跳 + 连接 MATLAB 生命周期信号
        self._setup_matlab_lifecycle_signals()
        self._export_service = ExportService()
        self._file_service = FileService()
        self._pp_fields = {}
        self._cs_fields = {}
        self._path_thread = None
        self._path_worker = None
        self._morph_thread = None
        self._morph_worker = None
        self._compute_thread = None
        self._compute_worker = None
        self._pipeline_launcher = None  # MatlabBridgeLauncher 实例（跨计算复用）
        self._progress_subscriber = None  # ProgressSubscriber 实例（实时进度订阅）

        # ---- 软件工程化模块 ----
        from repair_app.software.path_manager import PathManager
        from repair_app.software.project_manager import (
            ProjectManager, AutoRecovery, RecentProjects,
        )
        self._path_manager = PathManager.get_instance()
        self._project_manager = ProjectManager(self._path_manager)
        self._auto_recovery = AutoRecovery(self._path_manager)
        self._recent_projects = RecentProjects(self._path_manager)
        # 自动保存定时器（60 秒一次）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60000)
        self._autosave_timer.timeout.connect(self._do_autosave)

        setup_logging()  # P3-4: level=None 时自动读取 CSAM_LOG_LEVEL 环境变量
        info(f"冷喷涂缺陷修复软件 v{APP_VERSION} 启动")
        info(self._path_manager.describe())

        self._license = LicenseManager()
        # MF-3: License 已在 run_app.py 启动前验证通过，此处仅加载用于状态栏显示
        # Developer Mode 下 verify_runtime() 已设置 _valid=True，无需再调用 load_license()
        if AppConfig.is_developer_mode():
            # 开发者模式：run_app.py 已通过 verify_runtime() 放行，此处同步状态
            self._license.verify_runtime()
            info("Developer Mode: License 校验已跳过")
        else:
            self._license.load_license()
            if self._license.is_valid:
                info(f"License 验证通过 ({self._license.days_remaining} 天后到期)")
            else:
                # 正常流程不会走到这里（run_app.py 已拦截），保留防御性日志
                warning(f"License 状态异常: {self._license.error}")

        self._calibration = CalibrationWizard()

        self._setup_ui()
        self._setup_statusbar()
        self._update_connection_status()
        self._update_step_buttons()
        QTimer.singleShot(300, self._load_demo)
        # 启动后检查崩溃恢复，延迟到 UI 就绪后
        QTimer.singleShot(500, self._check_recovery)
        self._autosave_timer.start()

    # ========== UI Layout ==========
    def _setup_ui(self) -> None:
        c = QWidget()
        self.setCentralWidget(c)
        self._apply_theme()

        root = QVBoxLayout(c)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._app_header())
        # MF-3: License 横幅已移除 — License 验证前置到 run_app.py，失败时拒绝启动

        # Pipeline 指示器（5 阶段流水线可视化）
        from repair_app.ui.pipeline_indicator import PipelineIndicator
        self._pipeline = PipelineIndicator()
        root.addWidget(self._pipeline)

        # 使用 QSplitter 替代固定宽度列，支持拖拽调整 + DPI 缩放
        body = QSplitter(Qt.Horizontal)
        body.setContentsMargins(0, 0, 0, 0)
        body.setHandleWidth(2)
        body.addWidget(self._left_column())
        body.addWidget(self._center())
        body.addWidget(self._right_column())
        # 比例：左侧栏 2 : 中间区 7 : 右侧栏 3
        body.setStretchFactor(0, 2)
        body.setStretchFactor(1, 7)
        body.setStretchFactor(2, 3)
        body.setChildrenCollapsible(False)
        root.addWidget(body, 1)

    def _app_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("AppHeader")
        header.setMinimumHeight(60)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(14)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("冷喷涂缺陷修复工作流")
        title.setObjectName("AppTitle")
        subtitle = QLabel("数据导入 → 缺陷选区 → 路径规划 → 形貌预测 → 工艺交付")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box, 1)

        self._lb_mode_state = QLabel("修复模式")
        self._lb_mode_state.setObjectName("HeaderChip")
        self._lb_workflow_state = QLabel("等待数据")
        self._lb_workflow_state.setObjectName("HeaderChip")
        layout.addWidget(self._lb_mode_state)
        layout.addWidget(self._lb_workflow_state)
        return header

    def _apply_theme(self) -> None:
        """应用工业级主题（从 ThemeManager 读取统一 QSS）。"""
        self.setStyleSheet(ThemeManager.get_qss())

    def _left_column(self) -> QWidget:
        outer = QWidget()
        outer.setObjectName("SideRail")
        outer.setMinimumWidth(220)
        layout = QVBoxLayout(outer); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(10)

        # --- 步骤按钮栏 ---
        workflow = QGroupBox("工作流")
        sl = QVBoxLayout(workflow); sl.setContentsMargins(12, 18, 12, 12); sl.setSpacing(8)

        self._step1_btn = QPushButton("01  数据与路径\n加载点云、选区、生成路径")
        self._step1_btn.setMinimumHeight(58)
        self._step1_btn.setCursor(Qt.PointingHandCursor)
        self._step1_btn.clicked.connect(lambda: self._switch_to_step(PAGE_PATH))
        sl.addWidget(self._step1_btn)

        self._arrow_lb = QLabel("↓")
        self._arrow_lb.setAlignment(Qt.AlignCenter)
        sl.addWidget(self._arrow_lb)

        self._step2_btn = QLabel("02  形貌预测\n等待路径规划输出")
        self._step2_btn.setMinimumHeight(54)
        self._step2_btn.setAlignment(Qt.AlignCenter)
        self._style_workflow_label(self._step2_btn, "locked")
        sl.addWidget(self._step2_btn)

        self._step3_lb = QLabel("03  结果校核\n查看指标、截面和风险")
        self._step3_lb.setMinimumHeight(54)
        self._step3_lb.setAlignment(Qt.AlignCenter)
        self._step3_lb.setStyleSheet(
            "color:#475569; font-size:11px; padding:8px; "
            "background:#0F172A; border:1px dashed #334155; border-radius:6px;"
        )
        sl.addWidget(self._step3_lb)

        self._step4_btn = QPushButton("04  输出交付\n导出 G-code 与 PDF 报告")
        self._step4_btn.setMinimumHeight(58)
        self._step4_btn.setCursor(Qt.PointingHandCursor)
        self._step4_btn.setEnabled(False)
        self._step4_btn.clicked.connect(lambda: self._switch_to_step(PAGE_OUTPUT))
        sl.addWidget(self._step4_btn)
        layout.addWidget(workflow)

        # --- 材料选择 ---
        mat_bar = QGroupBox("材料选择")
        mat_ml = QVBoxLayout(mat_bar); mat_ml.setSpacing(4)
        mat_row = QHBoxLayout(); mat_row.addWidget(QLabel("材料"))
        self._cb_mat = QComboBox()
        self._cb_mat.setToolTip("选择喷涂材料。不同材料有不同的临界速度和密度，影响沉积效率和涂层质量。")
        for label, _ in _MATERIALS: self._cb_mat.addItem(label)
        self._cb_mat.setCurrentIndex(1)
        self._cb_mat.currentIndexChanged.connect(self._on_material_changed)
        mat_row.addWidget(self._cb_mat); mat_row.addStretch()
        mat_ml.addLayout(mat_row)
        self._lb_mat_info = QLabel("v_cr: — m/s | 密度: — kg/m³")
        self._lb_mat_info.setStyleSheet("color:#64748B; font-size:11px; padding-left:4px;")
        mat_ml.addWidget(self._lb_mat_info)
        layout.addWidget(mat_bar)

        # --- QStackedWidget ---
        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._build_path_planning_panel())
        self._mode_stack.addWidget(self._build_morphology_panel())
        self._mode_stack.addWidget(self._build_output_panel())
        layout.addWidget(self._mode_stack)
        return outer

    # ====== Panel A: 路径规划 ======
    def _build_path_planning_panel(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        p = QFrame(); scroll.setWidget(p)
        l = QVBoxLayout(p); l.setContentsMargins(10, 10, 10, 10); l.setSpacing(8)

        self._btn_load = QPushButton("📂 加载点云"); self._btn_load.setMinimumHeight(38)
        self._btn_load.setToolTip("加载点云文件（支持 CSV、TXT、XYZ、ASC 格式）")
        self._btn_load.clicked.connect(self._on_load); l.addWidget(self._btn_load)
        l.addWidget(self._sep())

        # --- 修复模式选择 ---
        mg = QGroupBox("修复模式"); ml = QVBoxLayout(mg); ml.setSpacing(4)
        self._rb_additive = QRadioButton(" 增材模式（全表面覆盖）")
        self._rb_repairing = QRadioButton(" 修复模式（缺陷填充）")
        self._rb_repairing.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._rb_additive, MODE_ADDITIVE)
        self._mode_group.addButton(self._rb_repairing, MODE_REPAIRING)
        self._mode_group.idClicked.connect(self._on_mode_changed)
        ml.addWidget(self._rb_additive)
        ml.addWidget(self._rb_repairing)
        l.addWidget(mg)

        self._lb_mode_hint = QLabel("💡 在中心视图框选缺陷区域 → 调参数 → 点击生成路径")
        self._lb_mode_hint.setStyleSheet("color:#64748B; font-size:11px; padding:4px;")
        self._lb_mode_hint.setWordWrap(True); l.addWidget(self._lb_mode_hint)

        eg = QGroupBox("计算引擎"); el = QVBoxLayout(eg); el.setSpacing(4)
        engine_row = QHBoxLayout(); engine_row.addWidget(QLabel("引擎"))
        self._cb_engine = QComboBox()
        self._cb_engine.setToolTip("选择计算引擎。本地引擎用于快速预览；远程服务连接 MATLAB 获取精确计算结果。生产环境建议使用远程服务。")
        self._cb_engine.addItem("本地计算引擎", "local")
        self._cb_engine.addItem("远程服务 (MATLAB)", "zmq")
        if not _ZMQ_AVAILABLE:
            self._cb_engine.model().item(1).setEnabled(False)
        else:
            self._cb_engine.setCurrentIndex(1)
        self._cb_engine.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self._cb_engine); engine_row.addStretch(); el.addLayout(engine_row)
        self._lb_engine_hint = QLabel("本地引擎支持逐层实时刷新；远程服务用于连接 MATLAB 获取最终计算结果。")
        self._lb_engine_hint.setStyleSheet("color:#64748B; font-size:11px; padding:4px;")
        self._lb_engine_hint.setWordWrap(True); el.addWidget(self._lb_engine_hint)
        eg.setVisible(False)
        l.addWidget(eg)

        ppg = QGroupBox("路径规划参数"); ppl = QVBoxLayout(ppg); ppl.setSpacing(5)
        # MF-8: 从 PARAM_SPECS 唯一权威源动态生成（消除硬编码范围双源冲突）
        for spec_key, ui_key, label, suffix, tooltip, _grp, read_only in UI_PARAM_SPECS:
            if _grp != "pp":
                continue
            lo, hi, default, step = get_ui_param(spec_key)[:4]
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setValue(default)
            sp.setSingleStep(step); sp.setSuffix(suffix); sp.setMinimumWidth(100)
            sp.setToolTip(tooltip)
            if read_only:
                sp.setEnabled(False)
            row.addWidget(sp); row.addStretch(); ppl.addLayout(row)
            self._pp_fields[ui_key] = sp

        nl_row = QHBoxLayout(); nl_row.addWidget(QLabel("规划层数"))
        self._sp_pp_layers = QSpinBox()
        _nl = schema_loader.get_process_param("num_layers")
        self._sp_pp_layers.setRange(int(_nl["min"]), int(_nl["max"]))
        self._sp_pp_layers.setSingleStep(int(_nl["step"]))
        self._sp_pp_layers.setValue(int(_nl["default"]))
        self._sp_pp_layers.setMinimumWidth(100)
        self._sp_pp_layers.setToolTip(_nl["tooltip"])
        nl_row.addWidget(self._sp_pp_layers); nl_row.addStretch(); ppl.addLayout(nl_row)
        l.addWidget(ppg)

        # --- 文件保存选项 ---
        sg = QGroupBox("输出选项"); sl2 = QVBoxLayout(sg); sl2.setSpacing(4)
        self._chk_save_files = QCheckBox("保存计算中间文件到磁盘")
        self._chk_save_files.setChecked(True)
        self._chk_save_files.setStyleSheet("color:#E2E8F0; font-size:12px;")
        self._chk_save_files.setToolTip("勾选：保存路径与速度数据供形貌预测读取；不勾选：数据仅保留在内存中")
        sl2.addWidget(self._chk_save_files)
        hint2 = QLabel("  勾选：路径规划后保存中间文件，形貌预测从文件读取\n"
                        "  不勾选：数据仅保留在内存中，不写入磁盘")
        hint2.setStyleSheet("color:#64748B; font-size:10px;")
        hint2.setWordWrap(True); sl2.addWidget(hint2)
        l.addWidget(sg)

        # --- 操作 ---
        og = QGroupBox("操作"); ol = QVBoxLayout(og); ol.setSpacing(8)
        self._btn_start_repair = QPushButton("🚀 开始修复")
        self._btn_start_repair.setMinimumHeight(48); self._btn_start_repair.setEnabled(False)
        self._btn_start_repair.setToolTip(
            "一键执行完整修复流程：\n"
            "路径规划 → 形貌预测 → 报告生成 → 安全校验\n"
            "根据引擎自动选择本地快速预览或 MATLAB 精确计算"
        )
        self._btn_start_repair.clicked.connect(self._on_start_repair)
        self._btn_start_repair.setStyleSheet(
            "QPushButton{background:#059669;color:#FFF;border:none;border-radius:6px;"
            "font-size:15px;font-weight:bold;}"
            "QPushButton:hover{background:#10B981;}"
            "QPushButton:disabled{background:#334155;color:#64748B;}"
        )
        ol.addWidget(self._btn_start_repair)

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Panel B: 形貌预测 ======
    def _build_morphology_panel(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        p = QFrame(); scroll.setWidget(p)
        l = QVBoxLayout(p); l.setContentsMargins(10, 10, 10, 10); l.setSpacing(8)

        # --- 输入状态 ---
        fg = QGroupBox("输入数据来源")
        fl = QVBoxLayout(fg); fl.setSpacing(4)

        self._lb_pl_status = QLabel("⏳ 请先完成路径规划")
        self._lb_pl_status.setStyleSheet("color:#F59E0B; font-size:13px;")
        fl.addWidget(self._lb_pl_status)

        self._lb_input_source = QLabel("来源: —")
        self._lb_input_source.setStyleSheet("color:#64748B; font-size:11px;")
        fl.addWidget(self._lb_input_source)
        l.addWidget(fg)

        # --- 冷喷涂工艺参数 ---
        cpg = QGroupBox("冷喷涂工艺参数"); cpl = QVBoxLayout(cpg); cpl.setSpacing(5)
        # MF-8: 从 PARAM_SPECS 唯一权威源动态生成（消除硬编码范围双源冲突）
        for spec_key, ui_key, label, suffix, tooltip, _grp, read_only in UI_PARAM_SPECS:
            if _grp != "cs":
                continue
            lo, hi, default, step = get_ui_param(spec_key)[:4]
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setValue(default)
            sp.setSingleStep(step); sp.setSuffix(suffix); sp.setMinimumWidth(100)
            sp.setToolTip(tooltip)
            if read_only:
                sp.setEnabled(False)
            row.addWidget(sp); row.addStretch(); cpl.addLayout(row)
            self._cs_fields[ui_key] = sp
        # 临界速度只读提示（额外补充）
        if "critical_velocity" in self._cs_fields:
            self._cs_fields["critical_velocity"].setToolTip(
                "临界速度由材料数据库自动计算，不可手动修改"
            )
        l.addWidget(cpg)

        dg = QGroupBox("沉积参数"); dl = QVBoxLayout(dg); dl.setSpacing(5)
        dr = QHBoxLayout(); dr.addWidget(QLabel("深度补偿"))
        self._sp_depth = QDoubleSpinBox()
        _dc = schema_loader.get_process_param("depth_compensation")
        self._sp_depth.setRange(_dc["min"], _dc["max"])
        self._sp_depth.setValue(_dc["default"]); self._sp_depth.setSingleStep(_dc["step"])
        self._sp_depth.setSuffix(" x"); self._sp_depth.setMinimumWidth(90)
        self._sp_depth.setToolTip(_dc["tooltip"])
        dr.addWidget(self._sp_depth); dr.addStretch(); dl.addLayout(dr)
        nr = QHBoxLayout(); nr.addWidget(QLabel("预测层数"))
        self._sp_max_layers = QSpinBox()
        _ml = schema_loader.get_process_param("max_morphology_layers")
        self._sp_max_layers.setRange(int(_ml["min"]), int(_ml["max"]))
        self._sp_max_layers.setSingleStep(int(_ml["step"]))
        self._sp_max_layers.setValue(int(_ml["default"]))
        self._sp_max_layers.setMinimumWidth(90)
        self._sp_max_layers.setToolTip(_ml["tooltip"])
        nr.addWidget(self._sp_max_layers); nr.addStretch(); dl.addLayout(nr)
        l.addWidget(dg)

        og = QGroupBox("操作"); ol = QVBoxLayout(og); ol.setSpacing(8)
        self._btn_feas = QPushButton("🔍 可行性检查")
        self._btn_feas.setMinimumHeight(34); self._btn_feas.setEnabled(False)
        self._btn_feas.setToolTip("检查当前工艺参数和缺陷区域是否适合冷喷涂修复")
        self._btn_feas.clicked.connect(self._on_feasibility_check)
        ol.addWidget(self._btn_feas)

        self._btn_fix = QPushButton("🔮 执行形貌预测")
        self._btn_fix.setMinimumHeight(42); self._btn_fix.setEnabled(False)
        self._btn_fix.setToolTip("基于路径规划输出模拟冷喷涂沉积过程，预测修复形貌")
        self._btn_fix.clicked.connect(self._on_fix)
        self._btn_fix.setStyleSheet(
            "QPushButton{background:#7C3AED;color:#FFF;border:none;border-radius:6px;"
            "font-size:14px;font-weight:bold;}"
            "QPushButton:hover{background:#8B5CF6;}"
            "QPushButton:disabled{background:#334155;color:#64748B;}"
        )
        ol.addWidget(self._btn_fix)

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Panel C: 输出交付 ======
    def _build_output_panel(self) -> QWidget:
        """04 输出交付面板：集中放置所有导出入口。

        P5-4: 从 ExporterRegistry 动态构建导出按钮。新增导出格式只需注册
        BaseExporter 子类，无需修改本方法或 MainWindow 任何代码。
        """
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        p = QFrame(); scroll.setWidget(p)
        l = QVBoxLayout(p); l.setContentsMargins(10, 10, 10, 10); l.setSpacing(8)

        og = QGroupBox("导出"); ol = QVBoxLayout(og); ol.setSpacing(6)

        # P5-4: 从注册表动态构建按钮
        self._export_buttons = {}
        for exporter in ExporterRegistry.list():
            btn = QPushButton(f"{exporter.icon} 导出 {exporter.display_name}")
            btn.setMinimumHeight(42 if exporter.sort_order == 10 else 34)
            btn.setEnabled(False)
            btn.setToolTip(exporter.tooltip)
            # 第一个导出器（G-code）使用醒目样式
            if exporter.sort_order == 10:
                btn.setStyleSheet(
                    "QPushButton{background:#1D4ED8;color:#FFF;border:none;border-radius:6px;"
                    "font-size:14px;font-weight:bold;}"
                    "QPushButton:hover{background:#2563EB;}"
                    "QPushButton:disabled{background:#334155;color:#64748B;}"
                )
            btn.clicked.connect(lambda checked, name=exporter.name: self._on_export(name))
            ol.addWidget(btn)
            self._export_buttons[exporter.name] = btn
            # 向后兼容：保持 _btn_exp_gcode/_btn_exp_robot/_btn_exp_pdf 属性
            if exporter.name == "gcode":
                self._btn_exp_gcode = btn
            elif exporter.name == "robot":
                self._btn_exp_robot = btn
            elif exporter.name == "pdf":
                self._btn_exp_pdf = btn

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Center ======
    def _center(self) -> QWidget:
        self._center_widget = QWidget()
        self._center_widget.setObjectName("Workspace")
        layout = QVBoxLayout(self._center_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._workspace_stack = QStackedWidget()
        self._workspace_stack.setObjectName("WorkspaceStack")

        # ---- 步骤 01：路径规划工作区 ----
        path_workspace = QWidget()
        path_layout = QVBoxLayout(path_workspace)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)

        self._selector = DefectSelector()
        self._selector.selection_changed.connect(self._on_selection_changed)

        self._visualizer = RepairVisualizer()

        # ---- 中心区 Tab 切换：3D 预览 / MATLAB 形貌分析 ----
        self._center_tabs = QTabWidget()
        self._center_tabs.setStyleSheet("""
            QTabWidget::pane { border:1px solid #1E293B; border-radius:8px; background:#0B1120; top:-1px; }
            QTabBar::tab { background:#0F172A; color:#94A3B8; padding:6px 14px; margin-right:2px;
                           border:1px solid #1E293B; border-bottom:none;
                           border-top-left-radius:6px; border-top-right-radius:6px; font-weight:600; }
            QTabBar::tab:selected { background:#1D4ED8; color:#FFFFFF; }
            QTabBar::tab:hover:!selected { background:#1E293B; color:#E2E8F0; }
        """)
        self._center_tabs.addTab(self._visualizer, "3D 预览（基体/路径/喷嘴）")

        self._profile_panel = ProfileResultPanel()
        self._center_tabs.addTab(self._profile_panel, "MATLAB 形貌分析")
        self._center_tabs.setCurrentIndex(0)

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.addWidget(self._center_tabs)

        right_panel = QWidget()
        right_panel.setObjectName("AuxPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self._lb_selector_title = QLabel("原始点云 / 缺陷选区")
        self._lb_selector_title.setStyleSheet(
            "color:#94A3B8; font-size:11px; padding:2px 4px; font-weight:bold;"
        )
        right_layout.addWidget(self._lb_selector_title)
        right_layout.addWidget(self._selector, 5)

        # ---- 路径规划 + 形貌预测辅助截面 ----
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        fig_bottom = Figure(figsize=(4.5, 5.5), dpi=100)
        fig_bottom.set_facecolor("#0F172A")
        self._canvas_bottom = FigureCanvas(fig_bottom)

        gs = fig_bottom.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.45)
        self._ax_path = fig_bottom.add_subplot(gs[0])
        self._ax_path.set_facecolor("#0F172A")
        self._ax_path.set_title("截面路径规划", color="#94A3B8", fontsize=10)
        self._ax_path.tick_params(colors="#64748B", labelsize=8)
        for spine in self._ax_path.spines.values():
            spine.set_color("#334155")
        self._ax_path.grid(True, color="#1E293B", alpha=0.5)

        self._ax_morph = fig_bottom.add_subplot(gs[1])
        self._ax_morph.set_facecolor("#0F172A")
        self._ax_morph.set_title("形貌预测结果", color="#94A3B8", fontsize=10)
        self._ax_morph.tick_params(colors="#64748B", labelsize=8)
        for spine in self._ax_morph.spines.values():
            spine.set_color("#334155")
        self._ax_morph.grid(True, color="#1E293B", alpha=0.5)

        self._lb_bottom_status = QLabel("请先完成路径规划...")
        self._lb_bottom_status.setStyleSheet("color:#64748B; font-size:11px; padding:4px;")
        self._lb_bottom_status.setAlignment(Qt.AlignCenter)

        bottom_panel = QWidget()
        bottom_panel.setObjectName("AuxPanel")
        bl = QVBoxLayout(bottom_panel); bl.setContentsMargins(8, 8, 8, 8); bl.setSpacing(6)
        bl.addWidget(self._lb_bottom_status)
        bl.addWidget(self._canvas_bottom)
        right_layout.addWidget(bottom_panel, 4)

        self._main_splitter.addWidget(right_panel)
        self._main_splitter.setSizes([760, 430])
        path_layout.addWidget(self._main_splitter)

        self._workspace_stack.addWidget(path_workspace)
        layout.addWidget(self._workspace_stack, 1)

        # ---- 实时统计面板 + 逐层播放器 ----
        from repair_app.ui.realtime_stats import RealtimeStatsPanel
        from repair_app.ui.layer_player import LayerPlayer
        from repair_app.ui.progress_subscriber import ProgressSubscriber
        self._realtime_stats = RealtimeStatsPanel()
        layout.addWidget(self._realtime_stats)
        self._layer_player = LayerPlayer()
        self._layer_player.layer_changed.connect(self._on_layer_changed)
        layout.addWidget(self._layer_player)

        # ---- 实时进度订阅器（ZMQ SUB，监听 MATLAB 逐步发布的进度） ----
        self._progress_subscriber = ProgressSubscriber(self)
        self._progress_subscriber.stats_updated.connect(self._realtime_stats.update_stats)
        self._progress_subscriber.layer_completed.connect(self._on_layer_completed)
        self._progress_subscriber.mesh_updated.connect(self._on_mesh_updated)
        self._progress_subscriber.progress_received.connect(self._on_progress_received)

        self._top_splitter = self._main_splitter  # 兼容旧引用
        self._bottom_splitter = self._main_splitter
        self._tabs = self._main_splitter  # 兼容旧引用
        return self._center_widget

    # ====== Right Column ======
    def _right_column(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(260); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        p = QFrame(); scroll.setWidget(p)
        p.setObjectName("Inspector")
        l = QVBoxLayout(p); l.setContentsMargins(12, 12, 12, 12); l.setSpacing(10)

        ig = QGroupBox("点云信息"); il = QVBoxLayout(ig)
        self._lb_pts = QLabel("点数: —"); il.addWidget(self._lb_pts)
        self._lb_sel = QLabel("已选: 0"); il.addWidget(self._lb_sel)
        l.addWidget(ig)

        fg = QGroupBox("可行性报告"); fl = QVBoxLayout(fg)
        self._lb_feas_status = QLabel("状态: 尚未检查"); fl.addWidget(self._lb_feas_status)
        self._lb_feas_score = QLabel("评分: —"); fl.addWidget(self._lb_feas_score)
        self._feas_text = QTextEdit(); self._feas_text.setReadOnly(True)
        self._feas_text.setMinimumHeight(80); self._feas_text.setMaximumHeight(250)
        self._feas_text.setPlaceholderText("点击'可行性检查'后显示...")
        fl.addWidget(self._feas_text)
        l.addWidget(fg)

        pg = QGroupBox("进度"); pl = QVBoxLayout(pg)
        self._prog = QProgressBar(); self._prog.setRange(0, 100); self._prog.setValue(0)
        pl.addWidget(self._prog)
        self._lb_prog = QLabel("就绪"); pl.addWidget(self._lb_prog)
        l.addWidget(pg)

        rg = QGroupBox("结果摘要"); rl = QVBoxLayout(rg); rl.setSpacing(5)
        self._lb_vol  = self._kv("填充点数", "— pts")
        self._lb_mass = self._kv("材料用量", "— g")
        self._lb_time = self._kv("预计耗时", "— s")
        self._lb_lay  = self._kv("修复层数", "—")
        self._lb_unif = self._kv("均匀性",   "—")
        self._lb_feas = self._kv("可行性",   "—")
        rl.addWidget(self._lb_vol); rl.addWidget(self._lb_mass)
        rl.addWidget(self._lb_time); rl.addWidget(self._lb_lay)
        rl.addWidget(self._lb_unif); rl.addWidget(self._lb_feas)
        l.addWidget(rg)
        l.addStretch()
        return scroll

    def _setup_statusbar(self) -> None:
        self._sb = QStatusBar()
        # 永久部件：BusyIndicator / 版本 / License / 项目 / 连接
        self._busy_label = BusyLabel()
        self._sb.addPermanentWidget(self._busy_label)

        self._lb_version = QLabel(f"v{APP_VERSION}")
        self._lb_version.setStyleSheet(f"color:{ThemeManager.get_palette().text_muted}; padding:0 8px;")
        self._sb.addPermanentWidget(self._lb_version)

        self._lb_license = QLabel("⚫ License 未验证")
        self._lb_license.setStyleSheet(f"color:{ThemeManager.get_palette().text_muted}; padding:0 8px;")
        self._sb.addPermanentWidget(self._lb_license)
        self._refresh_license_status()

        self._lb_project = QLabel("项目: 未命名")
        self._lb_project.setStyleSheet(f"color:{ThemeManager.get_palette().text_muted}; padding:0 8px;")
        self._sb.addPermanentWidget(self._lb_project)

        self._lb_conn = QLabel("⚫ 本地模式")
        self._lb_conn.setStyleSheet(f"color:{ThemeManager.get_palette().text_muted}; padding:0 8px;")
        self._sb.addPermanentWidget(self._lb_conn)
        self.setStatusBar(self._sb)
        self._sb.showMessage("路径规划 — 加载点云并选取缺陷区域后生成路径")
        # 菜单栏（文件 / 编辑 / 视图 / 工具 / 帮助）
        self._setup_menubar()
        # 工具栏
        self._setup_toolbar()
        # 右键上下文菜单
        self._setup_context_menu()

    def _refresh_license_status(self) -> None:
        """刷新状态栏 License 指示。"""
        try:
            p = ThemeManager.get_palette()
            if self._license.is_developer_mode:
                # Developer Mode: 状态栏显示醒目的开发模式标识
                text = "🛠 Developer Mode"
                color = p.warning
            elif self._license.is_valid:
                days = self._license.days_remaining
                if days < 0:
                    text = "✅ 永久授权"
                    color = p.success
                elif days <= int(schema_loader.get_system_value("license_warning_days")):
                    text = f"⚠️ License {days} 天后到期"
                    color = p.warning
                else:
                    text = f"✅ License 有效 ({days} 天)"
                    color = p.success
            else:
                text = f"⛔ License 无效"
                color = p.error
            self._lb_license.setText(text)
            self._lb_license.setStyleSheet(f"color:{color}; padding:0 8px; font-weight:600;")
        except Exception as e:
            log_error(f"License 状态更新失败: {e}")

    def _setup_menubar(self) -> None:
        """创建菜单栏：文件 / 编辑 / 视图 / 工具 / 帮助。

        参考商业工业软件菜单结构：
        - Siemens NX: File / Edit / View / Insert / Format / Tools / ...
        - SolidWorks: 文件 / 编辑 / 视图 / 插入 / 工具 / 窗口 / 帮助
        """
        menubar = self.menuBar()
        # 菜单栏 QSS 由 ThemeManager 统一管理，不再局部 setStyleSheet

        # ---- 文件菜单 ----
        file_menu = menubar.addMenu("文件(&F)")
        act_open = file_menu.addAction("打开点云...")
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_load)
        file_menu.addSeparator()
        act_save_project = file_menu.addAction("保存项目")
        act_save_project.triggered.connect(self._on_save_project)
        act_open_project = file_menu.addAction("打开项目...")
        act_open_project.triggered.connect(self._on_open_project)
        file_menu.addSeparator()
        # 最近项目子菜单
        self._recent_menu = file_menu.addMenu("最近项目")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        act_open_export_dir = file_menu.addAction("打开导出目录")
        act_open_export_dir.triggered.connect(self._on_open_export_dir)
        act_open_log_dir = file_menu.addAction("打开日志目录")
        act_open_log_dir.triggered.connect(self._on_open_log_dir)
        # P3-4: 日志导出功能
        act_export_logs = file_menu.addAction("导出日志为 ZIP...")
        act_export_logs.setToolTip("将所有日志打包为 zip 文件，用于问题反馈")
        act_export_logs.triggered.connect(self._on_export_logs)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("退出")
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)

        # ---- 高级菜单（高级功能入口，不影响主流程） ----
        adv_menu = menubar.addMenu("高级(&A)")

        act_feas = adv_menu.addAction("🔍 可行性检查...")
        act_feas.setToolTip("评估当前参数下修复的可行性")
        act_feas.triggered.connect(self._on_feasibility_check)

        adv_menu.addSeparator()

        act_robot = adv_menu.addAction("🤖 导出工业机器人轨迹...")
        act_robot.setToolTip("将修复航点转换为 KUKA KRL 或 ABB Rapid 机器人指令")
        act_robot.setShortcut("Ctrl+R")
        act_robot.triggered.connect(self._on_export_robot)

        adv_menu.addSeparator()

        act_calib = adv_menu.addAction("🎯 单道沉积标定向导...")
        act_calib.setToolTip("通过实测数据计算宽度/高度/效率修正系数")
        act_calib.setShortcut("Ctrl+Shift+C")
        act_calib.triggered.connect(self._on_calibration)

        act_coord = adv_menu.addAction("📐 坐标系变换...")
        act_coord.setToolTip("对点云执行平移/旋转/缩放变换")
        act_coord.setShortcut("Ctrl+Shift+T")
        act_coord.triggered.connect(self._on_coord_transform)

        adv_menu.addSeparator()

        act_preset = adv_menu.addAction("⚙️ 参数预设管理...")
        act_preset.setToolTip("保存/加载/删除参数预设组合")
        act_preset.setShortcut("Ctrl+Shift+P")
        act_preset.triggered.connect(self._on_param_preset)

        act_batch = adv_menu.addAction("🔬 批量验证...")
        act_batch.setToolTip("对多组参数批量执行可行性检查")
        act_batch.setShortcut("Ctrl+Shift+B")
        act_batch.triggered.connect(self._on_batch_validation)

        act_validator = adv_menu.addAction("✓ 参数校验器...")
        act_validator.setToolTip("实时校验当前工艺参数是否在合法范围内")
        act_validator.setShortcut("Ctrl+Shift+V")
        act_validator.triggered.connect(self._on_param_validator)

        # ---- 编辑菜单（Undo/Redo，参考 SolidWorks / NX） ----
        edit_menu = menubar.addMenu("编辑(&E)")
        # UndoStack 单例
        self._undo_stack = UndoStack.instance()
        act_undo = self._undo_stack.create_undo_action(self, "撤销")
        edit_menu.addAction(act_undo)
        act_redo = self._undo_stack.create_redo_action(self, "重做")
        edit_menu.addAction(act_redo)
        edit_menu.addSeparator()
        act_clear_sel = edit_menu.addAction("清除选区")
        act_clear_sel.triggered.connect(self._on_clear_selection)

        # ---- 视图菜单（参考 NX / Geomagic 视图控制） ----
        view_menu = menubar.addMenu("视图(&V)")
        act_reset_view = view_menu.addAction("重置视角")
        act_reset_view.setShortcut("F")
        act_reset_view.triggered.connect(self._on_reset_view)
        act_fit_view = view_menu.addAction("适应窗口")
        act_fit_view.setShortcut("Ctrl+Shift+F")
        act_fit_view.triggered.connect(self._on_fit_view)
        view_menu.addSeparator()
        act_toggle_axes = view_menu.addAction("显示/隐藏坐标轴")
        act_toggle_axes.setCheckable(True)
        act_toggle_axes.setChecked(True)
        act_toggle_axes.triggered.connect(self._on_toggle_axes)
        view_menu.addSeparator()
        # 主题切换子菜单
        theme_menu = view_menu.addMenu("主题")
        act_dark = theme_menu.addAction("深色主题")
        act_dark.setCheckable(True)
        act_dark.setChecked(True)
        act_dark.triggered.connect(lambda: self._on_switch_theme("dark"))
        act_light = theme_menu.addAction("浅色主题")
        act_light.setCheckable(True)
        act_light.triggered.connect(lambda: self._on_switch_theme("light"))

        # ---- 帮助菜单 ----
        help_menu = menubar.addMenu("帮助(&H)")
        act_about = help_menu.addAction("关于")
        act_about.triggered.connect(self._on_show_about)
        act_about_qt = help_menu.addAction("关于 Qt")
        act_about_qt.triggered.connect(lambda: QMessageBox.aboutQt(self, "关于 Qt"))

    def _setup_toolbar(self) -> None:
        """创建主工具栏（参考 Siemens NX / SolidWorks 工具栏）。

        提供：打开 / 保存 / 撤销 / 重做 / 视角控制 / 计算 / 导出
        """
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        # 文件操作
        act_tb_open = QAction("📂 打开", self)
        act_tb_open.setToolTip("打开点云文件 (Ctrl+O)")
        act_tb_open.setShortcut("Ctrl+O")
        act_tb_open.triggered.connect(self._on_load)
        tb.addAction(act_tb_open)

        act_tb_save = QAction("💾 保存", self)
        act_tb_save.setToolTip("保存项目 (Ctrl+S)")
        act_tb_save.setShortcut("Ctrl+S")
        act_tb_save.triggered.connect(self._on_save_project)
        tb.addAction(act_tb_save)

        tb.addSeparator()

        # Undo / Redo
        tb.addAction(self._undo_stack.create_undo_action(self, "↩ 撤销"))
        tb.addAction(self._undo_stack.create_redo_action(self, "↪ 重做"))

        tb.addSeparator()

        # 视图操作
        act_tb_reset = QAction("🎯 重置视角", self)
        act_tb_reset.setShortcut("F")
        act_tb_reset.setToolTip("重置 3D 视角 (F)")
        act_tb_reset.triggered.connect(self._on_reset_view)
        tb.addAction(act_tb_reset)

        act_tb_fit = QAction("🔍 适应", self)
        act_tb_fit.setShortcut("Ctrl+Shift+F")
        act_tb_fit.setToolTip("适应窗口 (Ctrl+Shift+F)")
        act_tb_fit.triggered.connect(self._on_fit_view)
        tb.addAction(act_tb_fit)

        tb.addSeparator()

        # 主题切换
        act_tb_theme = QAction("🌙 主题", self)
        act_tb_theme.setToolTip("切换深色/浅色主题")
        act_tb_theme.triggered.connect(lambda: self._on_switch_theme(
            "light" if ThemeManager.get_theme_name() == "dark" else "dark"
        ))
        tb.addAction(act_tb_theme)

    def _setup_context_menu(self) -> None:
        """为主视图安装右键上下文菜单。"""
        self._context_menu_mgr = ContextMenuManager(self)
        # 为可视化视图安装右键菜单
        if hasattr(self, "_visualizer") and self._visualizer is not None:
            self._visualizer.setContextMenuPolicy(Qt.CustomContextMenu)
            self._visualizer.customContextMenuRequested.connect(
                self._context_menu_mgr.show_context_menu
            )

    # ---- 视图菜单动作 ----
    def _on_reset_view(self) -> None:
        if hasattr(self, "_visualizer") and self._visualizer is not None:
            try:
                self._visualizer.reset_view()
            except Exception as exc:
                log_error(f"重置视角失败: {exc}")

    def _on_fit_view(self) -> None:
        if hasattr(self, "_visualizer") and self._visualizer is not None:
            try:
                self._visualizer.fit_to_view()
            except Exception as exc:
                log_error(f"适应窗口失败: {exc}")

    def _on_toggle_axes(self) -> None:
        if hasattr(self, "_visualizer") and self._visualizer is not None:
            try:
                self._visualizer.toggle_axes()
            except Exception as exc:
                log_error(f"切换坐标轴失败: {exc}")

    def _on_clear_selection(self) -> None:
        if hasattr(self, "_selector") and self._selector is not None:
            try:
                self._selector.clear_selection()
                Toast.info(self, "选区已清除")
            except Exception as exc:
                log_error(f"清除选区失败: {exc}")

    def _on_switch_theme(self, name: str) -> None:
        """切换深色/浅色主题。"""
        ThemeManager.set_theme(name)
        self.setStyleSheet(ThemeManager.get_qss())
        Toast.info(self, f"已切换到{name}主题")

    def _refresh_recent_menu(self) -> None:
        """刷新最近项目子菜单。"""
        self._recent_menu.clear()
        items = self._recent_projects.items
        if not items:
            act = self._recent_menu.addAction("（无）")
            act.setEnabled(False)
            return
        for it in items:
            name = it.get("name", "未命名")
            path = it.get("path", "")
            label = f"{name} — {path}"
            act = self._recent_menu.addAction(label)
            act.triggered.connect(lambda checked=False, p=path: self._on_open_recent(p))
        self._recent_menu.addSeparator()
        act_clear = self._recent_menu.addAction("清空最近项目")
        act_clear.triggered.connect(self._on_clear_recent)

    # ========== 步骤切换 ==========
    @Slot(int)
    def _on_mode_changed(self, mode_id: int) -> None:
        self._session.repair_mode = mode_id
        self._update_step_buttons()
        if mode_id == MODE_ADDITIVE:
            self._lb_mode_hint.setText("💡 增材模式：将对整个零件表面生成全覆盖路径")
            self._btn_start_repair.setText("🚀 开始修复（增材）")
            if self._session.is_busy:
                return
            self._btn_start_repair.setEnabled(self._session.point_cloud.xyz is not None)
            # 增材模式不需要选择缺陷
            self._btn_feas.setEnabled(False)
        else:
            self._lb_mode_hint.setText("💡 修复模式：在中心视图框选缺陷区域 → 调参数 → 点击开始修复")
            self._btn_start_repair.setText("🚀 开始修复")
            if self._session.is_busy:
                return
            sel_mask = self._selector.get_selection_mask() if self._selector else None
            self._btn_start_repair.setEnabled(self._session.point_cloud.xyz is not None and sel_mask is not None and np.any(sel_mask))

    @Slot(int)
    def _on_engine_changed(self, _idx: int) -> None:
        if self._use_zmq_engine():
            self._lb_engine_hint.setText("远程服务：发送计算请求至 MATLAB，返回最终修复结果。")
        else:
            self._lb_engine_hint.setText("本地引擎支持逐层实时刷新；远程服务用于连接 MATLAB 获取最终计算结果。")

    def _use_zmq_engine(self) -> bool:
        return (
            hasattr(self, "_cb_engine")
            and self._cb_engine.currentData() == "zmq"
            and self._zmq_client is not None
        )

    def _build_repair_request(self, sel_mask: np.ndarray):
        params = self._collect_params()
        request_xyz = self._session.point_cloud.xyz[sel_mask]
        request_normals = self._session.point_cloud.normals[sel_mask] if self._session.point_cloud.normals is not None else self._est_normals(request_xyz)
        mat_code = _MATERIALS[self._cb_mat.currentIndex()][1]
        return _Coord.build_repair_request(
            request_xyz,
            request_normals,
            scan_id=f"SCAN-{self._session.latest_seed:04d}",
            depth_compensation=params.get("depth_compensation", 1.0),
            smooth_threshold=0.5,
            max_layers=params.get("max_layers", 5),
            material=mat_code,
            particle_velocity_ms=params.get("particle_velocity_ms", 500.0),
            critical_velocity_ms=params.get("critical_velocity_ms", 400.0),
            nozzle_diameter_mm=params.get("nozzle_diameter_mm", 6.0),
            spray_angle_deg=params.get("spray_angle_deg", 90.0),
            standoff_distance_mm=params.get("standoff_distance_mm", 30.0),
            particle_size_um=params.get("particle_size_um", 25.0),
            traversing_speed_mms=params.get("traversing_speed_mms", 500.0),
            material_id=mat_code,
            num_layers=params.get("num_layers", 5),
            layer_height_mm=params.get("layer_height_mm", 2.0),
            scanning_angle_deg=params.get("scanning_angle_deg", -45.0),
            scanning_step_mm=params.get("scanning_step_mm", 2.0),
            edge_step_size_mm=params.get("edge_step_size_mm", 2.0),
            tilt_angle_deg=params.get("tilt_angle_deg", 60.0),
            buffer_additive_mm=params.get("buffer_additive_mm", 2.0),
            buffer_repairing_mm=params.get("buffer_repairing_mm", 0.0),
            link_path_free_dist_mm=params.get("link_path_free_dist_mm", 20.0),
            obstacle_resolution_mm=params.get("obstacle_resolution_mm", 2.0),
        )

    def _switch_to_step(self, page: int) -> None:

        if page == PAGE_MORPH and not self._session.output.path_output_ready:
            self._sb.showMessage("请先完成路径规划：加载点云 → 框选缺陷 → 点击「开始修复」", 5000)
            return
        if page == PAGE_OUTPUT and not self._session.output.path_output_ready:
            self._sb.showMessage("请先完成路径规划与形貌预测：加载点云 → 框选缺陷 → 点击「开始修复」", 5000)
            return
        self._mode_stack.setCurrentIndex(page)
        self._update_step_buttons()
        if page == PAGE_PATH:
            self._sb.showMessage("路径规划 — 加载点云并生成修复路径")
        elif page == PAGE_OUTPUT:
            self._sb.showMessage("输出交付 — 导出 G-code / 机器人轨迹 / PDF 报告")
        else:
            self._refresh_morph_status()
            self._sb.showMessage("形貌预测 — 基于路径规划输出执行沉积预测")

    def _update_step_buttons(self) -> None:
        """根据当前步骤和输出状态更新按钮样式。"""
        current = self._mode_stack.currentIndex()
        morph_done = self._session.morphology.repair_xyz is not None
        mode_name = "增材模式" if self._session.repair_mode == MODE_ADDITIVE else "修复模式"

        if current == PAGE_PATH:
            if self._session.output.path_output_ready:
                self._step1_btn.setStyleSheet(_STEP_DONE)
                self._step1_btn.setText("✓ 01  数据与路径\n路径已生成，可进入预测")
            else:
                self._step1_btn.setStyleSheet(_STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6"))
                self._step1_btn.setText("01  数据与路径\n加载点云、选区、生成路径")

            if self._session.output.path_output_ready:
                self._style_workflow_label(self._step2_btn, "active")
                self._step2_btn.setText("02  形貌预测\n航点就绪，自动执行中")
                self._arrow_lb.setStyleSheet(_ARROW_READY)
            else:
                self._style_workflow_label(self._step2_btn, "locked")
                self._step2_btn.setText("02  形貌预测\n等待路径规划输出")
                self._arrow_lb.setStyleSheet(_ARROW)
        elif current == PAGE_MORPH:
            # 在形貌预测步骤
            self._step1_btn.setStyleSheet(_STEP_DONE)
            self._step1_btn.setText("✓ 01  数据与路径\n路径已生成")
            if morph_done:
                self._style_workflow_label(self._step2_btn, "done")
                self._step2_btn.setText("✓ 02  形貌预测\n预测已完成")
            else:
                self._style_workflow_label(self._step2_btn, "active")
                self._step2_btn.setText("02  形貌预测\n沉积模拟中")
            self._arrow_lb.setStyleSheet(_ARROW_READY)
        else:
            # 在输出交付步骤
            self._step1_btn.setStyleSheet(_STEP_DONE)
            self._step1_btn.setText("✓ 01  数据与路径\n路径已生成")
            self._style_workflow_label(self._step2_btn, "done" if morph_done else "active")
            self._step2_btn.setText("✓ 02  形貌预测\n预测已完成" if morph_done else "02  形貌预测\n沉积模拟中")
            self._arrow_lb.setStyleSheet(_ARROW_READY)

        if hasattr(self, "_step3_lb"):
            if morph_done:
                self._style_workflow_label(self._step3_lb, "done")
                self._step3_lb.setText("✓ 03  结果校核\n指标、截面和风险已更新")
            elif self._session.output.path_output_ready:
                self._style_workflow_label(self._step3_lb, "active")
                self._step3_lb.setText("03  结果校核\n建议先做可行性检查")
            else:
                self._style_workflow_label(self._step3_lb, "locked")
                self._step3_lb.setText("03  结果校核\n等待路径与预测结果")

        if hasattr(self, "_step4_btn"):
            if not self._session.output.path_output_ready:
                self._step4_btn.setEnabled(False)
                self._step4_btn.setStyleSheet(_STEP_LOCKED)
                self._step4_btn.setText("04  输出交付\n等待路径规划完成")
            elif current == PAGE_OUTPUT:
                self._step4_btn.setEnabled(True)
                self._step4_btn.setStyleSheet(_STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6"))
                self._step4_btn.setText("04  输出交付\n导出 G-code 与报告")
            elif morph_done:
                self._step4_btn.setEnabled(True)
                self._step4_btn.setStyleSheet(_STEP_DONE)
                self._step4_btn.setText("✓ 04  输出交付\n可导出 G-code 与报告")
            else:
                self._step4_btn.setEnabled(True)
                self._step4_btn.setStyleSheet(_STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6"))
                self._step4_btn.setText("04  输出交付\n可导出 G-code 与报告")

        if hasattr(self, "_lb_mode_state"):
            self._lb_mode_state.setText(mode_name)
        if hasattr(self, "_lb_workflow_state"):
            if self._session.is_busy:
                self._lb_workflow_state.setText("计算中")
            elif morph_done:
                self._lb_workflow_state.setText("交付就绪")
            elif self._session.output.path_output_ready:
                self._lb_workflow_state.setText("等待形貌预测")
            elif self._session.point_cloud.xyz is not None:
                self._lb_workflow_state.setText("等待选区/路径")
            else:
                self._lb_workflow_state.setText("等待数据")

    @staticmethod
    def _style_workflow_label(label: QLabel, state: str) -> None:
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

    def _refresh_morph_status(self) -> None:
        """更新形貌预测面板的输入状态显示。"""
        pl_file = os.path.exists(_POINTLIST_FILE)
        vl_file = os.path.exists(_VELOCITYLIST_FILE)

        if self._session.waypoint.mock is not None and len(self._session.waypoint.mock) > 0:
            n_wp = len(self._session.waypoint.mock)
            source = "文件" if (pl_file or vl_file) else "内存"
            self._lb_pl_status.setText(f"✅ 航点数据就绪 ({n_wp:,} 个)")
            self._lb_pl_status.setStyleSheet("color:#10B981; font-size:13px;")
            self._lb_input_source.setText(f"来源: {source}")
            if pl_file:
                self._lb_input_source.setText(f"来源: 内存 (MATLAB Pipeline)")
            elif self._session.output.files_saved is False and self._session.waypoint.mock is not None:
                self._lb_input_source.setText("来源: 内存（未保存到文件）")
        else:
            self._lb_pl_status.setText("⏳ 请先完成路径规划")
            self._lb_pl_status.setStyleSheet("color:#F59E0B; font-size:13px;")
            self._lb_input_source.setText("来源: —")

        ready = self._session.waypoint.mock is not None and len(self._session.waypoint.mock) > 0
        if self._session.is_busy:
            return
        self._btn_fix.setEnabled(ready)
        self._btn_feas.setEnabled(ready)

    def _set_busy(self, busy: bool) -> None:
        self._session.is_busy = busy
        self._update_step_buttons()
        # 联动状态栏 BusyIndicator
        if hasattr(self, "_busy_label"):
            if busy:
                self._busy_label.set_busy(True, "处理中...")
            else:
                self._busy_label.set_busy(False, "就绪")
        if busy:
            for btn in (
                self._btn_start_repair,
                self._btn_exp_gcode,
                self._btn_fix,
                self._btn_feas,
                self._btn_exp_pdf,
            ):
                btn.setEnabled(False)
            return

        can_path = self._session.point_cloud.xyz is not None
        if can_path and self._session.repair_mode == MODE_REPAIRING:
            sel_mask = self._selector.get_selection_mask() if self._selector else None
            can_path = bool(sel_mask is not None and np.any(sel_mask))
        self._btn_start_repair.setEnabled(can_path)
        # P5-4: 从注册表动态启用/禁用导出按钮
        if hasattr(self, "_export_buttons"):
            for exporter in ExporterRegistry.list():
                btn = self._export_buttons.get(exporter.name)
                if btn is not None:
                    btn.setEnabled(exporter.is_ready(self._session))
        self._refresh_morph_status()
        self._update_step_buttons()

    def _fallback_waypoints(self, sel_mask: np.ndarray) -> np.ndarray:
        base = self._session.point_cloud.xyz[sel_mask]
        x_min, y_min = np.min(base[:, :2], axis=0)
        x_max, y_max = np.max(base[:, :2], axis=0)
        z_base = float(np.max(base[:, 2]))
        waypoints = []
        for i in range(6):
            y = y_min + (y_max - y_min) * i / 5
            xs = np.linspace(x_min, x_max, 15) if i % 2 == 0 else np.linspace(x_max, x_min, 15)
            waypoints.append(np.column_stack([xs, np.full(15, y), np.full(15, z_base + 0.2)]))
        return np.vstack(waypoints)

    def _finish_path_planning(
        self,
        waypoints: np.ndarray,
        sel_mask: np.ndarray,
        show_dialog: bool = True,
        *,
        metrics: dict | None = None,
        waypoint_layers: np.ndarray | None = None,
        full_waypoints: np.ndarray | None = None,
    ) -> None:
        self._session.waypoint.mock = waypoints
        self._session.waypoint.full = full_waypoints  # 含法向量，供喷嘴方向可视化
        self._session.waypoint.layers = waypoint_layers  # P2-1: 保存层号供 G-code 分层导出
        n_wp = len(self._session.waypoint.mock)
        self._session.waypoint.velocity_list = ["v500"] * n_wp

        save_to_disk = self._chk_save_files.isChecked()
        if save_to_disk:
            self._lb_prog.setText("正在缓存航点数据...")
            try:
                self._file_service.save_waypoints(self._session.waypoint.mock, self._session.waypoint.velocity_list)
                self._session.output.files_saved = True
                info(f"已缓存航点: pointlist.npz ({n_wp} 航点), velocitylist.json (临时目录)")
            except Exception as e:
                self._session.output.files_saved = False
                log_error(f"缓存文件失败: {e}")
                _show_error(self, "缓存失败", e)
        else:
            self._session.output.files_saved = False
            info("跳过文件保存（仅保留在内存中）")

        self._session.output.path_output_ready = True
        # 若远程结果带逐层信息，构建真实逐层动画（替代伪造插值）
        layers = None
        if waypoint_layers is not None and len(waypoint_layers) == n_wp:
            layers = self._build_layers_from_waypoints(
                self._session.waypoint.mock, waypoint_layers
            )
        self._visualizer.set_data(
            substrate=self._session.point_cloud.xyz, defect_mask=sel_mask,
            repair=None, waypoints=self._session.waypoint.mock, layers=layers,
        )
        # 传递喷嘴方向向量（含法向量的完整航点）供 quiver3 原生可视化
        if full_waypoints is not None and full_waypoints.shape[1] >= 6:
            self._visualizer.set_nozzle_orientations(
                full_waypoints[:, :3], full_waypoints[:, 3:6],
            )
        self._update_section_views(sel_mask)

        # 填充右侧度量面板（MATLAB 计算引擎返回的真实指标）
        self._apply_result_metrics(metrics, n_wp, waypoint_layers)

        # P2-2: 路径规划结果检查（连续性/法向稳定/层正确性）
        self._inspect_path_result(waypoint_layers)

        self._prog.setValue(100)
        self._set_busy(False)
        self._refresh_morph_status()

        file_msg = "已保存到 形貌预测/ 目录" if self._session.output.files_saved else "仅保留在内存中（未存文件）"
        self._lb_prog.setText("✅ 路径规划完成，自动进入形貌预测...")
        self._sb.showMessage(f"路径规划完成 – {n_wp} 个航点 – {file_msg}", 3000)

        # Pipeline: 本地引擎路径推进（ZMQ 路径由 _on_compute_stage 管理）
        if metrics is None:
            self._pipeline.set_done(1)      # 路径规划完成
            self._pipeline.set_running(2)   # 形貌预测执行中
            # PR1-7: 本地引擎自动串联形貌预测
            QTimer.singleShot(100, self._on_fix)

    def _inspect_path_result(self, waypoint_layers: np.ndarray | None) -> None:
        """P2-2: 路径规划结果检查 — 连续性/法向稳定/层正确性。

        检查结果写入日志，warning 通过状态栏提示，error 阻断后续流程。
        不修改 UI 布局，仅状态反馈。
        """
        from repair_app.core.path_inspector import inspect_path
        wp = self._session.waypoint.mock
        if wp is None or len(wp) < 2:
            return
        # 提取法向量（仅 ZMQ 路径有完整航点含法向）
        normals = None
        if self._session.waypoint.full is not None and self._session.waypoint.full.shape[1] >= 6:
            normals = self._session.waypoint.full[:, 3:6]
        result = inspect_path(
            wp,
            normals=normals,
            layer_indices=waypoint_layers,
            expected_n_layers=self._sp_max_layers.value() if hasattr(self, "_sp_max_layers") else None,
            expected_layer_height=float(self._collect_params().get("layer_height_mm", 2.0)),
        )
        # 写日志
        if result.warning_messages:
            for msg in result.warning_messages:
                from repair_app.utils.logger_config import info as _log_info
                _log_info(f"[PathInspect] {msg}")
            self._sb.showMessage(
                f"路径检查: {len(result.warning_messages)} 项警告（详见日志）", 4000
            )
        if result.error_messages:
            for msg in result.error_messages:
                log_error(f"[PathInspect] {msg}")

    def _build_layers_from_waypoints(
        self, waypoints: np.ndarray, waypoint_layers: np.ndarray
    ) -> list[np.ndarray] | None:
        """按层号聚合航点，构建逐层累积动画帧（真实沉积进程）。

        替代旧的 _build_morph_layers 伪造线性插值。每帧包含到当前层为止的全部航点，
        末帧为完整路径。层间 Z 高度由航点实际 Z 值驱动。
        """
        if waypoints is None or len(waypoints) == 0 or waypoint_layers is None:
            return None
        layers = np.asarray(waypoint_layers).astype(int)
        unique_layers = sorted(np.unique(layers).tolist())
        if len(unique_layers) < 2:
            return None
        frames = []
        for end_layer in unique_layers:
            mask = layers <= end_layer
            if np.any(mask):
                frames.append(waypoints[mask].copy())
        return frames if len(frames) >= 2 else None

    def _apply_result_metrics(
        self,
        metrics: dict | None,
        n_wp: int,
        waypoint_layers: np.ndarray | None,
    ) -> None:
        """将 MATLAB 计算引擎返回的度量填入右侧面板。"""
        if not metrics:
            return
        mass_g = float(metrics.get("estimated_mass_g", 0.0) or 0.0)
        time_s = float(metrics.get("estimated_time_s", 0.0) or 0.0)
        unif = float(metrics.get("uniformity_score", 0.0) or 0.0)
        if mass_g > 0:
            self._lb_mass.setText(f"材料用量: {mass_g:.3f} g")
        if time_s > 0:
            self._lb_time.setText(f"预计耗时: {time_s:.2f} s")
        if unif > 0:
            self._lb_unif.setText(f"均匀性: {unif:.1%}")
        # 逐层轮廓数（若有）
        layer_profiles = metrics.get("layer_profiles") or []
        if layer_profiles and waypoint_layers is not None:
            n_layers = len(np.unique(np.asarray(waypoint_layers).astype(int)))
            self._lb_lay.setText(f"修复层数: {n_layers}")

    def _build_morph_layers(self, repair_pts: np.ndarray) -> list[np.ndarray] | None:
        if repair_pts is None or len(repair_pts) == 0:
            return None
        total_h = self._sp_max_layers.value() * 0.3
        layers = []
        for f in range(60):
            frac = (f + 1) / 60
            frame_pts = repair_pts.copy()
            frame_pts[:, 2] = np.min(frame_pts[:, 2]) + frac * total_h
            layers.append(frame_pts)
        return layers

    def _finish_morphology(self, repair_pts: np.ndarray, sel_mask: np.ndarray) -> None:
        self._session.morphology.repair_xyz = np.vstack([self._session.point_cloud.xyz, repair_pts])
        layers = self._build_morph_layers(repair_pts)
        self._visualizer.set_data(
            substrate=self._session.point_cloud.xyz, defect_mask=sel_mask,
            repair=repair_pts, waypoints=self._session.waypoint.mock, layers=layers,
        )
        self._update_section_views(sel_mask)

        rc = len(repair_pts)
        self._lb_prog.setText("✅ 形貌预测完成")
        self._sb.showMessage(f"形貌预测完成 – {rc:,} 个沉积点")
        self._lb_vol.setText(f"填充点数: {rc:,} pts")
        self._lb_lay.setText(f"修复层数: {self._sp_max_layers.value()}")
        self._lb_feas.setText(
            f"可行性: {'✓' if self._session.feas_result is None or self._session.feas_result.feasible else '✗'}"
        )
        self._prog.setValue(100)
        self._set_busy(False)

        # Pipeline: 形貌预测完成 → 结果生成执行中
        self._pipeline.set_done(2)      # 形貌预测完成
        self._pipeline.set_running(3)   # 结果生成执行中

        # PR1-7: 形貌预测完成后自动生成 PDF 报告
        self._lb_prog.setText("✅ 形貌预测完成，正在自动生成报告...")
        QTimer.singleShot(100, self._auto_generate_report)

    def _compute_defect_metrics(self, sel_mask: np.ndarray) -> dict:
        if self._session.point_cloud.xyz is None or not np.any(sel_mask):
            return {
                "point_count": 0,
                "depth_mm": 0.0,
                "area_mm2": 0.0,
                "volume_mm3": 0.0,
            }
        pts = self._session.point_cloud.xyz[sel_mask]
        x_min, y_min = np.min(pts[:, :2], axis=0)
        x_max, y_max = np.max(pts[:, :2], axis=0)
        z_min = float(np.min(pts[:, 2]))
        z_max = float(np.max(pts[:, 2]))
        area = float(max(x_max - x_min, 0.0) * max(y_max - y_min, 0.0))
        depth = max(z_max - z_min, 0.0)
        return {
            "point_count": int(len(pts)),
            "depth_mm": depth,
            "area_mm2": area,
            "volume_mm3": area * depth * 0.5,
        }

    def _compute_path_metrics(self) -> dict:
        if self._session.waypoint.mock is None or len(self._session.waypoint.mock) < 2:
            return {"path_length_mm": 0.0, "estimated_time_s": 0.0}
        seg = np.linalg.norm(np.diff(self._session.waypoint.mock[:, :3], axis=0), axis=1)
        length = float(np.sum(seg))
        speed = max(float(self._collect_params().get("traversing_speed_mms", 500.0)), 1e-6)
        return {
            "path_length_mm": length,
            "estimated_time_s": length / speed,
        }

    def _compute_layer_data(self) -> list[dict]:
        """P2-4: 计算逐层沉积数据（真实层信息）。

        优先使用 _waypoint_layers（MATLAB 远程结果），否则按 Z 坐标分层推断。
        """
        if self._session.waypoint.mock is None or len(self._session.waypoint.mock) == 0:
            return []
        wp = self._session.waypoint.mock
        layer_height = float(self._collect_params().get("layer_height_mm", 2.0))
        # 优先使用真实层号
        if self._session.waypoint.layers is not None and len(self._session.waypoint.layers) == len(wp):
            layers_arr = np.asarray(self._session.waypoint.layers, dtype=int)
            unique_layers = np.unique(layers_arr)
        else:
            # 按 Z 坐标推断层号
            z_vals = wp[:, 2]
            z_base = float(np.min(z_vals))
            layers_arr = ((z_vals - z_base) / max(layer_height, 1e-6)).astype(int)
            unique_layers = np.unique(layers_arr)
        result = []
        for lid in unique_layers:
            mask = layers_arr == lid
            pts = wp[mask]
            if len(pts) == 0:
                continue
            result.append({
                "points": int(len(pts)),
                "avg_height": float(np.mean(pts[:, 2])),
                "mass_g": float(len(pts) * 1e-4),  # 估算：点数 × 单点质量
            })
        return result

    def _compute_statistics_data(self, defect_metrics: dict, path_metrics: dict) -> dict:
        """P2-4: 计算统计信息（真实数据）。"""
        wp = self._session.waypoint.mock
        stats = {}
        if wp is not None and len(wp) > 0:
            seg = np.linalg.norm(np.diff(wp[:, :3], axis=0), axis=1) if len(wp) > 1 else np.array([0.0])
            stats["航点总数"] = f"{len(wp):,}"
            stats["平均段间距"] = f"{float(np.mean(seg)):.3f} mm"
            stats["最大段间距"] = f"{float(np.max(seg)):.3f} mm"
            stats["最小段间距"] = f"{float(np.min(seg)):.3f} mm"
            stats["路径标准差"] = f"{float(np.std(seg)):.3f} mm"
        if self._session.morphology.repair_xyz is not None and len(self._session.morphology.repair_xyz) > 0:
            rz = self._session.morphology.repair_xyz[:, 2]
            stats["沉积高度均值"] = f"{float(np.mean(rz)):.3f} mm"
            stats["沉积高度范围"] = f"{float(np.ptp(rz)):.3f} mm"
        stats["缺陷体积"] = f"{defect_metrics['volume_mm3']:.2f} mm³"
        stats["路径总长"] = f"{path_metrics['path_length_mm']:.2f} mm"
        stats["预计加工时间"] = f"{path_metrics['estimated_time_s']:.1f} s"
        return stats

    def _compute_quality_data(self) -> dict:
        """P2-4: 计算质量评估数据（真实数据）。"""
        quality = {}
        # 可行性评分
        if self._session.feas_result is not None:
            quality["可行性评分"] = f"{self._session.feas_result.score:.1%}"
            quality["可行性结论"] = "通过" if self._session.feas_result.feasible else "不通过"
        # 形貌预测来源标记
        quality["形貌预测来源"] = "mock（本地启发式）" if self._session.morphology.is_mock else "MATLAB 物理模型"
        # 覆盖率（修复点数 / 缺陷点数）
        if self._session.morphology.repair_xyz is not None and self._session.point_cloud.xyz is not None and self._session.selection.mask is not None:
            defect_pts = int(np.sum(self._session.selection.mask))
            repair_pts = len(self._session.morphology.repair_xyz)
            if defect_pts > 0:
                quality["覆盖率"] = f"{repair_pts / defect_pts:.1%}"
        # 均匀性评分（来自 MATLAB 远程结果，若有）
        if hasattr(self, "_profile_panel") and self._profile_panel is not None:
            try:
                profile_data = self._profile_panel.get_profile_result()
                if profile_data and "uniformity_score" in profile_data:
                    quality["均匀性评分"] = f"{profile_data['uniformity_score']:.1%}"
            except Exception as exc:
                warning(f"读取质量数据失败: {exc}")
        return quality

    # ========== Event Handlers ==========
    @Slot(object)
    def _on_selection_changed(self, mask: np.ndarray) -> None:
        n_sel = int(np.sum(mask))
        self._lb_sel.setText(f"已选: {n_sel}")
        if self._session.is_busy:
            return
        if self._session.repair_mode == MODE_ADDITIVE:
            self._btn_start_repair.setEnabled(self._session.point_cloud.xyz is not None)
        else:
            self._btn_start_repair.setEnabled(n_sel >= 3)

    def _on_material_changed(self, idx: int) -> None:
        db = _Coord.get_material_database()
        key = _MAT_KEY_MAP.get(idx, "STEEL_316L")
        mat = db.get(key)
        self._lb_mat_info.setText(
            f"v_cr: {mat.v_cr_base_ms:.0f} m/s | 密度: {mat.density_kgm3:.0f} kg/m³"
        )
        self._cs_fields["critical_velocity"].setValue(mat.v_cr_base_ms)
        self._feasibility_checker = _Coord.create_feasibility_checker(mat)

    @Slot()
    def _on_feasibility_check(self) -> None:
        sel_points = self._selector.get_selected_points()
        if len(sel_points) < 3:
            self._sb.showMessage("请至少选取 3 个点再执行可行性检查", 5000)
            Toast.warning(self, "选区不足：请至少选取 3 个点")
            return
        params = self._collect_params()
        result = self._feasibility_checker.check_from_cloud(
            selected_points=sel_points,
            nozzle_diameter_mm=params["nozzle_diameter_mm"],
            spray_angle_deg=params["spray_angle_deg"],
            particle_velocity_ms=params["particle_velocity_ms"],
        )
        self._session.feas_result = result
        _WL = _Coord.WarningLevel
        color = {_WL.OK: "#10B981", _WL.WARNING: "#F59E0B", _WL.BLOCKED: "#EF4444"}
        level_names = {_WL.OK: "✅ 可行", _WL.WARNING: "⚠️ 有条件可行", _WL.BLOCKED: "❌ 不可行"}
        self._lb_feas_status.setText(f"状态: {level_names.get(result.overall_level, '未知')}")
        self._lb_feas_score.setText(f"评分: {result.score:.1%}")
        self._lb_feas.setText(f"可行性: {'✓' if result.feasible else '✗'}")
        lines = [f"【{result.summary}】\n"]
        for w in result.warnings:
            icon = {"ok": "✅", "warning": "⚠️", "blocked": "🚫"}.get(w.level.value, "•")
            lines.append(f"{icon} [{w.code}] {w.message}")
            if w.detail: lines.append(f"   详情: {w.detail}")
            if w.suggestion: lines.append(f"   建议: {w.suggestion}")
            lines.append("")
        self._feas_text.setPlainText("\n".join(lines))
        self._lb_feas_status.setStyleSheet(
            f"color:{color.get(result.overall_level, '#64748B')}; font-weight:bold; font-size:14px;"
        )
        self._lb_feas_score.setStyleSheet(
            f"color:{color.get(result.overall_level, '#64748B')}; font-size:16px; font-weight:bold;"
        )
        self._sb.showMessage(f"可行性检查完成: {result.summary}")

    @Slot()
    def _on_load(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(
            self, "加载点云", "",
            "点云文件 (*.csv *.txt *.xyz *.asc);;所有文件 (*)"
        )
        if fp:
            try:
                self._sb.showMessage(f"加载中: {os.path.basename(fp)}...")
                xyz, normals = self._file_service.load_point_cloud(fp)
                self._session.point_cloud.xyz = xyz
                self._session.point_cloud.path = fp
                if normals is not None:
                    self._session.point_cloud.normals = normals
                else:
                    self._session.point_cloud.normals = self._est_normals(self._session.point_cloud.xyz)
                self._reset_output()
                pts_with_normals = np.hstack([self._session.point_cloud.xyz, self._session.point_cloud.normals])
                self._selector.set_points(pts_with_normals)
                self._lb_pts.setText(f"点数: {len(self._session.point_cloud.xyz):,}")
                self._btn_start_repair.setEnabled(True)
                proj_name = os.path.splitext(os.path.basename(fp))[0]
                self._project_manager.new_project(proj_name)
                self._lb_project.setText(f"项目: {proj_name}")
                info(f"点云已加载: {os.path.basename(fp)} ({len(self._session.point_cloud.xyz):,} 点)")
                self._sb.showMessage(f"已加载: {os.path.basename(fp)} ({len(self._session.point_cloud.xyz):,} 点)")
                # Pipeline: 导入点云完成
                self._pipeline.set_done(0)
            except Exception as e:
                _show_error(self, "加载失败", e)
        else:
            # 未选择文件：静默返回（演示数据已在启动时自动加载）
            self._sb.showMessage("已取消加载", 2000)

    def _load_demo(self) -> None:
        pts, normals, _, _ = _Coord.generate_sample_defect(
            defect_types=["pit"], seed=self._session.latest_seed, n_points=8000
        )
        self._session.point_cloud.xyz = pts
        self._session.point_cloud.normals = normals
        self._reset_output()
        pts_with_normals = np.hstack([self._session.point_cloud.xyz, self._session.point_cloud.normals])
        self._selector.set_points(pts_with_normals)
        self._lb_pts.setText(f"点数: {len(self._session.point_cloud.xyz):,}")
        self._btn_start_repair.setEnabled(True)
        info(f"演示数据已加载 ({len(self._session.point_cloud.xyz):,} 点)")
        self._sb.showMessage(f"演示数据已加载 ({len(self._session.point_cloud.xyz):,} 点)")
        # Pipeline: 导入点云完成
        self._pipeline.set_done(0)

    def _reset_output(self) -> None:
        self._session.morphology.repair_xyz = None
        self._session.waypoint.mock = None
        self._session.waypoint.full = None
        self._session.waypoint.layers = None  # P2-1: 重置层号
        self._session.waypoint.velocity_list = None
        self._session.output.path_output_ready = False
        self._session.output.files_saved = False
        # P5-4: 从注册表统一禁用所有导出按钮
        if hasattr(self, "_export_buttons"):
            for btn in self._export_buttons.values():
                btn.setEnabled(False)
        self._btn_fix.setEnabled(False)
        self._btn_feas.setEnabled(False)
        self._update_step_buttons()

    def _est_normals(self, xyz, k=30):
        return _Coord.estimate_normals(xyz, k=k)

    def _update_section_views(self, sel_mask: np.ndarray) -> None:
        """更新右侧辅助截面面板。"""
        if self._session.waypoint.mock is None or len(self._session.waypoint.mock) == 0:
            return
        self._lb_bottom_status.setText("辅助截面视图已更新")
        self._lb_bottom_status.setStyleSheet(
            "color:#10B981; font-size:12px; padding:4px; font-weight:bold;"
        )
        self._update_path_section(sel_mask)
        self._update_morph_section(sel_mask)

    def _style_aux_axis(self, ax, title: str) -> None:
        ax.clear()
        ax.set_facecolor("#0F172A")
        ax.set_title(title, color="#94A3B8", fontsize=10)
        ax.tick_params(colors="#64748B", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.grid(True, color="#1E293B", alpha=0.5)

    def _finish_aux_axis(self, ax) -> None:
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(
                handles, labels, fontsize=7, loc="upper right",
                facecolor="#1E293B", edgecolor="#334155", labelcolor="#94A3B8",
            )
        self._canvas_bottom.draw_idle()

    def _update_path_section(
        self, sel_mask: np.ndarray, waypoints: np.ndarray | None = None
    ) -> None:
        """更新右侧路径截面图。"""
        wp = waypoints if waypoints is not None else self._session.waypoint.mock
        self._style_aux_axis(self._ax_path, "截面路径规划")

        if np.any(sel_mask):
            defect_pts = self._session.point_cloud.xyz[sel_mask]
            x_range = (np.min(defect_pts[:, 0]), np.max(defect_pts[:, 0]))
            z_range = (np.min(defect_pts[:, 2]), np.max(defect_pts[:, 2]))
            self._ax_path.fill_between([x_range[0]-1, x_range[1]+1],
                                       z_range[0]-1, z_range[0]-1,
                                       color="#475569", alpha=0.3, label="缺陷区域")
            self._ax_path.plot([x_range[0], x_range[1]], [z_range[0], z_range[0]],
                              color="#EF4444", linewidth=2, label="缺陷底面")

            layer_height = self._pp_fields.get("layer_height", self._sp_pp_layers)
            if hasattr(layer_height, 'value'):
                lh = layer_height.value()
            else:
                lh = 2.0
            n_layers = self._sp_pp_layers.value()
            for i in range(n_layers):
                z = z_range[0] + 0.1 + i * lh
                self._ax_path.plot([x_range[0], x_range[1]], [z, z],
                                  color="#3B82F6", alpha=0.4, linewidth=1,
                                  linestyle="--")

            if wp is not None and len(wp) > 0:
                self._ax_path.scatter(wp[:, 0], wp[:, 2], c=wp[:, 1], cmap="viridis",
                                     s=2, alpha=0.7, label="航点")
            self._ax_path.set_xlabel("X (mm)", color="#64748B", fontsize=8)
            self._ax_path.set_ylabel("Z (mm)", color="#64748B", fontsize=8)
        self._finish_aux_axis(self._ax_path)

    def _update_morph_section(
        self, sel_mask: np.ndarray, repair_pts: np.ndarray | None = None
    ) -> None:
        """更新右侧形貌截面图。"""
        if repair_pts is None and self._session.morphology.repair_xyz is not None:
            repair_pts = (
                self._session.morphology.repair_xyz[len(self._session.point_cloud.xyz):]
                if len(self._session.morphology.repair_xyz) > len(self._session.point_cloud.xyz)
                else self._session.morphology.repair_xyz
            )
        self._style_aux_axis(self._ax_morph, "形貌预测结果")

        if np.any(sel_mask):
            defect_pts = self._session.point_cloud.xyz[sel_mask]
            x_range_d = (np.min(defect_pts[:, 0]), np.max(defect_pts[:, 0]))
            z_max = np.max(defect_pts[:, 2])

            self._ax_morph.plot([x_range_d[0]-1, x_range_d[1]+1],
                               [z_max, z_max], color="#64748B", linewidth=1.5,
                               label="基体表面")
            self._ax_morph.fill_between([x_range_d[0], x_range_d[1]],
                                        z_max-1.5, z_max,
                                        color="#EF4444", alpha=0.2, label="原始缺陷")

            if repair_pts is not None and len(repair_pts) > 0:
                xs = repair_pts[:, 0]
                zs = repair_pts[:, 2]
                self._ax_morph.scatter(xs, zs, s=2, c=zs, cmap="turbo", alpha=0.65, label="沉积点")

                bins = np.linspace(x_range_d[0], x_range_d[1], 80)
                digitized = np.digitize(xs, bins)
                profile_x = []
                profile_z = []
                for idx in range(1, len(bins)):
                    in_bin = digitized == idx
                    if np.any(in_bin):
                        profile_x.append(float(np.mean(xs[in_bin])))
                        profile_z.append(float(np.max(zs[in_bin])))
                if profile_x:
                    px = np.array(profile_x)
                    pz = np.array(profile_z)
                    self._ax_morph.fill_between(px, z_max, pz, where=pz >= z_max,
                                                color="#10B981", alpha=0.28)
                    self._ax_morph.plot(px, pz, color="#10B981", linewidth=1.8,
                                        label="预测轮廓")
            else:
                self._ax_morph.text(
                    0.5, 0.5, "等待形貌预测",
                    transform=self._ax_morph.transAxes,
                    ha="center", va="center", color="#64748B", fontsize=9,
                )

            self._ax_morph.set_xlabel("X (mm)", color="#64748B", fontsize=8)
            self._ax_morph.set_ylabel("Z (mm)", color="#64748B", fontsize=8)
        self._finish_aux_axis(self._ax_morph)

    def _collect_params(self) -> dict:
    
        mat_idx = self._cb_mat.currentIndex()
        mat_name = _MATERIALS[mat_idx][0]
        ss = {k: v.value() for k, v in self._cs_fields.items()}
        pp = {k: v.value() for k, v in self._pp_fields.items()}
        return {
            "material": mat_name,
            "depth_compensation": self._sp_depth.value(),
            "max_layers": self._sp_max_layers.value(),
            "particle_velocity_ms": ss["particle_velocity"],
            "critical_velocity_ms": ss["critical_velocity"],
            "nozzle_diameter_mm": ss["nozzle_diameter"],
            "spray_angle_deg": ss["spray_angle"],
            "standoff_distance_mm": ss["standoff_distance"],
            "particle_size_um": ss["particle_size"],
            
            "gas_temperature_c": ss.get("gas_temperature", 800.0),
            "gas_pressure_bar": ss.get("gas_pressure", 40.0),
            "powder_feed_rate_gmin": ss.get("powder_feed_rate", 30.0),
            "traversing_speed_mms": ss["traversing_speed"],
            "num_layers": self._sp_max_layers.value(),
            "layer_height_mm": pp["layer_height"],
            "scanning_angle_deg": pp["scanning_angle"],
            "scanning_step_mm": pp["scanning_step"],
            "edge_step_size_mm": pp["edge_step_size"],
            "tilt_angle_deg": pp["tilt_angle"],
            "buffer_additive_mm": pp["buffer_additive"],
            "buffer_repairing_mm": pp["buffer_repairing"],
            "link_path_free_dist_mm": pp["link_free_dist"],
            "obstacle_resolution_mm": pp["obstacle_resolution"],
        }

    # ====== 一键计算（自动：MATLAB → Bridge → 路径规划 → 形貌预测 → GUI → 报告）======
    @Slot()
    def _on_start_repair(self) -> None:
        """统一主入口：根据引擎自动分流。

        本地引擎 → _on_generate_path（自动串联形貌预测）
        远程引擎 → _on_start_calculation（MATLAB 一键串联）
        """
        if self._use_zmq_engine():
            self._on_start_calculation()
        else:
            self._on_generate_path()

    def _on_start_calculation(self) -> None:
        """一键执行完整计算流程，用户无需打开 MATLAB、无需运行 main.m、无需复制中间文件。"""
        if self._session.is_busy:
            return
        if not self._license.is_valid:
            Toast.warning(self, f"License 无效：{self._license.error}")
            return
        if self._session.point_cloud.xyz is None:
            Toast.warning(self, "请先加载点云")
            return
        if self._session.repair_mode == MODE_REPAIRING:
            sel_mask = self._selector.get_selection_mask()
            if not np.any(sel_mask):
                Toast.warning(self, "请在中心视图选取缺陷区域")
                return
        else:
            sel_mask = np.ones(len(self._session.point_cloud.xyz), dtype=bool)
        self._session.selection.mask = sel_mask

        # 构造 protobuf 请求
        try:
            request = self._build_repair_request(sel_mask)
            request_bytes = request.SerializeToString()
        except Exception as e:
            _show_error(self, "请求构建失败", e)
            return
        # 确定项目根目录（matlab_bridge_server.m 所在位置）
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Pipeline: 重置 → 导入点云 完成 → 路径规划执行中
        self._pipeline.reset()
        self._pipeline.set_done(0)

        # 通过生命周期管理器确保 MATLAB + Bridge 就绪
        # MF-2: 使用 LoadingDialog 提供 Progress / Cancel / Timeout
        self._sb.showMessage("正在启动 MATLAB + Bridge（预计 60-120 秒，请耐心等待）...")
        self._prog.setValue(2)
        self._lb_prog.setText("正在启动 MATLAB + Bridge...（预计 1-2 分钟）")
        QApplication.processEvents()  # 强制刷新 UI，让用户看到进度反馈
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            from repair_app.ui.dialogs import LoadingDialog
            manager = MatlabLifecycleManager.get_instance(project_root)
            # MF-2: 用模态 LoadingDialog 包裹 ensure_ready，支持取消和超时
            loading = LoadingDialog(
                self,
                timeout_sec=int(schema_loader.get_network_value("matlab_loading_timeout_sec")),
            )
            loading.start(manager)
            loading.exec()
            if not loading.result_ok:
                self._prog.setValue(0)
                self._lb_prog.setText("MATLAB 启动失败")
                if loading.cancelled:
                    self._sb.showMessage("MATLAB 启动已取消")
                    return
                from repair_app.ui.dialogs import ErrorDialog
                ErrorDialog.show(
                    self,
                    title="MATLAB 不可用",
                    what="软件无法启动 MATLAB 计算服务。",
                    why=f"可能原因：{loading.result_msg}",
                    how="1. 确认 MATLAB 已安装且可正常启动\n"
                        "2. 让管理员设置环境变量 CSAM_MATLAB_EXE 指向 matlab.exe 路径\n"
                        "3. 确认 MATLAB 许可证有效\n"
                        "4. 如果反复超时，联系管理员检查 MATLAB 启动速度",
                )
                return
        except Exception as exc:
            log_error(f"MATLAB 启动异常: {exc}")
            self._prog.setValue(0)
            self._lb_prog.setText("MATLAB 启动异常")
            from repair_app.ui.dialogs import ErrorDialog
            ErrorDialog.show(
                self,
                title="MATLAB 启动异常",
                what="MATLAB 启动过程中发生错误。",
                why=f"错误详情：{exc}",
                how="请让管理员检查 MATLAB 环境后重试。",
                exc=exc,
            )
            return

        self._sb.showMessage("一键计算：MATLAB 已就绪，正在执行...")
        self._prog.setValue(5)
        self._lb_prog.setText("正在执行计算...")
        self._set_busy(True)

        # 标记 MATLAB 为 BUSY 状态（暂停崩溃检测，避免误判）
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            MatlabLifecycleManager.get_instance(project_root).mark_busy()
        except Exception as e:
            log_error(f"标记 MATLAB BUSY 状态失败: {e}")

        self._visualizer.set_data(
            substrate=self._session.point_cloud.xyz, defect_mask=sel_mask,
            repair=None, waypoints=None, layers=None,
        )

        # 启动实时进度订阅（监听 MATLAB 逐步发布的进度）
        self._start_progress_subscriber()

        # 防御性检查：确保前一个计算线程已完成
        if self._compute_thread is not None and self._compute_thread.isRunning():
            Toast.warning(self, "上一次计算仍在进行中，请等待完成")
            self._set_busy(False)
            return

        from repair_app.ui.workers import ComputePipelineWorker
        self._compute_thread = QThread(self)
        self._compute_worker = ComputePipelineWorker(
            project_root=project_root,
            request_bytes=request_bytes,
        )
        self._compute_worker.moveToThread(self._compute_thread)
        self._compute_thread.started.connect(self._compute_worker.run)
        self._compute_worker.stage.connect(self._on_compute_stage)
        self._compute_worker.result.connect(self._on_compute_result)
        self._compute_worker.failed.connect(self._on_compute_failed)
        self._compute_worker.result.connect(self._compute_thread.quit)
        self._compute_worker.failed.connect(self._compute_thread.quit)
        self._compute_thread.finished.connect(self._compute_worker.deleteLater)
        self._compute_thread.finished.connect(self._compute_thread.deleteLater)
        self._compute_thread.finished.connect(self._on_compute_thread_finished)
        self._compute_thread.start()

    @Slot(str)
    def _on_compute_stage(self, stage: str) -> None:
        """计算管线阶段进度更新。"""
        self._lb_prog.setText(stage)
        self._sb.showMessage(stage)
        # Pipeline 指示器状态更新
        from repair_app.ui.pipeline_indicator import PipelineStage
        if "启动" in stage:
            self._prog.setValue(10)
            self._pipeline.set_running(1)   # 路径规划执行中
        elif "执行" in stage:
            self._prog.setValue(30)
            self._pipeline.set_done(1)      # 路径规划完成
            self._pipeline.set_running(2)   # 形貌预测执行中
        elif "解析" in stage:
            self._prog.setValue(80)
            self._pipeline.set_done(2)      # 形貌预测完成
            self._pipeline.set_running(3)   # 结果生成执行中

    @Slot(dict)
    def _on_compute_result(self, result: dict) -> None:
        """一键计算成功：更新 GUI + 自动生成报告。"""
        try:
            if not _Coord.is_repair_success(result):
                raise RuntimeError(result.get("error_message") or result.get("status_name"))
            waypoints = result.get("waypoints")
            if waypoints is None or len(waypoints) == 0:
                raise RuntimeError("MATLAB 返回成功，但没有航点数据")

            self._prog.setValue(85)
            self._lb_prog.setText("正在更新 GUI...")
            # Pipeline: 结果生成完成 → 导出执行中
            self._pipeline.set_done(3)
            self._pipeline.set_running(4)

            sel_mask = self._session.selection.mask
            metrics = {
                "estimated_mass_g": result.get("estimated_mass_g", 0.0),
                "estimated_time_s": result.get("estimated_time_s", 0.0),
                "uniformity_score": result.get("uniformity_score", 0.0),
                "predicted_volume_mm3": result.get("predicted_volume_mm3", 0.0),
                "layer_profiles": result.get("layer_profiles", []),
                "particle_dist": result.get("particle_dist"),
            }
            # 转发到 MATLAB 形貌分析面板
            try:
                reason = result.get("feasibility_reason", "") or ""
                warnings_list = []
                if "Warnings:" in reason:
                    warns_part = reason.split("Warnings:", 1)[1].strip()
                    warnings_list = [w.strip() for w in warns_part.split(";") if w.strip()]
                self._profile_panel.set_profile_result({
                    "mesh_bytes": result.get("mesh_bytes", b"") or b"",
                    "mesh_format": result.get("mesh_format", ""),
                    "layer_profiles": result.get("layer_profiles", []),
                    "particle_dist": result.get("particle_dist"),
                    "uniformity_score": result.get("uniformity_score", 0.0),
                    "estimated_mass_g": result.get("estimated_mass_g", 0.0),
                    "estimated_time_s": result.get("estimated_time_s", 0.0),
                    "predicted_volume_mm3": result.get("predicted_volume_mm3", 0.0),
                    "material_density_gcm3": result.get("material_density_gcm3", 0.0),
                    "compute_time_ms": result.get("compute_time_ms", 0),
                    "warnings": warnings_list,
                })
            except Exception as exc:
                log_error(f"形貌预测面板刷新失败: {exc}")

            waypoint_layers = result.get("waypoint_layers")
            full_waypoints = waypoints if waypoints.shape[1] >= 6 else None
            # 复用 _finish_path_planning 更新 3D 预览面板
            self._finish_path_planning(
                waypoints[:, :3], sel_mask,
                metrics=metrics,
                waypoint_layers=waypoint_layers,
                full_waypoints=full_waypoints,
            )

            self._prog.setValue(90)
            self._lb_prog.setText("正在生成报告...")
            self._sb.showMessage("正在自动生成 PDF 报告...")

            # 自动生成报告（不弹窗，保存到桌面）
            try:
                self._auto_generate_report()
            except Exception as exc:
                log_error(f"自动报告生成失败: {exc}")

            self._prog.setValue(100)
            self._lb_prog.setText("✅ 一键计算完成")
            self._sb.showMessage(
                f"一键计算完成 · {len(waypoints)} 航点 · "
                f"质量={metrics['estimated_mass_g']:.3f}g · "
                f"均匀性={metrics['uniformity_score']:.2f}"
            )
            info(f"一键计算完成: {len(waypoints)} 航点, "
                 f"质量={metrics['estimated_mass_g']:.3f}g, "
                 f"均匀性={metrics['uniformity_score']:.2f}")
            # Pipeline: 导出完成
            self._pipeline.set_done(4)
            self._set_busy(False)
            # 标记 MATLAB 为空闲状态（恢复崩溃检测）
            try:
                from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
                MatlabLifecycleManager.get_instance().mark_idle()
            except Exception as e:
                log_error(f"标记 MATLAB 空闲状态失败: {e}")
        except Exception as exc:
            self._set_busy(False)
            log_error(f"一键计算结果处理失败: {exc}")
            # 停止实时进度订阅 + 恢复 MATLAB 崩溃检测（与 _on_compute_failed 对齐）
            self._stop_progress_subscriber()
            try:
                from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
                MatlabLifecycleManager.get_instance().mark_idle()
            except Exception as e:
                log_error(f"标记 MATLAB 空闲状态失败: {e}")
            self._pipeline.mark_running_as_failed()
            _show_error(self, "计算失败", exc)

    @Slot(str, str, str)
    def _on_compute_failed(self, error_code: str, friendly: str, detail: str) -> None:
        """一键计算失败（结构化错误信号）。"""
        self._set_busy(False)
        self._prog.setValue(0)
        self._lb_prog.setText("❌ 计算失败")
        self._sb.showMessage("一键计算失败")
        log_error(f"一键计算失败 [{error_code}]: {friendly}\n{detail}")
        # 停止实时进度订阅
        self._stop_progress_subscriber()
        # Pipeline: 标记当前执行中的阶段为失败
        self._pipeline.mark_running_as_failed()
        # 标记 MATLAB 为空闲状态（恢复崩溃检测）
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            MatlabLifecycleManager.get_instance().mark_idle()
        except Exception as e:
            log_error(f"标记 MATLAB 空闲状态失败: {e}")
        # 显示结构化错误对话框（用户友好 + 可展开详情）
        # friendly 已包含完整 What/Why/How（来自 _pack_error）
        from repair_app.ui.dialogs import ErrorDialog
        ErrorDialog.show(
            self, title="一键计算失败", what=friendly, why="", how="",
            log_text=detail,
        )

    @Slot()
    def _on_compute_thread_finished(self) -> None:
        """计算线程结束清理。"""
        self._compute_thread = None
        self._compute_worker = None
        # 计算线程结束后停止实时进度订阅
        self._stop_progress_subscriber()

    # ========== 实时可视化：ProgressSubscriber 信号处理 ==========

    def _start_progress_subscriber(self) -> None:
        """启动实时进度订阅（计算开始时调用）。"""
        # 重置实时面板与逐层播放器
        try:
            self._realtime_stats.reset()
            self._layer_player.reset()
        except Exception as e:
            log_error(f"重置实时面板/逐层播放器失败: {e}")
        # 清空层缓存
        self._session.layer.by_layer = {}
        try:
            if self._progress_subscriber is not None and not self._progress_subscriber.is_running:
                self._progress_subscriber.start()
                info(f"实时进度订阅器已启动（ZMQ SUB {_PROGRESS_ADDRESS}）")
        except Exception as exc:
            log_error(f"启动实时进度订阅器失败: {exc}")

    def _stop_progress_subscriber(self) -> None:
        """停止实时进度订阅（计算结束/失败时调用）。"""
        try:
            if self._progress_subscriber is not None and self._progress_subscriber.is_running:
                self._progress_subscriber.stop()
                info("实时进度订阅器已停止")
        except Exception as exc:
            log_error(f"停止实时进度订阅器失败: {exc}")

    @Slot(dict)
    def _on_progress_received(self, parsed: dict) -> None:
        """收到完整 ProgressUpdate 消息：缓存该层的航点数据，供逐层查看使用。"""
        try:
            layer_idx = int(parsed.get("layer_index", 0))
            total_layers = int(parsed.get("total_layers", 0))
            waypoints = parsed.get("waypoints")
            mesh_bytes = parsed.get("partial_mesh_data", b"")

            # 更新 LayerPlayer 的总层数
            if total_layers > 0:
                self._layer_player.set_total_layers(total_layers)

            # 缓存该层数据（用于逐层查看时回放）
            self._session.layer.by_layer[layer_idx] = {
                "waypoints": waypoints,
                "mesh_bytes": mesh_bytes,
                "progress": float(parsed.get("progress", 0.0)),
                "message": str(parsed.get("message", "")),
                "stage_name": str(parsed.get("stage_name", "")),
            }

            # 实时刷新 3D 预览：航点 + mesh
            if waypoints is not None and len(waypoints) > 0:
                self._visualizer.set_partial_waypoints(waypoints)
            if mesh_bytes:
                self._visualizer.set_partial_mesh(mesh_bytes)
        except Exception as exc:
            log_error(f"处理实时进度消息异常: {exc}")

    @Slot(int)
    def _on_layer_completed(self, layer_idx: int) -> None:
        """某层完成：同步 LayerPlayer 到当前层。"""
        try:
            total = max(1, len(self._session.layer.by_layer))
            # 确保 LayerPlayer 的总层数已更新
            self._layer_player.set_total_layers(total)
            # 自动跳到最新完成的层（仅当未在手动播放时跟随）
            self._layer_player.set_current_layer(layer_idx)
        except Exception as e:
            log_error(f"更新逐层播放器状态失败: {e}")

    @Slot(bytes)
    def _on_mesh_updated(self, mesh_bytes: bytes) -> None:
        """实时 mesh 更新：直接刷新 3D 预览。"""
        try:
            if mesh_bytes:
                self._visualizer.set_partial_mesh(mesh_bytes)
        except Exception as exc:
            log_error(f"实时 mesh 刷新失败: {exc}")

    @Slot(int)
    def _on_layer_changed(self, layer_idx: int) -> None:
        """LayerPlayer 切换层号：从缓存回放该层的航点/mesh。"""
        try:
            cached = self._session.layer.by_layer.get(layer_idx)
            if not cached:
                return
            waypoints = cached.get("waypoints")
            mesh_bytes = cached.get("mesh_bytes", b"")
            # 清除 partial 并按缓存重放
            if waypoints is not None and len(waypoints) > 0:
                self._visualizer.set_partial_waypoints(waypoints)
            else:
                self._visualizer.set_partial_waypoints(None)
            if mesh_bytes:
                self._visualizer.set_partial_mesh(mesh_bytes)
            # 同步状态栏提示
            stage = cached.get("stage_name", "")
            msg = cached.get("message", "")
            self._sb.showMessage(f"Layer {layer_idx + 1} | {stage} | {msg}", 3000)
        except Exception as exc:
            log_error(f"逐层查看回放失败: {exc}")

    def _auto_generate_report(self) -> None:
        """自动生成 PDF 报告到统一导出目录（不弹文件对话框）。"""
        import datetime
        # Pipeline 注：结果生成(3)的 running 状态由调用方设置（_finish_morphology 或 _on_compute_result）
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        proj_name = self._project_manager.current_name or "repair"
        # 消除文件名中的非法字符
        safe_name = "".join(c for c in proj_name if c not in '\\/:*?"<>|')
        fp = str(self._path_manager.pdf_path(f"{safe_name}_report_{ts}"))

        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else (
            self._selector.get_selection_mask() if self._selector else np.ones(len(self._session.point_cloud.xyz), dtype=bool)
        )
        defect_metrics = self._compute_defect_metrics(sel_mask)
        path_metrics = self._compute_path_metrics()
        scan_info = {
            "scan_id": f"SCAN-{self._session.latest_seed:04d}",
            "points": len(self._session.point_cloud.xyz) if self._session.point_cloud.xyz is not None else 0,
            "defect_volume_mm3": defect_metrics["volume_mm3"],
            "defect_depth_mm": defect_metrics["depth_mm"],
            "material": self._cb_mat.currentText(),
        }
        results = {
            "填充点数": f"{len(self._session.morphology.repair_xyz) if self._session.morphology.repair_xyz is not None else 0:,}",
            "修复层数": str(self._sp_max_layers.value()),
            "缺陷选区点数": f"{defect_metrics['point_count']:,}",
            "估算缺陷面积": f"{defect_metrics['area_mm2']:.2f} mm²",
            "路径长度": f"{path_metrics['path_length_mm']:.2f} mm",
            "预计加工时间": f"{path_metrics['estimated_time_s']:.1f} s",
            "可行性评分": f"{self._session.feas_result.score:.1%}" if self._session.feas_result else "—",
        }
        # P2-4: 计算真实的 layers/statistics/quality 数据
        layers_data = self._compute_layer_data()
        statistics_data = self._compute_statistics_data(defect_metrics, path_metrics)
        quality_data = self._compute_quality_data()
        # P4-5: 报告字段统一写入 Session.report（禁止重复同步）
        self._session.report.scan_info = scan_info
        self._session.report.parameters = self._collect_params()
        self._session.report.results = results
        self._session.report.layers = layers_data
        self._session.report.statistics = statistics_data
        self._session.report.quality = quality_data
        # P4-5: 派生指标写入 Session.metrics（禁止重复计算）
        self._session.metrics.defect = defect_metrics
        self._session.metrics.path = path_metrics
        self._session.metrics.layers = layers_data
        self._session.metrics.statistics = statistics_data
        self._session.metrics.quality = quality_data
        ok = self._export_service.export_pdf_report(self._session, output_path=fp)
        if ok:
            info(f"报告已自动保存: {fp}")
            self._sb.showMessage(f"修复完成 · 报告已保存: {fp}", 5000)
            # Pipeline: 结果生成完成 → 导出就绪
            self._pipeline.set_done(3)
            self._pipeline.set_running(4)
            self._lb_prog.setText("✅ 修复完成，可导出 G-code / 报告")
            Toast.success(self, "修复完成：路径规划 → 形貌预测 → 报告均已生成，可导出交付")
        else:
            warning("PDF 报告自动生成失败")
            self._pipeline.mark_running_as_failed()
            self._lb_prog.setText("⚠ 报告自动生成失败")
            Toast.error(self, "报告自动生成失败，请查看日志")

    # ====== 步骤①：路径规划 ======
    @Slot()
    def _on_generate_path(self) -> None:
        if self._session.is_busy:
            return
        if not self._license.is_valid:
            Toast.warning(self, f"License 无效：{self._license.error}")
            return
        if self._session.point_cloud.xyz is None:
            Toast.warning(self, "请先加载点云")
            return
        if self._session.repair_mode == MODE_REPAIRING:
            sel_mask = self._selector.get_selection_mask()
            if not np.any(sel_mask):
                Toast.warning(self, "请在中心视图选取缺陷区域")
                return
        else:
            # 增材模式：全表面标记为选区
            sel_mask = np.ones(len(self._session.point_cloud.xyz), dtype=bool)
        self._session.selection.mask = sel_mask

        # Pipeline: 本地引擎路径，重置 → 导入点云完成 → 路径规划执行中
        self._pipeline.reset()
        self._pipeline.set_done(0)
        self._pipeline.set_running(1)

        self._sb.showMessage("路径规划中...")
        self._prog.setValue(10)
        self._lb_prog.setText("正在生成修复路径...")
        self._set_busy(True)
        self._visualizer.set_data(
            substrate=self._session.point_cloud.xyz, defect_mask=sel_mask,
            repair=None, waypoints=None, layers=None,
        )

        if self._use_zmq_engine():
            try:
                request = self._build_repair_request(sel_mask)
            except Exception as e:
                self._set_busy(False)
                _show_error(self, "请求构建失败", e)
                return
            self._lb_prog.setText("正在请求远程服务...")
            self._sb.showMessage("正在向远程服务发送计算请求...")
            self._zmq_client.request_repair(
                request,
                self._on_zmq_path_result,
                self._on_zmq_path_error,
            )
            return

        params = self._collect_params()
        buffer_mm = (
            params.get("buffer_additive_mm", 2.0)
            if self._session.repair_mode == MODE_ADDITIVE
            else params.get("buffer_repairing_mm", 0.0)
        )
        # 防御性检查：确保前一个路径规划线程已完成
        if self._path_thread is not None and self._path_thread.isRunning():
            Toast.warning(self, "路径规划仍在进行中，请等待完成")
            self._set_busy(False)
            return
        self._path_thread = QThread(self)
        self._path_worker = PathPlanningWorker(
            self._session, params, self._sp_pp_layers.value(), buffer_mm
        )
        self._path_worker.moveToThread(self._path_thread)
        self._path_thread.started.connect(self._path_worker.run)
        self._path_worker.partial.connect(self._on_path_partial)
        self._path_worker.finished.connect(self._on_path_finished)
        self._path_worker.failed.connect(self._on_path_failed)
        self._path_worker.finished.connect(self._path_thread.quit)
        self._path_worker.failed.connect(self._path_thread.quit)
        self._path_thread.finished.connect(self._path_worker.deleteLater)
        self._path_thread.finished.connect(self._path_thread.deleteLater)
        self._path_thread.finished.connect(self._on_path_thread_finished)
        self._path_thread.start()

    # ====== 步骤②：形貌预测 ======
    @Slot()
    def _on_fix(self) -> None:
        if self._session.is_busy:
            return
        if not self._license.is_valid:
            Toast.warning(self, f"License 无效：{self._license.error}")
            return
        if self._session.point_cloud.xyz is None:
            Toast.warning(self, "请先加载点云")
            return
        sel_mask = self._selector.get_selection_mask()
        if not np.any(sel_mask):
            Toast.warning(self, "请在中心视图选取缺陷区域")
            return
        self._session.selection.mask = sel_mask  # P4-4: 同步到 Session 供 MorphologyWorker 读取

        # 优先使用内存中的航点；仅在内存丢失时从缓存目录恢复
        if (self._session.waypoint.mock is None or len(self._session.waypoint.mock) == 0) and \
           self._file_service.has_saved_waypoints():
            try:
                loaded = self._file_service.load_waypoints()
                if loaded is not None:
                    self._session.waypoint.mock = loaded
                    info(f"从缓存目录恢复航点: {len(self._session.waypoint.mock)} 个")
            except Exception as e:
                log_error(f"加载航点文件失败: {e}")

        if self._session.waypoint.mock is None or len(self._session.waypoint.mock) == 0:
            Toast.warning(self, "未找到航点数据，请先执行路径规划")
            return

        params = self._collect_params()
        info("形貌预测开始")
        # Pipeline: 路径规划完成 → 形貌预测执行中
        self._pipeline.set_done(1)
        self._pipeline.set_running(2)
        self._sb.showMessage("形貌预测中...")
        self._prog.setValue(20)
        self._lb_prog.setText("模拟沉积中...")
        self._set_busy(True)
        self._visualizer.set_data(
            substrate=self._session.point_cloud.xyz, defect_mask=sel_mask,
            repair=None, waypoints=self._session.waypoint.mock, layers=None,
        )
        # 防御性检查：确保前一个形貌预测线程已完成
        if self._morph_thread is not None and self._morph_thread.isRunning():
            Toast.warning(self, "形貌预测仍在进行中，请等待完成")
            self._set_busy(False)
            return
        self._morph_thread = QThread(self)
        self._morph_worker = MorphologyWorker(
            self._session, params,
            self._sp_max_layers.value(), self._session.latest_seed,
        )
        self._morph_worker.moveToThread(self._morph_thread)
        self._morph_thread.started.connect(self._morph_worker.run)
        self._morph_worker.partial.connect(self._on_morph_partial)
        self._morph_worker.finished.connect(self._on_morph_finished)
        self._morph_worker.failed.connect(self._on_morph_failed)
        self._morph_worker.finished.connect(self._morph_thread.quit)
        self._morph_worker.failed.connect(self._morph_thread.quit)
        self._morph_thread.finished.connect(self._morph_worker.deleteLater)
        self._morph_thread.finished.connect(self._morph_thread.deleteLater)
        self._morph_thread.finished.connect(self._on_morph_thread_finished)
        self._morph_thread.start()

    @Slot(object, int, int)
    def _on_path_partial(self, waypoints: np.ndarray, layer_idx: int, total_layers: int) -> None:
        self._session.waypoint.mock = waypoints
        self._prog.setValue(10 + int(60 * layer_idx / max(total_layers, 1)))
        self._lb_prog.setText(f"路径规划中... 第 {layer_idx}/{total_layers} 层")
        self._sb.showMessage(f"路径规划中 – 已生成 {len(waypoints):,} 个航点")
        self._lb_bottom_status.setText(f"路径截面同步中：第 {layer_idx}/{total_layers} 层")
        self._lb_bottom_status.setStyleSheet(
            "color:#F59E0B; font-size:12px; padding:4px; font-weight:bold;"
        )
        self._visualizer.set_partial_waypoints(waypoints)
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        self._update_path_section(sel_mask, waypoints)

    @Slot(object)
    def _on_path_finished(self, waypoints: np.ndarray) -> None:
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        if waypoints is None or len(waypoints) == 0:
            waypoints = self._fallback_waypoints(sel_mask)
            warning("路径规划未生成航点，使用模拟航点")
        self._finish_path_planning(waypoints, sel_mask)

    @Slot(str, str, str)
    def _on_path_failed(self, error_code: str, friendly: str, detail: str) -> None:
        """路径规划失败（结构化错误信号）。

        策略：回退到模拟航点 + 显示结构化错误对话框。
        """
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        log_error(f"路径规划失败 [{error_code}]: {friendly}\n{detail}，使用模拟航点")
        try:
            self._finish_path_planning(self._fallback_waypoints(sel_mask), sel_mask, show_dialog=False)
            # 回退成功：显示带技术日志的对话框
            from repair_app.ui.dialogs import ErrorDialog
            ErrorDialog.show(
                self, title="路径规划回退",
                what="路径规划失败，已自动回退到模拟航点。",
                why=friendly,
                how="1. 可继续后续操作（使用模拟航点）\n2. 如需真实航点，请检查参数后重试",
                log_text=detail,
            )
        except Exception as exc:
            self._set_busy(False)
            _show_error(self, "路径规划失败", exc)

    @Slot()
    def _on_path_thread_finished(self) -> None:
        self._path_thread = None
        self._path_worker = None

    def _on_zmq_path_result(self, result_msg) -> None:
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        try:
            result = _Coord.parse_repair_result(result_msg)
            if not _Coord.is_repair_success(result):
                raise RuntimeError(result["error_message"] or result["status_name"])
            waypoints = result["waypoints"]
            if len(waypoints) == 0:
                raise RuntimeError("黑盒返回成功，但没有航点数据")
            self._prog.setValue(70)
            self._lb_prog.setText("远程服务路径规划完成，正在刷新视图...")
            # P2-3: MATLAB 远程结果为真实数据（非 mock）
            self._session.morphology.is_mock = False
            # 提取 MATLAB 计算引擎返回的可视化/度量数据（v2.1 字段）
            metrics = {
                "estimated_mass_g": result.get("estimated_mass_g", 0.0),
                "estimated_time_s": result.get("estimated_time_s", 0.0),
                "uniformity_score": result.get("uniformity_score", 0.0),
                "predicted_volume_mm3": result.get("predicted_volume_mm3", 0.0),
                "layer_profiles": result.get("layer_profiles", []),
                "particle_dist": result.get("particle_dist"),
            }
            # 将完整 MATLAB 形貌预测结果转发到原生可视化面板
            try:
                # 从 feasibility_reason 中解析 MATLAB warnings（Protobuf 无独立 warnings 字段）
                reason = result.get("feasibility_reason", "") or ""
                warnings_list = []
                if "Warnings:" in reason:
                    warns_part = reason.split("Warnings:", 1)[1].strip()
                    warnings_list = [w.strip() for w in warns_part.split(";") if w.strip()]

                self._profile_panel.set_profile_result({
                    "mesh_bytes": result.get("mesh_bytes", b"") or b"",
                    "mesh_format": result.get("mesh_format", ""),
                    "layer_profiles": result.get("layer_profiles", []),
                    "particle_dist": result.get("particle_dist"),
                    "uniformity_score": result.get("uniformity_score", 0.0),
                    "estimated_mass_g": result.get("estimated_mass_g", 0.0),
                    "estimated_time_s": result.get("estimated_time_s", 0.0),
                    "predicted_volume_mm3": result.get("predicted_volume_mm3", 0.0),
                    "material_density_gcm3": result.get("material_density_gcm3", 0.0),
                    "compute_time_ms": result.get("compute_time_ms", 0),
                    "warnings": warnings_list,
                })
            except Exception as exc:
                log_error(f"形貌预测面板刷新失败: {exc}")
            waypoint_layers = result.get("waypoint_layers")
            # 保留完整航点（含法向量）供喷嘴方向可视化
            full_waypoints = waypoints if waypoints.shape[1] >= 6 else None
            self._finish_path_planning(
                waypoints[:, :3], sel_mask,
                metrics=metrics,
                waypoint_layers=waypoint_layers,
                full_waypoints=full_waypoints,
            )
            info(f"ZMQ 黑盒返回路径: {len(waypoints)} 航点, "
                 f"质量={metrics['estimated_mass_g']:.3f}g, "
                 f"均匀性={metrics['uniformity_score']:.2f}")
        except Exception as exc:
            self._set_busy(False)
            log_error(f"ZMQ 路径规划结果解析失败: {exc}")
            _show_error(self, "远程服务路径规划失败", exc)

    def _on_zmq_path_error(self, message: str) -> None:
        self._set_busy(False)
        log_error(f"ZMQ 路径规划失败: {message}")
        self._pipeline.mark_running_as_failed()
        from repair_app.ui.dialogs import ErrorDialog
        ErrorDialog.show(
            self, title="远程服务路径规划失败",
            what="远程 MATLAB 服务返回错误。",
            why=message,
            how="1. 检查 MATLAB Bridge 是否正常运行\n2. 查看日志排查具体错误\n3. 稍后重试或切换本地引擎",
        )

    @Slot(object, int, int)
    def _on_morph_partial(self, repair_pts: np.ndarray, layer_idx: int, total_layers: int) -> None:
        self._session.morphology.repair_xyz = np.vstack([self._session.point_cloud.xyz, repair_pts])
        self._prog.setValue(20 + int(70 * layer_idx / max(total_layers, 1)))
        self._lb_prog.setText(f"模拟沉积中... 第 {layer_idx}/{total_layers} 层")
        self._sb.showMessage(f"形貌预测中 – 当前 {len(repair_pts):,} 个沉积点")
        self._lb_bottom_status.setText(f"形貌截面同步中：第 {layer_idx}/{total_layers} 层")
        self._lb_bottom_status.setStyleSheet(
            "color:#F59E0B; font-size:12px; padding:4px; font-weight:bold;"
        )
        self._visualizer.set_partial_repair(repair_pts)
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        self._update_morph_section(sel_mask, repair_pts)

    @Slot(object)
    def _on_morph_finished(self, repair_pts: np.ndarray, is_mock: bool = False) -> None:
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        # P2-3: 记录 mock 标记，供报告生成使用
        self._session.morphology.is_mock = bool(is_mock)
        if is_mock:
            from repair_app.utils.logger_config import info as _log_info
            _log_info("[Morphology] 输出为 mock 数据（本地启发式模型，非 MATLAB 物理模型）")
            self._sb.showMessage("形貌预测: 本地启发式模型（mock）", 3000)
        self._finish_morphology(repair_pts, sel_mask)

    @Slot(str, str, str, object)
    def _on_morph_failed(self, error_code: str, friendly: str, detail: str,
                          repair_pts: np.ndarray) -> None:
        """形貌预测失败（结构化错误信号）。

        策略：若有部分结果则回退显示，否则显示错误对话框。
        """
        log_error(f"形貌预测失败 [{error_code}]: {friendly}\n{detail}")
        sel_mask = self._session.selection.mask if self._session.selection.mask is not None else self._selector.get_selection_mask()
        if repair_pts is not None and len(repair_pts) > 0:
            self._finish_morphology(repair_pts, sel_mask)
            from repair_app.ui.dialogs import ErrorDialog
            ErrorDialog.show(
                self, title="形貌预测回退",
                what="形貌预测失败，已显示基础沉积点。",
                why=friendly,
                how="1. 可继续后续操作（使用基础沉积点）\n2. 如需完整形貌，请检查参数后重试",
                log_text=detail,
            )
        else:
            self._set_busy(False)
            from repair_app.ui.dialogs import ErrorDialog
            ErrorDialog.show(
                self, title="形貌预测失败", what=friendly, why="", how="",
                log_text=detail,
            )

    @Slot()
    def _on_morph_thread_finished(self) -> None:
        self._morph_thread = None
        self._morph_worker = None

    def _update_connection_status(self) -> None:
        if self._zmq_client is not None:
            self._lb_conn.setText("🟡 远程服务就绪（未连接）")
        else:
            self._lb_conn.setText("⚫ 本地模式")

    # ====== 导出 ======
    def _save_validation_report(self, validation, fp: str | None) -> None:
        """P2-5: 保存 Validation Report 到导出目录。

        Args:
            validation: ExportValidationResult 对象
            fp: G-code 文件路径（用于推导报告路径），None 时用默认路径
        """
        try:
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            if fp:
                base = os.path.splitext(fp)[0]
                report_path = f"{base}_validation_{ts}.md"
            else:
                proj_name = self._project_manager.current_name or "repair"
                safe_name = "".join(c for c in proj_name if c not in '\\/:*?"<>|')
                report_path = str(self._path_manager.pdf_path(f"{safe_name}_validation_{ts}.md"))
            ok = validation.generate_report(report_path)
            if ok:
                info(f"Validation Report 已保存: {report_path}")
            else:
                log_error("Validation Report 生成失败")
        except Exception as exc:
            log_error(f"保存 Validation Report 失败: {exc}")

    @Slot()
    def _on_export(self, format_name: str) -> None:
        """P5-4: 统一导出入口。所有导出格式走 ExporterRegistry，无需为新增格式修改本方法。

        流程：License 检查 → 预填充 Session → ExporterRegistry.run() → Toast 反馈
        """
        if not self._license.is_valid:
            Toast.warning(self, f"License 无效：{self._license.error}")
            return

        exporter = ExporterRegistry.get(format_name)
        if exporter is None:
            Toast.error(self, f"未知导出格式: {format_name}")
            return

        # 格式相关预填充
        self._prepare_for_export(format_name)

        # 状态反馈
        self._sb.showMessage(f"正在导出 {exporter.display_name}...")
        if hasattr(self, "_lb_prog"):
            self._lb_prog.setText(f"正在导出 {exporter.display_name}...")
            self._prog.setValue(50)
        QApplication.processEvents()

        try:
            result = ExporterRegistry.run(format_name, self, self._session, self._path_manager)
            if result.ok:
                if hasattr(self, "_lb_prog"):
                    self._prog.setValue(100)
                    self._lb_prog.setText(f"✅ {exporter.display_name} 导出完成")
                self._sb.showMessage(f"{exporter.display_name} 已保存: {result.output_path}", 5000)
                msg = f"{exporter.display_name} 已保存: {result.output_path}"
                if result.warnings:
                    msg += "\n（含安全检查警告，详见日志）"
                Toast.success(self, msg)
                # G-code 额外生成 Validation Report
                if format_name == "gcode" and self._session.validation.result is not None:
                    self._save_validation_report(self._session.validation.result, fp=result.output_path)
            elif result.error and result.error != "用户取消":
                if hasattr(self, "_lb_prog"):
                    self._prog.setValue(0)
                    self._lb_prog.setText(f"{exporter.display_name} 导出失败")
                if result.error == "数据不完整，无法导出":
                    Toast.warning(self, f"数据不完整，无法导出 {exporter.display_name}")
                else:
                    Toast.error(self, f"{exporter.display_name} 导出失败：{result.error}")
        except Exception as e:
            if hasattr(self, "_lb_prog"):
                self._prog.setValue(0)
                self._lb_prog.setText(f"{exporter.display_name} 导出失败")
            _show_error(self, "导出失败", e)

    def _prepare_for_export(self, format_name: str) -> None:
        """格式相关的 Session 预填充。新增格式只需在此添加分支。"""
        if format_name == "gcode":
            # 验证参数
            self._session.validation.expected_n_layers = self._sp_max_layers.value() if hasattr(self, "_sp_max_layers") else None
            self._session.validation.expected_layer_height = float(self._collect_params().get("layer_height_mm", 2.0))
            # 工艺参数（G-code 追溯元数据用）
            self._session.report.parameters = self._collect_params()
            # License ID
            lic_data = self._license.license_data
            self._session.license_id = lic_data.machine_id[:12] if lic_data and lic_data.machine_id else "N/A"

        elif format_name == "pdf":
            # 报告字段预填充
            sel_mask = self._selector.get_selection_mask() if self._selector else None
            if sel_mask is not None:
                self._session.selection.mask = sel_mask
            defect_metrics = self._compute_defect_metrics(sel_mask) if sel_mask is not None else {}
            path_metrics = self._compute_path_metrics()
            self._session.report.scan_info = {
                "scan_id": f"SCAN-{self._session.latest_seed:04d}",
                "points": len(self._session.point_cloud.xyz) if self._session.point_cloud.xyz is not None else 0,
                "defect_volume_mm3": defect_metrics.get("volume_mm3", 0.0),
                "defect_depth_mm": defect_metrics.get("depth_mm", 0.0),
                "material": self._cb_mat.currentText() if hasattr(self, "_cb_mat") else "未指定",
            }
            self._session.report.results = {
                "填充点数": f"{len(self._session.morphology.repair_xyz) if self._session.morphology.repair_xyz is not None else 0:,}",
                "修复层数": str(self._sp_max_layers.value()) if hasattr(self, "_sp_max_layers") else "0",
                "缺陷选区点数": f"{defect_metrics.get('point_count', 0):,}",
                "估算缺陷面积": f"{defect_metrics.get('area_mm2', 0.0):.2f} mm²",
                "路径长度": f"{path_metrics.get('path_length_mm', 0.0):.2f} mm",
                "预计加工时间": f"{path_metrics.get('estimated_time_s', 0.0):.1f} s",
                "可行性评分": f"{self._session.feas_result.score:.1%}" if self._session.feas_result else "—",
            }
            self._session.report.parameters = self._collect_params()
            self._session.metrics.defect = defect_metrics
            self._session.metrics.path = path_metrics

    @Slot()
    def _on_export_gcode(self) -> None:
        """向后兼容：G-code 导出（委托统一 Pipeline）。"""
        self._on_export("gcode")

    @Slot()
    def _on_export_pdf(self) -> None:
        """向后兼容：PDF 报告导出（委托统一 Pipeline）。"""
        self._on_export("pdf")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    # ========== 软件工程化：项目 / 恢复 / 关于 / 目录 ==========

    def _collect_project_state(self) -> dict:
        """收集当前会话状态用于项目保存/自动保存。"""
        params = {}
        try:
            params = self._collect_params()
        except Exception as e:
            log_error(f"收集参数失败: {e}")
        sel_summary = {}
        try:
            if self._session.selection.mask is not None:
                metrics = self._compute_defect_metrics(self._session.selection.mask)
                sel_summary = {
                    "point_count": int(metrics.get("point_count", 0)),
                    "volume_mm3": float(metrics.get("volume_mm3", 0.0)),
                    "area_mm2": float(metrics.get("area_mm2", 0.0)),
                }
        except Exception as e:
            log_error(f"计算缺陷指标失败: {e}")
        return self._project_manager.collect_state(
            point_cloud_path=self._session.point_cloud.path,
            repair_mode=self._session.repair_mode,
            material_index=self._cb_mat.currentIndex() if hasattr(self, "_cb_mat") else 0,
            params=params,
            selection_summary=sel_summary,
        )

    def _do_autosave(self) -> None:
        """定时自动保存（由 _autosave_timer 触发）。"""
        try:
            state = self._collect_project_state()
            self._auto_recovery.save(state)
        except Exception as exc:
            log_error(f"自动保存失败: {exc}")

    def _check_recovery(self) -> None:
        """启动时检查是否存在崩溃恢复数据。"""
        try:
            if not self._auto_recovery.has_pending_recovery:
                return
            state = self._auto_recovery.load()
            if not state:
                return
            saved_at = ""
            try:
                import json
                payload = json.loads(self._auto_recovery.autosave_path.read_text(encoding="utf-8"))
                saved_at = payload.get("saved_at", "")
            except Exception as e:
                log_error(f"读取自动保存时间戳失败: {e}")
            reply = QMessageBox.question(
                self, "恢复未保存的会话",
                f"检测到上次会话未正常关闭（自动保存于 {saved_at}）。\n\n"
                f"是否恢复以下状态？\n"
                f"  点云: {state.get('point_cloud_path') or '无'}\n"
                f"  模式: {'修复' if state.get('repair_mode', 1) == 1 else '增材'}\n\n"
                f"选择「Yes」恢复，「No」放弃恢复并删除快照。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._apply_recovered_state(state)
            else:
                self._auto_recovery.clear()
        except Exception as exc:
            log_error(f"恢复检查失败: {exc}")

    def _apply_recovered_state(self, state: dict) -> None:
        """应用恢复的会话状态。"""
        try:
            # 恢复点云
            pcd_path = state.get("point_cloud_path")
            if pcd_path and os.path.isfile(pcd_path):
                xyz, normals = self._file_service.load_point_cloud(pcd_path)
                self._session.point_cloud.xyz = xyz
                self._session.point_cloud.path = pcd_path
                self._session.point_cloud.normals = normals if normals is not None else self._est_normals(self._session.point_cloud.xyz)
                pts_with_normals = np.hstack([self._session.point_cloud.xyz, self._session.point_cloud.normals])
                self._selector.set_points(pts_with_normals)
                self._lb_pts.setText(f"点数: {len(self._session.point_cloud.xyz):,}")
                self._btn_start_repair.setEnabled(True)
                proj_name = os.path.splitext(os.path.basename(pcd_path))[0]
                self._project_manager.new_project(proj_name)
                self._lb_project.setText(f"项目: {proj_name}")
                info(f"已恢复点云: {pcd_path}")
            # 恢复模式
            mode = state.get("repair_mode", 1)
            if hasattr(self, "_rb_repair") and hasattr(self, "_rb_additive"):
                if mode == 0:
                    self._rb_additive.setChecked(True)
                else:
                    self._rb_repair.setChecked(True)
                self._on_mode_changed(mode)
            # 恢复材料
            mat_idx = state.get("material_index", 0)
            if hasattr(self, "_cb_mat"):
                self._cb_mat.setCurrentIndex(mat_idx)
            # 恢复参数
            params = state.get("params", {})
            self._apply_params(params)
            self._sb.showMessage("已恢复上次会话状态")
            self._auto_recovery.clear()
        except Exception as exc:
            log_error(f"恢复状态应用失败: {exc}")
            Toast.error(self, f"部分状态恢复失败: {exc}")

    # ========== UI 接线：6 个 Backend 功能入口 ==========

    @Slot()
    def _on_export_robot(self) -> None:
        """向后兼容：机器人轨迹导出（委托统一 Pipeline）。"""
        self._on_export("robot")

    @Slot()
    def _on_calibration(self) -> None:
        """UI 接线：单道沉积标定向导（Backend: calibration_wizard.py）"""
        dlg = CalibrationDialog(self)
        dlg.exec()

    @Slot()
    def _on_coord_transform(self) -> None:
        """UI 接线：坐标系变换（Backend: coordination_service.py）"""
        points = getattr(self, '_point_cloud', None)
        if points is None and self._selector is not None:
            points = getattr(self._selector, '_points', None)
        dlg = CoordinateSystemDialog(self, points=points)
        if dlg.exec() and dlg.transformed_points is not None:
            # 应用变换后的点云
            try:
                self._point_cloud = dlg.transformed_points
                if self._selector is not None:
                    self._selector.set_points(dlg.transformed_points)
                self._sb.showMessage("坐标系变换已应用", 3000)
            except Exception as exc:
                _show_error(self, "变换应用失败", exc)

    @Slot()
    def _on_param_preset(self) -> None:
        """UI 接线：参数预设管理（Backend: config.py PARAM_SPECS）"""
        current_params = self._collect_params()
        dlg = ParameterPresetDialog(self, current_params=current_params)
        if dlg.exec() and dlg.result_params:
            self._apply_preset_params(dlg.result_params)

    def _apply_preset_params(self, params: dict) -> None:
        """将加载的预设参数应用到 UI spinbox。"""
        try:
            # 冷喷涂参数
            cs_map = {
                "particle_velocity_ms": "particle_velocity",
                "critical_velocity_ms": "critical_velocity",
                "nozzle_diameter_mm": "nozzle_diameter",
                "spray_angle_deg": "spray_angle",
                "standoff_distance_mm": "standoff_distance",
                "particle_size_um": "particle_size",
                "gas_temperature_c": "gas_temperature",
                "gas_pressure_bar": "gas_pressure",
                "powder_feed_rate_gmin": "powder_feed_rate",
                "traversing_speed_mms": "traversing_speed",
            }
            # 路径规划参数
            pp_map = {
                "layer_height_mm": "layer_height",
                "scanning_angle_deg": "scanning_angle",
                "scanning_step_mm": "scanning_step",
                "edge_step_size_mm": "edge_step_size",
                "tilt_angle_deg": "tilt_angle",
                "buffer_additive_mm": "buffer_additive",
                "buffer_repairing_mm": "buffer_repairing",
                "link_free_dist_mm": "link_free_dist",
                "obstacle_resolution_mm": "obstacle_resolution",
            }
            for spec_key, ui_key in cs_map.items():
                if spec_key in params and ui_key in self._cs_fields:
                    self._cs_fields[ui_key].setValue(float(params[spec_key]))
            for spec_key, ui_key in pp_map.items():
                if spec_key in params and ui_key in self._pp_fields:
                    self._pp_fields[ui_key].setValue(float(params[spec_key]))
            if "num_layers" in params:
                self._sp_pp_layers.setValue(int(params["num_layers"]))
            self._sb.showMessage("预设参数已加载", 3000)
        except Exception as exc:
            _show_error(self, "预设加载失败", exc)

    @Slot()
    def _on_batch_validation(self) -> None:
        """UI 接线：批量验证（Backend: validation_service.py）"""
        current_params = self._collect_params()
        dlg = BatchValidationDialog(self, base_params=current_params)
        dlg.exec()

    @Slot()
    def _on_param_validator(self) -> None:
        """UI 接线：参数校验器（Backend: validation_service.py + PARAM_SPECS）"""
        current_params = self._collect_params()
        dlg = ParameterValidatorDialog(self, current_params=current_params)
        dlg.exec()

    @Slot()
    def _on_save_project(self) -> None:
        """保存当前会话为 .csam 工程文件。"""
        try:
            state = self._collect_project_state()
            path = self._project_manager.save_project(state)
            # 加入最近项目
            self._recent_projects.add(self._project_manager.current_name, str(path))
            self._refresh_recent_menu()
            self._lb_project.setText(f"项目: {self._project_manager.current_name}")
            self._sb.showMessage(f"项目已保存: {path}", 5000)
            info(f"项目已保存: {path}")
            Toast.success(self, f"项目已保存: {path}")
        except Exception as exc:
            log_error(f"保存项目失败: {exc}")
            _show_error(self, "保存失败", exc)

    @Slot()
    def _on_open_project(self) -> None:
        """打开 .csam 工程文件。"""
        fp, _ = QFileDialog.getOpenFileName(
            self, "打开项目",
            str(self._path_manager.projects_dir),
            "CSAM 项目 (*.csam);;所有文件 (*)",
        )
        if not fp:
            return
        self._load_project_from_path(fp)

    def _on_open_recent(self, path: str) -> None:
        """从最近项目列表打开。"""
        if not os.path.isfile(path):
            Toast.warning(self, f"项目文件已不存在：{path}")
            self._recent_projects.remove(path)
            self._refresh_recent_menu()
            return
        self._load_project_from_path(path)

    def _load_project_from_path(self, fp: str) -> None:
        """从路径加载工程文件。"""
        try:
            from pathlib import Path
            state = self._project_manager.load_project(Path(fp))
            self._apply_recovered_state(state)
            # 注意：_apply_recovered_state 会 clear autosave，这里恢复一下项目路径
            self._recent_projects.add(self._project_manager.current_name, fp)
            self._refresh_recent_menu()
            self._lb_project.setText(f"项目: {self._project_manager.current_name}")
        except Exception as exc:
            log_error(f"打开项目失败: {exc}")
            _show_error(self, "打开失败", exc)

    @Slot()
    def _on_clear_recent(self) -> None:
        """清空最近项目列表。"""
        self._recent_projects.clear()
        self._refresh_recent_menu()
        self._sb.showMessage("已清空最近项目列表")

    @Slot()
    def _on_open_export_dir(self) -> None:
        """在系统资源管理器中打开导出目录。"""
        self._open_in_explorer(self._path_manager.exports_dir)

    def _setup_matlab_lifecycle_signals(self) -> None:
        """P3-2/P3-3: 连接 MATLAB 生命周期信号 + 启动 ZMQ 心跳。

        消费此前无消费者的 matlab_crashed/matlab_restarted/engine_lost 信号。
        启动 ZMQ 心跳监控（HeartbeatMonitor 代码已存在但从未启用）。
        """
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            manager = MatlabLifecycleManager.get_instance()
            # P3-3: MATLAB 崩溃 → ErrorDialog + 状态栏提示
            manager.matlab_crashed.connect(self._on_matlab_crashed)
            # P3-3: MATLAB 重启成功 → 状态栏提示
            manager.matlab_restarted.connect(self._on_matlab_restarted)
        except Exception as exc:
            log_error(f"连接 MATLAB 生命周期信号失败: {exc}")

        # P3-2: 启动 ZMQ 心跳监控（若客户端支持）
        try:
            if hasattr(self._zmq_client, '_client') and hasattr(self._zmq_client._client, 'start_heartbeat'):
                self._zmq_client._client.start_heartbeat()
                info("ZMQ 心跳监控已启动")
            elif hasattr(self._zmq_client, 'start_heartbeat'):
                self._zmq_client.start_heartbeat()
                info("ZMQ 心跳监控已启动")
        except Exception as exc:
            log_error(f"启动 ZMQ 心跳失败: {exc}")

    @Slot()
    def _on_matlab_crashed(self) -> None:
        """P3-3: MATLAB 崩溃回调。"""
        from repair_app.utils.error_manager import ErrorCode, ErrorManager
        log_error("MATLAB 进程崩溃")
        self._sb.showMessage("MATLAB 进程崩溃，正在尝试自动恢复...", 5000)
        Toast.error(self, "MATLAB 进程崩溃，系统正在尝试自动恢复")

    @Slot()
    def _on_matlab_restarted(self) -> None:
        """P3-3: MATLAB 重启成功回调。"""
        info("MATLAB 已自动重启")
        self._sb.showMessage("MATLAB 已自动恢复", 3000)
        Toast.success(self, "MATLAB 已自动恢复，可继续操作")

    @Slot()
    def _on_export_logs(self) -> None:
        """P3-4: 导出日志为 zip 文件。"""
        from repair_app.utils.logger_config import export_logs
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出日志",
            str(self._path_manager.logs_dir / "logs_export.zip"),
            "ZIP 文件 (*.zip)",
        )
        if not fp:
            return
        try:
            result_path = export_logs(fp)
            Toast.success(self, f"日志已导出: {result_path}")
            self._sb.showMessage(f"日志已导出: {result_path}", 5000)
        except Exception as exc:
            _show_error(self, "日志导出失败", exc)

    @Slot()
    def _on_open_log_dir(self) -> None:
        """在系统资源管理器中打开日志目录。"""
        self._open_in_explorer(self._path_manager.logs_dir)

    def _open_in_explorer(self, path) -> None:
        """跨平台打开资源管理器。"""
        import subprocess
        path = str(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            Toast.info(self, f"无法自动打开，请手动访问：\n{path}")

    @Slot()
    def _on_show_about(self) -> None:
        """显示关于对话框。"""
        from repair_app.software.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec()

    def _apply_params(self, params: dict) -> None:
        """从保存的参数恢复 GUI 控件状态。"""
        if not params:
            return
        # 路径规划参数 + 冷喷涂参数
        for fields_dict in (getattr(self, '_pp_fields', {}), getattr(self, '_cs_fields', {})):
            for key, widget in fields_dict.items():
                if key in params:
                    try:
                        widget.setValue(params[key])
                    except Exception as e:
                        log_error(f"恢复参数 {key} 失败: {e}")
        # 独立命名的控件
        for key, attr_name in [
            ("pp_layers", "_sp_pp_layers"),
            ("max_layers", "_sp_max_layers"),
            ("depth", "_sp_depth"),
        ]:
            if key in params and hasattr(self, attr_name):
                try:
                    getattr(self, attr_name).setValue(params[key])
                except Exception as e:
                    log_error(f"恢复参数 {key} 失败: {e}")

    def closeEvent(self, event) -> None:
        # 退出前做一次强制自动保存
        try:
            self._do_autosave()
        except Exception as e:
            log_error(f"退出前自动保存失败: {e}")
        # 停止自动保存定时器
        try:
            self._autosave_timer.stop()
        except Exception as e:
            log_error(f"停止自动保存定时器失败: {e}")
        for thread in (self._path_thread, self._morph_thread, self._compute_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                # 给予充分时间优雅退出（5 秒），仅在极端情况下 terminate
                if not thread.wait(_THREAD_WAIT_MS):
                    warning(f"线程 {thread.objectName() or thread.__class__.__name__} 未在 5 秒内退出，强制终止")
                    thread.terminate()
                    thread.wait(_THREAD_TERMINATE_WAIT_MS)
        # 停止实时进度订阅器
        self._stop_progress_subscriber()
        # 关闭一键计算启动的 MATLAB 子进程
        if self._compute_worker is not None and hasattr(self._compute_worker, "stop_launcher"):
            self._compute_worker.stop_launcher()
        # 关闭生命周期管理器（停止看门狗 + 关闭 MATLAB）
        try:
            from repair_app.bridge.lifecycle_manager import MatlabLifecycleManager
            manager = MatlabLifecycleManager.get_instance()
            manager.stop()
        except Exception as exc:
            log_error(f"生命周期管理器关闭异常: {exc}")
        if self._zmq_client is not None and hasattr(self._zmq_client, "close"):
            self._zmq_client.close()
        # 清理可视化组件的 matplotlib 资源（防止 Figure 内存泄漏）
        if self._visualizer is not None and hasattr(self._visualizer, "cleanup"):
            self._visualizer.cleanup()
        super().closeEvent(event)

    @staticmethod
    def _kv(k, v):
        l = QLabel(f"{k}: {v}")
        l.setStyleSheet("color:#CBD5E1; font-size:13px; padding:3px 0;")
        return l

    @staticmethod
    def _sep():
        f = QFrame(); f.setFrameShape(QFrame.HLine); f.setFrameShadow(QFrame.Sunken)
        f.setStyleSheet("color:#E2E8F0;")
        return f


if __name__ == "__main__":
    app = QApplication(sys.argv); app.setStyle("Fusion")
    w = MainWindow(); w.show()
    sys.exit(app.exec())
