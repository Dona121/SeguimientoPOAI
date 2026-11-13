# -*- coding: utf-8 -*-
"""El catalogo MGA territorial, su homologacion con el plan y la carga de la
informacion general de los proyectos en PIIP (tabla InfoGeneral)."""
import hashlib
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from siifweb import cargas
from siifweb.admin import CargaReporteForm
from siifweb.models import (CargaReporte, Departamento, FormulacionProyecto, HomologacionIndicador,
                            IndicadorCatalogo, IndicadorMGA, IndicadorProyecto, Municipio, ProductoCatalogo)

from .fabricas import cadena, libro, proyecto

COLUMNAS = cargas.COLUMNAS_PIIP

# Una fila de la tabla con un indicador del catalogo territorial (Personas con discapacidad
# atendidas, del producto 4104020); cada prueba cambia lo que le interesa
FILA = {
    "NombreArchivo": "Reporte Ficha actualizada del proyecto_12112026164549.xlsx",
    "BPIN": "202500000000001",
    "SectorProyecto": "Inclusión social y reconciliación",
    "Programa": "4104 - Atención integral de población en situación permanente de desprotección social y/o familiar",
    "Inicio": "2025", "Fin": "2026",
    "ObjetivoGeneral": "Mejorar la atención", "Problema": "Baja atención", "Descripcion": "Se atiende",
    "PoblacionAfectada": "1006044", "PoblacionObjetivo": "2470",
    "Región": "Caribe", "Departamento": "Sucre", "Municipios": "Sincelejo, Corozal",
    "ObjetivoEspecifico": "Atender a la población",
    "CodigoProducto": "4104020",
    "Producto": "Servicio de atención integral a población en condición de discapacidad     (Producto principal del proyecto)",
    "Etapa": "Inversión", "CodigoIndicador": "410402000", "Indicador": "Personas atendidas",
    "UMI": "Número de personas", "TipoIndicador": "Principal", "Acumula": "Si",
    "MetaTotalIndicador": "300", "Vigencia": "2025", "MetaVigencia": "100",
}


def fila(**cambios):
    return {**FILA, **cambios}


def carga_piip(filas):
    datos = libro(filas, tabla="InfoGeneral", hoja="IndicadoresPIIP", columnas=COLUMNAS).getvalue()
    registro = CargaReporte(tipo_reporte=CargaReporte.TipoReporte.PIIP, vigencia=None,
                            hash=hashlib.sha256(datos).hexdigest())
    registro.archivo.save("ReporteSIIFWEB.xlsx", ContentFile(datos), save=True)
    cargas.procesar(registro)
    registro.refresh_from_db()
    return registro


class CatalogoDeLosProyectos(TestCase):
    """Lo que deja la migracion 0021."""

    def test_trae_solo_los_indicadores_de_los_proyectos(self):
        # Los 190 codigos de InfoGeneral, no los 5.739 territoriales del catalogo
        self.assertEqual(IndicadorCatalogo.objects.count(), 190)
        self.assertEqual(ProductoCatalogo.objects.count(), 187)
        # Validados por codigo contra el catalogo: entran aunque no sean territoriales
        self.assertEqual(set(IndicadorCatalogo.objects.filter(es_territorial=False).values_list("codigo", flat=True)),
                         {"370800900", "370801300"})

    def test_homologa_por_codigo_los_indicadores_del_plan(self):
        con_par = IndicadorMGA.objects.filter(codigo__in=IndicadorCatalogo.objects.values("codigo"))
        self.assertEqual(HomologacionIndicador.objects.filter(por_codigo=True).count(), con_par.count())
        for h in HomologacionIndicador.objects.select_related("indicador", "indicador_pdd")[:50]:
            self.assertEqual(h.indicador.codigo, h.indicador_pdd.codigo)
        # El del plan que ya no esta en el catalogo de 2025 queda para homologar a mano
        self.assertFalse(HomologacionIndicador.objects.filter(indicador_pdd__codigo="410109300").exists())

    def test_los_municipios_existentes_son_de_sucre(self):
        sucre = Departamento.objects.get(nombre="Sucre")
        self.assertEqual(sucre.region, "Caribe")
        self.assertFalse(Municipio.objects.filter(departamento__isnull=True).exists())


