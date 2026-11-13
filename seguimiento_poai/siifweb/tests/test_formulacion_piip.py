# -*- coding: utf-8 -*-
"""El catalogo PIIP (producto e indicador, vinculado al plan) y la carga de la informacion
general de los proyectos en PIIP (tabla InfoGeneral)."""
import hashlib
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from siifweb import cargas
from siifweb.admin import CargaReporteForm
from siifweb.models import (CargaReporte, Departamento, FormulacionProyecto, IndicadorCatalogo, IndicadorMGA,
                            IndicadorProyecto, Municipio, ProductoCatalogo)

from .fabricas import cadena, libro, proyecto

COLUMNAS = cargas.COLUMNAS_PIIP
HOMOLOGADO = "410402000"      # esta en el plan: queda homologado por codigo
FUERA_DEL_PLAN = "170201200"  # no esta en el plan: se homologa a mano

# Una fila de la tabla con un indicador que esta en el plan (Personas con discapacidad
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
    "Etapa": "Inversión", "UMP": "Número de personas", "CodigoIndicador": HOMOLOGADO,
    "Indicador": "Personas atendidas", "UMI": "Número de personas", "TipoIndicador": "Principal",
    "Acumula": "Si", "MetaTotalIndicador": "300", "Vigencia": "2025", "MetaVigencia": "100",
}


def fila(**cambios):
    return {**FILA, **cambios}


def fuera_del_plan(**cambios):
    return fila(CodigoProducto="1702012", CodigoIndicador=FUERA_DEL_PLAN, **cambios)


def carga_piip(filas):
    datos = libro(filas, tabla="InfoGeneral", hoja="IndicadoresPIIP", columnas=COLUMNAS).getvalue()
    registro = CargaReporte(tipo_reporte=CargaReporte.TipoReporte.PIIP, vigencia=None,
                            hash=hashlib.sha256(datos).hexdigest())
    registro.archivo.save("ReporteSIIFWEB.xlsx", ContentFile(datos), save=True)
    cargas.procesar(registro)
    registro.refresh_from_db()
    return registro


def un_indicador_del_plan_fuera_del_catalogo():
    return (IndicadorMGA.objects.exclude(codigo__in=IndicadorCatalogo.objects.values("codigo"))
            .exclude(codigo="410109300").first())


