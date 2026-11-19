"""Programacion financiera de un proyecto: cuanto va de cada fuente a cada meta, por vigencia.

La pantalla (ProyectoAdmin.programacion_financiera) es una matriz con tres listados que el
equipo arma: vigencias, fuentes y metas. Cada vigencia es un bloque de filas (una por fuente),
las metas son las columnas y en cada cruce va el valor. Los montos los define el equipo; aqui
no se contrastan con SIIFWEB.

- Al abrir: las vigencias, fuentes y metas que ya tienen valores, mas las metas en que el
  proyecto esta programado para esas vigencias (Programacion de proyectos, por el BPIN). Sin
  nada guardado, la vigencia del anio en curso.
- La matriz es un formulario. Digitar, agregar o quitar una vigencia, una fuente o una meta no
  toca la base: lo que se ve viaja en la pagina (campos ocultos "vigencias", "fuentes" y
  "metas" y una casilla por cruce, v-<vigencia>-<fuente>-<meta>).
- El boton Guardar deja la programacion del proyecto exactamente como se ve: crea o cambia los
  valores y borra los vacios o en cero y los de vigencias, fuentes o metas quitadas. Si una
  casilla tiene un error no se guarda nada.
- Los numeros se escriben como en Colombia: punto para miles y coma para decimales.
"""
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Fuente, MetaIndicador, ProgramacionFinanciera, ProgramacionMeta, listado_vigencias_metas

CERO = Decimal(0)
ENTEROS = 15
DECIMALES = 5
POR_PAGINA = 50


# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------

def leer_valor(texto):
    """'1.500.000,5' -> Decimal('1500000.5'). Vacio -> cero. Lo que no se puede leer, ValueError."""
    limpio = re.sub(r"[\s$]", "", texto or "")
    if not limpio:
        return CERO
    if limpio.count(",") > 1:
        raise ValueError("Use la coma solo para los decimales (por ejemplo 1.500.000,50).")
    if not re.fullmatch(r"-?[\d.]*(,\d*)?", limpio):
        raise ValueError("El valor tiene que ser un número (por ejemplo 1.500.000,50).")
    normal = limpio.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(normal)
    except InvalidOperation:
        raise ValueError("El valor tiene que ser un número (por ejemplo 1.500.000,50).")
    if valor < 0:
        raise ValueError("El valor no puede ser negativo.")
    if valor.as_tuple().exponent < -DECIMALES:
        raise ValueError(f"El valor admite hasta {DECIMALES} decimales.")
    if valor.adjusted() >= ENTEROS:
        raise ValueError(f"El valor admite hasta {ENTEROS} dígitos enteros.")
    return valor


def _leer_o_none(texto):
    try:
        return leer_valor(texto)
    except ValueError:
        return None


def formato(valor):
    """Decimal('1500000.50000') -> '1.500.000,5'. Sin ceros de mas; cero o None, vacio."""
    if not valor:
        return ""
    valor = Decimal(valor)
    valor = valor.quantize(Decimal(1)) if valor == valor.to_integral_value() else valor.normalize()
    entero, _, decimales = format(valor, "f").partition(".")
    signo = "-" if entero.startswith("-") else ""
    entero = f"{int(entero.lstrip('-')):,}".replace(",", ".")
    return signo + entero + (f",{decimales}" if decimales else "")


# ---------------------------------------------------------------------------
# Listados y casillas
# ---------------------------------------------------------------------------

def vigencias_validas():
    return [v for v, _ in listado_vigencias_metas()]


def _ids(valores, validos=None):
    """Enteros sin repetir, en el orden en que llegan (y solo los validos, si se dicen)."""
    vistos = []
    for v in valores or ():
        if str(v).isdigit() and int(v) not in vistos and (validos is None or int(v) in validos):
            vistos.append(int(v))
    return vistos


def digitados_de(datos):
    """{(vigencia, fuente, meta): texto} de las casillas del formulario (v-<vig>-<fuente>-<meta>)."""
    digitados = {}
    for clave in datos:
        partes = clave.split("-")
        if len(partes) == 4 and partes[0] == "v" and all(p.isdigit() for p in partes[1:]):
            digitados[tuple(int(p) for p in partes[1:])] = datos.get(clave, "")
    return digitados


