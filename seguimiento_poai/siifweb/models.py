from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Sum


def listado_vigencias():
    year = timezone.localdate().year
    return [(y, y) for y in range(2017, year + 1)]


# 0 - Operación

class Fechas(models.Model):
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CargaReporte(Fechas):
    class TipoReporte(models.TextChoices):
        CDP = "cdp", _("Consolidado de disponibilidades")
        COMPROMISOS = "compromisos", _("Consolidado de compromisos")
        OBLIGACIONES = "obligaciones", _("Consolidado de obligaciones")
        RESERVAS = "reservas", _("Consolidado de reservas")
        HISTORIAL = "historial", _("Historial de orden de gasto 2 (rango completo)")
        POAI = "poai", _("Cruce proyectos POAI (opcional: nombre, dependencia y clasificacion)")

    class Estado(models.TextChoices):
        PENDIENTE = "P", _("Pendiente")
        PROCESADO = "OK", _("Procesado")
        ERROR = "E", _("Con error")

    tipo_reporte = models.CharField(max_length=20, choices=TipoReporte.choices, verbose_name="Tipo de reporte")
    archivo = models.FileField(upload_to="reportes/", verbose_name="Archivo")
    fecha_descarga = models.DateField(verbose_name="Fecha de descarga", default=timezone.localdate,
                                      help_text="Los saldos del reporte son la foto de este dia")
    vigencia = models.IntegerField(verbose_name="Vigencia", null=True, blank=True, choices=listado_vigencias,
                                   help_text="Dejar vacia en el historial de ordenes de gasto 2: "
                                             "se descarga por rango completo, no por vigencia")
    filas = models.IntegerField(verbose_name="Numero de filas", default=0)
    hash = models.CharField(max_length=64, unique=True, blank=True, verbose_name="Hash del archivo",
                            help_text="Detecta recargas del mismo archivo")
    estado = models.CharField(max_length=2, choices=Estado.choices, default=Estado.PENDIENTE, verbose_name="Estado")
    mensaje = models.TextField(blank=True, verbose_name="Resultado del proceso")

    class Meta:
        verbose_name = "Carga del reporte"
        verbose_name_plural = "Cargas del reporte"

    def __str__(self):
        return f"{self.get_tipo_reporte_display()} {self.vigencia or ''} - {self.fecha_descarga} ({self.filas} filas)"


# Grupo 1 - Dimensiones

class Rubro(Fechas):
    class TipoRubro(models.TextChoices):
        INGRESO = "I", _("Ingreso")
        GASTO = "G", _("Gasto")

    codigo = models.CharField(max_length=30, verbose_name="Codigo", unique=True)
    nombre = models.CharField(max_length=255, verbose_name="Nombre")
    tipo = models.CharField(max_length=1, choices=TipoRubro.choices)

    class Meta:
        verbose_name = "Rubro"
        verbose_name_plural = "Rubros"

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Fuente(Fechas):
    codigo = models.CharField(max_length=5, verbose_name="Codigo", unique=True)
    nombre = models.CharField(max_length=255, verbose_name="Nombre")

    class Meta:
        verbose_name = "Fuente"
        verbose_name_plural = "Fuentes"

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class CentroCosto(Fechas):
    codigo = models.CharField(max_length=5, verbose_name="Codigo", unique=True)
    nombre = models.CharField(max_length=255, verbose_name="Nombre")

    class Meta:
        verbose_name = "Dependencia"
        verbose_name_plural = "Dependencias"

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class DependenciaResponsable(Fechas):
    """Quien responde por el proyecto segun el POAI.

    No es la misma dimension que CentroCosto: aquella es quien ejecuta el gasto en
    SIIFWEB. Ojo, estos nombres llevan comas internas ("Mujer, Juventud, e Inclusion
    Social"), asi que NO se pueden partir por coma.
    """
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Dependencia responsable"
        verbose_name_plural = "Dependencias responsables"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class Clasificacion(Fechas):
    """Como se financia el proyecto: POAI, regalias, vigencias futuras, recursos del
    balance... Un proyecto puede tener varias a la vez, por eso la relacion es M2M:
    en el reporte llegan en una sola celda separadas por coma."""
    nombre = models.CharField(max_length=120, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Clasificacion"
        verbose_name_plural = "Clasificaciones"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class Proyecto(Fechas):
    class Origen(models.TextChoices):
        MANUAL = "manual", _("Ingresado por el equipo")
        SIIFWEB = "siifweb", _("Detectado en un reporte de SIIFWEB")
        POAI = "poai", _("Cruce POAI")

    bpin = models.CharField(max_length=25, verbose_name="BPIN", blank=True, null=True, unique=True,
                            help_text="BPIN. Se normaliza al guardar: sin espacios ni sufijo .0")
    nombre = models.TextField(verbose_name="Nombre", blank=True, null=True)
    dependencia = models.ForeignKey(CentroCosto, null=True, blank=True, on_delete=models.PROTECT,
                                    verbose_name="Dependencia (SIIFWEB)", related_name="proyectos",
                                    help_text="Centro de costo que ejecuta, segun SIIFWEB")
    # Del cruce POAI: no existen en SIIFWEB y la dependencia difiere de la ejecutora
    dependencia_responsable = models.ForeignKey(DependenciaResponsable, null=True, blank=True,
                                                on_delete=models.PROTECT, related_name="proyectos",
                                                verbose_name="Dependencia responsable (POAI)",
                                                help_text="Quien responde por el proyecto; "
                                                          "puede diferir de la que ejecuta en SIIFWEB")
    clasificaciones = models.ManyToManyField(Clasificacion, blank=True, related_name="proyectos",
                                             verbose_name="Clasificaciones (POAI)",
                                             help_text="Un proyecto puede tener varias: "
                                                       "POAI 2026 y Recursos del Balance, por ejemplo")
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.MANUAL,
                              verbose_name="Origen del registro",
                              help_text="Como entro el proyecto al sistema")

    class Meta:
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"

    def save(self, *args, **kwargs):
        # El BPIN es la llave con la que las cargas enganchan la ejecucion.
        # Si el equipo lo teclea con espacios o Excel le deja un ".0", no cruzaria.
        if self.bpin:
            self.bpin = str(self.bpin).strip().removesuffix(".0")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bpin} - {self.nombre or ''}"


