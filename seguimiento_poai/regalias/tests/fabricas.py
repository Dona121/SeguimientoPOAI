"""Piezas para armar los escenarios de las pruebas de regalias.

Los libros de GESPROY y la matriz se arman en memoria con la forma de los reales (titulo en
la fila 1, encabezados con tabulaciones, tablas de Excel con nombre), para fabricar los casos
raros sin depender de los archivos de octubre.
"""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Model
from django.forms.models import model_to_dict
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table

from siifweb.models import DependenciaResponsable, Municipio, SectorMGA

from regalias import calculos
from regalias.models import ClasificacionRegalias, EstadoProyectoRegalias, ProyectoRegalias

DEPARTAMENTO = ClasificacionRegalias.DEPARTAMENTO
DESCENTRALIZADA = ClasificacionRegalias.DESCENTRALIZADA
MUNICIPIO = ClasificacionRegalias.MUNICIPIO


def usuario_de(rol, nombre):
    """Un usuario del equipo: staff para entrar al admin, sin poderes propios."""
    persona = get_user_model().objects.create_user(nombre, f"{nombre}@sucre.gov.co", "clave", is_staff=True)
    persona.groups.add(Group.objects.get(name=rol))
    return persona


def clasificacion(codigo):
    return ClasificacionRegalias.objects.get(codigo=codigo)


def estado(codigo):
    return EstadoProyectoRegalias.objects.get(codigo=codigo)


def catalogos():
    """Un sector, una dependencia y dos municipios de SIIFWEB (algunos ya los crean sus migraciones)."""
    return {
        "sector": SectorMGA.objects.get_or_create(codigo="24", defaults={"descripcion": "Transporte"})[0],
        "dependencia": DependenciaResponsable.objects.get_or_create(nombre="Secretaría de Infraestructura")[0],
        "sincelejo": Municipio.objects.get_or_create(nombre="Sincelejo")[0],
        "corozal": Municipio.objects.get_or_create(nombre="Corozal")[0],
    }


def proyecto(bpin="2025000020001", codigo=DEPARTAMENTO, **campos):
    """Un proyecto guardado con sus calculados al dia, como los deja cualquier carga o edicion."""
    campos.setdefault("nombre", f"Proyecto {bpin}")
    campos.setdefault("estado", estado(EstadoProyectoRegalias.SIN_CONTRATAR))
    obj = ProyectoRegalias(bpin=bpin, clasificacion=clasificacion(codigo), **campos)
    calculos.aplicar(obj)
    obj.save()
    return obj


# Los nombres visibles de los calculados: las pruebas del historial de datos los dejan aparte
NOMBRES_CALCULADOS = {str(ProyectoRegalias._meta.get_field(c).verbose_name)
                      for c in (*calculos.CALCULADOS, "cal_informacion_a_tiempo")}


TITULOS = {"proyectos": "PROYECTOS", "contratos": "CONTRATOS", "cargue": "CARGUE INFORMACIÓN EN GESPROY-SGR"}

COLUMNAS_REPORTE = {
    "proyectos": ["BPIN", "NOMBRE PROYECTO", "SECTOR", "ESTADO PROYECTO", "VALOR PAGOS"],
    "contratos": ["BPIN", "CONTRATO NUMERO", "FECHA SUSCRIPCION", "TIPO CONTRATO", "ESTADO CONTRATO",
                  "VALOR TOTAL FUENTES SGR", "FECHA ACT ADTIVO APERT", "FECHA INICIAL", "ULTIMA FECHA PAGO",
                  "CONTRATO OBJETO"],
    "cargue": ["BPIN", "AVANCE FISICO", "AVANCE FINANCIERO", "FECHA APROBACIÓN PROYECTO"],
}


def reporte(tipo, filas, titulo=None):
    """Un reporte de GESPROY en memoria. `filas` son diccionarios por nombre de columna."""
    libro = Workbook()
    hoja = libro.active
    hoja.append([titulo or TITULOS[tipo]])
    columnas = COLUMNAS_REPORTE[tipo]
    hoja.append([f"\t{c}" for c in columnas])   # como los reales: encabezados con tabulacion
    for fila in filas:
        hoja.append([fila.get(c) for c in columnas])
    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida


def matriz(tablas):
    """La matriz en memoria: {nombre_de_tabla: (columnas, filas)}, una hoja por tabla."""
    libro = Workbook()
    libro.remove(libro.active)
    for nombre, (columnas, filas) in tablas.items():
        hoja = libro.create_sheet(nombre[:31])
        hoja.append(columnas)
        for fila in filas:
            hoja.append([fila.get(c) for c in columnas])
        ref = f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}"
        hoja.add_table(Table(displayName=nombre, ref=ref))
    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida


def datos_del_formulario(obj, campos):
    """Lo que enviaria el formulario del admin para `obj` tal como esta guardado."""
    datos = {}
    for nombre, valor in model_to_dict(obj, fields=campos).items():
        if valor is None:
            datos[nombre] = ""
        elif isinstance(valor, list):
            datos[nombre] = [v.pk if isinstance(v, Model) else v for v in valor]
        elif isinstance(valor, date):
            datos[nombre] = valor.isoformat()
        elif isinstance(valor, Decimal):
            datos[nombre] = f"{valor.normalize():f}"
        else:
            datos[nombre] = valor
    return datos
