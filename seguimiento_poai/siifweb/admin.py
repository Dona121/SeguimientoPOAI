# -*- coding: utf-8 -*-
import hashlib
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import (Case, Count, DateField, DecimalField, Exists, F, IntegerField, OuterRef,
                              Prefetch, Q, Subquery, Sum, Value, When)
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format, number_format
from django.utils.html import format_html, format_html_join, strip_tags
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (ChoicesDropdownFilter, RangeDateFilter,
                                          RelatedDropdownFilter,TextFilter,FieldTextFilter,AutocompleteSelectMultipleFilter)
from unfold.decorators import action, display
from unfold.sections import TableSection
from unfold.widgets import UnfoldAdminFileFieldWidget

from . import cargas, programacion_financiera, tablero
from .models import (BpinProceso, CargaReporte, Cdp, CdpImputacion, CentroCosto, Clasificacion,
                     Compromiso, CompromisoImputacion, Contrato, ContratoActa, ContratoImputacion,
                     ContratoSecop, DependenciaResponsable, Fuente, Obligacion, ObligacionImputacion,
                     OrdenGasto, ProcesoSecop, Proyecto, Reserva, ReservaImputacion, Rubro, Tercero)
from .models import (IndicadorMGA, IndicadorPDD, LineaEstrategica, MedidoATravesDe, MetaIndicador, MetaODS,
                     ODS, PlanDesarrollo, ProductoMGA, ProgramaMGA, ProgramaPDD, SectorMGA, SectorPDD,
                     UnidadMedida, VigenciaMeta, indicadores_fuera_del_programa)
from .models import (MESES, Municipio, ObservacionProyecto, PeriodoReporte, ProgramacionMeta,
                     ProgramacionProyectos, SeguimientoMeta, TipoBanco, listado_vigencias_metas)
from .models import (PASOS, RADICACION, TRAMITES, Departamento, FormulacionProyecto, IndicadorCatalogo, IndicadorProyecto,
                     MedidaTiempo, ObservacionProyectoSiifweb, ProductoCatalogo, ProgramacionFinanciera,
                     ProgramacionFisica, EntidadAportante)
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import User, Group
from unfold.forms import UserChangeForm, AdminPasswordChangeForm, UserCreationForm


admin.site.unregister(User)
admin.site.unregister(Group)

