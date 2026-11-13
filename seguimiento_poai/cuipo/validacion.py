"""Validaciones de la distribucion (fase 5 del CUIPO).

`validar_distribucion(distribucion)` devuelve los errores (bloquean validar la distribucion y
generar el plano) y las advertencias (se muestran, no bloquean). La usan la pantalla por
BPIN, el cambio de estado y el generador del plano.

Errores:
- lo que la derivacion no resuelve (fuente sin homologar, concepto no habilitado...);
- por fila, la suma de sus lineas debe dar el valor de SIIFWEB en C, O y P, al centavo;
- por linea: nada negativo, O <= C y P <= O;
- el producto debe ser del BPIN segun la formulacion PIIP (en la inversion sin BPIN, solo el 0);
- CPC, detalle sectorial, tercero y politica publica no pueden quedar vacios;
- ningun codigo de las listas puede estar inactivo (producto, vigencia del gasto, cualitativos);
- una distribucion sin productos en la lista CHIP no se puede validar.

Advertencias:
- CPC 0 (no aplica) en un concepto que exige CPC: CHIP lo acepto en el T3 (viaticos).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .derivacion import Derivador
from .distribucion import CAMPOS_VALOR, PRODUCTO_SIN_BPIN, productos_piip
from .models import DistribucionBPIN

CUALITATIVOS = (("cpc", "CPC"), ("detalle_sectorial", "detalle sectorial"), ("tercero", "tercero"),
                ("politica_publica", "política pública"))


@dataclass
class Problema:
    mensaje: str
    fila: object = None
    linea: object = None


@dataclass
class Resultado:
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)

    @property
    def valida(self):
        return not self.errores


def etiqueta(fila):
    return f"{fila.rubro} · recurso {fila.recurso} · CC {fila.centro_costo}"


def pesos(valor):
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def validar_distribucion(distribucion, derivador=None):
    derivador = derivador or Derivador(distribucion.corte.vigencia)
    r = Resultado()
    if distribucion.regla == DistribucionBPIN.Regla.SIN_PRODUCTOS:
        r.errores.append(Problema("El BPIN no tiene productos en la lista CHIP: no se puede distribuir."))
    if distribucion.bpin == "0":
        del_bpin = {PRODUCTO_SIN_BPIN}
    else:
        del_bpin = set(productos_piip([distribucion.bpin], distribucion.corte.vigencia).get(distribucion.bpin, []))

    por_fila = defaultdict(list)
    for linea in distribucion.lineas.select_related("producto", "vigencia_gasto", "cpc", "detalle_sectorial",
                                                    "tercero", "politica_publica"):
        por_fila[linea.fila_id].append(linea)

    for fila in distribucion.filas().order_by("rubro", "recurso", "centro_costo"):
        nombre = etiqueta(fila)
        d = derivador.derivar(fila)
        r.errores += [Problema(faltante, fila) for faltante in d.faltantes]
        lineas = por_fila.get(fila.pk, [])
        for campo, de_siifweb, texto in zip(CAMPOS_VALOR, (fila.rp, fila.obligacion, fila.pago),
                                            ("compromisos", "obligaciones", "pagos")):
            distribuido = sum((getattr(l, campo) for l in lineas), Decimal(0))
            if distribuido != de_siifweb:
                r.errores.append(Problema(f"{nombre}: {texto} distribuidos {pesos(distribuido)} y en SIIFWEB "
                                          f"{pesos(de_siifweb)} (diferencia {pesos(de_siifweb - distribuido)})", fila))
        for linea in lineas:
            donde = f"{nombre} · producto {linea.producto.codigo} · vigencia {linea.vigencia_gasto.codigo}"
            if min(linea.compromisos, linea.obligaciones, linea.pagos) < 0:
                r.errores.append(Problema(f"{donde}: hay valores negativos", fila, linea))
            if linea.obligaciones > linea.compromisos:
                r.errores.append(Problema(f"{donde}: obligaciones ({pesos(linea.obligaciones)}) mayores que "
                                          f"compromisos ({pesos(linea.compromisos)})", fila, linea))
            if linea.pagos > linea.obligaciones:
                r.errores.append(Problema(f"{donde}: pagos ({pesos(linea.pagos)}) mayores que obligaciones "
                                          f"({pesos(linea.obligaciones)})", fila, linea))
            if linea.producto.codigo not in del_bpin:
                r.errores.append(Problema(f"{donde}: el producto no está programado en {distribucion.corte.vigencia} según la formulación PIIP", fila, linea))
            if not linea.producto.activo:
                r.errores.append(Problema(f"{donde}: el producto está inactivo en la lista CHIP", fila, linea))
            if not linea.vigencia_gasto.activo:
                r.errores.append(Problema(f"{donde}: la vigencia del gasto está inactiva en la lista CHIP", fila, linea))
            for campo, texto in CUALITATIVOS:
                valor = getattr(linea, campo)
                if valor is None:
                    r.errores.append(Problema(f"{donde}: falta el {texto}", fila, linea))
                elif not valor.activo:
                    r.errores.append(Problema(f"{donde}: el {texto} {valor.codigo} está inactivo en la lista CHIP",
                                              fila, linea))
            if linea.cpc_id and linea.cpc.codigo == "0" and d.concepto and d.concepto.requiere_cpc:
                r.advertencias.append(Problema(f"{donde}: CPC 0 (no aplica) en un concepto que exige CPC", fila, linea))
    return r


def validar_corte(corte):
    """[(distribucion, resultado)] de todas las distribuciones del corte, con un solo derivador."""
    derivador = Derivador(corte.vigencia)
    return [(d, validar_distribucion(d, derivador)) for d in corte.distribuciones.order_by("bpin")]


# Borrador -> validado (sin errores) -> enviado. Una validada puede volver a borrador para
# corregirla; una enviada ya no cambia (es lo que esta en CHIP).
TRANSICIONES = {
    DistribucionBPIN.Estado.BORRADOR: {DistribucionBPIN.Estado.VALIDADO},
    DistribucionBPIN.Estado.VALIDADO: {DistribucionBPIN.Estado.BORRADOR, DistribucionBPIN.Estado.ENVIADO},
    DistribucionBPIN.Estado.ENVIADO: set(),
}


def revisar_cambio(distribucion, nuevo):
    """Lanza ValueError si la distribucion no puede pasar al estado nuevo."""
    actual = DistribucionBPIN.Estado(distribucion.estado)
    if nuevo == actual:
        return
    if nuevo not in TRANSICIONES[actual]:
        raise ValueError(f"De {actual.label.lower()} no se pasa a {DistribucionBPIN.Estado(nuevo).label.lower()}.")
    if nuevo == DistribucionBPIN.Estado.VALIDADO:
        resultado = validar_distribucion(distribucion)
        if not resultado.valida:
            raise ValueError(f"No se puede validar: {len(resultado.errores)} errores. "
                             f"El primero: {resultado.errores[0].mensaje}")


def cambiar_estado(distribucion, nuevo, usuario=None):
    from django.utils import timezone
    revisar_cambio(distribucion, nuevo)
    distribucion.estado = nuevo
    if nuevo == DistribucionBPIN.Estado.VALIDADO:
        distribucion.validado_por, distribucion.fecha_validacion = usuario, timezone.now()
    elif nuevo == DistribucionBPIN.Estado.BORRADOR:
        distribucion.validado_por, distribucion.fecha_validacion = None, None
    distribucion.save(update_fields=["estado", "validado_por", "fecha_validacion", "fecha_actualizacion"])
