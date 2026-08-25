$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -m venv .venv
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
}
else {
    throw "Python 3.11-3.13 was not found. Install 64-bit Python 3.12 from python.org."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]"

Write-Host ""
Write-Host "FlipFill CAD is ready. Run: .\scripts\run.ps1"
