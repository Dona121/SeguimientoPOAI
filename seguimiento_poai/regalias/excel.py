"""Descarga de la matriz de seguimiento en Excel, con la estructura de la que arma hoy el Streamlit.

Tres hojas (MatrizSeguimientoEvaluacion, OtrosEjecutoresDescentralizadas y
OtrosEjecutoresMunicipios), cada una con:
- una tabla de Excel con su nombre, desde la fila 2;
- la fila 1 con las secciones combinadas;
- encabezados de color, el ancho, las alturas y los formatos de consolidacion/columnas.py,
  diseno.py y escritura.py del Streamlit;
- las columnas de apoyo ocultas.

Las columnas que en Excel son formulas van como formulas, las de consolidacion/formulas.py con las
cuatro correcciones del plan (seccion 7.6), asi que al abrir el archivo Excel da lo mismo que el
sistema. Los dias van como valor, como hoy. El libro se marca para recalcular al abrir.

Que proyectos van:
- Departamento: sin CERRADO ni DESAPROBADO, como la matriz de hoy (que sale de CG-proy sin ellos).
- Descentralizadas y municipios: todos.

En comentarios va el ultimo comentario del proyecto, sin contar la nota "Datos de la matriz
anterior" que dejo la importacion.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table

from .models import ClasificacionRegalias, EstadoProyectoRegalias, ProyectoRegalias

# ---------- diseno (consolidacion/diseno.py) ----------

AZUL, AZUL_HEADER = "B7DEE8", "31869B"
NARANJA, NARANJA_HEADER = "F1A983", "BE5014"
VERDE, VERDE_HEADER = "D8E4BC", "9BBB59"
ALTO_FILA, ALTO_FILA_SECCION, ANCHO_COLUMNA = 70, 40, 25
FUENTE = "Roboto"
FORMATO_FECHA, FORMATO_NUMERO = "dd/mm/yyyy", "#,##0.000"
EN_EJECUCION = "CONTRATADO EN EJECUCIÓN"
NOTA_DE_IMPORTACION = "Datos de la matriz anterior."

# ---------- columnas (consolidacion/columnas.py) ----------

H1_GENERALES = [
    "BPIN", "ENTIDAD O SECRETARIA", "NOMBRE PROYECTO", "ALCANCE DEL PROYECTO", "SECTOR",
    "INDICADOR DE PRODUCTO MGA", "ESTADO PROYECTO", "ESTADO CONTRATO", "TIPO CONTRATO",
    "FUENTE DE FINANCIACIÓN", "VALOR SGR", "VALOR NACIÓN", "VALOR OTROS", "VALOR OTRAS FUENTES NO SUIFP",
    "VALOR TOTAL PROYECTO", "VALOR PAGOS", "ULTIMA FECHA PAGO", "FECHA DE MIGRACIÓN A GESPROY",
    "FECHA DE ASIGNACIÓN DE RECURSOS", "FECHA DE INCORPORACIÓN DE RECURSOS",
]
DIAS = [
    "DIAS DESDE LA APROBACIÓN HASTA APERTURA DEL PRIMER PROCESO",
    "DIAS DESDE LA APERTURA HASTA LA FIRMA DEL PRIMER CONTRATO",
    "DIAS DESDE LA FECHA DE SUSCRIPCIÓN HASTA LA FECHA DEL ACTA DE INICIO",
]
H1_CALIFICACION = [
    "AVANCE FISICO", "AVANCE FINANCIERO", "CPI", "SPI", "FECHA APROBACIÓN PROYECTO",
    "FECHA DE APERTURA DEL PRIMER PROCESO", "FECHA DE SUSCRIPCIÓN DEL CONTRATO PRINCIPAL",
    "FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO", "FECHA ACTA INICIO", "HORIZONTE DEL PROYECTO",
    "FECHA DE FINALIZACIÓN", "FECHA EN LA QUE PASO A ESTADO PARA CIERRE", "FECHA DE CORTE GESPROY",
    "INFORMACIÓN SOLICITADA", "INFORMACIÓN RECIBIDA", "FECHA DE RECIBO DE INFORMACIÓN", *DIAS,
    "DESEMPEÑO EN EL CRONOGRAMA", "DESEMPEÑO EN EL COSTO", "COLUMNA APOYO", "BRECHA FISICO - FINANCIERA",
    "CONTROL EXTERNALIDADES",
]
H1_EVALUACION = [
    "CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN", "CALIFICACIÓN INFORMACIÓN A TIEMPO",
    "CALIFICACIÓN CALIDAD INFORMACIÓN", "COLUMNA APOYO 2", "CALIFICACIÓN EJECUCIÓN DEL PROYECTO",
    "ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN", "COMENTARIOS CALIFICACIÓN", "RESPONSABLE CARGUE EN GESPROY",
    "MUNICIPIOS",
]
DESC_GENERALES = [
    "BPIN", "EJECUTOR", "NOMBRE DEL PROYECTO", "ALCANCE", "SECTOR", "FUENTE", "ESTADO PROYECTO",
    "ESTADO CONTRATO", "VALOR SGR", "VALOR OTROS", "VALOR TOTAL", "FECHA DE MIGRACIÓN A GESPROY",
    "FECHA DE ASIGNACIÓN DE RECURSOS", "FECHA DE INCORPORACIÓN DE RECURSOS",
]
DESC_CALIFICACION = [
    "AVANCE FÍSICO", "AVANCE FINANCIERO", "CPI", "SPI", "FECHA APROBACIÓN PROYECTO",
    "FECHA DE APERTURA DEL PRIMER PROCESO", "FECHA DE SUSCRIPCIÓN DEL CONTRATO PRINCIPAL",
    "FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO", "FECHA ACTA INICIO", "HORIZONTE DEL PROYECTO",
    "FECHA EN LA QUE PASO A ESTADO PARA CIERRE", "FECHA DE CORTE GESPROY", *DIAS,
    "DESEMPEÑO EN EL CRONOGRAMA", "DESEMPEÑO EN EL COSTO", "COLUMNA APOYO", "BRECHA FISICO - FINANCIERA",
    "CONTROL EXTERNALIDADES",
]
DESC_EVALUACION = [
    "CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN", "CALIFICACIÓN INFORMACIÓN A TIEMPO",
    "CALIFICACIÓN CALIDAD INFORMACIÓN", "COLUMNA APOYO 2", "CALIFICACIÓN EJECUCIÓN DEL PROYECTO",
    "ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN", "COMENTARIOS CALIFICACIÓN", "MUNICIPIOS",
]
MUN = [
    "BPIN", "EJECUTOR", "NOMBRE DEL PROYECTO", "ALCANCE", "SECTOR", "FUENTE", "ESTADO PROYECTO",
    "ESTADO CONTRATO", "VALOR SGR", "VALOR OTROS", "VALOR TOTAL", "FECHA APROBACIÓN PROYECTO",
    "FECHA DE ASIGNACIÓN DE RECURSOS", "FECHA DE INCORPORACIÓN DE RECURSOS", "FECHA ACTA INICIO",
    "AVANCE FÍSICO", "AVANCE FINANCIERO", "COMENTARIOS", "MUNICIPIOS",
]
VERDES = {"RESPONSABLE CARGUE EN GESPROY", "MUNICIPIOS"}
OCULTAS = ("COLUMNA APOYO", "COLUMNA APOYO 2")
NUMEROS = {"VALOR SGR", "VALOR NACIÓN", "VALOR OTROS", "VALOR OTRAS FUENTES NO SUIFP", "VALOR TOTAL PROYECTO",
           "VALOR TOTAL", "VALOR PAGOS", "AVANCE FISICO", "AVANCE FÍSICO", "AVANCE FINANCIERO",
           "CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN", "CALIFICACIÓN CALIDAD INFORMACIÓN",
           "ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN"}
# En descentralizadas, como en el Streamlit, las dos calificaciones manuales van sin formato
NUMEROS_DESC = NUMEROS - {"CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN", "CALIFICACIÓN CALIDAD INFORMACIÓN"}

# Columna de la matriz -> como sale del proyecto
CAMPOS = {
    "BPIN": "bpin", "NOMBRE PROYECTO": "nombre", "NOMBRE DEL PROYECTO": "nombre",
    "ALCANCE DEL PROYECTO": "alcance", "ALCANCE": "alcance", "INDICADOR DE PRODUCTO MGA": "indicadores_mga",
    "ESTADO CONTRATO": "estado_contrato", "TIPO CONTRATO": "tipo_contrato",
    "FUENTE DE FINANCIACIÓN": "fuentes", "FUENTE": "fuentes",
    "VALOR SGR": "valor_sgr", "VALOR NACIÓN": "valor_nacion", "VALOR OTROS": "valor_otros",
    "VALOR OTRAS FUENTES NO SUIFP": "valor_otras_no_suifp", "VALOR TOTAL PROYECTO": "valor_total",
    "VALOR TOTAL": "valor_total", "VALOR PAGOS": "valor_pagos", "ULTIMA FECHA PAGO": "fecha_ultimo_pago",
    "FECHA DE MIGRACIÓN A GESPROY": "fecha_migracion_gesproy",
    "FECHA DE ASIGNACIÓN DE RECURSOS": "fecha_asignacion_recursos",
    "FECHA DE INCORPORACIÓN DE RECURSOS": "fecha_incorporacion_recursos",
    "AVANCE FISICO": "avance_fisico", "AVANCE FÍSICO": "avance_fisico", "AVANCE FINANCIERO": "avance_financiero",
    "CPI": "cpi", "SPI": "spi", "FECHA APROBACIÓN PROYECTO": "fecha_aprobacion",
    "FECHA DE APERTURA DEL PRIMER PROCESO": "fecha_apertura_primer_proceso",
    "FECHA DE SUSCRIPCIÓN DEL CONTRATO PRINCIPAL": "fecha_suscripcion_principal",
    "FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO": "fecha_suscripcion_primer_contrato",
    "FECHA ACTA INICIO": "fecha_acta_inicio", "HORIZONTE DEL PROYECTO": "horizonte",
    "FECHA DE FINALIZACIÓN": "fecha_finalizacion", "FECHA EN LA QUE PASO A ESTADO PARA CIERRE": "fecha_para_cierre",
    "FECHA DE CORTE GESPROY": "fecha_corte", "INFORMACIÓN SOLICITADA": "informacion_solicitada",
    "INFORMACIÓN RECIBIDA": "informacion_recibida", "FECHA DE RECIBO DE INFORMACIÓN": "fecha_recibo_informacion",
    DIAS[0]: "dias_aprobacion_a_apertura", DIAS[1]: "dias_apertura_a_firma", DIAS[2]: "dias_suscripcion_a_acta",
    "CONTROL EXTERNALIDADES": "control_externalidades",
    "CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN": "cal_desempeno_contratacion",
    "CALIFICACIÓN CALIDAD INFORMACIÓN": "cal_calidad_informacion",
    "CALIFICACIÓN INFORMACIÓN A TIEMPO": "cal_informacion_a_tiempo",
    "ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN": "indice_eficiencia_terminacion",
}


# ---------- formulas (consolidacion/formulas.py, con las correcciones de la seccion 7.6) ----------

def formulas(columnas, fila, departamento):
    """{columna: formula} de la fila (1-based). `departamento` elige la variante de la hoja principal."""
    letra = {c: get_column_letter(i + 1) for i, c in enumerate(columnas)}

    def ref(c):
        return f"${letra[c]}{fila}"

    estado, spi, cpi = ref("ESTADO PROYECTO"), ref("SPI"), ref("CPI")
    af = ref("AVANCE FINANCIERO")
    afis = ref("AVANCE FISICO" if departamento else "AVANCE FÍSICO")
    apoyo, apoyo2 = ref("COLUMNA APOYO"), ref("COLUMNA APOYO 2")
    cron, cost, brecha = ref("DESEMPEÑO EN EL CRONOGRAMA"), ref("DESEMPEÑO EN EL COSTO"), ref("BRECHA FISICO - FINANCIERA")
    ext, horizonte, fcorte = ref("CONTROL EXTERNALIDADES"), ref("HORIZONTE DEL PROYECTO"), ref("FECHA DE CORTE GESPROY")
    susc = ref("FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO")
    en_ejecucion = f'{estado}="{EN_EJECUCION}"'

    def indicador(v):
        p = f"(({v}-0.38)/(0.84-0.38))*100"
        # Correccion 1: el tramo de 100 incluye 1,2 (en Excel quedaba fuera de todos)
        return (f'=IF(AND({v}>1.3,{en_ejecucion}),0,'
                f'IF(AND({v}>1.25,{v}<=1.3,{en_ejecucion}),30,'
                f'IF(AND({v}>1.2,{v}<=1.25,{en_ejecucion}),90,'
                f'IF(AND({v}>=0.84,{v}<=1.2,{en_ejecucion}),100,'
                f'IF(AND({v}>=0.38,{v}<0.84,{en_ejecucion}),{p},'
                f'IF(AND({v}<0.38,{en_ejecucion}),0,""))))))')

    b = f"({af}-{afis})"
    f_apoyo = (f'=IF(AND({af}<60,{b}<=50),100,IF(AND({af}<60,{b}>50),0,'
               f'IF(AND({af}>=60,{af}<70,{b}<=40),100,IF(AND({af}>=60,{af}<70,{b}>40),0,'
               f'IF(AND({af}>=70,{af}<80,{b}<=30),100,IF(AND({af}>=70,{af}<80,{b}>30),0,'
               f'IF(AND({af}>=80,{af}<90,{b}<=20),100,IF(AND({af}>=80,{af}<90,{b}>20),0,'
               f'IF(AND({af}>=90,{af}<=100,{b}<=10),100,'
               f'IF(AND({af}>=90,{af}<=100,{b}>10),0,""))))))))))')
    # Correccion 4: las cuatro reglas de la brecha exigen ejecucion
    f_brecha = (f'=IF(AND({afis}>{af},{en_ejecucion}),100,'
                f'IF(AND({af}>{afis},{b}>50,{en_ejecucion}),0,'
                f'IF(AND({af}>{afis},{b}<=50,{af}<=60,{en_ejecucion}),100,'
                f'IF(AND({af}>{afis},{b}<=50,{af}>60,{en_ejecucion}),{apoyo},""))))')
    f_apoyo2 = (f'=IF({ext}=0,100,IF({ext}=1,90,IF({ext}=2,75,'
                f'IF({ext}=3,60,IF({ext}=4,50,IF({ext}=5,25,'
                f'IF({ext}>=6,0,"")))))))')

    if departamento:
        info, chequeo, error = ref("INFORMACIÓN SOLICITADA"), "ISTEXT", '"Revisar"'
    else:
        info, chequeo, error = ref("CALIFICACIÓN INFORMACIÓN A TIEMPO"), "ISNUMBER", '""'
    ponderado = f"({cron}*0.4+{cost}*0.2+{brecha}*0.4)"
    calculo = f'IFERROR(IF({chequeo}({info}),{ponderado},""),"")'
    vencido = f"AND(ISNUMBER({horizonte}),ISNUMBER({fcorte}),{horizonte}<{fcorte})"
    rama_ejecucion = f"IF({vencido},0,IF({ext}>=1,({calculo})*{apoyo2}/100,{calculo}))"
    # Correccion 2: sin alguna de las dos fechas, vacio
    dias = f"{fcorte}-{susc}"
    rama_sin_acta = f'IF(AND(ISNUMBER({fcorte}),ISNUMBER({susc})),IF(AND({dias}>=0,{dias}<=30),100,0),"")'
    f_ejecucion = (f'=IFERROR(IF({en_ejecucion},{rama_ejecucion},'
                   f'IF({estado}="CONTRATADO SIN ACTA DE INICIO",{rama_sin_acta},"")),{error})')

    resultado = {
        "DESEMPEÑO EN EL CRONOGRAMA": indicador(spi),
        "DESEMPEÑO EN EL COSTO": indicador(cpi),
        "COLUMNA APOYO": f_apoyo,
        "BRECHA FISICO - FINANCIERA": f_brecha,
        "COLUMNA APOYO 2": f_apoyo2,
        "CALIFICACIÓN EJECUCIÓN DEL PROYECTO": f_ejecucion,
    }
    if departamento:
        recibo = ref("FECHA DE RECIBO DE INFORMACIÓN")
        resultado["CALIFICACIÓN INFORMACIÓN A TIEMPO"] = (
            f'=IF(ISNUMBER({recibo}),IF(DAY({recibo})=10,100,IF(DAY({recibo})=11,80,'
            f'IF(DAY({recibo})=12,50,0))),"")')
    return resultado


# ---------- valores ----------

def _ultimo_comentario(proyecto):
    for comentario in proyecto.comentarios.all():          # del mas reciente al mas antiguo
        if not comentario.texto.startswith(NOTA_DE_IMPORTACION):
            return comentario.texto
    return None


def valor(proyecto, columna):
    """Lo que va en la celda de la columna, como lo guarda el sistema."""
    if columna in CAMPOS:
        dato = getattr(proyecto, CAMPOS[columna])
    elif columna == "ENTIDAD O SECRETARIA":
        dato = proyecto.dependencia
    elif columna == "EJECUTOR":
        dato = proyecto.entidad_ejecutora or proyecto.dependencia
    elif columna == "SECTOR":
        dato = proyecto.sector
    elif columna == "ESTADO PROYECTO":
        dato = proyecto.estado
    elif columna in ("COMENTARIOS CALIFICACIÓN", "COMENTARIOS"):
        dato = _ultimo_comentario(proyecto)
    elif columna == "RESPONSABLE CARGUE EN GESPROY":
        dato = "\n".join(r.nombre for r in proyecto.responsables_cargue.all()) or None
    elif columna == "MUNICIPIOS":
        dato = ", ".join(m.nombre for m in proyecto.municipios.all()) or None
    else:
        raise KeyError(columna)
    if dato == "":
        return None
    if isinstance(dato, Decimal):
        return float(dato)
    if isinstance(dato, (int, float, date, datetime)) or dato is None:
        return dato
    return str(dato)


# ---------- escritura ----------

def _estilos():
    borde = Side(style="thin")
    return {
        "borde": Border(left=borde, right=borde, top=borde, bottom=borde),
        "centro": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "titulo": Font(name=FUENTE, size=12, bold=True, color="FFFFFF"),
        "encabezado": Font(name=FUENTE, size=10, bold=True, color="FFFFFF"),
        "celda": Font(name=FUENTE, size=10),
    }


def _hoja(libro, nombre, secciones, verdes, proyectos, departamento, con_formulas, numeros):
    """Una hoja: secciones (fila 1), tabla con encabezados (fila 2) y una fila por proyecto."""
    estilos = _estilos()
    hoja = libro.create_sheet(nombre)
    columnas = [c for _, cols, _ in secciones for c in cols]

    for i in range(1, len(columnas) + 1):
        hoja.column_dimensions[get_column_letter(i)].width = ANCHO_COLUMNA
    hoja.row_dimensions[1].height = ALTO_FILA_SECCION
    hoja.row_dimensions[2].height = ALTO_FILA

    inicio = 1
    for titulo, cols, color in secciones:
        fin = inicio + len(cols) - 1
        celda = hoja.cell(row=1, column=inicio, value=titulo)
        for c in range(inicio, fin + 1):
            hoja.cell(row=1, column=c).fill = PatternFill("solid", fgColor=color)
            hoja.cell(row=1, column=c).border = estilos["borde"]
        celda.font, celda.alignment = estilos["titulo"], estilos["centro"]
        hoja.merge_cells(start_row=1, start_column=inicio, end_row=1, end_column=fin)
        inicio = fin + 1

    color_de = {c: color for _, cols, color in secciones for c in cols}
    for i, columna in enumerate(columnas, start=1):
        celda = hoja.cell(row=2, column=i, value=columna)
        fondo = VERDE_HEADER if columna in verdes else {AZUL: AZUL_HEADER, NARANJA: NARANJA_HEADER}[color_de[columna]]
        celda.fill = PatternFill("solid", fgColor=fondo)
        celda.font, celda.alignment, celda.border = estilos["encabezado"], estilos["centro"], estilos["borde"]

    fila = 2
    for proyecto in proyectos:
        fila += 1
        hoja.row_dimensions[fila].height = ALTO_FILA
        de_la_fila = formulas(columnas, fila, departamento) if con_formulas else {}
        for i, columna in enumerate(columnas, start=1):
            contenido = de_la_fila.get(columna) or valor(proyecto, columna)
            celda = hoja.cell(row=fila, column=i, value=contenido)
            celda.font, celda.alignment, celda.border = estilos["celda"], estilos["centro"], estilos["borde"]
            if CAMPOS.get(columna, "").startswith(("fecha_", "horizonte")):
                celda.number_format = FORMATO_FECHA
            elif columna in numeros:
                celda.number_format = FORMATO_NUMERO
    if fila == 2:                     # una tabla de Excel necesita al menos una fila de datos
        fila = 3

    tabla = Table(displayName=nombre, ref=f"A2:{get_column_letter(len(columnas))}{fila}")
    hoja.add_table(tabla)
    for columna in OCULTAS:
        if columna in columnas:
            hoja.column_dimensions[get_column_letter(columnas.index(columna) + 1)].hidden = True
    return hoja


def _proyectos(codigo, excluir_estados=()):
    consulta = (ProyectoRegalias.objects.filter(clasificacion__codigo=codigo)
                .exclude(estado__codigo__in=excluir_estados)
                .select_related("estado", "sector", "dependencia", "entidad_ejecutora")
                .prefetch_related("municipios", "responsables_cargue", "comentarios")
                .order_by("bpin"))
    return list(consulta)


def matriz():
    """El libro de la matriz, en bytes."""
    libro = Workbook()
    libro.remove(libro.active)
    _hoja(libro, "MatrizSeguimientoEvaluacion",
          [("DATOS GENERALES", H1_GENERALES, AZUL), ("DATOS PARA CALIFICACIÓN", H1_CALIFICACION, NARANJA),
           ("EVALUACIÓN", H1_EVALUACION, AZUL)], VERDES,
          _proyectos(ClasificacionRegalias.DEPARTAMENTO,
                     (EstadoProyectoRegalias.CERRADO, EstadoProyectoRegalias.DESAPROBADO)),
          departamento=True, con_formulas=True, numeros=NUMEROS)
    _hoja(libro, "OtrosEjecutoresDescentralizadas",
          [("DATOS GENERALES", DESC_GENERALES, AZUL), ("DATOS PARA CALIFICACIÓN", DESC_CALIFICACION, NARANJA),
           ("EVALUACIÓN", DESC_EVALUACION, AZUL)], {"MUNICIPIOS"},
          _proyectos(ClasificacionRegalias.DESCENTRALIZADA), departamento=False, con_formulas=True,
          numeros=NUMEROS_DESC)
    _hoja(libro, "OtrosEjecutoresMunicipios", [("DATOS GENERALES", MUN, AZUL)], {"MUNICIPIOS"},
          _proyectos(ClasificacionRegalias.MUNICIPIO), departamento=False, con_formulas=False, numeros=NUMEROS)
    libro.calculation.fullCalcOnLoad = True           # Excel recalcula las formulas al abrir
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
