"""Semillas de homologacion de fuentes y rubros (Semillas_CUIPO_T3_2026.xlsx)."""
from io import BytesIO, StringIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from cuipo import semillas
from cuipo.models import FuenteCUIPO, HomologacionFuente, HomologacionRubro
from siifweb.models import Fuente

from .test_derivacion import corte_con, listas
from .test_ejecucion_gastos import fila

VALIDADO = "Presupuesto (CUIPO T3 2026)"


def libro(fuentes=None, rubros=None):
    fuentes = fuentes if fuentes is not None else [("108", "1.3.3.3.20", 2026), ("7", "1.2.3.3.03", 2026)]
    rubros = rubros if rubros is not None else [("2.3.3.05.09.054", "2.3.3.05.09.099")]
    wb = Workbook()
    wb.active.title = "LEEME"
    hoja = wb.create_sheet("HomologacionFuente")
    hoja.append(["recurso_siifweb", "nombre_recurso_siifweb", "fuente_cuipo", "nombre_fuente_cuipo", "vigencia",
                 "validado_por"])
    for recurso, fuente, vigencia in fuentes:
        hoja.append([recurso, f"Recurso {recurso}", fuente, f"Fuente {fuente}", vigencia, VALIDADO])
    hoja = wb.create_sheet("HomologacionRubro")
    hoja.append(["rubro_siifweb", "concepto_cuipo", "nombre_concepto_cuipo", "vigencia", "validado_por"])
    for rubro, concepto in rubros:
        hoja.append([rubro, concepto, f"Concepto {concepto}", 2026, VALIDADO])
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


class CargarSemillas(TestCase):
    def setUp(self):
        listas()

    def test_crea_las_homologaciones(self):
        mensaje = semillas.cargar(libro())
        self.assertEqual(mensaje, "Fuentes: 2 creadas, 0 ya estaban | Rubros: 1 creadas, 0 ya estaban")
        h = HomologacionFuente.objects.get(fuente_siifweb__codigo="108")
        self.assertEqual((h.fuente_cuipo.codigo, h.vigencia), ("1.3.3.3.20", 2026))
        self.assertEqual(h.observacion, f"Semilla validada por {VALIDADO}")
        self.assertIsNone(h.validado_por)       # no la valido un usuario del aplicativo
        self.assertEqual(HomologacionRubro.objects.get().concepto.codigo, "2.3.3.05.09.099")

    def test_cargar_otra_vez_no_duplica(self):
        semillas.cargar(libro())
        mensaje = semillas.cargar(libro())
        self.assertEqual(mensaje, "Fuentes: 0 creadas, 2 ya estaban | Rubros: 0 creadas, 1 ya estaban")
        self.assertEqual(HomologacionFuente.objects.count(), 2)

    def test_no_cambia_una_homologacion_distinta_y_avisa(self):
        HomologacionFuente.objects.create(fuente_siifweb=Fuente.objects.get(codigo="7"), vigencia=2026,
                                          fuente_cuipo=FuenteCUIPO.objects.get(codigo="1.2.1.0.00"))
        mensaje = semillas.cargar(libro())
        self.assertIn("recurso 7 (2026): la semilla dice 1.2.3.3.03 y está 1.2.1.0.00", mensaje)
        self.assertEqual(HomologacionFuente.objects.get(fuente_siifweb__codigo="7").fuente_cuipo.codigo, "1.2.1.0.00")

    def test_un_codigo_que_no_existe_aborta_sin_dejar_nada(self):
        with self.assertRaisesMessage(ValueError, "fuente 9.9.9 no está en las listas CHIP"):
            semillas.cargar(libro(fuentes=[("108", "1.3.3.3.20", 2026), ("7", "9.9.9", 2026)]))
        self.assertFalse(HomologacionFuente.objects.exists())
        with self.assertRaisesMessage(ValueError, "recurso 999 no está en los recursos de SIIFWEB"):
            semillas.cargar(libro(fuentes=[("999", "1.3.3.3.20", 2026)]))

    def test_comando(self):
        salida = StringIO()
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "Semillas.xlsx"
            ruta.write_bytes(libro().getvalue())
            call_command("cargar_semillas_cuipo", str(ruta), stdout=salida)
        self.assertIn("2 creadas", salida.getvalue())


class SemillasDesdeLosPendientes(TestCase):
    def setUp(self):
        listas()
        self.client.force_login(User.objects.create_superuser("admin", "admin@example.com", "clave"))
        self.corte = corte_con([fila(102, "2.3.3.05.09.054", 40, "108", "10", "202600000018441")])

    def test_subir_el_libro_carga_y_no_lo_guarda(self):
        url = reverse("admin:cuipo_corte_pendientes", args=(self.corte.pk,))
        self.assertContains(self.client.get(url), "Cargar semillas de homologación")
        respuesta = self.client.post(url, {"semillas": SimpleUploadedFile("Semillas.xlsx", libro().getvalue())},
                                     follow=True)
        self.assertContains(respuesta, "Fuentes: 2 creadas")
        self.assertEqual(HomologacionFuente.objects.count(), 2)
        self.assertNotContains(respuesta, "Recurso 108: sin homologación")
