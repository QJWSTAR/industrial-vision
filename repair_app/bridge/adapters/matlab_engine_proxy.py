"""bridge.adapters.matlab_engine_proxy — MATLAB 引擎代理

封装 matlab.engine，提供与 MatlabAdapter._algorithm_fn 兼容的调用接口。

连接策略（按优先级）：
1. 若运行在 MATLAB pyenv 内（CSAM_BRIDGE_IN_MATLAB=1），依次尝试：
   a. connect_matlab() 无参数 — 连接当前宿主会话（最轻量）
   b. connect_matlab(sharedName) — 按名称连接共享会话
   c. start_matlab(background=True) — 启动后台引擎（最重，作为兜底）
2. 外部模式：find_matlab + connect_matlab(name) 发现并连接共享会话
3. 连接默认共享会话（connect_matlab() 无参数）
4. 独立启动新引擎（仅强制 matlab 模式，耗时 30-60s）
5. 全部失败则抛出异常，由上层降级到 Python 算法

数据流：
  Python (xyz ndarray + meta dict)
    → 写临时 STL 文件
    → eng.run_path_planning(stl_path, params)  [MATLAB 内存执行]
    → 返回 (pointlist M×6, feed_rates M×1, layer_indices M×1)
    → 组装为 (M, 8) waypoints ndarray
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import tempfile
import threading
import time
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("csam.bridge.matlab_engine")

# 共享会话名称（与 matlab_bridge_server.m 中的 shareEngine 一致）
DEFAULT_SHARED_NAME = "matlab_bridge"


def _safe_float(raw: dict, key: str, default: float) -> float:
    """安全读取浮点数，避免 `or` 短路覆盖合法 0.0 值。

    `float(raw.get(k, d) or d)` 当值为 0.0 时会被默认值覆盖（0.0 是 falsy）。
    本函数仅在 key 缺失或值为 None 时使用 default，保留合法的 0.0。
    """
    val = raw.get(key, default)
    return float(val) if val is not None else float(default)


def _safe_int(raw: dict, key: str, default: int) -> int:
    """安全读取整数，避免 `or` 短路覆盖合法 0 值。"""
    val = raw.get(key, default)
    return int(val) if val is not None else int(default)


class MatlabEngineProxy:
    """matlab.engine 单例封装，符合 _algorithm_fn 签名。

    用法：
        proxy = MatlabEngineProxy()
        waypoints = proxy(xyz, meta)  # 等价于 _algorithm_fn(xyz, meta)
    """

    _instance: Optional["MatlabEngineProxy"] = None
    _eng = None
    # RLock（可重入）：reset_singleton() 在持有锁时调用 disconnect()，
    # disconnect() 也需获取同一把锁。Lock() 不可重入会死锁，RLock() 允许同线程重入。
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(
        self,
        shared_name: str = DEFAULT_SHARED_NAME,
        algo_dir: Optional[str] = None,
        call_timeout_s: float = 60.0,
        connect_retry: int = 3,
        connect_interval_s: float = 2.0,
        pipeline_timeout_s: float = 180.0,
    ) -> None:
        # __init__ 可能因单例被多次调用，只初始化一次
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._shared_name = shared_name or os.environ.get(
            "CSAM_MATLAB_SHARED_NAME", DEFAULT_SHARED_NAME
        )
        self._algo_dir = algo_dir or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "path_planning"
        )
        self._algo_dir = os.path.abspath(self._algo_dir)
        self._call_timeout = call_timeout_s
        # P1-11: 完整管线（路径规划+形貌预测）耗时远超单次调用，
        # 分离 pipeline_timeout_s 避免真实工作负载误判超时
        self._pipeline_timeout = pipeline_timeout_s
        self._connect_retry = connect_retry
        self._connect_interval = connect_interval_s
        self._connected = False
        self._started_independently = False
        self._unhealthy = False  # True after timeout/error, requires recovery

    # ================================================================
    # 引擎连接
    # ================================================================

    def _is_running_in_matlab(self) -> bool:
        """检测当前 Python 是否运行在 MATLAB pyenv 宿主内。

        判据：
        1. 环境变量 CSAM_BRIDGE_IN_MATLAB=1（由 matlab_bridge_server.m 显式设置）
        2. 或 MATLAB 自身的 __pyenv__ 标记存在
        """
        if os.environ.get("CSAM_BRIDGE_IN_MATLAB", "0") == "1":
            return True
        # MATLAB pyenv 会在 sys.modules 注入 matlab 内置模块的标记
        # 但更可靠的是显式环境变量
        return False

    def _ensure_connected(self) -> None:
        """连接到 MATLAB 引擎。

        策略优先级：
        1. pyenv 宿主模式（Python 运行在 MATLAB 进程内）：
           a. connect_matlab() 无参数 — 连接当前宿主会话
           b. connect_matlab(sharedName) — 按名称连接
           c. start_matlab(background=True) — 后台新引擎（兜底）
        2. 外部模式：find_matlab + connect_matlab(name)
        3. 默认共享会话：connect_matlab() 无参数
        4. 独立启动：start_matlab()（仅强制模式）
        """
        if self._connected and self._eng is not None:
            return

        with self._lock:
            if self._connected and self._eng is not None:
                return

            import matlab.engine as me

            last_err: Optional[Exception] = None

            # ---- 策略 1：pyenv 宿主模式 ----
            # Python 运行在 MATLAB 进程内（matlab_bridge_server.m 通过 pyenv 调用）。
            # 依次尝试 connect_matlab() → connect_matlab(name) → start_matlab(background)
            if self._is_running_in_matlab():
                # 1a. 无参数 connect_matlab：连接当前宿主会话
                try:
                    logger.info("pyenv 宿主模式：尝试连接当前 MATLAB 会话")
                    self._eng = me.connect_matlab()
                    self._connected = True
                    logger.info("已连接当前 MATLAB 会话（pyenv 模式）")
                except Exception as exc:
                    last_err = exc
                    logger.debug("pyenv connect_matlab() 失败: %s", exc)

                # 1b. 按名称连接共享会话
                if not self._connected:
                    try:
                        logger.info(
                            "pyenv 宿主模式：尝试连接共享会话 '%s'",
                            self._shared_name,
                        )
                        self._eng = me.connect_matlab(self._shared_name)
                        self._connected = True
                        logger.info("已连接共享 MATLAB 会话（pyenv 模式）")
                    except Exception as exc:
                        last_err = exc
                        logger.debug(
                            "pyenv connect_matlab('%s') 失败: %s",
                            self._shared_name, exc,
                        )

                # 1c. 兜底：启动后台引擎
                if not self._connected:
                    try:
                        logger.info("pyenv 宿主模式：启动后台 MATLAB 引擎会话")
                        future = me.start_matlab(background=True)
                        # start_matlab(background=True) 返回 FutureResult，
                        # 需调用 .result() 阻塞等待引擎就绪
                        if hasattr(future, 'result') and not hasattr(future, 'addpath'):
                            try:
                                self._eng = future.result(timeout=self._call_timeout)
                            except Exception as fut_exc:
                                last_err = fut_exc
                                logger.error(
                                    "start_matlab 超时或失败 (%ds): %s",
                                    self._call_timeout, fut_exc,
                                )
                                raise
                        else:
                            self._eng = future
                        self._connected = True
                        self._started_independently = True
                        logger.info("已连接后台 MATLAB 引擎（pyenv 模式）")
                    except Exception as exc:
                        last_err = exc
                        logger.warning("pyenv 后台引擎启动失败: %s", exc)

            # ---- 策略 2：外部模式，按名称查找共享会话 ----
            if not self._connected:
                for attempt in range(1, self._connect_retry + 1):
                    try:
                        sessions = me.find_matlab()
                        if self._shared_name in sessions:
                            logger.info(
                                "连接共享 MATLAB 会话 '%s' (尝试 %d/%d)",
                                self._shared_name, attempt, self._connect_retry,
                            )
                            self._eng = me.connect_matlab(self._shared_name)
                            self._connected = True
                            logger.info("已连接共享 MATLAB 会话")
                            break
                        else:
                            logger.debug(
                                "未找到共享会话 '%s'，可用: %s",
                                self._shared_name, sessions,
                            )
                    except Exception as exc:
                        last_err = exc
                        logger.warning(
                            "连接共享会话失败 (尝试 %d/%d): %s",
                            attempt, self._connect_retry, exc,
                        )

                    if attempt < self._connect_retry:
                        time.sleep(self._connect_interval)

            # ---- 策略 3：连接默认共享会话（无名称）----
            if not self._connected:
                try:
                    logger.info("尝试连接默认 MATLAB 会话")
                    self._eng = me.connect_matlab()
                    self._connected = True
                    logger.info("已连接默认 MATLAB 会话")
                except Exception as exc:
                    last_err = exc
                    logger.warning("连接默认会话失败: %s", exc)

            # ---- 策略 4：独立启动新引擎（仅强制 matlab 模式）----
            engine_mode = os.environ.get("CSAM_ALGORITHM_ENGINE", "auto").lower()
            allow_standalone = engine_mode == "matlab" or os.environ.get(
                "CSAM_MATLAB_ALLOW_STANDALONE", "0"
            ) == "1"
            if not self._connected and allow_standalone:
                try:
                    logger.info("尝试独立启动 MATLAB 引擎（可能需要 30-60s）")
                    self._eng = me.start_matlab()
                    self._connected = True
                    self._started_independently = True
                    logger.info("MATLAB 引擎已独立启动")
                except Exception as exc:
                    last_err = exc
                    logger.error("MATLAB 引擎启动失败: %s", exc)
                    # P3-3: 使用 EngineUnavailableError 替代 RuntimeError，保持异常层次一致
                    from repair_app.bridge.communication.exceptions import EngineUnavailableError
                    raise EngineUnavailableError(
                        f"无法连接 MATLAB 引擎: {last_err}"
                    ) from last_err

            if not self._connected:
                # P3-3: 使用 EngineUnavailableError 替代 RuntimeError
                from repair_app.bridge.communication.exceptions import EngineUnavailableError
                raise EngineUnavailableError(
                    f"无可用 MATLAB 会话（auto 模式跳过独立启动）: {last_err}"
                )

            # 添加算法路径（仅独立启动时需要；共享/pyenv 会话由 matlab_bridge_server.m 已 addpath）
            if self._started_independently and self._algo_dir and os.path.isdir(self._algo_dir):
                try:
                    self._eng.addpath(self._algo_dir, nargout=0)
                    logger.debug("addpath: %s", self._algo_dir)
                except Exception as exc:
                    logger.warning("addpath 失败（共享会话应已预加载）: %s", exc)

    @property
    def is_healthy(self) -> bool:
        """引擎是否健康（非 unhealthy 状态）。"""
        with self._lock:
            return self._connected and not self._unhealthy

    def _check_healthy(self) -> None:
        """检查引擎健康状态，不健康时拒绝请求。"""
        with self._lock:
            if self._unhealthy:
                from repair_app.bridge.communication.exceptions import MatlabEngineUnhealthyError
                raise MatlabEngineUnhealthyError(
                    "MATLAB 引擎因超时进入不健康状态，需要恢复",
                    reason="previous call timed out",
                )

    def disconnect(self) -> None:
        """断开 MATLAB 引擎连接，释放资源。

        用于 Bridge 关闭时清理单例状态，避免下次启动残留旧连接。

        P1-8: 独立引擎的 quit() 可能永久阻塞（MATLAB 内部死锁），
        用线程池加 10s 超时保护，超时后强制置 None 释放引用，
        避免持有 RLock 导致整个 Bridge 死锁。
        """
        with self._lock:
            if self._eng is not None:
                eng = self._eng
                started_indep = self._started_independently
                # 先重置状态，即使 quit() 阻塞也不影响后续连接
                self._eng = None
                self._connected = False
                self._started_independently = False

                if not started_indep:
                    # 共享/pyenv 会话不退出 MATLAB 本身，仅释放引用
                    logger.info("已释放 MATLAB 会话引用")
                    return

                # 独立引擎：quit() 可能阻塞，用线程池+超时保护
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(eng.quit)
                        try:
                            future.result(timeout=10.0)
                            logger.info("独立启动的 MATLAB 引擎已退出")
                        except concurrent.futures.TimeoutError:
                            logger.warning(
                                "MATLAB eng.quit() 10s 未返回，强制释放引用"
                                "（MATLAB 进程可能残留，由 launcher.stop 清理）"
                            )
                        except Exception as exc:
                            logger.warning("MATLAB eng.quit() 异常: %s", exc)
                except Exception as exc:
                    logger.warning("断开 MATLAB 引擎时异常: %s", exc)

    def recover(self) -> bool:
        """尝试从不健康状态恢复。

        Returns:
            True if recovery successful (engine is healthy again).
            False if recovery failed (engine remains unhealthy). 调用方据此决定
            是否降级或抛异常，本方法不主动抛出，遵守 `-> bool` 返回契约（P0-7）。
        """
        with self._lock:
            if not self._unhealthy:
                return True
            # 在同一锁内完成状态重置，避免竞态窗口
            self._unhealthy = False
            self._connected = False
            self._eng = None
            self._started_independently = False  # 重置标志，避免 disconnect() 误 quit 共享会话

        logger.info("尝试恢复 MATLAB 引擎...")
        try:
            self._ensure_connected()
            with self._lock:
                if self._connected and self._eng is not None:
                    self._unhealthy = False
                    logger.info("MATLAB 引擎恢复成功")
                    return True
                else:
                    self._unhealthy = True
        except Exception as exc:
            logger.error("MATLAB 引擎恢复失败: %s", exc)
            with self._lock:
                self._unhealthy = True
                self._connected = False
                self._eng = None

        # P0-7: 返回 False 而非抛异常，遵守返回契约。调用方（matlab_adapter）
        # 已用 try/except 包裹 recover() 调用，可根据返回值决定降级策略。
        return False

    @classmethod
    def reset_singleton(cls) -> None:
        """重置单例实例（用于 Bridge 重启场景）。"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.disconnect()
            cls._instance = None

    # ================================================================
    # 超时保护调用
    # ================================================================

    def _call_with_timeout(self, func_name: str, *args, **kwargs) -> Any:
        """使用 background=True + timeout 调用 MATLAB 函数。

        Args:
            func_name: MATLAB 函数名（用于日志）
            *args, **kwargs: 传递给 eng.func_name() 的参数（不含 nargout/background）

        Returns:
            MATLAB 函数返回值（Future.result()）

        Raises:
            MatlabCallTimeoutError: 超时
            MatlabEngineUnhealthyError: 引擎不健康
            EngineUnavailableError: 引擎不可用
        """
        from repair_app.bridge.communication.exceptions import (
            MatlabCallTimeoutError,
            MatlabEngineUnhealthyError,
        )

        self._check_healthy()
        self._ensure_connected()

        # 在锁内获取函数引用，防止 disconnect() 将 _eng 置 None 后 getattr 崩溃
        with self._lock:
            if self._eng is None:
                from repair_app.bridge.communication.exceptions import EngineUnavailableError
                raise EngineUnavailableError("MATLAB 引擎在调用前被断开")
            func = getattr(self._eng, func_name)

        try:
            # background=True 返回 FutureResult
            future = func(*args, **kwargs, background=True)

            # 等待结果（带超时）
            result = future.result(timeout=self._call_timeout)

            return result
        except concurrent.futures.TimeoutError:
            # 超时：标记引擎不健康，尝试取消 MATLAB 计算，然后断开连接
            with self._lock:
                self._unhealthy = True
            logger.error(
                "MATLAB %s 超时 (%.1fs)，引擎进入不健康状态",
                func_name, self._call_timeout,
            )
            # best-effort：注入 error 中断 MATLAB 端正在执行的计算（P0-8）。
            # drawnow 只刷新图窗无法打断计算；error('csam_cancelled') 会抛出
            # MATLAB 异常中止当前 feval，释放共享会话供下次调用使用。
            # 用 background=True 避免本线程再次阻塞；失败仅记日志。
            try:
                eng = self._eng
                if eng is not None:
                    eng.eval(
                        "error('csam_cancelled:MATLAB timeout interrupted');",
                        nargout=0, background=True,
                    )
            except Exception as cancel_exc:
                logger.debug("注入取消 error 失败（best-effort）: %s", cancel_exc)
            try:
                self.disconnect()
            except Exception as disc_exc:
                # P1-12: 不再静默吞没，至少记日志便于诊断状态不一致
                logger.warning("超时清理中断开连接失败: %s", disc_exc)
            raise MatlabCallTimeoutError(
                f"MATLAB {func_name} 超时 ({self._call_timeout}s)",
                timeout_s=self._call_timeout,
            )
        except (MatlabEngineUnhealthyError, MatlabCallTimeoutError):
            raise
        except Exception as exc:
            # P1-14: 用具体异常类型判定引擎连接丢失，避免字符串匹配跨版本不可靠。
            # matlab.engine.EngineError / EngineConnectionError 在不同版本名称不一，
            # 因此捕获连接类异常（ConnectionError/BrokenPipeError/OSError）+ EngineError。
            is_engine_error = False
            try:
                import matlab.engine as _me
                if isinstance(exc, _me.EngineError):
                    is_engine_error = True
            except Exception:
                pass
            if (
                is_engine_error
                or isinstance(exc, (ConnectionError, BrokenPipeError, OSError))
            ):
                with self._lock:
                    self._unhealthy = True
                try:
                    self.disconnect()
                except Exception as disc_exc:
                    # P1-12: 不静默吞没，记日志便于诊断
                    logger.warning("异常清理中断开连接失败: %s", disc_exc)
                from repair_app.bridge.communication.exceptions import EngineUnavailableError
                raise EngineUnavailableError(f"MATLAB 引擎连接丢失: {exc}") from exc
            raise

    # ================================================================
    # _algorithm_fn 签名实现
    # ================================================================

    def __call__(self, xyz: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
        """符合 _algorithm_fn 签名：xyz + meta → waypoints(M,8)。

        流程：
        1. 将点云写为临时 STL 文件
        2. 构造 MATLAB params struct
        3. 调用 eng.run_path_planning(stl_path, params)
        4. 将返回值组装为 (M, 8) ndarray
        """
        self._check_healthy()

        stl_path = self._write_xyz_as_stl(xyz)
        params = self._meta_to_matlab_struct(meta)

        try:
            result = self._call_with_timeout(
                "run_path_planning",
                stl_path, params, nargout=4,
            )
            pointlist, feed_rates, layer_indices, meta_out = result
            waypoints = self._assemble_waypoints(
                pointlist, feed_rates, layer_indices
            )
            compute_time = 0.0
            try:
                compute_time = float(meta_out.get("compute_time_s", 0)) if isinstance(meta_out, dict) else 0.0
            except Exception:
                pass
            logger.info(
                "MATLAB 路径规划完成: %d 航点, 耗时 %.2fs",
                len(waypoints), compute_time,
            )
            return waypoints
        finally:
            # 清理临时 STL
            try:
                os.remove(stl_path)
            except OSError:
                pass

    # ================================================================
    # 形貌预测（run_profile_prediction）
    # ================================================================

    def call_profile_prediction(
        self, xyz: np.ndarray, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """调用 MATLAB run_profile_prediction，返回形貌预测完整结果。

        流程：
        1. 将点云写为临时 STL 文件
        2. 构造 MATLAB params struct
        3. 调用 eng.run_profile_prediction(stl_path, excel_path, params)
        4. 将返回的 struct 解析为 Python dict（含 mesh、layer_profiles、
           particle_distribution、uniformity、estimated_mass_g、estimated_time_s、
           warnings）
        """
        self._check_healthy()

        stl_path = self._write_xyz_as_stl(xyz)
        params = self._meta_to_profile_params(meta)
        # CFD Excel 路径：优先用 meta 中的 cfd_excel_path，否则传空让 MATLAB 自动查找
        excel_path = str(meta.get("cfd_excel_path", ""))

        try:
            raw = self._call_with_timeout(
                "run_profile_prediction",
                stl_path, excel_path, params, nargout=1,
            )
            result = self._parse_profile_result(raw)
            logger.info(
                "MATLAB 形貌预测完成: mesh=%d 三角形, 航点=%d, 耗时 %.2fs",
                len(result.get("mesh", [])),
                result.get("waypoint_count", 0),
                result.get("compute_time_s", 0.0),
            )
            return result
        finally:
            try:
                os.remove(stl_path)
            except OSError:
                pass

    def call_full_pipeline(
        self, xyz: np.ndarray, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """调用 MATLAB 完整管线：路径规划 → 形貌预测（一次 STL 读取，无重复计算）。

        流程：
        1. 将点云写为临时 STL 文件
        2. 构造 MATLAB params struct
        3. 调用 eng.run_path_planning(stl_path, params) → 获取 pointlist/velocitylist
        4. 调用 eng.run_profile_prediction(stl_path, excel_path, params, pointlist, velocitylist)
           → 传入预计算航点，跳过内部重复路径规划
        5. 返回 dict 含 waypoints + 形貌预测结果

        相比分别调用 __call__ + call_profile_prediction：
        - 避免重复写 STL 文件（1 次而非 2 次）
        - 避免重复调用 run_path_planning（1 次而非 2 次）
        - 计算时间减少 30-50%

        P1-11: 完整管线两阶段合计耗时远超单次调用 60s 默认超时，
        临时切换为 pipeline_timeout（默认 180s），避免真实工作负载误判超时。
        """
        self._check_healthy()

        stl_path = self._write_xyz_as_stl(xyz)
        params = self._meta_to_profile_params(meta)
        # P1-16: str(None) 会得到 "None"，用 `or ""` 避免 None 污染
        excel_path = str(meta.get("cfd_excel_path") or "")

        # P1-11: 保存原始超时，完整管线期间切换为 pipeline_timeout
        original_timeout = self._call_timeout
        self._call_timeout = self._pipeline_timeout
        try:
            # ---- 阶段 1：路径规划 ----
            logger.info("MATLABPipeline 阶段 1/2：路径规划")
            pp_result = self._call_with_timeout(
                "run_path_planning",
                stl_path, params, nargout=4,
            )
            pointlist, feed_rates, layer_indices, meta_out = pp_result
            waypoints = self._assemble_waypoints(
                pointlist, feed_rates, layer_indices
            )
            # 构造 velocitylist（MATLAB string 数组）
            velocitylist = self._feed_rates_to_velocitylist(
                feed_rates, float(meta.get("traversing_speed_mms", 500.0))
            )
            pp_time = 0.0
            try:
                pp_time = float(meta_out.get("compute_time_s", 0)) if isinstance(meta_out, dict) else 0.0
            except Exception:
                pass
            logger.info(
                "MATLABPipeline 路径规划完成: %d 航点, 耗时 %.2fs",
                len(waypoints), pp_time,
            )

            # ---- 阶段 2：形貌预测（传入预计算航点） ----
            logger.info("MATLABPipeline 阶段 2/2：形貌预测（使用预计算航点）")
            raw = self._call_with_timeout(
                "run_profile_prediction",
                stl_path, excel_path, params, pointlist, velocitylist, nargout=1,
            )
            result = self._parse_profile_result(raw)
            result["waypoints"] = waypoints
            result["layer_indices"] = np.asarray(layer_indices, dtype=np.int32)
            logger.info(
                "MATLABPipeline 形貌预测完成: mesh=%d 三角形, 航点=%d, 总耗时 %.2fs",
                len(result.get("mesh", [])),
                len(waypoints),
                result.get("compute_time_s", 0.0),
            )
            return result
        finally:
            # 恢复原始超时
            self._call_timeout = original_timeout
            try:
                os.remove(stl_path)
            except OSError:
                pass

    @staticmethod
    def _feed_rates_to_velocitylist(feed_rates, default_speed: float):
        """将数值进给速度转为 MATLAB velocitylist string 数组。

        与 run_path_planning.m 中 velocity_to_numeric 互逆。
        feed_rates 可能是 matlab.double、list 或 np.ndarray，
        统一转为 np.float64 数组再做算术比较。
        """
        import matlab

        # 统一转为 numpy 数组，消除 matlab.double / list / ndarray 的类型差异
        arr = np.asarray(feed_rates, dtype=np.float64).ravel()
        # 某些 matlab.engine 版本中 asarray 会创建 object dtype 数组，
        # 元素仍为 matlab.double 标量，无法直接参与算术运算。
        # 检测到 object dtype 时回退到逐元素 float() 转换。
        if arr.dtype == object:
            flat = []
            for item in feed_rates:
                if hasattr(item, '__iter__'):
                    flat.extend(float(x) for x in item)
                else:
                    flat.append(float(item))
            arr = np.array(flat, dtype=np.float64).ravel()
        n = len(arr)
        if n == 0:
            return matlab.string_array([])
        strings = []
        for fr in arr:
            fr_val = float(fr)
            if abs(fr_val - default_speed * 0.6) < 1e-3:
                strings.append("velocity_edge")
            elif abs(fr_val - default_speed * 1.2) < 1e-3:
                strings.append("velocity_link")
            else:
                strings.append("velocity_infill")
        return matlab.string_array(strings)

    def _meta_to_profile_params(self, meta: dict[str, Any]) -> dict:
        """将 Python meta dict 转为 MATLAB run_profile_prediction 兼容的 struct dict。"""
        def safe_float(val, default):
            try:
                return float(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        # 路径规划相关参数复用 _meta_to_matlab_struct 的映射
        base = self._meta_to_matlab_struct(meta)

        # 形貌预测特有参数
        base["standoff_distance_mm"] = safe_float(
            meta.get("standoff_distance_mm"), 30.0
        )
        base["spot_step_size_mm"] = safe_float(
            meta.get("spot_step_size_mm"),
            safe_float(meta.get("scanning_step_mm"), 2.0),
        )
        base["subdivide_max_edge"] = safe_float(
            meta.get("subdivide_max_edge"), 5.0
        )
        base["improve_short_edge"] = safe_float(
            meta.get("improve_short_edge"), 1.5
        )
        base["octree_max_depth"] = safe_float(
            meta.get("octree_max_depth"), 6.0
        )
        base["octree_max_tris"] = safe_float(
            meta.get("octree_max_tris"), 8.0
        )
        base["nozzle_diameter_mm"] = safe_float(
            meta.get("nozzle_diameter_mm"), 6.0
        )
        base["material_density_gcm3"] = safe_float(
            meta.get("material_density_gcm3"), 7.99
        )
        base["particle_velocity_ms"] = safe_float(
            meta.get("particle_velocity_ms"), 500.0
        )
        base["critical_velocity_ms"] = safe_float(
            meta.get("critical_velocity_ms"), 400.0
        )
        base["particle_size_um"] = safe_float(
            meta.get("particle_size_um"), 25.0
        )
        base["num_layers"] = safe_float(
            meta.get("num_layers"), 3.0
        )
        base["preview_fps"] = safe_float(
            meta.get("preview_fps"), 8.0
        )
        base["preview_max_triangles"] = safe_float(
            meta.get("preview_max_triangles"), 1500.0
        )
        # request_id 用于 MATLAB 进度发布（ProgressPublisher）
        # P1-16: meta.get("request_id") 可能显式为 None，str(None)="None" 会污染 operation_id
        base["request_id"] = str(meta.get("request_id") or "")
        return base

    @staticmethod
    def _parse_profile_result(raw: Any) -> dict[str, Any]:
        """将 MATLAB 返回的 struct（Python dict）解析为标准化 dict。

        处理 matlab.double → numpy.ndarray 转换，处理空数组与嵌套 struct。
        """
        def to_np(val) -> np.ndarray:
            if val is None:
                return np.zeros((0,), dtype=np.float32)
            arr = np.asarray(val, dtype=np.float64)
            # 处理 object dtype（matlab.double 标量未被自动转换）
            if arr.dtype == object:
                flat = []
                for item in val:
                    if hasattr(item, '__iter__'):
                        flat.extend(float(x) for x in item)
                    else:
                        flat.append(float(item))
                arr = np.array(flat, dtype=np.float64)
            return arr.astype(np.float32)

        def to_list(val) -> list:
            if val is None:
                return []
            if isinstance(val, (list, tuple)):
                return [str(v) for v in val]
            return [str(val)]

        result: dict[str, Any] = {
            "mesh": to_np(raw.get("mesh", [])),
            "substrate_triangles": to_np(raw.get("substrate_triangles", [])),
            "layer_profiles": to_np(raw.get("layer_profiles", [])),
            "uniformity": _safe_float(raw, "uniformity", 0.78),
            "estimated_mass_g": _safe_float(raw, "estimated_mass_g", 0.0),
            "estimated_time_s": _safe_float(raw, "estimated_time_s", 0.0),
            "predicted_volume_mm3": _safe_float(raw, "predicted_volume_mm3", 0.0),
            "compute_time_s": _safe_float(raw, "compute_time_s", 0.0),
            "waypoint_count": _safe_int(raw, "waypoint_count", 0),
            "warnings": to_list(raw.get("warnings", [])),
        }

        # 解析嵌套的 particle_distribution struct
        pd_raw = raw.get("particle_distribution", None)
        if pd_raw is not None:
            result["particle_distribution"] = {
                "px": to_np(pd_raw.get("px", [])),
                "py": to_np(pd_raw.get("py", [])),
                "vx": to_np(pd_raw.get("vx", [])),
                "vy": to_np(pd_raw.get("vy", [])),
                "vz": to_np(pd_raw.get("vz", [])),
                "vcr": to_np(pd_raw.get("vcr", [])),
                "dep_efficiency": _safe_float(pd_raw, "dep_efficiency", 0.0),
                "diameter": to_np(pd_raw.get("diameter", [])),
                "temperature": to_np(pd_raw.get("temperature", [])),
            }
        else:
            result["particle_distribution"] = None

        # 将 mesh（N×9）转为二进制 STL bytes
        mesh = result["mesh"]
        if mesh.ndim == 2 and mesh.shape[1] == 9 and len(mesh) > 0:
            result["mesh_stl_bytes"] = _triangles_to_binary_stl(mesh)
        else:
            result["mesh_stl_bytes"] = b""

        return result

    # ================================================================
    # 数据转换
    # ================================================================

    @staticmethod
    def _write_xyz_as_stl(xyz: np.ndarray) -> str:
        """将点云写为 ASCII STL 文件（轻量 I/O，非算法）。

        使用 Delaunay 三角化生成网格，写入临时 STL。
        """
        from scipy.spatial import Delaunay

        xyz = np.asarray(xyz, dtype=np.float64)
        if len(xyz) < 3:
            raise ValueError(f"点云太少，无法三角化: {len(xyz)} 点")

        # XY 平面 Delaunay 三角化
        pts2d = xyz[:, :2]
        tri = Delaunay(pts2d)
        triangles = tri.simplices  # (N, 3) 顶点索引

        # 计算法向量
        v1 = xyz[triangles[:, 1]] - xyz[triangles[:, 0]]
        v2 = xyz[triangles[:, 2]] - xyz[triangles[:, 0]]
        normals = np.cross(v1, v2)
        norm_len = np.linalg.norm(normals, axis=1, keepdims=True)
        norm_len[norm_len < 1e-12] = 1e-12
        normals = normals / norm_len

        # 写 ASCII STL
        fd, stl_path = tempfile.mkstemp(suffix=".stl", prefix="csam_cloud_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("solid csam_substrate\n")
                for i in range(len(triangles)):
                    n = normals[i]
                    p0, p1, p2 = xyz[triangles[i, 0]], xyz[triangles[i, 1]], xyz[triangles[i, 2]]
                    f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
                    f.write("    outer loop\n")
                    f.write(f"      vertex {p0[0]:.6e} {p0[1]:.6e} {p0[2]:.6e}\n")
                    f.write(f"      vertex {p1[0]:.6e} {p1[1]:.6e} {p1[2]:.6e}\n")
                    f.write(f"      vertex {p2[0]:.6e} {p2[1]:.6e} {p2[2]:.6e}\n")
                    f.write("    endloop\n")
                    f.write("  endfacet\n")
                f.write("endsolid csam_substrate\n")
        except Exception:
            os.remove(stl_path)
            raise

        return stl_path

    def _meta_to_matlab_struct(self, meta: dict[str, Any]) -> dict:
        """将 Python meta dict 转为 MATLAB struct 兼容的 dict。

        matlab.engine 会自动将 Python dict 转为 MATLAB struct。
        所有值必须是 float（MATLAB double 兼容）。
        """
        def safe_float(val, default):
            try:
                return float(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        return {
            "base_plane": safe_float(meta.get("base_plane_mm"), 5.0),
            "layer_height": safe_float(meta.get("layer_height_mm"), 2.0),
            "buffer_additive": safe_float(meta.get("buffer_additive_mm"), 2.0),
            "buffer_repairing": safe_float(meta.get("buffer_repairing_mm"), 0.0),
            "scanning_angle": safe_float(meta.get("scanning_angle_deg"), -45.0),
            "scanning_step": safe_float(meta.get("scanning_step_mm"), 2.0),
            "edge_step_size": safe_float(meta.get("edge_step_size_mm"), 2.0),
            "tilt_angle": safe_float(meta.get("tilt_angle_deg"), 60.0),
            "link_path_free_dist": safe_float(meta.get("link_path_free_dist_mm"), 20.0),
            "resolution": safe_float(meta.get("obstacle_resolution_mm"), 2.0),
            "traversing_speed_mms": safe_float(meta.get("traversing_speed_mms"), 500.0),
            # P1-16: 避免 str(None)="None" 污染 operation_id
            "request_id": str(meta.get("request_id") or ""),
        }

    @staticmethod
    def _assemble_waypoints(
        pointlist: Any,
        feed_rates: Any,
        layer_indices: Any,
    ) -> np.ndarray:
        """将 MATLAB 返回的数组组装为 (M, 8) waypoints ndarray。

        pointlist: matlab.double (M×6) [x, y, z, nx, ny, nz]
        feed_rates: matlab.double (M×1)
        layer_indices: matlab.double (M×1)
        """
        def _to_float_array(val):
            arr = np.asarray(val, dtype=np.float32)
            if arr.dtype == object:
                # matlab.double 标量元素未被自动转换，手动展开
                flat = []
                for item in val:
                    if hasattr(item, '__iter__'):
                        flat.extend(float(x) for x in item)
                    else:
                        flat.append(float(item))
                arr = np.array(flat, dtype=np.float32)
            return arr

        pts = _to_float_array(pointlist)
        feeds = _to_float_array(feed_rates).ravel()
        layers = _to_float_array(layer_indices).ravel()

        # 空数组快速返回 (0, 8)，避免 reshape 产生错误形状
        if pts.size == 0:
            return np.zeros((0, 8), dtype=np.float32)

        # 统一为 2D (M, 6)
        if pts.ndim == 1:
            # 1D 数组：重塑为 (M, 6)
            if pts.size % 6 != 0:
                pts = pts.reshape(-1, 3)
                pts = np.hstack([pts, np.zeros((pts.shape[0], 3), dtype=np.float32)])
            else:
                pts = pts.reshape(-1, 6)
        # matlab.double 列优先可能导致 (6, M) 而非 (M, 6)，需要转置
        if pts.shape[0] == 6 and pts.shape[1] != 6:
            pts = pts.T

        M = pts.shape[0]
        feeds = feeds[:M].reshape(-1, 1) if feeds.size >= M else np.zeros((M, 1), dtype=np.float32)
        layers = layers[:M].reshape(-1, 1) if layers.size >= M else np.zeros((M, 1), dtype=np.float32)

        # 组装 (M, 8): x, y, z, nx, ny, nz, feed_rate, layer_index
        waypoints = np.hstack([pts, feeds, layers])
        return waypoints.astype(np.float32)

    # ================================================================
    # 生命周期
    # ================================================================
    # shutdown() 实例方法已移除：生产路径统一使用 reset_singleton()，
    # 后者已通过 cls._lock 保护共享状态。


def _triangles_to_binary_stl(triangles: np.ndarray) -> bytes:
    """将 N×9 三角形矩阵转换为二进制 STL bytes。

    每行格式：[x1,y1,z1, x2,y2,z2, x3,y3,z3]
    输出符合二进制 STL 规范：80 字节头 + 三角面数 + 每面 50 字节。
    """
    import struct

    triangles = np.asarray(triangles, dtype=np.float32)
    if triangles.ndim != 2 or triangles.shape[1] != 9:
        return b""

    n = triangles.shape[0]
    if n == 0:
        return b""

    # 80 字节头 + 4 字节三角形数
    buf = bytearray(b"\x00" * 80)
    buf += struct.pack("<I", n)

    for i in range(n):
        v0 = triangles[i, 0:3]
        v1 = triangles[i, 3:6]
        v2 = triangles[i, 6:9]

        # 计算法向量
        e1 = v1 - v0
        e2 = v2 - v0
        normal = np.cross(e1, e2)
        norm_len = float(np.linalg.norm(normal))
        if norm_len > 1e-12:
            normal = normal / norm_len
        else:
            normal = np.zeros(3, dtype=np.float32)

        # 50 字节：12(法向) + 12*3(三顶点) + 2(属性)
        buf += struct.pack("<3f", float(normal[0]), float(normal[1]), float(normal[2]))
        buf += struct.pack("<3f", float(v0[0]), float(v0[1]), float(v0[2]))
        buf += struct.pack("<3f", float(v1[0]), float(v1[1]), float(v1[2]))
        buf += struct.pack("<3f", float(v2[0]), float(v2[1]), float(v2[2]))
        buf += struct.pack("<H", 0)

    return bytes(buf)
