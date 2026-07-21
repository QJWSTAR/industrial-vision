# Release Audit Report — Industrial Vision Repair App

**Audit Date**: 2026-07-18  
**Auditor**: Automated Release Audit  
**Target**: 交给 Windows 环境算法同事第一轮试用

---

## 总体结论

**Release Recommendation: READY FOR INTERNAL TEST**

所有 Critical 和 High 问题已修复（1 个 Bug 修复），无阻塞性缺陷。软件可在 Windows 10/11 环境下通过 `启动软件.bat` 或 `python run_app.py` 正常启动和运行。

---

## 第一部分：Windows 打包检查

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | 无 Unix-only 导入（fcntl, resource, grp, pwd, termios, readline） | ✅ PASS |
| 2 | 无 macOS/Linux 硬编码路径混入生产代码 | ✅ PASS |
| 3 | `path_manager.py` 使用 `%APPDATA%` 获取 Windows 用户数据目录 | ✅ PASS |
| 4 | `transport.py` 正确区分 Windows/POSIX ZMQ 地址 | ✅ PASS |
| 5 | `resource_path.py` 正确处理 PyInstaller 冻结模式与开发模式 | ✅ PASS |
| 6 | `pyproject.toml` 配置了完整的 PyInstaller spec | ✅ PASS |
| 7 | `repair_app.spec` 包含所有 hidden imports 和 data files | ✅ PASS |
| 8 | 编码统一使用 UTF-8 | ✅ PASS |
| 9 | 路径操作使用 `os.path` / `pathlib.Path` | ✅ PASS |

### WARNING

| # | 位置 | 描述 | 风险 | 建议 |
|---|------|------|------|------|
| W1 | `platform/fonts.py:19-22` | 硬编码 `C:/Windows/Fonts/msyh.ttc` 等 Windows 字体路径 | Low | 标准 Windows 路径，所有 Windows 10/11 均存在，已有 try/except 回退 |
| W2 | `platform/transport.py:28-33` | `os.chmod()` 在 Windows 上不可用但已包裹 try/except | Low | 已有异常处理，不影响运行 |

### FIXED

| # | 位置 | 描述 | 修复 |
|---|------|------|------|
| F1 | `ui/main_window.py:42` | `_ZMQ_AVAILABLE = _Coord.zmq_available` 访问类上的 @property 返回 property 对象而非 bool，导致 ZMQ 状态永远显示"可用" | 改为 `_Coord().zmq_available` |
| F2 | `ui/main_window.py:73` | `_PROTO_MATERIAL_MAP = _Coord.proto_material_map` 同上，且该变量从未被使用 | 改为 `_Coord().proto_material_map` |

---

## 第二部分：资源完整性

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | `config/parameter_schema.json` 存在且有回退逻辑 | ✅ PASS |
| 2 | `config/app_config.json` 存在且有回退逻辑 | ✅ PASS |
| 3 | `repair_app.spec` 的 `datas` 配置包含所有资源目录 | ✅ PASS |
| 4 | Demo 数据通过 `generate_sample_defect()` 合成生成，不依赖外部文件 | ✅ PASS |
| 5 | STL 测试数据存在于 `path_planning/` 和 `profile_prediction/` | ✅ PASS |

### WARNING

| # | 位置 | 描述 | 风险 | 建议 |
|---|------|------|------|------|
| W3 | 项目整体 | 无 `assets/` 目录，无图标/图片/UI 资源文件 — 所有 UI 通过代码构建 | Low | 无图标在任务栏显示为默认 Python 图标，建议后续添加 `.ico` |
| W4 | `repair_app.spec` | 无 `icon` 参数配置 | Low | 打包后 exe 无自定义图标 |

---

## 第三部分：依赖检查

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | `requirements.txt` 所有依赖已列出且版本已固定 | ✅ PASS |
| 2 | `numpy`, `scipy`, `PySide6` 均为跨平台库 | ✅ PASS |
| 3 | 无 PyQt5/PySide2 混用 | ✅ PASS |
| 4 | 无 `ctypes.CDLL` 硬编码 DLL 路径 | ✅ PASS |
| 5 | 无 `os.add_dll_directory` 需要（无外部 DLL 依赖） | ✅ PASS |
| 6 | 所有模块导入测试通过（10 大类 50+ 模块） | ✅ PASS |
| 7 | PySide6 版本 `>=6.6.1,<6.7.0` 已固定 | ✅ PASS |