@admin.register(User)
class UserAdmin(BaseUserAdmin,ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

@admin.register(Group)
class GroupAdmin(BaseGroupAdmin,ModelAdmin):
    pass

def pesos(valor):
    return f"${valor:,.0f}" if valor is not None else "-"


def suma_de(modelo, campo, relacion="proyecto"):
    """Suma por subconsulta, no por join.

    Anotar dos relaciones a la vez con Sum() multiplica las filas (el producto
    cartesiano de ambos joins) e infla los totales. Es el mismo problema del grano
    que hay que cuidar al cruzar los reportes.
    """
    return Subquery(
        modelo.objects.filter(**{relacion: OuterRef("pk")})
        .values(relacion).annotate(t=Sum(campo)).values("t"),
        output_field=DecimalField(max_digits=20, decimal_places=2))


def fecha_del_get(request, nombre):
    """Fecha de un parametro GET, o None si viene vacia o no es una fecha.

    parse_date devuelve None con un texto que no parece fecha, pero LANZA ValueError
    con una bien formada e imposible ('2025-13-45'): sin esto la pagina daba 500.
    """
    try:
        return parse_date(request.GET.get(nombre, "") or "")
    except ValueError:
        return None


def primera_fecha(modelo, campo_fecha, relacion="proyecto"):
    """Fecha mas antigua de la relacion, por subconsulta.

    Reemplaza un .filter().first() por fila (N+1 en el listado) por una sola
    subconsulta correlacionada que se resuelve dentro del query del changelist.
    """
    return Subquery(
        modelo.objects.filter(**{relacion: OuterRef("pk")})
        .order_by(campo_fecha).values(campo_fecha)[:1],
        output_field=DateField())


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------

class SoloLectura(ModelAdmin):
    """Los datos migrados se revisan, no se editan a mano."""
    compressed_fields = True
    list_fullwidth = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ImputacionInline(TabularInline):
    """Las lineas de un documento, en solo lectura."""
    extra = 0
    can_delete = False
    show_change_link = True
    tab = True
    hide_title = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class CdpImputacionInline(ImputacionInline):
    model = CdpImputacion
    verbose_name_plural = "Imputaciones (rubro x fuente x proyecto)"
    fields = ("rubro", "fuente", "proyecto", "valor_certificado",
              "valor_disponibilidad_def", "saldo_certf")
    readonly_fields = fields


class CompromisoDelCdpInline(ImputacionInline):
    """Los RP que se expidieron con cargo a este CDP."""
    model = CompromisoImputacion
    fk_name = "cdp"
    verbose_name_plural = "Compromisos con cargo a este CDP"
    fields = ("compromiso", "rubro", "fuente", "proyecto", "valor_compromiso_def", "saldo_rp")
    readonly_fields = fields


class ReservaDelCdpInline(ImputacionInline):
    """Lo que este CDP dejo en reserva para la vigencia siguiente."""
    model = ReservaImputacion
    fk_name = "cdp_origen"
    verbose_name_plural = "Reservas constituidas con cargo a este CDP (vigencia siguiente)"
    fields = ("reserva", "rubro", "fuente", "valor_reserva", "obligaciones_reserva", "saldo_reserva")
    readonly_fields = fields


class CompromisoImputacionInline(ImputacionInline):
    model = CompromisoImputacion
    fk_name = "compromiso"
    verbose_name_plural = "Imputaciones (CDP x rubro x fuente x proyecto)"
    fields = ("cdp", "rubro", "fuente", "proyecto", "valor_registro",
              "valor_compromiso_def", "saldo_rp")
    readonly_fields = fields


class ObligacionDelCompromisoInline(ImputacionInline):
    model = ObligacionImputacion
    fk_name = "compromiso"
    verbose_name_plural = "Obligaciones causadas contra este RP"
    fields = ("obligacion", "rubro", "fuente", "proyecto", "valor_obligacion", "saldo_obli", "pagos")
    readonly_fields = fields


class ContratoDelCompromisoInline(ImputacionInline):
    model = ContratoImputacion
    fk_name = "compromiso"
    verbose_name_plural = "Contrato que respalda este RP"
    fields = ("contrato", "rubro", "fuente", "proyecto", "nro_comprobante")
    readonly_fields = fields


class ObligacionImputacionInline(ImputacionInline):
    model = ObligacionImputacion
    fk_name = "obligacion"
    verbose_name_plural = "Imputaciones (RP x rubro x fuente x proyecto)"
    fields = ("compromiso", "rubro", "fuente", "proyecto", "valor_obligacion", "saldo_obli", "pagos")
    readonly_fields = fields


class ReservaImputacionInline(ImputacionInline):
    model = ReservaImputacion
    fk_name = "reserva"
    verbose_name_plural = "Imputaciones (CDP de origen x rubro x fuente)"
    fields = ("cdp_origen", "rubro", "fuente", "proyecto", "valor_reserva",
              "obligaciones_reserva", "pagos_reserva", "saldo_reserva")
    readonly_fields = fields


class ContratoActaInline(ImputacionInline):
    model = ContratoActa
    verbose_name_plural = "Actas de pago"
    fields = ("nrodoc_acta", "tipo_orden", "fecha_pago", "valor_pago", "concepto")
    readonly_fields = fields
    ordering = ("fecha_pago",)


class ContratoImputacionInline(ImputacionInline):
    model = ContratoImputacion
    fk_name = "contrato"
    verbose_name_plural = "Imputaciones presupuestales"
    fields = ("vigencia", "compromiso", "rubro", "fuente", "proyecto", "nro_comprobante")
    readonly_fields = fields


# ---------------------------------------------------------------------------
# Cargas
# ---------------------------------------------------------------------------

def hash_archivo(archivo):
    digest = hashlib.sha256()
    for bloque in archivo.chunks():
        digest.update(bloque)
    archivo.seek(0)
    return digest.hexdigest()


class CargaReporteForm(forms.ModelForm):
    class Meta:
        model = CargaReporte
        fields = ("tipo_reporte", "vigencia", "archivo", "fecha_descarga")

    # Tipos que ya no se cargan. Siguen en el modelo para que las cargas viejas se lean
    # con su nombre, pero el formulario no los ofrece. El cruce POAI se dejo de usar en
    # octubre de 2026: la dependencia responsable y la clasificacion las mantiene el equipo.
    RETIRADOS = (CargaReporte.TipoReporte.POAI,)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actual = self.instance.tipo_reporte if self.instance.pk else None
        self.fields["tipo_reporte"].choices = [
            (valor, etiqueta) for valor, etiqueta in self.fields["tipo_reporte"].choices
            if valor not in self.RETIRADOS or valor == actual]

    def clean(self):
        datos = super().clean()
        archivo = datos.get("archivo")
        if archivo and hasattr(archivo, "chunks"):
            digest = hash_archivo(archivo)
            # El mismo libro trae SECOP II y la informacion general del PIIP: lo repetido
            # es el mismo archivo cargado otra vez como el mismo tipo de reporte
            previa = (CargaReporte.objects.filter(hash=digest, tipo_reporte=datos.get("tipo_reporte"))
                      .exclude(pk=self.instance.pk).first())
            if previa:
                raise forms.ValidationError(
                    f"Este archivo ya fue cargado el {previa.fecha_creacion:%Y-%m-%d} "
                    f"como '{previa}'. No se vuelve a procesar.")
            self.instance.hash = digest
        tipo = datos.get("tipo_reporte")
        sin_vigencia = (CargaReporte.TipoReporte.HISTORIAL, CargaReporte.TipoReporte.POAI,
                        CargaReporte.TipoReporte.SECOP, CargaReporte.TipoReporte.PIIP)
        if tipo and tipo not in sin_vigencia and not datos.get("vigencia"):
            raise forms.ValidationError("La vigencia es obligatoria salvo en el historial de contratos, "
                                        "SECOP II y la informacion general del PIIP, que cubren varias "
                                        "vigencias.")
        return datos


@admin.register(CargaReporte)
class CargaReporteAdmin(ModelAdmin):
    form = CargaReporteForm
    compressed_fields = True
    list_fullwidth = True
    list_display = ("tipo_reporte", "vigencia", "fecha_descarga", "estado_badge", "filas_fmt", "mensaje")
    list_filter = (("tipo_reporte", ChoicesDropdownFilter), ("estado", ChoicesDropdownFilter), "vigencia")
    readonly_fields = ("hash", "filas", "estado", "mensaje", "fecha_creacion", "fecha_actualizacion")
    actions = ("procesar_cargas",)
    fieldsets = (
        ("Archivo", {"fields": ("tipo_reporte", "vigencia", "archivo", "fecha_descarga"),
                     "description": "El historial de contratos se descarga por rango completo: "
                                    "dejar la vigencia vacia."}),
        ("Resultado del proceso", {"fields": ("estado", "filas", "mensaje", "hash"),
                                   "classes": ("collapse",)}),
    )

    @display(description="Estado", label={"Pendiente": "warning", "Procesado": "success",
                                          "Con error": "danger"})
    def estado_badge(self, obj):
        return obj.get_estado_display()

    @display(description="Filas", ordering="filas")
    def filas_fmt(self, obj):
        return f"{obj.filas:,}"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            messages.info(request, "Archivo guardado. Selecciona la carga y usa la accion "
                                   "'Procesar los reportes seleccionados' para migrarlo.")

    @action(description="Procesar los reportes seleccionados", icon="play_arrow")
    def procesar_cargas(self, request, queryset):
        # Los FK exigen orden y la accion lo impone sola, para que "seleccionar todo
        # y procesar" siempre funcione:
        #   1. vigencia ascendente, con los de rango completo al final. Donde caen
        #      los nulos depende del motor -SQLite los pone primero, PostgreSQL al
        #      final-, asi que se ordena explicitamente.
        #   2. dentro de una vigencia, por tipo de reporte (CDP -> RP -> obligacion
        #      -> reserva) y no por el orden en que se crearon los registros.
        prioridad = Case(
            *[When(tipo_reporte=tipo, then=Value(i))
              for i, tipo in enumerate(cargas.ORDEN_DE_CARGA)],
            default=Value(len(cargas.ORDEN_DE_CARGA)), output_field=IntegerField())
        ordenadas = (queryset.annotate(_orden=prioridad)
                     .order_by(F("vigencia").asc(nulls_last=True), "_orden", "id"))
        for carga in ordenadas:
            if cargas.procesar(carga):
                self.message_user(request, f"{carga}: {carga.mensaje}", messages.SUCCESS)
            else:
                self.message_user(request, f"{carga}: {carga.mensaje}", messages.ERROR)


# ---------------------------------------------------------------------------
# Cadena de gasto
# ---------------------------------------------------------------------------

@admin.register(Cdp)
class CdpAdmin(SoloLectura):
    inlines = (CdpImputacionInline, CompromisoDelCdpInline, ReservaDelCdpInline)
    list_display = ("nro_cdp", "vigencia", "fecha_disp", "centro_costo", "n_imputaciones",
                    "certificado", "objeto_corto")
    list_filter = ("vigencia", ("centro_costo", RelatedDropdownFilter), ("fecha_disp", RangeDateFilter))
    search_fields = ("nro_cdp", "objeto_cert")
    date_hierarchy = "fecha_disp"
    fieldsets = (
        ("Documento", {"fields": ("vigencia", "nro_cdp", "fecha_disp", "centro_costo")}),
        ("Objeto", {"fields": ("objeto_cert",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("centro_costo").annotate(
            n=Count("cdps_imputados", distinct=True),
            total=Sum("cdps_imputados__valor_certificado"))

    @display(description="Imputaciones", ordering="n")
    def n_imputaciones(self, obj):
        return obj.n

    @display(description="Certificado", ordering="total")
    def certificado(self, obj):
        return pesos(obj.total)

    @display(description="Objeto")
    def objeto_corto(self, obj):
        return obj.objeto_cert[:60]


@admin.register(Compromiso)
class CompromisoAdmin(SoloLectura):
    inlines = (CompromisoImputacionInline, ObligacionDelCompromisoInline, ContratoDelCompromisoInline)
    list_display = ("nro_rp", "vigencia", "fecha_reg", "centro_costo", "n_imputaciones",
                    "comprometido", "sin_obligar")
    list_filter = ("vigencia", ("centro_costo", RelatedDropdownFilter), ("fecha_reg", RangeDateFilter))
    search_fields = ("nro_rp", "acto_admon")
    date_hierarchy = "fecha_reg"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("centro_costo").annotate(
            n=Count("compromisos_imputados", distinct=True),
            total=Sum("compromisos_imputados__valor_compromiso_def"),
            saldo=Sum("compromisos_imputados__saldo_rp"))

    @display(description="Imputaciones", ordering="n")
    def n_imputaciones(self, obj):
        return obj.n

    @display(description="Comprometido", ordering="total")
    def comprometido(self, obj):
        return pesos(obj.total)

    @display(description="Sin obligar", ordering="saldo")
    def sin_obligar(self, obj):
        if obj.saldo and obj.saldo > 0:
            return format_html('<span style="color:#c98500">{}</span>', pesos(obj.saldo))
        return pesos(obj.saldo)


@admin.register(Obligacion)
class ObligacionAdmin(SoloLectura):
    inlines = (ObligacionImputacionInline,)
    list_display = ("nro_obligacion", "vigencia", "fecha_obli", "tipo_orden_gasto",
                    "nro_orden_gasto", "orden_pago", "obligado", "pagado")
    list_filter = ("vigencia", ("tipo_orden_gasto", RelatedDropdownFilter), ("fecha_obli", RangeDateFilter))
    search_fields = ("nro_obligacion", "orden_pago", "nro_orden_gasto")
    date_hierarchy = "fecha_obli"
    fieldsets = (
        ("Documento", {"fields": ("vigencia", "nro_obligacion", "fecha_obli", "centro_costo")}),
        ("Origen del gasto", {"fields": ("tipo_orden_gasto", "nro_orden_gasto", "prefijo_orden")}),
        ("Pago", {"fields": ("orden_pago",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("tipo_orden_gasto").annotate(
            total=Sum("obligaciones_imputadas__valor_obligacion"),
            girado=Sum("obligaciones_imputadas__pagos"))

    @display(description="Obligado", ordering="total")
    def obligado(self, obj):
        return pesos(obj.total)

    @display(description="Pagado", ordering="girado")
    def pagado(self, obj):
        return pesos(obj.girado)


# ---------------------------------------------------------------------------
# Cierre
# ---------------------------------------------------------------------------

@admin.register(Reserva)
class ReservaAdmin(SoloLectura):
    inlines = (ReservaImputacionInline,)
    list_display = ("nro_reserva", "vigencia", "fecha_reserva", "beneficiario", "reservado", "pendiente")
    list_filter = ("vigencia",)
    search_fields = ("nro_reserva", "objeto_reserva", "beneficiario__nombre")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("beneficiario").annotate(
            total=Sum("reservas_imputadas__valor_reserva"),
            saldo=Sum("reservas_imputadas__saldo_reserva"))

    @display(description="Reservado", ordering="total")
    def reservado(self, obj):
        return pesos(obj.total)

    @display(description="Sin ejecutar", ordering="saldo")
    def pendiente(self, obj):
        return pesos(obj.saldo)


# ---------------------------------------------------------------------------
# Contractual
# ---------------------------------------------------------------------------

@admin.register(Contrato)
class ContratoAdmin(SoloLectura):
    inlines = (ContratoActaInline, ContratoImputacionInline)
    list_display = ("nro_contrato", "tipo_contrato", "fecha_firma", "tercero", "valor_fmt",
                    "n_actas", "pagado_fmt")
    list_filter = (("tipo_contrato", ChoicesDropdownFilter), ("dependencia", RelatedDropdownFilter),
                   ("fecha_firma", RangeDateFilter))
    search_fields = ("nro_contrato", "tercero__nombre", "descripcion", "interventor")
    date_hierarchy = "fecha_firma"
    fieldsets = (
        ("Contrato", {"fields": ("tipo_contrato", "nro_contrato", "fecha_firma", "tercero",
                                 "valor_contrato")}),
        ("Ejecucion", {"fields": ("fecha_inicio", "fecha_final", "interventor", "dependencia")}),
        ("Objeto", {"fields": ("descripcion",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("tercero", "dependencia").annotate(
            n=Count("actas_del_contrato", distinct=True),
            pagado=Sum("actas_del_contrato__valor_pago"))

    @display(description="Valor", ordering="valor_contrato")
    def valor_fmt(self, obj):
        return pesos(obj.valor_contrato)

    @display(description="Actas", ordering="n")
    def n_actas(self, obj):
        return obj.n

    @display(description="Pagado", ordering="pagado")
    def pagado_fmt(self, obj):
        return pesos(obj.pagado)


@admin.register(ContratoActa)
class ContratoActaAdmin(SoloLectura):
    list_display = ("nrodoc_acta", "contrato", "tipo_orden", "fecha_pago", "valor_fmt")
    list_filter = (("tipo_orden", ChoicesDropdownFilter), ("fecha_pago", RangeDateFilter))
    search_fields = ("contrato__nro_contrato", "nrodoc_acta", "concepto")
    date_hierarchy = "fecha_pago"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("contrato", "contrato__tercero")

    @display(description="Valor", ordering="valor_pago")
    def valor_fmt(self, obj):
        return pesos(obj.valor_pago)


@admin.register(ContratoImputacion)
class ContratoImputacionAdmin(SoloLectura):
    list_display = ("contrato", "vigencia", "compromiso", "rubro", "fuente", "proyecto",
                    "nro_comprobante")
    list_filter = ("vigencia", ("fuente", RelatedDropdownFilter))
    search_fields = ("contrato__nro_contrato", "compromiso__nro_rp", "proyecto__bpin")
    list_select_related = ("contrato", "compromiso", "rubro", "fuente", "proyecto")


# ---------------------------------------------------------------------------
# Transaccional
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Imputaciones sueltas (para busquedas transversales)
# ---------------------------------------------------------------------------

@admin.register(CdpImputacion)
class CdpImputacionAdmin(SoloLectura):
    list_display = ("cdp", "rubro", "fuente", "proyecto", "valor_certificado",
                    "valor_disponibilidad_def", "saldo_certf")
    list_filter = ("cdp__vigencia", ("fuente", RelatedDropdownFilter))
    search_fields = ("cdp__nro_cdp", "rubro__codigo", "proyecto__bpin")
    list_select_related = ("cdp", "rubro", "fuente", "proyecto")


@admin.register(CompromisoImputacion)
class CompromisoImputacionAdmin(SoloLectura):
    list_display = ("compromiso", "cdp", "rubro", "fuente", "proyecto",
                    "valor_compromiso_def", "saldo_rp")
    list_filter = ("compromiso__vigencia", ("fuente", RelatedDropdownFilter))
    search_fields = ("compromiso__nro_rp", "cdp__nro_cdp", "proyecto__bpin")
    list_select_related = ("compromiso", "cdp", "rubro", "fuente", "proyecto")


@admin.register(ObligacionImputacion)
class ObligacionImputacionAdmin(SoloLectura):
    list_display = ("obligacion", "compromiso", "rubro", "fuente", "proyecto",
                    "valor_obligacion", "saldo_obli", "pagos")
    list_filter = ("obligacion__vigencia", ("fuente", RelatedDropdownFilter))
    search_fields = ("obligacion__nro_obligacion", "compromiso__nro_rp", "proyecto__bpin")
    list_select_related = ("obligacion", "compromiso", "rubro", "fuente", "proyecto")


@admin.register(ReservaImputacion)
class ReservaImputacionAdmin(SoloLectura):
    list_display = ("reserva", "cdp_origen", "rubro", "fuente", "proyecto",
                    "valor_reserva", "obligaciones_reserva", "saldo_reserva")
    list_filter = ("reserva__vigencia",)
    list_select_related = ("reserva", "cdp_origen", "rubro", "fuente", "proyecto")


# ---------------------------------------------------------------------------
# Catalogos
# ---------------------------------------------------------------------------

class ClasificacionPorDefectoFilter(admin.SimpleListFilter):
    """Filtro del listado con valor por defecto.

    Al entrar sin elegir nada, el listado muestra los proyectos que TIENEN alguna
    clasificacion. Se puede pedir 'Todas' (incluye los sin clasificar) o filtrar
    por una clasificacion puntual. Vive en el listado (lo aplica el ChangeList),
    NO en get_queryset, asi que ningun proyecto queda inaccesible por su ficha o
    su pagina de cambio: solo cambia lo que se ve, no lo que existe.
    """
    title = "Clasificacion"
    parameter_name = "clasif"
    TODAS = "__todas__"
    CON = "__con__"

    def lookups(self, request, model_admin):
        return [(self.CON, "Con clasificacion"), (self.TODAS, "Todas")] + [
            (str(c.pk), c.nombre) for c in Clasificacion.objects.exclude(nombre__icontains="regalías")]

    def queryset(self, request, queryset):
        valor = self.value() or self.CON         # por defecto: con clasificacion
        if valor == self.TODAS:
            return queryset                       # todo, incluidas regalias
        if valor == self.CON:
            # con clasificacion PERO sin regalias (esas se ven pidiendo 'Todas')
            return (queryset.filter(clasificaciones__isnull=False)
                    .exclude(clasificaciones__nombre__icontains="regalías").distinct())
        return queryset.filter(clasificaciones__pk=valor)

    def choices(self, changelist):
        # Sin la opcion vacia "Todos" de Django: el vacio ES el default (con
        # clasificacion), y "Todas" es la valvula de escape explicita.
        activo = self.value() or self.CON
        for lookup, titulo in self.lookup_choices:
            yield {
                "selected": str(activo) == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": titulo,
            }


class SoporteSinLimpiar(UnfoldAdminFileFieldWidget):
    """El campo de soporte de un paso del proyecto sin la casilla "Limpiar": el soporte se
    reemplaza cargando otro archivo, no se quita. Tambien ignora la orden de limpiar si llegara
    en el formulario."""
    template_name = "siifweb/widgets/soporte_sin_limpiar.html"

    def value_from_datadict(self, data, files, name):
        # Sin la casilla de limpiar: solo cuenta el archivo nuevo (None deja el que habia)
        return files.get(name)


@admin.register(Proyecto)
class ProyectoAdmin(ModelAdmin):
    compressed_fields = False
    list_fullwidth = True
    list_display = ("bpin", "nombre","responsable","ficha_link" ,"clasificacion_txt","fecha_primer_cdp","fecha_primer_rp","disponibilidad_definitiva",
                    "obligado")
    list_filter = (ClasificacionPorDefectoFilter,
                   ("origen", ChoicesDropdownFilter),
                   ("dependencia_responsable", RelatedDropdownFilter),
                   ("dependencia", RelatedDropdownFilter))
    search_fields = ("bpin", "nombre", "dependencia_responsable__nombre", "clasificaciones__nombre")
    list_display_links = ("bpin","nombre","responsable")
    autocomplete_fields = ("dependencia_responsable",)
    list_filter_sheet = True
    filter_horizontal = ("clasificaciones",)
    actions_detail = ("ficha_ejecucion", "programacion_financiera", "observaciones")
    list_filter_submit = True
    ordering = ("bpin",)
    readonly_fields = ("programado",)
    fieldsets = (
        ("Proyecto", {"fields": ("bpin", "nombre")}),
        ("Responsables y clasificacion", {
            "fields": ("dependencia", "dependencia_responsable", "clasificaciones")}),
        # Cada paso con su fecha y su soporte en la misma linea; los dos solo aparecen (y son
        # obligatorios) con la casilla marcada
        ("Radicación y ejecución", {
            "fields": (*RADICACION, ("tiempo_ejecucion", "medida_tiempo"), "contratacion_directa")}),
        ("Trámite", {"fields": TRAMITES}),
        ("Programación financiera", {"fields": ("programado",)}),
        ("Origen", {"fields": ("origen",)}),
    )
    # Campos condicionales de unfold (expresiones de Alpine sobre los campos del formulario)
    conditional_fields = {campo: f"{casilla} == true" for casilla, fecha, soporte in PASOS
                          for campo in (fecha, soporte)}

    @display(description="Valor programado")
    def programado(self, obj):
        """La suma de la programacion financiera (todas las vigencias) y lo de cada vigencia."""
        if obj is None or not obj.pk:
            return "-"
        partes = (obj.programacion_financiera.values("vigencia").annotate(t=Sum("valor")).order_by("vigencia"))
        detalle = " · ".join(f"{p['vigencia']}: {pesos(p['t'])}" for p in partes)
        return pesos(obj.valor_programado) + (f"  ({detalle})" if detalle else "")

    AYUDA_BPIN = ("Si registras aqui un proyecto nuevo, la proxima carga buscara su BPIN y le "
                  "enganchara la ejecucion. Lo que escribas en nombre y responsable no se sobreescribe.")

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # Los soportes de los pasos no se limpian: se reemplazan
        if db_field.name.startswith("soporte_"):
            kwargs["widget"] = SoporteSinLimpiar
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        """El BPIN lleva su ayuda en un globo al lado de la etiqueta."""
        form = super().get_form(request, obj, **kwargs)
        if "bpin" in form.base_fields:
            ayuda = render_to_string("siifweb/_ayuda.html", {"texto": self.AYUDA_BPIN, "etiqueta": "Ayuda del BPIN"})
            form.base_fields["bpin"].label = format_html("BPIN {}", ayuda)
        return form

    @display(description="Origen", label={"Ingresado por el equipo": "success",
                                          "Detectado en un reporte de SIIFWEB": "info",
                                          "Cruce POAI": "warning"})

    def origen_badge(self, obj):
        return obj.get_origen_display()

    @display(description="Responsable", ordering="dependencia_responsable__nombre")
    def responsable(self, obj):
        return obj.dependencia_responsable.nombre if obj.dependencia_responsable else "-"

    @display(description="Clasificacion")
    def clasificacion_txt(self, obj):
        nombres = [c.nombre for c in obj.clasificaciones.all()]
        return ", ".join(nombres) if nombres else "-"

    def get_queryset(self, request):
        # Sin filtro por clasificacion aqui: get_queryset gobierna tambien el
        # acceso a cada objeto (get_object). El recorte del listado va por el
        # ClasificacionPorDefectoFilter, que solo toca lo que se muestra.
        return (super().get_queryset(request)
                .select_related("dependencia", "dependencia_responsable")
                .prefetch_related("clasificaciones")
                .annotate(disp_def=suma_de(CdpImputacion, "valor_disponibilidad_def"),
                          oblig=suma_de(ObligacionImputacion, "valor_obligacion"),
                          primer_cdp=primera_fecha(CdpImputacion, "cdp__fecha_disp"),
                          primer_rp=primera_fecha(CompromisoImputacion, "compromiso__fecha_reg"))
                .order_by("-oblig"))

    @display(description="Primer CDP", ordering="primer_cdp")
    def fecha_primer_cdp(self, obj):
        return obj.primer_cdp or "-"

    @display(description="Primer RP", ordering="primer_rp")
    def fecha_primer_rp(self, obj):
        return obj.primer_rp or "-"

    @display(description="Disponibilidad def.", ordering="disp_def")
    def disponibilidad_definitiva(self, obj):
        return pesos(obj.disp_def)

    @display(description="Obligado", ordering="oblig")
    def obligado(self, obj):
        return pesos(obj.oblig)

    @display(description="")
    def ficha_link(self, obj):
        url = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(obj.pk,))
        return format_html('<a href="{}" class="text-primary-600" title="Expediente"><i class="material-symbols-outlined">folder_open</a>', url)

    def _ficha_piip(self, proyecto):
        """El panel de la formulacion: lo que el proyecto registro en PIIP.

        Cada indicador va con su producto del PIIP y, si esta homologado, con la linea del
        plan (sector, programa, producto e indicador del plan); las metas por vigencia en
        columnas.
        """
        formulacion = (FormulacionProyecto.objects.filter(proyecto=proyecto)
                       .select_related("reporte")
                       .prefetch_related("municipios__departamento").first())
        if formulacion is None:
            return {"formulacion": None}
        indicadores = list(
            formulacion.indicadores
            .select_related("indicador__producto__medido_a_traves_de",
                            "indicador__indicador_pdd__producto_mga__programa_mga__sector_mga")
            .prefetch_related("metas")
            .order_by("indicador__producto__codigo", "indicador__codigo"))
        vigencias = sorted({m.vigencia for i in indicadores for m in i.metas.all()})
        for i in indicadores:
            por_vigencia = {m.vigencia: m.meta for m in i.metas.all()}
            i.metas_por_vigencia = [por_vigencia.get(v) for v in vigencias]
        municipios = list(formulacion.municipios.all())
        departamentos = {m.departamento for m in municipios if m.departamento_id}
        return {
            "formulacion": formulacion,
            "piip_indicadores": indicadores,
            "piip_vigencias": vigencias,
            "piip_municipios": municipios,
            "piip_departamentos": sorted(d.nombre for d in departamentos),
            "piip_regiones": sorted({d.region for d in departamentos if d.region}),
        }

    def _ficha_secop(self, proyecto):
        """El panel de SECOP II: la contratacion publica del proyecto.

        Los contratos se resuelven por una subconsulta de ids y no por el join con
        BpinProceso: filtrar y sumar a la vez sobre la relacion multiplicaria las
        filas. Es la misma cautela del grano que en el resto de la ficha.
        """
        ids_contratos = (BpinProceso.objects
                         .filter(proyecto=proyecto, contrato_secop__isnull=False)
                         .values("contrato_secop_id"))
        contratos = (ContratoSecop.objects
                     .filter(id__in=ids_contratos)
                     .select_related("proveedor", "proceso")
                     .order_by(F("fecha_firma").desc(nulls_last=True), "-valor"))
        contratado = contratos.aggregate(t=Sum("valor"))["t"] or 0

        # Procesos del proyecto que aun no adjudican: el pipeline contractual. SIIFWEB
        # todavia no los ve como compromiso -el CDP puede existir desde antes, el RP
        # solo se expide al firmar el contrato-.
        ids_procesos = (BpinProceso.objects
                        .filter(proyecto=proyecto, contrato_secop__isnull=True)
                        .values("proceso_id"))
        en_tramite = (ProcesoSecop.objects
                      .filter(id__in=ids_procesos)
                      .order_by(F("fecha_publicacion").desc(nulls_last=True)))

        # Contraste, no conciliacion: el valor del contrato es el total pactado y el
        # comprometido es el RP de cada vigencia. No tienen por que coincidir.
        comprometido = (CompromisoImputacion.objects.filter(proyecto=proyecto)
                        .aggregate(t=Sum("valor_compromiso_def"))["t"] or 0)

        return {
            "secop_contratos": contratos,
            "secop_en_tramite": en_tramite,
            # En el orden del tramite: primero la convocatoria, despues lo ya firmado
            "secop_tarjetas": [
                ("Procesos en tramite", en_tramite.count(), "publicados, sin contrato adjudicado", False),
                ("Contratos en SECOP", contratos.count(), "contratos electronicos adjudicados", False),
                ("Valor contratado", contratado, "suma del valor de esos contratos", True),
                ("Comprometido en SIIFWEB", comprometido, "contraste: RP de todas las vigencias", True),
            ],
        }

    @action(description="Ficha de ejecucion", url_path="ficha-ejecucion", icon="analytics")
    def ficha_ejecucion(self, request, object_id):
        """Vista propia: los inlines muestran filas, esto muestra la ejecucion agregada.

        Dos paneles en la misma URL (?panel=siifweb|secop) para que la ficha no crezca
        sin fin: cada uno queda enlazable y solo se consulta el que se esta viendo.

        admin_view() solo exige estar autenticado como staff, asi que el permiso de
        vista se revisa aqui: si no, un rol sin acceso al proyecto entraria por la URL.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied

        proyecto = self.get_object(request, object_id)
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")

        panel = request.GET.get("panel")
        panel = panel if panel in ("secop", "piip") else "siifweb"
        comun = {
            **self.admin_site.each_context(request),
            "title": f"Ficha de ejecucion - {proyecto.bpin}",
            "proyecto": proyecto,
            "panel": panel,
            "paneles": (("siifweb", "SIIFWEB"), ("secop", "SECOP II"), ("piip", "Ficha PIIP")),
            "volver": reverse("admin:siifweb_proyecto_change", args=(object_id,)),
        }
        if panel == "secop":
            return TemplateResponse(request, "siifweb/ficha_proyecto.html",
                                    {**comun, **self._ficha_secop(proyecto)})
        if panel == "piip":
            return TemplateResponse(request, "siifweb/ficha_proyecto.html",
                                    {**comun, **self._ficha_piip(proyecto)})

        # Filtro de fechas y de centro de costo: recorta las tablas de CDPs, RPs y
        # obligaciones, en la pantalla y en el PDF y el Excel de cada una
        # (?descargar=pdf|xlsx&tabla=...), que salen de las mismas consultas
        from . import pdf_ficha
        desde = fecha_del_get(request, "desde")
        hasta = fecha_del_get(request, "hasta")
        # Solo los centros de costo que tienen documentos del proyecto. Por subconsultas de
        # ids: un OR sobre las tres relaciones las cruzaria y multiplicaria las filas
        centros = CentroCosto.objects.filter(
            Q(pk__in=Cdp.objects.filter(cdps_imputados__proyecto=proyecto).values("centro_costo"))
            | Q(pk__in=Compromiso.objects.filter(compromisos_imputados__proyecto=proyecto)
                .values("centro_costo"))
            | Q(pk__in=Obligacion.objects.filter(obligaciones_imputadas__proyecto=proyecto)
                .values("centro_costo"))).order_by("nombre")
        valor = request.GET.get("centro", "")
        centro = centros.filter(pk=valor).first() if valor.isdigit() else None
        documentos = self._documentos_filtrados(proyecto, desde, hasta, centro)
        formatos = {
            "pdf": (pdf_ficha.generar, "application/pdf"),
            "xlsx": (pdf_ficha.generar_excel,
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        formato = request.GET.get("descargar")
        if formato in formatos:
            tabla = request.GET.get("tabla")
            if tabla not in pdf_ficha.TABLAS:
                raise Http404("Tabla desconocida para la descarga.")
            generar, tipo = formatos[formato]
            respuesta = HttpResponse(generar(proyecto, desde, hasta, documentos, tabla),
                                     content_type=tipo)
            respuesta["Content-Disposition"] = (
                f'attachment; filename="{tabla}_{proyecto.bpin}_{timezone.localdate():%Y%m%d}.{formato}"')
            return respuesta

        # Los enlaces de descarga de cada tabla llevan el filtro que esta aplicado
        filtro = {k: v for k, v in (("desde", desde), ("hasta", hasta),
                                    ("centro", centro.pk if centro else None)) if v}
        enlaces_pdf, enlaces_excel = (
            {tabla: "?" + urlencode({"panel": "siifweb", **filtro, "tabla": tabla, "descargar": formato})
             for tabla in pdf_ficha.TABLAS}
            for formato in ("pdf", "xlsx"))

        por_vigencia = {}

        def acumular(consulta, clave):
            for fila in consulta:
                v = fila["v"]
                por_vigencia.setdefault(v, {"vigencia": v})[clave] = fila["t"]

        acumular(CdpImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("cdp__vigencia")).annotate(t=Sum("valor_disponibilidad_def")), "disponibilidad_definitiva")
        acumular(CdpImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("cdp__vigencia")).annotate(t=Sum("saldo_certf")), "sin_comprometer")
        acumular(CompromisoImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("compromiso__vigencia")).annotate(t=Sum("valor_compromiso_def")), "comprometido")
        acumular(CompromisoImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("compromiso__vigencia")).annotate(t=Sum("saldo_rp")), "sin_obligar")
        acumular(ObligacionImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("obligacion__vigencia")).annotate(t=Sum("valor_obligacion")), "obligado")
        acumular(ObligacionImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("obligacion__vigencia")).annotate(t=Sum("pagos")), "pagado")

        filas = []
        for v in sorted(por_vigencia):
            f = por_vigencia[v]
            cert, obl = f.get("disponibilidad_definitiva") or 0, f.get("obligado") or 0
            f["avance"] = float(obl) / float(cert) * 100 if cert else 0
            filas.append(f)

        totales = {c: sum(f.get(c) or 0 for f in filas)
                   for c in ("disponibilidad_definitiva", "comprometido", "obligado", "pagado",
                             "sin_comprometer", "sin_obligar")}

        # El pagado va por subconsulta: sumarlo junto al filtro por imputacion
        # multiplicaria las actas por el numero de imputaciones del contrato
        contratos = list(Contrato.objects
                         .filter(imputaciones_del_contrato__proyecto=proyecto).distinct()
                         .select_related("tercero", "dependencia")
                         .annotate(n_actas=Count("actas_del_contrato", distinct=True),
                                   pagado=suma_de(ContratoActa, "valor_pago", "contrato"))
                         .prefetch_related(Prefetch("actas_del_contrato", to_attr="actas",
                                                    queryset=ContratoActa.objects.order_by(
                                                        F("fecha_pago").asc(nulls_last=True), "pk")))
                         .order_by("-valor_contrato"))
        # El calendario de pagos de cada contrato, para su modal: sus actas en orden de
        # fecha. Las actas llegan por contrato, asi que no se duplican aunque el contrato
        # tenga varias imputaciones en el proyecto
        for c in contratos:
            c.actas_json = json.dumps([{
                "fecha": date_format(a.fecha_pago) if a.fecha_pago else "—",
                "acta": a.nrodoc_acta or "—", "orden": a.nro_orden or "—",
                "tipo": a.tipo_orden or "—", "concepto": a.concepto or "",
                "valor": number_format(round(a.valor_pago or 0), force_grouping=True),
            } for a in c.actas])
        
        # Lo comprometido, obligado y pagado de cada fuente en este proyecto. Cada etapa
        # se suma en su propia consulta y se cruza por la fuente: sumar RPs y
        # obligaciones en un mismo join multiplicaria las filas
        def por_fuente(modelo, **sumas):
            return {r["fuente"]: r for r in (modelo.objects.filter(proyecto=proyecto)
                                             .values("fuente").annotate(**sumas))}

        comprometido = por_fuente(CompromisoImputacion, t=Sum("valor_compromiso_def"))
        obligado = por_fuente(ObligacionImputacion, o=Sum("valor_obligacion"), p=Sum("pagos"))
        fuentes_por_proyecto = list(Fuente.objects.filter(pk__in=set(comprometido) | set(obligado)))
        for f in fuentes_por_proyecto:
            f.valor_comprometido = comprometido.get(f.pk, {}).get("t") or 0
            f.valor_obligado = obligado.get(f.pk, {}).get("o") or 0
            f.valor_pagado = obligado.get(f.pk, {}).get("p") or 0
        fuentes_por_proyecto_total = {
            "comprometido": sum(f.valor_comprometido for f in fuentes_por_proyecto),
            "obligado": sum(f.valor_obligado for f in fuentes_por_proyecto),
            "pagado": sum(f.valor_pagado for f in fuentes_por_proyecto),
        }

        contexto = {
            **comun,
            **documentos,
            "filas": filas,
            "totales": totales,
            "totales_tarjetas": [
                ("Disponibilidad definitiva", totales["disponibilidad_definitiva"], "cupo apartado en CDP"),
                ("Comprometido", totales["comprometido"], "contratado en firme"),
                ("Obligado", totales["obligado"], "recibido a satisfaccion"),
                ("Pagado", totales["pagado"], "girado por tesoreria"),
            ],
            "desde": desde.isoformat() if desde else "",
            "hasta": hasta.isoformat() if hasta else "",
            "centros": centros,
            "centro": centro,
            "enlaces_pdf": enlaces_pdf,
            "enlaces_excel": enlaces_excel,
            "fuentes_por_proyecto":fuentes_por_proyecto,
            "fuentes_por_proyecto_total":fuentes_por_proyecto_total,
            "contratos": contratos,
            "reservas": self._reservas(proyecto),
            "reservas_total": ReservaImputacion.objects.filter(proyecto=proyecto).aggregate(
                definitivo=Sum("valor_reserva_def"), obligado=Sum("obligaciones_reserva"),
                pagado=Sum("pagos_reserva"), saldo=Sum("saldo_reserva")),
        }
        return TemplateResponse(request, "siifweb/ficha_proyecto.html", contexto)

    def _reservas(self, proyecto):
        """Una fila por reserva, con lo de sus imputaciones de este proyecto, y esas
        imputaciones (CDP de origen, rubro, fuente y valores) para el modal de la fila.

        Filtro y sumas van sobre la misma relacion, asi que comparten el join y no se
        multiplican; las imputaciones llegan aparte, en un solo prefetch.
        """
        def pesos(valor):
            return number_format(round(valor or 0), force_grouping=True)

        reservas = list(
            Reserva.objects.filter(reservas_imputadas__proyecto=proyecto)
            .annotate(definitivo=Sum("reservas_imputadas__valor_reserva_def"),
                      obligado=Sum("reservas_imputadas__obligaciones_reserva"),
                      pagado=Sum("reservas_imputadas__pagos_reserva"),
                      saldo=Sum("reservas_imputadas__saldo_reserva"))
            .select_related("beneficiario")
            .prefetch_related(Prefetch(
                "reservas_imputadas", to_attr="lineas",
                queryset=(ReservaImputacion.objects.filter(proyecto=proyecto)
                          .select_related("cdp_origen", "rubro", "fuente")
                          .order_by("cdp_origen__nro_cdp", "rubro__codigo", "fuente__codigo"))))
            .order_by("vigencia", "fecha_reserva", "nro_reserva"))
        for r in reservas:
            r.lineas_json = json.dumps([{
                "cdp": f"{i.cdp_origen.nro_cdp}/{i.cdp_origen.vigencia}" if i.cdp_origen_id else "—",
                "rubro": i.rubro.codigo, "rubro_nombre": i.rubro.nombre,
                "fuente": i.fuente.nombre,
                "definitivo": pesos(i.valor_reserva_def), "obligado": pesos(i.obligaciones_reserva),
                "pagado": pesos(i.pagos_reserva), "saldo": pesos(i.saldo_reserva),
            } for i in r.lineas])
        return reservas

    def _documentos_filtrados(self, proyecto, desde, hasta, centro=None):
        """CDPs, RPs y obligaciones del proyecto, recortados por el filtro de fechas y,
        si se elige, por el centro de costo del documento.

        Lo usan la ficha y sus descargas, para que el reporte sea exactamente lo que se ve
        en pantalla. Cada tabla se corta por su propia fecha (disponibilidad, registro,
        obligacion); las tarjetas y la cadena por vigencia no pasan por aqui.
        """
        def en_rango(qs, campo):
            if desde:
                qs = qs.filter(**{f"{campo}__gte": desde})
            if hasta:
                qs = qs.filter(**{f"{campo}__lte": hasta})
            if centro:
                # El centro de costo es del documento, igual que la fecha: "cdp__fecha_disp"
                # da "cdp__centro_costo"
                documento = campo.rpartition("__")[0]
                qs = qs.filter(**{f"{documento}__centro_costo" if documento else "centro_costo": centro})
            return qs

        cdps_proyecto = (
            en_rango(Cdp.objects, "fecha_disp")
            .filter(cdps_imputados__proyecto=proyecto)
            .annotate(valor_cdp=Sum("cdps_imputados__valor_disponibilidad_def"))
            .select_related("centro_costo")
            .order_by("fecha_disp")
        )

        # NO re-agregar cdps_proyecto (ya trae annotate sobre la misma relacion).
        # aggregate() sobre annotate() de la misma relacion aplica un DISTINCT implicito
        # y colapsa valores repetidos legitimos (dos imputaciones del mismo CDP con igual
        # valor), dando un total mas bajo. Se suma directo desde las imputaciones.
        cdps_proyecto_total = (en_rango(CdpImputacion.objects, "cdp__fecha_disp")
                               .filter(proyecto=proyecto)
                               .aggregate(t=Sum("valor_disponibilidad_def"))["t"] or 0)

        rps_por_proyecto = (
            en_rango(Compromiso.objects, "fecha_reg")
            .filter(compromisos_imputados__proyecto = proyecto)
            .annotate(valor_rp=Sum("compromisos_imputados__valor_compromiso_def"))
            .select_related("centro_costo")
            .order_by("fecha_reg")
        )

        rps_por_proyecto_total = (
            en_rango(Compromiso.objects, "fecha_reg")
            .filter(compromisos_imputados__proyecto = proyecto)
            .aggregate(t=Sum("compromisos_imputados__valor_compromiso_def"))["t"] or 0
        )

        # Obligaciones del proyecto. El objeto propio viene en el consolidado
        # (columna OBJETO_OBLIG); el del RP queda de respaldo para lo que se cargo
        # antes de que ese campo existiera. Va por subconsulta y no por un segundo
        # Sum: agregar dos relaciones a la vez multiplicaria las filas.
        # El saldo y el pagado salen de SALDO_OBLI y PAGOS del mismo consolidado
        # (valor = saldo + pagado). Los tres suman sobre la MISMA relacion (las
        # imputaciones del proyecto), asi que comparten el join y no se multiplican.
        obligaciones_por_proyecto = (
            en_rango(Obligacion.objects, "fecha_obli")
            .filter(obligaciones_imputadas__proyecto=proyecto)
            .annotate(valor_obli=Sum("obligaciones_imputadas__valor_obligacion"),
                      saldo_oblig=Sum("obligaciones_imputadas__saldo_obli"),
                      pagado_obli=Sum("obligaciones_imputadas__pagos"),
                      objeto_rp=Subquery(ObligacionImputacion.objects
                                         .filter(obligacion=OuterRef("pk"), proyecto=proyecto)
                                         .values("compromiso__objeto_reg")[:1]))
            .select_related("tipo_orden_gasto", "beneficiario", "centro_costo")
            .order_by("vigencia", "fecha_obli", "nro_obligacion")
        )

        totales_obligaciones = (en_rango(ObligacionImputacion.objects, "obligacion__fecha_obli")
                                .filter(proyecto=proyecto)
                                .aggregate(t=Sum("valor_obligacion"), s=Sum("saldo_obli"),
                                           p=Sum("pagos")))
        return {
            "centro_costo": centro,
            "cdps_proyecto": cdps_proyecto,
            "cdps_proyecto_total": cdps_proyecto_total,
            "rps_por_proyecto": rps_por_proyecto,
            "rps_por_proyecto_total": rps_por_proyecto_total,
            "obligaciones_por_proyecto": obligaciones_por_proyecto,
            "obligaciones_por_proyecto_total": totales_obligaciones["t"] or 0,
            "obligaciones_por_proyecto_saldo": totales_obligaciones["s"] or 0,
            "obligaciones_por_proyecto_pagado": totales_obligaciones["p"] or 0,
        }

    # -----------------------------------------------------------------------
    # Reportes: un indice y tres reportes, cada uno con su pagina y su Excel
    # -----------------------------------------------------------------------
    # Cada reporte se define por sus filtros, sus columnas y su constructor (reportes.py),
    # y comparte la pagina (_pagina_reporte). Como la ficha: admin_view() solo exige ser
    # staff, asi que el permiso se revisa dentro.

    def _reportes(self, request):
        """Los tres reportes, con lo que necesita su pagina. Solo los que el usuario abre."""
        from . import reportes

        def lista(nombre):
            return [x.strip() for x in request.GET.get(nombre, "").replace(",", " ").split() if x.strip()]

        def entero(nombre):
            valor = request.GET.get(nombre, "")
            return int(valor) if valor.isdigit() else None

        def vigencias():
            return [int(x) for x in request.GET.getlist("vigencia") if x.isdigit()]

        def texto(nombre, etiqueta, ayuda):
            return {"tipo": "texto", "nombre": nombre, "etiqueta": etiqueta, "ayuda": ayuda,
                    "valor": request.GET.get(nombre, "")}

        def opciones(nombre, etiqueta, queryset):
            return {"tipo": "lista", "nombre": nombre, "etiqueta": etiqueta,
                    "valor": entero(nombre), "opciones": [(o.pk, str(o)) for o in queryset]}

        def chips(disponibles):
            return {"tipo": "vigencias", "nombre": "vigencia", "etiqueta": "Vigencia",
                    "opciones": disponibles, "valor": set(vigencias())}

        filtros_de_la_meta = lambda: [  # noqa: E731
            texto("mt", "MT", "Una o varias, separadas por coma o espacio"),
            opciones("linea", "Línea estratégica", LineaEstrategica.objects.order_by("descripcion")),
            opciones("sector", "Sector PDD", SectorPDD.objects.order_by("descripcion")),
            opciones("dependencia", "Dependencia responsable",
                     DependenciaResponsable.objects.filter(metaindicador__isnull=False).distinct()),
        ]
        de_la_meta = lambda: {"mts": lista("mt"), "linea": entero("linea"),  # noqa: E731
                              "sector": entero("sector"), "dependencia": entero("dependencia")}
        todos = [
            {
                "clave": "financiero", "titulo": "Reporte Financiero del proyecto",
                "url": "admin:siifweb_proyecto_reporte_financiero", "archivo": "reporte_financiero",
                "permiso": self.has_view_permission(request),
                "filtros": lambda: [
                    chips(sorted(Cdp.objects.values_list("vigencia", flat=True).distinct())),
                    texto("bpin", "BPIN", "Uno o varios, separados por coma o espacio"),
                    texto("nombre", "Nombre del proyecto", "Parte del nombre..."),
                ],
                "columnas": lambda: reportes.COLUMNAS,
                "construir": lambda: reportes.construir(vigencias=vigencias(), bpines=lista("bpin"),
                                                        nombre=request.GET.get("nombre", "").strip()),
                "excel": {},
            },
            {
                "clave": "plan", "titulo": "Plan indicativo",
                "url": "admin:siifweb_proyecto_reporte_plan", "archivo": "plan_indicativo",
                "permiso": request.user.has_perm("siifweb.view_metaindicador"),
                "filtros": filtros_de_la_meta,
                "columnas": reportes.columnas_plan,
                "construir": lambda: reportes.construir_plan(**de_la_meta()),
                "excel": {"hoja": "Plan indicativo", "tabla": "PlanIndicativo", "anchos_col": {}},
            },
            {
                "clave": "proyectos", "titulo": "Proyectos programados",
                "url": "admin:siifweb_proyecto_reporte_proyectos", "archivo": "proyectos_programados",
                "permiso": request.user.has_perm("siifweb.view_programacionproyectos"),
                "filtros": lambda: [
                    # order_by() vacio: el orden por defecto incluye meta__codigo y con el
                    # el distinct repetiria cada ano una vez por meta
                    chips(sorted(v for v in ProgramacionMeta.objects.order_by()
                                 .values_list("vigencia", flat=True).distinct() if v)),
                    *filtros_de_la_meta(),
                    opciones("tipo_banco", "Tipo de banco", TipoBanco.objects.all()),
                    texto("bpin", "BPIN", "Uno o varios, separados por coma o espacio"),
                    texto("nombre", "Nombre del proyecto", "Parte del nombre..."),
                ],
                "columnas": reportes.columnas_proyectos,
                "construir": lambda: reportes.construir_proyectos(
                    **de_la_meta(), vigencias=vigencias(), tipo_banco=entero("tipo_banco"),
                    bpines=lista("bpin"), nombre=request.GET.get("nombre", "").strip()),
                "excel": {"hoja": "Proyectos programados", "tabla": "ProyectosProgramados",
                          "anchos_col": {"nombre_proyecto": 60}},
            },
        ]
        return [r for r in todos if r["permiso"]]

    def reportes_indice(self, request):
        """La pagina de Reportes: los reportes que el usuario puede abrir."""
        disponibles = self._reportes(request)
        if not disponibles:
            raise PermissionDenied
        contexto = {
            **self.admin_site.each_context(request),
            "title": "Reportes",
            "reportes": [{**r, "url": reverse(r["url"]), "n_columnas": len(r["columnas"]())}
                         for r in disponibles],
        }
        return TemplateResponse(request, "siifweb/reportes.html", contexto)

    def _pagina_reporte(self, request, clave):
        """GET normal -> pagina con filtros; con descargar=xlsx (mas los filtros) -> el Excel."""
        from . import reportes
        import io

        reporte = next((r for r in self._reportes(request) if r["clave"] == clave), None)
        if reporte is None:
            raise PermissionDenied
        columnas = reporte["columnas"]()

        if request.GET.get("descargar"):
            wb = reportes.a_excel(reporte["construir"](), columnas=columnas, **reporte["excel"])
            buffer = io.BytesIO()
            wb.save(buffer)
            resp = HttpResponse(
                buffer.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp["Content-Disposition"] = (
                f'attachment; filename="{reporte["archivo"]}_{timezone.localdate():%Y%m%d}.xlsx"')
            return resp

        contexto = {
            **self.admin_site.each_context(request),
            "title": reporte["titulo"],
            "reporte": reporte,
            "filtros": reporte["filtros"](),
            "columnas": [c[1] for c in columnas],
            "limpiar": reverse(reporte["url"]),
            "volver": reverse("admin:siifweb_proyecto_reportes"),
        }
        return TemplateResponse(request, "siifweb/reporte.html", contexto)

    def reporte_financiero(self, request):
        return self._pagina_reporte(request, "financiero")

    def reporte_plan(self, request):
        return self._pagina_reporte(request, "plan")

    def reporte_proyectos(self, request):
        return self._pagina_reporte(request, "proyectos")

    def tablero(self, request):
        """Tablero de gestion por dependencia responsable (POAI).

        Una fila por dependencia y, al elegir una, la misma tabla por proyecto. Cada
        etapa se corta por su propia fecha (el CDP por la de expedicion, el pago por la
        del acta), que es lo que hace comparable un corte semanal o mensual.

        Como el reporte financiero: `admin_view()` no mira permisos de modelo.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied

        def entero(nombre):
            valor = request.GET.get(nombre, "")
            return int(valor) if valor.isdigit() else None

        preset = request.GET.get("preset", "")
        desde, hasta = tablero.rango_del_preset(preset)
        if not preset:
            desde = fecha_del_get(request, "desde")
            hasta = fecha_del_get(request, "hasta")

        filtros = tablero.Filtros(
            desde=desde, hasta=hasta,
            vigencias=tuple(int(v) for v in request.GET.getlist("vigencia") if v.isdigit()),
            dependencia=entero("dependencia"), clasificacion=entero("clasificacion"))

        filas, totales = tablero.por_dependencia(filtros)
        # El conteo de documentos ya no se muestra, pero es lo que distingue un periodo
        # sin movimiento de una dependencia que no gestiono.
        movimientos = sum(totales[m] for m in ("cdps", "rps", "obligaciones", "actas"))

        # El enlace de cada fila conserva el corte de fechas y cambia solo la dependencia
        def con_dependencia(pk):
            parametros = request.GET.copy()
            parametros["dependencia"] = pk
            return f"?{parametros.urlencode()}"

        for fila in filas:
            fila["url"] = con_dependencia(fila["llave"])

        filas_proyecto, totales_proyecto = tablero.por_proyecto(filtros)
        for fila in filas_proyecto:
            fila["url"] = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(fila["llave"],))

        elegida = None
        if filtros.dependencia:
            elegida = next((f for f in filas if f["llave"] == filtros.dependencia), None)

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Avance financiero",
            **tablero.catalogos(),
            "filas": filas,
            "totales": totales,
            "filas_proyecto": filas_proyecto,
            "totales_proyecto": totales_proyecto,
            "dependencia_elegida": elegida,
            "tarjetas": [
                ("Proyectos", totales["proyectos"], "con dependencia responsable", False),
                ("Comprometido", totales["comprometido"], "valor de los RP", True),
                ("Obligado", totales["obligado"], "recibido a satisfaccion", True),
                ("Pagado", totales["pagado"], "girado sobre las obligaciones", True),
            ],
            "preset": preset,
            "presets": (("", "Rango libre"), ("semana", "Esta semana"), ("mes", "Este mes"),
                        ("trimestre", "Este trimestre"), ("anio", "Este año")),
            # Los reportes se cargan por tandas: el corte de hoy casi nunca es el corte
            # de los datos. Sin este aviso, un periodo reciente se lee como una
            # dependencia que no hizo nada, cuando lo que pasa es que aun no se ha cargado.
            "ultimo_dato": tablero.ultimo_movimiento(),
            "sin_movimiento": movimientos == 0,
            "leyenda_periodo": (f"Del {desde} al {hasta}" if desde and hasta
                                else f"Desde {desde}" if desde
                                else f"Hasta {hasta}" if hasta
                                else "Toda la historia cargada"),
            "desde": desde.isoformat() if desde else "",
            "hasta": hasta.isoformat() if hasta else "",
            "vigencias_disponibles": sorted(Cdp.objects.values_list("vigencia", flat=True).distinct()),
            "vigencias_sel": set(filtros.vigencias),
            "dependencia_sel": filtros.dependencia,
            "clasificacion_sel": filtros.clasificacion,
            "limpiar": reverse("admin:siifweb_proyecto_tablero"),
            "volver": reverse("admin:siifweb_proyecto_changelist"),
        }
        return TemplateResponse(request, "siifweb/tablero.html", contexto)

    def get_urls(self):
        # Las URLs propias van ANTES de las del admin: '<path:object_id>/' las capturaria
        propia = [
            path("reportes/", self.admin_site.admin_view(self.reportes_indice),
                 name="siifweb_proyecto_reportes"),
            path("reporte-financiero/", self.admin_site.admin_view(self.reporte_financiero),
                 name="siifweb_proyecto_reporte_financiero"),
            path("reporte-plan-indicativo/", self.admin_site.admin_view(self.reporte_plan),
                 name="siifweb_proyecto_reporte_plan"),
            path("reporte-proyectos-programados/", self.admin_site.admin_view(self.reporte_proyectos),
                 name="siifweb_proyecto_reporte_proyectos"),
            path("tablero/", self.admin_site.admin_view(self.tablero),
                 name="siifweb_proyecto_tablero"),
            path("<path:object_id>/ficha-ejecucion/",
                 self.admin_site.admin_view(self.ficha_ejecucion),
                 name="siifweb_proyecto_ficha_ejecucion"),
            path("<int:pk>/programacion-financiera/matriz/", self.admin_site.admin_view(self.pf_matriz),
                 name="siifweb_proyecto_pf_matriz"),
            path("<int:pk>/programacion-financiera/guardar/", self.admin_site.admin_view(self.pf_guardar),
                 name="siifweb_proyecto_pf_guardar"),
            path("<int:pk>/programacion-financiera/elegir/", self.admin_site.admin_view(self.pf_elegir),
                 name="siifweb_proyecto_pf_elegir"),
            path("<path:object_id>/programacion-financiera/",
                 self.admin_site.admin_view(self.programacion_financiera),
                 name="siifweb_proyecto_programacion_financiera"),
            path("<path:object_id>/observaciones/", self.admin_site.admin_view(self.observaciones),
                 name="siifweb_proyecto_observaciones"),
        ]
        return propia + super().get_urls()

    # -- Programacion financiera: pantalla propia con HTMX, como las distribuciones del CUIPO,
    # pero con un boton Guardar y con las vigencias como un listado mas (vigencias, fuentes y
    # metas). Logica en siifweb/programacion_financiera.py. Ver pide view_programacionfinanciera;
    # guardar, agregar, cambiar y borrar.

    # -- Observaciones del proyecto: pantalla propia (no un inline: el detalle solo edita el
    # proyecto). Ver pide view_observacionproyectosiifweb; agregar, editar y borrar, su permiso.

    def has_ver_observaciones_permission(self, request, object_id=None):
        return request.user.has_perm("siifweb.view_observacionproyectosiifweb")

    @action(description="Observaciones", url_path="observaciones", icon="chat", permissions=["ver_observaciones"])
    def observaciones(self, request, object_id):
        """Las observaciones del proyecto, de la mas reciente a la mas antigua, para agregar,
        editar y borrar."""
        if not self.has_ver_observaciones_permission(request):
            raise PermissionDenied
        proyecto = self.get_object(request, str(object_id))
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")
        puede = {p: request.user.has_perm(f"siifweb.{p}_observacionproyectosiifweb") for p in ("add", "change", "delete")}
        if request.method == "POST":
            accion = request.POST.get("accion", "")
            permiso = {"agregar": "add", "editar": "change", "borrar": "delete"}.get(accion)
            if permiso is None or not puede[permiso]:
                raise PermissionDenied
            texto = (request.POST.get("texto") or "").strip()
            if accion == "agregar":
                if texto:
                    ObservacionProyectoSiifweb.objects.create(proyecto=proyecto, texto=texto, usuario=request.user)
                    self.message_user(request, "Observación agregada.", messages.SUCCESS)
                else:
                    self.message_user(request, "Escriba la observación antes de agregarla.", messages.ERROR)
            else:
                observacion = proyecto.observaciones_siifweb.filter(pk=request.POST.get("id") or 0).first()
                if observacion is None:
                    raise Http404("Esa observación ya no existe.")
                if not observacion.editable:
                    self.message_user(request, f"Pasados {observacion.DIAS_EDITABLE} días una observación ya no "
                                               f"se puede modificar ni borrar.", messages.ERROR)
                elif not observacion.es_de(request.user):
                    self.message_user(request, "Solo quien escribió la observación la puede modificar o borrar.",
                                      messages.ERROR)
                elif accion == "borrar":
                    observacion.delete()
                    self.message_user(request, "Observación borrada.", messages.SUCCESS)
                elif texto:
                    observacion.texto = texto
                    observacion.save()
                    self.message_user(request, "Observación guardada.", messages.SUCCESS)
                else:
                    self.message_user(request, "La observación no puede quedar vacía.", messages.ERROR)
            return HttpResponseRedirect(request.path)
        observaciones = list(proyecto.observaciones_siifweb.select_related("usuario"))
        for o in observaciones:
            o.mia = o.es_de(request.user)   # solo quien la escribio ve editar y borrar
        contexto = {**self.admin_site.each_context(request), "title": f"Observaciones {proyecto.bpin or ''}",
                    "proyecto": proyecto, "observaciones": observaciones, "puede": puede}
        return TemplateResponse(request, "siifweb/observaciones_proyecto.html", contexto)

    # Las pestanas de la pantalla de programacion: (clave, titulo, modelo de sus permisos)
    PANELES_PROGRAMACION = (("financiera", "Financiera", "programacionfinanciera"),
                            ("fisica", "Física", "programacionfisica"))

    def _paneles_pf(self, request):
        """Las pestanas que el usuario puede ver."""
        return [(clave, titulo) for clave, titulo, modelo in self.PANELES_PROGRAMACION
                if request.user.has_perm(f"siifweb.view_{modelo}")]

    def has_ver_programacion_permission(self, request, object_id=None):
        return bool(self._paneles_pf(request))

    def _panel_pf(self, request, datos):
        """La pestana pedida si el usuario la puede ver; si no, la primera que pueda."""
        paneles = [clave for clave, _ in self._paneles_pf(request)]
        if not paneles:
            raise PermissionDenied
        return datos.get("panel") if datos.get("panel") in paneles else paneles[0]

    def _puede_programar(self, request, panel="financiera"):
        modelo = {clave: modelo for clave, _, modelo in self.PANELES_PROGRAMACION}[panel]
        return all(request.user.has_perm(f"siifweb.{p}_{modelo}") for p in ("add", "change", "delete"))

    def _proyecto_programable(self, request, object_id):
        if not self.has_ver_programacion_permission(request):
            raise PermissionDenied
        proyecto = self.get_object(request, str(object_id))
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")
        return proyecto

    def _contexto_pf(self, request, proyecto, panel, mensaje="", parcial=False, advertencia="", **kwargs):
        matriz = programacion_financiera.matriz_fisica if panel == "fisica" else programacion_financiera.matriz
        return {"proyecto": proyecto, "panel": panel, "m": matriz(proyecto, **kwargs), "mensaje": mensaje,
                "advertencia": advertencia, "parcial": parcial, "editable": self._puede_programar(request, panel)}

    def _matriz_pf(self, request, proyecto, panel, **kwargs):
        contexto = self._contexto_pf(request, proyecto, panel, parcial=True, **kwargs)
        plantilla = "siifweb/_programacion_fisica.html" if panel == "fisica" else "siifweb/_programacion_matriz.html"
        return HttpResponse(render_to_string(plantilla, contexto, request=request))

    @action(description="Programación", url_path="programacion-financiera", icon="account_balance_wallet",
            permissions=["ver_programacion"])
    def programacion_financiera(self, request, object_id):
        """La programacion del proyecto por vigencia, en dos pestanas: financiera (fuente por meta)
        y fisica (valor por meta)."""
        proyecto = self._proyecto_programable(request, object_id)
        panel = self._panel_pf(request, request.GET)
        proyecto.refresh_from_db(fields=["valor_programado"])
        contexto = {**self.admin_site.each_context(request), "title": f"Programación {proyecto.bpin or ''}",
                    "paneles": self._paneles_pf(request), **self._contexto_pf(request, proyecto, panel)}
        return TemplateResponse(request, "siifweb/programacion_financiera.html", contexto)

    def pf_matriz(self, request, pk):
        """La pestana otra vez, sin guardar: con una vigencia agregada o quitada, o una fuente o
        meta agregada o quitada en una vigencia (en=<vigencia>), y con lo que ya se habia digitado."""
        proyecto = self._proyecto_programable(request, pk)
        datos = request.GET
        panel = self._panel_pf(request, datos)
        digitados = programacion_financiera.digitados_de(datos)
        estado = programacion_financiera.cambiar_estado(programacion_financiera.estado_de(datos), datos,
                                                        proyecto=proyecto, fisica=panel == "fisica",
                                                        digitados=digitados)
        return self._matriz_pf(request, proyecto, panel, estado=estado, digitados=digitados)

    def pf_guardar(self, request, pk):
        """Deja la programacion de la pestana como se ve. Con un error en alguna casilla no guarda nada."""
        proyecto = self._proyecto_programable(request, pk)
        if request.method != "POST":
            return HttpResponseBadRequest("Solo POST")
        panel = self._panel_pf(request, request.POST)
        if not self._puede_programar(request, panel):
            raise PermissionDenied
        estado = programacion_financiera.estado_de(request.POST)
        digitados = programacion_financiera.digitados_de(request.POST)
        guardar = programacion_financiera.guardar_fisica if panel == "fisica" else programacion_financiera.guardar
        errores, mensaje = guardar(proyecto, estado, digitados)
        proyecto.refresh_from_db(fields=["valor_programado"])
        if errores:
            return self._matriz_pf(request, proyecto, panel, estado=estado, digitados=digitados, errores=errores)
        # Guarda aunque las metas no coincidan con la otra pestana (se puede llenar cualquiera
        # primero), pero lo advierte
        return self._matriz_pf(request, proyecto, panel, mensaje=mensaje, estado=estado,
                               advertencia=programacion_financiera.mensaje_descuadre(proyecto))

    def pf_elegir(self, request, pk):
        """La ventana para agregar una vigencia; en una vigencia (en=), una entidad aportante, una
        meta o una fuente de una entidad (entidad=); o para asignar la entidad a lo que no la tiene
        (tipo=entidad&asignar=1). Buscador y listado por paginas. Con solo=resultados devuelve solo
        el listado."""
        proyecto = self._proyecto_programable(request, pk)
        datos = request.GET
        self._panel_pf(request, datos)
        tipo = datos.get("tipo")
        tipo = tipo if tipo in ("vigencia", "entidad", "meta") else "fuente"
        estado = programacion_financiera.estado_de(datos)
        en = datos.get("en", "")
        en = int(en) if en.isdigit() and int(en) in estado else None
        entidad, programadas = None, set()
        if tipo == "vigencia":
            presentes = list(estado)
        else:
            if en is None:
                return HttpResponseBadRequest("Falta la vigencia")
            bloque = estado[en]
            if tipo == "entidad":
                presentes = bloque["entidades"]
            elif tipo == "fuente":
                entidad = datos.get("entidad", "")
                entidad = int(entidad) if entidad.isdigit() else None
                if entidad is None or entidad == programacion_financiera.SIN_ENTIDAD or entidad not in bloque["entidades"]:
                    return HttpResponseBadRequest("Falta la entidad aportante")
                presentes = bloque["fuentes"].get(entidad, [])
            else:
                presentes = bloque["metas"]
                programadas = programacion_financiera.metas_programadas(proyecto, en)
        asignar = tipo == "entidad" and datos.get("asignar") == "1"
        texto = datos.get("q", "")
        opciones = programacion_financiera.opciones(tipo, texto, presentes, datos.get("pagina", 1), programadas)
        contexto = {"proyecto": proyecto, "tipo": tipo, "texto": texto, "en": en or "", "entidad": entidad or "",
                    "nombre_entidad": EntidadAportante.objects.filter(pk=entidad).first() if entidad else None,
                    "asignar": "1" if asignar else "", "accion": "asignar_entidad" if asignar else f"agregar_{tipo}",
                    **opciones}
        plantilla = "siifweb/_programacion_opciones.html" if datos.get("solo") == "resultados" \
            else "siifweb/_programacion_elegir.html"
        return HttpResponse(render_to_string(plantilla, contexto, request=request))


@admin.register(Tercero)
class TerceroAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("codigo", "nombre", "n_contratos")
    search_fields = ("codigo", "nombre")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("contratos", distinct=True))

    @display(description="Contratos", ordering="n")
    def n_contratos(self, obj):
        return obj.n


class HomologadoCUIPO(admin.SimpleListFilter):
    """Si el recurso o el rubro ya tiene su codigo CUIPO (anotacion homologado_cuipo)."""
    title = "homologado (CUIPO)"
    parameter_name = "homologado"

    def lookups(self, request, model_admin):
        return (("si", "Sí"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() in ("si", "no"):
            return queryset.filter(homologado_cuipo=self.value() == "si")
        return queryset


class EnElCorteCUIPO(admin.SimpleListFilter):
    """Solo los que tienen filas en el corte que se esta reportando (inversion con valores)."""
    title = "en el corte del CUIPO"
    parameter_name = "en_corte"
    campo = None          # "recurso" o "rubro" de la fila de ejecucion

    def lookups(self, request, model_admin):
        return (("si", "Con filas en el corte"), ("no", "Sin filas en el corte"))

    def queryset(self, request, queryset):
        if self.value() not in ("si", "no"):
            return queryset
        from cuipo.derivacion import corte_de_trabajo, filas_cuipo
        corte = corte_de_trabajo()
        codigos = filas_cuipo(corte).values(self.campo) if corte else []
        return queryset.filter(codigo__in=codigos) if self.value() == "si" else queryset.exclude(codigo__in=codigos)


class RecursoEnElCorte(EnElCorteCUIPO):
    campo = "recurso"


class RubroEnElCorte(EnElCorteCUIPO):
    campo = "rubro"


@admin.register(Rubro)
class RubroAdmin(ModelAdmin):
    """Con la columna Homologado (CUIPO): si el rubro tiene concepto CUIPO valido, por una
    homologacion o por su mismo codigo (activo y habilitado para departamentos)."""
    compressed_fields = True
    list_display = ("codigo", "nombre", "tipo", "homologado", "concepto_cuipo")
    list_filter_submit = True
    list_filter = (HomologadoCUIPO, RubroEnElCorte, ("tipo", ChoicesDropdownFilter))
    search_fields = ("codigo", "nombre")

    def get_queryset(self, request):
        from cuipo.models import ConceptoCUIPO, HomologacionRubro
        valido = {"activo": True, "habilitado_departamentos": True}
        excepcion = HomologacionRubro.objects.filter(rubro=OuterRef("pk"), **{f"concepto__{k}": v for k, v in valido.items()})
        mismo = ConceptoCUIPO.objects.filter(codigo=OuterRef("codigo"), **valido)
        return super().get_queryset(request).annotate(
            homologado_cuipo=Exists(excepcion) | Exists(mismo),
            por_excepcion=Subquery(HomologacionRubro.objects.filter(rubro=OuterRef("pk")).values("concepto__codigo")[:1]),
            por_mismo=Exists(mismo))

    @display(description="Homologado", boolean=True, ordering="homologado_cuipo")
    def homologado(self, obj):
        return obj.homologado_cuipo

    @display(description="Concepto CUIPO")
    def concepto_cuipo(self, obj):
        if obj.por_excepcion:
            return f"{obj.por_excepcion} (homologación)"
        return f"{obj.codigo} (mismo código)" if obj.por_mismo else "—"


@admin.register(Fuente)
class FuenteAdmin(ModelAdmin):
    """Con la columna Homologado (CUIPO): si el recurso tiene fuente CUIPO para la vigencia que
    se esta reportando (la del ultimo corte que cierra trimestre)."""
    compressed_fields = True
    list_display = ("codigo", "nombre", "homologado", "fuente_cuipo")
    list_filter_submit = True
    list_filter = (HomologadoCUIPO, RecursoEnElCorte)
    search_fields = ("codigo", "nombre")

    def get_queryset(self, request):
        from cuipo.derivacion import vigencia_de_trabajo
        from cuipo.models import HomologacionFuente
        homologacion = HomologacionFuente.objects.filter(fuente_siifweb=OuterRef("pk"), vigencia=vigencia_de_trabajo())
        return super().get_queryset(request).annotate(
            homologado_cuipo=Exists(homologacion),
            fuente_cuipo_codigo=Subquery(homologacion.values("fuente_cuipo__codigo")[:1]))

    @display(description="Homologado", boolean=True, ordering="homologado_cuipo")
    def homologado(self, obj):
        return obj.homologado_cuipo

    @display(description="Fuente CUIPO")
    def fuente_cuipo(self, obj):
        if not obj.fuente_cuipo_codigo:
            return "—"
        from cuipo.derivacion import vigencia_de_trabajo
        return f"{obj.fuente_cuipo_codigo} ({vigencia_de_trabajo()})"


class CentroEnElCorte(EnElCorteCUIPO):
    campo = "centro_costo"


class SeccionCUIPO(admin.SimpleListFilter):
    title = "sección CUIPO"
    parameter_name = "seccion"

    def lookups(self, request, model_admin):
        return (("regla", "Con regla de sección"), ("defecto", "Por defecto (16.0)"))

    def queryset(self, request, queryset):
        if self.value() in ("regla", "defecto"):
            return queryset.filter(regla_seccion_cuipo__isnull=self.value() == "defecto")
        return queryset


@admin.register(CentroCosto)
class CentroCostoAdmin(ModelAdmin):
    """Con la columna Sección CUIPO: la de su regla o, sin regla, 16.0 (administracion central).
    Sirve para notar una dependencia que deberia reportarse en otra seccion."""
    compressed_fields = True
    list_display = ("codigo", "nombre", "seccion_cuipo")
    list_filter_submit = True
    list_filter = (SeccionCUIPO, CentroEnElCorte)
    list_select_related = ("regla_seccion_cuipo__seccion",)
    search_fields = ("codigo", "nombre")

    @display(description="Sección CUIPO", label={"regla": "success", "defecto": "info"})
    def seccion_cuipo(self, obj):
        regla = getattr(obj, "regla_seccion_cuipo", None)
        if regla:
            return "regla", f"{regla.seccion.codigo} {regla.seccion.descripcion}"
        return "defecto", "16.0 por defecto"


@admin.register(DependenciaResponsable)
class DependenciaResponsableAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre", "n_proyectos")
    search_fields = ("nombre",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("proyectos", distinct=True))

    @display(description="Proyectos", ordering="n")
    def n_proyectos(self, obj):
        return obj.n


@admin.register(Clasificacion)
class ClasificacionAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre", "n_proyectos")
    search_fields = ("nombre",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("proyectos", distinct=True))

    @display(description="Proyectos", ordering="n")
    def n_proyectos(self, obj):
        return obj.n


# ---------------------------------------------------------------------------
# SECOP II
# ---------------------------------------------------------------------------

class BpinDelContratoInline(ImputacionInline):
    """Los BPIN que financian este contrato: 18 contratos tienen mas de uno."""
    model = BpinProceso
    fk_name = "contrato_secop"
    verbose_name_plural = "BPIN que financian el contrato"
    fields = ("bpin", "proyecto", "anio", "validacion_bpin")
    readonly_fields = fields


class ContratoDelProcesoInline(ImputacionInline):
    model = ContratoSecop
    fk_name = "proceso"
    verbose_name_plural = "Contratos adjudicados"
    fields = ("referencia", "estado", "proveedor", "valor", "fecha_firma", "fecha_fin")
    readonly_fields = fields


@admin.register(ProcesoSecop)
class ProcesoSecopAdmin(SoloLectura):
    inlines = (ContratoDelProcesoInline,)
    list_display = ("id_proceso", "id_portafolio", "estado_procedimiento",
                    "fecha_publicacion", "n_contratos")
    list_filter = (("estado_procedimiento", ChoicesDropdownFilter),
                   ("fecha_publicacion", RangeDateFilter))
    search_fields = ("id_proceso", "id_portafolio")
    ordering = ("-fecha_publicacion",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("contratos_del_proceso", distinct=True))

    @display(description="Contratos", ordering="n")
    def n_contratos(self, obj):
        return obj.n


@admin.register(ContratoSecop)
class ContratoSecopAdmin(SoloLectura):
    inlines = (BpinDelContratoInline,)
    list_display = ("referencia", "estado", "proveedor", "valor_fmt", "fecha_firma",
                    "fecha_fin", "objeto_corto", "ver_en_secop")
    list_filter = (("estado", ChoicesDropdownFilter), ("fecha_firma", RangeDateFilter))
    search_fields = ("referencia", "id_contrato", "objeto", "proveedor__codigo", "proveedor__nombre")
    ordering = ("-fecha_firma",)
    list_filter_submit = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("proveedor", "proceso")

    @display(description="Valor", ordering="valor")
    def valor_fmt(self, obj):
        return pesos(obj.valor)

    @display(description="Objeto")
    def objeto_corto(self, obj):
        return (obj.objeto or "")[:70]

    @display(description="")
    def ver_en_secop(self, obj):
        if not obj.url_proceso:
            return "-"
        return format_html('<a href="{}" target="_blank" class="text-primary-600" '
                           'title="Ver el proceso en SECOP II">'
                           '<i class="material-symbols-outlined">open_in_new</i></a>', obj.url_proceso)


@admin.register(BpinProceso)
class BpinProcesoAdmin(SoloLectura):
    list_display = ("bpin", "proyecto", "anio", "proceso", "contrato_secop", "validacion_bpin")
    list_filter = (("anio", ChoicesDropdownFilter), ("validacion_bpin", ChoicesDropdownFilter),
                   ("proyecto", RelatedDropdownFilter))
    search_fields = ("bpin", "proceso__id_proceso", "contrato_secop__referencia")
    ordering = ("bpin",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("proyecto", "proceso", "contrato_secop")


@admin.register(OrdenGasto)
class OrdenGastoAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre",)
    search_fields = ("nombre",)


# ---------------------------------------------------------------------------
# Plan de desarrollo (metas traidas de SUTEC)
# ---------------------------------------------------------------------------
# Catalogos que mantiene el equipo, asi que son editables, al contrario de lo que llega de
# los reportes. Los catalogos grandes van con autocompletado: 376 indicadores y productos
# MGA, 108 indicadores PDD.

def corto(texto, largo=90):
    """Las descripciones del plan son largas: en el listado basta el comienzo."""
    texto = texto or ""
    return texto if len(texto) <= largo else texto[:largo].rstrip() + "..."


class CatalogoPlan(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    search_fields = ("codigo", "descripcion")
    list_filter_submit = True

    @display(description="Nombre", ordering="descripcion")
    def nombre(self, obj):
        return corto(obj.descripcion)


@admin.register(PlanDesarrollo)
class PlanDesarrolloAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "vigencia_inicio", "vigencia_fin", "estado")


@admin.register(LineaEstrategica)
class LineaEstrategicaAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "plan_desarrollo", "estado")
    list_filter = (("plan_desarrollo", RelatedDropdownFilter), "estado")
    list_select_related = ("plan_desarrollo",)


@admin.register(SectorPDD)
class SectorPDDAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "linea_estrategica", "estado")
    list_filter = (("linea_estrategica", RelatedDropdownFilter), "estado")
    list_select_related = ("linea_estrategica",)


@admin.register(ProgramaPDD)
class ProgramaPDDAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "sector_pdd", "estado")
    list_filter = (("sector_pdd", RelatedDropdownFilter), "estado")
    list_select_related = ("sector_pdd",)


@admin.register(IndicadorPDD)
class IndicadorPDDAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "n_programas", "estado")
    list_filter = (("programas_pdd", RelatedDropdownFilter), "estado")
    autocomplete_fields = ("programas_pdd",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("programas_pdd", distinct=True))

    @display(description="Programas", ordering="n")
    def n_programas(self, obj):
        return obj.n


class VigenciaMetaInline(TabularInline):
    model = VigenciaMeta
    extra = 0
    fields = ("vigencia", "valor")
    ordering = ("vigencia",)
    tab = True


class MetaIndicadorForm(forms.ModelForm):
    """Los indicadores PDD de la meta tienen que ser de su programa.

    El modelo lo vigila con una senal sobre la relacion, pero ahi el error sale como un
    500. Aqui sale como aviso en el campo. Y la validacion del modelo recibe los
    indicadores que se van a guardar, no los de la base: cambiar programa e indicadores a
    la vez no da un error falso.
    """

    class Meta:
        model = MetaIndicador
        fields = "__all__"

    def clean(self):
        datos = super().clean()
        programa, indicadores = datos.get("programa_pdd"), datos.get("indicadores_pdd")
        if programa is not None and indicadores is not None:
            ids = list(indicadores.values_list("pk", flat=True))
            fuera = indicadores_fuera_del_programa(programa.pk, ids)
            if fuera:
                self.add_error("indicadores_pdd", "No pertenecen al programa elegido: %s."
                               % ", ".join(str(i) for i in fuera))
            # Con el error ya en su campo, el modelo no lo repite en el del programa
            self.instance._indicadores_pdd_por_guardar = [] if fuera else ids
        return datos


def cargas_llave(nombre):
    """El nombre de un proyecto para compararlo: sin mayusculas, tildes, signos ni espacios
    de mas. La misma regla con que se agruparon los proyectos del Access."""
    import re
    import unicodedata
    limpio = re.sub(r"\s+", " ", nombre or "").strip(" .,;:-")
    limpio = unicodedata.normalize("NFKD", limpio).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^\w ]", "", limpio).strip()


def leer_programaciones(post, sin_vigencia=False):
    """Las filas de programacion de un modal de la ficha de la meta.

    Llegan como listas paralelas (programacion, meta, vigencia, meta_vigencia). Devuelve
    (filas, error), con cada fila como (id o None, meta, vigencia, valor). sin_vigencia
    admite la vigencia vacia, que traen algunas programaciones del Access.
    """
    metas = post.getlist("meta")
    metas_ok = {m.pk: m for m in MetaIndicador.objects.filter(pk__in=[x for x in metas if x.isdigit()])}
    vigencias_ok = {v for v, _ in listado_vigencias_metas()}
    ids = post.getlist("programacion")
    filas, vistas = [], set()
    for i, (m, v, valor) in enumerate(zip(metas, post.getlist("vigencia"), post.getlist("meta_vigencia")),
                                      start=1):
        meta = metas_ok.get(int(m)) if m.isdigit() else None
        if meta is None:
            return [], f"Fila {i}: elija la meta."
        if v == "" and sin_vigencia:
            vigencia = None
        elif not v.isdigit() or int(v) not in vigencias_ok:
            return [], f"Fila {i}: elija la vigencia."
        else:
            vigencia = int(v)
        valor = (valor or "").strip().replace(",", ".")
        if valor:
            try:
                valor = Decimal(valor)
            except InvalidOperation:
                return [], f"Fila {i}: la meta de la vigencia tiene que ser un número."
            if valor.as_tuple().exponent < -5 or valor < 0:
                return [], (f"Fila {i}: la meta de la vigencia admite hasta cinco decimales "
                            "y no puede ser negativa.")
        else:
            valor = None
        if (meta.pk, vigencia) in vistas:
            return [], f"Fila {i}: {meta.codigo} en {vigencia or 'sin vigencia'} está repetida."
        vistas.add((meta.pk, vigencia))
        id_ = ids[i - 1] if i <= len(ids) else ""
        filas.append((int(id_) if id_.isdigit() else None, meta, vigencia, valor))
    return filas, None


def leer_proyecto(post):
    """BPIN, nombre, tipo de banco y municipios de un modal. Devuelve (datos, error)."""
    nombre = " ".join((post.get("nombre") or "").split())
    bpin = (post.get("bpin") or "").strip()
    if not nombre:
        return None, "Escriba el nombre del proyecto."
    if bpin and (not bpin.isdigit() or len(bpin) > 20):
        return None, "El BPIN lleva solo números, hasta 20."
    tipo = post.get("tipo_banco") or ""
    return {"bpin": bpin, "nombre": nombre,
            "tipo_banco": TipoBanco.objects.filter(pk=tipo).first() if tipo.isdigit() else None,
            "municipios": Municipio.objects.filter(
                pk__in=[x for x in post.getlist("municipios") if x.isdigit()])}, None


def proyecto_repetido(bpin, nombre, excluir=None):
    """El proyecto programado que ya usa ese BPIN o ese nombre (comparado con cargas_llave).
    Sin BPIN o sin nombre, esa parte no se revisa."""
    otros = ProgramacionProyectos.objects.exclude(pk=excluir) if excluir else ProgramacionProyectos.objects.all()
    llave = cargas_llave(nombre) if nombre else None
    return (otros.filter(bpin=bpin).first() if bpin else None) or \
        (next((p for p in otros.only("pk", "bpin", "nombre") if cargas_llave(p.nombre) == llave), None)
         if llave else None)


def puede_reprogramar(usuario):
    """Cambiar las programaciones de un proyecto crea, modifica y borra filas."""
    return all(usuario.has_perm(f"siifweb.{a}_programacionmeta") for a in ("add", "change", "delete"))


def valor_editable(valor):
    """La meta de la vigencia como se escribe en el modal: coma decimal y sin ceros de mas."""
    if valor is None:
        return ""
    texto = format(valor, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def cifra(valor):
    """Una meta sin los ceros que sobran: 15 y no 15,00000; 3,0976 completo."""
    if valor is None:
        return "-"
    valor = valor.quantize(Decimal(1)) if valor == valor.to_integral_value() else valor.normalize()
    return number_format(valor, use_l10n=True, force_grouping=True)


class ProyectosDeLaMeta(TableSection):
    """El desplegable de cada meta en su listado, como el subformulario de Access."""
    verbose_name = "Proyectos programados"
    related_name = "programaciones_de_proyectos"
    fields = ("bpin", "proyecto", "vigencia", "meta_de_la_vigencia", "tipo_de_banco")

    def bpin(self, programacion):
        return programacion.proyecto.bpin or "-"
    bpin.short_description = "BPIN"

    def proyecto(self, programacion):
        return programacion.proyecto.nombre
    proyecto.short_description = "Proyecto"

    def meta_de_la_vigencia(self, programacion):
        return cifra(programacion.meta_vigencia)
    meta_de_la_vigencia.short_description = "Meta de la vigencia"

    def tipo_de_banco(self, programacion):
        return programacion.proyecto.tipo_banco or "-"
    tipo_de_banco.short_description = "Tipo de banco"


class CodigoMetaFilter(FieldTextFilter):
    """La MT a mano: "MT323", o parte del codigo ("MT32") para varias."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = "MT"


VIGENCIAS_DEL_CUATRIENIO = (2024, 2025, 2026, 2027)


def _columna_meta_del_anio(anio):
    """Columna del listado de metas con la meta de una vigencia (anotada en get_queryset)."""
    @display(description=f"Meta {anio}", ordering=f"valor_{anio}")
    def columna(self, obj):
        return cifra(getattr(obj, f"valor_{anio}", None))
    return columna


@admin.register(MetaIndicador)
class MetaIndicadorAdmin(ModelAdmin):
    form = MetaIndicadorForm
    compressed_fields = True
    list_fullwidth = True
    inlines = (VigenciaMetaInline,)
    list_sections = (ProyectosDeLaMeta,)
    list_display = ("codigo", "ficha_link", "programa_pdd", "producto", "indicador", "meta_del_cuatrienio",
                    "meta_2024", "meta_2025", "meta_2026", "meta_2027")
    # De menor a mayor (MT001, MT002...). Va aqui y no en el Meta del modelo para no
    # tocar la migracion 0011, que se genero con el orden de SUTEC
    ordering = ("codigo",)
    actions_detail = ("ficha_meta",)
    # En el orden de las dos jerarquias: el plan (linea, sector, programa, indicador PDD)
    # y la cadena MGA (sector, programa, producto, indicador)
    list_filter = (("codigo", CodigoMetaFilter),
                   ("programa_pdd__sector_pdd__linea_estrategica", RelatedDropdownFilter),
                   ("programa_pdd__sector_pdd", RelatedDropdownFilter),
                   ("programa_pdd", RelatedDropdownFilter),
                   ("indicadores_pdd", RelatedDropdownFilter),
                   ("indicador_mga__producto_mga__programa_mga__sector_mga", RelatedDropdownFilter),
                   ("indicador_mga__producto_mga__programa_mga", RelatedDropdownFilter),
                   ("indicador_mga__producto_mga", RelatedDropdownFilter),
                   ("indicador_mga", RelatedDropdownFilter),
                   ("dependencias_responsables", RelatedDropdownFilter), "estado")
    list_filter_submit = True
    search_fields = ("codigo", "descripcion", "indicador_mga__codigo", "indicador_mga__descripcion")
    list_select_related = ("indicador_mga__producto_mga", "programa_pdd", "programa_pdd__sector_pdd")
    autocomplete_fields = ("indicador_mga", "programa_pdd", "indicadores_pdd",
                           "dependencias_responsables")
    filter_horizontal = ("ods",)

    @display(description="Producto MGA", ordering="indicador_mga__producto_mga__codigo")
    def producto(self, obj):
        producto = obj.indicador_mga.producto_mga
        return corto(f"{producto.codigo} - {producto.descripcion}", 80) if producto else "-"

    @display(description="Indicador MGA", ordering="indicador_mga__codigo")
    def indicador(self, obj):
        return corto(f"{obj.indicador_mga.codigo} - {obj.indicador_mga.descripcion}", 80)

    @display(description="Meta cuatrienio", ordering="meta_cuatrenio")
    def meta_del_cuatrienio(self, obj):
        # 1.500 y no 1500,000: el campo lleva tres decimales y asi se leia como millon y medio
        return cifra(obj.meta_cuatrenio)

    # Las anota get_queryset
    meta_2024, meta_2025, meta_2026, meta_2027 = (_columna_meta_del_anio(a) for a in VIGENCIAS_DEL_CUATRIENIO)

    @display(description="")
    def ficha_link(self, obj):
        url = reverse("admin:siifweb_metaindicador_ficha", args=(obj.pk,))
        return format_html('<a href="{}" class="text-primary-600" title="Ficha de la meta">'
                           '<i class="material-symbols-outlined">folder_open</i></a>', url)

    @action(description="Ficha de la meta", url_path="ficha", icon="folder_open")
    def ficha_meta(self, request, object_id):
        """La meta contra lo que programan los proyectos, vigencia por vigencia.

        Como la ficha del proyecto: admin_view() solo exige ser staff, asi que el permiso
        de vista se revisa aqui.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        meta = (MetaIndicador.objects
                .select_related("programa_pdd__sector_pdd__linea_estrategica__plan_desarrollo",
                                "indicador_mga__producto_mga__programa_mga__sector_mga",
                                "indicador_mga__producto_mga__medido_a_traves_de",
                                "indicador_mga__unidad_medida")
                .prefetch_related("dependencias_responsables", "ods")
                .filter(pk=object_id).first())
        if meta is None:
            raise Http404("No hay meta con ese id.")

        # La linea jerarquica de la meta: el plan y la cadena MGA, con el codigo delante
        def nombre(objeto):
            if objeto is None:
                return ""
            texto = strip_tags(getattr(objeto, "descripcion", None) or getattr(objeto, "nombre", ""))
            return f"{objeto.codigo} - {texto}" if getattr(objeto, "codigo", None) else texto
        indicador = meta.indicador_mga
        producto = indicador.producto_mga
        programa_mga = producto.programa_mga if producto else None
        jerarquia = [
            ("Plan de desarrollo", nombre(meta.plan_desarrollo)),
            ("Línea estratégica", nombre(meta.linea_estrategica)),
            ("Sector PDD", nombre(meta.sector_pdd)),
            ("Programa PDD", nombre(meta.programa_pdd)),
            ("Sector MGA", nombre(programa_mga.sector_mga if programa_mga else None)),
            ("Programa MGA", nombre(programa_mga)),
            ("Producto MGA", nombre(producto)),
            ("Medido a través de", nombre(producto.medido_a_traves_de if producto else None)),
            ("Indicador MGA", nombre(indicador)),
            ("Unidad de medida", nombre(indicador.unidad_medida)),
        ]

        programaciones = list(
            meta.programaciones_de_proyectos
            .select_related("proyecto", "proyecto__tipo_banco")
            .prefetch_related(
                "proyecto__municipios", "proyecto__observaciones",
                # Todas las metas del proyecto, para el modal: de una vez y no una por fila
                Prefetch("proyecto__programaciones",
                         queryset=ProgramacionMeta.objects.select_related("meta")
                         .order_by(F("vigencia").asc(nulls_last=True), "meta__codigo")))
            .order_by(F("vigencia").asc(nulls_last=True), "proyecto__nombre"))

        # La ejecucion en SIIFWEB de los proyectos programados: por BPIN y vigencia. Es la
        # plata del proyecto completo, no la parte de esta meta (SIIFWEB no la separa).
        bpins = {p.proyecto.bpin for p in programaciones if p.proyecto.bpin}
        dinero, total_por_bpin = self._ejecucion_por_bpin(bpins)
        ficha_de = {b: reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(pk,))
                    for b, pk in Proyecto.objects.filter(bpin__in=bpins).values_list("bpin", "pk")}
        puede_anotar = request.user.has_perm("siifweb.add_observacionproyecto")
        puede_programar = request.user.has_perm("siifweb.add_programacionmeta")
        puede_editar = request.user.has_perm("siifweb.change_programacionproyectos")
        # El seguimiento de cada proyecto en esta meta, del mas reciente al mas viejo
        seguimientos = {}
        for x in meta.seguimientos.order_by("-vigencia", "-mes"):
            seguimientos.setdefault(x.proyecto_id, []).append(
                {"vigencia": x.vigencia, "mes": x.get_mes_display(), "valor": cifra(x.valor),
                 "observacion": x.observacion})
        abiertas = PeriodoReporte.vigencias_abiertas()

        detalle = [{
            "programacion": p,
            "meta": cifra(p.meta_vigencia),
            "siifweb": dinero.get((p.proyecto.bpin, p.vigencia)) if p.proyecto.bpin in ficha_de else None,
            "total": total_por_bpin.get(p.proyecto.bpin),
            "ficha_url": ficha_de.get(p.proyecto.bpin, ""),
            "observacion_url": (reverse("admin:siifweb_programacionproyectos_observacion",
                                        args=(p.proyecto_id,)) if puede_anotar else ""),
            "municipios": ", ".join(m.nombre for m in p.proyecto.municipios.all()) or "-",
            # Una por linea: el modal las separa
            "observaciones": "\n".join(
                f"{o.fecha:%Y-%m-%d}: {o.texto}" if o.fecha else o.texto
                for o in p.proyecto.observaciones.all()),
            # Meta, vigencia y programacion, separadas por tabulador; una por linea
            "metas": "\n".join(f"{q.meta.codigo}\t{q.vigencia or 'Sin vigencia'}\t{cifra(q.meta_vigencia)}"
                                for q in p.proyecto.programaciones.all()),
            "url": reverse("admin:siifweb_programacionproyectos_change", args=(p.proyecto_id,)),
            # Lo que llena el formulario de edicion del modal
            "editar_url": (reverse("admin:siifweb_programacionproyectos_editar_desde_ficha",
                                   args=(p.proyecto_id,)) if puede_editar else ""),
            "editar": json.dumps({
                "bpin": p.proyecto.bpin, "nombre": p.proyecto.nombre,
                "tipo_banco": p.proyecto.tipo_banco_id,
                "municipios": [m.pk for m in p.proyecto.municipios.all()],
                "programaciones": [{"id": q.pk, "meta": q.meta_id, "vigencia": q.vigencia,
                                    "valor": valor_editable(q.meta_vigencia)}
                                   for q in p.proyecto.programaciones.all()],
            }) if puede_editar else "",
            "seguimientos": json.dumps(seguimientos.get(p.proyecto_id, [])),
            # Las vigencias abiertas en las que el proyecto esta programado en esta meta
            "reportables": json.dumps([v for v in abiertas if v in {
                q.vigencia for q in p.proyecto.programaciones.all() if q.meta_id == meta.pk}]),
        } for p in programaciones]

        # Una fila por vigencia: las del plan y las que traigan los proyectos. Cada una
        # lleva sus proyectos, que se despliegan debajo
        plan = {v.vigencia: v.valor for v in meta.vigencias.all()}
        vigencias = sorted(set(plan) | {p.vigencia for p in programaciones if p.vigencia})
        filas = []
        for vigencia in vigencias + ([None] if any(p.vigencia is None for p in programaciones) else []):
            suyas = [p for p in programaciones if p.vigencia == vigencia]
            programado = sum((p.meta_vigencia for p in suyas if p.meta_vigencia is not None), Decimal(0))
            esperado = plan.get(vigencia)
            # Cada BPIN una vez por vigencia, aunque este programado dos veces en la meta
            suyos = {p.proyecto.bpin for p in suyas if p.proyecto.bpin in ficha_de}
            ejecucion = {c: sum((dinero.get((b, vigencia), {}).get(c, Decimal(0)) for b in suyos), Decimal(0))
                         for c in ("comprometido", "obligado", "pagado", "reservas")}
            filas.append({
                "ejecucion": ejecucion if suyos else None,
                "vigencia": vigencia or "Sin vigencia",
                "meta": cifra(esperado),
                "programado": cifra(programado) if suyas else "-",
                "proyectos": len({p.proyecto_id for p in suyas}),
                "sin_valor": sum(1 for p in suyas if p.meta_vigencia is None),
                "detalle": [d for d in detalle if d["programacion"].vigencia == vigencia],
            })

        total_programado = sum((p.meta_vigencia for p in programaciones if p.meta_vigencia is not None),
                               Decimal(0))
        tarjetas = [
            ("Meta del cuatrienio", cifra(meta.meta_cuatrenio)),
            ("Meta en las vigencias", cifra(sum(plan.values(), Decimal(0))) if plan else "-"),
            ("Programado por los proyectos", cifra(total_programado) if programaciones else "-"),
            ("Proyectos", len({p.proyecto_id for p in programaciones})),
        ]
        catalogos = {
            # Las vigencias del plan (2024-2027), no las del ano: una meta se programa para
            # el cuatrienio
            "vigencias": sorted(set(VigenciaMeta.objects.order_by().values_list("vigencia", flat=True)))
                         or [v for v, _ in listado_vigencias_metas()],
            "metas": [(m.pk, f"{m.codigo} - {m.indicador_mga.codigo}: {corto(m.indicador_mga.descripcion, 70)}")
                      for m in MetaIndicador.objects.select_related("indicador_mga").order_by("codigo")],
            "tipos_banco": TipoBanco.objects.all(),
            "municipios": Municipio.objects.all(),
        } if puede_programar or puede_editar else {}
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Ficha de la meta {meta.codigo}",
            "meta": meta,
            "jerarquia": jerarquia,
            "tarjetas": tarjetas,
            "filas": filas,
            "volver": reverse("admin:siifweb_metaindicador_change", args=(meta.pk,)),
            # El formulario completo de un proyecto nuevo, ya programado en esta meta, que vuelve
            # aqui. Es el enlace secundario del modal de programar
            "nuevo_proyecto": (reverse("admin:siifweb_programacionproyectos_add") + "?" + urlencode(
                {"meta": meta.pk, "volver": request.path})
                if request.user.has_perm("siifweb.add_programacionproyectos") else ""),
            # Las listas de los dos modales: programar y editar
            "catalogos": catalogos,
            # El modal de programar: solo para quien puede crear programaciones
            "programar": ({
                **catalogos,
                "url": reverse("admin:siifweb_metaindicador_programar", args=(meta.pk,)),
                "buscar": reverse("admin:siifweb_metaindicador_buscar_proyectos", args=(meta.pk,)),
                "puede_crear": request.user.has_perm("siifweb.add_programacionproyectos"),
                "puede_anotar": puede_anotar,
            } if puede_programar else None),
            # Editar desde el modal del proyecto; las programaciones, con los tres permisos
            "editar": ({**catalogos, "programaciones": puede_reprogramar(request.user)}
                       if puede_editar else None),
            # Reportar seguimiento desde el modal: solo con permiso y con alguna vigencia
            # abierta en los periodos de reporte
            "seguimiento": ({
                "url": reverse("admin:siifweb_metaindicador_seguimiento", args=(meta.pk,)),
                "vigencias": abiertas,
                "meses": MESES,
                "mes_actual": timezone.localdate().month,
            } if abiertas and request.user.has_perm("siifweb.add_seguimientometa") else None),
            # La vigencia que se acaba de programar llega desplegada, y el proyecto que se
            # acaba de editar, abierto
            "abrir": request.GET.get("abrir", ""),
            "ver": request.GET.get("ver", "") if request.GET.get("ver", "").isdigit() else "",
        }
        return TemplateResponse(request, "siifweb/ficha_meta.html", contexto)

    @staticmethod
    def _ejecucion_por_bpin(bpins):
        """({(bpin, vigencia): cifras}, {bpin: cifras de todas las vigencias}).

        Compromisos, obligaciones y pagos por la vigencia de su documento. Las reservas, por
        la vigencia a la que pasaron: los compromisos de la anterior que quedaron sin obligar.
        Una consulta agregada por tabla, cruzadas por la llave: nunca dos Sum sobre joins.
        """
        dinero = {}

        def sumar(consulta, campos):
            for fila in consulta:
                cifras = dinero.setdefault((fila["b"], fila["v"]), {
                    "comprometido": Decimal(0), "obligado": Decimal(0), "pagado": Decimal(0),
                    "reservas": Decimal(0)})
                for campo in campos:
                    cifras[campo] += fila[campo] or Decimal(0)

        if bpins:
            sumar(CompromisoImputacion.objects.filter(proyecto__bpin__in=bpins)
                  .values(b=F("proyecto__bpin"), v=F("compromiso__vigencia"))
                  .annotate(comprometido=Sum("valor_compromiso_def")), ("comprometido",))
            sumar(ObligacionImputacion.objects.filter(proyecto__bpin__in=bpins)
                  .values(b=F("proyecto__bpin"), v=F("obligacion__vigencia"))
                  .annotate(obligado=Sum("valor_obligacion"), pagado=Sum("pagos")),
                  ("obligado", "pagado"))
            sumar(ReservaImputacion.objects.filter(proyecto__bpin__in=bpins)
                  .values(b=F("proyecto__bpin"), v=F("reserva__vigencia"))
                  .annotate(reservas=Sum("valor_reserva_def")), ("reservas",))
        total = {}
        for (bpin, _), cifras in dinero.items():
            suma = total.setdefault(bpin, {c: Decimal(0) for c in cifras})
            for campo, valor in cifras.items():
                suma[campo] += valor
        return dinero, total

    def buscar_proyectos(self, request, object_id):
        """GET ?q=: proyectos programados por BPIN o nombre, para el modal de programar."""
        if not request.user.has_perm("siifweb.view_programacionproyectos"):
            raise PermissionDenied
        termino = (request.GET.get("q") or "").strip()
        if len(termino) < 3:
            return JsonResponse({"resultados": []})
        en_la_meta = set(ProgramacionMeta.objects.filter(meta_id=object_id)
                         .values_list("proyecto_id", flat=True))
        # El BPIN exacto primero; despues, por nombre
        proyectos = (ProgramacionProyectos.objects
                     .filter(Q(bpin__icontains=termino) | Q(nombre__icontains=termino))
                     .annotate(exacto=Case(When(bpin=termino, then=Value(0)), default=Value(1),
                                           output_field=IntegerField()))
                     .order_by("exacto", "nombre")[:15])
        return JsonResponse({"resultados": [
            {"id": p.pk, "bpin": p.bpin, "nombre": p.nombre, "vigencias": p.vigencias,
             "en_la_meta": p.pk in en_la_meta} for p in proyectos]})

    def programar_proyecto(self, request, object_id):
        """POST desde el modal: programa un proyecto existente o uno nuevo en una o varias metas.

        Las programaciones llegan como listas paralelas (meta, vigencia, meta_vigencia); la
        primera es la meta de la ficha. Un proyecto nuevo trae ademas BPIN, nombre, tipo de
        banco y municipios, y cualquiera puede llevar una observacion. Todo o nada: si una
        fila falla no se guarda ninguna, y el aviso dice cual. Lo que evita duplicados: un
        proyecto nuevo no repite un BPIN ni un nombre, y un proyecto no se programa dos
        veces en la misma meta y vigencia.
        """
        if request.method != "POST":
            return JsonResponse({"error": "Solo POST"}, status=405)
        if not request.user.has_perm("siifweb.add_programacionmeta"):
            raise PermissionDenied
        meta_ficha = MetaIndicador.objects.filter(pk=object_id).first()
        if meta_ficha is None:
            raise Http404("No hay meta con ese id.")

        def error(mensaje):
            return JsonResponse({"error": mensaje}, status=400)

        filas, falla = leer_programaciones(request.POST)
        if falla:
            return error(falla)
        filas = [(meta, vigencia, valor) for _, meta, vigencia, valor in filas]
        if not filas:
            return error("Agregue al menos una meta con su vigencia.")

        observacion = (request.POST.get("observacion") or "").strip()[:5000]
        if observacion and not request.user.has_perm("siifweb.add_observacionproyecto"):
            raise PermissionDenied

        with transaction.atomic():
            if request.POST.get("modo") == "existente":
                proyecto = ProgramacionProyectos.objects.filter(pk=request.POST.get("proyecto") or 0).first()
                if proyecto is None:
                    return error("Busque y elija el proyecto.")
            else:
                if not request.user.has_perm("siifweb.add_programacionproyectos"):
                    raise PermissionDenied
                datos, falla = leer_proyecto(request.POST)
                if falla:
                    return error(falla)
                repetido = proyecto_repetido(datos["bpin"], datos["nombre"])
                if repetido:
                    return error(f"Ya existe: {repetido}. Elíjalo en «Proyecto existente».")
                proyecto = ProgramacionProyectos.objects.create(
                    bpin=datos["bpin"], nombre=datos["nombre"], tipo_banco=datos["tipo_banco"])
                proyecto.municipios.set(datos["municipios"])

            ya = set(proyecto.programaciones.values_list("meta_id", "vigencia"))
            for meta, vigencia, _ in filas:
                if (meta.pk, vigencia) in ya:
                    transaction.set_rollback(True)
                    return error(f"El proyecto ya está programado en {meta.codigo} para {vigencia}.")
            ProgramacionMeta.objects.bulk_create(
                [ProgramacionMeta(proyecto=proyecto, meta=meta, vigencia=vigencia, meta_vigencia=valor)
                 for meta, vigencia, valor in filas])
            if observacion:
                ObservacionProyecto.objects.create(proyecto=proyecto, texto=observacion,
                                                   fecha=timezone.localdate())
            proyecto.actualizar_vigencias()

        # Se vuelve a la ficha con la vigencia de esta meta desplegada, si se programo en ella
        abrir = next((v for m, v, _ in filas if m.pk == meta_ficha.pk), None)
        volver = reverse("admin:siifweb_metaindicador_ficha", args=(meta_ficha.pk,))
        return JsonResponse({"proyecto": proyecto.pk, "programaciones": len(filas),
                             "volver": volver + (f"?abrir={abrir}" if abrir else "")}, status=201)

    def registrar_seguimiento(self, request, object_id):
        """POST desde el modal del proyecto: el seguimiento de la meta para una vigencia y mes.

        La meta es la de la ficha; el proyecto, el del modal. Las reglas (periodo de reporte
        abierto, proyecto programado en la meta, un reporte por mes) estan en el modelo y se
        aplican con full_clean.
        """
        if request.method != "POST":
            return JsonResponse({"error": "Solo POST"}, status=405)
        if not request.user.has_perm("siifweb.add_seguimientometa"):
            raise PermissionDenied
        meta = MetaIndicador.objects.filter(pk=object_id).first()
        proyecto = ProgramacionProyectos.objects.filter(pk=request.POST.get("proyecto") or 0).first()
        if meta is None or proyecto is None:
            raise Http404("No hay meta o proyecto con ese id.")

        def error(mensaje):
            return JsonResponse({"error": mensaje}, status=400)

        vigencia, mes = request.POST.get("vigencia", ""), request.POST.get("mes", "")
        if not vigencia.isdigit():
            return error("Elija la vigencia.")
        if not mes.isdigit() or not 1 <= int(mes) <= 12:
            return error("Elija el mes.")
        valor = (request.POST.get("valor") or "").strip().replace(",", ".")
        try:
            valor = Decimal(valor)
        except InvalidOperation:
            return error("El valor tiene que ser un número.")
        if valor.as_tuple().exponent < -5:
            return error("El valor admite hasta cinco decimales.")
        seguimiento = SeguimientoMeta(meta=meta, proyecto=proyecto, vigencia=int(vigencia), mes=int(mes),
                                      valor=valor, observacion=(request.POST.get("observacion") or "").strip()[:5000],
                                      reportado_por=request.user)
        try:
            seguimiento.full_clean()
        except ValidationError as e:
            return error(" ".join(m for mensajes in e.message_dict.values() for m in mensajes))
        seguimiento.save()
        return JsonResponse({"proyecto": proyecto.pk, "vigencia": seguimiento.vigencia}, status=201)

    def get_urls(self):
        # Antes de las del admin: '<path:object_id>/' la capturaria
        propia = [path("<path:object_id>/ficha/", self.admin_site.admin_view(self.ficha_meta),
                       name="siifweb_metaindicador_ficha"),
                  path("<path:object_id>/programar/", self.admin_site.admin_view(self.programar_proyecto),
                       name="siifweb_metaindicador_programar"),
                  path("<path:object_id>/buscar-proyectos/", self.admin_site.admin_view(self.buscar_proyectos),
                       name="siifweb_metaindicador_buscar_proyectos"),
                  path("<path:object_id>/seguimiento/", self.admin_site.admin_view(self.registrar_seguimiento),
                       name="siifweb_metaindicador_seguimiento")]
        return propia + super().get_urls()

    def get_queryset(self, request):
        # El desplegable se arma para las 100 metas de la pagina: los proyectos se traen de
        # una vez y no con una consulta por meta. Y la meta de cada vigencia del cuatrienio,
        # en la misma consulta y ordenable
        return super().get_queryset(request).prefetch_related(Prefetch(
            "programaciones_de_proyectos",
            queryset=ProgramacionMeta.objects.select_related("proyecto", "proyecto__tipo_banco")
            .order_by("vigencia", "proyecto__nombre"))).annotate(**{
                f"valor_{anio}": Subquery(VigenciaMeta.objects.filter(meta_indicador=OuterRef("pk"), vigencia=anio)
                                          .values("valor")[:1])
                for anio in VIGENCIAS_DEL_CUATRIENIO})


@admin.register(VigenciaMeta)
class VigenciaMetaAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_display = ("meta_indicador", "vigencia", "valor")
    list_filter = ("vigencia",)
    search_fields = ("meta_indicador__codigo", "meta_indicador__indicador_mga__codigo")
    list_select_related = ("meta_indicador", "meta_indicador__indicador_mga",
                           "meta_indicador__programa_pdd__sector_pdd")
    autocomplete_fields = ("meta_indicador",)


@admin.register(SectorMGA)
class SectorMGAAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "estado")
    list_filter = ("estado",)


@admin.register(ProgramaMGA)
class ProgramaMGAAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "sector_mga", "estado")
    list_filter = (("sector_mga", RelatedDropdownFilter), "estado")
    list_select_related = ("sector_mga",)


@admin.register(ProductoMGA)
class ProductoMGAAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "programa_mga", "medido_a_traves_de", "estado")
    list_filter = (("programa_mga", RelatedDropdownFilter), ("medido_a_traves_de", RelatedDropdownFilter),
                   "estado")
    search_fields = ("codigo", "descripcion", "descripcion_producto")
    list_select_related = ("programa_mga", "medido_a_traves_de")
    autocomplete_fields = ("programa_mga", "medido_a_traves_de")


@admin.register(IndicadorMGA)
class IndicadorMGAAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "producto_mga", "unidad_medida", "es_nacional", "es_territorial",
                    "estado")
    list_filter = (("ods", RelatedDropdownFilter), ("unidad_medida", RelatedDropdownFilter),
                   "es_nacional", "es_territorial", "estado")
    list_select_related = ("producto_mga", "unidad_medida")
    autocomplete_fields = ("producto_mga", "unidad_medida")
    filter_horizontal = ("ods",)


class CatalogoDeMedidas(ModelAdmin):
    """Medido a traves de y Unidad de medida: un nombre y cuantos lo usan."""
    compressed_fields = True
    list_display = ("nombre", "n_usos")
    search_fields = ("nombre",)
    relacion = ""

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count(self.relacion, distinct=True))

    @display(description="Usos", ordering="n")
    def n_usos(self, obj):
        return obj.n


@admin.register(MedidoATravesDe)
class MedidoATravesDeAdmin(CatalogoDeMedidas):
    relacion = "productos"


@admin.register(UnidadMedida)
class UnidadMedidaAdmin(CatalogoDeMedidas):
    relacion = "indicadores"


@admin.register(ODS)
class ODSAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("descripcion", "estado")
    search_fields = ("descripcion",)


@admin.register(MetaODS)
class MetaODSAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_display = ("nombre", "ods", "n_productos", "estado")
    list_filter = (("ods", RelatedDropdownFilter), "estado")
    list_filter_submit = True
    search_fields = ("descripcion",)
    list_select_related = ("ods",)
    autocomplete_fields = ("productos_mga",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("productos_mga", distinct=True))

    @display(description="Nombre", ordering="descripcion")
    def nombre(self, obj):
        return corto(obj.descripcion)

    @display(description="Productos MGA", ordering="n")
    def n_productos(self, obj):
        return obj.n


# ---------------------------------------------------------------------------
# Programacion de proyectos en las metas (traida del Access "Seguimiento PDD STO")
# ---------------------------------------------------------------------------

@admin.register(TipoBanco)
class TipoBancoAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre", "n_proyectos")
    search_fields = ("nombre",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("proyectos", distinct=True))

    @display(description="Proyectos", ordering="n")
    def n_proyectos(self, obj):
        return obj.n


@admin.register(Municipio)
class MunicipioAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre", "departamento", "n_proyectos")
    list_filter = (("departamento", RelatedDropdownFilter),)
    list_select_related = ("departamento",)
    search_fields = ("nombre",)
    autocomplete_fields = ("departamento",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("proyectos", distinct=True))

    @display(description="Proyectos", ordering="n")
    def n_proyectos(self, obj):
        return obj.n


class ProgramacionMetaInline(TabularInline):
    model = ProgramacionMeta
    extra = 0

    def get_extra(self, request, obj=None, **kwargs):
        # Desde "Nuevo proyecto" en la ficha de la meta: una fila, ya con la meta puesta
        return 1 if obj is None and str(request.GET.get("meta", "")).isdigit() else 0
    fields = ("meta", "vigencia", "meta_vigencia")
    autocomplete_fields = ("meta",)
    tab = True
    hide_title = True
    verbose_name_plural = "Programacion en metas"


class ObservacionProyectoInline(TabularInline):
    model = ObservacionProyecto
    extra = 0
    fields = ("fecha", "texto")
    tab = True
    verbose_name_plural = "Observaciones"


class SeguimientoMetaInline(TabularInline):
    model = SeguimientoMeta
    extra = 0
    fields = ("meta", "vigencia", "mes", "valor", "observacion")
    autocomplete_fields = ("meta",)
    tab = True
    verbose_name_plural = "Seguimiento"


@admin.register(ProgramacionProyectos)
class ProgramacionProyectosAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    inlines = (ProgramacionMetaInline, ObservacionProyectoInline, SeguimientoMetaInline)
    list_display = ("bpin", "nombre_corto", "tipo_banco", "vigencias", "n_metas")
    list_filter = (("tipo_banco", RelatedDropdownFilter), ("municipios", RelatedDropdownFilter),
                   ("programaciones__vigencia", ChoicesDropdownFilter),
                   ("programaciones__meta__dependencias_responsables", RelatedDropdownFilter))
    list_filter_submit = True
    search_fields = ("bpin", "nombre", "programaciones__meta__codigo")
    list_select_related = ("tipo_banco",)
    autocomplete_fields = ("tipo_banco",)
    filter_horizontal = ("municipios",)
    # Se calculan de las programaciones: editarlas a mano las descuadraria
    readonly_fields = ("vigencias",)
    fields = ("bpin", "nombre", "tipo_banco", "municipios", "vigencias")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("programaciones__meta", distinct=True))

    def get_search_results(self, request, queryset, search_term):
        # Buscar por el codigo de la meta cruza con las programaciones y repetiria filas
        resultado, _ = super().get_search_results(request, queryset, search_term)
        return resultado.distinct(), False

    @display(description="Nombre del proyecto", ordering="nombre")
    def nombre_corto(self, obj):
        return corto(obj.nombre, 100)

    @display(description="Metas", ordering="n")
    def n_metas(self, obj):
        return obj.n

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.actualizar_vigencias()

    def save_formset(self, request, form, formset, change):
        # Quien reporta un seguimiento nuevo desde el detalle del proyecto
        if formset.model is SeguimientoMeta:
            for objeto in formset.save(commit=False):
                if objeto.pk is None:
                    objeto.reportado_por = request.user
                objeto.save()
            for objeto in formset.deleted_objects:
                objeto.delete()
            formset.save_m2m()
            return
        super().save_formset(request, form, formset, change)

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
        meta = str(request.GET.get("meta", ""))
        if (obj is None or obj.pk is None) and isinstance(inline, ProgramacionMetaInline) \
                and meta.isdigit() and MetaIndicador.objects.filter(pk=meta).exists():
            kwargs["initial"] = [{"meta": int(meta)}]
        return kwargs

    def response_add(self, request, obj, post_url_continue=None):
        # Guardado desde la ficha de la meta: se vuelve a ella, salvo que se pida seguir
        # editando o agregar otro
        volver = request.GET.get("volver", "")
        if (volver and "_continue" not in request.POST and "_addanother" not in request.POST
                and url_has_allowed_host_and_scheme(volver, allowed_hosts={request.get_host()},
                                                    require_https=request.is_secure())):
            self.message_user(request, f"Proyecto \"{obj}\" agregado.", messages.SUCCESS)
            return HttpResponseRedirect(volver)
        return super().response_add(request, obj, post_url_continue)

    def agregar_observacion(self, request, object_id):
        """POST desde el modal de la ficha de la meta: una observacion con la fecha del dia.

        admin_view() ya exige staff y token CSRF; el permiso de crear observaciones se
        revisa aqui, como en las demas vistas propias.
        """
        if request.method != "POST":
            return JsonResponse({"error": "Solo POST"}, status=405)
        if not request.user.has_perm("siifweb.add_observacionproyecto"):
            raise PermissionDenied
        proyecto = ProgramacionProyectos.objects.filter(pk=object_id).first()
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")
        texto = (request.POST.get("texto") or "").strip()
        if not texto:
            return JsonResponse({"error": "Escriba la observacion."}, status=400)
        nota = ObservacionProyecto.objects.create(proyecto=proyecto, texto=texto[:5000],
                                                  fecha=timezone.localdate())
        return JsonResponse({"fecha": f"{nota.fecha:%Y-%m-%d}", "texto": nota.texto}, status=201)

    def editar_desde_ficha(self, request, object_id):
        """POST desde el modal de la ficha de la meta: los datos del proyecto y, con permiso,
        sus programaciones.

        Las programaciones llegan completas: la que no viene se borra. Todo o nada, con las
        reglas del modal de programar. El BPIN y el nombre solo se comparan con los demas
        proyectos si cambian, para no trabar la edicion de un dato viejo del Access.
        """
        if request.method != "POST":
            return JsonResponse({"error": "Solo POST"}, status=405)
        if not self.has_change_permission(request):
            raise PermissionDenied
        proyecto = ProgramacionProyectos.objects.filter(pk=object_id).first()
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")

        def error(mensaje):
            return JsonResponse({"error": mensaje}, status=400)

        datos, falla = leer_proyecto(request.POST)
        if falla:
            return error(falla)
        repetido = proyecto_repetido(
            datos["bpin"] if datos["bpin"] != proyecto.bpin else "",
            datos["nombre"] if cargas_llave(datos["nombre"]) != cargas_llave(proyecto.nombre) else "",
            excluir=proyecto.pk)
        if repetido:
            return error(f"Ya existe otro proyecto con ese BPIN o nombre: {repetido}.")

        con_programaciones = request.POST.get("programaciones") == "1"
        if con_programaciones:
            if not puede_reprogramar(request.user):
                raise PermissionDenied
            filas, falla = leer_programaciones(request.POST, sin_vigencia=True)
            if falla:
                return error(falla)
            if not filas:
                return error("El proyecto tiene que quedar programado en al menos una meta.")
            propias = {p.pk: p for p in proyecto.programaciones.all()}
            if any(i is not None and i not in propias for i, *_ in filas):
                return error("Una de las programaciones no es de este proyecto. Recargue la ficha.")

        with transaction.atomic():
            proyecto.bpin, proyecto.nombre, proyecto.tipo_banco = (datos["bpin"], datos["nombre"],
                                                                    datos["tipo_banco"])
            proyecto.save()
            proyecto.municipios.set(datos["municipios"])
            if con_programaciones:
                quedan = {i for i, *_ in filas if i is not None}
                ProgramacionMeta.objects.filter(pk__in=set(propias) - quedan).delete()
                for i, meta, vigencia, valor in filas:
                    if i is None:
                        ProgramacionMeta.objects.create(proyecto=proyecto, meta=meta, vigencia=vigencia,
                                                        meta_vigencia=valor)
                        continue
                    p = propias[i]
                    if (p.meta_id, p.vigencia, p.meta_vigencia) != (meta.pk, vigencia, valor):
                        p.meta, p.vigencia, p.meta_vigencia = meta, vigencia, valor
                        p.save()
                proyecto.actualizar_vigencias()
        return JsonResponse({"proyecto": proyecto.pk})

    def get_urls(self):
        propia = [path("<path:object_id>/observacion/", self.admin_site.admin_view(self.agregar_observacion),
                       name="siifweb_programacionproyectos_observacion"),
                  path("<path:object_id>/editar-desde-ficha/", self.admin_site.admin_view(self.editar_desde_ficha),
                       name="siifweb_programacionproyectos_editar_desde_ficha")]
        return propia + super().get_urls()