class Tercero(Fechas):
    codigo = models.CharField(max_length=30, verbose_name="Codigo", blank=True, null=True, unique=True)
    nombre = models.TextField(verbose_name="Nombre", blank=True, null=True)

    class Meta:
        verbose_name = "Tercero"
        verbose_name_plural = "Terceros"

    def __str__(self):
        return f"{self.codigo} - {self.nombre or ''}"


class OrdenGasto(Fechas):
    nombre = models.TextField(verbose_name="Nombre")

    class Meta:
        verbose_name = "Tipo de orden de gasto"
        verbose_name_plural = "Tipos de orden de gasto"

    def __str__(self):
        return f"{self.nombre}"


# Grupo 2 - Documentos presupuestales

class Cdp(Fechas):
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.PROTECT, related_name="cdps",
                                     verbose_name="Dependencia")
    vigencia = models.IntegerField(choices=listado_vigencias)
    nro_cdp = models.CharField(max_length=20, verbose_name="Numero")
    fecha_disp = models.DateField(verbose_name="Fecha expedicion CDP")
    objeto_cert = models.TextField(verbose_name="Objeto", blank=True)

    class Meta:
        verbose_name = "Disponibilidad"
        verbose_name_plural = "Disponibilidades"
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "nro_cdp"], name="cdp_unico_por_vigencia")
        ]

    def __str__(self):
        return f"{self.vigencia} - {self.nro_cdp} - {self.fecha_disp}"


class CdpImputacion(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="cdps_imputados", null=True, blank=True,
                                on_delete=models.PROTECT)
    cdp = models.ForeignKey(Cdp, on_delete=models.PROTECT, related_name="cdps_imputados")
    rubro = models.ForeignKey(Rubro, on_delete=models.PROTECT, related_name="cdps_imputados")
    fuente = models.ForeignKey(Fuente, on_delete=models.PROTECT, related_name="cdps_imputados")
    proyecto = models.ForeignKey(Proyecto, on_delete=models.PROTECT, related_name="cdps_imputados",
                                 null=True, blank=True)
    valor_certificado = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor certificado")
    valor_disponibilidad_def = models.DecimalField(max_digits=20, decimal_places=2,
                                                   verbose_name="Valor disponibilidad definitiva")
    saldo_certf = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Saldo certificado",
                                      blank=True, null=True)
    saldo_calculado = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Saldo calculado",
                                          blank=True, null=True,
                                          help_text="Calculado desde la relacion para comprobar el de SIIFWEB")

    class Meta:
        verbose_name = "Imputacion del CDP"
        verbose_name_plural = "Imputacion de los CDPs"

    def actualizar_saldo(self):
        comprometido = CompromisoImputacion.objects.filter(
            cdp=self.cdp, rubro=self.rubro, fuente=self.fuente, proyecto=self.proyecto
        ).aggregate(total=Sum("valor_compromiso_def"))["total"] or 0
        self.saldo_calculado = self.valor_disponibilidad_def - comprometido
        self.save(update_fields=["saldo_calculado"])

    def __str__(self):
        proyecto = self.proyecto.nombre if self.proyecto else "sin proyecto"
        return f"{self.cdp.nro_cdp} - {self.rubro.codigo}: {self.rubro.nombre} - {self.fuente.nombre} - {proyecto}"


