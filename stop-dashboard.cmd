@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0work\rlcd_companion\scripts\dashboard_windows.ps1" -Action stop
pause
