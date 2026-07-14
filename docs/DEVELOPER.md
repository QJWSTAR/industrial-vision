# 开发者文档

CSAM Repair — 冷喷涂增材制造缺陷修复软件

## 架构概述

应用程序采用分层架构，具有严格的依赖方向：

```
UI 层（PySide6）
    ↓ 调用
控制器层（AppController, WorkflowController）
    ↓ 调用
服务层（RepairEngineService, ExportService, FileService, ...）
    ↓ 调用
领域层（模型、接口）+ 算法层（PathPlanner, MorphologyPredictor）
    ↓ 调用
仓储层（FileRepository, MaterialRepository）+ 基础设施（ZMQ, Protobuf）
```

### 层级职责

| 层级 | 包 | 职责 |
|-------|---------|---------------|
| UI | `repair_app/ui/` | PySide6 控件、3D 可视化、用户交互 |
| 控制器 | `repair_app/controller/` | 工作流状态机、UI 到服务的路由 |
| 服务 | `repair_app/service/` | 业务逻辑编排、用例协调 |
| 领域 | `repair_app/domain/` | 领域模型、引擎接口（IEngine, IPathPlanner） |
| 核心/算法 | `repair_app/core/` | 路径规划、形貌预测、可行性检查 |
| 仓储 | `repair_app/repository/` | 文件 I/O、材料数据库访问 |
| 通信（生产） | `repair_app/bridge/` | 通信桥接层：MatlabService、BridgeClient、LegacyZmqClient 适配器、心跳、结构化异常 |
| 通信（旧版） | `repair_app/communication/` | 旧版 ZMQ 客户端（已弃用，保留向后兼容）、Protobuf 序列化（仍被 bridge 复用） |
| 导出 | `repair_app/export/` | G-code 生成、PDF 报告生成 |
| 平台 | `repair_app/platform/` | 操作系统抽象（ZMQ 传输、CJK 字体） |
| 工具 | `repair_app/utils/` | 配置、日志、许可证、崩溃处理器、资源路径 |

### 关键约束

UI 层不得直接调用算法模块、MATLAB 功能或数据库访问。所有业务交互都通过服务层或控制器层进行。

### 通信层架构（当前生产路径）

```
MainWindow
  ↓ _Coord.create_zmq_client()
CoordinationService
  ↓ 返回 LegacyZmqClient (bridge 适配器)
LegacyZmqClient (repair_app/bridge/adapters/legacy_adapter.py)
  ↓ 委托
BridgeClient (repair_app/bridge/communication/zmq_client.py)
  ↓ ZMQ REQ/REP
Engine / MATLAB Server
```

**通信入口**：`CoordinationService.create_zmq_client()` 是 UI 层获取通信客户端的唯一入口。
它返回 bridge 适配器 `LegacyZmqClient`（API 与旧版 `ZmqRepairClient` 完全兼容）。

**弃用模块**：`repair_app/communication/zmq_client.py`（`ZmqRepairClient`）已标记为 deprecated，
实例化时发出 `DeprecationWarning`。保留用于向后兼容和现有测试，将在下一大版本移除。
`repair_app/communication/repair_serialization.py` 和 `repair_protocol_pb2.py` 仍被 bridge 层复用，不属于弃用范围。

**已弃用的 TCP/JSON/v3.0/5570 通信栈**：以下模块已全部标记为 DEPRECATED，不得用于生产代码：
- `repair_app/engine/matlab_engine.py`（TCP 客户端，端口 5570）
- `repair_app/engine/factory.py`（MatlabEngine 工厂）
- `repair_app/engine/lifecycle.py`（MatlabEngine 生命周期管理）
- `repair_app/bridge/protocol_v3/`（v3.0 通用算法协议）
- `matlab_server/`（TCP/JSON MATLAB 服务端）

这些模块仅保留用于向后兼容与 `test_matlab_platform.py` 的 mock-server 测试。
完整的通信架构定稿与弃用说明详见 `docs/COMMUNICATION.md`。

