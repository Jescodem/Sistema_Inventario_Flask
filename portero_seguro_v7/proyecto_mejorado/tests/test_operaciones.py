"""
Tests de operaciones de Portero Seguro.

Complementan a tests/test_flujos.py cubriendo los flujos de negocio de punta
a punta a traves del cliente HTTP de Flask:

- Guias por cantidad y serializadas (creacion, descuento de stock, kardex).
- Anulacion de guia y devolucion parcial de series.
- Permisos por rol (operador vs lectura vs admin).
- Dar de baja (normal y bloqueada por guia activa).
- Ingresos: unificacion de producto y validacion SKU/MAC.
- Funciones nuevas: exportacion a Excel, alertas de stock minimo y
  expiracion de sesion.

Ejecutar con:  python -m unittest tests.test_operaciones -v
Usa una base temporal (PORTERO_DB): nunca toca inventario.db.
"""
import itertools
import json
import os
import re
import tempfile
import unittest
from datetime import timedelta

# ── Entorno ANTES de importar la app ─────────────────────────────────────
_TMP = tempfile.mkdtemp(prefix='portero_test_op_')
os.environ.setdefault('PORTERO_DB', os.path.join(_TMP, 'test_op.db'))
os.environ.setdefault('ADMIN_USERNAME', 'admin')
os.environ.setdefault('ADMIN_PASSWORD', 'TestAdmin123!')

import app as app_module            # noqa: E402
from db import get_db_connection    # noqa: E402
from auth import hash_password      # noqa: E402

PWD = 'Test123!'
_serial_seq = itertools.count(1)


def _serial_unico():
    return f'SN-TEST-{next(_serial_seq):06d}'


class OpsBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app_module.app.testing = True
        conn = get_db_connection()
        # Usuarios propios (no dependemos del admin autogenerado).
        for usuario, rol in [('adm_test', 'admin'),
                             ('op_test', 'operador'),
                             ('lec_test', 'lectura')]:
            conn.execute("""
                INSERT OR IGNORE INTO usuarios
                    (username, password_hash, nombre_completo, rol, activo, debe_cambiar_password)
                VALUES (?, ?, ?, ?, 1, 0)
            """, (usuario, hash_password(PWD), usuario, rol))
        # Maestros para guias.
        conn.execute("INSERT OR IGNORE INTO personal (nombre, cargo) VALUES ('PERS_TEST', 'Tecnico Instalador')")
        conn.execute("INSERT OR IGNORE INTO edificios (nombre) VALUES ('OBRA_TEST')")
        conn.commit()
        conn.close()

    def setUp(self):
        self.client = app_module.app.test_client()
        app_module._login_attempts.clear()

    # ── Sesion ───────────────────────────────────────────────────────────
    def login(self, username, password=PWD):
        # Cliente nuevo en cada login: evita arrastrar la sesion anterior
        # (login() redirige a index si ya hay sesion y no habria token CSRF).
        self.client = app_module.app.test_client()
        r = self.client.get('/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
        return self.client.post('/login', data={
            'username': username, 'password': password, 'csrf_token': token,
        }, follow_redirects=False)

    def csrf(self):
        with self.client.session_transaction() as sess:
            return sess.get('csrf_token', '')

    # ── Fabricas de datos ────────────────────────────────────────────────
    def crear_producto_cantidad(self, cantidad=10, stock_minimo=0, desc='Prod Cant'):
        conn = get_db_connection()
        cur = conn.execute("""
            INSERT INTO equipos (categoria, marca, descripcion, cantidad, stock_minimo, estado, control_stock)
            VALUES ('CCTV', 'MarcaT', ?, ?, ?, 'En Stock', 'CANTIDAD')
        """, (desc, cantidad, stock_minimo))
        eid = cur.lastrowid
        conn.commit()
        conn.close()
        return eid

    def crear_producto_serial(self, n_series=3, desc='Prod Serial'):
        conn = get_db_connection()
        cur = conn.execute("""
            INSERT INTO equipos (categoria, marca, descripcion, cantidad, estado, control_stock)
            VALUES ('CCTV', 'MarcaT', ?, ?, 'En Stock', 'SERIAL')
        """, (desc, n_series))
        eid = cur.lastrowid
        series_ids = []
        for _ in range(n_series):
            c = conn.execute("""
                INSERT INTO equipo_series (equipo_id, serial, estado, ubicacion_actual)
                VALUES (?, ?, 'EN_STOCK', 'Almacen')
            """, (eid, _serial_unico()))
            series_ids.append(c.lastrowid)
        conn.commit()
        conn.close()
        return eid, series_ids

    # ── Consultas de apoyo ───────────────────────────────────────────────
    def _scalar(self, sql, params=()):
        conn = get_db_connection()
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row[0] if row else None

    def stock(self, equipo_id):
        return self._scalar('SELECT cantidad FROM equipos WHERE id = ?', (equipo_id,))

    def estado_equipo(self, equipo_id):
        return self._scalar('SELECT estado FROM equipos WHERE id = ?', (equipo_id,))

    def estado_serie(self, serie_id):
        return self._scalar('SELECT estado FROM equipo_series WHERE id = ?', (serie_id,))

    def guia_de(self, equipo_id):
        return self._scalar(
            'SELECT guia_id FROM guia_detalle WHERE equipo_id = ? ORDER BY guia_id DESC LIMIT 1',
            (equipo_id,))

    def estado_guia(self, guia_id):
        return self._scalar('SELECT estado FROM guias_salida WHERE id = ?', (guia_id,))

    def movimientos_de(self, equipo_id, tipo=None):
        conn = get_db_connection()
        if tipo:
            n = conn.execute('SELECT COUNT(*) FROM movimientos WHERE equipo_id = ? AND tipo = ?',
                             (equipo_id, tipo)).fetchone()[0]
        else:
            n = conn.execute('SELECT COUNT(*) FROM movimientos WHERE equipo_id = ?',
                             (equipo_id,)).fetchone()[0]
        conn.close()
        return n

    # ── Accion: crear guia ───────────────────────────────────────────────
    def crear_guia(self, productos):
        return self.client.post('/guardar_guia', data={
            'personal': 'PERS_TEST', 'destino': 'OBRA_TEST',
            'productos': json.dumps(productos), 'csrf_token': self.csrf(),
        }, follow_redirects=False)


class TestGuiaPorCantidad(OpsBase):

    def test_crear_guia_descuenta_stock_y_registra_kardex(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=10)
        r = self.crear_guia([{'id': eid, 'cantidad': 3, 'control_stock': 'CANTIDAD'}])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.stock(eid), 7, 'El stock debe bajar de 10 a 7')
        guia_id = self.guia_de(eid)
        self.assertIsNotNone(guia_id)
        self.assertEqual(self.estado_guia(guia_id), 'ACTIVA')
        self.assertEqual(self.movimientos_de(eid, 'SALIDA_GUIA'), 1)

    def test_guia_por_encima_del_stock_no_descuenta(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=2)
        self.crear_guia([{'id': eid, 'cantidad': 5, 'control_stock': 'CANTIDAD'}])
        self.assertEqual(self.stock(eid), 2, 'Sin stock suficiente, no debe descontar')


