@echo off
cd /d "%~dp0"
rem Abre o navegador so depois que /health responder (ate 30 tentativas, 1 por segundo)
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health | Out-Null; Start-Process http://127.0.0.1:8000; break}catch{Start-Sleep -Seconds 1}}"
.venv\Scripts\python.exe -m uvicorn app:app --app-dir src --host 127.0.0.1 --port 8000
