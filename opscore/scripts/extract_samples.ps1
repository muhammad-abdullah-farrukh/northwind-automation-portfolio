<#
.SYNOPSIS
  Posts every PDF in a folder to /v1/extract/sync and compares each result with labels.jsonl.

.DESCRIPTION
  Reads the dev API key from .secrets\dev.key (never printed). Uses curl.exe for the multipart upload.
  "Data match" means the extracted data equals the ground-truth label exactly (all fields and line items).
  Every number printed here comes from the actual run; nothing is estimated.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\extract_samples.ps1
#>
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Dir
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Dir) { $Dir = Join-Path $root "evals\data\invoices" }
$key = (Get-Content (Join-Path $root ".secrets\dev.key") -Raw).Trim()

$labels = @{}
Get-Content (Join-Path $Dir "labels.jsonl") -Encoding UTF8 | ForEach-Object { $l = $_ | ConvertFrom-Json; $labels[$l.file] = $l }

$rows = foreach ($f in Get-ChildItem $Dir -Filter *.pdf | Sort-Object Name) {
    $out = & curl.exe -s -w "`n%{http_code}" -H "X-API-Key: $key" -F "file=@$($f.FullName);type=application/pdf" -F "schema=invoice" "$BaseUrl/v1/extract/sync"
    $lines = @($out)
    $code = $lines[-1]
    $body = ($lines[0..($lines.Count - 2)] -join "`n") | ConvertFrom-Json
    $label = $labels[$f.Name]
    if ($code -eq "200") {
        $match = ($body.data | ConvertTo-Json -Depth 6 -Compress) -eq ($label.data | ConvertTo-Json -Depth 6 -Compress)
        [pscustomobject]@{
            File       = $f.Name
            HTTP       = $code
            Status     = $body.status
            Expected   = $label.expected_status
            DataMatch  = $match
            Confidence = $body.confidence.overall
            Errors     = (($body.validation.errors | ForEach-Object { $_.code }) -join ",")
            Tokens     = $body.meta.tokens
            LlmMs      = $body.meta.latency_ms
            JobId      = $body.job_id
        }
    } else {
        [pscustomobject]@{ File = $f.Name; HTTP = $code; Status = "-"; Expected = $label.expected_status; DataMatch = $false; Confidence = $null; Errors = $body.detail; Tokens = $null; LlmMs = $null; JobId = $null }
    }
}

$rows | Format-Table File, HTTP, Status, Expected, DataMatch, Confidence, Errors, Tokens, LlmMs -AutoSize | Out-String -Width 220 | Write-Host
$ok = @($rows | Where-Object { $_.HTTP -eq "200" }).Count
$asExpected = @($rows | Where-Object { $_.Status -eq $_.Expected }).Count
$matched = @($rows | Where-Object { $_.DataMatch }).Count
Write-Host "$($rows.Count) files: $ok returned 200, $asExpected ended in the expected status, $matched matched their label exactly."
