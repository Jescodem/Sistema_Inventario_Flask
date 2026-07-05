@echo off
:: =====================================================================
::  Reinicia el servidor de Portero Seguro:
::  detiene cualquier instancia anterior (Caddy + Flask) y lo arranca
::  de nuevo DESDE ESTA carpeta. Util tras actualizar o si quedo colgado.
:: =====================================================================
title Portero Seguro - Reiniciar servidor

:: Auto-elevacion (el servidor corre con privilegios de administrador).
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Solicitando permisos de administrador...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo  Deteniendo cualquier servidor anterior...
taskkill /f /im caddy.exe >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :5051 ^| findstr LISTENING') do taskkill /f /pid %%p >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo  Iniciando el servidor desde esta carpeta...
echo.
call "%~dp0lanzar.bat"