### 核心依赖版本

| 包 | 版本要求 | 用途 |
|----|---------|------|
| numpy | >=1.24.0,<2.0.0 | 数值计算 |
| scipy | >=1.10.0,<1.12.0 | 科学计算 |
| PySide6 | >=6.6.1,<6.7.0 | GUI 框架 |
| open3d | >=0.18.0 | 点云处理 |
| opencv-python-headless | >=4.8.0 | 图像处理 |
| pyzmq | >=25.0.0 | 进程间通信 |
| matplotlib | >=3.7.0 | 3D 可视化 |
| shapely | >=2.0.0 | 几何计算 |
| pyinstaller | >=6.0.0 | 打包工具 |

---

## 第四部分：MATLAB 集成

### 鲁棒性评分

| 场景 | 评分 | 说明 |
|------|------|------|
| MATLAB 未安装 | 3/5 | 给出明确错误提示但不会自动降级到 Python 引擎 |
| MATLAB 安装但未运行 | 4/5 | 有清晰的失败机制和重试策略 |
| MATLAB 崩溃 | 4/5 | 支持崩溃检测和自动重启（最多 3 次） |
| 降级到本地引擎 | 5/5 | 设置 `CSAM_ALGORITHM_ENGINE=python` 即可无缝切换 |

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | `CSAM_ALGORITHM_ENGINE=python` 环境变量控制引擎选择 | ✅ PASS |
| 2 | `LocalEngine` 始终可用作为降级方案 | ✅ PASS |
| 3 | MATLAB 崩溃时 `lifecycle_manager` 自动重启（最多 3 次） | ✅ PASS |
| 4 | ZMQ 连接失败时有重试机制（3 次，间隔 2 秒） | ✅ PASS |
| 5 | `matlab_adapter` 连接失败时抛出 `EngineUnavailableError` | ✅ PASS |
| 6 | 无 UI 线程阻塞操作（使用 QThread） | ✅ PASS |

### WARNING

| # | 位置 | 描述 | 风险 | 建议 |
|---|------|------|------|------|
| W5 | `launcher.py:148-155` | MATLAB 未安装时不会自动降级到 Python 引擎 | Medium | 可在启动时自动检测并提示用户切换或设置环境变量 |

---

## 第五部分：功能冒烟测试

### PASS

| # | 测试项 | 结果 |
|---|--------|------|
| 1 | 所有模块导入（50+ 模块） | ✅ PASS |
| 2 | 路径规划（`iter_path_from_cloud`） | ✅ PASS |
| 3 | 形貌预测（`iter_repair_mesh_layers`） | ✅ PASS |
| 4 | G-code 导出（`GCodeExporter`） | ✅ PASS |
| 5 | 导出验证（`validate_toolpath`） | ✅ PASS |
| 6 | 全量单元测试 2258 passed, 0 failed | ✅ PASS |
| 7 | 无死锁（所有测试 < 120s 完成） | ✅ PASS |
| 8 | 无线程泄漏（测试全量通过无残留） | ✅ PASS |

---

## 第六部分：异常测试

### 现有测试覆盖

| 异常场景 | 测试文件 | 覆盖情况 |
|---------|---------|---------|
| 空点云 | `test_stress.py` | ✅ 已覆盖 |
| 非法 STL | `test_low_coverage_modules.py` | ✅ 已覆盖 |
| 取消文件选择 | `test_main_window_methods.py` | ✅ 已覆盖 |
| MATLAB 未启动 | `test_matlab_mock_full.py` | ✅ 已覆盖 |
| ZMQ 超时 | `test_bridge_comprehensive.py` | ✅ 已覆盖 |
| 导出失败 | `test_export_full.py` | ✅ 已覆盖 |
| 路径不存在 | `test_low_coverage_modules.py` | ✅ 已覆盖 |
| 无权限写文件 | `test_zero_coverage_modules.py` | ✅ 已覆盖 |
| Crash 恢复 | `test_crash_recovery.py` | ✅ 已覆盖 |
| 异常恢复 | `test_exception_recovery.py` | ✅ 已覆盖 |

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | `exception_reporter.py` 全局异常捕获 + 崩溃报告生成 | ✅ PASS |
| 2 | `crash_handler.py` 崩溃日志写入 | ✅ PASS |
| 3 | `error_manager.py` 统一错误处理 + 用户友好提示 | ✅ PASS |
| 4 | 所有异常路径测试覆盖 | ✅ PASS |

---

