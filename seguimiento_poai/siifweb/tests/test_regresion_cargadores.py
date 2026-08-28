# -*- coding: utf-8 -*-
"""Los cargadores de SIIFWEB, que comparten `leer_filas` con el de SECOP.

El cambio de esta sesion toco esa funcion, que usan los seis cargadores anteriores.
Aqui se comprueba de punta a punta que un reporte de los de siempre -una hoja plana,
SIN tabla de Excel- se sigue cargando igual.
"""
import hashlib
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.test import TestCase
from openpyxl import Workbook

from siifweb import cargas
from siifweb.models import CargaReporte, Cdp, CdpImputacion, Proyecto

COLUMNAS_CDP = ["NRO_CDP", "FECHA_DISP", "OBJETO_CERT", "ID_CENTROCOSTO", "SOLICITANTE",
                "IDENTIFICACION_PRESUPUESTAL", "NOMBRE_RUBRO", "FONDO", "NOMBRE_FONDO",
                "PROYECTO", "VALOR_CERTIFICADO", "VALOR_DISPONIBILIDAD_DEF", "SALDO_CERTF"]


def fila_cdp(**cambios):
    fila = {
        "NRO_CDP": 1,
        "FECHA_DISP": "15/01/2025",
        "OBJETO_CERT": "COMPRA DE INSUMOS",
        "ID_CENTROCOSTO": 16,
        "SOLICITANTE": "Secretaria De Infraestructura",
        "IDENTIFICACION_PRESUPUESTAL": "2.3.2.01.01.001",
        "NOMBRE_RUBRO": "Servicios",
        "FONDO": 1,
        "NOMBRE_FONDO": "Recursos propios",
        "PROYECTO": 202500000000001,
        "VALOR_CERTIFICADO": "1000000",
        "VALOR_DISPONIBILIDAD_DEF": "1000000",
        "SALDO_CERTF": "0",
    }
    fila.update(cambios)
    return fila


def libro_cdp(filas):
    """Como los emite SIIFWEB: una hoja plana, sin tabla de Excel."""
    wb = Workbook()
    hoja = wb.active
    hoja.title = "Hoja1"
    hoja.append(COLUMNAS_CDP)
    for f in filas:
        hoja.append([f[c] for c in COLUMNAS_CDP])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def cargar(filas, vigencia=2025):
    datos = libro_cdp(filas)
    registro = CargaReporte(tipo_reporte="cdp", vigencia=vigencia,
                            hash=hashlib.sha256(datos + str(len(filas)).encode()).hexdigest())
    registro.archivo.save("cdp.xlsx", ContentFile(datos), save=True)
    cargas.procesar(registro)
    registro.refresh_from_db()
    return registro


