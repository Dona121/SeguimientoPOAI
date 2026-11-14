"""Plano CHIP del CUIPO: el bloque D_EJECUCION_DE_GASTOS de la inversion (fase 6).

Formato (PLAN_CUIPO.md, seccion 4.4):
- encabezado `S<tab>117070000<tab>10909<tab>2026<tab>D_EJECUCION_DE_GASTOS`;
- lineas de detalle de 15 campos: D, CODIGO, VIG, SECCION, PROD, CPC, DETSEC, FUENTE, BPIN, SITFON,
  POLPUB, TERC, C, O, P;
- lineas resumen por cada nivel de prefijo del codigo, con los 8 cualitativos vacios;
- valores enteros: se redondea solo aqui. Por fila de ejecucion, el total de cada valor se
  redondea al peso y se reparte entre sus lineas por el metodo del mayor residuo, asi los
  enteros cuadran con el total;
- las lineas con iguales VIG, SECCION, CODIGO y cualitativos se agrupan sumando; las lineas en
  cero no van;
- orden: vigencia del gasto -> seccion -> segmentos del codigo; el resumen antes que su detalle.

`generar(corte)` da el bloque de la inversion (2.3). `integrar(texto, corte)` lo pone en el
plano completo de presupuesto: dentro del bloque D cambia las lineas 2.3 y la linea resumen 2;
las lineas 2.1, 2.2 y las demas categorias quedan identicas, en su orden.

Solo se genera si todas las filas del corte tienen distribucion y ninguna tiene errores.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from .derivacion import Derivador, filas_cuipo
from .distribucion import CAMPOS_VALOR, repartir
from .models import LineaCUIPO, periodo_de
from .validacion import validar_distribucion

ENTIDAD = getattr(settings, "CUIPO_ENTIDAD", "117070000")
CATEGORIA = "D_EJECUCION_DE_GASTOS"
N_CUALITATIVOS = 8
INVERSION = "2.3"


class PlanoInvalido(ValueError):
    def __init__(self, problemas):
        self.problemas = problemas
        super().__init__(f"No se puede generar el plano: {len(problemas)} problemas. El primero: {problemas[0]}")


def segmentos(codigo):
    return tuple(int(s) if s.isdigit() else s for s in codigo.split("."))


def numero(texto):
    try:
        return (0, Decimal(texto))
    except Exception:
        return (1, texto)


@dataclass
class Linea:
    codigo: str
    vigencia: str
    seccion: str
    cualitativos: tuple = None     # None en las lineas resumen
    valores: list = field(default_factory=lambda: [0, 0, 0])
    original: str = None           # el texto tal cual, para las lineas que se conservan
    indice: int = 0

    @property
    def resumen(self):
        return self.cualitativos is None

    def texto(self):
        if self.original is not None:
            return self.original
        cual = self.cualitativos or ("",) * N_CUALITATIVOS
        return "\t".join(["D", self.codigo, self.vigencia, self.seccion, *cual, *(str(v) for v in self.valores)])

    def orden(self):
        desempate = (0, self.indice) if self.original is not None else (1, self.cualitativos or ())
        return (numero(self.vigencia), numero(self.seccion), segmentos(self.codigo), not self.resumen, desempate)


def encabezado(periodo, vigencia):
    return "\t".join(["S", ENTIDAD, periodo, str(vigencia), CATEGORIA])


def al_peso(valor):
    return int(Decimal(valor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def respetar_orden(valores, donde=""):
    """Cada campo se redondea por separado, asi que una linea puede quedar con obligaciones
    mayores que compromisos (o pagos mayores que obligaciones) por un peso, aunque con centavos
    estuviera bien. Se pasa ese peso a otra linea de la misma fila que tenga margen: los totales
    de la fila no cambian. `valores` es la lista [C, O, P] en enteros de cada linea; se modifica.
    """
    for alto, bajo in ((1, 0), (2, 1)):          # primero O <= C, luego P <= O
        while True:
            excedidas = [i for i, v in enumerate(valores) if v[alto] > v[bajo]]
            if not excedidas:
                break
            con_margen = [j for j, v in enumerate(valores) if v[alto] < v[bajo]]
            if not con_margen:     # solo pasa si la fila de SIIFWEB ya trae O > C o P > O
                nombres = ("compromisos", "obligaciones", "pagos")
                raise PlanoInvalido([f"{donde}: {nombres[alto]} mayores que {nombres[bajo]} al redondear a pesos"])
            i = excedidas[0]
            j = max(con_margen, key=lambda j: valores[j][bajo] - valores[j][alto])
            valores[i][alto] -= 1
            valores[j][alto] += 1
    return valores


def revisar(corte):
    """Los problemas que impiden generar el plano del corte (lista vacia si ninguno)."""
    problemas = []
    if periodo_de(corte) is None:
        return [f"{corte}: no va del 1 de enero al cierre de un trimestre, no tiene periodo CUIPO."]
    derivador = Derivador(corte.vigencia)
    distribuciones = {d.bpin: d for d in corte.distribuciones.all()}
    bpines = set(filas_cuipo(corte).values_list("proyecto", flat=True))
    for bpin in sorted(bpines - set(distribuciones)):
        problemas.append(f"BPIN {bpin}: sus filas no tienen distribución (precargar el corte)")
    for bpin, d in sorted(distribuciones.items()):
        r = validar_distribucion(d, derivador)
        if r.errores:
            problemas.append(f"BPIN {bpin}: {len(r.errores)} errores. {r.errores[0].mensaje}")
    return problemas


def detalle(corte):
    """Las lineas de detalle de la inversion, redondeadas y agrupadas."""
    problemas = revisar(corte)
    if problemas:
        raise PlanoInvalido(problemas)
    derivador = Derivador(corte.vigencia)
    por_fila = defaultdict(list)
    for linea in (LineaCUIPO.objects.filter(distribucion__corte=corte)
                  .select_related("producto", "vigencia_gasto", "cpc", "detalle_sectorial", "tercero",
                                  "politica_publica").order_by("pk")):
        por_fila[linea.fila_id].append(linea)

    agrupado = {}
    for fila in filas_cuipo(corte).order_by("rubro", "recurso", "centro_costo", "proyecto"):
        lineas = por_fila.get(fila.pk, [])
        d = derivador.derivar(fila)
        enteros = {linea.pk: [0, 0, 0] for linea in lineas}
        for i, campo in enumerate(CAMPOS_VALOR):
            valores = [getattr(linea, campo) for linea in lineas]
            if not sum(valores):
                continue
            for linea, entero in zip(lineas, repartir(al_peso(sum(valores)), valores, decimales=0)):
                enteros[linea.pk][i] = int(entero)
        respetar_orden(list(enteros.values()), f"{fila.rubro} {fila.recurso} {fila.centro_costo} {fila.proyecto}")
        for linea in lineas:
            cualitativos = (linea.producto.codigo, linea.cpc.codigo, linea.detalle_sectorial.codigo, d.fuente.codigo,
                            fila.proyecto, d.situacion.codigo, linea.politica_publica.codigo, linea.tercero.codigo)
            clave = (d.concepto.codigo, linea.vigencia_gasto.codigo, d.seccion.codigo, cualitativos)
            destino = agrupado.setdefault(clave, Linea(clave[0], clave[1], clave[2], cualitativos))
            destino.valores = [a + b for a, b in zip(destino.valores, enteros[linea.pk])]
    return [linea for linea in agrupado.values() if any(linea.valores)]


def resumenes(lineas, desde=None):
    """Una linea resumen por (vigencia, seccion, prefijo del codigo), sumando el detalle. Con
    `desde`, solo los prefijos que empiezan por ese codigo (ej. "2.3")."""
    sumas = {}
    for linea in lineas:
        partes = linea.codigo.split(".")
        for n in range(1, len(partes) + 1):
            prefijo = ".".join(partes[:n])
            if desde and not (prefijo == desde or prefijo.startswith(desde + ".")):
                continue
            clave = (linea.vigencia, linea.seccion, prefijo)
            resumen = sumas.setdefault(clave, Linea(prefijo, linea.vigencia, linea.seccion))
            resumen.valores = [a + b for a, b in zip(resumen.valores, linea.valores)]
    return [r for r in sumas.values() if any(r.valores)]


def generar(corte):
    """El bloque D_EJECUCION_DE_GASTOS de la inversion, con su encabezado, en texto."""
    lineas = detalle(corte)
    todas = sorted(lineas + resumenes(lineas), key=Linea.orden)
    return "\r\n".join([encabezado(periodo_de(corte), corte.vigencia)] + [l.texto() for l in todas]) + "\r\n"


def _leer(texto_linea, indice):
    campos = texto_linea.split("\t")
    if len(campos) != 15 or campos[0] != "D":
        raise ValueError(f"Línea {indice + 1} del bloque {CATEGORIA}: no tiene 15 campos o no empieza por D")
    cualitativos = tuple(campos[4:12])
    return Linea(campos[1], campos[2], campos[3], None if not any(cualitativos) else cualitativos,
                 [int(Decimal(v or 0)) for v in campos[12:15]], original=texto_linea, indice=indice)


def integrar(texto, corte):
    """El plano de presupuesto completo con la inversion del corte en su bloque D."""
    salto = "\r\n" if "\r\n" in texto else "\n"
    termina_en_salto = texto.endswith(("\n", "\r\n"))
    renglones = texto.splitlines()
    inicio = next((i for i, r in enumerate(renglones)
                   if r.split("\t")[0] == "S" and r.split("\t")[-1].strip() == CATEGORIA), None)
    if inicio is None:
        raise ValueError(f"El plano no tiene el bloque {CATEGORIA}.")
    cabeza = renglones[inicio].split("\t")
    periodo = periodo_de(corte)
    if len(cabeza) < 5 or cabeza[2] != periodo or cabeza[3] != str(corte.vigencia):
        raise ValueError(f"El plano es del periodo {cabeza[2] if len(cabeza) > 2 else '?'} de "
                         f"{cabeza[3] if len(cabeza) > 3 else '?'} y el corte es del {periodo} de {corte.vigencia}.")
    fin = next((i for i in range(inicio + 1, len(renglones)) if renglones[i].split("\t")[0] == "S"), len(renglones))

    conservadas, primer_nivel = [], []
    for indice, renglon in enumerate(renglones[inicio + 1:fin]):
        if not renglon.strip():
            continue
        linea = _leer(renglon, indice)
        if linea.codigo == "2" and linea.resumen:
            continue                                      # se recalcula
        if linea.codigo == INVERSION or linea.codigo.startswith(INVERSION + "."):
            continue                                      # la reemplaza el aplicativo
        conservadas.append(linea)
        if linea.resumen and len(linea.codigo.split(".")) == 2 and linea.codigo.startswith("2."):
            primer_nivel.append(linea)

    nuevas = detalle(corte)
    de_inversion = resumenes(nuevas, desde=INVERSION)
    totales = {}
    for linea in primer_nivel + [r for r in de_inversion if r.codigo == INVERSION]:
        total = totales.setdefault((linea.vigencia, linea.seccion), Linea("2", linea.vigencia, linea.seccion))
        total.valores = [a + b for a, b in zip(total.valores, linea.valores)]
    bloque = sorted(conservadas + nuevas + de_inversion + [t for t in totales.values() if any(t.valores)],
                    key=Linea.orden)
    resultado = renglones[:inicio + 1] + [l.texto() for l in bloque] + renglones[fin:]
    return salto.join(resultado) + (salto if termina_en_salto else "")


def nombre_archivo(corte):
    return f"CUIPO_{ENTIDAD}_{periodo_de(corte)}_{corte.vigencia}_{CATEGORIA}_inversion.txt"