class TestGuiaSerializada(OpsBase):

    def test_flujo_completo_crear_y_anular(self):
        self.login('op_test')
        eid, sids = self.crear_producto_serial(n_series=3)

        # Crear guia con 2 de las 3 series
        r = self.crear_guia([{'id': eid, 'series_ids': sids[:2], 'control_stock': 'SERIAL'}])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.stock(eid), 1, 'Quedan 1 de 3')
        self.assertEqual(self.estado_serie(sids[0]), 'ENTREGADO')
        self.assertEqual(self.estado_serie(sids[1]), 'ENTREGADO')
        self.assertEqual(self.estado_serie(sids[2]), 'EN_STOCK', 'La no seleccionada sigue en stock')

        guia_id = self.guia_de(eid)
        # Las series entregadas quedan enlazadas en guia_detalle_series
        n_enlazadas = self._scalar("""
            SELECT COUNT(*) FROM guia_detalle_series gds
            JOIN guia_detalle gd ON gd.id = gds.guia_detalle_id
            WHERE gd.guia_id = ?
        """, (guia_id,))
        self.assertEqual(n_enlazadas, 2)

        # Anular: revierte todo
        r2 = self.client.post(f'/eliminar_guia/{guia_id}',
                              data={'csrf_token': self.csrf()}, follow_redirects=False)
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(self.estado_guia(guia_id), 'ANULADA')
        self.assertEqual(self.stock(eid), 3, 'El stock vuelve a 3')
        self.assertEqual(self.estado_serie(sids[0]), 'EN_STOCK')
        self.assertEqual(self.estado_serie(sids[1]), 'EN_STOCK')

    def test_devolucion_parcial_de_una_serie(self):
        self.login('op_test')
        eid, sids = self.crear_producto_serial(n_series=3)
        self.crear_guia([{'id': eid, 'series_ids': sids[:2], 'control_stock': 'SERIAL'}])
        guia_id = self.guia_de(eid)
        self.assertEqual(self.stock(eid), 1)

        # Quitar solo una serie
        r = self.client.post(f'/guia/{guia_id}/quitar_serie/{sids[0]}',
                             data={'csrf_token': self.csrf()}, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estado_serie(sids[0]), 'EN_STOCK', 'La devuelta vuelve a stock')
        self.assertEqual(self.estado_serie(sids[1]), 'ENTREGADO', 'La otra sigue entregada')
        self.assertEqual(self.stock(eid), 2, 'El stock sube en 1')
        self.assertGreaterEqual(self.movimientos_de(eid, 'DEVOLUCION_GUIA'), 1)


class TestPermisos(OpsBase):

    def test_operador_puede_crear_guia_pero_no_administrar(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=5)
        r = self.crear_guia([{'id': eid, 'cantidad': 1, 'control_stock': 'CANTIDAD'}])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.stock(eid), 4, 'El operador sí puede despachar')
        # Pero no accede a Configuracion (admin)
        r2 = self.client.get('/configuracion', follow_redirects=False)
        self.assertEqual(r2.status_code, 302)

    def test_lectura_no_puede_crear_guia(self):
        self.login('lec_test')
        eid = self.crear_producto_cantidad(cantidad=5)
        r = self.crear_guia([{'id': eid, 'cantidad': 2, 'control_stock': 'CANTIDAD'}])
        self.assertEqual(r.status_code, 302, 'Rechazado por permiso insuficiente')
        self.assertEqual(self.stock(eid), 5, 'La guia NO debe haberse creado')

    def test_admin_accede_a_configuracion(self):
        self.login('adm_test')
        r = self.client.get('/configuracion')
        self.assertEqual(r.status_code, 200)


class TestDarDeBaja(OpsBase):

    def test_baja_normal(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=4)
        r = self.client.post(f'/dar_baja_equipo/{eid}',
                             data={'motivo': 'Prueba de baja', 'csrf_token': self.csrf()},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.estado_equipo(eid), 'Baja')
        self.assertEqual(self.stock(eid), 0)
        self.assertEqual(self.movimientos_de(eid, 'BAJA'), 1)

    def test_baja_bloqueada_por_guia_activa(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=5)
        self.crear_guia([{'id': eid, 'cantidad': 1, 'control_stock': 'CANTIDAD'}])
        self.client.post(f'/dar_baja_equipo/{eid}',
                        data={'motivo': 'x', 'csrf_token': self.csrf()},
                        follow_redirects=False)
        self.assertNotEqual(self.estado_equipo(eid), 'Baja',
                            'No debe darse de baja con una guia activa')


