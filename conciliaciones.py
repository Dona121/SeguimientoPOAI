# -*- coding: utf-8 -*-
"""Suite de conciliaciones de las bases SIIFWEB.

Uso:  uv run python conciliaciones.py

Valida, para cada relacion del modelo:
  1. Unicidad del grano declarado (la PK logica no tiene duplicados)
  2. Que el join no multiplique filas
  3. Que los agregados de la tabla hija coincidan al peso con los arrastrados del padre

Resultado esperado: todo OK salvo las excepciones documentadas (2023: 35 obligaciones
de reservas; ordengasto: duplicados por adiciones). Cualquier otra linea FALLA es un
cambio en la fuente o un error de pipeline.
"""
from pathlib import Path

import polars as pl

D = Path(__file__).parent / "data" / "parquet"
TOL = 1.0  # tolerancia contable: un peso

fallas = []


def cod(c):
    return pl.col(c).cast(pl.Utf8).str.replace(r"\.0$", "").alias(c)


def num(c):
    return pl.col(c).cast(pl.Utf8).str.replace(",", ".").cast(pl.Float64, strict=False).alias(c)


def carga(base, codigos=(), numericos=()):
    dfs = []
    for f in sorted(D.glob(f"{base}_*.parquet")):
        if base == "ordenes" and "estado" not in f.name:
            continue
        df = pl.read_parquet(f)
        df = df.with_columns([cod(c) for c in codigos if c in df.columns]
                             + [num(c) for c in numericos if c in df.columns])
        dfs.append(df)
    return pl.concat(dfs, how="diagonal_relaxed")


