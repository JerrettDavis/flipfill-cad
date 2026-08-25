param(
    [string]$Project = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\scripts\bootstrap.ps1 first."
}

Set-Location $Root
if ([string]::IsNullOrWhiteSpace($Project)) {
    & $Python -m flipfill gui
}
else {
    & $Python -m flipfill gui $Project
}
