param([switch]$Build, [switch]$NoBrowser, [string]$DataDirectory, [ValidateRange(0,65535)][int]$Port = 0)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Crea .venv e installa requirements-dev.txt prima di avviare.' }
if ($Build) {
    Push-Location (Join-Path $root 'frontend')
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Installazione frontend fallita.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Compilazione frontend fallita.' }
    } finally { Pop-Location }
}
$arguments = @((Join-Path $root 'scripts\start_local.py'), '--port', "$Port")
if ($NoBrowser) { $arguments += '--no-browser' }
if ($DataDirectory) { $arguments += @('--data-dir', $DataDirectory) }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Avvio locale non riuscito; nessun trading automatico attivato.' }
