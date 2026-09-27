@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install qoder-agent-sdk qodercn-agent-sdk
if errorlevel 1 (pause & exit /b 1)
.venv\Scripts\python.exe setup_accounts.py
