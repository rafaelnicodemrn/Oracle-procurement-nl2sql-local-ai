@echo off
rem Sobe o Ollama num container Docker e baixa o modelo.
rem Alternativa para maquinas em que o instalador do Ollama nao pode ser usado.
rem Uso: scripts\iniciar_ollama_docker.bat [modelo]   padrao: qwen2.5-coder:3b
setlocal
set "MODELO=%~1"
if "%MODELO%"=="" set "MODELO=qwen2.5-coder:3b"

docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
echo Iniciando o Docker Desktop...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
for /l %%i in (1,1,60) do (
  ping -n 4 127.0.0.1 >nul
  docker info >nul 2>&1 && goto docker_ok
)
echo Docker nao respondeu. Abra o Docker Desktop e rode este atalho de novo.
goto fim

:docker_ok
docker container inspect ollama >nul 2>&1
if errorlevel 1 goto criar
echo Iniciando o container ollama...
docker start ollama >nul
goto aguardar

:criar
echo Criando o container ollama, porta 11434 acessivel so nesta maquina...
docker run -d --name ollama --restart unless-stopped -p 127.0.0.1:11434:11434 -v ollama:/root/.ollama ollama/ollama
if errorlevel 1 goto fim

:aguardar
ping -n 6 127.0.0.1 >nul
echo Baixando o modelo %MODELO%...
docker exec ollama ollama pull %MODELO%
if errorlevel 1 goto fim
docker exec ollama ollama list
echo.
echo Ollama pronto em http://127.0.0.1:11434

:fim
if not defined SEM_PAUSA pause
endlocal
