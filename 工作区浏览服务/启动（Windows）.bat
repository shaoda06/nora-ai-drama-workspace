@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Please complete setup in README.md first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\launcher.py" start
