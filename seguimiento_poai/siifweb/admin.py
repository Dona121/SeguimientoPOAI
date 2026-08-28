# -*- coding: utf-8 -*-
import hashlib

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import (Case, Count, DateField, DecimalField, F, IntegerField, OuterRef,
                              Q, Subquery, Sum, Value, When)
from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (ChoicesDropdownFilter, RangeDateFilter,
                                          RelatedDropdownFilter,TextFilter,FieldTextFilter,AutocompleteSelectMultipleFilter)
from unfold.decorators import action, display

from . import cargas, tablero
from .models import (BpinProceso, CargaReporte, Cdp, CdpImputacion, CentroCosto, Clasificacion,
                     Compromiso, CompromisoImputacion, Contrato, ContratoActa, ContratoImputacion,
                     ContratoSecop, DependenciaResponsable, Fuente, Obligacion, ObligacionImputacion,
                     OrdenGasto, ProcesoSecop, Proyecto, Reserva, ReservaImputacion, Rubro, Tercero)
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
        
        cdps_proyecto = (
            Cdp.objects
            .filter(cdps_imputados__proyecto=proyecto)
            .annotate(valor_cdp=Sum("cdps_imputados__valor_disponibilidad_def"))
            .order_by("fecha_disp")
        )

        # NO re-agregar cdps_proyecto (ya trae annotate sobre la misma relacion).
        # aggregate() sobre annotate() de la misma relacion aplica un DISTINCT implicito
        # y colapsa valores repetidos legitimos (dos imputaciones del mismo CDP con igual
        # valor), dando un total mas bajo. Se suma directo desde las imputaciones.
        cdps_proyecto_total = (CdpImputacion.objects
                               .filter(proyecto=proyecto)
                               .aggregate(t=Sum("valor_disponibilidad_def"))["t"] or 0)

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

        # Obligaciones del proyecto. El objeto propio viene en el consolidado
        # (columna OBJETO_OBLIG); el del RP queda de respaldo para lo que se cargo
        # antes de que ese campo existiera. Va por subconsulta y no por un segundo
        # Sum: agregar dos relaciones a la vez multiplicaria las filas.
        obligaciones_por_proyecto = (
            Obligacion.objects
            .filter(obligaciones_imputadas__proyecto=proyecto)
            .annotate(valor_obli=Sum("obligaciones_imputadas__valor_obligacion"),
                      objeto_rp=Subquery(ObligacionImputacion.objects
                                         .filter(obligacion=OuterRef("pk"), proyecto=proyecto)
                                         .values("compromiso__objeto_reg")[:1]))
            .select_related("tipo_orden_gasto", "beneficiario")
            .order_by("vigencia", "fecha_obli", "nro_obligacion")
        )

        obligaciones_por_proyecto_total = (
            ObligacionImputacion.objects.filter(proyecto=proyecto)
            .aggregate(t=Sum("valor_obligacion"))["t"] or 0
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
            **comun,
            "filas": filas,
            "totales": totales,
            "totales_tarjetas": [
                ("Disponibilidad definitiva", totales["disponibilidad_definitiva"], "cupo apartado en CDP"),
                ("Comprometido", totales["comprometido"], "contratado en firme"),
                ("Obligado", totales["obligado"], "recibido a satisfaccion"),
                ("Pagado", totales["pagado"], "girado por tesoreria"),
            ],
            "cdps_proyecto" : cdps_proyecto,
            "cdps_proyecto_total" : cdps_proyecto_total,
            "rps_por_proyecto" :rps_por_proyecto,
            "rps_por_proyecto_total" : rps_por_proyecto_total,
            "obligaciones_por_proyecto": obligaciones_por_proyecto,
            "obligaciones_por_proyecto_total": obligaciones_por_proyecto_total,
            "fuentes_por_proyecto":fuentes_por_proyecto,
            "fuentes_por_proyecto_total":fuentes_por_proyecto_total,
            "contratos": contratos,
            "calendario": calendario,
            "total_pagado_bitacora": sum(p["t"] for p in pagos),
            "reservas": ReservaImputacion.objects.filter(proyecto=proyecto)
                        .select_related("reserva", "cdp_origen", "rubro"),
        }
        return TemplateResponse(request, "siifweb/ficha_proyecto.html", contexto)

    def reporte_financiero(self, request):
        """Reporte Financiero del proyecto: una fila por (proyecto, vigencia).

        GET normal -> pagina con filtros y el boton de descarga.
        GET con descargar=xlsx (mas los filtros) -> el Excel.

        Misma cautela que en la ficha: admin_view() no mira permisos de modelo.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied

        from . import reportes
        import io

        vigencias = [int(x) for x in request.GET.getlist("vigencia") if x.isdigit()]
        bpines = [b.strip() for b in request.GET.get("bpin", "").replace(",", " ").split() if b.strip()]
        nombre = request.GET.get("nombre", "").strip()

        if request.GET.get("descargar"):
            wb = reportes.a_excel(reportes.construir(vigencias=vigencias, bpines=bpines, nombre=nombre))
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            resp = HttpResponse(
                buffer.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp["Content-Disposition"] = (
                f'attachment; filename="reporte_financiero_{timezone.localdate():%Y%m%d}.xlsx"')
            return resp

        disponibles = sorted(Cdp.objects.values_list("vigencia", flat=True).distinct())
        contexto = {
            **self.admin_site.each_context(request),
            "title": "Reporte Financiero del proyecto",
            "columnas": [c[1] for c in reportes.COLUMNAS],
            "vigencias_disponibles": disponibles,
            "vigencias_sel": set(vigencias),
            "bpin": request.GET.get("bpin", ""),
            "nombre": nombre,
            "volver": reverse("admin:siifweb_proyecto_changelist"),
        }
        return TemplateResponse(request, "siifweb/reporte_financiero.html", contexto)

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
            desde = parse_date(request.GET.get("desde", "") or "")
            hasta = parse_date(request.GET.get("hasta", "") or "")

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
            "title": "Dashboard de seguimiento",
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
            path("reporte-financiero/", self.admin_site.admin_view(self.reporte_financiero),
                 name="siifweb_proyecto_reporte_financiero"),
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
