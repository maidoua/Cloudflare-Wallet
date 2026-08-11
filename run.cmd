@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "checker_exit_code=%ERRORLEVEL%"

echo.
if not "%checker_exit_code%"=="0" (
    echo The checker stopped with exit code %checker_exit_code%.
)
echo Press any key to close this window.
pause >nul

exit /b %checker_exit_code%
