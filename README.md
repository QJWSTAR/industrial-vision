# CSAM Repair — 冷喷涂增材制造缺陷修复软件

**版本**：1.0.0 | **状态**：Release Candidate

## 概述

CSAM Repair 是一款工业级桌面应用，用于冷喷涂增材制造（CSAM）缺陷修复。它提供了从点云加载到 G-code 导出的完整工作流程，集成了路径规划、形貌预测和 3D 可视化功能。

### 主要特性

- **点云处理**：加载带法线的 CSV/TXT/XYZ 点云数据
- **缺陷选取**：交互式 3D 缺陷区域选取
- **演示数据**：内置合成缺陷生成 — 无需外部数据即可上手
- **路径规划**：基于可配置扫描参数生成最优修复路径
- **形貌预测**：逐层预测沉积形貌
- **G-Code 导出**：将修复路径导出为工业级 G-code（.nc）
- **PDF 报告**：生成包含修复前后对比的专业修复报告
- **MATLAB 集成**：基于 ZeroMQ + Protocol Buffers 的 MATLAB R2025b 算法服务（唯一生产通信路径，详见 [docs/COMMUNICATION.md](docs/COMMUNICATION.md)）
- **许可证管理**：RSA-2048 许可证验证，带机器绑定

## 快速开始

### 前置条件

- Python 3.10+
- pip

### 安装

**建议：使用虚拟环境。**

```bash
# 克隆仓库
git clone <repository-url>
cd <project-directory>

#（推荐）创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 升级 pip（可编辑安装所需）
pip install --upgrade pip

# 安装基础依赖
pip install -r requirements.txt

# 可选：安装全功能版本（loguru）
pip install -e ".[full]"

# 可选：安装开发工具（pytest、flake8、bandit）
pip install -e ".[dev]"
```

> **macOS 用户注意事项**：如果遇到 `error: can't create or remove files in install directory`，这是 macOS 系统 Python 的权限问题。使用虚拟环境（`python3 -m venv venv`）即可解决。

### 运行

```bash
python run_app.py
```

如果已作为包安装：

```bash
pip install -e .
csam-repair
```

## 连接 MATLAB（可选但推荐）

软件支持 MATLAB R2025b 作为工业算法引擎。连接后可获得真实的路径规划和形貌预测计算结果。

### 启动 MATLAB Bridge 服务

1. 打开 MATLAB R2025b
2. 将工作目录切换到项目根目录
3. 运行以下命令：

```matlab
matlab_bridge_server
```

MATLAB 会共享引擎会话并启动 Bridge 服务（默认端口 5555）。

### 验证连接

启动 Python GUI 后，执行路径规划时软件会自动连接 MATLAB。如果 MATLAB 不可用，软件会自动降级到 Python 启发式算法（日志中会显示降级信息）。

> 详细 MATLAB 集成说明请参阅 [docs/MATLAB_INTEGRATION.md](docs/MATLAB_INTEGRATION.md)

### 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CSAM_ALGORITHM_ENGINE` | 算法引擎模式（auto/matlab/python） | auto |
| `CSAM_ZMQ_ADDRESS` | ZeroMQ 通信地址 | tcp://127.0.0.1:5555 |
| `CSAM_MATLAB_SHARED_NAME` | MATLAB 共享会话名称 | matlab_bridge |
| `CSAM_LOG_LEVEL` | 日志级别 | INFO |

## 使用指南

软件遵循 **两步工作流程**，并集成导出功能：

```
Step 1: Load & Path Planning → Step 2: Morphology Prediction → Export (G-code / PDF)
```

### 使用演示数据快速开始

无需外部数据文件。当您点击 **"📂 加载点云"** 并取消文件对话框时，软件会询问是否加载内置演示数据用于测试。

### 步骤 1：加载点云与路径规划

1. 在左侧面板点击 **"📂 加载点云"** 选择点云文件
   - 如果取消文件对话框，可以选择加载演示数据
2. 加载后，3D 视图会自动切换到 **选取模式** — 拖动鼠标选取缺陷区域（以红色高亮显示）
3. 从下拉菜单选择一种 **材料**（例如 STEEL_316L）
4. 调整 **路径规划参数**（层高、扫描角度、步长等）
   - 将鼠标悬停在任意参数上可查看工具提示说明
5. 点击 **"🔧 生成修复路径"** 计算路径点
6. 路径规划完成后，点击 **"📤 导出 G-code"** 保存刀具路径

**支持的点云格式**：
| 格式 | 扩展名 | 必需列 | 说明 |
|--------|-----------|-----------------|-------|
| CSV | `.csv` | `x, y, z` 或 `x, y, z, nx, ny, nz` | 逗号分隔。若为 6 列，则第 4-6 列视为法线。 |
| TXT | `.txt` | `x, y, z` 或 `x, y, z, nx, ny, nz` | 与 CSV 相同。 |
| XYZ | `.xyz` | `x, y, z` | 空格分隔。 |
| ASC | `.asc` | `x, y, z` | 空格分隔。 |

