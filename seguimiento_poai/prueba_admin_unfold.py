# -*- coding: utf-8 -*-
"""Verifica que todas las paginas del admin cargan y que los inlines traen datos.

    uv run python prueba_admin_unfold.py
"""
import os
import re

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

from siifweb.models import Cdp, Compromiso, Contrato, Obligacion, Reserva  # noqa: E402

admin_user = get_user_model().objects.filter(is_superuser=True).first()
assert admin_user, "no hay ningun superusuario en la base"
cliente = Client()
cliente.force_login(admin_user)

LISTADOS = ["proyecto", "cargareporte", "cdp", "compromiso", "obligacion", "reserva",
            "contrato", "contratoacta", "contratoimputacion", "cdpimputacion",
            "compromisoimputacion", "obligacionimputacion", "reservaimputacion",
            "tercero", "rubro", "fuente", "centrocosto", "ordengasto"]

print("1. LISTADOS")
fallas = 0
for modelo in LISTADOS:
    r = cliente.get(f"/admin/siifweb/{modelo}/")
    unfold = "unfold" in r.content.decode("utf-8", "ignore")[:8000]
    marca = "OK " if r.status_code == 200 else "FALLA"
    if r.status_code != 200:
        fallas += 1
    print(f"   [{marca}] {modelo:26} HTTP {r.status_code}  unfold={'si' if unfold else 'NO'}")

print("\n2. DETALLES CON INLINES (cuantas filas trae cada inline)")
casos = [
    ("cdp", Cdp.objects.get(vigencia=2024, nro_cdp="425").pk,
     ["cdps_imputados", "compromisos_imputados", "reservas_imputadas"]),
    ("compromiso", Compromiso.objects.get(vigencia=2024, nro_rp="2420").pk,
     ["compromisos_imputados", "obligaciones_imputadas", "imputaciones_del_contrato"]),
    ("obligacion", Obligacion.objects.filter(vigencia=2025).first().pk,
     ["obligaciones_imputadas"]),
    ("reserva", Reserva.objects.filter(vigencia=2025).first().pk, ["reservas_imputadas"]),
    ("contrato", Contrato.objects.filter(actas_del_contrato__isnull=False).first().pk,
     ["actas_del_contrato", "imputaciones_del_contrato"]),
]
for modelo, pk, inlines in casos:
    r = cliente.get(f"/admin/siifweb/{modelo}/{pk}/change/")
    html = r.content.decode("utf-8", "ignore")
    detalle = []
    for inline in inlines:
        # cada fila del inline lleva el prefijo del formset en sus inputs ocultos
        filas = len(set(re.findall(rf"{inline}-(\d+)-id", html)))
        detalle.append(f"{inline}={filas}")
    marca = "OK " if r.status_code == 200 else "FALLA"
    if r.status_code != 200:
        fallas += 1
    print(f"   [{marca}] {modelo:16} pk={pk:<6} " + "  ".join(detalle))

print(f"\n{'TODO OK' if fallas == 0 else str(fallas) + ' FALLAS'}")
