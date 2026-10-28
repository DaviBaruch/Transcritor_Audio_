@echo off
chcp 65001 >nul
set "PASTA=%~dp0"
cd /d "%PASTA%"
set "PYTHON=%PASTA%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Ambiente Python nao encontrado. Execute primeiro:
  echo   py -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Servidor de producao iniciado conforme TRANSCRITOR_HOST e TRANSCRITOR_PORT.
"%PYTHON%" servidor_producao.py
pause
