# Parche: stock en editar guia y catalogos relacionados

Este paquete corrige dos puntos del sistema:

1. En `Editar Guia`, el producto ya retirado ahora muestra su **disponible maximo**:

```text
stock actual en inventario + cantidad que ya estaba en la guia
```

Ejemplo:

```text
Camara A tenia 1 unidad.
Se retiro 1 en la guia.
Stock actual queda 0.
Al editar la guia, disponible maximo se muestra como 1, no como 0.
```

2. Los catalogos ahora quedan relacionados:

```text
Categoria -> Marca -> Modelo / Descripcion
```

Esto permite que al registrar ingresos o agregar productos a una guia:

- al seleccionar categoria, solo se muestren marcas asociadas;
- al seleccionar marca, solo se muestren modelos de esa categoria y marca;
- al buscar un modelo, el sistema pueda completar categoria y marca automaticamente.

## Archivos modificados

```text
app.py
migrar_fase1.py
templates/ingresos.html
templates/guias.html
templates/editar_guia.html
templates/configuracion.html
```

## Instalacion recomendada

1. Haz backup de tu proyecto y base actual.

```bash
copy inventario.db inventario_backup_catalogos.db
```

2. Copia los archivos del parche sobre tu proyecto.

3. Ejecuta la migracion:

```bash
python migrar_fase1.py
```

4. Levanta el sistema:

```bash
python app.py
```

## Prueba rapida

1. Entra a Configuracion.
2. Verifica que existan relaciones como:

```text
CCTV -> Hikvision
Control de Accesos -> Akuvox
Redes -> Cisco / Fortinet / Aruba
```

3. Entra a Ingresos.
4. Selecciona `CCTV` y valida que solo aparezcan marcas asociadas a CCTV.
5. Selecciona una marca y valida que solo aparezcan sus modelos.
6. Crea un equipo con stock 1.
7. Crea una guia retirando 1.
8. Edita la guia y verifica que el producto aparezca con disponible maximo 1 aunque el stock actual sea 0.

## Nota

Si tienes modelos antiguos mal clasificados, puedes ir a Configuracion > Modelos, editar el modelo y asignarlo a la categoria y marca correcta.
