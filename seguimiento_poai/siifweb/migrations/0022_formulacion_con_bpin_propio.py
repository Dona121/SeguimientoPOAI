"""La formulacion del PIIP guarda su BPIN y su nombre, y el proyecto de SIIFWEB es opcional.

Asi se cargan todos los BPIN del PIIP, incluso los que todavia no estan en SIIFWEB, y se
puede controlar cuales estan y cuales no. Las formulaciones existentes toman el BPIN y el
nombre de su proyecto.
"""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def desde_el_proyecto(apps, schema_editor):
    Formulacion = apps.get_model("siifweb", "FormulacionProyecto")
    Proyecto = apps.get_model("siifweb", "Proyecto")
    del_proyecto = Proyecto.objects.filter(pk=OuterRef("proyecto_id"))
    Formulacion.objects.update(bpin=Subquery(del_proyecto.values("bpin")[:1]),
                               nombre=Subquery(del_proyecto.values("nombre")[:1]))
    Formulacion.objects.filter(nombre__isnull=True).update(nombre="")


class Migration(migrations.Migration):

    dependencies = [
        ("siifweb", "0021_datos_catalogo_piip"),
    ]

    operations = [
        migrations.AddField(
            model_name="formulacionproyecto",
            name="bpin",
            field=models.CharField(max_length=25, null=True, verbose_name="BPIN"),
        ),
        migrations.AddField(
            model_name="formulacionproyecto",
            name="nombre",
            field=models.TextField(blank=True, null=True, verbose_name="Nombre del proyecto (PIIP)"),
        ),
        migrations.RunPython(desde_el_proyecto, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="formulacionproyecto",
            name="bpin",
            field=models.CharField(max_length=25, unique=True, verbose_name="BPIN"),
        ),
        migrations.AlterField(
            model_name="formulacionproyecto",
            name="nombre",
            field=models.TextField(blank=True, default="", verbose_name="Nombre del proyecto (PIIP)"),
        ),
        migrations.AlterField(
            model_name="formulacionproyecto",
            name="proyecto",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                       related_name="formulacion", to="siifweb.proyecto",
                                       verbose_name="Proyecto de SIIFWEB"),
        ),
        migrations.AlterModelOptions(
            name="formulacionproyecto",
            options={"ordering": ("bpin",), "verbose_name": "Formulación del proyecto (PIIP)",
                     "verbose_name_plural": "Formulación de los proyectos (PIIP)"},
        ),
    ]
