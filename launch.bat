@echo off
title CC Workshop

:: Start Ollama if not already running
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if errorlevel 1 (
    start "" /B ollama serve
    timeout /t 4 /nobreak >NUL
)

:: Launch the native desktop window (no browser)
cd /d "%~dp0"
start "" C:\Python314\pythonw.exe desktop.py
