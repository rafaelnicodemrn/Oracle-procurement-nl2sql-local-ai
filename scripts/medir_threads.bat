@echo off
rem Mede a velocidade da IA local com diferentes threads (nao acessa o Oracle)
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\medir_threads.py %*
if not defined SEM_PAUSA pause
