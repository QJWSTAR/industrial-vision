"""error_manager.py — 全局唯一异常处理编排中心

目标：用户永远不看到 Python Traceback。

三大组件：
  1. ErrorCode     — 错误分类枚举（License/MATLAB/File/Mesh/Network/Export/Unknown）
  2. LogManager    — 日志管理器（封装 logger_config，提供错误专用通道）
  3. ErrorManager  — 异常处理编排中心（统一 try → log → friendly → detail → recover → continue）

异常处理流程：
    try
      ↓
    log（LogManager 记录完整 traceback 到 error.log）
      ↓
    friendly message（ErrorManager.classify 生成 What/Why/How）
      ↓
    detail（保留 exc 供技术员展开）
      ↓
    recover（RecoveryStrategy 指明回退动作）
      ↓
    continue（用户确认后继续 / 重试 / 退出）

使用方式：
    from repair_app.utils.error_manager import ErrorManager, ErrorCode

    # 方式 1：手动分类
    try:
        risky_operation()
    except Exception as exc:
        ErrorManager.handle(exc, ErrorCode.MATLAB, context="路径规划", parent=self)

    # 方式 2：装饰器
    @ErrorManager.guard(ErrorCode.FILE, context="导出 G-code")
    def export_gcode():
        ...

    # 方式 3：上下文管理器
    with ErrorManager.context(ErrorCode.NETWORK, context="ZMQ 请求"):
        reply = sock.recv()
"""
from __future__ import annotations

import sys
import os
import traceback
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Optional, Callable, Any, Iterator

from repair_app.utils.logger_config import (
    error as _log_error,
    warning as _log_warning,
    info as _log_info,
    exception as _log_exception,
    get_logger,
)
from repair_app.utils.path_sanitizer import PathSanitizer


# 项目根目录（用于路径脱敏）
_PROJECT_ROOT = os.path.normpath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


# ============================================================
# 1. ErrorCode — 错误分类枚举
# ============================================================
class ErrorCode(Enum):
    """7 类错误码（覆盖项目全部异常场景）。

    每类错误对应：
    - 默认 What/Why/How 模板
    - 默认恢复策略
    - 是否致命（是否需要重启软件）
    """

    LICENSE = "license"      # License 授权无效 / 过期 / 缺失
    MATLAB = "matlab"        # MATLAB 引擎崩溃 / 算法异常 / 启动失败
    FILE = "file"            # 文件读写 / 路径 / 权限 / 磁盘空间
    MESH = "mesh"            # STL 读取 / 点云形状 / 三角化失败
    NETWORK = "network"      # ZMQ 连接 / 超时 / 协议 / 序列化
    EXPORT = "export"        # G-code / 机器人轨迹 / PDF 报告导出
    UNKNOWN = "unknown"      # 兜底：未分类异常


# ============================================================
# 2. FriendlyMessage — 友好消息数据类
# ============================================================
@dataclass
class FriendlyMessage:
    """用户三段式消息（What/Why/How）。

    用户只看到这三段；技术日志单独展开，不直接展示给用户。
    """
    title: str = "操作失败"
    what: str = ""           # 发生了什么（一句话）
    why: str = ""            # 为什么发生（可能原因）
    how: str = ""            # 如何解决（具体步骤）


# ============================================================
# 3. RecoveryStrategy — 恢复策略
# ============================================================
@dataclass
class RecoveryStrategy:
    """恢复策略：异常发生后系统应如何继续。

    action 取值：
    - "continue"  : 用户确认后继续使用（默认）
    - "retry"     : 提示用户重试当前操作
    - "fallback"  : 自动回退到降级模式（如本地模拟航点）
    - "restart"   : 建议重启软件
    - "fatal"     : 致命错误，软件无法继续（License 无效等）
    """
    action: str = "continue"
    fallback_hint: str = ""   # 回退模式的提示文字


