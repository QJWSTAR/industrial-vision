#!/bin/bash
# build_macos.sh — macOS 打包脚本
# 用法: bash build_macos.sh
set -euo pipefail

echo "============================================"
echo "  冷喷涂修复软件 - macOS 打包脚本"
echo "============================================"
echo ""

# 1. 检查 Python
echo "[1/5] 检查 Python 环境..."
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.11+"
    echo "  推荐: brew install python@3.11"
    exit 1
fi
python3 --version
echo ""

# 2. 升级 pip 并安装依赖
echo "[2/5] 安装依赖包（可能需要 5-10 分钟）..."
python3 -m pip install --upgrade pip -q
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller
echo ""

# 3. 验证关键模块
echo "[3/5] 验证关键模块..."
python3 -c "import PySide6, zmq, google.protobuf, numpy, matplotlib, reportlab, cryptography; print('核心模块全部可用')"
echo ""

# 4. 清理旧构建
echo "[4/5] 清理旧构建..."
rm -rf build dist
echo ""

# 5. 运行 PyInstaller
echo "[5/5] 开始打包（可能需要 3-10 分钟）..."
echo ""
python3 -m PyInstaller --clean repair_app.spec

echo ""
echo "============================================"
echo "  打包成功！"
echo "  输出位置: dist/CSAM_Repair.app"
echo "============================================"
echo ""
echo "测试步骤:"
echo "  1. open dist/CSAM_Repair.app"
echo "  2. 测试假数据加载、缺陷选择、可行性判断"
echo "  3. 如果有 MATLAB Runtime 环境，测试 ZMQ 联调"
echo ""
echo "已知限制:"
echo "  - ZMQ 联调需要 MATLAB 环境（或 MCR）在后台运行"
echo "  - matplotlib 3D 渲染可能不支持 GPU 加速"
echo "  - 分发前需手动执行 codesign 和 notarization"
