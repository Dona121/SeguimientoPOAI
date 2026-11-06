# -*- coding: utf-8 -*-
"""PDF y Excel de una tabla de la ficha del proyecto (CDPs, RPs u obligaciones), con el filtro de fechas.

Recibe las mismas consultas que dibuja la ficha (`ProyectoAdmin._documentos_filtrados`),
asi que el reporte es exactamente lo que el usuario tiene en pantalla: cada tabla
recortada por su propia fecha.

ReportLab y no una conversion de HTML a PDF: es Python puro, no necesita librerias del
sistema y corre igual en Windows y en el build de Railway.
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone
from django.utils.formats import date_format
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (CondPageBreak, LongTable, Paragraph, SimpleDocTemplate, Spacer,
                                TableStyle)

# Carlito: la version abierta de Calibri (Google, licencia OFL), con la misma forma y
# las mismas medidas. Calibri es de Microsoft: no esta en el servidor Linux de Railway
# y su licencia no deja subir el archivo al repositorio. Carlito si, asi que el PDF se
# ve igual en local y en produccion. Los .ttf viven en siifweb/fuentes/ con su licencia.
FUENTES = Path(__file__).resolve().parent / "fuentes"
FUENTE, FUENTE_NEGRILLA = "Carlito", "Carlito-Bold"
pdfmetrics.registerFont(TTFont(FUENTE, str(FUENTES / "Carlito-Regular.ttf")))
pdfmetrics.registerFont(TTFont(FUENTE_NEGRILLA, str(FUENTES / "Carlito-Bold.ttf")))
# Para que <b> dentro de un Paragraph use la negrilla de la misma familia
addMapping(FUENTE, 0, 0, FUENTE)
addMapping(FUENTE, 1, 0, FUENTE_NEGRILLA)
addMapping(FUENTE, 0, 1, FUENTE)
addMapping(FUENTE, 1, 1, FUENTE_NEGRILLA)

VERDE = colors.HexColor("#196B24")          # el de los encabezados del reporte financiero
GRIS_BORDE = colors.HexColor("#9CA3AF")
GRIS_TOTAL = colors.HexColor("#F3F4F6")

_base = getSampleStyleSheet()
TITULO = ParagraphStyle("titulo", parent=_base["Title"], fontName=FUENTE_NEGRILLA, fontSize=15,
                        leading=18, alignment=0, spaceAfter=2)
SUBTITULO = ParagraphStyle("subtitulo", parent=_base["Normal"], fontName=FUENTE, fontSize=10,
                           leading=13)
DATO = ParagraphStyle("dato", parent=_base["Normal"], fontName=FUENTE, fontSize=8.5, leading=11,
                      textColor=colors.HexColor("#4B5563"))
SECCION = ParagraphStyle("seccion", parent=_base["Heading2"], fontName=FUENTE_NEGRILLA,
                         fontSize=11.5, leading=14,
                         spaceBefore=12, spaceAfter=5)
CELDA = ParagraphStyle("celda", parent=_base["Normal"], fontName=FUENTE, fontSize=8.5, leading=10.5)
CELDA_DER = ParagraphStyle("celda_der", parent=CELDA, alignment=TA_RIGHT)
# Los encabezados van centrados en todas las columnas, tambien en las de valores
ENCABEZADO = ParagraphStyle("encabezado", parent=CELDA, fontName=FUENTE_NEGRILLA,
                            textColor=colors.white, alignment=TA_CENTER)
VACIO = ParagraphStyle("vacio", parent=CELDA, textColor=colors.HexColor("#6B7280"))


def _texto(valor):
    """Texto de una celda: escapado, porque Paragraph interpreta <, > y &."""
    return escape(str(valor)) if valor not in (None, "") else "—"


def _fecha(valor):
    """El mismo formato regional con que la ficha muestra las fechas."""
    return date_format(valor) if valor else "—"


def _pesos(valor):
    """1234567.8 -> 1.234.568, como las tablas de la ficha."""
    return f"{valor or 0:,.0f}".replace(",", ".")


def periodo(desde, hasta):
    if desde and hasta:
        return f"Del {_fecha(desde)} al {_fecha(hasta)}"
    if desde:
        return f"Desde el {_fecha(desde)}"
    if hasta:
        return f"Hasta el {_fecha(hasta)}"
    return "Sin filtro de fechas: toda la ejecución cargada"


def _tabla(columnas, filas, total, vacio):
    """columnas: [(titulo, ancho_cm, es_numero)]. filas: listas de textos ya formateados.

    El total va en la ultima columna numerica de cada fila de total (lista alineada a
    las columnas, con None donde no hay dato).
    """
    encabezado = [Paragraph(t, ENCABEZADO) for t, _, _ in columnas]
    cuerpo = [[Paragraph(_texto(v), CELDA_DER if num else CELDA)
               for v, (_, _, num) in zip(fila, columnas)] for fila in filas]
    if not cuerpo:
        cuerpo = [[Paragraph(vacio, VACIO)] + [""] * (len(columnas) - 1)]
    pie = [Paragraph("<b>Total</b>", CELDA)] + [
        Paragraph(f"<b>{v}</b>", CELDA_DER) if v is not None else ""
        for v in total[1:]]

    tabla = LongTable([encabezado, *cuerpo, pie], colWidths=[a * cm for _, a, _ in columnas],
                      repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), VERDE),
        # Tambien para las celdas sin Paragraph (las vacias), que si no caen en Helvetica
        ("FONTNAME", (0, 0), (-1, -1), FUENTE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        # Bordes en todas las celdas: separan las columnas y las filas
        ("GRID", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
        ("BACKGROUND", (0, -1), (-1, -1), GRIS_TOTAL),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if not filas:
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _seccion(titulo, cantidad, tabla):
    # Si no caben el titulo y unas filas, todo pasa a la pagina siguiente. No se usa
    # keepWithNext ni KeepTogether: agrupan el titulo con la tabla ENTERA y una tabla
    # larga salta completa de pagina, dejando un hueco en la anterior.
    return [CondPageBreak(3 * cm), Paragraph(f"{titulo} ({cantidad})", SECCION), tabla]


class _CanvasNumerado(canvas.Canvas):
    """Pie con 'Pagina X de Y': hay que dibujarlo cuando ya se conocen todas."""

    def __init__(self, *args, pie="", **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []
        self._pie = pie

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont(FUENTE, 7.5)
            self.setFillColor(colors.HexColor("#6B7280"))
            ancho, _ = self._pagesize
            self.drawString(1.2 * cm, 0.8 * cm, self._pie)
            self.drawRightString(ancho - 1.2 * cm, 0.8 * cm,
                                 f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


# Las columnas de cada tabla, una sola vez para el PDF y el Excel: (clave, titulo, ancho en
# el PDF en cm, tipo). La hoja carta horizontal deja 25,5 cm utiles con margenes de 1,2.
# Tipos: "numero" (vigencia y numeros de documento, sin separador de miles), "fecha",
# "money" y "texto".
COLUMNAS = {
    "cdps": [
        ("vigencia", "Vigencia", 1.6, "numero"), ("numero", "Número CDP", 2.2, "numero"),
        ("fecha", "Fecha disponibilidad", 3.6, "fecha"), ("centro", "Centro de costo", 3.6, "texto"),
        ("objeto", "Objeto", 10.5, "texto"), ("valor", "Valor disponibilidad definitiva", 4.0, "money"),
    ],
    "rps": [
        ("vigencia", "Vigencia", 1.6, "numero"), ("numero", "Número RP", 2.0, "numero"),
        ("fecha", "Fecha registro", 3.6, "fecha"), ("centro", "Centro de costo", 3.2, "texto"),
        ("acto", "Acto administrativo", 3.6, "texto"), ("objeto", "Objeto registro", 7.5, "texto"),
        ("valor", "Valor comprometido definitivo", 4.0, "money"),
    ],
    "obligaciones": [
        ("vigencia", "Vigencia", 1.3, "numero"), ("numero", "Número", 1.5, "numero"),
        ("fecha", "Fecha obligación", 2.2, "fecha"), ("centro", "Centro de costo", 2.2, "texto"),
        ("beneficiario", "Beneficiario", 2.9, "texto"), ("nit", "NIT", 1.8, "numero"),
        ("objeto", "Objeto", 3.8, "texto"), ("orden", "Tipo de orden de gasto", 2.6, "texto"),
        ("valor", "Valor obligación definitiva", 2.4, "money"), ("saldo", "Saldo", 2.4, "money"),
        ("pagado", "Pagado", 2.4, "money"),
    ],
}


def _filas_cdps(d):
    return [{"vigencia": c.vigencia, "numero": c.nro_cdp, "fecha": c.fecha_disp,
             "centro": c.centro_costo.nombre, "objeto": c.objeto_cert, "valor": c.valor_cdp}
            for c in d["cdps_proyecto"]]


def _filas_rps(d):
    return [{"vigencia": r.vigencia, "numero": r.nro_rp, "fecha": r.fecha_reg,
             "centro": r.centro_costo.nombre, "acto": r.acto_admon, "objeto": r.objeto_reg,
             "valor": r.valor_rp}
            for r in d["rps_por_proyecto"]]


def _filas_obligaciones(d):
    return [{"vigencia": o.vigencia, "numero": o.nro_obligacion, "fecha": o.fecha_obli,
             "centro": o.centro_costo.nombre,
             "beneficiario": o.beneficiario.nombre if o.beneficiario else None,
             "nit": o.beneficiario.codigo if o.beneficiario else None,
             # El objeto propio manda; el del RP es el respaldo de las cargas viejas
             "objeto": o.objeto_oblig or o.objeto_rp,
             "orden": o.tipo_orden_gasto.nombre if o.tipo_orden_gasto_id else None,
             "valor": o.valor_obli, "saldo": o.saldo_oblig, "pagado": o.pagado_obli}
            for o in d["obligaciones_por_proyecto"]]


# Cada tabla de la ficha se descarga por separado: (titulo, fecha que la recorta, filas,
# totales: columna -> llave del dict de documentos, vacio)
TABLAS = {
    "cdps": ("CDPs", "fecha de disponibilidad", _filas_cdps,
             {"valor": "cdps_proyecto_total"}, "Sin CDPs en el periodo"),
    "rps": ("RPs", "fecha de registro", _filas_rps,
            {"valor": "rps_por_proyecto_total"}, "Sin RPs en el periodo"),
    "obligaciones": ("Obligaciones", "fecha de obligación", _filas_obligaciones,
                     {"valor": "obligaciones_por_proyecto_total",
                      "saldo": "obligaciones_por_proyecto_saldo",
                      "pagado": "obligaciones_por_proyecto_pagado"},
                     "Sin obligaciones en el periodo"),
}


def _armar_pdf(tabla, d):
    _, _, filas_de, totales, vacio = TABLAS[tabla]
    columnas = COLUMNAS[tabla]
    filas = filas_de(d)

    def celda(valor, tipo):
        if tipo == "fecha":
            return _fecha(valor)
        if tipo == "money":
            return _pesos(valor)
        return valor

    return len(filas), _tabla(
        # A la derecha los numeros, menos la vigencia, que va a la izquierda como en la ficha
        [(titulo, ancho, tipo == "money" or (tipo == "numero" and clave != "vigencia"))
         for clave, titulo, ancho, tipo in columnas],
        [[celda(f[clave], tipo) for clave, _, _, tipo in columnas] for f in filas],
        [_pesos(d[totales[clave]]) if clave in totales else None for clave, _, _, _ in columnas],
        vacio)


def generar_excel(proyecto, desde, hasta, documentos, tabla):
    """El libro de UNA tabla de la ficha, con las mismas columnas y filas que su PDF."""
    from .reportes import a_excel

    titulo, criterio, filas_de, _, _ = TABLAS[tabla]
    grupo = f"{titulo} · BPIN {proyecto.bpin} · {periodo(desde, hasta)}, por {criterio}"
    columnas = [(clave, titulo_col, tipo, grupo) for clave, titulo_col, _, tipo in COLUMNAS[tabla]]

    def valor(v, tipo):
        # Los numeros de documento llegan como texto: en Excel, como numero si lo son
        if tipo == "numero" and isinstance(v, str) and v.isdigit():
            return int(v)
        return v

    filas = [{clave: valor(f[clave], tipo) for clave, _, _, tipo in COLUMNAS[tabla]}
             for f in filas_de(documentos)]
    libro = a_excel(filas, columnas, hoja=titulo, tabla=titulo,
                    anchos_col={"objeto": 60, "beneficiario": 34, "acto": 30, "centro": 26})
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def generar(proyecto, desde, hasta, documentos, tabla):
    """Bytes del PDF de UNA tabla de la ficha (una llave de TABLAS).

    `documentos` es el dict de `ProyectoAdmin._documentos_filtrados`.
    """
    titulo, criterio, _, _, _ = TABLAS[tabla]
    historia = [
        Paragraph(f"Reporte de {titulo}", TITULO),
        Paragraph(f"<b>BPIN {_texto(proyecto.bpin)}</b> · {_texto(proyecto.nombre)}", SUBTITULO),
    ]
    # La dependencia que responde por el proyecto segun el POAI (DependenciaResponsable),
    # no el centro de costo que ejecuta el gasto en SIIFWEB
    responsable = (proyecto.dependencia_responsable.nombre
                   if proyecto.dependencia_responsable_id else None)
    historia += [
        Paragraph(f"<b>Dependencia responsable:</b> {_texto(responsable)}", DATO),
        Paragraph(f"<b>Periodo:</b> {periodo(desde, hasta)}, por {criterio}.", DATO),
        Paragraph(f"Generado el {date_format(timezone.localtime(), 'DATETIME_FORMAT')}", DATO),
        Spacer(1, 4),
    ]
    cantidad, cuerpo = _armar_pdf(tabla, documentos)
    historia.extend(_seccion(titulo, cantidad, cuerpo))

    salida = BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=landscape(letter),
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.5 * cm,
                            title=f"{titulo} BPIN {proyecto.bpin}",
                            author="Seguimiento POAI")
    pie = f"{titulo} · BPIN {proyecto.bpin} · {periodo(desde, hasta)}"
    doc.build(historia, canvasmaker=lambda *a, **k: _CanvasNumerado(*a, pie=pie, **k))
    return salida.getvalue()
