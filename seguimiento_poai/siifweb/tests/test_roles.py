# -*- coding: utf-8 -*-
"""Los roles "Seguimiento" y "Consulta".

Un rol mal armado no se nota: la pagina abre igual y nadie reclama. Lo que se
comprueba aqui es lo contrario -que lo que no debe abrir, no abra- y que el menu
lateral no le ofrezca a nadie enlaces que terminan en 403.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from siifweb.models import Proyecto

from .fabricas import cadena, carga_secop, catalogos, contrato_siifweb, fila, proyecto

# Un listado por familia de datos: el proyecto, lo presupuestal, los contratos de
# SIIFWEB, los de SECOP II y los catalogos.
LISTADOS_PERMITIDOS = ("proyecto", "cdp", "compromiso", "obligacion", "reserva",
                       "contrato", "contratoacta", "contratosecop", "procesosecop",
                       "bpinproceso", "tercero", "rubro", "fuente", "centrocosto",
                       "dependenciaresponsable", "clasificacion")


def usuario_de(rol, nombre):
    """Un usuario del equipo: staff para entrar al admin, sin poderes propios."""
    persona = get_user_model().objects.create_user(nombre, f"{nombre}@sucre.gov.co",
                                                   "clave", is_staff=True)
    persona.groups.add(Group.objects.get(name=rol))
    return persona


class RolBase(TestCase):
    rol = None

    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de(cls.rol, cls.rol.lower())
        catalogos()
        cls.proy = proyecto()
        cadena(cls.proy)
        contrato_siifweb(cls.proy)
        carga_secop([fila()])

    def setUp(self):
        self.client.force_login(self.usuario)

    def enlaces_del_menu(self):
        """Los enlaces que la barra lateral le muestra a este usuario."""
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.usuario
        return [str(item["link"]) for grupo in admin.site.get_sidebar_list(peticion)
                for item in grupo["items"] if item["has_permission"]]

    def comprobar_menu_de_un_solo_modulo(self):
        """El menu de estos roles trae el modulo de Seguimiento y nada mas.

        Las demas secciones listan documento por documento lo que producen las cargas;
        el rol revisa esa misma informacion agregada en la ficha del proyecto.
        """
        self.assertEqual(self.enlaces_del_menu(), [
            reverse("admin:siifweb_proyecto_changelist"),
            reverse("admin:siifweb_proyecto_tablero"),
            reverse("admin:siifweb_proyecto_reporte_financiero"),
        ])


class LosRolesExisten(TestCase):
    def test_la_migracion_los_creo(self):
        self.assertTrue(Group.objects.filter(name="Seguimiento").exists())
        self.assertTrue(Group.objects.filter(name="Consulta").exists())

    def test_consulta_solo_tiene_permisos_de_vista(self):
        codigos = list(Group.objects.get(name="Consulta")
                       .permissions.values_list("codename", flat=True))
        self.assertTrue(all(c.startswith("view_") for c in codigos), sorted(codigos))
        self.assertIn("view_proyecto", codigos)

    def test_seguimiento_agrega_alta_y_edicion_del_proyecto(self):
        def permisos(rol):
            return set(Group.objects.get(name=rol)
                       .permissions.values_list("codename", flat=True))

        self.assertEqual(permisos("Seguimiento") - permisos("Consulta"),
                         {"add_proyecto", "change_proyecto"})

    def test_ninguno_toca_las_cargas_ni_los_usuarios(self):
        for rol in ("Seguimiento", "Consulta"):
            with self.subTest(rol=rol):
                permisos = Group.objects.get(name=rol).permissions.select_related("content_type")
                codigos = {p.codename for p in permisos}
                self.assertEqual({p.content_type.app_label for p in permisos}, {"siifweb"})
                self.assertNotIn("view_cargareporte", codigos)
                self.assertNotIn("delete_proyecto", codigos)


class Consulta(RolBase):
    rol = "Consulta"

    def test_ve_el_proyecto_lo_presupuestal_y_los_contratos(self):
        """Fuera del menu, pero abiertas: la ficha enlaza el contrato y el proceso."""
        for modelo in LISTADOS_PERMITIDOS:
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_ve_la_ficha_y_el_reporte_financiero(self):
        ficha = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.proy.pk,))
        self.assertEqual(self.client.get(ficha).status_code, 200)
        self.assertEqual(self.client.get(ficha, {"panel": "secop"}).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:siifweb_proyecto_reporte_financiero")).status_code, 200)

    def test_no_puede_crear_ni_editar_el_proyecto(self):
        self.assertEqual(self.client.get(reverse("admin:siifweb_proyecto_add")).status_code, 403)
        cambio = reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))
        self.assertEqual(self.client.post(cambio, {"bpin": "999", "nombre": "Cambiado"}).status_code,
                         403)
        self.proy.refresh_from_db()
        self.assertEqual(self.proy.nombre, "Proyecto de prueba")

    def test_no_entra_a_las_cargas_ni_a_los_usuarios(self):
        for url in (reverse("admin:siifweb_cargareporte_changelist"),
                    reverse("admin:siifweb_cargareporte_add"),
                    reverse("admin:auth_user_changelist"),
                    reverse("admin:auth_group_changelist")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_el_menu_solo_trae_el_modulo_de_seguimiento(self):
        self.comprobar_menu_de_un_solo_modulo()


class Seguimiento(RolBase):
    rol = "Seguimiento"

    def formularios_vacios(self):
        """Los inlines del proyecto van en solo lectura, pero el POST igual los exige."""
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.usuario
        datos = {}
        for FormSet, _ in admin.site._registry[Proyecto].get_formsets_with_inlines(peticion):
            prefijo = FormSet.get_default_prefix()
            datos.update({f"{prefijo}-TOTAL_FORMS": "0", f"{prefijo}-INITIAL_FORMS": "0",
                          f"{prefijo}-MIN_NUM_FORMS": "0", f"{prefijo}-MAX_NUM_FORMS": "0"})
        return datos

    def test_ve_lo_mismo_que_consulta(self):
        for modelo in LISTADOS_PERMITIDOS:
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_crea_un_proyecto(self):
        respuesta = self.client.post(reverse("admin:siifweb_proyecto_add"), {
            "bpin": "202500000000099", "nombre": "Proyecto nuevo",
            "origen": Proyecto.Origen.MANUAL, **self.formularios_vacios()})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Proyecto.objects.filter(bpin="202500000000099").exists())

    def test_edita_el_proyecto(self):
        cambio = reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))
        self.assertEqual(self.client.get(cambio).status_code, 200)
        respuesta = self.client.post(cambio, {
            "bpin": self.proy.bpin, "nombre": "Nombre corregido",
            "origen": Proyecto.Origen.MANUAL, **self.formularios_vacios()})
        self.assertEqual(respuesta.status_code, 302)
        self.proy.refresh_from_db()
        self.assertEqual(self.proy.nombre, "Nombre corregido")

    def test_no_edita_la_informacion_presupuestal(self):
        for modelo, objeto in (("cdp", self.proy.cdps_imputados.first().cdp),
                               ("contrato", self.proy.imputaciones_del_contrato.first().contrato)):
            with self.subTest(modelo=modelo):
                url = reverse(f"admin:siifweb_{modelo}_change", args=(objeto.pk,))
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(respuesta, 'name="_save"')

    def test_tampoco_borra_ni_carga_reportes(self):
        borrado = reverse("admin:siifweb_proyecto_delete", args=(self.proy.pk,))
        self.assertEqual(self.client.get(borrado).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("admin:siifweb_cargareporte_changelist")).status_code, 403)

    def test_el_menu_solo_trae_el_modulo_de_seguimiento(self):
        self.comprobar_menu_de_un_solo_modulo()


class StaffSinRol(TestCase):
    """Las vistas propias no las cubre el admin: hay que revisar el permiso a mano."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            "suelto", "suelto@sucre.gov.co", "clave", is_staff=True)
        cls.proy = proyecto()

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_la_ficha_y_el_reporte_le_responden_403(self):
        ficha = reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.proy.pk,))
        self.assertEqual(self.client.get(ficha).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("admin:siifweb_proyecto_reporte_financiero")).status_code, 403)
