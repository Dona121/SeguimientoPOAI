"""Entidades ejecutoras con el mismo nombre salvo tildes o mayusculas (27/11/2026: la importacion
creo "MUNICIPIO DE SINCE" y "MUNICIPIO DE SINCÉ"). La carga ya no las repite y el comando
homologar_entidades_ejecutoras junta las que estaban."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from regalias import cargas
from regalias.models import CambioProyectoRegalias, EntidadEjecutora, ProyectoRegalias

from .fabricas import MUNICIPIO, proyecto


def homologar(*argumentos):
    salida = StringIO()
    call_command("homologar_entidades_ejecutoras", *argumentos, stdout=salida)
    return salida.getvalue()


class LaCargaNoLasRepite(TestCase):
    def test_reconoce_la_entidad_sin_tildes_ni_mayusculas(self):
        since = EntidadEjecutora.objects.create(nombre="MUNICIPIO DE SINCE")
        resumen = cargas.Resumen("Matriz")
        catalogos = cargas.Catalogos(resumen)
        self.assertEqual(catalogos.entidad_ejecutora("Municipio de  Sincé"), since)
        nueva = catalogos.entidad_ejecutora("Universidad de Sucre")
        self.assertEqual(catalogos.entidad_ejecutora("UNIVERSIDAD DE SUCRE"), nueva)
        self.assertEqual(EntidadEjecutora.objects.count(), 2)


class ElComandoLasJunta(TestCase):
    def setUp(self):
        self.since = EntidadEjecutora.objects.create(nombre="MUNICIPIO DE SINCE", nit="800050331")
        self.sinc = EntidadEjecutora.objects.create(nombre="MUNICIPIO DE SINCÉ")
        self.corozal = EntidadEjecutora.objects.create(nombre="MUNICIPIO DE COROZAL")
        self.uno = proyecto("2012000020001", MUNICIPIO, entidad_ejecutora=self.since)
        self.dos = proyecto("2012000020002", MUNICIPIO, entidad_ejecutora=self.since)
        self.tres = proyecto("2012000020003", MUNICIPIO, entidad_ejecutora=self.sinc)
        self.otro = proyecto("2012000020004", MUNICIPIO, entidad_ejecutora=self.corozal)

    def test_sin_aplicar_solo_muestra(self):
        salida = homologar()
        self.assertIn("Queda «MUNICIPIO DE SINCÉ» (1 proyectos); se le juntan: «MUNICIPIO DE SINCE» (2 proyectos)",
                      salida)
        self.assertIn("Sin cambios", salida)
        self.assertEqual(EntidadEjecutora.objects.count(), 3)
        self.assertFalse(CambioProyectoRegalias.objects.exists())

    def test_aplicar_deja_la_de_tilde_con_todos_sus_proyectos_y_el_historial(self):
        self.assertIn("1 entidades juntadas, 2 proyectos movidos", homologar("--aplicar"))
        self.assertEqual(sorted(EntidadEjecutora.objects.values_list("nombre", flat=True)),
                         ["MUNICIPIO DE COROZAL", "MUNICIPIO DE SINCÉ"])
        self.sinc.refresh_from_db()
        self.assertEqual(self.sinc.nit, "800050331")                      # toma el NIT de la otra
        self.assertEqual(sorted(self.sinc.proyectos.values_list("bpin", flat=True)),
                         [self.uno.bpin, self.dos.bpin, self.tres.bpin])
        self.assertEqual(ProyectoRegalias.objects.get(pk=self.otro.pk).entidad_ejecutora, self.corozal)
        cambio = CambioProyectoRegalias.objects.get(proyecto=self.uno)
        self.assertEqual((cambio.campo, cambio.valor_anterior, cambio.valor_nuevo, cambio.origen),
                         ("Entidad ejecutora", "MUNICIPIO DE SINCE", "MUNICIPIO DE SINCÉ",
                          CambioProyectoRegalias.Origen.ACCION_MASIVA))
        self.assertEqual(CambioProyectoRegalias.objects.count(), 2)
        self.assertIn("No hay entidades ejecutoras repetidas.", homologar("--aplicar"))
