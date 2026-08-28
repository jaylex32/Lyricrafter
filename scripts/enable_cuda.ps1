$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

Write-Host "Installing CUDA-enabled PyTorch/Torchaudio wheels..."
.\.venv\Scripts\python.exe -m pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

Write-Host ""
Write-Host "Checking CUDA..."
.\.venv\Scripts\python.exe scripts\check_cuda.py
