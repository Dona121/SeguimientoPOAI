# -*- coding: utf-8 -*-
"""El seguimiento de las metas: el periodo de reporte de cada vigencia y lo que reporta cada
proyecto, por mes, desde el modal de la ficha de la meta.

Las fechas de los periodos van relativas a hoy, para que las pruebas no dependan del dia.
"""
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from siifweb.models import (MetaIndicador, PeriodoReporte, ProgramacionMeta, ProgramacionProyectos,
                            SeguimientoMeta)

HOY = timezone.localdate()


def periodo(vigencia, desde, hasta):
    """Un periodo de reporte de `desde` a `hasta` dias contados desde hoy."""
    return PeriodoReporte.objects.create(vigencia=vigencia, fecha_inicio=HOY + timedelta(days=desde),
                                         fecha_fin=HOY + timedelta(days=hasta))


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")
        cls.meta = MetaIndicador.objects.get(codigo="MT323")
        # Uno programado en la meta para 2026, que es la vigencia de casi todas las pruebas
        cls.proyecto = cls.meta.programaciones_de_proyectos.filter(vigencia=2026).first().proyecto
        cls.ficha = reverse("admin:siifweb_metaindicador_ficha", args=(cls.meta.pk,))
        cls.url = reverse("admin:siifweb_metaindicador_seguimiento", args=(cls.meta.pk,))

    def setUp(self):
        self.client.force_login(self.usuario)

    def seguimiento(self, **datos):
        base = {"meta": self.meta, "proyecto": self.proyecto, "vigencia": 2026, "mes": 3, "valor": Decimal("1.5")}
        return SeguimientoMeta(**{**base, **datos})


class ElPeriodoDeReporte(Base):
    def test_la_fecha_de_fin_no_va_antes_de_la_de_inicio(self):
        with self.assertRaises(ValidationError):
            PeriodoReporte(vigencia=2026, fecha_inicio=HOY, fecha_fin=HOY - timedelta(days=1)).full_clean()

    def test_vigencias_abiertas_incluye_el_cierre_de_la_anterior(self):
        periodo(2026, -300, 40)
        periodo(2027, -5, 400)
        periodo(2025, -700, -200)
        self.assertEqual(PeriodoReporte.vigencias_abiertas(), [2026, 2027])

    def test_una_vigencia_tiene_un_solo_periodo(self):
        periodo(2026, -10, 10)
        with self.assertRaises(ValidationError):
            PeriodoReporte(vigencia=2026, fecha_inicio=HOY, fecha_fin=HOY).full_clean()


class LasReglasDelSeguimiento(Base):
    def test_dentro_del_periodo_se_guarda(self):
        periodo(2026, -10, 10)
        s = self.seguimiento()
        s.full_clean()
        s.save()
        self.assertEqual(SeguimientoMeta.objects.get().valor, Decimal("1.5"))

    def test_fuera_del_periodo_esta_cerrado(self):
        periodo(2025, -400, -1)
        with self.assertRaisesMessage(ValidationError, "está cerrado"):
            self.seguimiento(vigencia=2025).full_clean()

    def test_sin_periodo_configurado_no_se_reporta(self):
        with self.assertRaisesMessage(ValidationError, "no tiene periodo de reporte"):
            self.seguimiento().full_clean()

    def test_un_reporte_por_meta_proyecto_vigencia_y_mes(self):
        periodo(2026, -10, 10)
        self.seguimiento().save()
        with self.assertRaises(ValidationError):
            self.seguimiento(valor=Decimal(2)).full_clean()
        self.seguimiento(mes=4).full_clean()          # otro mes, si

    def test_el_proyecto_tiene_que_estar_en_la_meta(self):
        periodo(2026, -10, 10)
        ajeno = ProgramacionProyectos.objects.exclude(programaciones__meta=self.meta).first()
        with self.assertRaisesMessage(ValidationError, "no está programado"):
            self.seguimiento(proyecto=ajeno).full_clean()

    def test_la_vigencia_tiene_que_estar_programada(self):
        periodo(2026, -10, 10)
        solo_antes = (ProgramacionProyectos.objects.filter(programaciones__meta=self.meta)
                      .exclude(programaciones__meta=self.meta, programaciones__vigencia=2026).first())
        with self.assertRaisesMessage(ValidationError, "para la vigencia 2026"):
            self.seguimiento(proyecto=solo_antes).full_clean()

    def test_el_valor_lleva_cinco_decimales_y_no_es_negativo(self):
        periodo(2026, -10, 10)
        self.assertEqual(SeguimientoMeta._meta.get_field("valor").decimal_places, 5)
        with self.assertRaises(ValidationError):
            self.seguimiento(valor=Decimal("-1")).full_clean()


