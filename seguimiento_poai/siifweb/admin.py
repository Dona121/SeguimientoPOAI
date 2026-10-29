# -*- coding: utf-8 -*-
import hashlib
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import (Case, Count, DateField, DecimalField, F, IntegerField, OuterRef,
                              Prefetch, Q, Subquery, Sum, Value, When)
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import number_format
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (ChoicesDropdownFilter, RangeDateFilter,
                                          RelatedDropdownFilter,TextFilter,FieldTextFilter,AutocompleteSelectMultipleFilter)
from unfold.decorators import action, display
from unfold.sections import TableSection

from . import cargas, tablero
from .models import (BpinProceso, CargaReporte, Cdp, CdpImputacion, CentroCosto, Clasificacion,
                     Compromiso, CompromisoImputacion, Contrato, ContratoActa, ContratoImputacion,
                     ContratoSecop, DependenciaResponsable, Fuente, Obligacion, ObligacionImputacion,
                     OrdenGasto, ProcesoSecop, Proyecto, Reserva, ReservaImputacion, Rubro, Tercero)
from .models import (IndicadorMGA, IndicadorPDD, LineaEstrategica, MetaIndicador, MetaODS, ODS,
                     PlanDesarrollo, ProductoMGA, ProgramaMGA, ProgramaPDD, SectorMGA, SectorPDD,
                     VigenciaMeta, indicadores_fuera_del_programa)
