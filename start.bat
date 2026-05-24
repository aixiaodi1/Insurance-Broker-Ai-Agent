@echo off
setlocal
chcp 65001 >nul

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%start-windows.ps1"
set "STATUS=%ERRORLEVEL%"

echo.
echo start-windows.ps1 exited with code %STATUS%
echo Press any key to close this window.
pause >nul
exit /b %STATUS%