> **建议**：使用带法线的 6 列 CSV（`x, y, z, nx, ny, nz`）以获得最佳可视化效果。

### 缺陷选取控件

- **🧭 导航模式 / ✂️ 选取模式**：在导航（旋转/缩放）和选取模式之间切换
- **模式**：选择选取方式 — 矩形框选 (Rectangle), 自由选区 (Freehand), 区域选择 (Brush Add), 取消选择 (Brush Remove)
- **笔刷**：调整笔刷半径（仅适用于笔刷模式）
- **↩ 撤销**：撤销上一次选取操作
- **✕ 清除选区**：清除所有选取
- **⇄ 反选**：反选选取

### 步骤 2：形貌预测

1. 在左侧面板点击 **"02 形貌预测"** 切换到预测页面
2. 调整 **冷喷涂参数**（粒子速度、喷嘴直径等）
   - **临界速度** (Critical Velocity) 由材料数据库自动计算，无法手动编辑
   - 将鼠标悬停在任意参数上可查看工具提示说明
3. 可选：点击 **"🔍 可行性检查"** 验证当前参数是否合适
4. 点击 **"🔮 执行形貌预测"** 模拟沉积过程
5. 预测完成后，点击 **"📄 导出 PDF 报告"** 生成报告

### 3D 可视化控件

- **视角**：在等轴测、俯视、侧视和正视之间切换
- **曲面 / 缺陷 / 路径 / 喷嘴 / 色温**：切换不同图层的可见性
- **▶ 逐层动画**：播放沉积过程的逐层动画
- **层 slider**：浏览单个沉积层

### 导出

**G-Code 导出**（路径规划后可用）：
1. 在路径规划面板点击 **"📤 导出 G-code"**
2. 选择保存位置（默认：`repair.nc`）
3. 生成的 G-code 包含安全 Z 轴移动、送粉 M 代码和进给速率映射

**PDF 报告**（形貌预测后可用）：
1. 在形貌预测面板点击 **"📄 导出 PDF 报告"**
2. 选择保存位置（默认：`repair_report.pdf`）
3. 报告内容包括：扫描信息、工艺参数、结果摘要、修复前后 3D 对比以及高度色温图

> **注意**：PDF 导出依赖 `reportlab`，已作为核心依赖随基础安装提供，无需额外安装 `[full]`。

## 打包与分发

### 构建可执行文件

项目使用 PyInstaller 进行跨平台打包。提供了生产级 spec 文件（`repair_app.spec`），包含运行时钩子、完整的隐藏导入以及 Qt DLL 的 UPX 排除配置。

**Windows：**
```cmd
build_windows.bat
```
输出：`dist/CSAM_Repair.exe`（单文件可执行程序）

**macOS：**
```bash
bash build_macos.sh
```
输出：`dist/CSAM_Repair.app`（应用程序包）

### 运行时配置

将 `.env.example` 复制为 `.env`，并为生产部署配置环境变量：

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `CSAM_HMAC_SECRET` | 用于许可证验证的 HMAC 密钥 | 开发回退密钥 |
| `CSAM_ZMQ_ADDRESS` | ZMQ 传输地址 | 平台默认值 |
| `CSAM_LOG_LEVEL` | 日志级别 | `INFO` |
| `CSAM_ENGINE_ADDRESS` | MATLAB 引擎地址 | 平台默认值 |

### 安装程序建议

