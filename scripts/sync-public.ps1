<#
.SYNOPSIS
    Sync the dev repo to the public-facing repo, driven by sync-public.json.

.DESCRIPTION
    What/where to copy is configured in sync-public.json. The script refuses
    to run if the dev repo path does not end in -dev.

.PARAMETER DryRun
    Preview what would be copied without writing anything.

.EXAMPLE
    .\scripts\sync-public.ps1
    .\scripts\sync-public.ps1 -DryRun
#>
param([switch]$DryRun)

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DevRoot    = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$ConfigPath = Join-Path $ScriptDir "sync-public.json"

# Refuse to run outside a *-dev repo
if (-not $DevRoot.TrimEnd('\').EndsWith('-dev')) {
    Write-Error "Must run from a *-dev repo. Current: $DevRoot"
    exit 1
}

if (-not (Test-Path $ConfigPath)) {
    Write-Error "Config not found: $ConfigPath"
    exit 1
}

# ── Load config ──────────────────────────────────────────────────────────────
$Config           = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$PublicRoot       = $Config.public_root
$CopyDirs         = @($Config.copy_dirs)
$CopyFiles        = @($Config.copy_files)
$ExcludePatterns  = @($Config.exclude_patterns)
$PrivatePaths     = @($Config.private_paths)

# ── Defense-in-depth: refuse to publish any private path ─────────────────────
function Test-PrivateName($name) {
    foreach ($p in $PrivatePaths) {
        if ($name -eq $p -or $name -eq ($p -replace '/', '\')) { return $true }
    }
    return $false
}

foreach ($entry in (@($CopyDirs) + @($CopyFiles))) {
    if (Test-PrivateName $entry) {
        Write-Error "Refusing to publish '$entry' — listed in private_paths. Aborting."
        exit 2
    }
}

Write-Host "Source : $DevRoot"
Write-Host "Target : $PublicRoot"
if ($DryRun) { Write-Host "(dry run - no files written)`n" }

if (-not $DryRun) {
    if (-not (Test-Path $PublicRoot)) {
        New-Item $PublicRoot -ItemType Directory -Force | Out-Null
    }
}

# Clean-slate: remove everything in the public repo except .git/ so stale
# files (no longer in sync-public.json) don't linger. Safety: refuses to
# wipe a folder that isn't an initialized git repo.
function Clear-PublicRoot($root) {
    if (-not (Test-Path $root)) { return }
    if (-not (Test-Path (Join-Path $root '.git'))) {
        Write-Error "Refusing to wipe '$root' - no .git/ found there. Set public_root to an initialized git repo."
        exit 3
    }
    Write-Host "`nClearing $root (preserving .git/)"
    Get-ChildItem $root -Force | Where-Object { $_.Name -ne '.git' } | ForEach-Object {
        if ($DryRun) {
            Write-Host "  would remove: $($_.Name)"
        } else {
            Remove-Item $_.FullName -Recurse -Force
        }
    }
}
Clear-PublicRoot $PublicRoot

$Copied = [System.Collections.Generic.List[string]]::new()

function Test-Excluded($path) {
    foreach ($pat in $ExcludePatterns) {
        if ($path -like "*$pat*") { return $true }
    }
    return $false
}

# Copy contents of $src into $dst, honoring exclude_patterns. $dst was
# already removed (along with everything else outside .git/) by
# Clear-PublicRoot above, so we just need to recreate it.
function Sync-Tree($src, $dst) {
    if (-not (Test-Path $src)) { return }
    if (-not $DryRun) {
        New-Item $dst -ItemType Directory -Force | Out-Null
    }
    Get-ChildItem $src -Recurse -File | Where-Object { -not (Test-Excluded $_.FullName) } | ForEach-Object {
        $rel  = $_.FullName.Substring($src.Length).TrimStart('\','/')
        $dest = Join-Path $dst $rel
        $script:Copied.Add($dest.Substring($PublicRoot.Length).TrimStart('\','/'))
        if (-not $DryRun) {
            $destDir = Split-Path $dest -Parent
            if (-not (Test-Path $destDir)) { New-Item $destDir -ItemType Directory -Force | Out-Null }
            Copy-Item $_.FullName $dest -Force
        }
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

# 1. copy_dirs
foreach ($d in $CopyDirs) {
    Sync-Tree (Join-Path $DevRoot $d) (Join-Path $PublicRoot $d)
}

# 2. copy_files (supports nested paths like .github\workflows\foo.yml)
foreach ($f in $CopyFiles) {
    $src = Join-Path $DevRoot $f
    if (Test-Path $src) {
        $Copied.Add($f)
        if (-not $DryRun) {
            $destPath = Join-Path $PublicRoot $f
            $destDir  = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) { New-Item $destDir -ItemType Directory -Force | Out-Null }
            Copy-Item $src $destPath -Force
        }
    }
}

Write-Host "`nCopied $($Copied.Count) file(s):"
$Copied | Sort-Object | ForEach-Object { Write-Host "  $_" }

if (-not $DryRun) {
    Write-Host "`nDone. Review changes in $PublicRoot before committing."
}
