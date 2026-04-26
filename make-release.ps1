$ErrorActionPreference = "Stop"

function Copy-DirectoryFiltered {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination
    )

    $excludeDirs = @(
        "\.git\",
        "\venv\",
        "\whisper_venv\",
        "\__pycache__\",
        "\BACKUP\",
        "\Hold App\",
        "\dist\",
        "\build\",
        "\buildbackup\",
        "\test\"
    )

    $excludeFiles = @(
        "app_search_log.txt",
        "auth_cache.json",
        "visualizer_state.json",
        "*.pyc",
        "*.pyo"
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    foreach ($item in (Get-ChildItem -Path $Source -Recurse -Force)) {
        $full = $item.FullName

        $excluded = $false
        foreach ($pattern in $excludeDirs) {
            if ($full -like "*$pattern*") { $excluded = $true; break }
        }
        if ($excluded) { continue }

        foreach ($pattern in $excludeFiles) {
            if ($item.Name -like $pattern) { $excluded = $true; break }
        }
        if ($excluded) { continue }

        $relative = $full.Substring($Source.Length).TrimStart("\")
        $target = Join-Path $Destination $relative

        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            continue
        }

        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $full -Destination $target -Force
    }
}

$root = "C:\GGF"
$releaseDir = Join-Path $root "release"
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$staging = Join-Path $releaseDir ("staging-" + $stamp)
$zipPath = Join-Path $releaseDir ("GGF-Tray-" + $stamp + ".zip")

if (-not (Test-Path $root)) {
    throw "Expected repo at C:\GGF"
}

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $staging | Out-Null
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

New-Item -ItemType Directory -Force -Path $staging | Out-Null

Copy-Item -LiteralPath (Join-Path $root "GGF-Tray.bat") -Destination $staging -Force
Copy-Item -LiteralPath (Join-Path $root "install-ggf-menu.bat") -Destination $staging -Force
Copy-Item -LiteralPath (Join-Path $root "cleanup.bat") -Destination $staging -Force
Copy-Item -LiteralPath (Join-Path $root "reset.bat") -Destination $staging -Force

if (Test-Path (Join-Path $root "Install-GGF-ContextMenu.ps1")) {
    Copy-Item -LiteralPath (Join-Path $root "Install-GGF-ContextMenu.ps1") -Destination $staging -Force
}
if (Test-Path (Join-Path $root "GGF-Context.ps1")) {
    Copy-Item -LiteralPath (Join-Path $root "GGF-Context.ps1") -Destination $staging -Force
}

Copy-DirectoryFiltered -Source (Join-Path $root "ggf-menu") -Destination (Join-Path $staging "ggf-menu")

# Ensure clean defaults (avoid distributing your local state)
Set-Content -Path (Join-Path $staging "ggf-menu\installed_apps.txt") -Value "" -Encoding UTF8
Set-Content -Path (Join-Path $staging "ggf-menu\shortcuts.txt") -Value "" -Encoding UTF8
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $staging "ggf-menu\app_search_log.txt")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $staging "ggf-menu\auth_cache.json")

$readme = @"
GGF-Tray Distribution

1. Unzip this folder anywhere (recommended: C:\GGF)
2. Run install-ggf-menu.bat
3. Tray starts via GGF-Tray.bat (also added to Startup)

Notes:
- Requires Python 3.10+ installed (python.org). The installer creates a venv in ggf-menu\venv.
- ffmpeg is recommended for video features (put ffmpeg in PATH).
- Explorer context menu is optional: run install-ggf-menu.bat --context-menu
"@

Set-Content -Path (Join-Path $staging "README-INSTALL.txt") -Value $readme -Encoding UTF8

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
Remove-Item -Recurse -Force $staging

Write-Host "Release zip created:"
Write-Host $zipPath
