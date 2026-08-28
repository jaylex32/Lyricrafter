param(
    [switch]$WithSeparation
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip

if ($WithSeparation) {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev,separation]"
} else {
    .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
}

Write-Host "Setup complete. Run scripts\run.ps1 to start Lyricrafter."
