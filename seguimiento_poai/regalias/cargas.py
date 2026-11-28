"""Importacion de la matriz y cargas de los reportes de GESPROY.

La regla de los proyectos: se actualizan los campos de los BPIN que aparecen en el archivo y
solo con los valores que vienen llenos. Lo que no viene, o viene vacio, se deja como esta.
Cada cambio de un proyecto queda en el historial con la carga y su usuario (servicios).

- Matriz: crea o actualiza los proyectos de las tres hojas. Fuentes, valores e indicadores
  no se migran (salen de la programacion): quedan en un comentario del proyecto.
- CG-proy: crea los BPIN nuevos (en Departamento) y actualiza nombre, sector, estado y pagos.
- CG-cttos: los contratos de cada BPIN que viene se reemplazan por los del reporte (los
  contratos no tienen una llave estable en GESPROY, ver ContratoRegalias). Despues, por cada
  BPIN, se elige el contrato principal y sus datos pasan al proyecto con la regla de arriba.
- CG-carga: actualiza avances y fecha de aprobacion de los BPIN que ya existen.

Ver docs/PLAN_REGALIAS_CONSOLIDACION.md, secciones 4 a 6.
"""
import logging
import re
from decimal import ROUND_HALF_UP, Decimal

from django.db import models, transaction

from siifweb.models import DependenciaResponsable, Municipio, SectorMGA

from . import lectura, servicios
from .lectura import normalizar
from .models import (CambioProyectoRegalias, CargaRegalias, ClasificacionRegalias, ComentarioProyectoRegalias,
                     ContratoRegalias, EntidadEjecutora, EstadoProyectoRegalias, ProyectoRegalias,
                     ResponsableGesproy)

log = logging.getLogger(__name__)
CARGA = CambioProyectoRegalias.Origen.CARGA
IMPORTACION = CambioProyectoRegalias.Origen.IMPORTACION

# La matriz nombra la secretaria corta ("Salud") y las descentralizadas con su razon social
EQUIVALENCIAS_DEPENDENCIA = {
    "PLANEACION": "Secretaría de Planeación",
    "SALUD": "Secretaría de Salud",
    "DESARROLLO ECONOMICO": "Secretaría de Desarrollo Económico y Medio Ambiente",
    "EDUCACION": "Secretaría de Educación",
    "INFRAESTRUCTURA": "Secretaría de Infraestructura",
    "ENERGIA": "Secretaría de Energías",
    "OFICINA DE INNOVACION": "Oficina de Innovación, Tecnología y Competitividad",
    "FONDO MIXTO DE PROMOCION DE LA CULTURA Y LAS ARTES DE SUCRE": "Fondo Mixto de Cultura",
    "INSTITUTO DEPARTAMENTAL DE DEPORTES Y RECREACION DE SUCRE INDERSUCRE":
        "Instituto Departamental de Deportes y Recreación",
    "EMPRESA AGUAS DE SUCRE S.A. E.S.P.": "Plan Departamental de Aguas",
}

# Nombres cortos o viejos de los municipios de Sucre
ALIAS_MUNICIPIO = {
    "TOLUVIEJO": "SAN JOSE DE TOLUVIEJO",
    "SINCE": "SAN LUIS DE SINCE",
    "BETULIA": "SAN JUAN DE BETULIA",
    "TOLU": "SANTIAGO DE TOLU",
    "SAN ANTONIO DE PALMITO": "PALMITO",
    "SAN ANTONIO DE PALMITOS": "PALMITO",
}

# Prioridad para elegir el contrato principal (la de la consolidacion de Streamlit)
TIPOS_PRIORITARIOS = {"OBRA PUBLICA", "CONSULTORIA", "CONVENIOS DE COOPERACION", "INTERADMINISTRATIVOS"}
TIPOS_SECUNDARIOS = {"SUMINISTRO", "CONTRATOS O CONVENIOS CON ENTIDADES SIN ANIMO DE LUCRO"}


