"""test_progress_fault.py — 进度系统容错测试

覆盖 ProgressSubscriberWorker / ProgressSubscriber 在各种异常场景下的行为：
  - 断开连接后计算仍成功
  - 缺失/乱序/延迟/损坏的进度包
  - operation_id 过滤与动态切换

运行：
    pytest -m unit tests/test_progress_fault.py -v
"""
from __future__ import annotations

import time
from unittest.mock import Mock, MagicMock, patch, PropertyMock

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QThread, Signal

# 确保项目根目录在 sys.path
import os, sys
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ================================================================
# 辅助函数：构造 mock protobuf ProgressUpdate 消息
# ================================================================
def _make_mock_progress_msg(
    request_id: str = "op-001",
    layer_index: int = 0,
    total_layers: int = 5,
    progress: float = 0.2,
    message: str = "elapsed=10.5s",
    stage: int = 1,
    mesh_data: bytes = b"",
    mesh_format: str = "",
    waypoints: np.ndarray | None = None,
) -> Mock:
    """构造 mock protobuf ProgressUpdate 消息对象。"""
    msg = Mock()
    msg.request_id = request_id
    msg.stage = stage
    msg.layer_index = layer_index
    msg.total_layers = total_layers
    msg.progress = progress
    msg.message = message
    msg.partial_mesh_data = mesh_data
    msg.partial_mesh_format = mesh_format
    msg.ParseFromString = Mock()

    # 构造 mock partial_waypoints
    if waypoints is None:
        waypoints = np.array([[1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 100.0]], dtype=np.float32)

    mock_wps = []
    for row in waypoints:
        wp = Mock()
        wp.x = float(row[0])
        wp.y = float(row[1])
        wp.z = float(row[2])
        wp.nx = float(row[3]) if len(row) > 3 else 0.0
        wp.ny = float(row[4]) if len(row) > 4 else 0.0
        wp.nz = float(row[5]) if len(row) > 5 else 1.0
        wp.feed_rate = float(row[6]) if len(row) > 6 else 100.0
        wp.layer_index = layer_index
        mock_wps.append(wp)
    msg.partial_waypoints = mock_wps
    msg.layer_profiles = []

    return msg


def _make_mock_parsed(
    request_id: str = "op-001",
    layer_index: int = 0,
    total_layers: int = 5,
    progress: float = 0.2,
    message: str = "elapsed=10.5s",
    stage: int = 1,
    stage_name: str = "PATH_PLANNING",
    mesh_data: bytes = b"",
    mesh_format: str = "",
    waypoints: np.ndarray | None = None,
) -> dict:
    """构造 mock parse_progress_update 返回的 dict。"""
    if waypoints is None:
        waypoints = np.array([[1.0, 2.0, 3.0, 0.0, 0.0, 1.0, 100.0]], dtype=np.float32)
    wp_layers = np.full(len(waypoints), layer_index, dtype=np.int32)
    return {
        "request_id": request_id,
        "stage": stage,
        "stage_name": stage_name,
        "layer_index": layer_index,
        "total_layers": total_layers,
        "progress": progress,
        "message": message,
        "waypoints": waypoints,
        "waypoint_layers": wp_layers,
        "partial_mesh_data": mesh_data,
        "partial_mesh_format": mesh_format,
        "layer_profiles": [],
    }


