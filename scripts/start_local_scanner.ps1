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
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $outLog = Join-Path $LogDir ("scanner-" + $stamp + ".out.log")
    $errLog = Join-Path $LogDir ("scanner-" + $stamp + ".err.log")
    Write-Log ("Launching main.py (out=" + $outLog + ")")
    $p = Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $Root -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-Log ("Scanner exited with code " + $p.ExitCode + " - restarting in 30s")
    Start-Sleep -Seconds 30
}