**新增通信应使用**：
```python
# 适配器（与旧版 API 兼容）
from repair_app.bridge.adapters.legacy_adapter import LegacyZmqClient

# 业务层门面（推荐）
from repair_app.bridge import MatlabService
```

## 开发环境设置

```bash
# 克隆
git clone <repository-url>
cd csam-repair

# 虚拟环境
python3 -m venv venv
source venv/bin/activate  # macOS
# venv\Scripts\activate   # Windows

# 安装开发依赖
pip install --upgrade pip
pip install -e ".[dev]"

# 安装 pre-commit 钩子
pre-commit install
```

## 测试

### 测试套件

15 个文件中共有 270 个测试：

| 测试文件 | 测试数 | 范围 |
|-----------|-------|-------|
| `test_fixes.py` | 7 | 缺陷修复验证 |
| `test_layers.py` | 26 | 控制器、服务、仓储层 |
| `test_stage1.py` | 21 | 核心算法（路径规划器、缺陷样本） |
| `test_stage2.py` | 25 | 通信（ZMQ、Protobuf、序列化） |
| `test_stage3.py` | 17 | UI 组件（缺陷选择器、可视化器） |
| `test_stage4.py` | 16 | 许可证管理器、报告生成 |
| `test_stage5.py` | 17 | 验证流水线 |
| `test_stress.py` | 7 | 压力和性能测试 |
| `test_migration.py` | 10 | 通信层迁移验证（bridge 集成） |
| `test_bridge.py` | 41 | bridge 通信层单元/集成测试 |
| 其他 | 83 | 自动更新、崩溃处理、法向量、覆盖率等 |

### 运行测试

```bash
# 所有测试
pytest

# 带覆盖率报告
pytest --cov=repair_app --cov-report=term-missing

# 特定测试文件
pytest repair_app/tests/test_stage1.py -v

# 仅基准测试
pytest repair_app/tests/test_stress.py -v --benchmark-only
```

### 测试约定

- 测试通过 CI 矩阵在 macOS、Windows 和 Linux 上运行
- 没有测试应依赖于特定操作系统或需要外部服务
- MATLAB ZMQ 测试使用模拟套接字，而非真实的 ZMQ 连接
- 使用 `np.random.randint` 生成随机数据（不使用 `random` 模块）

## 编码规范

- 使用 `numpy` 向量化操作而非 Python 循环
- 使用 `np.random.randint` 生成随机数（不使用 `random` 模块）
- 禁止 `try-except-pass` — 必须始终记录错误
- 禁止使用 `np.savez`/`np.load` 配合 `allow_pickle=True` — 使用 JSON 存储元数据
- HMAC 密钥从环境变量读取，不硬编码
- 增量变更：每次提交最多 5 个文件
- 每个子任务后运行所有测试；如有任何测试失败则停止并修复
- 小型 git 提交：每次提交一个逻辑变更

## CI/CD 流水线

### 持续集成（`.github/workflows/ci.yml`）

矩阵：Ubuntu、macOS、Windows × Python 3.10、3.11、3.12

步骤：
1. 检出代码
2. 安装 Python
3. `pip install -e ".[dev]"`
4. 运行 pre-commit 钩子
5. 运行 pytest 并生成覆盖率
6. 运行 flake8 和 bandit

### 发布流水线（`.github/workflows/release.yml`）

通过推送标签（`v*.*.*`）触发：

1. 在 Windows 和 macOS 上构建
2. 安装依赖 + PyInstaller
3. 运行测试
4. 通过 `repair_app.spec` 构建可执行文件
5. 上传产物到 GitHub Releases

触发发布：
```bash
git tag v1.0.0
git push origin v1.0.0
```

## 打包指南

### PyInstaller（推荐）

生产级 spec 文件 `repair_app.spec` 配置如下：

