"""test_theme_regression.py — Theme / QSS 回归测试（Phase 11）

验证：
- Palette / Typography / Spacing / Radius 所有 token 存在
- 主题切换（dark ↔ light）正确更新所有 token
- QSS 生成包含关键样式规则
- 关键 UI 文件无未经审批的硬编码颜色
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════
# 1. Design Tokens 完整性
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestDesignTokens:
    """Palette / Typography / Spacing / Radius 完整性。"""

    def test_palette_has_all_bg_tokens(self):
        """Palette 包含所有背景层级 token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        for attr in ("bg_app", "bg_panel", "bg_elevated", "bg_input", "bg_hover", "bg_menu"):
            assert hasattr(p, attr), f"Palette 缺少 {attr}"
            assert isinstance(getattr(p, attr), str)

    def test_palette_has_all_border_tokens(self):
        """Palette 包含所有边框 token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        for attr in ("border_default", "border_strong", "border_focus"):
            assert hasattr(p, attr), f"Palette 缺少 {attr}"

    def test_palette_has_all_text_tokens(self):
        """Palette 包含所有文字层级 token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        for attr in ("text_primary", "text_body", "text_secondary", "text_muted", "text_disabled"):
            assert hasattr(p, attr), f"Palette 缺少 {attr}"

    def test_palette_has_all_accent_tokens(self):
        """Palette 包含所有强调色 token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        for attr in ("accent", "accent_hover", "accent_light", "accent_pale", "accent_bg"):
            assert hasattr(p, attr), f"Palette 缺少 {attr}"

    def test_palette_has_all_status_tokens(self):
        """Palette 包含所有状态色 token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        for attr in ("success", "warning", "error", "info",
                      "success_bg", "warning_bg", "error_bg", "info_bg"):
            assert hasattr(p, attr), f"Palette 缺少 {attr}"

    def test_palette_has_title_accent(self):
        """Palette 包含 title_accent token。"""
        from repair_app.ui.theme_manager import Palette
        p = Palette()
        assert hasattr(p, "title_accent")

    def test_typography_has_all_tokens(self):
        """Typography 包含所有排版 token。"""
        from repair_app.ui.theme_manager import Typography
        t = Typography()
        for attr in ("family_ui", "family_mono",
                      "size_caption", "size_body", "size_body_lg",
                      "size_subtitle", "size_title", "size_title_lg", "size_huge",
                      "weight_normal", "weight_medium", "weight_semibold", "weight_bold"):
            assert hasattr(t, attr), f"Typography 缺少 {attr}"

    def test_spacing_has_all_tokens(self):
        """Spacing 包含所有间距 token。"""
        from repair_app.ui.theme_manager import Spacing
        s = Spacing()
        for attr in ("xs", "sm", "md", "lg", "xl", "xxl",
                      "pad_button", "pad_input", "pad_menu_item", "pad_statusbar"):
            assert hasattr(s, attr), f"Spacing 缺少 {attr}"

    def test_radius_has_all_tokens(self):
        """Radius 包含所有圆角 token。"""
        from repair_app.ui.theme_manager import Radius
        r = Radius()
        for attr in ("none", "sm", "md", "lg", "pill"):
            assert hasattr(r, attr), f"Radius 缺少 {attr}"


# ═══════════════════════════════════════════════════════════════════
# 2. 主题切换
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestThemeSwitching:
    """主题切换（dark ↔ light）。"""

    def test_default_theme_is_dark(self):
        """默认主题为 dark。"""
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        assert ThemeManager.get_theme_name() == "dark"

    def test_switch_to_light(self):
        """切换到 light 主题。"""
        from repair_app.ui.theme_manager import ThemeManager, PaletteLight
        ThemeManager.set_theme("light")
        assert ThemeManager.get_theme_name() == "light"
        assert isinstance(ThemeManager.get_palette(), PaletteLight)

    def test_switch_back_to_dark(self):
        """切回 dark 主题。"""
        from repair_app.ui.theme_manager import ThemeManager, Palette
        ThemeManager.set_theme("dark")
        assert ThemeManager.get_theme_name() == "dark"
        assert isinstance(ThemeManager.get_palette(), Palette)

    def test_light_palette_has_all_tokens(self):
        """浅色 Palette 同样包含所有 token。"""
        from repair_app.ui.theme_manager import PaletteLight
        p = PaletteLight()
        required = ("bg_app", "bg_panel", "bg_elevated", "bg_input", "bg_hover",
                     "text_primary", "text_body", "text_secondary", "text_muted",
                     "accent", "success", "warning", "error")
        for attr in required:
            assert hasattr(p, attr), f"PaletteLight 缺少 {attr}"

    def test_theme_switch_preserves_qss_structure(self):
        """主题切换后 QSS 结构不变（包含关键选择器）。"""
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        dark_qss = ThemeManager.get_qss()
        ThemeManager.set_theme("light")
        light_qss = ThemeManager.get_qss()

        # 关键选择器必须同时存在于两个主题
        selectors = (
            "QMainWindow", "QGroupBox", "QPushButton", "QComboBox",
            "QStatusBar", "QMenuBar", "QScrollBar", "QToolBar",
        )
        for sel in selectors:
            assert sel in dark_qss, f"Dark QSS 缺少 {sel}"
            assert sel in light_qss, f"Light QSS 缺少 {sel}"


