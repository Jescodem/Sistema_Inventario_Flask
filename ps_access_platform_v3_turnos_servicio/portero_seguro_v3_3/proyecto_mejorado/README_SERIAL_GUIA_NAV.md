# Parche: seriales en guia y navbar

## Cambios incluidos

1. Nueva pantalla para completar o corregir seriales/MAC de una guia existente:
   - Ruta: `/guia/<id>/series`
   - Accesos desde `Ver guia` y `Listado de guias`.
   - Permite escribir una serie por linea.
   - Formato permitido: `SERIAL` o `SERIAL,MAC`.
   - Valida que la cantidad de series ingresadas coincida con la cantidad del detalle de guia.
   - No modifica stock ni cantidad de guia; solo completa la trazabilidad de `equipo_series` y `guia_detalle_series`.

2. Correccion del menu lateral de Guias:
   - `Nueva Guia` solo queda activo en `/guias`.
   - `Listado` queda activo en `/listar_guias`, `/guia/<id>` y `/editar_guia/<id>`.
   - Se evita que ambas opciones se iluminen a la vez.

## Instalacion

1. Hacer backup:

```bat
copy inventario.db inventario_backup_antes_seriales_guia.db
```

2. Copiar estos archivos del parche sobre tu proyecto:

```text
app.py
templates/base.html
templates/ver_guia.html
templates/listar_guias.html
templates/actualizar_series_guia.html
```

3. Reiniciar Flask:

```bat
python app.py
```

## Uso

1. Ir a `Guias > Listado`.
2. Presionar `Seriales` en la guia que necesita correccion.
3. En cada producto, pegar las series reales.
4. Guardar.
5. Volver a la guia y verificar que aparezcan todos los seriales.

