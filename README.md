# CSAM Repair — 冷喷涂增材制造缺陷修复软件

**版本**：1.0.0 (Release Candidate) | **协议**：v2.1 (ZeroMQ + Protobuf) | **MATLAB**：R2025b

## 这是什么

CSAM Repair 是一款工业级桌面软件，用于冷喷涂增材制造（Cold Spray Additive Manufacturing，CSAM）的缺陷修复。它将 MATLAB 工业算法与 Python GUI 结合，提供从点云加载到 G-code 导出的完整工作流。

## 能做什么

- **加载点云**：支持 CSV / TXT / XYZ / ASC 格式，内置演示数据
- **选取缺陷**：交互式 3D 缺陷区域选取（矩形框选 / 自由选区 / 笔刷）
- **路径规划**：调用 MATLAB `run_path_planning.m` 生成修复航点
- **形貌预测**：调用 MATLAB `run_profile_prediction.m` 预测沉积形貌
- **原生渲染**：Python GUI 直接渲染 MATLAB 结果（沉积网格 / 逐层轮廓 / 粒子分布 / 均匀性仪表盘）
- **导出结果**：G-code（.nc 刀具路径）+ PDF 修复报告
- **自动降级**：MATLAB 不可用时自动降级到 Python 启发式算法

## 5 分钟快速开始

### 1. 安装 Python 依赖

```powershell
# 克隆仓库
git clone <repository-url>
cd industrial-vision

# 创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows
# source venv/bin/activate           # macOS / Linux

# 安装依赖
pip install -r requirements.txt
```

> 要求 Python 3.10-3.12（推荐 3.12）

### 2. 启动 Python GUI

```powershell
python run_app.py
```

### 3.（可选）启动 MATLAB 算法引擎

```matlab
% 在 MATLAB R2025b 中执行
cd('D:\work\demo\industrial-vision')
pyenv('Version', 'D:\work\demo\industrial-vision\venv\Scripts\python.exe')
matlab_bridge_server
```

> 不启动 MATLAB 也能运行 — 软件会自动降级到 Python 启发式算法。

### 4. 完成一次完整演示

1. 点击 **"加载点云"** → 取消对话框 → 选择加载演示数据
2. 切换到 **选取模式** → 拖动鼠标选取缺陷区域
3. 选择材料（如 STEEL_316L）→ 点击 **"生成修复路径"**
4. 切换到 **"02 形貌预测"** → 点击 **"执行形貌预测"**
5. 点击 **"导出 G-code"** 和 **"导出 PDF 报告"**

> 详细步骤请参阅 [docs/01_快速开始.md](docs/01_快速开始.md)

## 项目结构

```
industrial-vision/
├── run_app.py                      # Python 应用入口
├── matlab_bridge_server.m          # MATLAB Bridge 服务入口
├── repair_protocol.proto           # Protobuf v2.1 协议定义
├── repair_app.spec                 # PyInstaller 打包配置
├── requirements.txt                # Python 运行时依赖
├── pyproject.toml                  # 构建配置
│
├── repair_app/                     # Python 主应用
│   ├── ui/                         # GUI（PySide6）
│   │   ├── main_window.py          #   主窗口
│   │   ├── repair_visualizer.py    #   3D 可视化
│   │   ├── profile_result_panel.py #   MATLAB 结果原生渲染
│   │   └── workers.py              #   后台工作线程
│   ├── bridge/                     # Bridge 通信层（唯一生产路径）
│   │   ├── adapters/               #   MatlabAdapter + LegacyZmqClient + MatlabEngineProxy
│   │   ├── communication/          #   ZMQ REP/REQ + Protobuf v2.1
│   │   └── services/               #   MATLAB 服务封装
│   ├── core/                       # 核心算法（Python 原型，降级用）
│   ├── domain/                     # 领域模型 + 引擎接口
│   ├── engine/                     # LocalEngine（Python 降级引擎）
│   ├── export/                     # G-code + PDF 导出
│   ├── service/                    # 业务逻辑编排
│   ├── repository/                 # 文件 I/O + 材料数据
│   ├── platform/                   # 平台抽象（ZMQ 传输、CJK 字体）
│   ├── communication/              # 旧版通信层（已弃用）
│   ├── tests/                      # 单元测试（15 个文件，276 个测试）
│   ├── tools/                      # 性能分析工具
│   └── utils/                      # 配置、日志、许可证、崩溃处理
│
├── 路径规划/                        # MATLAB 形貌预测算法（12 个 .m 文件）
├── 形貌预测/                        # MATLAB 路径规划算法（6 个 .m 文件）
├── morphology_prediction/          # CFD 数据（pointlist / velocitylist）
├── config/                         # 标定数据库 + 许可证
├── docs/                           # 完整文档（见下方导航）
├── scripts/                        # 验证脚本
└── .github/                        # CI/CD + Issue 模板
```

