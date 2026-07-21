# CSAM Repair — 冷喷涂增材制造缺陷修复软件

**版本**：1.0.0 (Stable Release) | **协议**：v2.1 (ZeroMQ + Protobuf) | **MATLAB**：R2025b

## 这是什么

CSAM Repair 是一款工业级桌面软件，用于冷喷涂增材制造（Cold Spray Additive Manufacturing，CSAM）的缺陷修复。它将 MATLAB 工业算法与 Python GUI 结合，提供从点云加载到 G-code 导出的完整工作流。

## 能做什么

- **加载点云**：支持 CSV / TXT / XYZ / ASC 格式，内置演示数据
- **选取缺陷**：交互式 3D 缺陷区域选取（矩形框选 / 自由选区 / 笔刷）
- **路径规划**：调用 MATLAB `run_path_planning.m` 生成修复航点
- **形貌预测**：调用 MATLAB `run_profile_prediction.m` 预测沉积形貌
- **原生渲染**：Python GUI 直接渲染 MATLAB 结果（沉积网格 / 逐层轮廓 / 粒子分布 / 均匀性仪表盘）
- **导出结果**：G-code（.nc 刀具路径）+ PDF 修复报告
- **MATLAB 自动启动**：软件自动以 `-nodesktop -nosplash -r` 模式启动 MATLAB Bridge，用户无需手动操作

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

### 3. MATLAB 自动启动（无需手动操作）

软件启动后会自动以 `-nodesktop -nosplash -r` 模式拉起 MATLAB Bridge 服务（监听 `tcp://127.0.0.1:5555`）。用户无需手动打开 MATLAB 或运行任何脚本。

> 如果 MATLAB 未安装，软件会提示功能不可用。生产环境必须安装 MATLAB R2024b+。

### 4. 完成一次完整演示

1. 点击 **"加载点云"** → 取消对话框 → 选择加载演示数据
2. 切换到 **选取模式** → 拖动鼠标选取缺陷区域
3. 选择材料（如 STEEL_316L）→ 点击 **"生成修复路径"**
4. 切换到 **"02 形貌预测"** → 点击 **"执行形貌预测"**
5. 点击 **"导出 G-code"** 和 **"导出 PDF 报告"**

> 详细步骤请参阅 [快速开始](docs/用户手册/快速开始.md)

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
│   ├── tests/                      # 单元测试（15 个文件，402 个测试）
│   ├── tools/                      # 性能分析工具
│   └── utils/                      # 配置、日志、许可证、崩溃处理
│
├── path_planning/                  # 路径规划算法（6 个 .m 文件）
├── profile_prediction/             # 形貌预测算法（12 个 .m 文件）
├── config/                         # 标定数据库 + 许可证
├── docs/                           # 完整文档（见下方导航）
├── scripts/                        # 验证脚本
└── .github/                        # CI/CD + Issue 模板
```

## MATLAB 集成

软件启动时自动以 `-nodesktop -nosplash -r` 模式拉起 MATLAB Bridge 服务：

- 自动检测 MATLAB 安装路径（R2025b 优先，向下兼容 R2024b+）
- 自动启动 `matlab_bridge_server.m`，监听 `tcp://127.0.0.1:5555`
- 自动崩溃恢复（看门狗 3 秒轮询，最大 3 次自动重启）
- 自动清理（退出时三阶段 terminate → kill → taskkill）

**用户无需手动打开 MATLAB 或运行任何脚本。** 详细说明请参阅 [算法说明](docs/MATLAB集成/算法说明.md)。

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

> 完整环境变量列表请参阅 [安装部署](docs/用户手册/安装部署.md)

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

> Linux 仅支持从源码运行，详见 [安装部署](docs/用户手册/安装部署.md)

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部测试（402 个）
pytest repair_app/tests/ repair_app/bridge/tests/ -v

# 端到端验证（27 项）
python scripts/release_validation.py