class Resumen:
    """Lo que paso en una carga, para el mensaje."""

    def __init__(self, titulo):
        self.titulo = titulo
        self.filas = 0
        self.conteos = {}
        self.listas = {}

    def contar(self, clave, n=1):
        self.conteos[clave] = self.conteos.get(clave, 0) + n

    def anotar(self, lista, valor):
        self.listas.setdefault(lista, [])
        if valor not in self.listas[lista]:
            self.listas[lista].append(valor)

    def texto(self):
        partes = [f"{self.titulo} · {self.filas} filas"] + [f"{n} {clave}" for clave, n in self.conteos.items() if n]
        lineas = [" · ".join(partes)]
        for lista, valores in self.listas.items():
            muestra = ", ".join(str(v) for v in valores[:40])
            resto = f" y {len(valores) - 40} más" if len(valores) > 40 else ""
            lineas.append(f"{lista} ({len(valores)}): {muestra}{resto}")
        return "\n".join(lineas)


class Catalogos:
    """Busca por nombre normalizado los catalogos que asignan las cargas, con cache."""

    def __init__(self, resumen):
        self.resumen = resumen
        self.estados = {normalizar(e.nombre): e for e in EstadoProyectoRegalias.objects.all()}
        self.sectores = {normalizar(str(s)): s for s in SectorMGA.objects.all()}
        self.dependencias = {normalizar(d.nombre): d for d in DependenciaResponsable.objects.all()}
        self.municipios = {normalizar(m.nombre): m for m in Municipio.objects.all()}
        self.clasificaciones = {c.codigo: c for c in ClasificacionRegalias.objects.all()}

    def estado(self, valor, bpin):
        clave = normalizar(valor)
        if not clave:
            return None
        encontrado = self.estados.get(clave)
        if encontrado is None:
            self.resumen.anotar("Estados no reconocidos", f"{valor} ({bpin})")
        return encontrado

    def sector(self, valor, bpin):
        clave = normalizar(valor)
        if not clave:
            return None
        encontrado = self.sectores.get(clave)
        if encontrado is None:
            self.resumen.anotar("Sectores no reconocidos", f"{valor} ({bpin})")
        return encontrado

    def dependencia(self, valor, bpin):
        clave = normalizar(valor)
        if not clave:
            return None
        destino = normalizar(EQUIVALENCIAS_DEPENDENCIA.get(clave, valor))
        encontrada = self.dependencias.get(destino)
        if encontrada is None:
            self.resumen.anotar("Dependencias no reconocidas", f"{valor} ({bpin})")
        return encontrada

    def entidad_ejecutora(self, valor):
        nombre = " ".join(lectura.texto(valor).split())
        if not nombre:
            return None
        entidad, creada = EntidadEjecutora.objects.get_or_create(nombre=nombre[:255])
        if creada:
            self.resumen.contar("entidades ejecutoras creadas")
        return entidad

    def responsables(self, valor):
        nombres = [" ".join(p.split()) for p in lectura.texto(valor).splitlines() if p.strip()]
        personas = []
        for nombre in nombres:
            persona, creada = ResponsableGesproy.objects.get_or_create(nombre=nombre[:150])
            if creada:
                self.resumen.contar("responsables creados")
            personas.append(persona)
        return personas

    def municipios_de(self, valor, bpin):
        """Los municipios de la celda y los nombres que no estan en el catalogo de SIIFWEB.

        Los saltos de linea cortan nombres a la mitad ("SAN JUAN DE\\nBETULIA"): se unen. Se
        separa por coma y por " y " ("Morroa y Sincé"); "D.C." es el resto de "Bogotá, D.C.".
        """
        texto = lectura.texto(valor).replace("\n", " ")
        encontrados, sin_catalogo = [], []
        for parte in re.split(r",|\s+y\s+", texto, flags=re.IGNORECASE):
            nombre = parte.strip().rstrip(".").strip()
            clave = normalizar(nombre)
            if not clave or clave in ("D.C", "DC"):
                continue
            municipio = self.municipios.get(ALIAS_MUNICIPIO.get(clave, clave))
            if municipio is None:
                sin_catalogo.append(nombre)
                self.resumen.anotar("Municipios que no están en el catálogo", nombre)
            elif municipio not in encontrados:
                encontrados.append(municipio)
        return encontrados, sin_catalogo