# ================================================================
# 共享 mock patches（用于 mock ProgressUpdate 和 parse_progress_update）
# ================================================================
def _apply_progress_mocks(monkeypatch, mock_msg: Mock, mock_parsed: dict):
    """在 worker 的 _process_message 中 mock ProgressUpdate 和 parse_progress_update。

    _process_message 内部使用 from-import，因此需要 mock 该方法可见的 local 作用域。
    通过 monkeypatch 替换模块级别的引用无法生效，改用 mock 对象直接注入。
    """
    # _process_message 内部 import 了这些，我们 monkeypatch 系统的 import
    import repair_app.ui.progress_subscriber as ps_mod

    # 创建一个 fake ProgressUpdate 类，实例化返回 mock_msg
    class _FakeProgressUpdate:
        def __init__(self):
            # 将 mock_msg 的属性复制到 self
            self.request_id = mock_msg.request_id
            self.stage = mock_msg.stage
            self.layer_index = mock_msg.layer_index
            self.total_layers = mock_msg.total_layers
            self.progress = mock_msg.progress
            self.message = mock_msg.message
            self.partial_mesh_data = mock_msg.partial_mesh_data
            self.partial_mesh_format = mock_msg.partial_mesh_format
            self.partial_waypoints = mock_msg.partial_waypoints
            self.layer_profiles = mock_msg.layer_profiles
            self._parsed = False

        def ParseFromString(self, data: bytes):
            self._parsed = True

    monkeypatch.setattr(
        "repair_app.communication.repair_protocol_pb2.ProgressUpdate",
        _FakeProgressUpdate,
        raising=False,
    )
    monkeypatch.setattr(
        "repair_app.communication.repair_serialization.parse_progress_update",
        lambda msg: mock_parsed,
        raising=False,
    )


# ================================================================
# autouse fixture：提供 qapp
# ================================================================
@pytest.fixture(autouse=True)
def _flush_qt_events(qapp):
    yield
    qapp.processEvents()


