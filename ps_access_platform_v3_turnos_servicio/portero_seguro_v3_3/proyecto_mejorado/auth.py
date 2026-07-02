"""
Modulo de autenticacion y control de acceso.

Mantiene la logica de seguridad separada del monolito app.py:
- Hashing de contrasenas (no se guarda nunca texto plano).
- Jerarquia de roles: lectura < operador < admin.
- Generacion/validacion de tokens CSRF.

No depende de Flask directamente (salvo werkzeug.security, que ya viene
instalado junto con Flask) para que sea facil de testear de forma aislada.
"""
import secrets

from werkzeug.security import generate_password_hash, check_password_hash

# Jerarquia de roles: un rol "superior" puede hacer todo lo que hace uno
# "inferior". lectura = solo puede ver pantallas. operador = trabajo diario
# de almacen (ingresos, salidas, guias, seguimiento, avances). admin =
# ademas administra catalogos, edificios, personal y usuarios del sistema.
ROLE_LEVELS = {
    'lectura': 0,
    'operador': 1,
    'admin': 2,
}

ROLES_VALIDOS = tuple(ROLE_LEVELS.keys())


def hash_password(password):
    """Genera un hash seguro (PBKDF2 + salt) para guardar en la base."""
    return generate_password_hash(password)


def check_password(password_hash, password):
    """Compara una contrasena en texto plano contra su hash almacenado."""
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def generar_password_temporal(longitud=10):
    """Genera una contrasena temporal legible para nuevos usuarios."""
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alfabeto) for _ in range(longitud))


def nuevo_csrf_token():
    return secrets.token_hex(32)


def rol_alcanza(rol_usuario, rol_requerido):
    """True si rol_usuario tiene permisos suficientes para rol_requerido."""
    nivel_usuario = ROLE_LEVELS.get(rol_usuario, -1)
    nivel_requerido = ROLE_LEVELS.get(rol_requerido, 99)
    return nivel_usuario >= nivel_requerido
