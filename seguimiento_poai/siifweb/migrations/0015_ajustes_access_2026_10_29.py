"""Ajustes del Access "Seguimiento PDD STO" del 29/10/2026 a la programacion de proyectos.

La 0014 ya esta aplicada, asi que los cambios del Access van aqui y no regenerandola. Salen
de comparar los datos de la 0014 con los que el generador produce del Access nuevo
(tblProyectos paso de 1626 a 1622 filas):

  - Cuatro filas se borraron en el Access. Cada una era la unica programacion de su
    proyecto, de modo que el proyecto tambien sale, salvo que en la aplicacion le hayan
    agregado otra programacion o una observacion.
  - Una fila cambio de vigencia: Id 1693, MT242, de 2026 a 2027.

Cada fila se reconoce por su Id en Access (id_access). Si una ya se habia editado en la
aplicacion y no esta como la dejo la 0014, no se toca y se avisa en la salida.
"""
from decimal import Decimal

from django.db import migrations

APP = "siifweb"

# (id en Access, meta, vigencia, meta de la vigencia, bpin, nombre, tipo de banco, municipios):
# como las cargo la 0014, para deshacer
QUITADAS = [
    (552, 'MT213', 2026, '1.00000', '', 'Fortalecimiento al sector turístico a través del Plan de Desarrollo Turístico Departamental, el uso de datos y tecnologías, y la promoción y posicionamiento del departamento de Sucre. Sucre', 'Banco Territorial', ['Todo el departamento']),
    (553, 'MT214', 2026, None, '2021002700148', 'APOYO PARA LA AMBIENTACIÓN TURÍSTICA Y APROPIACIÓN CULTURAL DE LA OBRA Y VIDA DE GABRIEL GARCÍA MÁRQUEZ COMO PRODUCTO TURÍSTICO DEL MUNICIPIO DE SUCRE, EN EL MARCO DE LA REACTIVACIÓN ECONÓMICA DEL DEPARTAMENTO DE SUCRE (2021002700148)', None, []),
    (606, 'MT257', 2026, '1.00000', '', 'IMPLEMENTACIÓN DE UNA ESTACIÓN PISICICOLA PARA PRODUCCIÓN DE CARNE DE PESCADO Y REPOBLAMIENTO PESQUERO, FOMENTANDO LA ACUICULTURA EN EL DEPARTAMENTO DE SUCRE', None, []),
    (1648, 'MT245', 2026, '2160.00000', '202600000012343', 'APOYO LOGISTICO E INSTITUCIONAL PARA EL FORTALECIMIENTO DE LOS ESPACIOS DE PARTICIPACIÓN DE LOS PEQUEÑOS PRODUCTORES RURALES DEL DEPARTAMENTO DE SUCRE', 'Banco Territorial', ['Todo el departamento']),
]

# (id en Access, vigencia en la 0014, vigencia en el Access nuevo)
VIGENCIAS = [
    (1693, 2026, 2027),
]


def _vigencias(proyecto):
    anios = sorted({v for v in proyecto.programaciones.values_list("vigencia", flat=True) if v})
    return ", ".join(str(a) for a in anios)


def aplicar(apps, schema_editor):
    Programacion = apps.get_model(APP, "ProgramacionMeta")
    Proyecto = apps.get_model(APP, "ProgramacionProyectos")
    avisos, tocados = [], set()

    for id_access, codigo, vigencia, valor, *_ in QUITADAS:
        fila = Programacion.objects.filter(id_access=id_access).select_related("meta").first()
        if fila is None:
            continue
        if (fila.meta.codigo, fila.vigencia, fila.meta_vigencia) != (
                codigo, vigencia, Decimal(valor) if valor is not None else None):
            avisos.append(f"Id {id_access}: se edito en la aplicacion, no se borra")
            continue
        tocados.add(fila.proyecto_id)
        fila.delete()

    for id_access, antes, despues in VIGENCIAS:
        fila = Programacion.objects.filter(id_access=id_access).first()
        if fila is None:
            continue
        if fila.vigencia != antes:
            avisos.append(f"Id {id_access}: ya no esta en {antes}, no se cambia")
            continue
        fila.vigencia = despues
        fila.save(update_fields=["vigencia", "fecha_actualizacion"])
        tocados.add(fila.proyecto_id)

    for proyecto in Proyecto.objects.filter(pk__in=tocados):
        if not proyecto.programaciones.exists():
            if proyecto.observaciones.exists():
                avisos.append(f"Proyecto {proyecto.pk}: queda sin programaciones pero tiene observaciones")
            else:
                proyecto.delete()
                continue
        vigencias = _vigencias(proyecto)
        if proyecto.vigencias != vigencias:
            proyecto.vigencias = vigencias
            proyecto.save(update_fields=["vigencias", "fecha_actualizacion"])
    if avisos:
        print("\n  Ajustes del Access sin aplicar: " + "; ".join(avisos))


def deshacer(apps, schema_editor):
    Programacion = apps.get_model(APP, "ProgramacionMeta")
    Proyecto = apps.get_model(APP, "ProgramacionProyectos")
    Meta = apps.get_model(APP, "MetaIndicador")
    TipoBanco = apps.get_model(APP, "TipoBanco")
    Municipio = apps.get_model(APP, "Municipio")

    for id_access, antes, despues in VIGENCIAS:
        Programacion.objects.filter(id_access=id_access, vigencia=despues).update(vigencia=antes)
    for id_access, codigo, vigencia, valor, bpin, nombre, banco, municipios in QUITADAS:
        if Programacion.objects.filter(id_access=id_access).exists():
            continue
        proyecto = Proyecto.objects.filter(bpin=bpin, nombre=nombre).first()
        if proyecto is None:
            proyecto = Proyecto.objects.create(
                bpin=bpin, nombre=nombre,
                tipo_banco=TipoBanco.objects.filter(nombre=banco).first() if banco else None)
            proyecto.municipios.set(Municipio.objects.filter(nombre__in=municipios))
        Programacion.objects.create(id_access=id_access, proyecto=proyecto, meta=Meta.objects.get(codigo=codigo),
                                    vigencia=vigencia,
                                    meta_vigencia=Decimal(valor) if valor is not None else None)
    ids = [q[0] for q in QUITADAS] + [v[0] for v in VIGENCIAS]
    for proyecto in Proyecto.objects.filter(programaciones__id_access__in=ids).distinct():
        proyecto.vigencias = _vigencias(proyecto)
        proyecto.save(update_fields=["vigencias", "fecha_actualizacion"])


class Migration(migrations.Migration):

    dependencies = [
        (APP, "0014_datos_programacion_proyectos"),
    ]

    operations = [
        migrations.RunPython(aplicar, deshacer),
    ]
