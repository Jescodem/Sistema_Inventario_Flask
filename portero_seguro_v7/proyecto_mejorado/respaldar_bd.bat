@echo off
:: =====================================================================
::  Respaldo MANUAL de la base de datos de Portero Seguro.
::  Doble clic para crear una copia ahora mismo.
::  (El respaldo automatico diario lo hace la tarea programada, que llama
::   directamente a python respaldar_bd.py; ver programar_respaldo.bat.)
::
::  Los respaldos se guardan en backups\ con fecha y hora. Historial en
::  backups\respaldo.log. Se conservan los ultimos 30 dias.
:: =====================================================================
title Portero Seguro - Respaldo de base de datos
cd /d "%~dp0"

python respaldar_bd.py

echo.
echo  --------------------------------------------------------------
if %errorlevel% equ 0 (
    echo   Respaldo completado. Historial en backups\respaldo.log
) else (
    echo   ATENCION: el respaldo fallo. Revisa el mensaje de arriba.
)
echo  --------------------------------------------------------------
echo.
pause
