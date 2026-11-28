"""Campos calculados de los proyectos de regalias: los dias y las formulas de la matriz.

Hoy esas columnas son formulas de Excel (consolidacion/formulas.py del Streamlit) y tres
calculos de dias en Python (consolidacion/calculos.py). Aqui se replican con las mismas
reglas, mas las cuatro correcciones que decidio el usuario el 27/11/2026 (plan, seccion 7.6):

1. SPI o CPI = 1,2 da 100 (en Excel ningun tramo lo cubria y daba vacio).
2. Sin acta de inicio, si falta la fecha de corte o la de suscripcion del primer contrato,
   la calificacion queda vacia (en Excel daba 0 con una faltante y 100 con las dos).
3. Dias desde la apertura hasta la firma = fecha de corte - apertura, para SIN CONTRATAR
   (en Excel era acta de inicio - apertura y salia siempre vacio). Coincide con el hito 2.
4. La brecha fisico-financiera solo se calcula en ejecucion (en Excel dos reglas no lo
   exigian).

Convencion de Excel que se conserva: una celda vacia vale 0 al comparar y operar (`n()`),
pero no cuenta como numero. "Vacio" es None. Los resultados van con 3 decimales.

Las funciones son puras: reciben el proyecto (o cualquier objeto con sus atributos) y no
tocan la base. `aplicar` escribe los resultados en el proyecto; quien guarda es el llamador
(servicios.guardar_proyecto y el admin).
"""
from decimal import ROUND_HALF_UP, Decimal

from .models import ClasificacionRegalias, EstadoProyectoRegalias

CERO = Decimal(0)
CIEN = Decimal(100)
MILESIMA = Decimal("0.001")

SIN_CONTRATAR = EstadoProyectoRegalias.SIN_CONTRATAR
SIN_ACTA = EstadoProyectoRegalias.CONTRATADO_SIN_ACTA
EN_EJECUCION = EstadoProyectoRegalias.CONTRATADO_EN_EJECUCION

CALCULADOS = ("dias_aprobacion_a_apertura", "dias_apertura_a_firma", "dias_suscripcion_a_acta",
              "desempeno_cronograma", "desempeno_costo", "columna_apoyo", "brecha_fisico_financiera",
              "columna_apoyo_2", "cal_ejecucion", "ejecucion_revisar")


def n(valor):
    """El valor como Decimal, o 0 si esta vacio: como Excel al comparar una celda vacia."""
    return CERO if valor is None else Decimal(valor)


def redondear(valor):
    return None if valor is None else Decimal(valor).quantize(MILESIMA, rounding=ROUND_HALF_UP)


def _estado(proyecto):
    estado = getattr(proyecto, "estado", None)
    return getattr(estado, "codigo", None)


def _es_departamento(proyecto):
    clasificacion = getattr(proyecto, "clasificacion", None)
    return getattr(clasificacion, "codigo", None) == ClasificacionRegalias.DEPARTAMENTO


def _dias(hasta, desde):
    return (hasta - desde).days if hasta and desde else None


# ---------- dias (coinciden con los hitos 0, 2 y 3 de la app de hitos) ----------

def dias_aprobacion_a_apertura(p):
    """SIN CONTRATAR, tenga o no apertura: de la aprobacion a la fecha de corte (hito 0)."""
    return _dias(p.fecha_corte, p.fecha_aprobacion) if _estado(p) == SIN_CONTRATAR else None


def dias_apertura_a_firma(p):
    """SIN CONTRATAR: de la apertura del primer proceso a la fecha de corte (hito 2). Correccion 3."""
    return _dias(p.fecha_corte, p.fecha_apertura_primer_proceso) if _estado(p) == SIN_CONTRATAR else None


def dias_suscripcion_a_acta(p):
    """CONTRATADO SIN ACTA DE INICIO: de la suscripcion del contrato principal a la fecha de corte (hito 3)."""
    return _dias(p.fecha_corte, p.fecha_suscripcion_principal) if _estado(p) == SIN_ACTA else None


# ---------- formulas ----------

def desempeno(indice, en_ejecucion):
    """Desempeno en el cronograma (con el SPI) o en el costo (con el CPI). Correccion 1: 1,2 da 100."""
    if not en_ejecucion:
        return None
    v = n(indice)
    if v > Decimal("1.3"):
        return CERO
    if v > Decimal("1.25"):
        return Decimal(30)
    if v > Decimal("1.2"):
        return Decimal(90)
    if v >= Decimal("0.84"):
        return CIEN
    if v >= Decimal("0.38"):
        return (v - Decimal("0.38")) / (Decimal("0.84") - Decimal("0.38")) * CIEN
    return CERO


# Tolerancia de la columna apoyo: (tope del avance financiero, brecha maxima para 100)
TRAMOS_APOYO = ((Decimal(60), Decimal(50)), (Decimal(70), Decimal(40)), (Decimal(80), Decimal(30)),
                (Decimal(90), Decimal(20)))


