@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Please complete setup in README.md first.
  pause
  exit /b 1
)
start "" /wait "%~dp0.venv\Scripts\pythonw.exe" -X utf8 -B "%~dp0scripts\launcher.py" start
if errorlevel 1 (
  echo Nora browser startup failed. See the error dialog and runtime\server.log.
  pause
  exit /b 1
)
