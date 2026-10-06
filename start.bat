@echo off
cd /d "%~dp0"
if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY is not set.
  echo Run: setx OPENAI_API_KEY "your-api-key"
  pause
  exit /b 1
)
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"
python app.py
pause
