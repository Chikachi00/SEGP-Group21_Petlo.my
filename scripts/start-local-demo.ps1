param([switch]$CheckOnly, [switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$vite = Join-Path $projectRoot 'node_modules\vite\bin\vite.js'
if (!(Test-Path -LiteralPath $python)) { throw 'Missing .venv. Follow docs/local-full-stack-testing.md to install Python dependencies.' }
if (!(Test-Path -LiteralPath $vite)) { throw 'Missing frontend dependencies. Run npm ci from the repository root.' }
$node = (Get-Command node -ErrorAction Stop).Source
if (!(Test-Path -LiteralPath '.env.local')) {
    if ($CheckOnly) { throw 'Missing .env.local. Run this script without -CheckOnly to create the example configuration.' }
    Copy-Item -LiteralPath '.env.example' -Destination '.env.local'
}
if (!(Test-Path -LiteralPath 'backend\.env')) {
    if ($CheckOnly) { throw 'Missing backend/.env. Run this script without -CheckOnly to create the example configuration.' }
    Copy-Item -LiteralPath 'backend\.env.example' -Destination 'backend\.env'
}
$frontendConfig = Get-Content -LiteralPath '.env.local' -Raw
if ($frontendConfig -notmatch '(?m)^\s*VITE_USE_API\s*=\s*true\s*$') { throw 'Set VITE_USE_API=true in .env.local; existing configuration was preserved.' }
if ($frontendConfig -notmatch '(?m)^\s*VITE_API_BASE_URL\s*=\s*http://(localhost|127\.0\.0\.1):8000/api/v1\s*$') { throw 'This launcher expects VITE_API_BASE_URL=http://localhost:8000/api/v1. Existing configuration was preserved.' }
& $python -c "import fastapi, uvicorn, httpx, sqlalchemy, cv2, ultralytics; from backend.config import Settings; from backend.pipeline import PipelineRunner; s=Settings(); s.validate(); PipelineRunner(s).check_ready(); print('PASS: Python, model and FFmpeg readiness')"
if ($LASTEXITCODE -ne 0) { throw 'Backend readiness failed. Check the preceding error; do not continue to the presentation yet.' }
if ($CheckOnly) { Write-Host 'PASS: local demo configuration is ready.'; return }

function Test-LocalPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync('localhost', $Port).Wait(700) -and $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
function Wait-LocalUrl([string]$Url) {
    $deadline = (Get-Date).AddSeconds(35)
    do {
        try { return Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 }
        catch { Start-Sleep -Milliseconds 400 }
    } while ((Get-Date) -lt $deadline)
    throw "Service did not become ready: $Url. Inspect outputs/local-demo/ logs."
}
$logRoot = Join-Path $projectRoot 'outputs\local-demo'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$statePath = Join-Path $logRoot 'processes.json'
$ownedProcesses = @()
if (Test-Path -LiteralPath $statePath) {
    $loaded = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    foreach ($entry in $loaded) {
        if ($entry -and $entry.process_id -and $entry.started_utc_ticks -and $entry.kind -in 'backend', 'frontend') { $ownedProcesses += $entry }
    }
}
$runTag = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
function Save-StartedProcess($Process, [string]$Kind) {
    $script:ownedProcesses += [pscustomobject]@{ process_id = $Process.Id; started_utc_ticks = $Process.StartTime.ToUniversalTime().Ticks; kind = $Kind }
    ConvertTo-Json -InputObject @($script:ownedProcesses) | Set-Content -LiteralPath $statePath -Encoding UTF8
}
if (!(Test-LocalPort 8000)) {
    $process = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000', '--no-proxy-headers', '--env-file', 'backend/.env') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "backend-$runTag.out.log") -RedirectStandardError (Join-Path $logRoot "backend-$runTag.err.log")
    Save-StartedProcess $process 'backend'
}
$health = (Wait-LocalUrl 'http://127.0.0.1:8000/api/v1/health').Content | ConvertFrom-Json
if ($health.mode -ne 'local_single_user') { throw 'Port 8000 is occupied by a different service. It was not stopped.' }
if (!(Test-LocalPort 5173)) {
    # Quoted absolute argument preserves repository paths containing spaces.
    $arguments = '"' + $vite + '" --host 127.0.0.1 --port 5173 --strictPort'
    $process = Start-Process -FilePath $node -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "frontend-$runTag.out.log") -RedirectStandardError (Join-Path $logRoot "frontend-$runTag.err.log")
    Save-StartedProcess $process 'frontend'
}
$page = Wait-LocalUrl 'http://localhost:5173/'
if ($page.Content -notmatch '/src/main.tsx') { throw 'Port 5173 does not look like the expected Vite app. The existing service was not stopped.' }
Write-Host 'Ready: http://localhost:5173/ (real local API mode)'
Write-Host 'API docs: http://127.0.0.1:8000/docs'
Write-Host 'Logs: outputs/local-demo/. The backend must keep running during analysis.'
Write-Host 'To stop script-started services after tasks finish: powershell -ExecutionPolicy Bypass -File scripts/stop-local-demo.ps1'
if ($OpenBrowser) { Start-Process 'http://localhost:5173/' }
