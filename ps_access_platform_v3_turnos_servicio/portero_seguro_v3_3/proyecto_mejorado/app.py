from flask import Flask, render_template, request, redirect, url_for, json, flash, send_file, jsonify, session, abort
import sqlite3
import os
import io
import re
import secrets
from collections import defaultdict

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from auth import (
    ROLE_LEVELS, ROLES_VALIDOS, hash_password, check_password,
    generar_password_temporal, nuevo_csrf_token, rol_alcanza,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, 'inventario.db')
SECRET_KEY_FILE = os.path.join(BASE_DIR, '.secret_key')


def obtener_secret_key():
    """Resuelve la SECRET_KEY de Flask sin dejar un valor por defecto fijo.

    Orden de prioridad:
    1. Variable de entorno SECRET_KEY (recomendado en produccion).
    2. Un archivo .secret_key generado una sola vez junto al proyecto
       (persiste entre reinicios, no se versiona en git).
    """
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
            valor = f.read().strip()
            if valor:
                return valor

    nueva_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(nueva_key)
    try:
        os.chmod(SECRET_KEY_FILE, 0o600)
    except OSError:
        pass
    return nueva_key


app = Flask(__name__)
app.secret_key = obtener_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Si la app se sirve detras de HTTPS (recomendado), activa esto por entorno:
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

# Mapa de control de acceso por endpoint (nombre de la funcion de la ruta).
# Valor string => mismo rol minimo para cualquier metodo HTTP.
# Valor dict    => rol minimo distinto segun el metodo (ej. ver vs. crear).
# Si un endpoint protegido no aparece aqui, se deniega por defecto (admin),
# es decir: "denegar salvo que se liste explicitamente" en vez de lo opuesto.
ROUTE_ACCESS = {
    'index': 'lectura',
    'api_catalogos': 'lectura',
    'api_marcas': 'lectura',
    'api_modelos': 'lectura',
    'api_productos': 'lectura',
    'api_series': 'lectura',
    'ingreso_series': {'GET': 'lectura', 'POST': 'operador'},
    'ingresos': {'GET': 'lectura', 'POST': 'operador'},
    'salidas': {'GET': 'lectura', 'POST': 'operador'},
    'guias': 'lectura',
    'guardar_guia': 'operador',
    'actualizar_guia': 'operador',
    'ver_guia': 'lectura',
    'actualizar_series_guia': {'GET': 'lectura', 'POST': 'operador'},
    'quitar_serie_guia': 'operador',
    'listar_series': 'lectura',
    'eliminar_serie': 'operador',
    'eliminar_guia': 'operador',
    'listar_guias': 'lectura',
    'editar_guia': 'lectura',
    'pdf_guia': 'lectura',
    'movimientos': 'lectura',
    'configuracion': 'admin',
    'eliminar_relacion_categoria_marca': 'admin',
    'limpiar_relaciones_vacias': 'admin',
    'editar_catalogo': 'admin',
    'eliminar_catalogo': 'admin',
    'personal': {'GET': 'lectura', 'POST': 'admin'},
    'editar_personal': 'admin',
    'eliminar_personal': 'admin',
    'agregar_cargo': 'admin',
    'agregar_categoria': 'admin',
    'agregar_marca': 'admin',
    'agregar_modelo': 'admin',
    'edificios': {'GET': 'lectura', 'POST': 'admin'},
    'editar_edificio': 'admin',
    'eliminar_edificio': 'admin',
    'editar_equipo': 'operador',
    'dar_baja_equipo': 'operador',
    'seguimiento': {'GET': 'lectura', 'POST': 'operador'},
    'actualizar_seguimiento': 'operador',
    'eliminar_seguimiento': 'operador',
    'avances': {'GET': 'lectura', 'POST': 'operador'},
    'actualizar_avance': 'operador',
    'eliminar_avance': 'operador',
    'usuarios': 'admin',
    'crear_usuario': 'admin',
    'editar_usuario': 'admin',
    'resetear_password_usuario': 'admin',
}

# Endpoints publicos que no requieren sesion iniciada.
ENDPOINTS_PUBLICOS = {'login', 'static'}


@app.before_request
def seguridad_global():
    # Token CSRF: se crea uno por sesion (incluso antes de iniciar sesion,
    # para poder protejer tambien el propio formulario de login).
    if 'csrf_token' not in session:
        session['csrf_token'] = nuevo_csrf_token()

    if request.endpoint in ENDPOINTS_PUBLICOS or request.endpoint is None:
        return None

    # 1) Debe haber sesion iniciada.
    if not session.get('user_id'):
        if request.method == 'GET':
            return redirect(url_for('login', next=request.path))
        flash('Tu sesion expiro o no has iniciado sesion. Vuelve a ingresar.', 'warning')
        return redirect(url_for('login'))

    # 2) Validacion CSRF en cualquier metodo que modifique datos.
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token_formulario = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token_formulario or not secrets.compare_digest(token_formulario, session['csrf_token']):
            flash('Tu formulario expiro o no es valido (token de seguridad incorrecto). Intenta de nuevo.', 'danger')
            return redirect(request.referrer or url_for('index'))

    # 3) Rol minimo requerido para este endpoint.
    requerido = ROUTE_ACCESS.get(request.endpoint, 'admin')
    if isinstance(requerido, dict):
        requerido = requerido.get(request.method, 'admin')

    if not rol_alcanza(session.get('rol'), requerido):
        flash('No tienes permisos suficientes para realizar esta accion.', 'danger')
        return redirect(url_for('index'))

    return None


@app.context_processor
def inject_seguridad():
    return dict(
        csrf_token=session.get('csrf_token', ''),
        usuario_actual=session.get('username'),
        rol_actual=session.get('rol'),
    )

ESTADOS_EQUIPO = ['En Stock', 'Sin Stock', 'En Revision', 'En Transito', 'Instalado', 'Baja']
ESTADOS_COMPATIBLES = {
    'En Revisión': 'En Revision',
    'En Tránsito': 'En Transito'
}

TIPOS_MOVIMIENTO = [
    'INGRESO',
    'SALIDA_DIRECTA',
    'SALIDA_GUIA',
    'DEVOLUCION_GUIA',
    'ANULACION_GUIA',
    'AJUSTE',
    'BAJA',
    'TRANSFERENCIA'
]


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def clean_text(value):
    return (value or '').strip()


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_estado(value):
    value = clean_text(value)
    return ESTADOS_COMPATIBLES.get(value, value)


def estado_operativo_por_stock(cantidad, estado_actual='En Stock'):
    estado_actual = normalize_estado(estado_actual)
    cantidad = safe_int(cantidad)
    if estado_actual == 'Baja':
        return 'Baja'
    if estado_actual in ['En Revision', 'En Transito', 'Instalado']:
        return estado_actual
    return 'En Stock' if cantidad > 0 else 'Sin Stock'


