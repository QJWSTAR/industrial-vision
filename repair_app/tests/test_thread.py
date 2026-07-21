"""test_thread.py — 线程安全与线程生命周期测试

覆盖：
  - QThread 生命周期：正常退出 / 中断请求 / 超时终止
  - WorkerManager 线程管理：多 Worker 并发 / cancel_all / 引用清理
  - RepairSession 线程安全：并发只读 / Worker 读取期间主线程不修改
  - ZMQ 客户端线程（_RequestWorker/_HealthWorker）：启动退出 / 中断响应
  - HeartbeatMonitor：start/stop / 状态变化信号

目标：覆盖 WorkerManager / BaseWorker 线程相关方法 80%+。

运行：pytest -m unit tests/test_thread.py -v
"""
from __future__ import annotations

import gc
import sys
import time
import threading

import numpy as np
import pytest
from PySide6.QtCore import QThread, Signal

from repair_app.core.repair_session import RepairSession
from repair_app.ui.worker_base import BaseWorker, WorkerManager
from repair_app.ui.workers import PathPlanningWorker, MorphologyWorker


# ================================================================
# autouse fixture：提供 qapp。
# 线程安全的日志处理由 conftest.py 的 _disable_loguru_console_sink
# session 级 fixture 统一处理（移除 loguru 默认 stderr sink）。
# ================================================================
@pytest.fixture(autouse=True)
def _flush_qt_events(qapp):
    yield