def asignar(obj, campo, valor, resumen, bpin):
    """Escribe el valor solo si viene lleno y cabe en el campo. Devuelve si lo escribio.

    Los decimales se redondean a los del campo antes de escribirlos: asi lo que queda en
    memoria es lo que guarda la base, y repetir una carga no registra cambios falsos.
    """
    if valor is None or valor == "":
        return False
    definicion = obj._meta.get_field(campo)
    if isinstance(valor, Decimal):
        valor = valor.quantize(Decimal(1).scaleb(-definicion.decimal_places), rounding=ROUND_HALF_UP)
        if not lectura.cabe(valor, definicion):
            resumen.anotar("Valores que no caben en el campo", f"{definicion.verbose_name} {valor} ({bpin})")
            return False
    if isinstance(valor, int) and not isinstance(valor, bool) and valor < 0 and isinstance(
            definicion, (models.PositiveIntegerField, models.PositiveSmallIntegerField)):
        resumen.anotar("Valores negativos donde no se admiten", f"{definicion.verbose_name} {valor} ({bpin})")
        return False
    if isinstance(valor, str) and getattr(definicion, "max_length", None):
        valor = valor[:definicion.max_length]
    setattr(obj, campo, valor)
    return True


def _linea(valor):
    """Texto de una sola linea, con espacios simples (estados, tipos, nombres)."""
    return " ".join(lectura.texto(valor).split())


def _leer(convertir, valor, columna, bpin, resumen):
    """Convierte el valor de una celda; lo que no se puede leer se avisa y no se escribe."""
    try:
        return convertir(valor)
    except ValueError:
        resumen.anotar("Valores que no se pudieron leer", f"{columna} = {valor} ({bpin})")
        return None


def _pesos(valor):
    entero, _, decimales = f"{valor:,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{decimales}"


def _comentar(proyecto, texto, usuario=None):
    """Agrega el comentario si el proyecto no lo tiene ya: la importacion se puede repetir."""
    texto = texto.strip()
    if texto and not proyecto.comentarios.filter(texto=texto).exists():
        ComentarioProyectoRegalias.objects.create(proyecto=proyecto, texto=texto, usuario=usuario)
        return True
    return False


# ---------- importacion de la matriz ----------

FECHAS_MATRIZ = {
    "FECHA DE MIGRACIÓN A GESPROY": "fecha_migracion_gesproy",
    "FECHA DE ASIGNACIÓN DE RECURSOS": "fecha_asignacion_recursos",
    "FECHA DE INCORPORACIÓN DE RECURSOS": "fecha_incorporacion_recursos",
    "FECHA APROBACIÓN PROYECTO": "fecha_aprobacion",
    "FECHA DE APERTURA DEL PRIMER PROCESO": "fecha_apertura_primer_proceso",
    "FECHA DE SUSCRIPCIÓN DEL CONTRATO PRINCIPAL": "fecha_suscripcion_principal",
    "FECHA DE SUSCRIPCIÓN DEL PRIMER CONTRATO": "fecha_suscripcion_primer_contrato",
    "FECHA ACTA INICIO": "fecha_acta_inicio",
    "ULTIMA FECHA PAGO": "fecha_ultimo_pago",
    "HORIZONTE DEL PROYECTO": "horizonte",
    "FECHA DE FINALIZACIÓN": "fecha_finalizacion",
    "FECHA EN LA QUE PASO A ESTADO PARA CIERRE": "fecha_para_cierre",
    "FECHA DE CORTE GESPROY": "fecha_corte",
    "FECHA DE RECIBO DE INFORMACIÓN": "fecha_recibo_informacion",
}
DECIMALES_MATRIZ = {
    "AVANCE FISICO": "avance_fisico",
    "AVANCE FÍSICO": "avance_fisico",
    "AVANCE FINANCIERO": "avance_financiero",
    "CPI": "cpi",
    "SPI": "spi",
    "ÍNDICE DE EFICIENCIA EN LA TERMINACIÓN": "indice_eficiencia_terminacion",
    "CALIFICACIÓN DESEMPEÑO EN LA CONTRATACIÓN": "cal_desempeno_contratacion",
    "CALIFICACIÓN CALIDAD INFORMACIÓN": "cal_calidad_informacion",
    "VALOR PAGOS": "valor_pagos",
}
TEXTOS_MATRIZ = {
    "NOMBRE PROYECTO": "nombre",
    "NOMBRE DEL PROYECTO": "nombre",
    "ALCANCE DEL PROYECTO": "alcance",
    "ALCANCE": "alcance",
    "ESTADO CONTRATO": "estado_contrato",
    "TIPO CONTRATO": "tipo_contrato",
    "INFORMACIÓN SOLICITADA": "informacion_solicitada",
    "INFORMACIÓN RECIBIDA": "informacion_recibida",
}
# Lo que la matriz trae y ya no se migra: queda en el comentario de "datos de la matriz anterior"
PARA_EL_COMENTARIO = (
    ("FUENTE DE FINANCIACIÓN", "Fuente"), ("FUENTE", "Fuente"),
    ("INDICADOR DE PRODUCTO MGA", "Indicador de producto MGA"),
    ("VALOR SGR", "Valor SGR"), ("VALOR NACIÓN", "Valor Nación"), ("VALOR OTROS", "Valor otros"),
    ("VALOR OTRAS FUENTES NO SUIFP", "Valor otras fuentes no SUIFP"),
    ("VALOR TOTAL PROYECTO", "Valor total"), ("VALOR TOTAL", "Valor total"),
)