> **注意**：`路径规划/` 和 `形貌预测/` 两个目录名与实际内容互换（历史命名原因）。`路径规划/` 存放形貌预测算法，`形貌预测/` 存放路径规划算法。详见 [docs/04_MATLAB算法说明.md](docs/04_MATLAB算法说明.md)。

## 如何启动 MATLAB

```matlab
% 1. 打开 MATLAB R2025b
% 2. 配置 Python 环境
pyenv('Version', '<项目路径>/venv/Scripts/python.exe')

% 3. 切换到项目根目录
cd('<项目路径>')

% 4. 启动 Bridge 服务
matlab_bridge_server
```

MATLAB 会共享引擎会话（名称 `matlab_bridge`）并监听 `tcp://127.0.0.1:5555`。命令窗口会阻塞 — 这是正常的。

## 如何启动 Python

```powershell
python run_app.py
```

或安装后使用命令行：

```powershell
pip install -e .
csam-repair
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CSAM_ALGORITHM_ENGINE` | 算法引擎模式（auto / matlab / python） | `auto` |
| `CSAM_ZMQ_ADDRESS` | ZeroMQ 通信地址 | `tcp://127.0.0.1:5555` |
| `CSAM_MATLAB_SHARED_NAME` | MATLAB 共享会话名称 | `matlab_bridge` |
| `CSAM_LOG_LEVEL` | 日志级别 | `INFO` |
| `CSAM_HMAC_SECRET` | 许可证 HMAC 密钥（生产必须设置） | 开发回退密钥 |

> 完整环境变量列表请参阅 [docs/02_安装部署.md](docs/02_安装部署.md)

## 打包

**Windows：**
```cmd
build_windows.bat
```
输出：`dist/CSAM_Repair.exe`

**macOS：**
```bash
bash build_macos.sh
```
输出：`dist/CSAM_Repair.app`

> Linux 仅支持从源码运行，详见 [docs/02_安装部署.md](docs/02_安装部署.md)

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部测试（276 个）
pytest repair_app/tests/ repair_app/bridge/tests/ -v

# 端到端验证（27 项）
python scripts/release_validation.py

# 代码检查
flake8 repair_app/ --count --max-complexity=15
bandit -r repair_app/ -x repair_app/tests/ -ll
```

> 详细开发指南请参阅 [docs/07_开发指南.md](docs/07_开发指南.md)

## 文档导航

| 编号 | 文档 | 适合读者 |
|------|------|---------|
| 01 | [快速开始](docs/01_快速开始.md) | 所有人 |
| 02 | [安装部署](docs/02_安装部署.md) | 用户、运维 |
| 03 | [用户使用手册](docs/03_用户使用手册.md) | 操作员、工程师 |
| 04 | [MATLAB 算法说明](docs/04_MATLAB算法说明.md) | 算法工程师 |
| 05 | [软件架构](docs/05_软件架构.md) | 架构师 |
| 06 | [通信协议](docs/06_通信协议.md) | 开发者、架构师 |
| 07 | [开发指南](docs/07_开发指南.md) | 开发者 |
| 08 | [API 接口](docs/08_API接口.md) | 开发者 |
| 09 | [测试验证](docs/09_测试验证.md) | QA、发布工程师 |
| 10 | [FAQ](docs/10_FAQ.md) | 所有人 |
| 11 | [故障排查](docs/11_故障排查.md) | 操作员、运维 |
| — | [CHANGELOG](docs/CHANGELOG.md) | 所有人 |
| — | [RELEASE_NOTES](docs/RELEASE_NOTES.md) | 所有人 |
| — | [archive/](docs/archive/) | 历史参考 |

## 许可证

MIT License。详见 [LICENSE](LICENSE)。

应用在无许可证文件的情况下即可启动（会记录警告）。要启用完整许可证验证，将 `license.key` 和 `public_key.pem` 放置在 `config/` 目录中。

## 贡献

欢迎提交 Pull Request。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [docs/07_开发指南.md](docs/07_开发指南.md)。
