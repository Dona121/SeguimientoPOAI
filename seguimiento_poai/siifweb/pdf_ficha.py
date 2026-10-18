# -*- coding: utf-8 -*-
"""PDF de una tabla de la ficha del proyecto (CDPs, RPs u obligaciones), con el filtro de fechas.

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


# Anchos en cm: la hoja carta horizontal deja 25,5 cm utiles con margenes de 1,2

def _cdps(d):
    filas = list(d["cdps_proyecto"])
    return len(filas), _tabla(
        [("Vigencia", 1.6, False), ("Número CDP", 2.2, True), ("Fecha disponibilidad", 3.6, False),
         ("Objeto", 14.1, False), ("Valor disponibilidad definitiva", 4.0, True)],
        [[c.vigencia, c.nro_cdp, _fecha(c.fecha_disp), c.objeto_cert, _pesos(c.valor_cdp)]
         for c in filas],
        [None, None, None, None, _pesos(d["cdps_proyecto_total"])],
        "Sin CDPs en el periodo")


def _rps(d):
    filas = list(d["rps_por_proyecto"])
    return len(filas), _tabla(
        [("Vigencia", 1.6, False), ("Número RP", 2.0, True), ("Fecha registro", 3.6, False),
         ("Acto administrativo", 4.6, False), ("Objeto registro", 9.7, False),
         ("Valor comprometido definitivo", 4.0, True)],
        [[r.vigencia, r.nro_rp, _fecha(r.fecha_reg), r.acto_admon, r.objeto_reg, _pesos(r.valor_rp)]
         for r in filas],
        [None, None, None, None, None, _pesos(d["rps_por_proyecto_total"])],
        "Sin RPs en el periodo")


def _obligaciones(d):
    filas = list(d["obligaciones_por_proyecto"])
    return len(filas), _tabla(
        [("Vigencia", 1.3, False), ("Número", 1.5, True), ("Fecha obligación", 2.9, False),
         ("Beneficiario", 3.1, False), ("NIT", 1.9, True), ("Objeto", 4.9, False),
         ("Tipo de orden de gasto", 2.7, False), ("Valor obligación definitiva", 2.4, True),
         ("Saldo", 2.4, True), ("Pagado", 2.4, True)],
        [[o.vigencia, o.nro_obligacion, _fecha(o.fecha_obli),
          o.beneficiario.nombre if o.beneficiario else None,
          o.beneficiario.codigo if o.beneficiario else None,
          o.objeto_oblig or o.objeto_rp,
          o.tipo_orden_gasto.nombre if o.tipo_orden_gasto_id else None,
          _pesos(o.valor_obli), _pesos(o.saldo_oblig), _pesos(o.pagado_obli)]
         for o in filas],
        [None, None, None, None, None, None, None,
         _pesos(d["obligaciones_por_proyecto_total"]),
         _pesos(d["obligaciones_por_proyecto_saldo"]),
         _pesos(d["obligaciones_por_proyecto_pagado"])],
        "Sin obligaciones en el periodo")


# Cada tabla de la ficha se descarga por separado: (titulo, fecha que la recorta, armado)
TABLAS = {
    "cdps": ("CDPs", "fecha de disponibilidad", _cdps),
    "rps": ("RPs", "fecha de registro", _rps),
    "obligaciones": ("Obligaciones", "fecha de obligación", _obligaciones),
}


def generar(proyecto, desde, hasta, documentos, tabla):
    """Bytes del PDF de UNA tabla de la ficha (una llave de TABLAS).

    `documentos` es el dict de `ProyectoAdmin._documentos_filtrados`.
    """
    titulo, criterio, armar = TABLAS[tabla]
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
    cantidad, cuerpo = armar(documentos)
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
