"""Insumos del reporte CUIPO.

La ejecucion de gastos de SIIFWEB ("estado_ppto_gasto_gobatl_fyccw") se guarda por corte
y solo la usa el CUIPO: no alimenta la ficha, el tablero ni los catalogos de siifweb. Por
eso los codigos van como texto, tal como vienen en el reporte, y no como llaves a Rubro,
Fuente, CentroCosto o Proyecto (que la carga tendria que crear si faltaran).
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from siifweb.models import CentroCosto, Fechas, Fuente, Rubro, listado_vigencias


class CorteEjecucionGastos(Fechas):
    """Un reporte de ejecucion de gastos con el rango de fechas con que se descargo.

    Cada corte se conserva: cargar el de octubre no toca el de septiembre, y el CUIPO de
    un trimestre se puede volver a generar con el mismo insumo.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "P", "Pendiente"
        PROCESADO = "OK", "Procesado"
        ERROR = "E", "Con error"

    vigencia = models.IntegerField(choices=listado_vigencias)
    fecha_inicio = models.DateField(
        verbose_name="Fecha de inicio del corte",
        help_text="Fecha inicial del rango con que se descargó el reporte. Para el CUIPO, que es acumulado, "
                  "el 1 de enero de la vigencia")
    fecha_fin = models.DateField(
        verbose_name="Fecha de fin del corte",
        help_text="Fecha final del rango con que se descargó el reporte. Para una vigencia cerrada, el 31 de "
                  "diciembre")
    fecha_descarga = models.DateField(
        verbose_name="Fecha de descarga", default=timezone.localdate,
        help_text="Día en que se generó el archivo. Lo que se registra después en SIIFWEB con fecha anterior "
                  "al corte no queda en el reporte: dos descargas del mismo corte pueden diferir")
    archivo = models.FileField(upload_to="cuipo/ejecucion_gastos/")
    hash = models.CharField(max_length=64, blank=True, verbose_name="Hash del archivo")
    filas = models.IntegerField(default=0, verbose_name="Filas de detalle")
    estado = models.CharField(max_length=2, choices=Estado.choices, default=Estado.PENDIENTE)
    mensaje = models.TextField(blank=True, verbose_name="Resultado del proceso")

    class Meta:
        verbose_name = "Corte de ejecución de gastos"
        verbose_name_plural = "Cortes de ejecución de gastos"
        ordering = ("-vigencia", "-fecha_fin", "-fecha_inicio")
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "fecha_inicio", "fecha_fin"],
                                    name="un_corte_por_vigencia_y_rango"),
        ]

    def clean(self):
        errores = {}
        for campo in ("fecha_inicio", "fecha_fin"):
            valor = getattr(self, campo)
            if self.vigencia and valor and valor.year != self.vigencia:
                errores[campo] = f"La fecha debe estar dentro de la vigencia {self.vigencia}."
        if self.fecha_inicio and self.fecha_fin and self.fecha_inicio > self.fecha_fin:
            errores["fecha_fin"] = "La fecha de fin no puede ser anterior a la de inicio."
        if self.fecha_fin and self.fecha_descarga and self.fecha_descarga < self.fecha_fin:
            errores["fecha_descarga"] = "El reporte no se pudo descargar antes de la fecha de fin del corte."
        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"Ejecución de gastos {self.vigencia} del {self.fecha_inicio:%d/%m/%Y} al {self.fecha_fin:%d/%m/%Y}"


