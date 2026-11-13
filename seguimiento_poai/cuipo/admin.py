from django import forms
from django.contrib import admin, messages
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from siifweb import cargas
from siifweb.admin import SoloLectura, hash_archivo, pesos

from . import ejecucion, listas
from .models import (CPC, ConceptoCUIPO, CorteEjecucionGastos, DetalleSectorial, FilaEjecucionGastos, FuenteCUIPO,
                     PoliticaPublica, ProductoCUIPO, SeccionPresupuestal, SituacionFondos, TerceroCUIPO,
                     VersionListas, VigenciaGasto)


class CorteEjecucionGastosForm(forms.ModelForm):
    class Meta:
        model = CorteEjecucionGastos
        fields = ("vigencia", "fecha_inicio", "fecha_fin", "fecha_descarga", "archivo")

    def clean(self):
        datos = super().clean()
        archivo = datos.get("archivo")
        if archivo and hasattr(archivo, "chunks"):
            digest = hash_archivo(archivo)
            previo = CorteEjecucionGastos.objects.filter(hash=digest).exclude(pk=self.instance.pk).first()
            if previo:
                raise forms.ValidationError(f"Este archivo ya está cargado como '{previo}'.")
            self.instance.hash = digest
        return datos


@admin.register(CorteEjecucionGastos)
class CorteEjecucionGastosAdmin(ModelAdmin):
    """El reporte de ejecucion de gastos por corte. Al guardarlo se importa."""
    form = CorteEjecucionGastosForm
    compressed_fields = True
    list_fullwidth = True
    list_display = ("__str__", "vigencia", "fecha_inicio", "fecha_fin", "fecha_descarga", "estado_badge", "filas",
                    "rp", "obligacion", "pago", "ver_filas")
    list_filter = ("vigencia", ("estado", ChoicesDropdownFilter))
    readonly_fields = ("estado", "filas", "mensaje", "hash", "fecha_creacion", "fecha_actualizacion")
    actions = ("volver_a_procesar",)
    fieldsets = (
        ("Reporte", {"fields": ("vigencia", ("fecha_inicio", "fecha_fin"), "fecha_descarga", "archivo"),
                     "description": "Ejecución presupuestal del gasto por centro de costo y fondo "
                                    "(estado_ppto_gasto_gobatl_fyccw) de una vigencia, con todas sus columnas. "
                                    "Se importa al guardar."}),
        ("Resultado del proceso", {"fields": ("estado", "filas", "mensaje", "hash")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            t_rp=Sum("filas_ejecucion__rp"), t_obligacion=Sum("filas_ejecucion__obligacion"),
            t_pago=Sum("filas_ejecucion__pago"))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change or "archivo" in form.changed_data:
            self._informar(request, obj, ejecucion.procesar(obj))

    def _informar(self, request, corte, bien):
        self.message_user(request, f"{corte}: {corte.mensaje}", messages.SUCCESS if bien else messages.ERROR)

    @action(description="Volver a procesar los cortes seleccionados", icon="play_arrow")
    def volver_a_procesar(self, request, queryset):
        for corte in queryset:
            self._informar(request, corte, ejecucion.procesar(corte))

    @display(description="Estado", label={"Pendiente": "warning", "Procesado": "success", "Con error": "danger"})
    def estado_badge(self, obj):
        return obj.get_estado_display()

    @display(description="RP", ordering="t_rp")
    def rp(self, obj):
        return pesos(obj.t_rp)

    @display(description="Obligación", ordering="t_obligacion")
    def obligacion(self, obj):
        return pesos(obj.t_obligacion)

    @display(description="Pago", ordering="t_pago")
    def pago(self, obj):
        return pesos(obj.t_pago)

    @display(description="Filas")
    def ver_filas(self, obj):
        url = reverse("admin:cuipo_filaejecuciongastos_changelist")
        return format_html('<a href="{}?corte__id__exact={}" class="text-primary-600">Ver</a>', url, obj.pk)


@admin.register(FilaEjecucionGastos)
class FilaEjecucionGastosAdmin(SoloLectura):
    list_display = ("rubro", "nombre_rubro_corto", "recurso", "centro_costo", "proyecto",
                    "apropiacion_definitiva", "cdp", "rp", "obligacion", "pago", "de_otra_vigencia")
    list_filter = (("corte", RelatedDropdownFilter), "corte__vigencia", "de_otra_vigencia")
    search_fields = ("rubro", "nombre_rubro", "proyecto", "recurso", "nombre_recurso")
    list_select_related = ("corte",)
    list_per_page = 100
    fieldsets = (
        ("Fila", {"fields": ("corte", "rubro_id_siifweb", "de_otra_vigencia", "rubro", "nombre_rubro", "recurso",
                             "nombre_recurso", "centro_costo", "nombre_centro_costo", "proyecto")}),
        ("Apropiación", {"fields": ("apropiacion_inicial", "adicion", "disminucion", "credito", "contracredito",
                                    "aplazamientos", "desaplazamientos", "apropiacion_definitiva")}),
        ("Ejecución", {"fields": ("solicitud_tramite", "cdp", "rp", "obligacion", "pago")}),
    )

    @display(description="Nombre del rubro", ordering="nombre_rubro")
    def nombre_rubro_corto(self, obj):
        return obj.nombre_rubro if len(obj.nombre_rubro) <= 60 else obj.nombre_rubro[:60].rstrip() + "..."


# ---------------------------------------------------------------------------
# Listas CHIP
# ---------------------------------------------------------------------------

class VersionListasForm(forms.ModelForm):
    class Meta:
        model = VersionListas
        fields = ("nombre", "archivo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["archivo"].required = True

    def clean(self):
        datos = super().clean()
        archivo = datos.get("archivo")
        if archivo and hasattr(archivo, "chunks"):
            digest = hash_archivo(archivo)
            previa = VersionListas.objects.filter(hash=digest).exclude(pk=self.instance.pk).first()
            if previa:
                raise forms.ValidationError(f"Este archivo ya está importado como '{previa}'.")
            self.instance.hash = digest
        return datos


@admin.register(VersionListas)
class VersionListasAdmin(ModelAdmin):
    """Las listas CHIP que publica la Contaduria. Al guardar una version se importa."""
    form = VersionListasForm
    compressed_fields = True
    list_fullwidth = True
    list_display = ("nombre", "fecha_creacion", "cargado_por", "estado_badge", "mensaje")
    readonly_fields = ("estado", "mensaje", "hash", "cargado_por", "fecha_creacion", "fecha_actualizacion")
    actions = ("volver_a_importar",)
    fieldsets = (
        ("Listas", {"fields": ("nombre", "archivo"),
                    "description": "Listas_Categoria_CUIPO_MM-AAAA.xlsx de la Contaduría. Se importa al guardar: "
                                   "lo nuevo se crea, lo que cambió se actualiza y lo que ya no viene queda "
                                   "inactivo."}),
        ("Resultado de la importación", {"fields": ("estado", "mensaje", "cargado_por", "hash")}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.cargado_por = request.user
        super().save_model(request, obj, form, change)
        if not change or "archivo" in form.changed_data:
            self._importar(request, obj)

    def _importar(self, request, version):
        if not version.archivo:
            self.message_user(request, f"{version}: no tiene archivo para importar.", messages.ERROR)
            return
        bien = listas.procesar(version, cargas.stream(version.archivo))
        self.message_user(request, f"{version}: {version.mensaje}", messages.SUCCESS if bien else messages.ERROR)

    @action(description="Volver a importar las versiones seleccionadas", icon="play_arrow")
    def volver_a_importar(self, request, queryset):
        for version in queryset.order_by("fecha_creacion"):
            self._importar(request, version)

    @display(description="Estado", label={"Pendiente": "warning", "Procesado": "success", "Con error": "danger"})
    def estado_badge(self, obj):
        return obj.get_estado_display()


class CatalogoCHIPAdmin(SoloLectura):
    """Las listas se mantienen importando una version nueva, no a mano."""
    list_display = ("codigo", "descripcion_corta", "activo", "version")
    list_filter = ("activo", ("version", RelatedDropdownFilter))
    search_fields = ("codigo", "descripcion")
    list_select_related = ("version",)
    list_per_page = 100

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description="Descripción", ordering="descripcion")
    def descripcion_corta(self, obj):
        return obj.descripcion if len(obj.descripcion) <= 90 else obj.descripcion[:90].rstrip() + "..."


@admin.register(ConceptoCUIPO)
class ConceptoCUIPOAdmin(CatalogoCHIPAdmin):
    list_display = ("codigo", "descripcion_corta", "nivel", "habilitado_departamentos", "requiere_cpc", "activo")
    list_filter = ("nivel", "habilitado_departamentos", "requiere_cpc", "activo")


@admin.register(ProductoCUIPO)
class ProductoCUIPOAdmin(CatalogoCHIPAdmin):
    list_display = ("codigo", "descripcion_corta", "sector", "aplica_territoriales", "activo")
    list_filter = ("activo", "sector")
    search_fields = ("codigo", "descripcion", "programa")


@admin.register(CPC)
class CPCAdmin(CatalogoCHIPAdmin):
    list_display = ("codigo", "descripcion_corta", "seccion", "activo")
    list_filter = ("activo", "seccion")


@admin.register(DetalleSectorial)
class DetalleSectorialAdmin(CatalogoCHIPAdmin):
    list_display = ("codigo", "descripcion_corta", "grupo", "sector", "activo")
    list_filter = ("activo", "sector")


for _modelo in (FuenteCUIPO, SeccionPresupuestal, VigenciaGasto, SituacionFondos, PoliticaPublica, TerceroCUIPO):
    admin.site.register(_modelo, CatalogoCHIPAdmin)

