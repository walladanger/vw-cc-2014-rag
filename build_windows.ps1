$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& .\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

& .\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name "CCWorkshop" `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --hidden-import "rank_bm25" `
    desktop.py
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\CCWorkshop\CCWorkshop.exe"

