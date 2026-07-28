"""
panel_builder.py — UI 面板构建器（PanelBuilder）

Phase 16: 从 MainWindow 提取 UI 构建方法为静态方法，
减少 MainWindow 行数（~3334 → ~2000），保持所有功能不变。

所有方法均为静态方法，接收 parent 参数代替 self。
"""
from __future__ import annotations

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QComboBox,
    QProgressBar, QGroupBox, QFrame,
    QTabWidget, QTextEdit,
    QStackedWidget, QCheckBox, QSplitter, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt

from repair_app.ui.theme_manager import ThemeManager
from repair_app.ui.defect_selector import DefectSelector
from repair_app.ui.repair_visualizer import RepairVisualizer
from repair_app.ui.profile_result_panel import ProfileResultPanel
from repair_app.service.coordination_service import CoordinationService as _Coord
from repair_app.export.pipeline import ExporterRegistry
from repair_app.utils.config import (
    MATERIALS, MAT_KEY_MAP, mode as _mode_cfg, page as _page_cfg,
    get_ui_param, UI_PARAM_SPECS,
)
from repair_app.utils.app_config import AppConfig
from repair_app.config import schema_loader
from repair_app import __version__ as APP_VERSION

_ZMQ_AVAILABLE = _Coord().zmq_available

# 修复模式
MODE_ADDITIVE = _mode_cfg.additive
MODE_REPAIRING = _mode_cfg.repairing

PAGE_PATH = _page_cfg.path
PAGE_MORPH = _page_cfg.morph
PAGE_OUTPUT = _page_cfg.output