- **运行时钩子**：`hooks/pyi_runtime_hook.py` 在应用启动前设置 SSL 证书、Qt 插件、matplotlib 配置目录、ZMQ 前缀和字体缓存
- **隐藏导入**：显式声明了 40+ 个模块，包括所有 `repair_app` 子包、PySide6 模块、protobuf、zmq、matplotlib、scipy、reportlab、cryptography、shapely
- **资源打包**：`material_db.json`、`calibration_db.json`、`repair_protocol.proto` 打包到可执行文件中
- **UPX 排除**：Qt DLL（`Qt6Core.dll`、`Qt6Gui.dll` 等）排除在 UPX 压缩之外，以防止加载失败
- **模块排除**：`PySide6.QtQml`、`QtQuick`、`QtDesigner`、`QtHelp` 被排除以减小打包体积
- **macOS bundle**：`.app` bundle，包含 `CFBundleIdentifier`、`NSHighResolutionCapable`、`LSMinimumSystemVersion`

构建命令：
```bash
# Windows
build_windows.bat

# macOS
bash build_macos.sh

# 手动
pyinstaller --clean repair_app.spec
```

### 资源路径解析

`repair_app/utils/resource_path.py` 提供感知 PyInstaller 的路径解析：

- `is_frozen()` — 检查是否在 PyInstaller bundle 内运行
- `get_bundle_dir()` — 返回 bundle 目录（冻结时为 `sys._MEIPASS`，否则为项目根目录）
- `get_resource_path(filename)` — 解析相对于 bundle 的资源文件
- `get_config_dir()` — 返回配置目录（优先检查 `exe_dir/config/` 用于用户可修改的配置，回退到 `_MEIPASS/config/` 用于打包的默认配置）
- `get_data_dir()` — 返回运行时数据文件的数据目录

### Nuitka 评估

Nuitka 是一个替代的 Python 编译器，可生成原生机器码。针对本项目的评估：

**不推荐**，原因如下：

1. **PySide6 兼容性**：PyInstaller 通过官方钩子提供一流的 PySide6 支持。Nuitka 的 PySide6 支持不够成熟，在 Qt 插件发现方面存在已知问题。
2. **C 扩展依赖**：项目依赖 numpy、scipy、pyzmq、cryptography 和 shapely — 都是 C 扩展包。PyInstaller 通过成熟的钩子处理这些依赖。Nuitka 需要为每个包手动添加 `--include-package-data` 标志。
3. **Protobuf 生成代码**：`repair_protocol_pb2.py` 使用动态模块加载模式，Nuitka 的静态分析可能无法正确解析。
4. **构建复杂性**：Nuitka 需要构建机器上有 C 编译器工具链。PyInstaller 是纯 Python 的，无需额外工具链即可跨平台工作。
5. **调试**：PyInstaller 的 `--debug` 模式和日志输出更便于排查缺失模块的问题。

**结论**：对于此 PySide6 + 科学计算技术栈，PyInstaller 是最佳选择。Nuitka 会增加复杂性而无法带来相应的收益。

## 安装程序模板

### Windows — Inno Setup

创建 `installer/windows/installer.iss`：

```iss
[Setup]
AppName=CSAM Repair
AppVersion=1.0.0
AppPublisher=CSAM Team
DefaultDirName={pf}\CSAM_Repair
DefaultGroupName=CSAM Repair
OutputDir=..\dist_installer
OutputBaseFilename=CSAM_Repair_Setup_v1.0.0
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\CSAM_Repair.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\*"; DestDir: "{app}\config"; Flags: recursesubdirs

[Icons]
Name: "{group}\CSAM Repair"; Filename: "{app}\CSAM_Repair.exe"
Name: "{commondesktop}\CSAM Repair"; Filename: "{app}\CSAM_Repair.exe"

[Run]
Filename: "{app}\CSAM_Repair.exe"; Description: "Launch CSAM Repair"; Flags: nowait postinstall skipifsilent
```