def actualizar_equipo_stock_estado(conn, equipo_id, cantidad, estado_actual=None):
    if estado_actual is None:
        row = conn.execute('SELECT estado FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
        estado_actual = row['estado'] if row else 'En Stock'
    nuevo_estado = estado_operativo_por_stock(cantidad, estado_actual)
    conn.execute('''
        UPDATE equipos
        SET cantidad = ?, estado = ?, fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (safe_int(cantidad), nuevo_estado, equipo_id))
    return nuevo_estado


def normalizar_estados_por_stock(conn):
    conn.execute("UPDATE equipos SET estado = 'Sin Stock' WHERE COALESCE(cantidad,0) <= 0 AND estado = 'En Stock'")
    conn.execute("UPDATE equipos SET estado = 'En Stock' WHERE COALESCE(cantidad,0) > 0 AND estado = 'Sin Stock'")


# ---------------------------------------------------------------------------
# Ubicacion actual / trazabilidad
# ---------------------------------------------------------------------------
# Etiquetas estandar de ubicacion. Mantienen la trazabilidad clara sobre
# donde se encuentra fisicamente cada unidad o lote de inventario.
UBIC_ALMACEN = 'Almacén'        # disponible en stock dentro del almacen
UBIC_SIN_STOCK = 'Sin stock'    # producto por cantidad sin unidades
UBIC_BAJA = 'Baja'              # dado de baja


def ubic_edificio(destino):
    """Etiqueta de ubicacion cuando una unidad fue despachada a un edificio."""
    destino = clean_text(destino)
    return f'Edificio: {destino}' if destino else 'Entregado'


def ubicacion_por_estado_serie(conn, estado, guia_id=None):
    """Deriva la ubicacion de una serie a partir de su estado y guia.

    Es el valor por defecto que se guarda en cada movimiento; el usuario
    puede sobrescribirlo manualmente y solo se vuelve a recalcular cuando la
    unidad se mueve (ingreso, salida, devolucion, baja).
    """
    estado = (estado or '').strip().upper()
    if estado == 'EN_STOCK':
        return UBIC_ALMACEN
    if estado == 'BAJA':
        return UBIC_BAJA
    if estado == 'ENTREGADO':
        if guia_id:
            row = conn.execute(
                'SELECT destino, estado FROM guias_salida WHERE id = ?', (guia_id,)
            ).fetchone()
            if row:
                if (row['estado'] or 'ACTIVA') == 'ANULADA':
                    return UBIC_ALMACEN
                return ubic_edificio(row['destino'])
        return 'Entregado'
    return estado.capitalize() if estado else 'Sin definir'


def set_ubicacion_serie(conn, serie_id, ubicacion):
    """Guarda explicitamente la ubicacion de una serie."""
    conn.execute(
        'UPDATE equipo_series SET ubicacion_actual = ?, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?',
        (ubicacion, serie_id)
    )


def set_ubicacion_series_de_guia(conn, guia_id):
    """Recalcula la ubicacion de todas las series ligadas a una guia."""
    row = conn.execute('SELECT destino, estado FROM guias_salida WHERE id = ?', (guia_id,)).fetchone()
    if not row:
        return
    if (row['estado'] or 'ACTIVA') == 'ANULADA':
        ubic = UBIC_ALMACEN
    else:
        ubic = ubic_edificio(row['destino'])
    conn.execute(
        "UPDATE equipo_series SET ubicacion_actual = ? WHERE guia_id = ? AND estado = 'ENTREGADO'",
        (ubic, guia_id)
    )


def ubicacion_default_por_estado_equipo(estado):
    """Ubicacion por defecto para productos controlados por cantidad."""
    estado = normalize_estado(estado)
    return {
        'En Stock': UBIC_ALMACEN,
        'Sin Stock': UBIC_SIN_STOCK,
        'En Revision': 'En revisión',
        'En Transito': 'En tránsito',
        'Instalado': 'Instalado',
        'Baja': UBIC_BAJA,
    }.get(estado, estado or 'Sin definir')


def resumen_ubicacion_equipo(conn, equipo):
    """Texto de 'Ubicacion actual' para mostrar en el listado de inventario.

    - Producto SERIAL: desglose por ubicacion de sus unidades.
    - Producto por CANTIDAD: ubicacion editable guardada (o derivada del estado).
    """
    keys = equipo.keys()
    estado = normalize_estado(equipo['estado'] if 'estado' in keys else 'En Stock')
    control = (equipo['control_stock'] if 'control_stock' in keys else 'CANTIDAD') or 'CANTIDAD'

    if control == 'SERIAL':
        if estado == 'Baja':
            return UBIC_BAJA
        rows = conn.execute("""
            SELECT COALESCE(NULLIF(TRIM(ubicacion_actual), ''), 'Sin definir') AS u,
                   COUNT(*) AS c
            FROM equipo_series
            WHERE equipo_id = ? AND UPPER(COALESCE(estado, '')) <> 'BAJA'
            GROUP BY u
            ORDER BY c DESC, u
        """, (equipo['id'],)).fetchall()
        if not rows:
            return 'Sin unidades'
        return ' · '.join(f"{r['u']}: {r['c']}" for r in rows)

    # Producto por cantidad
    ubic = clean_text(equipo['ubicacion_actual']) if 'ubicacion_actual' in keys else ''
    if estado == 'Baja':
        return UBIC_BAJA
    if ubic:
        return ubic
    return ubicacion_default_por_estado_equipo(estado)


def guia_codigo(guia_id):
    return f"GS-{int(guia_id):06d}"


def validar_mac(mac):
    mac = clean_text(mac)
    if not mac:
        return True
    return re.fullmatch(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', mac) is not None


def table_columns(conn, table):
    return [row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]


def add_column_if_missing(conn, table, column, definition):
    if column not in table_columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def catalog_exists(conn, table, nombre):
    return conn.execute(f'SELECT 1 FROM {table} WHERE nombre = ?', (nombre,)).fetchone() is not None


def row_to_dict(row):
    return dict(row) if row else None


def ensure_catalog_value(conn, table, nombre):
    nombre = clean_text(nombre)
    if not nombre:
        return None
    row = conn.execute(f'SELECT id, nombre FROM {table} WHERE nombre = ?', (nombre,)).fetchone()
    if row:
        return row['id']
    cursor = conn.execute(f'INSERT INTO {table} (nombre) VALUES (?)', (nombre,))
    return cursor.lastrowid


def ensure_categoria_marca(conn, categoria, marca):
    categoria = clean_text(categoria)
    marca = clean_text(marca)
    if not categoria or not marca:
        return
    ensure_catalog_value(conn, 'categorias', categoria)
    ensure_catalog_value(conn, 'marcas', marca)
    conn.execute('''
        INSERT OR IGNORE INTO categoria_marca (categoria, marca)
        VALUES (?, ?)
    ''', (categoria, marca))


def relacion_categoria_marca_exists(conn, categoria, marca):
    return conn.execute('''
        SELECT 1
        FROM categoria_marca
        WHERE categoria = ? AND marca = ?
    ''', (categoria, marca)).fetchone() is not None


def modelo_catalog_exists(conn, nombre, categoria=None, marca=None):
    nombre = clean_text(nombre)
    categoria = clean_text(categoria)
    marca = clean_text(marca)
    if not nombre:
        return False
    if categoria and marca:
        return conn.execute('''
            SELECT 1
            FROM modelos
            WHERE nombre = ? AND categoria = ? AND marca = ?
        ''', (nombre, categoria, marca)).fetchone() is not None
    return conn.execute('SELECT 1 FROM modelos WHERE nombre = ?', (nombre,)).fetchone() is not None


def ensure_modelo(conn, nombre, categoria, marca):
    nombre = clean_text(nombre)
    categoria = clean_text(categoria)
    marca = clean_text(marca)
    if not nombre or not categoria or not marca:
        return None

    ensure_categoria_marca(conn, categoria, marca)

    row = conn.execute('''
        SELECT id
        FROM modelos
        WHERE nombre = ? AND categoria = ? AND marca = ?
    ''', (nombre, categoria, marca)).fetchone()
    if row:
        return row['id']

    row = conn.execute('''
        SELECT id, categoria, marca
        FROM modelos
        WHERE nombre = ?
        ORDER BY id
        LIMIT 1
    ''', (nombre,)).fetchone()
    if row and (not clean_text(row['categoria']) or not clean_text(row['marca'])):
        conn.execute('UPDATE modelos SET categoria = ?, marca = ? WHERE id = ?', (categoria, marca, row['id']))
        return row['id']

    try:
        cursor = conn.execute('''
            INSERT INTO modelos (nombre, categoria, marca)
            VALUES (?, ?, ?)
        ''', (nombre, categoria, marca))
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        row = conn.execute('SELECT id FROM modelos WHERE nombre = ? LIMIT 1', (nombre,)).fetchone()
        if row:
            conn.execute('UPDATE modelos SET categoria = ?, marca = ? WHERE id = ?', (categoria, marca, row['id']))
            return row['id']
        raise


def inferir_categoria_marca_modelo(nombre):
    texto = clean_text(nombre).lower()
    if any(k in texto for k in ['camara', 'cámara', 'domo', 'bullet', 'nvr', 'dvr', 'hikvision', 'dahua']):
        return 'CCTV', 'Hikvision'
    if any(k in texto for k in ['intercom', 'akuvox', 'akubox', 'acceso', 'lector', 'r29', 'control']):
        return 'Control de Accesos', 'Akuvox'
    if any(k in texto for k in ['switch', 'router', 'firewall', 'ap ', 'access point', 'aruba', 'cisco', 'fortinet']):
        return 'Redes', 'Cisco'
    if any(k in texto for k in ['cable', 'utp', 'bobina', 'conector', 'patch', 'consumible']):
        return 'Consumibles', 'Generico'
    return 'Consumibles', 'Generico'


def migrar_catalogos_relacionados(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categoria_marca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            marca TEXT NOT NULL,
            UNIQUE(categoria, marca)
        )
    ''')

    add_column_if_missing(conn, 'modelos', 'categoria', 'TEXT')
    add_column_if_missing(conn, 'modelos', 'marca', 'TEXT')

    defaults = [
        ('CCTV', 'Hikvision'),
        ('CCTV', 'Dahua'),
        ('Control de Accesos', 'Akuvox'),
        ('Redes', 'Cisco'),
        ('Redes', 'Fortinet'),
        ('Redes', 'Aruba'),
        ('Consumibles', 'Generico'),
    ]
    for categoria, marca in defaults:
        ensure_categoria_marca(conn, categoria, marca)

    default_models = [
        ('Camara Domo IP 4MP', 'CCTV', 'Hikvision'),
        ('Camara Bullet IP 4MP', 'CCTV', 'Hikvision'),
        ('NVR 16 Canales', 'CCTV', 'Hikvision'),
        ('Intercomunicador R29C', 'Control de Accesos', 'Akuvox'),
        ('Switch PoE 24 Puertos', 'Redes', 'Cisco'),
        ('Access Point Aruba', 'Redes', 'Aruba'),
        ('Firewall Fortinet', 'Redes', 'Fortinet'),
        ('Bobina Cable UTP Cat6', 'Consumibles', 'Generico'),
    ]
    for nombre, categoria, marca in default_models:
        ensure_modelo(conn, nombre, categoria, marca)

    for row in conn.execute('''
        SELECT DISTINCT categoria, marca
        FROM equipos
        WHERE COALESCE(categoria, '') <> '' AND COALESCE(marca, '') <> ''
    ''').fetchall():
        ensure_categoria_marca(conn, row['categoria'], row['marca'])

    for row in conn.execute('''
        SELECT DISTINCT descripcion, categoria, marca
        FROM equipos
        WHERE COALESCE(descripcion, '') <> ''
          AND COALESCE(categoria, '') <> ''
          AND COALESCE(marca, '') <> ''
    ''').fetchall():
        ensure_modelo(conn, row['descripcion'], row['categoria'], row['marca'])

    for row in conn.execute('''
        SELECT id, nombre
        FROM modelos
        WHERE COALESCE(categoria, '') = '' OR COALESCE(marca, '') = ''
    ''').fetchall():
        categoria, marca = inferir_categoria_marca_modelo(row['nombre'])
        ensure_categoria_marca(conn, categoria, marca)
        conn.execute('UPDATE modelos SET categoria = ?, marca = ? WHERE id = ?', (categoria, marca, row['id']))

    conn.execute('CREATE INDEX IF NOT EXISTS idx_categoria_marca_categoria ON categoria_marca(categoria)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_categoria_marca_marca ON categoria_marca(marca)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_modelos_relacion ON modelos(categoria, marca, nombre)')


def get_catalogos_payload(conn):
    categorias = [row['nombre'] for row in conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()]

    marcas = []
    for row in conn.execute('SELECT id, nombre FROM marcas ORDER BY nombre').fetchall():
        cats = [r['categoria'] for r in conn.execute('''
            SELECT categoria
            FROM categoria_marca
            WHERE marca = ?
            ORDER BY categoria
        ''', (row['nombre'],)).fetchall()]
        marcas.append({'id': row['id'], 'nombre': row['nombre'], 'categorias': cats})

    modelos = []
    for row in conn.execute('''
        SELECT id, nombre, categoria, marca
        FROM modelos
        ORDER BY categoria, marca, nombre
    ''').fetchall():
        modelos.append({
            'id': row['id'],
            'nombre': row['nombre'],
            'categoria': row['categoria'] or '',
            'marca': row['marca'] or ''
        })

    return {'categorias': categorias, 'marcas': marcas, 'modelos': modelos}


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def registrar_movimiento(conn, equipo_id, tipo, cantidad, stock_anterior, stock_nuevo,
                         guia_id=None, referencia=None, usuario=None, observaciones=''):
    cantidad = safe_int(cantidad)
    if cantidad <= 0:
        return
    if not usuario:
        # Si no se especifica explicitamente, se usa el usuario autenticado
        # de la sesion actual. Antes este valor quedaba fijo en 'Sistema',
        # lo que impedia saber quien hizo cada movimiento de inventario.
        usuario = session.get('username', 'Sistema') if session else 'Sistema'
    conn.execute('''
        INSERT INTO movimientos (
            equipo_id, guia_id, tipo, cantidad, stock_anterior, stock_nuevo,
            referencia, usuario, observaciones
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        equipo_id, guia_id, tipo, cantidad, stock_anterior, stock_nuevo,
        referencia, usuario, observaciones
    ))




def parse_seriales_text(raw):
    """Recibe series una por linea. Permite SERIAL o SERIAL,MAC."""
    lineas = []
    for linea in (raw or '').splitlines():
        linea = linea.strip()
        if not linea:
            continue
        partes = [p.strip() for p in linea.replace(';', ',').split(',')]
        serial = partes[0]
        mac = partes[1] if len(partes) > 1 else ''
        lineas.append({'serial': serial, 'mac': mac})
    return lineas


def get_or_create_equipo_base(conn, categoria, marca, descripcion, observaciones=''):
    """Producto base para equipos serializados: una sola fila por categoria + marca + modelo.

    Si ya existe el producto como CANTIDAD, se reutiliza y se convierte a SERIAL.
    Esto evita duplicar el mismo modelo cuando se empiezan a registrar series/MAC.
    """
    row = conn.execute("""
        SELECT *
        FROM equipos
        WHERE categoria = ?
          AND marca = ?
          AND descripcion = ?
          AND estado <> 'Baja'
        ORDER BY id
        LIMIT 1
    """, (categoria, marca, descripcion)).fetchone()
    if row:
        conn.execute("""
            UPDATE equipos
            SET control_stock = 'SERIAL',
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (row['id'],))
        return conn.execute('SELECT * FROM equipos WHERE id = ?', (row['id'],)).fetchone()

    cursor = conn.execute("""
        INSERT INTO equipos (
            categoria, marca, descripcion, sku, mac, estado, cantidad,
            observaciones, stock_minimo, control_stock, fecha_actualizacion
        )
        VALUES (?, ?, ?, '', '', 'Sin Stock', 0, ?, 0, 'SERIAL', CURRENT_TIMESTAMP)
    """, (categoria, marca, descripcion, observaciones))
    equipo_id = cursor.lastrowid
    return conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()


def recalcular_stock_serial(conn, equipo_id):
    total = conn.execute("""
        SELECT COUNT(*)
        FROM equipo_series
        WHERE equipo_id = ?
          AND estado = 'EN_STOCK'
    """, (equipo_id,)).fetchone()[0]
    estado = 'En Stock' if total > 0 else 'Sin Stock'
    conn.execute("""
        UPDATE equipos
        SET cantidad = ?, control_stock = 'SERIAL', estado = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (total, estado, equipo_id))
    return total



def get_or_create_producto_cantidad(conn, categoria, marca, descripcion, sku='', mac='', observaciones=''):
    """Devuelve una unica fila base para productos controlados por cantidad.

    Regla corporativa:
    - Categoria + Marca + Modelo/Descripcion identifica al producto base.
    - SKU/MAC no deben crear productos duplicados; quedan como referencia si la fila base aun no los tenia.
    - Para equipos con serial individual se debe usar Ingreso Series.
    """
    row = conn.execute("""
        SELECT *
        FROM equipos
        WHERE categoria = ?
          AND marca = ?
          AND descripcion = ?
          AND COALESCE(control_stock, 'CANTIDAD') = 'CANTIDAD'
        ORDER BY CASE WHEN estado = 'Baja' THEN 1 ELSE 0 END, id
        LIMIT 1
    """, (categoria, marca, descripcion)).fetchone()

    if row:
        updates = []
        params = []

        if sku and not clean_text(row['sku'] if 'sku' in row.keys() else ''):
            updates.append('sku = ?')
            params.append(sku)

        if mac and not clean_text(row['mac'] if 'mac' in row.keys() else ''):
            updates.append('mac = ?')
            params.append(mac)

        if observaciones:
            obs_actual = clean_text(row['observaciones'] if 'observaciones' in row.keys() else '')
            if obs_actual:
                nueva_obs = obs_actual + '\n' + observaciones
            else:
                nueva_obs = observaciones
            updates.append('observaciones = ?')
            params.append(nueva_obs)

        if updates:
            updates.append('fecha_actualizacion = CURRENT_TIMESTAMP')
            params.append(row['id'])
            conn.execute(
                f"UPDATE equipos SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            row = conn.execute('SELECT * FROM equipos WHERE id = ?', (row['id'],)).fetchone()

        return row, False

    cursor = conn.execute("""
        INSERT INTO equipos (
            categoria, marca, descripcion, sku, mac, estado, cantidad,
            observaciones, stock_minimo, control_stock, fecha_actualizacion
        )
        VALUES (?, ?, ?, ?, ?, 'Sin Stock', 0, ?, 0, 'CANTIDAD', CURRENT_TIMESTAMP)
    """, (categoria, marca, descripcion, sku, mac, observaciones))

    equipo_id = cursor.lastrowid
    row = conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
    return row, True




def preservar_serie_referencia_desde_equipo(conn, equipo_row, equipo_destino_id=None):
    """Convierte SKU/MAC antiguos en filas de equipo_series antes de consolidar.

    Protege la trazabilidad si antes existian productos duplicados con el
    mismo modelo pero con series/MAC distintas.
    """
    if not equipo_row:
        return False

    serial = clean_text(equipo_row['sku'] if 'sku' in equipo_row.keys() else '')
    mac = clean_text(equipo_row['mac'] if 'mac' in equipo_row.keys() else '')
    if not serial and not mac:
        return False

    if not serial:
        serial = f"MAC-{mac}"

    destino_id = equipo_destino_id or equipo_row['id']
    existe = conn.execute(
        'SELECT id FROM equipo_series WHERE lower(serial) = lower(?) LIMIT 1',
        (serial,)
    ).fetchone()
    if existe:
        return False

    conn.execute("""
        INSERT INTO equipo_series (
            equipo_id, serial, mac, estado, observaciones, fecha_actualizacion
        )
        VALUES (?, ?, ?, 'EN_STOCK', ?, CURRENT_TIMESTAMP)
    """, (
        destino_id,
        serial,
        mac,
        'Serie/MAC migrada desde registro historico de equipos antes de consolidar productos.'
    ))
    return True

def consolidar_productos_duplicados(conn):
    """Une productos duplicados por categoria + marca + descripcion + control_stock.

    Mantiene el ID mas antiguo y suma stock. Reapunta referencias historicas
    para que guias, salidas, movimientos, series y seguimiento no queden rotos.
    No mezcla productos en estado Baja con productos activos.
    """
    grupos = conn.execute("""
        SELECT
            categoria,
            marca,
            descripcion,
            COALESCE(control_stock, 'CANTIDAD') AS control_stock,
            GROUP_CONCAT(id) AS ids,
            COUNT(*) AS total,
            SUM(COALESCE(cantidad, 0)) AS cantidad_total
        FROM equipos
        WHERE estado <> 'Baja'
        GROUP BY categoria, marca, descripcion, COALESCE(control_stock, 'CANTIDAD')
        HAVING COUNT(*) > 1
    """).fetchall()

    consolidados = 0

    for grupo in grupos:
        ids = [safe_int(x) for x in (grupo['ids'] or '').split(',') if safe_int(x) > 0]
        if len(ids) <= 1:
            continue

        target_id = min(ids)
        duplicate_ids = [x for x in ids if x != target_id]

        # Conservar SKU/MAC historicos como series antes de fusionar filas.
        target = conn.execute('SELECT * FROM equipos WHERE id = ?', (target_id,)).fetchone()
        preservar_serie_referencia_desde_equipo(conn, target, target_id)
        for dup_id in duplicate_ids:
            dup = conn.execute('SELECT * FROM equipos WHERE id = ?', (dup_id,)).fetchone()
            if not dup:
                continue

            preservar_serie_referencia_desde_equipo(conn, dup, target_id)

            updates = []
            params = []

            if not clean_text(target['sku']) and clean_text(dup['sku']):
                updates.append('sku = ?')
                params.append(dup['sku'])

            if not clean_text(target['mac']) and clean_text(dup['mac']):
                updates.append('mac = ?')
                params.append(dup['mac'])

            obs_target = clean_text(target['observaciones'])
            obs_dup = clean_text(dup['observaciones'])
            if obs_dup and obs_dup not in obs_target:
                nueva_obs = (obs_target + '\n' if obs_target else '') + obs_dup
                updates.append('observaciones = ?')
                params.append(nueva_obs)

            if updates:
                params.append(target_id)
                conn.execute(f"UPDATE equipos SET {', '.join(updates)} WHERE id = ?", tuple(params))
                target = conn.execute('SELECT * FROM equipos WHERE id = ?', (target_id,)).fetchone()

            for tabla in ['salidas', 'movimientos', 'seguimiento_equipos', 'equipo_series']:
                try:
                    conn.execute(f'UPDATE {tabla} SET equipo_id = ? WHERE equipo_id = ?', (target_id, dup_id))
                except sqlite3.OperationalError:
                    pass

            conn.execute('UPDATE guia_detalle SET equipo_id = ? WHERE equipo_id = ?', (target_id, dup_id))
            conn.execute('DELETE FROM equipos WHERE id = ?', (dup_id,))
            consolidados += 1

        # Fusionar lineas duplicadas dentro de una misma guia.
        detalles_dup = conn.execute("""
            SELECT guia_id, equipo_id, GROUP_CONCAT(id) AS ids, SUM(cantidad) AS cantidad_total
            FROM guia_detalle
            WHERE equipo_id = ?
            GROUP BY guia_id, equipo_id
            HAVING COUNT(*) > 1
        """, (target_id,)).fetchall()

        for d in detalles_dup:
            detalle_ids = [safe_int(x) for x in (d['ids'] or '').split(',') if safe_int(x) > 0]
            keep_id = min(detalle_ids)
            delete_ids = [x for x in detalle_ids if x != keep_id]

            conn.execute(
                'UPDATE guia_detalle SET cantidad = ? WHERE id = ?',
                (safe_int(d['cantidad_total']), keep_id)
            )

            for old_detalle_id in delete_ids:
                try:
                    conn.execute(
                        'UPDATE guia_detalle_series SET guia_detalle_id = ? WHERE guia_detalle_id = ?',
                        (keep_id, old_detalle_id)
                    )
                except sqlite3.OperationalError:
                    pass

                conn.execute('DELETE FROM guia_detalle WHERE id = ?', (old_detalle_id,))

        # Recalcular stock de serializados o cantidad consolidada.
        if grupo['control_stock'] == 'SERIAL':
            try:
                recalcular_stock_serial(conn, target_id)
            except Exception:
                pass
        else:
            cantidad_total = safe_int(grupo['cantidad_total'])
            actualizar_equipo_stock_estado(conn, target_id, cantidad_total, 'En Stock' if cantidad_total > 0 else 'Sin Stock')

    return consolidados


def obtener_series_de_guia(conn, guia_id):
    rows = conn.execute("""
        SELECT gds.guia_detalle_id, gds.serie_id, es.serial, es.mac, gd.equipo_id
        FROM guia_detalle_series gds
        JOIN guia_detalle gd ON gd.id = gds.guia_detalle_id
        JOIN equipo_series es ON es.id = gds.serie_id
        WHERE gd.guia_id = ?
        ORDER BY gd.equipo_id, es.serial
    """, (guia_id,)).fetchall()
    por_detalle = {}
    por_equipo = {}
    for r in rows:
        por_detalle.setdefault(r['guia_detalle_id'], []).append(dict(r))
        por_equipo.setdefault(r['equipo_id'], []).append(dict(r))
    return por_detalle, por_equipo

def parse_productos_json(raw_productos):
    if not raw_productos:
        return None, 'Debe agregar al menos un producto.'
    try:
        data = json.loads(raw_productos)
    except Exception:
        return None, 'El detalle de productos no tiene un formato valido.'

    if not isinstance(data, list) or len(data) == 0:
        return None, 'Debe agregar al menos un producto.'

    productos = []
    acumulado_cantidad = defaultdict(int)
    acumulado_series = defaultdict(list)

    for item in data:
        if not isinstance(item, dict):
            return None, 'Existe un producto invalido en la guia.'
        equipo_id = safe_int(item.get('id'))
        control_stock = clean_text(item.get('control_stock')) or 'CANTIDAD'
        if equipo_id <= 0:
            return None, 'Existe un producto invalido en la guia.'

        if control_stock == 'SERIAL':
            series_ids = item.get('series_ids') or []
            if not isinstance(series_ids, list):
                return None, 'Las series seleccionadas no tienen formato valido.'
            limpias = []
            for sid in series_ids:
                sid = safe_int(sid)
                if sid <= 0:
                    return None, 'Existe una serie invalida en la guia.'
                if sid not in limpias:
                    limpias.append(sid)
            if not limpias:
                return None, 'Debe seleccionar al menos una serie para equipos serializados.'
            acumulado_series[equipo_id].extend(limpias)
        else:
            cantidad = safe_int(item.get('cantidad'))
            if cantidad <= 0:
                return None, 'Las cantidades deben ser mayores a cero.'
            acumulado_cantidad[equipo_id] += cantidad

    for equipo_id, cantidad in acumulado_cantidad.items():
        productos.append({
            'id': equipo_id,
            'cantidad': cantidad,
            'control_stock': 'CANTIDAD',
            'series_ids': []
        })

    for equipo_id, series_ids in acumulado_series.items():
        unicos = []
        for sid in series_ids:
            if sid not in unicos:
                unicos.append(sid)
        productos.append({
            'id': equipo_id,
            'cantidad': len(unicos),
            'control_stock': 'SERIAL',
            'series_ids': unicos
        })

    return productos, None

def validar_productos_para_guia(conn, productos, old_map=None, old_series_ids=None):
    old_map = old_map or {}
    old_series_ids = set(old_series_ids or [])
    equipos_validados = {}
    errores = []

    for item in productos:
        equipo_id = item['id']
        nueva_cantidad = item['cantidad']
        cantidad_anterior_guia = old_map.get(equipo_id, 0)

        equipo = conn.execute("""
            SELECT id, marca, descripcion, sku, cantidad, estado,
                   COALESCE(control_stock, 'CANTIDAD') AS control_stock
            FROM equipos
            WHERE id = ?
        """, (equipo_id,)).fetchone()

        if not equipo:
            errores.append(f'El producto ID {equipo_id} no existe.')
            continue

        estado = normalize_estado(equipo['estado'])
        control_stock = equipo['control_stock'] or 'CANTIDAD'
        disponible = equipo['cantidad'] + cantidad_anterior_guia

        if control_stock == 'SERIAL' or item.get('control_stock') == 'SERIAL':
            series_ids = item.get('series_ids') or []
            if len(series_ids) != nueva_cantidad:
                errores.append(f"La cantidad serializada de {equipo['marca']} - {equipo['descripcion']} no coincide con las series.")
                continue
            if len(series_ids) != len(set(series_ids)):
                errores.append(f"Hay series duplicadas en {equipo['marca']} - {equipo['descripcion']}.")
                continue
            if series_ids:
                placeholders = ','.join(['?'] * len(series_ids))
                rows = conn.execute(f"""
                    SELECT id, serial, equipo_id, estado
                    FROM equipo_series
                    WHERE id IN ({placeholders})
                """, tuple(series_ids)).fetchall()
                if len(rows) != len(series_ids):
                    errores.append(f"Una o mas series seleccionadas no existen para {equipo['marca']} - {equipo['descripcion']}.")
                    continue
                for serie in rows:
                    if serie['equipo_id'] != equipo_id:
                        errores.append(f"La serie {serie['serial']} no pertenece al producto seleccionado.")
                    if serie['estado'] != 'EN_STOCK' and serie['id'] not in old_series_ids:
                        errores.append(f"La serie {serie['serial']} no esta disponible. Estado actual: {serie['estado']}.")
        else:
            delta = nueva_cantidad - cantidad_anterior_guia
            if delta > 0 and estado != 'En Stock':
                errores.append(f"{equipo['marca']} - {equipo['descripcion']} no esta En Stock.")
            if nueva_cantidad > disponible:
                errores.append(
                    f"Stock insuficiente para {equipo['marca']} - {equipo['descripcion']}. "
                    f"Solicitado: {nueva_cantidad}. Disponible: {disponible}."
                )

        equipos_validados[equipo_id] = equipo

    if errores:
        return None, errores
    return equipos_validados, None

def init_db():
    conn = get_db_connection()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            marca TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            sku TEXT,
            mac TEXT,
            estado TEXT NOT NULL DEFAULT 'En Stock',
            cantidad INTEGER NOT NULL DEFAULT 0,
            observaciones TEXT,
            stock_minimo INTEGER NOT NULL DEFAULT 0,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP
        )
    ''')

    conn.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS marcas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS modelos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            categoria TEXT,
            marca TEXT,
            UNIQUE(nombre, categoria, marca)
        )
    ''')
    conn.execute('CREATE TABLE IF NOT EXISTS cargos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL, cargo TEXT NOT NULL)')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS edificios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            ubicacion TEXT,
            mapa_url TEXT,
            observaciones TEXT
        )
    ''')
    add_column_if_missing(conn, 'edificios', 'ubicacion', 'TEXT')
    add_column_if_missing(conn, 'edificios', 'mapa_url', 'TEXT')
    add_column_if_missing(conn, 'edificios', 'observaciones', 'TEXT')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS categoria_marca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            marca TEXT NOT NULL,
            UNIQUE(categoria, marca)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS salidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            personal TEXT NOT NULL,
            destino TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            observaciones TEXT,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS guias_salida (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            personal TEXT NOT NULL,
            destino TEXT NOT NULL,
            cargo TEXT,
            proyecto TEXT,
            entregado_por TEXT,
            recibido_por TEXT,
            aprobado_por TEXT,
            observaciones TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            estado TEXT DEFAULT 'ACTIVA',
            fecha_anulacion TIMESTAMP,
            motivo_anulacion TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS guia_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guia_id INTEGER NOT NULL,
            equipo_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL,
            FOREIGN KEY (guia_id) REFERENCES guias_salida(id),
            FOREIGN KEY (equipo_id) REFERENCES equipos(id)
        )
    ''')

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            serial TEXT UNIQUE NOT NULL,
            mac TEXT,
            estado TEXT NOT NULL DEFAULT 'EN_STOCK',
            guia_id INTEGER,
            ubicacion_actual TEXT,
            fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP,
            observaciones TEXT,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id),
            FOREIGN KEY (guia_id) REFERENCES guias_salida(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS guia_detalle_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guia_detalle_id INTEGER NOT NULL,
            serie_id INTEGER NOT NULL,
            UNIQUE(guia_detalle_id, serie_id),
            FOREIGN KEY (guia_detalle_id) REFERENCES guia_detalle(id),
            FOREIGN KEY (serie_id) REFERENCES equipo_series(id)
        )
    """)

    conn.execute('''
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            guia_id INTEGER,
            tipo TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            stock_anterior INTEGER NOT NULL,
            stock_nuevo INTEGER NOT NULL,
            referencia TEXT,
            usuario TEXT DEFAULT 'Sistema',
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            observaciones TEXT,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id),
            FOREIGN KEY (guia_id) REFERENCES guias_salida(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS seguimiento_equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER,
            serie_id INTEGER,
            nombre_equipo TEXT NOT NULL,
            categoria TEXT,
            marca TEXT,
            modelo TEXT,
            serial TEXT,
            edificio TEXT NOT NULL,
            ubicacion_detalle TEXT,
            fecha_dejado TEXT NOT NULL,
            dejado_por TEXT NOT NULL,
            solicitado_por TEXT,
            motivo TEXT,
            estado TEXT NOT NULL DEFAULT 'EN_SEGUIMIENTO',
            fecha_retiro TEXT,
            retirado_por TEXT,
            observaciones TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id),
            FOREIGN KEY (serie_id) REFERENCES equipo_series(id)
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS seguimiento_herramientas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herramienta TEXT NOT NULL,
            personal TEXT NOT NULL,
            fecha_dejado TEXT NOT NULL,
            edificio TEXT NOT NULL,
            entregado_por TEXT,
            estado TEXT NOT NULL DEFAULT 'EN_SEGUIMIENTO',
            fecha_retorno TEXT,
            recibido_por TEXT,
            observaciones TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS avances_actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            actividad TEXT NOT NULL,
            personal TEXT NOT NULL,
            solicitado_por TEXT,
            edificio TEXT,
            proyecto TEXT,
            estado TEXT NOT NULL DEFAULT 'EN_PROCESO',
            detalles TEXT,
            observaciones TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    ''')


    add_column_if_missing(conn, 'equipos', 'stock_minimo', 'INTEGER NOT NULL DEFAULT 0')
    add_column_if_missing(conn, 'equipos', 'fecha_creacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'equipos', 'fecha_actualizacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'equipos', 'control_stock', "TEXT NOT NULL DEFAULT 'CANTIDAD'")
    add_column_if_missing(conn, 'edificios', 'ubicacion', 'TEXT')
    add_column_if_missing(conn, 'edificios', 'mapa_url', 'TEXT')
    add_column_if_missing(conn, 'modelos', 'categoria', 'TEXT')
    add_column_if_missing(conn, 'modelos', 'marca', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'cargo', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'proyecto', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'entregado_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'recibido_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'aprobado_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'estado', "TEXT DEFAULT 'ACTIVA'")
    add_column_if_missing(conn, 'guias_salida', 'fecha_anulacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'guias_salida', 'motivo_anulacion', 'TEXT')

    conn.execute("UPDATE equipos SET estado = 'En Revision' WHERE estado = 'En Revisión'")
    conn.execute("UPDATE equipos SET estado = 'En Transito' WHERE estado = 'En Tránsito'")
    normalizar_estados_por_stock(conn)
    conn.execute("UPDATE equipos SET fecha_creacion = CURRENT_TIMESTAMP WHERE fecha_creacion IS NULL")
    conn.execute("UPDATE guias_salida SET estado = 'ACTIVA' WHERE estado IS NULL OR estado = ''")

    for categoria in ['CCTV', 'Control de Accesos', 'Redes', 'Consumibles']:
        ensure_catalog_value(conn, 'categorias', categoria)
    for marca in ['Hikvision', 'Dahua', 'Akuvox', 'Cisco', 'Fortinet', 'Aruba', 'Generico']:
        ensure_catalog_value(conn, 'marcas', marca)

    migrar_catalogos_relacionados(conn)

    if conn.execute('SELECT COUNT(*) FROM cargos').fetchone()[0] == 0:
        conn.executemany('INSERT INTO cargos (nombre) VALUES (?)', [
            ('Tecnico Instalador',), ('Ingeniero de Proyectos',), ('Soporte Tecnico',), ('Almacenero',)
        ])
    if conn.execute('SELECT COUNT(*) FROM personal').fetchone()[0] == 0:
        conn.executemany('INSERT INTO personal (nombre, cargo) VALUES (?, ?)', [
            ('Juan Perez', 'Tecnico Instalador'), ('Carlos Gomez', 'Ingeniero de Proyectos')
        ])

    # --- Migracion: columna 'Ubicacion actual' y trazabilidad ---
    add_column_if_missing(conn, 'equipos', 'ubicacion_actual', 'TEXT')
    add_column_if_missing(conn, 'equipo_series', 'ubicacion_actual', 'TEXT')

    # Backfill de productos por cantidad: ubicacion segun su estado actual.
    conn.execute("""
        UPDATE equipos
        SET ubicacion_actual = CASE
            WHEN estado = 'En Stock' THEN 'Almacén'
            WHEN estado = 'Sin Stock' THEN 'Sin stock'
            WHEN estado = 'En Revision' THEN 'En revisión'
            WHEN estado = 'En Transito' THEN 'En tránsito'
            WHEN estado = 'Instalado' THEN 'Instalado'
            WHEN estado = 'Baja' THEN 'Baja'
            ELSE estado
        END
        WHERE COALESCE(control_stock, 'CANTIDAD') <> 'SERIAL'
          AND (ubicacion_actual IS NULL OR TRIM(ubicacion_actual) = '')
    """)
    # Backfill de series en stock o dadas de baja (sin guia asociada).
    conn.execute("""
        UPDATE equipo_series
        SET ubicacion_actual = CASE
            WHEN UPPER(COALESCE(estado, '')) = 'EN_STOCK' THEN 'Almacén'
            WHEN UPPER(COALESCE(estado, '')) = 'BAJA' THEN 'Baja'
            ELSE ubicacion_actual
        END
        WHERE (ubicacion_actual IS NULL OR TRIM(ubicacion_actual) = '')
          AND UPPER(COALESCE(estado, '')) IN ('EN_STOCK', 'BAJA')
    """)
    # Backfill de series entregadas: ubicacion = edificio destino de su guia.
    conn.execute("""
        UPDATE equipo_series
        SET ubicacion_actual = (
            SELECT CASE
                WHEN COALESCE(g.estado, 'ACTIVA') = 'ANULADA' THEN 'Almacén'
                WHEN TRIM(COALESCE(g.destino, '')) <> '' THEN 'Edificio: ' || g.destino
                ELSE 'Entregado'
            END
            FROM guias_salida g WHERE g.id = equipo_series.guia_id
        )
        WHERE (ubicacion_actual IS NULL OR TRIM(ubicacion_actual) = '')
          AND guia_id IS NOT NULL
          AND UPPER(COALESCE(estado, '')) = 'ENTREGADO'
    """)

    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_descripcion ON equipos(descripcion)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_categoria_marca ON equipos(categoria, marca, descripcion)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_sku ON equipos(sku)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_guias_estado ON guias_salida(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_guia_detalle_guia ON guia_detalle(guia_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_equipo ON movimientos(equipo_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_guia ON movimientos(guia_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipo_series_equipo_estado ON equipo_series(equipo_id, estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipo_series_serial ON equipo_series(serial)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_guia_detalle_series_detalle ON guia_detalle_series(guia_detalle_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seguimiento_estado ON seguimiento_equipos(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seguimiento_edificio ON seguimiento_equipos(edificio)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seguimiento_equipo ON seguimiento_equipos(equipo_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_avances_fecha ON avances_actividades(fecha)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_avances_estado ON avances_actividades(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_avances_personal ON avances_actividades(personal)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seguimiento_herramientas_estado ON seguimiento_herramientas(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_seguimiento_herramientas_edificio ON seguimiento_herramientas(edificio)')

    migrar_usuarios(conn)

    conn.commit()
    conn.close()


def migrar_usuarios(conn):
    """Crea la tabla de usuarios y siembra un admin inicial si no hay ninguno.

    Las credenciales del admin inicial se toman de variables de entorno
    (ADMIN_USERNAME / ADMIN_PASSWORD). Si no se definen, se genera una
    contrasena aleatoria que se imprime UNA sola vez en consola al arrancar
    el servidor: nunca queda un usuario/clave por defecto fijo en el codigo.
    """
    conn.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre_completo TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'lectura',
            activo INTEGER NOT NULL DEFAULT 1,
            debe_cambiar_password INTEGER NOT NULL DEFAULT 0,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ultimo_acceso TIMESTAMP
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(username)')

    total_usuarios = conn.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0]
    if total_usuarios == 0:
        admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_pass = os.environ.get('ADMIN_PASSWORD')
        password_generada = False
        if not admin_pass:
            admin_pass = generar_password_temporal(12)
            password_generada = True

        conn.execute('''
            INSERT INTO usuarios (username, password_hash, nombre_completo, rol, activo, debe_cambiar_password)
            VALUES (?, ?, ?, 'admin', 1, ?)
        ''', (admin_user, hash_password(admin_pass), 'Administrador', 1 if password_generada else 0))

        if password_generada:
            print('=' * 70)
            print(' USUARIO ADMINISTRADOR CREADO AUTOMATICAMENTE')
            print(f'   Usuario:    {admin_user}')
            print(f'   Contrasena: {admin_pass}')
            print(' Cambia esta contrasena apenas inicies sesion.')
            print(' (Define ADMIN_USERNAME / ADMIN_PASSWORD como variables de')
            print('  entorno para fijar tus propias credenciales iniciales.)')
            print('=' * 70)

@app.context_processor
def utility_processor():
    return dict(guia_codigo=guia_codigo)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = clean_text(request.form.get('username'))
        password = request.form.get('password') or ''

        conn = get_db_connection()
        usuario = conn.execute(
            'SELECT * FROM usuarios WHERE username = ? COLLATE NOCASE', (username,)
        ).fetchone()
        conn.close()

        if not usuario or not usuario['activo'] or not check_password(usuario['password_hash'], password):
            flash('Usuario o contrasena incorrectos.', 'danger')
            return redirect(url_for('login'))

        session.clear()
        session['user_id'] = usuario['id']
        session['username'] = usuario['username']
        session['nombre_completo'] = usuario['nombre_completo']
        session['rol'] = usuario['rol']
        session['csrf_token'] = nuevo_csrf_token()
        session.permanent = True

        conn = get_db_connection()
        conn.execute('UPDATE usuarios SET ultimo_acceso = CURRENT_TIMESTAMP WHERE id = ?', (usuario['id'],))
        conn.commit()
        conn.close()

        if usuario['debe_cambiar_password']:
            flash('Por seguridad, cambia tu contrasena temporal antes de continuar.', 'warning')
            return redirect(url_for('usuarios'))

        destino = request.args.get('next')
        if destino and destino.startswith('/'):
            return redirect(destino)
        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Sesion cerrada correctamente.', 'success')
    return redirect(url_for('login'))


@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    conn = get_db_connection()

    if request.method == 'POST':
        accion = request.form.get('accion')

        if accion == 'cambiar_mi_password':
            actual = request.form.get('password_actual') or ''
            nueva = request.form.get('password_nueva') or ''
            confirmacion = request.form.get('password_confirmacion') or ''

            yo = conn.execute('SELECT * FROM usuarios WHERE id = ?', (session['user_id'],)).fetchone()
            if not yo or not check_password(yo['password_hash'], actual):
                flash('Tu contrasena actual no es correcta.', 'danger')
            elif len(nueva) < 8:
                flash('La nueva contrasena debe tener al menos 8 caracteres.', 'danger')
            elif nueva != confirmacion:
                flash('La confirmacion no coincide con la nueva contrasena.', 'danger')
            else:
                conn.execute(
                    'UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 0 WHERE id = ?',
                    (hash_password(nueva), session['user_id'])
                )
                conn.commit()
                flash('Tu contrasena fue actualizada correctamente.', 'success')

        conn.close()
        return redirect(url_for('usuarios'))

    lista_usuarios = conn.execute('SELECT * FROM usuarios ORDER BY username').fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, roles=ROLES_VALIDOS)


@app.route('/usuarios/crear', methods=['POST'])
def crear_usuario():
    conn = get_db_connection()
    try:
        username = clean_text(request.form.get('username'))
        nombre_completo = clean_text(request.form.get('nombre_completo'))
        rol = clean_text(request.form.get('rol'))

        errores = []
        if not username:
            errores.append('El usuario es obligatorio.')
        if not nombre_completo:
            errores.append('El nombre completo es obligatorio.')
        if rol not in ROLES_VALIDOS:
            errores.append('El rol seleccionado no es valido.')
        if username and conn.execute('SELECT 1 FROM usuarios WHERE username = ? COLLATE NOCASE', (username,)).fetchone():
            errores.append('Ya existe un usuario con ese nombre.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            return redirect(url_for('usuarios'))

        password_temporal = generar_password_temporal(10)
        conn.execute('''
            INSERT INTO usuarios (username, password_hash, nombre_completo, rol, activo, debe_cambiar_password)
            VALUES (?, ?, ?, ?, 1, 1)
        ''', (username, hash_password(password_temporal), nombre_completo, rol))
        conn.commit()
        flash(
            f'Usuario "{username}" creado. Contrasena temporal: {password_temporal} '
            '(se le pedira cambiarla al ingresar).',
            'success'
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ya existe un usuario con ese nombre.', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Error creando usuario: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('usuarios'))


@app.route('/usuarios/<int:id>/editar', methods=['POST'])
def editar_usuario(id):
    conn = get_db_connection()
    try:
        nombre_completo = clean_text(request.form.get('nombre_completo'))
        rol = clean_text(request.form.get('rol'))
        activo = 1 if request.form.get('activo') == 'on' else 0

        if id == session.get('user_id') and activo == 0:
            flash('No puedes desactivar tu propio usuario mientras tienes la sesion abierta.', 'warning')
            return redirect(url_for('usuarios'))

        if id == session.get('user_id') and rol != 'admin':
            flash('No puedes quitarte a ti mismo el rol de administrador.', 'warning')
            return redirect(url_for('usuarios'))

        if rol not in ROLES_VALIDOS:
            flash('El rol seleccionado no es valido.', 'danger')
            return redirect(url_for('usuarios'))

        conn.execute(
            'UPDATE usuarios SET nombre_completo = ?, rol = ?, activo = ? WHERE id = ?',
            (nombre_completo, rol, activo, id)
        )
        conn.commit()
        flash('Usuario actualizado correctamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando usuario: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('usuarios'))


@app.route('/usuarios/<int:id>/resetear_password', methods=['POST'])
def resetear_password_usuario(id):
    conn = get_db_connection()
    try:
        usuario = conn.execute('SELECT username FROM usuarios WHERE id = ?', (id,)).fetchone()
        if not usuario:
            flash('El usuario no existe.', 'danger')
            return redirect(url_for('usuarios'))

        password_temporal = generar_password_temporal(10)
        conn.execute(
            'UPDATE usuarios SET password_hash = ?, debe_cambiar_password = 1 WHERE id = ?',
            (hash_password(password_temporal), id)
        )
        conn.commit()
        flash(
            f'Contrasena de "{usuario["username"]}" restablecida. Nueva contrasena temporal: {password_temporal}',
            'success'
        )
    except Exception as e:
        conn.rollback()
        flash(f'Error restableciendo contrasena: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('usuarios'))


@app.route('/')

def index():
    conn = get_db_connection()
    normalizar_estados_por_stock(conn)
    conn.commit()
    search_query = request.args.get('q', '')
    categoria_filter = request.args.get('categoria', '')
    estado_filter = request.args.get('estado', '')

    query = """
        SELECT
            e.*,
            COALESCE((
                SELECT GROUP_CONCAT(es.serial, ', ')
                FROM equipo_series es
                WHERE es.equipo_id = e.id
            ), '') AS seriales_registradas,
            COALESCE((
                SELECT GROUP_CONCAT(es.mac, ', ')
                FROM equipo_series es
                WHERE es.equipo_id = e.id
                  AND COALESCE(es.mac, '') <> ''
            ), '') AS macs_registradas,
            COALESCE((
                SELECT COUNT(*)
                FROM equipo_series es
                WHERE es.equipo_id = e.id
            ), 0) AS total_series,
            COALESCE((
                SELECT COUNT(*)
                FROM equipo_series es
                WHERE es.equipo_id = e.id
                  AND es.estado = 'EN_STOCK'
            ), 0) AS series_en_stock
        FROM equipos e
        WHERE 1=1
    """
    params = []
    if search_query:
        query += """
            AND (
                e.descripcion LIKE ?
                OR e.sku LIKE ?
                OR e.mac LIKE ?
                OR e.marca LIKE ?
                OR e.categoria LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM equipo_series es
                    WHERE es.equipo_id = e.id
                      AND (es.serial LIKE ? OR es.mac LIKE ?)
                )
            )
        """
        like = f'%{search_query}%'
        params.extend([like, like, like, like, like, like, like])
    if categoria_filter:
        query += ' AND e.categoria = ?'
        params.append(categoria_filter)
    if estado_filter:
        query += ' AND e.estado = ?'
        params.append(normalize_estado(estado_filter))

    query += ' ORDER BY e.id DESC'
    equipos_rows = conn.execute(query, params).fetchall()
    equipos = []
    for e in equipos_rows:
        d = dict(e)
        d['ubicacion_display'] = resumen_ubicacion_equipo(conn, e)
        equipos.append(d)

    total_stock = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Stock"').fetchone()[0] or 0
    en_revision = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Revision"').fetchone()[0] or 0
    critico = conn.execute("""
        SELECT COUNT(*) FROM equipos
        WHERE estado = 'En Stock'
        AND cantidad <= CASE WHEN stock_minimo > 0 THEN stock_minimo ELSE 5 END
    """).fetchone()[0] or 0

    categorias_db = conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()
    conn.close()
    return render_template(
        'index.html', equipos=equipos, total_stock=total_stock,
        en_revision=en_revision, critico=critico,
        search_query=search_query, categoria_filter=categoria_filter,
        estado_filter=estado_filter, categorias_db=categorias_db,
        estados=ESTADOS_EQUIPO
    )





@app.route('/api/catalogos')
def api_catalogos():
    conn = get_db_connection()
    payload = get_catalogos_payload(conn)
    conn.close()
    return jsonify(payload)


@app.route('/api/marcas')
def api_marcas():
    categoria = clean_text(request.args.get('categoria'))
    conn = get_db_connection()
    if categoria:
        rows = conn.execute('''
            SELECT m.id, m.nombre
            FROM marcas m
            INNER JOIN categoria_marca cm ON cm.marca = m.nombre
            WHERE cm.categoria = ?
            ORDER BY m.nombre
        ''', (categoria,)).fetchall()
    else:
        rows = conn.execute('SELECT id, nombre FROM marcas ORDER BY nombre').fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route('/api/modelos')
def api_modelos():
    categoria = clean_text(request.args.get('categoria'))
    marca = clean_text(request.args.get('marca'))
    conn = get_db_connection()
    query = 'SELECT id, nombre, categoria, marca FROM modelos WHERE 1=1'
    params = []
    if categoria:
        query += ' AND categoria = ?'
        params.append(categoria)
    if marca:
        query += ' AND marca = ?'
        params.append(marca)
    rows = conn.execute(query + ' ORDER BY nombre', params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route('/api/productos')
def api_productos():
    categoria = clean_text(request.args.get('categoria'))
    marca = clean_text(request.args.get('marca'))
    modelo = clean_text(request.args.get('modelo'))
    conn = get_db_connection()
    query = '''
        SELECT id, categoria, marca, descripcion, sku, mac, cantidad, estado, COALESCE(control_stock, 'CANTIDAD') AS control_stock
        FROM equipos
        WHERE estado = 'En Stock' AND cantidad > 0
    '''
    params = []
    if categoria:
        query += ' AND categoria = ?'
        params.append(categoria)
    if marca:
        query += ' AND marca = ?'
        params.append(marca)
    if modelo:
        query += ' AND descripcion = ?'
        params.append(modelo)
    rows = conn.execute(query + ' ORDER BY descripcion, marca, sku', params).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route('/api/series')
def api_series():
    equipo_id = safe_int(request.args.get('equipo_id'))
    estado = clean_text(request.args.get('estado')) or 'EN_STOCK'
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, equipo_id, serial, mac, estado, guia_id
        FROM equipo_series
        WHERE equipo_id = ?
          AND estado = ?
        ORDER BY serial
    """, (equipo_id, estado)).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route('/ingreso_series', methods=['GET', 'POST'])
def ingreso_series():
    conn = get_db_connection()
    if request.method == 'POST':
        categoria = clean_text(request.form.get('categoria'))
        marca = clean_text(request.form.get('marca'))
        descripcion = clean_text(request.form.get('descripcion'))
        cantidad_esperada = safe_int(request.form.get('cantidad_esperada'))
        observaciones = clean_text(request.form.get('observaciones'))
        series = parse_seriales_text(request.form.get('series'))

        errores = []
        if not categoria or not marca or not descripcion:
            errores.append('Seleccione categoria, marca y modelo.')
        if not catalog_exists(conn, 'categorias', categoria):
            errores.append('La categoria seleccionada no existe.')
        if not catalog_exists(conn, 'marcas', marca):
            errores.append('La marca seleccionada no existe.')
        if categoria and marca and not relacion_categoria_marca_exists(conn, categoria, marca):
            errores.append('La marca no esta relacionada con la categoria seleccionada.')
        if cantidad_esperada <= 0:
            errores.append('La cantidad esperada debe ser mayor a cero.')
        if len(series) == 0:
            errores.append('Ingrese al menos una serie.')
        if cantidad_esperada > 0 and len(series) != cantidad_esperada:
            errores.append(f'Cantidad esperada {cantidad_esperada}, pero se ingresaron {len(series)} series.')

        seriales_texto = [x['serial'] for x in series]
        if len(seriales_texto) != len(set(s.lower() for s in seriales_texto)):
            errores.append('Hay series duplicadas en el listado ingresado.')
        for item in series:
            if item['mac'] and not validar_mac(item['mac']):
                errores.append(f"MAC invalida para la serie {item['serial']}.")

        if seriales_texto:
            placeholders = ','.join(['?'] * len(seriales_texto))
            existentes = conn.execute(f"""
                SELECT serial
                FROM equipo_series
                WHERE lower(serial) IN ({placeholders})
            """, tuple(x.lower() for x in seriales_texto)).fetchall()
            if existentes:
                errores.append('Ya existen estas series: ' + ', '.join([r['serial'] for r in existentes]))

        if errores:
            for e in errores:
                flash(e, 'danger')
            conn.close()
            return redirect(url_for('ingreso_series'))

        try:
            ensure_modelo(conn, descripcion, categoria, marca)
            equipo = get_or_create_equipo_base(conn, categoria, marca, descripcion, observaciones)
            stock_anterior = equipo['cantidad']

            for item in series:
                conn.execute("""
                    INSERT INTO equipo_series (
                        equipo_id, serial, mac, estado, ubicacion_actual, observaciones, fecha_actualizacion
                    )
                    VALUES (?, ?, ?, 'EN_STOCK', ?, ?, CURRENT_TIMESTAMP)
                """, (equipo['id'], item['serial'], item['mac'], UBIC_ALMACEN, observaciones))

            stock_nuevo = stock_anterior + len(series)
            conn.execute("""
                UPDATE equipos
                SET cantidad = ?, control_stock = 'SERIAL', estado = 'En Stock',
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (stock_nuevo, equipo['id']))

            registrar_movimiento(
                conn, equipo['id'], 'INGRESO', len(series), stock_anterior, stock_nuevo,
                referencia='ING-SERIES', observaciones=f'Ingreso serializado: {len(series)} unidad(es). {observaciones}'
            )
            conn.commit()
            flash(f'Ingreso serializado correcto: {len(series)} serie(s) agregada(s).', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            conn.rollback()
            flash(f'Error registrando series: {e}', 'danger')
            return redirect(url_for('ingreso_series'))
        finally:
            conn.close()

    catalogos = get_catalogos_payload(conn)
    conn.close()
    return render_template('ingreso_series.html', catalogos=catalogos)


@app.route('/ingresos', methods=['GET', 'POST'])
def ingresos():
    conn = get_db_connection()
    if request.method == 'POST':
        categoria = clean_text(request.form.get('categoria'))
        marca = clean_text(request.form.get('marca'))
        descripcion = clean_text(request.form.get('descripcion'))
        sku = clean_text(request.form.get('sku'))
        mac = clean_text(request.form.get('mac'))
        cantidad = safe_int(request.form.get('cantidad'))
        stock_minimo = safe_int(request.form.get('stock_minimo'))
        estado = normalize_estado(request.form.get('estado'))
        observaciones = clean_text(request.form.get('observaciones'))

        errores = []
        if not catalog_exists(conn, 'categorias', categoria):
            errores.append('La categoria seleccionada no existe.')
        if not catalog_exists(conn, 'marcas', marca):
            errores.append('La marca seleccionada no existe.')
        if categoria and marca and not relacion_categoria_marca_exists(conn, categoria, marca):
            errores.append('La marca seleccionada no esta asociada a esa categoria.')
        if not descripcion:
            errores.append('Debe seleccionar un modelo o descripcion.')
        elif not modelo_catalog_exists(conn, descripcion, categoria, marca):
            errores.append('El modelo seleccionado no pertenece a la categoria y marca indicadas.')
        if cantidad <= 0:
            errores.append('La cantidad debe ser mayor a cero.')
        if stock_minimo < 0:
            errores.append('El stock minimo no puede ser negativo.')
        if estado not in ESTADOS_EQUIPO:
            errores.append('El estado seleccionado no es valido.')
        if not validar_mac(mac):
            errores.append('La direccion MAC no tiene un formato valido.')

        # Si se informa SKU/Serie o MAC, se considera unidad serializada.
        # Para varios equipos serializados usa Ingreso Series: una serie por linea.
        if (sku or mac) and cantidad != 1:
            errores.append('Si ingresas SKU/Serie o MAC, la cantidad debe ser 1. Para varios equipos usa Ingreso Series.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.close()
            return redirect(url_for('ingresos'))

        try:
            ensure_modelo(conn, descripcion, categoria, marca)

            if sku or mac:
                serial = sku or f'MAC-{mac}'
                existente_serie = conn.execute(
                    'SELECT id FROM equipo_series WHERE lower(serial) = lower(?) LIMIT 1',
                    (serial,)
                ).fetchone()
                if existente_serie:
                    flash('Ya existe una unidad registrada con esa serie/MAC.', 'warning')
                    conn.close()
                    return redirect(url_for('ingresos'))

                equipo = get_or_create_equipo_base(conn, categoria, marca, descripcion, observaciones)
                stock_anterior = safe_int(equipo['cantidad'])
                conn.execute("""
                    INSERT INTO equipo_series (
                        equipo_id, serial, mac, estado, ubicacion_actual, observaciones, fecha_actualizacion
                    )
                    VALUES (?, ?, ?, 'EN_STOCK', ?, ?, CURRENT_TIMESTAMP)
                """, (equipo['id'], serial, mac, UBIC_ALMACEN, observaciones))
                stock_nuevo = recalcular_stock_serial(conn, equipo['id'])
                conn.execute("""
                    UPDATE equipos
                    SET sku = COALESCE(NULLIF(sku, ''), ?),
                        mac = COALESCE(NULLIF(mac, ''), ?),
                        stock_minimo = CASE WHEN ? > COALESCE(stock_minimo, 0) THEN ? ELSE COALESCE(stock_minimo, 0) END,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (sku, mac, stock_minimo, stock_minimo, equipo['id']))
                registrar_movimiento(
                    conn,
                    equipo['id'],
                    'INGRESO',
                    1,
                    stock_anterior,
                    stock_nuevo,
                    referencia=f'ING-SN-{equipo["id"]:06d}',
                    observaciones=f'Ingreso de unidad serializada: {serial}.'
                )
                conn.commit()
                conn.close()
                flash('Unidad serializada registrada correctamente sin duplicar el producto base.', 'success')
                return redirect(url_for('index'))

            # Regla nueva: si el producto base ya existe por Categoria + Marca + Modelo,
            # NO se crea otra fila. Solo se incrementa stock y se guarda movimiento.
            equipo, creado = get_or_create_producto_cantidad(
                conn, categoria, marca, descripcion, sku, mac, observaciones
            )

            stock_anterior = safe_int(equipo['cantidad'])
            stock_nuevo = stock_anterior + cantidad

            nuevo_estado = estado_operativo_por_stock(stock_nuevo, estado)
            if estado == 'Baja':
                nuevo_estado = 'En Stock' if stock_nuevo > 0 else 'Sin Stock'

            conn.execute("""
                UPDATE equipos
                SET cantidad = ?,
                    estado = ?,
                    stock_minimo = CASE
                        WHEN ? > COALESCE(stock_minimo, 0) THEN ?
                        ELSE COALESCE(stock_minimo, 0)
                    END,
                    control_stock = 'CANTIDAD',
                    ubicacion_actual = ?,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (stock_nuevo, nuevo_estado, stock_minimo, stock_minimo, UBIC_ALMACEN, equipo['id']))

            registrar_movimiento(
                conn,
                equipo['id'],
                'INGRESO',
                cantidad,
                stock_anterior,
                stock_nuevo,
                referencia=f'ING-{equipo["id"]:06d}',
                observaciones=(
                    'Ingreso acumulado sobre producto existente.'
                    if not creado else
                    'Ingreso inicial de producto.'
                )
            )

            consolidados = consolidar_productos_duplicados(conn)

            conn.commit()
            conn.close()

            if creado:
                flash('Producto creado e ingreso registrado correctamente.', 'success')
            else:
                flash('Producto existente actualizado: se incremento el stock sin crear duplicado.', 'success')

            if consolidados:
                flash(f'Se consolidaron {consolidados} producto(s) duplicado(s) existentes.', 'info')

            return redirect(url_for('index'))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f'Error registrando ingreso: {e}', 'danger')
            return redirect(url_for('ingresos'))

    catalogos = get_catalogos_payload(conn)
    conn.close()
    return render_template(
        'ingresos.html', catalogos=catalogos, estados=ESTADOS_EQUIPO
    )


@app.route('/salidas', methods=['GET', 'POST'])
def salidas():
    conn = get_db_connection()

    if request.method == 'POST':
        equipo_id = safe_int(request.form.get('equipo_id'))
        personal = clean_text(request.form.get('personal'))
        destino = clean_text(request.form.get('destino'))
        cantidad_salida = safe_int(request.form.get('cantidad'))
        observaciones = clean_text(request.form.get('observaciones'))

        errores = []
        equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
        if not equipo:
            errores.append('El equipo seleccionado no existe.')
        if not catalog_exists(conn, 'personal', personal):
            errores.append('El personal seleccionado no existe.')
        if not catalog_exists(conn, 'edificios', destino):
            errores.append('El destino seleccionado no existe.')
        if cantidad_salida <= 0:
            errores.append('La cantidad debe ser mayor a cero.')
        if equipo and normalize_estado(equipo['estado']) != 'En Stock':
            errores.append('Solo se pueden retirar equipos con estado En Stock.')
        if equipo and ('control_stock' in equipo.keys()) and (equipo['control_stock'] or 'CANTIDAD') == 'SERIAL':
            errores.append('Los equipos serializados deben salir por Guia seleccionando las series exactas.')
        if equipo and cantidad_salida > equipo['cantidad']:
            errores.append('Stock insuficiente para el despacho.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.close()
            return redirect(url_for('salidas'))

        stock_anterior = equipo['cantidad']
        stock_nuevo = stock_anterior - cantidad_salida
        actualizar_equipo_stock_estado(conn, equipo_id, stock_nuevo, equipo['estado'])
        if stock_nuevo <= 0:
            conn.execute('UPDATE equipos SET ubicacion_actual = ? WHERE id = ?', (UBIC_SIN_STOCK, equipo_id))
        cursor = conn.execute('''
            INSERT INTO salidas (equipo_id, personal, destino, cantidad, observaciones)
            VALUES (?, ?, ?, ?, ?)
        ''', (equipo_id, personal, destino, cantidad_salida, observaciones))
        salida_id = cursor.lastrowid
        registrar_movimiento(
            conn, equipo_id, 'SALIDA_DIRECTA', cantidad_salida, stock_anterior, stock_nuevo,
            referencia=f'SD-{salida_id:06d}', observaciones=f'Despacho directo a {personal} / {destino}.'
        )
        conn.commit()
        conn.close()
        flash('Despacho registrado correctamente.', 'success')
        return redirect(url_for('salidas'))

    f_personal = request.args.get('f_personal', '')
    f_destino = request.args.get('f_destino', '')
    f_fecha = request.args.get('f_fecha', '')

    query = '''
        SELECT s.id, datetime(s.fecha, 'localtime') as fecha_local,
               s.personal, s.destino, s.cantidad, s.observaciones,
               e.marca, e.descripcion, e.sku
        FROM salidas s
        JOIN equipos e ON s.equipo_id = e.id
        WHERE 1=1
    '''
    params = []
    if f_personal:
        query += ' AND s.personal = ?'
        params.append(f_personal)
    if f_destino:
        query += ' AND s.destino = ?'
        params.append(f_destino)
    if f_fecha:
        query += " AND strftime('%Y-%m-%d', datetime(s.fecha, 'localtime')) = ?"
        params.append(f_fecha)

    historial = conn.execute(query + ' ORDER BY s.id DESC', params).fetchall()
    equipos = conn.execute('''
        SELECT id, marca, descripcion, sku, cantidad
        FROM equipos
        WHERE cantidad > 0 AND estado = 'En Stock'
          AND COALESCE(control_stock, 'CANTIDAD') = 'CANTIDAD'
        ORDER BY descripcion
    ''').fetchall()
    personal_db = conn.execute('SELECT nombre FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    conn.close()

    return render_template(
        'salidas.html', equipos=equipos, personal=personal_db,
        edificios=edificios, historial=historial,
        f_personal=f_personal, f_destino=f_destino, f_fecha=f_fecha
    )


@app.route('/guias')
def guias():
    conn = get_db_connection()
    personal = conn.execute('SELECT * FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    equipos = conn.execute('''
        SELECT id, categoria, marca, descripcion, sku, mac, cantidad, estado, COALESCE(control_stock, 'CANTIDAD') AS control_stock,
               cantidad AS stock_disponible
        FROM equipos
        WHERE cantidad > 0 AND estado = 'En Stock'
        ORDER BY categoria, marca, descripcion, sku
    ''').fetchall()
    catalogos = get_catalogos_payload(conn)
    equipos_json = rows_to_dicts(equipos)
    conn.close()
    return render_template(
        'guias.html', personal=personal, edificios=edificios,
        equipos=equipos, equipos_json=equipos_json, catalogos=catalogos
    )

@app.route('/guardar_guia', methods=['POST'])
def guardar_guia():
    conn = get_db_connection()
    try:
        personal = clean_text(request.form.get('personal'))
        destino = clean_text(request.form.get('destino'))
        cargo = clean_text(request.form.get('cargo'))
        proyecto = clean_text(request.form.get('proyecto'))
        entregado_por = clean_text(request.form.get('entregado_por'))
        recibido_por = clean_text(request.form.get('recibido_por'))
        aprobado_por = clean_text(request.form.get('aprobado_por'))
        observaciones = clean_text(request.form.get('observaciones'))

        errores = []
        if not catalog_exists(conn, 'personal', personal):
            errores.append('El solicitante seleccionado no existe.')
        if not catalog_exists(conn, 'edificios', destino):
            errores.append('El destino seleccionado no existe.')

        productos, error = parse_productos_json(request.form.get('productos'))
        if error:
            errores.append(error)

        equipos_validados = {}
        if productos:
            equipos_validados, errores_productos = validar_productos_para_guia(conn, productos)
            if errores_productos:
                errores.extend(errores_productos)

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.rollback()
            return redirect(url_for('guias'))

        cursor = conn.execute("""
            INSERT INTO guias_salida (
                personal, destino, cargo, proyecto,
                entregado_por, recibido_por, aprobado_por, observaciones,
                estado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVA')
        """, (
            personal, destino, cargo, proyecto,
            entregado_por, recibido_por, aprobado_por, observaciones
        ))
        guia_id = cursor.lastrowid
        referencia = guia_codigo(guia_id)

        for item in productos:
            equipo_id = item['id']
            cantidad = item['cantidad']
            equipo = equipos_validados[equipo_id]
            stock_anterior = equipo['cantidad']
            stock_nuevo = stock_anterior - cantidad

            cursor_det = conn.execute("""
                INSERT INTO guia_detalle (guia_id, equipo_id, cantidad)
                VALUES (?, ?, ?)
            """, (guia_id, equipo_id, cantidad))
            guia_detalle_id = cursor_det.lastrowid

            if (equipo['control_stock'] or 'CANTIDAD') == 'SERIAL' or item.get('control_stock') == 'SERIAL':
                for serie_id in item.get('series_ids') or []:
                    conn.execute("""
                        UPDATE equipo_series
                        SET estado = 'ENTREGADO', guia_id = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                        WHERE id = ? AND equipo_id = ? AND estado = 'EN_STOCK'
                    """, (guia_id, serie_id, equipo_id))
                    conn.execute("""
                        INSERT INTO guia_detalle_series (guia_detalle_id, serie_id)
                        VALUES (?, ?)
                    """, (guia_detalle_id, serie_id))
            actualizar_equipo_stock_estado(conn, equipo_id, stock_nuevo, equipo['estado'])

            registrar_movimiento(
                conn, equipo_id, 'SALIDA_GUIA', cantidad, stock_anterior, stock_nuevo,
                guia_id=guia_id, referencia=referencia,
                observaciones=f'Guia emitida para {personal} / {destino}.'
            )

        set_ubicacion_series_de_guia(conn, guia_id)
        conn.commit()
        flash(f'Guia {referencia} creada correctamente.', 'success')
        return redirect('/listar_guias')

    except Exception as e:
        conn.rollback()
        flash(f'Error guardando guia: {e}', 'danger')
        return redirect(url_for('guias'))
    finally:
        conn.close()


def obtener_series_ids_de_guia(conn, guia_id):
    """Devuelve los ids de series actualmente asociadas a una guia."""
    rows = conn.execute("""
        SELECT gds.serie_id
        FROM guia_detalle_series gds
        JOIN guia_detalle gd ON gd.id = gds.guia_detalle_id
        WHERE gd.guia_id = ?
    """, (guia_id,)).fetchall()
    return [r['serie_id'] for r in rows]


def quitar_series_de_guia(conn, guia_id, serie_ids, referencia, observacion_base):
    """Quita series especificas de una guia y reintegra solo esas unidades al stock."""
    serie_ids = [safe_int(x) for x in (serie_ids or []) if safe_int(x) > 0]
    if not serie_ids:
        return 0

    placeholders = ','.join(['?'] * len(serie_ids))
    rows = conn.execute(f"""
        SELECT gds.id AS rel_id, gds.guia_detalle_id, gds.serie_id,
               gd.equipo_id, es.serial, es.estado
        FROM guia_detalle_series gds
        JOIN guia_detalle gd ON gd.id = gds.guia_detalle_id
        JOIN equipo_series es ON es.id = gds.serie_id
        WHERE gd.guia_id = ? AND gds.serie_id IN ({placeholders})
    """, [guia_id] + serie_ids).fetchall()

    por_equipo = defaultdict(int)
    for row in rows:
        por_equipo[row['equipo_id']] += 1
        conn.execute('DELETE FROM guia_detalle_series WHERE id = ?', (row['rel_id'],))
        conn.execute("""
            UPDATE equipo_series
            SET estado = 'EN_STOCK', guia_id = NULL, ubicacion_actual = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (UBIC_ALMACEN, row['serie_id'],))
        conn.execute("""
            UPDATE guia_detalle
            SET cantidad = CASE WHEN cantidad > 0 THEN cantidad - 1 ELSE 0 END
            WHERE id = ?
        """, (row['guia_detalle_id'],))

    for equipo_id, cantidad in por_equipo.items():
        equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
        if not equipo:
            continue
        stock_anterior = safe_int(equipo['cantidad'])
        stock_nuevo = stock_anterior + cantidad
        actualizar_equipo_stock_estado(conn, equipo_id, stock_nuevo)
        registrar_movimiento(
            conn, equipo_id, 'DEVOLUCION_GUIA', cantidad,
            stock_anterior, stock_nuevo, guia_id=guia_id, referencia=referencia,
            observaciones=observacion_base
        )

    conn.execute("DELETE FROM guia_detalle WHERE guia_id = ? AND cantidad <= 0", (guia_id,))
    return len(rows)



@app.route('/actualizar_guia/<int:id>', methods=['POST'])
def actualizar_guia(id):
    conn = get_db_connection()
    try:
        guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
        if not guia:
            flash('La guia no existe.', 'danger')
            return redirect('/listar_guias')
        if guia['estado'] == 'ANULADA':
            flash('No se puede editar una guia anulada.', 'warning')
            return redirect(f'/guia/{id}')

        productos, error = parse_productos_json(request.form.get('productos'))
        if error:
            flash(error, 'danger')
            return redirect(f'/editar_guia/{id}')

        referencia = guia_codigo(id)

        detalle_actual = conn.execute("""
            SELECT gd.id AS guia_detalle_id, gd.equipo_id, gd.cantidad,
                   e.cantidad AS stock_actual,
                   COALESCE(e.control_stock, 'CANTIDAD') AS control_stock
            FROM guia_detalle gd
            JOIN equipos e ON e.id = gd.equipo_id
            WHERE gd.guia_id = ?
        """, (id,)).fetchall()

        old_map = defaultdict(int)
        for item in detalle_actual:
            old_map[item['equipo_id']] += safe_int(item['cantidad'])
        old_series_ids = obtener_series_ids_de_guia(conn, id)

        equipos_validados, errores_productos = validar_productos_para_guia(
            conn, productos, old_map=old_map, old_series_ids=old_series_ids
        )
        if errores_productos:
            for error in errores_productos:
                flash(error, 'danger')
            raise ValueError('No se pudo validar el nuevo detalle de la guia. No se modifico el detalle anterior.')

        # Recién despues de validar el nuevo detalle, se revierte el detalle anterior.
        # Así evitamos que un error de serial/stock deje la guia sin productos.
        for item in detalle_actual:
            stock_anterior = item['stock_actual']
            stock_nuevo = stock_anterior + item['cantidad']
            actualizar_equipo_stock_estado(conn, item['equipo_id'], stock_nuevo)
            registrar_movimiento(
                conn, item['equipo_id'], 'DEVOLUCION_GUIA', item['cantidad'],
                stock_anterior, stock_nuevo, guia_id=id, referencia=referencia,
                observaciones='Edicion de guia: reverso temporal del detalle anterior.'
            )
            if item['control_stock'] == 'SERIAL':
                conn.execute("""
                    UPDATE equipo_series
                    SET estado = 'EN_STOCK', guia_id = NULL, ubicacion_actual = ?,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id IN (
                        SELECT serie_id FROM guia_detalle_series WHERE guia_detalle_id = ?
                    )
                """, (UBIC_ALMACEN, item['guia_detalle_id'],))

        conn.execute("""
            DELETE FROM guia_detalle_series
            WHERE guia_detalle_id IN (SELECT id FROM guia_detalle WHERE guia_id = ?)
        """, (id,))
        conn.execute('DELETE FROM guia_detalle WHERE guia_id = ?', (id,))

        conn.execute("""
            UPDATE guias_salida
            SET personal = ?, destino = ?, cargo = ?, proyecto = ?,
                entregado_por = ?, recibido_por = ?, aprobado_por = ?,
                observaciones = ?
            WHERE id = ?
        """, (
            clean_text(request.form.get('personal')),
            clean_text(request.form.get('destino')),
            clean_text(request.form.get('cargo')),
            clean_text(request.form.get('proyecto')),
            clean_text(request.form.get('entregado_por')),
            clean_text(request.form.get('recibido_por')),
            clean_text(request.form.get('aprobado_por')),
            clean_text(request.form.get('observaciones')),
            id
        ))

        for item in productos:
            equipo_id = item['id']
            cantidad = item['cantidad']
            equipo = equipos_validados[equipo_id]
            equipo_actual = conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
            stock_anterior = equipo_actual['cantidad'] if equipo_actual else equipo['cantidad']
            stock_nuevo = stock_anterior - cantidad
            cursor_det = conn.execute("""
                INSERT INTO guia_detalle (guia_id, equipo_id, cantidad)
                VALUES (?, ?, ?)
            """, (id, equipo_id, cantidad))
            guia_detalle_id = cursor_det.lastrowid

            if (equipo['control_stock'] or 'CANTIDAD') == 'SERIAL' or item.get('control_stock') == 'SERIAL':
                for serie_id in item.get('series_ids') or []:
                    cur = conn.execute("""
                        UPDATE equipo_series
                        SET estado = 'ENTREGADO', guia_id = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                        WHERE id = ? AND equipo_id = ? AND estado = 'EN_STOCK'
                    """, (id, serie_id, equipo_id))
                    if cur.rowcount != 1:
                        raise ValueError('Una serie dejo de estar disponible durante la actualizacion.')
                    conn.execute("""
                        INSERT INTO guia_detalle_series (guia_detalle_id, serie_id)
                        VALUES (?, ?)
                    """, (guia_detalle_id, serie_id))
            actualizar_equipo_stock_estado(conn, equipo_id, stock_nuevo, equipo['estado'])
            registrar_movimiento(
                conn, equipo_id, 'SALIDA_GUIA', cantidad, stock_anterior, stock_nuevo,
                guia_id=id, referencia=referencia,
                observaciones='Edicion de guia: nuevo detalle aplicado.'
            )

        set_ubicacion_series_de_guia(conn, id)
        conn.commit()
        flash(f'Guia {referencia} actualizada correctamente.', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando guia: {e}', 'danger')
    finally:
        conn.close()

    return redirect(f'/guia/{id}')


@app.route('/guia/<int:id>')
def ver_guia(id):
    conn = get_db_connection()
    guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
    if not guia:
        conn.close()
        flash('La guia no existe.', 'danger')
        return redirect('/listar_guias')

    detalle = conn.execute('''
        SELECT gd.id AS guia_detalle_id, gd.equipo_id, gd.cantidad, e.marca, e.descripcion, e.sku, e.mac, COALESCE(e.control_stock, 'CANTIDAD') AS control_stock
        FROM guia_detalle gd
        INNER JOIN equipos e ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ORDER BY e.descripcion
    ''', (id,)).fetchall()

    movimientos = conn.execute('''
        SELECT m.*, e.marca, e.descripcion
        FROM movimientos m
        JOIN equipos e ON e.id = m.equipo_id
        WHERE m.guia_id = ?
        ORDER BY m.id DESC
    ''', (id,)).fetchall()
    series_por_detalle, _series_por_equipo = obtener_series_de_guia(conn, id)
    conn.close()
    return render_template('ver_guia.html', guia=guia, detalle=detalle, movimientos=movimientos, series_por_detalle=series_por_detalle)


def actualizar_series_detalle_guia(conn, guia_id, guia_detalle_id, equipo_id, series_texto, cantidad_esperada):
    """Actualiza las series vinculadas a una linea de guia sin cambiar stock."""
    series = parse_seriales_text(series_texto)
    seriales_vistos = set()
    errores = []

    for item in series:
        serial_norm = item['serial'].strip().lower()
        if not serial_norm:
            errores.append('Existe una linea sin serial.')
            continue
        if serial_norm in seriales_vistos:
            errores.append(f"Serial duplicado en el formulario: {item['serial']}")
        seriales_vistos.add(serial_norm)
        if item.get('mac') and not validar_mac(item.get('mac')):
            errores.append(f"MAC invalida para el serial {item['serial']}: {item.get('mac')}")

    if len(series) != int(cantidad_esperada or 0):
        errores.append(
            f'El producto del detalle #{guia_detalle_id} tiene cantidad {cantidad_esperada}, '
            f'pero se ingresaron {len(series)} serial(es). Deben coincidir para no romper stock.'
        )

    if errores:
        return errores

    guia_row = conn.execute('SELECT destino FROM guias_salida WHERE id = ?', (guia_id,)).fetchone()
    ubic_destino = ubic_edificio(guia_row['destino'] if guia_row else '')

    series_actuales = conn.execute(
        'SELECT serie_id FROM guia_detalle_series WHERE guia_detalle_id = ?',
        (guia_detalle_id,)
    ).fetchall()
    ids_actuales = [r['serie_id'] for r in series_actuales]

    if ids_actuales:
        conn.execute(
            f"""
            UPDATE equipo_series
            SET estado = 'EN_STOCK', guia_id = NULL, ubicacion_actual = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id IN ({','.join(['?'] * len(ids_actuales))})
              AND guia_id = ?
            """,
            [UBIC_ALMACEN] + ids_actuales + [guia_id]
        )

    conn.execute('DELETE FROM guia_detalle_series WHERE guia_detalle_id = ?', (guia_detalle_id,))

    for item in series:
        serial = clean_text(item.get('serial'))
        mac = clean_text(item.get('mac'))

        existente = conn.execute(
            'SELECT * FROM equipo_series WHERE lower(serial) = lower(?) LIMIT 1',
            (serial,)
        ).fetchone()

        if existente:
            if existente['equipo_id'] != equipo_id:
                return [f"El serial {serial} ya existe, pero pertenece a otro producto."]
            if existente['guia_id'] not in (None, guia_id):
                return [f"El serial {serial} ya esta asociado a otra guia."]

            serie_id = existente['id']
            conn.execute(
                """
                UPDATE equipo_series
                SET mac = CASE WHEN ? <> '' THEN ? ELSE mac END,
                    estado = 'ENTREGADO',
                    guia_id = ?,
                    ubicacion_actual = ?,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (mac, mac, guia_id, ubic_destino, serie_id)
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO equipo_series (
                    equipo_id, serial, mac, estado, guia_id, ubicacion_actual, observaciones, fecha_actualizacion
                )
                VALUES (?, ?, ?, 'ENTREGADO', ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (equipo_id, serial, mac, guia_id, ubic_destino, f'Registrado manualmente desde guia {guia_codigo(guia_id)}')
            )
            serie_id = cursor.lastrowid

        conn.execute(
            'INSERT INTO guia_detalle_series (guia_detalle_id, serie_id) VALUES (?, ?)',
            (guia_detalle_id, serie_id)
        )

    conn.execute(
        "UPDATE equipos SET control_stock = 'SERIAL', fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
        (equipo_id,)
    )

    return []


@app.route('/guia/<int:id>/series', methods=['GET', 'POST'])
def actualizar_series_guia(id):
    conn = get_db_connection()
    try:
        guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
        if not guia:
            flash('La guia no existe.', 'danger')
            return redirect('/listar_guias')

        detalle = conn.execute("""
            SELECT gd.id AS guia_detalle_id,
                   gd.equipo_id,
                   gd.cantidad,
                   e.categoria,
                   e.marca,
                   e.descripcion,
                   e.sku,
                   e.mac,
                   COALESCE(e.control_stock, 'CANTIDAD') AS control_stock
            FROM guia_detalle gd
            JOIN equipos e ON e.id = gd.equipo_id
            WHERE gd.guia_id = ?
            ORDER BY e.categoria, e.marca, e.descripcion
        """, (id,)).fetchall()

        if request.method == 'POST':
            errores = []
            actualizados = 0

            for item in detalle:
                campo = f"series_{item['guia_detalle_id']}"
                texto = request.form.get(campo, '')
                if clean_text(texto):
                    err = actualizar_series_detalle_guia(
                        conn,
                        id,
                        item['guia_detalle_id'],
                        item['equipo_id'],
                        texto,
                        item['cantidad']
                    )
                    if err:
                        errores.extend(err)
                    else:
                        actualizados += 1

            if errores:
                conn.rollback()
                for error in errores:
                    flash(error, 'danger')
            else:
                conn.commit()
                flash(f'Seriales actualizados en {actualizados} detalle(s) de la guia {guia_codigo(id)}.', 'success')
                return redirect(url_for('ver_guia', id=id))

        series_por_detalle, _ = obtener_series_de_guia(conn, id)
        return render_template(
            'actualizar_series_guia.html',
            guia=guia,
            detalle=detalle,
            series_por_detalle=series_por_detalle
        )

    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando seriales de guia: {e}', 'danger')
        return redirect(url_for('ver_guia', id=id))
    finally:
        conn.close()


@app.route('/guia/<int:id>/quitar_serie/<int:serie_id>', methods=['POST'])
def quitar_serie_guia(id, serie_id):
    conn = get_db_connection()
    try:
        guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
        if not guia:
            flash('La guia no existe.', 'danger')
            return redirect('/listar_guias')
        if guia['estado'] == 'ANULADA':
            flash('No se puede modificar una guia anulada.', 'warning')
            return redirect(url_for('ver_guia', id=id))

        quitadas = quitar_series_de_guia(
            conn, id, [serie_id], guia_codigo(id),
            'Devolucion individual de serial desde la vista de guia.'
        )
        if quitadas <= 0:
            conn.rollback()
            flash('No se encontro ese serial dentro de la guia.', 'warning')
        else:
            conn.commit()
            flash('Serial quitado de la guia y reintegrado al stock correctamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error quitando serial de la guia: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('ver_guia', id=id))


@app.route('/series')
def listar_series():
    conn = get_db_connection()
    q = clean_text(request.args.get('q'))
    estado = clean_text(request.args.get('estado'))
    equipo_id = safe_int(request.args.get('equipo_id'))
    params = []
    where = ['1=1']
    if q:
        where.append('(es.serial LIKE ? OR es.mac LIKE ? OR e.descripcion LIKE ? OR e.marca LIKE ? OR e.categoria LIKE ?)')
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%'])
    if estado:
        where.append('es.estado = ?')
        params.append(estado)
    if equipo_id > 0:
        where.append('es.equipo_id = ?')
        params.append(equipo_id)

    series = conn.execute(f"""
        SELECT es.*, e.categoria, e.marca, e.descripcion,
               gs.id AS guia_actual_id, gs.personal, gs.destino
        FROM equipo_series es
        JOIN equipos e ON e.id = es.equipo_id
        LEFT JOIN guias_salida gs ON gs.id = es.guia_id
        WHERE {' AND '.join(where)}
        ORDER BY e.categoria, e.marca, e.descripcion, es.serial
        LIMIT 1000
    """, params).fetchall()
    conn.close()
    return render_template('series.html', series=series, q=q, estado=estado, equipo_id=equipo_id)


@app.route('/series/<int:serie_id>/eliminar', methods=['POST'])
def eliminar_serie(serie_id):
    conn = get_db_connection()
    try:
        serie = conn.execute("""
            SELECT es.*, e.marca, e.descripcion, e.cantidad AS stock_actual
            FROM equipo_series es
            JOIN equipos e ON e.id = es.equipo_id
            WHERE es.id = ?
        """, (serie_id,)).fetchone()
        if not serie:
            flash('La serie no existe.', 'danger')
            return redirect('/series')
        if serie['estado'] != 'EN_STOCK' or serie['guia_id']:
            flash('No se elimino la serie porque esta entregada/asociada a una guia. Primero quitela desde la guia.', 'warning')
            return redirect('/series')

        stock_anterior = safe_int(serie['stock_actual'])
        conn.execute('DELETE FROM equipo_series WHERE id = ?', (serie_id,))
        stock_nuevo = max(0, stock_anterior - 1)
        actualizar_equipo_stock_estado(conn, serie['equipo_id'], stock_nuevo)
        registrar_movimiento(
            conn, serie['equipo_id'], 'AJUSTE', 1,
            stock_anterior, stock_nuevo, referencia='SERIE-ELIMINADA',
            observaciones=f"Eliminacion individual de serial {serie['serial']} desde listado de series."
        )
        conn.commit()
        flash('Serie eliminada del stock correctamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error eliminando serie: {e}', 'danger')
    finally:
        conn.close()
    return redirect('/series')



@app.route('/eliminar_guia/<int:id>', methods=['POST'])
def eliminar_guia(id):
    conn = get_db_connection()
    try:
        guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
        if not guia:
            flash('La guia no existe.', 'danger')
            return redirect('/listar_guias')
        if guia['estado'] == 'ANULADA':
            flash('La guia ya estaba anulada. No se reintegro stock nuevamente.', 'warning')
            return redirect('/listar_guias')

        detalle = conn.execute("""
            SELECT gd.id AS guia_detalle_id, gd.equipo_id, gd.cantidad,
                   COALESCE(e.control_stock, 'CANTIDAD') AS control_stock
            FROM guia_detalle gd
            JOIN equipos e ON e.id = gd.equipo_id
            WHERE gd.guia_id = ?
        """, (id,)).fetchall()

        referencia = guia_codigo(id)
        for item in detalle:
            equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (item['equipo_id'],)).fetchone()
            if not equipo:
                continue
            stock_anterior = equipo['cantidad']
            stock_nuevo = stock_anterior + item['cantidad']
            actualizar_equipo_stock_estado(conn, item['equipo_id'], stock_nuevo)
            if item['control_stock'] == 'SERIAL':
                conn.execute("""
                    UPDATE equipo_series
                    SET estado = 'EN_STOCK', guia_id = NULL, ubicacion_actual = ?,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id IN (
                        SELECT serie_id FROM guia_detalle_series WHERE guia_detalle_id = ?
                    )
                """, (UBIC_ALMACEN, item['guia_detalle_id'],))
            registrar_movimiento(
                conn, item['equipo_id'], 'DEVOLUCION_GUIA', item['cantidad'],
                stock_anterior, stock_nuevo, guia_id=id, referencia=referencia,
                observaciones='Anulacion de guia: reintegro automatico al inventario.'
            )

        conn.execute("""
            UPDATE guias_salida
            SET estado = 'ANULADA', fecha_anulacion = CURRENT_TIMESTAMP,
                motivo_anulacion = ?
            WHERE id = ?
        """, ('Anulada desde el sistema.', id))
        conn.commit()
        flash(f'Guia {referencia} anulada. El stock y las series fueron reintegrados.', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Error anulando guia: {e}', 'danger')
    finally:
        conn.close()

    return redirect('/listar_guias')


@app.route('/listar_guias')
def listar_guias():
    conn = get_db_connection()
    guias = conn.execute('SELECT * FROM guias_salida ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('listar_guias.html', guias=guias)


@app.route('/editar_guia/<int:id>')
def editar_guia(id):
    conn = get_db_connection()
    guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
    if not guia:
        conn.close()
        flash('La guia no existe.', 'danger')
        return redirect('/listar_guias')
    if guia['estado'] == 'ANULADA':
        conn.close()
        flash('No se puede editar una guia anulada.', 'warning')
        return redirect(f'/guia/{id}')

    detalle = conn.execute('''
        SELECT gd.id AS guia_detalle_id, gd.equipo_id, gd.cantidad, e.descripcion, e.marca, e.categoria, e.sku, e.mac, COALESCE(e.control_stock, 'CANTIDAD') AS control_stock,
               e.cantidad AS stock_actual,
               e.cantidad + gd.cantidad AS stock_disponible
        FROM guia_detalle gd
        INNER JOIN equipos e ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ORDER BY e.categoria, e.marca, e.descripcion
    ''', (id,)).fetchall()
    personal = conn.execute('SELECT * FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    equipos = conn.execute('''
        SELECT e.id, e.categoria, e.marca, e.descripcion, e.sku, e.mac, e.estado, e.cantidad, COALESCE(e.control_stock, 'CANTIDAD') AS control_stock,
               COALESCE(gd.cantidad, 0) AS cantidad_en_guia,
               e.cantidad + COALESCE(gd.cantidad, 0) AS stock_disponible
        FROM equipos e
        LEFT JOIN guia_detalle gd
               ON gd.equipo_id = e.id AND gd.guia_id = ?
        WHERE (e.estado = 'En Stock' AND e.cantidad > 0)
           OR gd.equipo_id IS NOT NULL
        ORDER BY e.categoria, e.marca, e.descripcion, e.sku
    ''', (id,)).fetchall()
    catalogos = get_catalogos_payload(conn)
    equipos_json = rows_to_dicts(equipos)
    detalle_json = rows_to_dicts(detalle)
    _series_por_detalle, series_por_equipo = obtener_series_de_guia(conn, id)
    conn.close()

    return render_template(
        'editar_guia.html', guia=guia, detalle=detalle,
        personal=personal, edificios=edificios, equipos=equipos,
        equipos_json=equipos_json, detalle_json=detalle_json, catalogos=catalogos, series_por_equipo=series_por_equipo
    )

@app.route('/pdf_guia/<int:id>')
def pdf_guia(id):
    conn = get_db_connection()
    guia = conn.execute('SELECT * FROM guias_salida WHERE id = ?', (id,)).fetchone()
    if not guia:
        conn.close()
        flash('La guia no existe.', 'danger')
        return redirect('/listar_guias')

    detalle = conn.execute('''
        SELECT gd.id AS guia_detalle_id, gd.cantidad, e.marca, e.descripcion, e.sku,
               COALESCE(e.control_stock, 'CANTIDAD') AS control_stock
        FROM guia_detalle gd
        INNER JOIN equipos e ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ORDER BY e.descripcion
    ''', (id,)).fetchall()
    series_por_detalle, _series_por_equipo = obtener_series_de_guia(conn, id)
    conn.close()

    # ── Paleta de marca ─────────────────────────────────────────────────────
    C_RAIL    = colors.HexColor('#11151A')   # sidebar oscuro
    C_AMBER   = colors.HexColor('#D9790E')   # acento ámbar
    C_ROW_ALT = colors.HexColor('#F7F8FA')   # fila alterna (muy sutil)
    C_RULE    = colors.HexColor('#E2E6EB')   # líneas divisoras
    C_LABEL   = colors.HexColor('#6B7480')   # texto etiqueta gris
    C_WHITE   = colors.white
    C_BLACK   = colors.HexColor('#15191E')

    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import HRFlowable, KeepTogether, PageBreak
    from reportlab.platypus.flowables import Flowable

    # ── Flowable: membrete (logo + datos de la guía) ────────────────────────
    class Membrete(Flowable):
        def __init__(self, codigo, estado, ancho):
            Flowable.__init__(self)
            self.codigo  = codigo
            self.estado  = estado
            self.ancho   = ancho
            self.height  = 2.4 * cm

        def draw(self):
            c = self.canv
            w = self.ancho
            h = self.height

            # Fondo rail oscuro para la banda del logo
            c.setFillColor(C_RAIL)
            c.rect(0, h - 1.45*cm, w * 0.4, 1.45*cm, fill=1, stroke=0)

            # Cuadro "PS"
            c.setFillColor(C_AMBER)
            c.setStrokeColor(C_AMBER)
            c.roundRect(0.35*cm, h - 1.18*cm, 0.72*cm, 0.72*cm, 0.1*cm, fill=0, stroke=1)
            c.setFont('Helvetica-Bold', 7.5)
            c.setFillColor(C_AMBER)
            c.drawCentredString(0.71*cm, h - 0.82*cm, 'PS')

            # Nombre del sistema
            c.setFont('Helvetica-Bold', 9.5)
            c.setFillColor(C_WHITE)
            c.drawString(1.22*cm, h - 0.78*cm, 'Portero Seguro')
            c.setFont('Helvetica', 6)
            c.setFillColor(colors.HexColor('#8B93A1'))
            c.drawString(1.22*cm, h - 1.1*cm, 'CONTROL DE ACTIVOS')

            # Línea ámbar vertical separadora
            c.setStrokeColor(C_AMBER)
            c.setLineWidth(1.5)
            c.line(w * 0.4 + 0.3*cm, h - 1.45*cm, w * 0.4 + 0.3*cm, h)

            # Título del documento
            c.setFont('Helvetica-Bold', 13)
            c.setFillColor(C_BLACK)
            c.drawString(w * 0.4 + 0.9*cm, h - 0.72*cm, 'GUÍA DE SALIDA DE ALMACÉN')
            c.setFont('Helvetica', 7.5)
            c.setFillColor(C_LABEL)
            c.drawString(w * 0.4 + 0.9*cm, h - 1.1*cm, 'Documento de despacho y trazabilidad de activos')

            # Código + estado (esquina superior derecha)
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(C_BLACK)
            c.drawRightString(w, h - 0.52*cm, self.codigo)
            estado_color = {
                'activa': colors.HexColor('#198754'),
                'anulada': colors.HexColor('#DC2626'),
            }.get((self.estado or '').lower(), C_LABEL)
            c.setFont('Helvetica', 7)
            c.setFillColor(estado_color)
            c.drawRightString(w, h - 0.9*cm, f'Estado: {(self.estado or "").upper()}')

            # Línea ámbar inferior
            c.setStrokeColor(C_AMBER)
            c.setLineWidth(1.5)
            c.line(0, 0, w, 0)

    # ── Estilos tipográficos ─────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    st_label = ParagraphStyle('Label',
        fontName='Helvetica-Bold', fontSize=7, textColor=C_LABEL,
        leading=9, spaceAfter=0)
    st_value = ParagraphStyle('Value',
        fontName='Helvetica', fontSize=8.5, textColor=C_BLACK,
        leading=11, spaceAfter=0)
    st_th = ParagraphStyle('TH',
        fontName='Helvetica-Bold', fontSize=7.5, textColor=C_WHITE,
        leading=10, alignment=TA_LEFT)
    st_td = ParagraphStyle('TD',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=11)
    st_td_center = ParagraphStyle('TDC',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=11, alignment=TA_CENTER)
    st_mono = ParagraphStyle('Mono',
        fontName='Courier', fontSize=7.5, textColor=C_BLACK,
        leading=10)
    st_serial = ParagraphStyle('Serial',
        fontName='Courier', fontSize=7, textColor=C_LABEL,
        leading=9)
    st_obs = ParagraphStyle('Obs',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=12, leftIndent=0)
    st_section = ParagraphStyle('Section',
        fontName='Helvetica-Bold', fontSize=7.5, textColor=C_LABEL,
        leading=10, spaceBefore=6, spaceAfter=3,
        borderPad=0)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def campo(label, valor, ancho_label=3*cm, ancho_valor=5.2*cm):
        return Table(
            [[Paragraph(label.upper(), st_label), Paragraph(str(valor or '—'), st_value)]],
            colWidths=[ancho_label, ancho_valor]
        )

    def hrule(color=C_RULE, grosor=0.5):
        return HRFlowable(width='100%', thickness=grosor, color=color,
                          spaceAfter=6, spaceBefore=6)

    # ── Página con numeración ─────────────────────────────────────────────────
    codigo_doc = guia_codigo(id)

    def build_page(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(C_LABEL)
        canvas.drawRightString(
            doc.width + doc.leftMargin,
            0.65 * cm,
            f'Página {doc.page}  ·  {codigo_doc}  ·  generado por Portero Seguro'
        )
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 0.85*cm, doc.width + doc.leftMargin, 0.85*cm)
        canvas.restoreState()

    # ── Documento ─────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    ANCHO_UTIL = A4[0] - 3*cm   # márgenes 1.5cm cada lado
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.2*cm, bottomMargin=1.6*cm
    )

    E = []   # elementos

    # Membrete
    E.append(Membrete(codigo_doc, guia['estado'] or '', ANCHO_UTIL))
    E.append(Spacer(1, 0.45*cm))

    # ── Bloque de metadatos (2 columnas) ─────────────────────────────────────
    meta_izq = [
        [Paragraph('SOLICITANTE', st_label), Paragraph(str(guia['personal'] or '—'), st_value)],
        [Paragraph('CARGO',       st_label), Paragraph(str(guia['cargo'] or '—'), st_value)],
        [Paragraph('DESTINO',     st_label), Paragraph(str(guia['destino'] or '—'), st_value)],
        [Paragraph('PROYECTO',    st_label), Paragraph(str(guia['proyecto'] or '—'), st_value)],
    ]
    meta_der = [
        [Paragraph('FECHA',        st_label), Paragraph(str(guia['fecha'] or '—'), st_value)],
        [Paragraph('ENTREGADO POR',st_label), Paragraph(str(guia['entregado_por'] or '—'), st_value)],
        [Paragraph('RECIBIDO POR', st_label), Paragraph(str(guia['recibido_por'] or '—'), st_value)],
        [Paragraph('APROBADO POR', st_label), Paragraph(str(guia['aprobado_por'] or '—'), st_value)],
    ]
    COL_L = 2.5*cm
    COL_V = ANCHO_UTIL / 2 - COL_L - 0.4*cm

    t_izq = Table(meta_izq, colWidths=[COL_L, COL_V])
    t_der = Table(meta_der, colWidths=[COL_L, COL_V])
    for t in (t_izq, t_der):
        t.setStyle(TableStyle([
            ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_WHITE, C_ROW_ALT]),
            ('TOPPADDING',  (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))

    meta_wrapper = Table(
        [[t_izq, Spacer(0.8*cm, 1), t_der]],
        colWidths=[ANCHO_UTIL/2 - 0.4*cm, 0.8*cm, ANCHO_UTIL/2 - 0.4*cm]
    )
    meta_wrapper.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    E.append(meta_wrapper)
    E.append(Spacer(1, 0.4*cm))
    E.append(hrule(C_RULE))

    # ── Tabla de productos ────────────────────────────────────────────────────
    E.append(Paragraph('DETALLE DE PRODUCTOS DESPACHADOS', st_section))
    E.append(Spacer(1, 0.15*cm))

    COL_ITEM = 0.8*cm
    COL_CANT = 1.6*cm
    COL_MARCA = 2.8*cm
    COL_DESC = ANCHO_UTIL - COL_ITEM - COL_CANT - COL_MARCA - 3.8*cm
    COL_SKU  = 3.8*cm

    cabecera = [[
        Paragraph('N°',         st_th),
        Paragraph('CANT.',      st_th),
        Paragraph('MARCA',      st_th),
        Paragraph('DESCRIPCIÓN',st_th),
        Paragraph('SKU / REF.', st_th),
    ]]
    filas_prod = []
    for idx, item in enumerate(detalle, start=1):
        series_ids = series_por_detalle.get(item['guia_detalle_id'], [])
        sku_texto = item['sku'] or '—'
        filas_prod.append([
            Paragraph(str(idx), st_td_center),
            Paragraph(str(item['cantidad']), st_td_center),
            Paragraph(str(item['marca'] or '—'), st_td),
            Paragraph(str(item['descripcion'] or '—'), st_td),
            Paragraph(sku_texto, st_mono),
        ])

    tabla_prods = Table(
        cabecera + filas_prod,
        colWidths=[COL_ITEM, COL_CANT, COL_MARCA, COL_DESC, COL_SKU],
        repeatRows=1
    )
    tabla_prods.setStyle(TableStyle([
        # Cabecera
        ('BACKGROUND',   (0, 0), (-1, 0), C_RAIL),
        ('TOPPADDING',   (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING',(0, 0), (-1, 0), 6),
        ('LEFTPADDING',  (0, 0), (-1, 0), 6),
        # Filas alternas
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
        ('TOPPADDING',   (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 5),
        ('LEFTPADDING',  (0, 1), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # Bordes
        ('LINEBELOW',    (0, 0), (-1, 0), 0.8, C_AMBER),
        ('LINEBELOW',    (0, 1), (-1, -1), 0.3, C_RULE),
        ('BOX',          (0, 0), (-1, -1), 0.4, C_RULE),
        # Alineación columnas numéricas
        ('ALIGN',        (0, 0), (1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    E.append(tabla_prods)

    # ── Series individuales (solo si hay equipos serializados) ────────────────
    filas_series = []
    for item in detalle:
        ids = series_por_detalle.get(item['guia_detalle_id'], [])
        if ids:
            filas_series.append((item['descripcion'], item['marca'], ids))

    if filas_series:
        E.append(Spacer(1, 0.4*cm))
        E.append(hrule(C_RULE))
        E.append(Paragraph('NÚMEROS DE SERIE POR EQUIPO', st_section))
        E.append(Spacer(1, 0.15*cm))

        for desc, marca, ids in filas_series:
            series_texto = '   ·   '.join(str(s) for s in ids)
            bloque = Table([
                [Paragraph(f'{marca} – {desc}', st_label),
                 Paragraph(series_texto, st_serial)]
            ], colWidths=[ANCHO_UTIL * 0.35, ANCHO_UTIL * 0.65])
            bloque.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING',   (0, 0), (-1, -1), 5),
                ('LINEBELOW',     (0, 0), (-1, -1), 0.25, C_RULE),
            ]))
            E.append(bloque)

    # ── Observaciones ─────────────────────────────────────────────────────────
    obs = guia['observaciones'] or ''
    if obs:
        E.append(Spacer(1, 0.4*cm))
        E.append(hrule(C_RULE))
        E.append(Paragraph('OBSERVACIONES', st_section))
        E.append(Paragraph(obs, st_obs))

    # ── Firmas ────────────────────────────────────────────────────────────────
    E.append(Spacer(1, 1*cm))
    E.append(hrule(C_RULE))

    FIRMA_W = ANCHO_UTIL / 3 - 0.4*cm
    FIRMA_GAP = 0.6*cm

    firmas_data = [
        ['Entregado por', 'Recibido por', 'Aprobado por'],
        [guia['entregado_por'] or '', guia['recibido_por'] or '', guia['aprobado_por'] or ''],
    ]
    firma_table = Table(
        firmas_data,
        colWidths=[FIRMA_W, FIRMA_W, FIRMA_W],
        rowHeights=[1.8*cm, 0.55*cm],
        spaceAfter=0
    )
    firma_table.setStyle(TableStyle([
        # Etiquetas superiores centradas
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, 0),  'BOTTOM'),
        ('VALIGN',       (0, 1), (-1, 1),  'TOP'),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0),  8),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  C_LABEL),
        # Línea de firma en el borde inferior de la primera fila
        ('LINEBELOW',    (0, 0), (-1, 0),  0.8, C_BLACK),
        # Nombres bajo la línea
        ('FONTNAME',     (0, 1), (-1, 1),  'Helvetica'),
        ('FONTSIZE',     (0, 1), (-1, 1),  7.5),
        ('TEXTCOLOR',    (0, 1), (-1, 1),  C_BLACK),
        # Separación entre columnas de firma
        ('RIGHTPADDING', (0, 0), (1, -1),  FIRMA_GAP),
        ('LEFTPADDING',  (1, 0), (-1, -1), FIRMA_GAP),
    ]))
    E.append(firma_table)

    # ── Build ──────────────────────────────────────────────────────────────────
    doc.build(E, onFirstPage=build_page, onLaterPages=build_page)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=False,
        download_name=f'{codigo_doc}.pdf', mimetype='application/pdf'
    )


@app.route('/movimientos')
def movimientos():
    conn = get_db_connection()
    f_tipo = request.args.get('tipo', '')
    f_fecha = request.args.get('fecha', '')
    f_q = request.args.get('q', '')

    query = '''
        SELECT m.*, datetime(m.fecha, 'localtime') as fecha_local,
               e.marca, e.descripcion, e.sku
        FROM movimientos m
        JOIN equipos e ON e.id = m.equipo_id
        WHERE 1=1
    '''
    params = []
    if f_tipo:
        query += ' AND m.tipo = ?'
        params.append(f_tipo)
    if f_fecha:
        query += " AND strftime('%Y-%m-%d', datetime(m.fecha, 'localtime')) = ?"
        params.append(f_fecha)
    if f_q:
        query += ' AND (e.descripcion LIKE ? OR e.marca LIKE ? OR e.sku LIKE ? OR m.referencia LIKE ?)'
        params.extend([f'%{f_q}%', f'%{f_q}%', f'%{f_q}%', f'%{f_q}%'])

    movimientos_data = conn.execute(query + ' ORDER BY m.id DESC LIMIT 500', params).fetchall()
    conn.close()
    return render_template(
        'movimientos.html', movimientos=movimientos_data,
        tipos=TIPOS_MOVIMIENTO, f_tipo=f_tipo, f_fecha=f_fecha, f_q=f_q
    )


@app.route('/configuracion', methods=['GET', 'POST'])
def configuracion():
    conn = get_db_connection()
    if request.method == 'POST':
        tipo = clean_text(request.form.get('tipo'))
        nombre = clean_text(request.form.get('nombre'))
        categoria = clean_text(request.form.get('categoria'))
        marca = clean_text(request.form.get('marca'))

        try:
            if tipo == 'categoria':
                if not nombre:
                    flash('Debe ingresar el nombre de la categoria.', 'danger')
                else:
                    ensure_catalog_value(conn, 'categorias', nombre)
                    flash('Categoria registrada correctamente.', 'success')

            elif tipo == 'marca':
                if not nombre or not catalog_exists(conn, 'categorias', categoria):
                    flash('Debe ingresar marca y categoria valida.', 'danger')
                else:
                    ensure_categoria_marca(conn, categoria, nombre)
                    flash('Marca asociada a categoria correctamente.', 'success')

            elif tipo == 'modelo':
                if not nombre or not catalog_exists(conn, 'categorias', categoria) or not catalog_exists(conn, 'marcas', marca):
                    flash('Debe ingresar modelo, categoria y marca validos.', 'danger')
                elif not relacion_categoria_marca_exists(conn, categoria, marca):
                    flash('Primero debe asociar la marca a la categoria.', 'warning')
                else:
                    ensure_modelo(conn, nombre, categoria, marca)
                    flash('Modelo asociado correctamente.', 'success')

            elif tipo == 'cargo':
                if not nombre:
                    flash('Debe ingresar el nombre del cargo.', 'danger')
                else:
                    ensure_catalog_value(conn, 'cargos', nombre)
                    flash('Cargo registrado correctamente.', 'success')

            elif tipo == 'edificio':
                ubicacion = clean_text(request.form.get('ubicacion'))
                mapa_url = clean_text(request.form.get('mapa_url'))
                if not nombre:
                    flash('Debe ingresar el nombre del edificio.', 'danger')
                else:
                    row = conn.execute('SELECT id FROM edificios WHERE nombre = ?', (nombre,)).fetchone()
                    if row:
                        conn.execute('''
                            UPDATE edificios
                            SET ubicacion = COALESCE(NULLIF(?, ''), ubicacion),
                                mapa_url = COALESCE(NULLIF(?, ''), mapa_url)
                            WHERE id = ?
                        ''', (ubicacion, mapa_url, row['id']))
                    else:
                        conn.execute('INSERT INTO edificios (nombre, ubicacion, mapa_url) VALUES (?, ?, ?)', (nombre, ubicacion, mapa_url))
                    flash('Edificio registrado correctamente.', 'success')

            else:
                flash('Dato de configuracion invalido.', 'danger')

            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('Ese valor ya existe o no cumple una regla del catalogo.', 'warning')

        conn.close()
        return redirect(url_for('configuracion'))

    categorias = conn.execute('SELECT * FROM categorias ORDER BY nombre').fetchall()
    marcas = conn.execute('''
        SELECT m.id, m.nombre,
               COALESCE(GROUP_CONCAT(cm.categoria, ', '), 'Sin categoria') AS categorias
        FROM marcas m
        LEFT JOIN categoria_marca cm ON cm.marca = m.nombre
        GROUP BY m.id, m.nombre
        ORDER BY m.nombre
    ''').fetchall()
    relaciones = conn.execute('''
        SELECT id, categoria, marca
        FROM categoria_marca
        ORDER BY categoria, marca
    ''').fetchall()
    modelos = conn.execute('''
        SELECT id, nombre, categoria, marca
        FROM modelos
        ORDER BY categoria, marca, nombre
    ''').fetchall()
    cargos = conn.execute('SELECT * FROM cargos ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    catalogos = get_catalogos_payload(conn)
    conn.close()
    return render_template(
        'configuracion.html', categorias=categorias, marcas=marcas, modelos=modelos,
        relaciones=relaciones, cargos=cargos, edificios=edificios, catalogos=catalogos
    )


@app.route('/eliminar_relacion_categoria_marca/<int:id>', methods=['POST'])
def eliminar_relacion_categoria_marca(id):
    conn = get_db_connection()
    rel = conn.execute('SELECT * FROM categoria_marca WHERE id = ?', (id,)).fetchone()
    if not rel:
        conn.close()
        flash('La relacion no existe.', 'warning')
        return redirect(url_for('configuracion'))

    usados_modelos = conn.execute('''
        SELECT COUNT(*)
        FROM modelos
        WHERE categoria = ? AND marca = ?
    ''', (rel['categoria'], rel['marca'])).fetchone()[0]
    usados_equipos = conn.execute('''
        SELECT COUNT(*)
        FROM equipos
        WHERE categoria = ? AND marca = ?
    ''', (rel['categoria'], rel['marca'])).fetchone()[0]

    if usados_modelos or usados_equipos:
        conn.close()
        flash('No se puede eliminar la relacion porque tiene modelos o productos asociados. Primero mueve o elimina esos modelos/productos.', 'warning')
        return redirect(url_for('configuracion'))

    conn.execute('DELETE FROM categoria_marca WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Relacion eliminada correctamente.', 'success')
    return redirect(url_for('configuracion'))


@app.route('/limpiar_relaciones_vacias', methods=['POST'])
def limpiar_relaciones_vacias():
    conn = get_db_connection()
    cursor = conn.execute('''
        DELETE FROM categoria_marca
        WHERE NOT EXISTS (
            SELECT 1 FROM modelos
            WHERE modelos.categoria = categoria_marca.categoria
              AND modelos.marca = categoria_marca.marca
        )
        AND NOT EXISTS (
            SELECT 1 FROM equipos
            WHERE equipos.categoria = categoria_marca.categoria
              AND equipos.marca = categoria_marca.marca
        )
    ''')
    eliminadas = cursor.rowcount
    conn.commit()
    conn.close()
    flash(f'Relaciones vacias eliminadas: {eliminadas}.', 'success')
    return redirect(url_for('configuracion'))


@app.route('/editar_catalogo/<tipo>/<int:id>', methods=['POST'])
def editar_catalogo(tipo, id):
    nuevo_nombre = clean_text(request.form.get('nuevo_nombre'))
    if not nuevo_nombre:
        flash('Debe ingresar un nombre valido.', 'danger')
        return redirect(url_for('configuracion'))

    conn = get_db_connection()
    try:
        if tipo == 'categoria':
            actual = conn.execute('SELECT nombre FROM categorias WHERE id = ?', (id,)).fetchone()
            if actual:
                anterior = actual['nombre']
                conn.execute('UPDATE categorias SET nombre = ? WHERE id = ?', (nuevo_nombre, id))
                conn.execute('UPDATE equipos SET categoria = ? WHERE categoria = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE categoria_marca SET categoria = ? WHERE categoria = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE modelos SET categoria = ? WHERE categoria = ?', (nuevo_nombre, anterior))

        elif tipo == 'marca':
            actual = conn.execute('SELECT nombre FROM marcas WHERE id = ?', (id,)).fetchone()
            if actual:
                anterior = actual['nombre']
                conn.execute('UPDATE marcas SET nombre = ? WHERE id = ?', (nuevo_nombre, id))
                conn.execute('UPDATE equipos SET marca = ? WHERE marca = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE categoria_marca SET marca = ? WHERE marca = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE modelos SET marca = ? WHERE marca = ?', (nuevo_nombre, anterior))

        elif tipo == 'modelo':
            nueva_categoria = clean_text(request.form.get('categoria'))
            nueva_marca = clean_text(request.form.get('marca'))
            actual = conn.execute('SELECT nombre, categoria, marca FROM modelos WHERE id = ?', (id,)).fetchone()
            if actual:
                if nueva_categoria and nueva_marca:
                    ensure_categoria_marca(conn, nueva_categoria, nueva_marca)
                else:
                    nueva_categoria = actual['categoria']
                    nueva_marca = actual['marca']

                conn.execute('''
                    UPDATE modelos
                    SET nombre = ?, categoria = ?, marca = ?
                    WHERE id = ?
                ''', (nuevo_nombre, nueva_categoria, nueva_marca, id))

                if actual['categoria'] and actual['marca']:
                    conn.execute('''
                        UPDATE equipos
                        SET descripcion = ?, categoria = ?, marca = ?
                        WHERE descripcion = ? AND categoria = ? AND marca = ?
                    ''', (nuevo_nombre, nueva_categoria, nueva_marca, actual['nombre'], actual['categoria'], actual['marca']))
                else:
                    conn.execute('UPDATE equipos SET descripcion = ? WHERE descripcion = ?', (nuevo_nombre, actual['nombre']))

        elif tipo == 'cargo':
            actual = conn.execute('SELECT nombre FROM cargos WHERE id = ?', (id,)).fetchone()
            if actual:
                anterior = actual['nombre']
                conn.execute('UPDATE cargos SET nombre = ? WHERE id = ?', (nuevo_nombre, id))
                conn.execute('UPDATE personal SET cargo = ? WHERE cargo = ?', (nuevo_nombre, anterior))

        elif tipo == 'edificio':
            actual = conn.execute('SELECT nombre FROM edificios WHERE id = ?', (id,)).fetchone()
            if actual:
                anterior = actual['nombre']
                ubicacion = clean_text(request.form.get('ubicacion'))
                mapa_url = clean_text(request.form.get('mapa_url'))
                conn.execute('UPDATE edificios SET nombre = ?, ubicacion = ?, mapa_url = ? WHERE id = ?', (nuevo_nombre, ubicacion, mapa_url, id))
                conn.execute('UPDATE guias_salida SET destino = ? WHERE destino = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE salidas SET destino = ? WHERE destino = ?', (nuevo_nombre, anterior))
                conn.execute('UPDATE avances_actividades SET edificio = ? WHERE edificio = ?', (nuevo_nombre, anterior))
                try:
                    conn.execute('UPDATE seguimiento_herramientas SET edificio = ? WHERE edificio = ?', (nuevo_nombre, anterior))
                except sqlite3.OperationalError:
                    pass
        else:
            flash('Tipo de catalogo invalido.', 'danger')
            conn.close()
            return redirect(url_for('configuracion'))

        conn.commit()
        flash('Catalogo editado correctamente.', 'success')
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('No se pudo editar: el nombre ya existe o rompe una relacion.', 'warning')
    finally:
        conn.close()
    return redirect(url_for('configuracion'))


@app.route('/eliminar_catalogo/<tipo>/<int:id>', methods=['POST'])
def eliminar_catalogo(tipo, id):
    conn = get_db_connection()
    try:
        usado = 0
        if tipo == 'categoria':
            row = conn.execute('SELECT nombre FROM categorias WHERE id = ?', (id,)).fetchone()
            if row:
                usado += conn.execute('SELECT COUNT(*) FROM equipos WHERE categoria = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM modelos WHERE categoria = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM categoria_marca WHERE categoria = ?', (row['nombre'],)).fetchone()[0]
                if usado:
                    flash('No se puede eliminar una categoria usada por marcas, modelos o equipos.', 'warning')
                else:
                    conn.execute('DELETE FROM categorias WHERE id = ?', (id,))
                    flash('Categoria eliminada correctamente.', 'success')

        elif tipo == 'marca':
            row = conn.execute('SELECT nombre FROM marcas WHERE id = ?', (id,)).fetchone()
            if row:
                usado += conn.execute('SELECT COUNT(*) FROM equipos WHERE marca = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM modelos WHERE marca = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM categoria_marca WHERE marca = ?', (row['nombre'],)).fetchone()[0]
                if usado:
                    flash('No se puede eliminar una marca usada por categorias, modelos o equipos.', 'warning')
                else:
                    conn.execute('DELETE FROM marcas WHERE id = ?', (id,))
                    flash('Marca eliminada correctamente.', 'success')

        elif tipo == 'modelo':
            row = conn.execute('SELECT nombre, categoria, marca FROM modelos WHERE id = ?', (id,)).fetchone()
            if row:
                if row['categoria'] and row['marca']:
                    usado = conn.execute('''
                        SELECT COUNT(*) FROM equipos
                        WHERE descripcion = ? AND categoria = ? AND marca = ?
                    ''', (row['nombre'], row['categoria'], row['marca'])).fetchone()[0]
                else:
                    usado = conn.execute('SELECT COUNT(*) FROM equipos WHERE descripcion = ?', (row['nombre'],)).fetchone()[0]
                if usado:
                    flash('No se puede eliminar un modelo usado por equipos.', 'warning')
                else:
                    conn.execute('DELETE FROM modelos WHERE id = ?', (id,))
                    flash('Modelo eliminado correctamente.', 'success')

        elif tipo == 'cargo':
            row = conn.execute('SELECT nombre FROM cargos WHERE id = ?', (id,)).fetchone()
            if row:
                usado = conn.execute('SELECT COUNT(*) FROM personal WHERE cargo = ?', (row['nombre'],)).fetchone()[0]
                if usado:
                    flash('No se puede eliminar un cargo usado por personal.', 'warning')
                else:
                    conn.execute('DELETE FROM cargos WHERE id = ?', (id,))
                    flash('Cargo eliminado correctamente.', 'success')

        elif tipo == 'edificio':
            row = conn.execute('SELECT nombre FROM edificios WHERE id = ?', (id,)).fetchone()
            if row:
                usado = conn.execute('SELECT COUNT(*) FROM guias_salida WHERE destino = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM salidas WHERE destino = ?', (row['nombre'],)).fetchone()[0]
                if usado:
                    flash('No se puede eliminar un edificio usado en guias o salidas.', 'warning')
                else:
                    conn.execute('DELETE FROM edificios WHERE id = ?', (id,))
                    flash('Edificio eliminado correctamente.', 'success')

        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'Error eliminando catalogo: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('configuracion'))

@app.route('/personal', methods=['GET', 'POST'])
def personal():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = clean_text(request.form.get('nombre'))
        cargo = clean_text(request.form.get('cargo'))
        if not nombre or not catalog_exists(conn, 'cargos', cargo):
            flash('Debe ingresar nombre y cargo valido.', 'danger')
        else:
            try:
                conn.execute('INSERT INTO personal (nombre, cargo) VALUES (?, ?)', (nombre, cargo))
                conn.commit()
                flash('Personal registrado correctamente.', 'success')
            except sqlite3.IntegrityError:
                flash('Ese personal ya existe.', 'warning')
        conn.close()
        return redirect(url_for('personal'))

    lista_personal = conn.execute('SELECT * FROM personal ORDER BY nombre').fetchall()
    cargos_db = conn.execute('SELECT * FROM cargos ORDER BY nombre').fetchall()
    conn.close()
    return render_template('personal.html', personal=lista_personal, cargos_db=cargos_db)


@app.route('/editar_personal/<int:id>', methods=['POST'])
def editar_personal(id):
    nuevo_nombre = clean_text(request.form.get('nombre'))
    nuevo_cargo = clean_text(request.form.get('cargo'))
    conn = get_db_connection()
    if nuevo_nombre and catalog_exists(conn, 'cargos', nuevo_cargo):
        actual = conn.execute('SELECT nombre FROM personal WHERE id = ?', (id,)).fetchone()
        try:
            conn.execute('UPDATE personal SET nombre = ?, cargo = ? WHERE id = ?', (nuevo_nombre, nuevo_cargo, id))
            if actual:
                conn.execute('UPDATE guias_salida SET personal = ? WHERE personal = ?', (nuevo_nombre, actual['nombre']))
                conn.execute('UPDATE salidas SET personal = ? WHERE personal = ?', (nuevo_nombre, actual['nombre']))
            conn.commit()
            flash('Personal actualizado correctamente.', 'success')
        except sqlite3.IntegrityError:
            flash('No se pudo actualizar: nombre duplicado.', 'warning')
    else:
        flash('Datos de personal invalidos.', 'danger')
    conn.close()
    return redirect(url_for('personal'))


@app.route('/eliminar_personal/<int:id>', methods=['POST'])
def eliminar_personal(id):
    conn = get_db_connection()
    persona = conn.execute('SELECT nombre FROM personal WHERE id = ?', (id,)).fetchone()
    if persona:
        usado = conn.execute('SELECT COUNT(*) FROM guias_salida WHERE personal = ?', (persona['nombre'],)).fetchone()[0]
        usado += conn.execute('SELECT COUNT(*) FROM salidas WHERE personal = ?', (persona['nombre'],)).fetchone()[0]
        if usado > 0:
            flash('No se puede eliminar personal con movimientos o guias registradas.', 'warning')
        else:
            conn.execute('DELETE FROM personal WHERE id = ?', (id,))
            conn.commit()
            flash('Personal eliminado correctamente.', 'success')
    conn.close()
    return redirect(url_for('personal'))


@app.route('/agregar_cargo', methods=['POST'])
def agregar_cargo():
    nombre = clean_text(request.form.get('nombre'))
    if nombre:
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO cargos (nombre) VALUES (?)', (nombre,))
            conn.commit()
            flash('Cargo agregado correctamente.', 'success')
        except sqlite3.IntegrityError:
            flash('Ese cargo ya existe.', 'warning')
        conn.close()
    return redirect(url_for('personal'))


@app.route('/agregar_categoria', methods=['POST'])
def agregar_categoria():
    return _agregar_catalogo_rapido('categoria', 'ingresos')


@app.route('/agregar_marca', methods=['POST'])
def agregar_marca():
    return _agregar_catalogo_rapido('marca', 'ingresos')


@app.route('/agregar_modelo', methods=['POST'])
def agregar_modelo():
    return _agregar_catalogo_rapido('modelo', 'ingresos')


def _agregar_catalogo_rapido(tipo, endpoint):
    nombre = clean_text(request.form.get('nombre'))
    categoria = clean_text(request.form.get('categoria'))
    marca = clean_text(request.form.get('marca'))
    conn = get_db_connection()
    try:
        if tipo == 'categoria':
            if nombre:
                ensure_catalog_value(conn, 'categorias', nombre)
                flash('Categoria agregada correctamente.', 'success')
        elif tipo == 'marca':
            if nombre and catalog_exists(conn, 'categorias', categoria):
                ensure_categoria_marca(conn, categoria, nombre)
                flash('Marca agregada y asociada correctamente.', 'success')
            else:
                flash('Debe indicar una categoria valida para la marca.', 'danger')
        elif tipo == 'modelo':
            if nombre and catalog_exists(conn, 'categorias', categoria) and catalog_exists(conn, 'marcas', marca):
                if not relacion_categoria_marca_exists(conn, categoria, marca):
                    ensure_categoria_marca(conn, categoria, marca)
                ensure_modelo(conn, nombre, categoria, marca)
                flash('Modelo agregado correctamente.', 'success')
            else:
                flash('Debe indicar categoria, marca y modelo validos.', 'danger')
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ese valor ya existe o no cumple una regla del catalogo.', 'warning')
    finally:
        conn.close()
    return redirect(url_for(endpoint))


@app.route('/edificios', methods=['GET', 'POST'])
def edificios():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = clean_text(request.form.get('nombre'))
        ubicacion = clean_text(request.form.get('ubicacion'))
        mapa_url = clean_text(request.form.get('mapa_url'))
        observaciones = clean_text(request.form.get('observaciones'))
        if nombre:
            try:
                conn.execute("""
                    INSERT INTO edificios (nombre, ubicacion, mapa_url, observaciones)
                    VALUES (?, ?, ?, ?)
                """, (nombre, ubicacion, mapa_url, observaciones))
                conn.commit()
                flash('Edificio registrado correctamente.', 'success')
            except sqlite3.IntegrityError:
                flash('Ese edificio ya existe.', 'warning')
            except sqlite3.OperationalError:
                conn.execute('INSERT INTO edificios (nombre) VALUES (?)', (nombre,))
                conn.commit()
                flash('Edificio registrado correctamente. Ejecuta migrar_fase1.py para habilitar ubicacion y mapa.', 'warning')
        conn.close()
        return redirect(url_for('edificios'))

    lista = conn.execute("""
        SELECT
            e.*,
            (SELECT COUNT(*) FROM guias_salida g WHERE g.destino = e.nombre) AS total_guias,
            (SELECT COUNT(*) FROM salidas s WHERE s.destino = e.nombre) AS total_salidas,
            (SELECT COUNT(*) FROM avances_actividades a WHERE a.edificio = e.nombre) AS total_avances,
            (SELECT COUNT(*) FROM seguimiento_herramientas sh WHERE sh.edificio = e.nombre) AS total_seguimiento
        FROM edificios e
        ORDER BY e.nombre ASC
    """).fetchall()
    total_edificios = len(lista)
    con_mapa = sum(1 for e in lista if clean_text(e['mapa_url'] if 'mapa_url' in e.keys() else ''))
    conn.close()
    return render_template(
        'edificios.html',
        edificios=lista,
        total_edificios=total_edificios,
        con_mapa=con_mapa
    )


@app.route('/edificios/editar/<int:id>', methods=['POST'])
def editar_edificio(id):
    conn = get_db_connection()
    nombre = clean_text(request.form.get('nombre'))
    ubicacion = clean_text(request.form.get('ubicacion'))
    mapa_url = clean_text(request.form.get('mapa_url'))
    observaciones = clean_text(request.form.get('observaciones'))
    try:
        if not nombre:
            flash('El nombre del edificio es obligatorio.', 'danger')
        else:
            anterior = conn.execute('SELECT nombre FROM edificios WHERE id = ?', (id,)).fetchone()
            if not anterior:
                flash('Edificio no encontrado.', 'warning')
            else:
                nombre_anterior = anterior['nombre']
                conn.execute("""
                    UPDATE edificios
                    SET nombre = ?, ubicacion = ?, mapa_url = ?, observaciones = ?
                    WHERE id = ?
                """, (nombre, ubicacion, mapa_url, observaciones, id))
                if nombre != nombre_anterior:
                    conn.execute('UPDATE salidas SET destino = ? WHERE destino = ?', (nombre, nombre_anterior))
                    conn.execute('UPDATE guias_salida SET destino = ? WHERE destino = ?', (nombre, nombre_anterior))
                    conn.execute('UPDATE avances_actividades SET edificio = ? WHERE edificio = ?', (nombre, nombre_anterior))
                    conn.execute('UPDATE seguimiento_herramientas SET edificio = ? WHERE edificio = ?', (nombre, nombre_anterior))
                conn.commit()
                flash('Edificio actualizado correctamente.', 'success')
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ya existe un edificio con ese nombre.', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando edificio: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('edificios'))


@app.route('/edificios/eliminar/<int:id>', methods=['POST'])
def eliminar_edificio(id):
    conn = get_db_connection()
    edificio = conn.execute('SELECT nombre FROM edificios WHERE id = ?', (id,)).fetchone()
    if edificio:
        usado = conn.execute('SELECT COUNT(*) FROM guias_salida WHERE destino = ?', (edificio['nombre'],)).fetchone()[0]
        usado += conn.execute('SELECT COUNT(*) FROM salidas WHERE destino = ?', (edificio['nombre'],)).fetchone()[0]
        try:
            usado += conn.execute('SELECT COUNT(*) FROM avances_actividades WHERE edificio = ?', (edificio['nombre'],)).fetchone()[0]
            usado += conn.execute('SELECT COUNT(*) FROM seguimiento_herramientas WHERE edificio = ?', (edificio['nombre'],)).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        if usado > 0:
            flash('No se puede eliminar un edificio usado en guias, salidas, avances o seguimiento.', 'warning')
        else:
            conn.execute('DELETE FROM edificios WHERE id = ?', (id,))
            conn.commit()
            flash('Edificio eliminado correctamente.', 'success')
    conn.close()
    return redirect(url_for('edificios'))



# Inicializa y migra la base tanto con python app.py como con flask run.
init_db()


@app.route('/editar_equipo/<int:id>', methods=['POST'])
def editar_equipo(id):
    conn = get_db_connection()
    try:
        equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (id,)).fetchone()
        if not equipo:
            flash('El producto no existe.', 'danger')
            return redirect(url_for('index'))

        categoria = clean_text(request.form.get('categoria'))
        marca = clean_text(request.form.get('marca'))
        descripcion = clean_text(request.form.get('descripcion'))
        sku = clean_text(request.form.get('sku'))
        mac = clean_text(request.form.get('mac'))
        stock_minimo = safe_int(request.form.get('stock_minimo'))
        estado = normalize_estado(request.form.get('estado')) or equipo['estado']
        observaciones = clean_text(request.form.get('observaciones'))
        ubicacion_actual = clean_text(request.form.get('ubicacion_actual'))

        errores = []
        if not catalog_exists(conn, 'categorias', categoria):
            errores.append('La categoria seleccionada no existe.')
        if not catalog_exists(conn, 'marcas', marca):
            errores.append('La marca seleccionada no existe.')
        if categoria and marca and not relacion_categoria_marca_exists(conn, categoria, marca):
            errores.append('La marca no esta relacionada con la categoria.')
        if not descripcion:
            errores.append('La descripcion/modelo es obligatorio.')
        if mac and not validar_mac(mac):
            errores.append('La MAC no tiene formato valido.')
        if stock_minimo < 0:
            errores.append('El stock minimo no puede ser negativo.')
        if estado not in ESTADOS_EQUIPO:
            errores.append('Estado invalido.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            return redirect(url_for('index'))

        duplicado = conn.execute("""
            SELECT id
            FROM equipos
            WHERE id <> ?
              AND categoria = ?
              AND marca = ?
              AND descripcion = ?
              AND COALESCE(control_stock, 'CANTIDAD') = COALESCE(?, 'CANTIDAD')
              AND estado <> 'Baja'
            LIMIT 1
        """, (id, categoria, marca, descripcion, equipo['control_stock'] if 'control_stock' in equipo.keys() else 'CANTIDAD')).fetchone()
        if duplicado:
            flash('Ya existe otro producto activo con la misma categoria, marca y modelo. No se actualizo para evitar duplicados.', 'warning')
            return redirect(url_for('index'))

        ensure_modelo(conn, descripcion, categoria, marca)
        cantidad = safe_int(equipo['cantidad'])
        estado_final = estado_operativo_por_stock(cantidad, estado)
        ubicacion_final = ubicacion_actual or ubicacion_default_por_estado_equipo(estado_final)

        conn.execute("""
            UPDATE equipos
            SET categoria = ?, marca = ?, descripcion = ?, sku = ?, mac = ?,
                stock_minimo = ?, estado = ?, observaciones = ?, ubicacion_actual = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (categoria, marca, descripcion, sku, mac, stock_minimo, estado_final, observaciones, ubicacion_final, id))

        conn.commit()
        flash('Producto actualizado correctamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error editando producto: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))


@app.route('/dar_baja_equipo/<int:id>', methods=['POST'])
def dar_baja_equipo(id):
    conn = get_db_connection()
    motivo = clean_text(request.form.get('motivo')) or 'Baja manual desde inventario.'

    try:
        equipo = conn.execute('''
            SELECT id, marca, descripcion, sku, cantidad, estado,
                   COALESCE(control_stock, 'CANTIDAD') AS control_stock
            FROM equipos
            WHERE id = ?
        ''', (id,)).fetchone()

        if not equipo:
            flash('El producto no existe.', 'danger')
            return redirect(url_for('index'))

        if normalize_estado(equipo['estado']) == 'Baja':
            flash('El producto ya esta dado de baja.', 'warning')
            return redirect(url_for('index', estado='Baja'))

        guias_activas = conn.execute('''
            SELECT COUNT(*)
            FROM guia_detalle gd
            JOIN guias_salida g ON g.id = gd.guia_id
            WHERE gd.equipo_id = ?
              AND COALESCE(g.estado, 'ACTIVA') = 'ACTIVA'
        ''', (id,)).fetchone()[0]

        if guias_activas > 0:
            flash('No se puede dar de baja: el producto esta asociado a guias activas. Primero anula o regulariza esas guias.', 'warning')
            return redirect(url_for('index'))

        if equipo['control_stock'] == 'SERIAL':
            series_no_disponibles = conn.execute('''
                SELECT COUNT(*)
                FROM equipo_series
                WHERE equipo_id = ?
                  AND estado NOT IN ('EN_STOCK', 'BAJA')
            ''', (id,)).fetchone()[0]
            if series_no_disponibles > 0:
                flash('No se puede dar de baja: existen series entregadas, instaladas o en otro estado. Regulariza esas series primero.', 'warning')
                return redirect(url_for('index'))
            conn.execute('''
                UPDATE equipo_series
                SET estado = 'BAJA', ubicacion_actual = 'Baja',
                    fecha_actualizacion = CURRENT_TIMESTAMP,
                    observaciones = COALESCE(observaciones, '') || ' | Baja: ' || ?
                WHERE equipo_id = ? AND estado = 'EN_STOCK'
            ''', (motivo, id))

        stock_anterior = equipo['cantidad'] or 0
        conn.execute('''
            UPDATE equipos
            SET cantidad = 0,
                estado = 'Baja',
                ubicacion_actual = 'Baja',
                observaciones = COALESCE(observaciones, '') || ' | Baja: ' || ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (motivo, id))

        registrar_movimiento(
            conn, id, 'BAJA', stock_anterior, stock_anterior, 0,
            referencia=f'BAJA-{id:06d}', observaciones=motivo
        )

        conn.commit()
        flash('Producto dado de baja correctamente. Se conserva el historial para trazabilidad.', 'success')
        return redirect(url_for('index', estado='Baja'))

    except Exception as e:
        conn.rollback()
        flash(f'Error dando de baja el producto: {e}', 'danger')
        return redirect(url_for('index'))

    finally:
        conn.close()



