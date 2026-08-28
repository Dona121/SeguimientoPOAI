# -*- coding: utf-8 -*-
"""El cargador del consolidado BPIN por proceso."""
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.db.models import Count
from django.test import TestCase

from siifweb import cargas
from siifweb.models import (BpinProceso, CargaReporte, ContratoSecop, ProcesoSecop,
                            Proyecto, Tercero)

from .fabricas import carga_secop, fila, libro, proyecto, sin_contrato, tercero


class GranoDeLaCarga(TestCase):
    """Una fila es BPIN x proceso x contrato, y de ahi salen las tres tablas."""

    def test_carga_lo_basico(self):
        proy = proyecto()
        carga = carga_secop([fila()])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        self.assertEqual(carga.filas, 1)
        self.assertEqual(ProcesoSecop.objects.count(), 1)
        self.assertEqual(ContratoSecop.objects.count(), 1)
        self.assertEqual(BpinProceso.objects.count(), 1)

        linea = BpinProceso.objects.get()
        self.assertEqual(linea.proyecto, proy)
        self.assertEqual(linea.bpin, "202500000000001")
        self.assertEqual(linea.anio, 2025)
        self.assertEqual(linea.validacion_bpin, "Validado")
        self.assertEqual(linea.reporte, carga)

    def test_un_contrato_con_varios_bpin_es_un_solo_contrato(self):
        proyecto(bpin="202500000000001")
        proyecto(bpin="202500000000002", nombre="Otro proyecto")
        carga_secop([fila(), fila(**{"BPIN": "202500000000002"})])
        self.assertEqual(ContratoSecop.objects.count(), 1)
        self.assertEqual(BpinProceso.objects.count(), 2)
        self.assertEqual(ContratoSecop.objects.get().bpines.count(), 2)

    def test_un_proceso_puede_tener_varios_contratos(self):
        proyecto()
        carga_secop([fila(), fila(**{"ID Contrato": "CO1.PCCNTR.2",
                                     "Referencia del Contrato": "CPS-002-2025"})])
        self.assertEqual(ProcesoSecop.objects.count(), 1)
        self.assertEqual(ContratoSecop.objects.count(), 2)
        self.assertEqual(ProcesoSecop.objects.get().contratos_del_proceso.count(), 2)

    def test_descarta_las_filas_repetidas_exactas(self):
        proyecto()
        carga = carga_secop([fila(), fila(), fila()])
        self.assertEqual(carga.filas, 3)                  # el archivo traia tres
        self.assertEqual(BpinProceso.objects.count(), 1)  # una sola linea
        self.assertIn("2 filas repetidas descartadas", carga.mensaje)

    def test_proceso_sin_contrato_adjudicado(self):
        proyecto()
        carga = carga_secop([sin_contrato(**{"ID Proceso": "CO1.REQ.9",
                                             "ID Portafolio": "CO1.BDOS.9"})])
        self.assertEqual(ContratoSecop.objects.count(), 0)
        linea = BpinProceso.objects.get()
        self.assertIsNone(linea.contrato_secop)
        self.assertEqual(linea.proceso.estado_procedimiento, "Evaluación")
        self.assertIn("1 filas sin contrato adjudicado", carga.mensaje)


