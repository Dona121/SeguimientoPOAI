"""Importador de las listas CHIP de la categoria CUIPO (Listas_Categoria_CUIPO_MM-AAAA.xlsx).

El libro trae once hojas con el encabezado en la fila 1. Cada hoja alimenta un catalogo por
codigo: lo nuevo se crea, lo que ya estaba se actualiza y lo que no viene en la version queda
inactivo; nunca se borra nada. Todo corre en una transaccion: si una hoja falla, no queda nada
a medias.

Los codigos se guardan como texto exacto. Excel guarda como numero muchos de ellos (CPC,
vigencia del gasto, politica publica, detalle sectorial); se convierten sin el ".0". Un CPC
numerico de 4 o 6 digitos perdio su cero inicial en Excel y se le devuelve (los validos tienen
1, 5 o 7). Las secciones son texto como "16.0" y se conservan tal cual.
"""
import unicodedata

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from .models import (CPC, ConceptoCUIPO, DetalleSectorial, FuenteCUIPO, PoliticaPublica, ProductoCUIPO,
                     SeccionPresupuestal, SituacionFondos, TerceroCUIPO, VersionListas, VigenciaGasto)

LARGOS_CPC = (1, 5, 7)

# Hoja -> (modelo, {encabezado: campo}). "codigo" es obligatorio en todas; los encabezados se
# comparan sin tildes ni mayusculas.
HOJAS = [
    ("Conceptos por ambito", ConceptoCUIPO, {"codigo": "codigo", "nombre": "descripcion", "nivel": "nivel",
                                             "438 - departamentos": "habilitado_departamentos",
                                             "notas": "notas"}),
    ("Fuentes de Financiación", FuenteCUIPO, {"codigo": "codigo", "descripcion": "descripcion"}),
    ("Secciones Presupuestales", SeccionPresupuestal, {"codigo": "codigo", "descripcion": "descripcion"}),
    ("Vigencia Gasto", VigenciaGasto, {"codigo": "codigo", "descripcion": "descripcion"}),
    ("Producto MGA", ProductoCUIPO, {"codigo": "codigo", "descripcion": "descripcion", "sector": "sector",
                                     "programa": "programa",
                                     "aplica a entidades territoriales": "aplica_territoriales"}),
    ("CPC", CPC, {"codigo": "codigo", "clase o subclase": "descripcion", "seccion": "seccion",
                  "division": "division"}),
    ("Detalle Sectorial", DetalleSectorial, {"codigo": "codigo", "concepto": "descripcion",
                                             "grupo concepto": "grupo", "sector": "sector"}),
    ("Situación de Fondos", SituacionFondos, {"codigo": "codigo", "descripcion": "descripcion"}),
    ("Politica Pública", PoliticaPublica, {"codigo": "codigo", "descripcion": "descripcion"}),
    ("Tercero", TerceroCUIPO, {"codigo": "codigo", "entidad": "descripcion"}),
]
HOJA_CONCEPTOS_CPC = "Conceptos_CPC"
# Columnas que pueden faltar sin que la importacion falle
OPCIONALES = {"notas"}
# CHIP acepta el producto 0 y la hoja no lo trae
PRODUCTO_NO_APLICA = ("0", "NO APLICA")


