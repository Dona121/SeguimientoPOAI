"""Lectura de los reportes de GESPROY y de la matriz de seguimiento.

Los reportes de GESPROY (CG-proy, CG-cttos, CG-carga) traen el titulo en la fila 1 y los
encabezados en la fila 2, con tabulaciones y espacios alrededor. Ademas declaran mal su
tamano (la hoja dice A1:A1), asi que en modo read_only openpyxl no ve ninguna fila si no se
le pide reset_dimensions(). siifweb.cargas.leer_filas no lo hace; por eso la lectura de los
reportes vive aqui. La matriz si se lee con leer_filas, por el nombre de cada tabla.
"""
import unicodedata
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import load_workbook

from siifweb import cargas

# El titulo de la fila 1 de cada reporte, normalizado
TITULOS = {
    "proyectos": "PROYECTOS",
    "contratos": "CONTRATOS",
    "cargue": "CARGUE INFORMACION EN GESPROY-SGR",
}

COLUMNAS = {
    "proyectos": ("BPIN", "NOMBRE PROYECTO", "SECTOR", "ESTADO PROYECTO", "VALOR PAGOS"),
    "contratos": ("BPIN", "CONTRATO NUMERO", "FECHA SUSCRIPCION", "TIPO CONTRATO", "ESTADO CONTRATO",
                  "VALOR TOTAL FUENTES SGR", "FECHA ACT ADTIVO APERT", "FECHA INICIAL", "ULTIMA FECHA PAGO"),
    "cargue": ("BPIN", "AVANCE FISICO", "AVANCE FINANCIERO", "FECHA APROBACIÓN PROYECTO"),
}

TABLAS_MATRIZ = {
    "departamento": "MatrizSeguimientoEvaluacion",
    "descentralizada": "OtrosEjecutoresDescentralizadas",
    "municipio": "OtrosEjecutoresMunicipios",
}


def normalizar(valor):
    """Mayusculas, sin tildes y con espacios simples: para comparar nombres de catalogo."""
    sin_tildes = unicodedata.normalize("NFKD", cargas.texto(valor))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.upper().split())


def _bytes(origen):
    """El contenido del archivo, para poder abrirlo varias veces (ruta, archivo o FieldFile)."""
    if isinstance(origen, (str, bytes)) or hasattr(origen, "__fspath__"):
        with open(origen, "rb") as fh:
            return fh.read()
    if hasattr(origen, "open"):
        origen.open("rb")
    origen.seek(0)
    contenido = origen.read()
    origen.seek(0)
    return contenido


def _faltantes(encabezado, columnas):
    return [c for c in columnas if c not in encabezado]


def leer_reporte(origen, tipo):
    """Las filas de un reporte de GESPROY como diccionarios. Valida el titulo y las columnas."""
    libro = load_workbook(BytesIO(_bytes(origen)), read_only=True, data_only=True)
    try:
        hoja = libro.worksheets[0]
        hoja.reset_dimensions()
        filas = list(hoja.iter_rows(values_only=True))
    finally:
        libro.close()
    if not filas:
        raise ValueError("El archivo no tiene filas.")

    titulo = normalizar(next((c for c in filas[0] if c not in (None, "")), ""))
    if titulo != TITULOS[tipo]:
        parece = next((t for t, esperado in TITULOS.items() if esperado == titulo), None)
        detalle = f" Parece un reporte de tipo {parece}." if parece else ""
        raise ValueError(f"El título de la fila 1 es '{titulo or 'vacío'}' y para este tipo se espera "
                         f"'{TITULOS[tipo]}'.{detalle}")

    inicio = next((i for i, fila in enumerate(filas[:10]) if any(cargas.texto(c) == "BPIN" for c in fila)), None)
    if inicio is None:
        raise ValueError("No se encontró la fila de encabezados (la que tiene la columna BPIN).")
    encabezado = [cargas.texto(c) for c in filas[inicio]]
    faltan = _faltantes(encabezado, COLUMNAS[tipo])
    if faltan:
        raise ValueError("Al reporte le faltan columnas: " + ", ".join(faltan)
                         + ". Revise que el encabezado esté escrito igual, sin cambiar tildes ni mayúsculas.")
    return [dict(zip(encabezado, fila)) for fila in filas[inicio + 1:]
            if any(c not in (None, "") for c in fila)]


def leer_matriz(origen):
    """{clasificacion: filas} de las tres tablas de la matriz. Una tabla que falta queda en None.

    Sin la tabla del departamento la importacion no sigue; sin descentralizadas o municipios
    se importa lo que hay y se avisa.
    """
    contenido = _bytes(origen)
    tablas = {}
    for clasificacion, tabla in TABLAS_MATRIZ.items():
        try:
            tablas[clasificacion] = cargas.leer_filas(BytesIO(contenido), tabla=tabla)
        except ValueError:
            tablas[clasificacion] = None
    if tablas["departamento"] is None:
        raise ValueError(f"El archivo no contiene la tabla '{TABLAS_MATRIZ['departamento']}'.")
    return tablas


# ---------- valores ----------

def texto(valor):
    return cargas.texto(valor)


def fecha(valor):
    return cargas.fecha(valor)


def numero(valor):
    """Decimal o None si esta vacio. Lo que no se puede leer como numero lanza ValueError."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool):
        raise ValueError(f"'{valor}' no es un número")
    try:
        return cargas.decimal(valor)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"'{valor}' no es un número") from error


def entero(valor):
    valor = numero(valor)
    if valor is None:
        return None
    if valor != valor.to_integral_value():
        raise ValueError(f"'{valor}' no es un número entero")
    return int(valor)


def cabe(valor, campo):
    """El decimal cabe en el campo (max_digits y decimal_places del modelo)."""
    if valor is None:
        return True
    limite = Decimal(10) ** (campo.max_digits - campo.decimal_places)
    return abs(valor) < limite