class TestIngresos(OpsBase):

    def test_unificacion_suma_stock(self):
        self.login('op_test')
        base = {'categoria': 'CCTV', 'marca': 'Hikvision',
                'descripcion': 'Camara Domo IP 4MP', 'cantidad': '5',
                'stock_minimo': '0', 'estado': 'En Stock'}
        base['csrf_token'] = self.csrf()
        self.client.post('/ingresos', data=base, follow_redirects=False)
        base2 = dict(base, cantidad='3', csrf_token=self.csrf())
        self.client.post('/ingresos', data=base2, follow_redirects=False)
        total = self._scalar("""
            SELECT SUM(cantidad) FROM equipos
            WHERE categoria='CCTV' AND marca='Hikvision'
              AND descripcion='Camara Domo IP 4MP' AND control_stock='CANTIDAD'
        """)
        n_filas = self._scalar("""
            SELECT COUNT(*) FROM equipos
            WHERE categoria='CCTV' AND marca='Hikvision'
              AND descripcion='Camara Domo IP 4MP' AND control_stock='CANTIDAD'
        """)
        self.assertEqual(total, 8, 'Debe sumar 5 + 3 = 8')
        self.assertEqual(n_filas, 1, 'No debe crear un producto duplicado')

    def test_sku_con_cantidad_mayor_a_uno_es_rechazado(self):
        self.login('op_test')
        data = {'categoria': 'CCTV', 'marca': 'Hikvision',
                'descripcion': 'NVR 16 Canales', 'cantidad': '3',
                'stock_minimo': '0', 'estado': 'En Stock',
                'sku': 'SKU-XYZ-1', 'csrf_token': self.csrf()}
        self.client.post('/ingresos', data=data, follow_redirects=False)
        existe = self._scalar("SELECT COUNT(*) FROM equipo_series WHERE serial='SKU-XYZ-1'")
        self.assertEqual(existe, 0, 'Con SKU la cantidad debe ser 1; no debe registrar')


class TestExportarExcel(OpsBase):

    def test_exportaciones_devuelven_xlsx(self):
        self.login('op_test')
        for tipo in ('inventario', 'movimientos', 'guias', 'series'):
            r = self.client.get(f'/exportar/{tipo}')
            self.assertEqual(r.status_code, 200, f'{tipo} debe responder 200')
            self.assertIn('spreadsheetml', r.headers.get('Content-Type', ''),
                          f'{tipo} debe ser un .xlsx')
            self.assertEqual(r.data[:2], b'PK', f'{tipo}: firma de archivo Office invalida')

    def test_tipo_desconocido_es_404(self):
        self.login('op_test')
        r = self.client.get('/exportar/inexistente')
        self.assertEqual(r.status_code, 404)

    def test_exportar_sin_sesion_redirige_a_login(self):
        r = self.client.get('/exportar/inventario', follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers['Location'])


class TestAlertasStock(OpsBase):

    def test_dashboard_muestra_alerta_bajo_minimo(self):
        self.login('op_test')
        # Producto con stock (2) por debajo del minimo (5)
        self.crear_producto_cantidad(cantidad=2, stock_minimo=5,
                                     desc='Producto Bajo Minimo XYZ')
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('Reposición pendiente', html)
        self.assertIn('Producto Bajo Minimo XYZ', html)

    def test_producto_con_stock_suficiente_no_alerta_falsos(self):
        self.login('op_test')
        eid = self.crear_producto_cantidad(cantidad=50, stock_minimo=5,
                                           desc='Producto Bien Surtido QQQ')
        html = self.client.get('/').get_data(as_text=True)
        # No debe listar este producto como reposicion pendiente
        bloque = html.split('Reposición pendiente')
        if len(bloque) > 1:
            self.assertNotIn('Producto Bien Surtido QQQ', bloque[1][:2000])


