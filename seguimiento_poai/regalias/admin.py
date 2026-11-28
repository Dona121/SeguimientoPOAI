from pathlib import PurePath

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, DropdownFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from siifweb.admin import SoloLectura, hash_archivo

from . import calculos, cargas, servicios
from .models import (CambioProyectoRegalias, CargaRegalias, ClasificacionRegalias, ComentarioProyectoRegalias,
                     ContratoRegalias, EntidadEjecutora, EstadoProyectoRegalias, ProyectoDepartamento,
                     ProyectoDescentralizada, ProyectoMunicipio, ProyectoRegalias, ResponsableGesproy)

# El admin de cada clasificacion, para enlazar un proyecto desde el historial
PROXY_DE = {
    ClasificacionRegalias.DEPARTAMENTO: ProyectoDepartamento,
    ClasificacionRegalias.DESCENTRALIZADA: ProyectoDescentralizada,
    ClasificacionRegalias.MUNICIPIO: ProyectoMunicipio,
}


class EstadoFilter(DropdownFilter):
    """El estado, con la opcion de ver los que quedaron sin estado despues de una carga."""
    title = "Estado del proyecto"
    parameter_name = "estado"
    SIN_ESTADO = "sin"

    def lookups(self, request, model_admin):
        return [(str(e.pk), e.nombre) for e in EstadoProyectoRegalias.objects.all()] + [
            (self.SIN_ESTADO, "Sin estado")]

    def queryset(self, request, queryset):
        valor = self.value()
        if valor == self.SIN_ESTADO:
            return queryset.filter(estado__isnull=True)
        if valor:
            return queryset.filter(estado_id=valor)
        return queryset


class FechaDeCorteForm(forms.Form):
    fecha_corte = forms.DateField(label="Fecha de corte")


CALCULADOS = ("dias_aprobacion_a_apertura", "dias_apertura_a_firma", "dias_suscripcion_a_acta",
              "desempeno_cronograma", "desempeno_costo", "columna_apoyo", "brecha_fisico_financiera",
              "columna_apoyo_2", "cal_ejecucion", "ejecucion_revisar")
DE_LA_PROGRAMACION = ("fuentes", "valor_sgr", "valor_nacion", "valor_otros", "valor_otras_no_suifp",
                      "valor_total", "indicadores_mga")


