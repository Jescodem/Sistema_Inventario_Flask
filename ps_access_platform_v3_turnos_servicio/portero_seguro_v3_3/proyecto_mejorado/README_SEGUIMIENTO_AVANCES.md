# Parche Seguimiento + Avances / Notas

Este parche agrega dos módulos nuevos sin reemplazar tu inventario.db:

## 1. Seguimiento
Ruta: `/seguimiento`

Sirve para registrar equipos dejados temporalmente en edificios o clientes:
- módems de respaldo
- UPS
- switches
- cámaras
- NVR/DVR
- cualquier equipo no retornado aún

Campos principales:
- equipo del inventario o registro manual
- serial
- edificio
- ubicación exacta
- fecha en que fue dejado
- dejado por
- solicitado por
- motivo
- estado
- observaciones

Estados sugeridos:
- EN_SEGUIMIENTO
- RETIRADO
- INSTALADO
- DEVUELTO
- BAJA

## 2. Avances / Notas
Ruta: `/avances`

Sirve para registrar actividades diarias:
- actividad realizada
- personal responsable
- solicitado por
- edificio
- proyecto
- estado
- detalles
- observaciones

Estados sugeridos:
- PENDIENTE
- EN_PROCESO
- TERMINADO
- OBSERVADO
- CANCELADO

## Instalación

1. Haz backup de tu base:

```bat
copy inventario.db inventario_backup_seguimiento_avances.db
```

2. Copia los archivos del parche sobre tu proyecto:

```text
app.py
migrar_fase1.py
templates/base.html
templates/seguimiento.html
templates/avances.html
```

3. Ejecuta la migración:

```bat
python migrar_fase1.py
```

4. Levanta el sistema:

```bat
python app.py
```

5. En la barra lateral verás:
- Seguimiento
- Avances / Notas

## Tablas nuevas

```sql
seguimiento_equipos
avances_actividades
```

No se modifican ni eliminan tus registros actuales.