def check(nombre, condicion, detalle=""):
    estado = "OK   " if condicion else "FALLA"
    print(f"  [{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
    if not condicion:
        fallas.append(nombre)


cdp = carga("cdp", ["NRO_CDP", "PROYECTO", "FONDO"])
com = carga("compromisos", ["NRO_RP", "NRODOC_CDP", "PROYECTO", "FONDO"])
obl = carga("obligaciones", ["NRO_OBLIGACION", "NRO_RP", "NRO_ORDEN_GASTO", "PROYECTO", "FONDO"])
res = carga("reservas", ["NRO_RESERVA", "NUMERO_CDP", "FONDO"],
            ["VALOR_RESERVA", "VALOR_RESERVA_DEF", "SALDO_RESERVA", "OBLIGACIONES_RESERVA", "PAGOS_RESERVA"])
og = carga("ordengasto", ["NRO_CONTRATO", "COMPROMISO", "CDP"], ["TOTAL", "VALOR", "IVA"])
cxp = carga("cxp", ["NRO_CXP", "NRO_RP", "FONDO"])
hist = pl.read_parquet(D / "historial_contratos_imputaciones.parquet").with_columns(
    cod("NRODOC"), cod("PROYECTO"), cod("RECURSO"),
    pl.col("PREFIJO").cast(pl.Int64, strict=False).alias("PREFIJO"))

G_CDP = ["VIGENCIA", "NRO_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO"]
G_RP = ["VIGENCIA", "NRO_RP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO"]
G_OBL = ["VIGENCIA", "NRO_OBLIGACION", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO"]

print("=" * 72)
print("1. GRANO DECLARADO (informativo: un documento puede tener varias lineas")
print("   sobre la misma imputacion; SIEMPRE agregar antes de cruzar)")
print("=" * 72)
for nombre, df, grano in [("cdp", cdp, G_CDP), ("compromisos", com, G_RP), ("obligaciones", obl, G_OBL),
                          ("reservas", res, ["VIGENCIA", "NRO_RESERVA", "IDENTIFICACION_PRESUPUESTAL", "FONDO"]),
                          ("cxp", cxp, ["VIGENCIA", "NRO_CXP", "IDENTIFICACION_PRESUPUESTAL", "FONDO"])]:
    dups = df.group_by(grano).len().filter(pl.col("len") > 1)
    print(f"  [NOTA ] {nombre}: {df.height} filas, {dups.height} llaves del grano con lineas multiples")
dups_og = og.group_by("VIGENCIA", "PREFIJO", "NRO_CONTRATO", "COMPROMISO").len().filter(pl.col("len") > 1)
print(f"  [NOTA ] ordengasto: {dups_og.height} llaves con filas multiples (adiciones/actas; "
      "deduplicar con .first()/.max() antes de usar)")

print()
print("=" * 72)
print("2. COMPROMISOS -> CDP (igualdad de arrastrados, grano imputacion x proyecto)")
print("=" * 72)
a = cdp.group_by(G_CDP).agg(pl.col("VALOR_COMPROMISOS").sum())
b = com.group_by("VIGENCIA", "NRODOC_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO") \
       .agg(pl.col("VALOR_COMPROMISO_DEF").sum())
j = a.join(b, left_on=G_CDP,
           right_on=["VIGENCIA", "NRODOC_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO"],
           how="full", coalesce=True)
check("join sin multiplicacion", j.height == max(a.height, b.height),
      f"{a.height} cdp / {b.height} rp / {j.height} resultado")
dif = j.with_columns((pl.col("VALOR_COMPROMISOS").fill_null(0)
                      - pl.col("VALOR_COMPROMISO_DEF").fill_null(0)).abs().alias("d")).filter(pl.col("d") >= TOL)
check("agregados coinciden al peso", dif.height == 0, f"{dif.height} descuadres")

print()
print("=" * 72)
print("3. OBLIGACIONES -> COMPROMISOS (con clasificacion de origen)")
print("=" * 72)
rps_v = com.select("VIGENCIA", "NRO_RP").unique()
obl_c = (obl.join(rps_v.with_columns(pl.lit(True).alias("en_v")), on=["VIGENCIA", "NRO_RP"], how="left")
         .join(rps_v.select((pl.col("VIGENCIA") + 1).alias("VIGENCIA"), "NRO_RP",
                            pl.lit(True).alias("en_v1")), on=["VIGENCIA", "NRO_RP"], how="left")
         .with_columns(pl.when(pl.col("en_v")).then(pl.lit("vigencia"))
                       .when(pl.col("en_v1")).then(pl.lit("reserva"))
                       .otherwise(pl.lit("anomalia")).alias("origen")))
exc = obl_c.filter(pl.col("origen") != "vigencia")
resumen_exc = exc.group_by("VIGENCIA", "origen").agg(pl.len(), pl.col("VALOR_OBLI_DEF").sum())
esperado = (exc.height == 35 and exc.filter(pl.col("origen") == "anomalia").height == 0
            and exc["VIGENCIA"].unique().to_list() == [2023])
check("excepciones = solo las 35 reservas de 2023, cero anomalias", esperado,
      str(resumen_exc.to_dicts()) if not esperado else "35 filas de reserva en 2023")
a = com.group_by(G_RP).agg(pl.col("OBLIGACIONES").sum(), pl.col("PAGOS").sum())
b = obl_c.filter(pl.col("origen") == "vigencia").group_by(G_RP) \
         .agg(pl.col("VALOR_OBLI_DEF").sum().alias("obli"), pl.col("PAGOS").sum().alias("pagos_o"))
j = a.join(b, on=G_RP, how="full", coalesce=True)
d1 = j.filter((pl.col("OBLIGACIONES").fill_null(0) - pl.col("obli").fill_null(0)).abs() >= TOL)
# Excepcion documentada: 24 imputaciones de obligacion cuya combinacion rubro/fondo/proyecto
# no existe en su RP (0,06%). Hallazgo de fuente, verificado; si crece, investigar.
HUERFANAS_CONOCIDAS = 24
check(f"obligado arrastrado == obligado real (tolera {HUERFANAS_CONOCIDAS} huerfanas de imputacion conocidas)",
      d1.height <= HUERFANAS_CONOCIDAS, f"{d1.height} descuadres")
d2 = j.filter((pl.col("PAGOS").fill_null(0) - pl.col("pagos_o").fill_null(0)).abs() >= TOL)
check("pagado arrastrado == pagado real (misma tolerancia)",
      d2.height <= HUERFANAS_CONOCIDAS, f"{d2.height} descuadres")

print()
print("=" * 72)
print("4. IDENTIDADES INTERNAS (saldo = definitivo - etapa siguiente)")
print("=" * 72)
for nombre, df, expr in [
    ("cdp: SALDO_CERTF", cdp, (pl.col("SALDO_CERTF") - (pl.col("VALOR_DISPONIBILIDAD_DEF") - pl.col("VALOR_COMPROMISOS")))),
    ("compromisos: SALDO_RP", com, (pl.col("SALDO_RP") - (pl.col("VALOR_COMPROMISO_DEF") - pl.col("OBLIGACIONES")))),
    ("obligaciones: SALDO_OBLI", obl, (pl.col("SALDO_OBLI") - (pl.col("VALOR_OBLI_DEF") - pl.col("PAGOS")))),
    ("reservas: SALDO_RESERVA", res, (pl.col("SALDO_RESERVA") - (pl.col("VALOR_RESERVA_DEF") - pl.col("OBLIGACIONES_RESERVA")))),
    ("cxp: SALDO_CXP", cxp, (pl.col("SALDO_CXP") - (pl.col("VALOR_CXP_DEF") - pl.col("PAGOS")))),
]:
    malas = df.filter(expr.abs() >= TOL)
    check(nombre, malas.height == 0, f"{malas.height} filas rotas" if malas.height else f"{df.height} filas")

print()
print("=" * 72)
print("5. SALTOS TEMPORALES (reservas y cxp -> vigencia anterior)")
print("=" * 72)
r = res.with_columns((pl.col("VIGENCIA") - 1).alias("VO"))
cdp_u = cdp.select(pl.col("VIGENCIA").alias("VO"), pl.col("NRO_CDP").alias("NUMERO_CDP"),
                   "IDENTIFICACION_PRESUPUESTAL", "FONDO").unique().with_columns(pl.lit(True).alias("ok"))
j = r.join(cdp_u, on=["VO", "NUMERO_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO"], how="left")
check("toda reserva tiene su CDP en v-1 (mismo rubro y fondo)",
      j.filter(pl.col("ok").is_null()).height == 0)
saldos = com.group_by(pl.col("VIGENCIA").alias("VO"), pl.col("NRODOC_CDP").alias("NUMERO_CDP"),
                      "IDENTIFICACION_PRESUPUESTAL", "FONDO").agg(pl.col("SALDO_RP").sum())
jt = (r.group_by("VO", "NUMERO_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO")
      .agg(pl.col("VALOR_RESERVA").sum())
      .join(saldos, on=["VO", "NUMERO_CDP", "IDENTIFICACION_PRESUPUESTAL", "FONDO"], how="left"))
check("reserva <= saldo comprometido sin obligar (cota)",
      jt.filter(pl.col("VALOR_RESERVA") > pl.col("SALDO_RP").fill_null(0) + TOL).height == 0)
c = cxp.with_columns((pl.col("VIGENCIA") - 1).alias("VO"))
obl_u = obl.select(pl.col("VIGENCIA").alias("VO"), pl.col("NRO_OBLIGACION").alias("NRO_CXP")) \
           .unique().with_columns(pl.lit(True).alias("ok"))
j = c.join(obl_u, on=["VO", "NRO_CXP"], how="left")
sin = j.filter(pl.col("ok").is_null())
check("toda cxp nace de una obligacion de v-1 (99% conocido)", sin.height <= 15,
      f"{sin.height} sin origen ({j.height} filas)")

print()
print("=" * 72)
print("6. VISTA CONTRACTUAL (ordengasto e historial -> cadena)")
print("=" * 72)
rp_u = com.select("VIGENCIA", "NRO_RP").unique().with_columns(pl.lit(True).alias("ok"))
og_con_rp = og.filter(pl.col("COMPROMISO").is_not_null() & (pl.col("COMPROMISO") != "None"))
j = og_con_rp.join(rp_u, left_on=["VIGENCIA", "COMPROMISO"], right_on=["VIGENCIA", "NRO_RP"], how="left")
# 1 huerfano conocido (contrato 1/2024, V.P. GLOBAL, COMPROMISO 11)
check("ordengasto: todo COMPROMISO no nulo existe en compromisos (tolera 1 conocido)",
      j.filter(pl.col("ok").is_null()).height <= 1,
      f"{j.filter(pl.col('ok').is_null()).height} huerfanos de {og_con_rp.height}")
cdp_u2 = cdp.select("VIGENCIA", "NRO_CDP").unique().with_columns(pl.lit(True).alias("ok"))
j = og.join(cdp_u2, left_on=["VIGENCIA", "CDP"], right_on=["VIGENCIA", "NRO_CDP"], how="left")
check("ordengasto: todo CDP existe en disponibilidades", j.filter(pl.col("ok").is_null()).height == 0)
com_g = com.select(pl.col("VIGENCIA"), "NRO_RP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO") \
           .unique().with_columns(pl.lit(True).alias("ok"))
h = hist.filter(pl.col("PREFIJO").is_in(sorted(cdp["VIGENCIA"].unique().to_list())))
j = h.join(com_g, left_on=["PREFIJO", "NRODOC", "RUBRO", "RECURSO", "PROYECTO"],
           right_on=["VIGENCIA", "NRO_RP", "IDENTIFICACION_PRESUPUESTAL", "FONDO", "PROYECTO"], how="left")
tasa = j.filter(pl.col("ok")).height / max(h.height, 1)
check("historial imputaciones -> compromisos al grano con proyecto (>=99%)", tasa >= 0.99,
      f"{tasa:.1%} de {h.height} | sin multiplicacion: {j.height == h.height}")

print()
print("=" * 72)
print("7. BITACORA vs CONSOLIDADOS (totales por vigencia disponible)")
print("=" * 72)
for f in sorted(D.glob("comprobantes_*.parquet")):
    cb = pl.read_parquet(f)
    v = int(cb["VIGENCIA"][0])
    tipos = dict(cb.group_by("TIPO_COMPPTAL").agg(pl.col("VALOR").sum()).iter_rows())
    pares = [
        ("DISPONIBILIDAD == cdp.certificado", tipos.get("DISPONIBILIDAD", 0),
         cdp.filter(pl.col("VIGENCIA") == v)["VALOR_CERTIFICADO"].sum()),
        ("COMPROMISO == compromisos.registro", tipos.get("COMPROMISO", 0),
         com.filter(pl.col("VIGENCIA") == v)["VALOR_REGISTRO"].sum()),
        ("OBLIGACION == obligaciones.obligado", tipos.get("OBLIGACION", 0),
         obl.filter(pl.col("VIGENCIA") == v)["VALOR_OBLIGACION"].sum()),
        ("PAGO == obligaciones.pagos", tipos.get("PAGO", 0),
         obl.filter(pl.col("VIGENCIA") == v)["PAGOS"].sum()),
        ("CXP == cxp.constituido", tipos.get("CXP", 0),
         cxp.filter(pl.col("VIGENCIA") == v)["VALOR_CXP"].sum()),
        ("RESERVA == reservas.constituido", tipos.get("RESERVA", 0),
         res.filter(pl.col("VIGENCIA") == v)["VALOR_RESERVA"].sum()),
    ]
    for nombre, x, y in pares:
        check(f"{v}: {nombre}", abs((x or 0) - (y or 0)) < TOL, f"{x:,.0f} vs {y:,.0f}")

print()
print("=" * 72)
if fallas:
    print(f"RESULTADO: {len(fallas)} FALLAS — revisar antes de usar los datos:")
    for x in fallas:
        print("  -", x)
else:
    print("RESULTADO: todas las conciliaciones pasan. El pipeline esta sano.")