# 代码检查
flake8 repair_app/ --count --max-complexity=15
bandit -r repair_app/ -x repair_app/tests/ -ll
```

> 详细开发指南请参阅 [开发指南](docs/开发文档/开发指南.md)

## 文档导航

完整文档索引请参阅 [DOCUMENT_INDEX.md](DOCUMENT_INDEX.md)。

| 分类 | 文档 | 适合读者 |
|------|------|---------|
| 用户手册 | [快速开始](docs/用户手册/快速开始.md) | 所有人 |
| 用户手册 | [安装部署](docs/用户手册/安装部署.md) | 用户、运维 |
| 用户手册 | [使用手册](docs/用户手册/使用手册.md) | 操作员、工程师 |
| 用户手册 | [软件工程化功能](docs/用户手册/软件工程化功能.md) | 操作员、工程师 |
| MATLAB 集成 | [算法说明](docs/MATLAB集成/算法说明.md) | 算法工程师 |
| MATLAB 集成 | [算法架构](docs/MATLAB集成/算法架构.md) | 算法工程师、架构师 |
| MATLAB 集成 | [生命周期管理](docs/MATLAB集成/生命周期管理.md) | 运维、架构师 |
| MATLAB 集成 | [Pipeline 设计](docs/MATLAB集成/Pipeline设计.md) | 算法工程师 |
| MATLAB 集成 | [Bridge 稳定性审计](docs/MATLAB集成/Bridge稳定性审计.md) | 架构师 |
| MATLAB 集成 | [算法集成报告](docs/MATLAB集成/算法集成报告.md) | 架构师 |
| MATLAB 集成 | [算法验证体系](docs/MATLAB集成/算法验证体系.md) | QA、算法工程师 |
| 架构设计 | [软件架构](docs/架构设计/软件架构.md) | 架构师 |
| 架构设计 | [UX 重设计报告](docs/架构设计/UX重设计报告.md) | 产品、设计 |
| 架构设计 | [Windows 界面优化](docs/架构设计/Windows界面优化.md) | 前端开发 |
| 架构设计 | [文档代码一致性报告](docs/架构设计/文档代码一致性报告.md) | 架构师 |
| 架构设计 | [文档重构报告](docs/架构设计/文档重构报告.md) | 架构师 |
| 开发文档 | [开发指南](docs/开发文档/开发指南.md) | 开发者 |
| 开发文档 | [贡献指南](docs/开发文档/贡献指南.md) | 开发者 |
| 开发文档 | [计算流程设计](docs/开发文档/计算流程设计.md) | 开发者 |
| 开发文档 | [Pipeline 中间文件消除](docs/开发文档/Pipeline中间文件消除.md) | 开发者 |
| 开发文档 | [实时可视化说明](docs/开发文档/实时可视化说明.md) | 开发者 |
| 开发文档 | [可视化集成验证](docs/开发文档/可视化集成验证.md) | 开发者、QA |
| API | [通信协议](docs/API/通信协议.md) | 开发者、架构师 |
| API | [API 接口](docs/API/API接口.md) | 开发者 |
| 调试指南 | [测试验证](docs/调试指南/测试验证.md) | QA、发布工程师 |
| 调试指南 | [故障排查](docs/调试指南/故障排查.md) | 操作员、运维 |
| FAQ | [常见问题](docs/FAQ/常见问题.md) | 所有人 |
| 发布说明 | [发布说明](docs/发布说明/发布说明.md) | 所有人 |
| 更新日志 | [更新日志](docs/更新日志/更新日志.md) | 所有人 |
| — | [archive/](docs/archive/) | 历史参考 |

## 许可证

MIT License。详见 [LICENSE](LICENSE)。

软件使用 License 验证（HMAC + RSA 公钥 + 机器码绑定）。生产环境必须将 `license.key` 放置在 `dist/config/` 目录中。`public_key.pem` 从打包内置只读目录（`_MEIPASS`）加载，防止替换攻击。

## 贡献

欢迎提交 Pull Request。请参阅 [贡献指南](docs/开发文档/贡献指南.md) 和 [开发指南](docs/开发文档/开发指南.md)。
