# Freezes the Python backend into a standalone executable so a packaged
# SAMIDA install needs no Python on the target machine. Run from anywhere;
# paths below are resolved relative to the repo root.
#
# Usage: powershell -File desktop/build-backend.ps1

$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$DistPath = Join-Path $RepoRoot 'desktop\build\backend'
$WorkPath = Join-Path $RepoRoot 'desktop\build\pyinstaller-work'
$SpecPath = Join-Path $RepoRoot 'desktop\build'

if (Test-Path $DistPath) { Remove-Item -Recurse -Force $DistPath }

& $Python -m PyInstaller `
  --name samida-backend `
  --onedir `
  --noconfirm `
  --paths (Join-Path $RepoRoot 'server') `
  --collect-all rapidocr `
  --collect-all onnxruntime `
  --hidden-import tkinter `
  --distpath $DistPath `
  --workpath $WorkPath `
  --specpath $SpecPath `
  (Join-Path $RepoRoot 'server\backend_entry.py')

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

# Generic, static content that SAMIDA_PROJECT_ROOT points at in a packaged
# install (see desktop/main.js) - instructions/, AGENT.md and skills/ are
# safe to ship to every install. memory/ is deliberately NOT copied here:
# it's the owner's personal data (see server/samida/context.py's
# MEMORY_ROUTES) and must never end up in the installer - each install
# gets its own empty, writable memory dir under Electron's userData
# instead.
$ContentDir = Join-Path $RepoRoot 'desktop\build\content'
if (Test-Path $ContentDir) { Remove-Item -Recurse -Force $ContentDir }
New-Item -ItemType Directory -Force -Path $ContentDir | Out-Null
Copy-Item -Recurse (Join-Path $RepoRoot 'instructions') (Join-Path $ContentDir 'instructions')
Copy-Item (Join-Path $RepoRoot 'AGENT.md') $ContentDir
Copy-Item -Recurse (Join-Path $RepoRoot 'skills') (Join-Path $ContentDir 'skills')

Write-Host "Backend frozen to $DistPath\samida-backend\samida-backend.exe"
Write-Host "Static content staged to $ContentDir"
