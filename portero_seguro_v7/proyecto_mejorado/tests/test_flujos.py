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


if __name__ == '__main__':
    unittest.main(verbosity=2)
