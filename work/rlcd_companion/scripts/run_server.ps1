param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$serverDir = Join-Path $PSScriptRoot '../server'
Push-Location $serverDir
try {
    if (!(Test-Path '.venv/Scripts/python.exe')) { throw 'Python environment missing.' }
    & '.venv/Scripts/python.exe' -m uvicorn app:app --host 0.0.0.0 --port $Port
} finally { Pop-Location }
