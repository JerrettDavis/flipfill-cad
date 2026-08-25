$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\scripts\bootstrap.ps1 first."
}

Set-Location $Root
& $Python -m pip install -e ".[dev]"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name FlipFillCAD `
    --paths src `
    --collect-all cadquery `
    --collect-all OCP `
    --collect-all vtkmodules `
    --collect-all trimesh `
    --collect-all PIL `
    src\flipfill\ui\launcher.py

Write-Host "Windows application created under dist\FlipFillCAD."
