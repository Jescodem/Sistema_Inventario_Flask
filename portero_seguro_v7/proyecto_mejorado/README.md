# Portero Seguro — Sistema de Control de Activos y Trazabilidad

Aplicación web de **inventario y trazabilidad** para una empresa de instalaciones de seguridad
electrónica (CCTV, control de accesos, redes y consumibles). Gestiona el almacén, el despacho a obra
mediante **guías de salida**, la **trazabilidad por número de serie**, un **kardex auditable** de
movimientos y la operación en campo (seguimiento y avances).

> Aplicación monolítica **Flask + SQLite**, servida en red local tras un **proxy inverso Caddy**.

---

## Características principales

- **Inventario** por cantidad y por número de serie (`control_stock = CANTIDAD | SERIAL`).
- **Ingresos** unitarios, masivos serializados y por cantidad con **unificación** (no duplica productos).
- **Guías de salida** con PDF imprimible, edición, anulación y devolución parcial de series.
- **Kardex** de movimientos (auditoría con usuario, fecha y stock antes/después).
- **Seguimiento** de equipos/herramientas en campo y **bitácora de avances**.
- **Seguridad**: login, 3 roles (`lectura < operador < admin`), CSRF, rate limiting, hash PBKDF2.
- **Descuento de stock atómico** (a prueba de condiciones de carrera).

## Requisitos

- **Windows** 10/11.
- **Python 3.10+** en el PATH (marca *Add Python to PATH* al instalar).
- Conexión a internet **solo la primera vez** (para descargar dependencias y Caddy).

## Puesta en marcha (rápida)

1. Doble clic en **`lanzar.bat`**. Acepta el permiso de administrador.
2. La primera vez: instala dependencias, descarga Caddy, abre el firewall y registra el dominio local.
3. En el banner aparecerán la **URL** y las **credenciales iniciales** del administrador (solo la primera vez).
4. Abre en el navegador: `http://192.168.18.137` (por IP) o `http://inventario.porteroseguro.com` (por dominio).

Para detener: **Ctrl+C** en la ventana del servidor (o `detener.bat`).

## Acceso desde otros equipos de la red

Ver **[README_ACCESO_RED.md](README_ACCESO_RED.md)**. En resumen: por IP funciona sin configurar nada;
para el dominio, se añade una entrada DNS en el router (o se usa `configurar_cliente.bat` en cada equipo).

## Respaldo de la base de datos

La base es un único archivo (`inventario.db`). **Respáldala:**

- Manual: doble clic en **`respaldar_bd.bat`** → copia con fecha en `backups\`.
- Automático diario: ejecuta **`programar_respaldo.bat`** una vez (crea una tarea de Windows a las 20:00).
- Restaurar: detén el servidor y copia el respaldo deseado de `backups\` sobre `inventario.db`.

## Arranque automático (opcional)

Para que el servidor se levante solo al iniciar Windows: **`instalar_autoarranque.bat`**
(y `desinstalar_autoarranque.bat` para quitarlo).

## Ejecutables y utilidades

| Archivo | Para qué |
|---|---|
| `lanzar.bat` | Arranca el servidor + proxy. |
| `detener.bat` | Detiene el servidor. |
| `respaldar_bd.bat` | Respaldo manual de la base de datos. |
| `programar_respaldo.bat` | Programa el respaldo automático diario. |
| `instalar_autoarranque.bat` | Arranque automático al iniciar Windows. |
| `configurar_cliente.bat` | Configura un equipo cliente (fallback DNS). |

## Estructura del proyecto

```
proyecto_mejorado/
├── app.py                 # Rutas + lógica de negocio (monolito)
├── db.py                  # Esquema, migraciones, acceso a datos
├── auth.py                # Hashing, roles, CSRF
├── pdf_render.py          # PDF de guías (ReportLab)
├── migrar_fase1.py        # Consolidaciones históricas
├── templates/  static/    # Vistas Jinja2 y recursos (JS, imágenes)
├── tests/                 # Pruebas de integración
├── docs/                  # Documentación técnica y manuales (PDF)
└── *.bat / _portero_launcher.py / Caddyfile   # Arranque y despliegue
```

## Roles

| Rol | Puede |
|---|---|
| **lectura** | Ver dashboards, guías, series y movimientos. |
| **operador** | + Ingresos, salidas, guías, bajas, seguimiento y avances. |
| **admin** | + Catálogos, edificios, personal y usuarios. |

## Pruebas

```bash
python -m unittest discover -s tests -v
```

**47 pruebas** de integración en dos suites (`test_flujos.py` y `test_operaciones.py`):
seguridad y descuento atómico; guías por cantidad y serializadas, anulación, devolución
parcial, permisos por rol, bajas, ingresos, exportación a Excel, alertas de stock, gestión
de usuarios/contraseñas y red de edificios (IPs, credenciales, edición y enlaces).
Usan una base temporal (`PORTERO_DB`); nunca tocan `inventario.db`.

## Documentación

- **[docs/Documentacion_Tecnica_Portero_Seguro.pdf](docs/)** — arquitectura, modelo de datos, seguridad y casos de uso.
- **[docs/Manual_Usuario_Portero_Seguro.pdf](docs/)** — guía paso a paso para el operador.
- **[CHANGELOG.md](CHANGELOG.md)** — historial de versiones y parches.
- **[README_ACCESO_RED.md](README_ACCESO_RED.md)** — acceso en red local y proxy inverso.

## Licencia

Software interno de Portero Seguro. Todos los derechos reservados.