class CargaPIIP(TestCase):
    def setUp(self):
        self.proy = proyecto()
        cadena(self.proy)   # tiene documentos en SIIFWEB

    def test_carga_la_formulacion_con_sus_indicadores_y_metas(self):
        carga = carga_piip([fila(), fila(Vigencia="2026", MetaVigencia="200")])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        f = FormulacionProyecto.objects.get(proyecto=self.proy)
        self.assertEqual(f.programa.codigo, "4104")
        self.assertEqual(f.sector.codigo, "41")
        self.assertEqual((f.vigencia_inicio, f.vigencia_fin), (2025, 2026))
        self.assertEqual((f.poblacion_afectada, f.poblacion_objetivo), (1006044, 2470))
        self.assertEqual(sorted(f.municipios.values_list("nombre", flat=True)), ["Corozal", "Sincelejo"])
        [i] = f.indicadores.all()
        self.assertEqual(i.indicador.codigo, "410402000")
        self.assertEqual(i.producto.codigo, "4104020")   # el producto sale del indicador
        self.assertTrue(i.producto_principal)
        self.assertEqual((i.etapa, i.tipo, i.acumula), ("inversion", "principal", True))
        self.assertEqual(i.unidad_medida, "Número de personas")
        self.assertEqual(i.meta_total, Decimal("300"))
        self.assertEqual(list(i.metas.values_list("vigencia", "meta")),
                         [(2025, Decimal("100")), (2026, Decimal("200"))])

    def test_solo_entran_los_bpin_con_documentos_en_siifweb(self):
        proyecto(bpin="202500000000002", nombre="Sin ejecucion")   # en la base, sin documentos
        carga = carga_piip([fila(), fila(BPIN="202500000000002"), fila(BPIN="202500000000003")])
        self.assertEqual(list(FormulacionProyecto.objects.values_list("proyecto__bpin", flat=True)),
                         ["202500000000001"])
        self.assertIn("2 BPIN sin ejecucion en SIIFWEB", carga.mensaje)

    def test_volver_a_cargar_reemplaza_la_formulacion_del_bpin(self):
        carga_piip([fila(), fila(Vigencia="2026", MetaVigencia="200")])
        carga_piip([fila(MetaVigencia="150", Problema="Otro problema")])
        f = FormulacionProyecto.objects.get(proyecto=self.proy)
        self.assertEqual(f.problema, "Otro problema")
        self.assertEqual(IndicadorProyecto.objects.count(), 1)
        self.assertEqual(list(f.indicadores.get().metas.values_list("vigencia", "meta")), [(2025, Decimal("150"))])

    def test_el_indicador_bajo_dos_objetivos_no_duplica_la_meta(self):
        carga_piip([fila(), fila(ObjetivoEspecifico="Dotar la estación")])
        i = IndicadorProyecto.objects.get()
        self.assertEqual(i.objetivo_especifico, "Atender a la población\nDotar la estación")
        self.assertEqual(i.metas.get().meta, Decimal("100"))

    def test_municipio_con_coma_y_departamento_de_fuera(self):
        Municipio.objects.create(nombre="Bogotá, D.C.")
        carga = carga_piip([fila(Municipios="Bogotá, D.C.", Departamento="Distrito Capital", Región="Andina")])
        bogota = Municipio.objects.get(nombre="Bogotá, D.C.")
        self.assertEqual(list(FormulacionProyecto.objects.get().municipios.all()), [bogota])
        self.assertEqual((bogota.departamento.nombre, bogota.departamento.region), ("Distrito Capital", "Andina"))
        self.assertNotIn("municipios que no estan", carga.mensaje)

    def test_avisa_los_municipios_que_no_estan_en_el_admin(self):
        carga = carga_piip([fila(Municipios="Sincelejo, Garzón")])
        self.assertIn("municipios que no estan en el admin: Garzón", carga.mensaje)
        self.assertEqual(list(FormulacionProyecto.objects.get().municipios.values_list("nombre", flat=True)),
                         ["Sincelejo"])

    def test_un_indicador_fuera_del_catalogo_se_crea_y_se_asocia_con_sus_metas(self):
        carga = carga_piip([fila(), fila(CodigoProducto="9999001", Producto="Producto nuevo",
                                         CodigoIndicador="999900100", Indicador="Indicador nuevo",
                                         MetaTotalIndicador="10", MetaVigencia="4")])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        nuevo = IndicadorCatalogo.objects.get(codigo="999900100")
        self.assertEqual((nuevo.nombre, nuevo.producto.codigo, nuevo.producto.nombre, nuevo.producto.programa.codigo),
                         ("Indicador nuevo", "9999001", "Producto nuevo", "9999"))
        self.assertIsNone(nuevo.es_territorial)
        del_proyecto = IndicadorProyecto.objects.get(indicador=nuevo)
        self.assertEqual(del_proyecto.meta_total, Decimal("10"))
        self.assertEqual(list(del_proyecto.metas.values_list("vigencia", "meta")), [(2025, Decimal("4"))])
        self.assertIn("no estaban en el catalogo y se crearon: indicador 999900100 (BPIN 202500000000001); "
                      "producto 9999001 (BPIN 202500000000001); programa 9999", carga.mensaje)

    def test_lo_que_ya_esta_en_el_catalogo_no_se_cambia(self):
        IndicadorCatalogo.objects.filter(codigo="410402000").update(nombre="Nombre del equipo")
        carga = carga_piip([fila(Indicador="Nombre del PIIP")])
        self.assertEqual(IndicadorCatalogo.objects.get(codigo="410402000").nombre, "Nombre del equipo")
        self.assertNotIn("se crearon", carga.mensaje)

    def test_el_indicador_creado_se_homologa_si_su_codigo_esta_en_el_plan(self):
        del_plan = IndicadorMGA.objects.exclude(codigo__in=IndicadorCatalogo.objects.values("codigo"))             .exclude(codigo="").exclude(codigo="410109300").first()
        carga_piip([fila(CodigoIndicador=del_plan.codigo, CodigoProducto=del_plan.codigo[:7])])
        h = HomologacionIndicador.objects.get(indicador__codigo=del_plan.codigo)
        self.assertEqual((h.indicador_pdd, h.por_codigo), (del_plan, True))

    def test_homologa_por_codigo_los_indicadores_que_no_tienen_homologacion(self):
        del_plan = IndicadorMGA.objects.filter(codigo="410402000").first()
        if del_plan is None:
            self.skipTest("410402000 no esta en el plan")
        HomologacionIndicador.objects.filter(indicador__codigo="410402000").delete()
        carga = carga_piip([fila()])
        h = HomologacionIndicador.objects.get(indicador__codigo="410402000")
        self.assertEqual((h.indicador_pdd, h.por_codigo), (del_plan, True))
        self.assertIn("1 homologaciones nuevas por codigo", carga.mensaje)

    def test_no_vuelve_a_homologar_el_que_ya_tiene_una_manual(self):
        otro = IndicadorMGA.objects.exclude(codigo="410402000").exclude(codigo="").first()
        HomologacionIndicador.objects.filter(indicador__codigo="410402000").delete()
        manual = HomologacionIndicador.objects.create(
            indicador=IndicadorCatalogo.objects.get(codigo="410402000"), indicador_pdd=otro)
        carga_piip([fila()])
        self.assertEqual(list(HomologacionIndicador.objects.filter(indicador__codigo="410402000")), [manual])

    def test_proyecto_sin_indicadores(self):
        vacias = {c: None for c in ("ObjetivoEspecifico", "CodigoProducto", "Producto", "Etapa",
                                    "CodigoIndicador", "Indicador", "UMI", "TipoIndicador", "Acumula",
                                    "MetaTotalIndicador", "Vigencia", "MetaVigencia")}
        carga = carga_piip([fila(**vacias)])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        self.assertFalse(FormulacionProyecto.objects.get().indicadores.exists())


