"""Los campos de radicacion, ejecucion y tramite del proyecto y sus observaciones."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile

from siifweb.models import PASOS, RADICACION, TRAMITES, MedidaTiempo, ObservacionProyectoSiifweb, Proyecto

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

    def soporte(self, nombre="soporte.pdf"):
        return SimpleUploadedFile(nombre, b"%PDF-1.4 soporte", content_type="application/pdf")

    def test_doce_pasos_con_casilla_fecha_y_soporte(self):
        self.assertEqual([c for c, _, _ in RADICACION], ["radicado", "registrado"])
        self.assertEqual(len(TRAMITES), 10)
        etiquetas = {f.name: f.verbose_name for f in Proyecto._meta.fields}
        self.assertEqual(etiquetas["radicado"], "Radicado")
        self.assertEqual(etiquetas["registrado"], "Registrado")
        self.assertEqual(etiquetas["soporte_gestion_recursos_piip"], "Soporte gestión de recursos en PIIP")

    def test_fecha_y_soporte_dependen_de_su_casilla(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "x-data=")
        self.assertContains(respuesta, 'enctype="multipart/form-data"')
        for casilla, fecha, soporte in PASOS:
            with self.subTest(casilla=casilla):
                self.assertContains(respuesta, f'x-show="{casilla} == true"', count=2)
                self.assertContains(respuesta, f'id="id_{fecha}"')
                self.assertContains(respuesta, f'id="id_{soporte}"')

    def test_guardar_desde_el_detalle(self):
        meses = MedidaTiempo.objects.get(nombre="Meses")
        respuesta = self.client.post(self.url, self.formulario(
            radicado="on", fecha_radicacion="15/01/2026", soporte_radicacion=self.soporte("Radicación.pdf"),
            registrado="on", fecha_registro="20/01/2026", soporte_registro=self.soporte("registro.pdf"),
            tiempo_ejecucion="12.5", medida_tiempo=meses.pk, contratacion_directa="on",
            terminado="on", fecha_terminacion="30/06/2026", soporte_terminacion=self.soporte("acta.pdf"),
            fecha_decreto_traslado="01/02/2026"))                  # sin su casilla: se guarda, oculta
        if respuesta.status_code != 302:
            self.fail(respuesta.context["adminform"].form.errors)
        p = Proyecto.objects.get(pk=self.proy.pk)
        self.assertEqual((p.radicado, p.fecha_radicacion, p.registrado, p.fecha_registro),
                         (True, date(2026, 1, 15), True, date(2026, 1, 20)))
        self.assertEqual((p.tiempo_ejecucion, p.medida_tiempo), (Decimal("12.5"), meses))
        self.assertTrue(p.contratacion_directa)
        self.assertEqual((p.terminado, p.fecha_terminacion), (True, date(2026, 6, 30)))
        self.assertEqual((p.decreto_traslado, p.fecha_decreto_traslado), (False, date(2026, 2, 1)))
        self.assertEqual(p.soporte_radicacion.name, f"proyectos/{p.bpin}/soportes/Radicacion.pdf")
        self.assertTrue(p.soporte_terminacion.name.startswith(f"proyectos/{p.bpin}/soportes/acta"))

    def test_con_la_casilla_marcada_fecha_y_soporte_son_obligatorios(self):
        respuesta = self.client.post(self.url, self.formulario(gestion_recursos_piip="on", radicado="on",
                                                               fecha_radicacion="15/01/2026"))
        self.assertEqual(respuesta.status_code, 200)
        errores = respuesta.context["adminform"].form.errors
        self.assertIn("fecha_gestion_recursos_piip", errores)
        self.assertIn("soporte_gestion_recursos_piip", errores)
        self.assertIn("soporte_radicacion", errores)
        self.assertNotIn("fecha_radicacion", errores)
        self.assertContains(respuesta, "Cargue el soporte: la casilla está marcada.")
        self.assertFalse(Proyecto.objects.get(pk=self.proy.pk).gestion_recursos_piip)

    def test_tiempo_de_ejecucion_tres_enteros_y_dos_decimales(self):
        respuesta = self.client.post(self.url, self.formulario(tiempo_ejecucion="1000"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("tiempo_ejecucion", respuesta.context["adminform"].form.errors)

    def test_los_soportes_no_tienen_limpiar(self):
        self.proy.estudios_previos, self.proy.fecha_estudios_previos = True, date(2026, 3, 1)
        self.proy.soporte_estudios_previos = self.soporte("estudios.pdf")
        self.proy.save()
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'id="id_soporte_estudios_previos"')
        self.assertNotContains(respuesta, 'name="soporte_estudios_previos-clear"')
        # Aunque llegue la orden de limpiar, el soporte se queda
        self.client.post(self.url, self.formulario(estudios_previos="on", fecha_estudios_previos="01/03/2026",
                                                   **{"soporte_estudios_previos-clear": "on"}))
        self.assertTrue(Proyecto.objects.get(pk=self.proy.pk).soporte_estudios_previos)
        # Se reemplaza cargando otro
        self.client.post(self.url, self.formulario(estudios_previos="on", fecha_estudios_previos="01/03/2026",
                                                   soporte_estudios_previos=self.soporte("nuevo.pdf")))
        self.assertIn("nuevo", Proyecto.objects.get(pk=self.proy.pk).soporte_estudios_previos.name)

    def test_desmarcar_conserva_la_fecha_y_el_soporte(self):
        """Una casilla desmarcada por error no hace perder la fecha ni el soporte."""
        self.proy.estudios_previos, self.proy.fecha_estudios_previos = True, date(2026, 3, 1)
        self.proy.soporte_estudios_previos = self.soporte("estudios.pdf")
        self.proy.save()
        self.assertTrue(Proyecto.objects.get(pk=self.proy.pk).soporte_estudios_previos)
        self.proy.estudios_previos = False
        self.proy.save()
        p = Proyecto.objects.get(pk=self.proy.pk)
        self.assertEqual(p.fecha_estudios_previos, date(2026, 3, 1))
        self.assertTrue(p.soporte_estudios_previos.name.endswith("estudios.pdf"))
        # Y desde el detalle: la casilla desmarcada oculta la fecha, pero el navegador la sigue
        # enviando con su valor, y la casilla de archivo vacia deja el soporte que habia
        respuesta = self.client.post(self.url, self.formulario(fecha_estudios_previos="01/03/2026"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Proyecto.objects.get(pk=self.proy.pk).soporte_estudios_previos)
        self.assertEqual(Proyecto.objects.get(pk=self.proy.pk).fecha_estudios_previos, date(2026, 3, 1))


class Observaciones(Base):
    def setUp(self):
        self.url = reverse("admin:siifweb_proyecto_observaciones", args=(self.proy.pk,))

    def test_agregar_editar_y_borrar(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, {"accion": "agregar", "texto": "  Se radicó en planeación  "}, follow=True)
        self.assertContains(respuesta, "Observación agregada.")
        o = ObservacionProyectoSiifweb.objects.get()
        self.assertEqual((o.proyecto, o.texto, o.usuario), (self.proy, "Se radicó en planeación", self.admin))
        self.assertContains(respuesta, "Se radicó en planeación")
        self.assertContains(respuesta, '<b class="autor">admin</b>')
        # Otro usuario, aunque tenga los permisos de cambiar y borrar, no ve editar ni borrar,
        # y no la modifica ni la borra
        self.usuario("view_proyecto", "view_observacionproyectosiifweb", "change_observacionproyectosiifweb",
                     "delete_observacionproyectosiifweb")
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('value="editar"', html)
        self.assertNotIn('value="borrar"', html)
        self.assertNotIn("se puede modificar hasta el", html)
        for accion in ("editar", "borrar"):
            respuesta = self.client.post(self.url, {"accion": accion, "id": o.pk, "texto": "Cambiada por otro"}, follow=True)
            self.assertContains(respuesta, "Solo quien escribió la observación la puede modificar o borrar.")
        o.refresh_from_db()
        self.assertEqual(o.texto, "Se radicó en planeación")
        # Quien la escribio si, y sigue siendo su usuario
        self.client.force_login(self.admin)
        self.client.post(self.url, {"accion": "editar", "id": o.pk, "texto": "Se radicó el 15 de enero"})
        o.refresh_from_db()
        self.assertEqual((o.texto, o.usuario), ("Se radicó el 15 de enero", self.admin))
        self.client.post(self.url, {"accion": "borrar", "id": o.pk})
        self.assertFalse(ObservacionProyectoSiifweb.objects.exists())

    def vieja(self, texto="Nota vieja", dias=6):
        o = ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto=texto, usuario=self.admin)
        ObservacionProyectoSiifweb.objects.filter(pk=o.pk).update(fecha_creacion=timezone.now() - timedelta(days=dias))
        return ObservacionProyectoSiifweb.objects.get(pk=o.pk)

    def test_pasados_cinco_dias_no_se_modifica_ni_se_borra(self):
        self.client.force_login(self.admin)
        o = self.vieja()
        self.assertFalse(o.editable)
        self.assertTrue(self.vieja("Reciente", dias=4).editable)
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

    def test_en_el_admin_guarda_quien_la_agrega(self):
        u = self.usuario("view_observacionproyectosiifweb", "add_observacionproyectosiifweb",
                         "change_observacionproyectosiifweb", "delete_observacionproyectosiifweb")
        u.first_name, u.last_name = "Ana", "Pérez"
        u.save()
        agregar = reverse("admin:siifweb_observacionproyectosiifweb_add")
        self.assertEqual(self.client.post(agregar, {"proyecto": self.proy.pk, "texto": "Desde el admin"}).status_code, 302)
        o = ObservacionProyectoSiifweb.objects.get()
        self.assertEqual(o.usuario, u)
        # Otro, aunque sea superusuario, no la modifica ni la borra en el admin: se le abre de
        # solo lectura
        self.client.force_login(self.admin)
        cambio = reverse("admin:siifweb_observacionproyectosiifweb_change", args=(o.pk,))
        borrar = reverse("admin:siifweb_observacionproyectosiifweb_delete", args=(o.pk,))
        self.client.post(cambio, {"proyecto": self.proy.pk, "texto": "Cambiada por otro"})
        o.refresh_from_db()
        self.assertEqual(o.texto, "Desde el admin")
        self.assertEqual(self.client.get(cambio).status_code, 200)
        self.assertEqual(self.client.post(borrar, {"post": "yes"}).status_code, 403)
        self.assertContains(self.client.get(self.url), '<b class="autor">Ana Pérez</b>')
        # Quien la escribio si, y sigue siendo su usuario
        self.client.force_login(u)
        self.client.post(cambio, {"proyecto": self.proy.pk, "texto": "Cambiada"})
        o.refresh_from_db()
        self.assertEqual((o.texto, o.usuario), ("Cambiada", u))
        self.assertEqual(self.client.post(borrar, {"post": "yes"}).status_code, 302)
        self.assertFalse(ObservacionProyectoSiifweb.objects.exists())

    def test_las_viejas_sin_usuario_se_muestran(self):
        self.client.force_login(self.admin)
        ObservacionProyectoSiifweb.objects.create(proyecto=self.proy, texto="Sin autor")
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Sin autor")
        self.assertNotContains(respuesta, 'class="autor"')
        # Sin autor, nadie la modifica ni la borra
        self.assertNotContains(respuesta, 'value="editar"')
        self.assertNotContains(respuesta, 'value="borrar"')

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
