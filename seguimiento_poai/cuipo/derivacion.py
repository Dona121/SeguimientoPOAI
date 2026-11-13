"""De la fila de ejecucion de SIIFWEB a los codigos CHIP: concepto, fuente CUIPO, seccion,
situacion de fondos y tercero.

`Derivador(vigencia)` carga una vez las listas y las reglas, y `derivar(fila)` resuelve cada
fila. Lo que no se puede resolver queda en `faltantes` y bloquea la generacion del CUIPO.

Reglas (PLAN_CUIPO.md, seccion 4.2):
- Concepto: la excepcion de HomologacionRubro o, si no hay, el mismo codigo del rubro. En
  los dos casos el concepto debe existir, estar activo y habilitado para departamentos.
- Fuente: HomologacionFuente del recurso para la vigencia del corte.
- Seccion: ReglaSeccion del centro de costo de la fila; si no hay, 16.0.
- Situacion de fondos: la ReglaSituacionFondos de prefijo mas largo que aplique al rubro (y
  a la fuente CUIPO, si la nombra); si no hay, C.
- Tercero: ReglaTercero del rubro o, si no hay, la del centro de costo; si no hay, 1 - NO APLICA.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from siifweb.models import Fuente

from .models import (ConceptoCUIPO, FuenteCUIPO, HomologacionFuente, HomologacionRubro, ReglaSeccion,
                     ReglaSituacionFondos, ReglaTercero, SeccionPresupuestal, SituacionFondos, TerceroCUIPO)

SECCION_POR_DEFECTO = "16.0"
SITUACION_POR_DEFECTO = "C"
TERCERO_POR_DEFECTO = "1"   # NO APLICA


def filas_cuipo(corte):
    """Las filas del corte que entran al CUIPO: arbol de la vigencia, inversion (2.3) y con
    RP, obligacion o pago. Una fila con solo apropiacion o CDP no entra."""
    return (corte.filas_ejecucion.filter(de_otra_vigencia=False, rubro__startswith="2.3.")
            .filter(~Q(rp=0) | ~Q(obligacion=0) | ~Q(pago=0)))


@dataclass
class Derivacion:
    concepto: ConceptoCUIPO | None = None
    origen_concepto: str = ""
    fuente: FuenteCUIPO | None = None
    seccion: SeccionPresupuestal | None = None
    origen_seccion: str = ""
    situacion: SituacionFondos | None = None
    origen_situacion: str = ""
    tercero: TerceroCUIPO | None = None
    origen_tercero: str = ""
    faltantes: list = field(default_factory=list)

    @property
    def completa(self):
        return not self.faltantes


class Derivador:
    """Las listas y reglas en memoria, para derivar muchas filas de una vigencia."""

    def __init__(self, vigencia):
        self.vigencia = vigencia
        self.recursos = set(Fuente.objects.values_list("codigo", flat=True))
        self.fuentes = {h.fuente_siifweb.codigo: h.fuente_cuipo
                        for h in HomologacionFuente.objects.filter(vigencia=vigencia)
                        .select_related("fuente_siifweb", "fuente_cuipo")}
        self.conceptos = {c.codigo: c for c in ConceptoCUIPO.objects.all()}
        self.excepciones_rubro = {h.rubro.codigo: h.concepto
                                  for h in HomologacionRubro.objects.select_related("rubro", "concepto")}
        self.secciones = {r.centro_costo.codigo: r.seccion
                          for r in ReglaSeccion.objects.select_related("centro_costo", "seccion")}
        self.terceros_rubro, self.terceros_centro = {}, {}
        for r in ReglaTercero.objects.select_related("rubro", "centro_costo", "tercero"):
            if r.rubro_id:
                self.terceros_rubro[r.rubro.codigo] = r.tercero
            else:
                self.terceros_centro[r.centro_costo.codigo] = r.tercero
        # La mas especifica primero: prefijo mas largo y, a igual prefijo, la que nombra fuente
        self.situaciones = sorted(ReglaSituacionFondos.objects.select_related("fuente_cuipo", "situacion"),
                                  key=lambda r: (-len(r.prefijo_rubro), r.fuente_cuipo_id is None))
        self.seccion_defecto = SeccionPresupuestal.objects.filter(codigo=SECCION_POR_DEFECTO).first()
        self.situacion_defecto = SituacionFondos.objects.filter(codigo=SITUACION_POR_DEFECTO).first()
        self.tercero_defecto = TerceroCUIPO.objects.filter(codigo=TERCERO_POR_DEFECTO).first()

    # Cada parte devuelve (valor, origen) o agrega a faltantes

    def _concepto(self, fila, d):
        if fila.rubro in self.excepciones_rubro:
            concepto, d.origen_concepto = self.excepciones_rubro[fila.rubro], "homologación del rubro"
        else:
            concepto, d.origen_concepto = self.conceptos.get(fila.rubro), "mismo código del rubro"
            if concepto is None:
                d.faltantes.append(f"Rubro {fila.rubro}: no está en los conceptos CUIPO; falta su homologación")
                return
        if not concepto.activo:
            d.faltantes.append(f"Rubro {fila.rubro}: el concepto {concepto.codigo} está inactivo en las listas")
        elif not concepto.habilitado_departamentos:
            d.faltantes.append(f"Rubro {fila.rubro}: el concepto {concepto.codigo} no está habilitado para "
                               f"departamentos; falta su homologación")
        else:
            d.concepto = concepto

    def _fuente(self, fila, d):
        if fila.recurso not in self.recursos:
            d.faltantes.append(f"Recurso {fila.recurso}: no está en los recursos de SIIFWEB "
                               f"(cargar los consolidados al día)")
            return
        fuente = self.fuentes.get(fila.recurso)
        if fuente is None:
            d.faltantes.append(f"Recurso {fila.recurso}: sin homologación de fuente para {self.vigencia}")
        elif not fuente.activo:
            d.faltantes.append(f"Recurso {fila.recurso}: la fuente CUIPO {fuente.codigo} está inactiva en las listas")
        else:
            d.fuente = fuente

    def _seccion(self, fila, d):
        if fila.centro_costo in self.secciones:
            d.seccion, d.origen_seccion = self.secciones[fila.centro_costo], "regla del centro de costo"
        elif self.seccion_defecto:
            d.seccion, d.origen_seccion = self.seccion_defecto, "por defecto"
        else:
            d.faltantes.append(f"Falta la sección {SECCION_POR_DEFECTO} en las listas CHIP")

    def _situacion(self, fila, d):
        for regla in self.situaciones:
            prefijo = regla.prefijo_rubro
            if fila.rubro != prefijo and not fila.rubro.startswith(prefijo + "."):
                continue
            if regla.fuente_cuipo_id and (d.fuente is None or regla.fuente_cuipo_id != d.fuente.pk):
                continue
            d.situacion, d.origen_situacion = regla.situacion, "regla"
            return
        if self.situacion_defecto:
            d.situacion, d.origen_situacion = self.situacion_defecto, "por defecto"
        else:
            d.faltantes.append(f"Falta la situación de fondos {SITUACION_POR_DEFECTO} en las listas CHIP")

    def _tercero(self, fila, d):
        if fila.rubro in self.terceros_rubro:
            d.tercero, d.origen_tercero = self.terceros_rubro[fila.rubro], "regla del rubro"
        elif fila.centro_costo in self.terceros_centro:
            d.tercero, d.origen_tercero = self.terceros_centro[fila.centro_costo], "regla del centro de costo"
        elif self.tercero_defecto:
            d.tercero, d.origen_tercero = self.tercero_defecto, "por defecto"
        else:
            d.faltantes.append(f"Falta el tercero {TERCERO_POR_DEFECTO} (NO APLICA) en las listas CHIP")

    def derivar(self, fila):
        d = Derivacion()
        self._concepto(fila, d)
        self._fuente(fila, d)
        self._seccion(fila, d)
        self._situacion(fila, d)   # despues de la fuente: la regla puede depender de ella
        self._tercero(fila, d)
        return d


def derivar(fila):
    """Deriva una sola fila. Para muchas, usar un Derivador."""
    return Derivador(fila.corte.vigencia).derivar(fila)


# ---------------------------------------------------------------------------
# Pendientes de un corte
# ---------------------------------------------------------------------------

def _sumar(grupos, clave, fila, **datos):
    g = grupos.setdefault(clave, {"filas": 0, "rp": Decimal(0), **datos})
    g["filas"] += 1
    g["rp"] += fila.rp


def pendientes(corte):
    """Lo que falta resolver antes de distribuir el corte, agrupado para revisarlo.

    - recursos sin homologacion de fuente (con el codigo que trae el nombre como pista: no es
      confiable, en 20 recursos no es la fuente correcta);
    - rubros sin concepto CUIPO valido;
    - recursos que no estan en SIIFWEB y otros faltantes;
    - BPIN con ejecucion sin formulacion PIIP (sin productos para distribuir);
    - centros de costo que van a la seccion por defecto (informativo).
    """
    from siifweb.models import FormulacionProyecto

    derivador = Derivador(corte.vigencia)
    codigos_fuente = set(FuenteCUIPO.objects.values_list("codigo", flat=True))
    filas = list(filas_cuipo(corte).order_by("rubro", "recurso", "centro_costo", "proyecto"))
    recursos, rubros, otros, por_defecto, sin_piip = {}, {}, {}, {}, {}
    completas = 0
    formulados = set(FormulacionProyecto.objects.filter(bpin__in={f.proyecto for f in filas})
                     .values_list("bpin", flat=True))
    for f in filas:
        d = derivador.derivar(f)
        completas += d.completa
        for faltante in d.faltantes:
            if faltante.startswith(f"Recurso {f.recurso}: sin homologación"):
                pista = re.match(r"\s*([\d.]+)", f.nombre_recurso or "")
                pista = pista.group(1).rstrip(".") if pista else ""
                _sumar(recursos, f.recurso, f, nombre=f.nombre_recurso,
                       pista=pista if pista in codigos_fuente else "")
            elif faltante.startswith(f"Rubro {f.rubro}:"):
                _sumar(rubros, f.rubro, f, nombre=f.nombre_rubro, motivo=faltante.split(": ", 1)[1])
            else:
                _sumar(otros, faltante, f)
        if d.origen_seccion == "por defecto":
            _sumar(por_defecto, f.centro_costo, f, nombre=f.nombre_centro_costo)
        if f.proyecto != "0" and f.proyecto not in formulados:
            _sumar(sin_piip, f.proyecto, f)

    def lista(grupos, nombre_clave):
        return [{nombre_clave: k, **v} for k, v in sorted(grupos.items())]

    return {
        "filas": len(filas), "completas": completas, "con_faltantes": len(filas) - completas,
        "recursos": lista(recursos, "recurso"), "rubros": lista(rubros, "rubro"),
        "otros": lista(otros, "faltante"), "sin_piip": lista(sin_piip, "bpin"),
        "por_defecto": lista(por_defecto, "centro_costo"),
    }


# ---------------------------------------------------------------------------
# Reglas iniciales (las que trae el plan)
# ---------------------------------------------------------------------------

REGLAS_INICIALES = {
    "secciones": [("2", "22.0"), ("3", "21.0")],
    "terceros_rubro": [("2.3.1.01.02.006", "23900000"), ("2.3.1.01.02.007", "26800000"),
                       ("2.3.1.01.02.008", "22000000"), ("2.3.1.01.02.009", "11300000")],
    "terceros_centro": [("11", "128470000"), ("10", "220170001"), ("5", "923272066"), ("25", "128870000")],
    "rubros": [("2.3.3.05.09.054", "2.3.3.05.09.099")],
    "situaciones": [("2.3.1.01.02.001", "1.2.4.1.01", "S"), ("2.3.1.01.02.002", "1.2.4.1.01", "S"),
                    ("2.3.1.01.02.003", "1.2.4.1.01", "S")],
}


def crear_reglas_iniciales():
    """Crea las reglas del plan que falten. Devuelve (creadas, omitidas con su motivo).

    Necesita las listas CHIP importadas y los rubros y centros de costo de SIIFWEB; lo que no
    encuentre lo omite y lo dice. No cambia reglas existentes.
    """
    from siifweb.models import CentroCosto, Rubro

    creadas, omitidas = [], []

    def buscar(modelo, codigo, etiqueta):
        objeto = modelo.objects.filter(codigo=codigo).first()
        if objeto is None:
            omitidas.append(f"{etiqueta} {codigo} no existe")
        return objeto

    for cc, sec in REGLAS_INICIALES["secciones"]:
        centro, seccion = buscar(CentroCosto, cc, "centro de costo"), buscar(SeccionPresupuestal, sec, "sección")
        if centro and seccion and not ReglaSeccion.objects.filter(centro_costo=centro).exists():
            creadas.append(str(ReglaSeccion.objects.create(centro_costo=centro, seccion=seccion)))
    for rubro_cod, ter in REGLAS_INICIALES["terceros_rubro"]:
        rubro, tercero = buscar(Rubro, rubro_cod, "rubro"), buscar(TerceroCUIPO, ter, "tercero")
        if rubro and tercero and not ReglaTercero.objects.filter(rubro=rubro).exists():
            creadas.append(str(ReglaTercero.objects.create(rubro=rubro, tercero=tercero)))
    for cc, ter in REGLAS_INICIALES["terceros_centro"]:
        centro, tercero = buscar(CentroCosto, cc, "centro de costo"), buscar(TerceroCUIPO, ter, "tercero")
        if centro and tercero and not ReglaTercero.objects.filter(centro_costo=centro).exists():
            creadas.append(str(ReglaTercero.objects.create(centro_costo=centro, tercero=tercero)))
    for rubro_cod, con in REGLAS_INICIALES["rubros"]:
        rubro, concepto = buscar(Rubro, rubro_cod, "rubro"), buscar(ConceptoCUIPO, con, "concepto")
        if rubro and concepto and not HomologacionRubro.objects.filter(rubro=rubro).exists():
            creadas.append(str(HomologacionRubro.objects.create(rubro=rubro, concepto=concepto)))
    for prefijo, fue, sit in REGLAS_INICIALES["situaciones"]:
        fuente, situacion = buscar(FuenteCUIPO, fue, "fuente CUIPO"), buscar(SituacionFondos, sit, "situación")
        if fuente and situacion and not ReglaSituacionFondos.objects.filter(prefijo_rubro=prefijo,
                                                                            fuente_cuipo=fuente).exists():
            creadas.append(str(ReglaSituacionFondos.objects.create(prefijo_rubro=prefijo, fuente_cuipo=fuente,
                                                                   situacion=situacion)))
    return creadas, list(dict.fromkeys(omitidas))
