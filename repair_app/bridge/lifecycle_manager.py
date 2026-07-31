"""bridge.lifecycle_manager — MATLAB 生命周期管理看门狗

职责：在后台 QThread 中持续监控 MATLAB + Bridge 健康状态，
检测崩溃时自动重启，并对外发出状态变更信号。

用法：
    manager = MatlabLifecycleManager(project_root)
    manager.status_changed.connect(on_status)   # GUI 订阅状态
    manager.start()                              # 启动监控（非阻塞）
    ...
    manager.stop()                               # 停止监控 + 关闭 MATLAB

设计要点：
- 不阻塞 GUI（QThread + QTimer 轮询）
- 自动重启（崩溃检测后调用 launcher.restart）
- 状态变更通知（信号驱动 GUI 更新）
- 单例模式（全局唯一管理器）
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer

from .launcher import MatlabBridgeLauncher

logger = logging.getLogger("csam.bridge.lifecycle")


class LifecycleStatus:
    """MATLAB 生命周期状态枚举（字符串常量）。"""
    UNKNOWN = "unknown"               # 未知/未启动
    DETECTING = "detecting"           # 正在检测 MATLAB
    STARTING = "starting"             # 正在启动 MATLAB + Bridge
    READY = "ready"                   # Bridge 已就绪
    BUSY = "busy"                     # 正在执行计算
    RECOVERING = "recovering"         # 超时/崩溃后正在恢复
    CRASHED = "crashed"               # 检测到崩溃
    RESTARTING = "restarting"         # 正在重启
    FAILED = "failed"                 # 启动失败/重启次数耗尽
    STOPPING = "stopping"             # 正在关闭
    STOPPED = "stopped"               # 已主动停止


class MatlabLifecycleManager(QObject):
    """MATLAB 生命周期管理器（单例）。

    信号：
        status_changed(str, str)  : (status, message) 状态变更
        matlab_started(str)       : MATLAB 版本号
        matlab_stopped()          : MATLAB 已关闭
        matlab_crashed(str)       : 崩溃原因
        matlab_restarted(int)     : 重启次数
    """

    # 信号定义
    status_changed = Signal(str, str)   # (status, message)
    matlab_started = Signal(str)        # version
    matlab_stopped = Signal()
    matlab_crashed = Signal(str)        # reason
    matlab_restarted = Signal(int)      # restart_count
    _watchdog_requested = Signal()
    _async_start_finished = Signal(bool, str)

    # 监控参数
    WATCH_INTERVAL_MS = 3000            # 监控轮询间隔（3 秒）
    STARTUP_TIMEOUT_S = 120             # 启动超时
    MAX_AUTO_RESTARTS = 3               # 自动重启最大次数

    _singleton: Optional["MatlabLifecycleManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, project_root: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._project_root = Path(project_root).resolve()
        self._launcher = MatlabBridgeLauncher(str(self._project_root))
        self._status = LifecycleStatus.UNKNOWN
        self._message = ""
        self._watch_timer: Optional[QTimer] = None
        self._enabled = False
        self._auto_restart_enabled = True
        self._is_starting = False  # 防止并发启动
        self._state_lock = threading.Lock()  # 保护 _status/_message/_is_starting
        self._watchdog_requested.connect(self._start_watchdog)
        self._async_start_finished.connect(self._on_async_start_finished)

        # 合法状态转换表
        self._VALID_TRANSITIONS = {
            LifecycleStatus.UNKNOWN:    {LifecycleStatus.STARTING, LifecycleStatus.STOPPED},
            LifecycleStatus.DETECTING:  {LifecycleStatus.STARTING, LifecycleStatus.FAILED, LifecycleStatus.STOPPED},
            LifecycleStatus.STARTING:   {LifecycleStatus.READY, LifecycleStatus.FAILED, LifecycleStatus.STOPPING},
            LifecycleStatus.READY:      {LifecycleStatus.BUSY, LifecycleStatus.STOPPING, LifecycleStatus.CRASHED},
            LifecycleStatus.BUSY:       {LifecycleStatus.READY, LifecycleStatus.RECOVERING, LifecycleStatus.CRASHED, LifecycleStatus.STOPPING},
            LifecycleStatus.RECOVERING: {LifecycleStatus.READY, LifecycleStatus.FAILED, LifecycleStatus.STOPPING},
            LifecycleStatus.CRASHED:    {LifecycleStatus.RESTARTING, LifecycleStatus.FAILED, LifecycleStatus.STOPPING},
            LifecycleStatus.RESTARTING: {LifecycleStatus.READY, LifecycleStatus.FAILED, LifecycleStatus.STOPPING},
            LifecycleStatus.FAILED:     {LifecycleStatus.STARTING, LifecycleStatus.STOPPING},
            LifecycleStatus.STOPPING:   {LifecycleStatus.STOPPED},
            LifecycleStatus.STOPPED:    set(),
        }

    # ------------------------------------------------------------------
    # 单例
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls, project_root: Optional[str] = None) -> "MatlabLifecycleManager":
        """获取单例实例。

        首次调用需提供 project_root，后续调用可省略。
        """
        with cls._singleton_lock:
            if cls._singleton is None:
                if project_root is None:
                    raise ValueError("首次调用必须提供 project_root")
                cls._singleton = cls(project_root)
            return cls._singleton

    @classmethod
    def reset_singleton(cls) -> None:
        """重置单例（测试用）。先取出引用再释放锁，避免 stop() 阻塞其他线程。"""
        with cls._singleton_lock:
            instance = cls._singleton
            cls._singleton = None
        if instance is not None:
            instance.stop()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def status(self) -> str:
        return self._status

    @property
    def message(self) -> str:
        return self._message

    @property
    def is_ready(self) -> bool:
        """Bridge 是否就绪。"""
        return self._status == LifecycleStatus.READY

    @property
    def launcher(self) -> MatlabBridgeLauncher:
        return self._launcher

    @property
    def matlab_version(self) -> Optional[str]:
        return self._launcher.matlab_version

    @property
    def restart_count(self) -> int:
        return self._launcher.restart_count

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------
    def _validate_transition(self, new_status: str) -> None:
        """验证状态转换是否合法（开发阶段检查，生产环境仅警告）。"""
        allowed = self._VALID_TRANSITIONS.get(self._status, set())
        if new_status not in allowed:
            logger.warning(
                "非标准状态转换: %s → %s (允许: %s)",
                self._status, new_status, allowed,
            )

    def _set_status(self, status: str, message: str = "") -> None:
        """更新状态并发出信号。"""
        with self._state_lock:
            if self._status == status and self._message == message:
                return
            self._validate_transition(status)
            old = self._status
            self._status = status
            self._message = message
        logger.info("Lifecycle 状态变更: %s → %s (%s)", old, status, message)
        self.status_changed.emit(status, message)

        # 派发特定事件
        if status == LifecycleStatus.READY and old != LifecycleStatus.READY:
            version = self._launcher.matlab_version or "unknown"
            self.matlab_started.emit(version)
        elif status == LifecycleStatus.STOPPED:
            self.matlab_stopped.emit()
        elif status == LifecycleStatus.CRASHED:
            self.matlab_crashed.emit(message)
        elif status == LifecycleStatus.RESTARTING:
            self.matlab_restarted.emit(self._launcher.restart_count)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self, auto_restart: bool = True) -> bool:
        """启动生命周期管理。

        1. 启动 MATLAB + Bridge（若未运行）
        2. 启动后台监控定时器

        Args:
            auto_restart: 是否启用崩溃自动重启

        Returns:
            True 表示 MATLAB + Bridge 已就绪
        """
        self._auto_restart_enabled = auto_restart
        self._enabled = True

        with self._state_lock:
            # 已就绪则直接返回，避免不必要的状态转换和 UI 闪烁
            if self._status == LifecycleStatus.READY:
                return True
            if self._is_starting:
                logger.warning("Lifecycle 已在启动中，跳过重复调用")
                return self.is_ready
            self._is_starting = True

        try:
            self._set_status(LifecycleStatus.STARTING, "正在启动 MATLAB + Bridge...")

            ok = self._launcher.start(timeout=self.STARTUP_TIMEOUT_S)
            if not ok:
                self._set_status(
                    LifecycleStatus.FAILED,
                    "MATLAB 启动失败。请检查 MATLAB 安装或设置 CSAM_MATLAB_EXE 环境变量",
                )
                self._enabled = False
                return False

            version = self._launcher.matlab_version or "unknown"
            reused = "复用现有会话" if self._launcher.reused_existing else "新启动"
            self._set_status(
                LifecycleStatus.READY,
                f"MATLAB {version} 已就绪（{reused}）",
            )

            # 启动监控定时器
            self._watchdog_requested.emit()
            return True
        finally:
            with self._state_lock:
                self._is_starting = False

    def start_async(self, auto_restart: bool = True) -> bool:
        """Start MATLAB without blocking the GUI event loop."""
        self._auto_restart_enabled = auto_restart
        self._enabled = True
        with self._state_lock:
            if self._is_starting:
                return False
            if self._status == LifecycleStatus.READY:
                return True
            self._is_starting = True

        self._set_status(LifecycleStatus.STARTING, "正在启动 MATLAB + Bridge...")

        def _launch() -> None:
            try:
                ok = self._launcher.start(timeout=self.STARTUP_TIMEOUT_S)
                self._async_start_finished.emit(ok, "")
            except Exception as exc:
                self._async_start_finished.emit(False, str(exc))

        threading.Thread(
            target=_launch,
            name="csam-matlab-startup",
            daemon=True,
        ).start()
        return True

    @Slot(bool, str)
    def _on_async_start_finished(self, ok: bool, error: str) -> None:
        try:
            if ok:
                version = self._launcher.matlab_version or "unknown"
                reused = (
                    "复用现有会话"
                    if self._launcher.reused_existing
                    else "新启动"
                )
                self._set_status(
                    LifecycleStatus.READY,
                    f"MATLAB {version} 已就绪（{reused}）",
                )
                self._start_watchdog()
            else:
                message = "MATLAB 启动失败"
                if error:
                    message += f": {error}"
                self._set_status(LifecycleStatus.FAILED, message)
                self._enabled = False
        finally:
            with self._state_lock:
                self._is_starting = False

    def stop(self) -> None:
        """停止生命周期管理并关闭 MATLAB。"""
        self._enabled = False
        self._stop_watchdog()

        if self._launcher is not None:
            self._launcher.stop()
        self._set_status(LifecycleStatus.STOPPED, "MATLAB 已关闭")

    def ensure_ready(self) -> bool:
        """确保 Bridge 已就绪（供计算前调用）。

        若已就绪返回 True。
        若未就绪尝试启动一次。
        若已崩溃尝试重启一次。
        """
        if self.is_ready:
            return True

        if self._status == LifecycleStatus.CRASHED:
            return self._try_restart()

        # 未启动或失败状态：尝试启动
        return self.start(auto_restart=self._auto_restart_enabled)

    def terminate_owned_worker(self, reason: str = "") -> bool:
        """Terminate only a MATLAB process launched by this application.

        Reused/manual MATLAB sessions are never killed.  On success the
        lifecycle enters CRASHED so the next ``ensure_ready`` performs a clean
        restart before accepting another computation.
        """
        if self._launcher.reused_existing:
            logger.error("拒绝终止复用的 MATLAB 会话: %s", reason)
            return False
        if self._launcher.process is None:
            logger.error("没有当前应用拥有的 MATLAB Worker 可终止: %s", reason)
            return False

        self._launcher.stop()
        terminated = not self._launcher.is_process_alive
        if terminated:
            self._set_status(
                LifecycleStatus.CRASHED,
                f"MATLAB Worker 已终止，等待恢复: {reason}",
            )
        return terminated

    # ------------------------------------------------------------------
    # 监控看门狗
    # ------------------------------------------------------------------
    def _start_watchdog(self) -> None:
        """启动后台监控定时器。"""
        if self._watch_timer is not None:
            return
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)
        self._watch_timer.start(self.WATCH_INTERVAL_MS)
        logger.info("看门狗已启动（间隔 %dms）", self.WATCH_INTERVAL_MS)

    def _stop_watchdog(self) -> None:
        """停止监控定时器。"""
        if self._watch_timer is not None:
            self._watch_timer.stop()
            self._watch_timer.deleteLater()
            self._watch_timer = None
            logger.info("看门狗已停止")

    @Slot()
    def _watch_tick(self) -> None:
        """看门狗轮询：检测崩溃并自动恢复。"""
        if not self._enabled:
            return

        # 仅在 READY 状态下监控崩溃
        if self._status != LifecycleStatus.READY:
            return

        try:
            if self._launcher.detect_crash():
                reason = "MATLAB 进程已退出"
                if self._launcher.process is not None:
                    rc = self._launcher.process.returncode
                    reason = f"MATLAB 进程已退出（返回码={rc}）"
                logger.error("检测到 MATLAB 崩溃: %s", reason)
                self._set_status(LifecycleStatus.CRASHED, reason)

                # 自动重启
                if self._auto_restart_enabled:
                    QTimer.singleShot(100, self._try_restart)
        except Exception as exc:
            logger.warning("看门狗轮询异常: %s", exc)

    def _try_restart(self) -> bool:
        """尝试重启 MATLAB + Bridge（在后台线程执行，避免阻塞主线程）。"""
        if self._launcher.restart_count >= self.MAX_AUTO_RESTARTS:
            self._set_status(
                LifecycleStatus.FAILED,
                f"已达到最大重启次数 {self.MAX_AUTO_RESTARTS}，放弃自动恢复",
            )
            return False

        self._set_status(
            LifecycleStatus.RESTARTING,
            f"正在重启 MATLAB（第 {self._launcher.restart_count + 1} 次）...",
        )

        def _do_restart():
            """后台线程执行重启，通过信号回传结果。"""
            ok = self._launcher.restart(timeout=self.STARTUP_TIMEOUT_S)
            if ok:
                version = self._launcher.matlab_version or "unknown"
                self._set_status(
                    LifecycleStatus.READY,
                    f"MATLAB {version} 已重启成功",
                )
            else:
                if self._launcher.restart_count >= self.MAX_AUTO_RESTARTS:
                    self._set_status(
                        LifecycleStatus.FAILED,
                        "重启次数耗尽，MATLAB 不可用",
                    )
                else:
                    self._set_status(
                        LifecycleStatus.CRASHED,
                        "重启失败，将再次尝试",
                    )

        # 在后台线程执行，避免 MATLAB 启动（30-60s）阻塞 Qt 主线程
        import threading
        t = threading.Thread(target=_do_restart, daemon=True)
        t.start()
        return True

    # ------------------------------------------------------------------
    # 计算状态标记
    # ------------------------------------------------------------------
    @contextmanager
    def execution_scope(self) -> Generator[None, None, None]:
        """执行上下文管理器：自动管理 BUSY/READY 状态转换。

        用法：
            with manager.execution_scope():
                result = do_matlab_computation()

        自动完成：
        - 进入时：READY → BUSY
        - 正常退出时：BUSY → READY
        - 异常退出时：BUSY → RECOVERING（不自动回 READY）
        """
        if self._status != LifecycleStatus.READY:
            self.ensure_ready()
            if not self.is_ready:
                raise RuntimeError(
                    f"MATLAB 未就绪（当前状态: {self._status}），无法执行计算"
                )

        self._set_status(LifecycleStatus.BUSY, "正在执行计算...")
        try:
            yield
            # 正常完成：恢复 READY 并重置重启计数
            self._launcher.reset_restart_count()
            version = self._launcher.matlab_version or "unknown"
            self._set_status(LifecycleStatus.READY, f"MATLAB {version} 已就绪")
        except Exception:
            # 区分异常类型：仅引擎级异常才进入 RECOVERING
            # 临时网络错误（BridgeError 子类如 ConnectionTimeoutError）保持 READY
            from repair_app.bridge.communication.exceptions import (
                EngineUnavailableError,
                MatlabEngineUnhealthyError,
                EngineCrashError,
                MatlabCallTimeoutError,
            )
            if isinstance(exc := sys.exc_info()[1], (
                EngineUnavailableError,
                MatlabEngineUnhealthyError,
                EngineCrashError,
                # P1-15: 超时意味着引擎已不健康，进入 RECOVERING 而非错误恢复 READY
                MatlabCallTimeoutError,
            )):
                self._set_status(
                    LifecycleStatus.RECOVERING,
                    "引擎异常，MATLAB 需要恢复",
                )
            else:
                # 临时错误：恢复 READY 状态，下次可重试
                version = self._launcher.matlab_version or "unknown"
                self._set_status(
                    LifecycleStatus.READY,
                    f"MATLAB {version} 已就绪（上次计算异常但引擎健康）",
                )
            raise

    def mark_busy(self) -> None:
        """DEPRECATED: 使用 execution_scope() 替代。"""
        logger.warning("mark_busy() 已废弃，请使用 execution_scope()")
        if self._status == LifecycleStatus.READY:
            self._set_status(LifecycleStatus.BUSY, "正在执行计算...")

    def mark_idle(self) -> None:
        """DEPRECATED: 使用 execution_scope() 替代。"""
        logger.warning("mark_idle() 已废弃，请使用 execution_scope()")
        if self._status == LifecycleStatus.BUSY:
            self._launcher.reset_restart_count()
            version = self._launcher.matlab_version or "unknown"
            self._set_status(LifecycleStatus.READY, f"MATLAB {version} 已就绪")
