@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0" || exit /b 1

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 "Krea2_更新工具\server.py"
) else (
    python "Krea2_更新工具\server.py"
)
set "launch_exit=%errorlevel%"
popd

if not "%launch_exit%"=="0" (
    echo.
    echo 启动失败。请查看上方错误，确认已安装 Python 3.9 或更新版本，且可通过 py 或 python 命令运行。
    pause
)
exit /b %launch_exit%
