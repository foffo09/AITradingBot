param(
    [string]$DatabasePath,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Ambiente virtuale non trovato: $python"
}

if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA non è impostato; impossibile garantire un database demo isolato."
    }
    $DatabasePath = Join-Path $env:LOCALAPPDATA "AITradingBot\demo\simulation.sqlite3"
} elseif (-not [System.IO.Path]::IsPathRooted($DatabasePath)) {
    throw "Il percorso DB demo deve essere assoluto: $DatabasePath"
}

$resolvedDatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$personalDatabasePath = Join-Path $projectRoot "data\simulation.sqlite3"
$resolvedPersonalDatabasePath = [System.IO.Path]::GetFullPath($personalDatabasePath)
if ([string]::Equals(
    $resolvedDatabasePath,
    $resolvedPersonalDatabasePath,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Il percorso demo coincide con il ledger personale; avvio annullato."
}
if (Test-Path -LiteralPath $resolvedDatabasePath -PathType Container) {
    throw "Il percorso del database demo è una directory: $resolvedDatabasePath"
}
if ((Test-Path -LiteralPath $resolvedDatabasePath -PathType Leaf) -and
    (Test-Path -LiteralPath $resolvedPersonalDatabasePath -PathType Leaf)) {
    $demoFile = Get-Item -LiteralPath $resolvedDatabasePath
    $personalFile = Get-Item -LiteralPath $resolvedPersonalDatabasePath
    if ($demoFile.FullName -eq $personalFile.FullName) {
        throw "Il percorso demo non può indicare il ledger personale."
    }
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try {
    $listener.Start()
} catch {
    throw "La porta loopback $Port non è disponibile; dashboard non avviata."
} finally {
    $listener.Stop()
}
$demoDirectory = Split-Path -Parent $resolvedDatabasePath
New-Item -ItemType Directory -Path $demoDirectory -Force | Out-Null

$environmentNames = @(
    "TRADING_MODE",
    "AUTO_TRADE",
    "AI_TRADINGBOT_DEMO_DB_PATH",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $entry = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    $previousEnvironment[$name] = if ($null -eq $entry) {
        @{ Exists = $false; Value = $null }
    } else {
        @{ Exists = $true; Value = $entry.Value }
    }
}

$locationPushed = $false
$streamlitExitCode = 0
try {
    $env:TRADING_MODE = "demo"
    $env:AUTO_TRADE = "false"
    $env:AI_TRADINGBOT_DEMO_DB_PATH = $resolvedDatabasePath
    $env:ALPACA_API_KEY = ""
    $env:ALPACA_SECRET_KEY = ""

    Push-Location -LiteralPath $projectRoot
    $locationPushed = $true
    Write-Host "Modalità demo: AUTO_TRADE=false; nessuna credenziale Alpaca caricata."
    Write-Host "Database demo verificato: $resolvedDatabasePath"
    Write-Host "Dashboard limitata a http://127.0.0.1:$Port/; per arrestarla, premi Ctrl+C."
    & $python -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port
    $streamlitExitCode = $LASTEXITCODE
} finally {
    if ($locationPushed) {
        Pop-Location
    }
    foreach ($name in $environmentNames) {
        $previous = $previousEnvironment[$name]
        if ($previous.Exists) {
            Set-Item -LiteralPath "Env:$name" -Value $previous.Value
        } else {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

if ($streamlitExitCode -ne 0) {
    throw "Streamlit terminato con codice $streamlitExitCode."
}
