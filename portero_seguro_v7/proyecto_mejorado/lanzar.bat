@echo off
setlocal enabledelayedexpansion
title Portero Seguro - Sistema de Inventario
color 0F

:: =====================================================================
::  Portero Seguro - Lanzador con proxy inverso HTTP (Caddy)
::  Acceso: http://inventario.porteroseguro.com   (o por IP)
::  Nota: HTTP sin cifrado, a proposito. Usar solo en red de confianza.
:: =====================================================================

:: --- Paso 0: Elevar a administrador -----------------------------------
::  Necesario para: editar el archivo hosts, abrir el firewall y que
::  Caddy pueda escuchar en el puerto 80.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Solicitando permisos de administrador...
    echo  ^(necesarios para el firewall y el dominio local^)
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

set "DOMINIO=inventario.porteroseguro.com"
set "XDG_DATA_HOME=%~dp0caddy_data"

echo.
echo  +----------------------------------------------------------+
echo  ^|   [PS]  PORTERO SEGURO                                   ^|
echo  ^|         Sistema de Control de Activos y Trazabilidad     ^|
echo  +----------------------------------------------------------+
echo.

:: --- Paso 1: Verificar Python ------------------------------------------
echo  [1/4]  Verificando Python...

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
echo  [2/4]  Verificando e instalando dependencias...
echo.

python -m pip install -r requirements.txt --disable-pip-version-check

echo.
echo         Dependencias listas.
echo.

:: --- Paso 3: Preparar el proxy inverso HTTP (Caddy) -------------------
echo  [3/4]  Preparando el proxy inverso ^(puerto 80^)...

:: 3a. Descargar Caddy la primera vez.
if not exist "caddy.exe" (
    echo         Descargando Caddy ^(solo la primera vez, ~40 MB^)...
    powershell -Command "try { Invoke-WebRequest -Uri 'https://caddyserver.com/api/download?os=windows&arch=amd64' -OutFile 'caddy.exe' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
    if not exist "caddy.exe" (
        color 4F
        echo.
        echo  ERROR: No se pudo descargar Caddy.
        echo         Revisa tu conexion a internet y vuelve a intentarlo.
        echo.
        pause
        exit /b 1
    )
    echo         Caddy descargado.
) else (
    echo         Caddy ya esta presente.
)

:: 3b. Registrar el dominio en el archivo hosts -> 127.0.0.1 (este equipo).
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
findstr /I /C:"%DOMINIO%" "%HOSTS%" >nul 2>&1
if %errorlevel% neq 0 (
    echo         Registrando %DOMINIO% en el archivo hosts...
    >> "%HOSTS%" echo 127.0.0.1    %DOMINIO%
) else (
    echo         %DOMINIO% ya esta en el archivo hosts.
)

:: 3c. Abrir el firewall para que la red local pueda conectarse (puerto 80).
::     Sin esto, Caddy escucha pero Windows bloquea las conexiones entrantes.
set "FW_NOMBRE=Portero Seguro (Caddy)"
netsh advfirewall firewall show rule name="%FW_NOMBRE%" >nul 2>&1
if %errorlevel% neq 0 (
    echo         Abriendo el firewall para la red local ^(puerto 80^)...
    netsh advfirewall firewall add rule name="%FW_NOMBRE%" dir=in action=allow protocol=TCP localport=80 profile=any >nul
) else (
    echo         Regla de firewall ya configurada.
)
echo.

:: --- Paso 4: Iniciar servidor + proxy ---------------------------------
echo  [4/4]  Iniciando servidor y proxy...
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
