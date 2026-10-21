@echo off
cd /d "%~dp0"
echo For real AI: install Ollama then run: ollama pull qwen2.5:3b
echo.
where py >nul 2>&1
if %errorlevel%==0 (py server.py) else (python server.py)
pause
