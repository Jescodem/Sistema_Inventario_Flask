# Seguridad: autenticación, roles y protección CSRF

Este documento resume los cambios de seguridad implementados sobre la base del
proyecto original. Antes de esto, **cualquier persona con acceso a la URL
podía ver y modificar todo el inventario sin iniciar sesión**, el servidor
corría con el debugger de Flask expuesto en la red, y existían rutas que
borraban datos con un simple `GET` (vulnerables a CSRF).

## Qué cambió

1. **Login obligatorio.** Ninguna pantalla es accesible sin iniciar sesión
   (`/login` y los archivos estáticos son las únicas excepciones).
2. **Tres roles**, de menor a mayor privilegio:
   - `lectura`: solo puede ver pantallas, no puede crear ni modificar nada.
   - `operador`: trabajo diario de almacén (ingresos, salidas, guías,
     series, seguimiento, avances, dar de baja equipos).
   - `admin`: además administra catálogos (categorías, marcas, modelos,
     cargos), personal, edificios y usuarios del sistema.
3. **Contraseñas con hash** (PBKDF2 vía Werkzeug). Nunca se guarda una
   contraseña en texto plano.
4. **Protección CSRF** en todos los formularios `POST`. El token se inyecta
   automáticamente vía JavaScript en `base.html`, así que no fue necesario
   tocar cada plantilla individualmente.
5. **Auditoría real de movimientos**: `registrar_movimiento()` ahora usa el
   usuario autenticado de la sesión en vez del valor fijo `'Sistema'`.
6. **Rutas destructivas convertidas de `GET` a `POST`**: anular guía
   (`/eliminar_guia`) y eliminar edificio (`/edificios/eliminar`) ya no se
   pueden disparar con un simple enlace o un bot que siga links.
7. **`SECRET_KEY` ya no tiene un valor por defecto fijo en el código.** Se
   toma de la variable de entorno `SECRET_KEY` o, si no existe, se genera
   una vez y se guarda en `.secret_key` (excluido de git).
8. **`debug=True` ya no está fijo.** El servidor arranca en modo seguro por
   defecto; el modo debug y el host solo se activan explícitamente por
   variable de entorno.

## Primer arranque

La primera vez que ejecutes la aplicación (con la tabla `usuarios` vacía),
se crea automáticamente un usuario `admin`. Si no defines variables de
entorno, la contraseña se genera al azar **y se imprime una sola vez en la
consola del servidor**:

```bash
python app.py
```

```
======================================================================
 USUARIO ADMINISTRADOR CREADO AUTOMATICAMENTE
   Usuario:    admin
   Contrasena: ********** (ejemplo)
 Cambia esta contrasena apenas inicies sesion.
======================================================================
```

Para fijar tus propias credenciales iniciales en vez de una contraseña
aleatoria:

```bash
export ADMIN_USERNAME=tu_usuario
export ADMIN_PASSWORD=tu_password_segura
python app.py
```

Una vez dentro, cualquier usuario puede cambiar su propia contraseña desde
**Administración → Usuarios**. Los administradores también pueden crear
nuevos usuarios (se genera una contraseña temporal que el usuario debe
cambiar en su primer ingreso) y restablecer contraseñas olvidadas.

## Variables de entorno relevantes

| Variable | Por defecto | Descripción |
|---|---|---|
| `SECRET_KEY` | (generada y guardada en `.secret_key`) | Clave de firma de sesiones. Defínela explícitamente en producción. |
| `ADMIN_USERNAME` | `admin` | Usuario del admin inicial (solo aplica si no hay usuarios todavía). |
| `ADMIN_PASSWORD` | (aleatoria) | Contraseña del admin inicial. |
| `FLASK_DEBUG` | `false` | Activa el modo debug (**nunca** en producción: expone ejecución remota de código). |
| `FLASK_HOST` | `127.0.0.1` | Interfaz de red donde escucha el servidor. Usa `0.0.0.0` solo si necesitas acceso desde otras máquinas de tu red. |
| `FLASK_PORT` | `5051` | Puerto del servidor. |
| `SESSION_COOKIE_SECURE` | `false` | Ponlo en `true` si sirves la app detrás de HTTPS. |

## Qué NO incluye todavía esta entrega

Quedó fuera de este alcance (seguridad), pero vale la pena considerarlo
después:

- Bloqueo temporal tras varios intentos fallidos de login (rate limiting).
- Expiración/renovación automática de sesión por inactividad.
- HTTPS (debe resolverse con un reverse proxy como nginx o Caddy delante de
  Flask; Flask por sí solo no debería exponerse directo a Internet).
- Corregir la condición de carrera al validar stock disponible en guías
  con escritura concurrente (mencionado en el análisis general).
- Tests automatizados de los flujos de autenticación y permisos.

## Matriz de permisos por ruta

| Acción | lectura | operador | admin |
|---|---|---|---|
| Ver dashboard, guías, movimientos, series | ✅ | ✅ | ✅ |
| Registrar ingresos / salidas / guías | ❌ | ✅ | ✅ |
| Anular guía, dar de baja equipo | ❌ | ✅ | ✅ |
| Seguimiento y avances de obra | ❌ | ✅ | ✅ |
| Catálogos (categorías, marcas, modelos, cargos) | ❌ | ❌ | ✅ |
| Personal y edificios (crear/editar/eliminar) | ❌ | ❌ | ✅ |
| Gestión de usuarios | ❌ | ❌ | ✅ |
