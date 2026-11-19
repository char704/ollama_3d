& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'manage.py') restart-api
exit $LASTEXITCODE
