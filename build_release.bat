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
echo [1/9] 检查构建环境...

REM Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if (3, 10) ^<= sys.version_info[:2] ^< (3, 13) else 1)"
if errorlevel 1 (
    echo [错误] 仅支持 Python 3.10-3.12。
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
echo [2/9] 安装 Python 依赖...
python -m pip install --upgrade pip -q
if errorlevel 1 goto :dependency_error
python -m pip install -r requirements.txt -q
if errorlevel 1 goto :dependency_error
python -m pip install pyinstaller -q
if errorlevel 1 goto :dependency_error
echo.

REM ============================================================
REM 2. 验证模块
REM ============================================================
echo [3/9] 验证关键模块...
python -c "import PySide6, zmq, google.protobuf, numpy, matplotlib, reportlab, cryptography; print('核心模块全部可用')"
if errorlevel 1 (
    echo [错误] 核心模块导入失败
    pause
    exit /b 1
)
echo.

REM ============================================================
REM 4. 验证发布 License 公钥
REM ============================================================
echo [4/9] 检查 License 公钥...
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

REM ============================================================
REM 4. 运行测试
REM ============================================================
echo [5/9] 运行回归测试...
python -m pytest repair_app/tests/ repair_app/bridge/tests/ -q --tb=line
if errorlevel 1 (
    echo [错误] 回归测试失败，发布构建已停止。
    pause
    exit /b 1
)
echo.

REM ============================================================
REM 5. 清理旧构建
REM ============================================================
echo [6/9] 清理旧构建...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo.

REM ============================================================
REM 6. PyInstaller 打包
REM ============================================================
echo [7/9] PyInstaller 打包中（预计 3-10 分钟）...
python -m PyInstaller --clean repair_app.spec
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)
echo 打包完成: dist\CSAM_Repair.exe
echo.

REM ============================================================
REM 7. 代码签名（如已配置）
REM ============================================================
echo [8/9] 代码签名...

if not "%SIGN_TOOL%"=="" (
    REM 签名主程序
    echo 正在签名 CSAM_Repair.exe...
    "%SIGN_TOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%CSAM_CERT_PATH%" /p "%CSAM_CERT_PASSWORD%" "dist\CSAM_Repair.exe"
    if errorlevel 1 (
        echo [错误] 主程序签名失败，请检查证书和密码
        pause
        exit /b 1
    )
    echo 主程序签名完成
    REM 验证签名
    "%SIGN_TOOL%" verify /pa /v "dist\CSAM_Repair.exe"
    if errorlevel 1 (
        echo [错误] 主程序签名验证失败
        pause
        exit /b 1
    )
) else (
    echo 跳过代码签名（未配置 CSAM_CERT_PATH）
)
echo.

REM ============================================================
REM 8. 构建安装程序（如 Inno Setup 可用）
REM ============================================================
if not "%ISCC%"=="" (
    echo [9/9] 构建安装程序...
    pushd installer
    "%ISCC%" setup.iss
    if errorlevel 1 (
        popd
        echo [错误] 安装程序构建失败
        pause
        exit /b 1
    )
    echo 安装程序构建完成: installer\Output\

    REM 签名安装程序（如已配置）
    if not "%SIGN_TOOL%"=="" (
        echo 正在签名安装程序...
        "%SIGN_TOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%CSAM_CERT_PATH%" /p "%CSAM_CERT_PASSWORD%" "Output\CSAM_Repair_Setup_v1.0.0.exe"
        if errorlevel 1 (
            popd
            echo [错误] 安装程序签名失败
            pause
            exit /b 1
        )
    )
    popd
) else (
    echo [9/9] 跳过安装程序构建（未找到 Inno Setup）
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
exit /b 0

:dependency_error
echo [错误] 依赖安装失败
pause
exit /b 1
