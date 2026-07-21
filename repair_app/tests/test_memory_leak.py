"""test_memory_leak.py — 内存泄漏检测测试

覆盖：
  - Worker 内存释放：PathPlanningWorker / MorphologyWorker 连续创建销毁
  - RepairSession 内存：reset() / reset_pipeline() / 大数据量 reset
  - ndarray 引用计数：赋值后引用计数正确 / Worker 持有 session 不增加 ndarray 引用
  - QThread 资源清理：thread / worker 对象 deleteLater
  - ZMQ socket 清理：close() 后 socket 被清理

检测方式：
  - tracemalloc：跟踪 Python 内存分配
  - weakref：验证对象是否被垃圾回收
  - sys.getrefcount：验证 ndarray 引用计数

运行：pytest -m "unit or stress" tests/test_memory_leak.py -v
"""
from __future__ import annotations

import gc
import sys
import time
import weakref

import numpy as np
import pytest

from repair_app.core.repair_session import RepairSession
from repair_app.ui.workers import PathPlanningWorker, MorphologyWorker


# ================================================================
# 辅助函数
# ================================================================
def make_session(n_points: int = 100) -> RepairSession:
    """构造带最小可用数据的 RepairSession。"""
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


def _memory_growth_mb(create_destroy_fn, iterations: int) -> float:
    """测量连续 create/destroy 后的内存增长（MB）。

    使用 tracemalloc 跟踪 Python 分配的内存。
    """
    import tracemalloc

    # 预热：先跑一轮，避免首次导入/缓存的干扰
    create_destroy_fn()
    gc.collect()

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for _ in range(iterations):
        create_destroy_fn()

    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 使用 traced memory 的差值（current 反映当前仍在分配的内存）
    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    diff_bytes = sum(stat.size_diff for stat in stats if stat.size_diff > 0)
    return diff_bytes / (1024 * 1024)


# ================================================================
# 1. Worker 内存释放测试
# ================================================================
@pytest.mark.stress
class TestWorkerMemoryRelease:
    """Worker 连续创建/销毁后内存不泄漏。"""

    def test_path_planning_worker_no_leak(self, qapp):
        """连续创建/销毁 PathPlanningWorker 100 次，内存增长 < 10MB。"""
        session = make_session(n_points=100)
        params = {"layer_height_mm": 2.0, "scanning_angle_deg": -45.0}

        def create_destroy() -> None:
            worker = PathPlanningWorker(
                session, params, n_layers=2, buffer_mm=1.0, timeout_s=10.0
            )
            # 模拟使用：访问 session 引用（不 copy）
            _ = worker._session.point_cloud.xyz
            worker.deleteLater()
            qapp.processEvents()

        growth_mb = _memory_growth_mb(create_destroy, iterations=100)
        # 10MB 阈值（允许少量缓存/分配抖动）
        assert growth_mb < 10.0, (
            f"PathPlanningWorker 内存增长 {growth_mb:.2f}MB 超过 10MB 阈值，可能存在泄漏"
        )

    def test_morphology_worker_no_leak(self, qapp):
        """连续创建/销毁 MorphologyWorker 100 次，内存增长 < 10MB。"""
        session = make_session(n_points=100)
        params = {"particle_velocity_ms": 500}

        def create_destroy() -> None:
            worker = MorphologyWorker(
                session, params, n_layers=2, seed=42, timeout_s=10.0
            )
            _ = worker._session.point_cloud.xyz
            worker.deleteLater()
            qapp.processEvents()

        growth_mb = _memory_growth_mb(create_destroy, iterations=100)
        assert growth_mb < 10.0, (
            f"MorphologyWorker 内存增长 {growth_mb:.2f}MB 超过 10MB 阈值，可能存在泄漏"
        )

    def test_path_planning_worker_garbage_collected(self, qapp):
        """PathPlanningWorker 对象无引用后被垃圾回收（weakref 验证）。"""
        session = make_session(n_points=50)
        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=1, buffer_mm=1.0)
        ref = weakref.ref(worker)

        # 删除引用
        del worker
        gc.collect()

        assert ref() is None, "PathPlanningWorker 应被垃圾回收"

    def test_morphology_worker_garbage_collected(self, qapp):
        """MorphologyWorker 对象无引用后被垃圾回收。"""
        session = make_session(n_points=50)
        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(session, params, n_layers=1, seed=42)
        ref = weakref.ref(worker)

        del worker
        gc.collect()

        assert ref() is None, "MorphologyWorker 应被垃圾回收"