class ProyectoRegaliasAdmin(ModelAdmin):
    """Lo comun a las tres hojas de la matriz. Cada proxy fija su clasificacion.

    Las tres muestran todos los campos: los de las tres hojas son editables en cualquiera.
    El historial se registra en save_related, cuando ya estan guardados los M2M.
    """
    compressed_fields = True
    list_fullwidth = True
    list_filter_submit = True
    list_filter_sheet = True
    list_per_page = 50
    search_fields = ("bpin", "nombre")
    ordering = ("bpin",)
    autocomplete_fields = ("sector", "dependencia", "entidad_ejecutora", "municipios", "responsables_cargue")
    actions_detail = ("comentarios", "historial")
    readonly_fields = DE_LA_PROGRAMACION + CALCULADOS
    columna_entidad = "dependencia"
    fieldsets = (
        ("Identificación", {"fields": (
            "clasificacion", "bpin", "nombre", "alcance", "sector", ("dependencia", "entidad_ejecutora"),
            "municipios", "responsables_cargue")}),
        ("Estado y contrato", {"fields": ("estado", ("estado_contrato", "tipo_contrato"))}),
        ("Valores", {"fields": (
            "fuentes", ("valor_sgr", "valor_nacion"), ("valor_otros", "valor_otras_no_suifp"),
            ("valor_total", "valor_pagos"), "indicadores_mga")}),
        ("Avance", {"fields": (("avance_fisico", "avance_financiero"), ("cpi", "spi"),
                               "indice_eficiencia_terminacion")}),
        ("Fechas", {"fields": (
            ("fecha_migracion_gesproy", "fecha_asignacion_recursos", "fecha_incorporacion_recursos"),
            ("fecha_aprobacion", "fecha_apertura_primer_proceso"),
            ("fecha_suscripcion_principal", "fecha_suscripcion_primer_contrato"),
            ("fecha_acta_inicio", "fecha_ultimo_pago"),
            ("horizonte", "fecha_finalizacion", "fecha_para_cierre"),
            "fecha_corte")}),
        ("Seguimiento", {"fields": ("informacion_solicitada", "informacion_recibida",
                                    ("fecha_recibo_informacion", "control_externalidades"))}),
        ("Calificaciones", {"fields": (("cal_desempeno_contratacion", "cal_calidad_informacion"),
                                       "cal_informacion_a_tiempo")}),
        ("Calculados", {"fields": (
            ("dias_aprobacion_a_apertura", "dias_apertura_a_firma", "dias_suscripcion_a_acta"),
            ("desempeno_cronograma", "desempeno_costo"), ("columna_apoyo", "brecha_fisico_financiera"),
            ("columna_apoyo_2", "cal_ejecucion"), "ejecucion_revisar")}),
    )

    def get_list_display(self, request):
        return ("bpin", "nombre_corto", self.columna_entidad, "estado", "avance_fisico", "avance_financiero",
                "fecha_corte", "cal_ejecucion")

    def get_list_filter(self, request):
        return (EstadoFilter, ("sector", RelatedDropdownFilter), (self.columna_entidad, RelatedDropdownFilter),
                "fecha_corte", "ejecucion_revisar")

    @display(description="Nombre del proyecto")
    def nombre_corto(self, obj):
        return obj.nombre if len(obj.nombre) <= 90 else obj.nombre[:90] + "…"

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .filter(clasificacion__codigo=self.model.CLASIFICACION)
                .select_related("estado", "sector", "dependencia", "entidad_ejecutora"))

    def get_changeform_initial_data(self, request):
        datos = super().get_changeform_initial_data(request)
        clasificacion = ClasificacionRegalias.objects.filter(codigo=self.model.CLASIFICACION).first()
        if clasificacion:
            datos.setdefault("clasificacion", clasificacion.pk)
        return datos

    def save_model(self, request, obj, form, change):
        request._regalias_antes = servicios.foto_de_la_base(obj.pk if change else None)
        calculos.aplicar(obj)
        super().save_model(request, obj, form, change)

    actions = ["recalcular", "asignar_fecha_corte"]

    def _guardar_varios(self, request, proyectos):
        for proyecto in proyectos:
            servicios.guardar_proyecto(proyecto, usuario=request.user,
                                       origen=CambioProyectoRegalias.Origen.ACCION_MASIVA)

    @action(description="Recalcular", permissions=["change"])
    def recalcular(self, request, queryset):
        proyectos = list(queryset)
        self._guardar_varios(request, proyectos)
        self.message_user(request, f"{len(proyectos)} proyectos recalculados.", messages.SUCCESS)

    @action(description="Asignar fecha de corte", permissions=["change"])
    def asignar_fecha_corte(self, request, queryset):
        """Pone la misma fecha de corte a los seleccionados y los recalcula. Pide la fecha antes."""
        form = FechaDeCorteForm(request.POST if "aplicar" in request.POST else None)
        if form.is_valid():
            fecha = form.cleaned_data["fecha_corte"]
            proyectos = list(queryset)
            for proyecto in proyectos:
                proyecto.fecha_corte = fecha
            self._guardar_varios(request, proyectos)
            self.message_user(request, f"Fecha de corte {fecha:%d/%m/%Y} asignada a {len(proyectos)} proyectos.",
                              messages.SUCCESS)
            return None
        return TemplateResponse(request, "regalias/asignar_fecha_corte.html", {
            **self.admin_site.each_context(request), "title": "Asignar fecha de corte", "opts": self.model._meta,
            "form": form, "proyectos": queryset, "casilla": helpers.ACTION_CHECKBOX_NAME})

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        antes = getattr(request, "_regalias_antes", None) or servicios.foto_de_la_base(None)
        servicios.registrar_cambios(form.instance, antes, servicios.foto(form.instance), usuario=request.user,
                                    origen=CambioProyectoRegalias.Origen.EDICION)

    def has_ver_comentarios_permission(self, request, object_id=None):
        return request.user.has_perm("regalias.view_comentarioproyectoregalias")

    @action(description="Comentarios", url_path="comentarios", icon="chat", permissions=["ver_comentarios"])
    def comentarios(self, request, object_id):
        """Los comentarios del proyecto, del mas reciente al mas antiguo, para agregar, editar y
        borrar. Misma logica que las observaciones de SIIFWEB: solo su autor y durante 5 dias."""
        if not self.has_ver_comentarios_permission(request):
            raise PermissionDenied
        proyecto = self.get_object(request, str(object_id))
        if proyecto is None:
            raise Http404("No hay proyecto con ese id en esta lista.")
        puede = {p: request.user.has_perm(f"regalias.{p}_comentarioproyectoregalias") for p in ("add", "change", "delete")}
        if request.method == "POST":
            accion = request.POST.get("accion", "")
            permiso = {"agregar": "add", "editar": "change", "borrar": "delete"}.get(accion)
            if permiso is None or not puede[permiso]:
                raise PermissionDenied
            texto = (request.POST.get("texto") or "").strip()
            if accion == "agregar":
                if texto:
                    ComentarioProyectoRegalias.objects.create(proyecto=proyecto, texto=texto, usuario=request.user)
                    self.message_user(request, "Comentario agregado.", messages.SUCCESS)
                else:
                    self.message_user(request, "Escriba el comentario antes de agregarlo.", messages.ERROR)
            else:
                comentario = proyecto.comentarios.filter(pk=request.POST.get("id") or 0).first()
                if comentario is None:
                    raise Http404("Ese comentario ya no existe.")
                if not comentario.editable:
                    self.message_user(request, f"Pasados {comentario.DIAS_EDITABLE} días un comentario ya no se "
                                               f"puede modificar ni borrar.", messages.ERROR)
                elif not comentario.es_de(request.user):
                    self.message_user(request, "Solo quien escribió el comentario lo puede modificar o borrar.",
                                      messages.ERROR)
                elif accion == "borrar":
                    comentario.delete()
                    self.message_user(request, "Comentario borrado.", messages.SUCCESS)
                elif texto:
                    comentario.texto = texto
                    comentario.save()
                    self.message_user(request, "Comentario guardado.", messages.SUCCESS)
                else:
                    self.message_user(request, "El comentario no puede quedar vacío.", messages.ERROR)
            return HttpResponseRedirect(request.path)
        comentarios = list(proyecto.comentarios.select_related("usuario"))
        for c in comentarios:
            c.mio = c.es_de(request.user)   # solo su autor ve editar y borrar
        return TemplateResponse(request, "regalias/comentarios_proyecto.html", {
            **self.admin_site.each_context(request), "title": f"Comentarios {proyecto.bpin}",
            "opts": self.model._meta, "proyecto": proyecto, "comentarios": comentarios, "puede": puede})

    def has_ver_historial_permission(self, request, object_id=None):
        return request.user.has_perm("regalias.view_cambioproyectoregalias")

    @action(description="Historial", url_path="historial", icon="history", permissions=["ver_historial"])
    def historial(self, request, object_id):
        return redirect(reverse("admin:regalias_cambioproyectoregalias_changelist")
                        + f"?proyecto__id__exact={object_id}")


