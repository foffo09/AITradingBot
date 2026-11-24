# Only generated installers in this checkout and disposable directories are exercised.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$setups = @(Get-ChildItem (Join-Path $root 'src-tauri/target/release/bundle/nsis/*-setup.exe') -File)
if ($setups.Count -ne 1) { throw 'Expected exactly one generated NSIS setup' }
$folder = Join-Path ([IO.Path]::GetTempPath()) ('AITradingBot installer smoke ' + [guid]::NewGuid())
$install = Join-Path $folder 'installed app'
$data = Join-Path $folder 'retained data'
New-Item -ItemType Directory -Path $data -Force | Out-Null
$sentinel = Join-Path $data 'retain.txt'
Set-Content -LiteralPath $sentinel -Value 'fixture retained ledger boundary'
$uninstaller = Join-Path $install 'uninstall.exe'
try {
    # NSIS requires /D last and unquoted, including directories containing spaces.
    $result = Start-Process -FilePath $setups[0].FullName -ArgumentList "/S /D=$install" -Wait -PassThru
    if ($result.ExitCode -ne 0) { throw "NSIS install exit $($result.ExitCode)" }
    foreach ($relative in @('aitradingbot-desktop.exe', 'aitradingbot-service.exe', 'ui/index.html',
                            'ui/lightweight-charts-LICENSE.txt', 'ui/lightweight-charts-NOTICE.txt', 'uninstall.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $install $relative) -PathType Leaf)) {
            throw "Installed resource missing: $relative"
        }
    }
    Push-Location $root
    try {
        python -m scripts.check_local_service --binary (Join-Path $install 'aitradingbot-service.exe') --ui-dir (Join-Path $install 'ui')
        if ($LASTEXITCODE -ne 0) { throw 'Installed sidecar/UI HTTP smoke failed' }
    } finally { Pop-Location }
    # Real desktop app with WebView2 (disposable runner profile): start, find the owned sidecar, check
    # health, then (1) close the window and (2) force-kill the shell; the sidecar must always go away.
    $desktop = Join-Path $install 'aitradingbot-desktop.exe'
    function Get-Sidecar {
        @(Get-CimInstance Win32_Process -Filter "Name='aitradingbot-service.exe'")
    }
    function Wait-SidecarPort([int]$seconds) {
        $deadline = (Get-Date).AddSeconds($seconds)
        while ((Get-Date) -lt $deadline) {
            foreach ($process in Get-Sidecar) {
                $listen = Get-NetTCPConnection -State Listen -OwningProcess $process.ProcessId -ErrorAction SilentlyContinue |
                    Where-Object LocalAddress -eq '127.0.0.1' | Select-Object -First 1
                if ($listen) { return [int]$listen.LocalPort }
            }
            Start-Sleep -Milliseconds 250
        }
        throw 'Desktop app did not start its sidecar'
    }
    function Assert-SidecarGone([int]$port, [int]$seconds, [string]$case) {
        $deadline = (Get-Date).AddSeconds($seconds)
        while ((Get-Sidecar).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
        if ((Get-Sidecar).Count -gt 0) { throw "Sidecar processes left after $case" }
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port still open after $case" }
    }
    if ((Get-Sidecar).Count -gt 0) { throw 'Precondition: a sidecar is already running' }
    $app = Start-Process -FilePath $desktop -PassThru
    $port = Wait-SidecarPort 90
    if ((Invoke-RestMethod "http://127.0.0.1:$port/api/v1/health" -NoProxy).status -ne 'ready') { throw 'Desktop sidecar not ready' }
    $deadline = (Get-Date).AddSeconds(20)
    while ($app.MainWindowHandle -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250; $app.Refresh() }
    if (-not $app.CloseMainWindow()) { throw 'Desktop window not found' }
    if (-not $app.WaitForExit(40000)) { throw 'Desktop app did not exit after window close' }
    Assert-SidecarGone $port 10 'window close'
    $app = Start-Process -FilePath $desktop -PassThru
    $port = Wait-SidecarPort 90
    Stop-Process -Id $app.Id -Force  # TerminateProcess: no cleanup code runs in the shell
    Assert-SidecarGone $port 10 'shell crash'
    Write-Output "DESKTOP PASS: WebView2 app started, sidecar healthy, clean exit on window close and on shell crash."
    # _?= prevents the NSIS uninstaller from detaching into a temporary copy.
    $result = Start-Process -FilePath $uninstaller -ArgumentList "/S _?=$install" -Wait -PassThru
    if ($result.ExitCode -ne 0) { throw "NSIS uninstall exit $($result.ExitCode)" }
    foreach ($relative in @('aitradingbot-desktop.exe', 'aitradingbot-service.exe', 'ui/index.html')) {
        if (Test-Path -LiteralPath (Join-Path $install $relative)) { throw "Uninstall retained program resource: $relative" }
    }
    if ((Get-Content -Raw -LiteralPath $sentinel).Trim() -ne 'fixture retained ledger boundary') {
        throw 'Uninstall modified separate application data'
    }
    Write-Output 'NSIS PASS: unsigned installer, installed UI/sidecar HTTP smoke, desktop lifecycle, uninstall, separate data retained; no publication.'
} finally {
    Get-Process -Name 'aitradingbot-desktop', 'aitradingbot-service' -ErrorAction SilentlyContinue | Stop-Process -Force
    if (Test-Path -LiteralPath (Join-Path $install 'aitradingbot-desktop.exe')) {
        if (Test-Path -LiteralPath $uninstaller) {
            Start-Process -FilePath $uninstaller -ArgumentList "/S _?=$install" -Wait | Out-Null
        }
    }
    if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force }
}
