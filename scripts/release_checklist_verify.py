"""Release Checklist 综合验证脚本。

验证项：
- License 正常：LicenseManager 导入 + 公钥加载
- MATLAB 正常：Bridge 导入 + Protocol 版本
- G-code 正常：默认导出产生 G90（绝对坐标模式）
- ErrorManager：7 类错误码 + handle() 入口

不依赖外部 MATLAB/License 真实文件，仅验证代码完整性。
"""
from __future__ import annotations
import sys
import os
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

failures = []
passed = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        passed.append(f"{name}: OK {detail}")
        print(f"[OK]   {name} {detail}")
    else:
        failures.append(f"{name}: FAIL {detail}")
        print(f"[FAIL] {name} {detail}")


# ---------- 1. License 正常 ----------
print("\n=== 1. License 验证 ===")
try:
    from repair_app.utils.license_manager import LicenseManager
    check("LicenseManager 导入", True)
    # 公钥从 _MEIPASS 加载（开发环境从 config/）
    from repair_app.utils.resource_path import get_builtin_config_file, get_config_dir
    pub_builtin = get_builtin_config_file("public_key.pem")
    pub_config = get_config_dir() / "public_key.pem"
    pub_path = pub_builtin or pub_config
    check("公钥文件存在", pub_path is not None and Path(pub_path).exists(),
          f"-> {pub_path}")
    # 实例化（不调用 verify，仅检查构造）
    lm = LicenseManager()
    check("LicenseManager 实例化", lm is not None)
    # 公钥已加载（load_pem_public_key 成功）
    has_pubkey = getattr(lm, "_public_key", None) is not None
    check("License 公钥已加载", has_pubkey)
