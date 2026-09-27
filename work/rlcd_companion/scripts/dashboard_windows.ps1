param([ValidateSet('start','stop','diagnose')][string]$Action='start')
$ErrorActionPreference='Stop'
$server=(Resolve-Path (Join-Path $PSScriptRoot '../server')).Path
$python=Join-Path $server '.venv/Scripts/python.exe'
$state=Join-Path $server 'data/server-pid.txt'
New-Item -ItemType Directory -Force -Path (Join-Path $server 'data') | Out-Null
if ($Action -eq 'start') {
    $listener=Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { Write-Host 'Dashboard is already listening on port 8787.'; exit 0 }
    Start-Process -FilePath $python -ArgumentList '-m uvicorn app:app --host 0.0.0.0 --port 8787' -WorkingDirectory $server -WindowStyle Hidden -RedirectStandardOutput (Join-Path $server 'monitor-server.log') -RedirectStandardError (Join-Path $server 'monitor-server.err.log')
    for ($attempt=0;$attempt -lt 20;$attempt++) {
        Start-Sleep -Milliseconds 500
        $listener=Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) { Set-Content -LiteralPath $state -Value $listener.OwningProcess; Write-Host 'Dashboard started: http://127.0.0.1:8787/'; exit 0 }
    }
    throw 'Service did not start. Run diagnose-dashboard.cmd.'
} elseif ($Action -eq 'stop') {
    if (!(Test-Path -LiteralPath $state)) { throw 'No saved service process. Run diagnose-dashboard.cmd.' }
    $servicePid=[int](Get-Content -LiteralPath $state)
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$servicePid"
    if ($process -and $process.CommandLine -like '*uvicorn app:app*' -and $process.CommandLine -like '*8787*') { Stop-Process -Id $servicePid; Write-Host 'Dashboard stopped.' }
} else {
    try {
        $summary=Invoke-RestMethod 'http://127.0.0.1:8787/api/monitor'
        $frame=Invoke-WebRequest 'http://127.0.0.1:8787/frame.bin'
        Write-Host "Service OK; frame bytes=$($frame.RawContentLength); layout=$($frame.Headers['X-RLCD-Layout'])"
        Write-Host "Lab computers: $($summary.machines.Count); tasks: $($summary.tasks.Count)"
        foreach ($p in 'codex','glm','qoder') {
            $q=$summary.quotas.$p
            Write-Host "$p connected=$([bool]$q) stale=$($q.stale) error=$($q.error)"
        }
    } catch { Write-Host 'Service unavailable. Check monitor-server.err.log.' }
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -Like '*ZeroTier*' | Select-Object IPAddress,InterfaceAlias
}
