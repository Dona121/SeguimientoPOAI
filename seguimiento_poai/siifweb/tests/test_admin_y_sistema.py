# -*- coding: utf-8 -*-
"""El admin y lo que el cambio pudo romper de rebote.

Las paginas nuevas de SECOP, pero tambien las que ya existian: el registro de tres
modelos, un inline mas en Proyecto y una entrada nueva en el menu lateral tocan el
admin entero, y una sola clase mal escrita tumba el arranque del servidor.
"""
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from siifweb.models import BpinProceso, ContratoSecop, ProcesoSecop, Proyecto

from .fabricas import carga_secop, contrato_siifweb, fila, proyecto, sin_contrato


class AdminBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def setUp(self):
        self.client.force_login(self.usuario)
        self.proy = proyecto()
        carga_secop([fila(), sin_contrato(**{"ID Proceso": "CO1.REQ.3"})])


class PaginasDeSecop(AdminBase):
    def test_listados(self):
        for modelo in ("procesosecop", "contratosecop", "bpinproceso"):
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_detalles(self):
        objetos = {"procesosecop": ProcesoSecop.objects.first(),
                   "contratosecop": ContratoSecop.objects.first(),
                   "bpinproceso": BpinProceso.objects.first()}
        for modelo, objeto in objetos.items():
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_change", args=(objeto.pk,))
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_los_filtros_no_revientan(self):
        casos = [
            ("procesosecop", {"estado_procedimiento": "Seleccionado"}),
            ("contratosecop", {"estado": "En ejecución"}),
            ("bpinproceso", {"anio": "2025"}),
        ]
        for modelo, parametros in casos:
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_changelist")
                self.assertEqual(self.client.get(url, parametros).status_code, 200)

    def test_la_busqueda_funciona(self):
        url = reverse("admin:siifweb_contratosecop_changelist")
        respuesta = self.client.get(url, {"q": "CPS-001-2025"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "CPS-001-2025")

    def test_son_de_solo_lectura(self):
        for modelo in ("procesosecop", "contratosecop", "bpinproceso"):
            with self.subTest(modelo=modelo):
                registro = admin.site._registry[
                    {"procesosecop": ProcesoSecop, "contratosecop": ContratoSecop,
                     "bpinproceso": BpinProceso}[modelo]]
                self.assertFalse(registro.has_add_permission(None))
                self.assertFalse(registro.has_change_permission(None))

    def test_el_menu_lateral_apunta_a_paginas_que_existen(self):
        from django.conf import settings
        enlaces = [item["link"] for grupo in settings.UNFOLD["SIDEBAR"]["navigation"]
                   for item in grupo["items"]]
        self.assertIn(reverse("admin:siifweb_contratosecop_changelist"), [str(e) for e in enlaces])
        self.assertIn(reverse("admin:siifweb_procesosecop_changelist"), [str(e) for e in enlaces])
        self.assertIn(reverse("admin:siifweb_bpinproceso_changelist"), [str(e) for e in enlaces])


class PaginasQueYaExistian(AdminBase):
    """Regresion: el admin es un solo modulo y ya se rompio una vez al editarlo."""

    def test_todos_los_listados_registrados_cargan(self):
        for modelo, registro in admin.site._registry.items():
            if modelo._meta.app_label != "siifweb":
                continue
            with self.subTest(modelo=modelo.__name__):
                url = reverse(f"admin:siifweb_{modelo._meta.model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_el_detalle_del_proyecto_es_solo_el_proyecto(self):
        """Una sola pestana: la ejecucion se revisa en la ficha, no en inlines.

        El detalle tenia seis inlines (CDP, RP, obligaciones, contratos, reservas y
        SECOP II) que repetian -recortados a 20 filas- lo que la ficha muestra
        completo y agregado.
        """
        contrato_siifweb(self.proy)
        url = reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(admin.site._registry[Proyecto].inlines), [])
        self.assertNotContains(respuesta, "Contratacion (SECOP II)")
        self.assertContains(respuesta,
                            reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.proy.pk,)))

    def test_la_pagina_de_cargas_muestra_el_tipo_secop(self):
        url = reverse("admin:siifweb_cargareporte_changelist")
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "SECOP II")

    def test_el_formulario_de_carga_ofrece_el_tipo_secop(self):
        url = reverse("admin:siifweb_cargareporte_add")
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'value="secop"')

    def test_el_reporte_financiero_sigue_en_pie(self):
        url = reverse("admin:siifweb_proyecto_reporte_financiero")
        self.assertEqual(self.client.get(url).status_code, 200)


