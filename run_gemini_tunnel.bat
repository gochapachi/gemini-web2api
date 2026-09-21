@echo off
title Gemini Web2API + Cloudflare Tunnel
setlocal enabledelayedexpansion

echo =====================================================================
echo           Gemini-Web2API Local Launcher + Public Tunnel
echo =====================================================================
echo.

cd /d "%~dp0"

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    pause
    exit /b 1
)

:: 2. Check cloudflared
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] cloudflared is not installed or not in PATH!
    echo Please install cloudflared or place cloudflared.exe in this folder.
    pause
    exit /b 1
)

:: 3. Start local Gemini-Web2API server in a separate window
echo [1/2] Starting local Gemini-Web2API server on port 8081...
start "Gemini Web2API Server [Port 8081]" cmd /k "cd /d "%~dp0" && python -m gemini_web2api --config config.json"

:: 4. Wait for local server to initialize
timeout /t 3 /nobreak >nul

:: 5. Start Cloudflare Tunnel
echo [2/2] Starting Cloudflare Quick Tunnel...
echo.
echo ---------------------------------------------------------------------
echo  IMPORTANT:
echo  Look for the line below containing:
echo  "https://<random-subdomain>.trycloudflare.com"
echo.
echo  Use that URL in n8n or any OpenAI client:
echo    Base URL:  https://<subdomain>.trycloudflare.com/v1
echo    API Key:   sk-anagata-gemini (or sk-gemini)
echo    Model:     gemini-3.8-flash-thinking (or gemini-3.8-flash)
echo ---------------------------------------------------------------------
echo.

cloudflared tunnel --config "%~dp0empty_config.yml" --url http://127.0.0.1:8081

pause