def metas_programadas(proyecto, vigencias):
    """{meta: [vigencias]} en que el proyecto (por su BPIN) esta programado (Programacion de proyectos)."""
    programadas = {}
    if proyecto.bpin and vigencias:
        for meta_id, vigencia in (ProgramacionMeta.objects.filter(proyecto__bpin=proyecto.bpin, vigencia__in=vigencias)
                                  .values_list("meta_id", "vigencia").distinct()):
            programadas.setdefault(meta_id, set()).add(vigencia)
    return {m: sorted(v) for m, v in programadas.items()}


# ---------------------------------------------------------------------------
# La matriz
# ---------------------------------------------------------------------------

def matriz(proyecto, vigencias=None, fuentes=None, metas=None, digitados=None, errores=None):
    """Bloques por vigencia con una fila por fuente y una columna por meta, y sus totales.

    Sin listados (al abrir) salen de lo guardado y de las metas programadas. Con ellos (al
    agregar, quitar o guardar con errores) se muestran exactamente esos, con lo digitado en
    `digitados`; una casilla cuyo texto no coincide con lo guardado queda como cambio
    pendiente. Los totales de la tabla suman lo que se ve.
    """
    registros = list(proyecto.programacion_financiera.all())
    guardados = {(r.vigencia, r.fuente_id, r.meta_id): r.valor for r in registros}
    if vigencias is None:
        ids_vigencias = sorted({r.vigencia for r in registros}) or [timezone.localdate().year]
    else:
        ids_vigencias = sorted(_ids(vigencias, set(vigencias_validas())))
    programadas = metas_programadas(proyecto, ids_vigencias)
    ids_fuentes = sorted({r.fuente_id for r in registros}) if fuentes is None else _ids(fuentes)
    ids_metas = sorted({r.meta_id for r in registros} | set(programadas)) if metas is None else _ids(metas)
    lista_fuentes = list(Fuente.objects.filter(pk__in=ids_fuentes).order_by("codigo"))
    lista_metas = list(MetaIndicador.objects.filter(pk__in=ids_metas).order_by("codigo"))
    digitados, errores = digitados or {}, errores or {}

    bloques, por_meta = [], {m.pk: CERO for m in lista_metas}
    for v in ids_vigencias:
        filas, subtotales = [], {m.pk: CERO for m in lista_metas}
        for f in lista_fuentes:
            celdas, total_fila = [], CERO
            for m in lista_metas:
                clave = (v, f.pk, m.pk)
                guardado = guardados.get(clave)
                texto = digitados[clave] if clave in digitados else formato(guardado)
                leido = _leer_o_none(texto)
                celdas.append({"meta": m, "texto": texto, "nombre": f"v-{v}-{f.pk}-{m.pk}", "con": bool(leido),
                               "cambio": leido is None or leido != (guardado or CERO), "error": errores.get(clave, "")})
                subtotales[m.pk] += leido or CERO
                total_fila += leido or CERO
            filas.append({"fuente": f, "celdas": celdas, "total_texto": formato(total_fila) or "0"})
        for m_id, valor in subtotales.items():
            por_meta[m_id] += valor
        bloques.append({"vigencia": v, "filas": filas, "total_texto": formato(sum(subtotales.values(), CERO)) or "0",
                        "subtotales": [formato(subtotales[m.pk]) or "0" for m in lista_metas],
                        "guardada": any(vi == v for vi, _, _ in guardados)})

    columnas = [{"meta": m, "total_texto": formato(por_meta[m.pk]) or "0", "programada": programadas.get(m.pk, []),
                 "guardada": any(me == m.pk for _, _, me in guardados)} for m in lista_metas]
    visibles = {(v, f.pk, m.pk) for v in ids_vigencias for f in lista_fuentes for m in lista_metas}
    por_borrar = [clave for clave in guardados if clave not in visibles]
    pendiente = bool(por_borrar) or any(c["cambio"] for b in bloques for f in b["filas"] for c in f["celdas"])
    por_vigencia = list(proyecto.programacion_financiera.values("vigencia").annotate(t=Sum("valor")).order_by("vigencia"))
    return {
        "bloques": bloques, "columnas": columnas, "total_texto": formato(sum(por_meta.values(), CERO)) or "0",
        "fuentes_guardadas": {fu for _, fu, _ in guardados},
        "vigencias": ids_vigencias, "fuentes": [f.pk for f in lista_fuentes], "metas": [m.pk for m in lista_metas],
        "sin_fuentes": not lista_fuentes, "sin_metas": not lista_metas,
        "pendiente": pendiente, "por_borrar": len(por_borrar), "errores": len(errores),
        "por_vigencia": [(p["vigencia"], formato(p["t"]) or "0") for p in por_vigencia],
        "total_proyecto": formato(proyecto.valor_programado) or "0",
    }


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def guardar(proyecto, vigencias, fuentes, metas, digitados):
    """Deja la programacion del proyecto como se ve en la matriz. Devuelve ({casilla: error}, mensaje).

    Con algun error no cambia nada. Si no: crea o cambia los valores, y borra los vacios o en
    cero y los de vigencias, fuentes o metas que ya no estan en la matriz.
    """
    ids_vigencias = _ids(vigencias, set(vigencias_validas()))
    ids_fuentes = set(Fuente.objects.filter(pk__in=_ids(fuentes)).values_list("pk", flat=True))
    ids_metas = set(MetaIndicador.objects.filter(pk__in=_ids(metas)).values_list("pk", flat=True))
    valores, errores = {}, {}
    for v in ids_vigencias:
        for f in ids_fuentes:
            for m in ids_metas:
                try:
                    valores[(v, f, m)] = leer_valor(digitados.get((v, f, m), ""))
                except ValueError as e:
                    errores[(v, f, m)] = str(e)
    if errores:
        return errores, ""

    creados = cambiados = borrados = 0
    with transaction.atomic():
        for r in list(proyecto.programacion_financiera.all()):
            nuevo = valores.pop((r.vigencia, r.fuente_id, r.meta_id), CERO)
            if not nuevo:
                r.delete()                  # uno por uno: la senal recalcula el total del proyecto
                borrados += 1
            elif nuevo != r.valor:
                r.valor = nuevo
                r.save(update_fields=["valor", "fecha_actualizacion"])
                cambiados += 1
        for (v, f, m), valor in valores.items():
            if valor:
                ProgramacionFinanciera.objects.create(proyecto=proyecto, vigencia=v, fuente_id=f, meta_id=m, valor=valor)
                creados += 1
    partes = [f"{n} {texto}" for n, texto in ((creados, "nuevos"), (cambiados, "cambiados"), (borrados, "borrados")) if n]
    return {}, ("Guardado: " + ", ".join(partes) + ".") if partes else "Sin cambios."


