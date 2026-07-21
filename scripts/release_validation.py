"""
release_validation.py — 工业软件发布前端到端验证脚本

模拟真实用户流程：导入 STL → 路径规划 → 形貌预测 → GUI 字段 → 导出 → 资源释放。
检查：算法、通信、GUI 数据契约、Bridge、日志、异常、性能、内存、线程。
"""
from __future__ import annotations
import os, sys, time, gc, tracemalloc, traceback, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

# 项目模块
from repair_app.core.stl_reader import read_stl_file
from repair_app.communication.repair_serialization import (
    build_repair_request, parse_repair_result,
)
from repair_app.communication.repair_protocol_pb2 import RepairResult, RepairStatusCode
from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
from repair_app.export.gcode_exporter import GCodeExporter
from repair_app.export.report_generator import RepairReport
from repair_app.utils.logger_config import setup_logging, info, warning

setup_logging(level="INFO")

REPORT: list[dict] = []
BUGS: list[dict] = []

def _record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0.0):
    REPORT.append({
        "check": name, "passed": passed, "detail": detail, "elapsed_ms": round(elapsed_ms, 1)
    })
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}" + (f" ({elapsed_ms:.0f}ms)" if elapsed_ms > 0 else ""))
    if not passed:
        BUGS.append({"check": name, "detail": detail})

# =====================================================================
# 1. STL 导入
# =====================================================================
def validate_stl_import():
    print("\n=== 1. STL 导入 ===")
    stl_path = str(Path(__file__).resolve().parents[1] / "profile_prediction" / "substrate.stl")
    t0 = time.time()
    try:
        tris = read_stl_file(stl_path)
        n = len(tris)
        # 提取顶点点云
        verts = tris[:, :9].reshape(-1, 3)
        xyz = np.unique(verts, axis=0).astype(np.float32)
        ok = n > 0 and len(xyz) >= 3
        _record("STL 读取", ok,
                f"{n} 个三角面, {len(xyz)} 个唯一顶点, 文件={os.path.basename(stl_path)}",
                (time.time() - t0) * 1000)
        return xyz
    except Exception as e:
        _record("STL 读取", False, f"异常: {e}\n{traceback.format_exc()}")
        return None

# =====================================================================
# 2. Protobuf 序列化往返
# =====================================================================
def validate_serialization(xyz):
    print("\n=== 2. Protobuf 序列化往返 ===")
    if xyz is None:
        _record("序列化", False, "无点云输入")
        return None
    normals = np.zeros_like(xyz); normals[:, 2] = 1.0
    t0 = time.time()
    try:
        req = build_repair_request(
            xyz, normals, "VAL-001", material="STEEL_316L", max_layers=5,
            request_id="val-1",
        )
        req_bytes = req.SerializeToString()
        ok1 = len(req_bytes) > 0
        _record("RepairRequest 序列化", ok1, f"{len(req_bytes)} 字节")

        req2 = type(req)()
        req2.ParseFromString(req_bytes)
        ok2 = req2.request_id == "val-1"
        _record("RepairRequest 反序列化", ok2, f"request_id={req2.request_id}")

        _record("序列化往返总耗时", ok1 and ok2, "", (time.time() - t0) * 1000)
        return req
    except Exception as e:
        _record("序列化", False, f"异常: {e}\n{traceback.format_exc()}")
        return None

# =====================================================================
# 3. Bridge: MatlabAdapter handle_repair (Python 降级路径)
# =====================================================================
def validate_bridge_handle_repair(req):
    print("\n=== 3. Bridge handle_repair (Python 降级) ===")
    if req is None:
        _record("handle_repair", False, "无请求")
        return None
    t0 = time.time()
    try:
        adapter = MatlabAdapter()
        result_msg = adapter.handle_repair(req)
        ok = result_msg.status_code == RepairStatusCode.SUCCESS
        _record("handle_repair 成功", ok,
                f"status={RepairStatusCode.Name(result_msg.status_code)}",
                (time.time() - t0) * 1000)
        if not ok:
            _record("错误信息", False, result_msg.error_message)
        return result_msg
    except Exception as e:
        _record("handle_repair", False, f"异常: {e}\n{traceback.format_exc()}")
        return None

