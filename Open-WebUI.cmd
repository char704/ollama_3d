@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-OpenWebUI.ps1" %*
if errorlevel 1 (
  pause
  exit /b 1
)
