"""export 模块 — 导出管线与内置导出器。

import 本包即自动注册全部内置导出器到 ExporterRegistry。
"""
from repair_app.export.pipeline import BaseExporter, ExporterRegistry, ExportResult, register

# 导入内置导出器以触发 @register 注册
from repair_app.export import builtin_exporters  # noqa: F401