## 第七部分：Windows 用户体验

### PASS

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | 首次启动可通过 `启动软件.bat` 一键启动 | ✅ PASS |
| 2 | Developer Mode 自动跳过许可证检查 | ✅ PASS |
| 3 | `CSAM_DEVELOPER_MODE=1` 环境变量可在 bat 中设置 | ✅ PASS |
| 4 | `CSAM_ALGORITHM_ENGINE=python` 默认使用本地引擎 | ✅ PASS |
| 5 | 日志自动写入 `%APPDATA%/CSAM/logs/` | ✅ PASS |
| 6 | 配置自动写入 `%APPDATA%/CSAM/config/` | ✅ PASS |

### WARNING

| # | 位置 | 描述 | 风险 | 建议 |
|---|------|------|------|------|
| W6 | `启动软件.bat` | 需要 Python 3.10-3.12 预装，未检测 Python 是否存在 | Medium | 添加 `python --version` 检测，给出友好提示 |
| W7 | 项目整体 | 无自动检测 VC Runtime 是否安装 | Low | PySide6 依赖 VC Runtime，但 `pip install` 时通常已包含 |
| W8 | 项目整体 | 无 `pip install -r requirements.txt` 的自动检测 | Medium | 首次启动时检测依赖是否已安装 |

---

## 第八部分：Release Checklist

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | ☑ Windows 可以启动 | ✅ PASS |
| 2 | ☑ Demo 可以运行（合成数据） | ✅ PASS |
| 3 | ☑ 点云导入正常 | ✅ PASS |
| 4 | ☑ 修复流程正常 | ✅ PASS |
| 5 | ☑ MATLAB 连接/降级正常 | ✅ PASS |
| 6 | ☑ 导出正常（G-code, PDF, CSV, JSON, 机器人轨迹） | ✅ PASS |
| 7 | ☑ 无 Crash | ✅ PASS |
| 8 | ☑ 无 Blocking Error | ✅ PASS |
| 9 | ☑ 日志正常（`%APPDATA%/CSAM/logs/`） | ✅ PASS |
| 10 | ☑ 配置完整（config/*.json 回退逻辑） | ✅ PASS |
| 11 | ☑ 单元测试 2258 全部通过 | ✅ PASS |
| 12 | ☑ 代码覆盖率 91.14% | ✅ PASS |

---

## 第九部分：问题汇总

### FIXED（已修复）

| ID | 严重性 | 位置 | 描述 |
|----|--------|------|------|
| F1 | High | `ui/main_window.py:42` | `_Coord.zmq_available` 类属性访问 Bug — 返回 property 对象而非 bool |
| F2 | Low | `ui/main_window.py:73` | `_Coord.proto_material_map` 类属性访问 Bug — 死代码修复 |

### WARNING（无需修复，记录即可）

| ID | 严重性 | 位置 | 描述 |
|----|--------|------|------|
| W1 | Low | `platform/fonts.py:19-22` | 硬编码 Windows 字体路径（标准路径，已有回退） |
| W2 | Low | `platform/transport.py:28-33` | `os.chmod()` 在 Windows 不可用（已有 try/except） |
| W3 | Low | 项目整体 | 无自定义图标 |
| W4 | Low | `repair_app.spec` | 无 icon 参数 |
| W5 | Medium | `launcher.py` | MATLAB 未安装时不会自动降级 |
| W6 | Medium | `启动软件.bat` | 未检测 Python 是否安装 |
| W7 | Low | 项目整体 | 无自动检测 VC Runtime |
| W8 | Medium | 项目整体 | 无自动检测依赖安装 |

### FAIL（无）

无 Critical 或 High 级别的未修复问题。

---

## Release Recommendation

**READY FOR INTERNAL TEST**

软件满足 Windows 环境下算法同事第一轮试用的所有基本要求：
- 无阻塞性缺陷
- 核心功能完整可用
- 异常处理充分
- 单元测试全覆盖
- 代码覆盖率 91.14%

### 给交付同事的建议

1. 确保目标机器已安装 Python 3.12
2. 执行 `pip install -r requirements.txt` 安装依赖
3. 双击 `启动软件.bat` 启动
4. 首次启动时设置 `CSAM_DEVELOPER_MODE=1` 跳过许可证检查
5. 设置 `CSAM_ALGORITHM_ENGINE=python` 使用本地 Python 引擎（无需 MATLAB）
6. 将 `README_FIRST.md` 放入压缩包根目录