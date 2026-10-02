@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_gmail_oauth_gui.ps1"
if errorlevel 1 (
  echo.
  echo Gmail configuration failed. No authorization was granted.
  pause
)
endlocal
