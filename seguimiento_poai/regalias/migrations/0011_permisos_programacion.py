"""El rol Regalías programa los proyectos (fase 6).

- Programación financiera y física: agregar, cambiar, ver y borrar. Guardar la pantalla borra
  los valores en cero o quitados, como en SIIFWEB.
- Fuentes SGR: agregar, cambiar y ver. Las mantiene el equipo.
"""
from django.db import migrations

ROL = "Regalías"
PERMISOS = ([f"{accion}_{modelo}" for modelo in ("programacionfinancieraregalias", "programacionfisicaregalias")
             for accion in ("add", "change", "view", "delete")]
            + [f"{accion}_fuentesgr" for accion in ("add", "change", "view")])


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
        ("regalias", "0010_programacion"),
    ]

    operations = [
        migrations.RunPython(agregar, quitar),
    ]