@admin.register(PeriodoReporte)
class PeriodoReporteAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("vigencia", "fecha_inicio", "fecha_fin", "abierto_hoy")

    @display(description="Abierto hoy", boolean=True)
    def abierto_hoy(self, obj):
        return obj.esta_abierto()


@admin.register(MedidaTiempo)
class MedidaTiempoAdmin(ModelAdmin):
    """Dias, meses, anios: la medida del tiempo de ejecucion del proyecto."""
    compressed_fields = True
    list_display = ("nombre",)
    search_fields = ("nombre",)


@admin.register(ObservacionProyectoSiifweb)
class ObservacionProyectoSiifwebAdmin(ModelAdmin):
    """Todas las observaciones. Se escriben en la pantalla Observaciones de cada proyecto."""
    compressed_fields = True
    list_fullwidth = True
    list_display = ("proyecto_bpin", "texto_corto", "usuario", "fecha_creacion", "fecha_actualizacion")
    search_fields = ("proyecto__bpin", "proyecto__nombre", "texto")
    list_select_related = ("proyecto", "usuario")
    autocomplete_fields = ("proyecto",)
    fields = ("proyecto", "texto", "usuario", "fecha_creacion", "fecha_actualizacion")
    readonly_fields = ("usuario", "fecha_creacion", "fecha_actualizacion")

    def save_model(self, request, obj, form, change):
        # El usuario es quien la agrega; editarla no lo cambia
        if not change:
            obj.usuario = request.user
        super().save_model(request, obj, form, change)

    # Pasados 5 dias no se modifica ni se borra (ObservacionProyectoSiifweb.editable), y solo quien
    # la escribio la modifica o la borra (a los demas se les abre de solo lectura)
    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or (obj.editable and obj.es_de(request.user)))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or (obj.editable and obj.es_de(request.user)))

    def get_actions(self, request):
        # El borrado masivo no revisa cada observacion: se quita
        acciones = super().get_actions(request)
        acciones.pop("delete_selected", None)
        return acciones

    @display(description="Proyecto", ordering="proyecto__bpin")
    def proyecto_bpin(self, obj):
        return corto(str(obj.proyecto), 70)

    @display(description="Observación")
    def texto_corto(self, obj):
        return corto(obj.texto, 120)


