"""bridge.launcher — MATLAB + Bridge 自动启动器

目标：用户不需要手动打开 MATLAB、不需要手动运行 matlab_bridge_server.m。
点击"开始计算"时，本模块自动完成：
  1. 查找 MATLAB 可执行文件（优先 R2025b 及接近版本）
  2. 以 -batch 模式启动 MATLAB，运行 matlab_bridge_server
  3. 等待 Bridge 端口就绪
  4. 软件退出时自动关闭 MATLAB 进程
  5. MATLAB 崩溃时自动检测并重启

设计要点：
- 跨平台兼容（Windows / Linux / macOS）
- 不阻塞 GUI（在 QThread 中调用）
- 启动失败时给出明确错误提示
- 支持复用已运行的 MATLAB 共享会话（避免重复启动）
- 崩溃检测 + 自动重启（max_restarts 次数限制）
- 强制清理：terminate → kill → wait，杜绝僵尸进程
"""
from __future__ import annotations

import atexit
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from repair_app.config import schema_loader as _schema


def _extract_port_from_addr(addr: str) -> int:
    """从 tcp://host:port 地址中提取端口。失败返回 schema 默认端口。"""
    try:
        return int(addr.rsplit(":", 1)[1])
    except Exception:
        return int(_schema.get_network_value("zmq_default_address").rsplit(":", 1)[1])

from typing import Optional, Tuple, List

logger = logging.getLogger("csam.bridge.launcher")

# 支持的 MATLAB 版本（R2025b 优先，向下兼容到 R2022a）
PREFERRED_MATLAB_VERSIONS = [
    "R2025b", "R2025a",
    "R2024b", "R2024a",
    "R2023b", "R2023a",
    "R2022b", "R2022a",
]


