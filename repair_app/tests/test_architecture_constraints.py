"""test_architecture_constraints.py — 架构约束测试

Phase 1: 验证 ComputePipelineWorker 不再直接操作 ZMQ。
后续 Phase 会逐步添加更多约束。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest


# ---- 辅助函数 ----

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _production_files() -> list[Path]:
    """返回所有生产代码 .py 文件（排除 tests/）。"""
    root = _project_root()
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "tests", "docs")]
        for f in filenames:
            if f.endswith(".py"):
                py_files.append(Path(dirpath) / f)
    return py_files


def _parse_imports(filepath: Path) -> list[tuple[str, int]]:
    """解析文件中的所有 import 语句，返回 (module_path, line_number) 列表。"""
    imports = []
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                imports.append((full, node.lineno))
    return imports


def _parse_zmq_context_usages(filepath: Path) -> list[int]:
    """检测文件中是否有 zmq.Context() 或 zmq.Context.instance() 调用。"""
    lines = []
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return lines
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                # zmq.Context() or zmq.Context.instance()
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "zmq":
                    if node.func.attr in ("Context",):
                        lines.append(node.lineno)
    return lines


# ---- 测试 ----

class TestArchitecturePhase1:
    """Phase 1 架构约束：ComputePipelineWorker 不直接操作 ZMQ。"""

    def test_worker_no_zmq_import(self):
        """ComputePipelineWorker 不得 import zmq。"""
        worker_file = _project_root() / "ui" / "workers.py"
        imports = _parse_imports(worker_file)
        zmq_imports = [(mod, line) for mod, line in imports if "zmq" in mod.lower()]
        assert len(zmq_imports) == 0, (
            f"workers.py 不得 import zmq，但发现: {zmq_imports}"
        )

    def test_worker_no_zmq_context(self):
        """ComputePipelineWorker 不得创建 zmq.Context。"""
        worker_file = _project_root() / "ui" / "workers.py"
        usages = _parse_zmq_context_usages(worker_file)
        assert len(usages) == 0, (
            f"workers.py 不得创建 zmq.Context，但发现行: {usages}"
        )

    def test_worker_no_launcher_import(self):
        """ComputePipelineWorker 不得 import MatlabBridgeLauncher。"""
        worker_file = _project_root() / "ui" / "workers.py"
        imports = _parse_imports(worker_file)
        launcher_imports = [
            (mod, line) for mod, line in imports
            if "MatlabBridgeLauncher" in mod or "launcher" in mod.lower()
        ]
        assert len(launcher_imports) == 0, (
            f"workers.py 不得 import launcher 相关模块，但发现: {launcher_imports}"
        )

    def test_bridge_client_has_blocking_method(self):
        """BridgeClient 必须有 request_blocking 方法。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient
        assert hasattr(BridgeClient, "request_blocking"), (
            "BridgeClient 必须有 request_blocking 方法"
        )
        assert callable(BridgeClient.request_blocking), (
            "BridgeClient.request_blocking 必须可调用"
        )

    def test_matlab_service_has_blocking_method(self):
        """MatlabService 必须有 run_full_pipeline_blocking 方法。"""
        from repair_app.bridge.services.matlab_service import MatlabService
        assert hasattr(MatlabService, "run_full_pipeline_blocking"), (
            "MatlabService 必须有 run_full_pipeline_blocking 方法"
        )
        assert callable(MatlabService.run_full_pipeline_blocking), (
            "MatlabService.run_full_pipeline_blocking 必须可调用"
        )

    def test_compute_pipeline_worker_accepts_matlab_service(self):
        """ComputePipelineWorker 构造接受 matlab_service 参数。"""
        from repair_app.ui.workers import ComputePipelineWorker
        import inspect
        sig = inspect.signature(ComputePipelineWorker.__init__)
        params = list(sig.parameters.keys())
        assert "matlab_service" in params, (
            f"ComputePipelineWorker.__init__ 必须有 matlab_service 参数，当前: {params}"
        )
        assert "project_root" not in params, (
            f"ComputePipelineWorker.__init__ 不得有 project_root 参数，当前: {params}"
        )

    def test_zmq_context_only_in_bridge_layer(self):
        """生产代码中 zmq.Context() 只能存在于 bridge/ 层或旧版 communication/ 层。"""
        # Phase 1 已知违规（将在后续 Phase 修复）：
        #   - ui/progress_subscriber.py: Phase 7 重构
        KNOWN_VIOLATIONS = {
            ("ui", "progress_subscriber.py"): "Phase 7 重构 Progress 系统",
        }
        violations = []
        for filepath in _production_files():
            rel = str(filepath.relative_to(_project_root()))
            # 允许 bridge/ 层（含 bridge/communication, bridge/progress_publisher 等）
            if "bridge" in rel.split(os.sep)[0] if os.sep in rel else rel.startswith("bridge"):
                continue
            # 允许旧版 communication/ 层（已标记 deprecated）
            if rel.startswith("communication") and "bridge" not in rel:
                continue
            usages = _parse_zmq_context_usages(filepath)
            if usages:
                # 检查是否已知违规
                parts = Path(rel).parts
                key = (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0], "")
                if key in KNOWN_VIOLATIONS:
                    continue
                violations.append((rel, usages))
        if violations:
            msg = "以下文件在非 bridge/ 层创建 zmq.Context:\n"
            for rel, lines in violations:
                msg += f"  {rel} lines {lines}\n"
            pytest.fail(msg)


