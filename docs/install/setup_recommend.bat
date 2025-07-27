@echo on
chcp 65001
cd /d "%~dp0"

echo === Checking Python installation ===
where python
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    goto :err
)

echo === Checking pip availability ===
python -m pip --version
if errorlevel 1 (
    echo [ERROR] pip is not available. Please ensure pip is installed.
    goto :err
)

echo === Checking Git repository ===
if not exist "desktopPyLauncher\" (
    echo Cloning repository...
    git clone https://github.com/KAEDEAK/desktopPyLauncher
) else (
    echo Repository already exists. Skipping clone.
)

set "DATAFOLDER=desktopPyLauncherDATA"
set "TARGET=%DATAFOLDER%\default.json"
set "SOURCE=desktopPyLauncher\default.json"

echo === Preparing data folder ===
if not exist "%DATAFOLDER%\" (
    echo Creating folder %DATAFOLDER%
    mkdir "%DATAFOLDER%"
) else (
    echo [%DATAFOLDER%] already exists
)

echo === Ensuring default.json is present ===
if not exist "%SOURCE%" (
    echo [ERROR] Source file not found: %SOURCE%
    goto :err
)

if not exist "%TARGET%" (
    echo [%TARGET%] does not exist. Copying...
    copy /Y "%SOURCE%" "%TARGET%"
) else (
    for %%F in ("%TARGET%") do (
        if %%~zF==0 (
            echo [%TARGET%] is empty. Copying...
            copy /Y "%SOURCE%" "%TARGET%"
        ) else (
            echo [%TARGET%] already exists and is not empty.
        )
    )
)

echo === Installing Python dependencies ===
if exist "desktopPyLauncher\requirements.txt" (
    python -m pip install -r "desktopPyLauncher\requirements.txt"
) else (
    echo [WARNING] requirements.txt not found. Skipping pip install.
)

goto :end

:err
echo.
echo ❌ Please fix the above error before continuing.
goto :EOF

:end
echo.
echo ✅ Completed successfully.
timeout /t 3
