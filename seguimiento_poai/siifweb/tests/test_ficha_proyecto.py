# -*- coding: utf-8 -*-
"""La ficha de ejecucion: los dos paneles, lo que consulta cada uno y lo que dibuja."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from siifweb.models import BpinProceso, ContratoSecop, ProcesoSecop

from .fabricas import cadena, carga_secop, contrato_siifweb, fila, proyecto, sin_contrato


class FichaBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def setUp(self):
        self.client.force_login(self.usuario)

    def url(self, proy, panel=None):
        base = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(proy.pk,))
        return base + (f"?panel={panel}" if panel else "")

    def html(self, respuesta):
        return respuesta.content.decode("utf8", "replace")


class Paneles(FichaBase):
    def setUp(self):
        super().setUp()
        self.proy = proyecto()

    def test_sin_panel_muestra_siifweb(self):
        respuesta = self.client.get(self.url(self.proy))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["panel"], "siifweb")
        self.assertIn("Cadena de ejecucion por vigencia", self.html(respuesta))

    def test_panel_secop(self):
        respuesta = self.client.get(self.url(self.proy, "secop"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["panel"], "secop")
        self.assertIn("Contratos en SECOP II", self.html(respuesta))

    def test_un_panel_desconocido_cae_en_siifweb(self):
        respuesta = self.client.get(self.url(self.proy, "inventado"))
        self.assertEqual(respuesta.context["panel"], "siifweb")

    def test_cada_panel_solo_calcula_lo_suyo(self):
        """El de SECOP no paga las quince consultas del de SIIFWEB, ni al reves."""
        secop = self.client.get(self.url(self.proy, "secop")).context
        siifweb = self.client.get(self.url(self.proy, "siifweb")).context
        self.assertIn("secop_contratos", secop)
        self.assertNotIn("filas", secop)
        self.assertNotIn("calendario", secop)
        self.assertIn("filas", siifweb)
        self.assertNotIn("secop_contratos", siifweb)

    def test_las_dos_pestanas_estan_en_los_dos_paneles(self):
        for panel in ("siifweb", "secop"):
            with self.subTest(panel=panel):
                html = self.html(self.client.get(self.url(self.proy, panel)))
                self.assertIn("?panel=siifweb", html)
                self.assertIn("?panel=secop", html)

    def test_proyecto_inexistente(self):
        base = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(999999,))
        self.assertEqual(self.client.get(base).status_code, 404)


class PanelSecop(FichaBase):
    def setUp(self):
        super().setUp()
        self.proy = proyecto()
        carga_secop([
            fila(),
            fila(**{"ID Proceso": "CO1.REQ.2", "ID Contrato": "CO1.PCCNTR.2",
                    "Referencia del Contrato": "CPS-002-2025", "ID Portafolio": "CO1.BDOS.2",
                    "Proceso de Compra": "CO1.BDOS.2", "Valor del Contrato": 1000000}),
            sin_contrato(**{"ID Proceso": "CO1.REQ.3", "ID Portafolio": "CO1.BDOS.3"}),
        ])

    def test_trae_los_contratos_del_proyecto(self):
        contexto = self.client.get(self.url(self.proy, "secop")).context
        self.assertEqual(contexto["secop_contratos"].count(), 2)
        self.assertEqual(contexto["secop_en_tramite"].count(), 1)

    def test_las_tarjetas_van_en_orden_del_tramite(self):
        tarjetas = self.client.get(self.url(self.proy, "secop")).context["secop_tarjetas"]
        self.assertEqual([t[0] for t in tarjetas],
                         ["Procesos en tramite", "Contratos en SECOP",
                          "Valor contratado", "Comprometido en SIIFWEB"])
        self.assertEqual(tarjetas[0][1], 1)                       # procesos en tramite
        self.assertEqual(tarjetas[1][1], 2)                       # contratos
        self.assertEqual(tarjetas[2][1], Decimal("10000000"))     # 9.000.000 + 1.000.000

    def test_el_contrato_de_dos_bpin_se_cuenta_una_vez_por_proyecto(self):
        """El contrato que financia dos BPIN no puede contarse dos veces."""
        proyecto(bpin="202500000000002", nombre="Otro")
        carga_secop([fila(), fila(**{"BPIN": "202500000000002"})])
        tarjetas = self.client.get(self.url(self.proy, "secop")).context["secop_tarjetas"]
        self.assertEqual(tarjetas[1][1], 1)
        self.assertEqual(tarjetas[2][1], Decimal("9000000"))

    def test_el_valor_no_se_multiplica_si_un_contrato_tiene_dos_filas_del_proyecto(self):
        """Defensa del grano: filtrar y sumar sobre la relacion multiplicaria el valor.

        Se arma a mano el caso que el join duplicaria (dos filas del mismo proyecto
        apuntando al mismo contrato); la vista resuelve por subconsulta de ids y por
        eso el contrato sigue contando una sola vez.
        """
        contrato = ContratoSecop.objects.get(referencia="CPS-001-2025")
        otro_proceso = ProcesoSecop.objects.create(id_proceso="CO1.REQ.99")
        BpinProceso.objects.create(bpin=self.proy.bpin, proyecto=self.proy,
                                   proceso=otro_proceso, contrato_secop=contrato)
        contexto = self.client.get(self.url(self.proy, "secop")).context
        self.assertEqual(contexto["secop_contratos"].count(), 2)
        self.assertEqual(contexto["secop_tarjetas"][2][1], Decimal("10000000"))

    def test_contraste_con_lo_comprometido_en_siifweb(self):
        cadena(self.proy, valor=Decimal("7000000.00"))
        tarjetas = self.client.get(self.url(self.proy, "secop")).context["secop_tarjetas"]
        self.assertEqual(tarjetas[3][1], Decimal("7000000.00"))

    def test_los_procesos_van_antes_que_los_contratos(self):
        html = self.html(self.client.get(self.url(self.proy, "secop")))
        self.assertLess(html.index("Procesos en tramite ("), html.index("Contratos en SECOP II ("))

    def test_dibuja_los_datos_del_contrato(self):
        html = self.html(self.client.get(self.url(self.proy, "secop")))
        self.assertIn("CPS-001-2025", html)
        self.assertIn("CO1.REQ.3", html)                      # el proceso en tramite
        self.assertIn("community.secop.gov.co", html)         # enlace al proceso

    def test_un_proyecto_sin_secop_muestra_los_mensajes_de_vacio(self):
        otro = proyecto(bpin="202600000000009", nombre="Sin contratacion")
        html = self.html(self.client.get(self.url(otro, "secop")))
        self.assertIn("no tiene contratos en SECOP II", html)
        self.assertIn("No hay procesos pendientes de adjudicar", html)

    def test_solo_muestra_lo_del_proyecto_que_se_esta_viendo(self):
        otro = proyecto(bpin="202600000000009", nombre="Sin contratacion")
        contexto = self.client.get(self.url(otro, "secop")).context
        self.assertEqual(contexto["secop_contratos"].count(), 0)
        self.assertEqual(contexto["secop_en_tramite"].count(), 0)


class PanelSiifweb(FichaBase):
    def setUp(self):
        super().setUp()
        self.proy = proyecto()
        _, self.rp, _ = cadena(self.proy)

    def test_el_pagado_del_contrato_no_se_duplica(self):
        """Dos imputaciones del proyecto por dos actas: el pagado son 1.000.000, no 2.000.000."""
        contrato_siifweb(self.proy, imputaciones=2, actas=2,
                         valor_acta=Decimal("500000.00"), compromiso=self.rp)
        contratos = self.client.get(self.url(self.proy, "siifweb")).context["contratos"]
        self.assertEqual(len(contratos), 1)
        self.assertEqual(contratos[0].pagado, Decimal("1000000.00"))
        self.assertEqual(contratos[0].n_actas, 2)

    def test_el_calendario_tampoco_se_duplica(self):
        contrato_siifweb(self.proy, imputaciones=2, actas=2,
                         valor_acta=Decimal("500000.00"), compromiso=self.rp)
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        self.assertEqual(contexto["total_pagado_bitacora"], Decimal("1000000.00"))
        self.assertEqual(len(contexto["calendario"]), 2)

    def test_la_cadena_por_vigencia(self):
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        self.assertEqual(len(contexto["filas"]), 1)
        self.assertEqual(contexto["totales"]["obligado"], Decimal("10000000.00"))
        self.assertEqual([t[0] for t in contexto["totales_tarjetas"]],
                         ["Disponibilidad definitiva", "Comprometido", "Obligado", "Pagado"])

    def test_el_objeto_del_registro_del_rp_se_muestra(self):
        html = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertIn("Objeto del registro", html)

    def test_la_seccion_de_obligaciones(self):
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        obligaciones = list(contexto["obligaciones_por_proyecto"])
        self.assertEqual(len(obligaciones), 1)
        obligacion = obligaciones[0]
        self.assertEqual(obligacion.vigencia, 2025)
        self.assertEqual(obligacion.nro_obligacion, "1")
        self.assertEqual(obligacion.valor_obli, Decimal("10000000.00"))
        self.assertEqual(obligacion.tipo_orden_gasto.nombre, "CONTRATO")
        self.assertEqual(obligacion.objeto_oblig, "Objeto de la obligacion")
        self.assertEqual(obligacion.beneficiario.nombre, "Contratista de prueba")
        self.assertEqual(obligacion.beneficiario.codigo, "1005639763")
        self.assertEqual(contexto["obligaciones_por_proyecto_total"], Decimal("10000000.00"))

    def test_el_beneficiario_se_dibuja_con_su_nit(self):
        html = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertIn("Contratista de prueba", html)
        self.assertIn("1005639763", html)

    def test_el_objeto_propio_manda_sobre_el_del_rp(self):
        html = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertIn("Objeto de la obligacion", html)

    def test_si_la_obligacion_no_trae_objeto_se_muestra_el_del_rp(self):
        """Las cargas anteriores a la columna OBJETO_OBLIG no tienen objeto propio."""
        from siifweb.models import Obligacion
        Obligacion.objects.update(objeto_oblig="")
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        obligacion = list(contexto["obligaciones_por_proyecto"])[0]
        self.assertEqual(obligacion.objeto_oblig, "")
        self.assertEqual(obligacion.objeto_rp, "Objeto del registro")
        # Aparece dos veces: en la fila del RP y, por el respaldo, en la de la obligacion
        html = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertEqual(html.count("Objeto del registro"), 2)

    def test_la_seccion_de_obligaciones_se_dibuja_debajo_de_los_rps(self):
        html = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertIn("Obligaciones (1)", html)
        self.assertLess(html.index("RPs ("), html.index("Obligaciones (1)"))
        self.assertLess(html.index("Obligaciones (1)"), html.index("Fuentes de financiación"))
        for encabezado in ("Número obligación", "Fecha obligación", "Objeto", "Beneficiario",
                           "NIT", "Tipo de orden de gasto", "Valor obligación definitiva"):
            with self.subTest(columna=encabezado):
                self.assertIn(encabezado, html)

    def test_el_valor_de_la_obligacion_no_se_multiplica(self):
        """Dos imputaciones del proyecto en la misma obligacion se suman, no se duplican."""
        from siifweb.models import ObligacionImputacion
        imputacion = ObligacionImputacion.objects.get()
        ObligacionImputacion.objects.create(
            obligacion=imputacion.obligacion, compromiso=imputacion.compromiso,
            rubro=imputacion.rubro, fuente=imputacion.fuente, proyecto=self.proy,
            valor_obligacion=Decimal("2000000.00"), saldo_obli=Decimal("2000000.00"),
            pagos=Decimal("0.00"))
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        obligaciones = list(contexto["obligaciones_por_proyecto"])
        self.assertEqual(len(obligaciones), 1)
        self.assertEqual(obligaciones[0].valor_obli, Decimal("12000000.00"))

    def test_no_muestra_las_obligaciones_de_otro_proyecto(self):
        otro = proyecto(bpin="202600000000009", nombre="Otro")
        cadena(otro, valor=Decimal("3000000.00"), nro="2")
        contexto = self.client.get(self.url(self.proy, "siifweb")).context
        self.assertEqual(len(list(contexto["obligaciones_por_proyecto"])), 1)
        self.assertEqual(contexto["obligaciones_por_proyecto_total"], Decimal("10000000.00"))

    def test_mas_contratos_no_significan_mas_consultas(self):
        """El modal muestra dependencia e interventor: sin select_related seria N+1."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        contrato_siifweb(self.proy, compromiso=self.rp)
        with CaptureQueriesContext(connection) as una:
            self.client.get(self.url(self.proy, "siifweb"))

        for numero in ("3000", "3001", "3002"):
            contrato_siifweb(self.proy, compromiso=self.rp, nro=numero)
        with CaptureQueriesContext(connection) as cuatro:
            self.client.get(self.url(self.proy, "siifweb"))

        self.assertEqual(len(cuatro.captured_queries), len(una.captured_queries))


