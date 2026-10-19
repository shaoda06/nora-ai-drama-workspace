@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" exit /b 1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\launcher.py" stop
