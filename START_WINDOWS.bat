@echo off
cd /d "%~dp0"
echo [TEAM] Checking Python dependencies...
py -m pip install -r requirements.txt >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt

echo [TEAM] Starting dashboard...
py run.py
if errorlevel 1 python run.py
pause
