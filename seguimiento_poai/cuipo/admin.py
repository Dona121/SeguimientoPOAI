from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from siifweb import cargas
from siifweb.admin import SoloLectura, hash_archivo, pesos

from . import derivacion, ejecucion, listas
from .models import (CPC, ConceptoCUIPO, CorteEjecucionGastos, DetalleSectorial, FilaEjecucionGastos, FuenteCUIPO,
                     HomologacionFuente, HomologacionRubro, PoliticaPublica, ProductoCUIPO, ReglaSeccion,
                     ReglaSituacionFondos, ReglaTercero, SeccionPresupuestal, SituacionFondos, TerceroCUIPO,
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
                    "rp", "obligacion", "pago", "ver_filas", "ver_pendientes")
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

    def get_urls(self):
        propias = [
            path("pendientes/", self.admin_site.admin_view(self.pendientes_ultimo), name="cuipo_pendientes"),
            path("<int:pk>/pendientes/", self.admin_site.admin_view(self.pendientes),
                 name="cuipo_corte_pendientes"),
        ]
        return propias + super().get_urls()

    def pendientes_ultimo(self, request):
        """Los pendientes del corte mas reciente que se proceso bien."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        corte = (CorteEjecucionGastos.objects.filter(estado=CorteEjecucionGastos.Estado.PROCESADO)
                 .order_by("-vigencia", "-fecha_fin", "-fecha_descarga", "-pk").first())
        if corte is None:
            self.message_user(request, "No hay cortes de ejecución procesados.", messages.WARNING)
            return redirect("admin:cuipo_corteejecuciongastos_changelist")
        return redirect("admin:cuipo_corte_pendientes", pk=corte.pk)

    def pendientes(self, request, pk):
        """Lo que falta homologar o reglamentar antes de distribuir un corte."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        corte = get_object_or_404(CorteEjecucionGastos, pk=pk)
        puede_crear = all(request.user.has_perm(f"cuipo.add_{m}") for m in
                          ("reglaseccion", "reglatercero", "homologacionrubro", "reglasituacionfondos"))
        if request.method == "POST" and request.POST.get("reglas_iniciales") and puede_crear:
            with transaction.atomic():
                creadas, omitidas = derivacion.crear_reglas_iniciales()
            self.message_user(request, f"Reglas creadas: {len(creadas)}" + (f" ({'; '.join(creadas)})" if creadas else ""),
                              messages.SUCCESS)
            if omitidas:
                self.message_user(request, "Omitidas: " + "; ".join(omitidas), messages.WARNING)
            return redirect("admin:cuipo_corte_pendientes", pk=corte.pk)
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Pendientes del CUIPO · {corte}",
            "corte": corte,
            "p": derivacion.pendientes(corte),
            "otros_cortes": CorteEjecucionGastos.objects.filter(estado=CorteEjecucionGastos.Estado.PROCESADO)
                            .exclude(pk=corte.pk).order_by("-vigencia", "-fecha_fin")[:10],
            "puede_crear_reglas": puede_crear,
        }
        return TemplateResponse(request, "cuipo/pendientes.html", contexto)

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

    @display(description="Pendientes")
    def ver_pendientes(self, obj):
        if obj.estado != CorteEjecucionGastos.Estado.PROCESADO:
            return "—"
        url = reverse("admin:cuipo_corte_pendientes", args=(obj.pk,))
        return format_html('<a href="{}" class="text-primary-600">Revisar</a>', url)


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

    def get_search_results(self, request, queryset, search_term):
        resultados, duplicados = super().get_search_results(request, queryset, search_term)
        if "field_name" in request.GET:      # autocompletar de un formulario: solo lo vigente
            resultados = resultados.filter(activo=True)
        return resultados, duplicados

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


for _modelo in (SeccionPresupuestal, VigenciaGasto, SituacionFondos, PoliticaPublica, TerceroCUIPO):
    admin.site.register(_modelo, CatalogoCHIPAdmin)


# ---------------------------------------------------------------------------
# Homologaciones y reglas
# ---------------------------------------------------------------------------

def marcar_validacion(request, homologacion):
    homologacion.validado_por, homologacion.fecha_validacion = request.user, timezone.now()


