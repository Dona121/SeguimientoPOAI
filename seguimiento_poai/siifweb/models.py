from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _


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
        # Ya no se carga (octubre de 2026): queda para que las cargas viejas se lean con
        # su nombre. El formulario no lo ofrece y no tiene cargador.
        POAI = "poai", _("Cruce proyectos POAI (opcional: nombre, dependencia y clasificacion)")
        SECOP = "secop", _("Consolidado BPIN por proceso de SECOP II (rango completo)")

    class Estado(models.TextChoices):
        PENDIENTE = "P", _("Pendiente")
        PROCESADO = "OK", _("Procesado")
        ERROR = "E", _("Con error")

    tipo_reporte = models.CharField(max_length=20, choices=TipoReporte.choices, verbose_name="Tipo de reporte")
    archivo = models.FileField(upload_to="reportes/", verbose_name="Archivo")
    fecha_descarga = models.DateField(verbose_name="Fecha de descarga", default=timezone.localdate,
                                      help_text="Los saldos del reporte son la foto de este dia")
    vigencia = models.IntegerField(verbose_name="Vigencia", null=True, blank=True, choices=listado_vigencias,
                                   help_text="Dejar vacia en el historial de ordenes de gasto 2 y en "
                                             "el consolidado de SECOP II: se descargan por rango "
                                             "completo, no por vigencia")
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

    bpin = models.CharField(max_length=25, verbose_name="BPIN", blank=True, null=True, unique=True)
    nombre = models.TextField(verbose_name="Nombre", blank=True, null=True)
    # El centro de costo que ejecuta el gasto, segun SIIFWEB
    dependencia = models.ForeignKey(CentroCosto, null=True, blank=True, on_delete=models.PROTECT,
                                    verbose_name="Dependencia (SIIFWEB)", related_name="proyectos")
    # Del cruce POAI: no existen en SIIFWEB y la dependencia difiere de la ejecutora
    dependencia_responsable = models.ForeignKey(DependenciaResponsable, null=True, blank=True,
                                                on_delete=models.PROTECT, related_name="proyectos",
                                                verbose_name="Dependencia responsable (POAI)")
    # Un proyecto puede tener varias: POAI 2026 y Recursos del Balance, por ejemplo
    clasificaciones = models.ManyToManyField(Clasificacion, blank=True, related_name="proyectos",
                                             verbose_name="Clasificaciones (POAI)")
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.MANUAL,
                              verbose_name="Origen del registro")

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
    objeto_oblig = models.TextField(verbose_name="Objeto de la obligacion", blank=True,
                                    help_text="Columna OBJETO_OBLIG del consolidado")
    beneficiario = models.ForeignKey(Tercero, related_name="obligaciones", on_delete=models.PROTECT,
                                     null=True, blank=True, verbose_name="Beneficiario",
                                     help_text="Columnas NIT y BENEFICIARIO del consolidado")
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


# 5. Contratacion publica (SECOP II)
#
# Vienen del consolidado "BPIN por proceso", que junta tres bases de datos abiertos
# del DNP: BPIN por Proceso (la que trae el BPIN y las tres llaves), Procesos de
# Contratacion (las fechas de publicacion y el estado del procedimiento) y Contratos
# Electronicos (el contrato adjudicado). Una tabla por base de origen.
#
# El contrato de SECOP NO se enlaza con el Contrato de SIIFWEB: las dos numeraciones
# son independientes (la referencia CPS-872-2024 es el contrato 2666 en SIIFWEB) y el
# dato abierto no trae ninguna columna puente. El vinculo con el seguimiento es el
# BPIN, es decir, el proyecto.