from .models import (Municipio, ObservacionProyecto, ProgramacionMeta, ProgramacionProyectos,
                     TipoBanco, listado_vigencias_metas)
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
            previa = CargaReporte.objects.filter(hash=digest).exclude(pk=self.instance.pk).first()
            if previa:
                raise forms.ValidationError(
                    f"Este archivo ya fue cargado el {previa.fecha_creacion:%Y-%m-%d} "
                    f"como '{previa}'. No se vuelve a procesar.")
            self.instance.hash = digest
        tipo = datos.get("tipo_reporte")
        sin_vigencia = (CargaReporte.TipoReporte.HISTORIAL, CargaReporte.TipoReporte.POAI,
                        CargaReporte.TipoReporte.SECOP)
        if tipo and tipo not in sin_vigencia and not datos.get("vigencia"):
            raise forms.ValidationError("La vigencia es obligatoria salvo en el historial de contratos "
                                        "y SECOP II, que cubren varias vigencias.")
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
    actions_detail = ("ficha_ejecucion",)
    list_filter_submit = True
    ordering = ("bpin",)
    fieldsets = (
        ("Proyecto", {"fields": ("bpin", "nombre"),
                      "description": "Aqui solo se editan los datos del proyecto. La cadena de "
                                     "gasto, los contratos y el calendario de pagos se revisan "
                                     "en la ficha de ejecucion, con el boton de arriba."}),
        ("Responsables y clasificacion", {
            "fields": ("dependencia", "dependencia_responsable", "clasificaciones"),
            "description": "La dependencia de SIIFWEB es la que ejecuta el gasto; la responsable "
                           "es la del POAI, la asigna el equipo y en algunos casos difiere."}),
        ("Origen", {"fields": ("origen",),
                    "description": "Si registras aqui un proyecto nuevo, la proxima carga "
                                   "buscara su BPIN y le enganchara la ejecucion. Lo que "
                                   "escribas en nombre y responsable no se sobreescribe."}),
    )

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

        panel = "secop" if request.GET.get("panel") == "secop" else "siifweb"
        comun = {
            **self.admin_site.each_context(request),
            "title": f"Ficha de ejecucion - {proyecto.bpin}",
            "proyecto": proyecto,
            "panel": panel,
            "paneles": (("siifweb", "SIIFWEB"), ("secop", "SECOP II")),
            "volver": reverse("admin:siifweb_proyecto_change", args=(object_id,)),
        }
        if panel == "secop":
            return TemplateResponse(request, "siifweb/ficha_proyecto.html",
                                    {**comun, **self._ficha_secop(proyecto)})

        # Filtro de fechas: recorta las tablas de CDPs, RPs y obligaciones, en la
        # pantalla y en el PDF de cada una (?descargar=pdf&tabla=...), que sale de
        # las mismas consultas
        from . import pdf_ficha
        desde = fecha_del_get(request, "desde")
        hasta = fecha_del_get(request, "hasta")
        documentos = self._documentos_filtrados(proyecto, desde, hasta)
        if request.GET.get("descargar") == "pdf":
            tabla = request.GET.get("tabla")
            if tabla not in pdf_ficha.TABLAS:
                raise Http404("Tabla desconocida para el PDF.")
            respuesta = HttpResponse(pdf_ficha.generar(proyecto, desde, hasta, documentos, tabla),
                                     content_type="application/pdf")
            respuesta["Content-Disposition"] = (
                f'attachment; filename="{tabla}_{proyecto.bpin}_{timezone.localdate():%Y%m%d}.pdf"')
            return respuesta

        # El enlace de descarga de cada tabla lleva el filtro que esta aplicado
        filtro = {k: v for k, v in (("desde", desde), ("hasta", hasta)) if v}
        enlaces_pdf = {tabla: "?" + urlencode({"panel": "siifweb", **filtro,
                                               "tabla": tabla, "descargar": "pdf"})
                       for tabla in pdf_ficha.TABLAS}

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
        contratos = (Contrato.objects
                     .filter(imputaciones_del_contrato__proyecto=proyecto).distinct()
                     .select_related("tercero", "dependencia")
                     .annotate(n_actas=Count("actas_del_contrato", distinct=True),
                               pagado=suma_de(ContratoActa, "valor_pago", "contrato"))
                    .order_by("-valor_contrato"))

        # El calendario sale de las actas del contrato: fecha y valor de cada pago,
        # con el contratista. La bitacora quedo fuera del alcance (proceso financiero).
        # Los contratos se resuelven en una subconsulta: filtrar las actas por
        # contrato__imputaciones_del_contrato__proyecto duplicaria cada acta por el
        # numero de imputaciones que el contrato tiene en el proyecto.
        contratos_del_proyecto = ContratoImputacion.objects.filter(
            proyecto=proyecto).values("contrato_id")
        pagos = (ContratoActa.objects
                 .filter(contrato_id__in=contratos_del_proyecto)
                 .values("fecha_pago", "nrodoc_acta", "tipo_orden", "valor_pago",
                         tercero=F("contrato__tercero__nombre"),
                         contrato_nro=F("contrato__nro_contrato"))
                 .annotate(t=Sum("valor_pago")).order_by("fecha_pago"))
        max_pago = max((p["t"] for p in pagos), default=0)
        calendario = [{**p, "ancho": float(p["t"]) / float(max_pago) * 100 if max_pago else 0}
                      for p in pagos]
        
        fuentes_por_proyecto = (
            Fuente.objects
            .filter(compromisos_imputados__proyecto=proyecto)
            .annotate(valor_comprometido=Sum("compromisos_imputados__valor_compromiso_def"))
        )

        fuentes_por_proyecto_total = (
            Fuente.objects
            .filter(compromisos_imputados__proyecto=proyecto)
            .aggregate(tcomprometido=Sum("compromisos_imputados__valor_compromiso_def"))["tcomprometido"] or 0
        )

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
            "enlaces_pdf": enlaces_pdf,
            "fuentes_por_proyecto":fuentes_por_proyecto,
            "fuentes_por_proyecto_total":fuentes_por_proyecto_total,
            "contratos": contratos,
            "calendario": calendario,
            "total_pagado_bitacora": sum(p["t"] for p in pagos),
            "reservas": ReservaImputacion.objects.filter(proyecto=proyecto)
                        .select_related("reserva", "cdp_origen", "rubro"),
        }
        return TemplateResponse(request, "siifweb/ficha_proyecto.html", contexto)

    def _documentos_filtrados(self, proyecto, desde, hasta):
        """CDPs, RPs y obligaciones del proyecto, recortados por el filtro de fechas.

        Lo usan la ficha y su PDF, para que el reporte sea exactamente lo que se ve en
        pantalla. Cada tabla se corta por su propia fecha (disponibilidad, registro,
        obligacion); las tarjetas y la cadena por vigencia no pasan por aqui.
        """
        def en_rango(qs, campo):
            if desde:
                qs = qs.filter(**{f"{campo}__gte": desde})
            if hasta:
                qs = qs.filter(**{f"{campo}__lte": hasta})
            return qs

        cdps_proyecto = (
            en_rango(Cdp.objects, "fecha_disp")
            .filter(cdps_imputados__proyecto=proyecto)
            .annotate(valor_cdp=Sum("cdps_imputados__valor_disponibilidad_def"))
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
            .select_related("tipo_orden_gasto", "beneficiario")
            .order_by("vigencia", "fecha_obli", "nro_obligacion")
        )

        totales_obligaciones = (en_rango(ObligacionImputacion.objects, "obligacion__fecha_obli")
                                .filter(proyecto=proyecto)
                                .aggregate(t=Sum("valor_obligacion"), s=Sum("saldo_obli"),
                                           p=Sum("pagos")))
        return {
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
        ]
        return propia + super().get_urls()


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


