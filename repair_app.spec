# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 冷喷涂缺陷修复软件 (Production Release)
# 用法: pyinstaller --clean repair_app.spec

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(SPECPATH)  # SPECPATH = spec文件所在目录

# 从包中读取版本号（单一数据源）
sys.path.insert(0, str(PROJECT_DIR))
try:
    from repair_app import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = "0.0.0"

IS_MACOS = sys.platform == 'darwin'
IS_WINDOWS = sys.platform == 'win32'

# Production builds must be tied to the deployment public key. The key may
# live outside the repository; never generate or commit a production private
# key just to satisfy PyInstaller.
_public_key_env = os.environ.get('CSAM_PUBLIC_KEY_PATH', '').strip()
PUBLIC_KEY_PATH = (
    Path(_public_key_env).expanduser()
    if _public_key_env
    else PROJECT_DIR / 'config' / 'public_key.pem'
)
if not PUBLIC_KEY_PATH.is_file():
    raise SystemExit(
        "License public key not found. Set CSAM_PUBLIC_KEY_PATH to the "
        "deployment public_key.pem, or place it at config/public_key.pem."
    )

# --- Icon 配置 ---
ICON_PATH = None
# 优先在项目根目录查找图标，回退到 docs/images/
_icon_search_dirs = [PROJECT_DIR, PROJECT_DIR / 'docs' / 'images']
for _icon_dir in _icon_search_dirs:
    for ext in ['.ico', '.png', '.jpg']:
        candidate = _icon_dir / f'p1{ext}'
        if candidate.exists():
            ICON_PATH = str(candidate)
            break
    if ICON_PATH:
        break

# --- 资源文件 ---
datas = [
    # 材料数据库
    (str(PROJECT_DIR / 'repair_app' / 'core' / 'material_db.json'), 'repair_app/core'),
    # 参数 Schema（单一 Truth Source，启动时必需）
    (str(PROJECT_DIR / 'repair_app' / 'config' / 'parameter_schema.json'), 'repair_app/config'),
    # 标定配置
    (str(PROJECT_DIR / 'config' / 'calibration_db.json'), 'config'),
    # License 公钥（打包后许可证验证必需，从 _MEIPASS 只读加载）
    (str(PUBLIC_KEY_PATH), 'config'),
    # 应用级配置（Developer Mode 开关等，从 _MEIPASS 只读加载）
    (str(PROJECT_DIR / 'config' / 'app_config.json'), 'config'),
    # MATLAB Bridge Server 脚本
    (str(PROJECT_DIR / 'matlab_bridge_server.m'), '.'),
    # MATLAB 路径规划算法
    (str(PROJECT_DIR / 'path_planning'), 'path_planning'),
    # MATLAB 形貌预测算法
    (str(PROJECT_DIR / 'profile_prediction'), 'profile_prediction'),
    # proto 文件
    (str(PROJECT_DIR / 'repair_protocol.proto'), '.'),
]

# Windows: 添加 Visual C++ 运行时
if IS_WINDOWS:
    # PyInstaller 会自动检测 VC 运行时，但显式包含更安全
    pass

