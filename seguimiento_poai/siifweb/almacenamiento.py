"""Almacenamiento con nombres de archivo que acepta el bucket de Supabase.

Supabase responde 400 (Bad Request) a las llaves con caracteres fuera de ASCII: un archivo
llamado "Guía año 2026.pdf" no se podia subir (fallaba al revisar si ya existia). Estas clases
limpian el nombre antes de guardarlo, en todas las cargas del aplicativo: tildes y enes se
quitan ("Guía año" queda "Guia_ano"), los espacios y simbolos pasan a "_" y la extension queda
en minusculas. Solo cambia el nombre con que se guarda; la descripcion del registro no se toca.
"""
import re
import unicodedata

from django.core.files.storage import FileSystemStorage
from storages.backends.s3 import S3Storage


def _ascii(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def nombre_seguro(nombre):
    """La ruta con cada parte en letras, numeros, punto, guion y guion bajo (ASCII)."""
    partes = []
    for parte in nombre.replace("\\", "/").split("/"):
        if not parte:
            continue
        base, punto, extension = parte.rpartition(".")
        if not punto or not base:
            base, extension = parte, ""
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", _ascii(base)).strip("._") or "archivo"
        extension = re.sub(r"[^A-Za-z0-9]+", "", _ascii(extension)).lower()
        partes.append(base + (f".{extension}" if extension else ""))
    return "/".join(partes)


class NombresSeguros:
    """get_valid_name lo usan los FileField al armar el nombre; get_available_name, cualquier
    save() del almacenamiento. Con los dos no hay forma de guardar un nombre que el bucket rechace."""

    def get_valid_name(self, name):
        return super().get_valid_name(nombre_seguro(name))

    def get_available_name(self, name, max_length=None):
        return super().get_available_name(nombre_seguro(name), max_length=max_length)


class S3NombresSeguros(NombresSeguros, S3Storage):
    """El bucket de Supabase (produccion, y tambien el local: el .env apunta al mismo)."""


class ArchivosLocalesNombresSeguros(NombresSeguros, FileSystemStorage):
    """El de las pruebas: mismo criterio de nombres, en una carpeta temporal."""
