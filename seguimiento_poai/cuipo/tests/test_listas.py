"""Importador de las listas CHIP de la categoria CUIPO."""
from io import BytesIO, StringIO
from pathlib import Path
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from cuipo import listas
from cuipo.models import (CPC, ConceptoCUIPO, DetalleSectorial, FuenteCUIPO, PoliticaPublica, ProductoCUIPO,
                          SeccionPresupuestal, SituacionFondos, TerceroCUIPO, VersionListas, VigenciaGasto)


def hojas_minimas():
    """Las once hojas con pocas filas, con los tipos que trae el archivo real."""
    return {
        "Conceptos por ambito": [
            ["Nivel", "CODIGO", "NOMBRE", "438 - DEPARTAMENTOS", "439 - MUNICIPIOS", "Notas"],
            ["S", "2.3", "INVERSION", 1, 1, None],
            ["D", "2.3.2.02.02.009", "SERVICIOS PARA LA COMUNIDAD", 1, 1, None],
            ["D", "2.3.3.05.09.054", "A ESTABLECIMIENTOS PUBLICOS", 0, 1, "Solo municipios"],
            ["D", "2.3.3.05.09.099", "APORTES A ESTABLECIMIENTOS PUBLICOS", 1, 1, None],
            [None, None, None, None, None, None],
        ],
        "Conceptos_CPC": [["Código", "Nombre", "Descripción"], ["2.3.2.02.02.009", "Servicios", "Servicios"],
                          [None, None, None]],
        "CPC": [["Código", "Clase o Subclase", "Sección", "División"],
                ["0", "No aplica", "NO APLICA", "NO APLICA"],
                ["01111", "Trigo semilla", "AGRICULTURA", "PRODUCTOS DE LA AGRICULTURA"],
                [1101001, "Antracita", "MINERALES", "CARBON"],     # numero en Excel, 7 digitos
                [21111, "Carne de bovino", "PRODUCTOS ALIMENTICIOS", "CARNE"]],
        "Fuentes de Financiación": [["Código", "Descripción"], ["1.2.1.0.00", "ICLD"], ["1.3.3.3.20", "R.B. ESTAMPILLAS"]],
        "Tercero": [["Código", "Entidad"], ["0", "OTRO"], ["220170001", "Fondo Mixto"]],
        "Politica Pública": [["Código", "Descripción"], [0, "NO APLICA"], [8182, "PDET"]],
        "Secciones Presupuestales": [["Código", "Descripción", None, "Nota suelta"],
                                     ["16.0", "ADMINISTRACION CENTRAL", None, "no es una columna"],
                                     ["21.0", "SALUD", None, None]],
        "Vigencia Gasto": [["Código", "Descripción", None], [1, "VIGENCIA ACTUAL", None], [2, "RESERVAS", None]],
        "Producto MGA": [["Codigo", "Descripción", "Sector", "Programa", "Aplica a Entidades Territoriales"],
                         ["0101004", "Servicios de difusion", "CONGRESO", "Eficiencia legislativa", None],
                         ["3301053", "Servicio de apoyo", "CULTURA", "Promocion cultural", None],
                         ["3201051", "Producto nuevo", "AMBIENTE", "Programa", "Nuevo"]],
        "Situación de Fondos": [["Código", "Descripción"], ["C", "CON SITUACION DE FONDOS"],
                                ["S", "SIN SITUACION DE FONDOS"]],
        "Detalle Sectorial": [["Código", "Concepto", "Grupo concepto", "Sector", None],
                              [0, "NO APLICA", "NO APLICA", "NO APLICA", None],
                              ["19.01.17", "RS - TRANSFERENCIAS", "RÉGIMEN SUBSIDIADO", "SALUD", None]],
    }


def libro(**cambios):
    """Libro de listas en memoria. cambios: {nombre de hoja (con _ por espacio): filas o None}."""
    hojas = hojas_minimas()
    for clave, filas in cambios.items():
        nombre = next(h for h in hojas if h.replace(" ", "_") == clave or h == clave)
        if filas is None:
            del hojas[nombre]
        else:
            hojas[nombre] = filas
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        hoja = wb.create_sheet(nombre)
        for fila in filas:
            hoja.append(fila)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def importar(nombre="09-2026", **cambios):
    version, _ = VersionListas.objects.get_or_create(nombre=nombre)
    bien = listas.procesar(version, libro(**cambios))
    version.refresh_from_db()
    return bien, version