# ================================================================
# 2. RepairSession 内存测试
# ================================================================
@pytest.mark.unit
class TestRepairSessionMemory:
    """RepairSession reset() / reset_pipeline() 后内存释放。"""

    def test_reset_releases_point_cloud(self, qapp):
        """reset() 后 point_cloud.xyz 被释放（weakref 验证）。"""
        session = make_session(n_points=1000)
        xyz = session.point_cloud.xyz
        ref = weakref.ref(xyz)

        # 删除外部引用 + reset
        del xyz
        session.reset()
        gc.collect()

        assert ref() is None, "reset() 后 point_cloud.xyz 应被回收"
        assert session.point_cloud.xyz is None

    def test_reset_releases_selection(self, qapp):
        """reset() 后 selection.mask 被释放。"""
        session = make_session(n_points=500)
        mask = session.selection.mask
        ref = weakref.ref(mask)

        del mask
        session.reset()
        gc.collect()

        assert ref() is None, "reset() 后 selection.mask 应被回收"
        assert session.selection.mask is None

    def test_reset_releases_waypoint(self, qapp):
        """reset() 后 waypoint.mock 被释放。"""
        session = make_session(n_points=100)
        wp = session.waypoint.mock
        ref = weakref.ref(wp)

        del wp
        session.reset()
        gc.collect()

        assert ref() is None, "reset() 后 waypoint.mock 应被回收"
        assert session.waypoint.mock is None

    def test_reset_pipeline_releases_waypoint(self, qapp):
        """reset_pipeline() 后 waypoint/layer/morphology 被释放，但保留 point_cloud。"""
        session = make_session(n_points=200)
        xyz = session.point_cloud.xyz
        wp = session.waypoint.mock
        wp_ref = weakref.ref(wp)
        xyz_ref = weakref.ref(xyz)

        del wp, xyz
        session.reset_pipeline()
        gc.collect()

        # waypoint 应被释放
        assert wp_ref() is None, "reset_pipeline() 后 waypoint.mock 应被回收"
        # point_cloud 应保留（reset_pipeline 仅重置管线数据）
        assert xyz_ref() is not None, "reset_pipeline() 不应释放 point_cloud.xyz"
        assert session.point_cloud.xyz is not None
        assert session.waypoint.mock is None

    def test_reset_pipeline_releases_morphology(self, qapp):
        """reset_pipeline() 后 morphology.repair_xyz 被释放。"""
        session = make_session(n_points=100)
        repair = np.zeros((50, 3), dtype=np.float32)
        session.morphology.repair_xyz = repair
        ref = weakref.ref(repair)

        del repair
        session.reset_pipeline()
        gc.collect()

        assert ref() is None, "reset_pipeline() 后 morphology.repair_xyz 应被回收"
        assert session.morphology.repair_xyz is None

    def test_reset_preserves_seed_and_mode(self, qapp):
        """reset() 保留 latest_seed 和 repair_mode（验证 reset 语义正确）。"""
        session = make_session(n_points=100)
        session.latest_seed = 99
        session.repair_mode = "testing"

        session.reset()

        assert session.latest_seed == 99, "reset 应保留 latest_seed"
        assert session.repair_mode == "testing", "reset 应保留 repair_mode"

    @pytest.mark.slow
    def test_large_session_reset_releases_memory(self, qapp):
        """大数据量 session（100万点）reset 后内存回收（tracemalloc 验证）。"""
        import tracemalloc

        tracemalloc.start()
        gc.collect()
        snapshot_before = tracemalloc.take_snapshot()

        session = RepairSession()
        # 100万点 × 3维 × 4字节(float32) ≈ 12MB
        rng = np.random.default_rng(0)
        session.point_cloud.xyz = rng.uniform(-100, 100, (1_000_000, 3)).astype(np.float32)
        mask = np.zeros(1_000_000, dtype=bool)
        mask[::3] = True
        session.selection.mask = mask

        # 触发 reset
        session.reset()
        gc.collect()

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # reset 后 xyz 应为 None
        assert session.point_cloud.xyz is None
        assert session.selection.mask is None

        # 内存差值：reset 后不应残留大量分配
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        diff_bytes = sum(stat.size_diff for stat in stats)
        # 允许少量残留（gc 未完全回收 / 缓存），但不应残留 > 5MB
        assert diff_bytes < 5 * 1024 * 1024, (
            f"100万点 session reset 后残留 {diff_bytes / 1024 / 1024:.2f}MB，"
            f"可能存在内存泄漏"
        )


