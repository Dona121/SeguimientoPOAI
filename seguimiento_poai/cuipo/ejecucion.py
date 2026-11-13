"""Importador del reporte de ejecucion de gastos de SIIFWEB (estado_ppto_gasto_gobatl_fyccw).

El reporte es una hoja plana con el arbol de rubros: las filas sin RECURSO son subtotales
y las que lo traen son el detalle (rubro x recurso x centro de costo x proyecto). Se
guarda el detalle con todas las columnas menos DISPONIBLE, y se comprueba que cada
subtotal sea la suma de su detalle: si no cuadra, el archivo se leyo mal o llego cortado,
y la carga no deja nada.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from siifweb import cargas
from siifweb.cargas import decimal, texto

from .models import CorteEjecucionGastos, FilaEjecucionGastos

# Columna del reporte -> campo del modelo
VALORES = {
    "APROPIACION_INICIAL": "apropiacion_inicial",
    "ADICION": "adicion",
    "DISMINUCION": "disminucion",
    "CREDITO": "credito",
    "CONTRACREDITO": "contracredito",
    "APLAZAMIENTOS": "aplazamientos",
    "DESAPLAZAMIENTOS": "desaplazamientos",
    "APROPIACION_DEFINITIVA": "apropiacion_definitiva",
    "SOLICITUD_TRAMITE": "solicitud_tramite",
    "CDP": "cdp",
    "RP": "rp",
    "OBLIGACION": "obligacion",
    "PAGO": "pago",
}
COLUMNAS = ["RUBRO_ID", "RUBRO", "NOMBRE_RUBRO", "RECURSO", "NOMBRE_RECURSO", "CENTROCOSTO",
            "NOMBRE_CENTROCOSTO", "PROYECTO", *VALORES]


def _arboles(filas):
    """RUBRO_ID de la raiz del arbol de cada fila y el de la raiz de la vigencia.

    Las raices son los subtotales sin punto en el codigo ("2"). SIIFWEB numera los rubros
    de cada vigencia en un bloque, asi que una fila pertenece a la raiz de mayor id que no
    supere el suyo. El arbol de la vigencia es el de la raiz mas reciente.
    """
    raices = sorted(f["id"] for f in filas if not f["recurso"] and "." not in f["rubro"])
    if not raices:
        raise ValueError("El reporte no trae la fila raíz del árbol de rubros (rubro 2).")
    arbol = {}
    for f in filas:
        previas = [r for r in raices if r <= f["id"]]
        if not previas:
            raise ValueError(f"La fila del rubro {f['rubro']} (RUBRO_ID {f['id']}) no cuelga de ninguna raíz.")
        arbol[f["id"]] = previas[-1]
    return arbol, raices[-1]


def _validar_subtotales(subtotales, detalle, arbol):
    """Cada subtotal es la suma del detalle de su arbol que empieza por su codigo."""
    descuadres = []
    for s in subtotales:
        suma = defaultdict(Decimal)
        for f in detalle:
            if arbol[f["id"]] == arbol[s["id"]] and (f["rubro"] == s["rubro"]
                                                     or f["rubro"].startswith(s["rubro"] + ".")):
                for campo in VALORES.values():
                    suma[campo] += f["valores"][campo]
        for columna, campo in VALORES.items():
            if suma[campo] != s["valores"][campo]:
                descuadres.append(f"{s['rubro']} {columna}: subtotal {s['valores'][campo]:,.2f}, "
                                  f"detalle {suma[campo]:,.2f}")
    if descuadres:
        raise ValueError(f"{len(descuadres)} subtotales no cuadran con su detalle: " + "; ".join(descuadres[:5]))


def leer(contenido):
    """Filas del reporte normalizadas: (subtotales, detalle)."""
    subtotales, detalle = [], []
    for f in cargas.leer_filas(contenido, columnas=COLUMNAS):
        fila = {
            "id": int(decimal(f["RUBRO_ID"])),
            "rubro": texto(f["RUBRO"]),
            "nombre_rubro": texto(f["NOMBRE_RUBRO"]),
            "recurso": texto(f["RECURSO"]),
            "nombre_recurso": texto(f["NOMBRE_RECURSO"]),
            "centro_costo": texto(f["CENTROCOSTO"]),
            "nombre_centro_costo": texto(f["NOMBRE_CENTROCOSTO"]),
            "proyecto": texto(f["PROYECTO"]) or "0",
            "valores": {campo: decimal(f[columna]) for columna, campo in VALORES.items()},
        }
        (detalle if fila["recurso"] else subtotales).append(fila)
    return subtotales, detalle


@transaction.atomic
def importar(corte):
    """Reemplaza las filas del corte con las del archivo. Devuelve el mensaje."""
    subtotales, detalle = leer(cargas.stream(corte.archivo))
    if not detalle:
        raise ValueError("El reporte no trae filas de detalle (con recurso).")
    arbol, de_la_vigencia = _arboles(subtotales + detalle)
    _validar_subtotales(subtotales, detalle, arbol)

    vistas = set()
    for f in detalle:
        llave = (f["id"], f["recurso"], f["centro_costo"], f["proyecto"])
        if llave in vistas:
            raise ValueError(f"Fila repetida: RUBRO_ID {f['id']}, rubro {f['rubro']}, recurso {f['recurso']}, "
                             f"centro de costo {f['centro_costo']}, proyecto {f['proyecto']}.")
        vistas.add(llave)

    corte.filas_ejecucion.all().delete()
    FilaEjecucionGastos.objects.bulk_create([
        FilaEjecucionGastos(
            corte=corte, rubro_id_siifweb=f["id"], de_otra_vigencia=arbol[f["id"]] != de_la_vigencia,
            rubro=f["rubro"], nombre_rubro=f["nombre_rubro"][:255], recurso=f["recurso"],
            nombre_recurso=f["nombre_recurso"][:255], centro_costo=f["centro_costo"],
            nombre_centro_costo=f["nombre_centro_costo"][:255], proyecto=f["proyecto"], **f["valores"])
        for f in detalle], batch_size=1000)

    otra = [f for f in detalle if arbol[f["id"]] != de_la_vigencia]
    total = lambda campo, filas=detalle: sum((f["valores"][campo] for f in filas), Decimal(0))
    partes = [f"{len(detalle)} filas de detalle",
              f"RP {total('rp'):,.2f}", f"obligación {total('obligacion'):,.2f}", f"pago {total('pago'):,.2f}"]
    if otra:
        partes.append(f"{len(otra)} del árbol de otra vigencia (obligación {total('obligacion', otra):,.2f}, "
                      f"pago {total('pago', otra):,.2f})")
    partes.append(f"{len(subtotales)} subtotales cuadran con el detalle")
    return len(detalle), " | ".join(partes)


class CorteConDistribucion(Exception):
    """El corte ya tiene distribuciones del CUIPO: no se reprocesa ni se borra."""


def procesar(corte):
    """Importa el corte y deja el resultado en el registro. Devuelve True si salio bien.

    Un corte con distribuciones no se reprocesa: sus lineas apuntan a las filas que la
    importacion borraria. Para datos mas recientes se carga otro corte.
    """
    if corte.pk and corte.distribuciones.exists():
        raise CorteConDistribucion(f"{corte} ya tiene distribuciones del CUIPO: no se reprocesa. "
                                   f"Para datos más recientes, cargue un corte nuevo.")
    try:
        corte.filas, corte.mensaje = importar(corte)
        corte.estado = CorteEjecucionGastos.Estado.PROCESADO
    except Exception as error:
        # La transaccion ya se revirtio: si el corte tenia filas de antes, siguen ahi
        corte.filas, corte.mensaje = corte.filas_ejecucion.count(), f"{type(error).__name__}: {error}"
        corte.estado = CorteEjecucionGastos.Estado.ERROR
    corte.save(update_fields=["filas", "mensaje", "estado", "fecha_actualizacion"])
    return corte.estado == CorteEjecucionGastos.Estado.PROCESADO
