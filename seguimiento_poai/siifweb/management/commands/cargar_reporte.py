# -*- coding: utf-8 -*-
"""Carga un reporte desde consola, igual que la accion del admin.

    uv run python manage.py cargar_reporte cdp 2025 "C:\\ruta\\consolidado.xlsx"
"""
import hashlib
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from siifweb import cargas
from siifweb.models import CargaReporte


class Command(BaseCommand):
    help = "Carga un reporte xlsx de SIIFWEB a la base de datos"

    def add_arguments(self, parser):
        parser.add_argument("tipo", choices=list(cargas.PROCESADORES))
        parser.add_argument("vigencia", help="Vigencia del reporte, o 'rango' para el historial")
        parser.add_argument("ruta")

    def handle(self, *args, **opciones):
        ruta = Path(opciones["ruta"])
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")

        digest = hashlib.sha256(ruta.read_bytes()).hexdigest()
        if CargaReporte.objects.filter(hash=digest).exists():
            raise CommandError("Ese archivo ya fue cargado (mismo hash)")

        vigencia = opciones["vigencia"]
        vigencia = int(vigencia) if str(vigencia).isdigit() else None
        carga = CargaReporte(tipo_reporte=opciones["tipo"], vigencia=vigencia, hash=digest)
        with ruta.open("rb") as archivo:
            carga.archivo.save(ruta.name, File(archivo), save=True)

        if cargas.procesar(carga):
            self.stdout.write(self.style.SUCCESS(f"OK  {carga.tipo_reporte} {carga.vigencia}: {carga.mensaje}"))
        else:
            self.stdout.write(self.style.ERROR(f"ERROR  {carga.tipo_reporte} {carga.vigencia}: {carga.mensaje}"))
