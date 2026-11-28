"""Guardar un proyecto dejando su historial.

Todo lo que escribe un ProyectoRegalias pasa por aqui: el admin, y despues las cargas de
GESPROY, la importacion de la matriz, las acciones masivas y la programacion. Se toma la
foto de los valores antes y despues, y cada campo que cambio queda en CambioProyectoRegalias
con el usuario y el origen.

Los valores se comparan como texto: asi una fecha, un decimal con ceros de mas o una lista de
municipios en otro orden no cuentan como cambio si dicen lo mismo.

Antes de guardar se recalcula todo lo que no se digita: los valores que salen de la
programacion y los calculados (regalias.calculos). Lo que cambia en ellos tambien queda en el
historial.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from . import calculos
from .models import CambioProyectoRegalias, FuenteSGR, ProyectoRegalias

# Lo que no es un dato del proyecto
EXCLUIDOS = {"id", "fecha_creacion", "fecha_actualizacion"}


def _campos():
    """Los campos del proyecto que se registran, en el orden del modelo: los propios y los M2M."""
    opciones = ProyectoRegalias._meta
    propios = [c for c in opciones.concrete_fields if c.name not in EXCLUIDOS]
    return propios, list(opciones.many_to_many)


def como_texto(valor):
    """El valor de un campo como se guarda en el historial."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, Decimal):
        return f"{valor.normalize():f}"
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor).strip()


def foto(proyecto):
    """Los valores actuales del proyecto (en memoria y, para los M2M, en la base)."""
    propios, m2m = _campos()
    valores = {}
    for campo in propios:
        if campo.is_relation:
            # El id basta para saber si cambio; el texto se arma solo para lo que cambio
            valores[campo.name] = getattr(proyecto, campo.attname)
        else:
            valores[campo.name] = como_texto(getattr(proyecto, campo.name))
    for campo in m2m:
        relacionados = getattr(proyecto, campo.name).all() if proyecto.pk else []
        valores[campo.name] = ", ".join(sorted(str(r) for r in relacionados))
    return valores


def foto_de_la_base(pk):
    """La foto del proyecto como esta guardado.

    Para un proyecto nuevo es la de un proyecto vacio, con los valores por defecto: asi al
    crearlo solo se registra lo que se digito, no un "No" en cada casilla sin marcar.
    """
    guardado = ProyectoRegalias.objects.filter(pk=pk).first() if pk is not None else None
    return foto(guardado or ProyectoRegalias())


def _texto_de_relacion(campo, pk):
    if pk is None:
        return ""
    objeto = campo.related_model._base_manager.filter(pk=pk).first()
    return str(objeto) if objeto else ""


def registrar_cambios(proyecto, antes, despues, *, usuario, origen, carga=None):
    """Una fila de historial por cada campo que cambio. Devuelve cuantas se crearon.

    Para un proyecto nuevo, `antes` es la foto de un proyecto vacio (foto_de_la_base(None)).
    """
    propios, m2m = _campos()
    por_nombre = {c.name: c for c in propios + m2m}
    filas = []
    for nombre, campo in por_nombre.items():
        anterior, nuevo = antes.get(nombre), despues.get(nombre)
        if campo.is_relation and not campo.many_to_many:
            if anterior == nuevo:
                continue
            anterior, nuevo = _texto_de_relacion(campo, anterior), _texto_de_relacion(campo, nuevo)
        anterior, nuevo = anterior or "", nuevo or ""
        if anterior == nuevo:
            continue
        filas.append(CambioProyectoRegalias(proyecto=proyecto, campo=str(campo.verbose_name),
                                            valor_anterior=anterior, valor_nuevo=nuevo,
                                            usuario=usuario, origen=origen, carga=carga))
    CambioProyectoRegalias.objects.bulk_create(filas)
    return len(filas)


CLASIFICACION_A_CAMPO = {
    FuenteSGR.Clasificacion.SGR: "valor_sgr",
    FuenteSGR.Clasificacion.NACION: "valor_nacion",
    FuenteSGR.Clasificacion.OTROS: "valor_otros",
    FuenteSGR.Clasificacion.NO_SUIFP: "valor_otras_no_suifp",
}


def valores_de_programacion(proyecto):
    """Fuentes, valores por clasificacion, total e indicador MGA desde la programacion.

    - fuentes: los nombres distintos de las fuentes con valor, ordenados, separados por ", ".
    - valores: la suma de cada clasificacion de fuente en todas las vigencias, y el total.
      Sin programacion financiera quedan vacios.
    - indicador MGA: "codigo - nombre" de los indicadores de la programacion fisica, con "; "
      (los nombres traen comas).
    """
    valores = {"fuentes": "", "indicadores_mga": "", "valor_total": None, **{c: None for c in CLASIFICACION_A_CAMPO.values()}}
    if proyecto.pk is None:
        return valores
    filas = list(proyecto.programacion_financiera.values("fuente__nombre", "fuente__clasificacion")
                 .annotate(total=Sum("valor")))
    if filas:
        for campo in CLASIFICACION_A_CAMPO.values():
            valores[campo] = Decimal(0)
        for fila in filas:
            campo = CLASIFICACION_A_CAMPO[fila["fuente__clasificacion"]]
            valores[campo] += fila["total"]
        valores["valor_total"] = sum((f["total"] for f in filas), Decimal(0))
        valores["fuentes"] = ", ".join(sorted({f["fuente__nombre"] for f in filas}))
    indicadores = (proyecto.programacion_fisica.values_list("indicador__codigo", "indicador__nombre")
                   .distinct().order_by("indicador__codigo"))
    valores["indicadores_mga"] = "; ".join(f"{codigo} - {nombre}" for codigo, nombre in indicadores)
    return valores


def recalcular(proyecto):
    """Pone al dia en memoria todo lo que no se digita: lo de la programacion y los calculados."""
    for campo, valor in valores_de_programacion(proyecto).items():
        setattr(proyecto, campo, valor)
    calculos.aplicar(proyecto)
    return proyecto


@transaction.atomic
def guardar_proyecto(proyecto, *, usuario, origen, m2m=None, carga=None):
    """Guarda el proyecto y registra lo que cambio.

    `m2m` es {campo: objetos} para fijar relaciones muchos a muchos despues de guardar
    (las cargas y la importacion las usan; el admin las guarda con su formulario y llama a
    registrar_cambios por su cuenta, ver ProyectoRegaliasAdmin).
    """
    antes = foto_de_la_base(proyecto.pk)
    recalcular(proyecto)
    proyecto.save()
    for nombre, objetos in (m2m or {}).items():
        getattr(proyecto, nombre).set(objetos)
    return registrar_cambios(proyecto, antes, foto(proyecto), usuario=usuario, origen=origen, carga=carga)
