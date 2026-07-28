"""Contract and lifecycle tests for the MATLAB realtime pipeline."""

from __future__ import annotations

import socket
import time

import numpy as np

from repair_app.communication.repair_protocol_pb2 import (
    ControlStatus,
    MeshFrameKind,
    ProgressEventType,
    RepairRequest,
)
from repair_app.communication.repair_serialization import (
    build_progress_envelope,
    build_repair_request,
    parse_progress_message,
)
from repair_app.config import schema_loader
from repair_app.ui.progress_subscriber import RealtimeEventBuffer
from repair_app.utils.config import UI_PARAM_SPECS


def test_canonical_ui_parameter_groups_are_present() -> None:
    schema_loader.validate_required_ui_groups()

    grouped_keys = {
        group: {ui_key for _, ui_key, _, _, _, spec_group, _ in UI_PARAM_SPECS
                if spec_group == group}
        for group in schema_loader.REQUIRED_UI_PROCESS_GROUPS
    }

    assert "layer_height" in grouped_keys[schema_loader.PATH_PLANNING_GROUP]
    assert "particle_velocity" in grouped_keys[schema_loader.COLD_SPRAY_GROUP]


def test_matlab_request_contract_remains_flat_protobuf_fields() -> None:
    xyz = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    normals = np.tile(np.asarray([[0.0, 0.0, 1.0]], dtype=np.float32), (3, 1))

    encoded = build_repair_request(
        xyz,
        normals,
        scan_id="contract-test",
        request_id="operation-1",
        particle_velocity_ms=612.0,
        layer_height_mm=1.25,
    ).SerializeToString()

    decoded = RepairRequest()
    decoded.ParseFromString(encoded)

    assert decoded.request_id == "operation-1"
    assert decoded.particle_velocity_ms == 612.0
    assert decoded.layer_height_mm == 1.25
    assert "path_planning" not in decoded.DESCRIPTOR.fields_by_name
    assert "cold_spray" not in decoded.DESCRIPTOR.fields_by_name


def test_v3_preview_snapshot_is_independently_decodable() -> None:
    mesh = b"binary-stl-preview"
    encoded = build_progress_envelope(
        "op-preview",
        ProgressEventType.PROGRESS_TOPO_SNAPSHOT,
        7,
        layer_index=2,
        total_layers=5,
        progress=0.6,
        mesh_data=mesh,
        mesh_frame_kind=MeshFrameKind.MESH_PREVIEW_SNAPSHOT,
        triangle_count=123,
    ).SerializeToString()

    parsed = parse_progress_message(encoded)

    assert parsed["operation_id"] == "op-preview"
    assert parsed["sequence_number"] == 7
    assert parsed["partial_mesh_data"] == mesh
    assert parsed["mesh_triangle_count"] == 123
    assert parsed["mesh_frame_kind"] == MeshFrameKind.MESH_PREVIEW_SNAPSHOT


def _stats_for(parsed: dict) -> dict:
    return {
        "elapsed_s": 0.0,
        "layer_index": parsed.get("layer_index", 0),
        "total_layers": parsed.get("total_layers", 0),
        "waypoint_count": len(parsed.get("waypoints", [])),
        "mesh_triangle_count": parsed.get("mesh_triangle_count", 0),
        "progress": parsed.get("progress", 0.0),
        "stage_name": parsed.get("stage_name", ""),
        "message": parsed.get("message", ""),
    }


def test_realtime_buffer_coalesces_mesh_but_preserves_path_layers_and_terminal() -> None:
    buffer = RealtimeEventBuffer()
    buffer.begin_operation("op-buffer")

    for sequence, mesh in ((1, b"old"), (2, b"new")):
        parsed = parse_progress_message(
            build_progress_envelope(
                "op-buffer",
                ProgressEventType.PROGRESS_TOPO_SNAPSHOT,
                sequence,
                mesh_data=mesh,
                mesh_frame_kind=MeshFrameKind.MESH_PREVIEW_SNAPSHOT,
            ).SerializeToString()
        )
        assert buffer.accept(parsed, _stats_for(parsed))

    for sequence, layer in ((3, 1), (4, 2)):
        points = np.asarray([[layer, 0, 0, 0, 0, 1, 100]], dtype=np.float32)
        parsed = parse_progress_message(
            build_progress_envelope(
                "op-buffer",
                ProgressEventType.PROGRESS_PATH_LAYER_READY,
                sequence,
                layer_index=layer,
                total_layers=2,
                waypoints=points,
            ).SerializeToString()
        )
        assert buffer.accept(parsed, _stats_for(parsed))

    terminal = parse_progress_message(
        build_progress_envelope(
            "op-buffer",
            ProgressEventType.PROGRESS_COMPLETED,
            5,
            message="done",
        ).SerializeToString()
    )
    assert buffer.accept(terminal, _stats_for(terminal))

    drained = buffer.drain()
    assert drained["mesh"] == b"new"
    assert [item["layer_index"] for item in drained["path_layers"]] == [1, 2]
    assert len(drained["terminal_events"]) == 1


def test_realtime_buffer_discards_old_sequence_and_operation() -> None:
    buffer = RealtimeEventBuffer()
    buffer.begin_operation("current")
    current = parse_progress_message(
        build_progress_envelope(
            "current", ProgressEventType.PROGRESS_TOPO_SNAPSHOT, 2
        ).SerializeToString()
    )
    old_sequence = parse_progress_message(
        build_progress_envelope(
            "current", ProgressEventType.PROGRESS_TOPO_SNAPSHOT, 1
        ).SerializeToString()
    )
    old_operation = parse_progress_message(
        build_progress_envelope(
            "old", ProgressEventType.PROGRESS_TOPO_SNAPSHOT, 3
        ).SerializeToString()
    )

    assert buffer.accept(current, _stats_for(current))
    assert not buffer.accept(old_sequence, _stats_for(old_sequence))
    assert not buffer.accept(old_operation, _stats_for(old_operation))


