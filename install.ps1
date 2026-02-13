#!/usr/bin/env pwsh
# ============================================
# GRALPH Installer (Windows)
# Usage: irm https://raw.githubusercontent.com/FacuVCanale/gralph/main/install.ps1 | iex
# ============================================

$ErrorActionPreference = "Continue"

$REPO = "https://github.com/FacuVCanale/gralph.git"
$INSTALL_DIR = Join-Path $HOME ".gralph"
$MIN_PYTHON = "3.10"

Write-Host ""
Write-Host "  GRALPH Installer" -ForegroundColor Cyan
Write-Host "  ================" -ForegroundColor Cyan
Write-Host ""

# ── Check git ───────────────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  [ERROR] git is required. Install from https://git-scm.com" -ForegroundColor Red
    exit 1
}

# ── Check Python 3.10+ ─────────────────────────────────────────────
$Python = $null
foreach ($candidate in @("python3", "python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $pyVersion = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($pyVersion) {
                $parts = $pyVersion.Split(".")
                $major = [int]$parts[0]
                $minor = [int]$parts[1]
                if ($major -ge 3 -and $minor -ge 10) {
                    $Python = $candidate
                    break
                }
            }
        } catch {}
    }
}

if (-not $Python) {
    Write-Host "  [ERROR] Python $MIN_PYTHON+ is required." -ForegroundColor Red
    Write-Host "  Install from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [OK] Found $Python ($pyVersion)" -ForegroundColor Green

# ── Ensure pipx ────────────────────────────────────────────────────
$hasPipx = Get-Command pipx -ErrorAction SilentlyContinue
if (-not $hasPipx) {
    Write-Host "  Installing pipx..." -ForegroundColor Yellow
    & $Python -m pip install --user pipx 2>$null | Out-Null
    & $Python -m pipx ensurepath 2>$null | Out-Null

    # Refresh PATH for this session
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$userPath;$machinePath"

    $hasPipx = Get-Command pipx -ErrorAction SilentlyContinue
    if (-not $hasPipx) {
        Write-Host "  [WARN] pipx installed but not in PATH yet." -ForegroundColor Yellow
        Write-Host "  Restart your terminal and run this installer again." -ForegroundColor Yellow
        exit 1
    }
}
Write-Host "  [OK] Found pipx" -ForegroundColor Green

# ── Clone or update repo ──────────────────────────────────────────
if (Test-Path (Join-Path $INSTALL_DIR ".git")) {
    Write-Host "  Updating existing installation..." -ForegroundColor Yellow
    & git -C $INSTALL_DIR pull --ff-only 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN] git pull failed, resetting..." -ForegroundColor Yellow
        & git -C $INSTALL_DIR fetch origin 2>$null | Out-Null
        & git -C $INSTALL_DIR reset --hard origin/main 2>$null | Out-Null
    }
    Write-Host "  [OK] Updated" -ForegroundColor Green
} else {
    if (Test-Path $INSTALL_DIR) { Remove-Item $INSTALL_DIR -Recurse -Force }
    Write-Host "  Cloning gralph to $INSTALL_DIR ..." -ForegroundColor Yellow
    & git clone --depth 1 $REPO $INSTALL_DIR 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] git clone failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Cloned" -ForegroundColor Green
}

# ── Install Python package via pipx ───────────────────────────────
Write-Host "  Installing gralph CLI via pipx..." -ForegroundColor Yellow
& pipx install $INSTALL_DIR --force 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] pipx install failed." -ForegroundColor Red
    Write-Host "  Try manually: pipx install $INSTALL_DIR" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [OK] Installed" -ForegroundColor Green

Write-Host ""
Write-Host "  Done! Restart your terminal, then run:" -ForegroundColor Green
Write-Host ""
Write-Host "    gralph --help           # show usage" -ForegroundColor White
Write-Host "    gralph --update         # update gralph" -ForegroundColor White
Write-Host "    gralph --init           # install skills in current repo" -ForegroundColor White
Write-Host ""
