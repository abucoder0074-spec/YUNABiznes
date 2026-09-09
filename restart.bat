@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%run.ps1" -Action Restart
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo YUNABiznes failed to restart. Review the error above and logs\startup.log.
)
echo.
pause
exit /b %EXIT_CODE%
