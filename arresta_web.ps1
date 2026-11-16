param([string]$DataDirectory)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python .venv non trovato.' }
$arguments = @((Join-Path $root 'scripts\start_local.py'), '--stop')
if ($DataDirectory) { $arguments += @('--data-dir', $DataDirectory) }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Arresto non confermato: non terminare processi per nome o porta.' }
