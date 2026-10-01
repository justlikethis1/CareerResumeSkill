@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3.11 or newer is required. Install Python, then open this file again.
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 goto setup_failed
)

".venv\Scripts\python.exe" -c "import career_resume_skill, starlette, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
    echo First launch: installing the application and its Python dependencies...
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto setup_failed
)

".venv\Scripts\python.exe" -m career_resume_skill.web_app
if errorlevel 1 goto launch_failed
exit /b 0

:setup_failed
echo Setup did not complete. Check your Python installation and internet connection.
pause
exit /b 1

:launch_failed
echo The local application stopped. Review the message above.
pause
exit /b 1