@app.route('/seguimiento', methods=['GET', 'POST'])
def seguimiento():
    """Seguimiento independiente para herramientas/equipos temporales fuera del inventario."""
    conn = get_db_connection()

    if request.method == 'POST':
        herramienta = clean_text(request.form.get('herramienta'))
        personal = clean_text(request.form.get('personal'))
        fecha_dejado = clean_text(request.form.get('fecha_dejado'))
        edificio = clean_text(request.form.get('edificio'))
        entregado_por = clean_text(request.form.get('entregado_por'))
        estado = clean_text(request.form.get('estado')) or 'EN_SEGUIMIENTO'
        observaciones = clean_text(request.form.get('observaciones'))

        errores = []
        if not herramienta:
            errores.append('Ingrese el equipo o herramienta a controlar.')
        if not catalog_exists(conn, 'personal', personal):
            errores.append('Seleccione el personal que se lo llevo.')
        if entregado_por and not catalog_exists(conn, 'personal', entregado_por):
            errores.append('Seleccione un entregado por valido.')
        if not catalog_exists(conn, 'edificios', edificio):
            errores.append('Seleccione un edificio valido.')
        if not fecha_dejado:
            errores.append('Ingrese la fecha.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.close()
            return redirect(url_for('seguimiento'))

        try:
            conn.execute("""
                INSERT INTO seguimiento_herramientas (
                    herramienta, personal, fecha_dejado, edificio,
                    entregado_por, estado, observaciones
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (herramienta, personal, fecha_dejado, edificio, entregado_por, estado, observaciones))
            conn.commit()
            flash('Seguimiento registrado correctamente.', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Error registrando seguimiento: {e}', 'danger')
        finally:
            conn.close()
        return redirect(url_for('seguimiento'))

    f_estado = clean_text(request.args.get('estado'))
    f_edificio = clean_text(request.args.get('edificio'))
    q = clean_text(request.args.get('q'))

    query = """
        SELECT *
        FROM seguimiento_herramientas
        WHERE 1 = 1
    """
    params = []
    if f_estado:
        query += ' AND estado = ?'
        params.append(f_estado)
    if f_edificio:
        query += ' AND edificio = ?'
        params.append(f_edificio)
    if q:
        query += """
            AND (herramienta LIKE ? OR personal LIKE ? OR entregado_por LIKE ? OR observaciones LIKE ?)
        """
        like = f'%{q}%'
        params.extend([like, like, like, like])

    registros = conn.execute(
        query + ' ORDER BY CASE WHEN estado = "EN_SEGUIMIENTO" THEN 0 ELSE 1 END, fecha_dejado DESC, id DESC',
        params
    ).fetchall()

    personal_db = conn.execute('SELECT nombre FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT nombre, ubicacion, mapa_url FROM edificios ORDER BY nombre').fetchall()
    resumen = {
        'total': conn.execute('SELECT COUNT(*) FROM seguimiento_herramientas').fetchone()[0],
        'activos': conn.execute("SELECT COUNT(*) FROM seguimiento_herramientas WHERE estado = 'EN_SEGUIMIENTO'").fetchone()[0],
        'retirados': conn.execute("SELECT COUNT(*) FROM seguimiento_herramientas WHERE estado = 'RETIRADO'").fetchone()[0],
        'devueltos': conn.execute("SELECT COUNT(*) FROM seguimiento_herramientas WHERE estado = 'DEVUELTO'").fetchone()[0],
    }
    conn.close()
    return render_template(
        'seguimiento.html', registros=registros, personal=personal_db, edificios=edificios,
        resumen=resumen, f_estado=f_estado, f_edificio=f_edificio, q=q,
        estados=['EN_SEGUIMIENTO', 'RETIRADO', 'DEVUELTO', 'PERDIDO', 'BAJA']
    )


@app.route('/seguimiento/actualizar/<int:id>', methods=['POST'])
def actualizar_seguimiento(id):
    conn = get_db_connection()
    estado = clean_text(request.form.get('estado')) or 'EN_SEGUIMIENTO'
    fecha_retorno = clean_text(request.form.get('fecha_retorno'))
    recibido_por = clean_text(request.form.get('recibido_por'))
    observaciones_nuevas = clean_text(request.form.get('observaciones'))
    try:
        actual = conn.execute('SELECT observaciones FROM seguimiento_herramientas WHERE id = ?', (id,)).fetchone()
        if not actual:
            flash('Registro de seguimiento no encontrado.', 'warning')
            conn.close()
            return redirect(url_for('seguimiento'))
        observaciones = actual['observaciones'] or ''
        if observaciones_nuevas:
            observaciones = (observaciones + '\n' if observaciones else '') + observaciones_nuevas
        conn.execute("""
            UPDATE seguimiento_herramientas
            SET estado = ?, fecha_retorno = ?, recibido_por = ?, observaciones = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (estado, fecha_retorno or None, recibido_por, observaciones, id))
        conn.commit()
        flash('Seguimiento actualizado correctamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando seguimiento: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('seguimiento'))


@app.route('/seguimiento/eliminar/<int:id>', methods=['POST'])
def eliminar_seguimiento(id):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM seguimiento_herramientas WHERE id = ?', (id,))
        conn.commit()
        flash('Registro de seguimiento eliminado.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error eliminando seguimiento: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('seguimiento'))


@app.route('/avances', methods=['GET', 'POST'])
def avances():
    conn = get_db_connection()

    if request.method == 'POST':
        fecha = clean_text(request.form.get('fecha'))
        actividad = clean_text(request.form.get('actividad'))
        personal_nombre = clean_text(request.form.get('personal'))
        solicitado_por = clean_text(request.form.get('solicitado_por'))
        edificio = clean_text(request.form.get('edificio'))
        proyecto = clean_text(request.form.get('proyecto'))
        estado = clean_text(request.form.get('estado')) or 'EN_PROCESO'
        detalles = clean_text(request.form.get('detalles'))
        observaciones = clean_text(request.form.get('observaciones'))

        if not fecha or not actividad or not personal_nombre:
            flash('Complete fecha, actividad y personal responsable.', 'danger')
            conn.close()
            return redirect(url_for('avances'))

        try:
            conn.execute(
                '''
                INSERT INTO avances_actividades (
                    fecha, actividad, personal, solicitado_por, edificio, proyecto,
                    estado, detalles, observaciones
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    fecha,
                    actividad,
                    personal_nombre,
                    solicitado_por,
                    edificio,
                    proyecto,
                    estado,
                    detalles,
                    observaciones
                )
            )
            conn.commit()
            flash('Avance o nota registrada correctamente.', 'success')

        except Exception as e:
            conn.rollback()
            flash(f'Error registrando avance: {e}', 'danger')

        finally:
            conn.close()

        return redirect(url_for('avances'))

    f_estado = clean_text(request.args.get('estado'))
    f_personal = clean_text(request.args.get('personal'))
    f_fecha = clean_text(request.args.get('fecha'))
    q = clean_text(request.args.get('q'))

    query = '''
        SELECT *
        FROM avances_actividades
        WHERE 1 = 1
    '''
    params = []

    if f_estado:
        query += ' AND estado = ?'
        params.append(f_estado)

    if f_personal:
        query += ' AND personal = ?'
        params.append(f_personal)

    if f_fecha:
        query += ' AND fecha = ?'
        params.append(f_fecha)

    if q:
        query += '''
            AND (
                actividad LIKE ?
                OR solicitado_por LIKE ?
                OR edificio LIKE ?
                OR proyecto LIKE ?
                OR detalles LIKE ?
                OR observaciones LIKE ?
            )
        '''
        like = f'%{q}%'
        params.extend([like, like, like, like, like, like])

    registros = conn.execute(
        query + ' ORDER BY fecha DESC, id DESC',
        params
    ).fetchall()

    personal = conn.execute('SELECT nombre FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT nombre, ubicacion, mapa_url FROM edificios ORDER BY nombre').fetchall()

    resumen = {
        'total': conn.execute('SELECT COUNT(*) FROM avances_actividades').fetchone()[0],
        'hoy': conn.execute("SELECT COUNT(*) FROM avances_actividades WHERE fecha = date('now','localtime')").fetchone()[0],
        'proceso': conn.execute("SELECT COUNT(*) FROM avances_actividades WHERE estado = 'EN_PROCESO'").fetchone()[0],
        'terminado': conn.execute("SELECT COUNT(*) FROM avances_actividades WHERE estado = 'TERMINADO'").fetchone()[0],
    }

    conn.close()

    return render_template(
        'avances.html',
        registros=registros,
        personal=personal,
        edificios=edificios,
        resumen=resumen,
        f_estado=f_estado,
        f_personal=f_personal,
        f_fecha=f_fecha,
        q=q,
        estados=['PENDIENTE', 'EN_PROCESO', 'TERMINADO', 'OBSERVADO', 'CANCELADO']
    )


@app.route('/avances/actualizar/<int:id>', methods=['POST'])
def actualizar_avance(id):
    conn = get_db_connection()

    estado = clean_text(request.form.get('estado')) or 'EN_PROCESO'
    observaciones_nuevas = clean_text(request.form.get('observaciones'))

    try:
        actual = conn.execute(
            'SELECT observaciones FROM avances_actividades WHERE id = ?',
            (id,)
        ).fetchone()

        if not actual:
            flash('Registro de avance no encontrado.', 'warning')
            conn.close()
            return redirect(url_for('avances'))

        observaciones = actual['observaciones'] or ''
        if observaciones_nuevas:
            observaciones = (observaciones + '\n' if observaciones else '') + observaciones_nuevas

        conn.execute(
            '''
            UPDATE avances_actividades
            SET estado = ?,
                observaciones = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (estado, observaciones, id)
        )

        conn.commit()
        flash('Avance actualizado correctamente.', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Error actualizando avance: {e}', 'danger')

    finally:
        conn.close()

    return redirect(url_for('avances'))


@app.route('/avances/eliminar/<int:id>', methods=['POST'])
def eliminar_avance(id):
    conn = get_db_connection()

    try:
        conn.execute('DELETE FROM avances_actividades WHERE id = ?', (id,))
        conn.commit()
        flash('Registro de avance eliminado.', 'success')

    except Exception as e:
        conn.rollback()
        flash(f'Error eliminando avance: {e}', 'danger')

    finally:
        conn.close()

    return redirect(url_for('avances'))


if __name__ == '__main__':
    modo_debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', '5051'))

    if modo_debug:
        print('AVISO: el modo debug esta activo. NO uses esta configuracion en produccion:')
        print('       expone un debugger interactivo que permite ejecutar codigo en el servidor.')
    if host == '0.0.0.0':
        print('AVISO: el servidor escuchara en todas las interfaces de red (0.0.0.0).')
        print('       Asegurate de que la red sea confiable o de usar un reverse proxy con HTTPS.')

    app.run(host=host, port=port, debug=modo_debug)
