"""test_workers.py — Worker 生命周期与业务流程测试

覆盖：
  - repair_app/ui/worker_base.py: BaseWorker / WorkerManager
  - repair_app/ui/workers.py: PathPlanningWorker / MorphologyWorker /
    ComputePipelineWorker / _pack_error

测试模式：
  - BaseWorker / WorkerManager / _pack_error：直接调用，无需事件循环
  - Worker.run() 正常/异常路径：直接同步调用（信号同步发射，便于覆盖率统计）
  - Worker.run() 中断路径：QThread + requestInterruption（必须真实线程）
  - ComputePipelineWorker.run()：mock launcher / fake zmq 覆盖各阶段分支

运行：pytest -m unit tests/test_workers.py -v
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QThread, Signal

from repair_app.core.repair_session import RepairSession
from repair_app.ui.worker_base import BaseWorker, WorkerManager
from repair_app.ui.workers import (
    ComputePipelineWorker,
    MorphologyWorker,
    PathPlanningWorker,
    _pack_error,
)
from repair_app.utils.error_manager import ErrorCode


# ================================================================
# 辅助函数 / 辅助 Worker
# ================================================================
def make_session() -> RepairSession:
    """构造带最小可用数据的 RepairSession（点云 + 选区 + mock 航点）。"""
    session = RepairSession()
    session.point_cloud.xyz = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 0]],
        dtype=np.float32,
    )
    session.selection.mask = np.array([False, True, True, False, True])
    session.waypoint.mock = np.array(
        [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.float32
    )
    return session


def _start_worker_thread(worker: BaseWorker) -> QThread:
    """创建 QThread，将 worker 移入并连接 started→run，启动后返回 thread。"""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    return thread


def _stop_thread(thread: QThread, wait_ms: int = 3000) -> None:
    """退出并等待线程结束（worker.run 返回后事件循环仍在运行，需手动 quit）。"""
    thread.quit()
    thread.wait(wait_ms)


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
    """立即完成的 Worker（用于 WorkerManager.start 测试）。"""
    done = Signal()

    def run(self) -> None:
        self._mark_start()
        self.done.emit()


class _LongWorker(BaseWorker):
    """循环运行直到中断的 Worker（用于 cancel / running 状态测试）。"""
    def run(self) -> None:
        self._mark_start()
        while not self.check_interruption():
            time.sleep(0.05)


def _blocking_path_iter(*args, **kwargs):
    """模拟路径规划迭代器：持续 yield，用于中断测试。"""
    while True:
        time.sleep(0.02)
        yield np.zeros((2, 3), dtype=np.float32)


def _blocking_morph_iter(*args, **kwargs):
    """模拟形貌预测迭代器：持续 yield，用于中断测试。"""
    while True:
        time.sleep(0.02)
        yield np.zeros((4, 3), dtype=np.float32)


def _raising(*args, **kwargs):
    """调用即抛异常的替身（用于 failed 信号测试）。"""
    raise RuntimeError("worker 模拟失败")


def _make_fake_zmq(poll_result: str, reply: bytes = b"\x07fake"):
    """构造 fake zmq 模块对象（注入 sys.modules 供 run() 内 import zmq 使用）。

    poll_result: "empty"（无事件，触发超时）或 "event"（有事件，触发接收）。
    """
    class _Sock:
        def setsockopt(self, *a, **kw): pass
        def connect(self, *a, **kw): pass
        def send(self, *a, **kw): pass
        def recv(self): return reply
        def close(self, *a, **kw): pass

    sock = _Sock()

    class _Poller:
        def register(self, s, k): pass
        def poll(self, ms):
            time.sleep(0.01)
            return [(sock, 1)] if poll_result == "event" else []

    class _Ctx:
        @staticmethod
        def instance(): return _Ctx()
        def socket(self, kind): return sock

    class _Zmq:
        Context = _Ctx
        Poller = _Poller
        REQ = 3
        LINGER = 17
        POLLIN = 1

    return _Zmq()


class _MockLauncherOk:
    """模拟启动成功的 launcher（start 返回 True）。"""
    def __init__(self, project_root):
        self.project_root = project_root

    def start(self, timeout=None):
        return True

    def stop(self):
        pass


class _MockLauncherFail:
    """模拟启动失败的 launcher（start 返回 False）。"""
    def __init__(self, project_root):
        self.project_root = project_root

    def start(self, timeout=None):
        return False

    def stop(self):
        pass


# ================================================================
# 1. BaseWorker 测试
# ================================================================
@pytest.mark.unit
class TestBaseWorker:
    """BaseWorker 生命周期方法测试。"""

    def test_init_default(self, qapp):
        """默认参数：timeout_s=None、check_interval=0.5、_start_time=None。"""
        worker = BaseWorker()
        assert worker._timeout_s is None
        assert worker._check_interval == 0.5
        assert worker._start_time is None
        assert worker._worker_name == "BaseWorker"
        worker.deleteLater()

    def test_init_custom(self, qapp):
        """自定义参数：timeout_s 和 check_interval 可传入。"""
        worker = BaseWorker(timeout_s=12.5, check_interval=0.1)
        assert worker._timeout_s == 12.5
        assert worker._check_interval == 0.1
        worker.deleteLater()

    def test_mark_start(self, qapp):
        """_mark_start 后 _start_time 被设置为 monotonic 值。"""
        worker = BaseWorker(timeout_s=10.0)
        assert worker._start_time is None
        before = time.monotonic()
        worker._mark_start()
        after = time.monotonic()
        assert worker._start_time is not None
        assert before <= worker._start_time <= after
        worker.deleteLater()

    def test_check_timeout_no_timeout(self, qapp):
        """timeout_s=None 时永不超时。"""
        worker = BaseWorker()  # timeout_s=None
        worker._mark_start()
        assert worker._check_timeout() is False
        worker.deleteLater()

    def test_check_timeout_not_started(self, qapp):
        """未 _mark_start（_start_time=None）时不判定超时。"""
        worker = BaseWorker(timeout_s=1.0)
        assert worker._start_time is None
        assert worker._check_timeout() is False
        worker.deleteLater()

    def test_check_timeout_within(self, qapp):
        """运行时间未超过 timeout_s 时不超时。"""
        worker = BaseWorker(timeout_s=100.0)
        worker._mark_start()
        assert worker._check_timeout() is False
        worker.deleteLater()

    def test_check_timeout_exceeded(self, qapp):
        """运行时间超过 timeout_s 时返回 True 并发出 timeout_elapsed 信号。"""
        worker = BaseWorker(timeout_s=1.0)
        worker._mark_start()
        # 将起始时间人为前置，模拟已运行很久
        worker._start_time = time.monotonic() - 100
        emitted = []
        worker.timeout_elapsed.connect(lambda name: emitted.append(name))
        assert worker._check_timeout() is True
        assert emitted == ["BaseWorker"], "应发出 timeout_elapsed 信号（含 worker 名称）"
        worker.deleteLater()

    def test_check_interruption_normal(self, qapp):
        """无中断请求、无超时 时 check_interruption 返回 False。"""
        worker = BaseWorker()  # 无 timeout，主线程无中断请求
        assert worker.check_interruption() is False
        worker.deleteLater()

    def test_cleanup_default(self, qapp):
        """默认 cleanup() 为空实现，调用不抛异常。"""
        worker = BaseWorker()
        worker.cleanup()  # 不应抛异常
        worker.deleteLater()

    def test_timeout_elapsed_signal(self, qapp):
        """timeout_elapsed 信号携带 worker 名称字符串。"""
        worker = BaseWorker(timeout_s=0.5)
        worker._mark_start()
        worker._start_time = time.monotonic() - 10
        received = []
        worker.timeout_elapsed.connect(lambda name: received.append(name))
        worker._check_timeout()
        assert len(received) == 1
        assert isinstance(received[0], str)
        assert received[0] == worker._worker_name
        worker.deleteLater()


# ================================================================
# 2. WorkerManager 测试
# ================================================================
@pytest.mark.unit
class TestWorkerManager:
    """WorkerManager 启动/取消/清理/状态查询测试。"""

    def test_init(self, qapp):
        """__init__：_workers 为空、等待参数为默认值。"""
        mgr = WorkerManager()
        assert mgr._workers == {}
        assert mgr._wait_ms == 5000
        assert mgr._terminate_wait_ms == 2000
        assert mgr._parent is None

    def test_start(self, qapp):
        """start() 启动 worker 并执行 run()，登记到 _workers。"""
        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()
        done = []
        worker.done.connect(lambda: done.append(True))
        mgr.start("w1", worker, thread)
        _wait_for(qapp, done, timeout_s=3.0)
        _stop_thread(thread)
        assert done, "worker.run 应被执行（done 信号发出）"
        assert "w1" in mgr._workers
        mgr.cleanup_all()

    def test_start_replaces_running(self, qapp):
        """同名 worker 仍在运行时，start 先停止旧 worker 再启动新的。"""
        mgr = WorkerManager()
        long_worker = _LongWorker()
        long_thread = QThread()
        mgr.start("dup", long_worker, long_thread)
        # 确认旧 worker 已运行
        _wait_for(qapp, [long_thread.isRunning()], timeout_s=2.0)
        # 启动同名新 worker（触发内部 cancel 旧 worker）
        new_worker = _QuickWorker()
        new_thread = QThread()
        done = []
        new_worker.done.connect(lambda: done.append(True))
        mgr.start("dup", new_worker, new_thread)
        _wait_for(qapp, done, timeout_s=3.0)
        _stop_thread(new_thread)
        assert done, "新 worker 应被执行"
        assert "dup" in mgr._workers
        mgr.cleanup_all()

    def test_cancel_unknown_name(self, qapp):
        """cancel 未登记的名称时不抛异常（直接返回）。"""
        mgr = WorkerManager()
        mgr.cancel("nonexistent")  # 不应抛异常
        assert mgr._workers == {}

    def test_cancel(self, qapp):
        """cancel() 取消指定 worker 并等待其退出。"""
        mgr = WorkerManager()
        worker = _LongWorker()
        thread = QThread()
        mgr.start("long", worker, thread)
        # 等待线程进入运行状态
        _wait_for(qapp, [thread.isRunning()], timeout_s=2.0)
        assert mgr.is_any_running() is True
        assert "long" in mgr.get_running_names()
        # 取消
        mgr.cancel("long")
        assert not thread.isRunning(), "cancel 后线程应已退出"
        assert mgr.is_any_running() is False
        mgr.cleanup_all()

    def test_cancel_all(self, qapp):
        """cancel_all() 取消所有运行中的 worker。"""
        mgr = WorkerManager()
        w1 = _LongWorker(); t1 = QThread()
        w2 = _LongWorker(); t2 = QThread()
        mgr.start("a", w1, t1)
        mgr.start("b", w2, t2)
        _wait_for(qapp, [t1.isRunning() and t2.isRunning()], timeout_s=2.0)
        assert mgr.is_any_running() is True
        mgr.cancel_all()
        assert mgr.is_any_running() is False
        assert mgr.get_running_names() == []
        mgr.cleanup_all()

    def test_cleanup_all(self, qapp):
        """cleanup_all() 清空 _workers 引用。"""
        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()
        mgr.start("w", worker, thread)
        _stop_thread(thread)
        assert "w" in mgr._workers
        mgr.cleanup_all()
        assert mgr._workers == {}

    def test_is_any_running_empty(self, qapp):
        """无 worker 时 is_any_running 返回 False。"""
        mgr = WorkerManager()
        assert mgr.is_any_running() is False

    def test_get_running_names_empty(self, qapp):
        """无 worker 时 get_running_names 返回空列表。"""
        mgr = WorkerManager()
        assert mgr.get_running_names() == []

    def test_running_names_and_state(self, qapp):
        """运行中 worker 反映在 is_any_running / get_running_names。"""
        mgr = WorkerManager()
        worker = _LongWorker()
        thread = QThread()
        mgr.start("running", worker, thread)
        _wait_for(qapp, [thread.isRunning()], timeout_s=2.0)
        assert mgr.is_any_running() is True
        names = mgr.get_running_names()
        assert "running" in names
        mgr.cancel("running")
        assert mgr.is_any_running() is False
        assert mgr.get_running_names() == []
        mgr.cleanup_all()


# ================================================================
# 3. _pack_error 测试
# ================================================================
@pytest.mark.unit
class TestPackError:
    """_pack_error 返回 (code, friendly, detail) 三元组。"""

    def test_returns_three_tuple(self, qapp):
        """返回值为长度 3 的 tuple，且元素均为 str。"""
        exc = RuntimeError("模拟失败")
        result = _pack_error(exc, ErrorCode.MATLAB, "路径规划")
        assert isinstance(result, tuple)
        assert len(result) == 3
        for item in result:
            assert isinstance(item, str)

    def test_code_value(self, qapp):
        """第一项为 ErrorCode 的 value 字符串。"""
        exc = RuntimeError("x")
        code, _, _ = _pack_error(exc, ErrorCode.NETWORK, "ZMQ")
        assert code == ErrorCode.NETWORK.value
        assert code == "network"

    def test_friendly_contains_context(self, qapp):
        """第二项友好消息含上下文标题。"""
        exc = RuntimeError("boom")
        _, friendly, _ = _pack_error(exc, ErrorCode.MATLAB, "路径规划")
        assert isinstance(friendly, str)
        assert len(friendly) > 0
        assert "路径规划" in friendly

    def test_detail_contains_traceback(self, qapp):
        """第三项 detail 含异常类型与 traceback 文本。"""
        exc = ValueError("详细错误信息")
        _, _, detail = _pack_error(exc, ErrorCode.UNKNOWN, "测试")
        assert isinstance(detail, str)
        assert "ValueError" in detail
        assert "详细错误信息" in detail

    def test_default_code_unknown(self, qapp):
        """未指定 code 时使用 ErrorCode.UNKNOWN。"""
        exc = ValueError("默认错误")
        code, friendly, detail = _pack_error(exc)
        assert code == ErrorCode.UNKNOWN.value
        assert isinstance(friendly, str)
        assert isinstance(detail, str)


# ================================================================
# 4. PathPlanningWorker 测试
# ================================================================
@pytest.mark.unit
class TestPathPlanningWorker:
    """路径规划 Worker 构造 / run / 中断 / failed / partial 测试。"""

    def test_construction(self, qapp):
        """构造：接收 RepairSession 并保存参数。"""
        session = make_session()
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0}
        worker = PathPlanningWorker(
            session, params, n_layers=3, buffer_mm=1.5, timeout_s=300.0
        )
        assert worker._session is session
        assert worker._params is params
        assert worker._n_layers == 3
        assert worker._buffer_mm == 1.5
        assert worker._timeout_s == 300.0
        assert worker._worker_name == "PathPlanningWorker"
        worker.deleteLater()

    def test_default_timeout(self, qapp):
        """默认 timeout_s=300.0。"""
        worker = PathPlanningWorker(make_session(), {}, 1, 1.0)
        assert worker._timeout_s == 300.0
        worker.deleteLater()

    def test_run_finishes(self, qapp):
        """run() 正常完成时 emit finished(object)（QThread + signal spy 模式）。"""
        session = make_session()
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0, "scanning_step_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=2, buffer_mm=1.0, timeout_s=10.0)
        results = []
        worker.finished.connect(lambda wp: results.append(wp))
        thread = _start_worker_thread(worker)
        _wait_for(qapp, results, timeout_s=10.0)
        _stop_thread(thread)
        assert len(results) == 1, "应发出一次 finished 信号"
        assert isinstance(results[0], np.ndarray)
        assert len(results[0]) > 0, "应生成非空航点"

    def test_run_emits_partial(self, qapp):
        """run() 逐层 emit partial(object, int, int)（直接同步调用）。"""
        session = make_session()
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0, "scanning_step_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=2, buffer_mm=1.0, timeout_s=10.0)
        partials = []
        finished = []
        worker.partial.connect(lambda wp, idx, n: partials.append((wp, idx, n)))
        worker.finished.connect(lambda wp: finished.append(wp))
        # 直接调用 run()：主线程同步执行，信号同步发射
        worker.run()
        assert len(partials) >= 1, "应至少发出一次 partial 信号"
        wp, idx, n = partials[0]
        assert isinstance(wp, np.ndarray)
        assert isinstance(idx, int)
        assert isinstance(n, int)
        assert n == 2
        assert len(finished) == 1, "应发出一次 finished 信号"
        worker.deleteLater()

    def test_run_interrupted(self, qapp, monkeypatch):
        """requestInterruption 后 run() 中断，不 emit finished。"""
        # 用阻塞迭代器保证 worker 停在循环中
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_path_from_cloud", _blocking_path_iter)

        session = make_session()
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0, "scanning_step_mm": 2.0}
        worker = PathPlanningWorker(
            session, params, n_layers=100, buffer_mm=1.0, timeout_s=30.0
        )
        finished = []
        partials = []
        worker.finished.connect(lambda wp: finished.append(wp))
        worker.partial.connect(lambda wp, idx, n: partials.append(idx))
        thread = _start_worker_thread(worker)
        # 等待 worker 进入循环（收到 partial）
        _wait_for(qapp, partials, timeout_s=3.0)
        # 请求中断
        thread.requestInterruption()
        thread.quit()
        assert thread.wait(5000), "线程应在中断后退出"
        assert len(finished) == 0, "中断后不应发出 finished 信号"

    def test_failed_emits_three_tuple(self, qapp, monkeypatch):
        """异常时 emit failed(str, str, str) 三元组（直接同步调用）。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_path_from_cloud", _raising)

        session = make_session()
        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=2, buffer_mm=1.0, timeout_s=10.0)
        failed = []
        finished = []
        worker.failed.connect(lambda c, f, d: failed.append((c, f, d)))
        worker.finished.connect(lambda wp: finished.append(wp))
        # 直接调用 run()：iter_path_from_cloud 抛异常 → except → emit failed
        worker.run()
        assert len(failed) == 1, "应发出一次 failed 信号"
        code, friendly, detail = failed[0]
        assert isinstance(code, str)
        assert isinstance(friendly, str)
        assert isinstance(detail, str)
        assert len(friendly) > 0
        assert "Traceback" in detail or "worker 模拟失败" in detail
        assert len(finished) == 0, "异常时不应发出 finished 信号"
        worker.deleteLater()


