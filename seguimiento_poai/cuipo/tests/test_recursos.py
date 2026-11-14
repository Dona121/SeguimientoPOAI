"""Recursos CUIPO: archivos de consulta que se ven en la ficha de distribucion."""
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion
from cuipo.models import DistribucionBPIN, RecursoCUIPO

from .fabricas import corte_t3, formular, listas_distribucion


def archivo(nombre):
    return SimpleUploadedFile(nombre, b"%PDF-1.4 prueba", content_type="application/pdf")


class Recursos(TestCase):
    def setUp(self):
        listas_distribucion()
        formular("202500000039332", "2201006", "2201048")
        corte = corte_t3()
        distribucion.precargar(corte)
        self.d = DistribucionBPIN.objects.get(corte=corte, bpin="202500000039332")
        self.activo = RecursoCUIPO.objects.create(descripcion="Instructivo CUIPO 2026",
                                                  archivo=archivo("instructivo_cuipo.pdf"))
        self.inactivo = RecursoCUIPO.objects.create(descripcion="Guía vieja", archivo=archivo("guia_2024.pdf"),
                                                    activo=False)
        self.ficha = reverse("admin:cuipo_distribuir", args=(self.d.pk,))

    def lector(self):
        """Ve las distribuciones, no la lista de recursos (como el rol de Consulta)."""
        usuario = User.objects.create_user("lector", "l@example.com", "clave", is_staff=True)
        usuario.user_permissions.add(Permission.objects.get(codename="view_distribucionbpin"))
        self.client.force_login(usuario)

    def test_la_ficha_muestra_solo_los_activos(self):
        self.lector()
        respuesta = self.client.get(self.ficha)
        self.assertContains(respuesta, "Recursos para el diligenciamiento")
        self.assertContains(respuesta, "Instructivo CUIPO 2026")
        self.assertContains(respuesta, reverse("admin:cuipo_recurso", args=(self.activo.pk,)))
        self.assertNotContains(respuesta, "Guía vieja")

    def test_sin_recursos_activos_no_hay_seccion(self):
        RecursoCUIPO.objects.update(activo=False)
        self.lector()
        self.assertNotContains(self.client.get(self.ficha), "Recursos para el diligenciamiento")

    def test_abrir_lleva_al_archivo(self):
        self.lector()
        respuesta = self.client.get(reverse("admin:cuipo_recurso", args=(self.activo.pk,)))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("cuipo/recursos/instructivo_cuipo", respuesta["Location"])

    def test_un_inactivo_solo_lo_abre_quien_ve_los_recursos(self):
        url = reverse("admin:cuipo_recurso", args=(self.inactivo.pk,))
        self.lector()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "clave"))
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_sin_permiso_no_abre(self):
        usuario = User.objects.create_user("otro", "o@example.com", "clave", is_staff=True)
        usuario.user_permissions.add(Permission.objects.get(codename="view_proyecto"))
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(reverse("admin:cuipo_recurso", args=(self.activo.pk,))).status_code, 403)

    def test_admin_de_recursos(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "clave"))
        lista = self.client.get(reverse("admin:cuipo_recursocuipo_changelist"))
        self.assertContains(lista, "Instructivo CUIPO 2026")
        self.assertContains(lista, "instructivo_cuipo")
        respuesta = self.client.post(reverse("admin:cuipo_recursocuipo_add"),
                                     {"descripcion": "Circular 2026", "archivo": archivo("circular.pdf"),
                                      "activo": "on"})
        self.assertEqual(respuesta.status_code, 302)
        nuevo = RecursoCUIPO.objects.get(descripcion="Circular 2026")
        self.assertTrue(nuevo.activo)
        self.assertIsNotNone(nuevo.fecha_creacion)
