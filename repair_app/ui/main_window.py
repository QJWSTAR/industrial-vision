"""
main_window.py — 冷喷涂缺陷修复软件主界面
v0.10: 三面板可视化 + 增材/修复双模式 + 气体参数
"""

from __future__ import annotations
import os, sys
import numpy as np

from repair_app.utils.resource_path import get_data_dir
os.environ.setdefault("MPLCONFIGDIR", os.path.join(str(get_data_dir()), ".matplotlib_cache"))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QComboBox,
    QProgressBar, QGroupBox, QStatusBar, QFrame,
    QFileDialog, QMessageBox, QApplication, QTabWidget, QTextEdit,
    QStackedWidget, QCheckBox, QSplitter, QRadioButton, QButtonGroup,
    QSlider, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QPixmap

# H1-H3 修复：UI 层通过 CoordinationService 访问 core/communication 模块
from repair_app.service.coordination_service import CoordinationService as _Coord
from repair_app.ui.defect_selector import DefectSelector
from repair_app.ui.repair_visualizer import RepairVisualizer
from repair_app.ui.profile_result_panel import ProfileResultPanel

_ZMQ_AVAILABLE = _Coord.zmq_available

from repair_app.utils.license_manager import LicenseManager
from repair_app.utils.logger_config import setup_logging, info, warning, error as log_error
from repair_app.service import ExportService
from repair_app.service.file_service import FileService
from repair_app.utils.calibration_wizard import CalibrationWizard
from repair_app.ui.workers import PathPlanningWorker, MorphologyWorker
from repair_app.utils.config import (
    APP_TITLE, MATERIALS, MAT_KEY_MAP, window as _win_cfg, mode as _mode_cfg,
    page as _page_cfg, style as _style_cfg,
    get_morph_dir, get_pointlist_file, get_velocitylist_file, get_p1_frame_dir,
)

_TITLE = APP_TITLE
_LW, _RW = _win_cfg.left_panel_width, _win_cfg.right_panel_width
_WINDOW_W, _WINDOW_H = _win_cfg.window_width, _win_cfg.window_height

_MATERIALS = MATERIALS
_MAT_KEY_MAP = MAT_KEY_MAP

_PROTO_MATERIAL_MAP = _Coord.proto_material_map


# 修复模式
MODE_ADDITIVE  = _mode_cfg.additive   # 增材模式
MODE_REPAIRING = _mode_cfg.repairing  # 修复模式

_MORPH_DIR = get_morph_dir()
_POINTLIST_FILE = get_pointlist_file()
_VELOCITYLIST_FILE = get_velocitylist_file()
_P1_FRAME_DIR = get_p1_frame_dir()

PAGE_PATH = _page_cfg.path
PAGE_MORPH = _page_cfg.morph

# ===== 暗色主题 QSS 样式表 =====
_DARK_THEME_QSS = """
    QMainWindow, QWidget {
        background:#0B1120;
        color:#CBD5E1;
        font-size:12px;
    }
    QFrame#AppHeader {
        background:#020617;
        border-bottom:1px solid #1E293B;
    }
    QLabel#AppTitle {
        color:#F8FAFC;
        font-size:20px;
        font-weight:700;
    }
    QLabel#AppSubtitle {
        color:#64748B;
        font-size:12px;
    }
    QLabel#HeaderChip {
        background:#0F172A;
        color:#BFDBFE;
        border:1px solid #1E3A8A;
        border-radius:12px;
        padding:6px 12px;
        font-weight:600;
    }
    QWidget#SideRail {
        background:#0B1120;
        border-right:1px solid #1E293B;
    }
    QWidget#Workspace {
        background:#0B1120;
    }
    QStackedWidget#WorkspaceStack {
        background:#0B1120;
    }
    QWidget#AuxPanel, QFrame#Inspector {
        background:#0F172A;
        border:1px solid #1E293B;
        border-radius:12px;
    }
    QFrame#P1Header, QFrame#P1Controls {
        background:#0F172A;
        border:1px solid #1E293B;
        border-radius:14px;
    }
    QScrollArea {
        background:#0B1120;
        border:none;
    }
    QFrame {
        border:none;
    }
    QGroupBox {
        background:#111827;
        border:1px solid #243044;
        border-radius:12px;
        margin-top:10px;
        padding:12px 10px 10px 10px;
        color:#CBD5E1;
        font-weight:600;
    }
    QGroupBox::title {
        subcontrol-origin:margin;
        left:10px;
        padding:0 5px;
        color:#93C5FD;
    }
    QLabel {
        color:#CBD5E1;
    }
    QPushButton {
        background:#1E293B;
        color:#E2E8F0;
        border:1px solid #334155;
        border-radius:8px;
        padding:7px 10px;
        font-weight:600;
    }
    QPushButton:hover {
        background:#263449;
        border-color:#475569;
    }
    QPushButton:disabled {
        background:#111827;
        color:#64748B;
        border-color:#243044;
    }
    QSlider::groove:horizontal {
        height:6px;
        border-radius:3px;
        background:#1E293B;
    }
    QSlider::handle:horizontal {
        width:16px;
        margin:-5px 0;
        border-radius:8px;
        background:#60A5FA;
    }
    QSlider::sub-page:horizontal {
        border-radius:3px;
        background:#2563EB;
    }
    QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit {
        background:#020617;
        color:#E2E8F0;
        border:1px solid #334155;
        border-radius:7px;
        padding:4px 6px;
    }
    QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {
        color:#64748B;
        border-color:#243044;
        background:#0F172A;
    }
    QCheckBox, QRadioButton {
        color:#CBD5E1;
        spacing:6px;
    }
    QProgressBar {
        background:#020617;
        color:#CBD5E1;
        border:1px solid #334155;
        border-radius:7px;
        height:14px;
        text-align:center;
    }
    QProgressBar::chunk {
        background:#3B82F6;
        border-radius:6px;
    }
    QSplitter::handle {
        background:#1E293B;
    }
    QStatusBar {
        background:#020617;
        color:#94A3B8;
        border-top:1px solid #1E293B;
    }
"""

