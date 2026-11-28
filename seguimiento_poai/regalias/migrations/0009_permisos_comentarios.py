"""El rol Regalías escribe comentarios en los proyectos (fase 3).

Agregar, cambiar, ver y borrar los comentarios. La pantalla del proyecto deja modificar y borrar
solo los propios y durante 5 días; la lista general de comentarios no borra.
"""
from django.db import migrations

ROL = "Regalías"
PERMISOS = [f"{accion}_comentarioproyectoregalias" for accion in ("add", "change", "view", "delete")]


def agregar(apps, schema_editor):
    from django.apps import apps as registro
    from django.contrib.auth.management import create_permissions

    db = schema_editor.connection.alias
    create_permissions(registro.get_app_config("regalias"), using=db, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permisos = list(Permission.objects.using(db).filter(content_type__app_label="regalias", codename__in=PERMISOS))
    faltantes = sorted(set(PERMISOS) - {p.codename for p in permisos})
    if faltantes:
        raise RuntimeError(f"El rol {ROL} pide permisos que no existen en regalias: " + ", ".join(faltantes))
    Group.objects.using(db).get(name=ROL).permissions.add(*permisos)


def quitar(apps, schema_editor):
    db = schema_editor.connection.alias
    grupo = apps.get_model("auth", "Group").objects.using(db).filter(name=ROL).first()
    if grupo:
        grupo.permissions.remove(*apps.get_model("auth", "Permission").objects.using(db).filter(
            content_type__app_label="regalias", codename__in=PERMISOS))


class Migration(migrations.Migration):

    dependencies = [
        ("regalias", "0008_contratos_sin_llave"),
    ]

    operations = [
        migrations.RunPython(agregar, quitar),
    ]