class FilaEjecucionGastos(Fechas):
    """Una fila de detalle del reporte: rubro x recurso x centro de costo x proyecto.

    Los subtotales del arbol de rubros no se guardan: la carga comprueba que cuadren con
    el detalle. RUBRO_ID es el id del rubro en SIIFWEB, distinto en cada vigencia; hace
    falta en la llave porque un reporte puede traer el arbol de otra vigencia (el de 2023
    trae filas del de 2022) con los mismos codigos.
    """
    corte = models.ForeignKey(CorteEjecucionGastos, on_delete=models.CASCADE, related_name="filas_ejecucion")
    rubro_id_siifweb = models.IntegerField(verbose_name="RUBRO_ID")
    de_otra_vigencia = models.BooleanField(
        default=False, verbose_name="Árbol de otra vigencia",
        help_text="La fila cuelga de un árbol de rubros distinto al de la vigencia del reporte")
    rubro = models.CharField(max_length=40)
    nombre_rubro = models.CharField(max_length=255, blank=True)
    recurso = models.CharField(max_length=10)
    nombre_recurso = models.CharField(max_length=255, blank=True)
    centro_costo = models.CharField(max_length=10, verbose_name="Centro de costo")
    nombre_centro_costo = models.CharField(max_length=255, blank=True, verbose_name="Nombre del centro de costo")
    proyecto = models.CharField(max_length=20, help_text="BPIN; 0 = sin proyecto")

    apropiacion_inicial = models.DecimalField(max_digits=20, decimal_places=2)
    adicion = models.DecimalField(max_digits=20, decimal_places=2)
    disminucion = models.DecimalField(max_digits=20, decimal_places=2)
    credito = models.DecimalField(max_digits=20, decimal_places=2)
    contracredito = models.DecimalField(max_digits=20, decimal_places=2)
    aplazamientos = models.DecimalField(max_digits=20, decimal_places=2)
    desaplazamientos = models.DecimalField(max_digits=20, decimal_places=2)
    apropiacion_definitiva = models.DecimalField(max_digits=20, decimal_places=2)
    solicitud_tramite = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Solicitud en trámite")
    cdp = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="CDP")
    rp = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="RP")
    obligacion = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Obligación")
    pago = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        verbose_name = "Fila de ejecución de gastos"
        verbose_name_plural = "Filas de ejecución de gastos"
        constraints = [
            models.UniqueConstraint(fields=["corte", "rubro_id_siifweb", "recurso", "centro_costo", "proyecto"],
                                    name="fila_unica_por_corte"),
        ]

    def __str__(self):
        return f"{self.rubro} · {self.recurso} · CC {self.centro_costo} · {self.proyecto}"


# ---------------------------------------------------------------------------
# Listas CHIP del CUIPO (Listas_Categoria_CUIPO_MM-AAAA.xlsx)
# ---------------------------------------------------------------------------

class VersionListas(Fechas):
    """Una version de las listas de la categoria CUIPO que publica la Contaduria.

    Cada importacion actualiza los catalogos por codigo: lo nuevo se crea, lo que cambia se
    actualiza y lo que ya no viene queda inactivo (nunca se borra, porque una distribucion
    vieja puede estar usandolo).
    """

    class Estado(models.TextChoices):
        PENDIENTE = "P", "Pendiente"
        PROCESADO = "OK", "Procesado"
        ERROR = "E", "Con error"

    nombre = models.CharField(max_length=20, unique=True, help_text='Por ejemplo "09-2026"')
    archivo = models.FileField(upload_to="cuipo/listas/", blank=True,
                               help_text="Listas_Categoria_CUIPO_MM-AAAA.xlsx de la Contaduría")
    hash = models.CharField(max_length=64, blank=True, verbose_name="Hash del archivo")
    cargado_por = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="versiones_listas_cuipo", verbose_name="Cargado por")
    estado = models.CharField(max_length=2, choices=Estado.choices, default=Estado.PENDIENTE)
    mensaje = models.TextField(blank=True, verbose_name="Resultado de la importación")

    class Meta:
        verbose_name = "Versión de las listas CHIP"
        verbose_name_plural = "Versiones de las listas CHIP"
        ordering = ("-fecha_creacion",)

    def __str__(self):
        return f"Listas CUIPO {self.nombre}"


class CatalogoCHIP(Fechas):
    """Base de las listas CHIP: codigo exacto como texto, descripcion y si sigue vigente."""
    codigo = models.CharField(max_length=40, unique=True)
    descripcion = models.TextField(verbose_name="Descripción")
    activo = models.BooleanField(default=True, help_text="Vino en la última versión importada")
    version = models.ForeignKey(VersionListas, on_delete=models.PROTECT, related_name="+",
                                verbose_name="Versión", help_text="Última versión que lo trajo")

    class Meta:
        abstract = True
        ordering = ("codigo",)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class ConceptoCUIPO(CatalogoCHIP):
    class Nivel(models.TextChoices):
        SUMA = "S", "Suma (agrupa)"
        DETALLE = "D", "Detalle"

    nivel = models.CharField(max_length=1, choices=Nivel.choices)
    habilitado_departamentos = models.BooleanField(
        default=False, verbose_name="Habilitado para departamentos", help_text='Columna "438 - DEPARTAMENTOS"')
    requiere_cpc = models.BooleanField(default=False, verbose_name="Requiere CPC",
                                       help_text='Está en la hoja "Conceptos_CPC"')
    notas = models.TextField(blank=True)

    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Concepto CUIPO"
        verbose_name_plural = "Conceptos CUIPO"


