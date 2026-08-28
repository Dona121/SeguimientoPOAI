# -*- coding: utf-8 -*-
"""El comando `validar`: la seccion nueva de SECOP II y que las anteriores sigan corriendo."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from siifweb.models import BpinProceso, ContratoSecop, ProcesoSecop

from .fabricas import cadena, carga_secop, fila, proyecto, sin_contrato


def salida(**opciones):
    buffer = StringIO()
    call_command("validar", stdout=buffer, stderr=buffer, **opciones)
    return buffer.getvalue()


class SinDatos(TestCase):
    def test_corre_con_la_base_vacia(self):
        texto = salida(vigencia=2025)
        self.assertIn("8. CONTRATACION PUBLICA (SECOP II)", texto)
        self.assertIn("sin datos de SECOP II cargados", texto)

    def test_no_se_queja_de_lo_que_no_hay(self):
        texto = salida(vigencia=2025)
        self.assertNotIn("FALLA", texto)


class ConDatosSanos(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.proy = proyecto()
        cadena(cls.proy)
        carga_secop([fila(), sin_contrato(**{"ID Proceso": "CO1.REQ.3",
                                             "ID Portafolio": "CO1.BDOS.3"})])

    def test_reporta_los_conteos(self):
        texto = salida(vigencia=2025)
        self.assertIn("procesos                          2", texto)
        self.assertIn("contratos                         1", texto)
        self.assertIn("(1 con contrato, 1 en tramite)", texto)
        self.assertIn("BPIN distintos                    1", texto)

    def test_todo_en_orden_no_reporta_fallas(self):
        texto = salida(vigencia=2025)
        seccion = texto.split("8. CONTRATACION PUBLICA")[1]
        self.assertNotIn("FALLA", seccion)
        self.assertIn("cada fila apunta al proceso de su contrato", seccion)
        self.assertIn("todo contrato tiene su fila BPIN", seccion)

    def test_muestra_el_pipeline_por_estado(self):
        texto = salida(vigencia=2025)
        self.assertIn("procesos sin adjudicar, por estado", texto)
        self.assertIn("Evaluación", texto)

    def test_cuenta_los_proyectos_con_las_dos_fuentes(self):
        texto = salida(vigencia=2025)
        self.assertIn("proyectos con contratacion        1   (1 tambien con compromisos", texto)


class ConProblemas(TestCase):
    def test_avisa_del_bpin_que_no_esta_en_el_catalogo(self):
        carga_secop([fila(**{"BPIN": "999900000000009"})])
        texto = salida(vigencia=2025)
        self.assertIn("FALLA", texto)
        self.assertIn("999900000000009", texto)
        self.assertIn("crear el proyecto o revisar el BPIN", texto)

    def test_avisa_del_bpin_sin_validar(self):
        proyecto()
        carga_secop([fila(**{"Validacion BPIN": "No validado"})])
        texto = salida(vigencia=2025)
        self.assertIn("BPIN validados por el DNP (1 sin validar)", texto)

    def test_avisa_del_valor_imposible_y_da_el_total_util(self):
        proyecto()
        carga_secop([fila(),
                     fila(**{"ID Proceso": "CO1.REQ.2", "ID Contrato": "CO1.PCCNTR.2",
                             "Referencia del Contrato": "CPS-999-2026",
                             "Valor del Contrato": 1_102_448_525_781_480})])
        texto = salida(vigencia=2025)
        self.assertIn("valores dentro de lo posible (1 por encima", texto)
        self.assertIn("CPS-999-2026", texto)
        self.assertIn("valor sin los atipicos", texto)
        self.assertIn("9,000,000.00", texto)   # el total util, sin el disparate

    def test_detecta_una_fila_que_apunta_al_proceso_equivocado(self):
        proy = proyecto()
        carga_secop([fila()])
        contrato = ContratoSecop.objects.get()
        otro = ProcesoSecop.objects.create(id_proceso="CO1.REQ.99")
        BpinProceso.objects.create(bpin=proy.bpin, proyecto=proy, proceso=otro,
                                   contrato_secop=contrato)
        texto = salida(vigencia=2025)
        self.assertIn("cada fila apunta al proceso de su contrato  (1 cruzadas)", texto)
        self.assertIn("FALLA", texto)

    def test_detecta_un_contrato_sin_fila_bpin(self):
        proyecto()
        carga_secop([fila(), sin_contrato(**{"ID Proceso": "CO1.REQ.3"})])
        BpinProceso.objects.filter(contrato_secop__isnull=False).delete()
        texto = salida(vigencia=2025)
        self.assertIn("todo contrato tiene su fila BPIN (1 sueltos)", texto)
        self.assertIn("FALLA", texto)

    def test_cuenta_los_datos_incompletos_de_la_fuente(self):
        proyecto()
        carga_secop([fila(**{"Fecha de Firma": None, "Documento Proveedor": None})])
        texto = salida(vigencia=2025)
        self.assertIn("contratos sin proveedor           1", texto)
        self.assertIn("contratos sin fecha de firma      1", texto)


class SeccionesAnteriores(TestCase):
    """La seccion nueva se agrego al final: las de siempre tienen que seguir saliendo."""

    @classmethod
    def setUpTestData(cls):
        cls.proy = proyecto()
        cadena(cls.proy, valor=Decimal("5000000.00"))

    def test_estan_las_ocho_secciones(self):
        texto = salida(vigencia=2025)
        for titulo in ("1. TOTALES CARGADOS", "2. IDENTIDADES INTERNAS",
                       "3. CONCILIACION PADRE-HIJO", "4. SALTO TEMPORAL",
                       "5. EJECUCION DE RESERVAS", "6. COBERTURA DEL SEGUIMIENTO",
                       "7. CATALOGO DE PROYECTOS", "8. CONTRATACION PUBLICA"):
            with self.subTest(seccion=titulo):
                self.assertIn(titulo, texto)

    def test_las_conciliaciones_de_siempre_siguen_cuadrando(self):
        texto = salida(vigencia=2025)
        conciliaciones = texto.split("3. CONCILIACION PADRE-HIJO")[1].split("8. CONTRATACION")[0]
        self.assertNotIn("FALLA", conciliaciones)

    def test_la_seccion_de_secop_no_depende_de_la_vigencia(self):
        carga_secop([fila()])
        for vigencia in (2024, 2025, 2026):
            with self.subTest(vigencia=vigencia):
                texto = salida(vigencia=vigencia)
                self.assertIn("contratos                         1", texto)