- **Windows**：使用 [Inno Setup](https://jrsoftware.org/isinfo.php) 或 [NSIS](https://nsis.sourceforge.io/) 创建用户友好的安装程序。`docs/07_开发者文档.md` 中提供了 Inno Setup 脚本模板示例。
- **macOS**：以签名 `.dmg` 磁盘映像形式分发。分发前运行 `codesign` 和 `notarize`。

### 图标配置

构建脚本会通过在项目根目录搜索 `p1.ico`、`p1.png` 或 `p1.jpg` 来自动检测应用图标。请在构建前将图标文件放置在该目录。

详细安装说明请参阅 [docs/UserManual/02_安装指南.md](docs/UserManual/02_安装指南.md)，开发者文档请参阅 [docs/07_开发者文档.md](docs/07_开发者文档.md)。

## 架构

```
csam-repair/
├── run_app.py                 # 应用入口
├── matlab_bridge_server.m     # MATLAB Bridge 服务入口
├── repair_app/
│   ├── core/                  # 核心算法（路径规划、形貌预测 Python 原型）
│   ├── bridge/                # Bridge 通信层（ZeroMQ + Protobuf v2.1）
│   │   ├── adapters/          # MatlabAdapter + LegacyZmqClient + MatlabEngineProxy
│   │   ├── communication/     # ZMQ REP/REQ 服务端/客户端
│   │   └── services/          # MATLAB 服务封装
│   ├── communication/         # 旧版通信层（已弃用，保留兼容）
│   ├── domain/                # 领域模型 + 引擎接口
│   ├── engine/                # LocalEngine（Python 原型引擎）
│   ├── export/                # G-code 导出 + PDF 报告生成
│   ├── platform/              # 平台抽象（ZMQ 传输、CJK 字体）
│   ├── repository/            # 文件 I/O + 材料数据访问
│   ├── service/               # 业务逻辑编排
│   ├── tests/                 # 测试套件（276 个测试）
│   ├── tools/                 # Profiler + Benchmark
│   ├── ui/                    # GUI（PySide6）
│   │   ├── main_window.py     # 主窗口
│   │   ├── repair_visualizer.py    # 3D 可视化
│   │   ├── profile_result_panel.py # MATLAB 结果原生渲染面板
│   │   └── workers.py         # 后台工作线程
│   └── utils/                 # 配置、日志、许可证、崩溃处理
├── 路径规划/                   # MATLAB 路径规划 + 形貌预测算法
├── 形貌预测/                   # MATLAB 形貌预测算法
├── morphology_prediction/     # CFD 数据（pointlist/velocitylist）
├── docs/                      # 完整文档体系
├── scripts/                   # 验证脚本
├── .github/workflows/ci.yml  # CI/CD 流水线
├── pyproject.toml             # 构建配置
├── requirements.txt           # 运行时依赖
└── README.md                  # 本文件
```

## 开发

### 运行测试

```bash
# 全部测试（276 个测试）
pytest repair_app/tests/ repair_app/bridge/tests/ -v

# 仅单元测试
pytest repair_app/tests/test_stage1.py -v

# 压力测试
pytest repair_app/tests/test_stress.py -v

# 分层测试（Controller / Service / Repository）
pytest repair_app/tests/test_layers.py -v
```

### 性能分析

```bash
python repair_app/tools/profiler.py --mode all --size medium
python repair_app/tools/benchmark.py
```

### 代码质量

```bash
# 安装 pre-commit 钩子（推荐）
pip install pre-commit
pre-commit install
pre-commit run --all-files

# 手动代码检查
flake8 repair_app/ --count --max-complexity=15
bandit -r repair_app/ -x repair_app/tests/ -ll
```

## 文档导航

| 文档 | 说明 | 适合读者 |
|------|------|---------|
| [docs/UserManual/](docs/UserManual/) | 完整用户手册（11 篇，从安装到术语解释） | 操作员、工程师 |
| [docs/07_开发者文档.md](docs/07_开发者文档.md) | 项目结构、模块职责、测试、构建 | 开发者 |
| [docs/08_运维手册.md](docs/08_运维手册.md) | 日志、备份、升级、性能调优 | 运维人员 |
| [docs/10_架构文档.md](docs/10_架构文档.md) | 系统架构图、模块关系、部署拓扑 | 架构师 |
| [docs/09_API文档.md](docs/09_API文档.md) | 公开接口签名、异常层次 | 开发者 |
| [docs/MATLAB_INTEGRATION.md](docs/MATLAB_INTEGRATION.md) | MATLAB R2025b 集成快速指南 | 算法工程师 |
| [docs/MATLAB_R2025B_Validation_Playbook.md](docs/MATLAB_R2025B_Validation_Playbook.md) | MATLAB 验证手册（19 章） | QA 工程师 |
| [docs/COMMUNICATION.md](docs/COMMUNICATION.md) | 通信架构决策（ZeroMQ + Protobuf v2.1） | 架构师 |
| [docs/BRIDGE_ARCHITECTURE.md](docs/BRIDGE_ARCHITECTURE.md) | Bridge 层详细架构 | 开发者 |
| [docs/PACKAGING_GUIDE.md](docs/PACKAGING_GUIDE.md) | PyInstaller 打包指南 | 发布工程师 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更记录 | 所有人 |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | 发布检查清单 | 发布工程师 |
| [docs/RELEASE_NOTES_V1.0.md](docs/RELEASE_NOTES_V1.0.md) | v1.0 发布说明 | 所有人 |
| [docs/checklists/](docs/checklists/) | 验收/兼容性/部署/回归/冒烟测试清单 | QA |
| [docs/archive/](docs/archive/) | 历史文档归档（迁移报告、集成报告等） | 历史参考 |

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

应用在无许可证文件的情况下即可启动（会记录一条警告，但不会阻止功能）。要启用完整的许可证验证，请将 `license.key` 和 `public_key.pem` 放置在 `config/` 目录中。

## 支持

如需技术支持，请联系 CSAM 团队。
