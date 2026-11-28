"""El rol "Regalías".

Un rol mal armado no se nota: la pagina abre igual y nadie reclama. Se comprueba lo que
debe abrir, lo que no (SIIFWEB, CUIPO, usuarios) y que el menu solo le ofrezca la seccion
de Regalías.
"""
import importlib

from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from regalias.models import EstadoProyectoRegalias, ProyectoRegalias

from .fabricas import DEPARTAMENTO, MUNICIPIO, catalogos, estado, proyecto, usuario_de

ROL = "Regalías"
migracion_del_rol = importlib.import_module("regalias.migrations.0003_rol_regalias")
migracion_de_cargas = importlib.import_module("regalias.migrations.0006_permisos_cargas_y_contratos")
migracion_de_comentarios = importlib.import_module("regalias.migrations.0009_permisos_comentarios")
migracion_de_programacion = importlib.import_module("regalias.migrations.0011_permisos_programacion")
migracion_de_entidades = importlib.import_module("regalias.migrations.0013_permisos_entidad_aportante")

LISTADOS = ("proyectodepartamento", "proyectodescentralizada", "proyectomunicipio", "contratoregalias",
            "cargaregalias", "cambioproyectoregalias", "fuentesgr", "entidadejecutora", "responsablegesproy",
            "estadoproyectoregalias", "clasificacionregalias")


class ElRolExiste(TestCase):
    def test_las_migraciones_le_dieron_sus_permisos(self):
        grupo = Group.objects.get(name=ROL)
        tiene = {(p.content_type.app_label, p.codename) for p in grupo.permissions.select_related("content_type")}
        esperados = {(app, codigo) for app, codigos in migracion_del_rol.PERMISOS.items() for codigo in codigos}
        esperados |= {("regalias", codigo) for codigo in migracion_de_cargas.PERMISOS + migracion_de_comentarios.PERMISOS
                      + migracion_de_programacion.PERMISOS}
        esperados |= {("siifweb", codigo) for codigo in migracion_de_entidades.PERMISOS}
        self.assertEqual(tiene, esperados)

    def test_solo_borra_comentarios_y_programacion(self):
        """Los comentarios propios durante 5 dias, y los valores en cero de la programacion: lo
        controlan sus pantallas. Proyectos, contratos y cargas no se borran."""
        codigos = Group.objects.get(name=ROL).permissions.values_list("codename", flat=True)
        self.assertEqual(sorted(c for c in codigos if c.startswith("delete_")),
                         ["delete_comentarioproyectoregalias", "delete_programacionfinancieraregalias",
                          "delete_programacionfisicaregalias"])

    def test_de_siifweb_solo_ve_los_catalogos_del_formulario_y_agrega_productos_indicadores_y_entidades(self):
        codigos = set(Group.objects.get(name=ROL).permissions
                      .filter(content_type__app_label="siifweb").values_list("codename", flat=True))
        self.assertEqual(codigos, {"view_sectormga", "view_dependenciaresponsable", "view_municipio",
                                   "view_productocatalogo", "add_productocatalogo",
                                   "view_indicadorcatalogo", "add_indicadorcatalogo",
                                   "view_entidadaportante", "add_entidadaportante"})

    def test_nada_de_cuipo(self):
        self.assertFalse(Group.objects.get(name=ROL).permissions.filter(content_type__app_label="cuipo").exists())


