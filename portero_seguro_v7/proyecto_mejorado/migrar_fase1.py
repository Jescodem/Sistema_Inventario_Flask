import sqlite3
from pathlib import Path

DB = Path(__file__).with_name('inventario.db')


def clean_text(value):
    return (value or '').strip()


def columns(conn, table):
    return [row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]


def add_column(conn, table, column, definition):
    if column not in columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def ensure_catalog_value(conn, table, nombre):
    nombre = clean_text(nombre)
    if not nombre:
        return None
    row = conn.execute(f'SELECT id FROM {table} WHERE nombre = ?', (nombre,)).fetchone()
    if row:
        return row['id']
    cur = conn.execute(f'INSERT INTO {table} (nombre) VALUES (?)', (nombre,))
    return cur.lastrowid


def ensure_categoria_marca(conn, categoria, marca):
    categoria = clean_text(categoria)
    marca = clean_text(marca)
    if not categoria or not marca:
        return
    ensure_catalog_value(conn, 'categorias', categoria)
    ensure_catalog_value(conn, 'marcas', marca)
    conn.execute('INSERT OR IGNORE INTO categoria_marca (categoria, marca) VALUES (?, ?)', (categoria, marca))


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


def ensure_modelo(conn, nombre, categoria, marca):
    nombre = clean_text(nombre)
    categoria = clean_text(categoria)
    marca = clean_text(marca)
    if not nombre or not categoria or not marca:
        return None
    ensure_categoria_marca(conn, categoria, marca)
    row = conn.execute('''
        SELECT id FROM modelos
        WHERE nombre = ? AND categoria = ? AND marca = ?
    ''', (nombre, categoria, marca)).fetchone()
    if row:
        return row['id']
    row = conn.execute('SELECT id, categoria, marca FROM modelos WHERE nombre = ? ORDER BY id LIMIT 1', (nombre,)).fetchone()
    if row and (not clean_text(row['categoria']) or not clean_text(row['marca'])):
        conn.execute('UPDATE modelos SET categoria = ?, marca = ? WHERE id = ?', (categoria, marca, row['id']))
        return row['id']
    try:
        cur = conn.execute('INSERT INTO modelos (nombre, categoria, marca) VALUES (?, ?, ?)', (nombre, categoria, marca))
        return cur.lastrowid
    except sqlite3.IntegrityError:
        row = conn.execute('SELECT id FROM modelos WHERE nombre = ? LIMIT 1', (nombre,)).fetchone()
        if row:
            conn.execute('UPDATE modelos SET categoria = ?, marca = ? WHERE id = ?', (categoria, marca, row['id']))
            return row['id']
        raise



def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,)
    ).fetchone() is not None


def preservar_serie_referencia_desde_equipo(conn, equipo_row, equipo_destino_id=None):
    if not equipo_row or not table_exists(conn, 'equipo_series'):
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
    if not table_exists(conn, 'equipos'):
        return 0

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
        target = conn.execute('SELECT * FROM equipos WHERE id = ?', (target_id,)).fetchone()
        preservar_serie_referencia_desde_equipo(conn, target, target_id)

        for dup_id in duplicate_ids:
            dup = conn.execute('SELECT * FROM equipos WHERE id = ?', (dup_id,)).fetchone()
            preservar_serie_referencia_desde_equipo(conn, dup, target_id)
            for tabla in ['salidas', 'movimientos', 'seguimiento_equipos', 'equipo_series']:
                if table_exists(conn, tabla):
                    try:
                        conn.execute(
                            f'UPDATE {tabla} SET equipo_id = ? WHERE equipo_id = ?',
                            (target_id, dup_id)
                        )
                    except sqlite3.OperationalError:
                        pass

            if table_exists(conn, 'guia_detalle'):
                conn.execute(
                    'UPDATE guia_detalle SET equipo_id = ? WHERE equipo_id = ?',
                    (target_id, dup_id)
                )

            conn.execute('DELETE FROM equipos WHERE id = ?', (dup_id,))
            consolidados += 1

        if table_exists(conn, 'guia_detalle'):
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
                    if table_exists(conn, 'guia_detalle_series'):
                        conn.execute(
                            'UPDATE guia_detalle_series SET guia_detalle_id = ? WHERE guia_detalle_id = ?',
                            (keep_id, old_detalle_id)
                        )
                    conn.execute('DELETE FROM guia_detalle WHERE id = ?', (old_detalle_id,))

        if grupo['control_stock'] == 'SERIAL' and table_exists(conn, 'equipo_series'):
            total = conn.execute("""
                SELECT COUNT(*)
                FROM equipo_series
                WHERE equipo_id = ?
                  AND estado = 'EN_STOCK'
            """, (target_id,)).fetchone()[0]
            estado = 'En Stock' if total > 0 else 'Sin Stock'
            conn.execute(
                "UPDATE equipos SET cantidad = ?, estado = ?, control_stock = 'SERIAL', fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
                (total, estado, target_id)
            )
        else:
            cantidad_total = safe_int(grupo['cantidad_total'])
            estado = 'En Stock' if cantidad_total > 0 else 'Sin Stock'
            conn.execute(
                "UPDATE equipos SET cantidad = ?, estado = ?, control_stock = 'CANTIDAD', fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
                (cantidad_total, estado, target_id)
            )

    return consolidados


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA foreign_keys = ON')

