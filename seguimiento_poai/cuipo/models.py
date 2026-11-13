"""Insumos del reporte CUIPO.

La ejecucion de gastos de SIIFWEB ("estado_ppto_gasto_gobatl_fyccw") se guarda por corte
y solo la usa el CUIPO: no alimenta la ficha, el tablero ni los catalogos de siifweb. Por
eso los codigos van como texto, tal como vienen en el reporte, y no como llaves a Rubro,
Fuente, CentroCosto o Proyecto (que la carga tendria que crear si faltaran).
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from siifweb.models import Fechas, listado_vigencias


class CorteEjecucionGastos(Fechas):
    """Un reporte de ejecucion de gastos con su fecha de corte.

    Cada corte se conserva: cargar el de octubre no toca el de septiembre, y el CUIPO de
    un trimestre se puede volver a generar con el mismo insumo.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "P", "Pendiente"
        PROCESADO = "OK", "Procesado"
        ERROR = "E", "Con error"

    vigencia = models.IntegerField(choices=listado_vigencias)
    fecha_corte = models.DateField(
        verbose_name="Fecha de corte",
        help_text="Fecha final del rango con que se descargó el reporte, que empieza el 1 de enero de la "
                  "vigencia. Para una vigencia cerrada, el 31 de diciembre")
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
        ordering = ("-vigencia", "-fecha_corte")
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "fecha_corte"], name="un_corte_por_vigencia_y_fecha"),
        ]

    def clean(self):
        errores = {}
        if self.vigencia and self.fecha_corte and self.fecha_corte.year != self.vigencia:
            errores["fecha_corte"] = f"La fecha de corte debe estar dentro de la vigencia {self.vigencia}."
        if self.fecha_corte and self.fecha_descarga and self.fecha_descarga < self.fecha_corte:
            errores["fecha_descarga"] = "El reporte no se pudo descargar antes de su fecha de corte."
        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"Ejecución de gastos {self.vigencia} al {self.fecha_corte:%d/%m/%Y}"


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
