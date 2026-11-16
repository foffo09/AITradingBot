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
    # _?= prevents the NSIS uninstaller from detaching into a temporary copy.
    $result = Start-Process -FilePath $uninstaller -ArgumentList "/S _?=$install" -Wait -PassThru
    if ($result.ExitCode -ne 0) { throw "NSIS uninstall exit $($result.ExitCode)" }
    foreach ($relative in @('aitradingbot-desktop.exe', 'aitradingbot-service.exe', 'ui/index.html')) {
        if (Test-Path -LiteralPath (Join-Path $install $relative)) { throw "Uninstall retained program resource: $relative" }
    }
    if ((Get-Content -Raw -LiteralPath $sentinel).Trim() -ne 'fixture retained ledger boundary') {
        throw 'Uninstall modified separate application data'
    }
    Write-Output 'NSIS PASS: unsigned installer, installed UI/sidecar HTTP smoke, uninstall, separate data retained; no publication.'
} finally {
    if (Test-Path -LiteralPath (Join-Path $install 'aitradingbot-desktop.exe')) {
        if (Test-Path -LiteralPath $uninstaller) {
            Start-Process -FilePath $uninstaller -ArgumentList "/S _?=$install" -Wait | Out-Null
        }
    }
    if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force }
}
