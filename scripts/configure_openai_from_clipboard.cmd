@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_openai_from_clipboard.ps1"
if errorlevel 1 pause
