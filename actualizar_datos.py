# -*- coding: utf-8 -*-
"""Regenera data/parquet a partir de los exportes xlsx de SIIFWEB.

Uso:  uv run python actualizar_datos.py [--forzar]
Con --forzar reconvierte todo; sin el, solo los archivos que no existan.
"""
import re
import sys
import time
from pathlib import Path

import pandas as pd

INFORMES = Path(r"C:\Users\Donal\Documents\MEGA\Reportes\plan_indicativo\Plataformas\SIIFWEB\Informes")
DOCS = Path(r"C:\Users\Donal\Documents")
OUT = Path(__file__).parent / "data" / "parquet"

FUENTES = {
    "cdp": INFORMES / "Consolidado disponibilidades",
    "ingresos": INFORMES / "Ingresos por rubro",
    "reservas": INFORMES / "Consolidado reservas",
    "ordengasto": INFORMES / "Orden de gasto",
    "obligaciones": DOCS / "Consolidado obligaciones",
    "compromisos": DOCS / "Consolidado compromisos",
    "cxp": INFORMES / "Consolidado cuentas por pagar",
    "comprobantes": INFORMES / "Comprobante por centro de costo",
}

# columnas numericas que en el xlsx vienen como texto con coma decimal
NUMERICAS = {
    "ingresos": ["VALOR", "CARGOS", "SALDO"],
    "obligaciones": ["VALOR_OBLIGACION", "VALOR_OBLI_DEF", "SALDO_OBLI", "PAGOS"],
    "compromisos": ["VALOR_REGISTRO", "VALOR_COMPROMISO_DEF", "SALDO_RP", "OBLIGACIONES", "PAGOS"],
    "cxp": ["VALOR_CXP", "VALOR_CXP_DEF", "SALDO_CXP", "PAGOS"],
    "comprobantes": ["VALOR"],
}

forzar = "--forzar" in sys.argv
OUT.mkdir(parents=True, exist_ok=True)

for alias, carpeta in FUENTES.items():
    for f in sorted(carpeta.glob("*.xlsx")):
        anio = re.search(r"(20\d\d)", f.name).group(1)
        destino = OUT / f"{alias}_{anio}.parquet"
        if destino.exists() and not forzar:
            continue
        t0 = time.time()
        df = pd.read_excel(f, dtype={c: str for c in NUMERICAS.get(alias, [])})
        for c in NUMERICAS.get(alias, []):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
        if alias in ("ingresos", "comprobantes") and "FECHA" in df.columns:
            df["FECHA"] = pd.to_datetime(df["FECHA"], format="%d/%m/%Y", errors="coerce")
        df["VIGENCIA"] = int(anio)
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].astype(str)
        df.to_parquet(destino, index=False)
        print(f"{alias}_{anio}: {len(df)} filas en {time.time()-t0:.0f}s")

print("Listo. Los parquet quedan en", OUT)
