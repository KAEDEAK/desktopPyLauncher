@echo off
setlocal

set "DATA_FOLDER=%USERPROFILE%\Documents\desktopPyLauncherDATA"
set "USER_PROJECT=%DATA_FOLDER%\default.json"

if not exist "%DATA_FOLDER%" (
    echo Error: desktopPyLauncherDATA folder not found in Documents
    echo Please run install.bat first to set up the application
    pause
    exit /b 1
)

if not exist "%USER_PROJECT%" (
    echo Error: default.json not found in %DATA_FOLDER%
    echo Please run install.bat first to set up the application
    pause
    exit /b 1
)

if exist "desktopPyLauncher.py" (
    python desktopPyLauncher.py -file "%USER_PROJECT%"
) else (
    echo Error: desktopPyLauncher.py not found in current directory
    pause
    exit /b 1
)

pause