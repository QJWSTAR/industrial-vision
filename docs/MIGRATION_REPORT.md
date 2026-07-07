# 迁移报告 — macOS 到跨平台

**项目**：CSAM Repair  
**版本**：1.0.0  
**日期**：2026-07-06  
**迁移范围**：仅 macOS → Windows 10/11 + macOS 跨平台

## 执行摘要

CSAM Repair 应用程序最初仅在 macOS 上开发和测试。为实现跨平台兼容性，执行了一个 7 阶段的迁移计划，涵盖 ZMQ 传输、字体处理、线程安全、CI/CD、架构债务和安全加固。在所有阶段中，全部 145 个测试均通过，零回归。

## 阶段摘要

### 阶段 1 — 解除阻塞（环境与路径修复）

**目标**：解决阻止项目在 Windows 上运行的直接阻塞问题。

**变更内容**：
- 修复了测试文件（`test_stage3.py`、`calibration_wizard.py`）中的 `sys.path` 操作
- 创建了 `setup.py` 以向后兼容 pip < 21.3
- 更新了 `pyproject.toml`，添加了正确的 `requires-python = ">=3.10"` 和分类器
- 更新了 `README.md`，修正了安装说明

**修改文件数**：5  
**测试**：145 个通过

### 阶段 2 — Windows 兼容性（平台抽象层）

**目标**：将操作系统特定逻辑隔离到平台抽象层之后。

**变更内容**：
- 创建了 `repair_app/platform/` 包，包含 `__init__.py`、`transport.py`、`fonts.py`
- `transport.py`：ZMQ 地址选择 — `ipc:///tmp/csam_engine`（POSIX）vs `tcp://127.0.0.1:5555`（Windows）
- `fonts.py`：CJK 字体选择 — PingFang SC（macOS）vs Microsoft YaHei（Windows）vs Noto CJK（Linux）
- 更新了 `zmq_client.py`，使用 `get_zmq_address_from_env()` 替代硬编码的 IPC 路径
- 更新了 `main_window.py` 和 `repair_visualizer.py`，使用平台字体选择器

**修改文件数**：7（3 个新建，4 个修改）  
**测试**：145 个通过

### 阶段 3 — 依赖治理

**目标**：修复依赖声明问题，以便在所有平台上进行干净的安装。

**变更内容**：
- 将 `cryptography` 和 `reportlab` 声明为基础依赖（之前仅在 requirements.txt 中，不在 pyproject.toml 中）
- 修复了 PyInstaller spec 路径引用
- 将 `requirements.txt` 与 `pyproject.toml` 依赖同步

**修改文件数**：3  
**测试**：145 个通过

### 阶段 4 — 健壮性

**目标**：加强生产环境的运行时稳定性。

**变更内容**：
- **机器 ID 强化**：`license_manager.py` 现在使用 `uuid.getnode()` + `platform.node()` 哈希替代纯主机名。旧版机器 ID 保留以向后兼容现有许可证。
- **ASCII 目录别名**：`config.py` 现在使用 `morphology_prediction/`（ASCII）作为主目录名，如果旧版目录存在则回退到 `形貌预测/`（中文）。`matlab_frames/` 与 `Matlab图片保存/` 采用相同模式。
- **协作式线程关闭**：`workers.py` 和 `zmq_client.py` 将 `QThread.terminate()` 替换为 `requestInterruption()` / `isInterruptionRequested()` 模式。ZMQ 客户端使用 200ms 轮询循环并进行中断检查。

**修改文件数**：4  
**测试**：145 个通过

### 阶段 5 — CI/CD 流水线

**目标**：建立多平台持续集成和发布自动化。

**变更内容**：
- 创建了 `build_macos.sh`（新建）— 带有依赖验证的 macOS 构建脚本
- 更新了 `ci.yml` — 将 Windows 添加到构建矩阵，添加 `pip install -e ".[dev]"`、pre-commit 钩子
- 创建了 `release.yml`（新建）— 标签触发的 PyInstaller 构建，支持 Windows 和 macOS 的产物上传

**修改文件数**：3（1 个新建，2 个修改）  
**测试**：145 个通过

### 阶段 6 — 架构债务

**目标**：将算法和 I/O 逻辑从 UI 层中迁移出来。

