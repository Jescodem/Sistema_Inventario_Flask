# Fase 1.1 - Serializacion de Activos

Este parche agrega control de activos por serial sin eliminar la logica existente por cantidad.

## Finalidad

Separar dos tipos de inventario:

- **CANTIDAD**: consumibles, conectores, cable, fuentes sin seguimiento individual.
- **SERIAL**: camaras, NVR, switches, AP, laptops, videoporteros y equipos que requieren trazabilidad individual.

## Nuevas tablas

```sql
CREATE TABLE equipo_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id INTEGER NOT NULL,
    serial TEXT UNIQUE NOT NULL,
    mac TEXT,
    estado TEXT DEFAULT 'EN_STOCK',
    guia_id INTEGER,
    ubicacion_actual TEXT,
    fecha_ingreso TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP,
    observaciones TEXT
);

CREATE TABLE guia_detalle_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guia_detalle_id INTEGER NOT NULL,
    serie_id INTEGER NOT NULL,
    UNIQUE(guia_detalle_id, serie_id)
);
```

Tambien agrega a `equipos`:

```sql
control_stock TEXT DEFAULT 'CANTIDAD'
```

## Nuevas rutas

- `/ingreso_series`: ingreso masivo de equipos serializados.
- `/api/series?equipo_id=ID`: lista series disponibles de un producto.

## Flujo de ingreso serializado

1. Selecciona categoria.
2. Selecciona marca filtrada por categoria.
3. Selecciona modelo filtrado por marca.
4. Indica cantidad esperada.
5. Pega las series, una por linea.
6. Opcional: `SERIAL,MAC`.
7. Guarda.

El sistema crea o actualiza el producto base y registra cada serie como una unidad fisica.

## Flujo de guia

- Si el producto es `CANTIDAD`, la guia pide cantidad.
- Si el producto es `SERIAL`, la guia muestra las series disponibles y la cantidad se calcula automaticamente.

Al guardar la guia:

- Baja stock del producto base.
- Cambia cada serie seleccionada a `ENTREGADO`.
- Guarda las series exactas en `guia_detalle_series`.

Al anular la guia:

- Reintegra stock.
- Devuelve las series a `EN_STOCK`.

## Pruebas recomendadas

1. Ejecutar `python migrar_fase1.py`.
2. Abrir `/ingreso_series`.
3. Registrar 3 series para una camara.
4. Crear guia y seleccionar 2 series.
5. Confirmar que el stock baja de 3 a 1.
6. Ver la guia y comprobar que salen las series.
7. Anular la guia y confirmar que el stock vuelve a 3 y las series a `EN_STOCK`.

## Nota

Para equipos con serial, usa preferentemente guias, no salidas directas. La trazabilidad corporativa queda en la guia y en los movimientos.
