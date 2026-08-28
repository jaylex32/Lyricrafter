$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

.\.venv\Scripts\python.exe -m app
