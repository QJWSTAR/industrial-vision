"""
platform.fonts — 跨平台 CJK 字体解析

为 matplotlib 和 reportlab 提供平台感知的中文字体解析:
  - macOS:   Songti SC, PingFang SC, Heiti SC
  - Windows: Microsoft YaHei, SimHei, SimSun
  - Linux:   Noto Sans CJK SC, WenQuanYi Micro Hei
"""

from __future__ import annotations

from repair_app.platform import is_windows, is_macos


def get_matplotlib_fonts() -> list[str]:
    """返回当前平台适用的 matplotlib 字体族列表（含 DejaVu Sans 回退）。"""
    if is_windows():
        return ["Microsoft YaHei", "SimHei", "SimSun", "DejaVu Sans"]
    if is_macos():
        return ["Songti SC", "PingFang SC", "Heiti SC", "DejaVu Sans"]
    # Linux / 其他
    return ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans"]


def get_cjk_font_paths() -> list[str]:
    """返回当前平台可用的 CJK TrueType 字体文件路径列表。

    用于 reportlab TTFont 注册。列表按优先级排序，
    调用方应遍历列表并注册第一个存在的字体。
    """
    if is_windows():
        return [
            "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
            "C:/Windows/Fonts/simhei.ttf",      # SimHei
            "C:/Windows/Fonts/simsun.ttc",      # SimSun
        ]
    if is_macos():
        return [
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]
    # Linux / 其他
    return [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
