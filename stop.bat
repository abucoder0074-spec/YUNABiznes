@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%run.ps1" -Action Stop
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo YUNABiznes stop reported an error. Review logs\startup.log.
)
echo.
pause
exit /b %EXIT_CODE%
