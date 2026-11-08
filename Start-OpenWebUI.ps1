param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { Write-Host 'Run Install.cmd first.'; exit 1 }
$arguments = @((Join-Path $PSScriptRoot 'manage.py'), 'start')
if ($NoBrowser) { $arguments += '--no-browser' }
& $python @arguments
exit $LASTEXITCODE
