"""La descarga de la matriz en Excel (fase 7).

Se comprueba la estructura (hojas, tablas, secciones, encabezados, colores, columnas ocultas),
que las columnas de formula lleven formulas con las correcciones del plan (seccion 7.6), que el
resto lleve el valor del sistema y que en el departamento no vayan CERRADO ni DESAPROBADO.

Que las formulas den lo mismo que el sistema se verifico el 27/11/2026 evaluando el archivo
con pycel (564 formulas, con los casos de las cuatro correcciones, sin diferencias). pycel no
corre en Python 3.14, asi que esa verificacion no esta en la suite.
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from siifweb.models import Municipio

from regalias import excel
from regalias.models import ComentarioProyectoRegalias, EstadoProyectoRegalias, ResponsableGesproy

from .fabricas import DEPARTAMENTO, DESCENTRALIZADA, MUNICIPIO, estado, proyecto, usuario_de

E = EstadoProyectoRegalias


def libro(respuesta):
    return load_workbook(BytesIO(respuesta.content))


class Descarga(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de("Regalías", "regalias")
        cls.activo = proyecto("2025000020001", DEPARTAMENTO, estado=estado(E.CONTRATADO_EN_EJECUCION),
                              avance_fisico=Decimal("45.5"), fecha_corte=date(2026, 10, 15), fuentes="SGR - Regional")
        cls.cerrado = proyecto("2025000020002", DEPARTAMENTO, estado=estado(E.CERRADO))
        cls.desaprobado = proyecto("2025000020003", DEPARTAMENTO, estado=estado(E.DESAPROBADO))
        cls.desc = proyecto("2020700010140", DESCENTRALIZADA, estado=estado(E.CERRADO))
        cls.mun = proyecto("2012000020042", MUNICIPIO, estado=estado(E.TERMINADO))
        cls.activo.municipios.set([Municipio.objects.get_or_create(nombre="Sincelejo")[0],
                                   Municipio.objects.get_or_create(nombre="Corozal")[0]])
        cls.activo.responsables_cargue.set([ResponsableGesproy.objects.create(nombre="SERGIO VILLALBA MERCADO")])
        ComentarioProyectoRegalias.objects.create(proyecto=cls.activo, texto="Primero")
        ComentarioProyectoRegalias.objects.create(proyecto=cls.activo, texto="Va bien")
        ComentarioProyectoRegalias.objects.create(proyecto=cls.activo, texto="Datos de la matriz anterior. Fuente: x.")

    def setUp(self):
        self.client.force_login(self.usuario)
        self.respuesta = self.client.get(reverse("admin:regalias_proyectodepartamento_descargar_matriz"))
        self.libro = libro(self.respuesta)

    def filas(self, hoja):
        ws = self.libro[hoja]
        encabezado = [c.value for c in ws[2]]
        return [dict(zip(encabezado, [c.value for c in fila])) for fila in ws.iter_rows(min_row=3)]

    def test_es_un_excel_con_las_tres_hojas_y_sus_tablas(self):
        self.assertEqual(self.respuesta["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("MatrizSeguimientoEvaluacion_", self.respuesta["Content-Disposition"])
        self.assertEqual(self.libro.sheetnames,
                         ["MatrizSeguimientoEvaluacion", "OtrosEjecutoresDescentralizadas", "OtrosEjecutoresMunicipios"])
        for hoja in self.libro.worksheets:
            self.assertEqual(list(hoja.tables), [hoja.title])
            self.assertTrue(list(hoja.tables.values())[0].ref.startswith("A2:"))
        self.assertTrue(self.libro.calculation.fullCalcOnLoad)

    def test_secciones_encabezados_y_columnas_ocultas(self):
        hoja = self.libro["MatrizSeguimientoEvaluacion"]
        self.assertEqual(sorted(str(r) for r in hoja.merged_cells.ranges), ["A1:T1", "AS1:BA1", "U1:AR1"])
        self.assertEqual([c.value for c in hoja[2]], excel.H1_GENERALES + excel.H1_CALIFICACION + excel.H1_EVALUACION)
        self.assertEqual(hoja["U2"].fill.fgColor.rgb[-6:], excel.NARANJA_HEADER)
        self.assertEqual(hoja["BA2"].fill.fgColor.rgb[-6:], excel.VERDE_HEADER)         # MUNICIPIOS
        ocultas = [c.value for c in hoja[2] if hoja.column_dimensions[c.column_letter].hidden]
        self.assertEqual(ocultas, ["COLUMNA APOYO", "COLUMNA APOYO 2"])

    def test_el_departamento_sale_sin_cerrados_ni_desaprobados(self):
        self.assertEqual([f["BPIN"] for f in self.filas("MatrizSeguimientoEvaluacion")], [self.activo.bpin])
        self.assertEqual([f["BPIN"] for f in self.filas("OtrosEjecutoresDescentralizadas")], [self.desc.bpin])
        self.assertEqual([f["BPIN"] for f in self.filas("OtrosEjecutoresMunicipios")], [self.mun.bpin])

    def test_valores_del_sistema_y_formulas_en_sus_columnas(self):
        fila = self.filas("MatrizSeguimientoEvaluacion")[0]
        self.assertEqual((fila["ESTADO PROYECTO"], fila["AVANCE FISICO"], fila["FUENTE DE FINANCIACIÓN"]),
                         ("CONTRATADO EN EJECUCIÓN", 45.5, "SGR - Regional"))
        self.assertEqual(fila["FECHA DE CORTE GESPROY"].date(), date(2026, 10, 15))
        self.assertEqual((fila["MUNICIPIOS"], fila["RESPONSABLE CARGUE EN GESPROY"]),
                         ("Corozal, Sincelejo", "SERGIO VILLALBA MERCADO"))
        self.assertEqual(fila["COMENTARIOS CALIFICACIÓN"], "Va bien")      # sin la nota de la importacion
        for columna in ("DESEMPEÑO EN EL CRONOGRAMA", "BRECHA FISICO - FINANCIERA", "CALIFICACIÓN INFORMACIÓN A TIEMPO",
                        "CALIFICACIÓN EJECUCIÓN DEL PROYECTO"):
            self.assertTrue(str(fila[columna]).startswith("="), columna)
        municipios = self.filas("OtrosEjecutoresMunicipios")[0]
        self.assertFalse(any(str(v).startswith("=") for v in municipios.values()))

    def test_el_rol_puede_descargar_desde_las_tres_listas(self):
        for modelo in ("proyectodescentralizada", "proyectomunicipio"):
            self.assertEqual(self.client.get(reverse(f"admin:regalias_{modelo}_descargar_matriz")).status_code, 200)


class LasFormulasLlevanLasCorrecciones(TestCase):
    """El texto de las formulas: lo que cambia respecto a las del Streamlit (plan, seccion 7.6)."""

    def setUp(self):
        columnas = excel.H1_GENERALES + excel.H1_CALIFICACION + excel.H1_EVALUACION
        self.f = excel.formulas(columnas, 3, departamento=True)

    def test_1_el_tramo_de_100_incluye_1_2(self):
        self.assertIn("$X3>=0.84,$X3<=1.2,", self.f["DESEMPEÑO EN EL CRONOGRAMA"])

    def test_2_sin_acta_pide_las_dos_fechas(self):
        self.assertIn("IF(AND(ISNUMBER($AG3),ISNUMBER($AB3))", self.f["CALIFICACIÓN EJECUCIÓN DEL PROYECTO"])

    def test_4_la_brecha_exige_ejecucion_en_las_cuatro_reglas(self):
        self.assertEqual(self.f["BRECHA FISICO - FINANCIERA"].count('$G3="CONTRATADO EN EJECUCIÓN"'), 4)

    def test_las_referencias_de_descentralizadas_son_las_de_su_hoja(self):
        columnas = excel.DESC_GENERALES + excel.DESC_CALIFICACION + excel.DESC_EVALUACION
        f = excel.formulas(columnas, 3, departamento=False)
        self.assertNotIn("CALIFICACIÓN INFORMACIÓN A TIEMPO", f)                  # en descentralizadas se digita
        self.assertIn("ISNUMBER($AJ3)", f["CALIFICACIÓN EJECUCIÓN DEL PROYECTO"])  # la informacion a tiempo digitada
        self.assertIn('""', f["CALIFICACIÓN EJECUCIÓN DEL PROYECTO"].rsplit(",", 1)[1])


MATRIZ_OCTUBRE = Path(os.environ.get(
    "REGALIAS_MATRIZ_OCTUBRE",
    Path(__file__).resolve().parents[5] / "Estudio" / "python" / "Consolidacion Regalias" / "Regalias octubre"
    / "MatrizSeguimientoEvaluacion_corte_oct2026.xlsx"))


@unittest.skipUnless(MATRIZ_OCTUBRE.exists(), f"no esta {MATRIZ_OCTUBRE.name}")
class LaMismaEstructuraQueLaMatrizDeOctubre(TestCase):
    def test_hojas_tablas_y_encabezados(self):
        octubre = load_workbook(MATRIZ_OCTUBRE, read_only=False)
        nuevo = load_workbook(BytesIO(excel.matriz()))
        self.assertEqual(nuevo.sheetnames, octubre.sheetnames)
        for n, o in zip(nuevo.worksheets, octubre.worksheets):
            with self.subTest(hoja=n.title):
                self.assertEqual(list(n.tables), list(o.tables))
                self.assertEqual([c.value for c in n[2]], [str(c.value).strip() for c in o[2]])
                self.assertEqual(sorted(str(r) for r in n.merged_cells.ranges),
                                 sorted(str(r) for r in o.merged_cells.ranges))