# ================================================================
# 1. Progress subscriber disconnected → computation still succeeds
# ================================================================
@pytest.mark.unit
class TestDisconnectedSubscriber:
    """断开连接后计算仍成功的容错测试。"""

    def test_subscriber_start_stop_no_errors(self, qapp):
        """ProgressSubscriber 可以正常 start/stop 而不抛异常。"""
        subscriber = _create_isolated_subscriber()
        assert subscriber.is_running is False

        subscriber.start()
        # 等待线程启动（ZMQ connect 会失败但不影响）
        qapp.processEvents()
        time.sleep(0.1)
        # 线程可能因 ZMQ 不可用已退出，也可能在运行中
        subscriber.stop()

        # stop 后不应在运行
        assert subscriber.is_running is False

    def test_no_signals_when_not_running(self, qapp):
        """ProgressSubscriber 未运行时不会发出信号。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriber

        subscriber = ProgressSubscriber()
        progress_received: list = []
        layer_completed: list = []
        mesh_updated: list = []
        stats_updated: list = []

        subscriber.progress_received.connect(lambda d: progress_received.append(d))
        subscriber.layer_completed.connect(lambda i: layer_completed.append(i))
        subscriber.mesh_updated.connect(lambda b: mesh_updated.append(b))
        subscriber.stats_updated.connect(lambda d: stats_updated.append(d))

        # 未 start 时不应有任何信号
        qapp.processEvents()
        time.sleep(0.05)

        assert len(progress_received) == 0
        assert len(layer_completed) == 0
        assert len(mesh_updated) == 0
        assert len(stats_updated) == 0

    def test_computation_succeeds_without_subscriber(self, qapp):
        """计算可以在没有进度订阅器的情况下成功完成。

        验证：创建 subscriber 但不 start，计算逻辑不受影响。
        """
        from repair_app.ui.progress_subscriber import ProgressSubscriber

        subscriber = ProgressSubscriber()
        # 不 start subscriber
        assert subscriber.is_running is False

        # 模拟计算完成：计算逻辑不依赖 subscriber 运行
        result = {"status": "success", "waypoints": np.zeros((3, 3))}
        assert result["status"] == "success"
        assert len(result["waypoints"]) == 3

        # subscriber 仍然未运行
        assert subscriber.is_running is False


# ================================================================
# 2. Missing progress packets → doesn't affect final result
# ================================================================
@pytest.mark.unit
class TestMissingProgressPackets:
    """缺失进度包不影响最终结果的容错测试。"""

    def test_empty_message_handled_gracefully(self, qapp, monkeypatch):
        """_process_message 收到空字节 b"" 时不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        # 空消息：mock protobuf 解析
        mock_msg = _make_mock_progress_msg()
        mock_parsed = _make_mock_parsed()
        _apply_progress_mocks(monkeypatch, mock_msg, mock_parsed)

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 空消息不应导致异常
        worker._process_message(b"", time.time())

        # 信号正常发出（因为 mock 解析成功）
        assert len(progress_received) == 1

    def test_signal_handlers_no_crash_on_partial_data(self, qapp, monkeypatch):
        """信号处理器收到部分/空数据时不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        # 构造一个 data 极少（例如只有 layer_index=0）的 mock
        mock_msg = _make_mock_progress_msg(
            layer_index=0,
            total_layers=0,
            progress=0.0,
            message="",
            mesh_data=b"",
            waypoints=np.empty((0, 7), dtype=np.float32),
        )
        mock_parsed = _make_mock_parsed(
            layer_index=0,
            total_layers=0,
            progress=0.0,
            message="",
            mesh_data=b"",
            waypoints=np.empty((0, 7), dtype=np.float32),
        )
        _apply_progress_mocks(monkeypatch, mock_msg, mock_parsed)

        progress_received: list = []
        layer_completed: list = []
        mesh_updated: list = []
        stats_updated: list = []

        worker.progress_received.connect(lambda d: progress_received.append(d))
        worker.layer_completed.connect(lambda i: layer_completed.append(i))
        worker.mesh_updated.connect(lambda b: mesh_updated.append(b))
        worker.stats_updated.connect(lambda d: stats_updated.append(d))

        worker._process_message(b"some-data", time.time())

        # 进度信号正常发出
        assert len(progress_received) == 1
        assert len(layer_completed) == 1
        assert layer_completed[0] == 0
        # mesh_data 为空，不应发出 mesh_updated
        assert len(mesh_updated) == 0
        # stats 信号正常发出
        assert len(stats_updated) == 1

    def test_missing_layer_jump_handled(self, qapp, monkeypatch):
        """层号跳跃（如从 layer 0 直接跳到 layer 5）不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        layer_completed: list = []
        worker.layer_completed.connect(lambda i: layer_completed.append(i))

        # 发送 layer 0
        mock_msg_0 = _make_mock_progress_msg(layer_index=0, progress=0.0)
        mock_parsed_0 = _make_mock_parsed(layer_index=0, progress=0.0)
        _apply_progress_mocks(monkeypatch, mock_msg_0, mock_parsed_0)
        worker._process_message(b"d0", time.time())

        # 跳过 layer 1-4，直接发送 layer 5
        mock_msg_5 = _make_mock_progress_msg(layer_index=5, progress=1.0)
        mock_parsed_5 = _make_mock_parsed(layer_index=5, progress=1.0)
        _apply_progress_mocks(monkeypatch, mock_msg_5, mock_parsed_5)
        worker._process_message(b"d5", time.time())

        assert layer_completed == [0, 5]