class TestConfiguracionSesion(unittest.TestCase):

    def test_timeout_de_sesion_configurado(self):
        self.assertEqual(app_module.app.config['PERMANENT_SESSION_LIFETIME'],
                         timedelta(minutes=30))

    def test_cookies_endurecidas(self):
        self.assertTrue(app_module.app.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(app_module.app.config['SESSION_COOKIE_SAMESITE'], 'Lax')


class TestGestionUsuarios(OpsBase):

    def _crear_usuario(self, username, rol='operador', password=None):
        self.login('adm_test')
        data = {'username': username, 'nombre_completo': f'Nombre {username}',
                'rol': rol, 'csrf_token': self.csrf()}
        if password is not None:
            data['password'] = password
        return self.client.post('/usuarios/crear', data=data, follow_redirects=False)

    def test_crear_con_password_fijada_permite_entrar(self):
        self._crear_usuario('u_fijo', password='ClaveFija123')
        u = self._scalar("SELECT debe_cambiar_password FROM usuarios WHERE username='u_fijo'")
        self.assertEqual(u, 0, 'Con password fijada no debe forzar cambio')
        # El usuario nuevo puede iniciar sesion con esa contrasena
        r = self.login('u_fijo', 'ClaveFija123')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('/login', r.headers['Location'], 'Debe entrar, no rebotar al login')

    def test_crear_sin_password_genera_temporal(self):
        self._crear_usuario('u_temp')
        u = self._scalar("SELECT debe_cambiar_password FROM usuarios WHERE username='u_temp'")
        self.assertEqual(u, 1, 'Sin password debe generar temporal y forzar cambio')

    def test_password_corta_es_rechazada_al_crear(self):
        self._crear_usuario('u_corto', password='123')
        existe = self._scalar("SELECT COUNT(*) FROM usuarios WHERE username='u_corto'")
        self.assertEqual(existe, 0, 'Contrasena < 8 no debe crear el usuario')

    def test_admin_actualiza_password_desde_edicion(self):
        self._crear_usuario('u_edit', password='Inicial123')
        uid = self._scalar("SELECT id FROM usuarios WHERE username='u_edit'")
        self.login('adm_test')
        self.client.post(f'/usuarios/{uid}/editar', data={
            'nombre_completo': 'Nombre u_edit', 'rol': 'operador', 'activo': 'on',
            'password_nueva': 'Cambiada456', 'csrf_token': self.csrf(),
        }, follow_redirects=False)
        # La nueva contrasena debe funcionar y la vieja no
        h = self._scalar("SELECT password_hash FROM usuarios WHERE id=?", (uid,))
        from auth import check_password
        self.assertTrue(check_password(h, 'Cambiada456'))
        self.assertFalse(check_password(h, 'Inicial123'))

    def test_no_admin_puede_cambiar_su_propia_password(self):
        # Un operador con sesion accede a /mi_cuenta y cambia su clave
        self._crear_usuario('u_self', rol='operador', password='Inicial123')
        self.login('u_self', 'Inicial123')
        r = self.client.get('/mi_cuenta')
        self.assertEqual(r.status_code, 200, 'Un operador SÍ debe poder abrir Mi cuenta')
        self.client.post('/mi_cuenta', data={
            'password_actual': 'Inicial123', 'password_nueva': 'NuevaProp789',
            'password_confirmacion': 'NuevaProp789', 'csrf_token': self.csrf(),
        }, follow_redirects=False)
        uid = self._scalar("SELECT id FROM usuarios WHERE username='u_self'")
        from auth import check_password
        h = self._scalar("SELECT password_hash FROM usuarios WHERE id=?", (uid,))
        self.assertTrue(check_password(h, 'NuevaProp789'), 'El operador debe poder cambiar su clave')

    def test_usuario_con_password_temporal_va_a_mi_cuenta(self):
        self._crear_usuario('u_forzado')  # sin password -> debe_cambiar=1
        # Fijamos una clave conocida directamente para probar el redirect del login
        conn = get_db_connection()
        from auth import hash_password
        conn.execute("UPDATE usuarios SET password_hash=? WHERE username='u_forzado'",
                     (hash_password('Temp12345'),))
        conn.commit(); conn.close()
        r = self.login('u_forzado', 'Temp12345')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/mi_cuenta', r.headers['Location'],
                      'Con contrasena temporal debe ir a Mi cuenta, no a /usuarios')


if __name__ == '__main__':
    unittest.main(verbosity=2)
