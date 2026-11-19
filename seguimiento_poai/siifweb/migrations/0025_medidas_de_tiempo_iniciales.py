"""Las medidas de tiempo con que arranca la lista. Se pueden agregar mas desde el admin."""
from django.db import migrations

MEDIDAS = ("Días", "Meses", "Años")


def crear(apps, schema_editor):
    MedidaTiempo = apps.get_model("siifweb", "MedidaTiempo")
    for nombre in MEDIDAS:
        MedidaTiempo.objects.get_or_create(nombre=nombre)


def quitar(apps, schema_editor):
    MedidaTiempo = apps.get_model("siifweb", "MedidaTiempo")
    MedidaTiempo.objects.filter(nombre__in=MEDIDAS, proyectos__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("siifweb", "0024_tramite_y_observaciones_del_proyecto"),
    ]

    operations = [
        migrations.RunPython(crear, quitar),
    ]
