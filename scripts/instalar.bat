@echo off
cd /d "%~dp0.."
if exist .venv rmdir /s /q .venv
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Instalacao concluida. Confira o arquivo .env
pause
