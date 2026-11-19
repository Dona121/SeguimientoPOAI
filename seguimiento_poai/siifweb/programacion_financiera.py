"""Programacion de un proyecto por vigencia: financiera (cuanto va de cada fuente a cada meta) y
fisica (cuanto se programa avanzar en cada meta; como la financiera, pero sin fuente). Las dos
son pestanas de la misma pantalla (ProyectoAdmin.programacion_financiera, ?panel=fisica).

Cada pestana tiene un bloque por vigencia, independiente: en la financiera sus fuentes (filas) y
metas (columnas), en la fisica sus metas (filas), con el valor en cada cruce. Los montos los
define el equipo; aqui no se contrastan con SIIFWEB.

Las metas de las dos deben ser las mismas en cada vigencia (una meta con valor en una debe
tenerlo en la otra). No es un constraint de la base (son dos tablas) ni bloquea al guardar,
porque se puede diligenciar primero cualquiera de las dos. Se mantiene asi:
- Espejo: al abrir una pestana, o al agregar una vigencia, cada bloque trae tambien las metas
  que la otra pestana tiene guardadas en esa vigencia.
- Aviso: cada bloque dice que metas tienen valor en una y no en la otra (`descuadres`), y al
  guardar, si no coinciden, sale un mensaje de advertencia con cuales son.
- Quitar una meta o una vigencia en una pestana nunca borra la otra (si alguien la quita por
  error, el trabajo de la otra queda intacto); el mensaje avisa que ya no coinciden.

Otros detalles:
- Al abrir sin nada guardado en ninguna de las dos, la vigencia del anio en curso vacia. Las
  metas en que el proyecto esta programado (Programacion de proyectos, por el BPIN) salen
  primero en el listado de "+ Meta", marcadas como programadas; no se agregan solas.
- La pantalla es un formulario. Digitar, agregar o quitar no toca la base: lo que se ve viaja
  en la pagina (campos ocultos "vigencias", "fuentes-<vigencia>", "metas-<vigencia>" y una
  casilla por cruce: v-<vigencia>-<fuente>-<meta> en la financiera, v-<vigencia>-<meta> en la
  fisica).
- Guardar deja la pestana exactamente como se ve: crea o cambia los valores y borra los vacios o
  en cero y lo quitado. Si una casilla tiene un error no se guarda nada.
- Los numeros se escriben como en las casillas del CUIPO: sin separador de miles y con punto
  decimal (1500000.50); se leen con siifweb.cargas.decimal. Los totales se muestran como en la
  pantalla del CUIPO (floatformat "2g").
"""
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import timezone

from .models import (Fuente, MetaIndicador, ProgramacionFinanciera, ProgramacionFisica, ProgramacionMeta,
                     listado_vigencias_metas)

CERO = Decimal(0)
ENTEROS = 15
DECIMALES = 5
POR_PAGINA = 50


# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------

def leer_valor(texto):
    """'1500000.5' -> Decimal('1500000.5'). Vacio -> cero. Lo que no se puede leer, ValueError.

    Se lee igual que las casillas del CUIPO (siifweb.cargas.decimal): el punto es el decimal."""
    from .cargas import decimal
    limpio = re.sub(r"[\s$]", "", texto or "")
    if not limpio:
        return CERO
    try:
        valor = decimal(limpio)
    except (ValueError, ArithmeticError):
        valor = None
    if valor is None or not valor.is_finite():
        raise ValueError("El valor tiene que ser un número (por ejemplo 1500000.50).")
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


def en_casilla(valor):
    """Decimal('1500000.50000') -> '1500000.5': como se escribe en la casilla, sin ceros de mas.
    Cero o None, vacio."""
    if not valor:
        return ""
    valor = Decimal(valor)
    valor = valor.quantize(Decimal(1)) if valor == valor.to_integral_value() else valor.normalize()
    return format(valor, "f")


# ---------------------------------------------------------------------------
# Lo que se ve: {vigencia: {"fuentes": [ids], "metas": [ids]}}
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


def _bloque_vacio():
    return {"fuentes": [], "metas": []}


