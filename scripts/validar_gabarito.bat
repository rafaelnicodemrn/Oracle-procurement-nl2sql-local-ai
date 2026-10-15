@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe avaliacao\validar_gabarito.py %*
pause