class MismoLibroParaSecopYPIIP(TestCase):
    """SECOP II y la informacion general del PIIP salen del mismo libro."""

    def formulario(self, tipo, datos):
        return CargaReporteForm(data={"tipo_reporte": tipo, "fecha_descarga": "2026-11-12"},
                                files={"archivo": ContentFile(datos, name="ReporteSIIFWEB.xlsx")})

    def test_el_mismo_archivo_se_puede_cargar_para_cada_tipo_una_vez(self):
        datos = b"el mismo libro"
        CargaReporte.objects.create(tipo_reporte=CargaReporte.TipoReporte.SECOP,
                                    hash=hashlib.sha256(datos).hexdigest(), archivo="reportes/x.xlsx")
        self.assertTrue(self.formulario(CargaReporte.TipoReporte.PIIP, datos).is_valid())
        otro = self.formulario(CargaReporte.TipoReporte.SECOP, datos)
        self.assertFalse(otro.is_valid())
        self.assertIn("ya fue cargado", str(otro.errors))


class PestanaDeLaFicha(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@b.co", "clave"))
        self.proy = proyecto()
        cadena(self.proy)

    def html(self):
        url = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.proy.pk,)) + "?panel=piip"
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.content.decode()

    def test_sin_formulacion_lo_dice(self):
        self.assertIn("no tiene formulación del PIIP cargada", self.html())

    def test_muestra_datos_generales_indicadores_y_homologacion(self):
        carga_piip([fila(), fila(Vigencia="2026", MetaVigencia="200")])
        html = self.html()
        for texto in ("Formulación (PIIP)", "Mejorar la atención", "4104 - ", "Corozal, Sincelejo", "Caribe",
                      "410402000", "4104020", "Producto principal", "Número de personas", "Meta 2025",
                      "Meta 2026"):
            self.assertIn(texto, html)
        homologado = HomologacionIndicador.objects.filter(indicador__codigo="410402000").exists()
        self.assertEqual("Sin homologar" not in html, homologado)