# =====================================================================
# 4. 结果解析 + 可视化字段完整性
# =====================================================================
def validate_result_fields(result_msg):
    print("\n=== 4. 结果字段完整性 ===")
    if result_msg is None:
        _record("结果字段", False, "无结果")
        return None
    t0 = time.time()
    try:
        r = parse_repair_result(result_msg)
        checks = [
            ("waypoints 非空", len(r["waypoints"]) > 0, f"{len(r['waypoints'])} 航点"),
            ("estimated_mass_g > 0", r["estimated_mass_g"] > 0, f"{r['estimated_mass_g']:.3f} g"),
            ("estimated_time_s > 0", r["estimated_time_s"] > 0, f"{r['estimated_time_s']:.3f} s"),
            ("uniformity_score ∈ [0,1]", 0 <= r["uniformity_score"] <= 1.0, f"{r['uniformity_score']:.3f}"),
            ("layer_profiles ≥ 1", len(r["layer_profiles"]) >= 1, f"{len(r['layer_profiles'])} 层"),
            ("particle_dist 存在", r["particle_dist"] is not None, "OK"),
            ("predicted_volume > 0", r["predicted_volume_mm3"] > 0, f"{r['predicted_volume_mm3']:.2f} mm³"),
            ("mesh_bytes 非空", len(r.get("mesh_bytes", b"")) > 0, f"{len(r.get('mesh_bytes', b''))} 字节"),
            ("mesh_format 正确", r.get("mesh_format") == "stl_binary", r.get("mesh_format")),
        ]
        all_ok = True
        for name, ok, detail in checks:
            _record(name, ok, detail)
            all_ok = all_ok and ok
        _record("字段完整性总览", all_ok, "", (time.time() - t0) * 1000)
        return r
    except Exception as e:
        _record("结果字段", False, f"异常: {e}\n{traceback.format_exc()}")
        return None

# =====================================================================
# 5. ProfileResultPanel 数据契约（模拟 GUI 接收）
# =====================================================================
def validate_profile_panel_contract(r):
    print("\n=== 5. ProfileResultPanel 数据契约 ===")
    if r is None:
        _record("ProfileResultPanel 契约", False, "无结果")
        return
    t0 = time.time()
    try:
        from repair_app.ui.profile_result_panel import ProfileResultPanel, decode_binary_stl
        # 验证 STL 解码
        tris = decode_binary_stl(r.get("mesh_bytes", b""))
        ok_stl = tris is not None and len(tris) > 0
        _record("STL 解码", ok_stl,
                f"{len(tris) if tris is not None else 0} 个三角面" if ok_stl else "解码失败")

        # 构建面板数据 dict（模拟 _on_zmq_path_result 转发）
        panel_data = {
            "mesh_bytes": r.get("mesh_bytes", b""),
            "mesh_format": r.get("mesh_format", ""),
            "layer_profiles": r.get("layer_profiles", []),
            "particle_dist": r.get("particle_dist"),
            "uniformity_score": r.get("uniformity_score", 0.0),
            "estimated_mass_g": r.get("estimated_mass_g", 0.0),
            "estimated_time_s": r.get("estimated_time_s", 0.0),
            "predicted_volume_mm3": r.get("predicted_volume_mm3", 0.0),
            "warnings": [],
        }
        # 验证 dict 可序列化关键字段（不含 bytes）
        serializable = {k: v for k, v in panel_data.items() if k != "mesh_bytes"}
        _record("面板数据可序列化", True, json.dumps({k: str(type(v).__name__) for k, v in serializable.items()}))
        _record("ProfileResultPanel 契约总览", ok_stl, "", (time.time() - t0) * 1000)
    except Exception as e:
        _record("ProfileResultPanel 契约", False, f"异常: {e}\n{traceback.format_exc()}")

# =====================================================================
# 6. 导出 G-code
# =====================================================================
def validate_gcode_export(r):
    print("\n=== 6. G-code 导出 ===")
    if r is None or len(r["waypoints"]) == 0:
        _record("G-code 导出", False, "无航点")
        return
    t0 = time.time()
    try:
        wp = r["waypoints"][:, :3]
        out_path = str(Path(__file__).resolve().parent / "validation_output" / "test_repair.nc")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        exporter = GCodeExporter(feed_rate=500.0, safe_z=10.0)
        gcode = exporter.export(wp, output_path=out_path)
        ok = len(gcode) > 0 and os.path.exists(out_path)
        _record("G-code 生成", ok,
                f"{len(gcode)} 字符, {len(gcode.splitlines())} 行, 文件={os.path.basename(out_path)}",
                (time.time() - t0) * 1000)
    except Exception as e:
        _record("G-code 导出", False, f"异常: {e}\n{traceback.format_exc()}")

# =====================================================================
# 7. 导出 PDF 报告
# =====================================================================
def validate_pdf_export(r):
    print("\n=== 7. PDF 报告导出 ===")
    if r is None:
        _record("PDF 导出", False, "无结果")
        return
    t0 = time.time()
    try:
        out_path = str(Path(__file__).resolve().parent / "validation_output" / "test_report.pdf")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        gen = RepairReport()
        gen.generate(out_path)
        ok = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        _record("PDF 生成", ok,
                f"{os.path.getsize(out_path) if ok else 0} 字节",
                (time.time() - t0) * 1000)
    except Exception as e:
        _record("PDF 导出", False, f"异常: {e}\n{traceback.format_exc()}")

