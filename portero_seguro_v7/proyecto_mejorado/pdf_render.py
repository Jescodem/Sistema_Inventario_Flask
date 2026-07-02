"""
pdf_render.py — Generación del PDF de guías de salida.

Separado de app.py para aislar las ~330 líneas de maquetación ReportLab
de la lógica de rutas. La función recibe los datos ya consultados
(la ruta en app.py hace las queries) y devuelve un BytesIO listo para
enviar con send_file.
"""
import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def render_guia_pdf(guia, detalle, series_por_detalle, codigo_doc):
    """Construye el PDF de una guía de salida y devuelve un io.BytesIO.

    Parámetros:
        guia: sqlite3.Row de guias_salida.
        detalle: filas de guia_detalle unidas con equipos.
        series_por_detalle: dict {guia_detalle_id: [seriales]}.
        codigo_doc: código legible de la guía (ej. GS-000001).
    """
    # ── Paleta de marca ─────────────────────────────────────────────────────
    C_RAIL    = colors.HexColor('#11151A')   # sidebar oscuro
    C_AMBER   = colors.HexColor('#E33F10')   # naranja exacto del logo
    C_ROW_ALT = colors.HexColor('#F7F8FA')   # fila alterna (muy sutil)
    C_RULE    = colors.HexColor('#E2E6EB')   # líneas divisoras
    C_LABEL   = colors.HexColor('#6B7480')   # texto etiqueta gris
    C_WHITE   = colors.white
    C_BLACK   = colors.HexColor('#15191E')

    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import HRFlowable, KeepTogether, PageBreak
    from reportlab.platypus.flowables import Flowable

    # ── Flowable: membrete (logo + datos de la guía) ────────────────────────
    class Membrete(Flowable):
        def __init__(self, codigo, estado, ancho):
            Flowable.__init__(self)
            self.codigo  = codigo
            self.estado  = estado
            self.ancho   = ancho
            self.height  = 2.4 * cm

        def draw(self):
            c = self.canv
            w = self.ancho
            h = self.height

            # Fondo rail oscuro para la banda del logo
            c.setFillColor(C_RAIL)
            c.rect(0, h - 1.45*cm, w * 0.4, 1.45*cm, fill=1, stroke=0)

            # Logo real de Portero Seguro
            LOGO_PATH = os.path.join(BASE_DIR, 'static', 'img', 'logo.png')
            if os.path.exists(LOGO_PATH):
                from reportlab.lib.utils import ImageReader
                logo_img = ImageReader(LOGO_PATH)
                c.drawImage(logo_img, 0.3*cm, h - 1.35*cm,
                            width=2.8*cm, height=1.1*cm,
                            mask='auto', preserveAspectRatio=True)
            else:
                c.setFillColor(C_AMBER)
                c.setStrokeColor(C_AMBER)
                c.roundRect(0.35*cm, h - 1.18*cm, 0.72*cm, 0.72*cm, 0.1*cm, fill=0, stroke=1)
                c.setFont('Helvetica-Bold', 7.5)
                c.setFillColor(C_AMBER)
                c.drawCentredString(0.71*cm, h - 0.82*cm, 'PS')
                c.setFont('Helvetica-Bold', 9.5)
                c.setFillColor(C_WHITE)
                c.drawString(1.22*cm, h - 0.78*cm, 'Portero Seguro')
                c.setFont('Helvetica', 6)
                c.setFillColor(colors.HexColor('#8B93A1'))
                c.drawString(1.22*cm, h - 1.1*cm, 'CONTROL DE ACTIVOS')

            # Línea ámbar vertical separadora
            c.setStrokeColor(C_AMBER)
            c.setLineWidth(1.5)
            c.line(w * 0.4 + 0.3*cm, h - 1.45*cm, w * 0.4 + 0.3*cm, h)

            # Título del documento
            c.setFont('Helvetica-Bold', 13)
            c.setFillColor(C_BLACK)
            c.drawString(w * 0.4 + 0.9*cm, h - 0.72*cm, 'GUÍA DE SALIDA DE ALMACÉN')
            c.setFont('Helvetica', 7.5)
            c.setFillColor(C_LABEL)
            c.drawString(w * 0.4 + 0.9*cm, h - 1.1*cm, 'Documento de despacho y trazabilidad de activos')

            # Código + estado (esquina superior derecha)
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(C_BLACK)
            c.drawRightString(w, h - 0.52*cm, self.codigo)
            estado_color = {
                'activa': colors.HexColor('#198754'),
                'anulada': colors.HexColor('#DC2626'),
            }.get((self.estado or '').lower(), C_LABEL)
            c.setFont('Helvetica', 7)
            c.setFillColor(estado_color)
            c.drawRightString(w, h - 0.9*cm, f'Estado: {(self.estado or "").upper()}')

            # Línea ámbar inferior
            c.setStrokeColor(C_AMBER)
            c.setLineWidth(1.5)
            c.line(0, 0, w, 0)

    # ── Estilos tipográficos ─────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    st_label = ParagraphStyle('Label',
        fontName='Helvetica-Bold', fontSize=7, textColor=C_LABEL,
        leading=9, spaceAfter=0)
    st_value = ParagraphStyle('Value',
        fontName='Helvetica', fontSize=8.5, textColor=C_BLACK,
        leading=11, spaceAfter=0)
    st_th = ParagraphStyle('TH',
        fontName='Helvetica-Bold', fontSize=7.5, textColor=C_WHITE,
        leading=10, alignment=TA_LEFT)
    st_td = ParagraphStyle('TD',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=11)
    st_td_center = ParagraphStyle('TDC',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=11, alignment=TA_CENTER)
    st_mono = ParagraphStyle('Mono',
        fontName='Courier', fontSize=7.5, textColor=C_BLACK,
        leading=10)
    st_serial = ParagraphStyle('Serial',
        fontName='Courier', fontSize=7, textColor=C_LABEL,
        leading=9)
    st_obs = ParagraphStyle('Obs',
        fontName='Helvetica', fontSize=8, textColor=C_BLACK,
        leading=12, leftIndent=0)
    st_section = ParagraphStyle('Section',
        fontName='Helvetica-Bold', fontSize=7.5, textColor=C_LABEL,
        leading=10, spaceBefore=6, spaceAfter=3,
        borderPad=0)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def campo(label, valor, ancho_label=3*cm, ancho_valor=5.2*cm):
        return Table(
            [[Paragraph(label.upper(), st_label), Paragraph(str(valor or '—'), st_value)]],
            colWidths=[ancho_label, ancho_valor]
        )

    def hrule(color=C_RULE, grosor=0.5):
        return HRFlowable(width='100%', thickness=grosor, color=color,
                          spaceAfter=6, spaceBefore=6)

    # ── Página con numeración ─────────────────────────────────────────────────

    def build_page(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(C_LABEL)
        canvas.drawRightString(
            doc.width + doc.leftMargin,
            0.65 * cm,
            f'Página {doc.page}  ·  {codigo_doc}  ·  generado por Portero Seguro'
        )
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 0.85*cm, doc.width + doc.leftMargin, 0.85*cm)
        canvas.restoreState()

    # ── Documento ─────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    ANCHO_UTIL = A4[0] - 3*cm   # márgenes 1.5cm cada lado
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.2*cm, bottomMargin=1.6*cm
    )

    E = []   # elementos

    # Membrete
    E.append(Membrete(codigo_doc, guia['estado'] or '', ANCHO_UTIL))
    E.append(Spacer(1, 0.45*cm))

    # ── Bloque de metadatos (2 columnas) ─────────────────────────────────────
    meta_izq = [
        [Paragraph('SOLICITANTE', st_label), Paragraph(str(guia['personal'] or '—'), st_value)],
        [Paragraph('CARGO',       st_label), Paragraph(str(guia['cargo'] or '—'), st_value)],
        [Paragraph('DESTINO',     st_label), Paragraph(str(guia['destino'] or '—'), st_value)],
        [Paragraph('PROYECTO',    st_label), Paragraph(str(guia['proyecto'] or '—'), st_value)],
    ]
    meta_der = [
        [Paragraph('FECHA',        st_label), Paragraph(str(guia['fecha'] or '—'), st_value)],
        [Paragraph('ENTREGADO POR',st_label), Paragraph(str(guia['entregado_por'] or '—'), st_value)],
        [Paragraph('RECIBIDO POR', st_label), Paragraph(str(guia['recibido_por'] or '—'), st_value)],
        [Paragraph('APROBADO POR', st_label), Paragraph(str(guia['aprobado_por'] or '—'), st_value)],
    ]
    COL_L = 2.5*cm
    COL_V = ANCHO_UTIL / 2 - COL_L - 0.4*cm

    t_izq = Table(meta_izq, colWidths=[COL_L, COL_V])
    t_der = Table(meta_der, colWidths=[COL_L, COL_V])
    for t in (t_izq, t_der):
        t.setStyle(TableStyle([
            ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_WHITE, C_ROW_ALT]),
            ('TOPPADDING',  (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))

    meta_wrapper = Table(
        [[t_izq, Spacer(0.8*cm, 1), t_der]],
        colWidths=[ANCHO_UTIL/2 - 0.4*cm, 0.8*cm, ANCHO_UTIL/2 - 0.4*cm]
    )
    meta_wrapper.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    E.append(meta_wrapper)
    E.append(Spacer(1, 0.4*cm))
    E.append(hrule(C_RULE))

    # ── Tabla de productos ────────────────────────────────────────────────────
    E.append(Paragraph('DETALLE DE PRODUCTOS DESPACHADOS', st_section))
    E.append(Spacer(1, 0.15*cm))

    COL_ITEM = 0.8*cm
    COL_CANT = 1.6*cm
    COL_MARCA = 2.8*cm
    COL_DESC = ANCHO_UTIL - COL_ITEM - COL_CANT - COL_MARCA - 3.8*cm
    COL_SKU  = 3.8*cm

    cabecera = [[
        Paragraph('N°',         st_th),
        Paragraph('CANT.',      st_th),
        Paragraph('MARCA',      st_th),
        Paragraph('DESCRIPCIÓN',st_th),
        Paragraph('SKU / REF.', st_th),
    ]]
    filas_prod = []
    for idx, item in enumerate(detalle, start=1):
        series_ids = series_por_detalle.get(item['guia_detalle_id'], [])
        sku_texto = item['sku'] or '—'
        filas_prod.append([
            Paragraph(str(idx), st_td_center),
            Paragraph(str(item['cantidad']), st_td_center),
            Paragraph(str(item['marca'] or '—'), st_td),
            Paragraph(str(item['descripcion'] or '—'), st_td),
            Paragraph(sku_texto, st_mono),
        ])

    tabla_prods = Table(
        cabecera + filas_prod,
        colWidths=[COL_ITEM, COL_CANT, COL_MARCA, COL_DESC, COL_SKU],
        repeatRows=1
    )
    tabla_prods.setStyle(TableStyle([
        # Cabecera
        ('BACKGROUND',   (0, 0), (-1, 0), C_RAIL),
        ('TOPPADDING',   (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING',(0, 0), (-1, 0), 6),
        ('LEFTPADDING',  (0, 0), (-1, 0), 6),
        # Filas alternas
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [C_WHITE, C_ROW_ALT]),
        ('TOPPADDING',   (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 5),
        ('LEFTPADDING',  (0, 1), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # Bordes
        ('LINEBELOW',    (0, 0), (-1, 0), 0.8, C_AMBER),
        ('LINEBELOW',    (0, 1), (-1, -1), 0.3, C_RULE),
        ('BOX',          (0, 0), (-1, -1), 0.4, C_RULE),
        # Alineación columnas numéricas
        ('ALIGN',        (0, 0), (1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    E.append(tabla_prods)

    # ── Series individuales (solo si hay equipos serializados) ────────────────
    filas_series = []
    for item in detalle:
        ids = series_por_detalle.get(item['guia_detalle_id'], [])
        if ids:
            filas_series.append((item['descripcion'], item['marca'], ids))

    if filas_series:
        E.append(Spacer(1, 0.4*cm))
        E.append(hrule(C_RULE))
        E.append(Paragraph('NÚMEROS DE SERIE POR EQUIPO', st_section))
        E.append(Spacer(1, 0.15*cm))

        for desc, marca, ids in filas_series:
            series_texto = '   ·   '.join(str(s) for s in ids)
            bloque = Table([
                [Paragraph(f'{marca} – {desc}', st_label),
                 Paragraph(series_texto, st_serial)]
            ], colWidths=[ANCHO_UTIL * 0.35, ANCHO_UTIL * 0.65])
            bloque.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING',   (0, 0), (-1, -1), 5),
                ('LINEBELOW',     (0, 0), (-1, -1), 0.25, C_RULE),
            ]))
            E.append(bloque)

    # ── Observaciones ─────────────────────────────────────────────────────────
    obs = guia['observaciones'] or ''
    if obs:
        E.append(Spacer(1, 0.4*cm))
        E.append(hrule(C_RULE))
        E.append(Paragraph('OBSERVACIONES', st_section))
        E.append(Paragraph(obs, st_obs))

    # ── Firmas ────────────────────────────────────────────────────────────────
    E.append(Spacer(1, 1*cm))
    E.append(hrule(C_RULE))

    FIRMA_W = ANCHO_UTIL / 3 - 0.4*cm
    FIRMA_GAP = 0.6*cm

    firmas_data = [
        ['Entregado por', 'Recibido por', 'Aprobado por'],
        [guia['entregado_por'] or '', guia['recibido_por'] or '', guia['aprobado_por'] or ''],
    ]
    firma_table = Table(
        firmas_data,
        colWidths=[FIRMA_W, FIRMA_W, FIRMA_W],
        rowHeights=[1.8*cm, 0.55*cm],
        spaceAfter=0
    )
    firma_table.setStyle(TableStyle([
        # Etiquetas superiores centradas
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, 0),  'BOTTOM'),
        ('VALIGN',       (0, 1), (-1, 1),  'TOP'),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0),  8),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  C_LABEL),
        # Línea de firma en el borde inferior de la primera fila
        ('LINEBELOW',    (0, 0), (-1, 0),  0.8, C_BLACK),
        # Nombres bajo la línea
        ('FONTNAME',     (0, 1), (-1, 1),  'Helvetica'),
        ('FONTSIZE',     (0, 1), (-1, 1),  7.5),
        ('TEXTCOLOR',    (0, 1), (-1, 1),  C_BLACK),
        # Separación entre columnas de firma
        ('RIGHTPADDING', (0, 0), (1, -1),  FIRMA_GAP),
        ('LEFTPADDING',  (1, 0), (-1, -1), FIRMA_GAP),
    ]))
    E.append(firma_table)

    # ── Build ──────────────────────────────────────────────────────────────────
    doc.build(E, onFirstPage=build_page, onLaterPages=build_page)
    buffer.seek(0)
    return buffer