class Compromiso(Fechas):
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.PROTECT, related_name="compromisos",
                                     verbose_name="Dependencia")
    vigencia = models.IntegerField(choices=listado_vigencias)
    nro_rp = models.CharField(max_length=20, verbose_name="Numero")
    fecha_reg = models.DateField(verbose_name="Fecha expedicion RP")
    acto_admon = models.TextField(verbose_name="Acto administrativo", blank=True)
    objeto_reg = models.TextField(verbose_name="Objeto del registro", blank=True)

    class Meta:
        verbose_name = "Compromiso"
        verbose_name_plural = "Compromisos"
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "nro_rp"], name="rp_unico_por_vigencia")
        ]

    def __str__(self):
        return f"{self.vigencia} - {self.nro_rp} - {self.fecha_reg}"


class CompromisoImputacion(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="compromisos_imputados", null=True, blank=True,
                                on_delete=models.PROTECT)
    compromiso = models.ForeignKey(Compromiso, on_delete=models.PROTECT, related_name="compromisos_imputados")
    cdp = models.ForeignKey(Cdp, on_delete=models.PROTECT, related_name="compromisos_imputados")
    rubro = models.ForeignKey(Rubro, on_delete=models.PROTECT, related_name="compromisos_imputados")
    fuente = models.ForeignKey(Fuente, on_delete=models.PROTECT, related_name="compromisos_imputados")
    proyecto = models.ForeignKey(Proyecto, on_delete=models.PROTECT, related_name="compromisos_imputados",
                                 null=True, blank=True)
    valor_registro = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor registro")
    valor_compromiso_def = models.DecimalField(max_digits=20, decimal_places=2,
                                               verbose_name="Valor compromiso definitivo")
    saldo_rp = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Saldo compromiso")
    saldo_rp_calculado = models.DecimalField(max_digits=20, decimal_places=2,
                                             verbose_name="Saldo compromiso calculado", blank=True, null=True,
                                             help_text="Calculado desde la relacion para comprobar el de SIIFWEB")

    class Meta:
        verbose_name = "Imputacion del compromiso"
        verbose_name_plural = "Imputacion de los compromisos"

    def actualizar_saldo(self):
        obligado = ObligacionImputacion.objects.filter(
            compromiso=self.compromiso, rubro=self.rubro, fuente=self.fuente, proyecto=self.proyecto
        ).aggregate(total=Sum("valor_obligacion"))["total"] or 0
        self.saldo_rp_calculado = self.valor_compromiso_def - obligado
        self.save(update_fields=["saldo_rp_calculado"])

    def __str__(self):
        proyecto = self.proyecto.nombre if self.proyecto else "sin proyecto"
        return f"{self.cdp.nro_cdp} - {self.compromiso.nro_rp} - {self.rubro.codigo} - {proyecto}"


class Obligacion(Fechas):
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.PROTECT, related_name="obligaciones",
                                     verbose_name="Dependencia")
    tipo_orden_gasto = models.ForeignKey(OrdenGasto, on_delete=models.PROTECT, related_name="obligaciones",
                                         verbose_name="Tipo de orden de gasto")
    vigencia = models.IntegerField(choices=listado_vigencias)
    nro_obligacion = models.CharField(max_length=20, verbose_name="Numero")
    fecha_obli = models.DateField(verbose_name="Fecha obligacion")
    nro_orden_gasto = models.CharField(max_length=20, verbose_name="Numero de contrato asociado",
                                       null=True, blank=True)
    prefijo_orden = models.CharField(max_length=20, verbose_name="Vigencia del contrato", null=True, blank=True)
    orden_pago = models.CharField(max_length=20, verbose_name="Numero de orden de pago", null=True, blank=True)

    class Meta:
        verbose_name = "Obligacion"
        verbose_name_plural = "Obligaciones"
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "nro_obligacion"], name="obligacion_unica_por_vigencia")
        ]

    def __str__(self):
        return f"{self.vigencia} - {self.nro_obligacion} - {self.fecha_obli}"


