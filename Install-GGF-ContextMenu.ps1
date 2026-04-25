$ErrorActionPreference = "Stop"

$contextScript = Join-Path $PSScriptRoot "GGF-Context.ps1"
$iconPath = Join-Path $PSScriptRoot "ggf-menu\logo.ico"

$fileCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$contextScript`" `"%1`""
$backgroundCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$contextScript`" `"%V`""

function Set-GGFContextMenu {
    param(
        [string]$SubKey,
        [string]$Command
    )

    $shellKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($SubKey)
    $commandKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$SubKey\command")
    try {
        $shellKey.SetValue("", "GGF-Tray", [Microsoft.Win32.RegistryValueKind]::String)
        $shellKey.SetValue("Icon", $iconPath, [Microsoft.Win32.RegistryValueKind]::String)
        $commandKey.SetValue("", $Command, [Microsoft.Win32.RegistryValueKind]::String)
    }
    finally {
        if ($commandKey) { $commandKey.Close() }
        if ($shellKey) { $shellKey.Close() }
    }
}

Set-GGFContextMenu -SubKey "Software\Classes\*\shell\GGF-Tray" -Command $fileCommand
Set-GGFContextMenu -SubKey "Software\Classes\Directory\shell\GGF-Tray" -Command $fileCommand
Set-GGFContextMenu -SubKey "Software\Classes\Directory\Background\shell\GGF-Tray" -Command $backgroundCommand

Write-Host "GGF-Tray context menu installed."
