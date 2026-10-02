$ErrorActionPreference = "Stop"

$sshPath = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$identityPath = Join-Path $env:USERPROFILE ".ssh\codex_vps_key"
$remoteTarget = "root@165.232.68.212"
$remoteHelper = "/opt/ai-outreach-system/tools/configure_openai_discovery_secret.sh"
$key = (Get-Clipboard -Raw).Trim("`r", "`n")

if ([string]::IsNullOrWhiteSpace($key) -or -not $key.StartsWith("sk-")) {
    throw "Clipboard does not contain an OpenAI key. Copy the new key first; nothing changed."
}
if ($key -match "\s") {
    throw "Clipboard key contains whitespace. Copy it again; nothing changed."
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $sshPath
$psi.Arguments = "-i `"$identityPath`" -o BatchMode=yes -o StrictHostKeyChecking=no $remoteTarget $remoteHelper"
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$process = [System.Diagnostics.Process]::Start($psi)

try {
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($key + "`n")
    $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $process.StandardInput.Close()
    $output = $process.StandardOutput.ReadToEnd()
    $errorOutput = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0 -or $output -notmatch "OPENAI_API_KEY=configured") {
        throw "Key was not saved. $errorOutput"
    }
    Set-Clipboard -Value ""
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "OPENAI_API_KEY=configured`nClipboard cleared.",
        "Completed",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}
finally {
    $key = $null
}
