& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'manage.py') api
exit $LASTEXITCODE