def test_heartbeat_never_invalidates_queued_payload_sequence() -> None:
    buffer = RealtimeEventBuffer()
    buffer.begin_operation("op-heartbeat")

    heartbeat = parse_progress_message(
        build_progress_envelope(
            "op-heartbeat",
            ProgressEventType.PROGRESS_HEARTBEAT,
            999,
        ).SerializeToString()
    )
    first_payload = parse_progress_message(
        build_progress_envelope(
            "op-heartbeat",
            ProgressEventType.PROGRESS_PATH_LAYER_READY,
            1,
            layer_index=1,
            waypoints=np.asarray([[1, 0, 0, 0, 0, 1, 100]], dtype=np.float32),
        ).SerializeToString()
    )

    assert buffer.accept(heartbeat, _stats_for(heartbeat))
    assert buffer.accept(first_payload, _stats_for(first_payload))
    drained = buffer.drain()
    assert drained["heartbeat"] is True
    assert [item["layer_index"] for item in drained["path_layers"]] == [1]


def test_publisher_heartbeats_are_outside_payload_sequence() -> None:
    from repair_app.bridge.progress_publisher import ProgressPublisher

    publisher = ProgressPublisher("inproc://unused-heartbeat-test")
    publisher._active_operation_id = "op-heartbeat"
    parsed = parse_progress_message(publisher._build_heartbeat())

    assert parsed["is_heartbeat"] is True
    assert parsed["sequence_number"] == 0
    assert publisher._sequence_by_operation.get("op-heartbeat", 0) == 0


def _free_tcp_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"tcp://127.0.0.1:{port}"


def test_cancel_control_roundtrip_is_idempotent() -> None:
    from repair_app.bridge.operation_control import (
        CancellationControlServer,
        begin_operation,
        finish_operation,
        request_cancel,
    )

    address = _free_tcp_address()
    server = CancellationControlServer(address)
    assert server.start()
    begin_operation("cancel-op")
    try:
        request_id = "cancel-request-1"
        first = request_cancel(
            "cancel-op",
            address=address,
            timeout_ms=1000,
            request_id=request_id,
        )
        duplicate = request_cancel(
            "cancel-op",
            address=address,
            timeout_ms=1000,
            request_id=request_id,
        )
        assert first.status == ControlStatus.CONTROL_ACCEPTED
        assert duplicate.status == ControlStatus.CONTROL_DUPLICATE
    finally:
        finish_operation("cancel-op", "cancelled")
        server.stop()


def test_cancelling_remains_busy_until_terminal_confirmation(qapp) -> None:
    from repair_app.ui.compute_controller import ComputeController, OperationState

    controller = ComputeController(project_root="/unused")
    controller._state = OperationState.RUNNING
    controller._busy = True
    assert controller._transition(OperationState.CANCELLING)
    assert controller.is_busy()

    controller._on_progress_terminal({
        "operation_id": controller.operation_id,
        "event_name": "PROGRESS_CANCELLED",
    })
    assert controller.state == OperationState.CANCELLED
    assert not controller.is_busy()


def test_successful_result_wins_late_cancel_race(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from repair_app.bridge import operation_control
    from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
    from repair_app.communication.repair_protocol_pb2 import RepairStatusCode

    operation_id = "op-success-cancel-race"
    request = build_repair_request(
        np.asarray(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            dtype=np.float32,
        ),
        np.asarray(
            [[0, 0, 1], [0, 0, 1], [0, 0, 1]],
            dtype=np.float32,
        ),
        scan_id="cancel-race",
        request_id=operation_id,
    )
    adapter = MatlabAdapter.__new__(MatlabAdapter)
    adapter._realtime_ready = True
    adapter._progress_publisher = MagicMock()

    def finish_while_cancel_arrives(_xyz, _meta):
        operation_control._REGISTRY.request_cancel(operation_id, "late-cancel")
        return {
            "waypoints": np.asarray(
                [[0, 0, 0, 0, 0, 1, 100]],
                dtype=np.float32,
            ),
            "predicted_volume_mm3": 1.0,
            "estimated_mass_g": 0.01,
            "estimated_time_s": 1.0,
            "uniformity": 0.9,
            "layer_profiles": [],
            "particle_dist": None,
            "mesh_data": b"",
            "mesh_format": "",
            "warnings": [],
        }

    monkeypatch.setattr(
        adapter,
        "_invoke_pipeline_with_fallback",
        finish_while_cancel_arrives,
    )

    result = adapter.handle_repair(request)

    assert result.status_code == RepairStatusCode.SUCCESS
    terminal_call = adapter._progress_publisher.publish_terminal.call_args
    assert terminal_call.args[1] == ProgressEventType.PROGRESS_COMPLETED


def test_matlab_realtime_scripts_use_pyargs_throttle_and_cancel_checks() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path_code = (root / "path_planning" / "run_path_planning.m").read_text(
        encoding="utf-8"
    )
    morphology_code = (
        root / "profile_prediction" / "run_profile_prediction.m"
    ).read_text(encoding="utf-8")

    assert "publish_progress(pyargs(" in path_code
    assert "is_cancel_requested" in path_code
    assert "preview_interval_s" in morphology_code
    assert "MESH_PREVIEW_SNAPSHOT" in morphology_code
    assert "assert_not_cancelled" in morphology_code
