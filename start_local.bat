@echo off
title Gemini Web2API Local Server
echo Starting Gemini Web2API on port 8081...
cd /d "%~dp0"
python -m gemini_web2api --config "%~dp0config.json"
pause