def metas_guardadas(proyecto, fisica):
    """{vigencia: {metas con valor}} de la programacion financiera o de la fisica."""
    modelo = proyecto.programacion_fisica if fisica else proyecto.programacion_financiera
    metas = {}
    for v, m in modelo.values_list("vigencia", "meta_id").distinct():
        metas.setdefault(v, set()).add(m)
    return metas


def espejo(proyecto, fisica, vigencia):
    """Las metas que la otra pestana tiene guardadas en la vigencia."""
    return sorted(metas_guardadas(proyecto, not fisica).get(vigencia, set()))


def estado_guardado(proyecto, fisica=False):
    """Lo que se ve al abrir: las vigencias y metas de lo guardado en la pestana y en la otra
    (espejo); en la financiera, ademas, sus fuentes. Sin nada, el anio en curso vacio."""
    estado = {}
    if fisica:
        filas = ((v, None, m) for v, m in proyecto.programacion_fisica.values_list("vigencia", "meta_id"))
    else:
        filas = proyecto.programacion_financiera.values_list("vigencia", "fuente_id", "meta_id")
    for v, f, m in filas:
        bloque = estado.setdefault(v, _bloque_vacio())
        if f is not None and f not in bloque["fuentes"]:
            bloque["fuentes"].append(f)
        if m not in bloque["metas"]:
            bloque["metas"].append(m)
    for v, metas in metas_guardadas(proyecto, not fisica).items():
        bloque = estado.setdefault(v, _bloque_vacio())
        bloque["metas"] += [m for m in sorted(metas) if m not in bloque["metas"]]
    return estado or {timezone.localdate().year: _bloque_vacio()}


def estado_de(datos):
    """Lo que se ve, leido del formulario (campos ocultos)."""
    validas = set(vigencias_validas())
    return {v: {"fuentes": _ids(datos.getlist(f"fuentes-{v}")), "metas": _ids(datos.getlist(f"metas-{v}"))}
            for v in _ids(datos.getlist("vigencias"), validas)}


def cambiar_estado(estado, datos, proyecto=None, fisica=False):
    """Aplica lo que pide el boton: agregar o quitar una vigencia, o una fuente o una meta en una
    vigencia (`en`). Al agregar una vigencia trae las metas que la otra pestana tiene en ella (si
    se da el proyecto)."""
    for v in _ids([datos.get("agregar_vigencia")], set(vigencias_validas())):
        bloque = estado.setdefault(v, _bloque_vacio())
        if proyecto is not None:
            bloque["metas"] += [m for m in espejo(proyecto, fisica, v) if m not in bloque["metas"]]
    for v in _ids([datos.get("quitar_vigencia")]):
        estado.pop(v, None)
    en = _ids([datos.get("en")])
    if en and en[0] in estado:
        bloque = estado[en[0]]
        for tipo in ("fuente", "meta"):
            lista = bloque[tipo + "s"]
            for x in _ids([datos.get(f"agregar_{tipo}")]):
                if x not in lista:
                    lista.append(x)
            for x in _ids([datos.get(f"quitar_{tipo}")]):
                if x in lista:
                    lista.remove(x)
    return estado


def digitados_de(datos):
    """Las casillas del formulario: {(vigencia, fuente, meta): texto} en la financiera
    (v-<vig>-<fuente>-<meta>) y {(vigencia, meta): texto} en la fisica (v-<vig>-<meta>)."""
    digitados = {}
    for clave in datos:
        partes = clave.split("-")
        if len(partes) in (3, 4) and partes[0] == "v" and all(p.isdigit() for p in partes[1:]):
            digitados[tuple(int(p) for p in partes[1:])] = datos.get(clave, "")
    return digitados


def metas_programadas(proyecto, vigencia):
    """Ids de las metas en que el proyecto (por su BPIN) esta programado para la vigencia."""
    if not proyecto.bpin:
        return set()
    return set(ProgramacionMeta.objects.filter(proyecto__bpin=proyecto.bpin, vigencia=vigencia)
               .values_list("meta_id", flat=True))


# ---------------------------------------------------------------------------
# Coincidencia de metas entre las dos pestanas
# ---------------------------------------------------------------------------

