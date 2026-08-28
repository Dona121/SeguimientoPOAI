# -*- coding: utf-8 -*-
"""El lector de xlsx: la parte que se toco para poder cargar el consolidado de SECOP.

Lo delicado es que `leer_filas` la usan los seis cargadores anteriores, asi que hay
que probar tanto lo nuevo (buscar una TABLA por su nombre) como que lo viejo (buscar
por hoja, o caer en la primera) siga funcionando igual.
"""
from django.test import SimpleTestCase

from siifweb import cargas

from .fabricas import COLUMNAS, fila, libro


class LeerFilasTabla(SimpleTestCase):
    def test_encuentra_la_tabla_en_una_hoja_que_no_es_la_primera(self):
        archivo = libro([fila(), fila(**{"ID Proceso": "CO1.REQ.2",
                                         "ID Contrato": "CO1.PCCNTR.2"})])
        filas = cargas.leer_filas(archivo, tabla="BPIN_por_proceso")
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["ID Proceso"], "CO1.REQ.1")

    def test_da_igual_como_se_llame_la_hoja(self):
        archivo = libro([fila()], hoja="Cualquier Nombre 2026")
        filas = cargas.leer_filas(archivo, tabla="BPIN_por_proceso")
        self.assertEqual(len(filas), 1)

    def test_no_lee_lo_que_este_fuera_del_rango_de_la_tabla(self):
        archivo = libro([fila()], ruido_abajo=True)
        filas = cargas.leer_filas(archivo, tabla="BPIN_por_proceso")
        self.assertEqual(len(filas), 1)
        self.assertNotIn("RUIDO", [f.get("BPIN") for f in filas])

    def test_falla_con_mensaje_claro_si_no_esta_la_tabla(self):
        archivo = libro([fila()], tabla=None)
        with self.assertRaises(ValueError) as error:
            cargas.leer_filas(archivo, tabla="BPIN_por_proceso")
        mensaje = str(error.exception)
        self.assertIn("BPIN_por_proceso", mensaje)
        self.assertIn("Hoja de otro proceso", mensaje)   # enumera las hojas del libro

    def test_falla_si_le_faltan_columnas(self):
        recortadas = [c for c in COLUMNAS if c != "Valor del Contrato"]
        archivo = libro([fila()], columnas=recortadas)
        with self.assertRaises(ValueError) as error:
            cargas.leer_filas(archivo, tabla="BPIN_por_proceso", columnas=COLUMNAS)
        self.assertIn("Valor del Contrato", str(error.exception))

    def test_no_reclama_columnas_de_mas(self):
        columnas = list(COLUMNAS) + ["Columna Extra"]
        archivo = libro([fila()], columnas=columnas)
        filas = cargas.leer_filas(archivo, tabla="BPIN_por_proceso", columnas=COLUMNAS)
        self.assertEqual(len(filas), 1)


class LeerFilasComoAntes(SimpleTestCase):
    """Retrocompatibilidad: los cargadores de SIIFWEB no pasan `tabla`."""

    def test_sin_tabla_usa_la_hoja_pedida(self):
        archivo = libro([fila()], hoja="Hoja1", tabla=None)
        filas = cargas.leer_filas(archivo, hoja="Hoja1")
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["BPIN"], "202500000000001")

    def test_sin_tabla_ni_hoja_cae_en_la_primera(self):
        archivo = libro([fila()], tabla=None)
        filas = cargas.leer_filas(archivo)
        self.assertEqual([f["PERIODO"] for f in filas], ["20260601"])   # la hoja senuelo

    def test_hoja_inexistente_cae_en_la_primera_como_siempre(self):
        archivo = libro([fila()], tabla=None)
        filas = cargas.leer_filas(archivo, hoja="No existe")
        self.assertEqual(len(filas), 1)
        self.assertIn("PERIODO", filas[0])

    def test_descarta_filas_vacias(self):
        archivo = libro([fila(), {c: None for c in COLUMNAS}], tabla=None, hoja="Hoja1")
        filas = cargas.leer_filas(archivo, hoja="Hoja1")
        self.assertEqual(len(filas), 1)
