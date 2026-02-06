#!/usr/bin/env pwsh
# ============================================
# GRALPH Installer
# Usage: irm https://raw.githubusercontent.com/FacuVCanale/gralph/main/install.ps1 | iex
# ============================================

# Use Continue so git stderr doesn't terminate (PS 5.x treats it as error)
$ErrorActionPreference = "Continue"

$REPO = "https://github.com/FacuVCanale/gralph.git"
$INSTALL_DIR = Join-Path $HOME ".gralph"
$BIN_DIR = Join-Path $INSTALL_DIR "scripts\gralph"

Write-Host ""
Write-Host "  GRALPH Installer" -ForegroundColor Cyan
Write-Host "  ================" -ForegroundColor Cyan
Write-Host ""

# Check git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  [ERROR] git is required. Install from https://git-scm.com" -ForegroundColor Red
    exit 1
}

# Clone or update
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

# Add to user PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BIN_DIR*") {
    Write-Host "  Adding to PATH..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BIN_DIR", "User")
    $env:Path = "$env:Path;$BIN_DIR"
    Write-Host "  [OK] Added $BIN_DIR to user PATH" -ForegroundColor Green
} else {
    Write-Host "  [OK] Already in PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Done! Restart your terminal, then run:" -ForegroundColor Green
Write-Host ""
Write-Host "    gralph --help           # show usage" -ForegroundColor White
Write-Host "    gralph --update         # update gralph" -ForegroundColor White
Write-Host "    gralph --init           # install skills in current repo" -ForegroundColor White
Write-Host ""