class BpinYCatalogos(TestCase):
    def test_no_crea_proyectos_desde_secop(self):
        """El BPIN que no esta en el catalogo entra con proyecto nulo, no lo inventa."""
        antes = Proyecto.objects.count()
        carga = carga_secop([fila(**{"BPIN": "999900000000009"})])
        self.assertEqual(Proyecto.objects.count(), antes)
        linea = BpinProceso.objects.get()
        self.assertIsNone(linea.proyecto)
        self.assertEqual(linea.bpin, "999900000000009")   # el BPIN crudo no se pierde
        self.assertIn("999900000000009", carga.mensaje)
        self.assertIn("no esta en el catalogo", carga.mensaje)

    def test_engancha_el_proyecto_existente_por_bpin(self):
        proy = proyecto(bpin="2024002700105")
        carga_secop([fila(**{"BPIN": "2024002700105"})])
        self.assertEqual(BpinProceso.objects.get().proyecto, proy)

    def test_reusa_el_tercero_y_respeta_su_nombre(self):
        proyecto()
        existente = tercero(codigo="1005639763", nombre="RAZON SOCIAL YA CARGADA")
        carga_secop([fila()])
        existente.refresh_from_db()
        self.assertEqual(ContratoSecop.objects.get().proveedor, existente)
        self.assertEqual(existente.nombre, "RAZON SOCIAL YA CARGADA")

    def test_crea_el_proveedor_que_falta_aunque_sea_sin_nombre(self):
        proyecto()
        carga_secop([fila(**{"Documento Proveedor": "900123456"})])
        nuevo = Tercero.objects.get(codigo="900123456")
        self.assertEqual(ContratoSecop.objects.get().proveedor, nuevo)
        self.assertFalse(nuevo.nombre)

    def test_contrato_sin_proveedor_queda_en_nulo(self):
        proyecto()
        carga_secop([fila(**{"Documento Proveedor": None})])
        self.assertIsNone(ContratoSecop.objects.get().proveedor)


class Normalizacion(TestCase):
    def test_fechas_y_valores(self):
        proyecto()
        carga_secop([fila()])
        contrato = ContratoSecop.objects.get()
        self.assertEqual(contrato.fecha_firma, date(2025, 9, 25))
        self.assertEqual(contrato.fecha_inicio, date(2025, 9, 26))
        self.assertEqual(contrato.fecha_fin, date(2025, 12, 23))
        self.assertEqual(contrato.valor, Decimal("9000000"))
        self.assertEqual(contrato.proceso.fecha_publicacion, date(2025, 9, 24))

    def test_acepta_fechas_en_texto_y_valores_con_coma(self):
        proyecto()
        carga_secop([fila(**{"Fecha de Firma": "25/09/2025",
                             "Valor del Contrato": "9000000,44"})])
        contrato = ContratoSecop.objects.get()
        self.assertEqual(contrato.fecha_firma, date(2025, 9, 25))
        self.assertEqual(contrato.valor, Decimal("9000000.44"))

    def test_los_identificadores_pierden_el_punto_cero(self):
        proyecto(bpin="202500000000001")
        carga_secop([fila(**{"BPIN": 202500000000001.0, "Año": 2025.0,
                             "Documento Proveedor": 1005639763.0})])
        linea = BpinProceso.objects.get()
        self.assertEqual(linea.bpin, "202500000000001")
        self.assertEqual(linea.anio, 2025)
        self.assertEqual(linea.contrato_secop.proveedor.codigo, "1005639763")

    def test_fechas_vacias_quedan_nulas(self):
        proyecto()
        carga_secop([fila(**{"Fecha de Firma": None, "Fecha de Fin del Contrato": None})])
        contrato = ContratoSecop.objects.get()
        self.assertIsNone(contrato.fecha_firma)
        self.assertIsNone(contrato.fecha_fin)