def descuadres(proyecto):
    """{vigencia: {"sin_fisica": [metas], "sin_financiera": [metas]}} de lo guardado: metas con
    valor financiero y sin valor fisico, y al reves. Solo las vigencias que no coinciden."""
    financieras, fisicas = metas_guardadas(proyecto, False), metas_guardadas(proyecto, True)
    ids = {m for metas in (*financieras.values(), *fisicas.values()) for m in metas}
    codigos = dict(MetaIndicador.objects.filter(pk__in=ids).values_list("pk", "codigo"))
    resultado = {}
    for v in sorted(set(financieras) | set(fisicas)):
        fin, fis = financieras.get(v, set()), fisicas.get(v, set())
        if fin != fis:
            resultado[v] = {"sin_fisica": sorted(codigos[m] for m in fin - fis),
                            "sin_financiera": sorted(codigos[m] for m in fis - fin)}
    return resultado


def mensaje_descuadre(proyecto):
    """El mensaje de advertencia cuando las metas de las dos pestanas no coinciden, o vacio."""
    partes = []
    for v, d in descuadres(proyecto).items():
        detalle = []
        if d["sin_fisica"]:
            detalle.append("sin valor físico " + ", ".join(d["sin_fisica"]))
        if d["sin_financiera"]:
            detalle.append("sin valor financiero " + ", ".join(d["sin_financiera"]))
        partes.append(f"{v}: " + "; ".join(detalle))
    if not partes:
        return ""
    return ("Las metas de la programación financiera y la física no coinciden. " + ". ".join(partes)
            + ". Complete la otra pestaña o corrija esta.")


def _comun(bloques, guardados, visibles, errores, proyecto):
    """Lo que las dos pestanas devuelven igual: avisos de coincidencia y pendientes."""
    por_borrar = [clave for clave in guardados if clave not in visibles]
    desc = descuadres(proyecto)
    for b in bloques:
        b["descuadre"] = desc.get(b["vigencia"])
    return {"bloques": bloques, "por_borrar": len(por_borrar), "errores": len(errores)}


# ---------------------------------------------------------------------------
# La pestana financiera
# ---------------------------------------------------------------------------

def matriz(proyecto, estado=None, digitados=None, errores=None):
    """Un bloque por vigencia con sus fuentes (filas), sus metas (columnas), los valores y totales.

    Sin estado (al abrir) sale de lo guardado y del espejo de la fisica. Con estado (al agregar,
    quitar o guardar con errores) se muestra exactamente ese, con lo digitado en `digitados`; una
    casilla cuyo texto no coincide con lo guardado queda como cambio pendiente. Los totales suman
    lo que se ve.
    """
    estado = estado_guardado(proyecto) if estado is None else estado
    guardados = {(r.vigencia, r.fuente_id, r.meta_id): r.valor for r in proyecto.programacion_financiera.all()}
    todas_fuentes = {f.pk: f for f in Fuente.objects.filter(pk__in={x for b in estado.values() for x in b["fuentes"]})}
    todas_metas = {m.pk: m for m in MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})}
    digitados, errores = digitados or {}, errores or {}

    bloques, visibles = [], set()
    for v in sorted(estado):
        fuentes = sorted((todas_fuentes[x] for x in estado[v]["fuentes"] if x in todas_fuentes), key=lambda f: f.codigo)
        metas = sorted((todas_metas[x] for x in estado[v]["metas"] if x in todas_metas), key=lambda m: m.codigo)
        programadas = metas_programadas(proyecto, v)
        filas, por_meta = [], {m.pk: CERO for m in metas}
        for f in fuentes:
            celdas, total_fila = [], CERO
            for m in metas:
                clave = (v, f.pk, m.pk)
                visibles.add(clave)
                guardado = guardados.get(clave)
                texto = digitados[clave] if clave in digitados else en_casilla(guardado)
                leido = _leer_o_none(texto)
                celdas.append({"meta": m, "texto": texto, "nombre": f"v-{v}-{f.pk}-{m.pk}", "con": bool(leido),
                               "cambio": leido is None or leido != (guardado or CERO), "error": errores.get(clave, "")})
                por_meta[m.pk] += leido or CERO
                total_fila += leido or CERO
            filas.append({"fuente": f, "celdas": celdas, "total": total_fila})
        bloques.append({
            "vigencia": v, "filas": filas, "fuentes": [f.pk for f in fuentes], "metas": [m.pk for m in metas],
            "columnas": [{"meta": m, "total": por_meta[m.pk], "programada": m.pk in programadas} for m in metas],
            "total": sum(por_meta.values(), CERO),
        })

    comun = _comun(bloques, guardados, visibles, errores, proyecto)
    por_vigencia = list(proyecto.programacion_financiera.values("vigencia").annotate(t=Sum("valor")).order_by("vigencia"))
    return {
        **comun, "total": sum((b["total"] for b in bloques), CERO),
        "pendiente": bool(comun["por_borrar"])
                     or any(c["cambio"] for b in bloques for f in b["filas"] for c in f["celdas"]),
        "por_vigencia": [(p["vigencia"], p["t"]) for p in por_vigencia],
        "total_proyecto": proyecto.valor_programado,
    }


