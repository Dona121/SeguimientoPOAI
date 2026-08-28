# -*- coding: utf-8 -*-
"""Dos roles para el modulo de seguimiento: "Seguimiento" y "Consulta".

**Consulta** solo mira: el proyecto, su informacion presupuestal y sus contratos, los
de SIIFWEB y los de SECOP II. **Seguimiento** ve exactamente lo mismo y ademas puede
crear y editar proyectos, que es el unico dato que el equipo alimenta a mano; el resto
llega desde los reportes y editarlo descuadraria la proxima carga.

Ninguno de los dos toca las cargas del reporte -subir un archivo dispara el
procesamiento y reescribe datos- ni los usuarios y roles de Django.

Va en una migracion y no en un comando suelto para que los roles existan igual en la
sqlite local, en las pruebas y en produccion, sin que nadie tenga que acordarse de
marcar veintitantas casillas a mano.
"""
from django.db import migrations

CONSULTA = "Consulta"
SEGUIMIENTO = "Seguimiento"

# Lo que ambos roles pueden consultar. Los catalogos entran porque los combos del
# formulario y el autocompletado exigen permiso de vista sobre el modelo relacionado.
SOLO_VISTA = (
    # El proyecto y sus catalogos
    "proyecto", "tercero", "rubro", "fuente", "centrocosto",
    "dependenciaresponsable", "clasificacion", "ordengasto",
    # Informacion presupuestal: la cadena de gasto y el cierre de vigencia
    "cdp", "cdpimputacion", "compromiso", "compromisoimputacion",
    "obligacion", "obligacionimputacion", "reserva", "reservaimputacion",
    # Contratos de SIIFWEB
    "contrato", "contratoacta", "contratoimputacion",
    # Contratacion publica (SECOP II)
    "procesosecop", "contratosecop", "bpinproceso",
)

VISTA = [f"view_{modelo}" for modelo in SOLO_VISTA]

# Sin borrado: un proyecto con ejecucion colgando no se elimina, se corrige.
ROLES = {
    CONSULTA: VISTA,
    SEGUIMIENTO: VISTA + ["add_proyecto", "change_proyecto"],
}


def _asegurar_permisos(schema_editor):
    """Los permisos nacen en post_migrate, que corre al terminar el `migrate`.

    En una base recien creada -la de las pruebas o un despliegue desde cero- todavia
    no existe ni un solo Permission cuando llega esta migracion, asi que se generan
    aqui. La funcion es idempotente y post_migrate no duplica nada despues.
    """
    from django.apps import apps as registro
    from django.contrib.auth.management import create_permissions

    create_permissions(registro.get_app_config("siifweb"),
                       using=schema_editor.connection.alias, verbosity=0)


def crear_roles(apps, schema_editor):
    _asegurar_permisos(schema_editor)
    db = schema_editor.connection.alias
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for nombre, codigos in ROLES.items():
        permisos = list(Permission.objects.using(db)
                        .filter(content_type__app_label="siifweb", codename__in=codigos))
        faltantes = sorted(set(codigos) - {p.codename for p in permisos})
        if faltantes:
            raise RuntimeError(
                f"El rol {nombre} pide permisos que no existen en siifweb: "
                + ", ".join(faltantes)
                + ". Revisa que el nombre del modelo siga siendo el mismo.")

        grupo, _ = Group.objects.using(db).get_or_create(name=nombre)
        grupo.permissions.set(permisos)


def borrar_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    (Group.objects.using(schema_editor.connection.alias)
     .filter(name__in=list(ROLES)).delete())


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("siifweb", "0008_obligacion_beneficiario"),
    ]

    operations = [
        migrations.RunPython(crear_roles, borrar_roles),
    ]
