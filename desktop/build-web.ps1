# Builds the frontend for packaging and stages a production-only copy
# (built dist/ + a prod-only node_modules) under desktop/build/web/, kept
# separate from the live web/ checkout so packaging never touches the
# dev node_modules or dist that `npm run dev`/`npm start` in web/ rely on.
#
# Usage: powershell -File desktop/build-web.ps1

$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$WebDir = Join-Path $RepoRoot 'web'
$StageDir = Join-Path $RepoRoot 'desktop\build\web'

# Must match SAMIDA_BACKEND_HOST/SAMIDA_BACKEND_PORT used when launching the
# frozen backend (see desktop/main.js) - this is baked into the client
# bundle at build time and can't be changed at launch time afterwards.
$BackendUrl = 'http://127.0.0.1:8765'

Push-Location $WebDir
try {
  $env:NEXT_PUBLIC_SAMIDA_API_URL = $BackendUrl
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "vinext build failed with exit code $LASTEXITCODE" }
} finally {
  Remove-Item Env:\NEXT_PUBLIC_SAMIDA_API_URL -ErrorAction SilentlyContinue
  Pop-Location
}

if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

Copy-Item -Recurse (Join-Path $WebDir 'dist') (Join-Path $StageDir 'dist')
Copy-Item (Join-Path $WebDir 'package.json') $StageDir
Copy-Item (Join-Path $WebDir 'package-lock.json') $StageDir
Copy-Item (Join-Path $WebDir 'prod-server.js') $StageDir

Push-Location $StageDir
try {
  npm ci --omit=dev
  if ($LASTEXITCODE -ne 0) { throw "npm ci --omit=dev failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}

# electron-builder's extraResources copying silently drops any directory
# literally named "node_modules" (it treats that name specially, as
# something it manages itself via its own dependency-tree logic - it's not
# just a passive file to copy). Renamed here so it survives packaging;
# desktop/main.js creates a directory junction (node_modules ->
# node_modules_prod) at launch so Node's module resolution still finds it.
$NodeModulesPath = Join-Path $StageDir 'node_modules'
$StagedNodeModulesPath = Join-Path $StageDir 'node_modules_prod'
if (Test-Path $StagedNodeModulesPath) { Remove-Item -Recurse -Force $StagedNodeModulesPath }
Rename-Item $NodeModulesPath 'node_modules_prod'

Write-Host "Frontend staged at $StageDir (API URL baked to $BackendUrl)"
