# Guía de uso y pruebas - Parche operativo Portero Seguro

Este parche corrige y agrega lo siguiente:

1. Edición de productos existentes desde el Dashboard.
2. Ingreso serializado sin duplicar producto base.
3. Historial de salidas con botón de ojo para ver observaciones/detalle completo.
4. Guías con responsables seleccionados desde Personal: entregado por, recibido por y aprobado por.
5. Seguimiento separado del inventario para herramientas/equipos temporales.
6. Avances y notas con listas desplegables de personal y edificios.
7. Edificios con ubicación/dirección y enlace de Google Maps.
8. Menú lateral agrupado en Operación.

## Instalación

1. Hacer backup de la base:

```bat
copy inventario.db inventario_backup_antes_parche_operativo.db
```

2. Copiar los archivos del parche sobre tu proyecto.

3. Ejecutar migración:

```bat
python migrar_fase1.py
```

4. Levantar Flask:

```bat
python app.py
```

5. Recargar navegador con `CTRL + F5`.

## Uso: editar producto en stock

En Dashboard, cada producto activo tiene botón **Editar**.

Permite modificar:

- Categoría.
- Marca.
- Modelo / descripción.
- SKU referencia.
- MAC referencia.
- Stock mínimo.
- Estado.
- Observaciones.

No permite modificar cantidad manualmente. Para aumentar stock usa **Ingresos** o **Ingreso Series**. Para reducir stock usa **Guías**, **Salidas** o **Dar baja**.

## Uso: ingreso por series

Ir a **Ingreso Series**.

1. Seleccionar categoría.
2. Seleccionar marca.
3. Seleccionar modelo.
4. Indicar cantidad esperada.
5. Pegar una serie por línea.

Formatos soportados:

```text
SERIAL001
SERIAL002
SERIAL003
```

O con MAC:

```text
SERIAL001,AA:BB:CC:DD:EE:01
SERIAL002,AA:BB:CC:DD:EE:02
```

Reglas:

- La cantidad esperada debe coincidir con la cantidad de líneas.
- No se aceptan series duplicadas.
- No se aceptan MAC con formato inválido.
- Si ya existe el producto base por categoría + marca + modelo, se reutiliza y no se crea otro producto duplicado.

## Uso: guías con responsables

En Nueva Guía y Editar Guía, los campos:

- Entregado por.
- Recibido por.
- Aprobado por.

son listas desplegables tomadas desde Personal.

## Uso: seguimiento

El nuevo seguimiento ya no depende de inventario.

Sirve para:

- Taladros.
- Herramientas.
- Módem temporal.
- UPS temporal.
- Equipos prestados no inventariados.

Campos:

- Herramienta / equipo.
- Personal que se lo llevó.
- Fecha.
- Edificio.
- Entregado por.
- Estado.
- Comentarios / observaciones.

## Uso: avances y notas

En Avances / Notas, los campos de personal, solicitado por y edificio ahora son seleccionables desde las tablas del sistema.

También hay botón de ojo para ver todos los detalles de una actividad.

## Uso: edificios

En Configuración > Edificios / Obras ahora puedes guardar:

- Nombre del edificio.
- Ubicación o dirección.
- Link de Google Maps.

## Pruebas recomendadas

1. Editar un producto desde Dashboard y verificar que no duplique.
2. Ingresar 3 series con MAC y verificar que el stock suba.
3. Crear guía y seleccionar responsables desde lista.
4. Registrar salida directa con observaciones y revisar el ojo en historial.
5. Registrar herramienta en Seguimiento sin usar Inventario.
6. Registrar avance usando select de personal y edificio.
7. Crear edificio con link de Maps y editarlo.