class ObligacionImputacion(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="obligaciones_imputadas", null=True, blank=True,
                                on_delete=models.PROTECT)
    obligacion = models.ForeignKey(Obligacion, on_delete=models.PROTECT, related_name="obligaciones_imputadas")
    compromiso = models.ForeignKey(Compromiso, on_delete=models.PROTECT, related_name="obligaciones_imputadas")
    rubro = models.ForeignKey(Rubro, on_delete=models.PROTECT, related_name="obligaciones_imputadas")
    fuente = models.ForeignKey(Fuente, on_delete=models.PROTECT, related_name="obligaciones_imputadas")
    proyecto = models.ForeignKey(Proyecto, on_delete=models.PROTECT, related_name="obligaciones_imputadas",
                                 blank=True, null=True)
    valor_obligacion = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor obligacion")
    saldo_obli = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Saldo obligacion")
    pagos = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Pagos")
    saldo_obli_calculado = models.DecimalField(max_digits=20, decimal_places=2,
                                               verbose_name="Saldo obligacion calculado", blank=True, null=True,
                                               help_text="Calculado para comprobar el de SIIFWEB")

    class Meta:
        verbose_name = "Imputacion de la obligacion"
        verbose_name_plural = "Imputacion de las obligaciones"

    def actualizar_saldo(self):
        # No hay tabla hija de pagos: se valida la aritmetica del propio reporte
        self.saldo_obli_calculado = self.valor_obligacion - self.pagos
        self.save(update_fields=["saldo_obli_calculado"])

    def __str__(self):
        proyecto = self.proyecto.nombre if self.proyecto else "sin proyecto"
        return f"{self.obligacion.nro_obligacion} - {self.compromiso.nro_rp} - {self.rubro.codigo} - {proyecto}"


# 3. Cierre (reservas y cuentas por pagar)

class Reserva(Fechas):
    vigencia = models.IntegerField(choices=listado_vigencias, verbose_name="Vigencia de constitucion")
    nro_reserva = models.CharField(max_length=20, verbose_name="Numero")
    fecha_reserva = models.DateField(verbose_name="Fecha de reserva")
    beneficiario = models.ForeignKey(Tercero, related_name="reservas", on_delete=models.PROTECT)
    objeto_reserva = models.TextField(verbose_name="Objeto de la reserva", blank=True)
    acto_admon = models.TextField(verbose_name="Acto administrativo", blank=True)

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        constraints = [
            models.UniqueConstraint(fields=["vigencia", "nro_reserva"], name="reserva_unica_por_vigencia")
        ]

    def __str__(self):
        return f"{self.vigencia} - {self.nro_reserva} - {self.fecha_reserva}"


class ReservaImputacion(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="reservas_imputadas", null=True, blank=True,
                                on_delete=models.PROTECT)
    reserva = models.ForeignKey(Reserva, related_name="reservas_imputadas", on_delete=models.PROTECT,
                                verbose_name="Reserva")
    cdp_origen = models.ForeignKey(Cdp, related_name="reservas_imputadas", on_delete=models.PROTECT,
                                   verbose_name="CDP de origen", null=True, blank=True,
                                   help_text="CDP de la vigencia anterior")
    rubro = models.ForeignKey(Rubro, related_name="reservas_imputadas", on_delete=models.PROTECT)
    fuente = models.ForeignKey(Fuente, related_name="reservas_imputadas", on_delete=models.PROTECT)
    proyecto = models.ForeignKey(Proyecto, related_name="reservas_imputadas", on_delete=models.PROTECT,
                                 null=True, blank=True)
    valor_reserva = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor reserva")
    valor_reserva_def = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor reserva definitiva")
    obligaciones_reserva = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Obligaciones reserva")
    pagos_reserva = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Pagos reserva")
    saldo_reserva = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Saldo reserva")

    class Meta:
        verbose_name = "Reserva imputada"
        verbose_name_plural = "Reservas imputadas"

    def __str__(self):
        proyecto = self.proyecto.nombre if self.proyecto else "sin proyecto"
        return f"{self.reserva.nro_reserva} - {self.rubro.codigo} - {self.fuente.nombre} - {proyecto}"