@admin.register(ProyectoDepartamento)
class ProyectoDepartamentoAdmin(ProyectoRegaliasAdmin):
    # En el departamento la calificacion de informacion a tiempo sale de la fecha de recibo
    readonly_fields = ProyectoRegaliasAdmin.readonly_fields + ("cal_informacion_a_tiempo",)


@admin.register(ProyectoDescentralizada)
class ProyectoDescentralizadaAdmin(ProyectoRegaliasAdmin):
    pass


@admin.register(ProyectoMunicipio)
class ProyectoMunicipioAdmin(ProyectoRegaliasAdmin):
    columna_entidad = "entidad_ejecutora"


@admin.register(CambioProyectoRegalias)
class CambioProyectoRegaliasAdmin(SoloLectura):
    """El historial es un registro: nadie lo edita ni lo borra."""
    list_filter = (("origen", ChoicesDropdownFilter), ("usuario", RelatedDropdownFilter))
    list_filter_submit = True
    search_fields = ("proyecto__bpin", "campo", "valor_anterior", "valor_nuevo")
    list_select_related = ("proyecto__clasificacion", "usuario")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_list_display(self, request):
        # El BPIN enlaza al proyecto solo si el usuario puede abrir la hoja donde esta
        puede_ver = {codigo: self.admin_site._registry[proxy].has_view_permission(request)
                     for codigo, proxy in PROXY_DE.items() if self.admin_site.is_registered(proxy)}

        @display(description="Proyecto")
        def proyecto(obj):
            codigo = obj.proyecto.clasificacion.codigo
            if not puede_ver.get(codigo):
                return obj.proyecto.bpin
            url = reverse(f"admin:regalias_{PROXY_DE[codigo]._meta.model_name}_change", args=[obj.proyecto_id])
            return format_html('<a href="{}" class="text-primary-600">{}</a>', url, obj.proyecto.bpin)

        return ("fecha_creacion", proyecto, "campo", "valor_anterior", "valor_nuevo", "usuario", "origen", "carga")