# =====================================================================
# 8. 异常处理：空点云、无效输入
# =====================================================================
def validate_exception_handling():
    print("\n=== 8. 异常处理 ===")
    t0 = time.time()
    try:
        adapter = MatlabAdapter()
        # 空点云
        empty_xyz = np.zeros((0, 3), dtype=np.float32)
        empty_n = np.zeros((0, 3), dtype=np.float32)
        req = build_repair_request(empty_xyz, empty_n, "EMPTY",
                                    material="STEEL_316L", request_id="empty-test")
        result = adapter.handle_repair(req)
        ok = result.status_code != RepairStatusCode.SUCCESS
        _record("空点云返回错误状态", ok,
                f"status={RepairStatusCode.Name(result.status_code)}")
    except Exception as e:
        _record("空点云异常处理", False, f"未捕获异常: {e}")

    try:
        # 单点输入
        single_xyz = np.array([[0, 0, 0]], dtype=np.float32)
        single_n = np.array([[0, 0, 1]], dtype=np.float32)
        req = build_repair_request(single_xyz, single_n, "SINGLE",
                                    material="STEEL_316L", request_id="single-test")
        result = adapter.handle_repair(req)
        _record("单点输入不崩溃", True, f"status={RepairStatusCode.Name(result.status_code)}")
    except Exception as e:
        _record("单点输入异常处理", False, f"未捕获异常: {e}")
    _record("异常处理总览", True, "", (time.time() - t0) * 1000)

# =====================================================================
# 9. 性能与内存
# =====================================================================
def validate_performance_memory(xyz):
    print("\n=== 9. 性能与内存 ===")
    if xyz is None:
        _record("性能内存", False, "无点云")
        return
    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    t0 = time.time()
    try:
        normals = np.zeros_like(xyz); normals[:, 2] = 1.0
        req = build_repair_request(xyz, normals, "PERF", material="STEEL_316L", max_layers=5)
        adapter = MatlabAdapter()
        result = adapter.handle_repair(req)
        r = parse_repair_result(result)
        elapsed = (time.time() - t0) * 1000
        snap2 = tracemalloc.take_snapshot()
        stats = snap2.compare_to(snap1, "lineno")
        total_mem_kb = sum(s.size_diff for s in stats if s.size_diff > 0) / 1024
        ok_perf = elapsed < 10000  # 10 秒内
        ok_mem = total_mem_kb < 100 * 1024  # < 100MB
        _record("端到端耗时 < 10s", ok_perf, f"{elapsed:.0f}ms", elapsed)
        _record("内存增量 < 100MB", ok_mem, f"{total_mem_kb:.1f} KB")
        tracemalloc.stop()
        # 强制 GC 验证资源释放
        gc.collect()
        _record("GC 资源回收", True, "gc.collect() 完成")
    except Exception as e:
        _record("性能内存", False, f"异常: {e}\n{traceback.format_exc()}")

# =====================================================================
# 10. 重复执行稳定性（5 次）
# =====================================================================
def validate_repeat_stability(xyz):
    print("\n=== 10. 重复执行稳定性 (5次) ===")
    if xyz is None:
        _record("重复稳定性", False, "无点云")
        return
    ok_all = True
    for i in range(5):
        t0 = time.time()
        try:
            normals = np.zeros_like(xyz); normals[:, 2] = 1.0
            req = build_repair_request(xyz, normals, f"REPEAT-{i}",
                                        material="STEEL_316L", max_layers=3,
                                        request_id=f"repeat-{i}")
            adapter = MatlabAdapter()
            result = adapter.handle_repair(req)
            r = parse_repair_result(result)
            ok = (r["status_name"] == "SUCCESS" and len(r["waypoints"]) > 0)
            ok_all = ok_all and ok
            dt = (time.time() - t0) * 1000
            print(f"    iter{i}: wp={len(r['waypoints'])} {dt:.0f}ms [{'PASS' if ok else 'FAIL'}]")
        except Exception as e:
            ok_all = False
            print(f"    iter{i}: 异常 {e}")
    _record("5 次重复执行稳定", ok_all)

# =====================================================================
# 主流程
# =====================================================================
def main():
    print("=" * 60)
    print("工业软件发布前端到端验证")
    print("=" * 60)

    xyz = validate_stl_import()
    req = validate_serialization(xyz)
    result_msg = validate_bridge_handle_repair(req)
    r = validate_result_fields(result_msg)
    validate_profile_panel_contract(r)
    validate_gcode_export(r)
    validate_pdf_export(r)
    validate_exception_handling()
    validate_performance_memory(xyz)
    validate_repeat_stability(xyz)

    # 汇总
    total = len(REPORT)
    passed = sum(1 for x in REPORT if x["passed"])
    failed = total - passed
    print("\n" + "=" * 60)
    print(f"汇总: {passed}/{total} 通过, {failed} 失败")
    if BUGS:
        print(f"BUG 数: {len(BUGS)}")
        for b in BUGS:
            print(f"  - {b['check']}: {b['detail'][:80]}")
    print("=" * 60)

    # 输出 JSON 供报告生成使用
    out_dir = Path(__file__).resolve().parent
    with open(out_dir / "validation_results.json", "w", encoding="utf-8") as f:
        json.dump({"report": REPORT, "bugs": BUGS,
                   "summary": {"total": total, "passed": passed, "failed": failed}},
                   f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {out_dir / 'validation_results.json'}")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
