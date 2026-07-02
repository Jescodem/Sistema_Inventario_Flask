# Mejoras técnicas — v6

Esta versión aplica las mejoras identificadas en el análisis de código,
enfocadas en robustez, seguridad operativa y mantenibilidad.

## 1. Modularización (inicio)

Se extrajo la capa de datos a **`db.py`**: conexiones, esquema, migraciones
y helpers de catálogos (~430 líneas fuera de `app.py`). La ruta de la base
ahora es configurable con la variable de entorno **`PORTERO_DB`**, lo que
permite apuntar a bases separadas para tests o entornos.

```
app.py   → rutas y lógica de negocio (todavía grande; siguiente fase: blueprints)
db.py    → get_db_connection, init_db, migraciones, helpers de catálogo
auth.py  → hashing, roles, CSRF
tests/   → suite de integración
```

## 2. Fix del race condition en stock (crítico)

El patrón anterior `leer stock → validar → escribir` permitía que dos
despachos simultáneos del mismo producto generaran **stock negativo** al
desplegarse con un servidor multi-worker.

Nueva función `descontar_stock_atomico()`: ejecuta
`UPDATE ... SET cantidad = cantidad - ? WHERE id = ? AND cantidad >= ?`
y verifica `rowcount`. El descuento solo ocurre si el stock alcanza **en el
momento de la escritura**. Aplicado en `guardar_guia` y `salidas` (los dos
puntos de descuento). Además, `get_db_connection` ahora incluye
`PRAGMA busy_timeout = 5000` para tolerar bloqueos transitorios.

## 3. Logging de aplicación

Archivo rotativo en `logs/app.log` (1 MB × 5 archivos). Se registran:
- Logins exitosos, fallidos y bloqueados por rate limit (con IP).
- Creación y anulación de guías (con usuario).
- Bajas de equipos.
- Excepciones en las operaciones de guía (con traceback completo).

## 4. Rate limiting en el login

Máximo **5 intentos fallidos por IP+usuario en 5 minutos**, sin
dependencias externas (en memoria). Tras el límite, incluso la contraseña
correcta es rechazada hasta que expire la ventana. Nota: si el despliegue
pasa a multi-worker, migrar a `flask-limiter` con backend compartido.

## 5. Suite de tests

`tests/test_flujos.py` — 10 tests de integración ejecutables con:

```bash
python -m unittest tests.test_flujos -v
```

Cubren: redirección de rutas protegidas, login correcto/incorrecto,
rechazo de POST sin CSRF, bloqueo por rate limiting, restricción de rol
lectura, y 4 tests del descuento atómico (incluido el escenario de
concurrencia). Usan una base temporal vía `PORTERO_DB`: **nunca tocan
`inventario.db`**.

## 6. Frontend: tokens de compatibilidad

El rediseño previo cambió los nombres de las variables CSS, dejando las
plantillas no reescritas (avances, seguimiento, personal, salidas, guías,
edificios…) con estilos rotos que caían a valores por defecto del
navegador. Se agregó en `base.html` una capa de **alias** que mapea los
tokens antiguos (`--surface`, `--mist`, `--ok`, `--font-mono`, …) a los
nuevos (`--c-surface`, `--c-muted`, `--c-success`, `--mono`, …). Todas las
páginas renderizan ahora con la paleta del logo sin reescritura masiva.

Los estilos del componente `.metric` se consolidaron en `base.html`
(estaban duplicados en avances y seguimiento).

## 7. Paginación del dashboard

La tabla de inventario pagina de a **25 registros**, integrada con el
filtro en tiempo real (se pagina sobre el resultado filtrado). Botones
Anterior/Siguiente + indicador de página.

## Pendiente para siguientes iteraciones

- Separar las 51 rutas en blueprints (`inventario`, `guias`, `admin`).
- Migrar categoría/marca/modelo de texto libre a claves foráneas numéricas
  (elimina `consolidar_productos_duplicados` de raíz).
- Sistema de migraciones numeradas en lugar de `init_db` en cada arranque.
- Extraer el JS inline de las plantillas a `static/js/`.
- Feedback de carga (spinner + disable) en formularios de guías.
