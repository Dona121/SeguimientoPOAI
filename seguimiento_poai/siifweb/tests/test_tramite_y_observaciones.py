"""Los campos de radicacion, ejecucion y tramite del proyecto y sus observaciones."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from siifweb.models import TRAMITES, MedidaTiempo, ObservacionProyectoSiifweb, Proyecto

from .fabricas import proyecto


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.proy = proyecto()
        cls.admin = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def usuario(self, *codigos):
        u = get_user_model().objects.create_user("u" + "".join(codigos)[:20], "u@b.co", "clave", is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=codigos))
        self.client.force_login(u)
        return u


class Tramite(Base):
    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))

    def formulario(self, **cambios):
        datos = {"bpin": self.proy.bpin, "nombre": self.proy.nombre, "origen": "manual", "_save": "Guardar"}
        datos.update(cambios)
        return datos

    def test_medidas_de_tiempo_iniciales(self):
        self.assertEqual(set(MedidaTiempo.objects.values_list("nombre", flat=True)), {"Días", "Meses", "Años"})

    def test_cada_fecha_depende_de_su_casilla(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "x-data=")
        for casilla, fecha in TRAMITES:
            with self.subTest(casilla=casilla):
                self.assertContains(respuesta, f'x-show="{casilla} == true"')
                self.assertContains(respuesta, f'id="id_{fecha}"')

    def test_guardar_desde_el_detalle(self):
        meses = MedidaTiempo.objects.get(nombre="Meses")
        respuesta = self.client.post(self.url, self.formulario(
            fecha_radicacion="15/01/2026", fecha_registro="20/01/2026", tiempo_ejecucion="12.5",
            medida_tiempo=meses.pk, contratacion_directa="on", terminado="on", fecha_terminacion="30/06/2026",
            fecha_decreto_traslado="01/02/2026"))                  # sin su casilla: no se guarda
        if respuesta.status_code != 302:
            self.fail(respuesta.context["adminform"].form.errors)
        p = Proyecto.objects.get(pk=self.proy.pk)
        self.assertEqual((p.fecha_radicacion, p.fecha_registro, p.tiempo_ejecucion, p.medida_tiempo),
                         (date(2026, 1, 15), date(2026, 1, 20), Decimal("12.5"), meses))
        self.assertTrue(p.contratacion_directa)
        self.assertEqual((p.terminado, p.fecha_terminacion), (True, date(2026, 6, 30)))
        self.assertEqual((p.decreto_traslado, p.fecha_decreto_traslado), (False, None))

    def test_tiempo_de_ejecucion_tres_enteros_y_dos_decimales(self):
        respuesta = self.client.post(self.url, self.formulario(tiempo_ejecucion="1000"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("tiempo_ejecucion", respuesta.context["adminform"].form.errors)

    def test_desmarcar_borra_la_fecha(self):
        self.proy.estudios_previos, self.proy.fecha_estudios_previos = True, date(2026, 3, 1)
        self.proy.save()
        self.proy.estudios_previos = False
        self.proy.save()
        self.assertIsNone(Proyecto.objects.get(pk=self.proy.pk).fecha_estudios_previos)


class Observaciones(Base):
    def setUp(self):
        self.url = reverse("admin:siifweb_proyecto_observaciones", args=(self.proy.pk,))

    def test_agregar_editar_y_borrar(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, {"accion": "agregar", "texto": "  Se radicó en planeación  "}, follow=True)
        self.assertContains(respuesta, "Observación agregada.")
        o = ObservacionProyectoSiifweb.objects.get()
        self.assertEqual((o.proyecto, o.texto), (self.proy, "Se radicó en planeación"))
        self.assertContains(respuesta, "Se radicó en planeación")
        self.client.post(self.url, {"accion": "editar", "id": o.pk, "texto": "Se radicó el 15 de enero"})
        o.refresh_from_db()
        self.assertEqual(o.texto, "Se radicó el 15 de enero")
        self.client.post(self.url, {"accion": "borrar", "id": o.pk})
        self.assertFalse(ObservacionProyectoSiifweb.objects.exists())

    def vieja(self, texto="Nota vieja", dias=4):
        o = ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto=texto)
        ObservacionProyectoSiifweb.objects.filter(pk=o.pk).update(fecha_creacion=timezone.now() - timedelta(days=dias))
        return ObservacionProyectoSiifweb.objects.get(pk=o.pk)

    def test_pasados_tres_dias_no_se_modifica_ni_se_borra(self):
        self.client.force_login(self.admin)
        o = self.vieja()
        self.assertFalse(o.editable)
        self.assertTrue(self.vieja("Reciente", dias=2).editable)
        respuesta = self.client.post(self.url, {"accion": "editar", "id": o.pk, "texto": "Cambiada"}, follow=True)
        self.assertContains(respuesta, "ya no se puede modificar ni borrar")
        self.client.post(self.url, {"accion": "borrar", "id": o.pk})
        o.refresh_from_db()
        self.assertEqual(o.texto, "Nota vieja")
        # La pantalla no ofrece editar ni borrar la vieja, y si la reciente
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('value="borrar"'), 1)
        self.assertEqual(html.count('value="editar"'), 1)
        self.assertIn("se puede modificar hasta el", html)

    def test_en_el_admin_tampoco(self):
        self.client.force_login(self.admin)
        o = self.vieja()
        cambio = reverse("admin:siifweb_observacionproyectosiifweb_change", args=(o.pk,))
        self.client.post(cambio, {"proyecto": self.proy.pk, "texto": "Cambiada"})
        o.refresh_from_db()
        self.assertEqual(o.texto, "Nota vieja")
        self.assertEqual(self.client.post(reverse("admin:siifweb_observacionproyectosiifweb_delete", args=(o.pk,)),
                                          {"post": "yes"}).status_code, 403)
        lista = self.client.get(reverse("admin:siifweb_observacionproyectosiifweb_changelist"))
        self.assertNotIn("delete_selected", lista.context["cl"].model_admin.get_actions(lista.wsgi_request))

    def test_vacia_no_se_agrega(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, {"accion": "agregar", "texto": "   "}, follow=True)
        self.assertContains(respuesta, "Escriba la observación")
        self.assertFalse(ObservacionProyectoSiifweb.objects.exists())

    def test_la_mas_reciente_primero_y_el_boton_en_el_proyecto(self):
        self.client.force_login(self.admin)
        ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto="Primera")
        ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto="Segunda")
        html = self.client.get(self.url).content.decode()
        self.assertLess(html.index("Segunda"), html.index("Primera"))
        self.assertIn("Volver al detalle", html)
        self.assertContains(self.client.get(reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))), self.url)

    def test_solo_ver_no_escribe(self):
        ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto="Nota")
        self.usuario("view_proyecto", "view_observacionproyectosiifweb")
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Nota")
        self.assertNotContains(respuesta, 'value="agregar"')
        self.assertNotContains(respuesta, 'value="borrar"')
        self.assertEqual(self.client.post(self.url, {"accion": "agregar", "texto": "x"}).status_code, 403)

    def test_sin_permiso_no_entra_ni_ve_el_boton(self):
        self.usuario("view_proyecto")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))), self.url)
