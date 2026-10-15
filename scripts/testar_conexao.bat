@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe src\bip_client.py %*
