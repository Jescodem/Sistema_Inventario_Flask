# Changelog — Portero Seguro

Historial de versiones y parches, del más reciente al más antiguo. Consolida los documentos
`README_*.md` de cada entrega.

El formato agrupa por **versiones técnicas** (v6, v7) y por **parches funcionales** anteriores.

---

## [Función] — Red de edificios: credenciales incluidas

- Por decisión del administrador, la red de cada edificio ahora incluye el **usuario y la clave**
  de cada equipo (columnas nuevas en `edificio_ips`), visibles al expandir, en el modal de
  detalle, en el formulario de agregar y en la exportación **Excel red**.
- El importador carga/actualiza las credenciales desde el Excel sin duplicar puntos
  (868 puntos actualizados: 670 con usuario, 693 con clave).

## [Función] — Red de edificios: gestión y exportación

- El **admin** puede **agregar y eliminar puntos de red** directamente desde el bloque expandible
  de cada edificio (sin depender del Excel).
- Nueva exportación **Excel red** (`/exportar/red_edificios`): todas las IPs/anexos por edificio,
  con botón en la vista de Edificios.
- **Fix:** eliminar un edificio con red registrada fallaba por la clave foránea; ahora su red se
  elimina junto con él (solo si el edificio no tiene actividad, como siempre).
- Documentación técnica y manual actualizados (19 tablas, nueva exportación).
- +4 pruebas (41 en total).

## [Función] — Red de edificios (IPs y anexos)

- Nueva tabla `edificio_ips`: puntos de red de cada edificio (intercom, lobby, altavoz, DVR,
  Mikrotik…) con IP, anexo y descripción.
- Importador `importar_ips_edificios.py`: carga edificios y su red desde el Excel corporativo
  (hoja ExtensionesIP). Re-ejecutable sin duplicar; normaliza IPs que Excel guardó como número
  (192168100101 → 192.168.100.101). **No importa usuarios/claves** de los equipos por seguridad.
- Vista `/edificios`: botón "IPs (n)" que **expande** la red del edificio (oculta a simple
  vista), sección de red en el modal de detalle y buscador que también encuentra por IP/anexo.
- Importados: 188 edificios nuevos (200 en total) y 868 puntos de red.
- +3 pruebas (37 en total).

## [Fix] — Login por dominio tras el cambio HTTPS→HTTP

- La cookie de sesión pasó a llamarse `ps_session`. Al servir antes el dominio por HTTPS, el
  navegador guardaba una cookie `session` marcada `Secure` que, por la regla "Leave Secure Cookies
  Alone", un sitio HTTP no puede sobreescribir: el login funcionaba por IP pero no por
  `inventario.porteroseguro.com`. Con el nombre nuevo, la cookie antigua queda ignorada y el acceso
  funciona igual por IP que por dominio (sin tener que limpiar cookies en cada equipo).

## [Fix] — Gestión de contraseñas de usuarios

- **El administrador ahora puede fijar la contraseña** al crear un usuario (campo opcional;
  si se deja en blanco se genera una temporal como antes) y **cambiarla desde el modal de edición**.
- **Nueva página "Mi cuenta"** (`/mi_cuenta`) accesible a cualquier rol para cambiar la propia
  contraseña, con acceso desde el bloque de usuario del menú lateral.
- **Corregido:** los usuarios no administradores con contraseña temporal eran redirigidos a
  `/usuarios` (solo admin) y quedaban sin poder cambiarla; ahora van a `/mi_cuenta`.
- +6 pruebas (34 en total).

## [Pruebas] — Cobertura ampliada

- Nueva suite `tests/test_operaciones.py` (18 pruebas): guías por cantidad y serializadas,
  anulación con reintegro, devolución parcial de series, permisos por rol (operador/lectura/admin),
  dar de baja (normal y bloqueada por guía activa), unificación de producto, validación SKU/MAC,
  exportación a Excel, alertas de stock mínimo y configuración de sesión.
- Total: **28 pruebas** (`python -m unittest discover -s tests -v`). Siguen usando una base
  temporal vía `PORTERO_DB`: nunca tocan `inventario.db`.

## [Mejoras de operación] — Excel, alertas de stock y sesión

- **Exportación a Excel** (`/exportar/<tipo>`): inventario, movimientos (kardex), guías y series,
  con botón "Excel" en cada pantalla. Nuevo módulo `excel_export.py` (openpyxl, ahora en requirements).
- **Alertas de reposición** en el dashboard: aviso con los productos en o bajo su stock mínimo
  (incluye los que llegaron a 0), ordenados del más crítico al menos.
- **Expiración de sesión por inactividad**: 30 minutos (ventana deslizante), configurable con
  `SESSION_TIMEOUT_MINUTES`. Importante en equipos compartidos.