class PanelBuilder:
    """UI 面板构建器 — 所有方法均为静态方法，不持有状态。"""

    # ====== 辅助控件 ======

    @staticmethod
    def kv(k, v):
        p = ThemeManager.get_palette()
        l = QLabel(f"{k}: {v}")
        l.setStyleSheet(f"color:{p.text_secondary}; font-size:13px; padding:3px 0;")
        return l

    @staticmethod
    def sep():
        p = ThemeManager.get_palette()
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFrameShadow(QFrame.Sunken)
        f.setStyleSheet(f"color:{p.text_body};")
        return f

    # ====== App Header ======

    @staticmethod
    def build_app_header(parent) -> QWidget:
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

        parent._lb_mode_state = QLabel("修复模式")
        parent._lb_mode_state.setObjectName("HeaderChip")
        parent._lb_workflow_state = QLabel("等待数据")
        parent._lb_workflow_state.setObjectName("HeaderChip")
        layout.addWidget(parent._lb_mode_state)
        layout.addWidget(parent._lb_workflow_state)
        return header

    # ====== Left Column ======

    @staticmethod
    def build_left_column(parent) -> QWidget:
        p = ThemeManager.get_palette()
        outer = QWidget()
        outer.setObjectName("SideRail")
        outer.setMinimumWidth(220)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- 步骤按钮栏 ---
        workflow = QGroupBox("工作流")
        sl = QVBoxLayout(workflow)
        sl.setContentsMargins(12, 18, 12, 12)
        sl.setSpacing(8)

        parent._step1_btn = QPushButton("01  数据与路径\n加载点云、选区、生成路径")
        parent._step1_btn.setMinimumHeight(58)
        parent._step1_btn.setCursor(Qt.PointingHandCursor)
        parent._step1_btn.clicked.connect(lambda: parent._switch_to_step(PAGE_PATH))
        sl.addWidget(parent._step1_btn)

        parent._arrow_lb = QLabel("↓")
        parent._arrow_lb.setAlignment(Qt.AlignCenter)
        sl.addWidget(parent._arrow_lb)

        parent._step2_btn = QLabel("02  形貌预测\n等待路径规划输出")
        parent._step2_btn.setMinimumHeight(54)
        parent._step2_btn.setAlignment(Qt.AlignCenter)
        parent._style_workflow_label(parent._step2_btn, "locked")
        sl.addWidget(parent._step2_btn)

        parent._step3_lb = QLabel("03  结果校核\n查看指标、截面和风险")
        parent._step3_lb.setMinimumHeight(54)
        parent._step3_lb.setAlignment(Qt.AlignCenter)
        parent._step3_lb.setStyleSheet(
            f"color:{p.text_disabled}; font-size:11px; padding:8px; "
            f"background:{p.bg_panel}; border:1px dashed {p.border_strong}; border-radius:6px;"
        )
        sl.addWidget(parent._step3_lb)

        parent._step4_btn = QPushButton("04  输出交付\n导出 G-code 与 PDF 报告")
        parent._step4_btn.setMinimumHeight(58)
        parent._step4_btn.setCursor(Qt.PointingHandCursor)
        parent._step4_btn.setEnabled(False)
        parent._step4_btn.clicked.connect(lambda: parent._switch_to_step(PAGE_OUTPUT))
        sl.addWidget(parent._step4_btn)
        layout.addWidget(workflow)

        # --- 材料选择 ---
        mat_bar = QGroupBox("材料选择")
        mat_ml = QVBoxLayout(mat_bar)
        mat_ml.setSpacing(4)
        mat_row = QHBoxLayout()
        mat_row.addWidget(QLabel("材料"))
        parent._cb_mat = QComboBox()
        parent._cb_mat.setToolTip("选择喷涂材料。不同材料有不同的临界速度和密度，影响沉积效率和涂层质量。")
        for label, _ in MATERIALS:
            parent._cb_mat.addItem(label)
        parent._cb_mat.setCurrentIndex(1)
        parent._cb_mat.currentIndexChanged.connect(parent._on_material_changed)
        mat_row.addWidget(parent._cb_mat)
        mat_row.addStretch()
        mat_ml.addLayout(mat_row)
        parent._lb_mat_info = QLabel("v_cr: — m/s | 密度: — kg/m³")
        parent._lb_mat_info.setStyleSheet(f"color:{p.text_disabled}; font-size:11px; padding-left:4px;")
        mat_ml.addWidget(parent._lb_mat_info)
        layout.addWidget(mat_bar)

        # --- QStackedWidget ---
        parent._mode_stack = QStackedWidget()
        parent._mode_stack.addWidget(PanelBuilder.build_path_planning_panel(parent))
        parent._mode_stack.addWidget(PanelBuilder.build_morphology_panel(parent))
        parent._mode_stack.addWidget(PanelBuilder.build_output_panel(parent))
        layout.addWidget(parent._mode_stack)
        return outer

    # ====== Panel A: 路径规划 ======

    @staticmethod
    def build_path_planning_panel(parent) -> QWidget:
        if not hasattr(parent, "_pp_fields"):
            parent._pp_fields = {}
        p = ThemeManager.get_palette()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QFrame()
        scroll.setWidget(panel)
        l = QVBoxLayout(panel)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(8)

        parent._btn_load = QPushButton("📂 加载点云")
        parent._btn_load.setMinimumHeight(38)
        parent._btn_load.setToolTip("加载点云文件（支持 CSV、TXT、XYZ、ASC 格式）")
        parent._btn_load.clicked.connect(parent._on_load)
        l.addWidget(parent._btn_load)
        l.addWidget(PanelBuilder.sep())

        # --- 修复模式选择 ---
        mg = QGroupBox("修复模式")
        ml = QVBoxLayout(mg)
        ml.setSpacing(4)
        parent._rb_additive = QRadioButton(" 增材模式（全表面覆盖）")
        parent._rb_repairing = QRadioButton(" 修复模式（缺陷填充）")
        parent._rb_repairing.setChecked(True)
        parent._mode_group = QButtonGroup(parent)
        parent._mode_group.addButton(parent._rb_additive, MODE_ADDITIVE)
        parent._mode_group.addButton(parent._rb_repairing, MODE_REPAIRING)
        parent._mode_group.idClicked.connect(parent._on_mode_changed)
        ml.addWidget(parent._rb_additive)
        ml.addWidget(parent._rb_repairing)
        l.addWidget(mg)

        parent._lb_mode_hint = QLabel("💡 在中心视图框选缺陷区域 → 调参数 → 点击生成路径")
        parent._lb_mode_hint.setStyleSheet(f"color:{p.text_disabled}; font-size:11px; padding:4px;")
        parent._lb_mode_hint.setWordWrap(True)
        l.addWidget(parent._lb_mode_hint)

        eg = QGroupBox("计算引擎")
        el = QVBoxLayout(eg)
        el.setSpacing(4)
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("引擎"))
        parent._cb_engine = QComboBox()
        parent._cb_engine.setToolTip("选择计算引擎。本地引擎用于快速预览；远程服务连接 MATLAB 获取精确计算结果。生产环境建议使用远程服务。")
        parent._cb_engine.addItem("本地计算引擎", "local")
        parent._cb_engine.addItem("远程服务 (MATLAB)", "zmq")
        if not _ZMQ_AVAILABLE:
            parent._cb_engine.model().item(1).setEnabled(False)
        else:
            parent._cb_engine.setCurrentIndex(1)
        parent._cb_engine.currentIndexChanged.connect(parent._on_engine_changed)
        engine_row.addWidget(parent._cb_engine)
        engine_row.addStretch()
        el.addLayout(engine_row)
        parent._lb_engine_hint = QLabel("本地引擎支持逐层实时刷新；远程服务用于连接 MATLAB 获取最终计算结果。")
        parent._lb_engine_hint.setStyleSheet(f"color:{p.text_disabled}; font-size:11px; padding:4px;")
        parent._lb_engine_hint.setWordWrap(True)
        el.addWidget(parent._lb_engine_hint)
        eg.setVisible(False)
        l.addWidget(eg)

        ppg = QGroupBox("路径规划参数")
        ppl = QVBoxLayout(ppg)
        ppl.setSpacing(5)
        # MF-8: 从 PARAM_SPECS 唯一权威源动态生成（消除硬编码范围双源冲突）
        for spec_key, ui_key, label, suffix, tooltip, _grp, read_only in UI_PARAM_SPECS:
            if _grp != schema_loader.PATH_PLANNING_GROUP:
                continue
            lo, hi, default, step = get_ui_param(spec_key)[:4]
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(default)
            sp.setSingleStep(step)
            sp.setSuffix(suffix)
            sp.setMinimumWidth(100)
            sp.setToolTip(tooltip)
            if read_only:
                sp.setEnabled(False)
            row.addWidget(sp)
            row.addStretch()
            ppl.addLayout(row)
            parent._pp_fields[ui_key] = sp

        nl_row = QHBoxLayout()
        nl_row.addWidget(QLabel("规划层数"))
        parent._sp_pp_layers = QSpinBox()
        _nl = schema_loader.get_process_param("num_layers")
        parent._sp_pp_layers.setRange(int(_nl["min"]), int(_nl["max"]))
        parent._sp_pp_layers.setSingleStep(int(_nl["step"]))
        parent._sp_pp_layers.setValue(int(_nl["default"]))
        parent._sp_pp_layers.setMinimumWidth(100)
        parent._sp_pp_layers.setToolTip(_nl["tooltip"])
        nl_row.addWidget(parent._sp_pp_layers)
        nl_row.addStretch()
        ppl.addLayout(nl_row)
        l.addWidget(ppg)

        # --- 文件保存选项 ---
        sg = QGroupBox("输出选项")
        sl2 = QVBoxLayout(sg)
        sl2.setSpacing(4)
        parent._chk_save_files = QCheckBox("保存计算中间文件到磁盘")
        parent._chk_save_files.setChecked(True)
        parent._chk_save_files.setStyleSheet(f"color:{p.text_body}; font-size:12px;")
        parent._chk_save_files.setToolTip("勾选：保存路径与速度数据供形貌预测读取；不勾选：数据仅保留在内存中")
        sl2.addWidget(parent._chk_save_files)
        hint2 = QLabel("  勾选：路径规划后保存中间文件，形貌预测从文件读取\n"
                        "  不勾选：数据仅保留在内存中，不写入磁盘")
        hint2.setStyleSheet(f"color:{p.text_disabled}; font-size:10px;")
        hint2.setWordWrap(True)
        sl2.addWidget(hint2)
        l.addWidget(sg)

        # --- 操作 ---
        og = QGroupBox("操作")
        ol = QVBoxLayout(og)
        ol.setSpacing(8)
        parent._btn_start_repair = QPushButton("🚀 开始修复")
        parent._btn_start_repair.setMinimumHeight(48)
        parent._btn_start_repair.setEnabled(False)
        parent._btn_start_repair.setToolTip(
            "一键执行完整修复流程：\n"
            "路径规划 → 形貌预测 → 报告生成 → 安全校验\n"
            "根据引擎自动选择本地快速预览或 MATLAB 精确计算"
        )
        parent._btn_start_repair.clicked.connect(parent._on_start_repair)
        parent._btn_start_repair.setStyleSheet(
            f"QPushButton{{background:{p.success};color:#FFF;border:none;border-radius:6px;"
            "font-size:15px;font-weight:bold;}"
            f"QPushButton:hover{{background:{p.success};}}"
            f"QPushButton:disabled{{background:{p.border_strong};color:{p.text_disabled};}}"
        )
        ol.addWidget(parent._btn_start_repair)
        parent._btn_cancel_repair = QPushButton("取消当前计算")
        parent._btn_cancel_repair.setMinimumHeight(36)
        parent._btn_cancel_repair.setEnabled(False)
        parent._btn_cancel_repair.setToolTip(
            "请求 MATLAB 在下一个安全检查点停止；若超时，只会终止本软件拥有的 Worker。"
        )
        parent._btn_cancel_repair.clicked.connect(parent._on_cancel_computation)
        ol.addWidget(parent._btn_cancel_repair)

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Panel B: 形貌预测 ======

    @staticmethod
    def build_morphology_panel(parent) -> QWidget:
        if not hasattr(parent, "_cs_fields"):
            parent._cs_fields = {}
        p = ThemeManager.get_palette()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QFrame()
        scroll.setWidget(panel)
        l = QVBoxLayout(panel)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(8)

        # --- 输入状态 ---
        fg = QGroupBox("输入数据来源")
        fl = QVBoxLayout(fg)
        fl.setSpacing(4)

        parent._lb_pl_status = QLabel("⏳ 请先完成路径规划")
        parent._lb_pl_status.setStyleSheet(f"color:{p.warning}; font-size:13px;")
        fl.addWidget(parent._lb_pl_status)

        parent._lb_input_source = QLabel("来源: —")
        parent._lb_input_source.setStyleSheet(f"color:{p.text_disabled}; font-size:11px;")
        fl.addWidget(parent._lb_input_source)
        l.addWidget(fg)

        # --- 冷喷涂工艺参数 ---
        cpg = QGroupBox("冷喷涂工艺参数")
        cpl = QVBoxLayout(cpg)
        cpl.setSpacing(5)
        # MF-8: 从 PARAM_SPECS 唯一权威源动态生成（消除硬编码范围双源冲突）
        for spec_key, ui_key, label, suffix, tooltip, _grp, read_only in UI_PARAM_SPECS:
            if _grp != schema_loader.COLD_SPRAY_GROUP:
                continue
            lo, hi, default, step = get_ui_param(spec_key)[:4]
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(default)
            sp.setSingleStep(step)
            sp.setSuffix(suffix)
            sp.setMinimumWidth(100)
            sp.setToolTip(tooltip)
            if read_only:
                sp.setEnabled(False)
            row.addWidget(sp)
            row.addStretch()
            cpl.addLayout(row)
            parent._cs_fields[ui_key] = sp
        # 临界速度只读提示（额外补充）
        if "critical_velocity" in parent._cs_fields:
            parent._cs_fields["critical_velocity"].setToolTip(
                "临界速度由材料数据库自动计算，不可手动修改"
            )
        l.addWidget(cpg)

        dg = QGroupBox("沉积参数")
        dl = QVBoxLayout(dg)
        dl.setSpacing(5)
        dr = QHBoxLayout()
        dr.addWidget(QLabel("深度补偿"))
        parent._sp_depth = QDoubleSpinBox()
        _dc = schema_loader.get_process_param("depth_compensation")
        parent._sp_depth.setRange(_dc["min"], _dc["max"])
        parent._sp_depth.setValue(_dc["default"])
        parent._sp_depth.setSingleStep(_dc["step"])
        parent._sp_depth.setSuffix(" x")
        parent._sp_depth.setMinimumWidth(90)
        parent._sp_depth.setToolTip(_dc["tooltip"])
        dr.addWidget(parent._sp_depth)
        dr.addStretch()
        dl.addLayout(dr)
        nr = QHBoxLayout()
        nr.addWidget(QLabel("预测层数"))
        parent._sp_max_layers = QSpinBox()
        _ml = schema_loader.get_process_param("max_morphology_layers")
        parent._sp_max_layers.setRange(int(_ml["min"]), int(_ml["max"]))
        parent._sp_max_layers.setSingleStep(int(_ml["step"]))
        parent._sp_max_layers.setValue(int(_ml["default"]))
        parent._sp_max_layers.setMinimumWidth(90)
        parent._sp_max_layers.setToolTip(_ml["tooltip"])
        nr.addWidget(parent._sp_max_layers)
        nr.addStretch()
        dl.addLayout(nr)
        l.addWidget(dg)

        og = QGroupBox("操作")
        ol = QVBoxLayout(og)
        ol.setSpacing(8)
        parent._btn_feas = QPushButton("🔍 可行性检查")
        parent._btn_feas.setMinimumHeight(34)
        parent._btn_feas.setEnabled(False)
        parent._btn_feas.setToolTip("检查当前工艺参数和缺陷区域是否适合冷喷涂修复")
        parent._btn_feas.clicked.connect(parent._on_feasibility_check)
        ol.addWidget(parent._btn_feas)

        parent._btn_fix = QPushButton("🔮 执行形貌预测")
        parent._btn_fix.setMinimumHeight(42)
        parent._btn_fix.setEnabled(False)
        parent._btn_fix.setToolTip("基于路径规划输出模拟冷喷涂沉积过程，预测修复形貌")
        parent._btn_fix.clicked.connect(parent._on_fix)
        parent._btn_fix.setStyleSheet(
            f"QPushButton{{background:{p.accent};color:#FFF;border:none;border-radius:6px;"
            "font-size:14px;font-weight:bold;}"
            f"QPushButton:hover{{background:{p.accent_light};}}"
            f"QPushButton:disabled{{background:{p.border_strong};color:{p.text_disabled};}}"
        )
        ol.addWidget(parent._btn_fix)

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Panel C: 输出交付 ======

    @staticmethod
    def build_output_panel(parent) -> QWidget:
        """04 输出交付面板：集中放置所有导出入口。

        P5-4: 从 ExporterRegistry 动态构建导出按钮。新增导出格式只需注册
        BaseExporter 子类，无需修改本方法或 MainWindow 任何代码。
        """
        p = ThemeManager.get_palette()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QFrame()
        scroll.setWidget(panel)
        l = QVBoxLayout(panel)
        l.setContentsMargins(10, 10, 10, 10)
        l.setSpacing(8)

        og = QGroupBox("导出")
        ol = QVBoxLayout(og)
        ol.setSpacing(6)

        # P5-4: 从注册表动态构建按钮
        parent._export_buttons = {}
        for exporter in ExporterRegistry.list():
            btn = QPushButton(f"{exporter.icon} 导出 {exporter.display_name}")
            btn.setMinimumHeight(42 if exporter.sort_order == 10 else 34)
            btn.setEnabled(False)
            btn.setToolTip(exporter.tooltip)
            # 第一个导出器（G-code）使用醒目样式
            if exporter.sort_order == 10:
                btn.setStyleSheet(
                    f"QPushButton{{background:{p.accent_hover};color:#FFF;border:none;border-radius:6px;"
                    "font-size:14px;font-weight:bold;}"
                    f"QPushButton:hover{{background:{p.accent};}}"
                    f"QPushButton:disabled{{background:{p.border_strong};color:{p.text_disabled};}}"
                )
            btn.clicked.connect(lambda checked, name=exporter.name: parent._on_export(name))
            ol.addWidget(btn)
            parent._export_buttons[exporter.name] = btn
            # 向后兼容：保持 _btn_exp_gcode/_btn_exp_robot/_btn_exp_pdf 属性
            if exporter.name == "gcode":
                parent._btn_exp_gcode = btn
            elif exporter.name == "robot":
                parent._btn_exp_robot = btn
            elif exporter.name == "pdf":
                parent._btn_exp_pdf = btn

        l.addWidget(og)
        l.addStretch()
        return scroll

    # ====== Center ======

    @staticmethod
    def build_center(parent) -> QWidget:
        p = ThemeManager.get_palette()
        parent._center_widget = QWidget()
        parent._center_widget.setObjectName("Workspace")
        layout = QVBoxLayout(parent._center_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        parent._workspace_stack = QStackedWidget()
        parent._workspace_stack.setObjectName("WorkspaceStack")

        # ---- 步骤 01：路径规划工作区 ----
        path_workspace = QWidget()
        path_layout = QVBoxLayout(path_workspace)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)

        parent._selector = DefectSelector()
        parent._selector.selection_changed.connect(parent._on_selection_changed)

        parent._visualizer = RepairVisualizer()

        # ---- 中心区 Tab 切换：3D 预览 / MATLAB 形貌分析 ----
        parent._center_tabs = QTabWidget()
        parent._center_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border:1px solid {p.border_default}; border-radius:8px; background:{p.bg_app}; top:-1px; }}
            QTabBar::tab {{ background:{p.bg_panel}; color:{p.text_muted}; padding:6px 14px; margin-right:2px;
                           border:1px solid {p.border_default}; border-bottom:none;
                           border-top-left-radius:6px; border-top-right-radius:6px; font-weight:600; }}
            QTabBar::tab:selected {{ background:{p.accent_hover}; color:#FFFFFF; }}
            QTabBar::tab:hover:!selected {{ background:{p.border_default}; color:{p.text_body}; }}
        """)
        parent._center_tabs.addTab(parent._visualizer, "3D 预览（基体/路径/喷嘴）")

        parent._profile_panel = ProfileResultPanel()
        parent._center_tabs.addTab(parent._profile_panel, "MATLAB 形貌分析")
        parent._center_tabs.setCurrentIndex(0)

        parent._main_splitter = QSplitter(Qt.Horizontal)
        parent._main_splitter.addWidget(parent._center_tabs)

        right_panel = QWidget()
        right_panel.setObjectName("AuxPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        parent._lb_selector_title = QLabel("原始点云 / 缺陷选区")
        parent._lb_selector_title.setStyleSheet(
            f"color:{p.text_muted}; font-size:11px; padding:2px 4px; font-weight:bold;"
        )
        right_layout.addWidget(parent._lb_selector_title)
        right_layout.addWidget(parent._selector, 5)

        # ---- 路径规划 + 形貌预测辅助截面 ----
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        fig_bottom = Figure(figsize=(4.5, 5.5), dpi=100)
        fig_bottom.set_facecolor(p.bg_panel)
        parent._canvas_bottom = FigureCanvas(fig_bottom)

        gs = fig_bottom.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.45)
        parent._ax_path = fig_bottom.add_subplot(gs[0])
        parent._ax_path.set_facecolor(p.bg_panel)
        parent._ax_path.set_title("截面路径规划", color=p.text_muted, fontsize=10)
        parent._ax_path.tick_params(colors=p.text_disabled, labelsize=8)
        for spine in parent._ax_path.spines.values():
            spine.set_color(p.border_strong)
        parent._ax_path.grid(True, color=p.border_default, alpha=0.5)

        parent._ax_morph = fig_bottom.add_subplot(gs[1])
        parent._ax_morph.set_facecolor(p.bg_panel)
        parent._ax_morph.set_title("形貌预测结果", color=p.text_muted, fontsize=10)
        parent._ax_morph.tick_params(colors=p.text_disabled, labelsize=8)
        for spine in parent._ax_morph.spines.values():
            spine.set_color(p.border_strong)
        parent._ax_morph.grid(True, color=p.border_default, alpha=0.5)

        parent._lb_bottom_status = QLabel("请先完成路径规划...")
        parent._lb_bottom_status.setStyleSheet(f"color:{p.text_disabled}; font-size:11px; padding:4px;")
        parent._lb_bottom_status.setAlignment(Qt.AlignCenter)

        bottom_panel = QWidget()
        bottom_panel.setObjectName("AuxPanel")
        bl = QVBoxLayout(bottom_panel)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(6)
        bl.addWidget(parent._lb_bottom_status)
        bl.addWidget(parent._canvas_bottom)
        right_layout.addWidget(bottom_panel, 4)

        parent._main_splitter.addWidget(right_panel)
        parent._main_splitter.setSizes([760, 430])
        path_layout.addWidget(parent._main_splitter)

        parent._workspace_stack.addWidget(path_workspace)
        layout.addWidget(parent._workspace_stack, 1)

        # ---- 实时统计面板 + 逐层播放器 ----
        from repair_app.ui.realtime_stats import RealtimeStatsPanel
        from repair_app.ui.layer_player import LayerPlayer
        parent._realtime_stats = RealtimeStatsPanel()
        layout.addWidget(parent._realtime_stats)
        parent._layer_player = LayerPlayer()
        parent._layer_player.layer_changed.connect(parent._on_layer_changed)
        layout.addWidget(parent._layer_player)

        parent._top_splitter = parent._main_splitter  # 兼容旧引用
        parent._bottom_splitter = parent._main_splitter
        parent._tabs = parent._main_splitter  # 兼容旧引用
        return parent._center_widget

    # ====== Right Column ======

    @staticmethod
    def build_right_column(parent) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(260)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        p = QFrame()
        scroll.setWidget(p)
        p.setObjectName("Inspector")
        l = QVBoxLayout(p)
        l.setContentsMargins(12, 12, 12, 12)
        l.setSpacing(10)

        ig = QGroupBox("点云信息")
        il = QVBoxLayout(ig)
        parent._lb_pts = QLabel("点数: —")
        il.addWidget(parent._lb_pts)
        parent._lb_sel = QLabel("已选: 0")
        il.addWidget(parent._lb_sel)
        l.addWidget(ig)

        fg = QGroupBox("可行性报告")
        fl = QVBoxLayout(fg)
        parent._lb_feas_status = QLabel("状态: 尚未检查")
        fl.addWidget(parent._lb_feas_status)
        parent._lb_feas_score = QLabel("评分: —")
        fl.addWidget(parent._lb_feas_score)
        parent._feas_text = QTextEdit()
        parent._feas_text.setReadOnly(True)
        parent._feas_text.setMinimumHeight(80)
        parent._feas_text.setMaximumHeight(250)
        parent._feas_text.setPlaceholderText("点击'可行性检查'后显示...")
        fl.addWidget(parent._feas_text)
        l.addWidget(fg)

        pg = QGroupBox("进度")
        pl = QVBoxLayout(pg)
        parent._prog = QProgressBar()
        parent._prog.setRange(0, 100)
        parent._prog.setValue(0)
        pl.addWidget(parent._prog)
        parent._lb_prog = QLabel("就绪")
        pl.addWidget(parent._lb_prog)
        l.addWidget(pg)

        rg = QGroupBox("结果摘要")
        rl = QVBoxLayout(rg)
        rl.setSpacing(5)
        parent._lb_vol = PanelBuilder.kv("填充点数", "— pts")
        parent._lb_mass = PanelBuilder.kv("材料用量", "— g")
        parent._lb_time = PanelBuilder.kv("预计耗时", "— s")
        parent._lb_lay = PanelBuilder.kv("修复层数", "—")
        parent._lb_unif = PanelBuilder.kv("均匀性", "—")
        parent._lb_feas = PanelBuilder.kv("可行性", "—")
        rl.addWidget(parent._lb_vol)
        rl.addWidget(parent._lb_mass)
        rl.addWidget(parent._lb_time)
        rl.addWidget(parent._lb_lay)
        rl.addWidget(parent._lb_unif)
        rl.addWidget(parent._lb_feas)
        l.addWidget(rg)
        l.addStretch()
        return scroll
