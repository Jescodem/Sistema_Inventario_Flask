# Instalacion - Fase 1 Corporativa

## Archivos incluidos
- `app.py`: aplicacion Flask mejorada.
- `templates/`: vistas HTML.
- `inventario.db`: base SQLite migrada desde el archivo entregado.
- `docs/MODELO_ER_FASE1.md`: modelo entidad relacion.
- `docs/MANUAL_USUARIO_ESTRUCTURA.md`: estructura de manual de usuario.

## Como ejecutar

```bash
pip install flask reportlab
python app.py
```

Abrir:

```text
http://127.0.0.1:5000
```

## Recomendacion antes de reemplazar
Hacer copia de seguridad de tu base actual:

```bash
copy inventario.db inventario_backup.db
```

o en Linux/Mac:

```bash
cp inventario.db inventario_backup.db
```

## Cambios principales
- Validacion backend de ingresos, salidas y guias.
- Guia con campos corporativos.
- PDF de guia mejorado.
- Movimientos auditables.
- Anulacion de guia en vez de borrado.
- Reintegro automatico de stock.
- Proteccion contra doble reintegro.
- Bloqueo de eliminacion de catalogos usados.
