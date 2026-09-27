@echo off
cd /d "%~dp0"
py scripts\prepare_deploy.py
if errorlevel 1 (
  echo.
  echo Prepare deploy failed.
  pause
  exit /b 1
)
echo.
echo Public database prepared. You can now git add / commit / push.
pause
