"""Nombres de archivo que acepta el bucket de Supabase (sin tildes, enes ni simbolos)."""
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase

from siifweb.almacenamiento import S3NombresSeguros, nombre_seguro
from siifweb.models import CargaReporte


class NombreSeguro(SimpleTestCase):
    def test_tildes_enes_espacios_y_simbolos(self):
        casos = {
            "Guía año 2026.pdf": "Guia_ano_2026.pdf",
            "Ejecución (v2) – septiembre.XLSX": "Ejecucion_v2_septiembre.xlsx",
            "reportes/Consolidado de compromisos 30-09.xlsx": "reportes/Consolidado_de_compromisos_30-09.xlsx",
            "cuipo\\recursos\\Circular Nº 5.pdf": "cuipo/recursos/Circular_No_5.pdf",
            "Listas_Categoria_CUIPO_09-2026.xlsx": "Listas_Categoria_CUIPO_09-2026.xlsx",   # ya valido: igual
            "ñññ.pdf": "nnn.pdf",
            "ááá": "aaa",
            "¿?.pdf": "archivo.pdf",
            ".env": "env",
        }
        for crudo, esperado in casos.items():
            with self.subTest(crudo=crudo):
                self.assertEqual(nombre_seguro(crudo), esperado)
                self.assertTrue(nombre_seguro(crudo).isascii())

    def test_produccion_usa_el_almacenamiento_con_nombres_seguros(self):
        # En pruebas STORAGES se cambia por el local; el de produccion se lee del modulo
        import importlib

        import config.settings as modulo
        fuente = importlib.util.find_spec(modulo.__name__).loader.get_source(modulo.__name__)
        self.assertIn('"BACKEND": "siifweb.almacenamiento.S3NombresSeguros"', fuente)
        self.assertTrue(issubclass(S3NombresSeguros, __import__("storages.backends.s3", fromlist=["S3Storage"]).S3Storage))


class CargasConTildes(TestCase):
    def test_el_filefield_guarda_el_nombre_limpio(self):
        carga = CargaReporte(tipo_reporte=CargaReporte._meta.get_field("tipo_reporte").choices[0][0])
        carga.archivo.save("Consolidado de obligación año 2026.xlsx", ContentFile(b"x"), save=False)
        self.assertEqual(carga.archivo.name, "reportes/Consolidado_de_obligacion_ano_2026.xlsx")

    def test_un_save_directo_tambien(self):
        nombre = default_storage.save("pruebas/Guía año.pdf", ContentFile(b"x"))
        self.assertEqual(nombre, "pruebas/Guia_ano.pdf")
        self.assertTrue(default_storage.exists(nombre))
        self.assertIn("ArchivosLocalesNombresSeguros", settings.STORAGES["default"]["BACKEND"])
