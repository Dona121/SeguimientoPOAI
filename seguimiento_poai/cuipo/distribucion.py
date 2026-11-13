"""Precarga de la distribucion por BPIN (fase 3 del CUIPO).

Para cada BPIN con filas en el corte se crea una DistribucionBPIN con sus productos (los de la
formulacion PIIP que esten en la lista CHIP) y se aplica la regla del Power Query:

- un producto: el 100 % de cada fila va a ese producto (valores de SIIFWEB);
- varios productos y un solo recurso: la matriz queda vacia, para digitar los valores por
  producto desde el reporte de AporteProductos del PIIP;
- varios productos y varios recursos: manual;
- sin BPIN (proyecto 0): el 100 % al producto 0 - NO APLICA;
- sin productos en la lista CHIP: no se puede distribuir; queda con su observacion.

Las lineas nuevas llevan vigencia de gasto 1 (se cambia en la distribucion) y sus
cualitativos: tercero por regla, CPC 0 si el concepto no lo exige, detalle sectorial y politica
publica 0; si el mismo BPIN se envio en un periodo anterior de la vigencia, CPC, detalle y
politica se toman de esa linea (origen "antecedente"). Una distribucion que ya existe no se
toca.
"""
from collections import Counter, defaultdict
from decimal import ROUND_DOWN, Decimal

from django.db import transaction

from siifweb.models import ProductoCatalogo

from .derivacion import Derivador, filas_cuipo
from .models import (CPC, AsociacionFuenteProducto, DetalleSectorial, DistribucionBPIN, LineaCUIPO,
                     PoliticaPublica, ProductoCUIPO, VigenciaGasto, periodo_de)

VIGENCIA_POR_DEFECTO = "1"
PRODUCTO_SIN_BPIN = "0"
CPC_NO_APLICA = "0"
DETALLE_NO_APLICA = "0"
POLITICA_NO_APLICA = "0"


def productos_piip(bpines):
    """{bpin: [codigos de producto]} de la formulacion PIIP."""
    productos = defaultdict(list)
    filas = (ProductoCatalogo.objects.filter(indicadores__en_proyectos__formulacion__bpin__in=list(bpines))
             .values_list("indicadores__en_proyectos__formulacion__bpin", "codigo").distinct().order_by("codigo"))
    for bpin, codigo in filas:
        productos[bpin].append(codigo)
    return productos


class Cualitativos:
    """Los valores por defecto y los antecedentes de un corte, para armar lineas."""

    def __init__(self, corte):
        self.derivador = Derivador(corte.vigencia)
        self.vigencia = VigenciaGasto.objects.filter(codigo=VIGENCIA_POR_DEFECTO).first()
        self.cpc = CPC.objects.filter(codigo=CPC_NO_APLICA).first()
        self.detalle = DetalleSectorial.objects.filter(codigo=DETALLE_NO_APLICA).first()
        self.politica = PoliticaPublica.objects.filter(codigo=POLITICA_NO_APLICA).first()
        # La ultima distribucion enviada de cada BPIN en un corte anterior de la vigencia
        self.antecedentes = {}
        enviadas = (LineaCUIPO.objects
                    .filter(distribucion__estado=DistribucionBPIN.Estado.ENVIADO, distribucion__corte__vigencia=corte.vigencia,
                            distribucion__corte__fecha_fin__lt=corte.fecha_fin)
                    .select_related("fila", "producto", "cpc", "detalle_sectorial", "politica_publica")
                    .order_by("distribucion__corte__fecha_fin"))
        for linea in enviadas:     # la mas reciente queda de ultima
            f = linea.fila
            self.antecedentes[(f.proyecto, f.rubro, f.recurso, f.centro_costo, linea.producto.codigo)] = linea

    def linea(self, distribucion, fila, producto, vigencia=None, compromisos=0, obligaciones=0, pagos=0,
              origen_valores=LineaCUIPO.OrigenValores.MANUAL):
        """Una LineaCUIPO sin guardar, con sus cualitativos."""
        Origen = LineaCUIPO.Origen
        d = self.derivador.derivar(fila)
        antes = self.antecedentes.get((fila.proyecto, fila.rubro, fila.recurso, fila.centro_costo, producto.codigo))
        linea = LineaCUIPO(distribucion=distribucion, fila=fila, producto=producto,
                           vigencia_gasto=vigencia or self.vigencia, compromisos=compromisos,
                           obligaciones=obligaciones, pagos=pagos, origen_valores=origen_valores)
        if d.tercero:
            linea.tercero, linea.origen_tercero = d.tercero, Origen.REGLA
        if antes and antes.cpc_id:
            linea.cpc, linea.origen_cpc = antes.cpc, Origen.ANTECEDENTE
        elif d.concepto and not d.concepto.requiere_cpc and self.cpc:
            linea.cpc, linea.origen_cpc = self.cpc, Origen.REGLA
        if antes and antes.detalle_sectorial_id:
            linea.detalle_sectorial, linea.origen_detalle_sectorial = antes.detalle_sectorial, Origen.ANTECEDENTE
        elif self.detalle:
            linea.detalle_sectorial, linea.origen_detalle_sectorial = self.detalle, Origen.REGLA
        if antes and antes.politica_publica_id:
            linea.politica_publica, linea.origen_politica_publica = antes.politica_publica, Origen.ANTECEDENTE
        elif self.politica:
            linea.politica_publica, linea.origen_politica_publica = self.politica, Origen.REGLA
        return linea


