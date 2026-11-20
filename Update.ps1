param(
    [switch]$SkipPull,
    [string]$JhvAddonPath
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

try {
    if (-not $SkipPull) {
        $branch = & git -C $root branch --show-current
        if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') {
            throw 'Switch to main before updating, or use -SkipPull to sync only the add-on.'
        }
        & git -C $root pull --ff-only origin main
        if ($LASTEXITCODE -ne 0) {
            throw 'Git could not fast-forward. Keep local changes and resolve them before retrying.'
        }
    }

    if (-not $JhvAddonPath) {
        $JhvAddonPath = Join-Path $root 'addons\jhv_dpc\jhv_dpc.py'
        if (-not (Test-Path -LiteralPath $JhvAddonPath -PathType Leaf)) {
            Write-Warning 'Project updated. To install the internal JHV add-on, run Update.ps1 -SkipPull -JhvAddonPath <path-to-jhv_dpc.py>.'
            exit 0
        }
    }
    $source = (Resolve-Path -LiteralPath $JhvAddonPath).Path
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw 'JhvAddonPath must point to the internal jhv_dpc.py file.'
    }
    $config = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $blender = [Environment]::ExpandEnvironmentVariables($config.paths.blender_exe)
    if (-not [IO.Path]::IsPathRooted($blender)) { $blender = Join-Path $root $blender }
    if (-not (Test-Path -LiteralPath $blender -PathType Leaf)) {
        throw 'Set paths.blender_exe in config.json to the Blender executable used on this machine.'
    }
    $probe = @'
import ast, bpy, sys, tokenize
from importlib.util import find_spec
from pathlib import Path
with tokenize.open(sys.argv[-1]) as stream:
    tree = ast.parse(stream.read())
if not any(isinstance(item, ast.FunctionDef) and item.name == 'refresh_asset_index' for item in tree.body):
    raise RuntimeError('Use the internal JHV build that includes SQLite asset indexing')
target = Path(bpy.utils.user_resource('SCRIPTS', path='addons', create=True)) / 'jhv_dpc.py'
spec = find_spec('jhv_dpc')
if spec and (not spec.origin or Path(spec.origin).resolve() != target.resolve()):
    raise RuntimeError('An add-on at another location takes precedence. Update it using the internal install procedure: ' + str(spec.origin))
print('JHV_ADDON_TARGET=' + str(target))
'@
    $probeOutput = & $blender --background --python-exit-code 1 --python-expr $probe -- $source
    if ($LASTEXITCODE -ne 0) {
        $probeOutput | Write-Host
        throw 'Blender could not validate the internal JHV add-on or its install location.'
    }
    $marker = @($probeOutput | Where-Object { $_ -like 'JHV_ADDON_TARGET=*' })
    if ($marker.Count -ne 1) { throw 'Blender did not report its user add-on path.' }
    $target = $marker[0].Substring('JHV_ADDON_TARGET='.Length)
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $installedHash = (Get-FileHash -LiteralPath $target).Hash
        if ($installedHash -eq (Get-FileHash -LiteralPath $source).Hash) {
            Write-Host "JHV add-on is already up to date: $target"
            exit 0
        }
        $backupDirectory = Join-Path $root 'runtime\addon-backups'
        New-Item -Path $backupDirectory -ItemType Directory -Force | Out-Null
        $backup = Join-Path $backupDirectory "jhv_dpc.$installedHash.py"
        if (-not (Test-Path -LiteralPath $backup)) {
            Copy-Item -LiteralPath $target -Destination $backup
        }
        Write-Host "Previous JHV add-on backed up: $backup"
    }
    Copy-Item -LiteralPath $source -Destination $target
    Write-Host "JHV add-on updated: $target"
    Write-Host 'Reopen Blender and start Ollama3D with Open-WebUI.cmd.'
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
