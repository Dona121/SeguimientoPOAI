# -*- coding: utf-8 -*-
"""Los tres modelos nuevos: llaves, restricciones y protecciones."""
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from siifweb import cargas
from siifweb.models import BpinProceso, CargaReporte, ContratoSecop, ProcesoSecop

from .fabricas import fila, proyecto


class Restricciones(TestCase):
    def setUp(self):
        self.proceso = ProcesoSecop.objects.create(id_proceso="CO1.REQ.1",
                                                   id_portafolio="CO1.BDOS.1")
        self.contrato = ContratoSecop.objects.create(id_contrato="CO1.PCCNTR.1",
                                                     proceso=self.proceso,
                                                     referencia="CPS-001-2025")

    def test_el_id_del_proceso_es_unico(self):
        with self.assertRaises(IntegrityError):
            ProcesoSecop.objects.create(id_proceso="CO1.REQ.1")

    def test_el_id_del_contrato_es_unico(self):
        with self.assertRaises(IntegrityError):
            ContratoSecop.objects.create(id_contrato="CO1.PCCNTR.1", proceso=self.proceso)

    def test_no_se_repite_el_mismo_bpin_en_el_mismo_proceso_y_contrato(self):
        BpinProceso.objects.create(bpin="1", proceso=self.proceso, contrato_secop=self.contrato)
        with self.assertRaises(IntegrityError):
            BpinProceso.objects.create(bpin="1", proceso=self.proceso,
                                       contrato_secop=self.contrato)

    def test_el_mismo_bpin_si_puede_estar_en_dos_contratos(self):
        otro = ContratoSecop.objects.create(id_contrato="CO1.PCCNTR.2", proceso=self.proceso)
        BpinProceso.objects.create(bpin="1", proceso=self.proceso, contrato_secop=self.contrato)
        BpinProceso.objects.create(bpin="1", proceso=self.proceso, contrato_secop=otro)
        self.assertEqual(BpinProceso.objects.count(), 2)

    def test_no_se_borra_un_proceso_con_contratos(self):
        with self.assertRaises(ProtectedError):
            self.proceso.delete()

    def test_no_se_borra_un_contrato_con_filas_bpin(self):
        BpinProceso.objects.create(bpin="1", proceso=self.proceso, contrato_secop=self.contrato)
        with self.assertRaises(ProtectedError):
            self.contrato.delete()


class Representacion(TestCase):
    def test_textos_legibles(self):
        proceso = ProcesoSecop.objects.create(id_proceso="CO1.REQ.1",
                                              estado_procedimiento="Seleccionado")
        contrato = ContratoSecop.objects.create(id_contrato="CO1.PCCNTR.1", proceso=proceso,
                                                referencia="CPS-001-2025", estado="En ejecución")
        linea = BpinProceso.objects.create(bpin="202500000000001", proceso=proceso,
                                           contrato_secop=contrato)
        self.assertEqual(str(proceso), "CO1.REQ.1 (Seleccionado)")
        self.assertEqual(str(contrato), "CPS-001-2025 - En ejecución")
        self.assertIn("CPS-001-2025", str(linea))
        self.assertIn("202500000000001", str(linea))

    def test_el_proceso_sin_estado_lo_dice(self):
        proceso = ProcesoSecop.objects.create(id_proceso="CO1.REQ.2")
        self.assertIn("sin estado", str(proceso))

    def test_la_fila_sin_contrato_lo_dice(self):
        proceso = ProcesoSecop.objects.create(id_proceso="CO1.REQ.3")
        linea = BpinProceso.objects.create(bpin="1", proceso=proceso)
        self.assertIn("sin contrato", str(linea))


class TipoDeReporte(TestCase):
    def test_secop_es_un_tipo_valido_y_tiene_cargador(self):
        self.assertIn("secop", CargaReporte.TipoReporte.values)
        self.assertIn("secop", cargas.PROCESADORES)
        self.assertIs(cargas.PROCESADORES["secop"], cargas.cargar_secop)

    def test_los_tipos_anteriores_siguen(self):
        for tipo in ("cdp", "compromisos", "obligaciones", "reservas", "historial", "poai"):
            with self.subTest(tipo=tipo):
                self.assertIn(tipo, CargaReporte.TipoReporte.values)
                self.assertIn(tipo, cargas.PROCESADORES)

    def test_un_tipo_sin_cargador_deja_la_carga_en_error(self):
        carga = CargaReporte.objects.create(tipo_reporte="inventado", hash="x" * 64)
        self.assertFalse(cargas.procesar(carga))
        carga.refresh_from_db()
        self.assertEqual(carga.estado, CargaReporte.Estado.ERROR)
        self.assertIn("inventado", carga.mensaje)

    def test_la_carga_de_secop_no_lleva_vigencia(self):
        proyecto()
        from .fabricas import carga_secop
        carga = carga_secop([fila()])
        self.assertIsNone(carga.vigencia)
        self.assertIn("rango completo", CargaReporte.TipoReporte.SECOP.label)
