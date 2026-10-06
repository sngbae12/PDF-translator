@echo off
cd /d "%~dp0"

rem Use the .venv virtual environment if it exists, otherwise fall back to python on PATH.
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

rem The OpenAI API key is entered in the browser, so no environment variable is required.
echo Starting PDF translator with %PYTHON%
echo Open http://127.0.0.1:5000 in your browser. Close this window to stop the server.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"
"%PYTHON%" app.py
pause