class MatlabBridgeLauncher:
    """自动启动 MATLAB 并运行 Bridge 服务。

    用法：
        launcher = MatlabBridgeLauncher(project_root)
        launcher.start()      # 启动 MATLAB + Bridge（阻塞直到就绪）
        # ... 执行计算 ...
        launcher.stop()       # 关闭 MATLAB（可选）

    若检测到 Bridge 端口已被占用（说明用户已手动启动 matlab_bridge_server），
    则跳过启动，直接复用现有会话。
    """

    DEFAULT_PORT = _extract_port_from_addr(_schema.get_network_value("zmq_default_address"))
    DEFAULT_SHARED_NAME = "matlab_bridge"
    STARTUP_TIMEOUT_S = int(_schema.get_network_value("launcher_startup_timeout_sec"))
    POLL_INTERVAL_S = float(_schema.get_network_value("launcher_poll_interval_sec"))
    MAX_RESTARTS = int(_schema.get_network_value("launcher_max_restarts"))
    RESTART_DELAY_S = float(_schema.get_network_value("launcher_restart_delay_sec"))
    STOP_TIMEOUT_S = int(_schema.get_network_value("launcher_stop_timeout_sec"))
    KILL_TIMEOUT_S = int(_schema.get_network_value("launcher_kill_timeout_sec"))

    def __init__(
        self,
        project_root: str,
        port: int = DEFAULT_PORT,
        shared_name: str = DEFAULT_SHARED_NAME,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._port = port
        self._shared_name = shared_name
        self._process: Optional[subprocess.Popen] = None
        self._reused_existing = False
        self._matlab_exe: Optional[str] = None
        self._matlab_version: Optional[str] = None
        self._restart_count = 0
        self._atexit_registered = False

    @property
    def is_running(self) -> bool:
        """Bridge 端口是否可连接（说明 Bridge 已就绪）。"""
        return self._is_port_open(self._port)

    @property
    def is_process_alive(self) -> bool:
        """MATLAB 子进程是否仍在运行（不代表 Bridge 已就绪）。"""
        if self._reused_existing:
            return self._is_port_open(self._port)
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def reused_existing(self) -> bool:
        """是否复用了已运行的 Bridge（而非新启动 MATLAB）。"""
        return self._reused_existing

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """底层 MATLAB 子进程（若由本启动器启动）。"""
        return self._process

    @property
    def matlab_exe(self) -> Optional[str]:
        """MATLAB 可执行文件路径。"""
        return self._matlab_exe

    @property
    def matlab_version(self) -> Optional[str]:
        """检测到的 MATLAB 版本（如 R2025b）。"""
        return self._matlab_version

    @property
    def restart_count(self) -> int:
        """已发生的重启次数。"""
        return self._restart_count

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def start(self, timeout: float = STARTUP_TIMEOUT_S) -> bool:
        """启动 MATLAB + Bridge，阻塞直到就绪或超时。

        返回 True 表示 Bridge 已就绪（新启动或复用现有）。
        返回 False 表示启动失败。
        """
        # 1. 检查 Bridge 是否已就绪（用户可能已手动启动）
        if self._is_port_open(self._port):
            logger.info("Bridge 端口 %d 已就绪，复用现有 MATLAB 会话", self._port)
            self._reused_existing = True
            return True

        # 2. 查找 MATLAB 可执行文件（优先 R2025b）
        matlab_exe, version = self._find_matlab_executable_with_version()
        if matlab_exe is None:
            logger.error("未找到 MATLAB 可执行文件，无法自动启动")
            return False
        self._matlab_exe = matlab_exe
        self._matlab_version = version
        logger.info("使用 MATLAB 版本: %s (%s)", version, matlab_exe)

        # 3. 构造启动命令
        server_script = self._project_root / "matlab_bridge_server.m"
        if not server_script.exists():
            logger.error("matlab_bridge_server.m 不存在: %s", server_script)
            return False

        # -nodesktop -nosplash -r 模式：启动 MATLAB 并执行脚本，不显示桌面
        # 使用 -r 而非 -batch 以支持 engine sharing（硬约束）
        # cd 到项目根目录后运行 matlab_bridge_server
        cmd = [
            matlab_exe,
            "-nodesktop",
            "-nosplash",
            "-r",
            f"cd('{self._project_root.as_posix()}'); matlab_bridge_server",
        ]

        logger.info("正在启动 MATLAB: %s", " ".join(cmd))
        try:
            # 关键：CREATE_NEW_PROCESS_GROUP 确保 Ctrl+C 不会传递到 MATLAB 子进程
            # 避免 MATLAB 僵尸进程（Ctrl+C 时主进程退出但 MATLAB 仍在运行）
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            self._process = subprocess.Popen(
                cmd,
                cwd=str(self._project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
                # 关键：在父进程退出时，子进程会被 stop() 显式关闭
                # 不使用 close_fds=False，避免 Windows 句柄泄露
            )
        except Exception as exc:
            logger.error("启动 MATLAB 失败: %s", exc)
            return False

        # 注册 atexit 清理（确保异常退出时也能关闭 MATLAB）
        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True

        # 4. 等待 Bridge 端口就绪
        logger.info("等待 Bridge 端口 %d 就绪（超时 %ds）...", self._port, timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._process.poll() is not None:
                # MATLAB 进程已退出
                logger.error("MATLAB 进程提前退出，返回码=%d", self._process.returncode)
                self._dump_process_output(max_lines=20)
                return False
            if self._is_port_open(self._port):
                elapsed = timeout - (deadline - time.time())
                logger.info("Bridge 已就绪（MATLAB 启动耗时 %.1fs）", elapsed)
                self._reused_existing = False
                # 启动成功后重置重启计数
                self._restart_count = 0
                return True
            time.sleep(self.POLL_INTERVAL_S)

        logger.error("等待 Bridge 就绪超时（%ds）", timeout)
        return False

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """关闭由本启动器启动的 MATLAB 进程。

        清理顺序：
        1. terminate() (SIGTERM) → 等待 STOP_TIMEOUT_S
        2. kill() (SIGKILL) → 等待 KILL_TIMEOUT_S
        3. 强制清理（Windows taskkill / Linux kill -9）

        若复用了现有会话则不关闭（避免影响用户手动启动的 MATLAB）。
        """
        if self._reused_existing:
            logger.info("复用现有 MATLAB 会话，不关闭")
            return
        if self._process is None:
            return
        if self._process.poll() is not None:
            logger.info("MATLAB 进程已退出")
            self._process = None
            return

        pid = self._process.pid
        try:
            logger.info("正在关闭 MATLAB 进程 (PID=%d)...", pid)

            # 阶段 1：优雅关闭 terminate()
            self._process.terminate()
            try:
                self._process.wait(timeout=self.STOP_TIMEOUT_S)
                logger.info("MATLAB 进程已优雅退出 (PID=%d)", pid)
                self._process = None
                return
            except subprocess.TimeoutExpired:
                logger.warning("MATLAB 未在 %ds 内退出，强制 kill (PID=%d)",
                               self.STOP_TIMEOUT_S, pid)

            # 阶段 2：强制 kill()
            self._process.kill()
            try:
                self._process.wait(timeout=self.KILL_TIMEOUT_S)
                logger.info("MATLAB 进程已强制终止 (PID=%d)", pid)
                self._process = None
                return
            except subprocess.TimeoutExpired:
                logger.error("MATLAB 进程 kill 后仍未退出 (PID=%d)", pid)

            # 阶段 3：操作系统级强制清理（兜底，防止僵尸进程）
            self._force_kill_os(pid)
            self._process = None

        except Exception as exc:
            logger.warning("关闭 MATLAB 进程异常: %s", exc)
            # 异常时也尝试强制清理
            try:
                self._force_kill_os(pid)
            except Exception:
                pass
            self._process = None

    # ------------------------------------------------------------------
    # 崩溃检测与重启
    # ------------------------------------------------------------------
    def detect_crash(self) -> bool:
        """检测 MATLAB 进程是否已崩溃（不再运行但未显式 stop）。

        返回 True 表示检测到崩溃。
        复用现有会话时，通过端口检测判断。
        """
        if self._reused_existing:
            # 复用模式：端口不可连接即视为崩溃
            return not self._is_port_open(self._port)
        if self._process is None:
            return False
        # 自启动模式：进程退出且未显式 stop 即视为崩溃
        return self._process.poll() is not None

    def restart(self, timeout: float = STARTUP_TIMEOUT_S) -> bool:
        """重启 MATLAB + Bridge（崩溃恢复）。

        Returns:
            True 表示重启成功，False 表示失败（达到最大重启次数或启动失败）。
        """
        if self._restart_count >= self.MAX_RESTARTS:
            logger.error("已达到最大重启次数 %d，放弃重启", self.MAX_RESTARTS)
            return False

        self._restart_count += 1
        logger.warning("MATLAB 崩溃，正在重启（第 %d/%d 次）...",
                       self._restart_count, self.MAX_RESTARTS)

        # 等待一段时间再重启（避免立即崩溃的循环）
        time.sleep(self.RESTART_DELAY_S)

        # 清理旧进程（避免端口占用）
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=self.KILL_TIMEOUT_S)
        except Exception:
            pass
        self._process = None
        self._reused_existing = False

        # 重新启动
        return self.start(timeout=timeout)

    def reset_restart_count(self) -> None:
        """重置重启计数器（计算成功后调用）。"""
        self._restart_count = 0

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _dump_process_output(self, max_lines: int = 20) -> None:
        """输出 MATLAB 子进程的 stdout/stderr（用于调试启动失败）。"""
        if self._process is None or self._process.stdout is None:
            return
        try:
            # 非阻塞读取已有输出
            import threading
            output_lines = []

            def reader():
                try:
                    for line in self._process.stdout:
                        output_lines.append(line)
                        if len(output_lines) >= max_lines:
                            break
                except Exception:
                    pass

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join(timeout=1.0)
            if output_lines:
                logger.error("MATLAB 进程输出（最后 %d 行）:", len(output_lines))
                for line in output_lines:
                    logger.error("  %s", line.rstrip())
        except Exception:
            pass

    def _force_kill_os(self, pid: int) -> None:
        """操作系统级强制清理（兜底防止僵尸进程）。"""
        try:
            if sys.platform == "win32":
                # Windows: taskkill /F /T /PID
                # /F 强制终止，/T 终止子进程树
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
                logger.info("taskkill 已执行 (PID=%d)", pid)
            else:
                # Linux/macOS: kill -9
                os.kill(pid, signal.SIGKILL)
                logger.info("SIGKILL 已发送 (PID=%d)", pid)
        except Exception as exc:
            logger.warning("操作系统级清理失败 (PID=%d): %s", pid, exc)

    @staticmethod
    def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
        """检查端口是否可连接。"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect((host, port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    @classmethod
    def _find_matlab_executable_with_version(cls) -> Tuple[Optional[str], Optional[str]]:
        """查找 MATLAB 可执行文件路径并返回版本号。

        查找顺序：
        1. 环境变量 CSAM_MATLAB_EXE（用户指定）
        2. PATH 中的 matlab
        3. Windows 默认安装路径（按版本优先级排序）
        4. Linux/macOS 默认安装路径

        Returns:
            (exe_path, version_str) 或 (None, None)
        """
        # 1. 环境变量
        env_exe = os.environ.get("CSAM_MATLAB_EXE")
        if env_exe and os.path.isfile(env_exe):
            version = cls._parse_version_from_path(env_exe)
            logger.info("使用环境变量 CSAM_MATLAB_EXE: %s (版本: %s)", env_exe, version)
            return env_exe, version

        # 2. PATH
        which = shutil.which("matlab")
        if which:
            version = cls._parse_version_from_path(which)
            logger.info("从 PATH 找到 MATLAB: %s (版本: %s)", which, version)
            return which, version

        # 3. 平台默认路径
        if sys.platform == "win32":
            # C:\Program Files\MATLAB\R20XXx\bin\matlab.exe
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            matlab_root = Path(program_files) / "MATLAB"
            if matlab_root.exists():
                # 按优先级排序（R2025b 优先）
                installed = [d for d in matlab_root.iterdir() if d.is_dir()]
                sorted_versions = cls._sort_by_preference(installed)
                for ver_dir in sorted_versions:
                    exe = ver_dir / "bin" / "matlab.exe"
                    if exe.exists():
                        version = ver_dir.name
                        logger.info("从默认安装路径找到 MATLAB: %s (版本: %s)", exe, version)
                        return str(exe), version
        elif sys.platform == "darwin":
            # /Applications/MATLAB_R20XXx.app/bin/matlab
            apps = Path("/Applications")
            installed = list(apps.glob("MATLAB_R*.app"))
            sorted_versions = cls._sort_by_preference(installed)
            for app in sorted_versions:
                exe = app / "bin" / "matlab"
                if exe.exists():
                    version = cls._parse_version_from_path(str(app))
                    logger.info("从 Applications 找到 MATLAB: %s (版本: %s)", exe, version)
                    return str(exe), version
        else:
            # Linux: /usr/local/MATLAB/R20XXx/bin/matlab
            usr_local = Path("/usr/local/MATLAB")
            if usr_local.exists():
                installed = [d for d in usr_local.iterdir() if d.is_dir()]
                sorted_versions = cls._sort_by_preference(installed)
                for ver_dir in sorted_versions:
                    exe = ver_dir / "bin" / "matlab"
                    if exe.exists():
                        version = ver_dir.name
                        logger.info("从 /usr/local/MATLAB 找到 MATLAB: %s (版本: %s)", exe, version)
                        return str(exe), version

        return None, None

    @classmethod
    def _find_matlab_executable(cls) -> Optional[str]:
        """向后兼容：仅返回可执行文件路径。"""
        exe, _ = cls._find_matlab_executable_with_version()
        return exe

    @staticmethod
    def _parse_version_from_path(path: str) -> Optional[str]:
        """从路径中解析 MATLAB 版本号（如 R2025b）。"""
        # 匹配 R20XXa / R20XXb 格式
        match = re.search(r"(R\d{4}[ab])", path, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def _sort_by_preference(paths: List[Path]) -> List[Path]:
        """按优先级排序 MATLAB 版本路径（R2025b 优先，向下兼容）。"""
        def version_key(p: Path) -> Tuple[int, int]:
            name = p.name.upper()
            for i, preferred in enumerate(PREFERRED_MATLAB_VERSIONS):
                if preferred.upper() in name:
                    return (0, -i)  # 优先级越高，i 越小，-i 越大
            # 未知版本排在最后
            match = re.search(r"R(\d{4})([AB])", name)
            if match:
                year = int(match.group(1))
                half = 1 if match.group(2).upper() == "B" else 0
                return (1, year * 10 + half)
            return (2, 0)

        return sorted(paths, key=version_key, reverse=True)
