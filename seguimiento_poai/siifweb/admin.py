# -*- coding: utf-8 -*-
import hashlib

from django import forms
from django.contrib import admin, messages
from django.forms.models import BaseInlineFormSet
from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum, Min, StringAgg, Max
from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (ChoicesDropdownFilter, RangeDateFilter,
                                          RelatedDropdownFilter,TextFilter,FieldTextFilter,AutocompleteSelectMultipleFilter)
from unfold.decorators import action, display

from . import cargas
from .models import (CargaReporte, Cdp, CdpImputacion, CentroCosto, Clasificacion, Compromiso,
                     CompromisoImputacion, Contrato, ContratoActa, ContratoImputacion,
                     DependenciaResponsable, Fuente, Obligacion, ObligacionImputacion, OrdenGasto,
                     Proyecto, Reserva, ReservaImputacion, Rubro, Tercero)
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
        sin_vigencia = (CargaReporte.TipoReporte.HISTORIAL, CargaReporte.TipoReporte.POAI)
        if tipo and tipo not in sin_vigencia and not datos.get("vigencia"):
            raise forms.ValidationError("La vigencia es obligatoria salvo en el historial de contratos "
                                        "y el cruce POAI, que cubren varias vigencias.")
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
        for carga in queryset.order_by("vigencia", "id"):
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

class FormSetLimitado(BaseInlineFormSet):
    """Limita las filas de un inline de solo lectura.

    No sirve get_queryset del inline (ahi todavia no se filtro por el padre) ni max_num
    (el admin lo pone en 0 cuando has_add_permission es False). El corte tiene que ir en
    el formset, que es quien ya tiene el filtro por la instancia padre.
    """
    limite = 20

    def get_queryset(self):
        if not hasattr(self, "_limitado"):
            self._limitado = super().get_queryset()[:self.limite]
        return self._limitado


class InlineDeProyecto(ImputacionInline):
    """Inline colgado del proyecto. Se muestran las primeras 20 filas: un proyecto de
    nomina tiene cientos de imputaciones y el inline no pagina. El detalle completo
    y agregado esta en la ficha de ejecucion."""
    fk_name = "proyecto"
    formset = FormSetLimitado


class CdpDelProyectoInline(InlineDeProyecto):
    model = CdpImputacion
    verbose_name_plural = "Disponibilidades (CDP)"
    fields = ("cdp", "rubro", "fuente", "valor_certificado", "valor_disponibilidad_def", "saldo_certf")
    readonly_fields = fields


class CompromisoDelProyectoInline(InlineDeProyecto):
    model = CompromisoImputacion
    verbose_name_plural = "Compromisos (RP)"
    fields = ("compromiso", "cdp", "rubro", "fuente", "valor_compromiso_def", "saldo_rp")
    readonly_fields = fields


class ObligacionDelProyectoInline(InlineDeProyecto):
    model = ObligacionImputacion
    verbose_name_plural = "Obligaciones"
    fields = ("obligacion", "compromiso", "rubro", "valor_obligacion", "saldo_obli", "pagos")
    readonly_fields = fields


class ContratoDelProyectoInline(InlineDeProyecto):
    model = ContratoImputacion
    verbose_name_plural = "Contratos"
    fields = ("contrato", "vigencia", "compromiso", "rubro", "fuente")
    readonly_fields = fields


