"""Procesa un archivo local de regalias: la matriz o un reporte de GESPROY.

    manage.py cargar_regalias matriz   "ruta/MatrizSeguimientoEvaluacion.xlsx"
    manage.py cargar_regalias proyectos "ruta/CG-proy.xlsx"
    manage.py cargar_regalias contratos "ruta/CG-cttos.xlsx"
    manage.py cargar_regalias cargue    "ruta/CG-carga.xlsx"

Deja la CargaRegalias con su resultado, como el admin, pero no sube el archivo al
almacenamiento: en este proyecto el almacenamiento por defecto es el bucket de produccion.
Por eso la carga queda sin archivo y con el nombre original. Orden: matriz, CG-proy,
CG-cttos, CG-carga. Antes de correrlo, DATABASE_URL tiene que apuntar a la base que se
quiere cargar (ver respaldo_claude/memory/pruebas-en-sqlite-local.md).
"""
import hashlib
from datetime import datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from regalias.cargas import procesar
from regalias.models import CargaRegalias


class Command(BaseCommand):
    help = "Procesa un archivo local de regalías (matriz, proyectos, contratos o cargue)."

    def add_arguments(self, parser):
        parser.add_argument("tipo", choices=CargaRegalias.Tipo.values)
        parser.add_argument("ruta")
        parser.add_argument("--fecha", help="Fecha de descarga dd/mm/aaaa (por defecto, hoy)")
        parser.add_argument("--usuario", help="Usuario que queda en la carga y en el historial")
        parser.add_argument("--repetir", action="store_true",
                            help="Procesar aunque el mismo archivo ya esté cargado con ese tipo")

    def handle(self, tipo, ruta, fecha=None, usuario=None, repetir=False, **opciones):
        archivo = Path(ruta)
        if not archivo.is_file():
            raise CommandError(f"No existe el archivo {archivo}")
        digest = hashlib.sha256(archivo.read_bytes()).hexdigest()
        previa = CargaRegalias.objects.filter(tipo=tipo, hash=digest).first()
        if previa and not repetir:
            raise CommandError(f"Este archivo ya está cargado como '{previa}' (carga {previa.pk}). "
                               "Use --repetir para procesarlo otra vez.")
        persona = None
        if usuario:
            persona = get_user_model().objects.filter(username=usuario).first()
            if persona is None:
                raise CommandError(f"No existe el usuario {usuario}")
        descarga = datetime.strptime(fecha, "%d/%m/%Y").date() if fecha else timezone.localdate()

        carga = CargaRegalias.objects.create(tipo=tipo, nombre_archivo=archivo.name, hash=digest,
                                             fecha_descarga=descarga, usuario=persona)
        procesar(carga, archivo)
        estilo = self.style.SUCCESS if carga.estado == CargaRegalias.Estado.PROCESADO else self.style.ERROR
        self.stdout.write(estilo(f"Carga {carga.pk} ({carga.get_estado_display()})"))
        self.stdout.write(self._para_la_consola(carga.mensaje))

    def _para_la_consola(self, texto):
        """La consola de Windows (cp1252) no tiene la flecha de "Cambios de estado" y el
        comando fallaba despues de procesar. Lo que no se puede mostrar se reemplaza; el mensaje
        completo queda en la carga."""
        codificacion = getattr(self.stdout._out, "encoding", None) or "utf-8"
        return texto.encode(codificacion, errors="replace").decode(codificacion)
