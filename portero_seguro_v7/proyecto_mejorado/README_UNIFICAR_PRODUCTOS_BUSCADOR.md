# Parche: productos unificados y buscador en guias

## Problema corregido

Antes, cada vez que se ingresaba el mismo producto con la misma Categoria + Marca + Modelo, el sistema podia crear una nueva fila en inventario. Eso generaba redundancia y hacia que en las guias apareciera el mismo producto varias veces con stocks separados.

## Nueva regla

El producto base se identifica por:

Categoria + Marca + Modelo/Descripcion + Tipo de control

Para productos por cantidad:
- Si ya existe, no crea otro producto.
- Solo incrementa el stock del producto existente.
- Registra movimiento INGRESO.
- Si habia duplicados previos, el migrador los consolida.

Para equipos serializados:
- Se mantiene el uso de Ingreso Series.
- Cada serial queda en equipo_series.
- El producto base sigue siendo unico.

## Cambios incluidos

- app.py
  - Ingresos ahora actualiza stock si el producto ya existe.
  - Se agrega consolidacion de productos duplicados existentes.
  - Se evita que las guias trabajen con filas duplicadas futuras.

- migrar_fase1.py
  - Consolida productos duplicados existentes.
  - Reapunta guia_detalle, salidas, movimientos, equipo_series y seguimiento_equipos al producto base.
  - Fusiona lineas duplicadas dentro de la misma guia.

- templates/guias.html
  - Agrega buscador de texto en el modal de productos.
  - Filtra por categoria, marca, modelo, SKU y MAC mientras escribes.

- templates/editar_guia.html
  - Agrega buscador de texto en el modal de edicion de guia.
  - Filtra productos mientras escribes.

## Instalacion

1. Hacer backup:

copy inventario.db inventario_backup_antes_unificar_productos.db

2. Reemplazar archivos del parche.

3. Ejecutar migracion:

python migrar_fase1.py

4. Levantar Flask:

python app.py

## Prueba recomendada

1. Ingresar CCTV > Hikvision > Camara Domo IP 4MP con cantidad 5.
2. Ingresar otra vez el mismo producto con cantidad 3.
3. Debe quedar un solo producto con stock 8.
4. Crear una guia y abrir el modal de producto.
5. Buscar por texto "hik" o "domo".
6. Debe filtrar mientras escribes y no duplicar el producto.
