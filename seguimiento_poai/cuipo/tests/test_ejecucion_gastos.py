"""Importador de la ejecucion de gastos por corte (estado_ppto_gasto_gobatl_fyccw)."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from cuipo import ejecucion
from cuipo.models import CorteEjecucionGastos, FilaEjecucionGastos

from .fabricas import COLUMNAS, cortar, fila, libro_ejecucion as libro, reporte_basico

class ImportarEjecucion(TestCase):
    def test_guarda_solo_el_detalle_con_todas_las_columnas(self):
        corte = cortar(reporte_basico())
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.PROCESADO, corte.mensaje)
        self.assertEqual(corte.filas, 2)
        f = FilaEjecucionGastos.objects.get(corte=corte, recurso="3")
        self.assertEqual((f.rubro_id_siifweb, f.rubro, f.centro_costo, f.proyecto),
                         (102, "2.3.2.02.02.009", "2", "202500000039332"))
        self.assertEqual((f.nombre_rubro, f.nombre_recurso, f.nombre_centro_costo),
                         ("Rubro 2.3.2.02.02.009", "Recurso 3", "Centro 2"))
        self.assertEqual((f.apropiacion_definitiva, f.cdp, f.rp, f.obligacion, f.pago), (Decimal(1000),) * 5)
        self.assertFalse(f.de_otra_vigencia)
        self.assertIn("3 subtotales cuadran", corte.mensaje)

    def test_proyecto_cero_es_funcionamiento(self):
        cortar(reporte_basico())
        self.assertEqual(FilaEjecucionGastos.objects.get(recurso="7").proyecto, "0")

    def test_lee_la_coma_decimal_de_siifweb(self):
        filas = reporte_basico()
        filas[3]["PAGO"], filas[3]["OBLIGACION"] = "999,5", "999,5"
        for subtotal in filas[:3]:
            subtotal["PAGO"], subtotal["OBLIGACION"] = "1499,5", "1499,5"
        corte = cortar(filas)
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.PROCESADO, corte.mensaje)
        self.assertEqual(FilaEjecucionGastos.objects.get(recurso="3").pago, Decimal("999.5"))

    def test_marca_el_arbol_de_otra_vigencia(self):
        """El reporte de 2023 trae filas del arbol de 2022 con los mismos codigos."""
        filas = [
            fila(50, "2", 0, obligacion=300),
            fila(51, "2.3.2.02.02.009", 0, obligacion=300),
            fila(51, "2.3.2.02.02.009", 0, "7", "16", "2023002700021", obligacion=300),
            *reporte_basico(),
            fila(102, "2.3.2.02.02.009", 0, "7", "16", "2023002700021", obligacion=0),
        ]
        corte = cortar(filas, vigencia=2023, fecha_fin=date(2023, 12, 31))
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.PROCESADO, corte.mensaje)
        otra = FilaEjecucionGastos.objects.get(rubro_id_siifweb=51)
        self.assertTrue(otra.de_otra_vigencia)
        self.assertEqual(otra.obligacion, Decimal(300))
        self.assertFalse(FilaEjecucionGastos.objects.get(rubro_id_siifweb=102, proyecto="2023002700021")
                         .de_otra_vigencia)
        self.assertIn("1 del árbol de otra vigencia", corte.mensaje)

    def test_un_subtotal_que_no_cuadra_aborta_sin_dejar_nada(self):
        filas = reporte_basico()
        filas[1]["RP"] = 1499
        corte = cortar(filas)
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.ERROR)
        self.assertIn("2.3 RP", corte.mensaje)
        self.assertEqual(FilaEjecucionGastos.objects.count(), 0)

    def test_una_fila_repetida_aborta(self):
        filas = reporte_basico()
        filas.append(fila(102, "2.3.2.02.02.009", 0, "3", "2", "202500000039332"))
        corte = cortar(filas)
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.ERROR)
        self.assertIn("Fila repetida", corte.mensaje)

    def test_falta_una_columna(self):
        filas = reporte_basico()
        for f in filas:
            del f["PAGO"]
        corte = CorteEjecucionGastos(vigencia=2026, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 9, 30))
        wb = Workbook()
        wb.active.append([c for c in COLUMNAS if c != "PAGO"])
        buffer = BytesIO()
        wb.save(buffer)
        corte.archivo.save("sin_pago.xlsx", ContentFile(buffer.getvalue()), save=True)
        self.assertFalse(ejecucion.procesar(corte))
        self.assertIn("PAGO", corte.mensaje)

    def test_reprocesar_reemplaza_las_filas_del_corte(self):
        corte = cortar(reporte_basico())
        self.assertTrue(ejecucion.procesar(corte))
        self.assertEqual(FilaEjecucionGastos.objects.filter(corte=corte).count(), 2)

    def test_un_error_al_reprocesar_conserva_las_filas_anteriores(self):
        corte = cortar(reporte_basico())
        corte.archivo.save("roto.xlsx", ContentFile(b"no es un excel"), save=True)
        self.assertFalse(ejecucion.procesar(corte))
        self.assertEqual(corte.filas, 2)
        self.assertEqual(FilaEjecucionGastos.objects.filter(corte=corte).count(), 2)

    def test_cada_corte_conserva_sus_filas(self):
        septiembre = cortar(reporte_basico())
        filas = reporte_basico()
        for f in filas:
            if f["RECURSO"] == "3" or not f["RECURSO"]:
                f["RP"] = f["RP"] + 100
                f["APROPIACION_INICIAL"] = f["APROPIACION_DEFINITIVA"] = f["SOLICITUD_TRAMITE"] = f["CDP"] = f["RP"]
                f["OBLIGACION"] = f["PAGO"] = f["RP"]
        octubre = cortar(filas, fecha_fin=date(2026, 10, 31))
        self.assertEqual(octubre.estado, CorteEjecucionGastos.Estado.PROCESADO, octubre.mensaje)
        self.assertEqual(FilaEjecucionGastos.objects.get(corte=septiembre, recurso="3").rp, Decimal(1000))
        self.assertEqual(FilaEjecucionGastos.objects.get(corte=octubre, recurso="3").rp, Decimal(1100))


class AdminDelCorte(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "admin@example.com", "clave"))
        self.url = reverse("admin:cuipo_corteejecuciongastos_add")

    def subir(self, datos, fecha_fin="2026-09-30"):
        return self.client.post(self.url, {
            "vigencia": 2026, "fecha_inicio": "2026-01-01", "fecha_fin": fecha_fin, "fecha_descarga": "2026-11-13",
            "archivo": SimpleUploadedFile("estado_ppto_gasto.xlsx", datos)}, follow=True)

    def test_al_guardar_se_importa(self):
        respuesta = self.subir(libro(reporte_basico()))
        self.assertEqual(respuesta.status_code, 200)
        corte = CorteEjecucionGastos.objects.get()
        self.assertEqual(corte.estado, CorteEjecucionGastos.Estado.PROCESADO, corte.mensaje)
        self.assertEqual(corte.filas_ejecucion.count(), 2)
        self.assertContains(respuesta, "2 filas de detalle")

    def test_el_mismo_archivo_no_se_carga_dos_veces(self):
        datos = libro(reporte_basico())
        self.subir(datos)
        respuesta = self.subir(datos, fecha_fin="2026-10-31")
        self.assertContains(respuesta, "ya está cargado")
        self.assertEqual(CorteEjecucionGastos.objects.count(), 1)

    def test_el_listado_de_filas_abre(self):
        self.subir(libro(reporte_basico()))
        corte = CorteEjecucionGastos.objects.get()
        respuesta = self.client.get(reverse("admin:cuipo_filaejecuciongastos_changelist"),
                                    {"corte__id__exact": corte.pk})
        self.assertContains(respuesta, "202500000039332")
        self.assertContains(self.client.get(reverse("admin:cuipo_corteejecuciongastos_changelist")), "$1,500")

    def test_las_fechas_del_corte_van_dentro_de_la_vigencia(self):
        respuesta = self.client.post(self.url, {
            "vigencia": 2025, "fecha_inicio": "2025-01-01", "fecha_fin": "2026-07-31", "fecha_descarga": "2026-07-31",
            "archivo": SimpleUploadedFile("estado_ppto_gasto.xlsx", libro(reporte_basico()))})
        self.assertContains(respuesta, "dentro de la vigencia 2025")
        self.assertFalse(CorteEjecucionGastos.objects.exists())

    def test_no_se_descarga_antes_del_corte(self):
        respuesta = self.client.post(self.url, {
            "vigencia": 2026, "fecha_inicio": "2026-01-01", "fecha_fin": "2026-09-30", "fecha_descarga": "2026-09-15",
            "archivo": SimpleUploadedFile("estado_ppto_gasto.xlsx", libro(reporte_basico()))})
        self.assertContains(respuesta, "antes de la fecha de fin del corte")
        self.assertFalse(CorteEjecucionGastos.objects.exists())

    def test_el_fin_no_es_anterior_al_inicio(self):
        respuesta = self.client.post(self.url, {
            "vigencia": 2026, "fecha_inicio": "2026-09-30", "fecha_fin": "2026-01-01", "fecha_descarga": "2026-11-13",
            "archivo": SimpleUploadedFile("estado_ppto_gasto.xlsx", libro(reporte_basico()))})
        self.assertContains(respuesta, "anterior a la de inicio")
        self.assertFalse(CorteEjecucionGastos.objects.exists())

    def test_dos_rangos_de_la_misma_vigencia_conviven(self):
        """Un corte acumulado y uno de un trimestre, con distinto archivo."""
        self.subir(libro(reporte_basico()))
        filas = reporte_basico()
        filas[-1]["NOMBRE_RUBRO"] = "Otro nombre"
        respuesta = self.client.post(self.url, {
            "vigencia": 2026, "fecha_inicio": "2026-07-01", "fecha_fin": "2026-09-30", "fecha_descarga": "2026-11-13",
            "archivo": SimpleUploadedFile("trimestre.xlsx", libro(filas))}, follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(CorteEjecucionGastos.objects.count(), 2)