class CargadorDeCdp(TestCase):
    def test_un_reporte_sin_tabla_de_excel_se_carga_igual(self):
        carga = cargar([fila_cdp(), fila_cdp(**{"NRO_CDP": 2, "VALOR_CERTIFICADO": "2000000",
                                                "VALOR_DISPONIBILIDAD_DEF": "2000000"})])
        self.assertEqual(carga.estado, CargaReporte.Estado.PROCESADO, carga.mensaje)
        self.assertEqual(Cdp.objects.count(), 2)
        self.assertEqual(CdpImputacion.objects.count(), 2)
        self.assertIn("2 CDPs", carga.mensaje)

    def test_normaliza_como_siempre(self):
        cargar([fila_cdp()])
        cdp = Cdp.objects.get(nro_cdp="1")
        self.assertEqual(cdp.fecha_disp, date(2025, 1, 15))
        self.assertEqual(cdp.vigencia, 2025)
        imputacion = CdpImputacion.objects.get()
        self.assertEqual(imputacion.valor_certificado, Decimal("1000000"))
        self.assertEqual(imputacion.proyecto.bpin, "202500000000001")   # sin el .0

    def test_el_bpin_nuevo_entra_como_detectado_en_siifweb(self):
        cargar([fila_cdp()])
        proyecto = Proyecto.objects.get(bpin="202500000000001")
        self.assertEqual(proyecto.origen, Proyecto.Origen.SIIFWEB)

    def test_engancha_el_proyecto_que_creo_el_equipo(self):
        Proyecto.objects.create(bpin="202500000000001", nombre="Nombre del equipo",
                                origen=Proyecto.Origen.MANUAL)
        carga = cargar([fila_cdp()])
        self.assertEqual(Proyecto.objects.filter(bpin="202500000000001").count(), 1)
        self.assertEqual(Proyecto.objects.get(bpin="202500000000001").nombre, "Nombre del equipo")
        self.assertIn("proyectos del equipo con ejecucion", carga.mensaje)

    def test_proyecto_cero_es_funcionamiento(self):
        cargar([fila_cdp(**{"PROYECTO": 0})])
        self.assertIsNone(CdpImputacion.objects.get().proyecto)

    def test_recargar_reemplaza_las_imputaciones_y_no_las_acumula(self):
        cargar([fila_cdp()])
        segunda = cargar([fila_cdp(), fila_cdp(**{"IDENTIFICACION_PRESUPUESTAL": "2.3.2.02"})])
        self.assertEqual(Cdp.objects.count(), 1)              # la cabecera se actualiza
        self.assertEqual(CdpImputacion.objects.count(), 2)    # las lineas se reemplazan
        self.assertIn("reemplazo 1 imputaciones", segunda.mensaje)

    def test_el_reporte_de_secop_no_se_cuela_por_el_cargador_de_cdp(self):
        """Cada tipo lee lo suyo: un libro de SECOP en el cargador de CDP falla claro."""
        from .fabricas import fila, libro
        datos = libro([fila()]).getvalue()
        registro = CargaReporte(tipo_reporte="cdp", vigencia=2025,
                                hash=hashlib.sha256(datos).hexdigest())
        registro.archivo.save("mezclado.xlsx", ContentFile(datos), save=True)
        cargas.procesar(registro)
        registro.refresh_from_db()
        self.assertEqual(registro.estado, CargaReporte.Estado.ERROR)
        self.assertEqual(Cdp.objects.count(), 0)


COLUMNAS_OBLI = ["NRO_OBLIGACION", "FECHA_OBLI", "OBJETO_OBLIG", "NIT", "BENEFICIARIO",
                 "TIPO_ORDEN_GASTO", "NRO_ORDEN_GASTO", "PREFIJO_ORDEN", "ORDEN_PAGO",
                 "CCOSTO", "NOMBRE_CCOSTO", "NRO_RP", "IDENTIFICACION_PRESUPUESTAL",
                 "NOMBRE_RUBRO", "FONDO", "NOMBRE_FONDO", "PROYECTO", "VALOR_OBLI_DEF",
                 "SALDO_OBLI", "PAGOS"]


