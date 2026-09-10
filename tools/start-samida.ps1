param(
    [Parameter(Mandatory = $true)]
    [string]$CamofoxRoot
)

$ErrorActionPreference = 'Stop'
$samidaRoot = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $samidaRoot 'data\camofox-profile'
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

Write-Host 'Startar Ollama...' -ForegroundColor Magenta
$ollama = $null
if (-not (Test-Port 11434)) { $ollama = Start-Process -FilePath 'ollama' -ArgumentList 'serve' -PassThru }

Write-Host 'Startar CamoFox...' -ForegroundColor Cyan
if (-not (Test-Path $camofoxCache)) {
    Write-Host 'Installerar Camoufox-binärer (första gången)...' -ForegroundColor Cyan
    Push-Location $CamofoxRoot
    try { & node 'node_modules\camoufox-js\dist\__main__.js' fetch }
    finally { Pop-Location }
}
$camofox = $null
if (-not (Test-Port 9377)) { $camofox = Start-Process -FilePath 'node' -ArgumentList 'server.js' -WorkingDirectory $CamofoxRoot -PassThru }

try {
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:9377/health' -TimeoutSec 2
            if ($health.ok) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'CamoFox svarade inte inom 30 sekunder.' }

    Write-Host 'Startar SAMIDA...' -ForegroundColor Green
    $web = $null
    if (-not (Test-Port 3000)) { $web = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run dev -- --host 127.0.0.1' -WorkingDirectory (Join-Path $samidaRoot 'web') -PassThru }
    Start-Process 'http://localhost:3000/'
    Push-Location $samidaRoot
    try { & '.venv\Scripts\python.exe' '-m' 'uvicorn' 'server.samida.main:app' '--reload' }
    finally { Pop-Location }
}
finally {
    if ($camofox -and -not $camofox.HasExited) {
        Write-Host 'Stoppar CamoFox...' -ForegroundColor Yellow
        Stop-Process -Id $camofox.Id -Force -ErrorAction SilentlyContinue
    }
    if ($ollama -and -not $ollama.HasExited) {
        Write-Host 'Stoppar Ollama...' -ForegroundColor Yellow
        Stop-Process -Id $ollama.Id -Force -ErrorAction SilentlyContinue
    }
    if ($web -and -not $web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
}
