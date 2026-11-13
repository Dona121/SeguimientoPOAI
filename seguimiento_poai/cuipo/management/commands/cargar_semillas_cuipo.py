"""manage.py cargar_semillas_cuipo <archivo>

Carga las homologaciones de fuentes y rubros de un libro de semillas (por ejemplo
Semillas_CUIPO_T3_2026.xlsx). Solo crea lo que falta; no cambia lo existente.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from cuipo import semillas


class Command(BaseCommand):
    help = "Carga las semillas de homologación de fuentes y rubros del CUIPO"

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta del libro de semillas")

    def handle(self, archivo, **opciones):
        ruta = Path(archivo)
        if not ruta.is_file():
            raise CommandError(f"No existe el archivo {ruta}")
        try:
            with ruta.open("rb") as contenido:
                mensaje = semillas.cargar(contenido)
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(self.style.SUCCESS(mensaje))