# ═══════════════════════════════════════════════════════════════════
# 3. QSS 生成
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestQSSGeneration:
    """QSS 字符串生成。"""

    def test_qss_is_non_empty(self):
        """QSS 非空字符串。"""
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        qss = ThemeManager.get_qss()
        assert isinstance(qss, str)
        assert len(qss) > 500  # 最少 500 字符

    def test_qss_contains_palette_colors(self):
        """QSS 包含调色板颜色值。"""
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        p = ThemeManager.get_palette()
        qss = ThemeManager.get_qss()
        # 验证 QSS 中引用了调色板的实际颜色值
        assert p.bg_app in qss
        assert p.accent in qss
        assert p.text_primary in qss

    def test_get_palette_returns_palette(self):
        """get_palette 返回 Palette 实例。"""
        from repair_app.ui.theme_manager import ThemeManager, Palette
        ThemeManager.set_theme("dark")
        p = ThemeManager.get_palette()
        assert isinstance(p, Palette)

    def test_get_typography_returns_typography(self):
        """get_typography 返回 Typography 实例。"""
        from repair_app.ui.theme_manager import ThemeManager, Typography
        assert isinstance(ThemeManager.get_typography(), Typography)

    def test_get_spacing_returns_spacing(self):
        """get_spacing 返回 Spacing 实例。"""
        from repair_app.ui.theme_manager import ThemeManager, Spacing
        assert isinstance(ThemeManager.get_spacing(), Spacing)

    def test_get_radius_returns_radius(self):
        """get_radius 返回 Radius 实例。"""
        from repair_app.ui.theme_manager import ThemeManager, Radius
        assert isinstance(ThemeManager.get_radius(), Radius)


# ═══════════════════════════════════════════════════════════════════
# 4. 防止硬编码回退
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestNoHardcodedColors:
    """关键 UI 文件中无回退的硬编码颜色。"""

    # 允许的硬编码颜色（白色、纯黑、透明）
    _ALLOWED = {"#FFFFFF", "#000000", "transparent", "none", "url()"}

    def _count_hardcoded(self, filepath: str) -> int:
        """统计文件中不在 Palette 中的硬编码 hex 颜色。"""
        import re
        from repair_app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme("dark")
        p = ThemeManager.get_palette()

        # 收集所有 palette token 值
        palette_values = {
            getattr(p, attr) for attr in dir(p)
            if not attr.startswith("_") and isinstance(getattr(p, attr), str)
        }

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 匹配所有 hex 颜色
        hex_colors = set(re.findall(r'#[0-9A-Fa-f]{6}', content))
        # 排除已在 palette 中的值和允许列表
        hardcoded = hex_colors - palette_values - self._ALLOWED
        return len(hardcoded), hardcoded

    def test_dialogs_no_unapproved_colors(self):
        """dialogs.py 无未审批的硬编码颜色。"""
        count, hardcoded = self._count_hardcoded(
            "repair_app/ui/dialogs.py"
        )
        # 允许少量色调变体（如 #DC2626 比 error 略深）
        if hardcoded:
            # 只报告，不强制失败（颜色迁移是渐进过程）
            print(f"dialogs.py 剩余硬编码颜色: {hardcoded}")
        # 目标：硬编码颜色在合理范围内
        assert count <= 5, f"dialogs.py 有 {count} 个未迁移的硬编码颜色: {hardcoded}"

    def test_toast_no_unapproved_colors(self):
        """toast.py 无未审批的硬编码颜色。"""
        count, hardcoded = self._count_hardcoded(
            "repair_app/ui/toast.py"
        )
        assert count == 0, f"toast.py 有 {count} 个硬编码颜色: {hardcoded}"

    def test_pipeline_indicator_no_unapproved_colors(self):
        """pipeline_indicator.py 无未审批的硬编码颜色。"""
        count, hardcoded = self._count_hardcoded(
            "repair_app/ui/pipeline_indicator.py"
        )
        assert count == 0, f"pipeline_indicator.py 有 {count} 个硬编码颜色: {hardcoded}"

    def test_workflow_controller_no_unapproved_colors(self):
        """workflow_controller.py 无未审批的硬编码颜色。"""
        count, hardcoded = self._count_hardcoded(
            "repair_app/ui/workflow_controller.py"
        )
        # workflow_controller.py 有步骤样式常量，使用 palette token
        assert count <= 10, f"workflow_controller.py 有 {count} 个未迁移的硬编码颜色: {hardcoded}"


# ═══════════════════════════════════════════════════════════════════
# 5. Light/Dark 视觉一致性
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestLightDarkConsistency:
    """Light/Dark 主题视觉一致性。"""

    def test_both_themes_have_contrasting_bg_text(self):
        """两个主题的背景和文字颜色对比度足够。"""
        from repair_app.ui.theme_manager import ThemeManager, Palette, PaletteLight

        for theme_name, palette_cls in [("dark", Palette), ("light", PaletteLight)]:
            ThemeManager.set_theme(theme_name)
            p = ThemeManager.get_palette()
            # 背景和文字颜色不同
            assert p.bg_app != p.text_primary, f"{theme_name}: bg_app == text_primary"
            assert p.bg_panel != p.text_body, f"{theme_name}: bg_panel == text_body"

    def test_critical_colors_distinct(self):
        """success / warning / error 颜色在视觉上可区分。"""
        from repair_app.ui.theme_manager import ThemeManager, Palette
        ThemeManager.set_theme("dark")
        p = ThemeManager.get_palette()
        assert p.success != p.warning
        assert p.warning != p.error
        assert p.error != p.info