def regla_para(productos, filas):
    Regla = DistribucionBPIN.Regla
    if not productos:
        return Regla.SIN_PRODUCTOS
    if len(productos) == 1:
        return Regla.UN_PRODUCTO
    return Regla.PIIP if len({f.recurso for f in filas}) == 1 else Regla.MANUAL


@transaction.atomic
def precargar(corte, bpines=None):
    """Crea las distribuciones que falten en el corte. Devuelve el mensaje del resultado."""
    periodo = periodo_de(corte)
    if periodo is None:
        raise ValueError(f"{corte}: el corte debe ir del 1 de enero al cierre de un trimestre "
                         f"(31/03, 30/06, 30/09 o 31/12) para tener periodo CUIPO.")
    contexto = Cualitativos(corte)
    if contexto.vigencia is None:
        raise ValueError("Faltan las listas CHIP: no está la vigencia del gasto 1.")

    por_bpin = defaultdict(list)
    for fila in filas_cuipo(corte).order_by("rubro", "recurso", "centro_costo"):
        if bpines is None or fila.proyecto in bpines:
            por_bpin[fila.proyecto].append(fila)
    existentes = set(corte.distribuciones.values_list("bpin", flat=True))
    piip = productos_piip(b for b in por_bpin if b != "0")
    chip = {p.codigo: p for p in ProductoCUIPO.objects.filter(
        codigo__in={c for codigos in piip.values() for c in codigos} | {PRODUCTO_SIN_BPIN}, activo=True)}
    if "0" in por_bpin and PRODUCTO_SIN_BPIN not in chip:
        raise ValueError("Faltan las listas CHIP: no está el producto 0 - NO APLICA.")

    resumen, lineas, asociaciones = Counter(), [], []
    Regla = DistribucionBPIN.Regla
    for bpin, filas in sorted(por_bpin.items()):
        if bpin in existentes:
            resumen["ya estaban"] += 1
            continue
        observacion = ""
        if bpin == "0":
            productos, regla = [chip[PRODUCTO_SIN_BPIN]], Regla.SIN_BPIN
        else:
            codigos = piip.get(bpin, [])
            productos = [chip[c] for c in codigos if c in chip]
            faltan = [c for c in codigos if c not in chip]
            if not codigos:
                observacion = "El BPIN no tiene formulación PIIP."
            elif faltan:
                observacion = f"Productos del PIIP que no están en la lista CHIP: {', '.join(faltan)}."
            regla = regla_para(productos, filas)
        distribucion = DistribucionBPIN.objects.create(corte=corte, periodo=periodo, bpin=bpin, regla=regla,
                                                       observacion=observacion)
        distribucion.productos.set(productos)
        asociaciones += [AsociacionFuenteProducto(distribucion=distribucion, fila=f, producto=p)
                         for f in filas for p in productos]
        if regla in (Regla.UN_PRODUCTO, Regla.SIN_BPIN):
            lineas += [contexto.linea(distribucion, f, productos[0], compromisos=f.rp, obligaciones=f.obligacion,
                                      pagos=f.pago, origen_valores=LineaCUIPO.OrigenValores.SIIFWEB) for f in filas]
        resumen[regla] += 1
    AsociacionFuenteProducto.objects.bulk_create(asociaciones, batch_size=1000)
    LineaCUIPO.objects.bulk_create(lineas, batch_size=1000)

    etiquetas = {Regla.UN_PRODUCTO: "un producto (100 %)", Regla.PIIP: "varios productos y una fuente (por digitar)",
                 Regla.MANUAL: "manuales", Regla.SIN_BPIN: "sin BPIN (producto 0)",
                 Regla.SIN_PRODUCTOS: "sin productos en la lista CHIP", "ya estaban": "ya estaban"}
    nuevas = sum(n for clave, n in resumen.items() if clave != "ya estaban")
    detalle = ", ".join(f"{resumen[clave]} {texto}" for clave, texto in etiquetas.items() if resumen[clave])
    return f"Periodo {periodo}: {nuevas} distribuciones nuevas y {len(lineas)} líneas" + (f" ({detalle})" if detalle else "")


