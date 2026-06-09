# Manual de Usuario - Sistema de Inventario CCTV y Redes

## 1. Portada
- Nombre del sistema.
- Version.
- Empresa / area responsable.
- Fecha de emision.
- Responsable del documento.

## 2. Objetivo del sistema
Explicar que el sistema permite controlar inventario, ingresos, salidas, guias, personal, edificios, catalogos y movimientos de stock.

## 3. Alcance
Incluye:
- Equipos CCTV.
- Equipos de red.
- Consumibles.
- Personal tecnico.
- Edificios, obras o proyectos.
- Guias de salida.
- Movimientos de inventario.

No incluye en Fase 1:
- Login por usuario.
- Compras.
- Proveedores.
- Activos fijos completos.
- Dashboard gerencial avanzado.

## 4. Roles recomendados
- Administrador: configura catalogos y mantiene la base.
- Almacenero: registra ingresos, salidas y guias.
- Supervisor: revisa y aprueba guias.
- Tecnico: recibe materiales.

## 5. Modulos del sistema

### 5.1 Dashboard
Uso:
- Ver stock actual.
- Filtrar por categoria y estado.
- Detectar stock critico.

### 5.2 Ingresos
Uso:
- Registrar equipos o materiales nuevos.
- Seleccionar categoria, marca y modelo.
- Registrar SKU, serie o MAC.
- Definir cantidad y stock minimo.

Reglas:
- La cantidad debe ser mayor a cero.
- No se permite SKU duplicado cuando el campo esta informado.
- La MAC debe tener formato valido si se registra.
- Todo ingreso genera movimiento `INGRESO`.

### 5.3 Salidas directas
Uso:
- Registrar un despacho rapido sin guia formal.

Reglas:
- Solo se permite retirar productos En Stock.
- No se puede retirar mas que el stock disponible.
- Toda salida genera movimiento `SALIDA_DIRECTA`.

### 5.4 Guias de salida
Uso:
- Crear documento formal de entrega.
- Agregar multiples productos.
- Registrar solicitante, cargo, destino, proyecto y responsables.
- Exportar PDF.

Reglas:
- Una guia se crea en estado `ACTIVA`.
- Al crearla, descuenta stock.
- Al editarla, solo descuenta o reintegra diferencias.
- Al anularla, reintegra el stock y conserva el historial.

### 5.5 Movimientos
Uso:
- Auditar todo lo ocurrido con un producto.
- Ver stock anterior y stock nuevo.
- Filtrar por tipo, fecha o referencia.

### 5.6 Configuracion
Uso:
- Crear y editar catalogos.
- Categorias, marcas, modelos, cargos y edificios.

Reglas:
- No se recomienda eliminar catalogos que ya tienen uso historico.
- El sistema bloquea eliminaciones si ya existen registros asociados.

## 6. Procedimiento operativo recomendado

### Crear una guia
1. Ingresar a Nueva Guia.
2. Seleccionar solicitante.
3. Revisar cargo.
4. Seleccionar destino.
5. Indicar proyecto.
6. Completar entregado por, recibido por y aprobado por.
7. Agregar productos.
8. Validar cantidades.
9. Guardar guia.
10. Exportar PDF.

### Editar una guia
1. Abrir Listado de Guias.
2. Seleccionar Editar.
3. Cambiar productos o cantidades.
4. Guardar.
5. Revisar movimientos generados.

### Anular una guia
1. Abrir la guia.
2. Seleccionar Anular y reintegrar stock.
3. Confirmar.
4. Verificar que la guia quede como `ANULADA`.
5. Revisar los movimientos de reintegro.

## 7. Reglas de integridad de datos
- No modificar la base de datos manualmente si no es necesario.
- No borrar guias con historia; se deben anular.
- No eliminar personal, edificios o catalogos usados en registros historicos.
- El stock de `equipos` debe coincidir con los movimientos acumulados.

## 8. Recomendaciones corporativas
- Hacer backup diario de `inventario.db`.
- Definir un responsable unico de configuracion.
- Usar codigos estandar: `GS-000001`, `SD-000001`, `ING-000001`.
- Auditar movimientos semanalmente.
- Separar ambientes: desarrollo y produccion.

## 9. Anexos
- Glosario.
- Estados de equipo.
- Tipos de movimiento.
- Formato de guia PDF.
- Politica de backup.
