@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\explorar.py %*
