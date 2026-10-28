@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "QT_QPA_PLATFORM="
set "QT_SCALE_FACTOR="

pushd "%~dp0"
if errorlevel 1 goto directory_error

set "launcher_exit=0"
if not exist "main_fluent.py" goto entrypoint_error
set "launcher_python=%~dp0venv\Scripts\python.exe"
if not exist "%launcher_python%" set "launcher_python=%~dp0.venv\Scripts\python.exe"
if not exist "%launcher_python%" goto environment_error

if "%~1"=="" goto check_dependencies
if /i "%~1"=="--comprobar" goto check_dependencies
echo Uso: arrancar_ordenasion.bat [--comprobar]
set "launcher_exit=2"
goto finish

:check_dependencies
"%launcher_python%" -B -c "import PyQt6.QtCore, PyQt6.QtWidgets, PyQt6.QtMultimedia, qfluentwidgets, psutil, send2trash, mutagen; import sys; __import__('wmi') if sys.platform == 'win32' else None"
set "launcher_exit=%errorlevel%"
if not "%launcher_exit%"=="0" goto dependencies_error
if /i "%~1"=="--comprobar" goto check_success

"%launcher_python%" "%~dp0main_fluent.py"
set "launcher_exit=%errorlevel%"
if not "%launcher_exit%"=="0" echo Ordenasion terminó con un error. Revisa el mensaje anterior.
goto finish

:check_success
echo Comprobación correcta: main_fluent.py y dependencias disponibles.
goto finish

:entrypoint_error
echo No se encontró main_fluent.py junto a este lanzador.
echo Conserva el lanzador en la carpeta raíz de Ordenasion.
set "launcher_exit=2"
goto finish

:environment_error
echo No se encontró Python en venv ni en .venv.
echo Prepara un entorno virtual desde esta carpeta y sus dependencias:
echo   py -3 -m venv venv
echo   venv\Scripts\python.exe -m pip install -r requirements.txt
echo El lanzador no instalará nada automáticamente.
set "launcher_exit=3"
goto finish

:dependencies_error
echo Faltan dependencias o el entorno virtual no funciona.
echo Para instalar los requisitos en el entorno seleccionado:
echo   "%launcher_python%" -m pip install -r "%~dp0requirements.txt"
goto finish

:finish
popd
if not "%launcher_exit%"=="0" pause
endlocal & exit /b %launcher_exit%

:directory_error
echo No se pudo abrir la carpeta del lanzador.
pause
endlocal & exit /b 2