class HomologacionFuenteInline(TabularInline):
    model = HomologacionFuente
    fk_name = "fuente_cuipo"
    extra = 0
    fields = ("fuente_siifweb", "vigencia", "observacion", "validado_por", "fecha_validacion")
    readonly_fields = ("validado_por", "fecha_validacion")
    autocomplete_fields = ("fuente_siifweb",)
    verbose_name_plural = "Recursos de SIIFWEB que se reportan con esta fuente"


@admin.register(FuenteCUIPO)
class FuenteCUIPOAdmin(CatalogoCHIPAdmin):
    """La fuente es de la lista (solo lectura); en ella se registran los recursos que la usan."""
    list_display = ("codigo", "descripcion_corta", "n_recursos", "activo")
    inlines = (HomologacionFuenteInline,)

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(n=Count("homologaciones", distinct=True))

    def has_change_permission(self, request, obj=None):
        return ModelAdmin.has_change_permission(self, request, obj)

    def get_readonly_fields(self, request, obj=None):
        return ("codigo", "descripcion", "activo", "version")

    def save_formset(self, request, form, formset, change):
        for homologacion in formset.save(commit=False):
            marcar_validacion(request, homologacion)
            homologacion.save()
        for borrada in formset.deleted_objects:
            borrada.delete()

    @display(description="Recursos SIIFWEB", ordering="n")
    def n_recursos(self, obj):
        return obj.n


class ReglaAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_per_page = 100


@admin.register(HomologacionFuente)
class HomologacionFuenteAdmin(ReglaAdmin):
    list_display = ("vigencia", "recurso", "nombre_recurso", "fuente_cuipo", "validado_por", "fecha_validacion")
    list_filter = ("vigencia", ("fuente_cuipo", RelatedDropdownFilter))
    search_fields = ("fuente_siifweb__codigo", "fuente_siifweb__nombre", "fuente_cuipo__codigo",
                     "fuente_cuipo__descripcion")
    list_select_related = ("fuente_siifweb", "fuente_cuipo", "validado_por")
    autocomplete_fields = ("fuente_siifweb", "fuente_cuipo")
    fields = ("vigencia", "fuente_siifweb", "fuente_cuipo", "observacion", "validado_por", "fecha_validacion")
    readonly_fields = ("validado_por", "fecha_validacion")

    def save_model(self, request, obj, form, change):
        marcar_validacion(request, obj)
        super().save_model(request, obj, form, change)

    @display(description="Recurso", ordering="fuente_siifweb__codigo")
    def recurso(self, obj):
        return obj.fuente_siifweb.codigo

    @display(description="Nombre del recurso", ordering="fuente_siifweb__nombre")
    def nombre_recurso(self, obj):
        return obj.fuente_siifweb.nombre


@admin.register(HomologacionRubro)
class HomologacionRubroAdmin(ReglaAdmin):
    list_display = ("rubro", "concepto", "observacion")
    search_fields = ("rubro__codigo", "rubro__nombre", "concepto__codigo", "concepto__descripcion")
    list_select_related = ("rubro", "concepto")
    autocomplete_fields = ("rubro", "concepto")


@admin.register(ReglaSeccion)
class ReglaSeccionAdmin(ReglaAdmin):
    list_display = ("centro_costo", "seccion", "observacion")
    search_fields = ("centro_costo__codigo", "centro_costo__nombre", "seccion__codigo", "seccion__descripcion")
    list_select_related = ("centro_costo", "seccion")
    autocomplete_fields = ("centro_costo", "seccion")


@admin.register(ReglaTercero)
class ReglaTerceroAdmin(ReglaAdmin):
    list_display = ("rubro", "centro_costo", "tercero", "observacion")
    search_fields = ("rubro__codigo", "centro_costo__codigo", "centro_costo__nombre", "tercero__codigo",
                     "tercero__descripcion")
    list_select_related = ("rubro", "centro_costo", "tercero")
    autocomplete_fields = ("rubro", "centro_costo", "tercero")


@admin.register(ReglaSituacionFondos)
class ReglaSituacionFondosAdmin(ReglaAdmin):
    list_display = ("prefijo_rubro", "fuente_cuipo", "situacion", "observacion")
    search_fields = ("prefijo_rubro", "fuente_cuipo__codigo")
    list_select_related = ("fuente_cuipo", "situacion")
    autocomplete_fields = ("fuente_cuipo", "situacion")
