from flask import Flask, render_template, request, redirect, url_for, json
import sqlite3

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from flask import send_file
import io

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('inventario.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Tablas existentes
    conn.execute('''
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT,
            marca TEXT,
            descripcion TEXT NOT NULL,
            sku TEXT,
            mac TEXT,
            estado TEXT,
            cantidad INTEGER DEFAULT 0,
            observaciones TEXT
        )
    ''')
    conn.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS marcas (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS modelos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS cargos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)')
    conn.execute('CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, cargo TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS edificios (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)')    # NUEVA TABLA: Historial de Salidas
    conn.execute('''
        CREATE TABLE IF NOT EXISTS salidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER,
            personal TEXT,
            destino TEXT,
            cantidad INTEGER,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            observaciones TEXT
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

        estado TEXT DEFAULT 'ACTIVA'
    )
    """)
    

    # Datos por defecto
    if conn.execute('SELECT COUNT(*) FROM categorias').fetchone()[0] == 0:
        conn.executemany('INSERT INTO categorias (nombre) VALUES (?)', [("CCTV",), ("Control de Accesos",), ("Redes",), ("Consumibles",)])
    if conn.execute('SELECT COUNT(*) FROM marcas').fetchone()[0] == 0:
        conn.executemany('INSERT INTO marcas (nombre) VALUES (?)', [("Hikvision",), ("Dahua",), ("Akuvox",), ("Cisco",), ("Fortinet",), ("Aruba",)])
    if conn.execute('SELECT COUNT(*) FROM modelos').fetchone()[0] == 0:
        conn.executemany('INSERT INTO modelos (nombre) VALUES (?)', [("Cámara Domo IP 4MP",), ("Intercomunicador R29C",), ("Bobina Cable UTP Cat6",)])
    if conn.execute('SELECT COUNT(*) FROM cargos').fetchone()[0] == 0:
        conn.executemany('INSERT INTO cargos (nombre) VALUES (?)', [("Técnico Instalador",), ("Ingeniero de Proyectos",), ("Soporte Técnico",), ("Almacenero",)])
    if conn.execute('SELECT COUNT(*) FROM personal').fetchone()[0] == 0:
        conn.executemany('INSERT INTO personal (nombre, cargo) VALUES (?, ?)', [("Juan Pérez", "Técnico Instalador"), ("Carlos Gómez", "Ingeniero de Proyectos")])

    conn.commit()
    conn.close()

# --- RUTAS PRINCIPALES ---
@app.route('/')
def index():
    conn = get_db_connection()
    search_query = request.args.get('q', '')
    categoria_filter = request.args.get('categoria', '')
    estado_filter = request.args.get('estado', '')

    query = 'SELECT * FROM equipos WHERE 1=1'
    params = []
    if search_query:
        query += ' AND (descripcion LIKE ? OR sku LIKE ?)'
        params.extend(['%'+search_query+'%', '%'+search_query+'%'])
    if categoria_filter:
        query += ' AND categoria = ?'
        params.append(categoria_filter)
    if estado_filter:
        query += ' AND estado = ?'
        params.append(estado_filter)

    query += ' ORDER BY id DESC'
    equipos = conn.execute(query, params).fetchall()

    total_stock = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Stock"').fetchone()[0] or 0
    en_revision = conn.execute('SELECT SUM(cantidad) FROM equipos WHERE estado = "En Revisión"').fetchone()[0] or 0
    critico = conn.execute('SELECT COUNT(*) FROM equipos WHERE cantidad <= 5 AND categoria = "Consumibles"').fetchone()[0] or 0

    categorias_db = conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()
    conn.close()
    return render_template('index.html', equipos=equipos, total_stock=total_stock, en_revision=en_revision, critico=critico, search_query=search_query, categoria_filter=categoria_filter, estado_filter=estado_filter, categorias_db=categorias_db)

@app.route('/ingresos', methods=['GET', 'POST'])
def ingresos():
    conn = get_db_connection()
    if request.method == 'POST':
        conn.execute('''
            INSERT INTO equipos (categoria, marca, descripcion, sku, mac, cantidad, estado, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (request.form['categoria'], request.form['marca'], request.form['descripcion'], request.form['sku'], request.form['mac'], int(request.form['cantidad']), request.form['estado'], request.form['observaciones']))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    categorias_db = conn.execute('SELECT nombre FROM categorias ORDER BY nombre').fetchall()
    marcas_db = conn.execute('SELECT nombre FROM marcas ORDER BY nombre').fetchall()
    modelos_db = conn.execute('SELECT nombre FROM modelos ORDER BY nombre').fetchall()
    conn.close()
    return render_template('ingresos.html', categorias_db=categorias_db, marcas_db=marcas_db, modelos_db=modelos_db)

# --- NUEVO MÓDULO: SALIDAS / DESPACHOS ---
@app.route('/salidas', methods=['GET', 'POST'])
def salidas():
    conn = get_db_connection()
    
    if request.method == 'POST':
        # Validamos que los campos existan antes de procesar
        equipo_id = request.form.get('equipo_id')
        personal = request.form.get('personal')
        destino = request.form.get('destino', '').strip()
        cantidad_str = request.form.get('cantidad', '0')
        observaciones = request.form.get('observaciones', '').strip()

        if equipo_id and cantidad_str.isdigit():
            cantidad_salida = int(cantidad_str)
            equipo = conn.execute('SELECT cantidad FROM equipos WHERE id = ?', (equipo_id,)).fetchone()
            
            if equipo and equipo['cantidad'] >= cantidad_salida:
                conn.execute('UPDATE equipos SET cantidad = cantidad - ? WHERE id = ?', (cantidad_salida, equipo_id))
                conn.execute('INSERT INTO salidas (equipo_id, personal, destino, cantidad, observaciones) VALUES (?, ?, ?, ?, ?)', 
                             (equipo_id, personal, destino, cantidad_salida, observaciones))
                conn.commit()
        
        conn.close()
        return redirect(url_for('salidas'))

    # --- LÓGICA DE FILTROS ---
    f_personal = request.args.get('f_personal', '')
    f_destino = request.args.get('f_destino', '')
    f_fecha = request.args.get('f_fecha', '')

    query = '''SELECT s.id, datetime(s.fecha, 'localtime') as fecha_local, s.personal, s.destino, s.cantidad, s.observaciones, e.marca, e.descripcion, e.sku 
               FROM salidas s JOIN equipos e ON s.equipo_id = e.id WHERE 1=1'''
    params = []

    if f_personal:
        query += ' AND s.personal = ?'
        params.append(f_personal)
    if f_destino:
        query += ' AND s.destino LIKE ?'
        params.append(f'%{f_destino}%')
    
# FILTRO DE FECHA CORREGIDO (Convirtiendo primero a localtime)
    if f_fecha:
        query += " AND strftime('%Y-%m-%d', datetime(s.fecha, 'localtime')) = ?"
        params.append(f_fecha)
        
    # DEBUG: Esto imprimirá en tu consola qué está buscando exactamente
    print(f"DEBUG: Ejecutando: {query} | Params: {params}")

    historial = conn.execute(query + ' ORDER BY s.id DESC', params).fetchall()

    equipos = conn.execute(
        'SELECT id, marca, descripcion, sku, cantidad '
        'FROM equipos '
        'WHERE cantidad > 0 AND estado = "En Stock"'
    ).fetchall()

    personal_db = conn.execute(
        'SELECT nombre FROM personal ORDER BY nombre'
    ).fetchall()

    edificios = conn.execute(
        'SELECT * FROM edificios ORDER BY nombre'
    ).fetchall()

    conn.close()

    return render_template(
        'salidas.html',
        equipos=equipos,
        personal=personal_db,
        edificios=edificios,   # <- ESTA LÍNEA FALTABA
        historial=historial,
        f_personal=f_personal,
        f_destino=f_destino,
        f_fecha=f_fecha
    )

@app.route('/pdf_guia/<int:id>')
def pdf_guia(id):

    conn = get_db_connection()

    guia = conn.execute(
        '''
        SELECT *
        FROM guias_salida
        WHERE id = ?
        ''',
        (id,)
    ).fetchone()

    detalle = conn.execute(
        '''
        SELECT
            gd.cantidad,
            e.marca,
            e.descripcion
        FROM guia_detalle gd
        INNER JOIN equipos e
            ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ''',
        (id,)
    ).fetchall()

    conn.close()

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer)

    styles = getSampleStyleSheet()

    elementos = []

    elementos.append(
        Paragraph(
            f"GUIA DE SALIDA N° {guia['id']}",
            styles['Title']
        )
    )

    elementos.append(Spacer(1, 12))

    elementos.append(
        Paragraph(
            f"<b>Solicitante:</b> {guia['personal']}",
            styles['Normal']
        )
    )

    elementos.append(
        Paragraph(
            f"<b>Destino:</b> {guia['destino']}",
            styles['Normal']
        )
    )

    elementos.append(
        Paragraph(
            f"<b>Fecha:</b> {guia['fecha']}",
            styles['Normal']
        )
    )

    elementos.append(Spacer(1, 15))

    data = [
        [
            "Cantidad",
            "Marca",
            "Descripción"
        ]
    ]

    for item in detalle:

        data.append([
            item["cantidad"],
            item["marca"],
            item["descripcion"]
        ])

    tabla = Table(data)

    tabla.setStyle(

        TableStyle([

            ('GRID', (0,0), (-1,-1), 1, colors.black),

            ('BACKGROUND',
             (0,0),
             (-1,0),
             colors.lightgrey),

            ('FONTNAME',
             (0,0),
             (-1,0),
             'Helvetica-Bold')

        ])

    )

    elementos.append(tabla)

    elementos.append(Spacer(1,20))

    elementos.append(

        Paragraph(

            f"<b>Observaciones:</b><br/>{guia['observaciones'] or ''}",

            styles['Normal']

        )

    )

    doc.build(elementos)

    buffer.seek(0)

    return send_file(

        buffer,

        as_attachment=True,

        download_name=f"Guia_{id}.pdf",

        mimetype='application/pdf'

    )

@app.route('/guias')
def guias():

    conn = get_db_connection()

    personal = conn.execute(
        'SELECT * FROM personal ORDER BY nombre'
    ).fetchall()

    edificios = conn.execute(
        'SELECT * FROM edificios ORDER BY nombre'
    ).fetchall()

    equipos = conn.execute(
        '''
        SELECT *
        FROM equipos
        WHERE cantidad > 0
        AND estado = "En Stock"
        ORDER BY descripcion
        '''
    ).fetchall()

    conn.close()

    return render_template(
        'guias.html',
        personal=personal,
        edificios=edificios,
        equipos=equipos
    )    

    conn.close()

@app.route('/guardar_guia', methods=['POST'])
def guardar_guia():
    conn = get_db_connection()

    try:
        personal = request.form.get('personal')
        destino = request.form.get('destino')
        cargo = request.form.get('cargo')
        proyecto = request.form.get('proyecto')
        entregado_por = request.form.get('entregado_por')
        recibido_por = request.form.get('recibido_por')
        aprobado_por = request.form.get('aprobado_por')
        observaciones = request.form.get('observaciones')

        productos = json.loads(request.form.get('productos'))

        cursor = conn.execute(
            '''
            INSERT INTO guias_salida (
                personal, destino, cargo, proyecto, 
                entregado_por, recibido_por, aprobado_por, observaciones
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                personal, destino, cargo, proyecto, 
                entregado_por, recibido_por, aprobado_por, observaciones
            )
        )

        guia_id = cursor.lastrowid

        for item in productos:
            equipo_id = int(item['id'])
            cantidad = int(item['cantidad'])

            # Guardar detalle
            conn.execute(
                '''
                INSERT INTO guia_detalle (guia_id, equipo_id, cantidad)
                VALUES (?, ?, ?)
                ''',
                (guia_id, equipo_id, cantidad)
            )

            # Descontar stock
            conn.execute(
                '''
                UPDATE equipos
                SET cantidad = cantidad - ?
                WHERE id = ?
                ''',
                (cantidad, equipo_id)
            )

        conn.commit()
        return redirect('/listar_guias')

    except Exception as e:
        conn.rollback()
        print("ERROR GUARDANDO GUIA:")
        print(e)
        return str(e)

    finally:
        conn.close()

@app.route('/actualizar_guia/<int:id>', methods=['POST'])
def actualizar_guia(id):

    conn = get_db_connection()

    try:

        productos = json.loads(
            request.form.get('productos')
        )

        # DEVOLVER STOCK ACTUAL

        detalle_actual = conn.execute(
            '''
            SELECT equipo_id, cantidad
            FROM guia_detalle
            WHERE guia_id = ?
            ''',
            (id,)
        ).fetchall()

        for item in detalle_actual:

            conn.execute(
                '''
                UPDATE equipos
                SET cantidad = cantidad + ?
                WHERE id = ?
                ''',
                (
                    item['cantidad'],
                    item['equipo_id']
                )
            )

        # ELIMINAR DETALLE ANTERIOR

        conn.execute(
            '''
            DELETE FROM guia_detalle
            WHERE guia_id = ?
            ''',
            (id,)
        )

        # ACTUALIZAR CABECERA

        conn.execute(
            '''
            UPDATE guias_salida
            SET personal = ?,
                destino = ?,
                observaciones = ?
            WHERE id = ?
            ''',
            (
                request.form.get('personal'),
                request.form.get('destino'),
                request.form.get('observaciones'),
                id
            )
        )

        # NUEVO DETALLE

        for item in productos:

            conn.execute(
                '''
                INSERT INTO guia_detalle
                (
                    guia_id,
                    equipo_id,
                    cantidad
                )
                VALUES
                (?, ?, ?)
                ''',
                (
                    id,
                    item['id'],
                    item['cantidad']
                )
            )

            conn.execute(
                '''
                UPDATE equipos
                SET cantidad = cantidad - ?
                WHERE id = ?
                ''',
                (
                    item['cantidad'],
                    item['id']
                )
            )

        conn.commit()

    except Exception as e:

        print(e)

    finally:

        conn.close()

    return redirect(
        f'/guia/{id}'
    )

    
@app.route('/guia/<int:id>')
def ver_guia(id):

    conn = get_db_connection()

    guia = conn.execute(
        '''
        SELECT *
        FROM guias_salida
        WHERE id = ?
        ''',
        (id,)
    ).fetchone()

    detalle = conn.execute(
        '''
        SELECT
            gd.cantidad,
            e.marca,
            e.descripcion
        FROM guia_detalle gd
        INNER JOIN equipos e
            ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ''',
        (id,)
    ).fetchall()

    conn.close()

    return render_template(
        'ver_guia.html',
        guia=guia,
        detalle=detalle
    )

@app.route('/eliminar_guia/<int:id>')
def eliminar_guia(id):

    conn = get_db_connection()

    try:

        # Obtener productos de la guía
        detalle = conn.execute(
            '''
            SELECT
                equipo_id,
                cantidad
            FROM guia_detalle
            WHERE guia_id = ?
            ''',
            (id,)
        ).fetchall()

        # Devolver stock
        for item in detalle:

            conn.execute(
                '''
                UPDATE equipos
                SET cantidad = cantidad + ?
                WHERE id = ?
                ''',
                (
                    item['cantidad'],
                    item['equipo_id']
                )
            )

        # Eliminar detalle
        conn.execute(
            '''
            DELETE FROM guia_detalle
            WHERE guia_id = ?
            ''',
            (id,)
        )

        # Eliminar cabecera
        conn.execute(
            '''
            DELETE FROM guias_salida
            WHERE id = ?
            ''',
            (id,)
        )

        conn.commit()

    except Exception as e:

        print("Error eliminando guía:", e)

    finally:

        conn.close()

    return redirect('/listar_guias')    

@app.route('/listar_guias')
def listar_guias():

    conn = get_db_connection()

    guias = conn.execute(
        '''
        SELECT *
        FROM guias_salida
        ORDER BY id DESC
        '''
    ).fetchall()

    conn.close()

    return render_template(
        'listar_guias.html',
        guias=guias
    )

@app.route('/agregar_categoria', methods=['POST'])
def agregar_categoria():

    conn = get_db_connection()

    try:
        conn.execute(
            'INSERT INTO categorias (nombre) VALUES (?)',
            (request.form.get('nombre').strip(),)
        )
        conn.commit()

    except:
        pass

    conn.close()

    return redirect(url_for('ingresos'))


@app.route('/agregar_marca', methods=['POST'])
def agregar_marca():

    conn = get_db_connection()

    try:
        conn.execute(
            'INSERT INTO marcas (nombre) VALUES (?)',
            (request.form.get('nombre').strip(),)
        )
        conn.commit()

    except:
        pass

    conn.close()

    return redirect(url_for('ingresos'))


@app.route('/agregar_modelo', methods=['POST'])
def agregar_modelo():

    conn = get_db_connection()

    try:
        conn.execute(
            'INSERT INTO modelos (nombre) VALUES (?)',
            (request.form.get('nombre').strip(),)
        )
        conn.commit()

    except:
        pass

    conn.close()

    return redirect(url_for('ingresos'))


# --- MÓDULO CONFIGURACIÓN ---
@app.route('/configuracion', methods=['GET', 'POST'])
def configuracion():
    conn = get_db_connection()
    if request.method == 'POST':
        tipo = request.form.get('tipo')
        nombre = request.form.get('nombre').strip()
        if nombre:
            try:
                if tipo == 'categoria': conn.execute('INSERT INTO categorias (nombre) VALUES (?)', (nombre,))
                elif tipo == 'marca': conn.execute('INSERT INTO marcas (nombre) VALUES (?)', (nombre,))
                elif tipo == 'modelo': conn.execute('INSERT INTO modelos (nombre) VALUES (?)', (nombre,))
                elif tipo == 'cargo': conn.execute('INSERT INTO cargos (nombre) VALUES (?)', (nombre,))
                elif tipo == 'edificio': conn.execute('INSERT INTO edificios (nombre) VALUES (?)', (nombre,)) 
                conn.commit()
            except sqlite3.IntegrityError: pass
        return redirect(url_for('configuracion'))

    categorias = conn.execute('SELECT * FROM categorias ORDER BY nombre').fetchall()
    marcas = conn.execute('SELECT * FROM marcas ORDER BY nombre').fetchall()
    modelos = conn.execute('SELECT * FROM modelos ORDER BY nombre').fetchall()
    cargos = conn.execute('SELECT * FROM cargos ORDER BY nombre').fetchall()
    edificios = conn.execute('SELECT * FROM edificios ORDER BY nombre').fetchall()
    conn.close()
    
    

    return render_template('configuracion.html', categorias=categorias, marcas=marcas, modelos=modelos, cargos=cargos, edificios=edificios)

@app.route('/editar_guia/<int:id>')
def editar_guia(id):

    conn = get_db_connection()

    guia = conn.execute(
        '''
        SELECT *
        FROM guias_salida
        WHERE id = ?
        ''',
        (id,)
    ).fetchone()

    detalle = conn.execute(
        '''
        SELECT
            gd.equipo_id,
            gd.cantidad,
            e.descripcion,
            e.marca
        FROM guia_detalle gd
        INNER JOIN equipos e
            ON gd.equipo_id = e.id
        WHERE gd.guia_id = ?
        ''',
        (id,)
    ).fetchall()

    print("GUIA:", dict(guia) if guia else None)
    print("DETALLE:", [dict(x) for x in detalle])

    personal = conn.execute(
        'SELECT * FROM personal ORDER BY nombre'
    ).fetchall()

    edificios = conn.execute(
        'SELECT * FROM edificios ORDER BY nombre'
    ).fetchall()

    equipos = conn.execute(
        '''
        SELECT *
        FROM equipos
        ORDER BY descripcion
        '''
    ).fetchall()

    conn.close()

    return render_template(
        'editar_guia.html',
        guia=guia,
        detalle=detalle,
        personal=personal,
        edificios=edificios,
        equipos=equipos
    )

@app.route('/editar_catalogo/<tipo>/<int:id>', methods=['POST'])
def editar_catalogo(tipo, id):
    nuevo_nombre = request.form.get('nuevo_nombre').strip()
    if nuevo_nombre:
        conn = get_db_connection()
        tabla = 'categorias' if tipo == 'categoria' else 'marcas' if tipo == 'marca' else 'modelos' if tipo == 'modelo' else 'cargos' if tipo == 'cargo' else 'edificios' if tipo == 'edificio' else None 
        if tabla:
            try: conn.execute(f'UPDATE {tabla} SET nombre = ? WHERE id = ?', (nuevo_nombre, id)); conn.commit()
            except sqlite3.IntegrityError: pass
        conn.close()
    return redirect(url_for('configuracion'))

@app.route('/eliminar_catalogo/<tipo>/<int:id>', methods=['POST'])
def eliminar_catalogo(tipo, id):
    conn = get_db_connection()
    tabla = 'categorias' if tipo == 'categoria' else 'marcas' if tipo == 'marca' else 'modelos' if tipo == 'modelo' else 'cargos' if tipo == 'cargo' else 'edificios' if tipo == 'edificio' else None 
    if tabla: conn.execute(f'DELETE FROM {tabla} WHERE id = ?', (id,)); conn.commit()
    conn.close()
    return redirect(url_for('configuracion'))

# --- MÓDULO DE PERSONAL ---
@app.route('/personal', methods=['GET', 'POST'])
def personal():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = request.form.get('nombre').strip()
        cargo = request.form.get('cargo').strip()
        if nombre:
            try: conn.execute('INSERT INTO personal (nombre, cargo) VALUES (?, ?)', (nombre, cargo)); conn.commit()
            except sqlite3.IntegrityError: pass 
        return redirect(url_for('personal'))
    
    lista_personal = conn.execute('SELECT * FROM personal ORDER BY nombre').fetchall()
    cargos_db = conn.execute('SELECT * FROM cargos ORDER BY nombre').fetchall()
    conn.close()
    return render_template('personal.html', personal=lista_personal, cargos_db=cargos_db)

@app.route('/editar_personal/<int:id>', methods=['POST'])
def editar_personal(id):
    nuevo_nombre = request.form.get('nombre').strip()
    nuevo_cargo = request.form.get('cargo').strip()
    if nuevo_nombre and nuevo_cargo:
        conn = get_db_connection()
        try: conn.execute('UPDATE personal SET nombre = ?, cargo = ? WHERE id = ?', (nuevo_nombre, nuevo_cargo, id)); conn.commit()
        except sqlite3.IntegrityError: pass
        conn.close()
    return redirect(url_for('personal'))

@app.route('/eliminar_personal/<int:id>', methods=['POST'])
def eliminar_personal(id):
    conn = get_db_connection(); conn.execute('DELETE FROM personal WHERE id = ?', (id,)); conn.commit(); conn.close()
    return redirect(url_for('personal'))

@app.route('/agregar_cargo', methods=['POST'])
def agregar_cargo():
    nombre = request.form.get('nombre').strip()
    if nombre:
        conn = get_db_connection()
        try: conn.execute('INSERT INTO cargos (nombre) VALUES (?)', (nombre,)); conn.commit()
        except sqlite3.IntegrityError: pass
        conn.close()
    return redirect(url_for('personal'))

# --- MÓDULO EDIFICIOS ---
@app.route('/edificios', methods=['GET', 'POST'])
def edificios():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = request.form.get('nombre').strip()
        if nombre:
            try: conn.execute('INSERT INTO edificios (nombre) VALUES (?)', (nombre,)); conn.commit()
            except sqlite3.IntegrityError: pass
        return redirect(url_for('edificios'))
    lista = conn.execute('SELECT * FROM edificios ORDER BY nombre ASC').fetchall()
    conn.close()
    return render_template('edificios.html', edificios=lista)

@app.route('/edificios/eliminar/<int:id>')
def eliminar_edificio(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM edificios WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('edificios'))

# --- SIEMPRE AL FINAL ---
if __name__ == '__main__':
    init_db()
    app.run(debug=True)

    
