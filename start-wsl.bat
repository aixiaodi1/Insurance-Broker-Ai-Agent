@echo off
setlocal
chcp 65001 >nul

set "WINDOWS_PROJECT_DIR=%~dp0"
set "DRIVE_LETTER=%WINDOWS_PROJECT_DIR:~0,1%"
set "PATH_AFTER_DRIVE=%WINDOWS_PROJECT_DIR:~3%"
set "PATH_AFTER_DRIVE=%PATH_AFTER_DRIVE:\=/%"

if /I "%DRIVE_LETTER%"=="A" set "DRIVE_LETTER=a"
if /I "%DRIVE_LETTER%"=="B" set "DRIVE_LETTER=b"
if /I "%DRIVE_LETTER%"=="C" set "DRIVE_LETTER=c"
if /I "%DRIVE_LETTER%"=="D" set "DRIVE_LETTER=d"
if /I "%DRIVE_LETTER%"=="E" set "DRIVE_LETTER=e"
if /I "%DRIVE_LETTER%"=="F" set "DRIVE_LETTER=f"
if /I "%DRIVE_LETTER%"=="G" set "DRIVE_LETTER=g"

set "WSL_PROJECT_DIR=/mnt/%DRIVE_LETTER%/%PATH_AFTER_DRIVE%"

if "%WSL_PROJECT_DIR%"=="" (
  echo Failed to resolve this project path inside WSL.
  echo Windows path: %WINDOWS_PROJECT_DIR%
  pause
  exit /b 1
)

echo Starting RAG backend in WSL...
echo Project: %WSL_PROJECT_DIR%
echo.

if "%START_WSL_DRY_RUN%"=="1" (
  echo Dry run only. Command not started.
  exit /b 0
)

wsl.exe --cd "%WSL_PROJECT_DIR%" -- bash -lc "chmod +x ./start.sh && ./start.sh; status=$?; echo; echo start.sh exited with code $status; echo Press Enter to close this window.; read; exit $status"

endlocal
