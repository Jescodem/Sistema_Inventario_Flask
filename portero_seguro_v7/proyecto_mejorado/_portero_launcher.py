"""
_portero_launcher.py
Lanzador interno de Portero Seguro.

Arranca DOS procesos y muestra un banner cuando todo esta listo:

  1. Caddy  -> proxy inverso HTTP en el puerto 80. Reenvia a Flask.
  2. Flask  -> la aplicacion (app.py), escuchando SOLO en local
               (127.0.0.1:5051); la unica cara publica es Caddy.

Despliegue HTTP (sin cifrado) a proposito: asi cualquier equipo de la
red local entra sin instalar certificados. Usar solo en red de confianza.

Lee el stdout de app.py linea a linea para capturar las credenciales del
administrador inicial y detectar el momento en que Flask esta listo.

Al pulsar Ctrl+C se detienen ambos procesos.

Se invoca automaticamente desde lanzar.bat, que ya se encarga de los
permisos de administrador, el archivo hosts, el firewall y de descargar
Caddy. No edites este archivo a menos que sepas lo que haces.
"""
import subprocess
import sys
import os
import socket

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
DOMINIO    = 'inventario.porteroseguro.com'
PUERTO_APP = '5051'

CADDY_EXE = os.path.join(DIRECTORIO, 'caddy.exe')
CADDYFILE = os.path.join(DIRECTORIO, 'Caddyfile')
LOG_DIR   = os.path.join(DIRECTORIO, 'logs')
CADDY_LOG = os.path.join(LOG_DIR, 'caddy.log')


# ── Detectar IP local de la maquina (la que ven los demas equipos) ───────────
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
env['FLASK_HOST']            = '127.0.0.1'   # solo local; Caddy es la cara publica
env['FLASK_PORT']            = PUERTO_APP
env['FLASK_DEBUG']           = 'false'
env['BEHIND_PROXY']          = 'true'        # ProxyFix: IP real del cliente en los logs
env['SESSION_COOKIE_SECURE'] = 'false'       # HTTP: la cookie NO puede ser 'Secure'
env.setdefault('XDG_DATA_HOME', os.path.join(DIRECTORIO, 'caddy_data'))

os.makedirs(LOG_DIR, exist_ok=True)

SEP      = '=' * 58
SEP_THIN = '-' * 58

# ── Iniciar Caddy (proxy inverso HTTP en el puerto 80) ────────────────────────
caddy_proc   = None
caddy_log_fh = None
if os.path.exists(CADDY_EXE) and os.path.exists(CADDYFILE):
    caddy_log_fh = open(CADDY_LOG, 'w', encoding='utf-8', errors='replace')
    caddy_proc = subprocess.Popen(
        [CADDY_EXE, 'run', '--config', CADDYFILE, '--adapter', 'caddyfile'],
        stdout=caddy_log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=DIRECTORIO,
    )
else:
    print('  AVISO: no se encontro caddy.exe o Caddyfile.')
    print(f'         La aplicacion arrancara solo en http://localhost:{PUERTO_APP}')
    print('         Ejecuta lanzar.bat para configurar el proxy en el puerto 80.')
    print()

# ── Iniciar Flask como subproceso ─────────────────────────────────────────────
proc = subprocess.Popen(
    [sys.executable, 'app.py'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding='utf-8',
    errors='replace',
    env=env,
    cwd=DIRECTORIO,
)

creds        = {'user': 'admin', 'pass': None}
banner_shown = False


def detener_todo():
    """Detiene Flask y Caddy y cierra el log."""
    try:
        proc.terminate()
    except Exception:
        pass
    if caddy_proc is not None:
        try:
            caddy_proc.terminate()
        except Exception:
            pass
    if caddy_log_fh is not None:
        try:
            caddy_log_fh.close()
        except Exception:
            pass


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
            ip = get_local_ip()
            proxy_ok = caddy_proc is not None

            print()
            print(f'  {SEP}')
            print(f'  {"PORTERO SEGURO  -  SERVIDOR ACTIVO":^58}')
            print(f'  {SEP}')
            if proxy_ok:
                print(f'  Desde CUALQUIER equipo de la red local:')
                print(f'    Por IP     :  http://{ip}')
                print(f'    Por nombre :  http://{DOMINIO}')
                print(f'  {SEP_THIN}')
                print(f'  Para que el NOMBRE funcione en todos los equipos, anade')
                print(f'  en tu router una entrada DNS local (una sola vez):')
                print(f'      {DOMINIO}  ->  {ip}')
                print(f'  (Si el router no lo permite, usa la IP, o ejecuta en cada')
                print(f'   equipo:  configurar_cliente.bat {ip})')
            else:
                print(f'  {"Este equipo:":<16} http://localhost:{PUERTO_APP}')
                print(f'  {"Red local:":<16} http://{ip}:{PUERTO_APP}')
                print(f'  {"":2}(Proxy en puerto 80 no activo. Ejecuta lanzar.bat.)')

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
    print()
    print(f'  {SEP}')
    print(f'  Deteniendo servidor y proxy...')
    print(f'  {SEP}')
    print()
finally:
    detener_todo()
