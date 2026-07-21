"""
report_generator.py — 论文级 PDF 修复报告生成器
Stage 4.3 v2.1：reportlab 生成 / 中文字体 / 多图嵌入 / 表格自适应 / 页眉页脚
"""

from __future__ import annotations
import logging
import os
import io
import tempfile
from datetime import datetime
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from repair_app.platform.fonts import get_matplotlib_fonts
plt.rcParams["font.sans-serif"] = get_matplotlib_fonts()
plt.rcParams["axes.unicode_minus"] = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image as RLImage, PageBreak, KeepTogether,
    )
    from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


if _REPORTLAB_AVAILABLE:
    PAGE_W, PAGE_H = A4
    MARGIN = 20 * mm
    # 品牌色
    _COLOR_PRIMARY = HexColor("#1D4ED8")
    _COLOR_ACCENT = HexColor("#3B82F6")
    _COLOR_DARK = HexColor("#0F172A")
    _COLOR_MUTED = HexColor("#64748B")
    _COLOR_BORDER = HexColor("#E2E8F0")
else:
    # reportlab 不可用时使用 A4 点数等效值（1mm ≈ 2.83465 pt）
    PAGE_W, PAGE_H = (595.27, 841.89)
    MARGIN = 56.69  # 20mm
    _COLOR_PRIMARY = _COLOR_ACCENT = _COLOR_DARK = _COLOR_MUTED = _COLOR_BORDER = None


def _setup_fonts() -> None:
    """注册中文字体。"""
    if not _REPORTLAB_AVAILABLE:
        return
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception as e:
        logger.warning("STSong-Light font registration failed: %s", e)
    # 跨平台注册系统 CJK 字体
    from repair_app.platform.fonts import get_cjk_font_paths
    for fp in get_cjk_font_paths():
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("CJKFont", fp))
                break
            except Exception as e:
                logger.warning("CJK font registration failed (%s): %s", fp, e)
                continue


def _get_styles() -> dict:
    """获取报告样式表。"""
    styles = getSampleStyleSheet() if _REPORTLAB_AVAILABLE else {}
    font_name = "CJKFont" if _REPORTLAB_AVAILABLE else "Helvetica"

    custom = {
        "title": ParagraphStyle(
            "ReportTitle", fontSize=18, leading=24, spaceAfter=6,
            textColor=_COLOR_DARK, alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", fontSize=11, leading=16, spaceAfter=20,
            textColor=_COLOR_MUTED, alignment=TA_CENTER,
        ),
        "h2": ParagraphStyle(
            "H2", fontSize=14, leading=20, spaceBefore=16, spaceAfter=8,
            textColor=_COLOR_PRIMARY, fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "Body", fontSize=10, leading=16, spaceAfter=6,
            textColor=_COLOR_DARK,
        ),
        "small": ParagraphStyle(
            "Small", fontSize=8, leading=12, textColor=_COLOR_MUTED,
        ),
    }
    return custom