# ============================================================
# 4. LogManager — 日志管理器
# ============================================================
class LogManager:
    """日志管理器（封装 logger_config）。

    职责：
    - 统一记录 ERROR 级别日志（带完整 traceback）
    - 提供错误专用通道（带 ErrorCode 标签）
    - 维护"最近错误"缓存（供 ErrorDialog 展示）
    - 线程安全

    不重新实现日志后端，仅做语义封装。
    """

    _lock = threading.Lock()
    _last_error: Optional[dict] = None  # {code, message, traceback, context, timestamp}

    @classmethod
    def log_error(
        cls,
        exc: BaseException,
        code: ErrorCode = ErrorCode.UNKNOWN,
        context: str = "",
    ) -> str:
        """记录错误日志，返回 traceback 文本。

        Args:
            exc: 异常对象
            code: 错误分类
            context: 操作上下文（如"路径规划"）
        Returns:
            traceback 文本（供 ErrorDialog 技术日志区展示）
        """
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # 路径脱敏：替换敏感路径为占位符
        tb_text = PathSanitizer.sanitize(tb_text, project_root=_PROJECT_ROOT)
        tag = f"[{code.value.upper()}]"
        ctx = f" | context={context}" if context else ""
        # 同时记录简短错误消息和完整 traceback
        _log_error(f"{tag} {exc}{ctx}\n{tb_text}")

        # 缓存最近错误（线程安全）
        with cls._lock:
            cls._last_error = {
                "code": code.value,
                "message": str(exc),
                "traceback": tb_text,
                "context": context,
            }

        return tb_text

    @classmethod
    def log_warning(cls, msg: str, *args) -> None:
        """记录警告日志。"""
        _log_warning(msg, *args)

    @classmethod
    def log_info(cls, msg: str, *args) -> None:
        """记录信息日志。"""
        _log_info(msg, *args)

    @classmethod
    def get_last_error(cls) -> Optional[dict]:
        """返回最近一次错误（供调试 / ErrorDialog 展开）。"""
        with cls._lock:
            return dict(cls._last_error) if cls._last_error else None

    @classmethod
    def clear_last_error(cls) -> None:
        """清除最近错误缓存。"""
        with cls._lock:
            cls._last_error = None


