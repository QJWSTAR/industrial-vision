"""
pyi_runtime_hook.py — PyInstaller 运行时钩子

在应用主代码执行前运行，负责：
1. 设置 SSL 证书路径（cryptography 库需要）
2. 设置 Qt 平台插件路径
3. 设置 MATPLOTLIB 配置目录（避免临时目录写入权限问题）
4. 设置 ZMQ 相关环境变量
5. 修复 Chinese font 缓存路径
"""

import sys
import os
from pathlib import Path


def _setup_ssl():
    """确保 cryptography 库能找到 SSL 证书。"""
    if hasattr(sys, '_MEIPASS'):
        cacert = Path(sys._MEIPASS) / 'cacert.pem'
        if cacert.exists():
            os.environ.setdefault('SSL_CERT_FILE', str(cacert))


def _setup_qt():
    """设置 Qt 平台插件路径。"""
    if hasattr(sys, '_MEIPASS'):
        # Windows: 使用 windows 平台插件
        # macOS: 使用 cocoa 平台插件
        # Linux: 使用 xcb 平台插件
        plugin_dir = Path(sys._MEIPASS) / 'PySide6' / 'plugins'
        if plugin_dir.exists():
            os.environ.setdefault('QT_PLUGIN_PATH', str(plugin_dir))

        # 禁用 Qt 自动屏幕缩放（避免高 DPI 下的界面模糊）
        os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

        # Windows 专用: 强制使用 ANGLE 或 software 渲染（避免 GPU 驱动崩溃）
        if sys.platform == 'win32':
            os.environ.setdefault('QT_OPENGL', 'angle')


def _setup_matplotlib():
    """设置 matplotlib 配置目录，避免打包后缓存写入失败。"""
    if hasattr(sys, '_MEIPASS'):
        # 使用用户目录而非临时目录
        import tempfile
        cache_dir = Path(tempfile.gettempdir()) / 'csam_mpl_cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault('MPLCONFIGDIR', str(cache_dir))


def _setup_zmq():
    """设置 ZMQ 相关环境变量。"""
    # 确保使用 bundled 的 libzmq
    if hasattr(sys, '_MEIPASS'):
        os.environ.setdefault('ZMQ_PREFIX', sys._MEIPASS)


def _setup_fonts():
    """设置字体缓存目录。"""
    if hasattr(sys, '_MEIPASS'):
        import tempfile
        font_cache = Path(tempfile.gettempdir()) / 'csam_font_cache'
        font_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault('FONTCONFIG_PATH', str(font_cache))


# 执行所有初始化
_setup_ssl()
_setup_qt()
_setup_matplotlib()
_setup_zmq()
_setup_fonts()