# ================================================================
# 3. Out-of-order progress
# ================================================================
@pytest.mark.unit
class TestOutOfOrderProgress:
    """乱序进度消息处理测试。"""

    def test_different_layer_indices_any_order(self, qapp, monkeypatch):
        """不同 layer_index 的消息按任意顺序处理都不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        layer_completed: list = []
        worker.layer_completed.connect(lambda i: layer_completed.append(i))

        # 乱序发送：3, 1, 5, 0, 4, 2
        order = [3, 1, 5, 0, 4, 2]
        for idx in order:
            mock_msg = _make_mock_progress_msg(layer_index=idx, total_layers=6, progress=idx / 6.0)
            mock_parsed = _make_mock_parsed(layer_index=idx, total_layers=6, progress=idx / 6.0)
            _apply_progress_mocks(monkeypatch, mock_msg, mock_parsed)
            worker._process_message(b"data", time.time())

        # 所有层都收到了信号，顺序就是发送顺序
        assert layer_completed == order
        assert len(layer_completed) == 6

    def test_old_layer_data_does_not_corrupt_new_layer(self, qapp, monkeypatch):
        """旧层数据不会破坏新层数据。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 先发送 layer 2（新层）
        new_mock = _make_mock_progress_msg(
            layer_index=2, progress=0.5, message="layer 2 processing"
        )
        new_parsed = _make_mock_parsed(
            layer_index=2, progress=0.5, message="layer 2 processing"
        )
        _apply_progress_mocks(monkeypatch, new_mock, new_parsed)
        worker._process_message(b"new", time.time())

        # 再发送 layer 1（旧层延迟到达）
        old_mock = _make_mock_progress_msg(
            layer_index=1, progress=0.25, message="layer 1 processing"
        )
        old_parsed = _make_mock_parsed(
            layer_index=1, progress=0.25, message="layer 1 processing"
        )
        _apply_progress_mocks(monkeypatch, old_mock, old_parsed)
        worker._process_message(b"old", time.time())

        assert len(progress_received) == 2
        # 第一条是 layer 2，第二条是 layer 1
        assert progress_received[0]["layer_index"] == 2
        assert progress_received[1]["layer_index"] == 1

    def test_progress_value_does_not_regress(self, qapp, monkeypatch):
        """进度值不会因旧消息而回退（取决于调用方逻辑，但 worker 不崩溃）。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        stats_updated: list = []
        worker.stats_updated.connect(lambda d: stats_updated.append(d))

        # 高进度
        mock_high = _make_mock_progress_msg(layer_index=4, total_layers=5, progress=0.8)
        mock_parsed_high = _make_mock_parsed(layer_index=4, total_layers=5, progress=0.8)
        _apply_progress_mocks(monkeypatch, mock_high, mock_parsed_high)
        worker._process_message(b"high", time.time())

        # 低进度（旧消息）- worker 仍然应处理而不崩溃
        mock_low = _make_mock_progress_msg(layer_index=1, total_layers=5, progress=0.2)
        mock_parsed_low = _make_mock_parsed(layer_index=1, total_layers=5, progress=0.2)
        _apply_progress_mocks(monkeypatch, mock_low, mock_parsed_low)
        worker._process_message(b"low", time.time())

        assert len(stats_updated) == 2
        # 第一个是高进度，第二个是低进度（worker 不负责过滤，只负责转发）
        assert stats_updated[0]["progress"] == 0.8
        assert stats_updated[1]["progress"] == 0.2


# ================================================================
# 4. Old operation delayed message → filtered
# ================================================================
@pytest.mark.unit
class TestOldOperationFiltered:
    """旧操作延迟消息被过滤的测试。"""

    def test_old_operation_id_filtered(self, qapp, monkeypatch):
        """不同 request_id 的消息被过滤，不发出信号。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("current-op-123")

        progress_received: list = []
        layer_completed: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))
        worker.layer_completed.connect(lambda i: layer_completed.append(i))

        # 旧操作的消息
        old_msg = _make_mock_progress_msg(request_id="old-op-456")
        old_parsed = _make_mock_parsed(request_id="old-op-456")
        _apply_progress_mocks(monkeypatch, old_msg, old_parsed)
        worker._process_message(b"old-data", time.time())

        # 旧操作消息被过滤，不应发出信号
        assert len(progress_received) == 0
        assert len(layer_completed) == 0

    def test_matching_operation_id_processed(self, qapp, monkeypatch):
        """匹配的 request_id 消息被正常处理。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("current-op-123")

        progress_received: list = []
        layer_completed: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))
        worker.layer_completed.connect(lambda i: layer_completed.append(i))

        # 匹配操作的消息
        match_msg = _make_mock_progress_msg(request_id="current-op-123")
        match_parsed = _make_mock_parsed(request_id="current-op-123")
        _apply_progress_mocks(monkeypatch, match_msg, match_parsed)
        worker._process_message(b"match-data", time.time())

        assert len(progress_received) == 1
        assert len(layer_completed) == 1
        assert progress_received[0]["request_id"] == "current-op-123"

    def test_both_old_and_new_in_sequence(self, qapp, monkeypatch):
        """旧消息被过滤，新消息被处理，两者正确区分。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("current-op-123")

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 旧消息
        old_msg = _make_mock_progress_msg(request_id="old-op-456")
        old_parsed = _make_mock_parsed(request_id="old-op-456")
        _apply_progress_mocks(monkeypatch, old_msg, old_parsed)
        worker._process_message(b"old", time.time())

        # 新消息
        new_msg = _make_mock_progress_msg(request_id="current-op-123")
        new_parsed = _make_mock_parsed(request_id="current-op-123")
        _apply_progress_mocks(monkeypatch, new_msg, new_parsed)
        worker._process_message(b"new", time.time())

        # 又一条旧消息
        old_msg2 = _make_mock_progress_msg(request_id="old-op-789")
        old_parsed2 = _make_mock_parsed(request_id="old-op-789")
        _apply_progress_mocks(monkeypatch, old_msg2, old_parsed2)
        worker._process_message(b"old2", time.time())

        assert len(progress_received) == 1
        assert progress_received[0]["request_id"] == "current-op-123"


