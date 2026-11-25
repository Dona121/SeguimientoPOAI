"""Los scripts de sql/ (reporte de Excel por ODBC) nombran tablas y columnas que existen.

No corren el SQL (es de Postgres y las pruebas usan sqlite): leen los nombres. Si un cambio de
modelos renombra o borra una tabla o columna que usa un script, esta prueba falla y hay que
actualizar el script (y, en produccion, volver a crear la vista: ver el encabezado de
sql/vista_seguimiento_proyectos.sql).
"""
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

CARPETA = Path(settings.BASE_DIR).parent / "sql"
PALABRAS = {"on", "where", "group", "join", "left", "inner", "order", "as", "and", "limit", "using"}


def columnas_por_tabla():
    tablas = {}
    for modelo in apps.get_models(include_auto_created=True):
        tablas[modelo._meta.db_table] = {f.column for f in modelo._meta.local_fields}
    return tablas


def sin_comentarios(texto):
    return re.sub(r"--[^\n]*", "", texto)


class ScriptsSql(SimpleTestCase):
    def setUp(self):
        self.scripts = sorted(CARPETA.glob("*.sql"))
        if not self.scripts:
            self.skipTest("No esta la carpeta sql/")
        self.tablas = columnas_por_tabla()

    def test_las_tablas_existen(self):
        for script in self.scripts:
            usadas = set(re.findall(r"\b(siifweb_[a-z_]+)\b", sin_comentarios(script.read_text(encoding="utf-8"))))
            with self.subTest(script=script.name):
                self.assertTrue(usadas)
                self.assertEqual(usadas - set(self.tablas), set(), "tablas que ya no existen")

    def test_las_columnas_existen(self):
        for script in self.scripts:
            texto = sin_comentarios(script.read_text(encoding="utf-8"))
            alias = {}
            for tabla, nombre in re.findall(r"\b(siifweb_[a-z_]+)\s+(?:as\s+)?([a-z_]+)\b", texto):
                if nombre not in PALABRAS:
                    alias.setdefault(nombre, set()).add(tabla)
            faltan = set()
            for nombre, columna in re.findall(r"\b([a-z_]+)\.([a-z_]+)\b", texto):
                if nombre in alias and not any(columna in self.tablas.get(t, set()) for t in alias[nombre]):
                    faltan.add(f"{nombre}.{columna}")
            with self.subTest(script=script.name):
                self.assertEqual(faltan, set(), "columnas que ya no existen")

    def test_la_vista_no_repite_nombres_ni_pasa_de_63_bytes(self):
        texto = (CARPETA / "vista_seguimiento_proyectos.sql").read_text(encoding="utf-8")
        nombres = re.findall(r'\bas\s+"([^"]+)"', sin_comentarios(texto))
        self.assertGreater(len(nombres), 50)
        self.assertEqual(len(nombres), len(set(nombres)), "columnas repetidas")
        self.assertEqual([n for n in nombres if len(n.encode("utf-8")) > 63], [])
