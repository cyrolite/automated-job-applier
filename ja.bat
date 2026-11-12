@echo off
REM Convenience wrapper so you can type `ja apply -f jd.txt` from this folder.
setlocal
set "PYTHONPATH=%~dp0src"
python -m job_applier %*
endlocal
