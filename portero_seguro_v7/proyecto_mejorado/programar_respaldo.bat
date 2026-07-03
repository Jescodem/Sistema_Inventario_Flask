@echo off
:: =====================================================================
::  Programa el RESPALDO AUTOMATICO diario de la base de datos.
::  Crea una tarea de Windows que ejecuta respaldar_bd.py cada dia.
::  Corre como tu usuario cuando la sesion esta iniciada (no necesita
::  administrador). Para respaldo aunque nadie inicie sesion, habria que
::  usar la cuenta SYSTEM (ver nota al final).
:: =====================================================================
title Portero Seguro - Programar respaldo diario
cd /d "%~dp0"

set "HORA=20:00"
set "TAREA=PorteroSeguro_Respaldo"

echo.
echo  Creando tarea "%TAREA%" (respaldo diario a las %HORA%)...
echo.
schtasks /create /tn "%TAREA%" /tr "python \"%~dp0respaldar_bd.py\"" /sc DAILY /st %HORA% /f

if %errorlevel% equ 0 (
    echo.
    echo  [OK] Respaldo automatico programado todos los dias a las %HORA%.
    echo       - Cambiar la hora:  edita la variable HORA arriba y vuelve a ejecutar.
    echo       - Ejecutar ahora:   schtasks /run /tn "%TAREA%"
    echo       - Quitarlo:         schtasks /delete /tn "%TAREA%" /f
) else (
    echo.
    echo  [!] No se pudo crear la tarea. Intenta con clic derecho ^>
    echo      "Ejecutar como administrador".
)
echo.
pause