class FuenteCUIPO(CatalogoCHIP):
    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Fuente CUIPO"
        verbose_name_plural = "Fuentes CUIPO"


class SeccionPresupuestal(CatalogoCHIP):
    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Sección presupuestal"
        verbose_name_plural = "Secciones presupuestales"


class VigenciaGasto(CatalogoCHIP):
    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Vigencia del gasto"
        verbose_name_plural = "Vigencias del gasto"


class ProductoCUIPO(CatalogoCHIP):
    """Producto MGA de la lista CHIP. Lleva sufijo para no confundirse con siifweb.ProductoMGA."""
    sector = models.CharField(max_length=255, blank=True)
    programa = models.TextField(blank=True)
    aplica_territoriales = models.CharField(
        max_length=50, blank=True, verbose_name="Aplica a entidades territoriales",
        help_text="Como viene en la lista: en la de 09-2026 solo dice \"Nuevo\" en 4 productos")

    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Producto MGA (CHIP)"
        verbose_name_plural = "Productos MGA (CHIP)"


class CPC(CatalogoCHIP):
    seccion = models.CharField(max_length=255, blank=True, verbose_name="Sección")
    division = models.CharField(max_length=255, blank=True, verbose_name="División")

    class Meta(CatalogoCHIP.Meta):
        verbose_name = "CPC"
        verbose_name_plural = "CPC"


class DetalleSectorial(CatalogoCHIP):
    grupo = models.CharField(max_length=255, blank=True, verbose_name="Grupo concepto")
    sector = models.CharField(max_length=255, blank=True)

    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Detalle sectorial"
        verbose_name_plural = "Detalles sectoriales"


class SituacionFondos(CatalogoCHIP):
    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Situación de fondos"
        verbose_name_plural = "Situaciones de fondos"


class PoliticaPublica(CatalogoCHIP):
    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Política pública"
        verbose_name_plural = "Políticas públicas"


class TerceroCUIPO(CatalogoCHIP):
    """Tercero de la lista CHIP. Lleva sufijo para no confundirse con siifweb.Tercero."""

    class Meta(CatalogoCHIP.Meta):
        verbose_name = "Tercero CUIPO"
        verbose_name_plural = "Terceros CUIPO"


# ---------------------------------------------------------------------------
# Homologaciones y reglas: de la fila de ejecucion de SIIFWEB a los codigos CHIP
# ---------------------------------------------------------------------------
# Las tablas apuntan a los catalogos de siifweb (Fuente, Rubro, CentroCosto) y a las listas
# CHIP; los modelos de siifweb no se tocan. La fila de ejecucion trae los codigos como texto
# y se cruza con ellos por codigo (cuipo/derivacion.py).

class HomologacionFuente(Fechas):
    """Recurso de SIIFWEB -> fuente CUIPO, por vigencia. Sin ella la fila no se puede reportar.

    Son muchos a uno (62 recursos -> 28 fuentes en 2026) y no se deduce del nombre del
    recurso: en 20 de ellos el codigo que trae el nombre no es la fuente correcta.
    """
    fuente_siifweb = models.ForeignKey(Fuente, on_delete=models.PROTECT, related_name="homologaciones_cuipo",
                                       verbose_name="Recurso SIIFWEB")
    fuente_cuipo = models.ForeignKey(FuenteCUIPO, on_delete=models.PROTECT, related_name="homologaciones",
                                     verbose_name="Fuente CUIPO")
    vigencia = models.IntegerField(choices=listado_vigencias)
    observacion = models.TextField(blank=True, verbose_name="Observación")
    validado_por = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="homologaciones_fuente_cuipo", verbose_name="Validado por")
    fecha_validacion = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de validación")

    class Meta:
        verbose_name = "Homologación de fuente"
        verbose_name_plural = "Homologación de fuentes"
        ordering = ("-vigencia", "fuente_siifweb__codigo")
        constraints = [
            models.UniqueConstraint(fields=["fuente_siifweb", "vigencia"], name="homologacion_fuente_por_vigencia"),
        ]

    def __str__(self):
        return f"{self.vigencia}: recurso {self.fuente_siifweb.codigo} -> {self.fuente_cuipo.codigo}"


