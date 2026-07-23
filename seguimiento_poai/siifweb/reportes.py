# -*- coding: utf-8 -*-
"""Reporte de proyectos: filtra la cadena de gasto y arma un Excel con las
columnas que el usuario elija. Parte del proyecto, igual que la ficha.

Regla de oro (aprendida a golpes): los totales salen por Subquery sobre la tabla
de imputaciones, nunca re-agregando un queryset ya anotado. Un aggregate() sobre
un annotate() de la misma relacion mete un DISTINCT implicito (colapsa valores
repetidos) o multiplica el join. Aqui cada columna es su propia subconsulta.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.db.models import (Count, DecimalField, Exists, IntegerField, OuterRef,
                              Subquery, Sum)

from .models import (CdpImputacion, CompromisoImputacion, ContratoImputacion,
                     ObligacionImputacion, Proyecto, ReservaImputacion)

_MONEY = DecimalField(max_digits=20, decimal_places=2)

# --- catalogo de columnas -------------------------------------------------
# (clave, etiqueta, grupo, tipo)   tipo: texto | money | entero
COLUMNAS = [
    ("bpin",                    "BPIN",                      "Identificacion", "texto"),
    ("nombre",                  "Nombre del proyecto",       "Identificacion", "texto"),
    ("dependencia",             "Dependencia (ejecuta)",     "Identificacion", "texto"),
    ("dependencia_responsable", "Dependencia responsable",   "Identificacion", "texto"),
    ("clasificaciones",         "Clasificaciones",           "Identificacion", "texto"),
    ("origen",                  "Origen",                    "Identificacion", "texto"),

    ("certificado",             "Certificado",               "Disponibilidad", "money"),
    ("disponibilidad_def",      "Disponibilidad definitiva", "Disponibilidad", "money"),
    ("sin_comprometer",         "Sin comprometer",           "Disponibilidad", "money"),
    ("n_cdps",                  "N.o de CDPs",               "Disponibilidad", "entero"),

    ("comprometido",            "Comprometido",              "Compromiso",     "money"),
    ("sin_obligar",             "Sin obligar",               "Compromiso",     "money"),
    ("n_rps",                   "N.o de RPs",                "Compromiso",     "entero"),

    ("obligado",                "Obligado",                  "Obligacion",     "money"),
    ("sin_girar",               "Sin girar",                 "Obligacion",     "money"),

    ("pagado",                  "Pagado",                    "Pago",           "money"),

    ("reservado",               "Reservado",                 "Cierre",         "money"),
    ("saldo_reserva",           "Saldo de reserva",          "Cierre",         "money"),

    ("n_contratos",             "N.o de contratos",          "Contractual",    "entero"),
    ("valor_contratado",        "Valor contratado",          "Contractual",    "money"),
    ("contratistas",            "Contratistas",              "Contractual",    "texto"),
]

META = {c[0]: {"label": c[1], "grupo": c[2], "tipo": c[3]} for c in COLUMNAS}
ORDEN = [c[0] for c in COLUMNAS]

GRUPOS = []
for _, _, g, _ in COLUMNAS:
    if g not in GRUPOS:
        GRUPOS.append(g)

DEF_SELECCION = ["bpin", "nombre", "dependencia", "certificado", "comprometido",
                 "obligado", "pagado"]


# --- lectura de los filtros del formulario --------------------------------

def parse_filtros(post):
    def fecha(v):
        try:
            return datetime.strptime((v or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    def numeros(v):
        return [t for t in (v or "").replace(",", " ").split() if t]

    return {
        "bpines": [b for b in post.getlist("bpines") if b],
        "disp_desde": fecha(post.get("disp_desde")),
        "disp_hasta": fecha(post.get("disp_hasta")),
        "reg_desde": fecha(post.get("reg_desde")),
        "reg_hasta": fecha(post.get("reg_hasta")),
        "nros_cdp": numeros(post.get("nros_cdp")),
        "nros_rp": numeros(post.get("nros_rp")),
        "contratista": (post.get("contratista") or "").strip(),
        "doc_contratista": (post.get("doc_contratista") or "").strip(),
    }


# --- aplicacion de filtros por etapa de la cadena -------------------------
# Cada grupo de filtros acota su propia etapa: la fecha de disponibilidad y el
# numero de CDP miden lo certificado; la fecha de registro y el numero de RP
# miden lo comprometido/obligado/pagado (todo lo que cuelga del compromiso).

def _f_cdp(qs, f):
    if f["disp_desde"]:
        qs = qs.filter(cdp__fecha_disp__gte=f["disp_desde"])
    if f["disp_hasta"]:
        qs = qs.filter(cdp__fecha_disp__lte=f["disp_hasta"])
    if f["nros_cdp"]:
        qs = qs.filter(cdp__nro_cdp__in=f["nros_cdp"])
    return qs


def _f_comp(qs, f):
    if f["reg_desde"]:
        qs = qs.filter(compromiso__fecha_reg__gte=f["reg_desde"])
    if f["reg_hasta"]:
        qs = qs.filter(compromiso__fecha_reg__lte=f["reg_hasta"])
    if f["nros_rp"]:
        qs = qs.filter(compromiso__nro_rp__in=f["nros_rp"])
    return qs


def _hay_filtro_cdp(f):
    return bool(f["disp_desde"] or f["disp_hasta"] or f["nros_cdp"])


def _hay_filtro_comp(f):
    return bool(f["reg_desde"] or f["reg_hasta"] or f["nros_rp"])


def base_proyectos(f):
    """Que proyectos entran: los que cumplen TODOS los filtros que se pusieron."""
    qs = Proyecto.objects.all()
    if f["bpines"]:
        qs = qs.filter(bpin__in=f["bpines"])
    if f["contratista"] or f["doc_contratista"]:
        ci = ContratoImputacion.objects.filter(proyecto=OuterRef("pk"))
        if f["contratista"]:
            ci = ci.filter(contrato__tercero__nombre__icontains=f["contratista"])
        if f["doc_contratista"]:
            ci = ci.filter(contrato__tercero__codigo__icontains=f["doc_contratista"])
        qs = qs.filter(Exists(ci))
    if _hay_filtro_cdp(f):
        qs = qs.filter(Exists(_f_cdp(CdpImputacion.objects.filter(proyecto=OuterRef("pk")), f)))
    if _hay_filtro_comp(f):
        qs = qs.filter(Exists(_f_comp(CompromisoImputacion.objects.filter(proyecto=OuterRef("pk")), f)))
    return qs


def _suma(modelo, campo, filtro, f):
    qs = modelo.objects.filter(proyecto=OuterRef("pk"))
    if filtro:
        qs = filtro(qs, f)
    return Subquery(qs.values("proyecto").annotate(t=Sum(campo)).values("t")[:1],
                    output_field=_MONEY)


def _cuenta(modelo, campo, filtro, f):
    qs = modelo.objects.filter(proyecto=OuterRef("pk"))
    if filtro:
        qs = filtro(qs, f)
    return Subquery(qs.values("proyecto").annotate(n=Count(campo, distinct=True)).values("n")[:1],
                    output_field=IntegerField())


def _anotaciones(claves, f):
    a = {}
    if "certificado" in claves:
        a["v_certificado"] = _suma(CdpImputacion, "valor_certificado", _f_cdp, f)
    if "disponibilidad_def" in claves:
        a["v_disponibilidad_def"] = _suma(CdpImputacion, "valor_disponibilidad_def", _f_cdp, f)
    if "sin_comprometer" in claves:
        a["v_sin_comprometer"] = _suma(CdpImputacion, "saldo_certf", _f_cdp, f)
    if "n_cdps" in claves:
        a["v_n_cdps"] = _cuenta(CdpImputacion, "cdp", _f_cdp, f)
    if "comprometido" in claves:
        a["v_comprometido"] = _suma(CompromisoImputacion, "valor_compromiso_def", _f_comp, f)
    if "sin_obligar" in claves:
        a["v_sin_obligar"] = _suma(CompromisoImputacion, "saldo_rp", _f_comp, f)
    if "n_rps" in claves:
        a["v_n_rps"] = _cuenta(CompromisoImputacion, "compromiso", _f_comp, f)
    if "obligado" in claves:
        a["v_obligado"] = _suma(ObligacionImputacion, "valor_obligacion", _f_comp, f)
    if "sin_girar" in claves:
        a["v_sin_girar"] = _suma(ObligacionImputacion, "saldo_obli", _f_comp, f)
    if "pagado" in claves:
        a["v_pagado"] = _suma(ObligacionImputacion, "pagos", _f_comp, f)
    if "reservado" in claves:
        a["v_reservado"] = _suma(ReservaImputacion, "valor_reserva", None, f)
    if "saldo_reserva" in claves:
        a["v_saldo_reserva"] = _suma(ReservaImputacion, "saldo_reserva", None, f)
    return a


def _contractual(ids, claves, f):
    """N.o de contratos, valor contratado y contratistas: en Python para no
    multiplicar el valor del contrato por sus imputaciones (fan-out del join)."""
    if not any(k in claves for k in ("n_contratos", "valor_contratado", "contratistas")):
        return {}
    pares = (ContratoImputacion.objects.filter(proyecto_id__in=ids)
             .values("proyecto_id", "contrato_id", "contrato__valor_contrato",
                     "contrato__tercero__nombre")
             .distinct())
    if f["contratista"]:
        pares = pares.filter(contrato__tercero__nombre__icontains=f["contratista"])
    if f["doc_contratista"]:
        pares = pares.filter(contrato__tercero__codigo__icontains=f["doc_contratista"])
    acc = defaultdict(lambda: {"n": 0, "valor": Decimal("0"), "nombres": set()})
    for r in pares:
        d = acc[r["proyecto_id"]]
        d["n"] += 1
        d["valor"] += r["contrato__valor_contrato"] or 0
        if r["contrato__tercero__nombre"]:
            d["nombres"].add(r["contrato__tercero__nombre"])
    return acc


def construir(f, claves):
    """Devuelve (claves_ordenadas, filas). Cada fila es un dict por proyecto."""
    claves = [c for c in ORDEN if c in claves] or list(DEF_SELECCION)

    base = (base_proyectos(f)
            .select_related("dependencia", "dependencia_responsable")
            .annotate(**_anotaciones(claves, f))
            .order_by("bpin"))
    proyectos = list(base)
    ids = [p.id for p in proyectos]

    clasif = {}
    if "clasificaciones" in claves:
        for p in Proyecto.objects.filter(id__in=ids).prefetch_related("clasificaciones"):
            clasif[p.id] = ", ".join(c.nombre for c in p.clasificaciones.all())

    contr = _contractual(ids, claves, f)

    filas = []
    for p in proyectos:
        fila = {}
        for clave in claves:
            if clave == "bpin":
                fila[clave] = p.bpin or ""
            elif clave == "nombre":
                fila[clave] = p.nombre or ""
            elif clave == "dependencia":
                fila[clave] = p.dependencia.nombre if p.dependencia_id else ""
            elif clave == "dependencia_responsable":
                fila[clave] = p.dependencia_responsable.nombre if p.dependencia_responsable_id else ""
            elif clave == "clasificaciones":
                fila[clave] = clasif.get(p.id, "")
            elif clave == "origen":
                fila[clave] = p.get_origen_display()
            elif clave == "n_contratos":
                fila[clave] = contr.get(p.id, {}).get("n", 0)
            elif clave == "valor_contratado":
                fila[clave] = contr.get(p.id, {}).get("valor", 0)
            elif clave == "contratistas":
                fila[clave] = ", ".join(sorted(contr.get(p.id, {}).get("nombres", [])))
            else:
                fila[clave] = getattr(p, "v_" + clave, None) or 0
        filas.append(fila)
    return claves, filas


# --- Excel ----------------------------------------------------------------

def a_excel(claves, filas):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Proyectos"

    verde = PatternFill("solid", fgColor="006030")
    blanco = Font(color="FFFFFF", bold=True, size=11)
    borde = Border(bottom=Side(style="thin", color="D0D5DD"))
    negrita = Font(bold=True)

    # encabezado
    for col, clave in enumerate(claves, start=1):
        c = ws.cell(row=1, column=col, value=META[clave]["label"])
        c.fill = verde
        c.font = blanco
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # datos
    for i, fila in enumerate(filas, start=2):
        for col, clave in enumerate(claves, start=1):
            c = ws.cell(row=i, column=col, value=fila[clave])
            c.border = borde
            tipo = META[clave]["tipo"]
            if tipo == "money":
                c.number_format = '#,##0'
                c.alignment = Alignment(horizontal="right")
            elif tipo == "entero":
                c.number_format = '#,##0'
                c.alignment = Alignment(horizontal="right")

    # fila de totales para las columnas numericas
    if filas:
        tot_row = len(filas) + 2
        primera = True
        for col, clave in enumerate(claves, start=1):
            tipo = META[clave]["tipo"]
            if tipo in ("money", "entero"):
                total = sum((f[clave] or 0) for f in filas)
                c = ws.cell(row=tot_row, column=col, value=total)
                c.number_format = '#,##0'
                c.font = negrita
                c.alignment = Alignment(horizontal="right")
            elif primera:
                ws.cell(row=tot_row, column=col, value="TOTAL").font = negrita
                primera = False

    # anchos
    anchos = {"texto": 32, "money": 18, "entero": 12}
    for col, clave in enumerate(claves, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = \
            anchos[META[clave]["tipo"]]
    ws.freeze_panes = "A2"
    return wb
