"""Deja una sola entidad ejecutora por nombre, sin contar tildes, mayusculas ni espacios.

    manage.py homologar_entidades_ejecutoras            # muestra lo que haria, sin cambiar nada
    manage.py homologar_entidades_ejecutoras --aplicar  # lo hace

La importacion de la matriz creo "MUNICIPIO DE SINCE" y "MUNICIPIO DE SINCÉ" como dos
entidades (27/11/2026). Desde entonces la carga las reconoce con el nombre normalizado
(cargas.Catalogos.entidad_ejecutora), y este comando junta las que ya estaban repetidas:

- se queda la variante con mas tildes (la ortografia correcta); si empatan, la que tiene mas
  proyectos, y si no, la mas antigua;
- los proyectos de las otras pasan a ella con servicios.guardar_proyecto, asi que cada cambio
  queda en el historial (origen "Accion masiva");
- si la que se queda no tiene NIT, toma el de las otras; despues las otras se borran.

Antes de correrlo, DATABASE_URL tiene que apuntar a la base que se quiere cambiar.
"""
import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from regalias import servicios
from regalias.lectura import normalizar
from regalias.models import CambioProyectoRegalias, EntidadEjecutora


def tildes(nombre):
    return sum(1 for c in unicodedata.normalize("NFKD", nombre) if unicodedata.combining(c))


def grupos_repetidos():
    """[(la que se queda, [las que se juntan con ella])], de las entidades con el mismo nombre normalizado."""
    por_nombre = defaultdict(list)
    for entidad in EntidadEjecutora.objects.annotate(n=Count("proyectos")).order_by("pk"):
        por_nombre[normalizar(entidad.nombre)].append(entidad)
    resultado = []
    for variantes in por_nombre.values():
        if len(variantes) > 1:
            queda = max(variantes, key=lambda e: (tildes(e.nombre), e.n, -e.pk))
            resultado.append((queda, [e for e in variantes if e.pk != queda.pk]))
    return sorted(resultado, key=lambda g: g[0].nombre)


def homologar(usuario=None):
    """Junta las repetidas. Devuelve [(la que se queda, las que se juntaron, proyectos movidos)]."""
    hecho = []
    with transaction.atomic():
        for queda, otras in grupos_repetidos():
            movidos = 0
            for otra in otras:
                for proyecto in otra.proyectos.all():
                    proyecto.entidad_ejecutora = queda
                    servicios.guardar_proyecto(proyecto, usuario=usuario,
                                               origen=CambioProyectoRegalias.Origen.ACCION_MASIVA)
                    movidos += 1
                if not queda.nit and otra.nit:
                    queda.nit = otra.nit
                    queda.save(update_fields=["nit", "fecha_actualizacion"])
                otra.delete()
            hecho.append((queda, otras, movidos))
    return hecho


class Command(BaseCommand):
    help = "Junta las entidades ejecutoras repetidas (mismo nombre sin contar tildes ni mayúsculas)."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Hace los cambios (sin esto, solo los muestra)")

    def handle(self, aplicar=False, **opciones):
        grupos = grupos_repetidos()
        if not grupos:
            self.stdout.write("No hay entidades ejecutoras repetidas.")
            return
        for queda, otras in grupos:
            detalle = ", ".join(f"«{o.nombre}» ({o.n} proyectos)" for o in otras)
            self.stdout.write(f"Queda «{queda.nombre}» ({queda.n} proyectos); se le juntan: {detalle}")
        if not aplicar:
            self.stdout.write("Sin cambios: corra con --aplicar para hacerlo.")
            return
        hecho = homologar()
        self.stdout.write(self.style.SUCCESS(
            f"Listo: {sum(len(o) for _, o, _ in hecho)} entidades juntadas, "
            f"{sum(m for _, _, m in hecho)} proyectos movidos (con su historial)."))