a = Analysis(
    [str(PROJECT_DIR / 'run_app.py')],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PySide6
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg', 'PySide6.QtNetwork',
        # protobuf
        'google.protobuf', 'google.protobuf.descriptor',
        'google.protobuf.message', 'google.protobuf.reflection',
        'google.protobuf.internal', 'google.protobuf.internal.enum_type_wrapper',
        'google.protobuf.runtime_version',
        # zmq
        'zmq', 'zmq.backend.cython', 'zmq.utils',
        # matplotlib
        'matplotlib', 'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.figure', 'matplotlib.backends.backend_svg',
        # numpy
        'numpy', 'numpy.core._methods', 'numpy.lib.format',
        # scipy
        'scipy', 'scipy.spatial', 'scipy.spatial.kdtree',
        'scipy.interpolate', 'scipy.spatial.transform', 'scipy.ndimage',
        # reportlab
        'reportlab', 'reportlab.graphics',
        'reportlab.lib.pagesizes', 'reportlab.pdfgen',
        'reportlab.platypus', 'reportlab.lib.styles',
        # cryptography
        'cryptography', 'cryptography.hazmat.backends',
        # shapely (条件导入，需显式声明)
        'shapely', 'shapely.geometry', 'shapely.ops',
        # 本地模块 — 完整包路径
        'repair_app',
        'repair_app.platform', 'repair_app.platform.transport', 'repair_app.platform.fonts',
        'repair_app.communication.repair_protocol_pb2', 'repair_app.communication.repair_serialization',
        'repair_app.communication.zmq_client',
        'repair_app.core.defect_sample', 'repair_app.core.feasibility_checker',
        'repair_app.core.material_database', 'repair_app.core.path_planner',
        'repair_app.core.morphology_predictor', 'repair_app.core.stl_reader',
        'repair_app.core.normal_estimator',
        'repair_app.export.report_generator', 'repair_app.export.gcode_exporter',
        'repair_app.export.export_validator',
        'repair_app.ui.defect_selector', 'repair_app.ui.repair_visualizer',
        'repair_app.ui.main_window', 'repair_app.ui.workers',
        'repair_app.ui.profile_result_panel', 'repair_app.ui.pipeline_indicator',
        'repair_app.ui.progress_subscriber', 'repair_app.ui.layer_player',
        'repair_app.ui.realtime_stats',
        'repair_app.utils.license_manager', 'repair_app.utils.logger_config',
        'repair_app.utils.look_up', 'repair_app.utils.config',
        'repair_app.utils.crash_handler', 'repair_app.utils.resource_path',
        'repair_app.utils.app_config',
        'repair_app.service.repair_engine_service', 'repair_app.service.file_service',
        'repair_app.service.export_service',
        'repair_app.service.validation_service',
        'repair_app.repository.file_repository', 'repair_app.repository.material_repository',
        'repair_app.domain.models', 'repair_app.domain.interfaces',
        # 独立模块（已整合到 repair_app 包内）
        'repair_app.export.robot_exporter', 'repair_app.utils.calibration_wizard',
        # V1.0: bridge 通信层 + MATLAB 执行平台
        'repair_app.bridge', 'repair_app.bridge.adapters.legacy_adapter',
        'repair_app.bridge.adapters.matlab_adapter',
        'repair_app.bridge.adapters.matlab_engine_proxy',
        'repair_app.bridge.adapters.matlab_pipeline',
        'repair_app.bridge.launcher',
        'repair_app.bridge.lifecycle_manager',
        'repair_app.bridge.operation_control',
        'repair_app.bridge.progress_publisher',
        'repair_app.bridge.services.matlab_service',
        # bridge.communication.* 子模块（PyInstaller 无法自动发现）
        'repair_app.bridge.communication.config',
        'repair_app.bridge.communication.heartbeat',
        'repair_app.bridge.communication.message',
        'repair_app.bridge.communication.protocol',
        'repair_app.bridge.communication.serializer',
        'repair_app.bridge.communication.zmq_client',
        'repair_app.bridge.communication.zmq_server',
        'repair_app.bridge.communication.exceptions',
        # loguru（结构化日志，多处动态导入）
        'loguru',
        'repair_app.engine.local_engine',
        'repair_app.software.path_manager',
        'repair_app.software.project_manager',
        'repair_app.software.exception_reporter',
        'repair_app.software.about_dialog',
        # V1.0: 算法验证体系（MATLAB/Python 双引擎比对）
        'repair_app.validation',
        'repair_app.validation.algorithm_validator',
        'repair_app.validation.result_comparator',
        'repair_app.validation.diff_report_generator',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(PROJECT_DIR / 'hooks' / 'pyi_runtime_hook.py'),
    ],
    excludes=[
        'pywin32', 'pynput',
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_wxagg',
        'matplotlib.backends.backend_gtk',
        # 排除不需要的 PySide6 模块
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtDesigner', 'PySide6.QtHelp',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 打包为单文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CSAM_Repair',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # 不压缩 Qt DLL（可能导致加载失败）
        'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll',
        'Qt6OpenGL.dll', 'Qt6Network.dll', 'Qt6Svg.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # 发布版关闭控制台窗口（GUI 应用）
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)

# macOS 额外输出 .app bundle
if IS_MACOS:
    app = BUNDLE(
        exe,
        name='CSAM_Repair.app',
        icon=ICON_PATH,
        bundle_identifier='com.coldspray.repair',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
            'CFBundleName': 'CSAM Repair',
            'LSMinimumSystemVersion': '10.14',
            'NSMicrophoneUsageDescription': 'This app does not use the microphone.',
        },
    )
