@echo off
chcp 65001

if exist "desktopPyLauncher\" (
    call :UpdateRepo
) else (
    echo Directory "desktopPyLauncher" does not exist. Skipping update.
)

goto :end

:UpdateRepo
echo.
echo Starting git fetch...
echo Updating the code. Any local changes will be lost.
echo Press CTRL+C now to cancel if you want to keep your changes.
timeout /t 15
echo Updating code from GitHub...
cd desktopPyLauncher
git fetch origin
git reset --hard origin/main
cd ..

goto :EOF

:end
echo Finished update process.
timeout /t 3
