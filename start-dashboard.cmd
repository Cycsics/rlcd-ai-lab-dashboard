@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "work\rlcd_companion\scripts\dashboard_windows.ps1" -Action start
start "" "http://127.0.0.1:8787/"
pause