@admin.register(ProgramacionFisica)
class ProgramacionFisicaAdmin(ModelAdmin):
    """Todos los valores fisicos programados. Se diligencian en la pestana Fisica de la pantalla
    de programacion de cada proyecto; aqui se revisan."""
    compressed_fields = True
    list_fullwidth = True
    list_display = ("proyecto_bpin", "vigencia", "meta", "valor_texto", "fecha_actualizacion")
    list_filter = (("vigencia", ChoicesDropdownFilter),)
    list_filter_submit = True
    search_fields = ("proyecto__bpin", "proyecto__nombre", "meta__codigo")
    list_select_related = ("proyecto", "meta")
    autocomplete_fields = ("proyecto", "meta")
    fields = ("proyecto", "vigencia", "meta", "valor")

    @display(description="Proyecto", ordering="proyecto__bpin")
    def proyecto_bpin(self, obj):
        return corto(str(obj.proyecto), 90)

    @display(description="Valor", ordering="valor")
    def valor_texto(self, obj):
        return cifra(obj.valor)


@admin.register(EntidadAportante)
class EntidadAportanteAdmin(ModelAdmin):
    """Quien pone los recursos de los proyectos. La programacion financiera va por entidad; la usa
    tambien la app regalias."""
    compressed_fields = True
    list_display = ("nombre", "nit")
    search_fields = ("nombre", "nit")
    fields = ("nombre", "nit")


