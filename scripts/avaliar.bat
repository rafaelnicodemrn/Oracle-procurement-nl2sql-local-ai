@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe avaliacao\avaliar.py %*
pause