class ImportarListas(TestCase):
    def test_importa_las_diez_listas(self):
        bien, version = importar()
        self.assertTrue(bien, version.mensaje)
        conteos = {m: m.objects.count() for m in (ConceptoCUIPO, FuenteCUIPO, SeccionPresupuestal, VigenciaGasto,
                                                  ProductoCUIPO, CPC, DetalleSectorial, SituacionFondos,
                                                  PoliticaPublica, TerceroCUIPO)}
        self.assertEqual(list(conteos.values()), [4, 2, 2, 2, 4, 4, 2, 2, 2, 2])  # productos: 3 + el 0
        self.assertEqual(version.estado, VersionListas.Estado.PROCESADO)

    def test_importar_dos_veces_da_lo_mismo(self):
        importar()
        primero = {m: list(m.objects.values_list("codigo", "descripcion", "activo")) for m in (CPC, ConceptoCUIPO)}
        bien, version = importar()
        self.assertTrue(bien, version.mensaje)
        for modelo, antes in primero.items():
            self.assertEqual(list(modelo.objects.values_list("codigo", "descripcion", "activo")), antes)
        self.assertNotIn("nuevos", version.mensaje)
        self.assertNotIn("cambiados", version.mensaje)

    def test_los_codigos_quedan_exactos(self):
        importar()
        self.assertTrue(CPC.objects.filter(codigo="01111").exists())
        self.assertTrue(CPC.objects.filter(codigo="1101001").exists())
        self.assertTrue(ProductoCUIPO.objects.filter(codigo="0101004").exists())
        self.assertEqual(sorted(SeccionPresupuestal.objects.values_list("codigo", flat=True)), ["16.0", "21.0"])
        self.assertEqual(sorted(VigenciaGasto.objects.values_list("codigo", flat=True)), ["1", "2"])
        self.assertEqual(sorted(PoliticaPublica.objects.values_list("codigo", flat=True)), ["0", "8182"])
        self.assertTrue(DetalleSectorial.objects.filter(codigo="0").exists())

    def test_un_cpc_que_perdio_el_cero_en_excel_lo_recupera(self):
        filas = hojas_minimas()["CPC"] + [[1112, "Maiz", "AGRICULTURA", "CEREALES"],
                                          [111202, "Trigo duro", "AGRICULTURA", "CEREALES"]]
        bien, version = importar(CPC=filas)
        self.assertTrue(bien, version.mensaje)
        self.assertTrue(CPC.objects.filter(codigo="01112").exists())
        self.assertTrue(CPC.objects.filter(codigo="0111202").exists())

    def test_un_cpc_de_largo_invalido_aborta_sin_dejar_nada(self):
        filas = hojas_minimas()["CPC"] + [["123", "Malo", "X", "Y"]]
        bien, version = importar(CPC=filas)
        self.assertFalse(bien)
        self.assertIn("123 (largo 3)", version.mensaje)
        self.assertFalse(ConceptoCUIPO.objects.exists())   # tampoco las hojas que si estaban bien
        self.assertEqual(version.estado, VersionListas.Estado.ERROR)

    def test_crea_el_producto_cero(self):
        importar()
        self.assertEqual(ProductoCUIPO.objects.get(codigo="0").descripcion, "NO APLICA")

    def test_conceptos(self):
        importar()
        servicios = ConceptoCUIPO.objects.get(codigo="2.3.2.02.02.009")
        self.assertEqual((servicios.nivel, servicios.habilitado_departamentos, servicios.requiere_cpc), ("D", True, True))
        a_municipios = ConceptoCUIPO.objects.get(codigo="2.3.3.05.09.054")
        self.assertEqual((a_municipios.habilitado_departamentos, a_municipios.requiere_cpc, a_municipios.notas),
                         (False, False, "Solo municipios"))
        self.assertEqual(ConceptoCUIPO.objects.get(codigo="2.3").nivel, "S")

    def test_lo_que_no_viene_queda_inactivo_y_no_se_borra(self):
        importar()
        sin_trigo = [f for f in hojas_minimas()["CPC"] if f[0] != "01111"]
        sin_cpc = [hojas_minimas()["Conceptos_CPC"][0]]
        bien, version = importar("12-2026", CPC=sin_trigo, Conceptos_CPC=sin_cpc)
        self.assertTrue(bien, version.mensaje)
        trigo = CPC.objects.get(codigo="01111")
        self.assertFalse(trigo.activo)
        self.assertEqual(trigo.version.nombre, "09-2026")           # la ultima que lo trajo
        self.assertEqual(CPC.objects.get(codigo="0").version, version)
        self.assertFalse(ConceptoCUIPO.objects.get(codigo="2.3.2.02.02.009").requiere_cpc)
        self.assertIn("1 inactivos", version.mensaje)
        # Si vuelve en otra version, se reactiva
        importar("03-2027")
        self.assertTrue(CPC.objects.get(codigo="01111").activo)

    def test_una_descripcion_cambiada_se_actualiza(self):
        importar()
        fuentes = [["Código", "Descripción"], ["1.2.1.0.00", "ICLD (nuevo nombre)"], ["1.3.3.3.20", "R.B. ESTAMPILLAS"]]
        bien, version = importar("12-2026", Fuentes_de_Financiación=fuentes)
        self.assertEqual(FuenteCUIPO.objects.get(codigo="1.2.1.0.00").descripcion, "ICLD (nuevo nombre)")
        self.assertIn("Fuentes CUIPO: 2 (1 cambiados)", version.mensaje)

    def test_falta_una_hoja(self):
        bien, version = importar(Tercero=None)
        self.assertFalse(bien)
        self.assertIn('le falta la hoja "Tercero"', version.mensaje)
        self.assertFalse(CPC.objects.exists())

    def test_falta_una_columna(self):
        filas = [["Codigo", "Descripción", "Sector"], ["0101004", "Servicios", "CONGRESO"]]
        bien, version = importar(Producto_MGA=filas)
        self.assertFalse(bien)
        self.assertIn("programa", version.mensaje)

    def test_un_codigo_repetido_aborta(self):
        filas = hojas_minimas()["Tercero"] + [["0", "OTRO REPETIDO"]]
        bien, version = importar(Tercero=filas)
        self.assertFalse(bien)
        self.assertIn("repite códigos: 0", version.mensaje)

    def test_un_nivel_desconocido_aborta(self):
        filas = hojas_minimas()["Conceptos por ambito"] + [["X", "2.4", "OTRO", 1, 1, None]]
        bien, version = importar(Conceptos_por_ambito=filas)
        self.assertFalse(bien)
        self.assertIn("2.4 (nivel X)", version.mensaje)

    def test_aplica_a_territoriales_se_guarda_como_viene(self):
        importar()
        self.assertEqual(ProductoCUIPO.objects.get(codigo="3201051").aplica_territoriales, "Nuevo")
        self.assertEqual(ProductoCUIPO.objects.get(codigo="3301053").aplica_territoriales, "")


