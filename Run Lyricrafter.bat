@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Lyricrafter virtual environment was not found.
    echo Run scripts\setup.ps1 first, or ask Codex to install dependencies again.
    pause
    exit /b 1
)

start "Lyricrafter" ".venv\Scripts\pythonw.exe" -m app