class ProcesoSecop(Fechas):
    """El proceso de contratacion. Un portafolio puede agrupar varios procesos."""
    reporte = models.ForeignKey(CargaReporte, related_name="procesos_secop", null=True, blank=True,
                                on_delete=models.PROTECT)
    id_proceso = models.CharField(max_length=60, unique=True, verbose_name="ID del proceso")
    id_portafolio = models.CharField(max_length=60, blank=True, db_index=True,
                                     verbose_name="ID del portafolio",
                                     help_text="Agrupa procesos: 114 portafolios traen dos o tres")
    estado_procedimiento = models.CharField(max_length=60, blank=True,
                                            verbose_name="Estado del procedimiento")
    fecha_publicacion = models.DateField(verbose_name="Fecha de publicacion", null=True, blank=True)
    fecha_ultima_publicacion = models.DateField(verbose_name="Fecha de ultima publicacion",
                                                null=True, blank=True)
    fecha_recepcion_respuestas = models.DateField(verbose_name="Fecha de recepcion de respuestas",
                                                  null=True, blank=True)
    fecha_apertura_respuestas = models.DateField(verbose_name="Fecha de apertura de respuestas",
                                                 null=True, blank=True)
    fecha_apertura_efectiva = models.DateField(verbose_name="Fecha de apertura efectiva",
                                               null=True, blank=True)

    class Meta:
        verbose_name = "Proceso de SECOP II"
        verbose_name_plural = "Procesos de SECOP II"

    def __str__(self):
        return f"{self.id_proceso} ({self.estado_procedimiento or 'sin estado'})"


class ContratoSecop(Fechas):
    """El contrato electronico adjudicado. Cada contrato pertenece a un solo proceso."""
    reporte = models.ForeignKey(CargaReporte, related_name="contratos_secop", null=True, blank=True,
                                on_delete=models.PROTECT)
    id_contrato = models.CharField(max_length=60, unique=True, verbose_name="ID del contrato")
    proceso = models.ForeignKey(ProcesoSecop, on_delete=models.PROTECT,
                                related_name="contratos_del_proceso", verbose_name="Proceso")
    referencia = models.CharField(max_length=120, blank=True, verbose_name="Referencia del contrato",
                                  help_text="Numeracion de SECOP (CPS-872-2024); no es el numero "
                                            "de contrato de SIIFWEB")
    estado = models.CharField(max_length=60, blank=True, verbose_name="Estado del contrato")
    objeto = models.TextField(blank=True, verbose_name="Objeto del contrato")
    descripcion_proceso = models.TextField(blank=True, verbose_name="Descripcion del proceso")
    proveedor = models.ForeignKey(Tercero, related_name="contratos_secop", on_delete=models.PROTECT,
                                  null=True, blank=True, verbose_name="Proveedor")
    valor = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Valor del contrato",
                                null=True, blank=True)
    fecha_firma = models.DateField(verbose_name="Fecha de firma", null=True, blank=True)
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio", null=True, blank=True)
    fecha_fin = models.DateField(verbose_name="Fecha de fin", null=True, blank=True)
    url_proceso = models.TextField(blank=True, verbose_name="URL del proceso")

    class Meta:
        verbose_name = "Contrato de SECOP II"
        verbose_name_plural = "Contratos de SECOP II"

    def __str__(self):
        return f"{self.referencia or self.id_contrato} - {self.estado or 'sin estado'}"


