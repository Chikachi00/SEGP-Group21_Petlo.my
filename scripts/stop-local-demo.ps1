$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot 'outputs\local-demo\processes.json'
if (!(Test-Path -LiteralPath $statePath)) { Write-Host 'No script-started services recorded. Close manually started terminals yourself.'; return }
$entries = @()
$loaded = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
foreach ($entry in $loaded) {
    if ($entry -and $entry.process_id -and $entry.started_utc_ticks -and $entry.kind -in 'backend', 'frontend') { $entries += $entry }
}
if ($entries.Count -eq 0) { Write-Host 'No script-started services to stop.'; return }
try {
    $first = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/sessions?page=1&page_size=100' -TimeoutSec 3
    $items = @($first.items)
    for ($page = 2; $items.Count -lt $first.total; $page++) {
        $next = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/sessions?page=$page&page_size=100" -TimeoutSec 3
        if (@($next.items).Count -eq 0) { throw 'Could not verify all task states.' }
        $items += @($next.items)
    }
} catch { throw 'Cannot verify that analysis is idle. Check the backend and finish active tasks before stopping it.' }
if (@($items | Where-Object { $_.status -in 'queued', 'running' }).Count -gt 0) { throw 'Analysis is still queued or running. Wait for completion before stopping services.' }
$remaining = @()
foreach ($entry in $entries) {
    $process = Get-Process -Id $entry.process_id -ErrorAction SilentlyContinue
    if (!$process -or $process.StartTime.ToUniversalTime().Ticks -ne [long]$entry.started_utc_ticks) { continue }
    $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.process_id)").CommandLine
    $expected = if ($entry.kind -eq 'backend') { 'backend.main:app' } else { Join-Path $projectRoot 'node_modules\vite\bin\vite.js' }
    if (!$command -or !$command.Contains($expected)) { Write-Warning "Process identity changed: $($entry.process_id). It was not stopped."; $remaining += $entry; continue }
    Stop-Process -Id $entry.process_id
    Write-Host "Stopped $($entry.kind) ($($entry.process_id))."
}
if ($remaining.Count -eq 0) { '[]' | Set-Content -LiteralPath $statePath -Encoding UTF8 }
else { ConvertTo-Json -InputObject $remaining | Set-Content -LiteralPath $statePath -Encoding UTF8 }
