# -*- coding: utf-8 -*-
"""Carga las vigencias faltantes en el orden que exigen los FK.

    uv run python cargar_todo.py

Orden: por vigencia ascendente (cdp -> compromisos -> obligaciones), luego las reservas
(que apuntan a los CDP de v-1) y al final el historial, para que enganche con los RP de
todas las vigencias ya cargadas.
"""
import hashlib
import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.files import File  # noqa: E402

from siifweb import cargas  # noqa: E402
from siifweb.models import CargaReporte, Contrato, ContratoActa, ContratoImputacion  # noqa: E402

BASE = Path(r"C:\Users\Donal\Documents\MEGA\Reportes\plan_indicativo\Plataformas\SIIFWEB\Informes")

# 2026 corta el 15 de julio en cdp, compromisos y obligaciones: se usa esa foto en los tres
# para que las conciliaciones comparen el mismo dia.
ARCHIVOS = {
    ("cdp", 2022): "Consolidado disponibilidades/consolidado_certificado_disponibilidad_presupuestal_2022_1Enero_31Diciembre.xlsx",
    ("compromisos", 2022): "Consolidado compromisos/consolidado_compromisosw_2022_1Enero_31Diciembre.xlsx",
    ("obligaciones", 2022): "Consolidado obligaciones/consolidado_obligacionw_2022_1Enero_31Diciembre.xlsx",
    ("cdp", 2023): "Consolidado disponibilidades/consolidado_certificado_disponibilidad_presupuestal_2023_1Enero_31Diciembre.xlsx",
    ("compromisos", 2023): "Consolidado compromisos/consolidado_compromisosw_2023_1Enero_31Diciembre.xlsx",
    ("obligaciones", 2023): "Consolidado obligaciones/consolidado_obligacionw_2023_1Enero_31Diciembre.xlsx",
    ("reservas", 2024): "Consolidado reservas/consolidado_reservaw_2024_1Enero_31Diciembre.xlsx",
    ("cdp", 2026): "Consolidado disponibilidades/consolidado_certificado_disponibilidad_presupuestal_2026_1Enero_15Julio.xlsx",
    ("compromisos", 2026): "Consolidado compromisos/consolidado_compromisosw_2026_1Enero_15Julio.xlsx",
    ("obligaciones", 2026): "Consolidado obligaciones/consolidado_obligacionw_2026_1Enero_15Julio.xlsx",
    ("reservas", 2026): "Consolidado reservas/consolidado_reservaw_2026_1Enero_16Julio.xlsx",
}

HISTORIAL = "Historial de orden de gasto 2/historial_ordengasto2_01012022_20260718.xlsx"


def cargar(tipo, vigencia, relativa):
    ruta = BASE / relativa
    if not ruta.exists():
        print(f"  FALTA  {tipo} {vigencia}: {ruta.name}")
        return
    digest = hashlib.sha256(ruta.read_bytes()).hexdigest()
    if CargaReporte.objects.filter(hash=digest).exists():
        print(f"  ya cargado  {tipo} {vigencia or 'rango'}")
        return
    carga = CargaReporte(tipo_reporte=tipo, vigencia=vigencia, hash=digest)
    with ruta.open("rb") as archivo:
        carga.archivo.save(ruta.name, File(archivo), save=True)
    marca = "OK   " if cargas.procesar(carga) else "ERROR"
    print(f"  {marca} {tipo} {vigencia or 'rango'}: {carga.mensaje}")


print("1. VIGENCIAS FALTANTES")
for (tipo, vigencia), relativa in ARCHIVOS.items():
    cargar(tipo, vigencia, relativa)

print("\n2. HISTORIAL (se recarga para reenganchar los RP de todas las vigencias)")
ContratoImputacion.objects.all().delete()
ContratoActa.objects.all().delete()
Contrato.objects.all().delete()
CargaReporte.objects.filter(tipo_reporte="historial").delete()
cargar("historial", None, HISTORIAL)
