@echo off
setlocal

set "DATA_FOLDER=%USERPROFILE%\Documents\desktopPyLauncherDATA"

if not exist "%DATA_FOLDER%" (
    mkdir "%DATA_FOLDER%"
    echo Created folder: %DATA_FOLDER%
)

if exist "default.json" (
    copy "default.json" "%DATA_FOLDER%\"
    echo Copied default.json to %DATA_FOLDER%
) else (
    echo Error: default.json not found in current directory
    pause
    exit /b 1
)

if exist "desktopPyLauncher.py" (
    python desktopPyLauncher.py -file "%DATA_FOLDER%\default.json"
) else (
    echo Error: desktopPyLauncher.py not found in current directory
    pause
    exit /b 1
)

pause