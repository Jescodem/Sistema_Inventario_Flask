from flask import Flask, render_template, request, redirect, url_for, json, flash, send_file
import sqlite3
import os
import io
import re
from collections import defaultdict

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, 'inventario.db')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'inventario-dev-key-change-me')

ESTADOS_EQUIPO = ['En Stock', 'En Revision', 'En Transito', 'Instalado', 'Baja']
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


def registrar_movimiento(conn, equipo_id, tipo, cantidad, stock_anterior, stock_nuevo,
                         guia_id=None, referencia=None, usuario='Sistema', observaciones='',
                         permitir_cero=False):
    cantidad = safe_int(cantidad)
    if cantidad < 0:
        return
    if cantidad == 0 and not permitir_cero:
        return
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


def parse_productos_json(raw_productos):
    if not raw_productos:
        return None, 'Debe agregar al menos un producto.'
    try:
        data = json.loads(raw_productos)
    except Exception:
        return None, 'El detalle de productos no tiene un formato valido.'

    if not isinstance(data, list) or len(data) == 0:
        return None, 'Debe agregar al menos un producto.'

    acumulado = defaultdict(int)
    for item in data:
        equipo_id = safe_int(item.get('id')) if isinstance(item, dict) else 0
        cantidad = safe_int(item.get('cantidad')) if isinstance(item, dict) else 0
        if equipo_id <= 0:
            return None, 'Existe un producto invalido en la guia.'
        if cantidad <= 0:
            return None, 'Las cantidades deben ser mayores a cero.'
        acumulado[equipo_id] += cantidad

    productos = [{'id': equipo_id, 'cantidad': cantidad} for equipo_id, cantidad in acumulado.items()]
    return productos, None


def validar_productos_para_guia(conn, productos, old_map=None):
    old_map = old_map or {}
    equipos_validados = {}
    errores = []

    for item in productos:
        equipo_id = item['id']
        nueva_cantidad = item['cantidad']
        cantidad_anterior_guia = old_map.get(equipo_id, 0)

        equipo = conn.execute('''
            SELECT id, marca, descripcion, sku, cantidad, estado
            FROM equipos
            WHERE id = ?
        ''', (equipo_id,)).fetchone()

        if not equipo:
            errores.append(f'El producto ID {equipo_id} no existe.')
            continue

        estado = normalize_estado(equipo['estado'])
        delta = nueva_cantidad - cantidad_anterior_guia
        disponible = equipo['cantidad'] + cantidad_anterior_guia

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


