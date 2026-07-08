@echo off
title VW CC Mechanic AI

:: Start Ollama if not already running
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if errorlevel 1 (
    echo Starting Ollama...
    start "" /B ollama serve
    timeout /t 4 /nobreak >NUL
)

:: Start Flask
echo Starting VW CC Mechanic AI...
cd /d "%~dp0"
start "" /B C:\Python314\python.exe app.py > logs\flask.log 2> logs\flask_err.log

:: Wait for Flask to be ready
timeout /t 6 /nobreak >NUL

:: Open browser
start "" http://localhost:5000

echo.
echo VW CC Mechanic AI is running at http://localhost:5000
echo Close this window to shut it down.
pause