class CatalogoDeLosProyectos(TestCase):
    """Lo que deja la migracion 0021."""

    def test_trae_solo_los_indicadores_de_los_proyectos_con_su_producto(self):
        # Los 190 codigos de InfoGeneral, no los miles del catalogo MGA
        self.assertEqual(IndicadorCatalogo.objects.count(), 190)
        self.assertEqual(ProductoCatalogo.objects.count(), 187)
        self.assertEqual(IndicadorCatalogo.objects.get(codigo=HOMOLOGADO).producto.codigo, "4104020")

    def test_homologa_por_codigo_con_el_plan(self):
        del_plan = set(IndicadorMGA.objects.values_list("codigo", flat=True))
        for i in IndicadorCatalogo.objects.select_related("indicador_pdd"):
            with self.subTest(codigo=i.codigo):
                if i.codigo in del_plan:
                    self.assertEqual((i.indicador_pdd.codigo, i.homologado_por_codigo), (i.codigo, True))
                else:
                    self.assertIsNone(i.indicador_pdd)
        self.assertEqual(IndicadorCatalogo.objects.filter(homologado_por_codigo=True).count(), 163)

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
        self.assertEqual(f.sector, "Inclusión social y reconciliación")
        self.assertTrue(f.programa.startswith("4104 - "))
        self.assertEqual((f.vigencia_inicio, f.vigencia_fin), (2025, 2026))
        self.assertEqual((f.poblacion_afectada, f.poblacion_objetivo), (1006044, 2470))
        self.assertEqual(sorted(f.municipios.values_list("nombre", flat=True)), ["Corozal", "Sincelejo"])
        [i] = f.indicadores.all()
        self.assertEqual(i.indicador.codigo, HOMOLOGADO)
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
        carga = carga_piip([fila(), fila(CodigoProducto="9999001", Producto="Producto nuevo", UMP="Número de cosas",
                                         CodigoIndicador="999900100", Indicador="Indicador nuevo",
                                         MetaTotalIndicador="10", MetaVigencia="4")])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        nuevo = IndicadorCatalogo.objects.get(codigo="999900100")
        self.assertEqual((nuevo.nombre, nuevo.producto.codigo, nuevo.producto.nombre,
                          nuevo.producto.medido_a_traves_de.nombre),
                         ("Indicador nuevo", "9999001", "Producto nuevo", "Número de cosas"))
        self.assertIsNone(nuevo.indicador_pdd)
        del_proyecto = IndicadorProyecto.objects.get(indicador=nuevo)
        self.assertEqual(del_proyecto.meta_total, Decimal("10"))
        self.assertEqual(list(del_proyecto.metas.values_list("vigencia", "meta")), [(2025, Decimal("4"))])
        self.assertIn("no estaban en el catalogo y se crearon: indicador 999900100 (BPIN 202500000000001); "
                      "producto 9999001 (BPIN 202500000000001)", carga.mensaje)

    def test_lo_que_ya_esta_en_el_catalogo_no_se_cambia(self):
        IndicadorCatalogo.objects.filter(codigo=HOMOLOGADO).update(nombre="Nombre del equipo")
        carga = carga_piip([fila(Indicador="Nombre del PIIP")])
        self.assertEqual(IndicadorCatalogo.objects.get(codigo=HOMOLOGADO).nombre, "Nombre del equipo")
        self.assertNotIn("se crearon", carga.mensaje)

    def test_el_indicador_creado_se_homologa_si_su_codigo_esta_en_el_plan(self):
        del_plan = un_indicador_del_plan_fuera_del_catalogo()
        carga = carga_piip([fila(CodigoIndicador=del_plan.codigo, CodigoProducto=del_plan.codigo[:7])])
        creado = IndicadorCatalogo.objects.get(codigo=del_plan.codigo)
        self.assertEqual((creado.indicador_pdd, creado.homologado_por_codigo), (del_plan, True))
        self.assertIn("1 indicadores homologados por codigo", carga.mensaje)

    def test_homologa_por_codigo_los_que_quedaron_sin_homologar(self):
        IndicadorCatalogo.objects.filter(codigo=HOMOLOGADO).update(indicador_pdd=None, homologado_por_codigo=False)
        carga_piip([fila()])
        i = IndicadorCatalogo.objects.get(codigo=HOMOLOGADO)
        self.assertEqual((i.indicador_pdd.codigo, i.homologado_por_codigo), (HOMOLOGADO, True))

    def test_no_cambia_una_homologacion_hecha_a_mano(self):
        otro = IndicadorMGA.objects.exclude(codigo=HOMOLOGADO).first()
        IndicadorCatalogo.objects.filter(codigo=HOMOLOGADO).update(indicador_pdd=otro, homologado_por_codigo=False)
        carga_piip([fila()])
        self.assertEqual(IndicadorCatalogo.objects.get(codigo=HOMOLOGADO).indicador_pdd, otro)

    def test_proyecto_sin_indicadores(self):
        vacias = {c: None for c in ("ObjetivoEspecifico", "CodigoProducto", "Producto", "Etapa", "UMP",
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

    def test_muestra_datos_generales_y_metas(self):
        carga_piip([fila(), fila(Vigencia="2026", MetaVigencia="200")])
        html = self.html()
        for texto in ("Formulación (PIIP)", "Mejorar la atención", "Inclusión social y reconciliación",
                      "4104 - Atención integral", "Corozal, Sincelejo", "Caribe", "Número de personas",
                      "Meta 2025", "Meta 2026"):
            self.assertIn(texto, html)
        self.assertNotIn("{#", html)

    def test_homologado_muestra_lo_del_piip_y_la_linea_del_plan_aunque_coincidan(self):
        carga_piip([fila()])
        tabla = self.html().split("Indicadores de producto")[1]
        # El codigo del indicador sale dos veces: el del PIIP y el del plan, que coinciden
        self.assertEqual(tabla.count(f">{HOMOLOGADO}<"), 2)
        self.assertEqual(tabla.count(">4104020<"), 2)
        self.assertIn("41 - Inclusión social y reconciliación", tabla)
        self.assertIn("4104 - ", tabla)
        self.assertIn("Por código", tabla)
        self.assertNotIn("Sin homologar", tabla)

    def test_sin_homologar_solo_muestra_lo_del_piip(self):
        carga_piip([fuera_del_plan()])
        tabla = self.html().split("Indicadores de producto")[1]
        self.assertEqual(tabla.count(f">{FUERA_DEL_PLAN}<"), 1)
        self.assertIn("Sin homologar", tabla)

    def test_homologado_a_mano_lo_dice(self):
        carga_piip([fuera_del_plan()])
        IndicadorCatalogo.objects.filter(codigo=FUERA_DEL_PLAN).update(
            indicador_pdd=IndicadorMGA.objects.get(codigo=HOMOLOGADO))
        tabla = self.html().split("Indicadores de producto")[1]
        self.assertIn(f">{FUERA_DEL_PLAN}<", tabla)
        self.assertIn(f">{HOMOLOGADO}<", tabla)
        self.assertIn("Homologado a mano", tabla)


class SeccionDelMenu(TestCase):
    ORDEN = ["formulacionproyecto", "productocatalogo", "indicadorcatalogo"]

    def seccion(self):
        return next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Catálogo PIIP")

    def test_va_despues_del_plan_con_sus_modelos(self):
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
        for rol in ("Seguimiento", "Consulta"):
            usuario = get_user_model().objects.create_user(f"u_{rol}", "x@b.co", "clave", is_staff=True)
            usuario.groups.add(Group.objects.get(name=rol))
            peticion = type("Peticion", (), {"user": usuario})()
            with self.subTest(rol=rol):
                self.assertFalse(any(item["permission"](peticion) for item in self.seccion()["items"]))


class EditarElIndicador(TestCase):
    """La ficha del indicador del catalogo: sus datos y su indicador del plan."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", "a@b.co", "clave"))
        self.indicador = IndicadorCatalogo.objects.get(codigo=FUERA_DEL_PLAN)
        self.del_plan = IndicadorMGA.objects.get(codigo=HOMOLOGADO)
        self.url = reverse("admin:siifweb_indicadorcatalogo_change", args=(self.indicador.pk,))

    def datos(self, **cambios):
        i = self.indicador
        datos = {"producto": str(i.producto_id), "codigo": i.codigo, "nombre": i.nombre,
                 "unidad_medida": str(i.unidad_medida_id or ""), "indicador_pdd": "", "observacion": "",
                 "_save": "Guardar"}
        datos.update(cambios)
        return datos

    def test_la_lista_dice_si_esta_homologado(self):
        html = self.client.get(reverse("admin:siifweb_indicadorcatalogo_changelist") + "?homologado=no").content.decode()
        self.assertIn(FUERA_DEL_PLAN, html)
        self.assertNotIn(HOMOLOGADO, html)

    def test_homologar_a_mano(self):
        respuesta = self.client.post(self.url, self.datos(indicador_pdd=str(self.del_plan.pk),
                                                          observacion="Mide lo mismo"))
        self.assertEqual(respuesta.status_code, 302)
        self.indicador.refresh_from_db()
        self.assertEqual((self.indicador.indicador_pdd, self.indicador.observacion,
                          self.indicador.homologado_por_codigo), (self.del_plan, "Mide lo mismo", False))

    def test_la_ficha_muestra_la_linea_del_plan(self):
        IndicadorCatalogo.objects.filter(pk=self.indicador.pk).update(indicador_pdd=self.del_plan)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Sector:", html)
        self.assertIn("Programa:", html)
        self.assertIn("Producto:", html)

    def test_los_datos_se_editan(self):
        respuesta = self.client.post(self.url, self.datos(nombre="Otro nombre"))
        self.assertEqual(respuesta.status_code, 302)
        self.indicador.refresh_from_db()
        self.assertEqual(self.indicador.nombre, "Otro nombre")

    def test_agregar_un_indicador_con_codigo_del_plan_lo_homologa_por_codigo(self):
        del_plan = un_indicador_del_plan_fuera_del_catalogo()
        datos = self.datos(codigo=del_plan.codigo, nombre="Nuevo")
        respuesta = self.client.post(reverse("admin:siifweb_indicadorcatalogo_add"), datos)
        self.assertEqual(respuesta.status_code, 302)
        nuevo = IndicadorCatalogo.objects.get(codigo=del_plan.codigo)
        self.assertEqual((nuevo.indicador_pdd, nuevo.homologado_por_codigo), (del_plan, True))

    def test_solo_se_borra_lo_que_no_esta_en_uso(self):
        libre = IndicadorCatalogo.objects.create(codigo="999999999", nombre="Sin uso",
                                                 producto=self.indicador.producto)
        borrar = reverse("admin:siifweb_indicadorcatalogo_delete", args=(libre.pk,))
        self.assertEqual(self.client.post(borrar, {"post": "yes"}).status_code, 302)
        self.assertFalse(IndicadorCatalogo.objects.filter(pk=libre.pk).exists())
        proy = proyecto()
        cadena(proy)
        carga_piip([fuera_del_plan()])
        usado = reverse("admin:siifweb_indicadorcatalogo_delete", args=(self.indicador.pk,))
        self.client.post(usado, {"post": "yes"})
        self.assertTrue(IndicadorCatalogo.objects.filter(pk=self.indicador.pk).exists())


class LaCargaNoTocaLaHomologacion(TestCase):
    def test_volver_a_cargar_conserva_la_homologacion_manual(self):
        proy = proyecto()
        cadena(proy)
        carga_piip([fuera_del_plan()])
        del_plan = IndicadorMGA.objects.get(codigo=HOMOLOGADO)
        IndicadorCatalogo.objects.filter(codigo=FUERA_DEL_PLAN).update(indicador_pdd=del_plan,
                                                                       observacion="Mide lo mismo")
        carga_piip([fuera_del_plan(), fuera_del_plan(Vigencia="2026", MetaVigencia="5")])
        i = IndicadorCatalogo.objects.get(codigo=FUERA_DEL_PLAN)
        self.assertEqual((i.indicador_pdd, i.observacion), (del_plan, "Mide lo mismo"))
        self.assertEqual(IndicadorProyecto.objects.get(formulacion__proyecto=proy).indicador.indicador_pdd, del_plan)