class ReservaDelProyectoInline(InlineDeProyecto):
    model = ReservaImputacion
    verbose_name_plural = "Reservas"
    fields = ("reserva", "cdp_origen", "rubro", "valor_reserva", "obligaciones_reserva", "saldo_reserva")
    readonly_fields = fields


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
            (str(c.pk), c.nombre) for c in Clasificacion.objects.all()]

    def queryset(self, request, queryset):
        valor = self.value() or self.CON         # por defecto: con clasificacion
        if valor == self.TODAS:
            return queryset
        if valor == self.CON:
            return queryset.filter(clasificaciones__isnull=False).distinct()
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
    inlines = (CdpDelProyectoInline, CompromisoDelProyectoInline, ObligacionDelProyectoInline,
               ContratoDelProyectoInline, ReservaDelProyectoInline)
    list_display = ("bpin", "nombre","responsable","ficha_link" ,"clasificacion_txt","primer_fecha_firma_contrato","fecha_inicio_primer_contrato_firmado","certificado",
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
    fieldsets = (
        ("Proyecto", {"fields": ("bpin", "nombre"),
                      "description": "Usa el boton 'Ficha de ejecucion' para ver la cadena completa, "
                                     "los contratos y el calendario de pagos."}),
        ("Responsables y clasificacion", {
            "fields": ("dependencia", "dependencia_responsable", "clasificaciones"),
            "description": "La dependencia de SIIFWEB es la que ejecuta el gasto; la responsable "
                           "viene del cruce POAI y en algunos casos difiere."}),
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
                .annotate(cert=suma_de(CdpImputacion, "valor_certificado"),
                          oblig=suma_de(ObligacionImputacion, "valor_obligacion"))
                .order_by("-oblig"))
    
    def primer_fecha_firma_contrato(self,obj):
        fechas_contrato_proyecto = ContratoImputacion.objects.filter(
            proyecto__id=obj.id
        ).select_related("contrato").order_by("contrato__fecha_firma").first()
        if fechas_contrato_proyecto:
            return fechas_contrato_proyecto.contrato.fecha_firma
        return format_html('<div style="background: oklch(50.5% 0.213 27.518);padding-left: 5px;padding-right: 5px; justify-content: center;align-items: center;align-content:center; border-radius: 5px;font-weight:500 !important; color: white ">{}</div>',"Sin registro de contratos")
    
    primer_fecha_firma_contrato.short_description = "Primer contrato"
    
    def fecha_inicio_primer_contrato_firmado(self,obj):
        fechas_contrato_proyecto = ContratoImputacion.objects.filter(
            proyecto__id=obj.id
        ).select_related("contrato").order_by("contrato__fecha_firma").first()
        if fechas_contrato_proyecto:
            contrato_fecha_inicio = Contrato.objects.filter(
                id=fechas_contrato_proyecto.contrato.id
            ).first()
            return contrato_fecha_inicio.fecha_inicio
        return format_html('<div style="background: oklch(50.5% 0.213 27.518);padding-left: 5px;padding-right: 5px; justify-content: center;align-items: center; border-radius: 5px;font-weight:500 !important; color: white ">{}</div>',"Sin registro de contratos")
    
    
    fecha_inicio_primer_contrato_firmado.short_description = "Inicio primer contrato"

    @display(description="Certificado", ordering="cert")
    def certificado(self, obj):
        return pesos(obj.cert)

    @display(description="Obligado", ordering="oblig")
    def obligado(self, obj):
        return pesos(obj.oblig)

    @display(description="")
    def ficha_link(self, obj):
        url = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(obj.pk,))
        return format_html('<a href="{}" class="text-primary-600" title="Expediente"><i class="material-symbols-outlined">folder_open</a>', url)

    @action(description="Ficha de ejecucion", url_path="ficha-ejecucion", icon="analytics")
    def ficha_ejecucion(self, request, object_id):
        """Vista propia: los inlines muestran filas, esto muestra la ejecucion agregada."""
        proyecto = self.get_object(request, object_id)
        if proyecto is None:
            raise Http404("No hay proyecto con ese id.")

        por_vigencia = {}

        def acumular(consulta, clave):
            for fila in consulta:
                v = fila["v"]
                por_vigencia.setdefault(v, {"vigencia": v})[clave] = fila["t"]

        acumular(CdpImputacion.objects.filter(proyecto=proyecto)
                 .values(v=F("cdp__vigencia")).annotate(t=Sum("valor_certificado")), "certificado")
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
            cert, obl = f.get("certificado") or 0, f.get("obligado") or 0
            f["avance"] = float(obl) / float(cert) * 100 if cert else 0
            filas.append(f)

        totales = {c: sum(f.get(c) or 0 for f in filas)
                   for c in ("certificado", "comprometido", "obligado", "pagado",
                             "sin_comprometer", "sin_obligar")}

        # El pagado va por subconsulta: sumarlo junto al filtro por imputacion
        # multiplicaria las actas por el numero de imputaciones del contrato
        contratos = (Contrato.objects
                     .filter(imputaciones_del_contrato__proyecto=proyecto).distinct()
                     .select_related("tercero")
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
        
        cdps_proyecto = (
            Cdp.objects
            .filter(cdps_imputados__proyecto=proyecto)
            .annotate(valor_cdp=Sum("cdps_imputados__valor_certificado"))
            .order_by("fecha_disp")
        )

        # NO re-agregar cdps_proyecto (ya trae annotate sobre la misma relacion).
        # aggregate() sobre annotate() de la misma relacion aplica un DISTINCT implicito
        # y colapsa valores repetidos legitimos (dos imputaciones del mismo CDP con igual
        # valor), dando un total mas bajo. Se suma directo desde las imputaciones.
        cdps_proyecto_total = (CdpImputacion.objects
                               .filter(proyecto=proyecto)
                               .aggregate(t=Sum("valor_certificado"))["t"] or 0)

        rps_por_proyecto = (
            Compromiso.objects
            .filter(compromisos_imputados__proyecto = proyecto)
            .annotate(valor_rp=Sum("compromisos_imputados__valor_compromiso_def"))
            .order_by("fecha_reg")
        )

        rps_por_proyecto_total = (
            Compromiso.objects
            .filter(compromisos_imputados__proyecto = proyecto)
            .aggregate(t=Sum("compromisos_imputados__valor_compromiso_def"))["t"] or 0
        )

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
            **self.admin_site.each_context(request),
            "title": f"Ficha de ejecucion - {proyecto.bpin}",
            "proyecto": proyecto,
            "filas": filas,
            "totales": totales,
            "totales_tarjetas": [
                ("Certificado", totales["certificado"], "cupo apartado en CDP"),
                ("Comprometido", totales["comprometido"], "contratado en firme"),
                ("Obligado", totales["obligado"], "recibido a satisfaccion"),
                ("Pagado", totales["pagado"], "girado por tesoreria"),
            ],
            "cdps_proyecto" : cdps_proyecto,
            "cdps_proyecto_total" : cdps_proyecto_total,
            "rps_por_proyecto" :rps_por_proyecto,
            "rps_por_proyecto_total" : rps_por_proyecto_total,
            "fuentes_por_proyecto":fuentes_por_proyecto,
            "fuentes_por_proyecto_total":fuentes_por_proyecto_total,
            "contratos": contratos,
            "calendario": calendario,
            "total_pagado_bitacora": sum(p["t"] for p in pagos),
            "reservas": ReservaImputacion.objects.filter(proyecto=proyecto)
                        .select_related("reserva", "cdp_origen", "rubro"),
            "volver": reverse("admin:siifweb_proyecto_change", args=(object_id,)),
        }
        return TemplateResponse(request, "siifweb/ficha_proyecto.html", contexto)

    def reportes_view(self, request):
        """Constructor del reporte: filtra la cadena, elige columnas, baja Excel."""
        from . import reportes
        import io

        preview = None
        if request.method == "POST":
            f = reportes.parse_filtros(request.POST)
            seleccion = [c for c in reportes.ORDEN if c in request.POST.getlist("columnas")]
            claves, filas = reportes.construir(f, seleccion)
            if request.POST.get("accion") == "excel":
                wb = reportes.a_excel(claves, filas)
                buffer = io.BytesIO()
                wb.save(buffer)
                buffer.seek(0)
                resp = HttpResponse(
                    buffer.getvalue(),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                resp["Content-Disposition"] = (
                    f'attachment; filename="reporte_proyectos_{timezone.localdate():%Y%m%d}.xlsx"')
                return resp
            preview = {
                "columnas": [(c, reportes.META[c]["label"], reportes.META[c]["tipo"]) for c in claves],
                "filas": [[(c, fila[c], reportes.META[c]["tipo"]) for c in claves]
                          for fila in filas[:50]],
                "total": len(filas),
            }
            seleccion_actual = seleccion or list(reportes.DEF_SELECCION)
            bpines_sel = set(f["bpines"])
        else:
            seleccion_actual = list(reportes.DEF_SELECCION)
            bpines_sel = set()

        grupos_columnas = [
            (g, [(c[0], c[1], c[3]) for c in reportes.COLUMNAS if c[2] == g])
            for g in reportes.GRUPOS]

        contexto = {
            **self.admin_site.each_context(request),
            "title": "Reportes",
            "grupos_columnas": grupos_columnas,
            "meta": reportes.META,
            "seleccion": set(seleccion_actual),
            "proyectos": list(Proyecto.objects.exclude(bpin__isnull=True)
                              .order_by("bpin").values("bpin", "nombre")),
            "bpines_sel": bpines_sel,
            "valores": request.POST if request.method == "POST" else {},
            "preview": preview,
            "volver": reverse("admin:siifweb_proyecto_changelist"),
        }
        return TemplateResponse(request, "siifweb/reportes.html", contexto)

    def get_urls(self):
        # Las URLs propias van ANTES de las del admin: '<path:object_id>/' las capturaria
        propia = [
            path("reportes/", self.admin_site.admin_view(self.reportes_view),
                 name="siifweb_proyecto_reportes"),
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


@admin.register(OrdenGasto)
class OrdenGastoAdmin(ModelAdmin):
    compressed_fields = True
    list_display = ("nombre",)
    search_fields = ("nombre",)
