# -*- coding: utf-8 -*-
"""Prueba el flujo de trabajo del equipo:

1. La vigencia en curso se recarga y la nueva informacion SUSTITUYE a la anterior.
2. Alguien del equipo crea un proyecto a mano; al cargar el reporte, la ejecucion de
   ese BPIN se engancha a su registro y no crea un duplicado.

    uv run python prueba_flujo_equipo.py
"""
import hashlib
import os
import time
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.files import File  # noqa: E402
from django.db.models import Sum  # noqa: E402

from siifweb import cargas  # noqa: E402
from siifweb.models import (CargaReporte, Cdp, CdpImputacion, Clasificacion,  # noqa: E402
                            CompromisoImputacion, ContratoImputacion, DependenciaResponsable,
                            ObligacionImputacion, Proyecto, ReservaImputacion)

BASE = Path(r"C:\Users\Donal\Documents\MEGA\Reportes\plan_indicativo\Plataformas\SIIFWEB\Informes")
CDP_2025 = BASE / ("Consolidado disponibilidades/"
                   "consolidado_certificado_disponibilidad_presupuestal_2025_1Enero_31Diciembre.xlsx")


def foto(etiqueta):
    print(f"  {etiqueta:22} "
          f"CDPs={Cdp.objects.filter(vigencia=2025).count():>5} "
          f"imputaciones={CdpImputacion.objects.filter(cdp__vigencia=2025).count():>5} "
          f"certificado={CdpImputacion.objects.filter(cdp__vigencia=2025).aggregate(t=Sum('valor_certificado'))['t'] or 0:>22,.2f}")


CONTADOR = [0]


def cargar(tipo, vigencia, ruta, forzar=False):
    """forzar: simula que el equipo bajo el reporte otra vez (archivo nuevo, hash distinto)."""
    CONTADOR[0] += 1
    datos = ruta.read_bytes()
    digest = hashlib.sha256(datos + f"recarga{time.time()}{CONTADOR[0]}".encode()).hexdigest()
    carga = CargaReporte(tipo_reporte=tipo, vigencia=vigencia, hash=digest)
    with ruta.open("rb") as archivo:
        carga.archivo.save(ruta.name, File(archivo), save=True)
    cargas.procesar(carga)
    return carga


print("=" * 78)
print("1. RECARGA DE LA VIGENCIA EN CURSO: la nueva version sustituye a la anterior")
print("=" * 78)
foto("antes de recargar")
carga = cargar("cdp", 2025, CDP_2025, forzar=True)
print(f"  -> {carga.mensaje}")
foto("despues de recargar")
print("  (los totales deben ser IDENTICOS: se reemplazo, no se acumulo)")

print()
print("=" * 78)
print("2. PROYECTO INGRESADO POR EL EQUIPO: la carga lo encuentra por su BPIN")
print("=" * 78)

# Un BPIN que ya existe en el reporte de 2025, pero lo borramos para simular que el
# equipo lo registra ANTES de que llegue el reporte.
BPIN = "2024002700170"
for modelo in (CdpImputacion, CompromisoImputacion, ObligacionImputacion,
               ReservaImputacion, ContratoImputacion):
    modelo.objects.filter(proyecto__bpin=BPIN).delete()
Proyecto.objects.filter(bpin=BPIN).delete()

# El equipo lo crea a mano, con espacios y un .0 de sobra (como saldria de Excel)
responsable, _ = DependenciaResponsable.objects.get_or_create(nombre="Educacion")
manual = Proyecto.objects.create(
    bpin=f"  {BPIN}.0  ",
    nombre="NOMBRE QUE ESCRIBIO EL EQUIPO",
    dependencia_responsable=responsable,
    origen=Proyecto.Origen.MANUAL,
)
manual.clasificaciones.set([Clasificacion.objects.get_or_create(nombre="POAI 2026")[0]])
print(f"  creado a mano: bpin guardado como '{manual.bpin}' (normalizado), id={manual.pk}")
print(f"  origen={manual.origen} | imputaciones={manual.cdps_imputados.count()}")

carga = cargar("cdp", 2025, CDP_2025, forzar=True)
print(f"  -> {carga.mensaje}")

manual.refresh_from_db()
duplicados = Proyecto.objects.filter(bpin=BPIN).count()
print()
print(f"  registros con ese BPIN: {duplicados} (debe ser 1: no se duplico)")
print(f"  imputaciones enganchadas al registro del equipo: {manual.cdps_imputados.count()}")
print(f"  certificado del proyecto: "
      f"{manual.cdps_imputados.aggregate(t=Sum('valor_certificado'))['t'] or 0:,.2f}")
print(f"  nombre conservado: '{manual.nombre}'")
print(f"  responsable conservado: '{manual.dependencia_responsable.nombre}'")
print(f"  clasificaciones conservadas: "
      f"{', '.join(manual.clasificaciones.values_list('nombre', flat=True))}")
print(f"  origen sigue siendo: {manual.origen}")

# La prueba borro las lineas de ese BPIN en las otras tablas: se recargan para dejar
# la base consistente y que las conciliaciones vuelvan a cuadrar.
print()
print("3. RESTAURANDO el resto de la cadena que toco la prueba")
for tipo, rel in (("compromisos", "Consolidado compromisos/consolidado_compromisosw_2025_1Enero_31Diciembre.xlsx"),
                  ("obligaciones", "Consolidado obligaciones/consolidado_obligacionw_2025_1Enero_31Diciembre.xlsx")):
    c = cargar(tipo, 2025, BASE / rel, forzar=True)
    print(f"  {tipo}: {c.mensaje}")
c = cargar("historial", None, BASE / "Historial de orden de gasto 2/historial_ordengasto2_01012022_20260718.xlsx", forzar=True)
print(f"  historial: {c.mensaje}")
