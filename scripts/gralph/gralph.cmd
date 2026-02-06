@echo off
setlocal

:: Find PowerShell 7 (pwsh) first, fall back to Windows PowerShell 5.x
where pwsh >nul 2>&1
if %errorlevel% equ 0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0gralph.ps1" %*
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0gralph.ps1" %*
)

exit /b %errorlevel%
