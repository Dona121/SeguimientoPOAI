# -*- coding: utf-8 -*-
"""El plan de desarrollo en el admin: la seccion del menu, sus paginas y la regla de la meta.

La base de pruebas ya trae el catalogo real: la migracion 0012 lo carga al crearla.
"""
from decimal import Decimal

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
         "indicadormga", "medidoatravesde", "unidadmedida", "ods", "metaods", "seguimientometa"]


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

    def test_el_listado_muestra_la_meta_de_cada_vigencia_y_no_el_estado(self):
        meta = MetaIndicador.objects.get(codigo="MT175")
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_changelist"), {"q": "MT175"})
        from django.contrib.admin.templatetags.admin_list import result_headers
        encabezados = [str(h["text"]) for h in result_headers(respuesta.context["cl"])]
        self.assertEqual(encabezados[-4:], ["Meta 2024", "Meta 2025", "Meta 2026", "Meta 2027"])
        self.assertLess(encabezados.index("Programa PDD"), encabezados.index("Producto MGA"))
        self.assertLess(encabezados.index("Producto MGA"), encabezados.index("Indicador MGA"))
        self.assertContains(respuesta, "3301090 - ")      # el producto de MT175
        self.assertNotIn("Estado", encabezados)
        fila = respuesta.context["cl"].result_list.get(pk=meta.pk)
        self.assertEqual([fila.valor_2024, fila.valor_2025, fila.valor_2026, fila.valor_2027],
                         [Decimal(0), Decimal(1), Decimal(1), Decimal(0)])


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


class ElCatalogoDeProductosMGA(Base):
    """La 0017 trae del catalogo MGA de junio de 2025 la descripcion y la medida del producto,
    y la unidad y el alcance del indicador, cruzando por codigo."""

    def test_los_datos_de_un_producto_y_su_indicador(self):
        from siifweb.models import IndicadorMGA, ProductoMGA
        producto = ProductoMGA.objects.get(codigo="0401102")
        self.assertTrue(producto.descripcion_producto.startswith("Corresponde al proceso"))
        self.assertEqual(producto.medido_a_traves_de.nombre, "Número de sistemas")
        indicador = IndicadorMGA.objects.get(codigo="040110200")
        self.assertEqual((indicador.unidad_medida.nombre, indicador.es_nacional, indicador.es_territorial),
                         ("Número", True, True))

    def test_medido_a_traves_de_y_unidad_de_medida_son_catalogos_propios(self):
        from siifweb.models import MedidoATravesDe, UnidadMedida
        self.assertEqual(MedidoATravesDe.objects.count(), 161)
        self.assertEqual(sorted(UnidadMedida.objects.values_list("nombre", flat=True)),
                         ["Hectáreas", "Kilómetros", "Metros cuadrados", "Metros cúbicos", "Metros lineales",
                          "Número", "Porcentaje"])
        self.assertEqual(UnidadMedida.objects.get(nombre="Número").indicadores.count() > 300, True)

    def test_cruzan_todos_menos_el_que_ya_no_esta_en_el_catalogo(self):
        from siifweb.models import IndicadorMGA, ProductoMGA
        self.assertEqual(list(ProductoMGA.objects.filter(medido_a_traves_de=None).values_list("codigo", flat=True)),
                         ["4101093"])
        sin_dato = IndicadorMGA.objects.filter(unidad_medida=None)
        self.assertEqual(list(sin_dato.values_list("codigo", flat=True)), ["410109300"])
        self.assertIsNone(sin_dato.get().es_nacional)
        self.assertEqual(IndicadorMGA.objects.filter(es_nacional=False).count(), 127)

    def test_los_listados_muestran_las_columnas_nuevas(self):
        for modelo, texto in (("productomga", "Medido a través de"), ("indicadormga", "Es territorial"),
                              ("medidoatravesde", "Número de sistemas"), ("unidadmedida", "Porcentaje")):
            with self.subTest(modelo=modelo):
                respuesta = self.client.get(reverse(f"admin:siifweb_{modelo}_changelist"), {"q": texto})
                self.assertContains(respuesta, texto)

    def test_la_ficha_de_la_meta_muestra_la_descripcion_del_producto(self):
        meta = MetaIndicador.objects.select_related("indicador_mga__producto_mga").exclude(
            indicador_mga__producto_mga__descripcion_producto="").first()
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(meta.pk,)))
        producto = meta.indicador_mga.producto_mga
        self.assertContains(respuesta, producto.descripcion_producto[:40])

    def test_la_ficha_muestra_la_linea_jerarquica_en_orden(self):
        meta = MetaIndicador.objects.get(codigo="MT323")
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(meta.pk,)))
        etiquetas = [e for e, _ in respuesta.context["jerarquia"]]
        self.assertEqual(etiquetas, ["Plan de desarrollo", "Línea estratégica", "Sector PDD", "Programa PDD",
                                     "Sector MGA", "Programa MGA", "Producto MGA", "Medido a través de",
                                     "Indicador MGA", "Unidad de medida"])
        valores = dict(respuesta.context["jerarquia"])
        self.assertTrue(valores["Indicador MGA"].startswith("240211400 - "))
        self.assertTrue(valores["Producto MGA"].startswith("2402114 - "))
        self.assertTrue(all(valores.values()), valores)
        # Despues de la linea: descripcion, dependencias y ODS, en ese orden
        html = respuesta.content.decode()
        inicio = html.index('<dl class="jerarquia')
        posiciones = [html.index(x, inicio) for x in ("Unidad de medida</dt>", "Descripción del producto",
                                                      ">Dependencia", ">ODS<")]
        self.assertEqual(posiciones, sorted(posiciones))


class LasPlantillas(TestCase):
    def test_ningun_comentario_de_plantilla_ocupa_dos_lineas(self):
        """Django solo reconoce {# ... #} en una linea: partido en dos, sale como texto."""
        from pathlib import Path
        carpeta = Path(__file__).resolve().parent.parent / "templates"
        for plantilla in carpeta.rglob("*.html"):
            for n, linea in enumerate(plantilla.read_text(encoding="utf-8").splitlines(), start=1):
                if "{#" in linea:
                    self.assertIn("#}", linea.split("{#", 1)[1], f"{plantilla.name}:{n}")
