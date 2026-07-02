# Mejoras técnicas — v7

Continúa la modularización iniciada en v6.

## 1. PDF extraído a `pdf_render.py`

Las ~330 líneas de maquetación ReportLab salieron de `app.py` hacia
`pdf_render.py`. La ruta `/pdf_guia/<id>` quedó delgada: consulta la guía,
el detalle y las series, y delega el render a
`render_guia_pdf(guia, detalle, series_por_detalle, codigo_doc)` que
devuelve un `BytesIO`. Los imports de reportlab e `io` ya no viven en
`app.py`. Verificado generando un PDF real (20 KB, cabecera %PDF válida).

`app.py`: 3,772 → 3,442 líneas.

## 2. JavaScript extraído a `static/js/`

- **`static/js/app.js`** — comportamiento global que antes vivía inline en
  `base.html`: sidebar colapsable con persistencia en localStorage,
  inyección automática del token CSRF en formularios POST, y **nuevo**:
  estado de carga en formularios (al enviar, deshabilita los botones y
  muestra un spinner; previene el doble clic que generaba guías duplicadas).
- **`static/js/dashboard.js`** — filtro en tiempo real + paginación del
  inventario, antes inline en `index.html`.

Beneficios: caché del navegador, separación de responsabilidades y un solo
lugar para editar cada comportamiento.

## Verificación

- `python -m unittest tests.test_flujos` → 10/10 OK.
- Smoke test con navegador real: filtro y paginación funcionando desde los
  archivos externos, cero errores de JavaScript propios.

## Pendiente (sin cambios desde v6)

- Blueprints para las 51 rutas (requiere mover helpers compartidos primero).
- Catálogos con claves foráneas numéricas.
- Migraciones numeradas en lugar de `init_db` en cada arranque.
