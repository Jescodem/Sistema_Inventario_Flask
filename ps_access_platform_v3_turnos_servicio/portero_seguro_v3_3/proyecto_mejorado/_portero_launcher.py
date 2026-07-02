"""
_portero_launcher.py
Lanzador interno de Portero Seguro.

Lee el stdout de app.py linea a linea, extrae las credenciales
del administrador inicial, y muestra un banner con URL + credenciales
en el momento exacto en que Flask esta listo para recibir conexiones.

No edites este archivo a menos que sepas lo que haces.
Se invoca automaticamente desde lanzar.bat.
"""
import subprocess
import sys
import os
import socket

# ── Detectar IP local de la maquina ──────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# ── Entorno del servidor ──────────────────────────────────────────────────────
env = os.environ.copy()
env['FLASK_HOST']  = '0.0.0.0'      # accesible desde toda la red local
env['FLASK_PORT']  = '5051'
env['FLASK_DEBUG'] = 'false'

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))

# ── Iniciar Flask como subproceso ─────────────────────────────────────────────
proc = subprocess.Popen(
    [sys.executable, 'app.py'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding='utf-8',
    errors='replace',
    env=env,
    cwd=DIRECTORIO
)

creds        = {'user': 'admin', 'pass': None}
banner_shown = False
SEP          = '=' * 58
SEP_THIN     = '-' * 58

try:
    for linea in proc.stdout:
        sys.stdout.write(linea)
        sys.stdout.flush()

        stripped = linea.strip()

        # Capturar credenciales del primer arranque
        if 'Contrasena:' in stripped:
            partes = stripped.split()
            if partes:
                creds['pass'] = partes[-1]
        if stripped.startswith('Usuario:') and 'Contrasena' not in stripped:
            partes = stripped.split()
            if partes:
                creds['user'] = partes[-1]

        # Cuando Flask esta listo, mostrar el banner
        if 'Running on' in stripped and not banner_shown:
            banner_shown = True
            ip   = get_local_ip()
            port = env.get('FLASK_PORT', '5051')

            print()
            print(f'  {SEP}')
            print(f'  {"PORTERO SEGURO  -  SERVIDOR ACTIVO":^58}')
            print(f'  {SEP}')
            print(f'  {"Este equipo:":<16} http://localhost:{port}')
            print(f'  {"Red local:":<16} http://{ip}:{port}')
            if creds.get('pass'):
                print(f'  {SEP_THIN}')
                print(f'  {"Credenciales iniciales del administrador":^58}')
                print(f'  {SEP_THIN}')
                print(f'  {"Usuario:":<16} {creds["user"]}')
                print(f'  {"Contrasena:":<16} {creds["pass"]}')
                print(f'  {"":2}Cambia esta contrasena al primer ingreso.')
            else:
                print(f'  {SEP_THIN}')
                print(f'  {"":2}El administrador ya existe en la base de datos.')
                print(f'  {"":2}Usa tus credenciales habituales para ingresar.')
            print(f'  {SEP}')
            print(f'  Presiona Ctrl+C para detener el servidor.')
            print()

    proc.wait()

except KeyboardInterrupt:
    proc.terminate()
    print()
    print(f'  {SEP}')
    print(f'  Servidor detenido por el usuario.')
    print(f'  {SEP}')
    print()