class Plantilla(FichaBase):
    """Detalles de la plantilla que ya fallaron una vez."""

    def setUp(self):
        super().setUp()
        self.proy = proyecto()
        carga_secop([fila(), sin_contrato(**{"ID Proceso": "CO1.REQ.3"})])
        contrato_siifweb(self.proy)

    def test_los_comentarios_no_se_imprimen(self):
        for panel in ("siifweb", "secop"):
            with self.subTest(panel=panel):
                html = self.html(self.client.get(self.url(self.proy, panel)))
                self.assertNotIn("Dos fuentes, dos paneles", html)
                self.assertNotIn("{#", html)
                self.assertNotIn("{%", html)

    def test_el_modal_esta_una_sola_vez_en_cada_panel(self):
        for panel in ("siifweb", "secop"):
            with self.subTest(panel=panel):
                html = self.html(self.client.get(self.url(self.proy, panel)))
                self.assertEqual(html.count('id="modal-detalle"'), 1)
                self.assertEqual(html.count('id="modal-detalle-cuerpo"'), 1)
                self.assertIn("#modal-detalle .celda", html)      # los estilos de las celdas

    def test_cada_panel_alimenta_el_modal_con_sus_datos(self):
        secop = self.html(self.client.get(self.url(self.proy, "secop")))
        self.assertIn("data-contrato-valor", secop)
        self.assertIn("data-proceso-publicacion", secop)
        self.assertNotIn('data-tipo="siifweb"', secop)

        siifweb = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertIn('data-tipo="siifweb"', siifweb)
        self.assertIn("data-siifweb-pagado", siifweb)
        self.assertIn("data-siifweb-interventor", siifweb)
        self.assertNotIn("data-contrato-valor", siifweb)

    def test_las_ayudas_estan_en_los_dos_paneles(self):
        secop = self.html(self.client.get(self.url(self.proy, "secop")))
        siifweb = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertEqual(secop.count('class="ayuda'), 2)
        self.assertEqual(siifweb.count('class="ayuda'), 8)
        self.assertEqual(secop.count('class="globo'), 2)
        self.assertEqual(siifweb.count('class="globo'), 8)
        self.assertIn("se reciben las ofertas y se adjudica", secop)
        self.assertIn("aparta el cupo antes de contratar", siifweb)

    def test_las_tablas_largas_se_limitan_en_alto(self):
        secop = self.html(self.client.get(self.url(self.proy, "secop")))
        siifweb = self.html(self.client.get(self.url(self.proy, "siifweb")))
        self.assertEqual(secop.count('style="max-height:26rem"'), 2)
        self.assertEqual(siifweb.count('style="max-height:26rem"'), 4)
        self.assertEqual(secop.count("position:sticky;top:0"), 2)
        self.assertEqual(siifweb.count("position:sticky;top:0"), 4)

    def test_el_texto_del_cruce_por_bpin(self):
        html = self.html(self.client.get(self.url(self.proy, "secop")))
        self.assertIn("SECOP no cuenta con una columna que especifique", html)
        self.assertIn("solo se hace el cruce a nivel de BPIN", html)
