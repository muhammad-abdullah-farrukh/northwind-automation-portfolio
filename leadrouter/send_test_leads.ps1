<#
.SYNOPSIS
  Posts the synthetic test leads to the LeadRouter Zap's Catch Hook.

.DESCRIPTION
  The hook URL is read from leadrouter\.secrets\hook_url.txt (git-ignored; anyone with the URL can
  trigger the Zap). Each lead goes out as JSON with its lead_ref, so results can be matched in the
  Zapier Tables log. Leads are spaced out so the run history stays readable.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File send_test_leads.ps1
  powershell -ExecutionPolicy Bypass -File send_test_leads.ps1 -Only T01,T15
#>
param(
    [string[]]$Only,
    [int]$DelaySeconds = 5
)
$ErrorActionPreference = "Stop"
$hookFile = Join-Path $PSScriptRoot ".secrets\hook_url.txt"
if (-not (Test-Path $hookFile)) { throw "Missing .secrets\hook_url.txt (the Catch Hook URL from the Zap's trigger step)." }
$hook = (Get-Content $hookFile -Raw).Trim()

$leads = (Get-Content (Join-Path $PSScriptRoot "test_leads.json") -Raw -Encoding UTF8 | ConvertFrom-Json).leads
if ($Only) { $leads = $leads | Where-Object { $Only -contains $_.lead_ref } }

foreach ($lead in $leads) {
    $payload = [ordered]@{
        lead_ref = $lead.lead_ref; name = $lead.name; email = $lead.email; company = $lead.company; website = $lead.website
        budget = $lead.budget; service = $lead.service; timeline = $lead.timeline; message = $lead.message; source = "test-script"
    }
    $body = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
    $resp = Invoke-RestMethod -Method POST -Uri $hook -ContentType "application/json; charset=utf-8" -Body $body -UseBasicParsing
    Write-Host ("{0}  expected {1,-6} -> hook status: {2}" -f $lead.lead_ref, $lead.expected_tier, $resp.status)
    Start-Sleep -Seconds $DelaySeconds
}
Write-Host "Sent $(@($leads).Count) lead(s). Check the Zap's run history and the LeadRouter log table."