@admin.register(ProgramacionFinanciera)
class ProgramacionFinancieraAdmin(ModelAdmin):
    """Todos los valores programados. Se diligencian en la pantalla de cada proyecto; aqui se
    revisan. Al guardar o borrar, el proyecto recalcula su valor programado (senales del modelo)."""
    compressed_fields = True
    list_fullwidth = True
    list_display = ("proyecto_bpin", "vigencia", "entidad_aportante", "fuente", "meta", "valor_texto",
                    "fecha_actualizacion")
    list_filter = (("vigencia", ChoicesDropdownFilter), ("entidad_aportante", RelatedDropdownFilter),
                   ("fuente", RelatedDropdownFilter))
    list_filter_submit = True
    search_fields = ("proyecto__bpin", "proyecto__nombre", "meta__codigo", "fuente__codigo", "fuente__nombre",
                     "entidad_aportante__nombre")
    list_select_related = ("proyecto", "entidad_aportante", "fuente", "meta")
    autocomplete_fields = ("proyecto", "entidad_aportante", "fuente", "meta")
    fields = ("proyecto", "vigencia", "entidad_aportante", "fuente", "meta", "valor")

    @display(description="Proyecto", ordering="proyecto__bpin")
    def proyecto_bpin(self, obj):
        return corto(str(obj.proyecto), 90)

    @display(description="Valor", ordering="valor")
    def valor_texto(self, obj):
        return pesos(obj.valor)