class OrdenDeProceso(TestCase):
    """La accion del admin procesa en el orden que exigen los FK, no en el de seleccion."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin2", "b@b.co", "clave")

    def crear(self, tipo, vigencia):
        from siifweb.models import CargaReporte
        return CargaReporte.objects.create(tipo_reporte=tipo, vigencia=vigencia,
                                           hash=f"{tipo}-{vigencia}".ljust(64, "0"))

    def procesar_todo(self):
        """Corre la accion sobre todas las cargas y devuelve el orden en que las proceso."""
        from unittest.mock import patch

        from django.test import RequestFactory

        from siifweb import cargas
        from siifweb.models import CargaReporte

        procesadas = []
        registro = admin.site._registry[CargaReporte]
        peticion = RequestFactory().post("/")
        peticion.user = self.usuario

        def anotar(carga):
            procesadas.append((carga.tipo_reporte, carga.vigencia))
            return True

        with patch.object(cargas, "procesar", side_effect=anotar), \
                patch.object(type(registro), "message_user"):
            registro.procesar_cargas(peticion, CargaReporte.objects.all())
        return procesadas

    def test_los_de_rango_completo_van_despues_de_los_consolidados(self):
        # Se crean a proposito en el orden equivocado
        self.crear("historial", None)
        self.crear("secop", None)
        self.crear("obligaciones", 2025)
        self.crear("cdp", 2024)
        self.crear("poai", None)

        procesadas = self.procesar_todo()
        vigencias = [v for _, v in procesadas]
        self.assertEqual(vigencias[:2], [2024, 2025])           # consolidados, ascendente
        self.assertTrue(all(v is None for v in vigencias[2:]))  # rango completo al final
        self.assertEqual([t for t, _ in procesadas[2:]], ["historial", "poai", "secop"])

    def test_dentro_de_una_vigencia_manda_la_cadena_y_no_el_orden_de_creacion(self):
        """Da igual como se suban: el CDP se procesa antes que el RP y este antes
        que la obligacion."""
        for tipo in ("reservas", "obligaciones", "compromisos", "cdp"):   # al reves
            self.crear(tipo, 2025)

        procesadas = self.procesar_todo()
        self.assertEqual([t for t, _ in procesadas],
                         ["cdp", "compromisos", "obligaciones", "reservas"])

    def test_el_lote_completo_de_varias_vigencias_sale_en_orden(self):
        import random

        cargas_creadas = [(tipo, vigencia)
                          for vigencia in (2024, 2025)
                          for tipo in ("cdp", "compromisos", "obligaciones", "reservas")]
        cargas_creadas += [("historial", None), ("poai", None), ("secop", None)]
        random.shuffle(cargas_creadas)
        for tipo, vigencia in cargas_creadas:
            self.crear(tipo, vigencia)

        procesadas = self.procesar_todo()
        self.assertEqual(procesadas, [
            ("cdp", 2024), ("compromisos", 2024), ("obligaciones", 2024), ("reservas", 2024),
            ("cdp", 2025), ("compromisos", 2025), ("obligaciones", 2025), ("reservas", 2025),
            ("historial", None), ("poai", None), ("secop", None),
        ])

    def test_el_orden_declarado_cubre_todos_los_tipos(self):
        from siifweb import cargas
        self.assertEqual(set(cargas.ORDEN_DE_CARGA), set(cargas.PROCESADORES))


class Sistema(TestCase):
    def test_el_check_de_django_no_reporta_errores(self):
        salida = StringIO()
        call_command("check", stdout=salida, stderr=salida)
        self.assertNotIn("ERRORS", salida.getvalue())

    def test_no_quedan_migraciones_pendientes_de_crear(self):
        """Los modelos y las migraciones tienen que estar sincronizados."""
        salida = StringIO()
        try:
            call_command("makemigrations", "siifweb", check=True, dry_run=True,
                         stdout=salida, stderr=salida)
        except SystemExit:
            self.fail(f"faltan migraciones por crear:\n{salida.getvalue()}")

    def test_las_pruebas_no_corren_contra_produccion(self):
        from django.conf import settings
        self.assertEqual(settings.DATABASES["default"]["ENGINE"],
                         "django.db.backends.sqlite3")
        self.assertIn("FileSystemStorage", settings.STORAGES["default"]["BACKEND"])
