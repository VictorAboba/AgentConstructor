# Builds the UI (first run) and starts AgentConstructor on http://localhost:8000
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -q -r backend\requirements.txt
}
if (-not (Test-Path frontend\dist)) {
    Push-Location frontend; npm install; npm run build; Pop-Location
}
Set-Location backend
..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
