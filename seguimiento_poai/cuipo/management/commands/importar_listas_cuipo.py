"""manage.py importar_listas_cuipo <archivo> --version 09-2026

Importa las listas CHIP desde un archivo del disco. El archivo no se guarda en el
almacenamiento (en local, el almacenamiento es el bucket de produccion); para dejarlo en la
version, subirlo desde el admin.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from cuipo import listas
from cuipo.models import VersionListas


class Command(BaseCommand):
    help = "Importa Listas_Categoria_CUIPO_MM-AAAA.xlsx en los catálogos CHIP del CUIPO"

    def create_parser(self, prog_name, subcommand, **kwargs):
        # Django ya usa --version para mostrar su version; aqui es el nombre de las listas
        return super().create_parser(prog_name, subcommand, conflict_handler="resolve", **kwargs)

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta del libro de listas")
        parser.add_argument("--version", required=True, dest="nombre", help='Nombre de la versión, p. ej. "09-2026"')

    def handle(self, archivo, nombre, **opciones):
        ruta = Path(archivo)
        if not ruta.is_file():
            raise CommandError(f"No existe el archivo {ruta}")
        version, _ = VersionListas.objects.get_or_create(nombre=nombre)
        with ruta.open("rb") as contenido:
            bien = listas.procesar(version, contenido)
        if not bien:
            raise CommandError(version.mensaje)
        self.stdout.write(self.style.SUCCESS(f"{version}: {version.mensaje}"))
