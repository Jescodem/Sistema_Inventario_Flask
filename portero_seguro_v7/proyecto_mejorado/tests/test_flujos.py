"""
Tests de integración de Portero Seguro.

Ejecutar con:  python -m unittest tests.test_flujos -v

Usa una base de datos temporal (via PORTERO_DB) para no tocar inventario.db.
Cubre: autenticación, CSRF, rate limiting, control de roles y el descuento
atómico de stock (fix del race condition).
"""
import os
import re
import shutil
import sqlite3
import tempfile
import unittest

# ── Configurar entorno ANTES de importar la app ──────────────────────────
_TMP = tempfile.mkdtemp(prefix='portero_test_')
os.environ['PORTERO_DB'] = os.path.join(_TMP, 'test.db')
os.environ['ADMIN_USERNAME'] = 'admin'
os.environ['ADMIN_PASSWORD'] = 'TestAdmin123!'

import app as app_module            # noqa: E402  (import tardío intencional)
from db import get_db_connection    # noqa: E402


def extraer_csrf(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else None


class BaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.testing = True

    def setUp(self):
        self.client = app_module.app.test_client()
        app_module._login_attempts.clear()

    def login(self, username='admin', password='TestAdmin123!'):
        r = self.client.get('/login')
        token = extraer_csrf(r.get_data(as_text=True))
        return self.client.post('/login', data={
            'username': username,
            'password': password,
            'csrf_token': token,
        }, follow_redirects=False)


class TestAutenticacion(BaseTestCase):

    def test_rutas_protegidas_redirigen_a_login(self):
        for ruta in ['/', '/series', '/listar_guias', '/movimientos', '/usuarios']:
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 302, f'{ruta} debería redirigir')
            self.assertIn('/login', r.headers['Location'])

    def test_login_correcto_da_acceso(self):
        r = self.login()
        self.assertEqual(r.status_code, 302)
        r2 = self.client.get('/')
        self.assertEqual(r2.status_code, 200)
        self.assertIn('Inventario', r2.get_data(as_text=True))

    def test_login_incorrecto_es_rechazado(self):
        r = self.login(password='clave-incorrecta')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers['Location'])
        # Sigue sin acceso
        r2 = self.client.get('/')
        self.assertEqual(r2.status_code, 302)

    def test_post_sin_csrf_es_rechazado(self):
        self.login()
        r = self.client.post('/eliminar_guia/999', data={'x': '1'},
                             follow_redirects=False)
        # Debe redirigir (rechazado por CSRF) sin ejecutar la acción
        self.assertEqual(r.status_code, 302)

    def test_rate_limiting_bloquea_tras_5_fallos(self):
        for _ in range(5):
            self.login(password='mala')
        # El 6to intento, incluso con la clave CORRECTA, debe estar bloqueado
        r = self.login(password='TestAdmin123!')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers['Location'])
        r2 = self.client.get('/')
        self.assertEqual(r2.status_code, 302, 'No debería tener sesión')


