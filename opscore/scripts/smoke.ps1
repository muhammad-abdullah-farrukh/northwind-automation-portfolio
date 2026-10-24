<#
.SYNOPSIS
  OpsCore P1 smoke test: /healthz, /v1/leads/enrich, and an idempotent replay.

.DESCRIPTION
  Reads the dev API key from .secrets\dev.key (never printed). Targets the Cloudflare
  quick-tunnel URL when the cloudflared container is running, otherwise http://127.0.0.1:8000.
  The test lead is a fictional person; nothing is ever emailed.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
  powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1 -BaseUrl http://localhost:8000
#>
param(
    [string]$BaseUrl,
    [string]$Email = "test.lead@posthog.com",
    [string]$Website = "https://posthog.com",
    [string]$Company = "PostHog"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$keyFile = Join-Path $root ".secrets\dev.key"
if (-not (Test-Path $keyFile)) { throw "Missing .secrets\dev.key. Run: docker compose exec api python -m app.cli create-key --name dev" }
$key = (Get-Content $keyFile -Raw).Trim()

if (-not $BaseUrl) {
    $logs = (docker compose -f (Join-Path $root "docker-compose.yml") logs cloudflared 2>$null) -join "`n"
    $found = [regex]::Matches($logs, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($found.Count -gt 0) { $BaseUrl = $found[$found.Count - 1].Value } else { $BaseUrl = "http://127.0.0.1:8000" }
}
Write-Host "Target: $BaseUrl`n"

function Invoke-Api([string]$Method, [string]$Path, [hashtable]$Headers = @{}, [string]$Body = $null) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $replay = $null
    try {
        $params = @{ Method = $Method; Uri = "$BaseUrl$Path"; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 30 }
        if ($Body) { $params.Body = $Body; $params.ContentType = "application/json" }
        $r = Invoke-WebRequest @params
        $status = [int]$r.StatusCode
        $content = $r.Content
        $replay = $r.Headers["Idempotent-Replay"]
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if (-not $resp) { throw }
        $status = [int]$resp.StatusCode
        $content = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
        $replay = $resp.Headers["Idempotent-Replay"]
    }
    $sw.Stop()
    [pscustomobject]@{ Status = $status; Ms = $sw.ElapsedMilliseconds; Body = $content; Replay = $replay }
}

$failures = 0
function Check([bool]$ok, [string]$label) {
    if ($ok) { Write-Host "PASS  $label" -ForegroundColor Green } else { Write-Host "FAIL  $label" -ForegroundColor Red; $script:failures++ }
}

$health = Invoke-Api GET "/healthz"
Write-Host "GET /healthz -> $($health.Status) in $($health.Ms) ms: $($health.Body)"
Check ($health.Status -eq 200) "healthz returns 200"

$lead = @{ email = $Email; website = $Website; company = $Company; name = "Test Lead" } | ConvertTo-Json -Compress
$idem = "smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 12)
$headers = @{ "X-API-Key" = $key; "Idempotency-Key" = $idem }

$first = Invoke-Api POST "/v1/leads/enrich" $headers $lead
Write-Host "`nPOST /v1/leads/enrich -> $($first.Status) in $($first.Ms) ms (end-to-end, includes network)"
if ($first.Status -eq 200) { $first.Body | ConvertFrom-Json | ConvertTo-Json -Depth 5 | Write-Host } else { Write-Host $first.Body }
Check ($first.Status -eq 200) "enrich returns 200"
Check ($first.Ms -lt 5000) "enrich answered in under 5 s"

$second = Invoke-Api POST "/v1/leads/enrich" $headers $lead
Write-Host "`nReplay with the same Idempotency-Key -> $($second.Status) in $($second.Ms) ms, Idempotent-Replay=$($second.Replay)"
Check ($second.Status -eq 200 -and $second.Replay -eq "true") "replay is flagged Idempotent-Replay: true"
Check ($second.Body -eq $first.Body) "replay body is byte-identical to the first response"

Write-Host ""
if ($failures -eq 0) { Write-Host "All checks passed." -ForegroundColor Green; exit 0 } else { Write-Host "$failures check(s) failed." -ForegroundColor Red; exit 1 }
