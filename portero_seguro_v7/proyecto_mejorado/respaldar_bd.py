"""
respaldar_bd.py - Respaldo seguro de la base de datos de Portero Seguro.

Usa la API de backup EN CALIENTE de SQLite (conn.backup), que produce una
copia consistente aunque la aplicacion este en uso, a diferencia de copiar
el archivo a mano. Guarda la copia con fecha en la carpeta backups/ y rota:
conserva los respaldos de los ultimos BACKUP_RETENCION_DIAS dias.

Uso manual:   python respaldar_bd.py
Programado:   lo invoca respaldar_bd.bat (ver programar_respaldo.bat).
"""
import os
import sqlite3
import glob
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGEN   = os.environ.get('PORTERO_DB', os.path.join(BASE_DIR, 'inventario.db'))
DEST_DIR = os.path.join(BASE_DIR, 'backups')
LOG      = os.path.join(DEST_DIR, 'respaldo.log')
RETENCION_DIAS = int(os.environ.get('BACKUP_RETENCION_DIAS', '30'))


def log(mensaje):
    """Muestra el mensaje por pantalla y lo anexa al historial de respaldos."""
    print(mensaje)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(mensaje + '\n')
    except OSError:
        pass


def main():
    os.makedirs(DEST_DIR, exist_ok=True)

    if not os.path.exists(ORIGEN):
        log(f'ERROR: no existe la base de datos: {ORIGEN}')
        return 1
    sello   = datetime.now().strftime('%Y%m%d_%H%M%S')
    destino = os.path.join(DEST_DIR, f'inventario_{sello}.db')

    # Copia consistente en caliente (no corrompe si la app esta escribiendo).
    src = sqlite3.connect(ORIGEN)
    dst = sqlite3.connect(destino)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    tam_kb = os.path.getsize(destino) // 1024
    log(f'[{sello}] Respaldo creado: {destino} ({tam_kb} KB)')

    # Rotacion: eliminar respaldos mas viejos que RETENCION_DIAS.
    limite = time.time() - RETENCION_DIAS * 86400
    borrados = 0
    for f in glob.glob(os.path.join(DEST_DIR, 'inventario_*.db')):
        if os.path.getmtime(f) < limite:
            try:
                os.remove(f)
                borrados += 1
            except OSError:
                pass
    if borrados:
        log(f'Rotacion: {borrados} respaldo(s) de mas de {RETENCION_DIAS} dias eliminados.')

    total = len(glob.glob(os.path.join(DEST_DIR, 'inventario_*.db')))
    log(f'Respaldos disponibles ahora: {total}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
