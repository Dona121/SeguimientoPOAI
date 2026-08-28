# -*- coding: utf-8 -*-
"""Carga el consolidado de SECOP II y verifica las cifras medidas sobre el archivo.

    uv run python prueba_secop.py

Corre contra la sqlite local (db.sqlite3) y con almacenamiento local: no toca ni la
base de produccion ni el bucket de medios. Para apuntar a otra base, exportar
DATABASE_URL antes de ejecutarlo.
"""
import hashlib
import os
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Vacia = settings cae en la sqlite local (BASE_DIR/db.sqlite3). Como python-dotenv no
# pisa lo que ya esta en el entorno, esto neutraliza el DATABASE_URL del .env.
os.environ.setdefault("DATABASE_URL", "")
django.setup()

from django.core.files import File          # noqa: E402
from django.db import connection            # noqa: E402
from django.db.models import Count, Sum     # noqa: E402
from django.test import override_settings   # noqa: E402

from siifweb import cargas                  # noqa: E402
from siifweb.models import (BpinProceso, CargaReporte, ContratoSecop,  # noqa: E402
                            ProcesoSecop, Proyecto)

RUTA = Path(r"C:\Users\Donal\Documents\MEGA\Paginas\Siifweb\data\secop\ReporteSIIFWEB_20260814.xlsx")

# Cifras verificadas sobre la tabla BPIN_por_proceso del archivo del 14/08/2026
ESPERADO = {
    "filas_archivo": 4546,
    "procesos": 4139,
    "contratos": 3988,
    "lineas": 4534,       # 12 filas repetidas exactas se descartan
    "bpines": 244,
}

LOCAL = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def revisar(etiqueta, obtenido, esperado):
    marca = "OK  " if obtenido == esperado else "MAL "
    print(f"   {marca}{etiqueta}: {obtenido}" + ("" if obtenido == esperado else f" (esperado {esperado})"))
    return obtenido == esperado


print(f"base: {connection.settings_dict['ENGINE'].split('.')[-1]} "
      f"{connection.settings_dict.get('NAME')}")
assert RUTA.exists(), f"no existe el archivo: {RUTA}"

with override_settings(STORAGES=LOCAL):
    # Escenario repetible: se borra lo que dejo una corrida anterior
    BpinProceso.objects.all().delete()
    ContratoSecop.objects.all().delete()
    ProcesoSecop.objects.all().delete()
    CargaReporte.objects.filter(tipo_reporte="secop").delete()

    digest = hashlib.sha256(RUTA.read_bytes()).hexdigest()
    carga = CargaReporte(tipo_reporte="secop", vigencia=None, hash=digest)
    with RUTA.open("rb") as archivo:
        carga.archivo.save(RUTA.name, File(archivo), save=True)

    print("\n1. Primera carga")
    cargas.procesar(carga)
    carga.refresh_from_db()
    print(f"   estado: {carga.get_estado_display()}")
    print(f"   mensaje: {carga.mensaje}")

    bien = all([
        revisar("filas leidas del archivo", carga.filas, ESPERADO["filas_archivo"]),
        revisar("procesos", ProcesoSecop.objects.count(), ESPERADO["procesos"]),
        revisar("contratos", ContratoSecop.objects.count(), ESPERADO["contratos"]),
        revisar("filas BPIN", BpinProceso.objects.count(), ESPERADO["lineas"]),
        revisar("BPIN distintos", BpinProceso.objects.values("bpin").distinct().count(),
                ESPERADO["bpines"]),
    ])

    sin_contrato = BpinProceso.objects.filter(contrato_secop__isnull=True)
    huerfanas = BpinProceso.objects.filter(proyecto__isnull=True)
    print(f"   -   filas sin contrato adjudicado: {sin_contrato.count()} "
          f"({sin_contrato.values('proceso').distinct().count()} procesos)")
    print(f"   -   filas con BPIN fuera del catalogo: {huerfanas.count()} "
          f"({sorted(huerfanas.values_list('bpin', flat=True).distinct())})")
    print(f"   -   proyectos del catalogo con contratacion: "
          f"{BpinProceso.objects.filter(proyecto__isnull=False).values('proyecto').distinct().count()}")

    print("\n2. Idempotencia: se vuelve a procesar la misma carga")
    cargas.procesar(carga)
    carga.refresh_from_db()
    bien = all([
        bien,
        revisar("procesos", ProcesoSecop.objects.count(), ESPERADO["procesos"]),
        revisar("contratos", ContratoSecop.objects.count(), ESPERADO["contratos"]),
        revisar("filas BPIN", BpinProceso.objects.count(), ESPERADO["lineas"]),
    ])
    print(f"   mensaje: {carga.mensaje}")

    print("\n3. El libro se busca por el nombre de la tabla, no por hoja ni por archivo")
    try:
        cargas.leer_filas(cargas.stream(carga.archivo), tabla="Tabla_Que_No_Existe")
        print("   MAL  no fallo con una tabla inexistente")
        bien = False
    except ValueError as error:
        print(f"   OK   falla con mensaje claro: {str(error)[:110]}...")

    print("\n4. Contratacion por proyecto (los cinco con mas contratos)")
    top = (Proyecto.objects
           .filter(procesos_secop__contrato_secop__isnull=False)
           .annotate(contratos=Count("procesos_secop__contrato_secop", distinct=True))
           .order_by("-contratos")[:5])
    for proyecto in top:
        valor = (ContratoSecop.objects
                 .filter(bpines__proyecto=proyecto).distinct()
                 .aggregate(total=Sum("valor"))["total"] or 0)
        print(f"   {proyecto.bpin}  {(proyecto.nombre or '')[:52]:52} "
              f"{proyecto.contratos:4} contratos  ${valor:,.0f}")

    print("\n5. Contratos con valor atipico (> $100.000 millones)")
    for c in ContratoSecop.objects.filter(valor__gt=100_000_000_000).order_by("-valor"):
        print(f"   {c.referencia:20} ${c.valor:,.0f}  firma={c.fecha_firma}  estado={c.estado}")

print("\nRESULTADO:", "todo OK" if bien else "hay diferencias")
