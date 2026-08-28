# -*- coding: utf-8 -*-
"""Comprueba el tablero contra la base real, rango por rango.

    uv run python prueba_tablero.py

Las pruebas de `siifweb/tests/test_tablero.py` corren sobre datos fabricados; esto
ejerce el mismo calculo contra la sqlite cargada y contrasta cada metrica con una
consulta escrita aparte. Sirve tambien para ver de un vistazo hasta que fecha llegan
los reportes: un periodo posterior sale en cero porque el dato no existe todavia.
"""
import os

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import date  # noqa: E402

from django.db.models import Count, Sum  # noqa: E402

from siifweb import tablero  # noqa: E402
from siifweb.models import (Cdp, CdpImputacion, Compromiso, CompromisoImputacion,  # noqa: E402
                            ContratoActa, Obligacion, ObligacionImputacion)

CON_DEP = "proyecto__dependencia_responsable__isnull"


def directo(desde, hasta, vigencias=()):
    """Los mismos numeros, calculados sin pasar por tablero.py."""
    def corte(qs, fecha, vigencia):
        qs = qs.filter(**{CON_DEP: False})
        if desde:
            qs = qs.filter(**{f"{fecha}__gte": desde})
        if hasta:
            qs = qs.filter(**{f"{fecha}__lte": hasta})
        if vigencias:
            qs = qs.filter(**{f"{vigencia}__in": vigencias})
        return qs

    cdp = corte(CdpImputacion.objects, "cdp__fecha_disp", "cdp__vigencia")
    rp = corte(CompromisoImputacion.objects, "compromiso__fecha_reg", "compromiso__vigencia")
    ob = corte(ObligacionImputacion.objects, "obligacion__fecha_obli", "obligacion__vigencia")
    actas = ContratoActa.objects.filter(
        contrato__imputaciones_del_contrato__proyecto__dependencia_responsable__isnull=False)
    if desde:
        actas = actas.filter(fecha_pago__gte=desde)
    if hasta:
        actas = actas.filter(fecha_pago__lte=hasta)
    if vigencias:
        actas = actas.filter(contrato__imputaciones_del_contrato__vigencia__in=vigencias)
    return {
        "cdps": cdp.aggregate(n=Count("cdp", distinct=True))["n"],
        "rps": rp.aggregate(n=Count("compromiso", distinct=True))["n"],
        "obligaciones": ob.aggregate(n=Count("obligacion", distinct=True))["n"],
        "actas": actas.values("id").distinct().count(),
        "disponible": cdp.aggregate(t=Sum("valor_disponibilidad_def"))["t"] or 0,
        "comprometido": rp.aggregate(t=Sum("valor_compromiso_def"))["t"] or 0,
        "obligado": ob.aggregate(t=Sum("valor_obligacion"))["t"] or 0,
        "pagado": ob.aggregate(t=Sum("pagos"))["t"] or 0,
    }


print("=" * 78)
print("1. QUE HAY EN LA BASE (solo proyectos con dependencia responsable)")
print("=" * 78)
for nombre, modelo, campo in (("CDP", Cdp, "fecha_disp"), ("RP", Compromiso, "fecha_reg"),
                              ("Obligacion", Obligacion, "fecha_obli"),
                              ("Acta de pago", ContratoActa, "fecha_pago")):
    total = modelo.objects.count()
    print(f"  {nombre:14} {total:>7} registros  "
          f"min={modelo.objects.order_by(campo).values_list(campo, flat=True).first()}  "
          f"max={modelo.objects.order_by('-' + campo).values_list(campo, flat=True).first()}")

print("\n  Documentos por ano (los que tocan proyectos con dependencia):")
por_anio = (CompromisoImputacion.objects.filter(**{CON_DEP: False})
            .values("compromiso__vigencia")
            .annotate(n=Count("compromiso", distinct=True)).order_by("compromiso__vigencia"))
print("   RPs:", {r["compromiso__vigencia"]: r["n"] for r in por_anio})
por_anio = (CdpImputacion.objects.filter(**{CON_DEP: False})
            .values("cdp__vigencia").annotate(n=Count("cdp", distinct=True)).order_by("cdp__vigencia"))
print("   CDPs:", {r["cdp__vigencia"]: r["n"] for r in por_anio})

print("\n" + "=" * 78)
print("2. EL TABLERO CONTRA LA CONSULTA DIRECTA, RANGO POR RANGO")
print("=" * 78)
casos = [
    ("todo", None, None, ()),
    ("2022", date(2022, 1, 1), date(2022, 12, 31), ()),
    ("2023", date(2023, 1, 1), date(2023, 12, 31), ()),
    ("2024", date(2024, 1, 1), date(2024, 12, 31), ()),
    ("2025", date(2025, 1, 1), date(2025, 12, 31), ()),
    ("2026", date(2026, 1, 1), date(2026, 12, 31), ()),
    ("este mes (ago 2026)", date(2026, 8, 1), date(2026, 8, 31), ()),
    ("julio 2026", date(2026, 7, 1), date(2026, 7, 31), ()),
    ("semana 6-12 jul 2026", date(2026, 7, 6), date(2026, 7, 12), ()),
    ("1er trim 2025", date(2025, 1, 1), date(2025, 3, 31), ()),
    ("vigencia 2025", None, None, (2025,)),
    ("vigencia 2024+2025", None, None, (2024, 2025)),
]
fallas = 0
for nombre, desde, hasta, vigencias in casos:
    _, tot = tablero.por_dependencia(
        tablero.Filtros(desde=desde, hasta=hasta, vigencias=vigencias))
    esperado = directo(desde, hasta, vigencias)
    difs = [k for k, v in esperado.items() if (tot[k] or 0) != (v or 0)]
    marca = "OK  " if not difs else "DIF "
    if difs:
        fallas += 1
    print(f"  [{marca}] {nombre:22} cdps={tot['cdps']:>5} rps={tot['rps']:>6} "
          f"obl={tot['obligaciones']:>6} actas={tot['actas']:>6} "
          f"comprometido={tot['comprometido']:>18,.0f}")
    for k in difs:
        print(f"          ! {k}: tablero={tot[k]} directo={esperado[k]}")