class BpinProceso(Fechas):
    """La fila del consolidado: que BPIN financia que proceso y que contrato.

    Es una tabla propia y no un campo del contrato porque el grano lo exige: 17
    contratos financian mas de un BPIN, y 250 procesos todavia no tienen contrato
    adjudicado (en evaluacion, cancelados, en borrador), que es el pipeline
    contractual del proyecto.

    El bpin se guarda siempre en texto aunque el proyecto quede nulo: un BPIN de
    SECOP que no esta en el catalogo tiene que quedar visible para que el equipo
    decida si crea el proyecto. La carga no crea proyectos desde esta fuente.
    """
    reporte = models.ForeignKey(CargaReporte, related_name="bpines_por_proceso", null=True, blank=True,
                                on_delete=models.PROTECT)
    bpin = models.CharField(max_length=25, db_index=True, verbose_name="BPIN")
    proyecto = models.ForeignKey(Proyecto, related_name="procesos_secop", on_delete=models.PROTECT,
                                 null=True, blank=True, verbose_name="Proyecto",
                                 help_text="Nulo si el BPIN no esta en el catalogo")
    proceso = models.ForeignKey(ProcesoSecop, related_name="bpines", on_delete=models.PROTECT,
                                verbose_name="Proceso")
    contrato_secop = models.ForeignKey(ContratoSecop, related_name="bpines", on_delete=models.PROTECT,
                                       null=True, blank=True, verbose_name="Contrato",
                                       help_text="Nulo si el proceso no tiene contrato adjudicado")
    anio = models.IntegerField(verbose_name="Anio del BPIN", null=True, blank=True)
    validacion_bpin = models.CharField(max_length=20, blank=True, verbose_name="Validacion del BPIN")

    class Meta:
        verbose_name = "BPIN por proceso"
        verbose_name_plural = "BPIN por proceso"
        constraints = [
            # Ojo: contrato_secop admite nulos y en SQL dos nulos no colisionan, asi que
            # esta restriccion no cubre las filas sin contrato. La carga deduplica antes
            # de insertar (el archivo trae 12 filas repetidas).
            models.UniqueConstraint(fields=["bpin", "proceso", "contrato_secop"],
                                    name="bpin_proceso_unico")
        ]

    def __str__(self):
        contrato = self.contrato_secop.referencia if self.contrato_secop else "sin contrato"
        return f"{self.bpin} - {self.proceso.id_proceso} - {contrato}"


# 6. Metas del plan de desarrollo (traidas de SUTEC)
#
# El catalogo del plan: PlanDesarrollo <- LineaEstrategica <- SectorPDD <- ProgramaPDD,
# con IndicadorPDD ligado a varios programas; la cadena MGA del DNP (SectorMGA <-
# ProgramaMGA <- ProductoMGA <- IndicadorMGA), que es otra clasificacion y no lleva al
# PDD; los ODS; y las metas con sus vigencias. La meta cuelga solo de su programa: sector,
# linea y plan suben desde el. Su dependencia es la DependenciaResponsable de siifweb.
# Los datos los carga la migracion 0012 desde el volcado de produccion de SUTEC.
# Decisiones de diseno y pasos: modelos-metas/PLAN_METAS_PDD.md.

