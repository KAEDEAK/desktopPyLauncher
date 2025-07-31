@echo off
echo Testing Desktop PyLauncher TNG Modules...
echo.

cd /d "%~dp0"

echo Current directory: %CD%
echo.

echo Setting up Python path...
set PYTHONPATH=%CD%;%CD%\module;%CD%\module\test
echo PYTHONPATH: %PYTHONPATH%
echo.

echo === Testing DPyL_debug (pytest) ===
python -m pytest module\test\test_DPyL_debug.py -v --tb=short
echo.

echo === Manual testing (avoiding batch syntax issues) ===
python test_manual.py
echo.

echo Test batch completed.
echo.
pause