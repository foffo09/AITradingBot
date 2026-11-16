# Exercise the real wrappers with synthetic data and an isolated, disposable directory.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
foreach ($entry in @(Get-ChildItem Env:)) {
    if ($entry.Name -match 'KEY|SECRET|TOKEN|PASSWORD|ACCOUNT|RPC_URL|WS_URL|ALPACA|MT5') {
        Remove-Item -LiteralPath "Env:$($entry.Name)"
    }
}
$env:PYTHON_DOTENV_DISABLED = '1'
$env:AUTO_TRADE = 'false'
$env:PAPER_EXECUTION_SCOPE = 'disabled'
$data = Join-Path ([IO.Path]::GetTempPath()) ('AITradingBot web smoke ' + [guid]::NewGuid())
$control = Join-Path $data 'web-service.json'
$job = $null
$duplicate = $null
$phase = 'start'
try {
    foreach ($round in 1..2) {
        $job = Start-Job -ArgumentList $root,$data -ScriptBlock {
            param($root,$data)
            & (Join-Path $root 'avvia_web.ps1') -NoBrowser -DataDirectory $data
        }
        $deadline = (Get-Date).AddSeconds(45)
        $info = $null
        while ((Get-Date) -lt $deadline) {
            if ($job.State -eq 'Failed' -or $job.State -eq 'Completed') {
                $phase = 'receive'
                Receive-Job $job -ErrorAction Stop
                throw 'Launcher exited before readiness'
            }
            if (Test-Path -LiteralPath $control) {
                try { $info = Get-Content -Raw -LiteralPath $control | ConvertFrom-Json } catch { $info = $null }
                if ($info.pid -gt 0 -and $info.port -gt 0 -and $info.instance_id) { break }
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not $info) { throw 'Launcher readiness timed out' }
        $origin = "http://127.0.0.1:$($info.port)"
        $health = Invoke-RestMethod "$origin/api/v1/health" -NoProxy
        if ($health.status -ne 'ready') { throw 'Service not ready' }
        if ($round -eq 1) {
            $before = Get-Content -Raw -LiteralPath $control
            $phase = 'duplicate'
            # Expected native stderr/exit must stay in a separate job, not fail this CI step.
            $duplicate = Start-Job -ArgumentList $root,$data -ScriptBlock {
                param($root,$data)
                & (Join-Path $root 'avvia_web.ps1') -NoBrowser -DataDirectory $data
            }
            if (-not (Wait-Job $duplicate -Timeout 20)) { throw 'Duplicate launcher hung' }
            Receive-Job $duplicate -ErrorAction SilentlyContinue | Out-Null
            if ($duplicate.State -ne 'Failed') { throw 'Duplicate launcher accepted' }
            Remove-Job $duplicate -Force
            $duplicate = $null
            if ((Get-Content -Raw -LiteralPath $control) -ne $before) { throw 'Duplicate changed owner record' }
            if ((Invoke-RestMethod "$origin/api/v1/health" -NoProxy).status -ne 'ready') { throw 'Duplicate interrupted first owner' }
        }
        $phase = 'stop'
        & (Join-Path $root 'arresta_web.ps1') -DataDirectory $data
        if (-not (Wait-Job $job -Timeout 20)) { throw 'Launcher did not exit after stop' }
        $phase = 'receive'
        Receive-Job $job -ErrorAction Stop
        if ($job.State -ne 'Completed') { throw 'Launcher failed' }
        Remove-Job $job
        $job = $null
        if (Test-Path -LiteralPath $control) { throw 'Control record remains after stop' }
        $probe = [Net.Sockets.TcpClient]::new()
        try {
            try { $probe.Connect('127.0.0.1', [int]$info.port) } catch [Net.Sockets.SocketException] { }
            if ($probe.Connected) { throw 'Loopback socket remains open after stop' }
        } finally { $probe.Dispose() }
    }
    Write-Output 'WINDOWS LAUNCHER PASS: real wrappers, duplicate rejected, shutdown, restart, closed socket; disposable data only.'
} catch {
    Write-Output "WINDOWS LAUNCHER FAIL: phase=$phase type=$($_.Exception.GetType().Name)"
    throw
} finally {
    if ($duplicate) { Stop-Job $duplicate; Remove-Job $duplicate -Force }
    if ($job) {
        if (Test-Path -LiteralPath $control) {
            try { & (Join-Path $root 'arresta_web.ps1') -DataDirectory $data } catch { Write-Warning 'Owned test launcher did not confirm graceful shutdown' }
        }
        Stop-Job $job
        Remove-Job $job -Force
    }
    if (Test-Path -LiteralPath $data) { Remove-Item -LiteralPath $data -Recurse -Force }
}
