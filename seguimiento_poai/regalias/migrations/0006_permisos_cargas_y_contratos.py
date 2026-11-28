"""El rol Regalías consolida: sube las cargas y mantiene los contratos.

- Cargas: agregar, ver y cambiar (cambiar es lo que pide la acción "Volver a procesar").
- Contratos: agregar, cambiar y ver.
- Borrar: tampoco aquí.
"""
from django.db import migrations

ROL = "Regalías"
PERMISOS = [f"{accion}_{modelo}" for modelo in ("cargaregalias", "contratoregalias")
            for accion in ("add", "change", "view")]


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
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    grupo = Group.objects.using(db).filter(name=ROL).first()
    if grupo:
        grupo.permissions.remove(*Permission.objects.using(db).filter(
            content_type__app_label="regalias", codename__in=PERMISOS))


class Migration(migrations.Migration):

    dependencies = [
        ("regalias", "0005_estado_en_proceso_de_contratacion"),
    ]

    operations = [
        migrations.RunPython(agregar, quitar),
    ]
