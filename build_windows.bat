@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  冷喷涂修复软件 - Windows 打包脚本
echo ============================================
echo.

REM 1. 检查 Python
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10-3.12
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
python -c "import sys; raise SystemExit(0 if (3, 10) ^<= sys.version_info[:2] ^< (3, 13) else 1)"
if errorlevel 1 (
    echo [错误] 仅支持 Python 3.10-3.12。
    pause
    exit /b 1
)
echo.

REM 2. 升级 pip 并安装依赖
echo [2/6] 安装依赖包（可能需要 5-10 分钟）...
python -m pip install --upgrade pip -q
if errorlevel 1 goto :dependency_error
python -m pip install -r requirements.txt
if errorlevel 1 goto :dependency_error
python -m pip install pyinstaller
if errorlevel 1 goto :dependency_error
echo.

REM 3. 验证关键模块
echo [3/6] 验证关键模块...
python -c "import PySide6, zmq, google.protobuf, numpy, matplotlib, reportlab, cryptography; print('核心模块全部可用')"
if errorlevel 1 (
    echo [错误] 模块导入失败！
    pause
    exit /b 1
)
echo.

REM 4. 验证发布 License 公钥（生产构建绝不自动生成密钥）
echo [4/6] 检查 License 公钥...
if "%CSAM_PUBLIC_KEY_PATH%"=="" set "CSAM_PUBLIC_KEY_PATH=%CD%\config\public_key.pem"
for %%I in ("%CSAM_PUBLIC_KEY_PATH%") do set "CSAM_PUBLIC_KEY_PATH=%%~fI"
if not exist "%CSAM_PUBLIC_KEY_PATH%" (
    echo [错误] 未找到发布公钥: %CSAM_PUBLIC_KEY_PATH%
    echo 请设置 CSAM_PUBLIC_KEY_PATH 指向已审核的 public_key.pem。
    echo 为避免发布密钥不一致，本脚本不会自动生成生产密钥。
    pause
    exit /b 1
)
echo 使用发布公钥: %CSAM_PUBLIC_KEY_PATH%
echo.

REM 5. 清理旧构建
echo [5/6] 清理旧构建...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo.

REM 6. 运行 PyInstaller
echo [6/6] 开始打包（可能需要 3-10 分钟）...
echo.
python -m PyInstaller --clean repair_app.spec
if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查上面的错误信息。
    echo.
    echo 常见问题：
    echo - PySide6 插件缺失：尝试 pip install PySide6 --force-reinstall
    echo - 中文路径问题：确保项目路径不含中文/空格
    echo - 模块缺失：检查 repair_app.spec 中 hiddenimports 列表
    pause
    exit /b 1
)

echo.
echo ============================================
echo  打包成功！
echo  输出位置: dist\CSAM_Repair.exe
echo ============================================
echo.
echo 测试步骤：
echo 1. 将 dist\ 中的 exe 拷贝到一台干净的 Windows 虚拟机
echo 2. 双击运行，检查是否能正常启动主界面
echo 3. 测试假数据加载、缺陷选择、可行性判断
echo 4. 如果有 MATLAB Runtime 环境，测试 ZMQ 联调
echo.
echo 已知限制：
echo - ZMQ 联调需要 MATLAB 环境（或 MCR）在后台运行
echo - 首次启动可能较慢（解压临时文件）
echo - matplotlib 3D 渲染在虚拟机中可能不支持 GPU 加速
pause
exit /b 0

:dependency_error
echo [错误] 依赖安装失败，请检查网络或 requirements.txt
pause
exit /b 1
