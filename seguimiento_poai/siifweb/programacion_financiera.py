"""Programacion de un proyecto por vigencia: financiera (cuanto pone cada entidad aportante, de
cada fuente, a cada meta) y fisica (cuanto se programa avanzar en cada meta; como la financiera,
pero sin entidad ni fuente). Las dos son pestanas de la misma pantalla
(ProyectoAdmin.programacion_financiera, ?panel=fisica).

Cada pestana tiene un bloque por vigencia, independiente: en la financiera sus entidades
aportantes, las fuentes de cada una (filas) y las metas (columnas); en la fisica sus metas
(filas), con el valor en cada cruce. Los montos los define el equipo; aqui no se contrastan con
SIIFWEB.

Entidad aportante (desde el 27/11/2026): un proyecto puede tener recursos de varias entidades, asi
que la financiera es la combinacion proyecto, vigencia, entidad, fuente y meta. Lo programado
antes no tiene entidad: sale primero, como "Sin entidad aportante", con un boton para asignarla,
y mientras tenga valor la pestana no se guarda.

Las metas de las dos deben ser las mismas en el proyecto (una meta con valor en una debe
tenerlo en la otra), pero no en cada vigencia: un proyecto puede tener las fuentes en 2025 y 2027
y la meta fisica en 2026 (decision del usuario, 27/11/2026). No es un constraint de la base (son
dos tablas) ni bloquea al guardar, porque se puede diligenciar primero cualquiera de las dos. Se
mantiene asi:
- Cada pestana muestra solo sus vigencias.
- Espejo: una vigencia nueva (al agregarla, o la del anio en curso al abrir una pestana sin nada
  guardado) trae las metas que la otra pestana tiene guardadas, en cualquier vigencia.
- Aviso: la pestana dice que metas tienen valor en una y en la otra no, en ninguna vigencia
  (`descuadres`), y al guardar, si no coinciden, sale un mensaje de advertencia con cuales son.
- Quitar una meta o una vigencia en una pestana nunca borra la otra (si alguien la quita por
  error, el trabajo de la otra queda intacto); el mensaje avisa que ya no coinciden.

Otros detalles:
- Al abrir sin nada guardado en ninguna de las dos, la vigencia del anio en curso vacia. Las
  metas en que el proyecto esta programado (Programacion de proyectos, por el BPIN) salen
  primero en el listado de "+ Meta", marcadas como programadas; no se agregan solas.
- La pantalla es un formulario. Digitar, agregar o quitar no toca la base: lo que se ve viaja
  en la pagina (campos ocultos "vigencias", "entidades-<vigencia>", "fuentes-<vigencia>-<entidad>",
  "metas-<vigencia>" y una casilla por cruce: v-<vigencia>-<entidad>-<fuente>-<meta> en la
  financiera, v-<vigencia>-<meta> en la fisica).
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

from .models import (EntidadAportante, Fuente, MetaIndicador, ProgramacionFinanciera, ProgramacionFisica,
                     ProgramacionMeta, listado_vigencias_metas)

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
# Lo que se ve: {vigencia: {"entidades": [ids], "fuentes": {entidad: [ids]}, "metas": [ids]}}
# La fisica solo usa "metas". La entidad SIN_ENTIDAD es la de lo programado antes del campo.
# ---------------------------------------------------------------------------

SIN_ENTIDAD = 0


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
    return {"entidades": [], "fuentes": {}, "metas": []}


def metas_guardadas(proyecto, fisica):
    """Las metas con valor en la programacion financiera o en la fisica, en cualquier vigencia."""
    modelo = proyecto.programacion_fisica if fisica else proyecto.programacion_financiera
    return set(modelo.values_list("meta_id", flat=True))


def espejo(proyecto, fisica):
    """Las metas que la otra pestana tiene guardadas, en cualquier vigencia."""
    return sorted(metas_guardadas(proyecto, not fisica))


def _bloque_nuevo(proyecto, fisica):
    """Una vigencia nueva: sin entidades ni fuentes y con las metas de la otra pestana."""
    return {**_bloque_vacio(), "metas": espejo(proyecto, fisica)}


def estado_guardado(proyecto, fisica=False):
    """Lo que se ve al abrir: las vigencias y metas de lo guardado en la pestana; en la
    financiera, ademas, sus entidades y las fuentes de cada una. Sin nada, el anio en curso como
    vigencia nueva."""
    estado = {}
    if fisica:
        filas = ((v, None, None, m) for v, m in proyecto.programacion_fisica.values_list("vigencia", "meta_id"))
    else:
        filas = ((v, e or SIN_ENTIDAD, f, m) for v, e, f, m in proyecto.programacion_financiera.values_list(
            "vigencia", "entidad_aportante_id", "fuente_id", "meta_id"))
    for v, e, f, m in filas:
        bloque = estado.setdefault(v, _bloque_vacio())
        if f is not None:
            if e not in bloque["entidades"]:
                bloque["entidades"].append(e)
            fuentes = bloque["fuentes"].setdefault(e, [])
            if f not in fuentes:
                fuentes.append(f)
        if m not in bloque["metas"]:
            bloque["metas"].append(m)
    return estado or {timezone.localdate().year: _bloque_nuevo(proyecto, fisica)}


def estado_de(datos):
    """Lo que se ve, leido del formulario (campos ocultos)."""
    estado = {}
    for v in _ids(datos.getlist("vigencias"), set(vigencias_validas())):
        entidades = _ids(datos.getlist(f"entidades-{v}"))
        estado[v] = {"entidades": entidades,
                     "fuentes": {e: _ids(datos.getlist(f"fuentes-{v}-{e}")) for e in entidades},
                     "metas": _ids(datos.getlist(f"metas-{v}"))}
    return estado


def _agregar_o_quitar(lista, datos, tipo, agregar=True):
    for x in _ids([datos.get(f"agregar_{tipo}")]) if agregar else ():
        if x not in lista:
            lista.append(x)
    for x in _ids([datos.get(f"quitar_{tipo}")]):
        if x in lista:
            lista.remove(x)


def cambiar_estado(estado, datos, proyecto=None, fisica=False, digitados=None):
    """Aplica lo que pide el boton: agregar o quitar una vigencia; en una vigencia (`en`), una
    entidad aportante, una meta o una fuente de una entidad (`entidad`); o asignar la entidad a lo
    que no la tiene.

    Al agregar una vigencia trae las metas que la otra pestana tiene guardadas, en cualquier
    vigencia (si se da el proyecto). Al asignar la entidad, lo digitado sin entidad pasa a ella
    (si se dan los `digitados`, que se cambian en el sitio)."""
    for v in _ids([datos.get("agregar_vigencia")], set(vigencias_validas())):
        if v not in estado:
            estado[v] = _bloque_nuevo(proyecto, fisica) if proyecto is not None else _bloque_vacio()
    for v in _ids([datos.get("quitar_vigencia")]):
        estado.pop(v, None)
    en = _ids([datos.get("en")])
    if not (en and en[0] in estado):
        return estado
    v, bloque = en[0], estado[en[0]]
    _agregar_o_quitar(bloque["metas"], datos, "meta")
    for e in _ids([datos.get("agregar_entidad")]):
        if e != SIN_ENTIDAD and e not in bloque["entidades"]:
            bloque["entidades"].append(e)
            bloque["fuentes"].setdefault(e, [])
    for e in _ids([datos.get("quitar_entidad")]):
        if e in bloque["entidades"]:
            bloque["entidades"].remove(e)
            bloque["fuentes"].pop(e, None)
    for e in _ids([datos.get("asignar_entidad")]):
        if e != SIN_ENTIDAD and SIN_ENTIDAD in bloque["entidades"] and e not in bloque["entidades"]:
            bloque["entidades"][bloque["entidades"].index(SIN_ENTIDAD)] = e
            bloque["fuentes"][e] = bloque["fuentes"].pop(SIN_ENTIDAD, [])
            for clave in [c for c in (digitados or {}) if len(c) == 4 and c[0] == v and c[1] == SIN_ENTIDAD]:
                digitados[(v, e, clave[2], clave[3])] = digitados.pop(clave)
    entidad = _ids([datos.get("entidad")])
    if entidad and entidad[0] in bloque["entidades"]:
        # a lo que no tiene entidad no se le agregan fuentes: solo se le quitan
        _agregar_o_quitar(bloque["fuentes"].setdefault(entidad[0], []), datos, "fuente",
                          agregar=entidad[0] != SIN_ENTIDAD)
    return estado


def digitados_de(datos):
    """Las casillas del formulario: {(vigencia, entidad, fuente, meta): texto} en la financiera
    (v-<vig>-<entidad>-<fuente>-<meta>) y {(vigencia, meta): texto} en la fisica (v-<vig>-<meta>)."""
    digitados = {}
    for clave in datos:
        partes = clave.split("-")
        if len(partes) in (3, 5) and partes[0] == "v" and all(p.isdigit() for p in partes[1:]):
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
    """{"sin_fisica": [metas], "sin_financiera": [metas]} de lo guardado: metas con valor
    financiero y sin valor fisico en ninguna vigencia, y al reves. Vacio si coinciden."""
    fin, fis = metas_guardadas(proyecto, False), metas_guardadas(proyecto, True)
    if fin == fis:
        return {}
    codigos = dict(MetaIndicador.objects.filter(pk__in=fin ^ fis).values_list("pk", "codigo"))
    return {"sin_fisica": sorted(codigos[m] for m in fin - fis),
            "sin_financiera": sorted(codigos[m] for m in fis - fin)}


def mensaje_descuadre(proyecto):
    """El mensaje de advertencia cuando las metas de las dos pestanas no coinciden, o vacio."""
    d = descuadres(proyecto)
    if not d:
        return ""
    detalle = []
    if d["sin_fisica"]:
        detalle.append("sin valor físico " + ", ".join(d["sin_fisica"]))
    if d["sin_financiera"]:
        detalle.append("sin valor financiero " + ", ".join(d["sin_financiera"]))
    return ("Las metas de la programación financiera y la física no coinciden en ninguna vigencia: "
            + "; ".join(detalle) + ". Complete la otra pestaña o corrija esta.")


def _comun(bloques, guardados, visibles, errores, proyecto):
    """Lo que las dos pestanas devuelven igual: aviso de coincidencia y pendientes."""
    por_borrar = [clave for clave in guardados if clave not in visibles]
    return {"bloques": bloques, "por_borrar": len(por_borrar), "errores": len(errores),
            "descuadre": descuadres(proyecto)}


# ---------------------------------------------------------------------------
# La pestana financiera
# ---------------------------------------------------------------------------

def _fuentes_del_estado(estado):
    return {x for b in estado.values() for fuentes in b["fuentes"].values() for x in fuentes}


def matriz(proyecto, estado=None, digitados=None, errores=None):
    """Un bloque por vigencia con sus entidades aportantes, las fuentes de cada una (filas), sus
    metas (columnas), los valores y totales.

    Sin estado (al abrir) sale de lo guardado. Con estado (al agregar, quitar o guardar con
    errores) se muestra exactamente ese, con lo digitado en `digitados`; una casilla cuyo texto no
    coincide con lo guardado queda como cambio pendiente. Los totales suman lo que se ve. Lo que no
    tiene entidad va primero, para asignarsela.
    """
    estado = estado_guardado(proyecto) if estado is None else estado
    guardados = {(r.vigencia, r.entidad_aportante_id or SIN_ENTIDAD, r.fuente_id, r.meta_id): r.valor
                 for r in proyecto.programacion_financiera.all()}
    todas_entidades = {e.pk: e for e in EntidadAportante.objects.filter(
        pk__in={x for b in estado.values() for x in b["entidades"]})}
    todas_fuentes = {f.pk: f for f in Fuente.objects.filter(pk__in=_fuentes_del_estado(estado))}
    todas_metas = {m.pk: m for m in MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})}
    digitados, errores = digitados or {}, errores or {}

    bloques, visibles = [], set()
    for v in sorted(estado):
        metas = sorted((todas_metas[x] for x in estado[v]["metas"] if x in todas_metas), key=lambda m: m.codigo)
        programadas = metas_programadas(proyecto, v)
        entidades = sorted((e for e in estado[v]["entidades"] if e == SIN_ENTIDAD or e in todas_entidades),
                           key=lambda e: (e != SIN_ENTIDAD, todas_entidades[e].nombre if e in todas_entidades else ""))
        grupos, por_meta = [], {m.pk: CERO for m in metas}
        for e in entidades:
            fuentes = sorted((todas_fuentes[x] for x in estado[v]["fuentes"].get(e, []) if x in todas_fuentes),
                             key=lambda f: f.codigo)
            filas, total_grupo = [], CERO
            for f in fuentes:
                celdas, total_fila = [], CERO
                for m in metas:
                    clave = (v, e, f.pk, m.pk)
                    visibles.add(clave)
                    guardado = guardados.get(clave)
                    texto = digitados[clave] if clave in digitados else en_casilla(guardado)
                    leido = _leer_o_none(texto)
                    celdas.append({"meta": m, "texto": texto, "nombre": f"v-{v}-{e}-{f.pk}-{m.pk}", "con": bool(leido),
                                   "cambio": leido is None or leido != (guardado or CERO),
                                   "error": errores.get(clave, "")})
                    por_meta[m.pk] += leido or CERO
                    total_fila += leido or CERO
                filas.append({"fuente": f, "celdas": celdas, "total": total_fila})
                total_grupo += total_fila
            grupos.append({"id": e, "entidad": todas_entidades.get(e), "filas": filas,
                           "fuentes": [f.pk for f in fuentes], "total": total_grupo})
        bloques.append({
            "vigencia": v, "grupos": grupos, "metas": [m.pk for m in metas],
            "columnas": [{"meta": m, "total": por_meta[m.pk], "programada": m.pk in programadas} for m in metas],
            "total": sum(por_meta.values(), CERO),
            "sin_entidad": any(g["id"] == SIN_ENTIDAD for g in grupos),
        })

    comun = _comun(bloques, _sin_lo_asignado(guardados, visibles), visibles, errores, proyecto)
    por_vigencia = list(proyecto.programacion_financiera.values("vigencia").annotate(t=Sum("valor")).order_by("vigencia"))
    return {
        **comun, "total": sum((b["total"] for b in bloques), CERO),
        "pendiente": bool(comun["por_borrar"])
                     or any(c["cambio"] for b in bloques for g in b["grupos"] for f in g["filas"] for c in f["celdas"]),
        "sin_entidad": [b["vigencia"] for b in bloques if b["sin_entidad"]],
        "por_vigencia": [(p["vigencia"], p["t"]) for p in por_vigencia],
        "total_proyecto": proyecto.valor_programado,
    }


def _sin_lo_asignado(guardados, visibles):
    """Lo guardado, sin los valores sin entidad que ya se ven con una (asignada y aun sin
    guardar): esos no cuentan como valores que se van a borrar."""
    con_entidad = {(v, f, m) for v, e, f, m in visibles if e != SIN_ENTIDAD}
    return {clave: valor for clave, valor in guardados.items()
            if not (clave[1] == SIN_ENTIDAD and (clave[0], clave[2], clave[3]) in con_entidad)}


def guardar(proyecto, estado, digitados):
    """Deja la programacion financiera como se ve. Devuelve ({casilla: error}, mensaje).

    Con algun error no cambia nada. Si no: crea o cambia los valores y borra los vacios o en cero
    y lo que ya no esta en la pantalla. Un valor sin entidad aportante es un error: hay que
    asignarsela (vaciarlo si lo borra). La fisica no se toca.
    """
    entidades_validas = set(EntidadAportante.objects.filter(
        pk__in={x for b in estado.values() for x in b["entidades"]}).values_list("pk", flat=True)) | {SIN_ENTIDAD}
    fuentes_validas = set(Fuente.objects.filter(pk__in=_fuentes_del_estado(estado)).values_list("pk", flat=True))
    metas_validas = set(MetaIndicador.objects.filter(pk__in={x for b in estado.values() for x in b["metas"]})
                        .values_list("pk", flat=True))
    valores, errores = {}, {}
    for v, bloque in estado.items():
        for e in (e for e in bloque["entidades"] if e in entidades_validas):
            for f in bloque["fuentes"].get(e, []):
                for m in bloque["metas"]:
                    if f in fuentes_validas and m in metas_validas:
                        clave = (v, e, f, m)
                        try:
                            valor = leer_valor(digitados.get(clave, ""))
                        except ValueError as error:
                            errores[clave] = str(error)
                            continue
                        if valor and e == SIN_ENTIDAD:
                            errores[clave] = "Asigne la entidad aportante antes de guardar."
                        else:
                            valores[clave] = valor
    if errores:
        return errores, ""

    with transaction.atomic():
        cuentas = _sincronizar(list(proyecto.programacion_financiera.all()), valores,
                               lambda r: (r.vigencia, r.entidad_aportante_id or SIN_ENTIDAD, r.fuente_id, r.meta_id),
                               lambda clave, valor: ProgramacionFinanciera.objects.create(
                                   proyecto=proyecto, vigencia=clave[0], entidad_aportante_id=clave[1],
                                   fuente_id=clave[2], meta_id=clave[3], valor=valor))
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
    """Una pagina del listado de vigencias, entidades aportantes, fuentes o metas que coinciden con
    el texto, sin las que ya estan. En metas, las `programadas` van primero y marcadas.
    Devuelve {"lista": [(id, codigo, nombre, programada)], "pagina", "paginas", "total", "desde", "hasta"}."""
    texto = (texto or "").strip()
    presentes = _ids(excluir)
    programadas = set(programadas)
    if tipo == "vigencia":
        todas = [(v, str(v), "", False) for v in reversed(vigencias_validas()) if v not in presentes and texto in str(v)]
    elif tipo == "entidad":
        consulta = EntidadAportante.objects.exclude(pk__in=presentes).order_by("nombre")
        if texto:
            consulta = consulta.filter(Q(nombre__icontains=texto) | Q(nit__icontains=texto))
        todas = consulta
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
    if tipo == "entidad":
        lista = [(e.pk, e.nit, e.nombre, False) for e in tramo]
    elif tipo == "fuente":
        lista = [(f.pk, f.codigo, f.nombre, False) for f in tramo]
    elif tipo == "meta":
        lista = [(m.pk, m.codigo, m.descripcion, m.pk in programadas) for m in tramo]
    else:
        lista = list(tramo)
    return {"lista": lista, "pagina": pagina, "paginas": paginas, "total": total,
            "desde": (pagina - 1) * POR_PAGINA + 1 if total else 0, "hasta": (pagina - 1) * POR_PAGINA + len(lista)}
