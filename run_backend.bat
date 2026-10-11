@echo off
cd /d "%~dp0backend"
echo ===================================================
echo   Starting PatentLens AI Backend Server...
echo ===================================================
py main.py
if %ERRORLEVEL% NEQ 0 (
    "C:\Users\Asus\AppData\Local\Python\bin\python.exe" main.py
)
pause
