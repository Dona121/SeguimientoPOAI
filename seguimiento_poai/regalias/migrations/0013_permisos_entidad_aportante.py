"""El rol Regalías ve y agrega entidades aportantes (catálogo de SIIFWEB), como con los productos e
indicadores del catálogo PIIP: la programación financiera va por entidad y el equipo agrega las
que falten. No las cambia ni las borra, porque las usa también SIIFWEB.
"""
from django.db import migrations

ROL = "Regalías"
PERMISOS = ["view_entidadaportante", "add_entidadaportante"]


def agregar(apps, schema_editor):
    from django.apps import apps as registro
    from django.contrib.auth.management import create_permissions

    db = schema_editor.connection.alias
    create_permissions(registro.get_app_config("siifweb"), using=db, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permisos = list(Permission.objects.using(db).filter(content_type__app_label="siifweb", codename__in=PERMISOS))
    faltantes = sorted(set(PERMISOS) - {p.codename for p in permisos})
    if faltantes:
        raise RuntimeError(f"El rol {ROL} pide permisos que no existen en siifweb: " + ", ".join(faltantes))
    Group.objects.using(db).get(name=ROL).permissions.add(*permisos)


def quitar(apps, schema_editor):
    db = schema_editor.connection.alias
    grupo = apps.get_model("auth", "Group").objects.using(db).filter(name=ROL).first()
    if grupo:
        grupo.permissions.remove(*apps.get_model("auth", "Permission").objects.using(db).filter(
            content_type__app_label="siifweb", codename__in=PERMISOS))


class Migration(migrations.Migration):

    dependencies = [
        ("regalias", "0012_entidad_aportante"),
    ]

    operations = [
        migrations.RunPython(agregar, quitar),
    ]
