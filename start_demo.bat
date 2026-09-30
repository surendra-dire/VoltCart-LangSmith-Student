@echo off
setlocal
title VoltCart with LangSmith
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import langsmith" >nul 2>&1
if errorlevel 1 (
  call setup.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo Could not start. Check the error above and the values in config.py.
  pause
)