class RecargaYErrores(TestCase):
    def test_es_idempotente(self):
        proyecto()
        primera = carga_secop([fila(), sin_contrato(**{"ID Proceso": "CO1.REQ.9"})])
        conteos = (ProcesoSecop.objects.count(), ContratoSecop.objects.count(),
                   BpinProceso.objects.count())

        cargas.procesar(primera)
        primera.refresh_from_db()
        self.assertEqual(primera.estado, CargaReporte.Estado.PROCESADO, primera.mensaje)
        self.assertEqual((ProcesoSecop.objects.count(), ContratoSecop.objects.count(),
                          BpinProceso.objects.count()), conteos)
        self.assertIn("reemplazo", primera.mensaje)

    def test_una_carga_nueva_reemplaza_a_la_anterior(self):
        proyecto()
        carga_secop([fila(), fila(**{"ID Proceso": "CO1.REQ.2",
                                     "ID Contrato": "CO1.PCCNTR.2"})])
        self.assertEqual(BpinProceso.objects.count(), 2)

        carga_secop([fila()])
        self.assertEqual(BpinProceso.objects.count(), 1)
        self.assertEqual(ProcesoSecop.objects.count(), 1)
        self.assertEqual(ContratoSecop.objects.count(), 1)

    def test_si_el_libro_no_trae_la_tabla_la_carga_queda_en_error_y_no_escribe(self):
        proyecto()
        datos = libro([fila()], tabla=None).getvalue()
        carga = carga_secop(contenido=datos)
        self.assertEqual(carga.estado, CargaReporte.Estado.ERROR)
        self.assertIn("BPIN_por_proceso", carga.mensaje)
        self.assertEqual(ProcesoSecop.objects.count(), 0)
        self.assertEqual(BpinProceso.objects.count(), 0)

    def test_un_error_a_media_carga_no_deja_datos_a_medias(self):
        """La carga es atomica: si falla, no queda ni el primer proceso escrito."""
        proyecto()
        carga_secop([fila()])
        self.assertEqual(ContratoSecop.objects.count(), 1)

        recortadas = [c for c in cargas.COLUMNAS_SECOP if c != "Estado Contrato"]
        datos = libro([fila()], columnas=recortadas).getvalue()
        carga = carga_secop(contenido=datos)
        self.assertEqual(carga.estado, CargaReporte.Estado.ERROR)
        self.assertIn("Estado Contrato", carga.mensaje)
        # lo de la carga anterior sigue intacto
        self.assertEqual(ContratoSecop.objects.count(), 1)


class MensajeDeLaCarga(TestCase):
    def test_resume_lo_cargado(self):
        proyecto()
        carga = carga_secop([fila(),
                             fila(**{"ID Proceso": "CO1.REQ.2", "ID Contrato": "CO1.PCCNTR.2"}),
                             sin_contrato(**{"ID Proceso": "CO1.REQ.3"})])
        self.assertIn("3 procesos", carga.mensaje)
        self.assertIn("2 contratos", carga.mensaje)
        self.assertIn("3 filas BPIN", carga.mensaje)
        self.assertIn("1 BPIN distintos", carga.mensaje)
        self.assertIn("1 filas sin contrato adjudicado", carga.mensaje)

    def test_avisa_si_proceso_de_compra_deja_de_ser_el_portafolio(self):
        proyecto()
        carga = carga_secop([fila(**{"Proceso de Compra": "CO1.BDOS.DISTINTO"})])
        self.assertIn("OJO", carga.mensaje)
        self.assertIn("Proceso de Compra", carga.mensaje)

    def test_sin_discrepancias_no_hay_aviso(self):
        proyecto()
        carga = carga_secop([fila()])
        self.assertNotIn("OJO", carga.mensaje)