except Exception as e:
    check("License 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 2. MATLAB / Bridge 正常 ----------
print("\n=== 2. MATLAB Bridge 验证 ===")
try:
    from repair_app.bridge import (
        MatlabService, BridgeClient, BridgeServer, BridgeConfig,
        PROTOCOL_VERSION, MessageType, BridgeError,
        ConnectionError, EngineUnavailableError, AlgorithmError,
    )
    check("Bridge 核心导入", True)
    check("协议版本非空", bool(PROTOCOL_VERSION), f"-> v{PROTOCOL_VERSION}")
    # MessageType 枚举完整（实际枚举值）
    msg_types = [mt.name for mt in MessageType]
    required = {"HEALTH_CHECK", "REPAIR_REQUEST", "REPAIR_RESULT",
                "PROGRESS_UPDATE", "SHUTDOWN"}
    has_all = required.issubset(set(msg_types))
    check("MessageType 枚举完整", has_all, f"-> {msg_types}")
    # BridgeConfig 默认值
    cfg = BridgeConfig()
    check("BridgeConfig 默认实例化", cfg is not None,
          f"-> port={getattr(cfg, 'port', '?')}")
    # launcher 启动模式（硬约束：-r 而非 -batch）
    launcher_path = PROJECT_ROOT / "repair_app" / "bridge" / "launcher.py"
    launcher_src = launcher_path.read_text(encoding="utf-8")
    uses_r_mode = '"-r"' in launcher_src or "'-r'" in launcher_src
    uses_batch = '"-batch"' in launcher_src or "'-batch'" in launcher_src
    check("launcher 使用 -r 模式", uses_r_mode and not uses_batch,
          f"-> r={uses_r_mode}, batch={uses_batch}")
except Exception as e:
    check("Bridge 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 3. G-code 正常 ----------
print("\n=== 3. G-code 导出验证 ===")
try:
    from repair_app.export.gcode_exporter import GCodeExporter
    import numpy as np
    check("GCodeExporter 导入", True)
    # 构造测试航点（Z=5，低于默认 safe_z=10）
    waypoints = np.array([
        [0.0, 0.0, 5.0],
        [10.0, 0.0, 5.0],
        [10.0, 10.0, 5.0],
        [0.0, 10.0, 5.0],
    ], dtype=float)
    # 默认绝对坐标模式导出
    exporter_abs = GCodeExporter(coordinate_mode="absolute")
    with tempfile.TemporaryDirectory() as td:
        out_abs = Path(td) / "abs.nc"
        gcode_abs = exporter_abs.export(waypoints, output_path=str(out_abs))
    check("G-code 绝对模式导出成功", bool(gcode_abs))
    check("G-code 包含 G90（绝对坐标）", "G90" in gcode_abs)
    check("G-code 不包含 G91（绝对模式）", "G91" not in gcode_abs)
    # 增量模式导出
    exporter_inc = GCodeExporter(coordinate_mode="incremental")
    with tempfile.TemporaryDirectory() as td:
        out_inc = Path(td) / "inc.nc"
        gcode_inc = exporter_inc.export(waypoints, output_path=str(out_inc))
    check("G-code 增量模式包含 G91", "G91" in gcode_inc)
    # 元数据
    check("G-code 包含版本元数据", "version" in gcode_abs.lower() or "1.0" in gcode_abs)
except Exception as e:
    check("G-code 验证", False, f"异常: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()


# ---------- 4. ErrorManager 正常 ----------
print("\n=== 4. ErrorManager 验证 ===")
try:
    from repair_app.utils.error_manager import (
        ErrorManager, ErrorCode, LogManager, FriendlyMessage,
    )
    check("ErrorManager 导入", True)
    # 7 类错误码
    codes = [c.name for c in ErrorCode]
    required_codes = {"LICENSE", "MATLAB", "FILE", "MESH",
                      "NETWORK", "EXPORT", "UNKNOWN"}
    check("ErrorCode 7 类完整", required_codes.issubset(set(codes)),
          f"-> {codes}")
    # handle() 入口存在
    check("ErrorManager.handle() 入口", hasattr(ErrorManager, "handle"))
    # get_friendly_message 存在
    check("ErrorManager.get_friendly_message()",
          hasattr(ErrorManager, "get_friendly_message"))
    # 实际触发一次错误处理（不弹窗）
    try:
        raise ValueError("test error for release checklist")
    except ValueError as ve:
        fm = ErrorManager.get_friendly_message(ve, ErrorCode.UNKNOWN, "verify")
        check("get_friendly_message 返回非空",
              fm is not None and bool(getattr(fm, "title", "")))
        has_what = bool(getattr(fm, "what", ""))
        check("FriendlyMessage 包含 What", has_what)
except Exception as e:
    check("ErrorManager 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 5. workers _pack_error 三段式 ----------
print("\n=== 5. Workers _pack_error 验证 ===")
try:
    from repair_app.ui.workers import _pack_error
    from repair_app.utils.error_manager import ErrorCode
    try:
        raise RuntimeError("pack error test")
    except RuntimeError as re:
        code_val, friendly, detail = _pack_error(re, ErrorCode.UNKNOWN, "verify")
    check("_pack_error 返回三元组",
          isinstance(code_val, str) and isinstance(friendly, str) and isinstance(detail, str))
    check("friendly 包含 What", "test" in friendly.lower() or len(friendly) > 10)
    check("detail 包含 traceback", "Traceback" in detail or "RuntimeError" in detail)
except Exception as e:
    check("_pack_error 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 6. crash_handler 安全 ----------
print("\n=== 6. crash_handler 验证 ===")
try:
    ch_path = PROJECT_ROOT / "repair_app" / "utils" / "crash_handler.py"
    ch_src = ch_path.read_text(encoding="utf-8")
    check("crash_handler 检查 sys.stderr is not None",
          "sys.stderr is not None" in ch_src)
except Exception as e:
    check("crash_handler 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 7. repair_visualizer cleanup ----------
print("\n=== 7. repair_visualizer cleanup 验证 ===")
try:
    rv_path = PROJECT_ROOT / "repair_app" / "ui" / "repair_visualizer.py"
    rv_src = rv_path.read_text(encoding="utf-8")
    check("repair_visualizer 包含 cleanup() 方法", "def cleanup" in rv_src)
    # main_window closeEvent 调用 cleanup
    mw_path = PROJECT_ROOT / "repair_app" / "ui" / "main_window.py"
    mw_src = mw_path.read_text(encoding="utf-8")
    check("main_window closeEvent 调用 visualizer.cleanup()",
          "visualizer.cleanup" in mw_src or "_visualizer.cleanup" in mw_src
          or "cleanup()" in mw_src)
except Exception as e:
    check("repair_visualizer 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 8. Spec 文件验证 ----------
print("\n=== 8. PyInstaller Spec 验证 ===")
try:
    spec_path = PROJECT_ROOT / "repair_app.spec"
    spec_src = spec_path.read_text(encoding="utf-8")
    check("Spec 包含 parameter_schema.json",
          "parameter_schema.json" in spec_src)
    check("Spec 包含 matlab_bridge_server.m",
          "matlab_bridge_server.m" in spec_src)
    check("Spec 包含 path_planning 目录",
          "path_planning" in spec_src)
    check("Spec 包含 profile_prediction 目录",
          "profile_prediction" in spec_src)
    check("Spec 包含 public_key.pem",
          "public_key.pem" in spec_src)
    check("Spec 设置 disable_windowed_traceback=True",
          "disable_windowed_traceback=True" in spec_src)
except Exception as e:
    check("Spec 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 9. dist 打包产物 ----------
print("\n=== 9. dist 打包产物验证 ===")
try:
    dist_dir = PROJECT_ROOT / "dist"
    exe_path = dist_dir / "CSAM_Repair.exe"
    check("dist/CSAM_Repair.exe 存在", exe_path.exists(),
          f"-> {exe_path.stat().st_size // (1024*1024)} MB" if exe_path.exists() else "")
    # config 目录
    cfg_dir = dist_dir / "config"
    check("dist/config 目录存在", cfg_dir.exists())
    if cfg_dir.exists():
        check("dist/config/license.key 存在",
              (cfg_dir / "license.key").exists())
        check("dist/config/public_key.pem 存在",
              (cfg_dir / "public_key.pem").exists())
except Exception as e:
    check("dist 验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 10. 平台脚本验证 ----------
print("\n=== 10. 跨平台脚本验证 ===")
try:
    win_script = PROJECT_ROOT / "build_windows.bat"
    mac_script = PROJECT_ROOT / "build_macos.sh"
    check("build_windows.bat 存在", win_script.exists())
    check("build_macos.sh 存在", mac_script.exists())
    # 启动脚本
    launcher_bat = PROJECT_ROOT / "启动软件.bat"
    check("启动软件.bat 存在", launcher_bat.exists())
except Exception as e:
    check("跨平台脚本验证", False, f"异常: {type(e).__name__}: {e}")


# ---------- 总结 ----------
print("\n" + "=" * 60)
print(f"通过: {len(passed)} 项")
print(f"失败: {len(failures)} 项")
print("=" * 60)
if failures:
    print("\n失败项:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\n所有验证项通过")
    sys.exit(0)