- **Manual de usuario con capturas de pantalla** reales (generadas con datos de demostración,
  sin exponer datos reales) y documentación técnica actualizada.

## [Despliegue] — Acceso en red con proxy inverso

- **Proxy inverso Caddy** en el puerto 80 delante de Flask (que ahora escucha solo en `127.0.0.1:5051`).
- Acceso por **IP** o por **dominio local** `inventario.porteroseguro.com`.
- `lanzar.bat` orquesta todo: eleva a administrador, instala dependencias, descarga Caddy, abre el
  firewall (puerto 80) y registra el dominio en `hosts`.
- `_portero_launcher.py` supervisa Caddy + Flask (Ctrl+C detiene ambos).
- `ProxyFix` en Flask para respetar las cabeceras del proxy; cookies de sesión ajustadas a HTTP.
- Detalles en `README_ACCESO_RED.md`.

## [Entregables operativos]

- **Respaldo automático** de la base de datos (`respaldar_bd.py` / `.bat`, `programar_respaldo.bat`)
  con copia en caliente (API de backup de SQLite) y rotación de 30 días.
- **Autoarranque** al iniciar Windows (`instalar_autoarranque.bat`) y `detener.bat`.
- **Documentación** técnica y **manual de usuario** en PDF (`docs/`).
- `README.md` y este `CHANGELOG.md`.

---

## v7 — Modularización (continuación)

- **PDF extraído** a `pdf_render.py` (~330 líneas de ReportLab fuera de `app.py`).
- **JavaScript extraído** a `static/js/`:
  - `app.js`: sidebar colapsable con persistencia, inyección automática de CSRF y **estado de carga**
    en formularios (evita el doble clic que duplicaba guías).
  - `dashboard.js`: filtro en vivo + paginación del inventario.
- `app.py`: 3.772 → 3.442 líneas. Tests 10/10 OK.

## v6 — Robustez, seguridad operativa y mantenibilidad

- **Modularización (inicio):** capa de datos extraída a `db.py` (ruta configurable con `PORTERO_DB`).
- **Fix de condición de carrera en stock (crítico):** `descontar_stock_atomico()` con `UPDATE ... WHERE
  cantidad >= ?`; imposible dejar stock negativo. `busy_timeout = 5000`.
- **Logging** rotativo en `logs/app.log` (logins, guías, bajas, excepciones).
- **Rate limiting** del login (5 intentos / 5 min por IP+usuario, en memoria).
- **Suite de tests** de integración (`tests/test_flujos.py`, 10 casos).
- **Frontend:** capa de alias de tokens CSS para reparar estilos; paginación del dashboard (25/pág.).

---

## Parches funcionales anteriores

### Seguridad: autenticación, roles y CSRF
- Login obligatorio; 3 roles (`lectura < operador < admin`); contraseñas con hash PBKDF2.
- Protección CSRF en todos los `POST`; auditoría real de movimientos con el usuario de la sesión.
- Rutas destructivas convertidas de `GET` a `POST`; `SECRET_KEY` sin default fijo; `debug` apagado.

### Serialización de activos (Fase 1.1)
- Tablas `equipo_series` y `guia_detalle_series`; columna `control_stock` (`CANTIDAD`/`SERIAL`).
- Ruta `/ingreso_series` (ingreso masivo) y `/api/series`. Guías con selección de series exactas;
  anulación que reintegra stock y devuelve series a `EN_STOCK`.

### Productos unificados y buscador en guías
- El producto base se identifica por Categoría + Marca + Modelo + tipo de control; ingresar el mismo
  producto **suma stock** en lugar de duplicar. Consolidación de duplicados históricos.
- Buscador de texto en los modales de producto de guías.

### Jerarquía Categoría → Marca → Modelo
- Filtrado real por API (`/api/marcas`, `/api/modelos`, `/api/productos`).
- Administración de relaciones en `/configuracion` y limpieza de relaciones vacías.

### Navegación, edificios y trazabilidad de series
- Navbar por grupos (Inventario, Guías, Operación, Administración).
- Dashboard de **edificios** (`/edificios`) y búsqueda instantánea en el dashboard principal.
- Botón "Ver series" y protección de series/MAC en migraciones.

### Seguimiento + Avances / Notas
- Módulo `/seguimiento` (equipos dejados temporalmente en campo) y `/avances` (bitácora de actividades).
- Tablas `seguimiento_equipos`, `seguimiento_herramientas` y `avances_actividades`.

### Stock 0, bajas y tema corporativo
- Normalización de estado por stock (`En Stock` / `Sin Stock`) sin tocar estados especiales.
- Botón **Dar de baja** (no borra: estado `Baja`, cantidad 0, movimiento `BAJA`), con bloqueos si hay
  guías activas o series entregadas.
- Tema visual naranja/marrón "Portero Seguro Perú". Salida directa protegida para productos serializados.