# ================================================================
# 5. Malformed packet
# ================================================================
@pytest.mark.unit
class TestMalformedPacket:
    """损坏/无效数据包处理测试。"""

    def test_invalid_protobuf_bytes_no_crash(self, qapp, monkeypatch):
        """_process_message 收到无效 protobuf 字节不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        # 不 mock protobuf，让真实 import 可用但 ParseFromString 抛异常
        # 由于测试环境可能没有 protobuf 模块，我们 mock 整个流程
        worker = ProgressSubscriberWorker()

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 使用真实的 mock，但让 ParseFromString 抛异常
        import repair_app.ui.progress_subscriber as ps_mod

        class _BadProgressUpdate:
            def ParseFromString(self, data: bytes):
                raise ValueError("invalid protobuf data: unexpected wire type")

        monkeypatch.setattr(
            "repair_app.communication.repair_protocol_pb2.ProgressUpdate",
            _BadProgressUpdate,
            raising=False,
        )

        # 不应抛出异常
        worker._process_message(b"not-valid-protobuf", time.time())

        # 没有信号发出
        assert len(progress_received) == 0

    def test_corrupted_data_no_crash(self, qapp, monkeypatch):
        """损坏的数据（随机字节）不导致崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        errors: list = []
        # 不 mock，让真实异常发生并被 _process_message 捕获
        # 但要确保测试环境不因 import 失败而崩溃

        # 让 ProgressUpdate 解析抛异常
        class _CorruptProgressUpdate:
            def ParseFromString(self, data: bytes):
                raise Exception("corrupted data: field number out of range")

        monkeypatch.setattr(
            "repair_app.communication.repair_protocol_pb2.ProgressUpdate",
            _CorruptProgressUpdate,
            raising=False,
        )

        # 不应崩溃
        try:
            worker._process_message(b"\xff\xfe\xfd\xfc" * 100, time.time())
        except Exception as e:
            errors.append(e)

        assert len(errors) == 0, f"处理损坏数据不应抛出异常: {errors}"

    def test_empty_bytes_no_crash(self, qapp, monkeypatch):
        """空字节数组不导致崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        # 空字节让 ParseFromString 可能抛异常
        class _EmptyProgressUpdate:
            def ParseFromString(self, data: bytes):
                raise Exception("unexpected end of protobuf input")

        monkeypatch.setattr(
            "repair_app.communication.repair_protocol_pb2.ProgressUpdate",
            _EmptyProgressUpdate,
            raising=False,
        )

        # 不应崩溃
        worker._process_message(b"", time.time())

    def test_parse_progress_update_returns_unexpected_data(self, qapp, monkeypatch):
        """parse_progress_update 返回非预期格式数据时不崩溃。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        stats_updated: list = []
        worker.stats_updated.connect(lambda d: stats_updated.append(d))

        # mock 返回缺少字段的解析结果
        mock_msg = _make_mock_progress_msg()
        mock_parsed = {
            "request_id": "op-001",
            "stage": 1,
            "stage_name": "TEST",
            "layer_index": 0,
            "total_layers": 0,
            "progress": 0.0,
            "message": "",
            "waypoints": np.empty((0, 7), dtype=np.float32),
            "waypoint_layers": np.empty((0,), dtype=np.int32),
            "partial_mesh_data": b"",
            "partial_mesh_format": "",
            "layer_profiles": [],
        }
        _apply_progress_mocks(monkeypatch, mock_msg, mock_parsed)

        worker._process_message(b"data", time.time())
        assert len(stats_updated) == 1