class PlanDesarrollo(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    descripcion = models.CharField(max_length=255, verbose_name="Nombre")
    vigencia_inicio = models.CharField(max_length=255, verbose_name="Año en el que empieza")
    vigencia_fin = models.CharField(max_length=255, verbose_name="Año en el que finaliza")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Plan de desarrollo"
        verbose_name_plural="Planes de desarrollo"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class LineaEstrategica(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    plan_desarrollo = models.ForeignKey(PlanDesarrollo, verbose_name="Plan de desarrollo", on_delete=models.SET_NULL, blank=True, null=True)
    descripcion = models.CharField(max_length=255, verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Línea estratégica"
        verbose_name_plural="Líneas estratégicas"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class SectorPDD(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    linea_estrategica = models.ForeignKey(LineaEstrategica, verbose_name="Línea estratégica", on_delete=models.SET_NULL, blank=True, null=True)
    descripcion = models.CharField(max_length=255, verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Sector PDD"
        verbose_name_plural="Sectores PDD"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class ProgramaPDD(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    sector_pdd = models.ForeignKey(SectorPDD, verbose_name="Sector PDD", on_delete=models.SET_NULL, blank=True, null=True)
    descripcion = models.CharField(max_length=255, verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Programa PDD"
        verbose_name_plural="Programas PDD"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class IndicadorPDD(Fechas):
    programas_pdd = models.ManyToManyField(
        ProgramaPDD,
        verbose_name="Programas PDD",
        blank=True,
        related_name="indicadores_pdd",
        help_text="Permite asociar el indicador a uno o más programas PDD. Útil para filtros por programa/sector/línea estratégica.",
    )
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    descripcion = models.TextField(verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Indicador PDD"
        verbose_name_plural="Indicadores PDD"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class SectorMGA(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    descripcion = models.TextField(verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Sector MGA"
        verbose_name_plural="Sectores MGA"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class ProgramaMGA(Fechas):
    sector_mga = models.ForeignKey(SectorMGA, verbose_name="Sector MGA", on_delete=models.SET_NULL, blank=True, null=True)
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    descripcion = models.TextField(verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Programa MGA"
        verbose_name_plural="Programas MGA"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class ProductoMGA(Fechas):
    programa_mga = models.ForeignKey(ProgramaMGA, verbose_name="Programa MGA", on_delete=models.SET_NULL, blank=True, null=True)
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    descripcion = models.TextField(verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Producto MGA"
        verbose_name_plural="Productos MGA"

    def __str__(self):
        # Con el codigo delante: el catalogo tiene cientos de productos y la
        # descripcion sola no basta para distinguirlos al elegir uno.
        try:
            descripcion = strip_tags(self.descripcion)
        except Exception:
            descripcion = self.descripcion
        if self.codigo:
            return '%s - %s' % (self.codigo, descripcion)
        return descripcion


class IndicadorMGA(Fechas):
    producto_mga = models.ForeignKey(ProductoMGA, verbose_name="Producto MGA", on_delete=models.SET_NULL, blank=True, null=True)
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    ods = models.ManyToManyField('ODS', verbose_name="Objetivos de desarrollo sostenible", blank=True)
    descripcion = models.TextField(verbose_name="Nombre")
    
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Indicador MGA"
        verbose_name_plural="Indicadores MGA"

    def __str__(self):
        if self.codigo:
            try:
                return f"{self.codigo} - {strip_tags(self.descripcion or '')}"
            except:
                return f"{self.codigo} - {self.descripcion or ''}"
        else:
            try:
                return strip_tags(self.descripcion or '')
            except:
                return self.descripcion or ''


class MetaIndicador(Fechas):
    codigo = models.CharField(max_length=50, verbose_name="Código", blank=True, null=True)
    indicador_mga = models.ForeignKey(IndicadorMGA, verbose_name="Indicador MGA", on_delete=models.CASCADE, related_name='metas')
    descripcion = models.TextField(verbose_name="Descripción")
    dependencias_responsables = models.ManyToManyField(DependenciaResponsable, verbose_name="Dependencias responsables", blank=True)
    ods = models.ManyToManyField('ODS', verbose_name="Objetivos de desarrollo sostenible", blank=True)
    # Decimal y no float, con tres decimales y no los dos del dinero: las metas
    # de vías van en kilómetros con precisión de metros (11,187 km).
    meta_cuatrenio = models.DecimalField(max_digits=20, decimal_places=3, verbose_name="Meta cuatrenio", blank=True, null=True)

    # El sitio de la meta en el plan es su programa, y solo él. El sector, la
    # línea estratégica y el plan no se guardan: se suben desde el programa
    # (ver las propiedades de abajo), así no hay forma de que se descuadren.
    #
    # Obligatorio, y por eso PROTECT: un programa con metas no se puede borrar.
    # SET_NULL no cabe en un campo sin nulos, y CASCADE borraría las metas con
    # sus vigencias por borrar una fila del catálogo.
    programa_pdd = models.ForeignKey(
        ProgramaPDD,
        verbose_name="Programa PDD",
        on_delete=models.PROTECT,
        related_name="metas_indicador",
    )
    indicadores_pdd = models.ManyToManyField(
        IndicadorPDD,
        verbose_name="Indicadores PDD",
        blank=True,
        related_name="metas_indicador",
        help_text="Indicadores de resultado del plan a los que aporta esta "
                  "meta. Son varios mas veces de las que parece: en 55 de las "
                  "436 del Plan Indicativo, y en dos de ellas son catorce. "
                  "Por eso no puede ser una sola clave ajena.",
    )

    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name = "Meta de Indicador MGA"
        verbose_name_plural = "Metas de Indicadores MGA"
        ordering = ['-codigo']

    def __str__(self):
        # La etiqueta se arma con el consecutivo de la meta y con el código y la
        # descripción **del indicador MGA**, no con la descripción propia.
        #
        # La descripción propia llegó irregular en la carga: unas filas dicen
        # «450203400 | Personas capacitadas» y otras «MT467 - 450203400 -
        # Personas capacitadas», así que anteponerle cualquier cosa producía
        # etiquetas repetidas —«MT467 - MT467 - …»—. El 06/09 eso se resolvió
        # dejando solo la descripción; el 07/09 el usuario pidió armarla desde
        # el indicador MGA, que sí es uniforme en las 468 filas cargadas:
        #
        #     MT467 - 450203400: Personas capacitadas
        #
        # El **sector PDD** va detrás del consecutivo porque es lo que separa
        # las que se leen igual. Hay 28 grupos de metas que comparten
        # consecutivo e indicador MGA —«MT467 - 450203400: Personas
        # capacitadas» aparece tres veces— y lo único que las distingue es el
        # sector del plan de desarrollo al que responden: Inclusión Social,
        # Comercio e Industria, Salud. Sin él, en el desplegable parecen
        # duplicados y no hay forma de saber cuál elegir.
        #
        # `indicador_mga` es obligatorio en el modelo, así que una meta guardada
        # siempre lo tiene; el sector PDD admite nulos, pero las 468 cargadas lo
        # traen.
        return f"{self.codigo} - {self.sector_pdd} - {self.indicador_mga.codigo}: {strip_tags(self.indicador_mga.descripcion)}"

    @property
    def sector_pdd(self):
        return self.programa_pdd.sector_pdd if self.programa_pdd else None

    @property
    def linea_estrategica(self):
        sector = self.sector_pdd
        return sector.linea_estrategica if sector else None

    @property
    def plan_desarrollo(self):
        linea = self.linea_estrategica
        return linea.plan_desarrollo if linea else None

    def clean(self):
        # Cambiar el programa de una meta que ya tiene indicadores no puede
        # dejarlos colgando de otro programa.
        super().clean()
        # Si el formulario trae los indicadores que va a guardar, se juzgan esos y
        # no los de la base: al cambiar programa e indicadores a la vez, los
        # guardados son los viejos y darian un error falso.
        indicadores = getattr(self, '_indicadores_pdd_por_guardar', None)
        if indicadores is None and self.pk:
            indicadores = self.indicadores_pdd.values_list('pk', flat=True)
        if indicadores is not None:
            fuera = indicadores_fuera_del_programa(self.programa_pdd_id, indicadores)
            if fuera:
                raise ValidationError({'programa_pdd': (
                    'Estos indicadores PDD de la meta no pertenecen al programa '
                    'elegido: %s.' % ', '.join(str(i) for i in fuera))})


def indicadores_fuera_del_programa(programa_id, indicador_ids):
    """Los indicadores PDD que no tienen al programa entre sus `programas_pdd`.

    Una meta pertenece a un solo programa y aporta a varios indicadores PDD,
    todos de ese programa. Un indicador puede compartirse entre programas, así
    que basta con que el de la meta esté entre los suyos. Sin programa, ningún
    indicador cuadra.
    """
    indicadores = IndicadorPDD.objects.filter(pk__in=list(indicador_ids))
    if programa_id is None:
        # No vale pasarle None al exclude: lo traduce a «sin ningún programa»
        # y dejaría entrar justo a los indicadores huérfanos.
        return list(indicadores)
    return list(indicadores.exclude(programas_pdd__pk=programa_id))


@receiver(m2m_changed, sender=MetaIndicador.indicadores_pdd.through)
def indicadores_pdd_del_programa_de_la_meta(sender, instance, action, reverse, pk_set, **kwargs):
    # Guardia de último recurso para cualquier vía (admin, guiones, cargues).
    # En un formulario conviene validarlo también en su `clean()`, porque una
    # excepción aquí llega como error 500 y no como aviso en el campo.
    if action != 'pre_add':
        return
    if reverse:
        # Se añaden metas desde el indicador: cada meta debe ser de un
        # programa del indicador.
        programas = set(instance.programas_pdd.values_list('pk', flat=True))
        malas = MetaIndicador.objects.filter(pk__in=pk_set).exclude(
            programa_pdd__in=programas)
        if malas.exists():
            raise ValidationError(
                'El indicador PDD %s no pertenece al programa de las metas: %s.'
                % (instance, ', '.join(str(m) for m in malas)))
    else:
        fuera = indicadores_fuera_del_programa(instance.programa_pdd_id, pk_set)
        if fuera:
            raise ValidationError(
                'Estos indicadores PDD no pertenecen al programa de la meta: %s.'
                % ', '.join(str(i) for i in fuera))


def listado_vigencias_metas():
    """Las vigencias que se pueden elegir para una meta.

    Como `listado_vigencias`, pero con tres años más: ese llega hasta el año en
    curso, y una meta se programa para el cuatrienio entero, así que necesita
    los años que aún no han llegado. Va aparte para no abrir años futuros en
    las demás vigencias de siifweb (CDP, compromisos, obligaciones...).
    """
    year = timezone.localdate().year
    return [(y, y) for y in range(2017, year + 4)]


class VigenciaMeta(Fechas):
    meta_indicador = models.ForeignKey(MetaIndicador, verbose_name="Meta Indicador", on_delete=models.CASCADE, related_name='vigencias')
    vigencia = models.IntegerField(verbose_name="Vigencia", choices=listado_vigencias_metas)
    valor = models.DecimalField(max_digits=20, decimal_places=3, verbose_name="Valor")

    class Meta:
        verbose_name = "Vigencia de Indicador MGA"
        verbose_name_plural = "Vigencias de Indicadores MGA"
        ordering = ['-vigencia']

    def __str__(self):
        return f"{self.meta_indicador} - {self.vigencia}: {self.valor}"

    def clean(self):
        # Que sea un año ya lo valida el campo; vacía la rechaza él también.
        if self.vigencia is not None and self.vigencia < 2020:
            raise ValidationError('La vigencia debe ser mayor a 2020')


class ODS(Fechas):
    descripcion = models.TextField(verbose_name="Nombre")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Objetivo de desarrollo sostenible"
        verbose_name_plural="Objetivos de desarrollo sostenible"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


class MetaODS(Fechas):
    ods = models.ForeignKey(ODS, verbose_name="Objetivo de desarrollo sostenible", on_delete=models.SET_NULL, blank=True, null=True)
    descripcion = models.TextField(verbose_name="Nombre")
    productos_mga = models.ManyToManyField(
        ProductoMGA, verbose_name="Productos MGA", blank=True,
        related_name='metas_ods',
        help_text="Productos del catálogo del DNP que aportan a esta meta. "
                  "Con esta relación, el ODS de un proyecto se deduce de sus "
                  "metas y no hace falta registrarlo a mano.")
    estado = models.BooleanField(default=True, verbose_name="Estado")

    class Meta:
        verbose_name="Meta ODS"
        verbose_name_plural="Metas ODS"

    def __str__(self):
        try:
            return strip_tags(self.descripcion)
        except:
            return self.descripcion


# 7. Programacion de proyectos en las metas del plan (traida del Access "Seguimiento PDD STO")
#
# Cada fila de tblProyectos era una programacion: un proyecto en una meta y una vigencia,
# con la meta del proyecto para ese ano. Aqui el proyecto queda una sola vez y sus
# programaciones y observaciones cuelgan de el. No es el Proyecto de SIIFWEB: muchos no
# tienen BPIN (iniciativas por gestion, recursos propios), asi que el BPIN es solo un dato.

class TipoBanco(Fechas):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Tipo de banco"
        verbose_name_plural = "Tipos de banco"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class Municipio(Fechas):
    """Los 26 municipios de Sucre, mas "Todo el departamento" para los proyectos que lo
    cubren entero."""
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Municipio"
        verbose_name_plural = "Municipios"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class ProgramacionProyectos(Fechas):
    bpin = models.CharField(max_length=20, blank=True, verbose_name="BPIN")
    nombre = models.TextField(verbose_name="Nombre del proyecto")
    tipo_banco = models.ForeignKey(TipoBanco, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="proyectos", verbose_name="Tipo de banco")
    municipios = models.ManyToManyField(Municipio, blank=True, related_name="proyectos",
                                        verbose_name="Municipios")
    # Las vigencias en que el proyecto tiene programacion, separadas por coma ("2024, 2025").
    # Se recalculan desde sus programaciones al guardar en el admin.
    vigencias = models.CharField(max_length=60, blank=True, verbose_name="Vigencias")

    class Meta:
        verbose_name = "Programacion de proyecto"
        verbose_name_plural = "Programacion de proyectos"
        ordering = ("nombre",)

    def __str__(self):
        return f"{self.bpin} - {self.nombre}" if self.bpin else self.nombre

    def vigencias_programadas(self):
        """Las vigencias de sus programaciones, en el formato del campo."""
        anios = sorted({v for v in self.programaciones.values_list("vigencia", flat=True) if v})
        return ", ".join(str(a) for a in anios)

    def actualizar_vigencias(self):
        """Pone al dia el campo con sus programaciones. Lo llaman los dos admins que las
        editan: el del proyecto y el de la meta."""
        vigencias = self.vigencias_programadas()
        if self.vigencias != vigencias:
            self.vigencias = vigencias
            self.save(update_fields=["vigencias", "fecha_actualizacion"])


class ProgramacionMeta(Fechas):
    """El proyecto en una meta del plan y una vigencia, con lo que aporta a esa meta."""
    proyecto = models.ForeignKey(ProgramacionProyectos, on_delete=models.CASCADE,
                                 related_name="programaciones", verbose_name="Proyecto")
    meta = models.ForeignKey(MetaIndicador, on_delete=models.PROTECT,
                             related_name="programaciones_de_proyectos", verbose_name="Meta")
    vigencia = models.IntegerField(choices=listado_vigencias_metas, null=True, blank=True,
                                   verbose_name="Vigencia")
    # Cinco decimales: en Access hay metas viales en kilometros con cuatro (3,0976 km), y
    # con tres se redondeaban. VigenciaMeta.valor sigue con tres, que es lo que trae SUTEC.
    meta_vigencia = models.DecimalField(max_digits=20, decimal_places=5, null=True, blank=True,
                                        verbose_name="Meta de la vigencia")
    # La fila de tblProyectos de la que salio, para rastrear el origen
    id_access = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False,
                                            verbose_name="Id en Access")

    class Meta:
        verbose_name = "Programacion en meta"
        verbose_name_plural = "Programacion en metas"
        ordering = ("vigencia", "meta__codigo")

    def __str__(self):
        return f"{self.meta.codigo} - {self.vigencia or 'sin vigencia'}: {self.meta_vigencia}"


class ObservacionProyecto(Fechas):
    proyecto = models.ForeignKey(ProgramacionProyectos, on_delete=models.CASCADE,
                                 related_name="observaciones", verbose_name="Proyecto")
    # Las traidas de Access no tenian fecha y quedan vacias; las nuevas llevan la del dia
    fecha = models.DateField(null=True, blank=True, default=timezone.localdate, verbose_name="Fecha")
    texto = models.TextField(verbose_name="Observacion")

    class Meta:
        verbose_name = "Observacion del proyecto"
        verbose_name_plural = "Observaciones del proyecto"
        ordering = ("-fecha", "-id")

    def __str__(self):
        return f"{self.fecha or 'sin fecha'}: {self.texto[:60]}"
