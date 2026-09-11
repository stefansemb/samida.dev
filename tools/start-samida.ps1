param(
    [Parameter(Mandatory = $true)]
    [string]$CamofoxRoot
)

# Re-launch itself as a hidden background process on first run, so the
# desktop shortcut never shows a console window. The child inherits
# SAMIDA_LAUNCHER_HIDDEN from the environment, so it skips this block.
if (-not $env:SAMIDA_LAUNCHER_HIDDEN) {
    $env:SAMIDA_LAUNCHER_HIDDEN = '1'
    $escapedRoot = $CamofoxRoot -replace '"', '""'
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
        '-File', "`"$PSCommandPath`"", '-CamofoxRoot', "`"$escapedRoot`""
    )
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden
    exit
}

$ErrorActionPreference = 'Stop'
$samidaRoot = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $samidaRoot 'data\camofox-profile'
$stateFile = Join-Path $samidaRoot 'data\samida-runtime.json'
function Test-Port([int]$Port) { return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) }

if (-not (Test-Path (Join-Path $CamofoxRoot 'server.js'))) {
    throw "Hittar inte CamoFox server.js i: $CamofoxRoot"
}

$env:CAMOFOX_CRASH_REPORT_ENABLED = 'false'
$env:CAMOFOX_BIND_HOST = '127.0.0.1'
$env:CAMOFOX_PROFILE_DIR = $profileDir
$env:SAMIDA_CAMOFOX_ENABLED = 'true'
$env:SAMIDA_CAMOFOX_BASE_URL = 'http://127.0.0.1:9377'
$camofoxCache = Join-Path $env:LOCALAPPDATA 'camoufox\camoufox\Cache\version.json'

$ollamaPid = $null
if (-not (Test-Port 11434)) {
    $ollama = Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    $ollamaPid = $ollama.Id
}

if (-not (Test-Path $camofoxCache)) {
    Push-Location $CamofoxRoot
    try { & node 'node_modules\camoufox-js\dist\__main__.js' fetch }
    finally { Pop-Location }
}
$camofoxPid = $null
if (-not (Test-Port 9377)) {
    $camofox = Start-Process -FilePath 'node' -ArgumentList 'server.js' -WorkingDirectory $CamofoxRoot -WindowStyle Hidden -PassThru
    $camofoxPid = $camofox.Id
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:9377/health' -TimeoutSec 2
        if ($health.ok) { $ready = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw 'CamoFox svarade inte inom 30 sekunder.' }

$webPid = $null
if (-not (Test-Port 3000)) {
    $web = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run dev -- --host 127.0.0.1' -WorkingDirectory (Join-Path $samidaRoot 'web') -WindowStyle Hidden -PassThru
    $webPid = $web.Id
}

$backendPid = $null
if (-not (Test-Port 8000)) {
    $pythonExe = Join-Path $samidaRoot '.venv\Scripts\python.exe'
    $backend = Start-Process -FilePath $pythonExe -ArgumentList '-m', 'uvicorn', 'server.samida.main:app', '--reload' -WorkingDirectory $samidaRoot -WindowStyle Hidden -PassThru
    $backendPid = $backend.Id
}

@{
    ollama   = $ollamaPid
    camofox  = $camofoxPid
    web      = $webPid
    backend  = $backendPid
} | ConvertTo-Json | Set-Content -Path $stateFile -Encoding utf8

Start-Process 'http://localhost:3000/'
