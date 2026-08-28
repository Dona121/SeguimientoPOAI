# -*- coding: utf-8 -*-
"""Tablero de gestion por dependencia responsable (POAI).

Una fila por dependencia con como va la gestion de sus proyectos: cuantos tiene, en
cuantos ya se movio cada etapa de la cadena, cuantos documentos se expidieron, cuanto
se comprometio y que hay en SECOP II. Al elegir una dependencia, la misma tabla baja al
grano del proyecto.

Solo entran los proyectos **con dependencia responsable asignada**: sin ella no hay a
quien atribuirle la gestion, y mezclarlos ensuciaria la lectura.

Dos reglas que gobiernan el modulo:

1. **Cada etapa se corta por su propia fecha.** El CDP por su fecha de expedicion, el RP
   por la suya, la obligacion por la de causacion y el pago por la fecha del acta. Un
   rango de fechas responde "que se movio en esta semana", no "que documentos pertenecen
   a un lote".
2. **Una consulta agregada por etapa, cruzadas en Python por la llave.** Nunca dos `Sum`
   sobre joins distintos: agregar dos relaciones a la vez multiplica las filas. Es la
   misma trampa del grano que ya aparecio en la ficha y en el reporte financiero.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, F, Max, Sum

from .models import (BpinProceso, Cdp, CdpImputacion, Clasificacion, Compromiso,
                     CompromisoImputacion, ContratoActa, DependenciaResponsable,
                     Obligacion, ObligacionImputacion, Proyecto)

CERO = Decimal("0")

# El camino del acta de pago hasta el proyecto pasa por las imputaciones del contrato,
# que son varias por contrato: de ahi que las actas solo se CUENTEN (distinct) y el
# valor pagado se lea de las obligaciones, donde no hay abanico.
RUTA_IMPUTACION = "contrato__imputaciones_del_contrato"
RUTA_ACTA = f"{RUTA_IMPUTACION}__proyecto"

# Columnas numericas de una fila, para inicializar en cero y para totalizar
METRICAS = ("proyectos", "proyectos_con_cdp", "proyectos_con_rp", "proyectos_con_obligacion",
            "proyectos_con_pago", "cdps", "rps", "obligaciones", "actas",
            "disponible", "comprometido", "obligado", "pagado",
            "procesos_secop", "contratos_secop", "valor_secop", "secop_dudosos")

# SECOP trae contratos con valores imposibles por error de digitacion en la fuente
# (dos de ellos, de $1.102 y $460 billones, contra un maximo creible de $29 mil
# millones). Se cargan y se suman tal cual -el dato es el que es-, pero la fila avisa
# cuantos lleva, para que nadie lea como gestion lo que es un error del DNP. El comando
# `validar` los reporta uno por uno.
VALOR_IMPOSIBLE = Decimal("1000000000000")

# Un tramite cancelado no es gestion: no hay contrato que ejecutar. Ademas es donde vive
# la basura de la fuente -los 51 contratos cancelados suman $1.563 billones contra unos
# $299 mil millones de todos los demas, y los dos de valor imposible estan cancelados-.
ESTADO_CANCELADO = "Cancelado"


@dataclass
class Filtros:
    """El corte que pide la pagina. Todo es opcional; sin nada, trae la historia entera."""
    desde: date | None = None
    hasta: date | None = None
    vigencias: tuple = ()
    dependencia: int | None = None
    clasificacion: int | None = None


def rango_del_preset(preset, hoy=None):
    """(desde, hasta) de los atajos de la barra de fechas. None si no hay preset."""
    hoy = hoy or date.today()
    if preset == "semana":
        inicio = hoy - timedelta(days=hoy.weekday())
        return inicio, inicio + timedelta(days=6)
    if preset == "mes":
        inicio = hoy.replace(day=1)
        siguiente = (inicio + timedelta(days=32)).replace(day=1)
        return inicio, siguiente - timedelta(days=1)
    if preset == "trimestre":
        primer_mes = 3 * ((hoy.month - 1) // 3) + 1
        inicio = hoy.replace(month=primer_mes, day=1)
        siguiente = (inicio + timedelta(days=100)).replace(day=1)
        return inicio, siguiente - timedelta(days=1)
    if preset == "anio":
        return hoy.replace(month=1, day=1), hoy.replace(month=12, day=31)
    return None, None


# ---------------------------------------------------------------------------
# Las etapas
# ---------------------------------------------------------------------------

def _clave(ruta, por_proyecto):
    """Por que se agrupa: el proyecto mismo o la dependencia que responde por el."""
    return ruta if por_proyecto else f"{ruta}__dependencia_responsable"


def _recortar(qs, filtros, ruta, fecha, vigencia):
    """Los filtros comunes, cada etapa con SU campo de fecha y de vigencia."""
    qs = qs.filter(**{f"{ruta}__dependencia_responsable__isnull": False})
    if filtros.desde:
        qs = qs.filter(**{f"{fecha}__gte": filtros.desde})
    if filtros.hasta:
        qs = qs.filter(**{f"{fecha}__lte": filtros.hasta})
    if filtros.vigencias:
        qs = qs.filter(**{f"{vigencia}__in": filtros.vigencias})
    if filtros.dependencia:
        qs = qs.filter(**{f"{ruta}__dependencia_responsable": filtros.dependencia})
    if filtros.clasificacion:
        # Filtrar por UNA clasificacion no duplica filas (el proyecto casa a lo sumo una
        # vez en la tabla intermedia), asi que las sumas siguen limpias.
        qs = qs.filter(**{f"{ruta}__clasificaciones": filtros.clasificacion})
    return qs


def _indexar(qs):
    """{llave del grupo: fila} a partir de un values(k=...).annotate(...)."""
    return {r["k"]: r for r in qs if r["k"] is not None}


def _cdps(filtros, por_proyecto):
    qs = _recortar(CdpImputacion.objects, filtros, "proyecto", "cdp__fecha_disp", "cdp__vigencia")
    return _indexar(qs.values(k=F(_clave("proyecto", por_proyecto)))
                    .annotate(cdps=Count("cdp", distinct=True),
                              proyectos_con_cdp=Count("proyecto", distinct=True),
                              disponible=Sum("valor_disponibilidad_def")))


def _rps(filtros, por_proyecto):
    qs = _recortar(CompromisoImputacion.objects, filtros, "proyecto",
                   "compromiso__fecha_reg", "compromiso__vigencia")
    return _indexar(qs.values(k=F(_clave("proyecto", por_proyecto)))
                    .annotate(rps=Count("compromiso", distinct=True),
                              proyectos_con_rp=Count("proyecto", distinct=True),
                              comprometido=Sum("valor_compromiso_def")))


def _obligaciones(filtros, por_proyecto):
    qs = _recortar(ObligacionImputacion.objects, filtros, "proyecto",
                   "obligacion__fecha_obli", "obligacion__vigencia")
    return _indexar(qs.values(k=F(_clave("proyecto", por_proyecto)))
                    .annotate(obligaciones=Count("obligacion", distinct=True),
                              proyectos_con_obligacion=Count("proyecto", distinct=True),
                              obligado=Sum("valor_obligacion"),
                              pagado=Sum("pagos")))


def _actas(filtros, por_proyecto):
    """Las actas de pago del contrato: lo unico que trae fecha de pago propia.

    Aqui NO se suma `valor_pago`: el camino hasta el proyecto pasa por las imputaciones
    del contrato y un contrato con dos imputaciones repetiria cada acta. El dinero
    pagado sale de las obligaciones.
    """
    qs = _recortar(ContratoActa.objects, filtros, RUTA_ACTA, "fecha_pago",
                   f"{RUTA_IMPUTACION}__vigencia")
    return _indexar(qs.values(k=F(_clave(RUTA_ACTA, por_proyecto)))
                    .annotate(actas=Count("id", distinct=True),
                              proyectos_con_pago=Count(RUTA_ACTA, distinct=True)))


def _procesos_secop(filtros, por_proyecto):
    qs = _recortar(BpinProceso.objects.exclude(proceso__estado_procedimiento__iexact=ESTADO_CANCELADO),
                   filtros, "proyecto", "proceso__fecha_publicacion", "anio")
    return _indexar(qs.values(k=F(_clave("proyecto", por_proyecto)))
                    .annotate(procesos_secop=Count("proceso", distinct=True)))


def _contratos_secop(filtros, por_proyecto):
    """Contratos adjudicados y su valor, por fecha de firma. Sin los cancelados.

    El valor no se puede sumar en la consulta: un contrato que financia dos BPIN sale en
    dos filas de BpinProceso. Se piden las parejas (grupo, contrato, valor) distintas y
    se suman en Python, que es exacto y sigue siendo una sola consulta.
    """
    clave = _clave("proyecto", por_proyecto)
    qs = _recortar(BpinProceso.objects
                   .filter(contrato_secop__isnull=False)
                   .exclude(contrato_secop__estado__iexact=ESTADO_CANCELADO), filtros,
                   "proyecto", "contrato_secop__fecha_firma", "anio")
    contratos = {}
    for fila in qs.values(clave, "contrato_secop", "contrato_secop__valor").distinct():
        grupo = fila[clave]
        if grupo is None:
            continue
        datos = contratos.setdefault(grupo, {"contratos_secop": 0, "valor_secop": CERO,
                                             "secop_dudosos": 0})
        valor = fila["contrato_secop__valor"] or CERO
        datos["contratos_secop"] += 1
        datos["valor_secop"] += valor
        if valor >= VALOR_IMPOSIBLE:
            datos["secop_dudosos"] += 1
    return contratos


def _proyectos_asignados(filtros, por_proyecto):
    """El denominador: cuantos proyectos responde cada dependencia.

    No lo toca el rango de fechas. Un proyecto sigue asignado aunque en la semana
    elegida no se le haya movido un peso, y esa diferencia es justo lo que se quiere ver.
    """
    qs = Proyecto.objects.filter(dependencia_responsable__isnull=False)
    if filtros.dependencia:
        qs = qs.filter(dependencia_responsable=filtros.dependencia)
    if filtros.clasificacion:
        qs = qs.filter(clasificaciones=filtros.clasificacion)
    clave = "id" if por_proyecto else "dependencia_responsable"
    return _indexar(qs.values(k=F(clave)).annotate(proyectos=Count("id", distinct=True)))


ETAPAS = (_cdps, _rps, _obligaciones, _actas, _procesos_secop, _contratos_secop)


# ---------------------------------------------------------------------------
# El armado
# ---------------------------------------------------------------------------

def _fila(nombre, llave):
    return {"llave": llave, "nombre": nombre, **{m: 0 for m in METRICAS}}


def _armar(filtros, por_proyecto, nombres):
    """Cruza las etapas contra el catalogo de grupos y devuelve (filas, totales)."""
    partes = [_proyectos_asignados(filtros, por_proyecto)]
    partes += [etapa(filtros, por_proyecto) for etapa in ETAPAS]

    filas = {llave: _fila(nombre, llave) for llave, nombre in nombres.items()}
    for parte in partes:
        for llave, datos in parte.items():
            if llave not in filas:
                continue
            for metrica, valor in datos.items():
                if metrica in METRICAS and valor is not None:
                    filas[llave][metrica] = valor

    ordenadas = sorted(filas.values(), key=lambda f: (-(f["comprometido"] or 0), f["nombre"]))
    totales = {m: sum((f[m] or 0) for f in ordenadas) for m in METRICAS}
    return ordenadas, totales


def por_dependencia(filtros):
    """Una fila por dependencia responsable, ordenadas por lo comprometido."""
    dependencias = DependenciaResponsable.objects.all()
    if filtros.dependencia:
        dependencias = dependencias.filter(pk=filtros.dependencia)
    nombres = {d.pk: d.nombre for d in dependencias}
    filas, totales = _armar(filtros, por_proyecto=False, nombres=nombres)
    # Una dependencia sin proyectos asignados no aporta nada a la lectura
    filas = [f for f in filas if f["proyectos"]]
    return filas, totales


def por_proyecto(filtros):
    """Una fila por proyecto de la dependencia elegida. Sin dependencia, no aplica."""
    if not filtros.dependencia:
        return [], {m: 0 for m in METRICAS}
    proyectos = Proyecto.objects.filter(dependencia_responsable=filtros.dependencia)
    if filtros.clasificacion:
        proyectos = proyectos.filter(clasificaciones=filtros.clasificacion)
    nombres = {p.pk: f"{p.bpin} - {p.nombre or ''}".strip(" -") for p in proyectos}
    return _armar(filtros, por_proyecto=True, nombres=nombres)


def catalogos():
    """Lo que necesitan los slicers: vigencias, dependencias y clasificaciones con datos."""
    return {
        "dependencias": DependenciaResponsable.objects
                        .filter(proyectos__isnull=False).distinct(),
        "clasificaciones": Clasificacion.objects
                           .filter(proyectos__dependencia_responsable__isnull=False).distinct(),
    }


def ultimo_movimiento():
    """La fecha mas reciente que traen los reportes cargados.

    Los datos entran por tandas y el corte de hoy casi nunca es el corte de lo cargado:
    a fin de agosto la ultima carga puede llegar a julio. Sin decirlo, un periodo
    reciente se lee como una dependencia que no hizo nada.
    """
    fechas = [Cdp.objects.aggregate(f=Max("fecha_disp"))["f"],
              Compromiso.objects.aggregate(f=Max("fecha_reg"))["f"],
              Obligacion.objects.aggregate(f=Max("fecha_obli"))["f"],
              ContratoActa.objects.aggregate(f=Max("fecha_pago"))["f"]]
    fechas = [f for f in fechas if f]
    return max(fechas) if fechas else None
