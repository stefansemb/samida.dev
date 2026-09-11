$samidaRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $samidaRoot 'data\samida-runtime.json'

if (-not (Test-Path $stateFile)) {
    Write-Host 'Ingen körande SAMIDA-session hittades.' -ForegroundColor Yellow
    exit
}

$state = Get-Content $stateFile -Raw | ConvertFrom-Json
foreach ($name in @('backend', 'web', 'camofox', 'ollama')) {
    $procId = $state.$name
    if (-not $procId) { continue }
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        Write-Host "Stoppar $name (PID $procId)..." -ForegroundColor Yellow
        & taskkill /PID $procId /T /F | Out-Null
    }
}

Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
Write-Host 'SAMIDA stoppad.' -ForegroundColor Green
