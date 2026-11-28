"""Base de proyectos de regalias.

Reemplaza la "Matriz de Seguimiento y Evaluacion" que hoy arma el aplicativo de Streamlit
de consolidacion. Cada proyecto es una fila por BPIN que se va actualizando: las cargas de
GESPROY escriben los campos que traen y el equipo diligencia el resto en el admin. No se
guarda una copia de la matriz por corte; lo que cambia queda en CambioProyectoRegalias.

Las tres hojas de la matriz (Departamento, Descentralizadas y Municipios) viven en la misma
tabla y se distinguen por la clasificacion. Ver PLAN_REGALIAS_CONSOLIDACION.md.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from siifweb.models import DependenciaResponsable, Fechas, Municipio, SectorMGA


class ClasificacionRegalias(Fechas):
    """Departamento, Descentralizada o Municipio. Los crea la migracion 0002."""
    DEPARTAMENTO = "departamento"
    DESCENTRALIZADA = "descentralizada"
    MUNICIPIO = "municipio"

    codigo = models.CharField(max_length=20, unique=True, verbose_name="Código")
    nombre = models.CharField(max_length=60, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Clasificación"
        verbose_name_plural = "Clasificaciones"
        ordering = ("pk",)

    def __str__(self):
        return self.nombre


class EstadoProyectoRegalias(Fechas):
    """Los estados de GESPROY. Los crean las migraciones 0002 y 0005.

    Los calculos comparan por `codigo`, no por el nombre: el nombre llega de los reportes
    con variantes de espacios y mayusculas.
    """
    SIN_CONTRATAR = "sin_contratar"
    # Aparecio en los reportes de octubre de 2026 (4 proyectos)
    EN_PROCESO_CONTRATACION = "en_proceso_contratacion"
    CONTRATADO_SIN_ACTA = "contratado_sin_acta"
    CONTRATADO_EN_EJECUCION = "contratado_en_ejecucion"
    TERMINADO = "terminado"
    PARA_CIERRE = "para_cierre"
    CERRADO = "cerrado"
    DESAPROBADO = "desaprobado"

    codigo = models.CharField(max_length=30, unique=True, verbose_name="Código")
    nombre = models.CharField(max_length=60, unique=True, verbose_name="Nombre")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")

    class Meta:
        verbose_name = "Estado del proyecto"
        verbose_name_plural = "Estados del proyecto"
        ordering = ("orden",)

    def __str__(self):
        return self.nombre


class EntidadEjecutora(Fechas):
    """Quien ejecuta un proyecto de municipios (un municipio, una universidad...).

    Las descentralizadas no van aqui: ya estan en DependenciaResponsable.
    """
    nombre = models.CharField(max_length=255, unique=True, verbose_name="Nombre")
    nit = models.CharField(max_length=30, blank=True, verbose_name="NIT")

    class Meta:
        verbose_name = "Entidad ejecutora"
        verbose_name_plural = "Entidades ejecutoras"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


class ResponsableGesproy(Fechas):
    """Quien carga la informacion del proyecto en GESPROY."""
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Nombre")

    class Meta:
        verbose_name = "Responsable del cargue en GESPROY"
        verbose_name_plural = "Responsables del cargue en GESPROY"
        ordering = ("nombre",)

    def __str__(self):
        return self.nombre


def _fecha(nombre):
    return models.DateField(null=True, blank=True, verbose_name=nombre)


def _decimal(nombre, digitos, editable=True):
    """Avances, indices y calificaciones: tres decimales."""
    return models.DecimalField(max_digits=digitos, decimal_places=3, null=True, blank=True,
                               editable=editable, verbose_name=nombre)


def _valor(nombre, editable=True):
    """Pesos: 15 enteros y 5 decimales, como la programacion financiera de SIIFWEB."""
    return models.DecimalField(max_digits=20, decimal_places=5, null=True, blank=True,
                               editable=editable, verbose_name=nombre)


class ProyectoRegalias(Fechas):
    """Un proyecto de regalias, sea del departamento, de una descentralizada o de un municipio.

    Los campos llevan como nombre visible la columna de la matriz. Los calculados
    (editable=False) los pone al dia regalias.calculos al guardar; los valores y las fuentes,
    la programacion financiera.
    """
    clasificacion = models.ForeignKey(ClasificacionRegalias, on_delete=models.PROTECT,
                                      related_name="proyectos", verbose_name="Clasificación")
    bpin = models.CharField(max_length=25, unique=True, verbose_name="BPIN")
    nombre = models.TextField(verbose_name="Nombre del proyecto")
    alcance = models.TextField(blank=True, verbose_name="Alcance del proyecto")
    sector = models.ForeignKey(SectorMGA, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="proyectos_regalias", verbose_name="Sector")
    # Departamento: la secretaria; descentralizadas: la entidad. Municipios usa entidad_ejecutora
    dependencia = models.ForeignKey(DependenciaResponsable, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="proyectos_regalias", verbose_name="Entidad o secretaría")
    entidad_ejecutora = models.ForeignKey(EntidadEjecutora, on_delete=models.PROTECT, null=True, blank=True,
                                          related_name="proyectos", verbose_name="Entidad ejecutora")
    municipios = models.ManyToManyField(Municipio, blank=True, related_name="proyectos_regalias",
                                        verbose_name="Municipios")
    responsables_cargue = models.ManyToManyField(ResponsableGesproy, blank=True, related_name="proyectos",
                                                 verbose_name="Responsables del cargue en GESPROY")

    # Estado y contrato. El estado puede quedar vacio despues de una carga (el reporte puede
    # traer proyectos sin estado), pero el formulario lo exige: blank=False con null=True
    estado = models.ForeignKey(EstadoProyectoRegalias, on_delete=models.PROTECT, null=True, blank=False,
                               related_name="proyectos", verbose_name="Estado del proyecto")
    estado_contrato = models.CharField(max_length=100, blank=True, verbose_name="Estado del contrato")
    tipo_contrato = models.CharField(max_length=150, blank=True, verbose_name="Tipo de contrato")

    # Valores: salen de la programacion financiera (fuentes por clasificacion). Pagos, de CG-proy
    fuentes = models.TextField(blank=True, editable=False, verbose_name="Fuente de financiación")
    valor_sgr = _valor("Valor SGR", editable=False)
    valor_nacion = _valor("Valor Nación", editable=False)
    valor_otros = _valor("Valor otros", editable=False)
    valor_otras_no_suifp = _valor("Valor otras fuentes no SUIFP", editable=False)
    valor_total = _valor("Valor total del proyecto", editable=False)
    valor_pagos = _valor("Valor pagos")
    indicadores_mga = models.TextField(blank=True, editable=False, verbose_name="Indicador de producto MGA")

    # Avance e indices
    avance_fisico = _decimal("Avance físico", 6)
    avance_financiero = _decimal("Avance financiero", 6)
    cpi = _decimal("CPI", 5)
    spi = _decimal("SPI", 5)
    indice_eficiencia_terminacion = _decimal("Índice de eficiencia en la terminación", 6)

    # Fechas
    fecha_migracion_gesproy = _fecha("Fecha de migración a GESPROY")
    fecha_asignacion_recursos = _fecha("Fecha de asignación de recursos")
    fecha_incorporacion_recursos = _fecha("Fecha de incorporación de recursos")
    fecha_aprobacion = _fecha("Fecha de aprobación del proyecto")
    fecha_apertura_primer_proceso = _fecha("Fecha de apertura del primer proceso")
    fecha_suscripcion_principal = _fecha("Fecha de suscripción del contrato principal")
    fecha_suscripcion_primer_contrato = _fecha("Fecha de suscripción del primer contrato")
    fecha_acta_inicio = _fecha("Fecha del acta de inicio")
    fecha_ultimo_pago = _fecha("Última fecha de pago")
    horizonte = _fecha("Horizonte del proyecto")
    fecha_finalizacion = _fecha("Fecha de finalización")
    fecha_para_cierre = _fecha("Fecha en la que pasó a estado para cierre")
    fecha_corte = _fecha("Fecha de corte GESPROY")

    # Seguimiento
    informacion_solicitada = models.TextField(blank=True, verbose_name="Información solicitada")
    informacion_recibida = models.TextField(blank=True, verbose_name="Información recibida")
    fecha_recibo_informacion = _fecha("Fecha de recibo de información")
    control_externalidades = models.PositiveSmallIntegerField(null=True, blank=True,
                                                              verbose_name="Control de externalidades")

    # Calificaciones (0 a 100). La de informacion a tiempo se calcula en Departamento y se
    # digita en las otras clasificaciones
    cal_desempeno_contratacion = _decimal("Calificación desempeño en la contratación", 6)
    cal_calidad_informacion = _decimal("Calificación calidad de la información", 6)
    cal_informacion_a_tiempo = _decimal("Calificación información a tiempo", 6)

    # Calculados (regalias.calculos)
    dias_aprobacion_a_apertura = models.IntegerField(
        null=True, blank=True, editable=False, verbose_name="Días desde la aprobación hasta apertura del primer proceso")
    dias_apertura_a_firma = models.IntegerField(
        null=True, blank=True, editable=False, verbose_name="Días desde la apertura hasta la firma del primer contrato")
    dias_suscripcion_a_acta = models.IntegerField(
        null=True, blank=True, editable=False, verbose_name="Días desde la suscripción hasta el acta de inicio")
    desempeno_cronograma = _decimal("Desempeño en el cronograma", 6, editable=False)
    desempeno_costo = _decimal("Desempeño en el costo", 6, editable=False)
    columna_apoyo = _decimal("Columna apoyo", 6, editable=False)
    brecha_fisico_financiera = _decimal("Brecha físico - financiera", 6, editable=False)
    columna_apoyo_2 = _decimal("Columna apoyo 2", 6, editable=False)
    cal_ejecucion = _decimal("Calificación ejecución del proyecto", 6, editable=False)
    # El "Revisar" que hoy muestra Excel cuando la calificacion de ejecucion no se puede calcular
    ejecucion_revisar = models.BooleanField(default=False, editable=False, verbose_name="Revisar ejecución")

    class Meta:
        verbose_name = "Proyecto de regalías"
        verbose_name_plural = "Proyectos de regalías"
        ordering = ("bpin",)

    def __str__(self):
        return f"{self.bpin} - {self.nombre[:80]}"

    @property
    def codigo_clasificacion(self):
        return self.clasificacion.codigo if self.clasificacion_id else None


# Una entrada del menu por hoja de la matriz. Son proxies: la misma tabla, con su propio
# listado, sus permisos y la clasificacion fija al crear
class ProyectoDepartamento(ProyectoRegalias):
    CLASIFICACION = ClasificacionRegalias.DEPARTAMENTO

    class Meta:
        proxy = True
        verbose_name = "Proyecto del departamento"
        verbose_name_plural = "Proyectos del departamento"


class ProyectoDescentralizada(ProyectoRegalias):
    CLASIFICACION = ClasificacionRegalias.DESCENTRALIZADA

    class Meta:
        proxy = True
        verbose_name = "Proyecto de descentralizada"
        verbose_name_plural = "Proyectos de descentralizadas"


class ProyectoMunicipio(ProyectoRegalias):
    CLASIFICACION = ClasificacionRegalias.MUNICIPIO

    class Meta:
        proxy = True
        verbose_name = "Proyecto de municipio"
        verbose_name_plural = "Proyectos de municipios"


class CargaRegalias(Fechas):
    """Un archivo cargado: la matriz (importacion inicial) o uno de los reportes de GESPROY.

    Se procesa al guardar (regalias.cargas.procesar). Desde el admin el archivo queda en el
    almacenamiento; el comando cargar_regalias procesa un archivo local sin subirlo, por eso
    `archivo` puede quedar vacio y se guarda el nombre original.
    """
    class Tipo(models.TextChoices):
        MATRIZ = "matriz", "Matriz de seguimiento (importación)"
        PROYECTOS = "proyectos", "CG-proy (proyectos)"
        CONTRATOS = "contratos", "CG-cttos (contratos)"
        CARGUE = "cargue", "CG-carga (cargue de información)"

    class Estado(models.TextChoices):
        PENDIENTE = "P", "Pendiente"
        PROCESADO = "OK", "Procesado"
        ERROR = "E", "Con error"

    tipo = models.CharField(max_length=20, choices=Tipo.choices, verbose_name="Tipo")
    archivo = models.FileField(upload_to="regalias/", blank=True, verbose_name="Archivo")
    nombre_archivo = models.CharField(max_length=255, blank=True, verbose_name="Nombre del archivo")
    fecha_descarga = models.DateField(default=timezone.localdate, verbose_name="Fecha de descarga")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="cargas_regalias", verbose_name="Usuario")
    hash = models.CharField(max_length=64, blank=True, verbose_name="Hash del archivo")
    filas = models.IntegerField(default=0, verbose_name="Filas")
    estado = models.CharField(max_length=2, choices=Estado.choices, default=Estado.PENDIENTE, verbose_name="Estado")
    mensaje = models.TextField(blank=True, verbose_name="Mensaje")

    class Meta:
        verbose_name = "Carga de regalías"
        verbose_name_plural = "Cargas de regalías"
        ordering = ("-fecha_creacion", "-pk")

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.fecha_descarga:%d/%m/%Y}"


def _valor_contrato(nombre):
    return models.DecimalField(max_digits=20, decimal_places=5, null=True, blank=True, verbose_name=nombre)


class ContratoRegalias(Fechas):
    """Un contrato de un proyecto, como lo trae CG-cttos.

    No tiene llave propia: los contratos de cada BPIN que viene en CG-cttos se reemplazan por
    las filas del reporte (regalias.cargas.cargar_contratos). Probado con los reportes de mayo
    a noviembre de 2026: GESPROY cambia la fecha de suscripcion de algunos contratos de un mes
    a otro, y un mismo numero puede ser dos contratos del mismo BPIN con la misma fecha
    (CONV-RE-SDED-028-2022). Cualquier llave dejaba contratos sobrantes o perdia uno.
    Los BPIN que no vienen en el reporte (descentralizadas y municipios) conservan los suyos.
    """
    proyecto = models.ForeignKey(ProyectoRegalias, on_delete=models.CASCADE, related_name="contratos",
                                 verbose_name="Proyecto")
    numero = models.CharField(max_length=100, verbose_name="Número del contrato")
    numero_proceso = models.CharField(max_length=100, blank=True, verbose_name="Número del proceso precontractual")
    modalidad = models.CharField(max_length=150, blank=True, verbose_name="Modalidad de contratación")
    tipo = models.CharField(max_length=150, blank=True, verbose_name="Tipo de contrato")
    objeto = models.TextField(blank=True, verbose_name="Objeto")
    estado = models.CharField(max_length=100, blank=True, verbose_name="Estado del contrato")
    valor_total = _valor_contrato("Valor total del contrato")
    valor_en_proyecto = _valor_contrato("Valor del contrato en el proyecto")
    valor_fuentes_sgr = _valor_contrato("Valor total fuentes SGR")
    pago_ejecutado = _valor_contrato("Pago ejecutado")
    nit_contratista = models.CharField(max_length=30, blank=True, verbose_name="NIT del contratista")
    nombre_contratista = models.CharField(max_length=255, blank=True, verbose_name="Contratista")
    fecha_acto_apertura = models.DateField(null=True, blank=True, verbose_name="Fecha del acto de apertura")
    fecha_suscripcion = models.DateField(null=True, blank=True, verbose_name="Fecha de suscripción")
    fecha_inicial = models.DateField(null=True, blank=True, verbose_name="Fecha inicial")
    fecha_final = models.DateField(null=True, blank=True, verbose_name="Fecha final")
    fecha_final_real = models.DateField(null=True, blank=True, verbose_name="Fecha final real")
    fecha_primer_pago = models.DateField(null=True, blank=True, verbose_name="Primera fecha de pago")
    fecha_ultimo_pago = models.DateField(null=True, blank=True, verbose_name="Última fecha de pago")
    # Con decimales: GESPROY trae plazos como 8,27 meses
    plazo = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Plazo contractual")
    unidad_plazo = models.CharField(max_length=30, blank=True, verbose_name="Unidad del plazo")
    ejecuta_varios_proyectos = models.BooleanField(default=False, verbose_name="Ejecuta varios proyectos")
    es_principal = models.BooleanField(default=False, editable=False, verbose_name="Contrato principal")

    class Meta:
        verbose_name = "Contrato de regalías"
        verbose_name_plural = "Contratos de regalías"
        ordering = ("proyecto__bpin", "fecha_suscripcion", "numero")

    def __str__(self):
        return f"{self.numero} ({self.proyecto.bpin})"


class ComentarioProyectoRegalias(Fechas):
    """Lo que el equipo anota sobre un proyecto, con la logica de ObservacionProyectoSiifweb.

    Solo quien lo escribio lo modifica o lo borra, y solo durante DIAS_EDITABLE dias. Los que
    deja la importacion de la matriz no tienen autor y quedan como registro.
    """
    DIAS_EDITABLE = 5
    proyecto = models.ForeignKey(ProyectoRegalias, on_delete=models.CASCADE, related_name="comentarios",
                                 verbose_name="Proyecto")
    texto = models.TextField(verbose_name="Comentario")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="comentarios_regalias", verbose_name="Usuario")

    class Meta:
        verbose_name = "Comentario del proyecto"
        verbose_name_plural = "Comentarios de los proyectos"
        ordering = ("-fecha_creacion", "-pk")

    def __str__(self):
        return f"{self.proyecto.bpin}: {self.texto[:60]}"

    @property
    def editable_hasta(self):
        return self.fecha_creacion + timedelta(days=self.DIAS_EDITABLE) if self.fecha_creacion else None

    @property
    def editable(self):
        return self.editable_hasta is None or timezone.now() <= self.editable_hasta

    def es_de(self, usuario):
        """Lo escribio ese usuario. Los que no tienen autor nadie los modifica."""
        return self.usuario_id is not None and self.usuario_id == getattr(usuario, "pk", None)


class CambioProyectoRegalias(Fechas):
    """Cada cambio de un campo del proyecto: quien, cuando, de donde y de que a que.

    Lo escribe regalias.servicios para todo lo que guarda un proyecto: el admin, las cargas,
    la importacion, las acciones masivas y la programacion. La fecha es fecha_creacion.
    """
    class Origen(models.TextChoices):
        EDICION = "edicion", "Edición"
        CARGA = "carga", "Carga"
        IMPORTACION = "importacion", "Importación"
        PROGRAMACION = "programacion", "Programación"
        ACCION_MASIVA = "accion_masiva", "Acción masiva"

    proyecto = models.ForeignKey(ProyectoRegalias, on_delete=models.CASCADE, related_name="cambios",
                                 verbose_name="Proyecto")
    campo = models.CharField(max_length=100, verbose_name="Campo")
    valor_anterior = models.TextField(blank=True, verbose_name="Valor anterior")
    valor_nuevo = models.TextField(blank=True, verbose_name="Valor nuevo")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="cambios_regalias", verbose_name="Usuario")
    origen = models.CharField(max_length=20, choices=Origen.choices, verbose_name="Origen")
    carga = models.ForeignKey(CargaRegalias, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="cambios", verbose_name="Carga")

    class Meta:
        verbose_name = "Cambio de un proyecto"
        verbose_name_plural = "Historial de cambios"
        ordering = ("-fecha_creacion", "-pk")

    def __str__(self):
        return f"{self.proyecto.bpin} · {self.campo}"