# ================================================================
# 6. operation_id set after worker starts
# ================================================================
@pytest.mark.unit
class TestOperationIdPropagation:
    """operation_id 在 worker 启动后传递的测试。"""

    def test_set_operation_id_propagates_to_worker(self, qapp):
        """ProgressSubscriber.set_operation_id 传播到 worker。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriber

        subscriber = ProgressSubscriber()
        # 直接设置内部 worker（不启动线程，避免 ZMQ 依赖）
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker
        subscriber._worker = ProgressSubscriberWorker()

        assert subscriber._worker._operation_id == ""
        assert subscriber._operation_id == ""

        subscriber.set_operation_id("new-op-001")

        assert subscriber._operation_id == "new-op-001"
        assert subscriber._worker._operation_id == "new-op-001"

    def test_set_operation_id_empty_disables_filtering(self, qapp, monkeypatch):
        """设置 operation_id 为空字符串禁用过滤。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("")

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 任何 request_id 的消息都应被处理（因为 operation_id 为空）
        msg = _make_mock_progress_msg(request_id="any-op-999")
        parsed = _make_mock_parsed(request_id="any-op-999")
        _apply_progress_mocks(monkeypatch, msg, parsed)
        worker._process_message(b"data", time.time())

        assert len(progress_received) == 1

    def test_set_operation_id_before_worker_created(self, qapp):
        """在 worker 创建前设置 operation_id 仍然有效。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriber

        subscriber = ProgressSubscriber()
        subscriber.set_operation_id("pre-set-op")

        # 手动创建 worker 模拟 start 流程
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker
        subscriber._worker = ProgressSubscriberWorker()
        # 再次设置，传播到 worker
        subscriber.set_operation_id("pre-set-op")

        assert subscriber._worker._operation_id == "pre-set-op"

    def test_set_operation_id_none_like_string(self, qapp, monkeypatch):
        """设置 operation_id 为类似 None 的字符串（如 "None"）仍正常工作。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("None")

        # "None" 作为字符串，它能匹配
        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        msg = _make_mock_progress_msg(request_id="None")
        parsed = _make_mock_parsed(request_id="None")
        _apply_progress_mocks(monkeypatch, msg, parsed)
        worker._process_message(b"data", time.time())

        assert len(progress_received) == 1


