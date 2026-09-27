@echo off
cd /d "%~dp0"
if not exist "data\admin_codes.txt" (
  echo.
  echo [TEAM] First launch: choose an admin code.
  echo [TEAM] This stays local and is ignored by Git.
  set /p TEAM_ADMIN_CODE=Admin code: 
  if not "%TEAM_ADMIN_CODE%"=="" echo %TEAM_ADMIN_CODE%>"data\admin_codes.txt"
)
echo [TEAM] Checking Python dependencies...
py -m pip install -r requirements.txt >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt

echo [TEAM] Starting dashboard...
py run.py
if errorlevel 1 python run.py
pause