class DatosGuardados(TestCase):
    def test_el_proceso_guarda_sus_fechas_y_estado(self):
        proyecto()
        carga_secop([fila(**{"Fecha de Recepcion de Respuestas": date(2025, 8, 1),
                             "Fecha de Apertura de Respuesta": date(2025, 8, 2),
                             "Fecha de Apertura Efectiva": date(2025, 8, 3),
                             "Estado del Procedimiento": "Evaluación"})])
        proceso = ProcesoSecop.objects.get()
        self.assertEqual(proceso.id_portafolio, "CO1.BDOS.1")
        self.assertEqual(proceso.estado_procedimiento, "Evaluación")
        self.assertEqual(proceso.fecha_recepcion_respuestas, date(2025, 8, 1))
        self.assertEqual(proceso.fecha_apertura_respuestas, date(2025, 8, 2))
        self.assertEqual(proceso.fecha_apertura_efectiva, date(2025, 8, 3))

    def test_el_contrato_guarda_objeto_url_y_referencia(self):
        proyecto()
        carga_secop([fila()])
        contrato = ContratoSecop.objects.get()
        self.assertEqual(contrato.referencia, "CPS-001-2025")
        self.assertEqual(contrato.estado, "En ejecución")
        self.assertEqual(contrato.objeto, "PRESTACION DE SERVICIOS DE PRUEBA")
        self.assertEqual(contrato.descripcion_proceso, "PRESTACION DE SERVICIOS DE PRUEBA")
        self.assertTrue(contrato.url_proceso.startswith("https://community.secop.gov.co"))
        self.assertEqual(contrato.proceso.id_proceso, "CO1.REQ.1")

    def test_textos_largos_no_se_truncan_a_la_fuerza(self):
        proyecto()
        objeto = "OBJETO " * 200
        carga_secop([fila(**{"Objeto del Contrato": objeto})])
        self.assertEqual(ContratoSecop.objects.get().objeto, objeto.strip())


ARCHIVO_REAL = Path(__file__).resolve().parents[3] / "data" / "secop" / "ReporteSIIFWEB_20260814.xlsx"


@unittest.skipUnless(ARCHIVO_REAL.exists(), f"no esta {ARCHIVO_REAL.name}")
class ArchivoDeVerdad(TestCase):
    """Las cifras medidas sobre el consolidado del 14/08/2026.

    Es la red de seguridad frente a un cambio de formato en la fuente: si el DNP
    cambia el reporte o alguien reordena el consolidado, estas cifras se mueven.
    """
    CIFRAS = {"filas": 4546, "procesos": 4139, "contratos": 3988, "lineas": 4534, "bpines": 244}

    @classmethod
    def setUpTestData(cls):
        cls.carga = carga_secop(contenido=ARCHIVO_REAL.read_bytes())

    def test_la_carga_sale_bien(self):
        self.assertEqual(self.carga.estado, CargaReporte.Estado.PROCESADO, self.carga.mensaje)
        self.assertEqual(self.carga.filas, self.CIFRAS["filas"])

    def test_los_conteos(self):
        self.assertEqual(ProcesoSecop.objects.count(), self.CIFRAS["procesos"])
        self.assertEqual(ContratoSecop.objects.count(), self.CIFRAS["contratos"])
        self.assertEqual(BpinProceso.objects.count(), self.CIFRAS["lineas"])
        self.assertEqual(BpinProceso.objects.values("bpin").distinct().count(),
                         self.CIFRAS["bpines"])

    def test_el_grano_que_se_verifico_sobre_los_datos(self):
        # cada contrato pertenece a un solo proceso, y hay procesos con varios contratos
        contratos_por_proceso = (ProcesoSecop.objects
                                 .annotate(n=Count("contratos_del_proceso"))
                                 .filter(n__gt=1).count())
        self.assertEqual(contratos_por_proceso, 81)
        # contratos que financian mas de un BPIN
        varios_bpin = (ContratoSecop.objects.annotate(n=Count("bpines")).filter(n__gt=1).count())
        self.assertEqual(varios_bpin, 17)
        # procesos publicados que aun no adjudican
        self.assertEqual(BpinProceso.objects.filter(contrato_secop__isnull=True)
                         .values("proceso").distinct().count(), 250)

    def test_las_filas_repetidas_del_archivo(self):
        self.assertIn("12 filas repetidas descartadas", self.carga.mensaje)

    def test_los_dos_valores_atipicos_siguen_ahi(self):
        atipicos = ContratoSecop.objects.filter(valor__gt=100_000_000_000)
        self.assertEqual(atipicos.count(), 2)
        self.assertEqual(sorted(atipicos.values_list("referencia", flat=True)),
                         ["CP-SDSD-440-2026", "CPS-170-2026"])
