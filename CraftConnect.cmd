@echo off
setlocal
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0craftconnect.py" %*
) else (
    start "" python "%~dp0craftconnect.py" %*
)