def guardar(proyecto, estado, digitados):
    """Deja la programacion financiera como se ve. Devuelve ({casilla: error}, mensaje).

    Con algun error no cambia nada. Si no: crea o cambia los valores y borra los vacios o en cero
    y lo que ya no esta en la pantalla. La fisica no se toca.
    """
    fuentes_validas = set(Fuente.objects.filter(pk__in={x for b in estado.values() for x in b["fuentes"]})
                          .values_list("pk", flat=True))
    metas_validas = set(MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})
                        .values_list("pk", flat=True))
    valores, errores = {}, {}
    for v, bloque in estado.items():
        for f in bloque["fuentes"]:
            for m in bloque["metas"]:
                if f in fuentes_validas and m in metas_validas:
                    try:
                        valores[(v, f, m)] = leer_valor(digitados.get((v, f, m), ""))
                    except ValueError as e:
                        errores[(v, f, m)] = str(e)
    if errores:
        return errores, ""

    with transaction.atomic():
        cuentas = _sincronizar(list(proyecto.programacion_financiera.all()), valores,
                               lambda r: (r.vigencia, r.fuente_id, r.meta_id),
                               lambda clave, valor: ProgramacionFinanciera.objects.create(
                                   proyecto=proyecto, vigencia=clave[0], fuente_id=clave[1], meta_id=clave[2],
                                   valor=valor))
    return {}, _mensaje(*cuentas)


# ---------------------------------------------------------------------------
# La pestana fisica: un bloque por vigencia con sus metas y un valor por meta
# ---------------------------------------------------------------------------

def matriz_fisica(proyecto, estado=None, digitados=None, errores=None):
    """Un bloque por vigencia con una fila por meta y su valor. Como `matriz`, sin fuentes; no
    lleva totales: cada meta tiene su propia unidad de medida."""
    estado = estado_guardado(proyecto, fisica=True) if estado is None else estado
    guardados = {(r.vigencia, r.meta_id): r.valor for r in proyecto.programacion_fisica.all()}
    todas = {m.pk: m for m in MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})
             .select_related("indicador_mga__unidad_medida")}
    digitados, errores = digitados or {}, errores or {}
    bloques, visibles = [], set()
    for v in sorted(estado):
        programadas = metas_programadas(proyecto, v)
        filas = []
        for m in sorted((todas[x] for x in estado[v]["metas"] if x in todas), key=lambda m: m.codigo):
            clave = (v, m.pk)
            visibles.add(clave)
            guardado = guardados.get(clave)
            texto = digitados[clave] if clave in digitados else en_casilla(guardado)
            leido = _leer_o_none(texto)
            filas.append({"meta": m, "texto": texto, "nombre": f"v-{v}-{m.pk}", "con": bool(leido),
                          "cambio": leido is None or leido != (guardado or CERO), "error": errores.get(clave, ""),
                          "programada": m.pk in programadas})
        bloques.append({"vigencia": v, "filas": filas, "metas": [f["meta"].pk for f in filas]})
    comun = _comun(bloques, guardados, visibles, errores, proyecto)
    return {**comun, "pendiente": bool(comun["por_borrar"])
            or any(f["cambio"] for b in bloques for f in b["filas"])}