def columna_apoyo(avance_fisico, avance_financiero):
    """100 si el financiero no le saca al fisico mas de lo tolerado para su tramo; si no, 0.

    No depende del estado. Con el financiero por encima de 100 queda vacia, como en Excel.
    """
    af = n(avance_financiero)
    brecha = af - n(avance_fisico)
    for tope, maximo in TRAMOS_APOYO:
        if af < tope:
            return CIEN if brecha <= maximo else CERO
    if af <= CIEN:
        return CIEN if brecha <= Decimal(10) else CERO
    return None


def brecha_fisico_financiera(avance_fisico, avance_financiero, apoyo, en_ejecucion):
    """Correccion 4: solo en ejecucion."""
    if not en_ejecucion:
        return None
    fisico, financiero = n(avance_fisico), n(avance_financiero)
    brecha = financiero - fisico
    if fisico > financiero:
        return CIEN
    if financiero > fisico:
        if brecha > 50:
            return CERO
        return CIEN if financiero <= 60 else apoyo
    return None     # fisico = financiero: Excel no tiene regla y queda vacio


DESCUENTO_EXTERNALIDADES = {0: Decimal(100), 1: Decimal(90), 2: Decimal(75), 3: Decimal(60), 4: Decimal(50),
                            5: Decimal(25)}


def columna_apoyo_2(control_externalidades):
    """El descuento por externalidades: 0 → 100 ... 5 → 25; 6 o mas → 0."""
    return DESCUENTO_EXTERNALIDADES.get(int(n(control_externalidades)), CERO)


def informacion_a_tiempo(fecha_recibo):
    """Solo en el departamento: dia 10 → 100, 11 → 80, 12 → 50, otro dia → 0."""
    if fecha_recibo is None:
        return None
    return {10: Decimal(100), 11: Decimal(80), 12: Decimal(50)}.get(fecha_recibo.day, CERO)


def calificacion_ejecucion(p, cronograma, costo, brecha, apoyo_2, informacion_a_tiempo_):
    """(calificacion, revisar). `revisar` es el "Revisar" de Excel en el departamento."""
    estado = _estado(p)
    departamento = _es_departamento(p)
    if estado == EN_EJECUCION:
        if p.horizonte and p.fecha_corte and p.horizonte < p.fecha_corte:
            return CERO, False
        if departamento:
            hay_informacion = bool((p.informacion_solicitada or "").strip())
        else:
            hay_informacion = informacion_a_tiempo_ is not None
        ponderado = None
        if None not in (cronograma, costo, brecha):
            ponderado = cronograma * Decimal("0.4") + costo * Decimal("0.2") + brecha * Decimal("0.4")
        calculo = ponderado if hay_informacion else None
        if n(p.control_externalidades) >= 1:
            if calculo is None:            # en Excel, operar con "" es un error: IFERROR
                return None, departamento
            return calculo * apoyo_2 / CIEN, False
        return calculo, False
    if estado == SIN_ACTA:
        # Correccion 2: sin alguna de las dos fechas no se calcula
        dias = _dias(p.fecha_corte, p.fecha_suscripcion_primer_contrato)
        if dias is None:
            return None, False
        return (CIEN if 0 <= dias <= 30 else CERO), False
    return None, False


# ---------- todo junto ----------

def calcular(p):
    """{campo: valor} de todos los calculados. Sin estado no se calcula nada."""
    if _estado(p) is None:
        valores = {campo: None for campo in CALCULADOS}
        valores["ejecucion_revisar"] = False
        if _es_departamento(p):
            valores["cal_informacion_a_tiempo"] = None
        return valores

    en_ejecucion = _estado(p) == EN_EJECUCION
    cronograma = desempeno(p.spi, en_ejecucion)
    costo = desempeno(p.cpi, en_ejecucion)
    apoyo = columna_apoyo(p.avance_fisico, p.avance_financiero)
    brecha = brecha_fisico_financiera(p.avance_fisico, p.avance_financiero, apoyo, en_ejecucion)
    apoyo_2 = columna_apoyo_2(p.control_externalidades)
    valores = {}
    if _es_departamento(p):
        valores["cal_informacion_a_tiempo"] = a_tiempo = informacion_a_tiempo(p.fecha_recibo_informacion)
    else:
        a_tiempo = p.cal_informacion_a_tiempo          # en las otras clasificaciones se digita
    ejecucion, revisar = calificacion_ejecucion(p, cronograma, costo, brecha, apoyo_2, a_tiempo)
    valores.update({
        "dias_aprobacion_a_apertura": dias_aprobacion_a_apertura(p),
        "dias_apertura_a_firma": dias_apertura_a_firma(p),
        "dias_suscripcion_a_acta": dias_suscripcion_a_acta(p),
        "desempeno_cronograma": cronograma,
        "desempeno_costo": costo,
        "columna_apoyo": apoyo,
        "brecha_fisico_financiera": brecha,
        "columna_apoyo_2": apoyo_2,
        "cal_ejecucion": ejecucion,
        "ejecucion_revisar": revisar,
    })
    return {campo: (redondear(valor) if isinstance(valor, Decimal) else valor) for campo, valor in valores.items()}


def aplicar(p):
    """Escribe los calculados en el proyecto (sin guardarlo)."""
    for campo, valor in calcular(p).items():
        setattr(p, campo, valor)
    return p
