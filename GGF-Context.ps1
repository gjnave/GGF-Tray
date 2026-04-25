param(
    [string]$TargetPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

if ($TargetPath) {
    Set-Clipboard -Value $TargetPath
}

$trayLauncher = Join-Path $PSScriptRoot "GGF-Tray.bat"
if (Test-Path $trayLauncher) {
    Start-Process -FilePath $trayLauncher -WorkingDirectory $PSScriptRoot
}