# ============================================================
# Phase 17 辅助函数
# ============================================================

def _ui_files() -> list[Path]:
    """返回 ui/ 目录下所有 .py 文件。"""
    root = _project_root()
    ui_dir = root / "ui"
    py_files = []
    if ui_dir.is_dir():
        for dirpath, dirnames, filenames in os.walk(ui_dir):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
            for f in filenames:
                if f.endswith(".py"):
                    py_files.append(Path(dirpath) / f)
    return py_files


def _has_import(filepath: Path, target: str) -> list[tuple[str, int]]:
    """检查文件是否 import 了指定模块名（含子模块匹配）。"""
    imports = _parse_imports(filepath)
    return [(mod, line) for mod, line in imports if target in mod]


def _has_import_prefix(filepath: Path, prefix: str) -> list[tuple[str, int]]:
    """检查文件是否 import 了以 prefix 开头的模块。"""
    imports = _parse_imports(filepath)
    return [(mod, line) for mod, line in imports if mod.startswith(prefix)]


def _parse_zmq_socket_creation(filepath: Path) -> list[int]:
    """检测文件中是否有 zmq socket 创建：zmq.Context / zmq.REQ / zmq.PUB / zmq.SUB / .socket(zmq.XXX)"""
    lines = []
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return lines
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                # zmq.Context() / zmq.Context.instance()
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "zmq":
                    if node.func.attr in ("Context", "REQ", "PUB", "SUB", "DEALER", "ROUTER", "PUSH", "PULL",
                                          "PAIR", "XPUB", "XSUB"):
                        lines.append(node.lineno)
                # ctx.socket(zmq.REQ) 等
                if node.func.attr == "socket":
                    for arg in node.args:
                        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "zmq":
                            lines.append(node.lineno)
    return lines


def _parse_hex_colors(filepath: Path) -> list[tuple[int, str]]:
    """检测文件中硬编码的 hex 颜色（#XXXXXX），排除 #FFFFFF、#000000 和模板变量引用。

    返回 [(line_number, hex_color), ...]
    """
    import re
    results = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return results
    # 匹配 #XXXXXX 格式，排除 f-string 模板变量（如 {p.accent}）
    pattern = re.compile(r'(?<![{.\w])#[0-9a-fA-F]{6}(?![}\w])')
    for i, line in enumerate(content.splitlines(), 1):
        for m in pattern.finditer(line):
            hex_val = m.group().upper()
            if hex_val not in ("#FFFFFF", "#000000"):
                results.append((i, hex_val))
    return results


def _parse_terminate_calls(filepath: Path) -> list[int]:
    """检测文件中的 .terminate() 调用行号。"""
    lines = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return lines
    for i, line in enumerate(content.splitlines(), 1):
        if ".terminate()" in line and not line.strip().startswith("#"):
            # 排除 subprocess.Popen.terminate() — 只匹配 QThread.terminate()
            # 但简单起见，先收集所有，后续按文件名过滤
            lines.append(i)
    return lines


# ============================================================
# Phase 17 架构约束测试
# ============================================================