class TestRoles(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Crear un usuario de rol lectura directamente en la BD
        from auth import hash_password
        conn = get_db_connection()
        conn.execute("""
            INSERT OR IGNORE INTO usuarios
                (username, password_hash, nombre_completo, rol, activo, debe_cambiar_password)
            VALUES ('lector', ?, 'Usuario Lectura', 'lectura', 1, 0)
        """, (hash_password('Lectura123!'),))
        conn.commit()
        conn.close()

    def test_lectura_puede_ver_pero_no_modificar(self):
        self.login('lector', 'Lectura123!')
        # Puede ver el dashboard
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        # No puede acceder a admin
        r2 = self.client.get('/usuarios', follow_redirects=False)
        self.assertEqual(r2.status_code, 302)


class TestStockAtomico(unittest.TestCase):
    """Verifica el fix del race condition en descuento de stock."""

    def setUp(self):
        self.conn = get_db_connection()
        cur = self.conn.execute("""
            INSERT INTO equipos (categoria, marca, descripcion, cantidad, estado, control_stock)
            VALUES ('CCTV', 'TestBrand', 'Equipo de prueba atomico', 5, 'En Stock', 'CANTIDAD')
        """)
        self.equipo_id = cur.lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.execute('DELETE FROM equipos WHERE id = ?', (self.equipo_id,))
        self.conn.commit()
        self.conn.close()

    def test_descuento_normal_funciona(self):
        exito, nuevo = app_module.descontar_stock_atomico(self.conn, self.equipo_id, 3)
        self.assertTrue(exito)
        self.assertEqual(nuevo, 2)

    def test_descuento_mayor_al_stock_falla_sin_modificar(self):
        exito, nuevo = app_module.descontar_stock_atomico(self.conn, self.equipo_id, 10)
        self.assertFalse(exito)
        row = self.conn.execute('SELECT cantidad FROM equipos WHERE id = ?',
                                (self.equipo_id,)).fetchone()
        self.assertEqual(row['cantidad'], 5, 'El stock no debe haberse tocado')

    def test_descuento_exacto_deja_cero_y_actualiza_estado(self):
        exito, nuevo = app_module.descontar_stock_atomico(self.conn, self.equipo_id, 5)
        self.assertTrue(exito)
        self.assertEqual(nuevo, 0)
        row = self.conn.execute('SELECT estado FROM equipos WHERE id = ?',
                                (self.equipo_id,)).fetchone()
        self.assertEqual(row['estado'], 'Sin Stock')

    def test_dos_descuentos_consecutivos_no_generan_negativo(self):
        """Simula el escenario de concurrencia: dos despachos del mismo stock."""
        exito1, _ = app_module.descontar_stock_atomico(self.conn, self.equipo_id, 4)
        exito2, _ = app_module.descontar_stock_atomico(self.conn, self.equipo_id, 4)
        self.assertTrue(exito1)
        self.assertFalse(exito2, 'El segundo descuento debe fallar (solo queda 1)')
        row = self.conn.execute('SELECT cantidad FROM equipos WHERE id = ?',
                                (self.equipo_id,)).fetchone()
        self.assertGreaterEqual(row['cantidad'], 0, 'Nunca debe quedar negativo')


class TestTagsAcceso(BaseTestCase):
    """Módulo de tags/tarjetas de acceso: alta, importación Excel y dedupe."""

    def setUp(self):
        super().setUp()
        conn = get_db_connection()
        conn.execute('DELETE FROM tags_acceso')
        conn.commit()
        conn.close()

    def _post(self, ruta, data, **kwargs):
        r = self.client.get('/tags')
        token = extraer_csrf(r.get_data(as_text=True))
        data = dict(data, csrf_token=token)
        return self.client.post(ruta, data=data, follow_redirects=True, **kwargs)

    def _excel_en_memoria(self, filas, encabezados=None):
        """Construye un .xlsx en memoria imitando el archivo real de campo."""
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['', '', '', ''])                       # filas basura arriba
        ws.append(['', 'EDIFICIO', 'DEPARTAMENTO', 'RESIDENTE',
                   'CÓDIGO', 'FECHA DE CREACIÓN', 'TIPO'] if encabezados is None else encabezados)
        for fila in filas:
            ws.append(fila)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_alta_manual_y_duplicado(self):
        self.login()
        r = self._post('/tags', {
            'edificio': 'Botanika', 'departamento': '405',
            'residente': 'Nathaly Gallegos Rojas', 'codigo': '33b85aaf',
            'tipo': 'Tag', 'fecha': '2026-01-19',
        })
        self.assertIn('Tag registrado', r.get_data(as_text=True))
        # El mismo registro otra vez → se detecta como duplicado
        r2 = self._post('/tags', {
            'edificio': 'botanika ', 'departamento': ' 405',
            'residente': 'NATHALY GALLEGOS ROJAS', 'codigo': ' 33B85AAF ',
            'tipo': 'Tag',
        })
        self.assertIn('ya estaba registrado', r2.get_data(as_text=True))
        conn = get_db_connection()
        total = conn.execute('SELECT COUNT(*) FROM tags_acceso').fetchone()[0]
        codigo = conn.execute('SELECT codigo FROM tags_acceso').fetchone()[0]
        conn.close()
        self.assertEqual(total, 1)
        self.assertEqual(codigo, '33B85AAF', 'El código se guarda normalizado en mayúsculas')

    def test_importar_excel_sucio_deduplica(self):
        self.login()
        excel = self._excel_en_memoria([
            [1, 'Botanika', '405', 'Nathaly Gallegos', '33B85AAF', '19/01/2026', 'Tag'],
            [2, 'Sienna', '203', '203', '"E3425EAF\n"', '18/02/2026', 'Tag'],      # código sucio
            [None, None, None, None, '00000000', None, None],                      # separador
            [3, 'Acrux', '101', '101', '32248E4A', '9/03/2026', 'Tag', '1250829362'],  # nº decimal extra
            [4, 'Padua', '203', '203', 'B7100B40', '20/02/2026', 'Tag', 'se cambio'],  # nota extra
            [5, 'Botanika', '405', 'Nathaly Gallegos', '33B85AAF', '6/04/2026', 'Tag'],  # duplicado (otra fecha)
        ])
        r = self._post('/tags/importar', {'archivo': (excel, 'tags.xlsx')},
                       content_type='multipart/form-data')
        html = r.get_data(as_text=True)
        self.assertIn('4 registro(s) nuevo(s)', html)
        self.assertIn('1 duplicado(s)', html)

        conn = get_db_connection()
        filas = {f['codigo']: f for f in conn.execute('SELECT * FROM tags_acceso').fetchall()}
        conn.close()
        self.assertEqual(len(filas), 4)
        self.assertIn('E3425EAF', filas, 'El código con comillas/saltos debe quedar limpio')
        self.assertEqual(filas['32248E4A']['numero'], '1250829362')
        self.assertEqual(filas['B7100B40']['observaciones'], 'se cambio')
        self.assertEqual(filas['33B85AAF']['fecha'], '2026-01-19', 'Fecha normalizada a ISO')

        # Re-importar el mismo archivo → todo son duplicados
        excel2 = self._excel_en_memoria([
            [1, 'Botanika', '405', 'Nathaly Gallegos', '33B85AAF', '19/01/2026', 'Tag'],
        ])
        r2 = self._post('/tags/importar', {'archivo': (excel2, 'tags2.xlsx')},
                        content_type='multipart/form-data')
        self.assertIn('0 registro(s) nuevo(s)', r2.get_data(as_text=True))

    def test_importar_sin_encabezados_da_error_claro(self):
        self.login()
        excel = self._excel_en_memoria([[1, 2, 3]], encabezados=['A', 'B', 'C'])
        r = self._post('/tags/importar', {'archivo': (excel, 'malo.xlsx')},
                       content_type='multipart/form-data')
        self.assertIn('encabezados reconocibles', r.get_data(as_text=True))

    def test_depurar_elimina_duplicados_existentes(self):
        self.login()
        conn = get_db_connection()
        for _ in range(3):
            conn.execute('''
                INSERT INTO tags_acceso (edificio, departamento, residente, codigo)
                VALUES ('Amalfi', '1', '1', '52DA754A')
            ''')
        conn.commit()
        conn.close()
        r = self._post('/tags/depurar', {})
        self.assertIn('2 registro(s) duplicado(s)', r.get_data(as_text=True))

    def test_tipos_se_normalizan_a_un_solo_nombre(self):
        """Variantes del mismo tipo colapsan a un único nombre canónico."""
        import tags_import
        casos = {
            'Tag': ['Tag', 'tag', 'TAG'],
            'Tag Pagado': ['Tag pagado', 'Tag Pagado', 'tag PAGADO'],
            'Tag de Regalo': ['Tag de Regalo', 'Tag de regalo', 'Tag Regalo', 'Tag de  regalo'],
            'Tag Migrado': ['Tag Migrado', 'Tag migrado'],
            'Tarjeta Blanca': ['Tarjeta blanca', 'Tarjeta Blanca', 'tarjeta BLANCA'],
            'Tarjeta con Números': ['Tarjeta numeros', 'Tarjeta con numeros', 'Tarjeta Números'],
            'Tarjeta Pagado': ['Tarjeta Pagado', 'tarjeta pagado'],
        }
        for canonico, variantes in casos.items():
            for v in variantes:
                self.assertEqual(tags_import.normalizar_tipo(v), canonico, f'{v!r}')

        # La migración de init_db corrige lo ya guardado sin tocar los registros
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO tags_acceso (edificio, departamento, residente, codigo, tipo)
            VALUES ('Milano', '801', 'Maria', '27A8E13F', 'Tag pagado'),
                   ('Milano', '802', 'Jose', '17B44F59', 'Tag Pagado')
        """)
        conn.commit()
        conn.close()
        from db import init_db
        init_db()
        conn = get_db_connection()
        tipos = [r[0] for r in conn.execute(
            "SELECT DISTINCT tipo FROM tags_acceso WHERE edificio = 'Milano'").fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM tags_acceso WHERE edificio = 'Milano'").fetchone()[0]
        conn.close()
        self.assertEqual(tipos, ['Tag Pagado'], 'Debe quedar un solo tipo')
        self.assertEqual(total, 2, 'Los registros no se eliminan, solo se unifica el tipo')

    def test_lectura_no_puede_importar(self):
        from auth import hash_password
        conn = get_db_connection()
        conn.execute("""
            INSERT OR IGNORE INTO usuarios
                (username, password_hash, nombre_completo, rol, activo, debe_cambiar_password)
            VALUES ('lector2', ?, 'Lector Tags', 'lectura', 1, 0)
        """, (hash_password('Lectura123!'),))
        conn.commit()
        conn.close()
        self.login('lector2', 'Lectura123!')
        r = self.client.get('/tags')
        self.assertEqual(r.status_code, 200, 'Lectura sí puede ver la lista')
        r2 = self._post('/tags', {'edificio': 'X', 'codigo': 'ABC12345'})
        self.assertIn('No tienes permisos', r2.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
