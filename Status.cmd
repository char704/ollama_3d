@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run Install.cmd first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0manage.py" status
set "project_status=%errorlevel%"
pause
exit /b %project_status%
