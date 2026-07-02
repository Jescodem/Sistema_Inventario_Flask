@echo off
setlocal
title Portero Seguro - Configurar equipo CLIENTE (opcional)
color 0F

:: =====================================================================
::  FALLBACK opcional. Solo necesario si tu router NO permite anadir una
::  entrada DNS local. Si la anadiste en el router, NO hace falta ejecutar
::  esto en ningun equipo.
::
::  Que hace: registra el nombre del dominio en el archivo hosts de ESTE
::  equipo para que apunte a la IP del servidor. (Es HTTP, sin certificado,
::  asi que no instala nada mas.)
::
::  Uso:  configurar_cliente.bat 192.168.18.137
::        (o ejecutalo sin argumentos y te pedira la IP del servidor)
::
::  Alternativa sin tocar nada: entra directamente por la IP del servidor,
::  por ejemplo  http://192.168.18.137
:: =====================================================================

:: --- Elevar a administrador -------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '%*'"
    exit /b
)

cd /d "%~dp0"
set "DOMINIO=inventario.porteroseguro.com"

echo.
echo  +----------------------------------------------------------+
echo  ^|   Portero Seguro - Configurar equipo CLIENTE           ^|
echo  +----------------------------------------------------------+
echo.

:: --- IP del servidor ---------------------------------------------------
set "SERVIDOR_IP=%~1"
if "%SERVIDOR_IP%"=="" (
    set /p SERVIDOR_IP=  Escribe la IP del servidor ^(ej. 192.168.18.137^):
)
if "%SERVIDOR_IP%"=="" (
    color 4F
    echo  ERROR: no se indico ninguna IP. Cancelado.
    pause
    exit /b 1
)

:: --- Archivo hosts -----------------------------------------------------
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
findstr /I /C:"%DOMINIO%" "%HOSTS%" >nul 2>&1
if %errorlevel% neq 0 (
    >> "%HOSTS%" echo %SERVIDOR_IP%    %DOMINIO%
    echo  [OK] hosts: %DOMINIO% -^> %SERVIDOR_IP%
) else (
    echo  [i]  %DOMINIO% ya existe en el archivo hosts.
    echo       Si la IP del servidor cambio, editalo manualmente:
    echo       %HOSTS%
)

echo.
echo  --------------------------------------------------------------
echo   Listo. Abre en el navegador:  http://%DOMINIO%
echo  --------------------------------------------------------------
echo.
pause