@admin.register(Rubro)
class RubroAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("codigo", "nombre", "tipo")
    list_filter = (("tipo", ChoicesDropdownFilter),)
    search_fields = ("codigo", "nombre")


@admin.register(Fuente)
class FuenteAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("codigo", "nombre")
    search_fields = ("codigo", "nombre")


@admin.register(CentroCosto)
class CentroCostoAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("codigo", "nombre")
    search_fields = ("codigo", "nombre")


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


@admin.register(MetaIndicador)
class MetaIndicadorAdmin(ModelAdmin):
    form = MetaIndicadorForm
    compressed_fields = True
    list_fullwidth = True
    inlines = (VigenciaMetaInline,)
    list_sections = (ProyectosDeLaMeta,)
    list_display = ("codigo", "ficha_link", "indicador", "programa_pdd", "meta_del_cuatrienio", "estado")
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
    list_select_related = ("indicador_mga", "programa_pdd", "programa_pdd__sector_pdd")
    autocomplete_fields = ("indicador_mga", "programa_pdd", "indicadores_pdd",
                           "dependencias_responsables")
    filter_horizontal = ("ods",)

    @display(description="Indicador MGA", ordering="indicador_mga__codigo")
    def indicador(self, obj):
        return corto(f"{obj.indicador_mga.codigo} - {obj.indicador_mga.descripcion}", 80)

    @display(description="Meta cuatrienio", ordering="meta_cuatrenio")
    def meta_del_cuatrienio(self, obj):
        # 1.500 y no 1500,000: el campo lleva tres decimales y asi se leia como millon y medio
        return cifra(obj.meta_cuatrenio)

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
                .select_related("indicador_mga", "programa_pdd__sector_pdd__linea_estrategica"
                                "__plan_desarrollo")
                .prefetch_related("dependencias_responsables", "ods")
                .filter(pk=object_id).first())
        if meta is None:
            raise Http404("No hay meta con ese id.")

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
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Ficha de la meta {meta.codigo}",
            "meta": meta,
            "tarjetas": tarjetas,
            "filas": filas,
            "volver": reverse("admin:siifweb_metaindicador_change", args=(meta.pk,)),
            # El formulario completo de un proyecto nuevo, ya programado en esta meta, que vuelve
            # aqui. Es el enlace secundario del modal de programar
            "nuevo_proyecto": (reverse("admin:siifweb_programacionproyectos_add") + "?" + urlencode(
                {"meta": meta.pk, "volver": request.path})
                if request.user.has_perm("siifweb.add_programacionproyectos") else ""),
            # El modal de programar: solo para quien puede crear programaciones
            "programar": ({
                "url": reverse("admin:siifweb_metaindicador_programar", args=(meta.pk,)),
                "buscar": reverse("admin:siifweb_metaindicador_buscar_proyectos", args=(meta.pk,)),
                # Las vigencias del plan (2024-2027), no las del ano: una meta se programa
                # para el cuatrienio
                "vigencias": sorted(set(VigenciaMeta.objects.order_by()
                                        .values_list("vigencia", flat=True)))
                             or [v for v, _ in listado_vigencias_metas()],
                "metas": [(m.pk, f"{m.codigo} - {m.indicador_mga.codigo}: "
                                 f"{corto(m.indicador_mga.descripcion, 70)}")
                          for m in MetaIndicador.objects.select_related("indicador_mga").order_by("codigo")],
                "tipos_banco": TipoBanco.objects.all(),
                "municipios": Municipio.objects.all(),
                "puede_crear": request.user.has_perm("siifweb.add_programacionproyectos"),
                "puede_anotar": request.user.has_perm("siifweb.add_observacionproyecto"),
            } if request.user.has_perm("siifweb.add_programacionmeta") else None),
            # La vigencia que se acaba de programar llega desplegada
            "abrir": request.GET.get("abrir", ""),
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

        # Las programaciones
        metas_ok = {m.pk: m for m in MetaIndicador.objects.filter(
            pk__in=[x for x in request.POST.getlist("meta") if x.isdigit()])}
        vigencias_ok = {v for v, _ in listado_vigencias_metas()}
        filas, vistas = [], set()
        for i, (m, v, valor) in enumerate(zip(request.POST.getlist("meta"), request.POST.getlist("vigencia"),
                                             request.POST.getlist("meta_vigencia")), start=1):
            meta = metas_ok.get(int(m)) if m.isdigit() else None
            if meta is None:
                return error(f"Fila {i}: elija la meta.")
            if not v.isdigit() or int(v) not in vigencias_ok:
                return error(f"Fila {i}: elija la vigencia.")
            valor = (valor or "").strip().replace(",", ".")
            if valor:
                try:
                    valor = Decimal(valor)
                except InvalidOperation:
                    return error(f"Fila {i}: la meta de la vigencia tiene que ser un número.")
                if valor.as_tuple().exponent < -5 or valor < 0:
                    return error(f"Fila {i}: la meta de la vigencia admite hasta cinco decimales "
                                 "y no puede ser negativa.")
            else:
                valor = None
            if (meta.pk, int(v)) in vistas:
                return error(f"Fila {i}: {meta.codigo} en {v} está repetida.")
            vistas.add((meta.pk, int(v)))
            filas.append((meta, int(v), valor))
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
                nombre = " ".join((request.POST.get("nombre") or "").split())
                bpin = (request.POST.get("bpin") or "").strip()
                if not nombre:
                    return error("Escriba el nombre del proyecto.")
                if bpin and (not bpin.isdigit() or len(bpin) > 20):
                    return error("El BPIN lleva solo números, hasta 20.")
                repetido = (ProgramacionProyectos.objects.filter(bpin=bpin).first() if bpin else None) or \
                    next((p for p in ProgramacionProyectos.objects.all().only("pk", "bpin", "nombre")
                          if cargas_llave(p.nombre) == cargas_llave(nombre)), None)
                if repetido:
                    return error(f"Ya existe: {repetido}. Elíjalo en «Proyecto existente».")
                tipo = request.POST.get("tipo_banco") or ""
                proyecto = ProgramacionProyectos.objects.create(
                    bpin=bpin, nombre=nombre,
                    tipo_banco=TipoBanco.objects.filter(pk=tipo).first() if tipo.isdigit() else None)
                proyecto.municipios.set(Municipio.objects.filter(
                    pk__in=[x for x in request.POST.getlist("municipios") if x.isdigit()]))

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

    def get_urls(self):
        # Antes de las del admin: '<path:object_id>/' la capturaria
        propia = [path("<path:object_id>/ficha/", self.admin_site.admin_view(self.ficha_meta),
                       name="siifweb_metaindicador_ficha"),
                  path("<path:object_id>/programar/", self.admin_site.admin_view(self.programar_proyecto),
                       name="siifweb_metaindicador_programar"),
                  path("<path:object_id>/buscar-proyectos/", self.admin_site.admin_view(self.buscar_proyectos),
                       name="siifweb_metaindicador_buscar_proyectos")]
        return propia + super().get_urls()

    def get_queryset(self, request):
        # El desplegable se arma para las 100 metas de la pagina: los proyectos se traen de
        # una vez y no con una consulta por meta
        return super().get_queryset(request).prefetch_related(Prefetch(
            "programaciones_de_proyectos",
            queryset=ProgramacionMeta.objects.select_related("proyecto", "proyecto__tipo_banco")
            .order_by("vigencia", "proyecto__nombre")))


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
    list_display = ("codigo", "nombre", "programa_mga", "estado")
    list_filter = (("programa_mga", RelatedDropdownFilter), "estado")
    list_select_related = ("programa_mga",)
    autocomplete_fields = ("programa_mga",)


@admin.register(IndicadorMGA)
class IndicadorMGAAdmin(CatalogoPlan):
    list_display = ("codigo", "nombre", "producto_mga", "estado")
    list_filter = (("ods", RelatedDropdownFilter), "estado")
    list_select_related = ("producto_mga",)
    autocomplete_fields = ("producto_mga",)
    filter_horizontal = ("ods",)


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
    list_display = ("nombre", "n_proyectos")
    search_fields = ("nombre",)

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


@admin.register(ProgramacionProyectos)
class ProgramacionProyectosAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    inlines = (ProgramacionMetaInline, ObservacionProyectoInline)
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

    def get_urls(self):
        propia = [path("<path:object_id>/observacion/", self.admin_site.admin_view(self.agregar_observacion),
                       name="siifweb_programacionproyectos_observacion")]
        return propia + super().get_urls()
