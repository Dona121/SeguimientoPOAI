# -*- coding: utf-8 -*-
"""El PDF de cada tabla de la ficha (CDPs, RPs u obligaciones), con el filtro de fechas aplicado."""
from datetime import date
from html import unescape
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from reportlab import rl_config

from siifweb import pdf_ficha
from siifweb.models import Cdp

from .fabricas import cadena, proyecto


class Base(TestCase):
    """La cadena de prueba: CDP del 15/01, RP del 01/02 y obligacion del 01/03 de 2025."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def setUp(self):
        self.client.force_login(self.usuario)
        self.proy = proyecto()
        cadena(self.proy)
        self.url = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.proy.pk,))

    def pdf(self, tabla, **parametros):
        return self.client.get(self.url, {"panel": "siifweb", "descargar": "pdf",
                                          "tabla": tabla, **parametros})

    def texto_del_pdf(self, tabla, **parametros):
        """Sin compresion, el texto de las paginas queda legible en el archivo."""
        with mock.patch.object(rl_config, "pageCompression", 0):
            return self.pdf(tabla, **parametros).content.decode("latin-1")


class PdfPorTabla(Base):
    def test_cada_tabla_descarga_su_propio_pdf(self):
        for tabla in ("cdps", "rps", "obligaciones"):
            with self.subTest(tabla=tabla):
                respuesta = self.pdf(tabla)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta["Content-Type"], "application/pdf")
                self.assertIn(f'filename="{tabla}_{self.proy.bpin}_',
                              respuesta["Content-Disposition"])
                self.assertTrue(respuesta.content.startswith(b"%PDF"))

    def test_el_pdf_trae_solo_la_tabla_pedida(self):
        cdps = self.texto_del_pdf("cdps")
        self.assertIn("Objeto del CDP", cdps)
        self.assertNotIn("Objeto del registro", cdps)
        self.assertNotIn("Objeto de la obligacion", cdps)
        rps = self.texto_del_pdf("rps")
        self.assertIn("Objeto del registro", rps)
        self.assertNotIn("Objeto del CDP", rps)
        obligaciones = self.texto_del_pdf("obligaciones")
        # "Contratista" solo: en la columna Beneficiario el nombre se parte en dos renglones
        for esperado in ("Objeto de la obligacion", "Contratista",
                         "10.000.000", "5.000.000"):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, obligaciones)
        self.assertNotIn("Objeto del CDP", obligaciones)

    def test_respeta_el_filtro_de_fechas(self):
        with mock.patch.object(pdf_ficha, "generar", return_value=b"%PDF-") as generar:
            self.pdf("rps", desde="2025-01-20", hasta="2025-02-15")
        _, desde, hasta, documentos, tabla = generar.call_args.args
        self.assertEqual((desde, hasta, tabla), (date(2025, 1, 20), date(2025, 2, 15), "rps"))
        self.assertEqual(len(documentos["rps_por_proyecto"]), 1)
        self.assertEqual(len(documentos["obligaciones_por_proyecto"]), 0)
        # Y en el archivo: la obligacion del 01/03 queda fuera del periodo
        texto = self.texto_del_pdf("obligaciones", desde="2025-01-20", hasta="2025-02-15")
        self.assertIn("Sin obligaciones en el periodo", texto)
        self.assertIn("Del 20", texto)

    def test_una_tabla_desconocida_da_404(self):
        self.assertEqual(self.pdf("contratos").status_code, 404)
        self.assertEqual(self.client.get(self.url, {"descargar": "pdf"}).status_code, 404)

    def test_los_textos_con_signos_de_marcado_no_rompen_el_pdf(self):
        """Paragraph de ReportLab interpreta <, > y &: los datos van escapados."""
        Cdp.objects.update(objeto_cert="OBRA <FASE 1> & DOTACION")
        texto = self.texto_del_pdf("cdps")
        self.assertIn("FASE 1", texto)
        self.assertIn("DOTACION", texto)

    def test_una_tabla_larga_sigue_en_las_paginas_siguientes(self):
        for n in range(2, 90):
            cadena(self.proy, nro=str(n))
        respuesta = self.pdf("obligaciones")
        self.assertEqual(respuesta.status_code, 200)
        self.assertGreater(respuesta.content.count(b"/Type /Page\n"), 1)

    def test_quien_no_ve_proyectos_no_descarga_el_pdf(self):
        otro = get_user_model().objects.create_user("sinrol", "s@b.co", "clave", is_staff=True)
        self.client.force_login(otro)
        self.assertEqual(self.pdf("cdps").status_code, 403)


class EnlacesEnLaFicha(Base):
    def html(self, **parametros):
        return unescape(self.client.get(self.url, {"panel": "siifweb", **parametros})
                        .content.decode())

    def test_cada_titulo_tiene_su_enlace_a_la_derecha(self):
        html = self.html()
        for marca, tabla in (("CDPs (", "cdps"), ("RPs (", "rps"), ("Obligaciones (", "obligaciones")):
            with self.subTest(tabla=tabla):
                cabecera = html[html.index(marca):html.index("</div>", html.index(marca))]
                self.assertIn(f"tabla={tabla}&descargar=pdf", cabecera)

    def test_el_enlace_lleva_el_filtro_aplicado(self):
        html = self.html(desde="2025-01-20", hasta="2025-02-15")
        self.assertIn("?panel=siifweb&desde=2025-01-20&hasta=2025-02-15&tabla=rps&descargar=pdf", html)

    def test_el_formulario_del_filtro_ya_no_descarga(self):
        html = self.html()
        filtro = html[html.index('id="filtro-fechas"'):html.index("</form>")]
        self.assertNotIn("descargar", filtro)


class EncabezadoDelPdf(Base):
    def test_muestra_la_dependencia_responsable_del_poai_y_no_la_que_ejecuta(self):
        from siifweb.models import CentroCosto, DependenciaResponsable
        self.proy.dependencia_responsable = DependenciaResponsable.objects.create(nombre="Hacienda")
        self.proy.dependencia = CentroCosto.objects.create(codigo="99", nombre="Secretaria De Hacienda")
        self.proy.save()
        texto = self.texto_del_pdf("cdps")
        self.assertIn("Dependencia responsable:", texto)
        self.assertIn("Hacienda", texto)
        self.assertNotIn("Ejecuta", texto)
        self.assertNotIn("Secretaria De Hacienda", texto)

    def test_sin_dependencia_responsable_lo_dice(self):
        texto = self.texto_del_pdf("cdps")
        self.assertIn("Dependencia responsable:", texto)
