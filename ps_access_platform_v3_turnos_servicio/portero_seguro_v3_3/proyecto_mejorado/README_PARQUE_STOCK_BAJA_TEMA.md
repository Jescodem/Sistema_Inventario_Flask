# Parche Portero Seguro: stock 0, bajas y tema naranja

## Cambios incluidos

1. **Estado Sin Stock**
   - Si un producto queda con `cantidad = 0`, deja de mostrarse como `En Stock`.
   - El sistema normaliza automáticamente:
     - `cantidad > 0` + estado operativo -> `En Stock`
     - `cantidad <= 0` + estado operativo -> `Sin Stock`
   - No modifica estados especiales como `Baja`, `Instalado`, `En Revision` o `En Transito`.

2. **Botón Dar baja en inventario**
   - Se agrega en el Dashboard.
   - No borra físicamente el producto.
   - Cambia estado a `Baja`, pone cantidad en `0` y registra movimiento `BAJA`.
   - Si el producto tiene guías activas, bloquea la baja.
   - Si es serializado y tiene series entregadas o instaladas, bloquea la baja hasta regularizarlas.

3. **Tema visual naranja cálido Portero Seguro Perú**
   - Sidebar cálido naranja/marrón.
   - Botones primarios naranja.
   - Fondo suave cálido.
   - Títulos y tarjetas adaptados al tono corporativo.

4. **Salida directa protegida**
   - Los productos serializados ya no deben salir por Salidas directas.
   - Deben salir por Guías para seleccionar los seriales exactos.

## Archivos del parche

- `app.py`
- `migrar_fase1.py`
- `templates/base.html`
- `templates/index.html`

## Instalación

1. Haz backup:

```bat
copy inventario.db inventario_backup_antes_parche_portero.db
```

2. Copia los archivos del parche sobre tu proyecto.

3. Ejecuta:

```bat
python migrar_fase1.py
python app.py
```

4. Recarga con `CTRL + F5`.

## Prueba rápida

1. Crea un producto con cantidad 1.
2. Sácalo por guía o salida directa.
3. Verifica que cantidad quede 0.
4. En Dashboard debe aparecer `Sin Stock`, no `En Stock`.
5. Prueba el botón `Dar baja` con un producto de prueba.