def contar_uso_equipo(conn, equipo_id):
    """Devuelve contadores de uso para decidir si un producto puede eliminarse fisicamente."""
    movimientos = conn.execute(
        'SELECT COUNT(*) FROM movimientos WHERE equipo_id = ?',
        (equipo_id,)
    ).fetchone()[0]
    salidas = conn.execute(
        'SELECT COUNT(*) FROM salidas WHERE equipo_id = ?',
        (equipo_id,)
    ).fetchone()[0]
    guias = conn.execute(
        'SELECT COUNT(*) FROM guia_detalle WHERE equipo_id = ?',
        (equipo_id,)
    ).fetchone()[0]
    guias_activas = conn.execute('''
        SELECT COUNT(*)
        FROM guia_detalle gd
        JOIN guias_salida g ON g.id = gd.guia_id
        WHERE gd.equipo_id = ?
        AND COALESCE(g.estado, 'ACTIVA') = 'ACTIVA'
    ''', (equipo_id,)).fetchone()[0]
    return {
        'movimientos': movimientos,
        'salidas': salidas,
        'guias': guias,
        'guias_activas': guias_activas,
        'total': movimientos + salidas + guias
    }


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
    conn.execute('CREATE TABLE IF NOT EXISTS modelos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS cargos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL, cargo TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS edificios (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE NOT NULL)')

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

    # Migraciones ligeras para bases existentes
    add_column_if_missing(conn, 'equipos', 'stock_minimo', 'INTEGER NOT NULL DEFAULT 0')
    add_column_if_missing(conn, 'equipos', 'fecha_creacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'equipos', 'fecha_actualizacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'guias_salida', 'cargo', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'proyecto', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'entregado_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'recibido_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'aprobado_por', 'TEXT')
    add_column_if_missing(conn, 'guias_salida', 'estado', "TEXT DEFAULT 'ACTIVA'")
    add_column_if_missing(conn, 'guias_salida', 'fecha_anulacion', 'TIMESTAMP')
    add_column_if_missing(conn, 'guias_salida', 'motivo_anulacion', 'TEXT')

    # Normaliza valores antiguos con acentos para evitar comparaciones mixtas.
    conn.execute("UPDATE equipos SET estado = 'En Revision' WHERE estado = 'En Revisión'")
    conn.execute("UPDATE equipos SET estado = 'En Transito' WHERE estado = 'En Tránsito'")
    conn.execute("UPDATE equipos SET fecha_creacion = CURRENT_TIMESTAMP WHERE fecha_creacion IS NULL")

    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_descripcion ON equipos(descripcion)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_equipos_sku ON equipos(sku)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_guias_estado ON guias_salida(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_guia_detalle_guia ON guia_detalle(guia_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_equipo ON movimientos(equipo_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_movimientos_guia ON movimientos(guia_id)')

    if conn.execute('SELECT COUNT(*) FROM categorias').fetchone()[0] == 0:
        conn.executemany('INSERT INTO categorias (nombre) VALUES (?)', [
            ('CCTV',), ('Control de Accesos',), ('Redes',), ('Consumibles',)
        ])
    if conn.execute('SELECT COUNT(*) FROM marcas').fetchone()[0] == 0:
        conn.executemany('INSERT INTO marcas (nombre) VALUES (?)', [
            ('Hikvision',), ('Dahua',), ('Akuvox',), ('Cisco',), ('Fortinet',), ('Aruba',)
        ])
    if conn.execute('SELECT COUNT(*) FROM modelos').fetchone()[0] == 0:
        conn.executemany('INSERT INTO modelos (nombre) VALUES (?)', [
            ('Camara Domo IP 4MP',), ('Intercomunicador R29C',), ('Bobina Cable UTP Cat6',)
        ])
    if conn.execute('SELECT COUNT(*) FROM cargos').fetchone()[0] == 0:
        conn.executemany('INSERT INTO cargos (nombre) VALUES (?)', [
            ('Tecnico Instalador',), ('Ingeniero de Proyectos',), ('Soporte Tecnico',), ('Almacenero',)
        ])
    if conn.execute('SELECT COUNT(*) FROM personal').fetchone()[0] == 0:
        conn.executemany('INSERT INTO personal (nombre, cargo) VALUES (?, ?)', [
            ('Juan Perez', 'Tecnico Instalador'), ('Carlos Gomez', 'Ingeniero de Proyectos')
        ])

    conn.commit()
    conn.close()


@app.context_processor
def utility_processor():
    return dict(guia_codigo=guia_codigo)


@app.route('/')
def index():
    conn = get_db_connection()
    search_query = request.args.get('q', '')
    categoria_filter = request.args.get('categoria', '')
    estado_filter = request.args.get('estado', '')

    query = 'SELECT * FROM equipos WHERE 1=1'
    params = []
    if search_query:
        query += ' AND (descripcion LIKE ? OR sku LIKE ? OR mac LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
    if categoria_filter:
        query += ' AND categoria = ?'
        params.append(categoria_filter)
    if estado_filter:
        query += ' AND estado = ?'
        params.append(normalize_estado(estado_filter))
    else:
        query += " AND estado <> 'Baja'"

    query += ' ORDER BY id DESC'
    equipos = conn.execute(query, params).fetchall()

    total_stock = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Stock"').fetchone()[0] or 0
    en_revision = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Revision"').fetchone()[0] or 0
    critico = conn.execute('''
        SELECT COUNT(*) FROM equipos
        WHERE estado = 'En Stock'
        AND cantidad <= CASE WHEN stock_minimo > 0 THEN stock_minimo ELSE 5 END
    ''').fetchone()[0] or 0

    categorias_db = conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()
    conn.close()
    return render_template(
        'index.html', equipos=equipos, total_stock=total_stock,
        en_revision=en_revision, critico=critico,
        search_query=search_query, categoria_filter=categoria_filter,
        estado_filter=estado_filter, categorias_db=categorias_db,
        estados=ESTADOS_EQUIPO
    )


@app.route('/eliminar_equipo/<int:id>', methods=['POST'])
def eliminar_equipo(id):
    conn = get_db_connection()
    try:
        equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (id,)).fetchone()
        if not equipo:
            flash('El producto seleccionado no existe.', 'danger')
            return redirect(url_for('index'))

        uso = contar_uso_equipo(conn, id)
        motivo = clean_text(request.form.get('motivo_baja')) or 'Baja solicitada desde el dashboard de inventario.'

        if normalize_estado(equipo['estado']) == 'Baja':
            flash('El producto ya se encuentra dado de baja.', 'warning')
            return redirect(url_for('index', estado='Baja'))

        if uso['guias_activas'] > 0:
            flash(
                'No se puede dar de baja este producto porque esta asociado a guias activas. '
                'Primero regulariza, edita o anula esas guias.',
                'warning'
            )
            return redirect(url_for('index'))

        if uso['total'] == 0:
            conn.execute('DELETE FROM equipos WHERE id = ?', (id,))
            conn.commit()
            flash('Producto eliminado fisicamente porque no tenia historial asociado.', 'success')
            return redirect(url_for('index'))

        stock_anterior = safe_int(equipo['cantidad'])
        stock_nuevo = 0
        cantidad_movimiento = stock_anterior

        conn.execute('''
            UPDATE equipos
            SET estado = 'Baja',
                cantidad = 0,
                fecha_actualizacion = CURRENT_TIMESTAMP,
                observaciones = CASE
                    WHEN observaciones IS NULL OR observaciones = '' THEN ?
                    ELSE observaciones || char(10) || ?
                END
            WHERE id = ?
        ''', (f'BAJA: {motivo}', f'BAJA: {motivo}', id))

        registrar_movimiento(
            conn, id, 'BAJA', cantidad_movimiento, stock_anterior, stock_nuevo,
            referencia=f'BAJA-{id:06d}', observaciones=motivo, permitir_cero=True
        )

        conn.commit()
        flash(
            'Producto dado de baja correctamente. Se conservo el historial y se registro el movimiento de baja.',
            'success'
        )

    except Exception as e:
        conn.rollback()
        flash(f'Error dando de baja el producto: {e}', 'danger')
    finally:
        conn.close()

    return redirect(url_for('index'))


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
        if not catalog_exists(conn, 'modelos', descripcion):
            errores.append('El modelo seleccionado no existe.')
        if cantidad <= 0:
            errores.append('La cantidad debe ser mayor a cero.')
        if stock_minimo < 0:
            errores.append('El stock minimo no puede ser negativo.')
        if estado not in ESTADOS_EQUIPO:
            errores.append('El estado seleccionado no es valido.')
        if not validar_mac(mac):
            errores.append('La direccion MAC no tiene un formato valido.')
        if sku and conn.execute('SELECT 1 FROM equipos WHERE sku = ?', (sku,)).fetchone():
            errores.append('Ya existe un equipo con ese SKU o numero de serie.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.close()
            return redirect(url_for('ingresos'))

        cursor = conn.execute('''
            INSERT INTO equipos (
                categoria, marca, descripcion, sku, mac, cantidad, estado,
                observaciones, stock_minimo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            categoria, marca, descripcion, sku, mac, cantidad, estado,
            observaciones, stock_minimo
        ))
        equipo_id = cursor.lastrowid
        registrar_movimiento(
            conn, equipo_id, 'INGRESO', cantidad, 0, cantidad,
            referencia=f'ING-{equipo_id:06d}', observaciones='Ingreso inicial de inventario.'
        )
        conn.commit()
        conn.close()
        flash('Ingreso registrado correctamente.', 'success')
        return redirect(url_for('index'))

    categorias_db = conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()
    marcas_db = conn.execute('SELECT nombre FROM marcas ORDER BY nombre').fetchall()
    modelos_db = conn.execute('SELECT nombre FROM modelos ORDER BY nombre').fetchall()
    conn.close()
    return render_template(
        'ingresos.html', categorias_db=categorias_db, marcas_db=marcas_db,
        modelos_db=modelos_db, estados=ESTADOS_EQUIPO
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
        if equipo and cantidad_salida > equipo['cantidad']:
            errores.append('Stock insuficiente para el despacho.')

        if errores:
            for error in errores:
                flash(error, 'danger')
            conn.close()
            return redirect(url_for('salidas'))

        stock_anterior = equipo['cantidad']
        stock_nuevo = stock_anterior - cantidad_salida
        conn.execute('UPDATE equipos SET cantidad = ?, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?', (stock_nuevo, equipo_id))
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
        SELECT *
        FROM equipos
        WHERE cantidad > 0 AND estado = 'En Stock'
        ORDER BY descripcion
    ''').fetchall()
    conn.close()
    return render_template('guias.html', personal=personal, edificios=edificios, equipos=equipos)


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

        cursor = conn.execute('''
            INSERT INTO guias_salida (
                personal, destino, cargo, proyecto,
                entregado_por, recibido_por, aprobado_por, observaciones,
                estado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVA')
        ''', (
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

            conn.execute('''
                INSERT INTO guia_detalle (guia_id, equipo_id, cantidad)
                VALUES (?, ?, ?)
            ''', (guia_id, equipo_id, cantidad))

            conn.execute('''
                UPDATE equipos
                SET cantidad = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (stock_nuevo, equipo_id))

            registrar_movimiento(
                conn, equipo_id, 'SALIDA_GUIA', cantidad, stock_anterior, stock_nuevo,
                guia_id=guia_id, referencia=referencia,
                observaciones=f'Guia emitida para {personal} / {destino}.'
            )

        conn.commit()
        flash(f'Guia {referencia} creada correctamente.', 'success')
        return redirect('/listar_guias')

    except Exception as e:
        conn.rollback()
        flash(f'Error guardando guia: {e}', 'danger')
        return redirect(url_for('guias'))
    finally:
        conn.close()


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

        detalle_actual = conn.execute('''
            SELECT equipo_id, cantidad
            FROM guia_detalle
            WHERE guia_id = ?
        ''', (id,)).fetchall()
        old_map = {row['equipo_id']: row['cantidad'] for row in detalle_actual}
        new_map = {item['id']: item['cantidad'] for item in productos}

        equipos_validados, errores_productos = validar_productos_para_guia(conn, productos, old_map=old_map)
        if errores_productos:
            for error in errores_productos:
                flash(error, 'danger')
            return redirect(f'/editar_guia/{id}')

        conn.execute('''
            UPDATE guias_salida
            SET personal = ?, destino = ?, cargo = ?, proyecto = ?,
                entregado_por = ?, recibido_por = ?, aprobado_por = ?,
                observaciones = ?
            WHERE id = ?
        ''', (
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

        referencia = guia_codigo(id)
        for equipo_id in sorted(set(old_map.keys()) | set(new_map.keys())):
            old_qty = old_map.get(equipo_id, 0)
            new_qty = new_map.get(equipo_id, 0)
            delta = new_qty - old_qty
            if delta == 0:
                continue

            equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
            if not equipo:
                raise ValueError(f'El equipo ID {equipo_id} ya no existe.')

            stock_anterior = equipo['cantidad']
            if delta > 0:
                if stock_anterior < delta:
                    raise ValueError(f'Stock insuficiente para actualizar el equipo ID {equipo_id}.')
                stock_nuevo = stock_anterior - delta
                tipo = 'SALIDA_GUIA'
                cantidad_mov = delta
                obs = 'Ajuste de guia: incremento de cantidad.'
            else:
                cantidad_mov = abs(delta)
                stock_nuevo = stock_anterior + cantidad_mov
                tipo = 'DEVOLUCION_GUIA'
                obs = 'Ajuste de guia: reintegro parcial o total al stock.'

            conn.execute('''
                UPDATE equipos
                SET cantidad = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (stock_nuevo, equipo_id))

            registrar_movimiento(
                conn, equipo_id, tipo, cantidad_mov, stock_anterior, stock_nuevo,
                guia_id=id, referencia=referencia, observaciones=obs
            )

        conn.execute('DELETE FROM guia_detalle WHERE guia_id = ?', (id,))
        for item in productos:
            conn.execute('''
                INSERT INTO guia_detalle (guia_id, equipo_id, cantidad)
                VALUES (?, ?, ?)
            ''', (id, item['id'], item['cantidad']))

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
        SELECT gd.equipo_id, gd.cantidad, e.marca, e.descripcion, e.sku, e.mac
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
    conn.close()
    return render_template('ver_guia.html', guia=guia, detalle=detalle, movimientos=movimientos)


@app.route('/eliminar_guia/<int:id>')
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

        detalle = conn.execute('''
            SELECT equipo_id, cantidad
            FROM guia_detalle
            WHERE guia_id = ?
        ''', (id,)).fetchall()

        referencia = guia_codigo(id)
        for item in detalle:
            equipo = conn.execute('SELECT * FROM equipos WHERE id = ?', (item['equipo_id'],)).fetchone()
            if not equipo:
                continue
            stock_anterior = equipo['cantidad']
            stock_nuevo = stock_anterior + item['cantidad']
            conn.execute('''
                UPDATE equipos
                SET cantidad = ?, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (stock_nuevo, item['equipo_id']))
            registrar_movimiento(
                conn, item['equipo_id'], 'DEVOLUCION_GUIA', item['cantidad'],
                stock_anterior, stock_nuevo, guia_id=id, referencia=referencia,
                observaciones='Anulacion de guia: reintegro automatico al inventario.'
            )

        conn.execute('''
            UPDATE guias_salida
            SET estado = 'ANULADA', fecha_anulacion = CURRENT_TIMESTAMP,
                motivo_anulacion = ?
            WHERE id = ?
        ''', ('Anulada desde el sistema.', id))
        conn.commit()
        flash(f'Guia {referencia} anulada. El stock fue reintegrado.', 'success')

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
        SELECT gd.equipo_id, gd.cantidad, e.descripcion, e.marca
        FROM guia_detalle gd
        INNER JOIN equipos e ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
    ''', (id,)).fetchall()
    personal = conn.execute('SELECT * FROM personal ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    equipos = conn.execute('SELECT * FROM equipos ORDER BY descripcion').fetchall()
    conn.close()

    return render_template(
        'editar_guia.html', guia=guia, detalle=detalle,
        personal=personal, edificios=edificios, equipos=equipos
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
        SELECT gd.cantidad, e.marca, e.descripcion, e.sku
        FROM guia_detalle gd
        INNER JOIN equipos e ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ORDER BY e.descripcion
    ''', (id,)).fetchall()
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Small', fontSize=8, leading=10))
    styles.add(ParagraphStyle(name='HeaderTitle', fontSize=16, leading=20, alignment=1, spaceAfter=8))

    elementos = []
    elementos.append(Paragraph('GUIA DE SALIDA DE ALMACEN', styles['HeaderTitle']))
    elementos.append(Paragraph(f"<b>Codigo:</b> {guia_codigo(id)} &nbsp;&nbsp; <b>Estado:</b> {guia['estado']}", styles['Normal']))
    elementos.append(Spacer(1, 10))

    info = [
        ['Solicitante', guia['personal'] or '', 'Cargo', guia['cargo'] or ''],
        ['Destino', guia['destino'] or '', 'Proyecto', guia['proyecto'] or ''],
        ['Fecha', guia['fecha'] or '', 'Aprobado por', guia['aprobado_por'] or ''],
        ['Entregado por', guia['entregado_por'] or '', 'Recibido por', guia['recibido_por'] or ''],
    ]
    tabla_info = Table(info, colWidths=[3*cm, 5.2*cm, 3*cm, 5.2*cm])
    tabla_info.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#EAF2F8')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#EAF2F8')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elementos.append(tabla_info)
    elementos.append(Spacer(1, 14))

    data = [['Item', 'Cantidad', 'Marca', 'Descripcion', 'SKU / Serie']]
    for idx, item in enumerate(detalle, start=1):
        data.append([idx, item['cantidad'], item['marca'], item['descripcion'], item['sku'] or '-'])
    tabla = Table(data, colWidths=[1.2*cm, 2*cm, 3*cm, 7*cm, 3.5*cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E78')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(f"<b>Observaciones:</b> {guia['observaciones'] or 'Sin observaciones.'}", styles['Normal']))
    elementos.append(Spacer(1, 34))

    firmas = Table([
        ['Entregado por', 'Recibido por', 'Aprobado por'],
        ['', '', ''],
        [guia['entregado_por'] or '', guia['recibido_por'] or '', guia['aprobado_por'] or '']
    ], colWidths=[5.4*cm, 5.4*cm, 5.4*cm], rowHeights=[0.6*cm, 1.2*cm, 0.6*cm])
    firmas.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LINEABOVE', (0, 2), (-1, 2), 0.8, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))
    elementos.append(firmas)

    doc.build(elementos)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True,
        download_name=f'{guia_codigo(id)}.pdf', mimetype='application/pdf'
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
        tablas = {
            'categoria': 'categorias',
            'marca': 'marcas',
            'modelo': 'modelos',
            'cargo': 'cargos',
            'edificio': 'edificios'
        }
        tabla = tablas.get(tipo)
        if not tabla or not nombre:
            flash('Dato de configuracion invalido.', 'danger')
        else:
            try:
                conn.execute(f'INSERT INTO {tabla} (nombre) VALUES (?)', (nombre,))
                conn.commit()
                flash('Catalogo actualizado correctamente.', 'success')
            except sqlite3.IntegrityError:
                flash('Ese valor ya existe en el catalogo.', 'warning')
        conn.close()
        return redirect(url_for('configuracion'))

    categorias = conn.execute('SELECT * FROM categorias ORDER BY nombre').fetchall()
    marcas = conn.execute('SELECT * FROM marcas ORDER BY nombre').fetchall()
    modelos = conn.execute('SELECT * FROM modelos ORDER BY nombre').fetchall()
    cargos = conn.execute('SELECT * FROM cargos ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    conn.close()
    return render_template('configuracion.html', categorias=categorias, marcas=marcas, modelos=modelos, cargos=cargos, edificios=edificios)


@app.route('/editar_catalogo/<tipo>/<int:id>', methods=['POST'])
def editar_catalogo(tipo, id):
    nuevo_nombre = clean_text(request.form.get('nuevo_nombre'))
    tablas = {
        'categoria': ('categorias', 'categoria', 'equipos'),
        'marca': ('marcas', 'marca', 'equipos'),
        'modelo': ('modelos', 'descripcion', 'equipos'),
        'cargo': ('cargos', 'cargo', 'personal'),
        'edificio': ('edificios', 'destino', None),
    }
    if nuevo_nombre and tipo in tablas:
        conn = get_db_connection()
        tabla, campo_relacionado, tabla_relacionada = tablas[tipo]
        actual = conn.execute(f'SELECT nombre FROM {tabla} WHERE id = ?', (id,)).fetchone()
        if actual:
            try:
                conn.execute(f'UPDATE {tabla} SET nombre = ? WHERE id = ?', (nuevo_nombre, id))
                if tabla_relacionada:
                    conn.execute(f'UPDATE {tabla_relacionada} SET {campo_relacionado} = ? WHERE {campo_relacionado} = ?', (nuevo_nombre, actual['nombre']))
                elif tipo == 'edificio':
                    conn.execute('UPDATE guias_salida SET destino = ? WHERE destino = ?', (nuevo_nombre, actual['nombre']))
                    conn.execute('UPDATE salidas SET destino = ? WHERE destino = ?', (nuevo_nombre, actual['nombre']))
                conn.commit()
                flash('Catalogo editado correctamente.', 'success')
            except sqlite3.IntegrityError:
                flash('No se pudo editar: el nombre ya existe.', 'warning')
        conn.close()
    return redirect(url_for('configuracion'))


@app.route('/eliminar_catalogo/<tipo>/<int:id>', methods=['POST'])
def eliminar_catalogo(tipo, id):
    conn = get_db_connection()
    tablas = {
        'categoria': ('categorias', 'categoria', 'equipos'),
        'marca': ('marcas', 'marca', 'equipos'),
        'modelo': ('modelos', 'descripcion', 'equipos'),
        'cargo': ('cargos', 'cargo', 'personal'),
        'edificio': ('edificios', 'destino', None),
    }
    if tipo in tablas:
        tabla, campo, tabla_rel = tablas[tipo]
        row = conn.execute(f'SELECT nombre FROM {tabla} WHERE id = ?', (id,)).fetchone()
        if row:
            usado = 0
            if tabla_rel:
                usado = conn.execute(f'SELECT COUNT(*) FROM {tabla_rel} WHERE {campo} = ?', (row['nombre'],)).fetchone()[0]
            elif tipo == 'edificio':
                usado = conn.execute('SELECT COUNT(*) FROM guias_salida WHERE destino = ?', (row['nombre'],)).fetchone()[0]
                usado += conn.execute('SELECT COUNT(*) FROM salidas WHERE destino = ?', (row['nombre'],)).fetchone()[0]
            if usado > 0:
                flash('No se puede eliminar porque ya esta siendo usado en registros.', 'warning')
            else:
                conn.execute(f'DELETE FROM {tabla} WHERE id = ?', (id,))
                conn.commit()
                flash('Catalogo eliminado correctamente.', 'success')
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
    return _agregar_catalogo_rapido('categorias', 'ingresos')


@app.route('/agregar_marca', methods=['POST'])
def agregar_marca():
    return _agregar_catalogo_rapido('marcas', 'ingresos')


@app.route('/agregar_modelo', methods=['POST'])
def agregar_modelo():
    return _agregar_catalogo_rapido('modelos', 'ingresos')


def _agregar_catalogo_rapido(tabla, endpoint):
    nombre = clean_text(request.form.get('nombre'))
    conn = get_db_connection()
    if nombre:
        try:
            conn.execute(f'INSERT INTO {tabla} (nombre) VALUES (?)', (nombre,))
            conn.commit()
            flash('Catalogo agregado correctamente.', 'success')
        except sqlite3.IntegrityError:
            flash('Ese valor ya existe.', 'warning')
    conn.close()
    return redirect(url_for(endpoint))


@app.route('/edificios', methods=['GET', 'POST'])
def edificios():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = clean_text(request.form.get('nombre'))
        if nombre:
            try:
                conn.execute('INSERT INTO edificios (nombre) VALUES (?)', (nombre,))
                conn.commit()
                flash('Edificio registrado correctamente.', 'success')
            except sqlite3.IntegrityError:
                flash('Ese edificio ya existe.', 'warning')
        conn.close()
        return redirect(url_for('edificios'))
    lista = conn.execute('SELECT * FROM edificios ORDER BY nombre ASC').fetchall()
    conn.close()
    return render_template('edificios.html', edificios=lista)


@app.route('/edificios/eliminar/<int:id>')
def eliminar_edificio(id):
    conn = get_db_connection()
    edificio = conn.execute('SELECT nombre FROM edificios WHERE id = ?', (id,)).fetchone()
    if edificio:
        usado = conn.execute('SELECT COUNT(*) FROM guias_salida WHERE destino = ?', (edificio['nombre'],)).fetchone()[0]
        usado += conn.execute('SELECT COUNT(*) FROM salidas WHERE destino = ?', (edificio['nombre'],)).fetchone()[0]
        if usado > 0:
            flash('No se puede eliminar un edificio usado en guias o salidas.', 'warning')
        else:
            conn.execute('DELETE FROM edificios WHERE id = ?', (id,))
            conn.commit()
            flash('Edificio eliminado correctamente.', 'success')
    conn.close()
    return redirect(url_for('edificios'))


# Inicializa y migra la base tanto con python app.py como con flask run.
init_db()

if __name__ == '__main__':
    app.run(debug=True)
