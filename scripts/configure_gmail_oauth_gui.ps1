param()

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$sshPath = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$identityPath = Join-Path $env:USERPROFILE ".ssh\codex_vps_key"
$remoteTarget = "root@165.232.68.212"
$remoteHelper = "/opt/ai-outreach-system/tools/configure_gmail_oauth_secret.py"

if (-not (Test-Path -LiteralPath $sshPath)) { throw "Windows OpenSSH was not found." }
if (-not (Test-Path -LiteralPath $identityPath)) { throw "SSH identity was not found." }

$form = New-Object System.Windows.Forms.Form
$form.Text = "Connect Gmail OAuth to Single Outreach"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(700, 330)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.TopMost = $true

$notice = New-Object System.Windows.Forms.Label
$notice.Location = New-Object System.Drawing.Point(20, 15)
$notice.Size = New-Object System.Drawing.Size(660, 42)
$notice.Text = "Choose the downloaded Google OAuth JSON, or paste Client ID and Client secret below. Values go directly to ai-prod-01 and are not stored on this computer."
$form.Controls.Add($notice)

$jsonLabel = New-Object System.Windows.Forms.Label
$jsonLabel.Location = New-Object System.Drawing.Point(20, 70)
$jsonLabel.Size = New-Object System.Drawing.Size(120, 22)
$jsonLabel.Text = "OAuth JSON file"
$form.Controls.Add($jsonLabel)

$jsonPath = New-Object System.Windows.Forms.TextBox
$jsonPath.Location = New-Object System.Drawing.Point(145, 66)
$jsonPath.Size = New-Object System.Drawing.Size(425, 26)
$jsonPath.ReadOnly = $true
$form.Controls.Add($jsonPath)

$browse = New-Object System.Windows.Forms.Button
$browse.Location = New-Object System.Drawing.Point(580, 64)
$browse.Size = New-Object System.Drawing.Size(100, 30)
$browse.Text = "Browse..."
$form.Controls.Add($browse)

$idLabel = New-Object System.Windows.Forms.Label
$idLabel.Location = New-Object System.Drawing.Point(20, 125)
$idLabel.Size = New-Object System.Drawing.Size(120, 22)
$idLabel.Text = "Client ID"
$form.Controls.Add($idLabel)

$clientIdBox = New-Object System.Windows.Forms.TextBox
$clientIdBox.Location = New-Object System.Drawing.Point(145, 121)
$clientIdBox.Size = New-Object System.Drawing.Size(535, 26)
$form.Controls.Add($clientIdBox)

$secretLabel = New-Object System.Windows.Forms.Label
$secretLabel.Location = New-Object System.Drawing.Point(20, 175)
$secretLabel.Size = New-Object System.Drawing.Size(120, 22)
$secretLabel.Text = "Client secret"
$form.Controls.Add($secretLabel)

$clientSecretBox = New-Object System.Windows.Forms.TextBox
$clientSecretBox.Location = New-Object System.Drawing.Point(145, 171)
$clientSecretBox.Size = New-Object System.Drawing.Size(535, 26)
$clientSecretBox.UseSystemPasswordChar = $true
$form.Controls.Add($clientSecretBox)

$safety = New-Object System.Windows.Forms.Label
$safety.Location = New-Object System.Drawing.Point(145, 205)
$safety.Size = New-Object System.Drawing.Size(535, 38)
$safety.Text = "Real email remains OFF. This only enables the Google authorization button and reply synchronization after your consent."
$form.Controls.Add($safety)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Location = New-Object System.Drawing.Point(435, 260)
$cancel.Size = New-Object System.Drawing.Size(100, 38)
$cancel.Text = "Cancel"
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.CancelButton = $cancel
$form.Controls.Add($cancel)

$save = New-Object System.Windows.Forms.Button
$save.Location = New-Object System.Drawing.Point(545, 260)
$save.Size = New-Object System.Drawing.Size(135, 38)
$save.Text = "Configure Gmail"
$save.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $save
$form.Controls.Add($save)

$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select Google OAuth client JSON"
    $dialog.Filter = "JSON files (*.json)|*.json"
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        try {
            $document = Get-Content -LiteralPath $dialog.FileName -Raw | ConvertFrom-Json
            $web = $document.web
            if ($null -eq $web) { $web = $document.installed }
            if ($null -eq $web.client_id -or $null -eq $web.client_secret) {
                throw "The JSON has no OAuth client credentials."
            }
            $jsonPath.Text = $dialog.FileName
            $clientIdBox.Text = [string]$web.client_id
            $clientSecretBox.Text = [string]$web.client_secret
        }
        catch {
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Invalid JSON") | Out-Null
        }
    }
})

$result = $form.ShowDialog()
if ($result -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }

$clientId = $clientIdBox.Text.Trim()
$clientSecret = $clientSecretBox.Text.Trim()
try {
    if (-not $clientId.EndsWith(".apps.googleusercontent.com")) {
        throw "Client ID is invalid."
    }
    if ([string]::IsNullOrWhiteSpace($clientSecret)) {
        throw "Client secret is empty."
    }
    $payload = @{ client_id = $clientId; client_secret = $clientSecret } | ConvertTo-Json -Compress
    $output = $payload | & $sshPath -i $identityPath -o BatchMode=yes -o StrictHostKeyChecking=no $remoteTarget $remoteHelper
    if ($LASTEXITCODE -ne 0) { throw "Production Gmail configuration failed." }
    [System.Windows.Forms.MessageBox]::Show(
        ($output -join [Environment]::NewLine),
        "Gmail configuration completed",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}
finally {
    $payload = $null
    $clientSecret = $null
    $clientSecretBox.Clear()
    $clientIdBox.Clear()
    $form.Dispose()
}
