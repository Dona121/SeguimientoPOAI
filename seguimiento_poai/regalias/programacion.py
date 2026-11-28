"""Programacion de un proyecto de regalias por vigencia: financiera y fisica.

Copia adaptada de siifweb/programacion_financiera.py (que no se modifica). Las dos son pestanas
de la misma pantalla (ProyectoRegaliasAdmin.programacion, ?panel=fisica):

- Financiera: un bloque por vigencia con sus entidades aportantes (catalogo de SIIFWEB), las
  fuentes SGR de cada una (filas) y sus productos del catalogo PIIP (columnas), y el valor en
  cada cruce. Lo programado antes de que existiera la entidad (27/11/2026) sale como "Sin
  entidad aportante", con un boton para asignarla, y mientras tenga valor la pestana no se
  guarda.
- Fisica: un bloque por vigencia con sus indicadores del catalogo PIIP y un valor por indicador
  (sin totales: cada indicador tiene su unidad).

Como en SIIFWEB, digitar, agregar o quitar no toca la base: lo que se ve viaja en la pagina
(campos ocultos "vigencias", "entidades-<v>", "fuentes-<v>-<entidad>", "productos-<v>",
"indicadores-<v>" y una casilla por cruce: v-<vigencia>-<entidad>-<fuente>-<producto> en la
financiera, v-<vigencia>-<indicador> en la fisica).
Guardar deja la pestana como se ve: crea o cambia los valores y borra los vacios o en cero.
Con una casilla con error no se guarda nada.

Lo que cambia de SIIFWEB, porque aqui las pestanas no comparten la misma dimension:
- Las vigencias de las dos pestanas no tienen que coincidir: un proyecto puede tener fuentes en
  2025 y 2027 y la meta fisica en 2026 (decision del usuario, 27/11/2026). Cada pestana muestra
  solo sus vigencias, y la relacion entre las dos es por producto, en todo el proyecto.
- Espejo: una vigencia nueva de la financiera empieza con los productos de los indicadores que
  tiene la fisica (en cualquier vigencia); se pueden quitar. Al agregar un producto o un
  indicador salen primero (marcados) los que tiene la otra pestana.
- Aviso de descuadre (no bloquea): productos con valor financiero sin ningun indicador con
  valor fisico, e indicadores con valor fisico cuyo producto no tiene valor financiero, en
  ninguna vigencia.

Despues de guardar, el admin recalcula el proyecto (fuentes, valores, indicador MGA) con
servicios.guardar_proyecto, que deja el cambio en el historial con el usuario.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import timezone

from siifweb.models import EntidadAportante, IndicadorCatalogo, ProductoCatalogo
from siifweb.programacion_financiera import en_casilla, leer_valor, vigencias_validas

from .models import FuenteSGR, ProgramacionFinancieraRegalias, ProgramacionFisicaRegalias

CERO = Decimal(0)
POR_PAGINA = 50
PLURAL = {"entidad": "entidades", "fuente": "fuentes", "producto": "productos", "indicador": "indicadores"}
SIN_ENTIDAD = 0            # la entidad de lo programado antes de que existiera el campo


def _leer_o_none(texto):
    try:
        return leer_valor(texto)
    except ValueError:
        return None


def _ids(valores, validos=None):
    """Enteros sin repetir, en el orden en que llegan (y solo los validos, si se dicen)."""
    vistos = []
    for v in valores or ():
        if str(v).isdigit() and int(v) not in vistos and (validos is None or int(v) in validos):
            vistos.append(int(v))
    return vistos


def _bloque_vacio(fisica):
    return {"indicadores": []} if fisica else {"entidades": [], "fuentes": {}, "productos": []}


# ---------------------------------------------------------------------------
# Lo guardado
# ---------------------------------------------------------------------------

def productos_financieros(proyecto):
    """Los productos con valor financiero, en cualquier vigencia."""
    return set(proyecto.programacion_financiera.values_list("producto_id", flat=True))


def productos_de_la_fisica(proyecto):
    """Los productos de los indicadores con valor fisico, en cualquier vigencia."""
    return set(proyecto.programacion_fisica.values_list("indicador__producto_id", flat=True))


def marcadas(proyecto, tipo):
    """Lo que la ventana de agregar muestra primero y marcado, por lo que tiene la otra pestana."""
    if tipo == "producto":
        return productos_de_la_fisica(proyecto)
    if tipo == "indicador":
        return set(IndicadorCatalogo.objects.filter(producto_id__in=productos_financieros(proyecto))
                   .values_list("pk", flat=True))
    return set()


def _bloque_nuevo(proyecto, fisica):
    """Una vigencia nueva. En la financiera empieza con los productos de la fisica."""
    bloque = _bloque_vacio(fisica)
    if not fisica:
        bloque["productos"] = sorted(productos_de_la_fisica(proyecto))
    return bloque


def estado_guardado(proyecto, fisica=False):
    """Lo que se ve al abrir: lo guardado en la pestana, con sus propias vigencias. Sin nada, el
    anio en curso como vigencia nueva."""
    estado = {}
    if fisica:
        for v, i in proyecto.programacion_fisica.values_list("vigencia", "indicador_id"):
            bloque = estado.setdefault(v, _bloque_vacio(True))
            if i not in bloque["indicadores"]:
                bloque["indicadores"].append(i)
    else:
        for v, e, f, p in proyecto.programacion_financiera.values_list("vigencia", "entidad_aportante_id", "fuente_id",
                                                                          "producto_id"):
            e = e or SIN_ENTIDAD
            bloque = estado.setdefault(v, _bloque_vacio(False))
            if e not in bloque["entidades"]:
                bloque["entidades"].append(e)
            fuentes = bloque["fuentes"].setdefault(e, [])
            if f not in fuentes:
                fuentes.append(f)
            if p not in bloque["productos"]:
                bloque["productos"].append(p)
    return estado or {timezone.localdate().year: _bloque_nuevo(proyecto, fisica)}


def estado_de(datos, fisica=False):
    """Lo que se ve, leido del formulario (campos ocultos)."""
    validas = set(vigencias_validas())
    vigencias = _ids(datos.getlist("vigencias"), validas)
    if fisica:
        return {v: {"indicadores": _ids(datos.getlist(f"indicadores-{v}"))} for v in vigencias}
    estado = {}
    for v in vigencias:
        entidades = _ids(datos.getlist(f"entidades-{v}"))
        estado[v] = {"entidades": entidades,
                     "fuentes": {e: _ids(datos.getlist(f"fuentes-{v}-{e}")) for e in entidades},
                     "productos": _ids(datos.getlist(f"productos-{v}"))}
    return estado


def _agregar_o_quitar(lista, datos, tipo, agregar=True):
    for x in _ids([datos.get(f"agregar_{tipo}")]) if agregar else ():
        if x not in lista:
            lista.append(x)
    for x in _ids([datos.get(f"quitar_{tipo}")]):
        if x in lista:
            lista.remove(x)


def cambiar_estado(estado, datos, proyecto=None, fisica=False, digitados=None):
    """Aplica lo que pide el boton: agregar o quitar una vigencia; en una vigencia (`en`), un
    indicador, o en la financiera una entidad aportante, un producto o una fuente de una entidad
    (`entidad`); o asignar la entidad a lo que no la tiene.

    Al agregar una vigencia en la financiera trae los productos de la fisica, de cualquier
    vigencia (si se da el proyecto). Al asignar la entidad, lo digitado sin entidad pasa a ella
    (si se dan los `digitados`, que se cambian en el sitio)."""
    for v in _ids([datos.get("agregar_vigencia")], set(vigencias_validas())):
        if v not in estado:
            estado[v] = _bloque_nuevo(proyecto, fisica) if proyecto is not None else _bloque_vacio(fisica)
    for v in _ids([datos.get("quitar_vigencia")]):
        estado.pop(v, None)
    en = _ids([datos.get("en")])
    if not (en and en[0] in estado):
        return estado
    v, bloque = en[0], estado[en[0]]
    if fisica:
        _agregar_o_quitar(bloque["indicadores"], datos, "indicador")
        return estado
    _agregar_o_quitar(bloque["productos"], datos, "producto")
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
    """Las casillas: {(vigencia, entidad, fuente, producto): texto} en la financiera y {(vigencia,
    indicador): texto} en la fisica."""
    digitados = {}
    for clave in datos:
        partes = clave.split("-")
        if len(partes) in (3, 5) and partes[0] == "v" and all(p.isdigit() for p in partes[1:]):
            digitados[tuple(int(p) for p in partes[1:])] = datos.get(clave, "")
    return digitados


# ---------------------------------------------------------------------------
# Coincidencia entre las dos pestanas
# ---------------------------------------------------------------------------

def descuadres(proyecto):
    """{"sin_fisica": [productos], "sin_financiera": [indicadores]} de lo guardado, en todo el
    proyecto y sin mirar la vigencia; vacio si las dos pestanas coinciden."""
    financieros = productos_financieros(proyecto)
    fisicas = set(proyecto.programacion_fisica.values_list("indicador_id", "indicador__producto_id"))
    con_fisica = {p for _, p in fisicas}
    sin_fisica = sorted(ProductoCatalogo.objects.filter(pk__in=financieros - con_fisica).values_list("codigo", flat=True))
    sin_financiera = sorted(IndicadorCatalogo.objects.filter(pk__in={i for i, p in fisicas if p not in financieros})
                            .values_list("codigo", flat=True))
    if not (sin_fisica or sin_financiera):
        return {}
    return {"sin_fisica": sin_fisica, "sin_financiera": sin_financiera}


def mensaje_descuadre(proyecto):
    """La advertencia al guardar cuando las dos pestanas no coinciden, o vacio."""
    d = descuadres(proyecto)
    if not d:
        return ""
    detalle = []
    if d["sin_fisica"]:
        detalle.append("productos sin indicador en la física " + ", ".join(d["sin_fisica"]))
    if d["sin_financiera"]:
        detalle.append("indicadores sin valor financiero de su producto " + ", ".join(d["sin_financiera"]))
    return ("La programación financiera y la física no coinciden en ninguna vigencia: " + "; ".join(detalle)
            + ". Complete la otra pestaña o corrija esta.")


def _comun(bloques, guardados, visibles, errores, proyecto):
    por_borrar = [clave for clave in guardados if clave not in visibles]
    return {"bloques": bloques, "por_borrar": len(por_borrar), "errores": len(errores),
            "descuadre": descuadres(proyecto)}


# ---------------------------------------------------------------------------
# La pestana financiera
# ---------------------------------------------------------------------------

def _fuentes_del_estado(estado):
    return {x for b in estado.values() for fuentes in b["fuentes"].values() for x in fuentes}


def _sin_lo_asignado(guardados, visibles):
    """Lo guardado, sin los valores sin entidad que ya se ven con una (asignada y aun sin
    guardar): esos no cuentan como valores que se van a borrar."""
    con_entidad = {(v, f, p) for v, e, f, p in visibles if e != SIN_ENTIDAD}
    return {clave: valor for clave, valor in guardados.items()
            if not (clave[1] == SIN_ENTIDAD and (clave[0], clave[2], clave[3]) in con_entidad)}


def matriz(proyecto, estado=None, digitados=None, errores=None):
    """Un bloque por vigencia con sus entidades aportantes, las fuentes de cada una (filas), sus
    productos (columnas), los valores y totales. Como en SIIFWEB: sin estado sale de lo guardado;
    con estado se muestra ese, con lo digitado; una casilla que no coincide con lo guardado queda
    como cambio pendiente. Lo que no tiene entidad va primero, para asignarsela."""
    estado = estado_guardado(proyecto) if estado is None else estado
    guardados = {(r.vigencia, r.entidad_aportante_id or SIN_ENTIDAD, r.fuente_id, r.producto_id): r.valor
                 for r in proyecto.programacion_financiera.all()}
    entidades_por_id = {e.pk: e for e in EntidadAportante.objects.filter(
        pk__in={x for b in estado.values() for x in b["entidades"]})}
    fuentes_por_id = {f.pk: f for f in FuenteSGR.objects.filter(pk__in=_fuentes_del_estado(estado))}
    productos_por_id = {p.pk: p for p in ProductoCatalogo.objects.filter(
        pk__in={x for b in estado.values() for x in b["productos"]})}
    de_la_fisica = productos_de_la_fisica(proyecto)
    digitados, errores = digitados or {}, errores or {}

    bloques, visibles = [], set()
    for v in sorted(estado):
        productos = sorted((productos_por_id[x] for x in estado[v]["productos"] if x in productos_por_id),
                           key=lambda p: p.codigo)
        entidades = sorted((e for e in estado[v]["entidades"] if e == SIN_ENTIDAD or e in entidades_por_id),
                           key=lambda e: (e != SIN_ENTIDAD, entidades_por_id[e].nombre if e in entidades_por_id else ""))
        grupos, por_producto = [], {p.pk: CERO for p in productos}
        for e in entidades:
            fuentes = sorted((fuentes_por_id[x] for x in estado[v]["fuentes"].get(e, []) if x in fuentes_por_id),
                             key=lambda f: f.nombre)
            filas, total_grupo = [], CERO
            for f in fuentes:
                celdas, total_fila = [], CERO
                for p in productos:
                    clave = (v, e, f.pk, p.pk)
                    visibles.add(clave)
                    guardado = guardados.get(clave)
                    texto = digitados[clave] if clave in digitados else en_casilla(guardado)
                    leido = _leer_o_none(texto)
                    celdas.append({"producto": p, "texto": texto, "nombre": f"v-{v}-{e}-{f.pk}-{p.pk}",
                                   "con": bool(leido), "cambio": leido is None or leido != (guardado or CERO),
                                   "error": errores.get(clave, "")})
                    por_producto[p.pk] += leido or CERO
                    total_fila += leido or CERO
                filas.append({"fuente": f, "celdas": celdas, "total": total_fila})
                total_grupo += total_fila
            grupos.append({"id": e, "entidad": entidades_por_id.get(e), "filas": filas,
                           "fuentes": [f.pk for f in fuentes], "total": total_grupo})
        bloques.append({
            "vigencia": v, "grupos": grupos, "productos": [p.pk for p in productos],
            "columnas": [{"producto": p, "total": por_producto[p.pk], "en_fisica": p.pk in de_la_fisica}
                         for p in productos],
            "total": sum(por_producto.values(), CERO),
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
        "total_proyecto": sum((p["t"] for p in por_vigencia), CERO),
    }


def guardar(proyecto, estado, digitados):
    """Deja la programacion financiera como se ve. Devuelve ({casilla: error}, mensaje). Con algun
    error no cambia nada. Un valor sin entidad aportante es un error: hay que asignarsela
    (vaciarlo si lo borra). La fisica no se toca."""
    entidades_validas = set(EntidadAportante.objects.filter(
        pk__in={x for b in estado.values() for x in b["entidades"]}).values_list("pk", flat=True)) | {SIN_ENTIDAD}
    fuentes_validas = set(FuenteSGR.objects.filter(pk__in=_fuentes_del_estado(estado)).values_list("pk", flat=True))
    productos_validos = set(ProductoCatalogo.objects.filter(pk__in={x for b in estado.values() for x in b["productos"]})
                            .values_list("pk", flat=True))
    valores, errores = {}, {}
    for v, bloque in estado.items():
        for e in (e for e in bloque["entidades"] if e in entidades_validas):
            for f in bloque["fuentes"].get(e, []):
                for p in bloque["productos"]:
                    if f in fuentes_validas and p in productos_validos:
                        clave = (v, e, f, p)
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
                               lambda r: (r.vigencia, r.entidad_aportante_id or SIN_ENTIDAD, r.fuente_id, r.producto_id),
                               lambda clave, valor: ProgramacionFinancieraRegalias.objects.create(
                                   proyecto=proyecto, vigencia=clave[0], entidad_aportante_id=clave[1],
                                   fuente_id=clave[2], producto_id=clave[3], valor=valor))
    return {}, _mensaje(*cuentas)


# ---------------------------------------------------------------------------
# La pestana fisica
# ---------------------------------------------------------------------------

def matriz_fisica(proyecto, estado=None, digitados=None, errores=None):
    """Un bloque por vigencia con una fila por indicador, su unidad y su valor."""
    estado = estado_guardado(proyecto, fisica=True) if estado is None else estado
    guardados = {(r.vigencia, r.indicador_id): r.valor for r in proyecto.programacion_fisica.all()}
    todos = {i.pk: i for i in IndicadorCatalogo.objects.filter(
        pk__in={x for b in estado.values() for x in b["indicadores"]}).select_related("producto", "unidad_medida")}
    financieros = productos_financieros(proyecto)
    digitados, errores = digitados or {}, errores or {}
    bloques, visibles = [], set()
    for v in sorted(estado):
        filas = []
        for i in sorted((todos[x] for x in estado[v]["indicadores"] if x in todos), key=lambda i: i.codigo):
            clave = (v, i.pk)
            visibles.add(clave)
            guardado = guardados.get(clave)
            texto = digitados[clave] if clave in digitados else en_casilla(guardado)
            leido = _leer_o_none(texto)
            filas.append({"indicador": i, "texto": texto, "nombre": f"v-{v}-{i.pk}", "con": bool(leido),
                          "cambio": leido is None or leido != (guardado or CERO), "error": errores.get(clave, ""),
                          "del_producto": i.producto_id in financieros})
        bloques.append({"vigencia": v, "filas": filas, "indicadores": [f["indicador"].pk for f in filas]})
    comun = _comun(bloques, guardados, visibles, errores, proyecto)
    return {**comun, "pendiente": bool(comun["por_borrar"]) or any(f["cambio"] for b in bloques for f in b["filas"])}


def guardar_fisica(proyecto, estado, digitados):
    """Deja la programacion fisica como se ve. Devuelve ({casilla: error}, mensaje)."""
    validos = set(IndicadorCatalogo.objects.filter(pk__in={x for b in estado.values() for x in b["indicadores"]})
                  .values_list("pk", flat=True))
    valores, errores = {}, {}
    for v, bloque in estado.items():
        for i in bloque["indicadores"]:
            if i in validos:
                try:
                    valores[(v, i)] = leer_valor(digitados.get((v, i), ""))
                except ValueError as e:
                    errores[(v, i)] = str(e)
    if errores:
        return errores, ""
    with transaction.atomic():
        cuentas = _sincronizar(list(proyecto.programacion_fisica.all()), valores, lambda r: (r.vigencia, r.indicador_id),
                               lambda clave, valor: ProgramacionFisicaRegalias.objects.create(
                                   proyecto=proyecto, vigencia=clave[0], indicador_id=clave[1], valor=valor))
    return {}, _mensaje(*cuentas)


def _sincronizar(registros, valores, clave_de, crear):
    """Deja los registros como dicen los valores. Devuelve (creados, cambiados, borrados)."""
    valores = dict(valores)
    creados = cambiados = borrados = 0
    for r in registros:
        nuevo = valores.pop(clave_de(r), CERO)
        if not nuevo:
            r.delete()
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

def opciones(tipo, texto="", excluir=(), pagina=1, marcados=()):
    """Una pagina del listado de vigencias, entidades, fuentes, productos o indicadores que coinciden con el
    texto, sin los que ya estan. Los `marcados` (por la otra pestana) van primero.
    Devuelve {"lista": [(id, codigo, nombre, marcado)], "pagina", "paginas", "total", "desde", "hasta"}."""
    texto = (texto or "").strip()
    presentes = _ids(excluir)
    marcados = set(marcados)
    primero = Case(When(pk__in=marcados, then=Value(0)), default=Value(1), output_field=IntegerField())
    if tipo == "vigencia":
        todas = [(v, str(v), "", False) for v in reversed(vigencias_validas()) if v not in presentes and texto in str(v)]
    elif tipo == "fuente":
        todas = FuenteSGR.objects.exclude(pk__in=presentes).order_by("nombre")
        if texto:
            todas = todas.filter(nombre__icontains=texto)
    elif tipo == "entidad":
        todas = EntidadAportante.objects.exclude(pk__in=presentes).order_by("nombre")
        if texto:
            todas = todas.filter(Q(nombre__icontains=texto) | Q(nit__icontains=texto))
    elif tipo == "producto":
        todas = ProductoCatalogo.objects.exclude(pk__in=presentes)
        if texto:
            todas = todas.filter(Q(codigo__icontains=texto) | Q(nombre__icontains=texto))
        todas = todas.annotate(orden=primero).order_by("orden", "codigo")
    else:
        todas = IndicadorCatalogo.objects.exclude(pk__in=presentes).select_related("producto")
        if texto:
            todas = todas.filter(Q(codigo__icontains=texto) | Q(nombre__icontains=texto)
                                 | Q(producto__codigo__icontains=texto))
        todas = todas.annotate(orden=primero).order_by("orden", "codigo")
    total = len(todas) if isinstance(todas, list) else todas.count()
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(int(pagina) if str(pagina).isdigit() else 1, 1), paginas)
    tramo = todas[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
    if tipo == "fuente":
        lista = [(f.pk, f.get_clasificacion_display(), f.nombre, False) for f in tramo]
    elif tipo == "entidad":
        lista = [(x.pk, x.nit, x.nombre, False) for x in tramo]
    elif tipo in ("producto", "indicador"):
        lista = [(x.pk, x.codigo, x.nombre, x.pk in marcados) for x in tramo]
    else:
        lista = list(tramo)
    return {"lista": lista, "pagina": pagina, "paginas": paginas, "total": total,
            "desde": (pagina - 1) * POR_PAGINA + 1 if total else 0, "hasta": (pagina - 1) * POR_PAGINA + len(lista)}