class CargadorDeObligaciones(TestCase):
    """La columna OBJETO_OBLIG: el consolidado paso de 25 a 27 columnas."""

    def setUp(self):
        from .fabricas import cadena, proyecto as crear_proyecto
        self.proy = crear_proyecto()
        _, self.rp, _ = cadena(self.proy, nro="7")

    def cargar(self, objeto, nro="99", vigencia=2025, nit="890000123",
               beneficiario="CONSTRUCTORA DEL CARIBE SAS"):
        valores = [nro, "05/03/2025", objeto, nit, beneficiario,
                   "ORDEN PAGO", "12", "2025", "500",
                   "16", "Infraestructura", self.rp.nro_rp, "2.3.2.01.01", "Rubro de prueba",
                   "1", "Recursos propios", self.proy.bpin, "3000000", "0", "3000000"]
        wb = Workbook()
        hoja = wb.active
        hoja.append(COLUMNAS_OBLI)
        hoja.append(valores)
        buffer = BytesIO()
        wb.save(buffer)
        datos = buffer.getvalue()

        registro = CargaReporte(tipo_reporte="obligaciones", vigencia=vigencia,
                                hash=hashlib.sha256(datos).hexdigest())
        registro.archivo.save("obligaciones.xlsx", ContentFile(datos), save=True)
        cargas.procesar(registro)
        registro.refresh_from_db()
        return registro

    def test_carga_el_objeto_de_la_obligacion(self):
        from siifweb.models import Obligacion
        registro = self.cargar("MANTENIMIENTO DE LA VIA SINCELEJO - TOLUVIEJO")
        self.assertEqual(registro.estado, CargaReporte.Estado.PROCESADO, registro.mensaje)
        obligacion = Obligacion.objects.get(vigencia=2025, nro_obligacion="99")
        self.assertEqual(obligacion.objeto_oblig,
                         "MANTENIMIENTO DE LA VIA SINCELEJO - TOLUVIEJO")
        self.assertEqual(obligacion.tipo_orden_gasto.nombre, "ORDEN PAGO")

    def test_recargar_actualiza_el_objeto(self):
        """La cabecera se actualiza en sitio: el objeto tiene que ir en el upsert.

        Es el caso de las obligaciones cargadas antes de que existiera la columna:
        al recargar el mismo documento, el objeto entra sin borrar nada.
        """
        from siifweb.models import Obligacion
        self.cargar("PRIMER OBJETO")
        self.assertEqual(Obligacion.objects.get(nro_obligacion="99").objeto_oblig,
                         "PRIMER OBJETO")

        registro = self.cargar("ACTA PARCIAL 3 - OBJETO CORREGIDO")
        self.assertEqual(registro.estado, CargaReporte.Estado.PROCESADO, registro.mensaje)
        self.assertEqual(Obligacion.objects.filter(nro_obligacion="99").count(), 1)
        self.assertEqual(Obligacion.objects.get(nro_obligacion="99").objeto_oblig,
                         "ACTA PARCIAL 3 - OBJETO CORREGIDO")

    def test_una_obligacion_sin_objeto_no_revienta(self):
        from siifweb.models import Obligacion
        registro = self.cargar(None)
        self.assertEqual(registro.estado, CargaReporte.Estado.PROCESADO, registro.mensaje)
        self.assertEqual(Obligacion.objects.get(nro_obligacion="99").objeto_oblig, "")

    def test_carga_el_beneficiario_y_su_nit(self):
        from siifweb.models import Obligacion, Tercero
        self.cargar("PAGO ACTA 1")
        obligacion = Obligacion.objects.get(nro_obligacion="99")
        self.assertEqual(obligacion.beneficiario.codigo, "890000123")
        self.assertEqual(obligacion.beneficiario.nombre, "CONSTRUCTORA DEL CARIBE SAS")
        self.assertTrue(Tercero.objects.filter(codigo="890000123").exists())

    def test_el_beneficiario_completa_el_nombre_de_un_tercero_que_estaba_sin_razon_social(self):
        """El consolidado de obligaciones enriquece el catalogo: trae NIT y razon social."""
        from .fabricas import tercero
        from siifweb.models import Obligacion
        vacio = tercero(codigo="890000123", nombre="")
        self.cargar("PAGO ACTA 1")
        vacio.refresh_from_db()
        self.assertEqual(vacio.nombre, "CONSTRUCTORA DEL CARIBE SAS")
        self.assertEqual(Obligacion.objects.get(nro_obligacion="99").beneficiario, vacio)

    def test_una_obligacion_sin_nit_queda_sin_beneficiario(self):
        from siifweb.models import Obligacion
        self.cargar("PAGO ACTA 1", nit=None, beneficiario=None)
        self.assertIsNone(Obligacion.objects.get(nro_obligacion="99").beneficiario)