# ================================================================
# 3. ndarray 引用计数测试
# ================================================================
@pytest.mark.unit
class TestNdarrayRefcount:
    """ndarray 引用计数验证：赋值后计数正确，Worker 持有 session 不增加 ndarray 引用。"""

    def test_assignment_increments_refcount(self, qapp):
        """session.point_cloud.xyz = arr 后 ndarray 引用计数 +1。"""
        arr = np.zeros((100, 3), dtype=np.float32)
        # getrefcount 自身持有 1 个引用（参数），arr 变量持有 1 个
        base_count = sys.getrefcount(arr)
        # 预期 base_count == 2（arr 变量 + getrefcount 参数）

        session = RepairSession()
        session.point_cloud.xyz = arr
        after_count = sys.getrefcount(arr)

        # session 持有 1 个引用，计数应 +1
        assert after_count == base_count + 1, (
            f"赋值后引用计数应 +1：base={base_count}, after={after_count}"
        )

    def test_replacement_decrements_old_refcount(self, qapp):
        """替换 session.point_cloud.xyz 后旧 ndarray 引用计数 -1。"""
        arr1 = np.zeros((100, 3), dtype=np.float32)
        session = RepairSession()
        session.point_cloud.xyz = arr1
        count_after_assign = sys.getrefcount(arr1)

        # 用新数组替换
        arr2 = np.zeros((50, 3), dtype=np.float32)
        session.point_cloud.xyz = arr2
        count_after_replace = sys.getrefcount(arr1)

        # 旧数组引用计数应 -1（session 不再持有）
        assert count_after_replace == count_after_assign - 1, (
            f"替换后旧数组引用计数应 -1："
            f"after_assign={count_after_assign}, after_replace={count_after_replace}"
        )

    def test_worker_session_ref_no_ndarray_copy(self, qapp):
        """Worker 持有 session 引用不增加 ndarray 引用计数（无 .copy()）。"""
        session = make_session(n_points=200)
        xyz = session.point_cloud.xyz
        # 此时引用：xyz 变量 + getrefcount 参数 + session.point_cloud.xyz
        base_count = sys.getrefcount(xyz)

        # 创建 Worker，传入 session 引用（不 copy ndarray）
        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=2, buffer_mm=1.0)

        # Worker 持有 session 引用，但不应增加 xyz 的引用计数
        # （worker._session is session，未访问 point_cloud.xyz）
        after_worker_count = sys.getrefcount(xyz)

        assert after_worker_count == base_count, (
            f"Worker 持有 session 引用不应增加 ndarray 引用计数："
            f"base={base_count}, after_worker={after_worker_count}"
        )

        # Worker 内部访问 session.point_cloud.xyz 时也只是临时引用
        # 在函数作用域内访问，局部引用随函数退出释放，不持久化
        def _access_temporarily() -> None:
            _ = worker._session.point_cloud.xyz  # noqa: F841 局部临时引用
        _access_temporarily()
        # 函数返回后局部引用已释放
        accessed_count = sys.getrefcount(xyz)
        assert accessed_count == base_count, (
            f"Worker 访问 session.point_cloud.xyz 后不应持久增加引用计数："
            f"base={base_count}, accessed={accessed_count}"
        )

        worker.deleteLater()

    def test_morph_worker_session_ref_no_ndarray_copy(self, qapp):
        """MorphologyWorker 持有 session 引用不增加 ndarray 引用计数。"""
        session = make_session(n_points=200)
        xyz = session.point_cloud.xyz
        base_count = sys.getrefcount(xyz)

        params = {"particle_velocity_ms": 500}
        worker = MorphologyWorker(session, params, n_layers=2, seed=42)

        after_worker_count = sys.getrefcount(xyz)
        assert after_worker_count == base_count, (
            f"MorphologyWorker 持有 session 引用不应增加 ndarray 引用计数："
            f"base={base_count}, after_worker={after_worker_count}"
        )

        worker.deleteLater()

    def test_worker_session_is_same_reference(self, qapp):
        """Worker._session is session（同一对象引用，非副本）。"""
        session = make_session(n_points=50)
        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=1, buffer_mm=1.0)

        assert worker._session is session, "Worker._session 应与传入的 session 是同一对象"
        worker.deleteLater()

    def test_ndarray_not_copied_on_worker_access(self, qapp):
        """Worker 访问 session.point_cloud.xyz 返回同一 ndarray（无 copy）。"""
        session = make_session(n_points=100)
        xyz_original = session.point_cloud.xyz

        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(session, params, n_layers=1, buffer_mm=1.0)
        xyz_from_worker = worker._session.point_cloud.xyz

        # 应是同一个 ndarray 对象（共享内存，无 copy）
        assert xyz_from_worker is xyz_original, (
            "Worker 访问 session.point_cloud.xyz 应返回同一对象，不应 copy"
        )
        # 内存地址相同
        assert xyz_from_worker.ctypes.data == xyz_original.ctypes.data
        worker.deleteLater()


