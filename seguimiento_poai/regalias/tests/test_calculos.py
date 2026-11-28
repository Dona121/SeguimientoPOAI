"""Los campos calculados: dias y formulas de la matriz (regalias.calculos).

Los casos salen de las formulas de Excel del Streamlit y de las cuatro correcciones del
27/11/2026 (plan, seccion 7.6). La prueba de paridad importa la matriz real de junio y compara
contra los valores que Excel dejo calculados en el archivo: las unicas diferencias admitidas son
las de esas correcciones.
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from regalias import calculos, servicios
from regalias.cargas import importar_matriz
from regalias.models import CambioProyectoRegalias, CargaRegalias, EstadoProyectoRegalias, ProyectoRegalias

from .fabricas import DEPARTAMENTO, DESCENTRALIZADA, estado, proyecto, usuario_de

E = EstadoProyectoRegalias


def ficticio(codigo_estado=E.CONTRATADO_EN_EJECUCION, codigo=DEPARTAMENTO, **campos):
    """Un proyecto en memoria, sin base: las funciones de calculos son puras."""
    base = dict(spi=None, cpi=None, avance_fisico=None, avance_financiero=None, control_externalidades=None,
                horizonte=None, fecha_corte=None, informacion_solicitada="", cal_informacion_a_tiempo=None,
                fecha_recibo_informacion=None, fecha_aprobacion=None, fecha_apertura_primer_proceso=None,
                fecha_suscripcion_principal=None, fecha_suscripcion_primer_contrato=None)
    base.update(campos)
    return SimpleNamespace(estado=SimpleNamespace(codigo=codigo_estado) if codigo_estado else None,
                           clasificacion=SimpleNamespace(codigo=codigo), **base)


def d(valor):
    return Decimal(str(valor))


class Desempeno(TestCase):
    def test_los_tramos_del_spi(self):
        casos = {"1.31": 0, "1.3": 30, "1.25": 90, "1.2": 100, "0.84": 100, "0.61": 50, "0.2": 0}
        for spi, esperado in casos.items():
            with self.subTest(spi=spi):
                self.assertEqual(calculos.redondear(calculos.desempeno(d(spi), True)), d(esperado))

    def test_sin_indice_en_ejecucion_da_cero_y_fuera_de_ejecucion_vacio(self):
        self.assertEqual(calculos.desempeno(None, True), 0)
        self.assertIsNone(calculos.desempeno(d("1"), False))


class Apoyos(TestCase):
    def test_columna_apoyo(self):
        self.assertEqual(calculos.columna_apoyo(d(25), d(65)), 100)      # brecha 40 con 60 <= af < 70
        self.assertEqual(calculos.columna_apoyo(d(24), d(65)), 0)        # brecha 41
        self.assertEqual(calculos.columna_apoyo(d(95), d(100)), 100)     # tramo de 90 a 100, brecha 5
        self.assertIsNone(calculos.columna_apoyo(d(100), d(101)))
        self.assertEqual(calculos.columna_apoyo(None, None), 100)        # vacio vale 0, como en Excel

    def test_brecha_solo_en_ejecucion(self):
        self.assertIsNone(calculos.brecha_fisico_financiera(d(99), d(100), d(100), False))
        self.assertEqual(calculos.brecha_fisico_financiera(d(50), d(40), None, True), 100)    # fisico adelante
        self.assertEqual(calculos.brecha_fisico_financiera(d(10), d(70), None, True), 0)      # brecha > 50
        self.assertEqual(calculos.brecha_fisico_financiera(d(30), d(55), None, True), 100)    # af <= 60
        self.assertEqual(calculos.brecha_fisico_financiera(d(60), d(85), d(0), True), 0)      # toma la columna apoyo
        self.assertIsNone(calculos.brecha_fisico_financiera(d(50), d(50), d(100), True))

    def test_columna_apoyo_2(self):
        for ext, esperado in ((None, 100), (0, 100), (1, 90), (2, 75), (5, 25), (6, 0), (9, 0)):
            self.assertEqual(calculos.columna_apoyo_2(ext), esperado)

    def test_informacion_a_tiempo(self):
        for dia, esperado in ((10, 100), (11, 80), (12, 50), (13, 0)):
            self.assertEqual(calculos.informacion_a_tiempo(date(2026, 5, dia)), esperado)
        self.assertIsNone(calculos.informacion_a_tiempo(None))


class CalificacionDeEjecucion(TestCase):
    EN_REGLA = dict(spi=d(1), cpi=d(1), avance_fisico=d(50), avance_financiero=d(40),
                    informacion_solicitada="Se pidió el informe", fecha_corte=date(2026, 6, 15))

    def test_ponderado_y_descuento_por_externalidades(self):
        self.assertEqual(calculos.calcular(ficticio(**self.EN_REGLA))["cal_ejecucion"], 100)
        self.assertEqual(calculos.calcular(ficticio(control_externalidades=2, **self.EN_REGLA))["cal_ejecucion"], 75)

    def test_horizonte_vencido_da_cero(self):
        datos = {**self.EN_REGLA, "horizonte": date(2026, 6, 14)}
        self.assertEqual(calculos.calcular(ficticio(**datos))["cal_ejecucion"], 0)

    def test_sin_informacion_y_con_externalidades_es_revisar_en_el_departamento(self):
        datos = {**self.EN_REGLA, "informacion_solicitada": "", "control_externalidades": 1}
        depto = calculos.calcular(ficticio(**datos))
        self.assertEqual((depto["cal_ejecucion"], depto["ejecucion_revisar"]), (None, True))
        desc = calculos.calcular(ficticio(codigo=DESCENTRALIZADA, **datos))
        self.assertEqual((desc["cal_ejecucion"], desc["ejecucion_revisar"]), (None, False))

    def test_descentralizadas_miran_la_informacion_a_tiempo_digitada(self):
        datos = {**self.EN_REGLA, "informacion_solicitada": ""}
        self.assertIsNone(calculos.calcular(ficticio(codigo=DESCENTRALIZADA, **datos))["cal_ejecucion"])
        con_dato = calculos.calcular(ficticio(codigo=DESCENTRALIZADA, cal_informacion_a_tiempo=d(80), **datos))
        self.assertEqual(con_dato["cal_ejecucion"], 100)
        self.assertNotIn("cal_informacion_a_tiempo", con_dato)          # en descentralizadas no se pisa

    def test_sin_acta_de_inicio(self):
        def ejecucion(**fechas):
            return calculos.calcular(ficticio(E.CONTRATADO_SIN_ACTA, **fechas))["cal_ejecucion"]
        corte = date(2026, 6, 15)
        self.assertEqual(ejecucion(fecha_corte=corte, fecha_suscripcion_primer_contrato=date(2026, 5, 16)), 100)
        self.assertEqual(ejecucion(fecha_corte=corte, fecha_suscripcion_primer_contrato=date(2026, 5, 15)), 0)
        self.assertEqual(ejecucion(fecha_corte=corte, fecha_suscripcion_primer_contrato=date(2026, 6, 16)), 0)
        self.assertIsNone(ejecucion(fecha_corte=corte))                  # correccion 2
        self.assertIsNone(ejecucion())

    def test_otro_estado_no_tiene_calificacion(self):
        self.assertIsNone(calculos.calcular(ficticio(E.TERMINADO, **self.EN_REGLA))["cal_ejecucion"])


class Dias(TestCase):
    def test_sin_contratar_con_aprobacion_y_apertura(self):
        p = ficticio(E.SIN_CONTRATAR, fecha_corte=date(2026, 5, 15), fecha_aprobacion=date(2024, 11, 19),
                     fecha_apertura_primer_proceso=date(2026, 3, 5))
        valores = calculos.calcular(p)
        self.assertEqual((valores["dias_aprobacion_a_apertura"], valores["dias_apertura_a_firma"]), (542, 71))

    def test_sin_apertura_solo_cuenta_desde_la_aprobacion(self):
        p = ficticio(E.SIN_CONTRATAR, fecha_corte=date(2026, 5, 15), fecha_aprobacion=date(2026, 4, 9))
        valores = calculos.calcular(p)
        self.assertEqual((valores["dias_aprobacion_a_apertura"], valores["dias_apertura_a_firma"]), (36, None))

    def test_sin_acta_cuenta_desde_la_suscripcion_del_principal(self):
        p = ficticio(E.CONTRATADO_SIN_ACTA, fecha_corte=date(2026, 5, 15),
                     fecha_suscripcion_principal=date(2025, 6, 19))
        self.assertEqual(calculos.calcular(p)["dias_suscripcion_a_acta"], 330)

    def test_sin_fecha_de_corte_o_en_otro_estado_quedan_vacios(self):
        sin_corte = calculos.calcular(ficticio(E.SIN_CONTRATAR, fecha_aprobacion=date(2026, 1, 1)))
        self.assertIsNone(sin_corte["dias_aprobacion_a_apertura"])
        otro = calculos.calcular(ficticio(E.TERMINADO, fecha_corte=date(2026, 5, 15), fecha_aprobacion=date(2026, 1, 1)))
        self.assertIsNone(otro["dias_aprobacion_a_apertura"])

    def test_sin_estado_no_se_calcula_nada(self):
        valores = calculos.calcular(ficticio(None, fecha_recibo_informacion=date(2026, 5, 10), **CalificacionDeEjecucion.EN_REGLA))
        self.assertTrue(all(valores[c] is None for c in calculos.CALCULADOS if c != "ejecucion_revisar"))
        self.assertIsNone(valores["cal_informacion_a_tiempo"])


class AlGuardar(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de("Regalías", "regalias")

    def test_guardar_recalcula_y_el_calculado_queda_en_el_historial(self):
        obj = proyecto("2025000020001", DEPARTAMENTO, estado=estado(E.SIN_CONTRATAR),
                       fecha_aprobacion=date(2026, 1, 1))
        obj.fecha_corte = date(2026, 1, 31)
        servicios.guardar_proyecto(obj, usuario=self.usuario, origen=CambioProyectoRegalias.Origen.EDICION)
        obj.refresh_from_db()
        self.assertEqual(obj.dias_aprobacion_a_apertura, 30)
        self.assertTrue(obj.cambios.filter(campo="Días desde la aprobación hasta apertura del primer proceso",
                                           valor_nuevo="30").exists())

    def test_las_acciones_de_la_lista(self):
        self.client.force_login(self.usuario)
        uno = proyecto("2025000020001", DEPARTAMENTO, estado=estado(E.SIN_CONTRATAR), fecha_aprobacion=date(2026, 1, 1))
        otro = proyecto("2025000020002", DEPARTAMENTO, estado=estado(E.SIN_CONTRATAR), fecha_aprobacion=date(2026, 2, 1))
        url = reverse("admin:regalias_proyectodepartamento_changelist")
        seleccion = {"_selected_action": [uno.pk, otro.pk]}
        pregunta = self.client.post(url, {"action": "asignar_fecha_corte", **seleccion})
        self.assertEqual(pregunta.status_code, 200)
        self.assertTemplateUsed(pregunta, "regalias/asignar_fecha_corte.html")
        aplicar = self.client.post(url, {"action": "asignar_fecha_corte", "aplicar": "1", "fecha_corte": "2026-03-03",
                                         **seleccion})
        self.assertEqual(aplicar.status_code, 302)
        uno.refresh_from_db()
        otro.refresh_from_db()
        self.assertEqual((uno.fecha_corte, uno.dias_aprobacion_a_apertura, otro.dias_aprobacion_a_apertura),
                         (date(2026, 3, 3), 61, 30))
        self.assertTrue(uno.cambios.filter(origen=CambioProyectoRegalias.Origen.ACCION_MASIVA).exists())
        # Recalcular sin cambios no deja historial nuevo
        antes = CambioProyectoRegalias.objects.count()
        self.assertEqual(self.client.post(url, {"action": "recalcular", **seleccion}).status_code, 302)
        self.assertEqual(CambioProyectoRegalias.objects.count(), antes)


MATRIZ_JUNIO = Path(os.environ.get(
    "REGALIAS_MATRIZ_JUNIO",
    Path(__file__).resolve().parents[5] / "Estudio" / "python" / "Consolidacion Regalias" / "Contexto"
    / "MatrizSeguimientoEvaluacion_20260609_1833.xlsx"))

COLUMNAS = {
    "DIAS DESDE LA APROBACIÓN HASTA APERTURA DEL PRIMER PROCESO": "dias_aprobacion_a_apertura",
    "DIAS DESDE LA APERTURA HASTA LA FIRMA DEL PRIMER CONTRATO": "dias_apertura_a_firma",
    "DIAS DESDE LA FECHA DE SUSCRIPCIÓN HASTA LA FECHA DEL ACTA DE INICIO": "dias_suscripcion_a_acta",
    "DESEMPEÑO EN EL CRONOGRAMA": "desempeno_cronograma",
    "DESEMPEÑO EN EL COSTO": "desempeno_costo",
    "COLUMNA APOYO": "columna_apoyo",
    "BRECHA FISICO - FINANCIERA": "brecha_fisico_financiera",
    "COLUMNA APOYO 2": "columna_apoyo_2",
    "CALIFICACIÓN EJECUCIÓN DEL PROYECTO": "cal_ejecucion",
}


@unittest.skipUnless(MATRIZ_JUNIO.exists(), f"no esta {MATRIZ_JUNIO.name}")
class ParidadConLaMatrizDeJunio(TestCase):
    """Los calculados del sistema contra los valores que Excel dejo en la matriz de junio."""

    @classmethod
    def setUpTestData(cls):
        cls.carga = CargaRegalias.objects.create(tipo=CargaRegalias.Tipo.MATRIZ)
        importar_matriz(MATRIZ_JUNIO, cls.carga)
        cls.excel = {}
        libro = load_workbook(MATRIZ_JUNIO, data_only=True)
        for hoja in libro.worksheets[:2]:                      # departamento y descentralizadas
            tabla = next(iter(hoja.tables.values()))
            celdas = hoja[tabla.ref]
            encabezado = [str(c.value).strip() for c in celdas[0]]
            for fila in celdas[1:]:
                datos = dict(zip(encabezado, [c.value for c in fila]))
                cls.excel[str(datos["BPIN"]).strip()] = datos

    def test_coinciden_salvo_las_correcciones_acordadas(self):
        diferencias, corregidas = [], []
        proyectos = ProyectoRegalias.objects.filter(bpin__in=self.excel).select_related("estado", "clasificacion")
        self.assertEqual(proyectos.count(), 74)                 # 58 del departamento y 16 descentralizadas
        for p in proyectos:
            fila = self.excel[p.bpin]
            columnas = dict(COLUMNAS)
            if p.clasificacion.codigo == DEPARTAMENTO:
                columnas["CALIFICACIÓN INFORMACIÓN A TIEMPO"] = "cal_informacion_a_tiempo"
            for columna, campo in columnas.items():
                excel = fila.get(columna)
                if excel == "Revisar":
                    excel, revisar = None, True
                else:
                    excel, revisar = (None if excel in ("", None) else Decimal(str(excel))), False
                sistema = getattr(p, campo)
                if campo == "cal_ejecucion" and revisar != p.ejecucion_revisar:
                    diferencias.append((p.bpin, "Revisar", revisar, p.ejecucion_revisar))
                if excel is None and sistema is None:
                    continue
                if excel is not None and sistema is not None and abs(Decimal(sistema) - excel) <= Decimal("0.001"):
                    continue
                # Correccion 3: la columna de Excel salia siempre vacia
                if campo == "dias_apertura_a_firma" and excel is None and p.estado.codigo == E.SIN_CONTRATAR:
                    corregidas.append((p.bpin, campo))
                    continue
                # Correccion 4: fuera de ejecucion la brecha ya no se calcula
                if campo == "brecha_fisico_financiera" and sistema is None and p.estado.codigo != E.CONTRATADO_EN_EJECUCION:
                    corregidas.append((p.bpin, campo))
                    continue
                diferencias.append((p.bpin, campo, excel, sistema))
        self.assertEqual(diferencias, [])
        # Las correcciones se notan donde se esperaba (3 dias con apertura y 5 brechas de terminados)
        self.assertEqual(sorted({campo for _, campo in corregidas}), ["brecha_fisico_financiera", "dias_apertura_a_firma"])