class CargaRegaliasForm(forms.ModelForm):
    class Meta:
        model = CargaRegalias
        fields = ("tipo", "archivo", "fecha_descarga")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "archivo" in self.fields:
            self.fields["archivo"].required = True
        # Desde el sistema solo se cargan los tres reportes de GESPROY. La matriz se importa una
        # sola vez, con el comando cargar_regalias (decision del 27/11/2026)
        if "tipo" in self.fields:
            self.fields["tipo"].choices = [(valor, etiqueta) for valor, etiqueta in self.fields["tipo"].choices
                                           if valor != CargaRegalias.Tipo.MATRIZ]

    def clean(self):
        datos = super().clean()
        archivo, tipo = datos.get("archivo"), datos.get("tipo")
        if archivo and hasattr(archivo, "chunks") and tipo:
            digest = hash_archivo(archivo)
            previa = CargaRegalias.objects.filter(tipo=tipo, hash=digest).exclude(pk=self.instance.pk).first()
            if previa:
                raise forms.ValidationError(f"Este archivo ya está cargado como '{previa}'.")
            self.instance.hash = digest
        return datos


@admin.register(CargaRegalias)
class CargaRegaliasAdmin(ModelAdmin):
    """Los reportes de GESPROY. Al guardar se procesan (regalias.cargas.procesar).

    La lista muestra tambien la importacion de la matriz, que se hizo con el comando.
    """
    form = CargaRegaliasForm
    compressed_fields = True
    list_fullwidth = True
    list_display = ("__str__", "nombre_archivo", "estado_badge", "filas", "usuario", "fecha_creacion")
    list_filter = (("tipo", ChoicesDropdownFilter), ("estado", ChoicesDropdownFilter))
    list_filter_submit = True
    actions = ["volver_a_procesar"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("tipo", "archivo", "fecha_descarga")
        return ("tipo", "nombre_archivo", "fecha_descarga", "usuario", "estado", "filas", "mensaje", "hash",
                "fecha_creacion")

    def get_readonly_fields(self, request, obj=None):
        # Una carga procesada no se edita: para otro archivo se sube una carga nueva
        return self.get_fields(request, obj) if obj else ()

    @display(description="Estado", label={"Procesado": "success", "Con error": "danger", "Pendiente": "warning"})
    def estado_badge(self, obj):
        return obj.get_estado_display()

    def save_model(self, request, obj, form, change):
        if change:
            return
        obj.usuario = request.user
        obj.nombre_archivo = PurePath(form.cleaned_data["archivo"].name).name
        super().save_model(request, obj, form, change)
        cargas.procesar(obj, obj.archivo)
        nivel = messages.SUCCESS if obj.estado == CargaRegalias.Estado.PROCESADO else messages.ERROR
        self.message_user(request, obj.mensaje.splitlines()[0] if obj.mensaje else obj.get_estado_display(), nivel)

    @action(description="Volver a procesar", permissions=["change"])
    def volver_a_procesar(self, request, queryset):
        for carga in queryset:
            if not carga.archivo:
                self.message_user(request, f"{carga}: se cargó con el comando, sin archivo guardado.", messages.WARNING)
                continue
            cargas.procesar(carga, carga.archivo)
            self.message_user(request, f"{carga}: {carga.get_estado_display()}",
                              messages.SUCCESS if carga.estado == CargaRegalias.Estado.PROCESADO else messages.ERROR)


@admin.register(ContratoRegalias)
class ContratoRegaliasAdmin(ModelAdmin):
    """Un contrato que se crea, cambia o borra actualiza los datos de contrato de su proyecto."""
    compressed_fields = True
    list_fullwidth = True
    list_display = ("numero", "bpin", "tipo", "estado", "fecha_suscripcion", "valor_fuentes_sgr", "es_principal")
    list_filter = ("es_principal",)
    search_fields = ("numero", "proyecto__bpin", "nombre_contratista", "objeto")
    list_select_related = ("proyecto",)
    readonly_fields = ("es_principal",)
    fieldsets = (
        ("Contrato", {"fields": ("proyecto", ("numero", "fecha_suscripcion"), "numero_proceso", "modalidad", "tipo",
                                 "objeto", "estado", "es_principal")}),
        ("Valores", {"fields": (("valor_total", "valor_en_proyecto"), ("valor_fuentes_sgr", "pago_ejecutado"))}),
        ("Contratista", {"fields": (("nit_contratista", "nombre_contratista"),)}),
        ("Fechas y plazo", {"fields": (("fecha_acto_apertura", "fecha_inicial"), ("fecha_final", "fecha_final_real"),
                                       ("fecha_primer_pago", "fecha_ultimo_pago"), ("plazo", "unidad_plazo"),
                                       "ejecuta_varios_proyectos")}),
    )

    @display(description="BPIN", ordering="proyecto__bpin")
    def bpin(self, obj):
        return obj.proyecto.bpin

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "proyecto":
            kwargs["queryset"] = ProyectoRegalias.objects.order_by("bpin")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _actualizar(self, request, proyectos):
        for proyecto in proyectos:
            cargas.actualizar_desde_contratos(proyecto, usuario=request.user,
                                              origen=CambioProyectoRegalias.Origen.EDICION)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._actualizar(request, [obj.proyecto])

    def delete_model(self, request, obj):
        proyecto = obj.proyecto
        super().delete_model(request, obj)
        self._actualizar(request, [proyecto])

    def delete_queryset(self, request, queryset):
        proyectos = {c.proyecto_id: c.proyecto for c in queryset.select_related("proyecto")}
        super().delete_queryset(request, queryset)
        self._actualizar(request, proyectos.values())


@admin.register(ComentarioProyectoRegalias)
class ComentarioProyectoRegaliasAdmin(SoloLectura):
    """Todos los comentarios, solo para consultar. Se escriben, editan y borran en la pantalla
    Comentarios de cada proyecto, que aplica las reglas (su autor, 5 dias): aqui no se borra."""
    list_display = ("fecha_creacion", "bpin", "texto", "usuario")
    search_fields = ("proyecto__bpin", "texto")
    list_select_related = ("proyecto", "usuario")

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description="BPIN", ordering="proyecto__bpin")
    def bpin(self, obj):
        return obj.proyecto.bpin


@admin.register(ClasificacionRegalias)
class ClasificacionRegaliasAdmin(SoloLectura):
    list_display = ("nombre", "codigo")


@admin.register(EstadoProyectoRegalias)
class EstadoProyectoRegaliasAdmin(SoloLectura):
    list_display = ("orden", "nombre", "codigo")
    ordering = ("orden",)


@admin.register(EntidadEjecutora)
class EntidadEjecutoraAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_display = ("nombre", "nit")
    search_fields = ("nombre", "nit")


@admin.register(ResponsableGesproy)
class ResponsableGesproyAdmin(ModelAdmin):
    compressed_fields = True
    list_fullwidth = True
    list_display = ("nombre",)
    search_fields = ("nombre",)