@admin.register(SeguimientoMeta)
class SeguimientoMetaAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_display = ("meta", "proyecto_corto", "vigencia", "mes", "valor_reportado", "reportado_por",
                    "fecha_creacion")
    list_filter = (("vigencia", ChoicesDropdownFilter), ("mes", ChoicesDropdownFilter),
                   ("meta__dependencias_responsables", RelatedDropdownFilter))
    list_filter_submit = True
    search_fields = ("meta__codigo", "proyecto__bpin", "proyecto__nombre")
    list_select_related = ("meta", "proyecto", "reportado_por")
    autocomplete_fields = ("meta", "proyecto")
    readonly_fields = ("reportado_por",)
    fields = ("meta", "proyecto", "vigencia", "mes", "valor", "observacion", "reportado_por")

    @display(description="Proyecto", ordering="proyecto__nombre")
    def proyecto_corto(self, obj):
        return corto(str(obj.proyecto), 90)

    @display(description="Valor", ordering="valor")
    def valor_reportado(self, obj):
        return cifra(obj.valor)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.reportado_por = request.user
        super().save_model(request, obj, form, change)



# ---------------------------------------------------------------------------
# Catalogo PIIP (producto e indicador, vinculado al plan) y formulacion de los proyectos
# ---------------------------------------------------------------------------

