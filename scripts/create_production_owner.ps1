$ErrorActionPreference = 'Stop'

$sshPath = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$keyPath = Join-Path $env:USERPROFILE '.ssh\codex_vps_key'

if (-not (Test-Path -LiteralPath $sshPath)) {
    throw "OpenSSH client not found: $sshPath"
}

if (-not (Test-Path -LiteralPath $keyPath)) {
    throw "SSH key not found: $keyPath"
}

$remoteCommand = @'
cd /opt/ai-outreach-system/current && docker compose --env-file /etc/ai-outreach-system/production.env -f compose.production.example.yaml exec app python scripts/create_owner.py --login owner
'@

Write-Host ''
Write-Host 'AI Outreach System owner setup' -ForegroundColor Cyan
Write-Host 'Enter a new password with at least 12 characters, then repeat it.'
Write-Host 'The password is not displayed while typing. This is normal.'
Write-Host ''

& $sshPath -i $keyPath -t 'root@165.232.68.212' $remoteCommand.Trim()

if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host 'Done. Open https://outreach.shaidigroup.com/login' -ForegroundColor Green
} else {
    Write-Host ''
    Write-Host "Command failed with exit code $LASTEXITCODE. Keep this window open and show the error to Codex." -ForegroundColor Red
}

Write-Host ''
Read-Host 'Press Enter to close this window'