class ComandoImportar(TestCase):
    def test_importa_desde_un_archivo_del_disco(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "Listas_Categoria_CUIPO_09-2026.xlsx"
            ruta.write_bytes(libro().getvalue())
            salida = StringIO()
            call_command("importar_listas_cuipo", str(ruta), "--version", "09-2026", stdout=salida)
        self.assertIn("Listas CUIPO 09-2026", salida.getvalue())
        version = VersionListas.objects.get(nombre="09-2026")
        self.assertEqual(version.estado, VersionListas.Estado.PROCESADO)
        self.assertFalse(version.archivo)        # el archivo no se sube al almacenamiento
        self.assertEqual(CPC.objects.count(), 4)

    def test_un_archivo_que_no_existe(self):
        with self.assertRaises(CommandError):
            call_command("importar_listas_cuipo", "no-existe.xlsx", "--version", "09-2026")


class AdminDeLasListas(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")
        self.client.force_login(self.usuario)

    def subir(self, nombre="09-2026", datos=None):
        datos = datos or libro().getvalue()
        return self.client.post(reverse("admin:cuipo_versionlistas_add"), {
            "nombre": nombre, "archivo": SimpleUploadedFile("Listas_Categoria_CUIPO_09-2026.xlsx", datos)},
            follow=True)

    def test_al_guardar_se_importa(self):
        respuesta = self.subir()
        self.assertEqual(respuesta.status_code, 200)
        version = VersionListas.objects.get()
        self.assertEqual(version.estado, VersionListas.Estado.PROCESADO, version.mensaje)
        self.assertEqual(version.cargado_por, self.usuario)
        self.assertEqual(TerceroCUIPO.objects.count(), 2)

    def test_el_mismo_archivo_no_se_importa_dos_veces(self):
        datos = libro().getvalue()
        self.subir(datos=datos)
        respuesta = self.subir("12-2026", datos=datos)
        self.assertContains(respuesta, "ya está importado")
        self.assertEqual(VersionListas.objects.count(), 1)

    def test_los_catalogos_se_ven_y_no_se_editan(self):
        self.subir()
        for modelo in ("conceptocuipo", "fuentecuipo", "seccionpresupuestal", "vigenciagasto", "productocuipo",
                       "cpc", "detallesectorial", "situacionfondos", "politicapublica", "tercerocuipo"):
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(reverse(f"admin:cuipo_{modelo}_changelist")).status_code, 200)
        self.assertContains(self.client.get(reverse("admin:cuipo_cpc_changelist"), {"q": "trigo"}), "01111")
        self.assertEqual(self.client.get(reverse("admin:cuipo_cpc_add")).status_code, 403)
        cpc = CPC.objects.get(codigo="01111")
        self.assertEqual(self.client.post(reverse("admin:cuipo_cpc_delete", args=(cpc.pk,)), {"post": "yes"}).status_code,
                         403)

    def test_una_version_con_catalogos_no_se_borra(self):
        self.subir()
        version = VersionListas.objects.get()
        self.client.post(reverse("admin:cuipo_versionlistas_delete", args=(version.pk,)), {"post": "yes"})
        self.assertTrue(VersionListas.objects.filter(pk=version.pk).exists())