@pytest.mark.unit
class TestArchitecturePhase17:
    """Phase 17 架构约束：全面验证 CSAM 分层架构规则。"""

    # ── Rule 1: UI 层禁止直接 import zmq / MatlabBridgeLauncher ──

    def test_rule1_ui_no_zmq_import(self):
        """Rule 1: UI 层任何文件不得 import zmq。"""
        KNOWN_VIOLATIONS = {
            # progress_subscriber.py: 在 QThread 中订阅 ZMQ PUB，已知违规（Phase 7 重构）
            "progress_subscriber.py": "Phase 7 重构 Progress 系统",
        }
        violations = []
        for filepath in _ui_files():
            fname = filepath.name
            zmq_imports = _has_import(filepath, "zmq")
            if zmq_imports:
                if fname in KNOWN_VIOLATIONS:
                    continue
                violations.append((fname, zmq_imports))
        if violations:
            msg = "Rule 1 违规: UI 层文件不得 import zmq:\n"
            for fname, imps in violations:
                msg += f"  {fname}: {imps}\n"
            pytest.fail(msg)

    def test_rule1_ui_no_matlab_bridge_launcher_import(self):
        """Rule 1: UI 层任何文件不得 import MatlabBridgeLauncher。"""
        violations = []
        for filepath in _ui_files():
            fname = filepath.name
            launcher_imports = _has_import(filepath, "MatlabBridgeLauncher")
            if launcher_imports:
                violations.append((fname, launcher_imports))
        if violations:
            msg = "Rule 1 违规: UI 层文件不得 import MatlabBridgeLauncher:\n"
            for fname, imps in violations:
                msg += f"  {fname}: {imps}\n"
            pytest.fail(msg)

    def test_rule1_main_window_no_zmq(self):
        """Rule 1: main_window.py 不得直接 import zmq 或 MatlabBridgeLauncher。"""
        mw = _project_root() / "ui" / "main_window.py"
        zmq_imports = _has_import(mw, "zmq")
        launcher_imports = _has_import(mw, "MatlabBridgeLauncher")
        assert len(zmq_imports) == 0, (
            f"main_window.py 不得 import zmq，但发现: {zmq_imports}"
        )
        assert len(launcher_imports) == 0, (
            f"main_window.py 不得 import MatlabBridgeLauncher，但发现: {launcher_imports}"
        )

    # ── Rule 2: MainWindow 禁止直接 import repair_app.bridge.communication.* ──

    def test_rule2_main_window_no_communication_import(self):
        """Rule 2: main_window.py 不得 import repair_app.bridge.communication.*"""
        mw = _project_root() / "ui" / "main_window.py"
        comm_imports = _has_import_prefix(mw, "repair_app.bridge.communication")
        assert len(comm_imports) == 0, (
            f"main_window.py 不得 import repair_app.bridge.communication.*，但发现: {comm_imports}"
        )

    def test_rule2_main_window_may_import_bridge(self):
        """Rule 2: main_window.py 可以 import repair_app.bridge（非 communication 子包）。"""
        # 此为正向测试：验证 main_window 可以通过 bridge 顶层访问服务
        # 不强制要求存在，仅验证若存在 bridge import 则不在 communication 子包
        mw = _project_root() / "ui" / "main_window.py"
        all_imports = _parse_imports(mw)
        bridge_imports = [(m, l) for m, l in all_imports if m.startswith("repair_app.bridge")]
        for mod, line in bridge_imports:
            assert not mod.startswith("repair_app.bridge.communication"), (
                f"main_window.py 行 {line}: 不得 import {mod}（communication 子包禁止）"
            )

    # ── Rule 3: 生产代码只有 Infrastructure 层允许创建 zmq socket ──

    def test_rule3_zmq_socket_only_in_bridge(self):
        """Rule 3: zmq socket 创建仅允许 bridge/ 和 infrastructure/ 层。"""
        KNOWN_VIOLATIONS = {
            # progress_subscriber.py: 在 QThread 中创建 zmq SUB socket（Phase 7 重构）
            ("ui", "progress_subscriber.py"): "Phase 7 重构 Progress 系统",
            # repair_engine_service.py: 服务端引擎原型，serve() 创建 zmq.REP server
            # 本质上是 infrastructure 层代码，但位于 service/ 包中
            ("service", "repair_engine_service.py"): "服务端引擎原型（infrastructure 级别）",
        }
        # 旧版 communication/ 层（deprecated）
        ALLOWED_DIRS = {"bridge", "communication", "infrastructure"}

        violations = []
        for filepath in _production_files():
            rel = str(filepath.relative_to(_project_root()))
            top_dir = rel.split(os.sep)[0] if os.sep in rel else ""

            if top_dir in ALLOWED_DIRS:
                continue

            usages = _parse_zmq_socket_creation(filepath)
            if usages:
                parts = Path(rel).parts
                key = (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0], "")
                if key in KNOWN_VIOLATIONS:
                    continue
                violations.append((rel, usages))

        if violations:
            msg = "Rule 3 违规: 以下文件在非 bridge/communication/infrastructure 层创建 zmq socket:\n"
            for rel, lines in violations:
                msg += f"  {rel} lines {lines}\n"
            pytest.fail(msg)

    def test_rule3_core_no_zmq_socket(self):
        """Rule 3: core/ 层不得创建 zmq socket。"""
        core_dir = _project_root() / "core"
        if not core_dir.is_dir():
            return
        violations = []
        for filepath in core_dir.rglob("*.py"):
            usages = _parse_zmq_socket_creation(filepath)
            if usages:
                violations.append((str(filepath.relative_to(_project_root())), usages))
        assert len(violations) == 0, (
            f"Rule 3 违规: core/ 层不得创建 zmq socket: {violations}"
        )

    def test_rule3_services_no_zmq_socket(self):
        """Rule 3: service/ 层不得创建 zmq socket。"""
        KNOWN_VIOLATIONS = {
            # repair_engine_service.py: 服务端引擎原型，serve() 创建 zmq.REP
            "repair_engine_service.py": "服务端引擎原型（infrastructure 级别）",
        }
        svc_dir = _project_root() / "service"
        if not svc_dir.is_dir():
            return
        violations = []
        for filepath in svc_dir.rglob("*.py"):
            usages = _parse_zmq_socket_creation(filepath)
            if usages:
                if filepath.name in KNOWN_VIOLATIONS:
                    continue
                violations.append((str(filepath.relative_to(_project_root())), usages))
        assert len(violations) == 0, (
            f"Rule 3 违规: service/ 层不得创建 zmq socket: {violations}"
        )

    # ── Rule 4: ComputePipelineWorker 禁止 import zmq / MatlabBridgeLauncher ──

    def test_rule4_workers_no_zmq(self):
        """Rule 4: workers.py 不得 import zmq。"""
        worker_file = _project_root() / "ui" / "workers.py"
        zmq_imports = _has_import(worker_file, "zmq")
        assert len(zmq_imports) == 0, (
            f"Rule 4 违规: workers.py 不得 import zmq，但发现: {zmq_imports}"
        )

    def test_rule4_workers_no_launcher(self):
        """Rule 4: workers.py 不得 import MatlabBridgeLauncher。"""
        worker_file = _project_root() / "ui" / "workers.py"
        launcher_imports = _has_import(worker_file, "MatlabBridgeLauncher")
        assert len(launcher_imports) == 0, (
            f"Rule 4 违规: workers.py 不得 import MatlabBridgeLauncher，但发现: {launcher_imports}"
        )

    # ── Rule 5: repair_app.communication.zmq_client 不得存在 ──

    def test_rule5_old_zmq_client_not_imported_by_production(self):
        """Rule 5: repair_app.communication.zmq_client 不得被生产代码 import。"""
        old_client = _project_root() / "communication" / "zmq_client.py"
        # 允许旧文件存在（deprecated），但不允许生产代码导入
        KNOWN_VIOLATIONS = {
            # coordination_service.py 有旧版回退导入（已标记 noqa）
            ("service", "coordination_service.py"): "旧版回退兼容（已标记 deprecated）",
        }
        violations = []
        for filepath in _production_files():
            rel = str(filepath.relative_to(_project_root()))
            # 跳过 communication/ 自身
            if rel.startswith("communication"):
                continue
            # 跳过 bridge/ 层（允许内部引用）
            if rel.startswith("bridge"):
                continue
            imports = _parse_imports(filepath)
            for mod, line in imports:
                if "repair_app.communication.zmq_client" in mod:
                    parts = Path(rel).parts
                    key = (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0], "")
                    if key in KNOWN_VIOLATIONS:
                        continue
                    violations.append((rel, line, mod))

        if violations:
            msg = "Rule 5 违规: 生产代码不得 import repair_app.communication.zmq_client:\n"
            for rel, line, mod in violations:
                msg += f"  {rel}:{line} -> {mod}\n"
            pytest.fail(msg)

    # ── Rule 6: 硬编码 UI Hex Color 限制在 Theme 定义文件 ──

    def test_rule6_hex_colors_restricted_to_theme_files(self):
        """Rule 6: 硬编码 hex 颜色仅允许 theme_manager.py 和 panel_builder.py。

        其他 UI 文件只允许 #FFFFFF、#000000。
        """
        ALLOWED_FILES = {"theme_manager.py", "panel_builder.py"}
        # 已知例外：这些文件使用了 matplotlib 可视化颜色（非 Qt 样式），暂豁免
        KNOWN_VIOLATIONS = {
            # profile_result_panel.py: matplotlib 图表颜色定义
            "profile_result_panel.py": "matplotlib 可视化颜色（Phase 后续重构）",
            # repair_visualizer.py: matplotlib 3D 可视化颜色
            "repair_visualizer.py": "matplotlib 3D 可视化颜色（Phase 后续重构）",
            # realtime_stats.py: 内联样式表颜色
            "realtime_stats.py": "实时统计面板样式（Phase 后续重构）",
            # workflow_controller.py: 工作流步骤按钮样式（Phase 后续重构）
            "workflow_controller.py": "工作流步骤按钮样式（Phase 后续重构）",
        }

        violations = []
        for filepath in _ui_files():
            fname = filepath.name
            if fname in ALLOWED_FILES:
                continue
            if fname in KNOWN_VIOLATIONS:
                continue
            hex_colors = _parse_hex_colors(filepath)
            if hex_colors:
                violations.append((fname, hex_colors))

        if violations:
            msg = "Rule 6 违规: 以下 UI 文件包含非标准硬编码 hex 颜色（仅 #FFFFFF/#000000 允许）:\n"
            for fname, colors in violations:
                unique = sorted(set(c for _, c in colors))
                lines = sorted(set(l for l, _ in colors))
                msg += f"  {fname} lines {lines}: {unique}\n"
            msg += "\n允许文件: theme_manager.py, panel_builder.py\n"
            msg += "其他文件请使用 ThemeManager.get_palette() 或仅使用 #FFFFFF/#000000。\n"
            pytest.fail(msg)

    def test_rule6_dialogs_uses_theme_colors(self):
        """Rule 6: dialogs.py 使用 ThemeManager 颜色而非硬编码 hex（验证豁免合理性）。"""
        dialog_file = _project_root() / "ui" / "dialogs.py"
        hex_colors = _parse_hex_colors(dialog_file)
        # dialogs.py 中的 #FFFFFF 是允许的（白色文字），检查是否有其他非白非黑 hex
        non_white_black = [(l, c) for l, c in hex_colors if c not in ("#FFFFFF", "#000000")]
        # dialogs.py 使用 f-string 模板 {p.accent} 等，所以 _parse_hex_colors 不应匹配到
        assert len(non_white_black) == 0, (
            f"Rule 6 违规: dialogs.py 包含非标准硬编码 hex 颜色: {non_white_black}"
        )

    # ── Rule 7: 禁止新增未经审核的 QThread.terminate() ──

    def test_rule7_terminate_only_in_shutdown_controller(self):
        """Rule 7: .terminate() 仅允许在 application_shutdown_controller.py。

        bridge 层和 worker_base 中的 terminate() 均为 QThread 优雅退出 fallback，
        作为已知例外允许。
        """
        ALLOWED_FILES = {
            "application_shutdown_controller.py",  # 关闭控制器
            "worker_base.py",                       # WorkerManager.cancel() fallback
            "launcher.py",                          # bridge/launcher: subprocess.terminate()（非 QThread）
        }
        # bridge 通信层 allowlist（QThread fallback 模式）
        ALLOWED_BRIDGE_PATTERNS = {
            "zmq_client.py",    # BridgeClient.close() fallback
            "heartbeat.py",     # HeartbeatThread.stop() fallback
        }

        violations = []
        for filepath in _production_files():
            fname = filepath.name
            rel = str(filepath.relative_to(_project_root()))

            # 跳过旧版 communication/（deprecated）
            if rel.startswith("communication") and "bridge" not in rel:
                continue

            if fname in ALLOWED_FILES:
                continue

            # bridge/ 层允许特定文件的 terminate() fallback
            if "bridge" in rel.split(os.sep):
                if fname in ALLOWED_BRIDGE_PATTERNS:
                    continue

            terminate_lines = _parse_terminate_calls(filepath)
            if terminate_lines:
                # 排除 subprocess.terminate() — 检查是否在 QThread 上下文中
                # 简单启发：桥接层文件中的 terminate 视为 QThread 操作
                violations.append((rel, terminate_lines))

        if violations:
            msg = "Rule 7 违规: 以下文件包含未经审核的 .terminate() 调用:\n"
            for rel, lines in violations:
                msg += f"  {rel} lines {lines}\n"
            msg += "\n仅允许: application_shutdown_controller.py, worker_base.py, launcher.py(subprocess)\n"
            msg += "以及 bridge/communication/zmq_client.py, bridge/communication/heartbeat.py\n"
            pytest.fail(msg)