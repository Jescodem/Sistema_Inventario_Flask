@echo off
title Portero Seguro - Sistema de Inventario
color 0F

echo.
echo  +----------------------------------------------------------+
echo  ^|   [PS]  PORTERO SEGURO                                   ^|
echo  ^|         Sistema de Control de Activos y Trazabilidad     ^|
echo  +----------------------------------------------------------+
echo.

cd /d "%~dp0"

:: --- Paso 1: Verificar Python ------------------------------------------
echo  [1/3]  Verificando Python...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 4F
    echo.
    echo  ERROR: Python no esta instalado o no esta en el PATH.
    echo.
    echo  Solucion:
    echo    1. Ve a https://www.python.org/downloads
    echo    2. Instala Python 3.10 o superior
    echo    3. Marca [x] Add Python to PATH durante la instalacion
    echo    4. Reinicia y vuelve a abrir este archivo
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo         OK - %%v
echo.

:: --- Paso 2: Instalar dependencias -------------------------------------
echo  [2/3]  Verificando e instalando dependencias...
echo.

python -m pip install -r requirements.txt --disable-pip-version-check

echo.
echo         Dependencias listas.
echo.

:: --- Paso 3: Iniciar el servidor ---------------------------------------
echo  [3/3]  Iniciando servidor...
echo         En unos segundos apareceran la URL y las credenciales.
echo.
echo  --------------------------------------------------------------
echo.

python _portero_launcher.py

:: El servidor se detuvo
echo.
echo  +----------------------------------------------------------+
echo  ^|   Servidor detenido. Presiona cualquier tecla.          ^|
echo  +----------------------------------------------------------+
echo.
pause >nul