# Tablas base si faltaran.
conn.execute('''
CREATE TABLE IF NOT EXISTS equipos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria TEXT NOT NULL DEFAULT '',
    marca TEXT NOT NULL DEFAULT '',
    descripcion TEXT NOT NULL DEFAULT '',
    sku TEXT,
    mac TEXT,
    estado TEXT NOT NULL DEFAULT 'En Stock',
    cantidad INTEGER NOT NULL DEFAULT 0,
    observaciones TEXT
)
''')
conn.execute('CREATE TABLE IF NOT EXISTS cargos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
conn.execute('CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL, cargo TEXT NOT NULL DEFAULT "")')
conn.execute('''
CREATE TABLE IF NOT EXISTS edificios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL,
    ubicacion TEXT,
    mapa_url TEXT,
    observaciones TEXT
)
''')
conn.execute('''
CREATE TABLE IF NOT EXISTS guias_salida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal TEXT NOT NULL DEFAULT '',
    destino TEXT NOT NULL DEFAULT '',
    observaciones TEXT,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
conn.execute('''
CREATE TABLE IF NOT EXISTS guia_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guia_id INTEGER NOT NULL,
    equipo_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL
)
''')
conn.execute('''
CREATE TABLE IF NOT EXISTS salidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id INTEGER NOT NULL,
    personal TEXT NOT NULL DEFAULT '',
    destino TEXT NOT NULL DEFAULT '',
    cantidad INTEGER NOT NULL DEFAULT 0,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    observaciones TEXT
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

conn.execute('''
CREATE TABLE IF NOT EXISTS categoria_marca (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria TEXT NOT NULL,
    marca TEXT NOT NULL,
    UNIQUE(categoria, marca)
)
''')

conn.execute('''
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
''')

conn.execute('''
CREATE TABLE IF NOT EXISTS guia_detalle_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guia_detalle_id INTEGER NOT NULL,
    serie_id INTEGER NOT NULL,
    UNIQUE(guia_detalle_id, serie_id),
    FOREIGN KEY (guia_detalle_id) REFERENCES guia_detalle(id),
    FOREIGN KEY (serie_id) REFERENCES equipo_series(id)
)
''')

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


for table, col, definition in [
    ('equipos', 'stock_minimo', 'INTEGER NOT NULL DEFAULT 0'),
    ('equipos', 'fecha_creacion', 'TIMESTAMP'),
    ('equipos', 'fecha_actualizacion', 'TIMESTAMP'),
    ('equipos', 'control_stock', "TEXT NOT NULL DEFAULT 'CANTIDAD'"),
    ('edificios', 'ubicacion', 'TEXT'),
    ('edificios', 'mapa_url', 'TEXT'),
    ('edificios', 'observaciones', 'TEXT'),
    ('modelos', 'categoria', 'TEXT'),
    ('modelos', 'marca', 'TEXT'),
    ('guias_salida', 'cargo', 'TEXT'),
    ('guias_salida', 'proyecto', 'TEXT'),
    ('guias_salida', 'entregado_por', 'TEXT'),
    ('guias_salida', 'recibido_por', 'TEXT'),
    ('guias_salida', 'aprobado_por', 'TEXT'),
    ('guias_salida', 'estado', "TEXT DEFAULT 'ACTIVA'"),
    ('guias_salida', 'fecha_anulacion', 'TIMESTAMP'),
    ('guias_salida', 'motivo_anulacion', 'TEXT'),
]:
    add_column(conn, table, col, definition)

conn.execute("UPDATE equipos SET estado = 'En Revision' WHERE estado = 'En Revisión'")
conn.execute("UPDATE equipos SET estado = 'En Transito' WHERE estado = 'En Tránsito'")
conn.execute("UPDATE equipos SET estado = 'Sin Stock' WHERE COALESCE(cantidad,0) <= 0 AND estado = 'En Stock'")
conn.execute("UPDATE equipos SET estado = 'En Stock' WHERE COALESCE(cantidad,0) > 0 AND estado = 'Sin Stock'")
conn.execute("UPDATE equipos SET fecha_creacion = CURRENT_TIMESTAMP WHERE fecha_creacion IS NULL")
conn.execute("UPDATE guias_salida SET estado = 'ACTIVA' WHERE estado IS NULL OR estado = ''")

for categoria in ['CCTV', 'Control de Accesos', 'Redes', 'Consumibles']:
    ensure_catalog_value(conn, 'categorias', categoria)
for marca in ['Hikvision', 'Dahua', 'Akuvox', 'Cisco', 'Fortinet', 'Aruba', 'Generico']:
    ensure_catalog_value(conn, 'marcas', marca)

for categoria, marca in [
    ('CCTV', 'Hikvision'),
    ('CCTV', 'Dahua'),
    ('Control de Accesos', 'Akuvox'),
    ('Redes', 'Cisco'),
    ('Redes', 'Fortinet'),
    ('Redes', 'Aruba'),
    ('Consumibles', 'Generico'),
]:
    ensure_categoria_marca(conn, categoria, marca)

for nombre, categoria, marca in [
    ('Camara Domo IP 4MP', 'CCTV', 'Hikvision'),
    ('Camara Bullet IP 4MP', 'CCTV', 'Hikvision'),
    ('NVR 16 Canales', 'CCTV', 'Hikvision'),
    ('Intercomunicador R29C', 'Control de Accesos', 'Akuvox'),
    ('Switch PoE 24 Puertos', 'Redes', 'Cisco'),
    ('Access Point Aruba', 'Redes', 'Aruba'),
    ('Firewall Fortinet', 'Redes', 'Fortinet'),
    ('Bobina Cable UTP Cat6', 'Consumibles', 'Generico'),
]:
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

conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_descripcion ON equipos(descripcion)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_sku ON equipos(sku)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_categoria_marca ON equipos(categoria, marca, descripcion)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_guias_estado ON guias_salida(estado)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_guia_detalle_guia ON guia_detalle(guia_id)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_equipo ON movimientos(equipo_id)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_guia ON movimientos(guia_id)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_categoria_marca_categoria ON categoria_marca(categoria)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_categoria_marca_marca ON categoria_marca(marca)')
conn.execute('CREATE INDEX IF NOT EXISTS idx_modelos_relacion ON modelos(categoria, marca, nombre)')
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

consolidados = consolidar_productos_duplicados(conn)
mov_count = conn.execute('SELECT COUNT(*) FROM movimientos').fetchone()[0]
if mov_count == 0:
    for equipo_id, cantidad in conn.execute('SELECT id, COALESCE(cantidad, 0) FROM equipos').fetchall():
        if cantidad > 0:
            conn.execute('''
                INSERT INTO movimientos (
                    equipo_id, guia_id, tipo, cantidad, stock_anterior, stock_nuevo,
                    referencia, usuario, observaciones
                )
                VALUES (?, NULL, 'AJUSTE', ?, 0, ?, ?, 'Sistema', 'Saldo inicial migrado a Fase 1 corporativa.')
            ''', (equipo_id, cantidad, cantidad, f'INI-{equipo_id:06d}'))

conn.commit()
conn.close()
print('Migracion Fase 1 + catalogos + serializacion completada:', DB)
if 'consolidados' in globals():
    print('Productos duplicados consolidados:', consolidados)
