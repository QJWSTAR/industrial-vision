@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  CSAM Repair — 发布构建流水线 v1.0.0
echo ============================================
echo.

REM ============================================================
REM 0. 环境检查
REM ============================================================
echo [0/7] 检查构建环境...

REM Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

REM Inno Setup
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
    echo [警告] 未找到 Inno Setup，将跳过安装程序构建
    echo   下载: https://jrsoftware.org/isinfo.php
)

REM 代码签名证书（可选）
set "SIGN_TOOL="
if exist "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe" (
    set "SIGN_TOOL=C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"
) else if exist "C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe" (
    set "SIGN_TOOL=C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
)

if "%SIGN_TOOL%"=="" (
    echo [警告] 未找到 signtool.exe，将跳过代码签名
    echo   安装 Windows SDK: https://developer.microsoft.com/windows/downloads/windows-sdk/
)

REM 代码签名证书路径（通过环境变量 CSAM_CERT_PATH 配置）
if "%CSAM_CERT_PATH%"=="" (
    echo [信息] 未设置 CSAM_CERT_PATH，跳过代码签名
    echo   设置方法: set CSAM_CERT_PATH=C:\path\to\certificate.pfx
    set SIGN_TOOL=
)
echo.

REM ============================================================
REM 1. 安装依赖
REM ============================================================
echo [1/7] 安装 Python 依赖...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

REM ============================================================
REM 2. 验证模块
REM ============================================================
echo [2/7] 验证关键模块...
python -c "import PySide6, zmq, google.protobuf, numpy, matplotlib, reportlab, cryptography; print('核心模块全部可用')"
if %errorlevel% neq 0 (
    echo [错误] 核心模块导入失败
    pause
    exit /b 1
)
echo.

REM ============================================================
REM 3. 生成 RSA 密钥对（如不存在）
REM ============================================================
echo [3/7] 检查 License 密钥对...
if not exist "config\public_key.pem" (
    echo 正在生成 RSA 密钥对...
    python -m repair_app.utils.license_manager keygen
    if %errorlevel% neq 0 (
        echo [错误] 密钥对生成失败
        pause
        exit /b 1
    )
) else (
    echo 密钥对已存在，跳过生成。
)
echo.

REM ============================================================
REM 4. 运行测试
REM ============================================================
echo [4/7] 运行回归测试...
python -m pytest repair_app/tests/ -q --tb=line
if %errorlevel% neq 0 (
    echo [警告] 部分测试失败，请检查
    echo 是否继续构建? (Y/N)
    choice /c YN /n
    if errorlevel 2 exit /b 1
)
echo.

REM ============================================================
REM 5. 清理旧构建
REM ============================================================
echo [5/7] 清理旧构建...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo.

REM ============================================================
REM 6. PyInstaller 打包
REM ============================================================
echo [6/7] PyInstaller 打包中（预计 3-10 分钟）...
python -m PyInstaller --clean repair_app.spec
if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)
echo 打包完成: dist\CSAM_Repair.exe
echo.

REM ============================================================
REM 7. 代码签名（如已配置）
REM ============================================================
echo [7/7] 代码签名...

if not "%SIGN_TOOL%"=="" (
    REM 签名主程序
    echo 正在签名 CSAM_Repair.exe...
    "%SIGN_TOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%CSAM_CERT_PATH%" /p "%CSAM_CERT_PASSWORD%" "dist\CSAM_Repair.exe"
    if %errorlevel% neq 0 (
        echo [警告] 主程序签名失败，请检查证书和密码
    ) else (
        echo 主程序签名完成
        REM 验证签名
        "%SIGN_TOOL%" verify /pa /v "dist\CSAM_Repair.exe"
    )
) else (
    echo 跳过代码签名（未配置 CSAM_CERT_PATH）
)
echo.

REM ============================================================
REM 8. 构建安装程序（如 Inno Setup 可用）
REM ============================================================
if not "%ISCC%"=="" (
    echo [8/8] 构建安装程序...
    cd installer
    "%ISCC%" setup.iss
    if %errorlevel% neq 0 (
        echo [警告] 安装程序构建失败
    ) else (
        echo 安装程序构建完成: installer\Output\

        REM 签名安装程序（如已配置）
        if not "%SIGN_TOOL%"=="" (
            echo 正在签名安装程序...
            "%SIGN_TOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%CSAM_CERT_PATH%" /p "%CSAM_CERT_PASSWORD%" "Output\CSAM_Repair_Setup_v1.0.0.exe"
        )
    )
    cd ..
) else (
    echo 跳过安装程序构建（未找到 Inno Setup）
)
echo.

echo ============================================
echo  发布构建完成!
echo ============================================
echo.
echo 输出文件:
echo   dist\CSAM_Repair.exe            — 单文件可执行程序
if exist "installer\Output\CSAM_Repair_Setup_v1.0.0.exe" (
    echo   installer\Output\CSAM_Repair_Setup_v1.0.0.exe — 安装程序
)
echo.
echo 发布前检查清单:
echo [ ] 所有测试通过
echo [ ] 代码已签名（signtool verify /pa）
echo [ ] 安装程序在干净虚拟机测试通过
echo [ ] SmartScreen 未拦截
echo [ ] License 文件已准备
echo [ ] 法律文件已更新（LICENSE / EULA / THIRD_PARTY_NOTICES）
echo.
pause