@transaction.atomic
def precargar_de_nuevo(distribucion):
    """Borra una distribucion en borrador (con lo digitado) y la vuelve a precargar."""
    if distribucion.estado != DistribucionBPIN.Estado.BORRADOR:
        raise ValueError(f"{distribucion}: solo se vuelve a precargar una distribución en borrador.")
    corte, bpin = distribucion.corte, distribucion.bpin
    distribucion.delete()
    return precargar(corte, bpines={bpin})


def cuadre(distribucion):
    """Por fila: su valor en SIIFWEB, lo distribuido y la diferencia en C, O y P."""
    sumas = defaultdict(lambda: [0, 0, 0])
    for linea in distribucion.lineas.all():
        s = sumas[linea.fila_id]
        s[0] += linea.compromisos
        s[1] += linea.obligaciones
        s[2] += linea.pagos
    resultado = []
    for fila in distribucion.filas().order_by("rubro", "recurso", "centro_costo"):
        c, o, p = sumas.get(fila.pk, [0, 0, 0])
        resultado.append({"fila": fila, "siifweb": (fila.rp, fila.obligacion, fila.pago), "distribuido": (c, o, p),
                          "diferencia": (fila.rp - c, fila.obligacion - o, fila.pago - p),
                          "cuadra": (fila.rp, fila.obligacion, fila.pago) == (c, o, p)})
    return resultado


# ---------------------------------------------------------------------------
# Edicion de la distribucion (la pantalla por BPIN, fase 4)
# ---------------------------------------------------------------------------

CAMPOS_VALOR = ("compromisos", "obligaciones", "pagos")
CUALITATIVOS = ("cpc", "detalle_sectorial", "tercero", "politica_publica")


def _modelo_cualitativo(campo):
    from .models import TerceroCUIPO
    return {"cpc": CPC, "detalle_sectorial": DetalleSectorial, "tercero": TerceroCUIPO,
            "politica_publica": PoliticaPublica}[campo]


def editable(distribucion):
    if distribucion.estado != DistribucionBPIN.Estado.BORRADOR:
        raise ValueError("La distribución no está en borrador: no se edita.")


def repartir(total, pesos, decimales=2):
    """Reparte `total` en proporcion a `pesos`, redondeado a `decimales`, sin perder un centavo.

    Metodo del mayor residuo: cada parte toma su piso y las unidades que sobran van a las de
    mayor residuo. La suma da exactamente el total.
    """
    unidad = Decimal(1).scaleb(-decimales)
    suma = sum(pesos)
    if not suma:
        raise ValueError("No hay con qué repartir: los pesos suman cero.")
    exactos = [Decimal(total) * Decimal(p) / Decimal(suma) for p in pesos]
    partes = [e.quantize(unidad, rounding=ROUND_DOWN) for e in exactos]
    sobran = int(((Decimal(total) - sum(partes)) / unidad).to_integral_value())
    for i in sorted(range(len(pesos)), key=lambda i: exactos[i] - partes[i], reverse=True)[:sobran]:
        partes[i] += unidad
    return partes


def origen_digitado(distribucion):
    if distribucion.regla == DistribucionBPIN.Regla.PIIP:
        return LineaCUIPO.OrigenValores.PIIP
    return LineaCUIPO.OrigenValores.MANUAL


def _fila_de(distribucion, fila_id):
    fila = distribucion.filas().filter(pk=fila_id).first()
    if fila is None:
        raise ValueError("La fila no es de este BPIN en este corte.")
    return fila


def _producto_de(distribucion, producto_id):
    producto = distribucion.productos.filter(pk=producto_id).first()
    if producto is None:
        raise ValueError("El producto no es de este BPIN.")
    return producto


def _vigencia(vigencia_id):
    vigencia = VigenciaGasto.objects.filter(pk=vigencia_id, activo=True).first()
    if vigencia is None:
        raise ValueError("Vigencia del gasto inválida.")
    return vigencia


@transaction.atomic
def asociar(distribucion, fila_id, producto_id, activo):
    """Asocia o desasocia una fila con un producto. Desasociar borra sus lineas."""
    editable(distribucion)
    fila, producto = _fila_de(distribucion, fila_id), _producto_de(distribucion, producto_id)
    if activo:
        AsociacionFuenteProducto.objects.get_or_create(distribucion=distribucion, fila=fila, producto=producto)
    else:
        distribucion.asociaciones.filter(fila=fila, producto=producto).delete()
        distribucion.lineas.filter(fila=fila, producto=producto).delete()
    return fila


