@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Radar de Licitaciones CV

echo ============================================
echo   RADAR DE LICITACIONES - COMUNITAT VALENCIANA
echo ============================================
echo.
echo Preparando la herramienta. No cierres esta ventana.
echo.

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo Python no esta instalado. Intentando instalarlo automaticamente...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo.
    echo No se ha podido instalar Python automaticamente.
    echo Instala Python desde Microsoft Store y vuelve a hacer doble clic en este archivo.
    echo.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo La instalacion automatica de Python no se ha completado.
    echo Instala Python desde Microsoft Store y vuelve a intentarlo.
    pause
    exit /b 1
  )
  set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
  if exist "%PYEXE%" (
    set "PYTHON_CMD=\"%PYEXE%\""
  ) else (
    where python >nul 2>nul && set "PYTHON_CMD=python"
    where py >nul 2>nul && set "PYTHON_CMD=py -3"
  )
)

if not defined PYTHON_CMD (
  echo No se encuentra Python despues de la instalacion.
  echo Reinicia Windows y vuelve a hacer doble clic en ABRIR_RADAR.bat
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creando el entorno de la aplicacion...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

echo Instalando o actualizando componentes necesarios...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Abriendo Radar de Licitaciones en tu navegador...
echo Cuando quieras cerrar la herramienta, cierra esta ventana negra.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
exit /b 0

:error
echo.
echo Ha ocurrido un problema al preparar la herramienta.
echo Haz una captura de esta ventana y compartemela para que pueda corregirlo.
echo.
pause
exit /b 1
