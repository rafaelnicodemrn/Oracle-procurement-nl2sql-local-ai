@echo off
rem Confere se o Ollama esta rodando e gera um SQL de exemplo (nao acessa o Oracle)
cd /d "%~dp0.."
.venv\Scripts\python.exe src\llm.py %*
pause