def _datos_anteriores(fila, municipios_sin_catalogo):
    partes = []
    for columna, etiqueta in PARA_EL_COMENTARIO:
        valor = fila.get(columna)
        if valor in (None, ""):
            continue
        if columna.startswith("VALOR"):
            try:
                numero = lectura.numero(valor)
            except ValueError:
                numero = None
            valor = _pesos(numero) if numero is not None else lectura.texto(valor)
        partes.append(f"{etiqueta}: {' '.join(lectura.texto(valor).split())}")
    if municipios_sin_catalogo:
        partes.append("Municipios: " + lectura.texto(fila.get("MUNICIPIOS")).replace("\n", " "))
    return ("Datos de la matriz anterior. " + ". ".join(partes) + ".") if partes else ""


def _importar_fila(fila, codigo, cat, existentes, resumen, carga):
    bpin = lectura.texto(fila.get("BPIN"))
    if not bpin:
        resumen.contar("filas sin BPIN")
        return
    proyecto = existentes.get(bpin)
    nuevo = proyecto is None
    if nuevo:
        nombre = lectura.texto(fila.get("NOMBRE PROYECTO") or fila.get("NOMBRE DEL PROYECTO"))
        if not nombre:
            resumen.anotar("Proyectos nuevos sin nombre (no se crearon)", bpin)
            return
        proyecto = ProyectoRegalias(bpin=bpin)
    proyecto.clasificacion = cat.clasificaciones[codigo]

    for columna, campo in TEXTOS_MATRIZ.items():
        if columna in fila:
            una_linea = campo in ("estado_contrato", "tipo_contrato")
            asignar(proyecto, campo, _linea(fila[columna]) if una_linea else lectura.texto(fila[columna]),
                    resumen, bpin)
    for columna, campo in FECHAS_MATRIZ.items():
        if columna in fila:
            asignar(proyecto, campo, lectura.fecha(fila[columna]), resumen, bpin)
    for columna, campo in DECIMALES_MATRIZ.items():
        if columna in fila:
            asignar(proyecto, campo, _leer(lectura.numero, fila[columna], columna, bpin, resumen), resumen, bpin)
    if "CONTROL EXTERNALIDADES" in fila:
        asignar(proyecto, "control_externalidades",
                _leer(lectura.entero, fila["CONTROL EXTERNALIDADES"], "CONTROL EXTERNALIDADES", bpin, resumen),
                resumen, bpin)
    # En el departamento la calificacion de informacion a tiempo se calcula; en las otras se digita
    if codigo != ClasificacionRegalias.DEPARTAMENTO and "CALIFICACIÓN INFORMACIÓN A TIEMPO" in fila:
        asignar(proyecto, "cal_informacion_a_tiempo",
                _leer(lectura.numero, fila["CALIFICACIÓN INFORMACIÓN A TIEMPO"], "CALIFICACIÓN INFORMACIÓN A TIEMPO",
                      bpin, resumen), resumen, bpin)

    asignar(proyecto, "estado", cat.estado(fila.get("ESTADO PROYECTO"), bpin), resumen, bpin)
    asignar(proyecto, "sector", cat.sector(fila.get("SECTOR"), bpin), resumen, bpin)
    if codigo == ClasificacionRegalias.MUNICIPIO:
        asignar(proyecto, "entidad_ejecutora", cat.entidad_ejecutora(fila.get("EJECUTOR")), resumen, bpin)
    else:
        entidad = fila.get("ENTIDAD O SECRETARIA") if codigo == ClasificacionRegalias.DEPARTAMENTO else fila.get("EJECUTOR")
        asignar(proyecto, "dependencia", cat.dependencia(entidad, bpin), resumen, bpin)

    m2m = {}
    municipios, sin_catalogo = cat.municipios_de(fila.get("MUNICIPIOS"), bpin)
    if municipios:
        m2m["municipios"] = municipios
    responsables = cat.responsables(fila.get("RESPONSABLE CARGUE EN GESPROY"))
    if responsables:
        m2m["responsables_cargue"] = responsables

    cambios = servicios.guardar_proyecto(proyecto, usuario=carga.usuario, origen=IMPORTACION, m2m=m2m, carga=carga)
    existentes[bpin] = proyecto
    resumen.contar("proyectos creados" if nuevo else ("proyectos actualizados" if cambios else "sin cambios"))
    if proyecto.estado_id is None:
        resumen.anotar("Proyectos sin estado", bpin)

    agregados = _comentar(proyecto, _datos_anteriores(fila, sin_catalogo))
    agregados += _comentar(proyecto, lectura.texto(fila.get("COMENTARIOS CALIFICACIÓN") or fila.get("COMENTARIOS")))
    resumen.contar("comentarios agregados", agregados)