class HomologacionRubro(Fechas):
    """Excepciones: el rubro de SIIFWEB que se reporta con otro concepto CUIPO.

    Sin excepcion, el concepto es el mismo codigo del rubro si existe en las listas y esta
    habilitado para departamentos (ej. 2.3.3.05.09.054 no lo esta y va como 2.3.3.05.09.099).
    """
    rubro = models.OneToOneField(Rubro, on_delete=models.PROTECT, related_name="homologacion_cuipo",
                                 verbose_name="Rubro SIIFWEB")
    concepto = models.ForeignKey(ConceptoCUIPO, on_delete=models.PROTECT, related_name="homologaciones",
                                 verbose_name="Concepto CUIPO")
    observacion = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Homologación de rubro"
        verbose_name_plural = "Homologación de rubros"
        ordering = ("rubro__codigo",)

    def __str__(self):
        return f"{self.rubro.codigo} -> {self.concepto.codigo}"


class ReglaSeccion(Fechas):
    """Centro de costo de la fila -> seccion presupuestal. Sin regla: 16.0 (administracion central)."""
    centro_costo = models.OneToOneField(CentroCosto, on_delete=models.PROTECT, related_name="regla_seccion_cuipo",
                                        verbose_name="Centro de costo")
    seccion = models.ForeignKey(SeccionPresupuestal, on_delete=models.PROTECT, related_name="reglas",
                                verbose_name="Sección presupuestal")
    observacion = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Regla de sección"
        verbose_name_plural = "Reglas de sección"
        ordering = ("centro_costo__codigo",)

    def __str__(self):
        return f"Centro de costo {self.centro_costo.codigo} -> {self.seccion.codigo}"


class ReglaTercero(Fechas):
    """Tercero CHIP por rubro o por centro de costo. Si una fila cumple las dos, gana la del rubro.

    Sin regla, el tercero es 1 - NO APLICA (asi va en la mayoria de lineas de inversion).
    """
    rubro = models.OneToOneField(Rubro, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="regla_tercero_cuipo", verbose_name="Rubro SIIFWEB")
    centro_costo = models.OneToOneField(CentroCosto, on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="regla_tercero_cuipo", verbose_name="Centro de costo")
    tercero = models.ForeignKey(TerceroCUIPO, on_delete=models.PROTECT, related_name="reglas")
    observacion = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Regla de tercero"
        verbose_name_plural = "Reglas de tercero"
        ordering = ("rubro__codigo", "centro_costo__codigo")
        constraints = [
            models.CheckConstraint(
                condition=Q(rubro__isnull=False, centro_costo__isnull=True)
                | Q(rubro__isnull=True, centro_costo__isnull=False),
                name="regla_tercero_por_rubro_o_por_centro"),
        ]

    def clean(self):
        if (self.rubro_id is None) == (self.centro_costo_id is None):
            raise ValidationError("La regla va por rubro o por centro de costo: uno de los dos, no ambos.")

    def __str__(self):
        cual = f"rubro {self.rubro.codigo}" if self.rubro_id else f"centro de costo {self.centro_costo.codigo}"
        return f"{cual} -> {self.tercero.codigo}"


class ReglaSituacionFondos(Fechas):
    """Prefijo de rubro (+ fuente CUIPO opcional) -> situacion de fondos. Sin regla: C.

    Gana la regla de prefijo mas largo y, a igual prefijo, la que nombra la fuente.
    Ejemplo: 2.3.1.01.02.001 con 1.2.4.1.01 (SGP educacion) -> S.
    """
    prefijo_rubro = models.CharField(max_length=40, verbose_name="Prefijo del rubro",
                                     help_text="El rubro o el comienzo de su código, por ejemplo 2.3.1.01.02.001")
    fuente_cuipo = models.ForeignKey(FuenteCUIPO, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="reglas_situacion", verbose_name="Fuente CUIPO",
                                     help_text="Vacía: aplica a cualquier fuente")
    situacion = models.ForeignKey(SituacionFondos, on_delete=models.PROTECT, related_name="reglas",
                                  verbose_name="Situación de fondos")
    observacion = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Regla de situación de fondos"
        verbose_name_plural = "Reglas de situación de fondos"
        ordering = ("prefijo_rubro",)
        constraints = [
            models.UniqueConstraint(fields=["prefijo_rubro", "fuente_cuipo"], name="regla_situacion_unica"),
            models.UniqueConstraint(fields=["prefijo_rubro"], condition=Q(fuente_cuipo__isnull=True),
                                    name="regla_situacion_unica_sin_fuente"),
        ]

    def save(self, *args, **kwargs):
        self.prefijo_rubro = self.prefijo_rubro.strip().rstrip(".")
        super().save(*args, **kwargs)

    def __str__(self):
        fuente = f" con {self.fuente_cuipo.codigo}" if self.fuente_cuipo_id else ""
        return f"{self.prefijo_rubro}{fuente} -> {self.situacion.codigo}"