def normal(texto):
    """Para comparar nombres de hoja y de columna: sin tildes, minusculas, espacios simples."""
    limpio = unicodedata.normalize("NFKD", " ".join(str(texto or "").split()).lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


def codigo(valor, modelo=None):
    """El codigo como texto exacto."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, int):
        texto = str(valor)
        if modelo is CPC and len(texto) in (4, 6):
            texto = texto.zfill(len(texto) + 1)
        return texto
    return str(valor).strip()


def texto(valor):
    return "" if valor is None else " ".join(str(valor).split())


def hoja_del_libro(libro, nombre):
    hojas = {normal(h): h for h in libro.sheetnames}
    if normal(nombre) not in hojas:
        raise ValueError(f'Al libro le falta la hoja "{nombre}". Hojas del libro: {", ".join(libro.sheetnames)}')
    return libro[hojas[normal(nombre)]]


def leer_hoja(libro, nombre, columnas, modelo=None):
    """{codigo: {campo: valor}} de una hoja; valida columnas y codigos repetidos."""
    filas = hoja_del_libro(libro, nombre).iter_rows(values_only=True)
    encabezado = [normal(c) for c in next(filas, ())]
    faltan = [c for c in columnas if c not in encabezado and c not in OPCIONALES]
    if faltan:
        raise ValueError(f'A la hoja "{nombre}" le faltan columnas: {", ".join(faltan)}')
    indice = {c: encabezado.index(c) for c in columnas if c in encabezado}
    registros, repetidos = {}, []
    for fila in filas:
        valores = {campo: fila[indice[c]] if indice[c] < len(fila) else None
                   for c, campo in columnas.items() if c in indice}
        cod = codigo(valores.pop("codigo"), modelo)
        if not cod:
            continue
        if cod in registros:
            repetidos.append(cod)
        registros[cod] = valores
    if repetidos:
        raise ValueError(f'La hoja "{nombre}" repite códigos: {", ".join(repetidos[:10])}')
    return registros


def preparar(modelo, registros, cpc_requerido=frozenset()):
    """Convierte los valores de cada fila a los del modelo y valida lo particular de cada lista."""
    malos = []
    for cod, datos in registros.items():
        for campo in list(datos):
            if campo != "habilitado_departamentos":
                datos[campo] = texto(datos[campo])
        if modelo is ConceptoCUIPO:
            datos["nivel"] = datos["nivel"].upper()
            if datos["nivel"] not in ("S", "D"):
                malos.append(f"{cod} (nivel {datos['nivel'] or 'vacío'})")
            datos["habilitado_departamentos"] = texto(datos["habilitado_departamentos"]) in ("1", "1.0")
            datos["requiere_cpc"] = cod in cpc_requerido
        if modelo is CPC and len(cod) not in LARGOS_CPC:
            malos.append(f"{cod} (largo {len(cod)})")
    if malos:
        raise ValueError(f"{modelo._meta.verbose_name_plural}: códigos inválidos: {', '.join(malos[:10])}")
    if modelo is ProductoCUIPO and PRODUCTO_NO_APLICA[0] not in registros:
        registros[PRODUCTO_NO_APLICA[0]] = {"descripcion": PRODUCTO_NO_APLICA[1], "sector": "", "programa": "",
                                            "aplica_territoriales": ""}
    return registros


def sincronizar(modelo, registros, version):
    """Crea, actualiza y desactiva por codigo. Devuelve (nuevos, cambiados, desactivados)."""
    ahora = timezone.now()
    existentes = {o.codigo: o for o in modelo.objects.all()}
    nuevos, actualizar, cambiados = [], [], 0
    campos = sorted({c for datos in registros.values() for c in datos})
    for cod, datos in registros.items():
        objeto = existentes.get(cod)
        if objeto is None:
            nuevos.append(modelo(codigo=cod, version=version, activo=True, **datos))
            continue
        if not objeto.activo or any(getattr(objeto, c) != v for c, v in datos.items()):
            cambiados += 1
        for c, v in datos.items():
            setattr(objeto, c, v)
        objeto.activo, objeto.version, objeto.fecha_actualizacion = True, version, ahora
        actualizar.append(objeto)
    modelo.objects.bulk_create(nuevos, batch_size=1000)
    modelo.objects.bulk_update(actualizar, [*campos, "activo", "version", "fecha_actualizacion"], batch_size=500)
    salen = [o.pk for cod, o in existentes.items() if cod not in registros and o.activo]
    for i in range(0, len(salen), 500):
        modelo.objects.filter(pk__in=salen[i:i + 500]).update(activo=False, fecha_actualizacion=ahora)
    return len(nuevos), cambiados, len(salen)


@transaction.atomic
def importar(version, contenido):
    """Importa el libro en los catalogos. Devuelve el mensaje del resultado."""
    libro = load_workbook(contenido, read_only=True, data_only=True)
    try:
        con_cpc = set(leer_hoja(libro, HOJA_CONCEPTOS_CPC, {"codigo": "codigo"}))
        leidas = [(modelo, leer_hoja(libro, nombre, columnas, modelo)) for nombre, modelo, columnas in HOJAS]
    finally:
        libro.close()

    partes, avisos = [], []
    for modelo, registros in leidas:
        registros = preparar(modelo, registros, con_cpc)
        nuevos, cambiados, salen = sincronizar(modelo, registros, version)
        detalle = [f"{nuevos} nuevos"] if nuevos else []
        detalle += [f"{cambiados} cambiados"] if cambiados else []
        detalle += [f"{salen} inactivos"] if salen else []
        partes.append(f"{modelo._meta.verbose_name_plural}: {len(registros)}"
                      + (f" ({', '.join(detalle)})" if detalle else ""))
        if modelo is ConceptoCUIPO:
            sin_concepto = sorted(con_cpc - set(registros))
            if sin_concepto:
                avisos.append(f"Conceptos_CPC trae códigos que no están en los conceptos: "
                              f"{', '.join(sin_concepto[:10])}")
    return " | ".join(partes + avisos)


def procesar(version, contenido):
    """Importa y deja el resultado en la version. Devuelve True si salio bien."""
    try:
        version.mensaje = importar(version, contenido)
        version.estado = VersionListas.Estado.PROCESADO
    except Exception as error:
        # La transaccion ya se revirtio: los catalogos quedan como estaban
        version.mensaje = f"{type(error).__name__}: {error}"
        version.estado = VersionListas.Estado.ERROR
    version.save(update_fields=["mensaje", "estado", "fecha_actualizacion"])
    return version.estado == VersionListas.Estado.PROCESADO
