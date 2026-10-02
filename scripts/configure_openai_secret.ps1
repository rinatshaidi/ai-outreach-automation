param(
    [switch]$Gui
)

$ErrorActionPreference = "Stop"

$sshPath = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$identityPath = Join-Path $env:USERPROFILE ".ssh\codex_vps_key"
$remoteTarget = "root@165.232.68.212"
$remoteHelper = "/opt/ai-outreach-system/tools/configure_openai_discovery_secret.sh"

if (-not (Test-Path -LiteralPath $sshPath)) {
    throw "Windows OpenSSH client was not found."
}
if (-not (Test-Path -LiteralPath $identityPath)) {
    throw "SSH identity file was not found."
}

$secureKey = $null
if ($Gui) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "OpenAI key for company discovery"
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = New-Object System.Drawing.Size(590, 185)
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true

    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(20, 18)
    $label.Size = New-Object System.Drawing.Size(550, 42)
    $label.Text = "Paste a NEW key. It will enable only company discovery, not AI rewrite or email sending."
    $form.Controls.Add($label)

    $keyBox = New-Object System.Windows.Forms.TextBox
    $keyBox.Location = New-Object System.Drawing.Point(20, 68)
    $keyBox.Size = New-Object System.Drawing.Size(550, 28)
    $keyBox.UseSystemPasswordChar = $true
    $form.Controls.Add($keyBox)

    $saveButton = New-Object System.Windows.Forms.Button
    $saveButton.Location = New-Object System.Drawing.Point(390, 118)
    $saveButton.Size = New-Object System.Drawing.Size(180, 38)
    $saveButton.Text = "Save to production"
    $saveButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.AcceptButton = $saveButton
    $form.Controls.Add($saveButton)

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Location = New-Object System.Drawing.Point(285, 118)
    $cancelButton.Size = New-Object System.Drawing.Size(95, 38)
    $cancelButton.Text = "Cancel"
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.CancelButton = $cancelButton
    $form.Controls.Add($cancelButton)

    $form.Add_Shown({ $keyBox.Focus() })
    $dialogResult = $form.ShowDialog()
    if ($dialogResult -ne [System.Windows.Forms.DialogResult]::OK) {
        exit 0
    }

    $secureKey = ConvertTo-SecureString -String $keyBox.Text -AsPlainText -Force
    $keyBox.Clear()
    $form.Dispose()
}
else {
    $secureKey = Read-Host "Paste NEW OPENAI_API_KEY (input is hidden)" -AsSecureString
}
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$plainKey = $null
$previousOutputEncoding = $OutputEncoding
$previousConsoleOutputEncoding = [Console]::OutputEncoding

try {
    # PowerShell 5 otherwise pipes native-process input as UTF-16LE, which the
    # remote validator correctly rejects as embedded control characters.
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = $OutputEncoding
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

    while ($plainKey.StartsWith("`r") -or $plainKey.StartsWith("`n")) {
        $plainKey = $plainKey.Substring(1)
    }
    while ($plainKey.EndsWith("`r") -or $plainKey.EndsWith("`n")) {
        $plainKey = $plainKey.Substring(0, $plainKey.Length - 1)
    }

    if ([string]::IsNullOrEmpty($plainKey)) {
        throw "The key is empty; nothing changed."
    }

    $prefix = $null
    foreach ($candidate in @("sk-proj-", "sk-svcacct-", "sk-")) {
        if ($plainKey.StartsWith($candidate, [StringComparison]::Ordinal)) {
            $prefix = $candidate
            break
        }
    }
    if ($null -eq $prefix) {
        throw "The key does not start with a supported OpenAI key prefix; nothing changed."
    }

    foreach ($character in $plainKey.ToCharArray()) {
        if ([char]::IsWhiteSpace($character) -or [char]::IsControl($character)) {
            throw "The key contains whitespace or control characters; nothing changed."
        }
    }

    $remainder = $plainKey.Substring($prefix.Length)
    $repeated = $remainder.Contains("sk-proj-") -or $remainder.Contains("sk-svcacct-")
    if ($prefix -eq "sk-" -and $remainder.Contains("sk-")) {
        $repeated = $true
    }
    if ($repeated) {
        throw "The key appears to have been pasted more than once; nothing changed."
    }

    $plainKey | & $sshPath -i $identityPath -o BatchMode=yes -o StrictHostKeyChecking=no $remoteTarget $remoteHelper
    if ($LASTEXITCODE -ne 0) {
        throw "Production secret configuration failed; nothing was printed or stored locally."
    }
    if ($Gui) {
        [System.Windows.Forms.MessageBox]::Show(
            "OPENAI_API_KEY=configured",
            "Completed",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
}
finally {
    $OutputEncoding = $previousOutputEncoding
    [Console]::OutputEncoding = $previousConsoleOutputEncoding
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainKey = $null
    $secureKey = $null
}
