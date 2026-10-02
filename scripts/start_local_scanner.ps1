# Always-on local Facebook Marketplace scanner for this PC.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Missing venv python at $Python"
    exit 1
}

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "local-scanner.log"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line
}

Write-Log "Starting local marketplace scanner"

while ($true) {
    $ErrorActionPreference = "Continue"
    $p = Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $Root -PassThru -Wait -NoNewWindow -RedirectStandardOutput $LogFile -RedirectStandardError (Join-Path $LogDir "local-scanner.err.log")
    Write-Log ("Scanner exited with code {0} - restarting in 30s" -f $p.ExitCode)
    Start-Sleep -Seconds 30
}