# 4. Contractual (del historial de orden de gasto)
# El contrato NO lleva vigencia en la llave: cruza anios. La vigencia entra por la imputacion.

class Contrato(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="contratos", null=True, blank=True,
                                on_delete=models.PROTECT)
    tipo_contrato = models.CharField(max_length=250, verbose_name="Tipo de contrato")
    nro_contrato = models.CharField(max_length=250, verbose_name="Numero de contrato")
    fecha_firma = models.DateField(verbose_name="Fecha de firma")
    tercero = models.ForeignKey(Tercero, related_name="contratos", on_delete=models.PROTECT,
                                verbose_name="Contratista")
    interventor = models.CharField(max_length=250, verbose_name="Interventor", blank=True, null=True)
    descripcion = models.TextField(verbose_name="Descripcion", blank=True, null=True)
    valor_contrato = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor",
                                         blank=True, null=True)
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio", blank=True, null=True)
    fecha_final = models.DateField(verbose_name="Fecha final", blank=True, null=True)
    dependencia = models.ForeignKey(CentroCosto, related_name="contratos", verbose_name="Dependencia",
                                    on_delete=models.PROTECT, blank=True, null=True)

    class Meta:
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        constraints = [
            models.UniqueConstraint(fields=["tipo_contrato", "nro_contrato", "fecha_firma", "tercero"],
                                    name="contrato_unico")
        ]

    def __str__(self):
        return f"{self.tipo_contrato} {self.nro_contrato} ({self.fecha_firma}) - {self.tercero.nombre or ''}"


class ContratoActa(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="actas", null=True, blank=True,
                                on_delete=models.PROTECT)
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="actas_del_contrato",
                                 verbose_name="Contrato")
    nro_orden = models.CharField(max_length=20, verbose_name="Numero de orden", blank=True)
    tipo_orden = models.CharField(max_length=250, verbose_name="Tipo de orden", blank=True)
    concepto = models.TextField(verbose_name="Concepto", blank=True)
    fecha_pago = models.DateField(verbose_name="Fecha de pago", null=True, blank=True)
    nrodoc_acta = models.CharField(max_length=20, verbose_name="Numero de documento acta", blank=True)
    valor_pago = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor")

    class Meta:
        verbose_name = "Acta del contrato"
        verbose_name_plural = "Actas del contrato"

    def __str__(self):
        return f"{self.contrato.nro_contrato} - acta {self.nrodoc_acta} - {self.fecha_pago}"


class ContratoImputacion(Fechas):
    reporte = models.ForeignKey(CargaReporte, related_name="imputaciones_del_contrato", null=True, blank=True,
                                on_delete=models.PROTECT)
    vigencia = models.IntegerField(choices=listado_vigencias, verbose_name="Vigencia", null=True, blank=True)
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="imputaciones_del_contrato",
                                 verbose_name="Contrato")
    compromiso = models.ForeignKey(Compromiso, on_delete=models.PROTECT, related_name="imputaciones_del_contrato",
                                   null=True, blank=True, verbose_name="Compromiso (RP)")
    nro_comprobante = models.CharField(max_length=20, verbose_name="Comprobante presupuestal", blank=True,
                                       help_text="Ancla a la bitacora")
    rubro = models.ForeignKey(Rubro, related_name="imputaciones_del_contrato", on_delete=models.PROTECT)
    fuente = models.ForeignKey(Fuente, related_name="imputaciones_del_contrato", on_delete=models.PROTECT)
    proyecto = models.ForeignKey(Proyecto, on_delete=models.PROTECT, related_name="imputaciones_del_contrato",
                                 null=True, blank=True)

    class Meta:
        verbose_name = "Imputacion del contrato"
        verbose_name_plural = "Imputaciones del contrato"

    def __str__(self):
        rp = self.compromiso.nro_rp if self.compromiso else "sin RP"
        proyecto = self.proyecto.nombre if self.proyecto else "sin proyecto"
        return f"{self.vigencia} - {self.contrato.nro_contrato} - RP {rp} - {self.rubro.codigo} - {proyecto}"