def importar_matriz(origen, carga):
    tablas = lectura.leer_matriz(origen)
    resumen = Resumen("Matriz")
    cat = Catalogos(resumen)
    existentes = {p.bpin: p for p in ProyectoRegalias.objects.all()}
    for codigo, filas in tablas.items():
        if filas is None:
            resumen.anotar("Tablas que no vienen en el archivo", lectura.TABLAS_MATRIZ[codigo])
            continue
        vistos = set()
        for fila in filas:
            bpin = lectura.texto(fila.get("BPIN"))
            if bpin in vistos:
                resumen.anotar("BPIN repetidos en una tabla (vale la última fila)", bpin)
            vistos.add(bpin)
            resumen.filas += 1
            _importar_fila(fila, codigo, cat, existentes, resumen, carga)
    return resumen


# ---------- CG-proy ----------

def cargar_proyectos(filas, carga):
    resumen = Resumen("CG-proy")
    cat = Catalogos(resumen)
    existentes = {p.bpin: p for p in ProyectoRegalias.objects.select_related("estado")}
    departamento = cat.clasificaciones[ClasificacionRegalias.DEPARTAMENTO]
    for fila in filas:
        resumen.filas += 1
        bpin = lectura.texto(fila.get("BPIN"))
        if not bpin:
            resumen.contar("filas sin BPIN")
            continue
        proyecto = existentes.get(bpin)
        nuevo = proyecto is None
        nombre = lectura.texto(fila.get("NOMBRE PROYECTO"))
        if nuevo:
            if not nombre:
                resumen.anotar("Proyectos nuevos sin nombre (no se crearon)", bpin)
                continue
            proyecto = ProyectoRegalias(bpin=bpin, clasificacion=departamento)
        estado_antes = proyecto.estado
        asignar(proyecto, "nombre", nombre, resumen, bpin)
        asignar(proyecto, "sector", cat.sector(fila.get("SECTOR"), bpin), resumen, bpin)
        asignar(proyecto, "estado", cat.estado(fila.get("ESTADO PROYECTO"), bpin), resumen, bpin)
        asignar(proyecto, "valor_pagos", _leer(lectura.numero, fila.get("VALOR PAGOS"), "VALOR PAGOS", bpin, resumen),
                resumen, bpin)
        cambios = servicios.guardar_proyecto(proyecto, usuario=carga.usuario, origen=CARGA, carga=carga)
        existentes[bpin] = proyecto
        resumen.contar("proyectos nuevos" if nuevo else ("proyectos actualizados" if cambios else "sin cambios"))
        if not nuevo and estado_antes != proyecto.estado:
            resumen.anotar("Cambios de estado", f"{bpin}: {estado_antes or 'sin estado'} → {proyecto.estado}")
        if proyecto.estado_id is None:
            resumen.anotar("Pendientes de asignar estado", bpin)
    return resumen


# ---------- CG-cttos ----------

def elegir_principal(contratos):
    """El contrato que representa al proyecto: por tipo y, dentro del tipo, el de mayor valor SGR."""
    if not contratos:
        return None
    prioritarios = [c for c in contratos if normalizar(c.tipo) in TIPOS_PRIORITARIOS]
    secundarios = [c for c in contratos if normalizar(c.tipo) in TIPOS_SECUNDARIOS]
    grupo = prioritarios or secundarios or contratos
    return max(grupo, key=lambda c: (c.valor_fuentes_sgr or Decimal(0), -c.pk))