def guardar_fisica(proyecto, estado, digitados):
    """Deja la programacion fisica como se ve. Devuelve ({casilla: error}, mensaje). Con algun
    error no cambia nada; vacio o cero borra. La financiera no se toca."""
    validas = set(MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})
                  .values_list("pk", flat=True))
    valores, errores = {}, {}
    for v, bloque in estado.items():
        for m in bloque["metas"]:
            if m in validas:
                try:
                    valores[(v, m)] = leer_valor(digitados.get((v, m), ""))
                except ValueError as e:
                    errores[(v, m)] = str(e)
    if errores:
        return errores, ""
    with transaction.atomic():
        cuentas = _sincronizar(list(proyecto.programacion_fisica.all()), valores, lambda r: (r.vigencia, r.meta_id),
                               lambda clave, valor: ProgramacionFisica.objects.create(
                                   proyecto=proyecto, vigencia=clave[0], meta_id=clave[1], valor=valor))
    return {}, _mensaje(*cuentas)


def _sincronizar(registros, valores, clave_de, crear):
    """Deja los registros como dicen los valores. Devuelve (creados, cambiados, borrados)."""
    valores = dict(valores)
    creados = cambiados = borrados = 0
    for r in registros:
        nuevo = valores.pop(clave_de(r), CERO)
        if not nuevo:
            r.delete()                      # uno por uno: la senal recalcula el total del proyecto
            borrados += 1
        elif nuevo != r.valor:
            r.valor = nuevo
            r.save(update_fields=["valor", "fecha_actualizacion"])
            cambiados += 1
    for clave, valor in valores.items():
        if valor:
            crear(clave, valor)
            creados += 1
    return creados, cambiados, borrados


def _mensaje(creados, cambiados, borrados):
    partes = [f"{n} {texto}" for n, texto in ((creados, "nuevos"), (cambiados, "cambiados"), (borrados, "borrados")) if n]
    return ("Guardado: " + ", ".join(partes) + ".") if partes else "Sin cambios."


# ---------------------------------------------------------------------------
# El listado de la ventana para agregar
# ---------------------------------------------------------------------------

def opciones(tipo, texto="", excluir=(), pagina=1, programadas=()):
    """Una pagina del listado de vigencias, fuentes o metas que coinciden con el texto, sin las
    que ya estan. En metas, las `programadas` van primero y marcadas.
    Devuelve {"lista": [(id, codigo, nombre, programada)], "pagina", "paginas", "total", "desde", "hasta"}."""
    texto = (texto or "").strip()
    presentes = _ids(excluir)
    programadas = set(programadas)
    if tipo == "vigencia":
        todas = [(v, str(v), "", False) for v in reversed(vigencias_validas()) if v not in presentes and texto in str(v)]
    elif tipo == "fuente":
        consulta = Fuente.objects.exclude(pk__in=presentes).order_by("codigo")
        if texto:
            consulta = consulta.filter(Q(codigo__icontains=texto) | Q(nombre__icontains=texto))
        todas = consulta
    else:
        consulta = MetaIndicador.objects.filter(estado=True).exclude(pk__in=presentes)
        if texto:
            consulta = consulta.filter(Q(codigo__icontains=texto) | Q(descripcion__icontains=texto)
                                       | Q(indicador_mga__codigo__icontains=texto))
        todas = consulta.annotate(orden=Case(When(pk__in=programadas, then=Value(0)), default=Value(1),
                                             output_field=IntegerField())).order_by("orden", "codigo")
    total = len(todas) if isinstance(todas, list) else todas.count()
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(int(pagina) if str(pagina).isdigit() else 1, 1), paginas)
    tramo = todas[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
    if tipo == "fuente":
        lista = [(f.pk, f.codigo, f.nombre, False) for f in tramo]
    elif tipo == "meta":
        lista = [(m.pk, m.codigo, m.descripcion, m.pk in programadas) for m in tramo]
    else:
        lista = list(tramo)
    return {"lista": lista, "pagina": pagina, "paginas": paginas, "total": total,
            "desde": (pagina - 1) * POR_PAGINA + 1 if total else 0, "hasta": (pagina - 1) * POR_PAGINA + len(lista)}