# 步骤按钮样式
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
        self._xyz = self._normals = None
        self._repair_xyz = None
        self._latest_seed = 42
        self._feasibility_checker = _Coord.create_feasibility_checker()
        self._feas_result = None
        self._zmq_client = _Coord.create_zmq_client()
        self._export_service = ExportService()
        self._file_service = FileService()
        self._mock_waypoints = None
        self._full_waypoints = None  # 含法向量的完整航点（远程结果）
        self._velocity_list = None
        self._path_output_ready = False
        self._files_saved = False
        self._pp_fields = {}
        self._cs_fields = {}
        self._repair_mode = MODE_REPAIRING
        self._sel_mask = None  # 选择掩码缓存
        self._is_busy = False
        self._path_thread = None
        self._path_worker = None
        self._morph_thread = None
        self._morph_worker = None

        setup_logging(level="INFO")
        info("冷喷涂缺陷修复软件 v0.10 启动")

        self._license = LicenseManager()
        if self._license.load_license():
            info(f"License 验证通过 ({self._license.days_remaining} 天后到期)")
        else:
            warning(f"License 验证失败: {self._license.error}")

        self._calibration = CalibrationWizard()

        self._setup_ui()
        self._setup_statusbar()
        self._update_connection_status()
        self._update_step_buttons()
        QTimer.singleShot(300, self._load_demo)

    # ========== UI Layout ==========
    def _setup_ui(self) -> None:
        c = QWidget()
        self.setCentralWidget(c)
        self._apply_theme()

        root = QVBoxLayout(c)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._app_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._left_column())
        body.addWidget(self._center(), 1)
        body.addWidget(self._right_column())
        root.addLayout(body, 1)

    def _app_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("AppHeader")
        header.setFixedHeight(70)
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
        self.setStyleSheet(_DARK_THEME_QSS)

    def _left_column(self) -> QWidget:
        outer = QWidget()
        outer.setObjectName("SideRail")
        outer.setFixedWidth(_LW)
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

        self._step2_btn = QPushButton("02  形貌预测\n可行性检查、沉积模拟")
        self._step2_btn.setMinimumHeight(58)
        self._step2_btn.setCursor(Qt.PointingHandCursor)
        self._step2_btn.clicked.connect(lambda: self._switch_to_step(PAGE_MORPH))
        self._step2_btn.setEnabled(False)
        sl.addWidget(self._step2_btn)

        self._step3_lb = QLabel("03  结果校核\n查看指标、截面和风险")
        self._step3_lb.setMinimumHeight(54)
        self._step3_lb.setAlignment(Qt.AlignCenter)
        self._step3_lb.setStyleSheet(
            "color:#475569; font-size:11px; padding:8px; "
            "background:#0F172A; border:1px dashed #334155; border-radius:6px;"
        )
        sl.addWidget(self._step3_lb)

        self._step4_lb = QLabel("04  输出交付\n导出 G-code 与 PDF 报告")
        self._step4_lb.setMinimumHeight(54)
        self._step4_lb.setAlignment(Qt.AlignCenter)
        self._step4_lb.setStyleSheet(
            "color:#475569; font-size:11px; padding:8px; "
            "background:#0F172A; border:1px dashed #334155; border-radius:6px;"
        )
        sl.addWidget(self._step4_lb)
        layout.addWidget(workflow)

        # --- 材料选择 ---
        mat_bar = QGroupBox("材料选择")
        mat_ml = QVBoxLayout(mat_bar); mat_ml.setSpacing(4)
        mat_row = QHBoxLayout(); mat_row.addWidget(QLabel("材料"))
        self._cb_mat = QComboBox()
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
        self._cb_engine.addItem("本地计算引擎", "local")
        self._cb_engine.addItem("远程服务 (MATLAB)", "zmq")
        if not _ZMQ_AVAILABLE:
            self._cb_engine.model().item(1).setEnabled(False)
        self._cb_engine.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self._cb_engine); engine_row.addStretch(); el.addLayout(engine_row)
        self._lb_engine_hint = QLabel("本地引擎支持逐层实时刷新；远程服务用于连接 MATLAB 获取最终计算结果。")
        self._lb_engine_hint.setStyleSheet("color:#64748B; font-size:11px; padding:4px;")
        self._lb_engine_hint.setWordWrap(True); el.addWidget(self._lb_engine_hint)
        l.addWidget(eg)

        ppg = QGroupBox("路径规划参数"); ppl = QVBoxLayout(ppg); ppl.setSpacing(5)
        pp_params = [
            ("layer_height",       "层高",           2.0,   0.1,  10.0,  0.1,  " mm"),
            ("scanning_angle",     "扫描角度",      -45.0, -90.0,  90.0, 15.0,  " °"),
            ("scanning_step",      "扫描步长",        2.0,   0.1,  10.0,  0.1,  " mm"),
            ("edge_step_size",     "边缘步长",        2.0,   0.1,  10.0,  0.1,  " mm"),
            ("tilt_angle",         "倾斜角度",       60.0,   0.0,  90.0,  5.0,  " °"),
            ("buffer_additive",    "增材缓冲",        2.0,   0.0,  10.0,  0.5,  " mm"),
            ("buffer_repairing",   "修复缓冲",        0.0,   0.0,  10.0,  0.5,  " mm"),
            ("link_free_dist",     "路径过渡距离",    10.0,   1.0, 100.0,  1.0,  " mm"),
            ("obstacle_resolution","避障精度",        0.5,   0.1,   5.0,  0.1,  " mm"),
        ]
        for key, label, default, vmin, vmax, step, suffix in pp_params:
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            sp = QDoubleSpinBox(); sp.setRange(vmin, vmax); sp.setValue(default)
            sp.setSingleStep(step); sp.setSuffix(suffix); sp.setFixedWidth(100)
            row.addWidget(sp); row.addStretch(); ppl.addLayout(row)
            self._pp_fields[key] = sp

        nl_row = QHBoxLayout(); nl_row.addWidget(QLabel("规划层数"))
        self._sp_pp_layers = QSpinBox(); self._sp_pp_layers.setRange(1, 50)
        self._sp_pp_layers.setValue(10); self._sp_pp_layers.setFixedWidth(100)
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
        self._btn_gen_path = QPushButton("🔧 生成修复路径")
        self._btn_gen_path.setMinimumHeight(42); self._btn_gen_path.setEnabled(False)
        self._btn_gen_path.setToolTip("根据参数和选区生成喷涂路径航点")
        self._btn_gen_path.clicked.connect(self._on_generate_path)
        self._btn_gen_path.setStyleSheet(
            "QPushButton{background:#1D4ED8;color:#FFF;border:none;border-radius:6px;"
            "font-size:14px;font-weight:bold;}"
            "QPushButton:hover{background:#2563EB;}"
            "QPushButton:disabled{background:#334155;color:#64748B;}"
        )
        ol.addWidget(self._btn_gen_path)

        self._btn_exp_gcode = QPushButton("📤 导出 G-code")
        self._btn_exp_gcode.setMinimumHeight(34); self._btn_exp_gcode.setEnabled(False)
        self._btn_exp_gcode.setToolTip("将生成的路径导出为数控 G-code 文件（.nc）")
        self._btn_exp_gcode.clicked.connect(self._on_export_gcode)
        ol.addWidget(self._btn_exp_gcode)
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

        p1g = QGroupBox("P1 动画演示")
        p1l = QVBoxLayout(p1g); p1l.setSpacing(6)
        frame_count = len(_list_p1_frame_paths())
        self._lb_p1_status = QLabel(f"MATLAB 帧: {frame_count} 张" if frame_count else "MATLAB 帧: 未找到")
        self._lb_p1_status.setStyleSheet(
            "color:#10B981; font-size:12px;" if frame_count else "color:#F59E0B; font-size:12px;"
        )
        p1l.addWidget(self._lb_p1_status)
        self._btn_p1_demo = QPushButton("▶ 播放 P1 演示动画")
        self._btn_p1_demo.setMinimumHeight(38)
        self._btn_p1_demo.setEnabled(frame_count > 0)
        self._btn_p1_demo.clicked.connect(self._on_play_p1_demo)
        self._btn_p1_demo.setStyleSheet(
            "QPushButton{background:#1D4ED8;color:#FFF;border:none;border-radius:8px;"
            "font-size:13px;font-weight:bold;}"
            "QPushButton:hover{background:#2563EB;}"
            "QPushButton:disabled{background:#334155;color:#64748B;}"
        )
        p1l.addWidget(self._btn_p1_demo)
        hint = QLabel("用于演示 P1 三视图过程；真实可交互渲染后续再接 .mat 数据帧。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748B; font-size:11px; line-height:1.4;")
        p1l.addWidget(hint)
        l.addWidget(p1g)

        # --- 冷喷涂工艺参数 ---
        cpg = QGroupBox("冷喷涂工艺参数"); cpl = QVBoxLayout(cpg); cpl.setSpacing(5)
        cs_params = [
            ("particle_velocity",  "粒子速度",     500.0,  100.0, 1200.0, 10.0,  " m/s"),
            ("critical_velocity",  "临界速度",     400.0,  100.0, 1000.0, 10.0,  " m/s"),
            ("nozzle_diameter",    "喷嘴直径",       6.0,    1.0,   20.0,  0.5,  " mm"),
            ("spray_angle",        "喷涂角度",      90.0,    0.0,  180.0,  5.0,  " °"),
            ("standoff_distance",  "喷涂距离",      30.0,    5.0,  100.0,  1.0,  " mm"),
            ("particle_size",      "粉末粒径",      25.0,    5.0,  100.0,  1.0,  " μm"),
            ("gas_temperature",   "气体温度",     800.0,  200.0, 1200.0, 10.0,  " °C"),
            ("gas_pressure",      "气体压力",      40.0,   10.0,  100.0,  1.0,  " bar"),
            ("powder_feed_rate",  "送粉速度",      30.0,    5.0,  200.0,  1.0,  " g/min"),
            ("traversing_speed",   "移动速度",     500.0,   50.0, 2000.0, 10.0,  " mm/s"),
        ]
        for key, label, default, vmin, vmax, step, suffix in cs_params:
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            sp = QDoubleSpinBox(); sp.setRange(vmin, vmax); sp.setValue(default)
            sp.setSingleStep(step); sp.setSuffix(suffix); sp.setFixedWidth(100)
            row.addWidget(sp); row.addStretch(); cpl.addLayout(row)
            self._cs_fields[key] = sp
        self._cs_fields["critical_velocity"].setEnabled(False)
        self._cs_fields["critical_velocity"].setToolTip(
            "临界速度由材料数据库自动计算，不可手动修改"
        )
        l.addWidget(cpg)

        dg = QGroupBox("沉积参数"); dl = QVBoxLayout(dg); dl.setSpacing(5)
        dr = QHBoxLayout(); dr.addWidget(QLabel("深度补偿"))
        self._sp_depth = QDoubleSpinBox(); self._sp_depth.setRange(0, 2)
        self._sp_depth.setValue(1.0); self._sp_depth.setSingleStep(0.1)
        self._sp_depth.setSuffix(" x"); self._sp_depth.setFixedWidth(90)
        dr.addWidget(self._sp_depth); dr.addStretch(); dl.addLayout(dr)
        nr = QHBoxLayout(); nr.addWidget(QLabel("预测层数"))
        self._sp_max_layers = QSpinBox(); self._sp_max_layers.setRange(1, 20)
        self._sp_max_layers.setValue(5); self._sp_max_layers.setFixedWidth(90)
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

        self._btn_exp_pdf = QPushButton("📄 导出 PDF 报告")
        self._btn_exp_pdf.setMinimumHeight(34); self._btn_exp_pdf.setEnabled(False)
        self._btn_exp_pdf.setToolTip("生成包含修复参数、对比图和结果摘要的 PDF 报告")
        self._btn_exp_pdf.clicked.connect(self._on_export_pdf)
        ol.addWidget(self._btn_exp_pdf)
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

        # ---- 步骤 02：形貌预测 P1 动画演示工作区 ----
        morph_workspace = QWidget()
        morph_layout = QVBoxLayout(morph_workspace)
        morph_layout.setContentsMargins(0, 0, 0, 0)
        morph_layout.setSpacing(8)

        self._p1_player = P1FramePlayer(_P1_FRAME_DIR)
        morph_layout.addWidget(self._p1_player, 1)

        self._workspace_stack.addWidget(path_workspace)
        self._workspace_stack.addWidget(morph_workspace)
        layout.addWidget(self._workspace_stack, 1)

        self._top_splitter = self._main_splitter  # 兼容旧引用
        self._bottom_splitter = self._main_splitter
        self._tabs = self._main_splitter  # 兼容旧引用
        return self._center_widget

    # ====== Right Column ======
    def _right_column(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFixedWidth(_RW); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        self._feas_text.setMaximumHeight(150)
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
        self._lb_conn = QLabel("⚫ 本地模式")
        self._lb_conn.setStyleSheet("color:#94A3B8; padding:0 8px;")
        self._sb.addPermanentWidget(self._lb_conn)
        self.setStatusBar(self._sb)
        self._sb.showMessage("路径规划 — 加载点云并选取缺陷区域后生成路径")

    # ========== 步骤切换 ==========
    @Slot(int)
    def _on_mode_changed(self, mode_id: int) -> None:
        self._repair_mode = mode_id
        self._update_step_buttons()
        if mode_id == MODE_ADDITIVE:
            self._lb_mode_hint.setText("💡 增材模式：将对整个零件表面生成全覆盖路径")
            self._btn_gen_path.setText("🏗️ 生成增材路径")
            if self._is_busy:
                return
            self._btn_gen_path.setEnabled(self._xyz is not None)
            # 增材模式不需要选择缺陷
            self._btn_feas.setEnabled(False)
        else:
            self._lb_mode_hint.setText("💡 修复模式：在中心视图框选缺陷区域 → 调参数 → 点击生成路径")
            self._btn_gen_path.setText("🔧 生成修复路径")
            if self._is_busy:
                return
            sel_mask = self._selector.get_selection_mask() if self._selector else None
            self._btn_gen_path.setEnabled(self._xyz is not None and sel_mask is not None and np.any(sel_mask))

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
        request_xyz = self._xyz[sel_mask]
        request_normals = self._normals[sel_mask] if self._normals is not None else self._est_normals(request_xyz)
        mat_code = _MATERIALS[self._cb_mat.currentIndex()][1]
        return _Coord.build_repair_request(
            request_xyz,
            request_normals,
            scan_id=f"SCAN-{self._latest_seed:04d}",
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
    
        if page == PAGE_MORPH and not self._path_output_ready:
            QMessageBox.information(self, "提示",
                "⚠️ 请先完成路径规划。\n\n"
                "加载点云 → 框选缺陷 → 点击「生成修复路径」。")
            return
        self._mode_stack.setCurrentIndex(page)
        self._update_step_buttons()
        if page == PAGE_PATH:
            self._sb.showMessage("路径规划 — 加载点云并生成修复路径")
        else:
            self._refresh_morph_status()
            self._sb.showMessage("形貌预测 — 基于路径规划输出执行沉积预测")

    def _update_step_buttons(self) -> None:
        """根据当前步骤和输出状态更新按钮样式。"""
        current = self._mode_stack.currentIndex()
        morph_done = self._repair_xyz is not None
        mode_name = "增材模式" if self._repair_mode == MODE_ADDITIVE else "修复模式"

        if current == PAGE_PATH:
            if self._path_output_ready:
                self._step1_btn.setStyleSheet(_STEP_DONE)
                self._step1_btn.setText("✓ 01  数据与路径\n路径已生成，可进入预测")
            else:
                self._step1_btn.setStyleSheet(_STEP_ACTIVE.format(c="#172554", h="#1D4ED8", b="#3B82F6"))
                self._step1_btn.setText("01  数据与路径\n加载点云、选区、生成路径")

            if self._path_output_ready:
                self._step2_btn.setEnabled(True)
                self._step2_btn.setStyleSheet(_STEP_ACTIVE.format(c="#3B0764", h="#6D28D9", b="#8B5CF6"))
                self._step2_btn.setText("02  形貌预测\n航点就绪，等待执行")
                self._arrow_lb.setStyleSheet(_ARROW_READY)
            else:
                self._step2_btn.setEnabled(False)
                self._step2_btn.setStyleSheet(_STEP_LOCKED)
                self._step2_btn.setText("02  形貌预测\n等待路径规划输出")
                self._arrow_lb.setStyleSheet(_ARROW)
        else:
            # 在形貌预测步骤
            self._step1_btn.setStyleSheet(_STEP_DONE)
            self._step1_btn.setText("✓ 01  数据与路径\n路径已生成")
            self._step2_btn.setEnabled(True)
            if morph_done:
                self._step2_btn.setStyleSheet(_STEP_DONE)
                self._step2_btn.setText("✓ 02  形貌预测\n预测已完成")
            else:
                self._step2_btn.setStyleSheet(_STEP_ACTIVE.format(c="#3B0764", h="#6D28D9", b="#8B5CF6"))
                self._step2_btn.setText("02  形貌预测\n可行性检查、沉积模拟")
            self._arrow_lb.setStyleSheet(_ARROW_READY)

        if hasattr(self, "_step3_lb"):
            if morph_done:
                self._style_workflow_label(self._step3_lb, "done")
                self._step3_lb.setText("✓ 03  结果校核\n指标、截面和风险已更新")
            elif self._path_output_ready:
                self._style_workflow_label(self._step3_lb, "active")
                self._step3_lb.setText("03  结果校核\n建议先做可行性检查")
            else:
                self._style_workflow_label(self._step3_lb, "locked")
                self._step3_lb.setText("03  结果校核\n等待路径与预测结果")

            if morph_done:
                self._style_workflow_label(self._step4_lb, "active")
                self._step4_lb.setText("04  输出交付\n可导出 G-code 与 PDF 报告")
            else:
                self._style_workflow_label(self._step4_lb, "locked")
                self._step4_lb.setText("04  输出交付\n等待预测完成")

        if hasattr(self, "_lb_mode_state"):
            self._lb_mode_state.setText(mode_name)
        if hasattr(self, "_lb_workflow_state"):
            if self._is_busy:
                self._lb_workflow_state.setText("计算中")
            elif morph_done:
                self._lb_workflow_state.setText("交付就绪")
            elif self._path_output_ready:
                self._lb_workflow_state.setText("等待形貌预测")
            elif self._xyz is not None:
                self._lb_workflow_state.setText("等待选区/路径")
            else:
                self._lb_workflow_state.setText("等待数据")

    def _on_play_p1_demo(self) -> None:
        if hasattr(self, "_p1_player"):
            self._p1_player.toggle_playback()

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

        if self._mock_waypoints is not None and len(self._mock_waypoints) > 0:
            n_wp = len(self._mock_waypoints)
            source = "文件" if (pl_file or vl_file) else "内存"
            self._lb_pl_status.setText(f"✅ 航点数据就绪 ({n_wp:,} 个)")
            self._lb_pl_status.setStyleSheet("color:#10B981; font-size:13px;")
            self._lb_input_source.setText(f"来源: {source}")
            if pl_file:
                self._lb_input_source.setText(f"来源: 文件 (形貌预测/pointlist.npz)")
            elif self._files_saved is False and self._mock_waypoints is not None:
                self._lb_input_source.setText("来源: 内存（未保存到文件）")
        else:
            self._lb_pl_status.setText("⏳ 请先完成路径规划")
            self._lb_pl_status.setStyleSheet("color:#F59E0B; font-size:13px;")
            self._lb_input_source.setText("来源: —")

        ready = self._mock_waypoints is not None and len(self._mock_waypoints) > 0
        if self._is_busy:
            return
        self._btn_fix.setEnabled(ready)
        self._btn_feas.setEnabled(ready)

    def _set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        self._update_step_buttons()
        if busy:
            for btn in (
                self._btn_gen_path,
                self._btn_exp_gcode,
                self._btn_fix,
                self._btn_feas,
                self._btn_exp_pdf,
                self._step2_btn,
            ):
                btn.setEnabled(False)
            return

        can_path = self._xyz is not None
        if can_path and self._repair_mode == MODE_REPAIRING:
            sel_mask = self._selector.get_selection_mask() if self._selector else None
            can_path = bool(sel_mask is not None and np.any(sel_mask))
        self._btn_gen_path.setEnabled(can_path)
        self._btn_exp_gcode.setEnabled(self._mock_waypoints is not None and len(self._mock_waypoints) > 0)
        self._btn_exp_pdf.setEnabled(self._repair_xyz is not None)
        self._step2_btn.setEnabled(self._path_output_ready)
        self._refresh_morph_status()
        self._update_step_buttons()

    def _fallback_waypoints(self, sel_mask: np.ndarray) -> np.ndarray:
        base = self._xyz[sel_mask]
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
        self._mock_waypoints = waypoints
        self._full_waypoints = full_waypoints  # 含法向量，供喷嘴方向可视化
        n_wp = len(self._mock_waypoints)
        self._velocity_list = ["v500"] * n_wp

        save_to_disk = self._chk_save_files.isChecked()
        if save_to_disk:
            self._lb_prog.setText("正在保存到 形貌预测/ 目录...")
            try:
                self._file_service.save_waypoints(self._mock_waypoints, self._velocity_list)
                self._files_saved = True
                info(f"已保存: pointlist.npz ({n_wp} 航点), velocitylist.json")
            except Exception as e:
                self._files_saved = False
                log_error(f"保存文件失败: {e}")
                QMessageBox.warning(self, "保存失败", str(e))
        else:
            self._files_saved = False
            info("跳过文件保存（仅保留在内存中）")

        self._path_output_ready = True
        # 若远程结果带逐层信息，构建真实逐层动画（替代伪造插值）
        layers = None
        if waypoint_layers is not None and len(waypoint_layers) == n_wp:
            layers = self._build_layers_from_waypoints(
                self._mock_waypoints, waypoint_layers
            )
        self._visualizer.set_data(
            substrate=self._xyz, defect_mask=sel_mask,
            repair=None, waypoints=self._mock_waypoints, layers=layers,
        )
        # 传递喷嘴方向向量（含法向量的完整航点）供 quiver3 原生可视化
        if full_waypoints is not None and full_waypoints.shape[1] >= 6:
            self._visualizer.set_nozzle_orientations(
                full_waypoints[:, :3], full_waypoints[:, 3:6],
            )
        self._update_section_views(sel_mask)

        # 填充右侧度量面板（MATLAB 计算引擎返回的真实指标）
        self._apply_result_metrics(metrics, n_wp, waypoint_layers)

        self._prog.setValue(100)
        self._set_busy(False)
        self._refresh_morph_status()

        file_msg = "已保存到 形貌预测/ 目录" if self._files_saved else "仅保留在内存中（未存文件）"
        self._lb_prog.setText("✅ 路径规划完成")
        self._sb.showMessage(f"路径规划完成 – {n_wp} 个航点 – {file_msg}")

        if show_dialog:
            QMessageBox.information(self, "路径规划完成",
                f"✅ 路径规划完成！\n\n"
                f"• 航点数: {n_wp:,}\n"
                f"• 文件: {file_msg}\n\n"
                f"👉 点击中心区「MATLAB 形貌分析」Tab 查看原生渲染结果\n"
                f"   （沉积网格 / 逐层轮廓 / 粒子分布 / 均匀性仪表盘）\n"
                f"👉 或点击左侧「02 形貌预测」进入下一步。")

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
        self._repair_xyz = np.vstack([self._xyz, repair_pts])
        layers = self._build_morph_layers(repair_pts)
        self._visualizer.set_data(
            substrate=self._xyz, defect_mask=sel_mask,
            repair=repair_pts, waypoints=self._mock_waypoints, layers=layers,
        )
        self._update_section_views(sel_mask)

        rc = len(repair_pts)
        self._lb_prog.setText("✅ 形貌预测完成")
        self._sb.showMessage(f"形貌预测完成 – {rc:,} 个沉积点")
        self._lb_vol.setText(f"填充点数: {rc:,} pts")
        self._lb_lay.setText(f"修复层数: {self._sp_max_layers.value()}")
        self._lb_feas.setText(
            f"可行性: {'✓' if self._feas_result is None or self._feas_result.feasible else '✗'}"
        )
        self._prog.setValue(100)
        self._set_busy(False)

    def _compute_defect_metrics(self, sel_mask: np.ndarray) -> dict:
        if self._xyz is None or not np.any(sel_mask):
            return {
                "point_count": 0,
                "depth_mm": 0.0,
                "area_mm2": 0.0,
                "volume_mm3": 0.0,
            }
        pts = self._xyz[sel_mask]
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
        if self._mock_waypoints is None or len(self._mock_waypoints) < 2:
            return {"path_length_mm": 0.0, "estimated_time_s": 0.0}
        seg = np.linalg.norm(np.diff(self._mock_waypoints[:, :3], axis=0), axis=1)
        length = float(np.sum(seg))
        speed = max(float(self._collect_params().get("traversing_speed_mms", 500.0)), 1e-6)
        return {
            "path_length_mm": length,
            "estimated_time_s": length / speed,
        }

    # ========== Event Handlers ==========
    @Slot(object)
    def _on_selection_changed(self, mask: np.ndarray) -> None:
        n_sel = int(np.sum(mask))
        self._lb_sel.setText(f"已选: {n_sel}")
        if self._is_busy:
            return
        if self._repair_mode == MODE_ADDITIVE:
            self._btn_gen_path.setEnabled(self._xyz is not None)
        else:
            self._btn_gen_path.setEnabled(n_sel >= 3)

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
            QMessageBox.warning(self, "选区不足", "请至少选取 3 个点。")
            return
        params = self._collect_params()
        result = self._feasibility_checker.check_from_cloud(
            selected_points=sel_points,
            nozzle_diameter_mm=params["nozzle_diameter_mm"],
            spray_angle_deg=params["spray_angle_deg"],
            particle_velocity_ms=params["particle_velocity_ms"],
        )
        self._feas_result = result
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
                self._xyz = xyz
                if normals is not None:
                    self._normals = normals
                else:
                    self._normals = self._est_normals(self._xyz)
                self._reset_output()
                pts_with_normals = np.hstack([self._xyz, self._normals])
                self._selector.set_points(pts_with_normals)
                self._lb_pts.setText(f"点数: {len(self._xyz):,}")
                self._btn_gen_path.setEnabled(True)
                info(f"点云已加载: {os.path.basename(fp)} ({len(self._xyz):,} 点)")
                self._sb.showMessage(f"已加载: {os.path.basename(fp)} ({len(self._xyz):,} 点)")
            except Exception as e:
                QMessageBox.warning(self, "加载失败", str(e))
        else:
            reply = QMessageBox.question(
                self, "加载演示数据",
                "未选择文件。是否加载内置演示数据？\n\n"
                "演示数据包含一个模拟缺陷点云，可用于熟悉软件操作流程。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._latest_seed = np.random.randint(0, 9999)
                self._load_demo()

    def _load_demo(self) -> None:
        pts, normals, _, _ = _Coord.generate_sample_defect(
            defect_types=["pit"], seed=self._latest_seed, n_points=8000
        )
        self._xyz = pts
        self._normals = normals
        self._reset_output()
        pts_with_normals = np.hstack([self._xyz, self._normals])
        self._selector.set_points(pts_with_normals)
        self._lb_pts.setText(f"点数: {len(self._xyz):,}")
        self._btn_gen_path.setEnabled(True)
        info(f"演示数据已加载 ({len(self._xyz):,} 点)")
        self._sb.showMessage(f"演示数据已加载 ({len(self._xyz):,} 点)")

    def _reset_output(self) -> None:
        self._repair_xyz = None
        self._mock_waypoints = None
        self._full_waypoints = None
        self._velocity_list = None
        self._path_output_ready = False
        self._files_saved = False
        self._btn_exp_gcode.setEnabled(False)
        self._btn_exp_pdf.setEnabled(False)
        self._btn_fix.setEnabled(False)
        self._btn_feas.setEnabled(False)
        self._step2_btn.setEnabled(False)
        self._update_step_buttons()

    def _est_normals(self, xyz, k=30):
        return _Coord.estimate_normals(xyz, k=k)

    def _update_section_views(self, sel_mask: np.ndarray) -> None:
        """更新右侧辅助截面面板。"""
        if self._mock_waypoints is None or len(self._mock_waypoints) == 0:
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
        wp = waypoints if waypoints is not None else self._mock_waypoints
        self._style_aux_axis(self._ax_path, "截面路径规划")

        if np.any(sel_mask):
            defect_pts = self._xyz[sel_mask]
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
        if repair_pts is None and self._repair_xyz is not None:
            repair_pts = (
                self._repair_xyz[len(self._xyz):]
                if len(self._repair_xyz) > len(self._xyz)
                else self._repair_xyz
            )
        self._style_aux_axis(self._ax_morph, "形貌预测结果")

        if np.any(sel_mask):
            defect_pts = self._xyz[sel_mask]
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

    # ====== 步骤①：路径规划 ======
    @Slot()
    def _on_generate_path(self) -> None:
        if self._is_busy:
            return
        if self._xyz is None:
            QMessageBox.warning(self, "无数据", "请先加载点云。")
            return
        if self._repair_mode == MODE_REPAIRING:
            sel_mask = self._selector.get_selection_mask()
            if not np.any(sel_mask):
                QMessageBox.warning(self, "未选区", "请在中心视图选取缺陷区域。")
                return
        else:
            # 增材模式：全表面标记为选区
            sel_mask = np.ones(len(self._xyz), dtype=bool)
        self._sel_mask = sel_mask

        self._sb.showMessage("路径规划中...")
        self._prog.setValue(10)
        self._lb_prog.setText("正在生成修复路径...")
        self._set_busy(True)
        self._visualizer.set_data(
            substrate=self._xyz, defect_mask=sel_mask,
            repair=None, waypoints=None, layers=None,
        )

        if self._use_zmq_engine():
            try:
                request = self._build_repair_request(sel_mask)
            except Exception as e:
                self._set_busy(False)
                QMessageBox.warning(self, "请求构建失败", str(e))
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
            if self._repair_mode == MODE_ADDITIVE
            else params.get("buffer_repairing_mm", 0.0)
        )
        # 防御性检查：确保前一个路径规划线程已完成
        if self._path_thread is not None and self._path_thread.isRunning():
            QMessageBox.warning(self, "正在处理", "路径规划仍在进行中，请等待完成。")
            self._set_busy(False)
            return
        self._path_thread = QThread(self)
        self._path_worker = PathPlanningWorker(
            self._xyz, sel_mask, params, self._sp_pp_layers.value(), buffer_mm
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
        if self._is_busy:
            return
        if self._xyz is None:
            QMessageBox.warning(self, "无数据", "请先加载点云。")
            return
        sel_mask = self._selector.get_selection_mask()
        if not np.any(sel_mask):
            QMessageBox.warning(self, "未选区", "请在中心视图选取缺陷区域。")
            return

        # 尝试从文件加载（如果存在），否则使用内存数据
        if self._file_service.has_saved_waypoints():
            try:
                loaded = self._file_service.load_waypoints()
                if loaded is not None:
                    self._mock_waypoints = loaded
                    info(f"从文件加载航点: {len(self._mock_waypoints)} 个")
            except Exception as e:
                log_error(f"加载航点文件失败: {e}")

        if self._mock_waypoints is None or len(self._mock_waypoints) == 0:
            QMessageBox.warning(self, "无航点",
                "未找到航点数据。\n请先回到路径规划步骤执行路径生成。")
            return

        params = self._collect_params()
        info("形貌预测开始")
        self._sb.showMessage("形貌预测中...")
        self._prog.setValue(20)
        self._lb_prog.setText("模拟沉积中...")
        self._set_busy(True)
        self._visualizer.set_data(
            substrate=self._xyz, defect_mask=sel_mask,
            repair=None, waypoints=self._mock_waypoints, layers=None,
        )
        # 防御性检查：确保前一个形貌预测线程已完成
        if self._morph_thread is not None and self._morph_thread.isRunning():
            QMessageBox.warning(self, "正在处理", "形貌预测仍在进行中，请等待完成。")
            self._set_busy(False)
            return
        self._morph_thread = QThread(self)
        self._morph_worker = MorphologyWorker(
            self._xyz, sel_mask, self._mock_waypoints, params,
            self._sp_max_layers.value(), self._latest_seed,
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
        self._mock_waypoints = waypoints
        self._prog.setValue(10 + int(60 * layer_idx / max(total_layers, 1)))
        self._lb_prog.setText(f"路径规划中... 第 {layer_idx}/{total_layers} 层")
        self._sb.showMessage(f"路径规划中 – 已生成 {len(waypoints):,} 个航点")
        self._lb_bottom_status.setText(f"路径截面同步中：第 {layer_idx}/{total_layers} 层")
        self._lb_bottom_status.setStyleSheet(
            "color:#F59E0B; font-size:12px; padding:4px; font-weight:bold;"
        )
        self._visualizer.set_partial_waypoints(waypoints)
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        self._update_path_section(sel_mask, waypoints)

    @Slot(object)
    def _on_path_finished(self, waypoints: np.ndarray) -> None:
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        if waypoints is None or len(waypoints) == 0:
            waypoints = self._fallback_waypoints(sel_mask)
            warning("路径规划未生成航点，使用模拟航点")
        self._finish_path_planning(waypoints, sel_mask)

    @Slot(str)
    def _on_path_failed(self, message: str) -> None:
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        log_error(f"路径规划失败: {message}，使用模拟航点")
        try:
            self._finish_path_planning(self._fallback_waypoints(sel_mask), sel_mask, show_dialog=False)
            QMessageBox.warning(self, "路径规划回退", f"路径规划失败，已使用模拟航点。\n\n{message}")
        except Exception as exc:
            self._set_busy(False)
            QMessageBox.warning(self, "路径规划失败", str(exc))

    @Slot()
    def _on_path_thread_finished(self) -> None:
        self._path_thread = None
        self._path_worker = None

    def _on_zmq_path_result(self, result_msg) -> None:
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        try:
            result = _Coord.parse_repair_result(result_msg)
            if not _Coord.is_repair_success(result):
                raise RuntimeError(result["error_message"] or result["status_name"])
            waypoints = result["waypoints"]
            if len(waypoints) == 0:
                raise RuntimeError("黑盒返回成功，但没有航点数据")
            self._prog.setValue(70)
            self._lb_prog.setText("远程服务路径规划完成，正在刷新视图...")
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
                    "warnings": [],
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
            QMessageBox.warning(self, "远程服务路径规划失败", str(exc))

    def _on_zmq_path_error(self, message: str) -> None:
        self._set_busy(False)
        log_error(f"ZMQ 路径规划失败: {message}")
        QMessageBox.warning(self, "远程服务路径规划失败", message)

    @Slot(object, int, int)
    def _on_morph_partial(self, repair_pts: np.ndarray, layer_idx: int, total_layers: int) -> None:
        self._repair_xyz = np.vstack([self._xyz, repair_pts])
        self._prog.setValue(20 + int(70 * layer_idx / max(total_layers, 1)))
        self._lb_prog.setText(f"模拟沉积中... 第 {layer_idx}/{total_layers} 层")
        self._sb.showMessage(f"形貌预测中 – 当前 {len(repair_pts):,} 个沉积点")
        self._lb_bottom_status.setText(f"形貌截面同步中：第 {layer_idx}/{total_layers} 层")
        self._lb_bottom_status.setStyleSheet(
            "color:#F59E0B; font-size:12px; padding:4px; font-weight:bold;"
        )
        self._visualizer.set_partial_repair(repair_pts)
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        self._update_morph_section(sel_mask, repair_pts)

    @Slot(object)
    def _on_morph_finished(self, repair_pts: np.ndarray) -> None:
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        self._finish_morphology(repair_pts, sel_mask)

    @Slot(str, object)
    def _on_morph_failed(self, message: str, repair_pts: np.ndarray) -> None:
        log_error(f"形貌预测失败: {message}")
        sel_mask = self._sel_mask if self._sel_mask is not None else self._selector.get_selection_mask()
        if repair_pts is not None and len(repair_pts) > 0:
            self._finish_morphology(repair_pts, sel_mask)
            QMessageBox.warning(self, "形貌预测回退", f"形貌预测失败，已显示基础沉积点。\n\n{message}")
        else:
            self._set_busy(False)
            QMessageBox.warning(self, "形貌预测失败", message)

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
    @Slot()
    def _on_export_gcode(self) -> None:
        if self._mock_waypoints is None or len(self._mock_waypoints) == 0:
            QMessageBox.warning(self, "无路径", "请先生成修复路径。")
            return
        ok, validation = self._export_service.validate_toolpath(self._mock_waypoints)
        if not ok:
            QMessageBox.warning(self, "导出安全检查未通过", "\n".join(validation.blocking_messages))
            return
        fp, _ = QFileDialog.getSaveFileName(self, "导出 G-code", "repair.nc", "G-code (*.nc *.gcode *.txt)")
        if not fp: return
        try:
            feed_rate = self._collect_params().get("traversing_speed_mms", 500) * 60
            success = self._export_service.export_gcode(
                self._mock_waypoints, output_path=fp, feed_rate=feed_rate,
            )
            if success:
                self._sb.showMessage(f"G-code 已保存: {fp}")
                warnings = validation.warning_messages
                suffix = "\n\n安全检查警告:\n" + "\n".join(warnings) if warnings else ""
                QMessageBox.information(self, "导出成功", f"G-code 已保存:\n{fp}{suffix}")
            else:
                QMessageBox.warning(self, "导出失败", "G-code 导出失败，请查看日志。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    @Slot()
    def _on_export_pdf(self) -> None:
        if self._xyz is None:
            QMessageBox.warning(self, "无数据", "请先执行形貌预测。")
            return
        fp, _ = QFileDialog.getSaveFileName(self, "导出修复报告", "repair_report.pdf", "PDF 文件 (*.pdf)")
        if not fp: return
        self._sb.showMessage("正在生成 PDF 报告...")
        QApplication.processEvents()
        try:
            sel_mask = self._selector.get_selection_mask()
            defect_metrics = self._compute_defect_metrics(sel_mask)
            path_metrics = self._compute_path_metrics()
            scan_info = {
                "scan_id": f"SCAN-{self._latest_seed:04d}",
                "points": len(self._xyz) if self._xyz is not None else 0,
                "defect_volume_mm3": defect_metrics["volume_mm3"],
                "defect_depth_mm": defect_metrics["depth_mm"],
                "material": self._cb_mat.currentText(),
            }
            results = {
                "填充点数": f"{len(self._repair_xyz) if self._repair_xyz is not None else 0:,}",
                "修复层数": str(self._sp_max_layers.value()),
                "缺陷选区点数": f"{defect_metrics['point_count']:,}",
                "估算缺陷面积": f"{defect_metrics['area_mm2']:.2f} mm²",
                "路径长度": f"{path_metrics['path_length_mm']:.2f} mm",
                "预计加工时间": f"{path_metrics['estimated_time_s']:.1f} s",
                "可行性评分": f"{self._feas_result.score:.1%}" if self._feas_result else "—",
            }
            ok = self._export_service.export_pdf_report(
                output_path=fp,
                scan_info=scan_info,
                parameters=self._collect_params(),
                results=results,
                xyz=self._xyz,
                defect_mask=sel_mask,
                repair_xyz=self._repair_xyz,
            )
            if ok:
                self._sb.showMessage(f"报告已保存: {fp}")
                QMessageBox.information(self, "导出成功", f"报告已保存到:\n{fp}")
            else:
                QMessageBox.warning(self, "导出失败", "PDF 报告生成失败，请查看日志。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        for thread in (self._path_thread, self._morph_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(2000):
                    thread.terminate()
                    thread.wait(1000)
        if self._zmq_client is not None and hasattr(self._zmq_client, "close"):
            self._zmq_client.close()
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