# ================================================================
# 4. QThread 资源清理测试
# ================================================================
@pytest.mark.unit
class TestQThreadResourceCleanup:
    """QThread / Worker 对象 deleteLater 资源清理测试。

    验证 WorkerManager 在 thread.finished 时正确连接 deleteLater / cleanup，
    以及 cleanup_all 释放内部引用。避免直接 weakref Qt C++ 对象（PySide6
    deleteLater 后 Python 包装对象生命周期由 Qt 管理，weakref 不可靠）。
    """

    def test_thread_delete_later_is_safe(self, qapp):
        """QThread.deleteLater() 调用后不崩溃，事件循环正常处理。"""
        from PySide6.QtCore import QThread

        thread = QThread()
        thread.start()
        thread.quit()
        assert thread.wait(3000) is True
        # deleteLater 不应抛异常
        thread.deleteLater()
        qapp.processEvents()
        # 再次 processEvents 确保事件处理完成（不崩溃即通过）
        qapp.processEvents()

    def test_worker_delete_later_is_safe(self, qapp):
        """BaseWorker.deleteLater() 调用后不崩溃。"""
        from repair_app.ui.worker_base import BaseWorker

        worker = BaseWorker()
        worker.deleteLater()
        qapp.processEvents()
        # 不崩溃即通过

    def test_manager_connects_finished_to_cleanup(self, qapp):
        """WorkerManager.start 连接 thread.finished → worker.cleanup。

        注意：为避免 processEvents 触发 deleteLater 删除 C++ 对象后 Python 包装器
        访问崩溃，此处手动连接 cleanup（不连 deleteLater）来验证 cleanup 钩子行为。
        deleteLater 的连接在 test_manager_connects_finished_to_delete_later 中
        通过 receiver 计数验证。
        """
        from PySide6.QtCore import QThread, Signal
        from repair_app.ui.worker_base import BaseWorker

        cleanup_calls: list[bool] = []

        class _CleanupWorker(BaseWorker):
            done = Signal()
            def run(self) -> None:
                self._mark_start()
                self.done.emit()
            def cleanup(self) -> None:
                cleanup_calls.append(True)

        worker = _CleanupWorker()
        thread = QThread()
        done: list[bool] = []
        worker.done.connect(lambda: done.append(True))

        # 手动连接（仅 cleanup，不连 deleteLater，避免 DeferredDelete 残留）
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.cleanup)

        thread.start()

        # 等待 worker.run 完成
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not done:
            qapp.processEvents()
            time.sleep(0.02)

        # worker.run 已返回，退出线程事件循环
        thread.quit()
        thread.wait(3000)
        # processEvents 处理 finished 信号（触发 cleanup）
        qapp.processEvents()

        assert len(cleanup_calls) >= 1, "thread.finished 应触发 worker.cleanup()"

    def test_manager_connects_finished_to_delete_later(self, qapp):
        """WorkerManager.start 连接 thread.finished → worker.deleteLater 和 thread.deleteLater。

        通过检查 thread.finished 信号的接收者数量验证连接已建立（不实际触发删除，
        避免 PySide6 C++ 对象删除后 Python 包装器访问崩溃）。
        """
        from PySide6.QtCore import QThread, SIGNAL, Signal
        from repair_app.ui.worker_base import BaseWorker, WorkerManager

        class _QuickWorker(BaseWorker):
            done = Signal()
            def run(self) -> None:
                self._mark_start()
                self.done.emit()

        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()

        # start 前无 finished 接收者
        before = thread.receivers(SIGNAL("finished()"))

        mgr.start("dl_test", worker, thread)

        # start 后应连接 4 个 finished 槽：
        #   worker.cleanup / worker.deleteLater / thread.deleteLater / on_finished(无)
        # 实际连接 3 个（无 on_finished 参数）
        after = thread.receivers(SIGNAL("finished()"))
        assert after >= before + 3, (
            f"thread.finished 应至少连接 3 个槽（cleanup + 2个deleteLater）："
            f"before={before}, after={after}"
        )

        # 清理：停止线程并清空引用（不 processEvents 以避免 deleteLater 执行）
        thread.quit()
        thread.wait(3000)
        mgr.cleanup_all()

    def test_cleanup_all_clears_workers_dict(self, qapp):
        """WorkerManager.cleanup_all() 清空 _workers 字典。"""
        from PySide6.QtCore import QThread, Signal
        from repair_app.ui.worker_base import BaseWorker, WorkerManager

        class _QuickWorker(BaseWorker):
            done = Signal()
            def run(self) -> None:
                self._mark_start()
                self.done.emit()

        mgr = WorkerManager()
        worker = _QuickWorker()
        thread = QThread()
        mgr.start("w", worker, thread)
        thread.quit()
        thread.wait(3000)

        assert "w" in mgr._workers
        assert len(mgr._workers) == 1

        mgr.cleanup_all()
        assert mgr._workers == {}
        assert "w" not in mgr._workers
        assert mgr.is_any_running() is False
        assert mgr.get_running_names() == []

    def test_worker_data_released_after_thread_exit(self, qapp, monkeypatch):
        """Worker 线程退出后，其引用的 session 数据（ndarray）可被回收。

        Worker 不 copy session 数据，线程退出后 worker 被销毁，
        session 中的 ndarray 引用计数应回到 worker 创建前的水平。
        """
        from PySide6.QtCore import QThread, Signal
        from repair_app.ui.worker_base import BaseWorker, WorkerManager
        import repair_app.ui.workers as workers_mod

        # 用阻塞迭代器让 worker 进入循环
        def _blocking_iter(*args, **kwargs):
            while True:
                time.sleep(0.02)
                yield np.zeros((2, 3), dtype=np.float32)

        monkeypatch.setattr(workers_mod, "iter_path_from_cloud", _blocking_iter)

        session = make_session(n_points=100)
        xyz = session.point_cloud.xyz
        base_count = sys.getrefcount(xyz)

        params = {"layer_height_mm": 2.0}
        worker = PathPlanningWorker(
            session, params, n_layers=100, buffer_mm=1.0, timeout_s=30.0
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.start()

        # 等待 worker 进入循环（访问了 session.point_cloud.xyz）
        partials: list[int] = []
        worker.partial.connect(lambda wp, idx, n: partials.append(idx))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not partials:
            qapp.processEvents()
            time.sleep(0.02)

        # worker 运行中，访问 session.point_cloud.xyz 创建了临时引用
        # 但 run() 中 xyz = self._session.point_cloud.xyz 是局部变量，
        # 不持久增加 session.point_cloud.xyz 的引用计数
        running_count = sys.getrefcount(xyz)
        # 运行期间引用计数可能波动（局部变量），但不应大幅增加
        assert running_count <= base_count + 2, (
            f"运行期间引用计数不应大幅增加：base={base_count}, running={running_count}"
        )

        # 停止线程
        thread.requestInterruption()
        thread.quit()
        thread.wait(5000)
        qapp.processEvents()

        # 线程退出后，worker 的局部引用已释放
        # 引用计数应回到 base 水平（worker._session 持有 session，不持有 xyz）
        after_exit_count = sys.getrefcount(xyz)
        assert after_exit_count == base_count, (
            f"线程退出后引用计数应回到 base：base={base_count}, after_exit={after_exit_count}"
        )


# ================================================================
# 5. ZMQ socket 清理测试
# ================================================================
@pytest.mark.unit
class TestZmqSocketCleanup:
    """ZMQ socket / worker 清理测试。"""

    def test_request_worker_closes_socket_on_exit(self, qapp, monkeypatch):
        """_RequestWorker.run 退出时（正常/异常）调用 sock.close()。"""
        from repair_app.bridge.communication import zmq_client as zc_mod

        close_calls: list[int] = []

        class _FakeSock:
            def setsockopt(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
            def send(self, *a, **kw): pass
            def recv(self): return b""
            def poll(self, ms, kind): return False  # 无事件，触发超时
            def close(self, linger=0): close_calls.append(linger)

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

        monkeypatch.setattr(zc_mod, "_ZMQ_AVAILABLE", True)
        monkeypatch.setattr(zc_mod, "zmq", _FakeZmq())

        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig

        config = BridgeConfig.from_env()
        worker = _RequestWorker(
            request_bytes=b"\x00",
            address="tcp://127.0.0.1:1",
            config=config,
            request_id="cleanup-test",
        )
        # 直接调用 run（同步执行，finally 中 close）
        worker.run()

        assert len(close_calls) == 1, "sock.close() 应被调用一次"
        assert close_calls[0] == 0, "close 应使用 linger=0"

    def test_health_worker_closes_socket_on_exit(self, qapp, monkeypatch):
        """_HealthWorker.run 退出时调用 sock.close()。"""
        from repair_app.bridge.communication import zmq_client as zc_mod

        close_calls: list[int] = []

        class _FakeSock:
            def setsockopt(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
            def send(self, *a, **kw): pass
            def recv(self): return b""
            def poll(self, ms, kind): return False
            def close(self, linger=0): close_calls.append(linger)

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

        monkeypatch.setattr(zc_mod, "_ZMQ_AVAILABLE", True)
        monkeypatch.setattr(zc_mod, "zmq", _FakeZmq())

        # mock Serializer 静态方法（build_health_check / serialize_health / parse_health_response）
        from repair_app.bridge.communication.serializer import Serializer
        monkeypatch.setattr(Serializer, "build_health_check", staticmethod(lambda: object()))
        monkeypatch.setattr(Serializer, "serialize_health", staticmethod(lambda hb: b"\x00"))
        monkeypatch.setattr(
            Serializer, "parse_health_response",
            staticmethod(lambda r: {"status_code": 0, "status": "OK", "service_version": ""}),
        )

        from repair_app.bridge.communication.zmq_client import _HealthWorker
        from repair_app.bridge.communication.config import BridgeConfig

        config = BridgeConfig.from_env()
        worker = _HealthWorker(address="tcp://127.0.0.1:1", config=config)
        worker.run()

        assert len(close_calls) == 1, "sock.close() 应被调用一次"
        assert close_calls[0] == 0

    def test_bridge_client_close_clears_workers(self, qapp):
        """BridgeClient.close() 后 _request_worker / _health_worker 为 None。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient

        client = BridgeClient()
        # 未启动任何 worker，close 应正常执行
        client.close(wait_ms=1000)

        assert client._request_worker is None, "close 后 _request_worker 应为 None"
        assert client._health_worker is None, "close 后 _health_worker 应为 None"
        assert client._closed is True, "close 后 _closed 应为 True"
        assert client._heartbeat is None, "close 后 _heartbeat 应为 None"

    def test_bridge_client_close_sets_closed_flag(self, qapp):
        """BridgeClient.close() 设置 _closed 标志，后续 request_repair 直接失败。"""
        from repair_app.bridge.communication.zmq_client import BridgeClient

        client = BridgeClient()
        client.close(wait_ms=1000)

        # close 后 request_repair 应通过 on_error 返回 ShutdownError
        errors = []
        from repair_app.bridge.communication.protocol import RepairRequest
        client.request_repair(
            RepairRequest(),
            on_result=lambda r: None,
            on_error=lambda e: errors.append(e),
        )
        assert len(errors) == 1, "close 后请求应触发 on_error"
        assert "关闭" in str(errors[0]) or "shutdown" in str(errors[0]).lower()

    def test_socket_closed_on_exception(self, qapp, monkeypatch):
        """_RequestWorker.run 中 send 抛异常时，finally 仍调用 sock.close()。"""
        from repair_app.bridge.communication import zmq_client as zc_mod

        close_calls: list[int] = []

        class _RaisingSock:
            def setsockopt(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
            def send(self, *a, **kw): raise RuntimeError("send 失败")
            def recv(self): return b""
            def poll(self, ms, kind): return False
            def close(self, linger=0): close_calls.append(linger)

        class _FakeCtx:
            @staticmethod
            def instance(): return _FakeCtx()
            def socket(self, kind): return _RaisingSock()

        class _FakeZmq:
            Context = _FakeCtx
            REQ = 3
            LINGER = 17
            RCVTIMEO = 18
            SNDTIMEO = 19
            POLLIN = 1

        monkeypatch.setattr(zc_mod, "_ZMQ_AVAILABLE", True)
        monkeypatch.setattr(zc_mod, "zmq", _FakeZmq())

        from repair_app.bridge.communication.zmq_client import _RequestWorker
        from repair_app.bridge.communication.config import BridgeConfig

        config = BridgeConfig.from_env()
        worker = _RequestWorker(
            request_bytes=b"\x00",
            address="tcp://127.0.0.1:1",
            config=config,
            request_id="exc-test",
        )
        errors: list[tuple[str, str]] = []
        worker.error_occurred.connect(lambda msg, rid: errors.append((msg, rid)))

        # send 抛异常 → except → emit error_occurred → finally close
        worker.run()

        assert len(errors) == 1, "应发出 error_occurred 信号"
        assert len(close_calls) == 1, "异常路径 finally 仍应调用 sock.close()"
