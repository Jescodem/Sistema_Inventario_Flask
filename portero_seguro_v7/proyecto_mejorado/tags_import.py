"""
tags_import.py — Importación de tags/tarjetas de acceso desde Excel.

El Excel de campo llega "sucio": encabezados que no están en la fila 1,
códigos con comillas y saltos de línea pegados, filas separadoras con
00000000, columnas extra sin nombre (el número decimal de la tarjeta,
notas como "se cambio" o "Regalo") y bloques completos repetidos porque
se consolidaron varios archivos con los mismos datos.

Este módulo normaliza cada fila y deduplica con la clave
(edificio, departamento, residente, código) ignorando mayúsculas y
espacios: si la misma persona con el mismo código aparece otra vez
(aunque tenga otra fecha), se considera duplicado y NO se inserta.

Lo usan la ruta /tags/importar de app.py y los tests.
"""
import re
from datetime import datetime, date

# Sinónimos aceptados para cada campo en la fila de encabezados.
ENCABEZADOS = {
    'edificio': ('EDIFICIO', 'EDIFICIOS'),
    'departamento': ('DEPARTAMENTO', 'DPTO', 'DPT', 'DEPA', 'DEPTO'),
    'residente': ('RESIDENTE', 'NOMBRE', 'PROPIETARIO', 'USUARIO'),
    'codigo': ('CODIGO', 'COD', 'TAG', 'HEX'),
    'fecha': ('FECHA DE CREACION', 'FECHA', 'FECHA CREACION'),
    'tipo': ('TIPO',),
    'numero': ('NUMERO', 'NRO', 'DEC', 'DECIMAL', 'N TARJETA'),
}

_RE_SOLO_DIGITOS = re.compile(r'^\d{6,}$')


def _texto(valor):
    """Convierte una celda a texto limpio (sin comillas ni saltos de línea)."""
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).replace('"', ' ').replace('\n', ' ').replace('\t', ' ')
    return re.sub(r'\s+', ' ', texto).strip()


def _sin_acentos(texto):
    tabla = str.maketrans('ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun')
    return texto.translate(tabla)


def normalizar_codigo(valor):
    return _texto(valor).replace(' ', '').upper()


def es_codigo_valido(codigo):
    """Descarta vacíos, filas separadoras (00000000) y errores de Excel (#...)."""
    if not codigo or codigo.startswith('#'):
        return False
    return set(codigo) != {'0'}


def parse_fecha(valor):
    """Normaliza a ISO (YYYY-MM-DD) para que el orden por fecha funcione.

    Si la fecha no se puede interpretar (ej. '20/25/2026' del Excel),
    se conserva el texto original para no perder información.
    """
    if isinstance(valor, datetime):
        return valor.strftime('%Y-%m-%d')
    if isinstance(valor, date):
        return valor.strftime('%Y-%m-%d')
    texto = _texto(valor)
    if not texto:
        return ''
    for formato in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return datetime.strptime(texto, formato).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return texto


def normalizar_tipo(valor):
    """Unifica las variantes del mismo tipo escritas distinto.

    En los Excel de campo el mismo concepto aparece con mayúsculas y
    palabras cambiadas: "Tag pagado" / "Tag Pagado", "Tarjeta blanca" /
    "Tarjeta Blanca", "Tag Regalo" / "Tag de regalo"... Aquí todas
    colapsan a un único nombre canónico para que el filtro por tipo
    muestre una sola opción por concepto.
    """
    texto = _texto(valor)
    if not texto:
        return ''
    plano = _sin_acentos(texto).casefold()
    palabras = set(re.sub(r'[^a-z0-9 ]', ' ', plano).split())

    if 'tag' in palabras or 'tarjeta' in palabras:
        base = 'Tag' if 'tag' in palabras else 'Tarjeta'
        if 'regalo' in palabras:
            return f'{base} de Regalo'
        if 'migrado' in palabras or 'migrada' in palabras:
            return f'{base} Migrado'
        if 'pagado' in palabras or 'pagada' in palabras:
            return f'{base} Pagado'
        if 'blanca' in palabras or 'blanco' in palabras:
            return f'{base} Blanca'
        if 'numeros' in palabras or 'numero' in palabras:
            return f'{base} con Números'
        if palabras == {'tag'} or palabras == {'tarjeta'}:
            return base

    # Tipo no reconocido: al menos unifica las mayúsculas (Título,
    # con los conectores en minúscula) para que "x y" == "X Y".
    menores = {'de', 'con', 'y', 'a', 'del', 'la', 'el'}
    resultado = []
    for i, palabra in enumerate(texto.split()):
        pl = palabra.lower()
        resultado.append(pl if (i > 0 and pl in menores) else pl.capitalize())
    return ' '.join(resultado)


def clave_dedupe(registro):
    return (
        _sin_acentos(registro['edificio']).casefold(),
        _sin_acentos(registro['departamento']).casefold(),
        _sin_acentos(registro['residente']).casefold(),
        registro['codigo'].upper(),
    )