class RepairReport:
    """冷喷涂修复报告生成器。"""

    def __init__(self) -> None:
        self.title = "冷喷涂缺陷修复报告"
        self.subtitle = ""
        self.scan_info: dict = {}
        self.parameters: dict = {}
        self.results: dict = {}
        self.images: list[tuple[str, str]] = []  # (caption, path)
        self.layers: list[dict] = []
        self.statistics: dict = {}  # P2-4: 统计信息
        self.quality: dict = {}     # P2-4: 质量评估
        self.calibration: dict = {}
        self._tmp_files: list[str] = []

    def set_scan_info(self, scan_id: str = "", points: int = 0,
                       defect_volume_mm3: float = 0.0, defect_depth_mm: float = 0.0,
                       material: str = "") -> None:
        self.scan_info = {
            "scan_id": scan_id,
            "points": points,
            "defect_volume_mm3": defect_volume_mm3,
            "defect_depth_mm": defect_depth_mm,
            "material": material,
        }

    def set_parameters(self, params: dict) -> None:
        self.parameters = params

    def set_results(self, results: dict) -> None:
        self.results = results

    def set_layers(self, layers: list[dict]) -> None:
        """P2-4: 设置逐层沉积数据，激活逐层分析章节。

        Args:
            layers: 每层 dict，含 points/avg_height/mass_g 等字段
        """
        self.layers = list(layers) if layers else []

    def set_statistics(self, statistics: dict) -> None:
        """P2-4: 设置统计信息章节数据。

        Args:
            statistics: dict，含 mean/min/max/std 等统计字段
        """
        self.statistics = dict(statistics) if statistics else {}

    def set_quality(self, quality: dict) -> None:
        """P2-4: 设置质量评估章节数据。

        Args:
            quality: dict，含 uniformity_score/coverage_rate/overspray_ratio 等
        """
        self.quality = dict(quality) if quality else {}

    def add_comparison_figure(self, substrate_pts: np.ndarray,
                               defect_mask: np.ndarray,
                               repair_pts: np.ndarray) -> None:
        """生成修复前后对比图并嵌入报告。"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5),
                                        subplot_kw={"projection": "3d"})

        # 修复前
        if np.any(defect_mask):
            ax1.scatter(substrate_pts[~defect_mask, 0],
                       substrate_pts[~defect_mask, 1],
                       substrate_pts[~defect_mask, 2],
                       s=1, c="steelblue", alpha=0.3)
            ax1.scatter(substrate_pts[defect_mask, 0],
                       substrate_pts[defect_mask, 1],
                       substrate_pts[defect_mask, 2],
                       s=4, c="coral", alpha=0.8)
        ax1.set_title("修复前 - 缺陷区域", fontsize=10)
        ax1.view_init(elev=30, azim=-60)

        # 修复后
        ax2.scatter(substrate_pts[:, 0], substrate_pts[:, 1], substrate_pts[:, 2],
                    s=1, c="steelblue", alpha=0.2)
        if repair_pts is not None and len(repair_pts) > 0:
            ax2.scatter(repair_pts[:, 0], repair_pts[:, 1], repair_pts[:, 2],
                        s=3, c="forestgreen", alpha=0.8, label="修复填充")
        ax2.set_title("修复后 - 沉积填充", fontsize=10)
        ax2.view_init(elev=30, azim=-60)

        plt.tight_layout()
        path = self._save_figure(fig)
        self.images.append(("修复前后对比", path))

    def add_height_colormap(self, repair_pts: np.ndarray) -> None:
        """生成沉积体高度色温图。"""
        if len(repair_pts) == 0:
            return
        fig, ax = plt.subplots(figsize=(6, 5), subplot_kw={"projection": "3d"})
        z = repair_pts[:, 2]
        z_norm = (z - z.min()) / max(np.ptp(z), 1e-6)
        sc = ax.scatter(repair_pts[:, 0], repair_pts[:, 1], repair_pts[:, 2],
                        c=z_norm, cmap="coolwarm", s=3, alpha=0.8)
        plt.colorbar(sc, ax=ax, shrink=0.6, label="归一化高度")
        ax.set_title("沉积体高度色温图", fontsize=10)
        path = self._save_figure(fig)
        self.images.append(("沉积体高度色温图", path))

    def _save_figure(self, fig) -> str:
        """保存图为临时 PNG。"""
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmp.name, dpi=150, bbox_inches="tight", format="png")
        plt.close(fig)
        self._tmp_files.append(tmp.name)
        return tmp.name

    def generate(self, output_path: str) -> bool:
        """生成 PDF 报告。"""
        if not _REPORTLAB_AVAILABLE:
            logger.warning("reportlab not installed, cannot generate PDF report")
            logger.warning("Install: pip3 install reportlab")
            return False

        _setup_fonts()
        styles = _get_styles()
        story = []

        # 构建各章节
        self._build_cover(story, styles)
        self._build_scan_info(story, styles)
        self._build_params(story, styles)
        self._build_results(story, styles)
        self._build_statistics(story, styles)   # P2-4: 统计信息
        self._build_images(story, styles)
        self._build_layer_analysis(story, styles)
        self._build_quality(story, styles)       # P2-4: 质量评估
        self._build_calibration(story, styles)

        # 页脚
        story.append(Spacer(1, 10 * mm))
        story.append(Paragraph(
            "本报告由冷喷涂缺陷修复软件自动生成 · 仅供内部参考",
            styles["small"]
        ))

        # 构建 PDF
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN,
        )
        try:
            doc.build(story)
        finally:
            self._cleanup_tmp_files()

        return True

    def _build_cover(self, story: list, styles: dict) -> None:
        """构建封面页。"""
        story.append(Spacer(1, 40 * mm))
        story.append(Paragraph(self.title, styles["title"]))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        story.append(Paragraph(f"生成时间: {now_str}", styles["subtitle"]))
        if self.subtitle:
            story.append(Paragraph(self.subtitle, styles["subtitle"]))
        story.append(PageBreak())

    def _build_scan_info(self, story: list, styles: dict) -> None:
        """构建扫描信息章节。"""
        story.append(Paragraph("1. 扫描信息", styles["h2"]))
        si = self.scan_info
        scan_data = [
            ["扫描 ID", si.get("scan_id", "—")],
            ["点云数量", f"{si.get('points', 0):,} 点"],
            ["缺陷体积", f"{si.get('defect_volume_mm3', 0):.2f} mm³"],
            ["缺陷深度", f"{si.get('defect_depth_mm', 0):.2f} mm"],
            ["修复材料", si.get("material", "—")],
        ]
        story.extend(self._build_table(scan_data))
        story.append(Spacer(1, 6 * mm))

    def _build_params(self, story: list, styles: dict) -> None:
        """构建工艺参数章节。"""
        story.append(Paragraph("2. 工艺参数", styles["h2"]))
        if self.parameters:
            param_data = [[k, str(v)] for k, v in self.parameters.items()
                          if not k.startswith("_")]
            story.extend(self._build_table(param_data, col_widths=[80*mm, 80*mm]))
        else:
            story.append(Paragraph("（未提供）", styles["body"]))
        story.append(Spacer(1, 6 * mm))

    def _build_results(self, story: list, styles: dict) -> None:
        """构建结果摘要章节。"""
        story.append(Paragraph("3. 结果摘要", styles["h2"]))
        if self.results:
            res_data = [[k, str(v)] for k, v in self.results.items()]
            story.extend(self._build_table(res_data, col_widths=[80*mm, 80*mm]))
        else:
            story.append(Paragraph("（未提供）", styles["body"]))
        story.append(PageBreak())

    def _build_images(self, story: list, styles: dict) -> None:
        """构建修复前后可视化章节。"""
        story.append(Paragraph("5. 修复前后可视化", styles["h2"]))
        for caption, path in self.images:
            if os.path.exists(path):
                story.append(Paragraph(caption, styles["body"]))
                img = RLImage(path, width=160 * mm, height=80 * mm)
                story.append(img)
                story.append(Spacer(1, 4 * mm))

    def _build_statistics(self, story: list, styles: dict) -> None:
        """P2-4: 构建统计信息章节。"""
        if not self.statistics:
            return
        story.append(Paragraph("4. 统计信息", styles["h2"]))
        stat_data = [[k, str(v)] for k, v in self.statistics.items()]
        story.extend(self._build_table(stat_data, col_widths=[80*mm, 80*mm]))
        story.append(Spacer(1, 6 * mm))

    def _build_layer_analysis(self, story: list, styles: dict) -> None:
        """构建逐层沉积分析章节。"""
        if not self.layers:
            return
        story.append(PageBreak())
        story.append(Paragraph("6. 逐层沉积分析", styles["h2"]))
        layer_data = [["层号", "填充点数", "平均高度 (mm)", "材料用量 (g)"]]
        for i, layer in enumerate(self.layers):
            layer_data.append([
                str(i + 1),
                str(layer.get("points", 0)),
                f"{layer.get('avg_height', 0):.3f}",
                f"{layer.get('mass_g', 0):.2f}",
            ])
        t = Table(layer_data, colWidths=[30*mm, 40*mm, 50*mm, 50*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#F1F5F9")),
            ("GRID", (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(t)

    def _build_quality(self, story: list, styles: dict) -> None:
        """P2-4: 构建质量评估章节。"""
        if not self.quality:
            return
        story.append(PageBreak())
        story.append(Paragraph("7. 质量评估", styles["h2"]))
        qual_data = [[k, str(v)] for k, v in self.quality.items()]
        story.extend(self._build_table(qual_data, col_widths=[80*mm, 80*mm]))
        story.append(Spacer(1, 6 * mm))

    def _build_calibration(self, story: list, styles: dict) -> None:
        """构建标定信息章节。"""
        if not self.calibration:
            return
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("8. 标定信息", styles["h2"]))
        cal_data = [[k, str(v)] for k, v in self.calibration.items()]
        story.extend(self._build_table(cal_data))

    def _cleanup_tmp_files(self) -> None:
        """清理临时图片文件。"""
        for tmp in self._tmp_files:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        self._tmp_files.clear()

    def _build_table(self, data: list[list[str]],
                     col_widths: list = None) -> list:
        """构建格式化表格。"""
        if not data:
            return [Paragraph("（无数据）", _get_styles()["body"])]
        n_cols = len(data[0])
        if col_widths is None:
            col_widths = [80 * mm] * n_cols
        t = Table(data, colWidths=col_widths[:n_cols])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#F1F5F9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), _COLOR_DARK),
            ("GRID", (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return [t, Spacer(1, 2 * mm)]
