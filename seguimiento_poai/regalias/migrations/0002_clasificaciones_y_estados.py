"""Las tres clasificaciones de la matriz y los siete estados de GESPROY.

Van en una migracion para que existan igual en la sqlite local, en las pruebas y en
produccion. Los calculos comparan el estado por su codigo; el nombre es el de GESPROY.
"""
from django.db import migrations

CLASIFICACIONES = (
    ("departamento", "Departamento"),
    ("descentralizada", "Descentralizada"),
    ("municipio", "Municipio"),
)

ESTADOS = (
    ("sin_contratar", "SIN CONTRATAR"),
    ("contratado_sin_acta", "CONTRATADO SIN ACTA DE INICIO"),
    ("contratado_en_ejecucion", "CONTRATADO EN EJECUCIÓN"),
    ("terminado", "TERMINADO"),
    ("para_cierre", "PARA CIERRE"),
    ("cerrado", "CERRADO"),
    ("desaprobado", "DESAPROBADO"),
)


def crear(apps, schema_editor):
    db = schema_editor.connection.alias
    Clasificacion = apps.get_model("regalias", "ClasificacionRegalias")
    Estado = apps.get_model("regalias", "EstadoProyectoRegalias")
    for codigo, nombre in CLASIFICACIONES:
        Clasificacion.objects.using(db).update_or_create(codigo=codigo, defaults={"nombre": nombre})
    for orden, (codigo, nombre) in enumerate(ESTADOS, start=1):
        Estado.objects.using(db).update_or_create(codigo=codigo, defaults={"nombre": nombre, "orden": orden})


def borrar(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("regalias", "EstadoProyectoRegalias").objects.using(db).filter(
        codigo__in=[c for c, _ in ESTADOS]).delete()
    apps.get_model("regalias", "ClasificacionRegalias").objects.using(db).filter(
        codigo__in=[c for c, _ in CLASIFICACIONES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("regalias", "0001_inicial"),
    ]

    operations = [
        migrations.RunPython(crear, borrar),
    ]
