# Modelo Entidad Relacion - Inventario CCTV y Redes - Fase 1 Corporativa

## Objetivo
Este modelo ordena el sistema para que la guia de salida no sea solo un documento, sino una operacion trazable. Cada ingreso, salida, edicion, anulacion o reintegro debe quedar registrado en `movimientos`.

## Diagrama ER recomendado para Fase 1

```mermaid
erDiagram
    CATEGORIAS ||--o{ EQUIPOS : clasifica
    MARCAS ||--o{ EQUIPOS : fabrica
    MODELOS ||--o{ EQUIPOS : describe
    CARGOS ||--o{ PERSONAL : asigna
    PERSONAL ||--o{ GUIAS_SALIDA : solicita
    EDIFICIOS ||--o{ GUIAS_SALIDA : destino
    GUIAS_SALIDA ||--o{ GUIA_DETALLE : contiene
    EQUIPOS ||--o{ GUIA_DETALLE : se_retira
    EQUIPOS ||--o{ SALIDAS : salida_directa
    EQUIPOS ||--o{ MOVIMIENTOS : genera
    GUIAS_SALIDA ||--o{ MOVIMIENTOS : audita

    EQUIPOS {
        int id PK
        text categoria
        text marca
        text descripcion
        text sku
        text mac
        text estado
        int cantidad
        int stock_minimo
        text observaciones
        datetime fecha_creacion
        datetime fecha_actualizacion
    }

    CATEGORIAS {
        int id PK
        text nombre UK
    }

    MARCAS {
        int id PK
        text nombre UK
    }

    MODELOS {
        int id PK
        text nombre UK
    }

    CARGOS {
        int id PK
        text nombre UK
    }

    PERSONAL {
        int id PK
        text nombre UK
        text cargo
    }

    EDIFICIOS {
        int id PK
        text nombre UK
    }

    GUIAS_SALIDA {
        int id PK
        text personal
        text cargo
        text destino
        text proyecto
        text entregado_por
        text recibido_por
        text aprobado_por
        text observaciones
        datetime fecha
        text estado
        datetime fecha_anulacion
        text motivo_anulacion
    }

    GUIA_DETALLE {
        int id PK
        int guia_id FK
        int equipo_id FK
        int cantidad
    }

    SALIDAS {
        int id PK
        int equipo_id FK
        text personal
        text destino
        int cantidad
        datetime fecha
        text observaciones
    }

    MOVIMIENTOS {
        int id PK
        int equipo_id FK
        int guia_id FK
        text tipo
        int cantidad
        int stock_anterior
        int stock_nuevo
        text referencia
        text usuario
        datetime fecha
        text observaciones
    }
```

## Regla principal de integridad

La tabla `equipos` guarda el stock actual. La tabla `movimientos` guarda la historia. Nunca se debe modificar stock sin registrar un movimiento.

## Flujo de stock para guias

1. Crear guia activa:
   - Valida producto existente.
   - Valida cantidad mayor a cero.
   - Valida stock suficiente.
   - Descuenta stock.
   - Inserta detalle en `guia_detalle`.
   - Registra `SALIDA_GUIA` en `movimientos`.

2. Editar guia activa:
   - Compara detalle anterior contra detalle nuevo.
   - Si aumenta cantidad, descuenta solo la diferencia.
   - Si reduce cantidad, reintegra solo la diferencia.
   - Si elimina un producto, reintegra todo lo anterior.
   - Registra `SALIDA_GUIA` o `DEVOLUCION_GUIA` segun corresponda.

3. Anular guia:
   - No borra la guia.
   - Cambia estado a `ANULADA`.
   - Reintegra todos los productos.
   - Registra `DEVOLUCION_GUIA`.
   - Evita doble reintegro si la guia ya estaba anulada.

## Nota corporativa
Actualmente el sistema conserva algunos catalogos como texto en tablas operativas para no romper tu aplicacion actual. En una Fase 2 de arquitectura se recomienda migrar esos campos a IDs reales:

- `equipos.categoria_id`
- `equipos.marca_id`
- `equipos.modelo_id`
- `personal.cargo_id`
- `guias_salida.personal_id`
- `guias_salida.destino_id`

La version entregada ahora agrega validacion de catalogos desde backend y trazabilidad sin obligarte a rehacer todo el sistema.