@transaction.atomic
def guardar_valor(distribucion, fila_id, producto_id, vigencia_id, campo, valor):
    """Escribe C, O o P de la linea (fila, producto, vigencia); la crea si no existe."""
    from siifweb.cargas import decimal
    editable(distribucion)
    if campo not in CAMPOS_VALOR:
        raise ValueError(f"Campo desconocido: {campo}")
    fila, producto, vigencia = _fila_de(distribucion, fila_id), _producto_de(distribucion, producto_id), _vigencia(vigencia_id)
    cantidad = decimal(valor).quantize(Decimal("0.01"))
    if cantidad < 0:
        raise ValueError("El valor no puede ser negativo.")
    AsociacionFuenteProducto.objects.get_or_create(distribucion=distribucion, fila=fila, producto=producto)
    linea = distribucion.lineas.filter(fila=fila, producto=producto, vigencia_gasto=vigencia).first()
    if linea is None:
        linea = Cualitativos(distribucion.corte).linea(distribucion, fila, producto, vigencia)
    setattr(linea, campo, cantidad)
    linea.origen_valores = origen_digitado(distribucion)
    linea.save()
    return fila


@transaction.atomic
def agregar_vigencia(distribucion, fila_id, producto_id, vigencia_id):
    """Una linea mas de la fila y el producto, en otra vigencia del gasto, en ceros."""
    editable(distribucion)
    fila, producto, vigencia = _fila_de(distribucion, fila_id), _producto_de(distribucion, producto_id), _vigencia(vigencia_id)
    if distribucion.lineas.filter(fila=fila, producto=producto, vigencia_gasto=vigencia).exists():
        raise ValueError(f"Ya hay una línea de ese producto con la vigencia {vigencia.codigo}.")
    AsociacionFuenteProducto.objects.get_or_create(distribucion=distribucion, fila=fila, producto=producto)
    Cualitativos(distribucion.corte).linea(distribucion, fila, producto, vigencia,
                                           origen_valores=origen_digitado(distribucion)).save()
    return fila


@transaction.atomic
def quitar_linea(distribucion, linea_id):
    editable(distribucion)
    linea = distribucion.lineas.select_related("fila").filter(pk=linea_id).first()
    if linea is None:
        raise ValueError("La línea no es de esta distribución.")
    fila = linea.fila
    linea.delete()
    return fila


@transaction.atomic
def cambiar_cualitativo(distribucion, linea_id, campo, codigo):
    """Pone el CPC, detalle sectorial, tercero o politica publica por su codigo (origen manual)."""
    editable(distribucion)
    if campo not in CUALITATIVOS:
        raise ValueError(f"Campo desconocido: {campo}")
    linea = distribucion.lineas.select_related("fila").filter(pk=linea_id).first()
    if linea is None:
        raise ValueError("La línea no es de esta distribución.")
    codigo = (codigo or "").strip()
    valor = None
    if codigo:
        valor = _modelo_cualitativo(campo).objects.filter(codigo=codigo).first()
        if valor is None:
            raise ValueError(f"{codigo}: no está en la lista CHIP.")
        if not valor.activo:
            raise ValueError(f"{codigo}: está inactivo en la lista CHIP.")
    setattr(linea, campo, valor)
    setattr(linea, f"origen_{campo}", LineaCUIPO.Origen.MANUAL if valor else "")
    linea.save()
    return linea.fila


@transaction.atomic
def proporcional_a_compromisos(distribucion):
    """Obligaciones y pagos de cada fila, repartidos con la participacion de los compromisos
    ya distribuidos en sus lineas. Las filas sin compromisos distribuidos quedan igual."""
    editable(distribucion)
    filas, omitidas = 0, []
    for fila in distribucion.filas().order_by("rubro", "recurso", "centro_costo"):
        lineas = list(distribucion.lineas.filter(fila=fila).order_by("pk"))
        pesos = [linea.compromisos for linea in lineas]
        if not lineas or not sum(pesos):
            omitidas.append(f"{fila.rubro} · recurso {fila.recurso}")
            continue
        for linea, o, p in zip(lineas, repartir(fila.obligacion, pesos), repartir(fila.pago, pesos)):
            linea.obligaciones, linea.pagos = o, p
        LineaCUIPO.objects.bulk_update(lineas, ["obligaciones", "pagos"])
        filas += 1
    mensaje = f"Obligaciones y pagos repartidos con la participación de los compromisos en {filas} filas."
    if omitidas:
        mensaje += f" Sin compromisos distribuidos: {', '.join(omitidas)}."
    return mensaje