class LoQueAbre(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de(ROL, "regalias")
        cls.cat = catalogos()
        cls.del_departamento = proyecto("2025000020001", DEPARTAMENTO)
        cls.de_municipio = proyecto("2025000020002", MUNICIPIO)

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_abre_los_listados_de_regalias(self):
        for modelo in LISTADOS:
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(reverse(f"admin:regalias_{modelo}_changelist")).status_code, 200)

    def test_ve_y_agrega_entidades_aportantes(self):
        self.assertEqual(self.client.get(reverse("admin:siifweb_entidadaportante_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:siifweb_entidadaportante_add")).status_code, 200)

    def test_abre_el_formulario_de_alta_y_el_de_un_proyecto(self):
        self.assertEqual(self.client.get(reverse("admin:regalias_proyectodepartamento_add")).status_code, 200)
        url = reverse("admin:regalias_proyectodepartamento_change", args=[self.del_departamento.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_cada_hoja_lista_solo_su_clasificacion(self):
        departamento = self.client.get(reverse("admin:regalias_proyectodepartamento_changelist"))
        municipios = self.client.get(reverse("admin:regalias_proyectomunicipio_changelist"))
        self.assertEqual([p.pk for p in departamento.context["cl"].result_list], [self.del_departamento.pk])
        self.assertEqual([p.pk for p in municipios.context["cl"].result_list], [self.de_municipio.pk])

    def test_el_autocompletado_de_los_catalogos_de_siifweb_responde(self):
        for campo in ("sector", "dependencia", "municipios"):
            with self.subTest(campo=campo):
                respuesta = self.client.get(reverse("admin:autocomplete"), {
                    "app_label": "regalias", "model_name": "proyectodepartamento", "field_name": campo, "term": ""})
                self.assertEqual(respuesta.status_code, 200)

    def test_no_abre_siifweb_cuipo_ni_usuarios(self):
        for nombre in ("admin:siifweb_proyecto_changelist", "admin:siifweb_cargareporte_changelist",
                       "admin:cuipo_corteejecuciongastos_changelist", "admin:auth_user_changelist",
                       "admin:auth_group_changelist"):
            with self.subTest(pagina=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 403)

    def test_no_borra_proyectos(self):
        url = reverse("admin:regalias_proyectodepartamento_delete", args=[self.del_departamento.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertTrue(ProyectoRegalias.objects.filter(pk=self.del_departamento.pk).exists())

    def test_el_menu_trae_la_seccion_de_regalias_y_las_entidades_aportantes(self):
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.usuario
        enlaces = [str(item["link"]) for grupo in admin.site.get_sidebar_list(peticion)
                   for item in grupo["items"] if item["has_permission"]]
        esperados = [reverse(f"admin:regalias_{modelo}_changelist") for modelo in LISTADOS]
        # y, en Configuracion y parametrizacion, el catalogo de entidades aportantes de SIIFWEB
        esperados.append(reverse("admin:siifweb_entidadaportante_changelist"))
        self.assertEqual(enlaces, esperados)


class LaListaAlEntrar(TestCase):
    """Al entrar, la lista no trae los cerrados ni los desaprobados; siguen existiendo."""

    @classmethod
    def setUpTestData(cls):
        E = EstadoProyectoRegalias
        cls.usuario = usuario_de(ROL, "regalias")
        cls.activo = proyecto("2025000020011", DEPARTAMENTO, estado=estado(E.CONTRATADO_EN_EJECUCION))
        cls.sin_estado = proyecto("2025000020012", DEPARTAMENTO, estado=None)
        cls.cerrado = proyecto("2025000020013", DEPARTAMENTO, estado=estado(E.CERRADO))
        cls.desaprobado = proyecto("2025000020014", DEPARTAMENTO, estado=estado(E.DESAPROBADO))

    def setUp(self):
        self.client.force_login(self.usuario)

    def lista(self, **filtros):
        respuesta = self.client.get(reverse("admin:regalias_proyectodepartamento_changelist"), filtros)
        return sorted(p.bpin for p in respuesta.context["cl"].result_list)

    def test_al_entrar_no_salen_cerrados_ni_desaprobados(self):
        self.assertEqual(self.lista(), [self.activo.bpin, self.sin_estado.bpin])
        self.assertContains(self.client.get(reverse("admin:regalias_proyectodepartamento_changelist")),
                            "Sin cerrados ni desaprobados")

    def test_con_todos_o_con_su_estado_si_salen(self):
        self.assertEqual(len(self.lista(estado="todos")), 4)
        self.assertEqual(self.lista(estado=str(self.cerrado.estado_id)), [self.cerrado.bpin])
        self.assertEqual(self.lista(estado="sin"), [self.sin_estado.bpin])

    def test_un_proyecto_cerrado_se_sigue_abriendo(self):
        url = reverse("admin:regalias_proyectodepartamento_change", args=[self.cerrado.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
