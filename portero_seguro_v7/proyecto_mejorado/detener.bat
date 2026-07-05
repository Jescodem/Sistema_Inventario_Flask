@echo off
:: =====================================================================
::  Detiene el servidor de Portero Seguro (Flask + proxy Caddy).
::  Util cuando arranca solo por autoarranque y no ves la ventana, o
::  para reiniciarlo limpio. No borra datos.
:: =====================================================================
title Portero Seguro - Detener servidor

:: El servidor se inicia con permisos de administrador, asi que para poder
:: detenerlo tambien hacen falta. Nos auto-elevamos.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  Deteniendo el proxy Caddy...
taskkill /f /im caddy.exe >nul 2>&1 && echo   [OK] Caddy detenido. || echo   [i]  Caddy no estaba corriendo.

echo.
echo  Deteniendo la aplicacion (puerto 5051)...
set "MATADO="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :5051 ^| findstr LISTENING') do (
    taskkill /f /pid %%p >nul 2>&1 && set "MATADO=1"
)
if defined MATADO ( echo   [OK] Aplicacion detenida. ) else ( echo   [i]  La aplicacion no estaba corriendo. )

echo.
echo  Servidor detenido. Para volver a iniciarlo: lanzar.bat
echo.
pause
