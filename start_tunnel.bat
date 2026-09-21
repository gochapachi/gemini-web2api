@echo off
title Gemini Web2API Cloudflare Tunnel
echo Exposing local Gemini Web2API (http://localhost:8081) via Cloudflare Quick Tunnel...
echo.
cloudflared tunnel --config "%~dp0empty_config.yml" --url http://127.0.0.1:8081
pause
