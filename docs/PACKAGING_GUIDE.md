# 打包指南 — CSAM 修复软件 V1.0

## Windows 打包

### 前置条件
- Windows 10/11
- Python 3.10-3.12（推荐 3.12）
- 项目依赖已安装（`pip install -r requirements.txt`）
- PyInstaller 已安装（`pip install pyinstaller`）

### 一键打包
```powershell
cd d:\work\demo\industrial-vision
.\build_windows.bat
```
输出：`dist\CSAM_Repair.exe`（单文件，约 80-120 MB）

### 手动打包
```powershell
python -m PyInstaller --clean repair_app.spec
```

### spec 文件说明 (`repair_app.spec`)
- **单文件模式**：所有依赖打包进单个 exe
- **hiddenimports**：显式声明所有运行时导入的模块（含 bridge/engine）
- **datas**：材料数据库 (`material_db.json`)、标定配置 (`calibration_db.json`)、proto 文件
- **excludes**：排除未使用的 PySide6 模块（QtQml/QtQuick 等）以减小体积
- **UPX 压缩**：启用，排除 Qt DLL（压缩会导致加载失败）
- **图标**：自动检测 `p1.ico`/`p1.png`/`p1.jpg`
- **控制台**：Windows 保留控制台便于调试

### 打包验证清单
- [ ] exe 可在干净 Windows 虚拟机启动
- [ ] 主界面正常显示
- [ ] 假数据加载正常
- [ ] 缺陷选择、可行性判断正常
- [ ] G-code 导出正常
- [ ] PDF 报告生成正常
- [ ] ZMQ 联调正常（需 MATLAB 环境）

## Linux 部署（从源码运行）

> **注意**：Linux 未提供官方打包安装包，仅支持从源码运行。以下说明适用于 Ubuntu 22.04+ / CentOS 8+。

### 前置条件

- Linux 发行版：Ubuntu 22.04+ 或 CentOS 8+
- Python 3.10-3.12
- 系统依赖：`libgl1`、`libxkbcommon0`、`libdbus-1-3`（PySide6 运行时依赖）

### 安装系统依赖

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libfreetype6

# CentOS / RHEL
sudo yum install -y mesa-libGL libxkbcommon dbus-libs fontconfig freetype
```

### 安装 Python 依赖

```bash
git clone <repo>
cd industrial-vision
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

### 运行

```bash
python run_app.py
```

### Linux 已知限制

- ZMQ 默认使用 `ipc:///tmp/csam_engine`（Unix 域套接字），如需 TCP 可设置 `CSAM_ZMQ_ADDRESS=tcp://127.0.0.1:5555`
- matplotlib 3D 渲染在无 GPU 的服务器上可能较慢
- MATLAB Engine API for Linux 需单独配置（参考 MathWorks 官方文档）
- 不提供 PyInstaller 打包的 .deb/.rpm 安装包

## macOS 打包

### 前置条件
- macOS 10.14+
- Python 3.10-3.12
- 项目依赖已安装

### 一键打包
```bash
chmod +x build_macos.sh
./build_macos.sh
```
输出：`dist/CSAM_Repair.app`（.app bundle）

### 代码签名（分发前必须）
```bash
codesign --deep --force --verify --verbose=4 \
  --sign "Developer ID Application: <Your Name>" \
  dist/CSAM_Repair.app
```

### 公证（Gatekeeper）
```bash
xcrun notarytool submit dist/CSAM_Repair.app.zip \
  --apple-id "<apple-id>" --team-id "<team-id>" --password "<app-password>" --wait
xcrun stapler staple dist/CSAM_Repair.app
```

## 常见打包问题

| 问题 | 解决方案 |
|------|---------|
| PySide6 插件缺失 | `pip install PySide6 --force-reinstall` |
| 中文路径导致打包失败 | 确保项目路径不含中文/空格 |
| 模块缺失警告 | 检查 `repair_app.spec` 中 hiddenimports |
| Qt DLL 加载失败 | spec 中已排除 UPX 压缩 Qt DLL |
| matplotlib 3D 渲染失败 | 虚拟机无 GPU 加速，属正常现象 |
| 首次启动慢 | 单文件模式需解压临时文件，约 5-10 秒 |

## 体积优化
- 已排除：PySide6 QtQml/QtQuick/QtQuick3D/QtDesigner/QtHelp
- 已排除：matplotlib Tk/Wx/GTK 后端
- 已排除：pywin32、pynput
- UPX 压缩：启用（Qt DLL 除外）

## 分发
- Windows：直接分发 `CSAM_Repair.exe`，无需安装
- macOS：分发 `CSAM_Repair.app`（需签名+公证）
- 目标机无需 Python 环境
