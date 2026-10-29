# -*- coding: utf-8 -*-
"""El plan de desarrollo en el admin: la seccion del menu, sus paginas y la regla de la meta.

La base de pruebas ya trae el catalogo real: la migracion 0012 lo carga al crearla.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from siifweb.admin import MetaIndicadorForm
from siifweb.models import IndicadorPDD, MetaIndicador, ProgramaPDD

# Las metas no: van en Seguimiento, con la programacion de proyectos
ORDEN = ["plandesarrollo", "lineaestrategica", "sectorpdd", "programapdd", "indicadorpdd",
         "vigenciameta", "sectormga", "programamga", "productomga",
         "indicadormga", "ods", "metaods"]


def datos_del_formulario(meta, **cambios):
    """Lo que mandaria el formulario de la meta sin tocar nada, mas los cambios."""
    datos = {
        "codigo": meta.codigo or "", "descripcion": meta.descripcion,
        "indicador_mga": meta.indicador_mga_id, "programa_pdd": meta.programa_pdd_id,
        "meta_cuatrenio": meta.meta_cuatrenio if meta.meta_cuatrenio is not None else "",
        "estado": meta.estado,
        "indicadores_pdd": list(meta.indicadores_pdd.values_list("pk", flat=True)),
        "dependencias_responsables": list(meta.dependencias_responsables.values_list("pk", flat=True)),
        "ods": list(meta.ods.values_list("pk", flat=True)),
    }
    datos.update(cambios)
    return datos


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def setUp(self):
        self.client.force_login(self.usuario)


class LaSeccionDelMenu(Base):
    def seccion(self):
        return next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"]
                    if g["title"] == "Plan de Desarrollo")

    def test_trae_los_modelos_en_el_orden_de_la_jerarquia(self):
        enlaces = [str(item["link"]) for item in self.seccion()["items"]]
        self.assertEqual(enlaces, [reverse(f"admin:siifweb_{m}_changelist") for m in ORDEN])

    def test_las_metas_van_en_seguimiento(self):
        grupo = next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Seguimiento")
        self.assertIn(reverse("admin:siifweb_metaindicador_changelist"), [str(i["link"]) for i in grupo["items"]])

    def test_va_despues_de_seguimiento(self):
        titulos = [g["title"] for g in settings.UNFOLD["SIDEBAR"]["navigation"]]
        self.assertEqual(titulos.index("Plan de Desarrollo"), titulos.index("Seguimiento") + 1)

    def test_cada_enlace_abre_su_listado(self):
        for item in self.seccion()["items"]:
            with self.subTest(item=item["title"]):
                self.assertEqual(self.client.get(str(item["link"])).status_code, 200)

    def test_los_roles_del_equipo_no_la_ven(self):
        """Seguimiento y Consulta solo tienen el modulo de Seguimiento en el menu."""
        for rol in ("Seguimiento", "Consulta"):
            usuario = get_user_model().objects.create_user(f"u_{rol}", "x@b.co", "clave", is_staff=True)
            usuario.groups.add(Group.objects.get(name=rol))
            peticion = type("Peticion", (), {"user": usuario})()
            with self.subTest(rol=rol):
                self.assertFalse(any(item["permission"](peticion) for item in self.seccion()["items"]))


class LasPaginas(Base):
    def test_el_catalogo_real_esta_cargado(self):
        self.assertEqual(MetaIndicador.objects.count(), 436)

    def test_el_detalle_de_una_meta_abre_con_sus_vigencias(self):
        meta = MetaIndicador.objects.filter(vigencias__isnull=False).first()
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_change", args=(meta.pk,)))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "vigencias-TOTAL_FORMS")

    def test_el_autocompletado_de_indicadores_responde(self):
        respuesta = self.client.get(reverse("admin:autocomplete"), {
            "app_label": "siifweb", "model_name": "metaindicador",
            "field_name": "indicadores_pdd", "term": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()["results"])

    def test_el_listado_de_metas_no_hace_una_consulta_por_fila(self):
        """La etiqueta de la meta lleva sector e indicador MGA: sin select_related serian
        tres consultas por fila, mas de 300 en una pagina de 100."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        url = reverse("admin:siifweb_metaindicador_changelist")
        self.client.get(url)                      # calienta sesion y cache de contenttypes
        with CaptureQueriesContext(connection) as consultas:
            self.client.get(url)
        self.assertLess(len(consultas), 20)


