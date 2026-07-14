# 安装指南

CSAM Repair — 冷喷涂增材制造缺陷修复软件

## 系统要求

### Windows

| 要求 | 最低 | 推荐 |
|-------------|---------|-------------|
| 操作系统 | Windows 10 (1903+) | Windows 11 |
| Python | 3.10 | 3.11 或 3.12 |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 500 MB | 1 GB |
| GPU | DirectX 11 | DirectX 12 带 GPU 加速 |
| Visual C++ | 2015-2022 Redistributable | 最新版 |

### macOS

| 要求 | 最低 | 推荐 |
|-------------|---------|-------------|
| 操作系统 | macOS 10.14 (Mojave) | macOS 13 (Ventura)+ |
| Python | 3.10 | 3.11 或 3.12 |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 500 MB | 1 GB |
| 架构 | Intel x86_64 | Apple Silicon (M1/M2/M3) |

### MATLAB 集成（可选）

如果使用 MATLAB ZMQ 引擎进行形貌预测：

- MATLAB R2021a 或更高版本，或 MATLAB Runtime R2021a+
- MATLAB 位于同一台机器上，或可通过 TCP 访问
- 与 gencode v6.31.1 兼容的 Protobuf 运行时（protobuf >= 5.26）

## 选项 A：从源码安装

### 步骤 1：安装 Python

**Windows：** 从 [python.org](https://www.python.org/downloads/) 下载。安装过程中，勾选"Add Python to PATH"。

**macOS：** 使用 Homebrew：
```bash
brew install python@3.11
```

验证安装：
```bash
python --version   # Windows
python3 --version  # macOS
```

### 步骤 2：克隆并进入项目

```bash
git clone <repository-url>
cd csam-repair
```

### 步骤 3：创建虚拟环境

**Windows：**
```cmd
python -m venv venv
venv\Scripts\activate
```

**macOS：**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 步骤 4：安装依赖

```bash
# 升级 pip（可编辑安装所需）
pip install --upgrade pip

# 安装基础依赖
pip install -r requirements.txt

# 以可编辑模式安装包
pip install -e .

# 可选：全功能安装（Open3D、PyVista、loguru）
pip install -e ".[full]"

# 可选：开发工具（pytest、flake8、bandit、pyinstaller）
pip install -e ".[dev]"
```

### 步骤 5：配置环境（可选）

```bash
cp .env.example .env
```

编辑 `.env` 并设置 `CSAM_HMAC_SECRET` 用于生产环境许可证验证。

### 步骤 6：运行

```bash
python run_app.py
```

或者如果已安装为包：
```bash
csam-repair
```

## 选项 B：使用预构建可执行文件

### Windows

1. 获取 `CSAM_Repair.exe`
2. 将其放在路径中不含中文或空格的目录中
3. 双击运行
4. 首次启动可能需要 10-30 秒（解压临时文件）

### macOS

1. 获取 `CSAM_Repair.app`
2. 拖动到 `/Applications/`
3. 右键点击 → 打开（首次启动绕过 Gatekeeper）
4. 用于分发时：应用必须经过代码签名和公证

## MATLAB ZMQ 引擎设置

软件通过 ZMQ + Protobuf 与 MATLAB 引擎通信。MATLAB 端必须：

1. 加载 `repair_protocol_pb2.py`（由 `repair_protocol.proto` 生成）
2. 绑定到 `CSAM_ZMQ_ADDRESS` 中配置的 ZMQ 地址
   - Windows 默认：`tcp://127.0.0.1:5555`
   - macOS/Linux 默认：`ipc:///tmp/csam_engine`
3. 实现 `repair_protocol.proto` 中定义的请求-响应协议

覆盖默认 ZMQ 地址：
```bash
# Windows
set CSAM_ZMQ_ADDRESS=tcp://127.0.0.1:5556

# macOS/Linux
export CSAM_ZMQ_ADDRESS=tcp://127.0.0.1:5556
```

## 许可证配置

应用程序在没有许可证文件的情况下也可以启动（会记录警告日志但不阻止功能）。要启用完整的许可证验证：

1. 将 `public_key.pem` 放在 `config/` 目录中
2. 将 `license.key` 放在 `config/` 目录中
3. 重启应用程序

生成开发许可证：
```bash
python -m repair_app.utils.license_manager issue "Developer" 365
```

## 故障排除

### "No module named PySide6"

PySide6 安装失败。尝试：
```bash
pip install PySide6 --force-reinstall
```

### Windows 上出现 "DLL load failed"

安装 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)。

### pip 安装时出现 macOS 权限错误

使用虚拟环境：
```bash
python3 -m venv venv
source venv/bin/activate
```

### ZMQ 连接被拒绝

确保 MATLAB 引擎正在运行并监听正确的 ZMQ 地址。检查 `CSAM_ZMQ_ADDRESS` 环境变量。

### Matplotlib 后端错误

显式设置后端：
```bash
export MPLBACKEND=QtAgg   # macOS/Linux
set MPLBACKEND=QtAgg      # Windows
```

### 中文字体渲染问题

应用程序使用 `repair_app/platform/fonts.py` 自动选择 CJK 字体。如果字体缺失：

- **Windows**：安装"Microsoft YaHei"（通常已预装）
- **macOS**：安装"PingFang SC"（通常已预装）
- **Linux**：安装 `fonts-noto-cjk` 包

### PyInstaller 构建失败

常见原因：
- 缺少隐藏导入：检查 `repair_app.spec` 的 hiddenimports 列表
- UPX 压缩破坏 Qt DLL：已在 spec 中排除
- 项目路径中包含中文字符：将项目移动到仅含 ASCII 字符的路径
