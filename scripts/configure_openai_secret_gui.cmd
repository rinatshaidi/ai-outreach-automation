@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_openai_secret.ps1" -Gui
if errorlevel 1 (
  echo.
  echo Configuration failed. No key was changed.
  pause
)
endlocal
