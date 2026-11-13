"""Semillas de homologacion: las tablas que presupuesto valido para un CUIPO ya enviado.

El libro (por ejemplo `Semillas_CUIPO_T3_2026.xlsx`) trae dos hojas:
- `HomologacionFuente`: recurso_siifweb, fuente_cuipo, vigencia y validado_por (texto).
- `HomologacionRubro`: rubro_siifweb y concepto_cuipo.

Solo crea lo que falta. Lo que ya existe con el mismo valor se cuenta como "ya estaba"; lo que
existe con otro valor no se cambia y se avisa, porque pudo corregirse a mano despues. Todo en
una transaccion: un codigo que no existe aborta la carga sin dejar nada a medias. El archivo no
se guarda en el almacenamiento.
"""
from django.db import transaction
from openpyxl import load_workbook

from siifweb.models import Fuente, Rubro

from .listas import hoja_del_libro, normal
from .models import ConceptoCUIPO, FuenteCUIPO, HomologacionFuente, HomologacionRubro


def _filas(libro, nombre, columnas):
    filas = hoja_del_libro(libro, nombre).iter_rows(values_only=True)
    encabezado = [normal(c) for c in next(filas, ())]
    faltan = [c for c in columnas if c not in encabezado]
    if faltan:
        raise ValueError(f'A la hoja "{nombre}" le faltan columnas: {", ".join(faltan)}')
    for fila in filas:
        datos = {c: fila[encabezado.index(c)] for c in encabezado if c}
        if any(v not in (None, "") for v in datos.values()):
            yield {c: ("" if v is None else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip())
                   for c, v in datos.items()}


@transaction.atomic
def cargar(contenido):
    """Carga las semillas. Devuelve el mensaje del resultado."""
    libro = load_workbook(contenido, read_only=True, data_only=True)
    try:
        fuentes = list(_filas(libro, "HomologacionFuente", ["recurso_siifweb", "fuente_cuipo", "vigencia"]))
        rubros = list(_filas(libro, "HomologacionRubro", ["rubro_siifweb", "concepto_cuipo"]))
    finally:
        libro.close()

    recursos = {f.codigo: f for f in Fuente.objects.all()}
    cuipo = {f.codigo: f for f in FuenteCUIPO.objects.all()}
    errores, creadas, iguales, distintas = [], 0, 0, []
    for s in fuentes:
        recurso, fuente = recursos.get(s["recurso_siifweb"]), cuipo.get(s["fuente_cuipo"])
        de_la_fila = []
        if recurso is None:
            de_la_fila.append(f"recurso {s['recurso_siifweb']} no está en los recursos de SIIFWEB")
        if fuente is None:
            de_la_fila.append(f"fuente {s['fuente_cuipo']} no está en las listas CHIP")
        elif not fuente.activo:
            de_la_fila.append(f"fuente {s['fuente_cuipo']} está inactiva en las listas CHIP")
        if not s["vigencia"].isdigit():
            de_la_fila.append(f"recurso {s['recurso_siifweb']}: vigencia '{s['vigencia']}' inválida")
        if de_la_fila:
            errores += de_la_fila
            continue
        actual = HomologacionFuente.objects.filter(fuente_siifweb=recurso, vigencia=int(s["vigencia"])).first()
        if actual is None:
            nota = f"Semilla validada por {s['validado_por']}" if s.get("validado_por") else "Semilla"
            HomologacionFuente.objects.create(fuente_siifweb=recurso, fuente_cuipo=fuente,
                                              vigencia=int(s["vigencia"]), observacion=nota)
            creadas += 1
        elif actual.fuente_cuipo_id == fuente.pk:
            iguales += 1
        else:
            distintas.append(f"recurso {recurso.codigo} ({s['vigencia']}): la semilla dice {fuente.codigo} "
                             f"y está {actual.fuente_cuipo.codigo}")

    rubros_siifweb = {r.codigo: r for r in Rubro.objects.all()}
    conceptos = {c.codigo: c for c in ConceptoCUIPO.objects.all()}
    r_creadas, r_iguales = 0, 0
    for s in rubros:
        rubro, concepto = rubros_siifweb.get(s["rubro_siifweb"]), conceptos.get(s["concepto_cuipo"])
        if rubro is None:
            errores.append(f"rubro {s['rubro_siifweb']} no está en los rubros de SIIFWEB")
        if concepto is None:
            errores.append(f"concepto {s['concepto_cuipo']} no está en las listas CHIP")
        if rubro is None or concepto is None:
            continue
        actual = HomologacionRubro.objects.filter(rubro=rubro).first()
        if actual is None:
            HomologacionRubro.objects.create(rubro=rubro, concepto=concepto, observacion="Semilla")
            r_creadas += 1
        elif actual.concepto_id == concepto.pk:
            r_iguales += 1
        else:
            distintas.append(f"rubro {rubro.codigo}: la semilla dice {concepto.codigo} y está {actual.concepto.codigo}")

    if errores:
        raise ValueError("No se cargó nada: " + "; ".join(dict.fromkeys(errores)))
    partes = [f"Fuentes: {creadas} creadas, {iguales} ya estaban",
              f"Rubros: {r_creadas} creadas, {r_iguales} ya estaban"]
    if distintas:
        partes.append("No se cambiaron (tienen otro valor): " + "; ".join(distintas))
    return " | ".join(partes)