class LosIndicadoresDeLaMeta(TestCase):
    """Los indicadores PDD de una meta tienen que ser de su programa."""

    @classmethod
    def setUpTestData(cls):
        cls.meta = (MetaIndicador.objects.filter(indicadores_pdd__isnull=False)
                    .order_by("pk").first())
        propios = set(cls.meta.programa_pdd.indicadores_pdd.values_list("pk", flat=True))
        # Un indicador de otro programa, que el de la meta no tiene
        cls.ajeno = IndicadorPDD.objects.exclude(pk__in=propios).exclude(programas_pdd=None).first()
        cls.otro_programa = cls.ajeno.programas_pdd.first()

    def test_un_indicador_de_otro_programa_se_rechaza_en_su_campo(self):
        formulario = MetaIndicadorForm(
            datos_del_formulario(self.meta, indicadores_pdd=[self.ajeno.pk]), instance=self.meta)
        self.assertFalse(formulario.is_valid())
        self.assertIn("indicadores_pdd", formulario.errors)
        self.assertNotIn("programa_pdd", formulario.errors)   # el aviso no sale dos veces

    def test_cambiar_programa_e_indicadores_a_la_vez_no_da_un_error_falso(self):
        """Los indicadores guardados son del programa viejo; los que se mandan, del nuevo."""
        formulario = MetaIndicadorForm(
            datos_del_formulario(self.meta, programa_pdd=self.otro_programa.pk,
                                 indicadores_pdd=[self.ajeno.pk]),
            instance=self.meta)
        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_cambiar_solo_el_programa_si_se_rechaza(self):
        formulario = MetaIndicadorForm(
            datos_del_formulario(self.meta, programa_pdd=self.otro_programa.pk), instance=self.meta)
        self.assertFalse(formulario.is_valid())

    def test_sin_tocar_nada_el_formulario_es_valido(self):
        formulario = MetaIndicadorForm(datos_del_formulario(self.meta), instance=self.meta)
        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_el_sector_la_linea_y_el_plan_suben_desde_el_programa(self):
        self.assertEqual(self.meta.sector_pdd, self.meta.programa_pdd.sector_pdd)
        self.assertEqual(self.meta.linea_estrategica, self.meta.sector_pdd.linea_estrategica)
        self.assertEqual(self.meta.plan_desarrollo, self.meta.linea_estrategica.plan_desarrollo)


class LosFiltrosDelListadoDeMetas(Base):
    """Cada filtro, con un valor real: responde, solo trae lo que cumple y no repite filas."""

    def resultado(self, parametros):
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_changelist"), parametros)
        self.assertEqual(respuesta.status_code, 200)
        cl = respuesta.context["cl"]
        metas = list(cl.queryset)
        self.assertEqual(len(metas), len({m.pk for m in metas}))      # sin filas repetidas
        return metas

    def test_la_mt_por_codigo_o_parte_de_el(self):
        self.assertEqual([m.codigo for m in self.resultado({"codigo__icontains": "MT323"})], ["MT323"])
        self.assertTrue(all("MT32" in m.codigo for m in self.resultado({"codigo__icontains": "MT32"})))

    def test_los_filtros_de_las_dos_jerarquias(self):
        meta = MetaIndicador.objects.select_related(
            "programa_pdd__sector_pdd__linea_estrategica",
            "indicador_mga__producto_mga__programa_mga__sector_mga").filter(
            indicadores_pdd__isnull=False, indicador_mga__producto_mga__programa_mga__sector_mga__isnull=False).first()
        mga = meta.indicador_mga
        casos = {
            "programa_pdd__sector_pdd__linea_estrategica": meta.programa_pdd.sector_pdd.linea_estrategica,
            "indicadores_pdd": meta.indicadores_pdd.first(),
            "indicador_mga__producto_mga__programa_mga__sector_mga": mga.producto_mga.programa_mga.sector_mga,
            "indicador_mga__producto_mga__programa_mga": mga.producto_mga.programa_mga,
            "indicador_mga__producto_mga": mga.producto_mga,
            "indicador_mga": mga,
        }
        for ruta, valor in casos.items():
            with self.subTest(filtro=ruta):
                metas = self.resultado({f"{ruta}__id__exact": valor.pk})
                self.assertIn(meta.pk, [m.pk for m in metas])
                esperadas = set(MetaIndicador.objects.filter(**{ruta: valor}).values_list("pk", flat=True))
                self.assertEqual({m.pk for m in metas}, esperadas)