def _detectar_encabezado(fila):
    """Si la fila contiene EDIFICIO y CÓDIGO/TAG, devuelve {campo: índice}."""
    mapa = {}
    for idx, celda in enumerate(fila):
        nombre = _sin_acentos(_texto(celda)).upper()
        if not nombre:
            continue
        for campo, sinonimos in ENCABEZADOS.items():
            if campo not in mapa and nombre in sinonimos:
                mapa[campo] = idx
                break
    if 'edificio' in mapa and 'codigo' in mapa:
        return mapa
    return None


def _fila_a_registro(fila, mapa):
    def celda(campo):
        idx = mapa.get(campo)
        return fila[idx] if idx is not None and idx < len(fila) else None

    registro = {
        'edificio': _texto(celda('edificio')),
        'departamento': _texto(celda('departamento')),
        'residente': _texto(celda('residente')),
        'codigo': normalizar_codigo(celda('codigo')),
        'fecha': parse_fecha(celda('fecha')),
        'tipo': normalizar_tipo(celda('tipo')),
        'numero': _texto(celda('numero')) if 'numero' in mapa else '',
        'observaciones': '',
    }

    # Columnas extra sin encabezado A LA DERECHA de las columnas conocidas:
    # el número decimal de la tarjeta y/o notas sueltas como "se cambio" o
    # "Regalo". Lo que está a la izquierda (ej. el número de fila) se ignora.
    umbral = max(mapa.values())
    extras = []
    for idx, valor in enumerate(fila):
        if idx <= umbral or idx in mapa.values():
            continue
        texto = _texto(valor)
        if texto:
            extras.append(texto)
    for extra in extras:
        if not registro['numero'] and _RE_SOLO_DIGITOS.match(extra.replace(' ', '')):
            registro['numero'] = extra.replace(' ', '')
        elif extra != registro['numero'] and not _RE_SOLO_DIGITOS.match(extra.replace(' ', '')):
            registro['observaciones'] = (
                (registro['observaciones'] + ' · ' if registro['observaciones'] else '') + extra
            )
    return registro


def extraer_registros(workbook):
    """Recorre todas las hojas del libro y devuelve la lista de registros.

    Ignora todo lo anterior a la fila de encabezados y las filas sin
    código utilizable. Lanza ValueError si ninguna hoja tiene encabezados
    reconocibles (EDIFICIO + CÓDIGO).
    """
    registros = []
    ignoradas = 0
    hubo_encabezado = False

    for hoja in workbook.worksheets:
        mapa = None
        # La primera columna numerada (1, 2, 3...) no interesa: los campos
        # se toman solo de las columnas mapeadas por encabezado.
        for fila in hoja.iter_rows(values_only=True):
            if mapa is None:
                mapa = _detectar_encabezado(fila)
                if mapa:
                    hubo_encabezado = True
                continue
            registro = _fila_a_registro(fila, mapa)
            if not es_codigo_valido(registro['codigo']):
                if any(v for v in registro.values()):
                    ignoradas += 1
                continue
            registros.append(registro)

    if not hubo_encabezado:
        raise ValueError(
            'No se encontraron encabezados reconocibles (EDIFICIO y CÓDIGO/TAG) '
            'en ninguna hoja del archivo.'
        )
    return registros, ignoradas


def importar_en_bd(conn, registros):
    """Inserta los registros que no existan aún. Devuelve (nuevos, duplicados).

    La deduplicación es doble: contra lo que ya hay en la base (permite
    re-importar el mismo Excel o los 3 archivos consolidados sin duplicar)
    y dentro del propio archivo (bloques repetidos).
    """
    existentes = set()
    for row in conn.execute(
        'SELECT edificio, departamento, residente, codigo FROM tags_acceso'
    ).fetchall():
        existentes.add(clave_dedupe({
            'edificio': row['edificio'] or '',
            'departamento': row['departamento'] or '',
            'residente': row['residente'] or '',
            'codigo': row['codigo'] or '',
        }))

    nuevos = 0
    duplicados = 0
    for registro in registros:
        clave = clave_dedupe(registro)
        if clave in existentes:
            duplicados += 1
            continue
        existentes.add(clave)
        conn.execute('''
            INSERT INTO tags_acceso
                (edificio, departamento, residente, codigo, numero, tipo, fecha, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            registro['edificio'], registro['departamento'], registro['residente'],
            registro['codigo'], registro['numero'], registro['tipo'],
            registro['fecha'], registro['observaciones'],
        ))
        nuevos += 1
    return nuevos, duplicados


def depurar_duplicados(conn):
    """Elimina duplicados ya guardados en la tabla (conserva el más antiguo)."""
    vistos = {}
    eliminar = []
    for row in conn.execute('''
        SELECT id, edificio, departamento, residente, codigo
        FROM tags_acceso ORDER BY id
    ''').fetchall():
        clave = clave_dedupe({
            'edificio': row['edificio'] or '',
            'departamento': row['departamento'] or '',
            'residente': row['residente'] or '',
            'codigo': row['codigo'] or '',
        })
        if clave in vistos:
            eliminar.append(row['id'])
        else:
            vistos[clave] = row['id']
    for id_ in eliminar:
        conn.execute('DELETE FROM tags_acceso WHERE id = ?', (id_,))
    return len(eliminar)
