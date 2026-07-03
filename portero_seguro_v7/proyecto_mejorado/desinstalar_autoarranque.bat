@echo off
:: =====================================================================
::  Quita el autoarranque de Portero Seguro (creado por
::  instalar_autoarranque.bat). No borra nada de la aplicacion.
:: =====================================================================
title Portero Seguro - Desinstalar autoarranque

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "TAREA=PorteroSeguro_Servidor"
echo.
schtasks /delete /tn "%TAREA%" /f
if %errorlevel% equ 0 (
    echo  [OK] Autoarranque desinstalado. El servidor ya no se iniciara solo.
    echo       Podras seguir arrancandolo a mano con lanzar.bat.
) else (
    echo  [i]  No habia autoarranque instalado ^(o ya se habia quitado^).
)
echo.
pause
