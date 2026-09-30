@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Setup complete. Edit config.py, then double-click start_demo.bat.
exit /b 0
:failed
echo.
echo Setup failed. Install Python 3.10 or newer and check your internet connection.
pause
exit /b 1