def actualizar_desde_contratos(proyecto, *, usuario, origen, carga=None):
    """Marca el contrato principal y copia al proyecto sus datos, solo los que tienen valor.

    La usan la carga de CG-cttos y el admin de contratos: un contrato que cambia actualiza su
    proyecto; guardar el proyecto no toca estos campos.
    """
    contratos = list(proyecto.contratos.all())
    principal = elegir_principal(contratos)
    proyecto.contratos.exclude(pk=getattr(principal, "pk", None)).update(es_principal=False)
    resumen = Resumen("Contrato principal")
    if principal is not None:
        if not principal.es_principal:
            ContratoRegalias.objects.filter(pk=principal.pk).update(es_principal=True)
        for campo, valor in (("estado_contrato", principal.estado), ("tipo_contrato", principal.tipo),
                             ("fecha_apertura_primer_proceso", principal.fecha_acto_apertura),
                             ("fecha_suscripcion_principal", principal.fecha_suscripcion),
                             ("fecha_acta_inicio", principal.fecha_inicial),
                             ("fecha_ultimo_pago", principal.fecha_ultimo_pago)):
            asignar(proyecto, campo, valor, resumen, proyecto.bpin)
    fechas = [c.fecha_suscripcion for c in contratos if c.fecha_suscripcion]
    asignar(proyecto, "fecha_suscripcion_primer_contrato", min(fechas) if fechas else None, resumen, proyecto.bpin)
    return servicios.guardar_proyecto(proyecto, usuario=usuario, origen=origen, carga=carga)


CONTRATO_TEXTOS = {
    "NO. PROCESO PRECONTRACTUAL": "numero_proceso",
    "MODALIDAD CONTRATACION": "modalidad",
    "TIPO CONTRATO": "tipo",
    "CONTRATO OBJETO": "objeto",
    "ESTADO CONTRATO": "estado",
    "NIT CONTRATISTA": "nit_contratista",
    "NOMBRE CONTRATISTA": "nombre_contratista",
    "UNIDAD PLAZO CONTRACTUAL": "unidad_plazo",
}
CONTRATO_VALORES = {
    "CONTRATO VALOR TOTAL": "valor_total",
    "VALOR CONTRATO EN EL PROYECTO": "valor_en_proyecto",
    "VALOR TOTAL FUENTES SGR": "valor_fuentes_sgr",
    "PAGO EJECUTADO VALOR": "pago_ejecutado",
}
CONTRATO_FECHAS = {
    "FECHA ACT ADTIVO APERT": "fecha_acto_apertura",
    "FECHA INICIAL": "fecha_inicial",
    "FECHA FINAL": "fecha_final",
    "FECHA FINAL REAL": "fecha_final_real",
    "PRIMERA FECHA PAGO": "fecha_primer_pago",
    "ULTIMA FECHA PAGO": "fecha_ultimo_pago",
}


def _contrato_de(fila, proyecto, resumen):
    """Un contrato nuevo (sin guardar) con lo que trae la fila."""
    bpin = proyecto.bpin
    contrato = ContratoRegalias(proyecto=proyecto, numero=_linea(fila.get("CONTRATO NUMERO"))[:100],
                                fecha_suscripcion=lectura.fecha(fila.get("FECHA SUSCRIPCION")))
    for columna, campo in CONTRATO_TEXTOS.items():
        valor = lectura.texto(fila.get(columna)) if campo == "objeto" else _linea(fila.get(columna))
        asignar(contrato, campo, valor, resumen, bpin)
    for columna, campo in CONTRATO_VALORES.items():
        asignar(contrato, campo, _leer(lectura.numero, fila.get(columna), columna, bpin, resumen), resumen, bpin)
    for columna, campo in CONTRATO_FECHAS.items():
        asignar(contrato, campo, lectura.fecha(fila.get(columna)), resumen, bpin)
    asignar(contrato, "plazo", _leer(lectura.numero, fila.get("PLAZO CONTRACTUAL"), "PLAZO CONTRACTUAL", bpin,
                                     resumen), resumen, bpin)
    contrato.ejecuta_varios_proyectos = lectura.texto(fila.get("EJECUTA VARIOS PROYECTOS")).upper() == "S"
    return contrato


