@echo off
title Gemini Web2API + Reverse Tunnel (anagataitsolutions.in)
cd /d "%~dp0"

echo ================================================================
echo   Gemini Web2API Permanent Endpoint Launcher
echo   Domain: https://gemini.anagataitsolutions.in
echo ================================================================

:: Check if local Python virtual environment exists
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

:: Auto-sync Google credentials and XSRF token from browser
echo [*] Syncing Google session credentials from browser...
%PYTHON% sync_cookies.py

:: Check if local server on port 8081 is already responding
netstat -ano | findstr ":8081" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [*] Local Gemini server is already running on port 8081.
) else (
    echo [*] Starting local Gemini Web2API on port 8081...
    start "Gemini Local Server (Port 8081)" /min %PYTHON% -m gemini_web2api --config config.json
    timeout /t 3 /nobreak >nul
)

:: Start Reverse Tunnel Client
echo [*] Launching reverse tunnel client to https://gemini.anagataitsolutions.in...
%PYTHON% gemini_tunnel_client.py

pause