# ================================================================
# 辅助函数 / 辅助 Worker
# ================================================================
def make_session(n_points: int = 100) -> RepairSession:
    """构造带最小可用数据的 RepairSession（点云 + 选区 + mock 航点）。"""
    session = RepairSession()
    rng = np.random.default_rng(42)
    xy = rng.uniform(-5, 5, (n_points, 2))
    z = rng.uniform(0, 0.5, n_points)
    session.point_cloud.xyz = np.column_stack([xy, z]).astype(np.float32)
    mask = np.zeros(n_points, dtype=bool)
    mask[n_points // 3: 2 * n_points // 3] = True
    session.selection.mask = mask
    session.waypoint.mock = rng.uniform(-3, 3, (max(1, n_points // 10), 3)).astype(np.float32)
    return session


def _start_worker_thread(worker: BaseWorker) -> QThread:
    """创建 QThread，将 worker 移入并连接 started→run，启动后返回 thread。"""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    return thread


def _stop_thread(thread: QThread, wait_ms: int = 3000) -> None:
    """退出并等待线程结束，然后调度删除 C++ 对象。"""
    thread.quit()
    thread.wait(wait_ms)
    thread.deleteLater()


def _wait_for(qapp, results, timeout_s: float = 10.0, interval: float = 0.02) -> bool:
    """主线程轮询处理事件，等待 results 非空。返回是否收到信号。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if results:
            return True
        qapp.processEvents()
        time.sleep(interval)
    return bool(results)


class _QuickWorker(BaseWorker):
    """立即完成的 Worker（发出 done 信号后返回）。"""
    done = Signal()

    def run(self) -> None:
        self._mark_start()
        self.done.emit()


class _LongWorker(BaseWorker):
    """循环运行直到中断的 Worker（用于 cancel / running 状态测试）。"""
    tick = Signal()

    def run(self) -> None:
        self._mark_start()
        while not self.check_interruption():
            self.tick.emit()
            time.sleep(0.02)


class _BlockingPathWorker(PathPlanningWorker):
    """路径规划 Worker 变体：使用阻塞迭代器，用于中断/超时测试。"""
    pass


def _blocking_path_iter(*args, **kwargs):
    """持续 yield 的路径迭代器，用于中断测试。"""
    while True:
        time.sleep(0.02)
        yield np.zeros((2, 3), dtype=np.float32)


def _blocking_morph_iter(*args, **kwargs):
    """持续 yield 的形貌迭代器，用于中断测试。"""
    while True:
        time.sleep(0.02)
        yield np.zeros((4, 3), dtype=np.float32)


def _make_threading_fake_zmq(poll_delay_ms: int = 50):
    """构造用于线程生命周期测试的 fake zmq。

    sock.poll 会阻塞 poll_delay_ms 毫秒后返回 False（模拟无事件超时），
    让 worker 在循环中等待，便于测试 requestInterruption 的响应。
    不使用真实 ZMQ Context，避免后台重连线程干扰后续测试。
    """
    class _FakeSock:
        def setsockopt(self, *a, **kw): pass
        def connect(self, *a, **kw): pass
        def send(self, *a, **kw): pass
        def recv(self): return b""
        def poll(self, ms, kind):
            time.sleep(poll_delay_ms / 1000.0)
            return False
        def close(self, linger=0): pass

    class _FakeCtx:
        @staticmethod
        def instance(): return _FakeCtx()
        def socket(self, kind): return _FakeSock()

    class _FakeZmq:
        Context = _FakeCtx
        REQ = 3
        LINGER = 17
        RCVTIMEO = 18
        SNDTIMEO = 19
        POLLIN = 1

    return _FakeZmq()


# ================================================================
# 1. QThread 生命周期测试
# ================================================================
@pytest.mark.unit
class TestQThreadLifecycle:
    """QThread 启动 / 退出 / 中断 / 终止 生命周期测试。"""

    def test_thread_quit_wait_normal_exit(self, qapp):
        """QThread 启动后通过 quit + wait 正常退出。"""
        thread = QThread()
        thread.start()
        # 等待线程进入运行
        _wait_for(qapp, [thread.isRunning()], timeout_s=2.0)
        assert thread.isRunning() is True

        thread.quit()
        ok = thread.wait(3000)
        assert ok is True, "quit + wait 后线程应正常退出"
        assert thread.isRunning() is False
        thread.deleteLater()

    def test_thread_request_interruption(self, qapp):
        """requestInterruption 后线程能响应中断并退出。"""
        worker = _LongWorker()
        thread = _start_worker_thread(worker)
        ticks = []
        worker.tick.connect(lambda: ticks.append(True))
        # 等待 worker 进入循环
        _wait_for(qapp, ticks, timeout_s=3.0)
        assert thread.isRunning() is True
        assert thread.isInterruptionRequested() is False

        # 请求中断：在请求后立即检查标志位（线程尚未退出时为 True）
        thread.requestInterruption()
        # 退出并等待线程响应中断
        thread.quit()
        ok = thread.wait(5000)
        assert ok is True, "中断请求后线程应退出"
        assert thread.isRunning() is False
        worker.deleteLater()
        thread.deleteLater()

    def test_thread_terminate_timeout(self, qapp):
        """terminate 强制终止线程（用于超时未退出的兜底场景）。"""
        # 构造一个不响应中断的线程：纯 QThread 没有业务逻辑，
        # 但事件循环运行中。terminate 后 isRunning 应为 False。
        thread = QThread()
        thread.start()
        _wait_for(qapp, [thread.isRunning()], timeout_s=2.0)
        assert thread.isRunning() is True

        thread.terminate()
        ok = thread.wait(3000)
        assert ok is True, "terminate 后线程应退出"
        assert thread.isRunning() is False
        thread.deleteLater()

    def test_thread_finished_signal_emitted(self, qapp):
        """线程退出后 finished 信号被发出。"""
        thread = QThread()
        finished = []
        thread.finished.connect(lambda: finished.append(True))
        thread.start()
        _wait_for(qapp, [thread.isRunning()], timeout_s=2.0)
        thread.quit()
        _wait_for(qapp, finished, timeout_s=3.0)
        assert len(finished) == 1, "应发出一次 finished 信号"
        assert thread.isRunning() is False
        thread.deleteLater()

    def test_thread_not_running_before_start(self, qapp):
        """未 start 的线程 isRunning 为 False。"""
        thread = QThread()
        assert thread.isRunning() is False
        assert thread.isInterruptionRequested() is False
        thread.deleteLater()


# ================================================================
# 2. WorkerManager 线程管理测试
# ================================================================
@pytest.mark.unit
class TestWorkerManagerThreading:
    """WorkerManager 多 Worker 并发 / cancel_all / 引用清理 测试。"""

    def test_multiple_workers_concurrent(self, qapp):
        """多个 Worker 并发启动，全部运行。"""
        mgr = WorkerManager()
        workers_threads = []
        for name in ("a", "b", "c"):
            worker = _LongWorker()
            thread = QThread()
            mgr.start(name, worker, thread)
            workers_threads.append((name, thread))

        _wait_for(
            qapp,
            [all(t.isRunning() for _, t in workers_threads)],
            timeout_s=3.0,
        )
        assert mgr.is_any_running() is True
        running = set(mgr.get_running_names())
        assert {"a", "b", "c"}.issubset(running), "三个 worker 应都在运行"

        mgr.cancel_all()
        assert mgr.is_any_running() is False
        for _, thread in workers_threads:
            assert thread.isRunning() is False
        mgr.cleanup_all()

    def test_cancel_all_cleans_all_threads(self, qapp):
        """cancel_all 清理所有线程，使其全部退出。"""
        mgr = WorkerManager()
        threads = []
        for name in ("w1", "w2"):
            worker = _LongWorker()
            thread = QThread()
            mgr.start(name, worker, thread)
            threads.append(thread)

        _wait_for(qapp, [t.isRunning() for t in threads], timeout_s=3.0)
        assert all(t.isRunning() for t in threads)

        mgr.cancel_all()
        assert all(not t.isRunning() for t in threads), "cancel_all 后所有线程应退出"
        assert mgr.get_running_names() == []
        mgr.cleanup_all()

    def test_thread_reference_cleaned_after_exit(self, qapp):
        """线程退出后 _workers 中引用仍存在，但 cleanup_all 后清空。"""
        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()
        done = []
        worker.done.connect(lambda: done.append(True))
        mgr.start("w", worker, thread)
        _wait_for(qapp, done, timeout_s=3.0)
        _stop_thread(thread)

        # 退出后引用仍保留（用于状态查询），但线程已停止
        assert "w" in mgr._workers
        assert thread.isRunning() is False
        # cleanup_all 清空引用
        mgr.cleanup_all()
        assert mgr._workers == {}
        assert "w" not in mgr._workers

    def test_start_replaces_running_worker(self, qapp):
        """同名 worker 运行时 start 会先停止旧 worker。"""
        mgr = WorkerManager()
        long_worker = _LongWorker()
        long_thread = QThread()
        mgr.start("dup", long_worker, long_thread)
        _wait_for(qapp, [long_thread.isRunning()], timeout_s=2.0)
        assert long_thread.isRunning() is True

        new_worker = _QuickWorker()
        new_thread = QThread()
        done = []
        new_worker.done.connect(lambda: done.append(True))
        mgr.start("dup", new_worker, new_thread)
        _wait_for(qapp, done, timeout_s=3.0)
        _stop_thread(new_thread)

        assert done, "新 worker 应执行"
        assert long_thread.isRunning() is False, "旧 worker 应已停止"
        mgr.cleanup_all()

    def test_cancel_unknown_name_noop(self, qapp):
        """cancel 未登记名称不抛异常。"""
        mgr = WorkerManager()
        mgr.cancel("nonexistent")  # 不应抛异常
        assert mgr._workers == {}

    def test_is_any_running_after_all_exit(self, qapp):
        """所有 worker 退出后 is_any_running 为 False。"""
        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()
        done = []
        worker.done.connect(lambda: done.append(True))
        mgr.start("w", worker, thread)
        _wait_for(qapp, done, timeout_s=3.0)
        _stop_thread(thread)
        # worker 已完成，但线程对象还在 _workers 中
        assert mgr.is_any_running() is False
        mgr.cleanup_all()


# ================================================================
# 3. RepairSession 线程安全测试
# ================================================================
@pytest.mark.unit
class TestRepairSessionThreadSafety:
    """RepairSession 多线程并发只读 / Worker 读取期间主线程不修改。"""

    def test_concurrent_read_point_cloud_xyz(self, qapp):
        """多线程并发读取 session.point_cloud.xyz 不出错（ndarray 读操作线程安全）。"""
        session = make_session(n_points=500)
        xyz = session.point_cloud.xyz
        errors: list[Exception] = []
        read_counts = [0] * 4

        def reader(idx: int) -> None:
            try:
                for _ in range(50):
                    arr = session.point_cloud.xyz
                    # 只读操作：求和 / 长度
                    _ = arr.sum()
                    _ = len(arr)
                    read_counts[idx] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"并发读取出现异常: {errors}"
        assert all(c == 50 for c in read_counts), f"读取次数不符: {read_counts}"
        # 数据未被修改
        np.testing.assert_array_equal(session.point_cloud.xyz, xyz)

    def test_concurrent_read_selection_mask(self, qapp):
        """多线程并发读取 session.selection.mask 不出错。"""
        session = make_session(n_points=200)
        mask = session.selection.mask.copy()
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(30):
                    _ = bool(np.sum(session.selection.mask))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"并发读取 mask 出现异常: {errors}"
        np.testing.assert_array_equal(session.selection.mask, mask)

    def test_worker_reads_while_main_holds_reference(self, qapp):
        """Worker 线程读取 session 数据时主线程不修改（共享引用，无 copy）。"""
        session = make_session(n_points=100)
        # 主线程持有原始引用
        xyz_main = session.point_cloud.xyz
        xyz_id_main = id(xyz_main)

        read_results: list[tuple[int, int]] = []  # (length, id)

        class _ReadWorker(BaseWorker):
            """读取 session 数据的 Worker（避免闭包循环引用）。"""
            done = Signal()
            def run(self) -> None:
                self._mark_start()
                arr = session.point_cloud.xyz
                read_results.append((len(arr), id(arr)))
                self.done.emit()

        worker = _ReadWorker()
        worker.done.connect(lambda: None)
        thread = _start_worker_thread(worker)
        _wait_for(qapp, read_results, timeout_s=3.0)
        _stop_thread(thread)
        worker.deleteLater()
        qapp.processEvents()

        assert len(read_results) == 1
        length, arr_id = read_results[0]
        assert length == len(xyz_main)
        # Worker 看到的是同一个 ndarray 对象（无 copy）
        assert arr_id == xyz_id_main, "Worker 应共享同一 ndarray 引用，不应 copy"

    def test_session_summary_thread_safe(self, qapp):
        """session.summary() 只读方法多线程调用安全。"""
        session = make_session(n_points=300)
        errors: list[Exception] = []
        summaries: list[str] = []

        def caller() -> None:
            try:
                for _ in range(20):
                    s = session.summary()
                    summaries.append(s)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=caller) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"并发 summary 出现异常: {errors}"
        assert len(summaries) == 60
        # 所有 summary 应一致
        assert all(s == summaries[0] for s in summaries)


# ================================================================
# 4. ZMQ 客户端线程测试（_RequestWorker / _HealthWorker）
# ================================================================
@pytest.mark.unit
class TestZmqClientThreads:
    """_RequestWorker / _HealthWorker 线程启动 / 退出 / 中断测试。

    使用 fake zmq（不创建真实 ZMQ Context），避免后台重连线程
    干扰后续测试导致偶发卡死。fake sock.poll 阻塞短暂时间后
    返回 False，让 worker 在循环中等待，便于测试中断响应。
    """

    @pytest.fixture(autouse=True)
    def _setup_fake_zmq(self, monkeypatch):
        """注入 fake zmq + mock Serializer，所有测试方法自动生效。"""
        from repair_app.bridge.communication import zmq_client as zc_mod
        monkeypatch.setattr(zc_mod, "_ZMQ_AVAILABLE", True)
        monkeypatch.setattr(zc_mod, "zmq", _make_threading_fake_zmq(poll_delay_ms=50))
        # _HealthWorker.run 需要 Serializer 静态方法
        from repair_app.bridge.communication.serializer import Serializer
        monkeypatch.setattr(Serializer, "build_health_check", staticmethod(lambda: object()))
        monkeypatch.setattr(Serializer, "serialize_health", staticmethod(lambda hb: b"\x00"))
        monkeypatch.setattr(
            Serializer, "parse_health_response",
            staticmethod(lambda r: {"status_code": 0, "status": "OK", "service_version": ""}),
        )

    def _make_config(self):
        """构造测试用 config：极短 poll 间隔 + 较长超时，便于测试中断。"""
        from repair_app.bridge.communication.config import BridgeConfig
        import dataclasses
        return dataclasses.replace(
            BridgeConfig.from_env(),
            request_timeout_ms=10000,
            poll_interval_ms=50,
            health_check_timeout_ms=10000,
            connect_timeout_ms=2000,
        )

    def test_request_worker_start_and_exit(self, qapp):
        """_RequestWorker 启动后能正常退出（quit + wait）。"""
        from repair_app.bridge.communication.zmq_client import _RequestWorker

        config = self._make_config()
        worker = _RequestWorker(
            request_bytes=b"\x00",
            address="tcp://127.0.0.1:1",
            config=config,
            request_id="test-1",
        )
        worker.start()
        _wait_for(qapp, [worker.isRunning()], timeout_s=2.0)
        assert worker.isRunning() is True

        # 请求中断 + 退出（worker 内部 poll 会响应中断）
        worker.requestInterruption()
        worker.quit()
        ok = worker.wait(5000)
        assert ok is True, "_RequestWorker 应在中断后退出"
        assert worker.isRunning() is False
        worker.deleteLater()

    def test_request_worker_interruption_response(self, qapp):
        """_RequestWorker 响应 requestInterruption 并退出。"""
        from repair_app.bridge.communication.zmq_client import _RequestWorker

        config = self._make_config()
        worker = _RequestWorker(
            request_bytes=b"\x00",
            address="tcp://127.0.0.1:1",
            config=config,
            request_id="test-2",
        )
        errors: list[tuple[str, str]] = []
        worker.error_occurred.connect(lambda msg, rid: errors.append((msg, rid)))

        worker.start()
        _wait_for(qapp, [worker.isRunning()], timeout_s=2.0)
        # 请求中断
        worker.requestInterruption()
        ok = worker.wait(5000)
        assert ok is True, "中断后应退出"
        assert worker.isRunning() is False
        worker.deleteLater()

    def test_health_worker_start_and_exit(self, qapp):
        """_HealthWorker 启动后能正常退出。"""
        from repair_app.bridge.communication.zmq_client import _HealthWorker

        config = self._make_config()
        worker = _HealthWorker(
            address="tcp://127.0.0.1:1",
            config=config,
        )
        worker.start()
        _wait_for(qapp, [worker.isRunning()], timeout_s=2.0)
        assert worker.isRunning() is True

        worker.requestInterruption()
        worker.quit()
        ok = worker.wait(5000)
        assert ok is True, "_HealthWorker 应在中断后退出"
        assert worker.isRunning() is False
        worker.deleteLater()

    def test_health_worker_interruption_response(self, qapp):
        """_HealthWorker 响应中断并退出。"""
        from repair_app.bridge.communication.zmq_client import _HealthWorker

        config = self._make_config()
        worker = _HealthWorker(
            address="tcp://127.0.0.1:1",
            config=config,
        )
        results: list[tuple[bool, str, float]] = []
        worker.result_ready.connect(lambda ok, msg, lat: results.append((ok, msg, lat)))

        worker.start()
        _wait_for(qapp, [worker.isRunning()], timeout_s=2.0)
        worker.requestInterruption()
        ok = worker.wait(5000)
        assert ok is True, "中断后应退出"
        assert worker.isRunning() is False
        worker.deleteLater()

    def test_request_worker_finished_signal(self, qapp):
        """_RequestWorker 退出后发出 finished 信号。"""
        from repair_app.bridge.communication.zmq_client import _RequestWorker

        config = self._make_config()
        worker = _RequestWorker(
            request_bytes=b"\x00",
            address="tcp://127.0.0.1:1",
            config=config,
            request_id="test-3",
        )
        finished: list[bool] = []
        worker.finished.connect(lambda: finished.append(True))

        worker.start()
        worker.requestInterruption()
        worker.quit()
        _wait_for(qapp, finished, timeout_s=5.0)
        assert len(finished) == 1, "应发出一次 finished 信号"
        assert worker.isRunning() is False
        worker.deleteLater()


# ================================================================
# 5. 心跳监控线程测试（HeartbeatMonitor）
# ================================================================
@pytest.mark.unit
class TestHeartbeatMonitor:
    """HeartbeatMonitor start / stop / 状态变化信号 测试。"""

    def test_start_and_stop(self, qapp):
        """HeartbeatMonitor start 后 isRunning，stop 后退出。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig

        config = BridgeConfig.from_env()
        monitor = HeartbeatMonitor(
            ping_fn=lambda cb: cb(False, "无引擎"),  # 始终失败
            config=config,
        )
        monitor.start()
        _wait_for(qapp, [monitor.isRunning()], timeout_s=2.0)
        assert monitor.isRunning() is True

        monitor.stop(wait_ms=5000)
        assert monitor.isRunning() is False, "stop 后线程应退出"

    def test_stop_idempotent(self, qapp):
        """多次 stop 不抛异常。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig

        config = BridgeConfig.from_env()
        monitor = HeartbeatMonitor(ping_fn=lambda cb: cb(True, "ok"), config=config)
        monitor.start()
        _wait_for(qapp, [monitor.isRunning()], timeout_s=2.0)
        monitor.stop(wait_ms=5000)
        # 二次 stop 不应抛异常
        monitor.stop(wait_ms=1000)
        assert monitor.isRunning() is False

    def test_status_changed_to_down_on_misses(self, qapp):
        """连续 miss 超阈值后发出 status_changed(DOWN) 信号。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig
        from repair_app.bridge.communication.protocol import EngineStatus

        # 构造极短间隔 + 低阈值的 config，快速触发 DOWN
        config = BridgeConfig.from_env()
        # frozen dataclass，用 object.__new__ + 手动设置不可行，改用替换字段
        import dataclasses
        config = dataclasses.replace(
            config,
            heartbeat_interval_ms=50,
            heartbeat_miss_threshold=2,
            health_check_timeout_ms=100,
        )

        statuses: list[tuple[int, str]] = []
        lost: list[bool] = []

        monitor = HeartbeatMonitor(
            ping_fn=lambda cb: cb(False, "引擎不可达"),
            config=config,
        )
        monitor.status_changed.connect(lambda s, m: statuses.append((s, m)))
        monitor.engine_lost.connect(lambda: lost.append(True))

        monitor.start()
        # 等待 DOWN 信号（miss_threshold=2，interval=50ms，约 100ms 后触发）
        _wait_for(qapp, lost, timeout_s=5.0)
        monitor.stop(wait_ms=5000)

        assert len(lost) >= 1, "应发出 engine_lost 信号"
        # 至少有一次状态变为 DOWN
        down_statuses = [s for s, _ in statuses if s == int(EngineStatus.DOWN)]
        assert len(down_statuses) >= 1, "应发出 status_changed(DOWN)"

    def test_status_changed_to_ok_on_pong(self, qapp):
        """ping 成功时发出 status_changed(OK) 和 latency_updated。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig
        from repair_app.bridge.communication.protocol import EngineStatus

        import dataclasses
        config = dataclasses.replace(
            BridgeConfig.from_env(),
            heartbeat_interval_ms=50,
            health_check_timeout_ms=200,
        )

        statuses: list[tuple[int, str]] = []
        latencies: list[float] = []

        monitor = HeartbeatMonitor(
            ping_fn=lambda cb: cb(True, "OK"),
            config=config,
        )
        monitor.status_changed.connect(lambda s, m: statuses.append((s, m)))
        monitor.latency_updated.connect(lambda lat: latencies.append(lat))

        monitor.start()
        _wait_for(qapp, statuses, timeout_s=3.0)
        monitor.stop(wait_ms=5000)

        assert len(statuses) >= 1, "应至少发出一次 status_changed"
        ok_statuses = [s for s, _ in statuses if s == int(EngineStatus.OK)]
        assert len(ok_statuses) >= 1, "应发出 status_changed(OK)"
        assert len(latencies) >= 1, "应发出 latency_updated"

    def test_engine_lost_signal(self, qapp):
        """连续 miss 超阈值后发出 engine_lost 信号。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig

        import dataclasses
        config = dataclasses.replace(
            BridgeConfig.from_env(),
            heartbeat_interval_ms=30,
            heartbeat_miss_threshold=1,
            health_check_timeout_ms=50,
        )

        lost: list[bool] = []
        monitor = HeartbeatMonitor(
            ping_fn=lambda cb: cb(False, "失联"),
            config=config,
        )
        monitor.engine_lost.connect(lambda: lost.append(True))

        monitor.start()
        _wait_for(qapp, lost, timeout_s=3.0)
        monitor.stop(wait_ms=5000)

        assert len(lost) >= 1, "miss 超阈值应发出 engine_lost"

    def test_latency_updated_signal(self, qapp):
        """ping 成功时 latency_updated 信号携带正的延迟值。"""
        from repair_app.bridge.communication.heartbeat import HeartbeatMonitor
        from repair_app.bridge.communication.config import BridgeConfig

        import dataclasses
        config = dataclasses.replace(
            BridgeConfig.from_env(),
            heartbeat_interval_ms=50,
            health_check_timeout_ms=200,
        )

        latencies: list[float] = []
        monitor = HeartbeatMonitor(
            ping_fn=lambda cb: cb(True, "OK"),
            config=config,
        )
        monitor.latency_updated.connect(lambda lat: latencies.append(lat))

        monitor.start()
        _wait_for(qapp, latencies, timeout_s=3.0)
        monitor.stop(wait_ms=5000)

        assert len(latencies) >= 1
        assert all(isinstance(l, float) for l in latencies)
        assert all(l >= 0 for l in latencies), "延迟应为非负值"


# ================================================================
# 6. Worker 中断与超时线程测试（补充覆盖 BaseWorker 线程路径）
# ================================================================
@pytest.mark.unit
class TestWorkerInterruptionInThread:
    """Worker 在真实 QThread 中运行时的中断/超时行为。"""

    def test_path_worker_interrupted_in_thread(self, qapp, monkeypatch):
        """PathPlanningWorker 在 QThread 中运行时响应 requestInterruption。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_path_from_cloud", _blocking_path_iter)

        session = make_session(n_points=50)
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0, "scanning_step_mm": 2.0}
        worker = PathPlanningWorker(
            session, params, n_layers=100, buffer_mm=1.0, timeout_s=30.0
        )
        finished: list[np.ndarray] = []
        partials: list[int] = []
        worker.finished.connect(lambda wp: finished.append(wp))
        worker.partial.connect(lambda wp, idx, n: partials.append(idx))

        thread = _start_worker_thread(worker)
        _wait_for(qapp, partials, timeout_s=3.0)
        thread.requestInterruption()
        thread.quit()
        ok = thread.wait(5000)
        assert ok is True, "中断后线程应退出"
        assert len(finished) == 0, "中断后不应发出 finished"
        worker.deleteLater()
        thread.deleteLater()

    def test_morph_worker_interrupted_in_thread(self, qapp, monkeypatch):
        """MorphologyWorker 在 QThread 中运行时响应 requestInterruption。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_repair_mesh_layers", _blocking_morph_iter)

        session = make_session(n_points=50)
        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(
            session, params, n_layers=100, seed=42, timeout_s=30.0
        )
        finished: list[bool] = []
        partials: list[int] = []
        worker.finished.connect(lambda pts, m: finished.append(True))
        worker.partial.connect(lambda pts, idx, n: partials.append(idx))

        thread = _start_worker_thread(worker)
        _wait_for(qapp, partials, timeout_s=3.0)
        thread.requestInterruption()
        thread.quit()
        ok = thread.wait(5000)
        assert ok is True, "中断后线程应退出"
        assert len(finished) == 0, "中断后不应发出 finished"
        worker.deleteLater()
        thread.deleteLater()

    def test_worker_timeout_triggers_interruption(self, qapp, monkeypatch):
        """Worker 总超时触发后 check_interruption 返回 True，run 退出。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_path_from_cloud", _blocking_path_iter)

        session = make_session(n_points=50)
        params = {"layer_height_mm": 2.0}
        # 极短超时，快速触发
        worker = PathPlanningWorker(
            session, params, n_layers=100, buffer_mm=1.0, timeout_s=0.1
        )
        timeout_emitted: list[str] = []
        finished: list[np.ndarray] = []
        worker.timeout_elapsed.connect(lambda name: timeout_emitted.append(name))
        worker.finished.connect(lambda wp: finished.append(wp))

        thread = _start_worker_thread(worker)
        # 等待超时触发
        _wait_for(qapp, timeout_emitted, timeout_s=5.0)
        thread.quit()
        thread.wait(5000)
        worker.deleteLater()
        thread.deleteLater()

        assert len(timeout_emitted) == 1, "应发出一次 timeout_elapsed"
        assert timeout_emitted[0] == "PathPlanningWorker"
        assert len(finished) == 0, "超时后不应发出 finished"