class SeccionDelMenu(TestCase):
    ORDEN = ["formulacionproyecto", "homologacionindicador", "sectorcatalogo", "programacatalogo",
             "productocatalogo", "indicadorcatalogo"]

    def seccion(self):
        from django.conf import settings
        return next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Catálogo PIIP")

    def test_va_despues_del_plan_con_sus_modelos(self):
        from django.conf import settings
        titulos = [g["title"] for g in settings.UNFOLD["SIDEBAR"]["navigation"]]
        self.assertEqual(titulos.index("Catálogo PIIP"), titulos.index("Plan de Desarrollo") + 1)
        self.assertEqual([str(i["link"]) for i in self.seccion()["items"]],
                         [reverse(f"admin:siifweb_{m}_changelist") for m in self.ORDEN])

    def test_cada_enlace_abre_su_listado(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@b.co", "clave"))
        for item in self.seccion()["items"]:
            with self.subTest(item=item["title"]):
                self.assertEqual(self.client.get(str(item["link"])).status_code, 200)

    def test_los_roles_del_equipo_no_la_ven(self):
        from django.contrib.auth.models import Group
        for rol in ("Seguimiento", "Consulta"):
            usuario = get_user_model().objects.create_user(f"u_{rol}", "x@b.co", "clave", is_staff=True)
            usuario.groups.add(Group.objects.get(name=rol))
            peticion = type("Peticion", (), {"user": usuario})()
            with self.subTest(rol=rol):
                self.assertFalse(any(item["permission"](peticion) for item in self.seccion()["items"]))


class EditarElIndicador(TestCase):
    """La ficha del indicador del catalogo: sus datos editables y la homologacion debajo."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@b.co", "clave"))
        # Uno de los que no estan en el plan: no tiene homologacion por codigo
        self.indicador = IndicadorCatalogo.objects.get(codigo="170201200")
        self.del_plan = IndicadorMGA.objects.exclude(codigo="").first()
        self.url = reverse("admin:siifweb_indicadorcatalogo_change", args=(self.indicador.pk,))

    def datos(self, **cambios):
        i = self.indicador
        nulo = lambda v: "unknown" if v is None else str(v).lower()
        datos = {"codigo": i.codigo, "nombre": i.nombre, "producto": str(i.producto_id),
                 "unidad_medida": str(i.unidad_medida_id or ""), "es_principal": nulo(i.es_principal),
                 "es_nacional": nulo(i.es_nacional), "es_territorial": nulo(i.es_territorial),
                 "homologaciones-TOTAL_FORMS": "1", "homologaciones-INITIAL_FORMS": "0",
                 "homologaciones-MIN_NUM_FORMS": "0", "homologaciones-MAX_NUM_FORMS": "1000",
                 "homologaciones-0-indicador_pdd": str(self.del_plan.pk),
                 "homologaciones-0-observacion": "Mide lo mismo", "_save": "Guardar"}
        datos.update(cambios)
        return datos

    def test_sin_homologar_abre_con_la_fila_para_elegir(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="homologaciones-0-indicador_pdd"', html)

    def test_guardar_crea_la_homologacion_manual(self):
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 302)
        h = HomologacionIndicador.objects.get(indicador=self.indicador)
        self.assertEqual((h.indicador_pdd, h.observacion, h.por_codigo), (self.del_plan, "Mide lo mismo", False))

    def test_los_datos_del_catalogo_se_editan(self):
        respuesta = self.client.post(self.url, self.datos(nombre="Otro nombre",
                                                          **{"homologaciones-TOTAL_FORMS": "0"}))
        self.assertEqual(respuesta.status_code, 302)
        self.indicador.refresh_from_db()
        self.assertEqual(self.indicador.nombre, "Otro nombre")

    def test_se_agregan_indicadores(self):
        self.assertEqual(self.client.get(reverse("admin:siifweb_indicadorcatalogo_add")).status_code, 200)
        for modelo in ("sectorcatalogo", "programacatalogo", "productocatalogo"):
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(reverse(f"admin:siifweb_{modelo}_add")).status_code, 200)

    def test_solo_se_borra_lo_que_no_esta_en_uso(self):
        libre = IndicadorCatalogo.objects.create(codigo="999999999", nombre="Sin uso",
                                                 producto=self.indicador.producto)
        borrar = reverse("admin:siifweb_indicadorcatalogo_delete", args=(libre.pk,))
        self.assertEqual(self.client.post(borrar, {"post": "yes"}).status_code, 302)
        self.assertFalse(IndicadorCatalogo.objects.filter(pk=libre.pk).exists())
        # Un indicador que usa un proyecto: el admin muestra que esta protegido y no lo borra
        proy = proyecto()
        cadena(proy)
        carga_piip([fila(CodigoProducto="1702012", CodigoIndicador="170201200")])
        usado = reverse("admin:siifweb_indicadorcatalogo_delete", args=(self.indicador.pk,))
        self.client.post(usado, {"post": "yes"})
        self.assertTrue(IndicadorCatalogo.objects.filter(pk=self.indicador.pk).exists())


class LaCargaNoTocaLaHomologacion(TestCase):
    def test_volver_a_cargar_conserva_la_homologacion_manual(self):
        proy = proyecto()
        cadena(proy)
        fuera_del_plan = fila(CodigoProducto="1702012", CodigoIndicador="170201200")
        carga_piip([fuera_del_plan])
        indicador = IndicadorCatalogo.objects.get(codigo="170201200")
        manual = HomologacionIndicador.objects.create(
            indicador=indicador, indicador_pdd=IndicadorMGA.objects.exclude(codigo="").first(),
            observacion="Mide lo mismo")
        carga_piip([fuera_del_plan, fila(CodigoProducto="1702012", CodigoIndicador="170201200",
                                         Vigencia="2026", MetaVigencia="5")])
        self.assertTrue(HomologacionIndicador.objects.filter(pk=manual.pk, observacion="Mide lo mismo").exists())
        # Y el indicador del proyecto la sigue viendo
        self.assertEqual(IndicadorProyecto.objects.get(formulacion__proyecto=proy).indicador.homologaciones.get(),
                         manual)


class HomologarAlAgregarEnElAdmin(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@b.co", "clave"))

    def test_agregar_un_indicador_con_codigo_del_plan_lo_homologa(self):
        # Un indicador del plan cuyo codigo no esta en el catalogo de los proyectos
        del_plan = IndicadorMGA.objects.exclude(codigo__in=IndicadorCatalogo.objects.values("codigo"))             .exclude(codigo="").exclude(codigo="410109300").first()
        producto = ProductoCatalogo.objects.first()
        datos = {"codigo": del_plan.codigo, "nombre": "Nuevo", "producto": str(producto.pk), "unidad_medida": "",
                 "es_principal": "unknown", "es_nacional": "unknown", "es_territorial": "unknown",
                 "homologaciones-TOTAL_FORMS": "0", "homologaciones-INITIAL_FORMS": "0",
                 "homologaciones-MIN_NUM_FORMS": "0", "homologaciones-MAX_NUM_FORMS": "1000", "_save": "Guardar"}
        respuesta = self.client.post(reverse("admin:siifweb_indicadorcatalogo_add"), datos)
        self.assertEqual(respuesta.status_code, 302)
        h = HomologacionIndicador.objects.get(indicador__codigo=del_plan.codigo)
        self.assertEqual((h.indicador_pdd, h.por_codigo), (del_plan, True))
