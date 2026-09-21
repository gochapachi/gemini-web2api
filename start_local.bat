@echo off
title Gemini Web2API Local Server
echo Starting Gemini Web2API on port 8081...
cd /d "%~dp0"
python gemini_web2api.py --config "%~dp0config.json"
pause
