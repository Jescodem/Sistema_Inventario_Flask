# Parche: navegación, edificios y trazabilidad de series

## Cambios incluidos

1. Navbar reorganizado por grupos:
   - Inventario
   - Guías
   - Operación
   - Administración

2. Corrección de activo visual en el navbar:
   - Configuración ya no activa Operación ni Edificios.
   - Edificios ahora tiene ruta propia `/edificios`.

3. Dashboard de edificios:
   - Ruta `/edificios`.
   - Permite crear, editar, buscar y visualizar edificios.
   - Campos: nombre, ubicación/dirección, link de Maps/coordenadas y observaciones.

4. Dashboard principal con búsqueda instantánea:
   - Filtra mientras escribes sin recargar.
   - Busca por marca, modelo, categoría, estado, SKU, serie y MAC.

5. Trazabilidad de series/MAC:
   - El dashboard muestra botón “Ver series” cuando el producto tiene series en `equipo_series`.
   - La migración protege series/MAC antiguas antes de consolidar productos duplicados.
   - Si un ingreso normal tiene SKU/MAC y cantidad 1, se guarda como unidad serializada en `equipo_series` y no duplica el producto.
   - Si tiene SKU/MAC y cantidad mayor a 1, el sistema pide usar “Ingreso Series”.

## Nota importante sobre datos ya perdidos

Si una migración anterior ya fusionó productos y solo dejó una serie/MAC en la fila principal, las otras series no se pueden reconstruir desde esa base actual. Para recuperarlas se necesita una copia backup anterior a la consolidación.

## Instalación

1. Haz backup:

```bat
copy inventario.db inventario_backup_nav_edificios_trazabilidad.db
```

2. Copia los archivos del parche sobre tu proyecto.

3. Ejecuta:

```bat
python migrar_fase1.py
python app.py
```

4. Recarga el navegador con `CTRL + F5`.

## Archivos modificados

- app.py
- migrar_fase1.py
- templates/base.html
- templates/index.html
- templates/edificios.html