@transaction.atomic
def todo_a_un_producto(distribucion, producto_id):
    """El 100 % de cada fila al producto, en vigencia 1. Borra las demas lineas."""
    editable(distribucion)
    producto = _producto_de(distribucion, producto_id)
    contexto = Cualitativos(distribucion.corte)
    distribucion.lineas.all().delete()
    distribucion.asociaciones.exclude(producto=producto).delete()
    nuevas = []
    for fila in distribucion.filas():
        AsociacionFuenteProducto.objects.get_or_create(distribucion=distribucion, fila=fila, producto=producto)
        nuevas.append(contexto.linea(distribucion, fila, producto, compromisos=fila.rp, obligaciones=fila.obligacion,
                                     pagos=fila.pago, origen_valores=LineaCUIPO.OrigenValores.SIIFWEB))
    LineaCUIPO.objects.bulk_create(nuevas)
    return f"Todo al producto {producto.codigo}: {len(nuevas)} filas."


def antecedente(distribucion):
    """La distribucion por producto del mismo BPIN en el ultimo periodo enviado de la vigencia:
    (distribucion anterior, [(codigo, descripcion, compromisos, participacion %)])."""
    anterior = (DistribucionBPIN.objects.filter(bpin=distribucion.bpin, estado=DistribucionBPIN.Estado.ENVIADO,
                                                corte__vigencia=distribucion.corte.vigencia,
                                                corte__fecha_fin__lt=distribucion.corte.fecha_fin)
                .select_related("corte").order_by("-corte__fecha_fin").first())
    if anterior is None:
        return None, []
    por_producto, nombres = defaultdict(Decimal), {}
    for linea in anterior.lineas.select_related("producto"):
        por_producto[linea.producto.codigo] += linea.compromisos
        nombres[linea.producto.codigo] = linea.producto.descripcion
    total = sum(por_producto.values())
    return anterior, [(codigo, nombres[codigo], valor, (valor / total * 100) if total else Decimal(0))
                      for codigo, valor in sorted(por_producto.items())]


def matriz(distribucion, solo_fila=None):
    """Lo que pinta la pantalla: por fila, sus lineas (y una vacia por cada producto asociado
    sin lineas), lo de SIIFWEB, lo distribuido y la diferencia."""
    lineas = defaultdict(list)
    consulta = distribucion.lineas.select_related("producto", "vigencia_gasto", "cpc", "detalle_sectorial",
                                                  "tercero", "politica_publica")
    for linea in consulta.order_by("producto__codigo", "vigencia_gasto__codigo"):
        lineas[linea.fila_id].append(linea)
    asociados = defaultdict(set)
    for fila_id, producto_id in distribucion.asociaciones.values_list("fila_id", "producto_id"):
        asociados[fila_id].add(producto_id)
    productos = list(distribucion.productos.order_by("codigo"))
    filas = distribucion.filas().order_by("rubro", "recurso", "centro_costo")
    if solo_fila is not None:
        filas = filas.filter(pk=solo_fila.pk)
    resultado = []
    for fila in filas:
        propias = lineas.get(fila.pk, [])
        con_linea = {linea.producto_id for linea in propias}
        distribuido = tuple(sum((getattr(linea, c) for linea in propias), Decimal(0)) for c in CAMPOS_VALOR)
        siifweb = (fila.rp, fila.obligacion, fila.pago)
        diferencia = tuple(s - d for s, d in zip(siifweb, distribuido))
        resultado.append({
            "fila": fila, "lineas": propias,
            "vacias": [p for p in productos if p.pk in asociados[fila.pk] and p.pk not in con_linea],
            "asociados": [(p, p.pk in asociados[fila.pk]) for p in productos],
            "siifweb": siifweb, "distribuido": distribuido, "diferencia": diferencia,
            "cuadra": not any(diferencia)})
    return resultado


def totales(distribucion):
    """Para el encabezado: SIIFWEB, distribuido y filas que cuadran."""
    filas = matriz(distribucion)
    suma = lambda clave, i: sum((f[clave][i] for f in filas), Decimal(0))
    return {"siifweb": tuple(suma("siifweb", i) for i in range(3)),
            "distribuido": tuple(suma("distribuido", i) for i in range(3)),
            "diferencia": tuple(suma("diferencia", i) for i in range(3)),
            "filas": len(filas), "cuadran": sum(f["cuadra"] for f in filas)}