# ================================================================
# 5. MorphologyWorker 测试
# ================================================================
@pytest.mark.unit
class TestMorphologyWorker:
    """形貌预测 Worker 构造 / run / 中断 / failed / partial 测试。"""

    def test_construction(self, qapp):
        """构造：接收 RepairSession 并保存参数。"""
        session = make_session()
        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(
            session, params, n_layers=4, seed=42, timeout_s=600.0
        )
        assert worker._session is session
        assert worker._params is params
        assert worker._n_layers == 4
        assert worker._seed == 42
        assert worker._timeout_s == 600.0
        assert worker._worker_name == "MorphologyWorker"
        worker.deleteLater()

    def test_default_timeout(self, qapp):
        """默认 timeout_s=600.0。"""
        worker = MorphologyWorker(make_session(), {}, 1, 1)
        assert worker._timeout_s == 600.0
        worker.deleteLater()

    def test_run_finishes(self, qapp):
        """run() 正常完成时 emit finished(repair_pts, is_mock)（QThread + signal spy 模式）。"""
        session = make_session()
        params = {
            "particle_velocity_ms": 500,
            "critical_velocity_ms": 400,
            "nozzle_diameter_mm": 6,
        }
        worker = MorphologyWorker(session, params, n_layers=2, seed=42, timeout_s=10.0)
        results = []
        worker.finished.connect(lambda pts, is_mock: results.append((pts, is_mock)))
        thread = _start_worker_thread(worker)
        _wait_for(qapp, results, timeout_s=10.0)
        _stop_thread(thread)
        assert len(results) == 1, "应发出一次 finished 信号"
        pts, is_mock = results[0]
        assert isinstance(pts, np.ndarray)
        assert isinstance(is_mock, bool)

    def test_run_emits_partial(self, qapp):
        """run() 逐层 emit partial(object, int, int)（直接同步调用）。"""
        session = make_session()
        params = {
            "particle_velocity_ms": 500,
            "critical_velocity_ms": 400,
            "nozzle_diameter_mm": 6,
        }
        worker = MorphologyWorker(session, params, n_layers=2, seed=42, timeout_s=10.0)
        partials = []
        finished = []
        worker.partial.connect(lambda pts, idx, n: partials.append((pts, idx, n)))
        worker.finished.connect(lambda pts, is_mock: finished.append(True))
        # 直接调用 run()：主线程同步执行，信号同步发射
        worker.run()
        assert len(partials) >= 1, "应至少发出一次 partial 信号"
        pts, idx, n = partials[0]
        assert isinstance(pts, np.ndarray)
        assert isinstance(idx, int)
        assert isinstance(n, int)
        assert n == 2
        assert len(finished) == 1, "应发出一次 finished 信号"
        worker.deleteLater()

    def test_run_interrupted(self, qapp, monkeypatch):
        """requestInterruption 后 run() 中断，不 emit finished。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_repair_mesh_layers", _blocking_morph_iter)

        session = make_session()
        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(session, params, n_layers=100, seed=42, timeout_s=30.0)
        finished = []
        partials = []
        worker.finished.connect(lambda pts, is_mock: finished.append(True))
        worker.partial.connect(lambda pts, idx, n: partials.append(idx))
        thread = _start_worker_thread(worker)
        _wait_for(qapp, partials, timeout_s=3.0)
        thread.requestInterruption()
        thread.quit()
        assert thread.wait(5000), "线程应在中断后退出"
        assert len(finished) == 0, "中断后不应发出 finished 信号"

    def test_failed_emits_four_tuple(self, qapp, monkeypatch):
        """异常时 emit failed(str, str, str, object) 四元组（含 repair_data）。"""
        import repair_app.ui.workers as workers_mod
        monkeypatch.setattr(workers_mod, "iter_repair_mesh_layers", _raising)

        session = make_session()
        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(session, params, n_layers=2, seed=42, timeout_s=10.0)
        failed = []
        finished = []
        worker.failed.connect(lambda c, f, d, data: failed.append((c, f, d, data)))
        worker.finished.connect(lambda pts, is_mock: finished.append(True))
        # 直接调用 run()：iter_repair_mesh_layers 抛异常 → except → emit failed
        worker.run()
        assert len(failed) == 1, "应发出一次 failed 信号"
        code, friendly, detail, repair_data = failed[0]
        assert isinstance(code, str)
        assert isinstance(friendly, str)
        assert isinstance(detail, str)
        # repair_data 为兜底修复点云（mock），应是 ndarray
        assert isinstance(repair_data, np.ndarray)
        assert len(repair_data) >= 1, "失败时应携带兜底 repair_data"
        assert len(finished) == 0, "异常时不应发出 finished 信号"
        worker.deleteLater()


# ================================================================
# 6. ComputePipelineWorker 测试
# ================================================================
@pytest.mark.unit
class TestComputePipelineWorker:
    """一键计算管线 Worker 构造 / 信号签名 / run 各阶段分支 测试。"""

    def test_construction(self, qapp):
        """构造：保存所有参数，_launcher 初始为 None。"""
        worker = ComputePipelineWorker(
            project_root="/tmp/proj",
            request_bytes=b"\x00\x01\x02",
            bridge_address="tcp://127.0.0.1:5555",
            startup_timeout=60.0,
            zmq_timeout=300.0,
        )
        assert worker._project_root == "/tmp/proj"
        assert worker._request_bytes == b"\x00\x01\x02"
        assert worker._bridge_address == "tcp://127.0.0.1:5555"
        assert worker._startup_timeout == 60.0
        assert worker._zmq_timeout == 300.0
        assert worker._launcher is None
        # 继承 BaseWorker，总超时由各阶段管理（None）
        assert worker._timeout_s is None
        assert worker._worker_name == "ComputePipelineWorker"
        worker.deleteLater()

    def test_default_values(self, qapp):
        """默认 bridge_address / startup_timeout / zmq_timeout。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        assert worker._bridge_address == "tcp://127.0.0.1:5555"
        assert worker._startup_timeout == 120.0
        assert worker._zmq_timeout == 600.0
        worker.deleteLater()

    def test_failed_signal_signature(self, qapp):
        """failed 信号签名：接受 3 个 str 参数 (code, friendly, detail)。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        received = []
        worker.failed.connect(lambda c, f, d: received.append((c, f, d)))
        worker.failed.emit("network", "友好消息", "技术详情")
        qapp.processEvents()
        assert received == [("network", "友好消息", "技术详情")]
        worker.deleteLater()

    def test_stage_signal_signature(self, qapp):
        """stage 信号签名：接受 1 个 str 参数。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        received = []
        worker.stage.connect(lambda s: received.append(s))
        worker.stage.emit("正在启动 MATLAB...")
        qapp.processEvents()
        assert received == ["正在启动 MATLAB..."]
        worker.deleteLater()

    def test_result_signal_signature(self, qapp):
        """result 信号签名：接受 1 个 dict 参数。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        received = []
        worker.result.connect(lambda r: received.append(r))
        payload = {"waypoints": np.zeros((1, 3)), "layers": 2}
        worker.result.emit(payload)
        qapp.processEvents()
        assert received == [payload]
        worker.deleteLater()

    def test_cleanup_no_op(self, qapp):
        """cleanup() 默认为空实现，调用不抛异常。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        worker.cleanup()  # 不应抛异常
        worker.deleteLater()

    def test_stop_launcher_no_launcher(self, qapp):
        """stop_launcher() 在无 launcher 时不抛异常。"""
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"")
        worker.stop_launcher()  # _launcher 为 None，不应抛异常
        assert worker._launcher is None
        worker.deleteLater()

    def test_stop_launcher_with_launcher(self, qapp, monkeypatch):
        """stop_launcher() 在有 launcher 时调用其 stop()。"""
        from repair_app.bridge import launcher as launcher_mod
        monkeypatch.setattr(launcher_mod, "MatlabBridgeLauncher", _MockLauncherOk)
        worker = ComputePipelineWorker(project_root="/tmp", request_bytes=b"\x00")
        # 直接调用 run() 让 launcher 启动成功（mock start=True），随后 ZMQ 阶段会失败
        # 这里仅验证 stop_launcher 在 _launcher 已设置时能调用 stop
        worker._launcher = _MockLauncherOk("/tmp")
        worker.stop_launcher()  # 不应抛异常
        worker.deleteLater()

    def test_run_launcher_start_failure(self, qapp, monkeypatch):
        """run() 中 launcher.start() 返回 False 时 emit failed(MATLAB)。"""
        from repair_app.bridge import launcher as launcher_mod
        monkeypatch.setattr(launcher_mod, "MatlabBridgeLauncher", _MockLauncherFail)

        worker = ComputePipelineWorker(
            project_root="/tmp/proj",
            request_bytes=b"\x00",
            startup_timeout=5.0,
            zmq_timeout=10.0,
        )
        stages = []
        failed = []
        worker.stage.connect(lambda s: stages.append(s))
        worker.failed.connect(lambda c, f, d: failed.append((c, f, d)))
        worker.run()  # 直接调用：launcher 启动失败分支
        assert len(failed) == 1, "launcher 启动失败应发出 failed 信号"
        code, friendly, detail = failed[0]
        assert code == ErrorCode.MATLAB.value
        assert isinstance(friendly, str) and len(friendly) > 0
        assert isinstance(detail, str)
        assert len(stages) >= 1, "应至少发出一次 stage 信号"
        assert worker._launcher is not None
        worker.deleteLater()

    def test_run_zmq_timeout(self, qapp, monkeypatch):
        """run() 中 ZMQ 轮询超时 时 emit failed(NETWORK)。"""
        from repair_app.bridge import launcher as launcher_mod
        monkeypatch.setattr(launcher_mod, "MatlabBridgeLauncher", _MockLauncherOk)
        # 注入 fake zmq：poll 始终无事件，触发超时
        monkeypatch.setitem(sys.modules, "zmq", _make_fake_zmq("empty"))

        worker = ComputePipelineWorker(
            project_root="/tmp/proj",
            request_bytes=b"\x00",
            startup_timeout=5.0,
            zmq_timeout=0.1,  # 很短的超时，快速触发
        )
        stages = []
        failed = []
        worker.stage.connect(lambda s: stages.append(s))
        worker.failed.connect(lambda c, f, d: failed.append((c, f, d)))
        worker.run()  # 直接调用：ZMQ 超时分支
        assert len(failed) == 1, "ZMQ 超时应发出 failed 信号"
        code, friendly, detail = failed[0]
        assert code == ErrorCode.NETWORK.value
        assert "超时" in friendly
        assert len(stages) >= 2, "应发出启动 + 计算两个 stage 信号"
        worker.deleteLater()

    def test_run_zmq_success(self, qapp, monkeypatch):
        """run() 中 ZMQ 收到回复后解析结果并 emit result(dict)。"""
        from repair_app.bridge import launcher as launcher_mod
        monkeypatch.setattr(launcher_mod, "MatlabBridgeLauncher", _MockLauncherOk)
        monkeypatch.setitem(sys.modules, "zmq", _make_fake_zmq("event", reply=b"\x07ok"))

        # mock 反序列化：跳过真实 protobuf 解析
        from repair_app.communication import repair_serialization as rs_mod
        monkeypatch.setattr(rs_mod, "deserialize_result", lambda data: {"raw": data})
        monkeypatch.setattr(rs_mod, "parse_repair_result", lambda msg: {"parsed": True, "n": 3})

        worker = ComputePipelineWorker(
            project_root="/tmp/proj",
            request_bytes=b"\x00",
            startup_timeout=5.0,
            zmq_timeout=10.0,
        )
        stages = []
        results = []
        failed = []
        worker.stage.connect(lambda s: stages.append(s))
        worker.result.connect(lambda r: results.append(r))
        worker.failed.connect(lambda c, f, d: failed.append((c, f, d)))
        worker.run()  # 直接调用：完整成功路径
        assert len(failed) == 0, "成功路径不应发出 failed 信号"
        assert len(results) == 1, "应发出一次 result 信号"
        assert results[0] == {"parsed": True, "n": 3}
        assert len(stages) >= 3, "应发出启动/计算/解析三个 stage 信号"
        worker.deleteLater()

    def test_run_parse_exception(self, qapp, monkeypatch):
        """run() 中结果解析抛异常时 emit failed（走 _pack_error 路径）。"""
        from repair_app.bridge import launcher as launcher_mod
        monkeypatch.setattr(launcher_mod, "MatlabBridgeLauncher", _MockLauncherOk)
        monkeypatch.setitem(sys.modules, "zmq", _make_fake_zmq("event", reply=b"\x07bad"))

        from repair_app.communication import repair_serialization as rs_mod

        def _raise(data):
            raise RuntimeError("反序列化失败")

        monkeypatch.setattr(rs_mod, "deserialize_result", _raise)

        worker = ComputePipelineWorker(
            project_root="/tmp/proj",
            request_bytes=b"\x00",
            startup_timeout=5.0,
            zmq_timeout=10.0,
        )
        failed = []
        worker.failed.connect(lambda c, f, d: failed.append((c, f, d)))
        worker.run()  # 直接调用：解析异常 → except → emit failed
        assert len(failed) == 1, "解析异常应发出 failed 信号"
        code, friendly, detail = failed[0]
        assert isinstance(code, str)
        assert "反序列化失败" in detail or "Traceback" in detail
        worker.deleteLater()