def cargar_contratos(filas, carga):
    """Los contratos de cada BPIN que viene en el reporte pasan a ser las filas del reporte.

    Se reemplazan en lugar de buscarse por una llave: GESPROY cambia la fecha de suscripcion de
    algunos contratos entre un mes y otro y repite numeros dentro del mismo BPIN (ver
    ContratoRegalias). Los BPIN que no vienen conservan los suyos.
    """
    resumen = Resumen("CG-cttos")
    bpines = {lectura.texto(f.get("BPIN")) for f in filas}
    proyectos = {p.bpin: p for p in ProyectoRegalias.objects.filter(bpin__in=bpines)}
    por_proyecto = {}
    for fila in filas:
        resumen.filas += 1
        bpin = lectura.texto(fila.get("BPIN"))
        proyecto = proyectos.get(bpin)
        if proyecto is None:
            resumen.anotar("BPIN que no existen (no se cargaron sus contratos)", bpin)
            continue
        if not _linea(fila.get("CONTRATO NUMERO")):
            resumen.anotar("Contratos sin número (no se cargaron)", bpin)
            continue
        por_proyecto.setdefault(proyecto.pk, (proyecto, []))[1].append(_contrato_de(fila, proyecto, resumen))

    for proyecto, contratos in por_proyecto.values():
        antes = proyecto.contratos.count()
        proyecto.contratos.all().delete()
        ContratoRegalias.objects.bulk_create(contratos)     # en el orden del reporte: desempata el principal
        resumen.contar("contratos cargados", len(contratos))
        if antes != len(contratos):
            resumen.anotar("BPIN con otro número de contratos", f"{proyecto.bpin}: {antes} → {len(contratos)}")
        if actualizar_desde_contratos(proyecto, usuario=carga.usuario, origen=CARGA, carga=carga):
            resumen.contar("proyectos actualizados desde su contrato principal")
    resumen.contar("BPIN con contratos", len(por_proyecto))
    return resumen


# ---------- CG-carga ----------

def cargar_cargue(filas, carga):
    resumen = Resumen("CG-carga")
    bpines = {lectura.texto(f.get("BPIN")) for f in filas}
    proyectos = {p.bpin: p for p in ProyectoRegalias.objects.filter(bpin__in=bpines)}
    for fila in filas:
        resumen.filas += 1
        bpin = lectura.texto(fila.get("BPIN"))
        proyecto = proyectos.get(bpin)
        if proyecto is None:
            resumen.anotar("BPIN que no existen (no se actualizaron)", bpin)
            continue
        for columna, campo in (("AVANCE FISICO", "avance_fisico"), ("AVANCE FINANCIERO", "avance_financiero")):
            asignar(proyecto, campo, _leer(lectura.numero, fila.get(columna), columna, bpin, resumen), resumen, bpin)
        asignar(proyecto, "fecha_aprobacion", lectura.fecha(fila.get("FECHA APROBACIÓN PROYECTO")), resumen, bpin)
        cambios = servicios.guardar_proyecto(proyecto, usuario=carga.usuario, origen=CARGA, carga=carga)
        resumen.contar("proyectos actualizados" if cambios else "sin cambios")
    return resumen


CARGADORES = {
    CargaRegalias.Tipo.PROYECTOS: cargar_proyectos,
    CargaRegalias.Tipo.CONTRATOS: cargar_contratos,
    CargaRegalias.Tipo.CARGUE: cargar_cargue,
}


def procesar(carga, origen):
    """Procesa la carga con su archivo (ruta, archivo abierto o FieldFile). Todo o nada.

    Un error deja la carga en estado E con el motivo, y la base como estaba.
    """
    try:
        with transaction.atomic():
            if carga.tipo == CargaRegalias.Tipo.MATRIZ:
                resumen = importar_matriz(origen, carga)
            else:
                resumen = CARGADORES[carga.tipo](lectura.leer_reporte(origen, carga.tipo), carga)
        carga.estado, carga.mensaje, carga.filas = CargaRegalias.Estado.PROCESADO, resumen.texto(), resumen.filas
    except ValueError as error:
        carga.estado, carga.mensaje, carga.filas = CargaRegalias.Estado.ERROR, str(error), 0
    except Exception as error:  # noqa: BLE001 - queda en la carga para que se vea en el admin
        log.exception("Error procesando la carga de regalias %s", carga.pk)
        carga.estado, carga.mensaje, carga.filas = CargaRegalias.Estado.ERROR, f"Error inesperado: {error}", 0
    carga.save(update_fields=["estado", "mensaje", "filas", "fecha_actualizacion"])
    return carga
