"""
db.py — Capa de acceso a datos de Portero Seguro.

Centraliza:
- Resolución de la ruta de la base de datos (variable de entorno PORTERO_DB
  permite apuntar a otra base, útil para tests y entornos separados).
- Creación de conexiones con PRAGMAs correctos (foreign_keys, busy_timeout).
- Inicialización del esquema y migraciones idempotentes.
"""
import os
import sqlite3

from auth import hash_password, generar_password_temporal

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.environ.get('PORTERO_DB', os.path.join(BASE_DIR, 'inventario.db'))

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    # Espera hasta 5s si otra conexión tiene la BD bloqueada, en vez de
    # fallar inmediatamente con "database is locked" bajo concurrencia.
    conn.execute('PRAGMA busy_timeout = 5000')
    return conn


def clean_text(value):
    return (value or '').strip()

def normalizar_estados_por_stock(conn):
    conn.execute("UPDATE equipos SET estado = 'Sin Stock' WHERE COALESCE(cantidad,0) <= 0 AND estado = 'En Stock'")
    conn.execute("UPDATE equipos SET estado = 'En Stock' WHERE COALESCE(cantidad,0) > 0 AND estado = 'Sin Stock'")

def table_columns(conn, table):
    return [row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]

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


def add_column_if_missing(conn, table, column, definition):
    if column not in table_columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


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

    # Red de cada edificio: puntos/equipos con su IP y anexo telefonico
    # (intercom de calle, telefono de lobby, altavoz, DVR, Mikrotik...).
    # Se muestran al expandir el edificio en /edificios; se cargan desde el
    # Excel corporativo con importar_ips_edificios.py. Incluye las
    # credenciales de los equipos por decision del administrador: cualquier
    # usuario del sistema con sesion puede verlas.
    conn.execute('''
        CREATE TABLE IF NOT EXISTS edificio_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edificio_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            ip TEXT,
            anexo TEXT,
            descripcion TEXT,
            usuario TEXT,
            clave TEXT,
            orden INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (edificio_id) REFERENCES edificios(id)
        )
    ''')
    add_column_if_missing(conn, 'edificio_ips', 'usuario', 'TEXT')
    add_column_if_missing(conn, 'edificio_ips', 'clave', 'TEXT')

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

    # Entregas de herramientas al personal: registro de que se le entrega a
    # cada persona, con acta imprimible y control de devolucion. Cabecera +
    # detalle (una fila por herramienta entregada).
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entregas_herramientas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            personal TEXT NOT NULL,
            cargo TEXT,
            entregado_por TEXT,
            proyecto TEXT,
            observaciones TEXT,
            estado TEXT NOT NULL DEFAULT 'ACTIVA',
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_devolucion TIMESTAMP,
            recibido_por TEXT,
            motivo_devolucion TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS entrega_herramienta_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_id INTEGER NOT NULL,
            herramienta TEXT NOT NULL,
            cantidad INTEGER NOT NULL DEFAULT 1,
            descripcion TEXT,
            estado TEXT NOT NULL DEFAULT 'ENTREGADA',
            FOREIGN KEY (entrega_id) REFERENCES entregas_herramientas(id)
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
    conn.execute('CREATE INDEX IF NOT EXISTS idx_edificio_ips_edificio ON edificio_ips(edificio_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entregas_herr_estado ON entregas_herramientas(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entregas_herr_personal ON entregas_herramientas(personal)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_entrega_herr_detalle ON entrega_herramienta_detalle(entrega_id)')

    migrar_ubicaciones(conn)
    migrar_usuarios(conn)

    conn.commit()
    conn.close()


def migrar_ubicaciones(conn):
    """Normaliza ubicacion_actual en equipo_series para registros historicos.

    - Series EN_STOCK sin ubicacion → 'Almacén'
    - Series ENTREGADO sin ubicacion → toma el destino de la guia que las tiene asignadas
    - Series BAJA sin ubicacion → 'Dado de baja'
    """
    # Series en stock sin ubicacion conocida
    conn.execute("""
        UPDATE equipo_series
        SET ubicacion_actual = 'Almacén'
        WHERE estado = 'EN_STOCK'
          AND (ubicacion_actual IS NULL OR ubicacion_actual = '')
    """)

    # Series entregadas: tomar el destino de la ultima guia activa que las contiene
    conn.execute("""
        UPDATE equipo_series
        SET ubicacion_actual = COALESCE(
            (SELECT gs.destino
             FROM guia_detalle_series gds
             JOIN guia_detalle gd ON gd.id = gds.guia_detalle_id
             JOIN guias_salida gs ON gs.id = gd.guia_id
             WHERE gds.serie_id = equipo_series.id
               AND gs.estado = 'ACTIVA'
             ORDER BY gs.id DESC
             LIMIT 1),
            'Despachado'
        )
        WHERE estado = 'ENTREGADO'
          AND (ubicacion_actual IS NULL OR ubicacion_actual = '')
    """)

    # Series dadas de baja
    conn.execute("""
        UPDATE equipo_series
        SET ubicacion_actual = 'Dado de baja'
        WHERE estado = 'BAJA'
          AND (ubicacion_actual IS NULL OR ubicacion_actual = '')
    """)


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
