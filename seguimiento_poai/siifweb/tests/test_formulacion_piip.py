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


class CatalogoTerritorial(TestCase):
    """Lo que deja la migracion 0021."""

    def test_trae_los_territoriales_y_las_excepciones_de_bomberos(self):
        self.assertGreater(IndicadorCatalogo.objects.filter(es_territorial=True).count(), 5000)
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

    def test_un_indicador_fuera_del_catalogo_se_crea_y_se_avisa(self):
        carga = carga_piip([fila(CodigoProducto="9999001", Producto="Producto nuevo",
                                 CodigoIndicador="999900100", Indicador="Indicador nuevo",
                                 Programa="9999 - Programa nuevo")])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        nuevo = IndicadorCatalogo.objects.get(codigo="999900100")
        self.assertIsNone(nuevo.es_territorial)
        self.assertEqual(nuevo.producto.programa.codigo, "9999")
        self.assertTrue(ProductoCatalogo.objects.filter(codigo="9999001", nombre="Producto nuevo").exists())
        self.assertIn("se crearon", carga.mensaje)

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
