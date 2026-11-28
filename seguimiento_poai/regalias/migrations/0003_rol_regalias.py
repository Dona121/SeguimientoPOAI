"""El rol "Regalías": quien consolida, ve y edita la base de proyectos de regalias.

- **Regalías:** agrega, cambia y ve los proyectos de las tres hojas y los catálogos que
  mantiene el equipo (entidades ejecutoras y responsables del cargue).
- **Catálogos fijos y historial:** solo los ve. El historial no se edita.
- **Borrar:** no puede. Un proyecto con historial no se elimina; se corrige.

De SIIFWEB solo tiene lo que piden los campos del formulario. El autocompletado exige
permiso de vista sobre el modelo relacionado: sector MGA, dependencia y municipio. Los
productos e indicadores del catálogo PIIP además los puede agregar, para la programación.
Nada más de SIIFWEB ni de CUIPO.

Las fases siguientes (cargas, programación, comentarios) suman sus permisos en sus propias
migraciones.
"""
from django.db import migrations

ROL = "Regalías"

PERMISOS = {
    "regalias": (
        [f"{accion}_{modelo}" for modelo in ("proyectodepartamento", "proyectodescentralizada",
                                             "proyectomunicipio", "entidadejecutora", "responsablegesproy")
         for accion in ("add", "change", "view")]
        + ["view_clasificacionregalias", "view_estadoproyectoregalias", "view_cambioproyectoregalias"]
    ),
    "siifweb": [
        "view_sectormga", "view_dependenciaresponsable", "view_municipio",
        "view_productocatalogo", "add_productocatalogo",
        "view_indicadorcatalogo", "add_indicadorcatalogo",
    ],
}


def _asegurar_permisos(schema_editor):
    """Los permisos nacen en post_migrate, al terminar el `migrate`.

    En una base recien creada (la de las pruebas o un despliegue desde cero) todavia no
    existen cuando llega esta migracion, asi que se generan aqui. Es idempotente.
    """
    from django.apps import apps as registro
    from django.contrib.auth.management import create_permissions

    for etiqueta in PERMISOS:
        create_permissions(registro.get_app_config(etiqueta),
                           using=schema_editor.connection.alias, verbosity=0)


def crear_rol(apps, schema_editor):
    _asegurar_permisos(schema_editor)
    db = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    permisos = []
    for etiqueta, codigos in PERMISOS.items():
        encontrados = list(Permission.objects.using(db)
                           .filter(content_type__app_label=etiqueta, codename__in=codigos))
        faltantes = sorted(set(codigos) - {p.codename for p in encontrados})
        if faltantes:
            raise RuntimeError(f"El rol {ROL} pide permisos que no existen en {etiqueta}: "
                               + ", ".join(faltantes))
        permisos += encontrados

    grupo, _ = Group.objects.using(db).get_or_create(name=ROL)
    grupo.permissions.set(permisos)


def borrar_rol(apps, schema_editor):
    apps.get_model("auth", "Group").objects.using(schema_editor.connection.alias).filter(name=ROL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("siifweb", "0028_observacion_con_usuario"),
        ("regalias", "0002_clasificaciones_y_estados"),
    ]

    operations = [
        migrations.RunPython(crear_rol, borrar_rol),
    ]
