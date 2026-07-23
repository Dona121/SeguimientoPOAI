# -*- coding: utf-8 -*-
"""Ejerce el flujo real del admin: subir el xlsx en el formulario y procesarlo con la accion.

    uv run python prueba_admin.py
"""
import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import Client  # noqa: E402

from siifweb.models import CargaReporte, Cdp, CdpImputacion  # noqa: E402

RUTA = Path(r"C:\Users\Donal\Documents\MEGA\Reportes\plan_indicativo\Plataformas\SIIFWEB"
            r"\Informes\Consolidado disponibilidades"
            r"\consolidado_certificado_disponibilidad_presupuestal_2023_1Enero_31Diciembre.xlsx")

def mensajes(respuesta):
    """Los mensajes del admin, sea que vengan del contexto o de la cookie de sesion."""
    contexto = respuesta.context
    if contexto and "messages" in contexto:
        return [m.message for m in contexto["messages"]]
    from django.contrib.messages import get_messages
    return [m.message for m in get_messages(respuesta.wsgi_request)]


from django.contrib.auth import get_user_model
cliente = Client()
admin_user = get_user_model().objects.filter(is_superuser=True).first()
assert admin_user, "no hay ningun superusuario en la base"
cliente.force_login(admin_user)

# Deja el escenario limpio para que la prueba sea repetible
CdpImputacion.objects.filter(cdp__vigencia=2023).delete()
Cdp.objects.filter(vigencia=2023).delete()
CargaReporte.objects.filter(tipo_reporte="cdp", vigencia=2023).delete()

antes_cdp = Cdp.objects.filter(vigencia=2023).count()
print(f"CDPs 2023 antes: {antes_cdp}")

# 1. Subir el archivo por el formulario de "Añadir carga del reporte"
with RUTA.open("rb") as archivo:
    respuesta = cliente.post("/admin/siifweb/cargareporte/add/", {
        "tipo_reporte": "cdp",
        "vigencia": "2023",
        "archivo": archivo,
        "fecha_descarga": "2026-07-18",
    }, follow=True)
print(f"1. Subida del archivo: HTTP {respuesta.status_code}")
for m in mensajes(respuesta):
    print(f"   mensaje: {m}")

carga = CargaReporte.objects.latest("id")
print(f"   registro creado: {carga.tipo_reporte} {carga.vigencia} | estado={carga.estado} "
      f"| hash={carga.hash[:16]}...")

# 2. Ejecutar la accion "Procesar los reportes seleccionados" sobre ese registro
respuesta = cliente.post("/admin/siifweb/cargareporte/", {
    "action": "procesar_cargas",
    "_selected_action": [str(carga.pk)],
}, follow=True)
print(f"2. Accion de procesar: HTTP {respuesta.status_code}")
for m in mensajes(respuesta):
    print(f"   mensaje: {m}")

carga.refresh_from_db()
print(f"\n3. Resultado en el registro: estado={carga.get_estado_display()} | filas={carga.filas}")
print(f"   CDPs 2023 despues: {Cdp.objects.filter(vigencia=2023).count()}")
print(f"   Imputaciones 2023: {CdpImputacion.objects.filter(cdp__vigencia=2023).count()}")
print(f"   Ligadas a esta carga: {CdpImputacion.objects.filter(reporte=carga).count()}")

# 4. El hash impide cargar dos veces el mismo archivo
with RUTA.open("rb") as archivo:
    respuesta = cliente.post("/admin/siifweb/cargareporte/add/", {
        "tipo_reporte": "cdp", "vigencia": "2023", "archivo": archivo,
        "fecha_descarga": "2026-07-18",
    })
duplicados = CargaReporte.objects.filter(hash=carga.hash).count()
errores = respuesta.context["adminform"].form.errors if respuesta.context else {}
print(f"\n4. Reintento del mismo archivo:")
print(f"   registros con ese hash: {duplicados} (debe ser 1)")
for lista in errores.values():
    for texto in lista:
        print(f"   error mostrado al usuario: {texto}")