class DesdeElModalDeLaFicha(Base):
    def reportar(self, **datos):
        return self.client.post(self.url, {"proyecto": self.proyecto.pk, "vigencia": 2026, "mes": 5,
                                           "valor": "3,0976", "observacion": "Avance de obra", **datos})

    def test_la_ficha_ofrece_el_formulario_con_las_vigencias_abiertas(self):
        periodo(2026, -300, 40)
        periodo(2025, -700, -200)
        respuesta = self.client.get(self.ficha)
        self.assertContains(respuesta, 'id="seguimiento-plantilla"')
        self.assertEqual(respuesta.context["seguimiento"]["vigencias"], [2026])
        self.assertEqual(respuesta.context["seguimiento"]["mes_actual"], HOY.month)
        self.assertContains(respuesta, "Valor del mes (no el acumulado)")

    def test_el_modal_ofrece_solo_las_vigencias_programadas(self):
        periodo(2026, -300, 40)
        html = self.client.get(self.ficha).content.decode()
        por_proyecto = {int(p): json.loads(v) for p, v in
                        re.findall(r'data-proyecto="(\d+)".*?data-reportables="([^"]*)"', html, re.S)}
        self.assertEqual(por_proyecto[self.proyecto.pk], [2026])
        sin_2026 = set(por_proyecto) - set(ProgramacionMeta.objects.filter(meta=self.meta, vigencia=2026)
                                          .values_list("proyecto", flat=True))
        self.assertTrue(sin_2026)
        self.assertTrue(all(por_proyecto[p] == [] for p in sin_2026))

    def test_sin_vigencias_abiertas_no_hay_boton(self):
        periodo(2025, -700, -200)
        respuesta = self.client.get(self.ficha)
        self.assertIsNone(respuesta.context["seguimiento"])
        self.assertNotContains(respuesta, 'id="seguimiento-plantilla"')

    def test_reporta_y_lo_muestra_en_el_modal(self):
        periodo(2026, -10, 10)
        respuesta = self.reportar()
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        s = SeguimientoMeta.objects.get()
        self.assertEqual((s.meta, s.proyecto, s.vigencia, s.mes, s.valor, s.reportado_por),
                         (self.meta, self.proyecto, 2026, 5, Decimal("3.0976"), self.usuario))
        self.assertContains(self.client.get(self.ficha), "Avance de obra")

    def test_los_errores_llegan_con_su_mensaje(self):
        periodo(2025, -400, -1)
        periodo(2026, -10, 10)
        self.reportar()
        casos = [({"vigencia": 2025}, "cerrado"), ({"mes": 5}, "Ya hay un seguimiento"),
                 ({"mes": 13}, "mes"), ({"valor": "abc", "mes": 6}, "número"),
                 ({"valor": "1,123456", "mes": 6}, "cinco decimales")]
        for datos, mensaje in casos:
            with self.subTest(mensaje=mensaje):
                respuesta = self.reportar(**datos)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(mensaje, respuesta.json()["error"])
        self.assertEqual(SeguimientoMeta.objects.count(), 1)

    def test_solo_por_post_y_con_permiso(self):
        periodo(2026, -10, 10)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        otro = get_user_model().objects.create_user("ve", "v@b.co", "clave", is_staff=True)
        otro.user_permissions.add(Permission.objects.get(codename="view_metaindicador"))
        self.client.force_login(otro)
        self.assertIsNone(self.client.get(self.ficha).context["seguimiento"])
        self.assertEqual(self.reportar().status_code, 403)


class LasPaginasDelAdmin(Base):
    def test_listados_y_menu(self):
        periodo(2026, -10, 10)
        self.seguimiento(reportado_por=self.usuario).save()
        for modelo in ("seguimientometa", "periodoreporte"):
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(reverse(f"admin:siifweb_{modelo}_changelist")).status_code, 200)
        detalle = reverse("admin:siifweb_programacionproyectos_change", args=(self.proyecto.pk,))
        self.assertContains(self.client.get(detalle), "seguimientos-TOTAL_FORMS")
        plan = next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Plan de Desarrollo")
        self.assertEqual(str(plan["items"][-1]["link"]), reverse("admin:siifweb_seguimientometa_changelist"))
        menu = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(reverse("admin:siifweb_seguimientometa_changelist"), menu)
        self.assertIn(reverse("admin:siifweb_periodoreporte_changelist"), menu)

    def test_el_admin_anota_quien_reporta(self):
        periodo(2026, -10, 10)
        self.client.post(reverse("admin:siifweb_seguimientometa_add"), {
            "meta": self.meta.pk, "proyecto": self.proyecto.pk, "vigencia": 2026, "mes": 7, "valor": "2",
            "observacion": ""})
        self.assertEqual(SeguimientoMeta.objects.get().reportado_por, self.usuario)