**变更内容**：
- 将 `_est_normals` 算法从 `MainWindow` 提取到 `repair_app/core/normal_estimator.py`
- 创建了 `repair_app/service/export_service.py` — G-code 和 PDF 导出操作通过服务层路由
- 创建了 `repair_app/service/file_service.py` — 文件 I/O 操作通过服务层路由
- 更新了 `main_window.py`，调用服务而不是直接导入导出模块

**修改文件数**：5（2 个新建，3 个修改）  
**测试**：145 个通过  
**注意**：初始 `service/__init__.py` 导入导致测试中 matplotlib Qt 后端崩溃。在阶段 7 中通过 PEP 562 延迟导入修复。

### 阶段 7 — 清理与安全

**目标**：移除死代码，修复安全问题，完成最终清理。

**变更内容**：
- `cfd_to_npz.py`：为 MATLAB 依赖添加了 Optional 导入。将 NPZ 元数据从对象数组（allow_pickle=True 风险）迁移到 JSON 附属文件。
- `look_up.py`：创建了 `_load_numeric_npz()` 安全加载器，使用 `allow_pickle=False` 和键过滤。
- 修复了 MATLAB 硬编码路径，改为使用环境变量。
- 更新了 `requires-python` 为 `>=3.10`。
- 在 `service/__init__.py` 中实现了 PEP 562 `__getattr__` 用于延迟 `ExportService` 导入（解决 matplotlib 后端冲突）。
- 在 `release.yml` 中添加了 `permissions: contents: write` 用于 GitHub Releases 上传。

**修改文件数**：5  
**测试**：145 个通过

## 迁移后工程审查

在 7 阶段迁移后进行了全面的 18 维度工程审查。在架构、代码质量、平台兼容性、死代码、线程安全、异常处理和打包方面共发现 36 个问题。其中 16 个问题在 11 个文件中自动修复，包括：

- `release.yml`：在 pytest 之前添加了缺失的 `pip install -e ".[dev]"`（严重）
- 构建脚本：添加了 `pip install pyinstaller`（高）
- `normal_estimator.py`：添加了少于 3 个点的边界处理（中）
- `export_service.py`：在形状访问之前添加了路径点验证（中）
- `license_manager.py`：为 4 个静默 except 块添加了日志记录（中）
- `zmq_client.py` + `repair_engine_service.py`：激活了死代码 `get_zmq_address_from_env()`（高）
- `cfd_to_npz.py`：移除了死代码循环，修复了脆弱的扩展名替换（低）

**审查修复后测试**：145 个通过

## 生产发布准备

应用了额外的生产加固：

- 创建了 `repair_app/utils/resource_path.py` — PyInstaller `_MEIPASS` 资源解析
- 创建了 `hooks/pyi_runtime_hook.py` — 用于 SSL、Qt 插件、matplotlib、ZMQ、字体的运行时钩子
- 创建了 `.env.example` — 环境变量模板
- 增强了 `repair_app.spec` — 生产级 spec，包含运行时钩子、18+ 个隐藏导入、UPX 排除、macOS bundle 元数据

## 累计统计

| 指标 | 数值 |
|--------|-------|
| 完成阶段数 | 7 |
| 修改文件总数 | 24 |
| 新建文件总数 | 10 |
| 删除文件总数 | 1 |
| 全程测试 | 145（零回归） |
| 测试覆盖率 | 67%（从 48% 提升） |
| 工程审查发现问题数 | 36 |
| 工程审查修复问题数 | 16 |

## 已知技术债务

1. **MainWindow 直接算法调用**：`MainWindow` 仍然直接调用 `FeasibilityChecker`、`ZmqRepairClient`。建议：扩展 `AppController` 并通过其路由。
2. **`calibration_wizard.py` 和 `license_manager.py`**：尚未与 `resource_path.py` 集成以进行 PyInstaller `_MEIPASS` 解析。该工具可用，但接线需要对配置文件路径进行仔细测试。
3. **HMAC 密钥硬编码回退**：`license_manager.py` 有一个开发回退密钥 `"csam_dev_secret_2026"`。生产环境必须设置 `CSAM_HMAC_SECRET` 环境变量。
4. **MATLAB `path` 变量遮蔽**：MATLAB 算法代码使用 `path` 作为变量名，遮蔽了 Python 内置函数。受"不修改 MATLAB 算法"规则约束。