@admin.register(Departamento)
class DepartamentoAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre", "region", "n_municipios")
    search_fields = ("nombre", "region")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("municipios", distinct=True))

    @display(description="Municipios", ordering="n")
    def n_municipios(self, obj):
        return obj.n


def linea_del_plan(indicador_pdd):
    """Sector > programa > producto > indicador del plan, cada uno con su codigo."""
    if indicador_pdd is None:
        return []
    producto = indicador_pdd.producto_mga
    programa = producto.programa_mga if producto else None
    sector = programa.sector_mga if programa else None
    return [(etiqueta, obj) for etiqueta, obj in (("Sector", sector), ("Programa", programa),
                                                  ("Producto", producto), ("Indicador", indicador_pdd))
            if obj is not None]


@admin.register(ProductoCatalogo)
class ProductoCatalogoAdmin(ModelAdmin):
    """Los productos con que se formularon los proyectos. De cada uno cuelga su objetivo
    especifico; el programa y el sector salen del indicador del plan."""
    compressed_fields = True
    list_fullwidth = True
    list_filter_submit = True
    list_display = ("codigo", "nombre_corto", "medido_a_traves_de", "n_indicadores")
    search_fields = ("codigo", "nombre")
    list_select_related = ("medido_a_traves_de",)
    autocomplete_fields = ("medido_a_traves_de",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("indicadores", distinct=True))

    @display(description="Nombre", ordering="nombre")
    def nombre_corto(self, obj):
        return corto(obj.nombre)

    @display(description="Indicadores", ordering="n")
    def n_indicadores(self, obj):
        return obj.n


