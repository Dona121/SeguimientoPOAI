"""El estado EN PROCESO DE CONTRATACIÓN, que aparecio en los reportes de octubre de 2026.

Va despues de SIN CONTRATAR; los siguientes corren un lugar en el orden.
"""
from django.db import migrations

ORDEN = (
    "sin_contratar", "en_proceso_contratacion", "contratado_sin_acta", "contratado_en_ejecucion",
    "terminado", "para_cierre", "cerrado", "desaprobado",
)


def crear(apps, schema_editor):
    Estado = apps.get_model("regalias", "EstadoProyectoRegalias")
    db = schema_editor.connection.alias
    Estado.objects.using(db).update_or_create(codigo="en_proceso_contratacion",
                                              defaults={"nombre": "EN PROCESO DE CONTRATACIÓN"})
    for orden, codigo in enumerate(ORDEN, start=1):
        Estado.objects.using(db).filter(codigo=codigo).update(orden=orden)


def borrar(apps, schema_editor):
    Estado = apps.get_model("regalias", "EstadoProyectoRegalias")
    db = schema_editor.connection.alias
    Estado.objects.using(db).filter(codigo="en_proceso_contratacion").delete()
    for orden, codigo in enumerate((c for c in ORDEN if c != "en_proceso_contratacion"), start=1):
        Estado.objects.using(db).filter(codigo=codigo).update(orden=orden)


class Migration(migrations.Migration):

    dependencies = [
        ("regalias", "0004_cargas_contratos_y_comentarios"),
    ]

    operations = [
        migrations.RunPython(crear, borrar),
    ]
