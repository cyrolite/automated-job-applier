@echo off
REM One-time setup. Run this once by double-clicking it, or from a terminal.
setlocal
cd /d "%~dp0"

echo Creating a virtual environment...
python -m venv .venv || goto :fail

echo Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt || goto :fail

echo.
echo Checking setup...
set "PYTHONPATH=%~dp0src"
python -m job_applier init

echo.
echo Done. From now on, in this folder:
echo    .venv\Scripts\activate
echo    ja score -f jd.txt
echo.
pause
exit /b 0

:fail
echo.
echo Setup failed. Is Python installed and on your PATH?
echo Check with:  python --version
pause
exit /b 1