# ---------------------------------------------------------------------------
# El listado de la ventana para agregar
# ---------------------------------------------------------------------------

def opciones(tipo, texto="", excluir=(), pagina=1):
    """Una pagina del listado de vigencias, fuentes o metas que coinciden con el texto, sin las
    que ya estan en la matriz. Devuelve {"lista": [(id, codigo, nombre)], "pagina", "paginas", "total"}."""
    texto = (texto or "").strip()
    presentes = _ids(excluir)
    if tipo == "vigencia":
        todas = [(v, str(v), "") for v in reversed(vigencias_validas()) if v not in presentes and texto in str(v)]
    elif tipo == "fuente":
        consulta = Fuente.objects.exclude(pk__in=presentes).order_by("codigo")
        if texto:
            consulta = consulta.filter(Q(codigo__icontains=texto) | Q(nombre__icontains=texto))
        todas = consulta
    else:
        consulta = MetaIndicador.objects.filter(estado=True).exclude(pk__in=presentes).order_by("codigo")
        if texto:
            consulta = consulta.filter(Q(codigo__icontains=texto) | Q(descripcion__icontains=texto)
                                       | Q(indicador_mga__codigo__icontains=texto))
        todas = consulta
    total = len(todas) if isinstance(todas, list) else todas.count()
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(int(pagina) if str(pagina).isdigit() else 1, 1), paginas)
    tramo = todas[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
    if tipo == "fuente":
        lista = [(f.pk, f.codigo, f.nombre) for f in tramo]
    elif tipo == "meta":
        lista = [(m.pk, m.codigo, m.descripcion) for m in tramo]
    else:
        lista = list(tramo)
    return {"lista": lista, "pagina": pagina, "paginas": paginas, "total": total,
            "desde": (pagina - 1) * POR_PAGINA + 1 if total else 0, "hasta": (pagina - 1) * POR_PAGINA + len(lista)}