class UsadoEnProyectos(admin.SimpleListFilter):
    title = "uso en proyectos"
    parameter_name = "en_proyectos"

    def lookups(self, request, model_admin):
        return (("si", "Lo usa algún proyecto"), ("no", "Ningún proyecto"))

    def queryset(self, request, queryset):
        if self.value() == "si":
            return queryset.filter(en_proyectos__isnull=False).distinct()
        if self.value() == "no":
            return queryset.filter(en_proyectos__isnull=True)
        return queryset


class Homologado(admin.SimpleListFilter):
    title = "homologación con el plan"
    parameter_name = "homologado"

    def lookups(self, request, model_admin):
        return (("si", "Homologado"), ("no", "Sin homologar"))

    def queryset(self, request, queryset):
        if self.value() == "si":
            return queryset.filter(indicador_pdd__isnull=False)
        if self.value() == "no":
            return queryset.filter(indicador_pdd__isnull=True)
        return queryset


@admin.register(IndicadorCatalogo)
class IndicadorCatalogoAdmin(ModelAdmin):
    """Los indicadores con que se formularon los proyectos y su indicador del plan.

    Con "Sin homologar" quedan los que el equipo debe vincular a mano. Al guardar sin
    indicador del plan, si su codigo esta en el plan se homologa por codigo.
    """
    compressed_fields = True
    list_fullwidth = True
    list_filter_submit = True
    search_fields = ("codigo", "nombre", "indicador_pdd__codigo", "indicador_pdd__descripcion")
    list_display = ("codigo", "nombre_corto", "producto", "homologado", "del_plan", "homologado_por_codigo",
                    "n_proyectos")
    list_filter = (Homologado, UsadoEnProyectos, "homologado_por_codigo")
    list_select_related = ("producto", "indicador_pdd")
    autocomplete_fields = ("producto", "unidad_medida", "indicador_pdd")
    fieldsets = (
        ("Indicador del PIIP", {"fields": ("producto", "codigo", "nombre", "unidad_medida")}),
        ("Homologación con el plan de desarrollo", {
            "fields": ("indicador_pdd", "observacion", "homologado_por_codigo", "linea_plan")}),
    )
    readonly_fields = ("homologado_por_codigo", "linea_plan")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("en_proyectos", distinct=True))

    def save_model(self, request, obj, form, change):
        # Elegido a mano: deja de ser por codigo
        if "indicador_pdd" in form.changed_data:
            obj.homologado_por_codigo = False
        super().save_model(request, obj, form, change)
        if IndicadorCatalogo.homologar_por_codigo([obj]):
            messages.info(request, "Se homologó por código con el indicador del plan que tiene su mismo código.")

    @display(description="Nombre", ordering="nombre")
    def nombre_corto(self, obj):
        return corto(obj.nombre)

    @display(description="Homologado", boolean=True, ordering="indicador_pdd")
    def homologado(self, obj):
        return obj.indicador_pdd_id is not None

    @display(description="Indicador del plan", ordering="indicador_pdd__codigo")
    def del_plan(self, obj):
        return corto(str(obj.indicador_pdd)) if obj.indicador_pdd_id else "—"

    @display(description="Proyectos", ordering="n")
    def n_proyectos(self, obj):
        return obj.n

    @display(description="Línea del plan")
    def linea_plan(self, obj):
        linea = linea_del_plan(obj.indicador_pdd)
        if not linea:
            return "Sin homologar"
        return format_html_join(mark_safe("<br>"), "{}: {}", ((e, corto(str(o), 120)) for e, o in linea))


class IndicadorProyectoInline(ImputacionInline):
    model = IndicadorProyecto
    fields = ("indicador", "producto_del_indicador", "indicador_del_plan", "objetivo_especifico",
              "etapa", "unidad_medida", "tipo", "acumula", "meta_total", "metas_por_vigencia")
    readonly_fields = fields
    show_change_link = False
    verbose_name_plural = "Indicadores"

    @display(description="Producto")
    def producto_del_indicador(self, obj):
        return obj.indicador.producto

    @display(description="Indicador del plan")
    def indicador_del_plan(self, obj):
        return obj.indicador.indicador_pdd or "Sin homologar"

    @display(description="Metas por vigencia")
    def metas_por_vigencia(self, obj):
        return ", ".join(f"{m.vigencia}: {number_format(m.meta.normalize(), force_grouping=True)}"
                         for m in obj.metas.all()) or "—"

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .select_related("indicador__producto", "indicador__indicador_pdd").prefetch_related("metas"))


def en_siifweb():
    """El BPIN tiene algun documento en SIIFWEB: CDP, RP, obligacion, reserva o contrato."""
    expresion = None
    for modelo in (CdpImputacion, CompromisoImputacion, ObligacionImputacion, ReservaImputacion,
                   ContratoImputacion):
        existe = Exists(modelo.objects.filter(proyecto_id=OuterRef("proyecto_id")))
        expresion = existe if expresion is None else expresion | existe
    return expresion


class EnSiifweb(admin.SimpleListFilter):
    title = "en SIIFWEB"
    parameter_name = "en_siifweb"

    def lookups(self, request, model_admin):
        return (("si", "Está en SIIFWEB"), ("no", "Solo en PIIP"))

    def queryset(self, request, queryset):
        if self.value() in ("si", "no"):
            return queryset.filter(en_siifweb=self.value() == "si")
        return queryset


@admin.register(FormulacionProyecto)
class FormulacionProyectoAdmin(SoloLectura):
    """Lo que cada proyecto formulo en PIIP. Se llena con la carga "Informacion general PIIP".

    Entran todos los BPIN del PIIP; el semaforo dice cuales tienen documentos en SIIFWEB.
    """
    list_display = ("bpin", "nombre_proyecto", "bpin_siifweb", "programa", "vigencia_inicio", "vigencia_fin",
                    "n_indicadores")
    list_filter = (EnSiifweb, ("indicadores__indicador", RelatedDropdownFilter), "sector",
                   "vigencia_inicio", "vigencia_fin")
    list_filter_submit = True
    search_fields = ("bpin", "nombre", "programa", "indicadores__indicador__codigo")
    inlines = (IndicadorProyectoInline,)
    fieldsets = (
        (None, {"fields": ("bpin", "nombre", "proyecto", "sector", "programa", "vigencia_inicio", "vigencia_fin",
                           "municipios", "poblacion_afectada", "poblacion_objetivo")}),
        ("Formulación", {"fields": ("objetivo_general", "problema", "descripcion")}),
        ("Origen", {"fields": ("archivo_ficha", "reporte")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("indicadores", distinct=True),
                                                      en_siifweb=en_siifweb())

    def get_search_results(self, request, queryset, search_term):
        # Buscar por codigo de indicador cruza una relacion de muchos: sin distinct repite filas
        resultados, _ = super().get_search_results(request, queryset, search_term)
        return resultados.distinct(), False

    @display(description="Proyecto", ordering="nombre")
    def nombre_proyecto(self, obj):
        return corto(obj.nombre)

    @display(description="BPIN en SIIFWEB", ordering="en_siifweb", label={"si": "success", "no": "danger"})
    def bpin_siifweb(self, obj):
        return ("si", obj.bpin) if obj.en_siifweb else ("no", "No está")

    @display(description="Indicadores", ordering="n")
    def n_indicadores(self, obj):
        return obj.n
