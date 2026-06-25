$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt

& .\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "CCWorkshop" `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --hidden-import "rank_bm25" `
    desktop.py

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\CCWorkshop.exe"
