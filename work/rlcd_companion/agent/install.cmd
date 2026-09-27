@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (echo Install Python 3.11 or newer from python.org, then retry. & pause & exit /b 1)
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if not exist .venv\Scripts\python.exe (pause & exit /b 1)
.venv\Scripts\python.exe -m pip install pydantic
if errorlevel 1 (pause & exit /b 1)
.venv\Scripts\python.exe agent.py install
pause
