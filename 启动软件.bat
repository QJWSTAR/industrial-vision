@echo off
cd /d "%~dp0"
chcp 65001 >nul 2>&1

REM 优先使用打包后的 EXE（发布版）
if exist "dist\CSAM_Repair.exe" (
    start "" "dist\CSAM_Repair.exe"
    exit /b 0
)

REM 开发模式：检查 venv
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [开发模式] 未找到 venv，使用系统 Python
)

REM 检查 run_app.py 是否存在
if not exist "run_app.py" (
    echo [错误] 未找到 run_app.py，请确认在正确的目录下运行
    pause
    exit /b 1
)

python run_app.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] 软件启动失败，错误码: %errorlevel%
    echo 请检查依赖是否安装: pip install -r requirements.txt
    pause
)