# ============================================================
# 5. ErrorManager — 异常处理编排中心
# ============================================================
class ErrorManager:
    """异常处理编排中心。

    统一编排：try → log → friendly → detail → recover → continue。

    所有异常处理必须经过 ErrorManager，禁止各模块自行 except + QMessageBox。
    """

    # ---- 5.1 默认友好消息模板（按 ErrorCode 分类）----
    _MESSAGE_TEMPLATES: dict[ErrorCode, FriendlyMessage] = {
        ErrorCode.LICENSE: FriendlyMessage(
            title="License 授权失败",
            what="软件 License 授权无效或已过期，无法继续当前操作。",
            why="License 文件缺失、损坏、机器码不匹配或已过期。",
            how="1. 确认 config 目录下存在 license.key 和 public_key.pem\n"
                "2. 联系管理员重新签发 License\n"
                "3. 将新 License 文件放入 config 目录后重启软件",
        ),
        ErrorCode.MATLAB: FriendlyMessage(
            title="MATLAB 计算失败",
            what="MATLAB 算法执行失败，无法完成计算任务。",
            why="MATLAB 引擎未启动、算法崩溃、参数不合法或 MATLAB 版本不兼容。",
            how="1. 确认 MATLAB 已安装并加入 PATH（或设置 CSAM_MATLAB_EXE）\n"
                "2. 重启软件后重试\n"
                "3. 如问题持续，联系管理员检查 MATLAB 许可证",
        ),
        ErrorCode.FILE: FriendlyMessage(
            title="文件操作失败",
            what="文件读取或写入出错，操作未能完成。",
            why="文件路径不存在、没有写入权限、路径含特殊字符或磁盘空间不足。",
            how="1. 检查文件路径是否正确\n"
                "2. 换一个目录（如桌面）重试\n"
                "3. 用纯英文数字命名文件\n"
                "4. 联系管理员检查磁盘空间",
        ),
        ErrorCode.MESH: FriendlyMessage(
            title="网格数据处理失败",
            what="STL 模型或点云数据处理失败，无法继续。",
            why="STL 文件损坏、点云形状不符、三角化失败或数据量过大。",
            how="1. 检查 STL 文件是否完整（可用其他软件打开验证）\n"
                "2. 减小模型规模后重试\n"
                "3. 联系管理员检查数据格式",
        ),
        ErrorCode.NETWORK: FriendlyMessage(
            title="网络通信失败",
            what="软件无法与 MATLAB 计算服务通信。",
            why="MATLAB 未启动、Bridge 桥接服务未运行、网络不通或端口被占用。",
            how="1. 确认 MATLAB 已打开\n"
                "2. 在 MATLAB 中执行 matlab_bridge_server 启动桥接服务\n"
                "3. 确认 5555 端口未被占用\n"
                "4. 联系管理员检查网络连接",
        ),
        ErrorCode.EXPORT: FriendlyMessage(
            title="导出失败",
            what="结果导出失败，文件未能生成。",
            why="航点数据为空、导出路径不可写或导出参数不合法。",
            how="1. 确认已完成计算并生成了航点\n"
                "2. 选择一个有写入权限的目录\n"
                "3. 用纯英文数字命名导出文件\n"
                "4. 联系管理员检查磁盘空间",
        ),
        ErrorCode.UNKNOWN: FriendlyMessage(
            title="操作失败",
            what="操作过程中发生未预期错误。",
            why="错误详情已记录到日志，请联系技术支持排查。",
            how="1. 请截图保存此错误信息\n"
                "2. 重启软件后重试\n"
                "3. 如问题持续，联系管理员并提供此截图和日志文件",
        ),
    }

    # ---- 5.2 默认恢复策略 ----
    _RECOVERY_STRATEGIES: dict[ErrorCode, RecoveryStrategy] = {
        ErrorCode.LICENSE: RecoveryStrategy(action="fatal", fallback_hint="License 无效，软件无法运行"),
        ErrorCode.MATLAB: RecoveryStrategy(action="retry", fallback_hint="可重试或检查 MATLAB 状态"),
        ErrorCode.FILE: RecoveryStrategy(action="continue", fallback_hint="文件操作失败，可继续其他操作"),
        ErrorCode.MESH: RecoveryStrategy(action="continue", fallback_hint="网格处理失败，可重新加载模型"),
        ErrorCode.NETWORK: RecoveryStrategy(action="retry", fallback_hint="可重试或检查 Bridge 服务"),
        ErrorCode.EXPORT: RecoveryStrategy(action="continue", fallback_hint="导出失败，可继续计算其他结果"),
        ErrorCode.UNKNOWN: RecoveryStrategy(action="continue", fallback_hint="未预期错误，建议重启软件"),
    }

    # ---- 5.3 关键字分类映射（用于自动分类）----
    _KEYWORD_MAP: list[tuple[list[str], ErrorCode]] = [
        (["license", "授权", "签名", "public_key", "hmac"], ErrorCode.LICENSE),
        (["matlab", "engine", "算法", "matlab_algorithm", "MatlabAlgorithmError"], ErrorCode.MATLAB),
        (["timeout", "超时", "connection", "connect", "连接", "zmq", "bridge",
          "serializ", "protocol", "heartbeat", "BridgeError"], ErrorCode.NETWORK),
        (["file", "路径", "path", "permission", "denied", "not found",
          "文件", "权限", "No such file", "IsADirectoryError"], ErrorCode.FILE),
        (["stl", "mesh", "点云", "xyz", "triangle", "三角化",
          "shape", "vertex", "face", "PointCloud"], ErrorCode.MESH),
        (["export", "gcode", "robot", "pdf", "导出", "report"], ErrorCode.EXPORT),
    ]

    # ============================================================
    # 公开 API
    # ============================================================

    @classmethod
    def classify(
        cls,
        exc: BaseException,
        code: Optional[ErrorCode] = None,
        context: str = "",
    ) -> ErrorCode:
        """自动分类异常（若未指定 code，根据异常类型和消息推断）。"""
        if code is not None:
            return code

        # 1. 根据异常类型分类
        exc_type_name = type(exc).__name__
        exc_module = type(exc).__module__ or ""
        msg = str(exc).lower()

        # BridgeError 体系 → NETWORK
        if "bridge" in exc_module.lower() or "bridge" in exc_type_name.lower():
            return ErrorCode.NETWORK

        # MatlabAlgorithmError → MATLAB
        if "matlab" in exc_type_name.lower():
            return ErrorCode.MATLAB

        # FileNotFoundError / PermissionError → FILE
        if isinstance(exc, (FileNotFoundError, PermissionError, IsADirectoryError)):
            return ErrorCode.FILE

        # TimeoutError → NETWORK
        if isinstance(exc, TimeoutError):
            return ErrorCode.NETWORK

        # MemoryError → UNKNOWN（不单独分类，按未预期处理）
        if isinstance(exc, MemoryError):
            return ErrorCode.UNKNOWN

        # 2. 根据关键字分类
        full_text = f"{exc_type_name} {msg}".lower()
        for keywords, err_code in cls._KEYWORD_MAP:
            for kw in keywords:
                if kw.lower() in full_text:
                    return err_code

        # 3. 根据上下文分类
        ctx_lower = context.lower()
        if "license" in ctx_lower or "授权" in ctx_lower:
            return ErrorCode.LICENSE
        if "matlab" in ctx_lower or "算法" in ctx_lower or "计算" in ctx_lower:
            return ErrorCode.MATLAB
        if "导出" in ctx_lower or "export" in ctx_lower or "g-code" in ctx_lower:
            return ErrorCode.EXPORT
        if "路径规划" in ctx_lower or "形貌" in ctx_lower:
            return ErrorCode.MATLAB
        if "文件" in ctx_lower or "file" in ctx_lower or "加载" in ctx_lower:
            return ErrorCode.FILE
        if "stl" in ctx_lower or "网格" in ctx_lower or "点云" in ctx_lower:
            return ErrorCode.MESH

        return ErrorCode.UNKNOWN

    @classmethod
    def get_friendly_message(
        cls,
        exc: BaseException,
        code: ErrorCode,
        context: str = "",
    ) -> FriendlyMessage:
        """生成友好消息（基于模板 + 异常特定信息补充）。"""
        template = cls._MESSAGE_TEMPLATES.get(code, cls._MESSAGE_TEMPLATES[ErrorCode.UNKNOWN])
        msg = str(exc).lower()

        # 超时特化
        if "timeout" in msg or "超时" in msg:
            return FriendlyMessage(
                title=f"{context or '操作'}超时" if context else template.title,
                what=f"{context or '操作'}未能完成，因为等待时间超过了系统限制。",
                why="MATLAB 算法计算耗时过长，或网络响应缓慢，或 MATLAB 进程卡死。",
                how="1. 请稍后重试一次\n"
                    "2. 如果反复超时，联系管理员调大超时时间（CSAM_BRIDGE_TIMEOUT_MS）\n"
                    "3. 减小点云数据量或规划层数后重试",
            )

        # 连接失败特化
        if any(kw in msg for kw in ["connection", "connect", "连接", "refused"]):
            return FriendlyMessage(
                title=f"{context or '操作'}：无法连接服务" if context else template.title,
                what=f"{context or '操作'}失败，因为软件无法连接到 MATLAB 计算服务。",
                why="MATLAB 未启动，或 Bridge 桥接服务未运行，或网络不通。",
                how="1. 确认 MATLAB 已打开\n"
                    "2. 在 MATLAB 中执行 matlab_bridge_server 启动桥接服务\n"
                    "3. 确认操作电脑与 MATLAB 电脑在同一网络\n"
                    "4. 联系管理员检查 5555 端口是否被占用",
            )

        # 内存不足特化
        if "memory" in msg or "内存" in msg:
            return FriendlyMessage(
                title=f"{context or '操作'}：内存不足" if context else template.title,
                what=f"{context or '操作'}失败，因为系统内存不足。",
                why="点云数据过大、规划层数过多，或同时运行了其他占用内存的程序。",
                how="1. 关闭其他占内存的程序\n"
                    "2. 减小点云数据量\n"
                    "3. 减少规划层数\n"
                    "4. 联系管理员升级内存到 16GB",
            )

        # 通用：使用模板，但 title 加上 context
        if context and code != ErrorCode.UNKNOWN:
            return FriendlyMessage(
                title=f"{context}失败",
                what=template.what,
                why=template.why,
                how=template.how,
            )

        return template

    @classmethod
    def get_recovery_strategy(cls, code: ErrorCode) -> RecoveryStrategy:
        """返回某类错误的恢复策略。"""
        return cls._RECOVERY_STRATEGIES.get(code, cls._RECOVERY_STRATEGIES[ErrorCode.UNKNOWN])

    @classmethod
    def handle(
        cls,
        exc: Optional[BaseException] = None,
        code: Optional[ErrorCode] = None,
        context: str = "",
        parent: Any = None,
        show_dialog: bool = True,
        override_friendly: Optional[str] = None,
        log_text: str = "",
    ) -> tuple[ErrorCode, str]:
        """统一异常处理入口（核心 API）。

        流程：try → log → friendly → detail → recover → continue
          1. classify：自动分类（若未指定 code）
          2. log：LogManager 记录完整 traceback
          3. friendly：生成 What/Why/How
          4. detail：保留 traceback 供技术员展开
          5. recover：返回恢复策略
          6. continue：用户确认后继续

        支持两种模式：
          - 标准模式：传入 exc，自动分类、生成友好消息、记录日志、显示对话框
          - 转发模式（P1-31）：跨线程信号传递场景，Worker 端已通过 _pack_error
            记录日志并生成友好消息，接收方传入 override_friendly + log_text + code，
            跳过重复日志记录与自动分类，仅做对话框显示与策略调度。

        Args:
            exc: 异常对象（转发模式可为 None）
            code: 错误分类（None 则自动分类；转发模式必填）
            context: 操作上下文（如"路径规划"）
            parent: 父窗口（用于显示对话框）
            show_dialog: 是否显示 GUI 对话框（False 仅记录日志）
            override_friendly: 转发模式下 Worker 已生成的友好消息文本
                （含 What/Why/How），跳过模板生成
            log_text: 转发模式下 Worker 已生成的 traceback 文本；
                提供时跳过 LogManager.log_error 避免重复日志（P1-31 日志聚合）

        Returns:
            (ErrorCode, traceback_text)
        """
        # 1. 分类
        if code is not None:
            resolved_code = code
        elif exc is not None:
            resolved_code = cls.classify(exc, code, context)
        else:
            resolved_code = ErrorCode.UNKNOWN

        # 2. 记录日志
        # 转发模式：log_text 已提供，Worker 端 _pack_error 已记录，跳过避免重复日志
        if log_text:
            tb_text = log_text
        elif exc is not None:
            tb_text = LogManager.log_error(exc, resolved_code, context)
        else:
            tb_text = ""

        # 3. 生成友好消息 + 4. 显示对话框
        if override_friendly is not None:
            # 转发模式：使用 Worker 已生成的友好消息文本
            if show_dialog:
                cls._show_dialog_override(parent, override_friendly, tb_text, context)
        else:
            # 标准模式：从 exc 生成 FriendlyMessage
            if exc is not None:
                friendly = cls.get_friendly_message(exc, resolved_code, context)
                if show_dialog:
                    cls._show_dialog(parent, friendly, tb_text, exc)

        return resolved_code, tb_text

    @classmethod
    def _show_dialog(
        cls,
        parent: Any,
        friendly: FriendlyMessage,
        tb_text: str,
        exc: BaseException,
    ) -> None:
        """显示 ErrorDialog（延迟导入避免循环依赖）。"""
        try:
            from repair_app.ui.dialogs import ErrorDialog
            ErrorDialog.show(
                parent=parent,
                title=friendly.title,
                what=friendly.what,
                why=friendly.why,
                how=friendly.how,
                exc=exc,
            )
        except Exception as dialog_exc:
            # 对话框自身失败时退化到 stderr（绝不再次抛出）
            _log_error(f"[ErrorManager] ErrorDialog 显示失败: {dialog_exc}")
            if sys.stderr is not None:
                print(
                    f"[ErrorManager] {friendly.title}: {friendly.what}",
                    file=sys.stderr,
                )

    @classmethod
    def _show_dialog_override(
        cls,
        parent: Any,
        friendly_text: str,
        tb_text: str,
        context: str = "",
    ) -> None:
        """转发模式对话框显示（P1-31）。

        与 _show_dialog 的区别：
        - 入参是已组合的 friendly_text（Worker 端 _pack_error 生成）而非 FriendlyMessage
        - friendly_text 首行即标题，整体作为 what 字段展示
        - tb_text 作为 log_text 传入折叠区，不暴露给用户主视图
        """
        try:
            from repair_app.ui.dialogs import ErrorDialog
            # 标题优先取 friendly_text 首行（_pack_error 组合时首行是 friendly.title）
            title = f"{context}失败" if context else "操作失败"
            if friendly_text:
                first_line = friendly_text.split("\n", 1)[0].strip()
                if first_line:
                    title = first_line
            ErrorDialog.show(
                parent=parent,
                title=title,
                what=friendly_text,
                why="",
                how="",
                log_text=tb_text,
            )
        except Exception as dialog_exc:
            _log_error(f"[ErrorManager] ErrorDialog 显示失败: {dialog_exc}")
            if sys.stderr is not None:
                print(f"[ErrorManager] {friendly_text}", file=sys.stderr)

    # ============================================================
    # 装饰器 API
    # ============================================================

    @classmethod
    def guard(
        cls,
        code: Optional[ErrorCode] = None,
        context: str = "",
        parent_getter: Optional[Callable[[], Any]] = None,
        show_dialog: bool = True,
        reraise: bool = False,
    ) -> Callable:
        """装饰器：自动捕获函数异常并走 ErrorManager。

        Args:
            code: 错误分类（None 自动分类）
            context: 操作上下文
            parent_getter: 返回父窗口的 callable（避免装饰时窗口未创建）
            show_dialog: 是否显示 GUI 对话框
            reraise: 是否重新抛出异常（True 时记录 + 抛出，用于上层需感知的场景）
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    parent = parent_getter() if parent_getter else None
                    cls.handle(exc, code, context, parent=parent, show_dialog=show_dialog)
                    if reraise:
                        raise
                    return None
            return wrapper
        return decorator

    # ============================================================
    # 上下文管理器 API
    # ============================================================

    @classmethod
    @contextmanager
    def context(
        cls,
        code: Optional[ErrorCode] = None,
        context: str = "",
        parent: Any = None,
        show_dialog: bool = True,
    ) -> Iterator[None]:
        """上下文管理器：自动捕获 with 块内的异常。

        用法：
            with ErrorManager.context(ErrorCode.NETWORK, "ZMQ 请求"):
                reply = sock.recv()
        """
        try:
            yield
        except Exception as exc:
            cls.handle(exc, code, context, parent=parent, show_dialog=show_dialog)

    # ============================================================
    # 全局钩子安装
    # ============================================================

    @classmethod
    def install_global_hooks(cls, show_dialog: bool = True) -> None:
        """安装全局异常钩子（sys.excepthook + threading.excepthook）。

        在 run_app.py 启动时调用一次，确保：
        1. 主线程未捕获异常 → ErrorManager.handle
        2. 子线程未捕获异常 → ErrorManager.handle
        3. 用户永远不看到 Python Traceback

        注意：此方法会与 exception_reporter 配合使用（exception_reporter
        生成结构化报告文件，ErrorManager 显示用户友好对话框）。
        """
        # ---- 主线程：包装 sys.excepthook ----
        prev_excepthook = sys.excepthook

        def main_thread_hook(exc_type, exc_value, exc_tb):
            # KeyboardInterrupt 不拦截
            if issubclass(exc_type, KeyboardInterrupt):
                prev_excepthook(exc_type, exc_value, exc_tb)
                return
            try:
                # 先调用前一个钩子（exception_reporter 生成报告 + crash_handler 写日志）
                prev_excepthook(exc_type, exc_value, exc_tb)
            except Exception as hook_exc:
                # P1-33: 钩子自身失败时至少保证 stderr 兜底输出，不静默吞没
                if sys.stderr is not None:
                    print(f"[ErrorManager prev_excepthook] {hook_exc}", file=sys.stderr)
            # 再显示用户友好对话框（主线程才能操作 GUI）
            try:
                cls.handle(exc_value, context="未捕获异常（主线程）", show_dialog=show_dialog)
            except Exception as hook_exc:
                # P1-33: 钩子自身失败时至少保证 stderr 兜底输出，不静默吞没
                if sys.stderr is not None:
                    print(f"[ErrorManager main_thread_hook] {hook_exc}", file=sys.stderr)

        sys.excepthook = main_thread_hook

        # ---- 子线程：安装 threading.excepthook ----
        def thread_hook(args):
            # 仅处理非 KeyboardInterrupt
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
            try:
                # 子线程异常不能直接弹 GUI 对话框（Qt 限制），仅记录日志
                cls.handle(
                    args.exc_value,
                    context=f"未捕获异常（子线程 {args.thread.name}）",
                    show_dialog=False,
                )
            except Exception as hook_exc:
                # P1-33: 钩子自身失败时至少保证 stderr 兜底输出，不静默吞没
                if sys.stderr is not None:
                    print(f"[ErrorManager thread_hook] {hook_exc}", file=sys.stderr)

        # Python 3.8+ 支持 threading.excepthook
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_hook

        _log_info("[ErrorManager] 全局异常钩子已安装（主线程 + 子线程）")


# ============================================================
# 便捷导出（供业务层直接 import）
# ============================================================
def handle_error(
    exc: BaseException,
    code: Optional[ErrorCode] = None,
    context: str = "",
    parent: Any = None,
    show_dialog: bool = True,
) -> tuple[ErrorCode, str]:
    """ErrorManager.handle 的便捷别名。"""
    return ErrorManager.handle(exc, code, context, parent=parent, show_dialog=show_dialog)


def classify_exception(exc: BaseException, context: str = "") -> ErrorCode:
    """ErrorManager.classify 的便捷别名。"""
    return ErrorManager.classify(exc, context=context)