构建：
```cmd
iscc installer\windows\installer.iss
```

### Windows — NSIS 替代方案

```nsi
OutFile "CSAM_Repair_Setup_v1.0.0.exe"
InstallDir "$PROGRAMFILES64\CSAM_Repair"
Page directory
Page instfiles
Section ""
    SetOutPath "$INSTDIR"
    File "dist\CSAM_Repair.exe"
    CreateDirectory "$INSTDIR\config"
    File /r "config\*.*"
    CreateShortcut "$DESKTOP\CSAM Repair.lnk" "$INSTDIR\CSAM_Repair.exe"
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd
```

### macOS — DMG

```bash
# 构建 CSAM_Repair.app 之后：

# 代码签名
codesign --deep --force --verify --verbose=4 \
    --sign "Developer ID Application: Your Name (TEAM_ID)" \
    dist/CSAM_Repair.app

# 公证
xcrun notarytool submit dist/CSAM_Repair.app.zip \
    --apple-id "your@email.com" \
    --team-id "TEAM_ID" \
    --password "app-specific-password" \
    --wait

# 装订
xcrun stapler staple dist/CSAM_Repair.app

# 创建 DMG
hdiutil create -volname "CSAM Repair" \
    -srcfolder dist/CSAM_Repair.app \
    -ov -format UDZO \
    dist/CSAM_Repair_v1.0.0.dmg
```

## 图标配置

构建脚本自动检测应用程序图标：
1. 在项目根目录中搜索 `p1.ico`（Windows 首选）、`p1.png` 或 `p1.jpg`
2. 如果找到，图标将嵌入到可执行文件和 macOS bundle 中

创建图标：
- **Windows**：使用包含多种分辨率（16x16、32x32、48x48、256x256）的 `.ico` 文件
- **macOS**：使用 `.icns` 文件（可使用 `iconutil` 从 PNG 生成）

## DLL 包含

PyInstaller 自动检测并包含所需的 DLL：
- **Windows**：`Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll`、`Qt6OpenGL.dll`、`Qt6Network.dll`、`Qt6Svg.dll`、Visual C++ 运行时、`python3.dll`
- **macOS**：Qt 框架、Python 共享库、ZMQ 库

Qt DLL 禁用 UPX 压缩以防止加载失败。其他二进制文件进行压缩以减小打包体积。

## 调试

### 启用调试日志

```bash
export CSAM_LOG_LEVEL=DEBUG  # macOS/Linux
set CSAM_LOG_LEVEL=DEBUG     # Windows
```

### PyInstaller 调试模式

```bash
pyinstaller --debug=all --log-level=DEBUG repair_app.spec
```

### 常见问题

| 症状 | 原因 | 解决方案 |
|---------|-------|-----|
| 找不到模块 | 缺少隐藏导入 | 在 spec 中添加到 `hiddenimports` |
| DLL 加载失败 | 缺少 VC++ 运行时 | 安装 Visual C++ Redistributable |
| 找不到 Qt 插件 | 未设置插件路径 | 检查运行时钩子 `QT_PLUGIN_PATH` |
| matplotlib 后端错误 | 导入顺序冲突 | 检查 `service/__init__.py` 中的 PEP 562 延迟导入 |
| ZMQ 连接被拒绝 | MATLAB 引擎未运行 | 启动 MATLAB 引擎，检查 `CSAM_ZMQ_ADDRESS` |
| 字体渲染问题 | 缺少 CJK 字体 | 检查 `repair_app/platform/fonts.py` 字体列表 |
| 许可证验证失败 | 机器 ID 不匹配 | 检查 `uuid.getnode()` 输出，重新生成许可证 |

## Pre-commit 钩子

`.pre-commit-config.yaml` 运行：
- flake8（代码检查，max-line-length=120）
- bandit（安全分析）
- trailing-whitespace
- end-of-file-fixer

手动运行：
```bash
pre-commit run --all-files
```
