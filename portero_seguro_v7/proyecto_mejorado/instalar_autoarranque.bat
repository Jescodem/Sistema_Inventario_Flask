@echo off
:: =====================================================================
::  Hace que Portero Seguro (servidor + proxy) ARRANQUE SOLO al iniciar
::  sesion en Windows, sin tener que hacer doble clic en lanzar.bat.
::  Crea una tarea que ejecuta lanzar.bat al iniciar sesion, con permisos
::  de administrador (para el firewall/hosts) sin mostrar el aviso UAC.
:: =====================================================================
title Portero Seguro - Instalar autoarranque

:: --- Elevar a administrador (necesario para crear tarea con privilegios) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set "TAREA=PorteroSeguro_Servidor"

echo.
echo  Creando tarea "%TAREA%" (arranque al iniciar sesion)...
echo.
schtasks /create /tn "%TAREA%" /tr "\"%~dp0lanzar.bat\"" /sc ONLOGON /rl HIGHEST /f

if %errorlevel% equ 0 (
    echo.
    echo  [OK] Autoarranque instalado. La proxima vez que inicies sesion en
    echo       Windows, el servidor se levantara solo en una ventana.
    echo       - Probar ahora:   schtasks /run /tn "%TAREA%"
    echo       - Quitarlo:       ejecuta desinstalar_autoarranque.bat
) else (
    echo.
    echo  [!] No se pudo crear la tarea.
)
echo.
pause
