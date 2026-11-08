@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run Install.cmd first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0manage.py" stop
if errorlevel 1 (
  pause
  exit /b 1
)
pause