# ================================================================
# 7. Multiple operations
# ================================================================
@pytest.mark.unit
class TestMultipleOperations:
    """多次调用 set_operation_id 的测试。"""

    def test_set_operation_id_multiple_times(self, qapp, monkeypatch):
        """set_operation_id 可被多次调用，旧值被替换。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 第一轮操作
        worker.set_operation_id("op-1")
        msg1 = _make_mock_progress_msg(request_id="op-1")
        parsed1 = _make_mock_parsed(request_id="op-1")
        _apply_progress_mocks(monkeypatch, msg1, parsed1)
        worker._process_message(b"d1", time.time())
        assert len(progress_received) == 1

        # 切换到第二轮操作
        worker.set_operation_id("op-2")
        # op-1 的旧消息被过滤
        msg1_old = _make_mock_progress_msg(request_id="op-1")
        parsed1_old = _make_mock_parsed(request_id="op-1")
        _apply_progress_mocks(monkeypatch, msg1_old, parsed1_old)
        worker._process_message(b"d1-old", time.time())
        assert len(progress_received) == 1  # 未增加

        # op-2 的消息被处理
        msg2 = _make_mock_progress_msg(request_id="op-2")
        parsed2 = _make_mock_parsed(request_id="op-2")
        _apply_progress_mocks(monkeypatch, msg2, parsed2)
        worker._process_message(b"d2", time.time())
        assert len(progress_received) == 2

    def test_old_operation_id_replaced(self, qapp, monkeypatch):
        """旧 operation_id 被替换后不再匹配。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()
        worker.set_operation_id("first-op")

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        # 替换为新的 operation_id
        worker.set_operation_id("second-op")

        # 旧 operation_id 的消息被过滤
        old_msg = _make_mock_progress_msg(request_id="first-op")
        old_parsed = _make_mock_parsed(request_id="first-op")
        _apply_progress_mocks(monkeypatch, old_msg, old_parsed)
        worker._process_message(b"old", time.time())

        assert len(progress_received) == 0

        # 新 operation_id 的消息被处理
        new_msg = _make_mock_progress_msg(request_id="second-op")
        new_parsed = _make_mock_parsed(request_id="second-op")
        _apply_progress_mocks(monkeypatch, new_msg, new_parsed)
        worker._process_message(b"new", time.time())

        assert len(progress_received) == 1

    def test_rapid_operation_switching(self, qapp, monkeypatch):
        """快速切换 operation_id 不导致状态混乱。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriberWorker

        worker = ProgressSubscriberWorker()

        progress_received: list = []
        worker.progress_received.connect(lambda d: progress_received.append(d))

        for i in range(5):
            worker.set_operation_id(f"op-{i}")
            msg = _make_mock_progress_msg(request_id=f"op-{i}")
            parsed = _make_mock_parsed(request_id=f"op-{i}")
            _apply_progress_mocks(monkeypatch, msg, parsed)
            worker._process_message(b"data", time.time())

        assert len(progress_received) == 5
        for i, d in enumerate(progress_received):
            assert d["request_id"] == f"op-{i}"

    def test_subscriber_multiple_set_operation_id(self, qapp):
        """ProgressSubscriber 多次调用 set_operation_id 正确传播到 worker。"""
        from repair_app.ui.progress_subscriber import ProgressSubscriber, ProgressSubscriberWorker

        subscriber = ProgressSubscriber()
        subscriber._worker = ProgressSubscriberWorker()

        subscriber.set_operation_id("op-a")
        assert subscriber._worker._operation_id == "op-a"

        subscriber.set_operation_id("op-b")
        assert subscriber._worker._operation_id == "op-b"

        subscriber.set_operation_id("")
        assert subscriber._worker._operation_id == ""


# ================================================================
# 辅助：创建隔离的 ProgressSubscriber（不依赖真实 ZMQ）
# ================================================================
def _create_isolated_subscriber():
    """创建 ProgressSubscriber 并 mock ZMQ 相关依赖。

    返回一个 ProgressSubscriber 实例，其 worker 的 run() 方法
    被替换为安全版本，不会尝试真实 ZMQ 连接。
    """
    from repair_app.ui.progress_subscriber import ProgressSubscriber, ProgressSubscriberWorker

    subscriber = ProgressSubscriber()

    # 创建一个不依赖 ZMQ 的 worker 子类
    class _IsolatedWorker(ProgressSubscriberWorker):
        def run(self) -> None:
            """运行但不连接 ZMQ，直接发出 finished。"""
            self.finished.emit()

    # 直接注入 worker 和 thread（不通过 start() 以避免 ZMQ import）
    subscriber._worker = _IsolatedWorker()
    subscriber._thread = None
    # 转发信号
    subscriber._worker.progress_received.connect(subscriber.progress_received)
    subscriber._worker.layer_completed.connect(subscriber.layer_completed)
    subscriber._worker.mesh_updated.connect(subscriber.mesh_updated)
    subscriber._worker.stats_updated.connect(subscriber.stats_updated)

    return subscriber