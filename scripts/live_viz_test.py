"""Live MATLAB R2025b visualization integration test.

Exercises the full chain: -> ZeroMQ(5555) -> Protobuf v2.1
-> matlab_bridge_server -> MatlabAdapter (new viz fields) -> back.

Uses a direct synchronous ZMQ REQ socket (no Qt event loop dependency),
mirroring what BridgeClient does internally but blocking.

Run: python scripts/live_viz_test.py
"""
from __future__ import annotations
import sys
import time

import numpy as np
import zmq

from repair_app.communication.repair_serialization import (
    build_repair_request,
    parse_repair_result,
)
from repair_app.communication.repair_protocol_pb2 import RepairResult


def _send_recv(req_bytes: bytes, timeout_ms: int = 15000) -> bytes:
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.connect("tcp://127.0.0.1:5555")
    try:
        sock.send(req_bytes)
        return sock.recv()
    finally:
        sock.close()


def main() -> int:
    rng = np.random.default_rng(42)
    xyz = rng.uniform(-20, 20, (500, 3)).astype(np.float32)
    xyz[:, 2] = np.abs(xyz[:, 2])
    nrm = np.zeros_like(xyz)
    nrm[:, 2] = 1.0
    req = build_repair_request(
        xyz, nrm, material="STEEL_316L", max_layers=6,
        scan_id="vis-live", request_id="live-1",
    )

    t0 = time.time()
    resp_bytes = _send_recv(req.SerializeToString())
    elapsed_ms = int((time.time() - t0) * 1000)

    result_msg = RepairResult()
    result_msg.ParseFromString(resp_bytes)
    r = parse_repair_result(result_msg)
    print("=== LIVE MATLAB R2025b VISUALIZATION TEST ===")
    print("status            =", r["status_name"])
    print("waypoints         =", len(r["waypoints"]))
    print("estimated_mass_g  =", round(r["estimated_mass_g"], 4))
    print("estimated_time_s  =", round(r["estimated_time_s"], 4))
    print("uniformity_score  =", round(r["uniformity_score"], 4), "(was hardcoded 0.78)")
    print("predicted_volume  =", round(r["predicted_volume_mm3"], 2), "mm3")
    print("material_density  =", round(r["material_density_gcm3"], 3), "g/cm3")
    print("compute_time_ms   =", r["compute_time_ms"], "(round-trip", elapsed_ms, "ms)")
    print("layer_profiles    =", len(r["layer_profiles"]))
    for lp in r["layer_profiles"]:
        print(
            f"  L{lp['layer_index']}: max_h={lp['max_height_mm']:.3f} "
            f"avg_h={lp['avg_height_mm']:.3f} dep_eff={lp['dep_efficiency']:.3f}"
        )
    pd = r["particle_dist"]
    if pd is not None:
        print(
            "particle_dist     : total=", pd["total_particles"],
            "dep_eff=", round(pd["dep_efficiency"], 3),
        )
    wl = r.get("waypoint_layers")
    if wl is not None and len(wl) > 0:
        print("waypoint_layers   =", sorted(set(wl.tolist())))

    ok = True
    checks = [
        ("status SUCCESS", r["status_name"] == "SUCCESS"),
        ("waypoints > 0", len(r["waypoints"]) > 0),
        ("estimated_mass_g > 0", r["estimated_mass_g"] > 0),
        ("estimated_time_s > 0", r["estimated_time_s"] > 0),
        ("uniformity in [0.5,1.0]", 0.5 <= r["uniformity_score"] <= 1.0),
        ("predicted_volume > 0", r["predicted_volume_mm3"] > 0),
        ("layer_profiles >= 1", len(r["layer_profiles"]) >= 1),
        ("particle_dist present", r["particle_dist"] is not None),
    ]
    print("\n=== VERIFICATION ===")
    for name, passed in checks:
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}")
        ok = ok and passed

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 2


def main_repeat(n: int = 5) -> int:
    """Repeated execution + increasing dataset size (Task 9 stability)."""
    rng = np.random.default_rng(99)
    ctx = zmq.Context.instance()
    ok = True
    print(f"=== REPEATED EXECUTION x{n} (growing dataset) ===")
    for i in range(n):
        npts = 300 + i * 100
        xyz = rng.uniform(-15, 15, (npts, 3)).astype(np.float32)
        xyz[:, 2] = np.abs(xyz[:, 2])
        nrm = np.zeros_like(xyz)
        nrm[:, 2] = 1.0
        req = build_repair_request(
            xyz, nrm, material="STEEL_316L", max_layers=4,
            scan_id="repeat", request_id=f"r{i}",
        )
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)
        s.setsockopt(zmq.RCVTIMEO, 15000)
        s.connect("tcp://127.0.0.1:5555")
        t0 = time.time()
        s.send(req.SerializeToString())
        data = s.recv()
        dt = (time.time() - t0) * 1000
        s.close()
        m = RepairResult()
        m.ParseFromString(data)
        r = parse_repair_result(m)
        passed = (
            r["status_name"] == "SUCCESS"
            and len(r["waypoints"]) > 0
            and r["estimated_mass_g"] > 0
            and len(r["layer_profiles"]) >= 1
            and r["particle_dist"] is not None
        )
        ok = ok and passed
        pd_n = r["particle_dist"]["total_particles"] if r["particle_dist"] else 0
        mark = "PASS" if passed else "FAIL"
        print(
            f"  iter{i}: pts={npts} wp={len(r['waypoints'])} "
            f"mass={r['estimated_mass_g']:.2f}g layers={len(r['layer_profiles'])} "
            f"pd={pd_n} {dt:.0f}ms [{mark}]"
        )
    print("REPEATED_EXEC:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--repeat":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        sys.exit(main_repeat(n))
    sys.exit(main())
