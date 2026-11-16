param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $matches = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe" -ErrorAction SilentlyContinue
    if ($matches) { return ($matches | Select-Object -First 1).FullName }
    return $null
}

function Install-Package([string]$Id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "WinGet is missing. Install Microsoft App Installer, then run Install.cmd again. Missing package: $Id"
    }
    Write-Host "Installing $Id..."
    & winget install --id $Id --exact --source winget --silent --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "WinGet failed for $Id (exit $LASTEXITCODE). Install that package, then run Install.cmd again." }
}

try {
    $configPath = Join-Path $root 'config.json'
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $uv = Find-Uv
    if (-not $uv) { Install-Package 'astral-sh.uv'; $uv = Find-Uv }
    if (-not $uv) { throw 'uv was installed but its executable could not be located. Reopen Install.cmd.' }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $root '.python'
    $env:PYTHONIOENCODING = 'utf-8'
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        & $uv venv --python 3.12 --managed-python (Join-Path $root '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
    }
    & $python -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
    if ($LASTEXITCODE -ne 0) { throw 'Existing Python environment is invalid. Keep webui-data and inputs; rebuild .venv on this machine.' }
    & $uv pip install --python $python --requirement (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    $ollamaPath = if ($config.ollama.executable) { [Environment]::ExpandEnvironmentVariables($config.ollama.executable) } elseif ($ollamaCommand) { $ollamaCommand.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe' }
    if (-not [IO.Path]::IsPathRooted($ollamaPath)) { $ollamaPath = Join-Path $root $ollamaPath }
    if (-not (Test-Path -LiteralPath $ollamaPath)) {
        if ($config.ollama.executable) { throw 'Configured ollama.executable does not exist. Correct config.json first.' }
        Install-Package 'Ollama.Ollama'
    }

    $enabledOperators = @($config.blender_operators | Where-Object { $_.enabled -ne $false })
    $needsBlender = $config.blender_agent.enabled -or $config.workflow.apply.provider -eq 'local' -or $enabledOperators.Count -gt 0
    if ($needsBlender) {
        $blenderPath = [Environment]::ExpandEnvironmentVariables($config.paths.blender_exe)
        if (-not [IO.Path]::IsPathRooted($blenderPath)) { $blenderPath = Join-Path $root $blenderPath }
        if (-not (Test-Path -LiteralPath $blenderPath -PathType Leaf)) {
            $candidate = Get-Command blender -ErrorAction SilentlyContinue
            if ($candidate) { $blenderPath = $candidate.Source } else {
                $candidate = Get-ChildItem -Path "$env:ProgramFiles\Blender Foundation\Blender*\blender.exe" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if (-not $candidate) {
                    Install-Package 'BlenderFoundation.Blender'
                    $candidate = Get-ChildItem -Path "$env:ProgramFiles\Blender Foundation\Blender*\blender.exe" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                }
                if (-not $candidate) { throw 'Set paths.blender_exe in config.json to the installed blender.exe.' }
                $blenderPath = $candidate.FullName
            }
            $config.paths.blender_exe = $blenderPath
            $config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8
        }
    }
    $arguments = @((Join-Path $root 'manage.py'), 'install')
    if ($NoBrowser) { $arguments += '--no-browser' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Setup did not finish. See the error above and logs folder.' }
    Write-Host 'Setup complete. Next time, use Open-WebUI.cmd.'
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
