# Parche: jerarquia Categoria -> Marca -> Modelo

Este parche corrige el filtrado de listbox y agrega administracion real de relaciones.

## Problema resuelto

Antes, al seleccionar una categoria como CCTV, el formulario podia seguir mostrando todas las marcas si la base tenia relaciones mal cargadas o si el formulario usaba datos estaticos.

Ahora los formularios consultan la base por API:

- `/api/marcas?categoria=CCTV`
- `/api/modelos?categoria=CCTV&marca=Hikvision`
- `/api/productos?categoria=CCTV&marca=Hikvision&modelo=...`

## Archivos modificados

- `app.py`
- `templates/configuracion.html`
- `templates/ingresos.html`
- `templates/guias.html`
- `templates/editar_guia.html`
- `migrar_fase1.py`

## Nueva administracion en Configuracion

En `/configuracion` ahora existe una seccion completa:

1. Categorias
2. Relaciones Categoria -> Marca
3. Modelos / Descripciones por categoria y marca

Desde ahi puedes:

- Asociar una marca a una categoria.
- Eliminar relaciones incorrectas si no tienen modelos ni productos asociados.
- Crear modelos solo dentro de una categoria y marca.
- Filtrar la tabla de modelos por categoria y marca.

## Importante despues de instalar

1. Ejecuta:

```bash
python migrar_fase1.py
```

2. Entra a Configuracion.
3. Haz clic en **Limpiar relaciones vacias** para borrar relaciones antiguas sin uso.
4. Verifica que tus relaciones queden asi, por ejemplo:

```text
CCTV -> Hikvision
CCTV -> Dahua
Control de Accesos -> Akuvox
Redes -> Cisco
Redes -> Fortinet
Redes -> Aruba
Consumibles -> Generico
```

5. Crea modelos dentro de su relacion correcta.

Ejemplo:

```text
Categoria: CCTV
Marca: Hikvision
Modelo: DS-2CD2143G2-I
```

## Flujo esperado en Ingresos

1. Seleccionas Categoria: CCTV.
2. Marca muestra solo Hikvision / Dahua.
3. Seleccionas Marca: Hikvision.
4. Modelo muestra solo modelos Hikvision dentro de CCTV.

## Flujo esperado en Guias

1. Seleccionas Categoria.
2. Marca se filtra.
3. Modelo se filtra.
4. Producto disponible se filtra segun stock real.

## Nota

Si una marca aparece en una categoria donde no corresponde, entra a Configuracion y elimina esa relacion. Si no permite eliminarla, es porque ya tiene modelos o productos asociados; primero debes corregir esos modelos o productos.
