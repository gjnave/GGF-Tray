param(
    [string]$TargetPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

if ($TargetPath) {
    Set-Clipboard -Value $TargetPath
}

$trayLauncher = Join-Path $PSScriptRoot "GGF-Tray.bat"
$rootPath = $PSScriptRoot.ToLowerInvariant()
$trayRunning = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object {
        $cmd = ($_.CommandLine -replace "\\\\", "\").ToLowerInvariant()
        $cmd.Contains("ggf-tray.py") -and $cmd.Contains($rootPath)
    }

if (-not $trayRunning -and (Test-Path $trayLauncher)) {
    Start-Process -FilePath $trayLauncher -WorkingDirectory $PSScriptRoot
}