print("\n" + "=" * 78)
print("3. PRESETS TAL COMO LOS CALCULA LA PAGINA (hoy =", date.today(), ")")
print("=" * 78)
for preset in ("semana", "mes", "trimestre", "anio"):
    desde, hasta = tablero.rango_del_preset(preset)
    _, tot = tablero.por_dependencia(tablero.Filtros(desde=desde, hasta=hasta))
    print(f"  {preset:10} {desde} -> {hasta}   cdps={tot['cdps']:>4} rps={tot['rps']:>5} "
          f"obl={tot['obligaciones']:>5} actas={tot['actas']:>5}")

print("\n" + "=" * 78)
print("4. UNA DEPENDENCIA, RANGO POR RANGO")
print("=" * 78)
filas, _ = tablero.por_dependencia(tablero.Filtros())
dep = filas[0]
print("  dependencia:", dep["nombre"], "| id", dep["llave"])
for nombre, desde, hasta in (("todo", None, None),
                             ("2024", date(2024, 1, 1), date(2024, 12, 31)),
                             ("2025", date(2025, 1, 1), date(2025, 12, 31)),
                             ("2026", date(2026, 1, 1), date(2026, 12, 31))):
    fila = next((f for f in tablero.por_dependencia(
        tablero.Filtros(desde=desde, hasta=hasta, dependencia=dep["llave"]))[0]), None)
    rps = (CompromisoImputacion.objects
           .filter(proyecto__dependencia_responsable=dep["llave"]))
    if desde:
        rps = rps.filter(compromiso__fecha_reg__range=(desde, hasta))
    n = rps.aggregate(n=Count("compromiso", distinct=True))["n"]
    igual = "OK " if fila["rps"] == n else "DIF"
    print(f"  [{igual}] {nombre:6} rps tablero={fila['rps']:>5} directo={n:>5} "
          f"| proyectos={fila['proyectos']} con_rp={fila['proyectos_con_rp']}")

print("\nRESULTADO:", "todo cuadra" if fallas == 0 else f"{fallas} rangos con diferencias")

print()
print("=" * 78)
print("5. SECOP II: LO CANCELADO QUEDA FUERA")
print("=" * 78)
from django.db.models import Q  # noqa: E402

from siifweb.models import BpinProceso, ContratoSecop  # noqa: E402

con_dep = Q(proyecto__dependencia_responsable__isnull=False)
ids_todos = set(BpinProceso.objects.filter(con_dep, contrato_secop__isnull=False)
                .values_list("contrato_secop", flat=True))
vivos = ContratoSecop.objects.filter(id__in=ids_todos).exclude(estado__iexact="Cancelado")
cancelados = ContratoSecop.objects.filter(id__in=ids_todos, estado__iexact="Cancelado")
print(f"  contratos de proyectos con dependencia: {len(ids_todos)}")
print(f"  cancelados descartados               : {cancelados.count():>5}  "
      f"{cancelados.aggregate(t=Sum('valor'))['t'] or 0:>28,.0f}")
print(f"  vigentes que si cuentan              : {vivos.count():>5}  "
      f"{vivos.aggregate(t=Sum('valor'))['t'] or 0:>28,.0f}")

# El total de la tabla es la suma de las filas, y un contrato que financia proyectos de
# dos dependencias cuenta en las dos. No es doble conteo: es lo que significa la fila.
compartidos = (BpinProceso.objects
               .filter(con_dep, contrato_secop__isnull=False)
               .exclude(contrato_secop__estado__iexact="Cancelado")
               .values("contrato_secop")
               .annotate(deps=Count("proyecto__dependencia_responsable", distinct=True))
               .filter(deps__gt=1))
extra_contratos = sum(c["deps"] - 1 for c in compartidos)
extra_valor = sum((ContratoSecop.objects.get(pk=c["contrato_secop"]).valor or 0) * (c["deps"] - 1)
                  for c in compartidos)
print(f"  contratos en mas de una dependencia  : {len(compartidos):>5}  "
      f"(cuentan en cada una: +{extra_contratos} contratos, +{extra_valor:,.0f})")

_, tot = tablero.por_dependencia(tablero.Filtros())
esperado_valor = (vivos.aggregate(t=Sum("valor"))["t"] or 0) + extra_valor
esperado_n = vivos.count() + extra_contratos
print(f"  valor en el tablero                  : {tot['valor_secop']:>34,.0f}  "
      f"{'OK' if (tot['valor_secop'] or 0) == esperado_valor else 'DIF'}")
print(f"  contratos en el tablero              : {tot['contratos_secop']:>5}  "
      f"{'OK' if tot['contratos_secop'] == esperado_n else 'DIF'}")
print(f"  filas marcadas con valor imposible   : {tot['secop_dudosos']:>5}")
