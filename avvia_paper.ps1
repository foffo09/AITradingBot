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
        throw "LOCALAPPDATA non è impostato; impossibile isolare il database Paper."
    }
    $DatabasePath = Join-Path $env:LOCALAPPDATA "AITradingBot\paper\simulation.sqlite3"
} elseif (-not [System.IO.Path]::IsPathRooted($DatabasePath)) {
    throw "Il percorso DB Paper deve essere assoluto: $DatabasePath"
}

$resolvedDatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$personalDatabasePath = [System.IO.Path]::GetFullPath(
    (Join-Path $projectRoot "data\simulation.sqlite3")
)
$demoDatabasePath = $null
if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $demoDatabasePath = [System.IO.Path]::GetFullPath(
        (Join-Path $env:LOCALAPPDATA "AITradingBot\demo\simulation.sqlite3")
    )
}
if ([string]::Equals(
    $resolvedDatabasePath,
    $personalDatabasePath,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Il percorso Paper coincide con il ledger personale; avvio annullato."
}
if ($demoDatabasePath -and [string]::Equals(
    $resolvedDatabasePath,
    $demoDatabasePath,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Paper e demo devono usare database distinti."
}
if (Test-Path -LiteralPath $resolvedDatabasePath -PathType Container) {
    throw "Il percorso DB Paper è una directory: $resolvedDatabasePath"
}
if ((Test-Path -LiteralPath $resolvedDatabasePath -PathType Leaf) -and
    (Test-Path -LiteralPath $personalDatabasePath -PathType Leaf)) {
    $paperFile = Get-Item -LiteralPath $resolvedDatabasePath
    $personalFile = Get-Item -LiteralPath $personalDatabasePath
    if ($paperFile.FullName -eq $personalFile.FullName) {
        throw "Il percorso Paper non può indicare il ledger personale."
    }
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $listener.Start()
} catch {
    throw "La porta loopback $Port non è disponibile; dashboard non avviata."
} finally {
    $listener.Stop()
}

$environmentNames = @(
    "TRADING_MODE",
    "AUTO_TRADE",
    "AI_TRADINGBOT_PAPER_DB_PATH",
    "AI_TRADINGBOT_DEMO_DB_PATH"
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
    $env:TRADING_MODE = "paper"
    $env:AUTO_TRADE = "false"
    $env:AI_TRADINGBOT_PAPER_DB_PATH = $resolvedDatabasePath
    Remove-Item Env:AI_TRADINGBOT_DEMO_DB_PATH -ErrorAction SilentlyContinue

    $paperDirectory = Split-Path -Parent $resolvedDatabasePath
    New-Item -ItemType Directory -Path $paperDirectory -Force | Out-Null
    Push-Location -LiteralPath $projectRoot
    $locationPushed = $true
    Write-Host "Modalità richiesta: Alpaca Paper; automazione disattivata all'avvio."
    Write-Host "Database Paper isolato: $resolvedDatabasePath"
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
