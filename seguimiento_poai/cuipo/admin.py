from django import forms
from django.contrib import admin, messages
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from siifweb.admin import SoloLectura, hash_archivo, pesos

from . import ejecucion
from .models import CorteEjecucionGastos, FilaEjecucionGastos


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
