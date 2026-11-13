from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from siifweb import cargas
from siifweb.admin import SoloLectura, hash_archivo, pesos

from . import derivacion, distribucion, ejecucion, listas, plano, semillas, validacion
from .models import periodo_de as derivacion_periodo
from .models import (CPC, ConceptoCUIPO, CorteEjecucionGastos, DetalleSectorial, DistribucionBPIN,
                     FilaEjecucionGastos, FuenteCUIPO, HomologacionFuente, LineaCUIPO, HomologacionRubro, PoliticaPublica, ProductoCUIPO, ReglaSeccion,
                     ReglaSituacionFondos, ReglaTercero, SeccionPresupuestal, SituacionFondos, TerceroCUIPO,
                     VersionListas, VigenciaGasto)


class CorteEjecucionGastosForm(forms.ModelForm):
    class Meta:
        model = CorteEjecucionGastos
        fields = ("vigencia", "fecha_inicio", "fecha_fin", "fecha_descarga", "archivo")

    def clean(self):
        datos = super().clean()
        archivo = datos.get("archivo")
        if archivo and hasattr(archivo, "chunks") and self.instance.pk and self.instance.distribuciones.exists():
            raise forms.ValidationError("Este corte ya tiene distribuciones del CUIPO: no se cambia su archivo. "
                                        "Para datos más recientes, cargue un corte nuevo.")
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
                    "rp", "obligacion", "pago", "ver_filas", "ver_pendientes", "n_distribuciones", "ver_plano")
    list_filter = ("vigencia", ("estado", ChoicesDropdownFilter))
    readonly_fields = ("estado", "filas", "mensaje", "hash", "fecha_creacion", "fecha_actualizacion")
    actions = ("volver_a_procesar", "precargar_distribucion")
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
            self._procesar(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.distribuciones.exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_urls(self):
        propias = [
            path("pendientes/", self.admin_site.admin_view(self.pendientes_ultimo), name="cuipo_pendientes"),
            path("<int:pk>/pendientes/", self.admin_site.admin_view(self.pendientes),
                 name="cuipo_corte_pendientes"),
            path("<int:pk>/plano/", self.admin_site.admin_view(self.plano_chip), name="cuipo_corte_plano"),
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
        puede_sembrar = all(request.user.has_perm(f"cuipo.add_{m}") for m in ("homologacionfuente", "homologacionrubro"))
        if request.method == "POST" and request.FILES.get("semillas") and puede_sembrar:
            # El archivo se lee en memoria y no se guarda (en local el almacenamiento es produccion)
            try:
                self.message_user(request, "Semillas: " + semillas.cargar(request.FILES["semillas"]), messages.SUCCESS)
            except Exception as error:
                self.message_user(request, f"Semillas: {error}", messages.ERROR)
            return redirect("admin:cuipo_corte_pendientes", pk=corte.pk)
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
            "puede_sembrar": puede_sembrar,
        }
        return TemplateResponse(request, "cuipo/pendientes.html", contexto)

    def plano_chip(self, request, pk):
        """El plano CHIP del corte: revisar, descargar el bloque de inversion, integrarlo en el plano
        de presupuesto y marcar enviadas las distribuciones validadas."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        corte = get_object_or_404(CorteEjecucionGastos, pk=pk)
        volver = redirect("admin:cuipo_corte_plano", pk=corte.pk)
        if request.GET.get("descargar"):
            try:
                texto = plano.generar(corte)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)
                return volver
            respuesta = HttpResponse(texto.encode("utf-8"), content_type="text/plain; charset=utf-8")
            respuesta["Content-Disposition"] = f'attachment; filename="{plano.nombre_archivo(corte)}"'
            return respuesta
        if request.method == "POST" and request.FILES.get("presupuesto"):
            archivo = request.FILES["presupuesto"]
            datos = archivo.read()
            codificacion = "utf-8"
            try:
                texto = datos.decode("utf-8")
            except UnicodeDecodeError:
                codificacion, texto = "latin-1", datos.decode("latin-1")
            try:
                integrado = plano.integrar(texto, corte)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)
                return volver
            nombre = archivo.name.rsplit(".", 1)[0] + "_con_inversion_CUIPO.txt"
            respuesta = HttpResponse(integrado.encode(codificacion), content_type=f"text/plain; charset={codificacion}")
            respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
            return respuesta
        if request.method == "POST" and request.POST.get("marcar_enviadas"):
            if not request.user.has_perm("cuipo.change_distribucionbpin"):
                raise PermissionDenied
            n = 0
            for dist in corte.distribuciones.filter(estado=DistribucionBPIN.Estado.VALIDADO):
                validacion.cambiar_estado(dist, DistribucionBPIN.Estado.ENVIADO, request.user)
                n += 1
            self.message_user(request, f"Marcadas como enviadas: {n}.", messages.SUCCESS)
            return volver

        problemas = plano.revisar(corte)
        vista, n_lineas = [], 0
        if not problemas:
            renglones = plano.generar(corte).splitlines()
            n_lineas, vista = len(renglones) - 1, renglones[:41]
        estados = {e: corte.distribuciones.filter(estado=e).count() for e in DistribucionBPIN.Estado.values}
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Plano CUIPO · {corte}",
            "corte": corte, "periodo": derivacion_periodo(corte), "problemas": problemas,
            "vista": [r.split("\t") for r in vista], "n_lineas": n_lineas,
            "estados": [(DistribucionBPIN.Estado(e).label, n) for e, n in estados.items()],
            "validadas": estados.get(DistribucionBPIN.Estado.VALIDADO, 0),
            "puede_marcar": request.user.has_perm("cuipo.change_distribucionbpin"),
        }
        return TemplateResponse(request, "cuipo/plano.html", contexto)

    @display(description="Plano")
    def ver_plano(self, obj):
        if not obj.distribuciones.exists():
            return "—"
        return format_html('<a href="{}" class="text-primary-600">Plano</a>',
                           reverse("admin:cuipo_corte_plano", args=(obj.pk,)))

    def _procesar(self, request, corte):
        try:
            bien = ejecucion.procesar(corte)
        except ejecucion.CorteConDistribucion as error:
            self.message_user(request, str(error), messages.ERROR)
            return
        self.message_user(request, f"{corte}: {corte.mensaje}", messages.SUCCESS if bien else messages.ERROR)

    @action(description="Volver a procesar los cortes seleccionados", icon="play_arrow")
    def volver_a_procesar(self, request, queryset):
        for corte in queryset:
            self._procesar(request, corte)

    @action(description="Precargar la distribución del CUIPO", icon="call_split",
            permissions=["precargar"])
    def precargar_distribucion(self, request, queryset):
        for corte in queryset:
            try:
                self.message_user(request, f"{corte}: {distribucion.precargar(corte)}", messages.SUCCESS)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)

    def has_precargar_permission(self, request):
        return request.user.has_perm("cuipo.add_distribucionbpin")

    @display(description="Distribuciones")
    def n_distribuciones(self, obj):
        n = obj.distribuciones.count()
        if not n:
            return "—"
        url = reverse("admin:cuipo_distribucionbpin_changelist")
        return format_html('<a href="{}?corte__id__exact={}" class="text-primary-600">{}</a>', url, obj.pk, n)

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


# ---------------------------------------------------------------------------
# Distribucion por BPIN
# ---------------------------------------------------------------------------

CUALITATIVOS = ("cpc", "detalle_sectorial", "tercero", "politica_publica")


class LineaCUIPOInline(TabularInline):
    """Las lineas de la distribucion. Mientras llega la pantalla por BPIN (fase 4), aqui se
    digitan los valores por producto y se cambia la vigencia de gasto."""
    model = LineaCUIPO
    extra = 0
    fields = ("fila", "producto", "vigencia_gasto", "compromisos", "obligaciones", "pagos", "origen_valores",
              "cpc", "detalle_sectorial", "tercero", "politica_publica")
    readonly_fields = ("origen_valores",)
    autocomplete_fields = ("producto", "vigencia_gasto", "cpc", "detalle_sectorial", "tercero", "politica_publica")
    tab = True

    def _borrador(self, obj):
        return obj is None or obj.estado == DistribucionBPIN.Estado.BORRADOR

    def has_add_permission(self, request, obj=None):
        return self._borrador(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._borrador(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._borrador(obj) and super().has_delete_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "fila":
            pk = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            dist = DistribucionBPIN.objects.filter(pk=pk).first() if pk else None
            kwargs["queryset"] = dist.filas() if dist else FilaEjecucionGastos.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(DistribucionBPIN)
class DistribucionBPINAdmin(ModelAdmin):
    """La distribucion de cada BPIN entre sus productos. La crea la precarga del corte."""
    compressed_fields = True
    list_fullwidth = True
    list_per_page = 100
    list_display = ("bpin", "nombre_proyecto", "periodo", "regla", "estado", "n_lineas", "cuadra", "enlace_distribuir")
    list_filter = (("corte", RelatedDropdownFilter), "regla", "estado")
    search_fields = ("bpin",)
    list_select_related = ("corte",)
    readonly_fields = ("corte", "periodo", "bpin", "regla", "productos_del_bpin", "observacion", "validado_por",
                       "fecha_validacion", "cuadre_por_fila", "pantalla", "resultado_validacion")
    fieldsets = (
        (None, {"fields": ("corte", "periodo", "bpin", "regla", "productos_del_bpin", "observacion", "pantalla")}),
        ("Estado", {"fields": ("estado", "validado_por", "fecha_validacion", "resultado_validacion"),
                    "description": "Borrador → validado (sin errores) → enviado. Una validada puede volver a borrador; "
                                   "una enviada ya no cambia."}),
        ("Cuadre con SIIFWEB", {"fields": ("cuadre_por_fila",)}),
    )
    inlines = (LineaCUIPOInline,)
    actions = ("volver_a_precargar", "validar_seleccionadas")

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        if request.method == "GET" and not DistribucionBPIN.objects.exists():
            self.message_user(request, "Las distribuciones no se agregan a mano: se crean con la acción \"Precargar "
                                       "la distribución del CUIPO\" en Cortes de ejecución de gastos, sobre un corte "
                                       "del 1 de enero al cierre de un trimestre (31/03, 30/06, 30/09 o 31/12).",
                              messages.INFO)
        return super().changelist_view(request, extra_context)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "estado" and request.resolver_match:
            pk = request.resolver_match.kwargs.get("object_id")
            actual = DistribucionBPIN.objects.filter(pk=pk).values_list("estado", flat=True).first() if pk else None
            if actual:
                permitidos = {actual} | validacion.TRANSICIONES[actual]
                kwargs["choices"] = [(v, t) for v, t in DistribucionBPIN.Estado.choices if v in permitidos]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # El estado se cambia despues de guardar las lineas (save_related), para validar lo ultimo
        if "estado" in form.changed_data:
            request._estado_pedido = obj.estado
            obj.estado = form.initial.get("estado", obj.estado)
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        nuevo = getattr(request, "_estado_pedido", None)
        if nuevo:
            try:
                validacion.cambiar_estado(form.instance, nuevo, request.user)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)

    def save_formset(self, request, form, formset, change):
        """Lo que se cambia a mano queda con origen manual."""
        for linea in formset.save(commit=False):
            cambios = next((f.changed_data for f in formset.forms if f.instance is linea), [])
            if {"compromisos", "obligaciones", "pagos"} & set(cambios) or linea.pk is None:
                linea.origen_valores = LineaCUIPO.OrigenValores.MANUAL
            for campo in CUALITATIVOS:
                if campo in cambios:
                    setattr(linea, f"origen_{campo}", LineaCUIPO.Origen.MANUAL)
            linea.save()
        for borrada in formset.deleted_objects:
            borrada.delete()

    # -- La pantalla por BPIN (HTMX; unfold ya carga htmx 2 en todas las paginas del admin) --

    def get_urls(self):
        def ruta(sufijo, vista, nombre):
            return path(f"<int:pk>/distribuir/{sufijo}", self.admin_site.admin_view(vista),
                        name=f"cuipo_distribuir{nombre}")
        propias = [
            ruta("", self.distribuir, ""),
            ruta("asociar/", self.d_asociar, "_asociar"),
            ruta("celda/", self.d_celda, "_celda"),
            ruta("vigencia/", self.d_vigencia, "_vigencia"),
            ruta("quitar/", self.d_quitar, "_quitar"),
            ruta("cualitativo/", self.d_cualitativo, "_cualitativo"),
            ruta("estado/", self.d_estado, "_estado"),
            ruta("elegir/", self.d_elegir, "_elegir"),
        ]
        return propias + super().get_urls()

    def _distribucion(self, request, pk):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return get_object_or_404(DistribucionBPIN.objects.select_related("corte"), pk=pk)

    def _puede_editar(self, request, dist):
        return dist.estado == DistribucionBPIN.Estado.BORRADOR and all(
            request.user.has_perm(f"cuipo.{p}_lineacuipo") for p in ("add", "change", "delete"))

    def _contexto(self, request, dist, **extra):
        return {"dist": dist, "editable": self._puede_editar(request, dist),
                "vigencias": list(VigenciaGasto.objects.filter(activo=True).order_by("codigo")),
                "vigencia_1": VigenciaGasto.objects.filter(codigo="1").first(),
                "totales": distribucion.totales(dist), "validacion": validacion.validar_distribucion(dist),
                "puede_cambiar_estado": request.user.has_perm("cuipo.change_distribucionbpin"), **extra}

    def _parcial(self, request, dist, fila=None, mensaje="", error=""):
        """La fila (o toda la matriz) y, fuera de banda, los totales."""
        if fila is not None:
            contexto = self._contexto(request, dist, d=distribucion.matriz(dist, solo_fila=fila)[0], error=error)
            html = render_to_string("cuipo/_fila.html", contexto, request=request)
        else:
            contexto = self._contexto(request, dist, filas=distribucion.matriz(dist), mensaje=mensaje, error=error)
            html = render_to_string("cuipo/_matriz.html", contexto, request=request)
        html += render_to_string("cuipo/_totales.html", {**contexto, "oob": True}, request=request)
        html += render_to_string("cuipo/_validacion.html", {**contexto, "oob": True}, request=request)
        return HttpResponse(html)

    def _editar(self, request, pk, accion, fila_de_respuesta=True):
        """Corre una accion de edicion y responde con la fila o la matriz."""
        dist = self._distribucion(request, pk)
        if request.method != "POST":
            return HttpResponseBadRequest("Solo POST")
        if not self._puede_editar(request, dist):
            raise PermissionDenied
        try:
            resultado = accion(dist)
        except ValueError as error:
            fila = dist.filas().filter(pk=request.POST.get("fila")).first() if fila_de_respuesta else None
            if fila is None and request.POST.get("linea"):
                linea = dist.lineas.filter(pk=request.POST["linea"]).select_related("fila").first()
                fila = linea.fila if linea else None
            return self._parcial(request, dist, fila=fila, error=str(error))
        if fila_de_respuesta:
            return self._parcial(request, dist, fila=resultado)
        return self._parcial(request, dist, mensaje=resultado)

    def distribuir(self, request, pk):
        dist = self._distribucion(request, pk)
        anterior, antecedente = distribucion.antecedente(dist)
        from siifweb.models import FormulacionProyecto
        formulacion = FormulacionProyecto.objects.filter(bpin=dist.bpin).first()
        contexto = {
            **self.admin_site.each_context(request),
            "title": f"Distribuir {dist.bpin}",
            **self._contexto(request, dist, filas=distribucion.matriz(dist)),
            "nombre": "Inversión sin proyecto" if dist.bpin == "0" else (formulacion.nombre if formulacion else ""),
            "productos": list(dist.productos.order_by("codigo")),
            "anterior": anterior, "antecedente": antecedente,
        }
        return TemplateResponse(request, "cuipo/distribuir.html", contexto)

    ELEGIBLES = {"cpc": ("CPC", CPC), "detalle_sectorial": ("detalle sectorial", DetalleSectorial),
                 "tercero": ("tercero", TerceroCUIPO), "politica_publica": ("política pública", PoliticaPublica)}

    def d_elegir(self, request, pk):
        """La ventana para elegir un cualitativo de la linea: buscador y lista con la descripcion
        completa. Con solo=resultados devuelve solo la lista (al escribir en el buscador)."""
        dist = self._distribucion(request, pk)
        if request.GET.get("campo") not in self.ELEGIBLES:
            return HttpResponseBadRequest("Campo desconocido")
        campo = request.GET["campo"]
        titulo, modelo = self.ELEGIBLES[campo]
        linea = get_object_or_404(dist.lineas.select_related("fila", "producto", campo), pk=request.GET.get("linea"))
        texto = (request.GET.get("codigo") or "").strip()
        opciones = modelo.objects.filter(activo=True)
        for palabra in texto.split():
            opciones = opciones.filter(Q(codigo__startswith=palabra) | Q(descripcion__icontains=palabra))
        total = opciones.count()
        contexto = {"dist": dist, "linea": linea, "campo": campo, "titulo": titulo, "actual": getattr(linea, campo),
                    "opciones": opciones.order_by("codigo")[:60], "total": total, "texto": texto,
                    "editable": self._puede_editar(request, dist)}
        plantilla = "cuipo/_opciones.html" if request.GET.get("solo") == "resultados" else "cuipo/_elegir.html"
        return TemplateResponse(request, plantilla, contexto)

    def d_estado(self, request, pk):
        """Validar, volver a borrador o marcar enviada, desde la pantalla."""
        dist = self._distribucion(request, pk)
        if request.method != "POST":
            return HttpResponseBadRequest("Solo POST")
        if not request.user.has_perm("cuipo.change_distribucionbpin"):
            raise PermissionDenied
        try:
            validacion.cambiar_estado(dist, request.POST.get("estado"), request.user)
            self.message_user(request, f"La distribución quedó {dist.get_estado_display().lower()}.", messages.SUCCESS)
        except ValueError as error:
            self.message_user(request, str(error), messages.ERROR)
        return redirect("admin:cuipo_distribuir", pk=dist.pk)

    def d_asociar(self, request, pk):
        return self._editar(request, pk, lambda d: distribucion.asociar(
            d, request.POST.get("fila"), request.POST.get("producto"), bool(request.POST.get("activo"))))

    def d_celda(self, request, pk):
        return self._editar(request, pk, lambda d: distribucion.guardar_valor(
            d, request.POST.get("fila"), request.POST.get("producto"), request.POST.get("vigencia"),
            request.POST.get("campo"), request.POST.get("valor")))

    def d_vigencia(self, request, pk):
        return self._editar(request, pk, lambda d: distribucion.agregar_vigencia(
            d, request.POST.get("fila"), request.POST.get("producto"), request.POST.get("vigencia")))

    def d_quitar(self, request, pk):
        return self._editar(request, pk, lambda d: distribucion.quitar_linea(d, request.POST.get("linea")))

    def d_cualitativo(self, request, pk):
        return self._editar(request, pk, lambda d: distribucion.cambiar_cualitativo(
            d, request.POST.get("linea"), request.POST.get("campo"), request.POST.get("codigo")))

    @display(description="Pantalla")
    def distribuir_enlace(self, obj):
        return format_html('<a href="{}" class="text-primary-600">Distribuir</a>',
                           reverse("admin:cuipo_distribuir", args=(obj.pk,)))

    @display(description="Distribuir")
    def enlace_distribuir(self, obj):
        return self.distribuir_enlace(obj)

    @display(description="Pantalla de distribución")
    def pantalla(self, obj):
        return self.distribuir_enlace(obj)

    @action(description="Validar las distribuciones seleccionadas", icon="task_alt")
    def validar_seleccionadas(self, request, queryset):
        validadas, con_errores = 0, []
        for dist in queryset.filter(estado=DistribucionBPIN.Estado.BORRADOR).select_related("corte"):
            try:
                validacion.cambiar_estado(dist, DistribucionBPIN.Estado.VALIDADO, request.user)
                validadas += 1
            except ValueError as error:
                con_errores.append(f"{dist.bpin}: {error}")
        self.message_user(request, f"Validadas: {validadas}.", messages.SUCCESS if validadas else messages.INFO)
        for texto in con_errores[:20]:
            self.message_user(request, texto, messages.ERROR)
        if len(con_errores) > 20:
            self.message_user(request, f"... y {len(con_errores) - 20} más con errores.", messages.ERROR)

    @display(description="Validación")
    def resultado_validacion(self, obj):
        r = validacion.validar_distribucion(obj)
        if r.valida and not r.advertencias:
            return "Sin errores."
        partes = [("Error", p.mensaje) for p in r.errores[:30]] + [("Advertencia", p.mensaje) for p in r.advertencias[:10]]
        resumen = f"{len(r.errores)} errores y {len(r.advertencias)} advertencias."
        return format_html("{}<br>{}", resumen, format_html_join(mark_safe("<br>"), "{}: {}", partes))

    @action(description="Volver a precargar (solo borradores; borra lo digitado)", icon="restart_alt")
    def volver_a_precargar(self, request, queryset):
        for dist in queryset:
            try:
                self.message_user(request, f"{dist.bpin}: {distribucion.precargar_de_nuevo(dist)}", messages.SUCCESS)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)

    @display(description="Proyecto")
    def nombre_proyecto(self, obj):
        if obj.bpin == "0":
            return "Inversión sin proyecto"
        from siifweb.models import FormulacionProyecto
        f = FormulacionProyecto.objects.filter(bpin=obj.bpin).only("nombre").first()
        nombre = f.nombre if f else ""
        return nombre if len(nombre) <= 70 else nombre[:70].rstrip() + "..."

    @display(description="Líneas")
    def n_lineas(self, obj):
        return obj.lineas.count()

    @display(description="Cuadra con SIIFWEB", boolean=True)
    def cuadra(self, obj):
        return all(f["cuadra"] for f in distribucion.cuadre(obj))

    @display(description="Productos")
    def productos_del_bpin(self, obj):
        return ", ".join(f"{p.codigo} {p.descripcion[:60]}" for p in obj.productos.all()) or "—"

    @display(description="Por fila (C / O / P)")
    def cuadre_por_fila(self, obj):
        def cifra(v):
            return f"{v:,.2f}"
        filas = distribucion.cuadre(obj)
        if not filas:
            return "Sin filas"
        return format_html_join(
            mark_safe("<br>"), "{} · recurso {} · CC {}: SIIFWEB {} / {} / {} · diferencia {} / {} / {} {}",
            ((f["fila"].rubro, f["fila"].recurso, f["fila"].centro_costo, *map(cifra, f["siifweb"]),
              *map(cifra, f["diferencia"]), "✔" if f["cuadra"] else "✘") for f in filas))
