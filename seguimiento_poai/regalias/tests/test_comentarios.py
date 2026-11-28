"""La pantalla de comentarios de un proyecto de regalias (fase 3).

Las reglas son las de las observaciones de SIIFWEB: queda el autor, solo el autor modifica o
borra, y solo durante 5 dias. Los comentarios que dejo la importacion no tienen autor y nadie
los modifica.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from regalias.models import ComentarioProyectoRegalias

from .fabricas import DEPARTAMENTO, MUNICIPIO, proyecto, usuario_de


class Comentarios(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.autora = usuario_de("Regalías", "autora")
        cls.otra = usuario_de("Regalías", "otra")

    def setUp(self):
        self.proy = proyecto("2025000020001", DEPARTAMENTO)
        self.url = reverse("admin:regalias_proyectodepartamento_comentarios", args=(self.proy.pk,))
        self.client.force_login(self.autora)

    def test_agregar_deja_el_autor(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, {"accion": "agregar", "texto": "  Se pidió el informe  "}).status_code, 302)
        comentario = self.proy.comentarios.get()
        self.assertEqual((comentario.texto, comentario.usuario), ("Se pidió el informe", self.autora))

    def test_la_autora_edita_y_borra_el_suyo(self):
        comentario = ComentarioProyectoRegalias.objects.create(proyecto=self.proy, texto="Uno", usuario=self.autora)
        self.client.post(self.url, {"accion": "editar", "id": comentario.pk, "texto": "Uno corregido"})
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, "Uno corregido")
        self.client.post(self.url, {"accion": "borrar", "id": comentario.pk})
        self.assertFalse(self.proy.comentarios.exists())

    def test_nadie_toca_el_comentario_de_otro(self):
        comentario = ComentarioProyectoRegalias.objects.create(proyecto=self.proy, texto="De la otra", usuario=self.otra)
        self.client.post(self.url, {"accion": "editar", "id": comentario.pk, "texto": "Cambiado"})
        self.client.post(self.url, {"accion": "borrar", "id": comentario.pk})
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, "De la otra")

    def test_pasados_5_dias_ya_no_se_modifica(self):
        comentario = ComentarioProyectoRegalias.objects.create(proyecto=self.proy, texto="Viejo", usuario=self.autora)
        ComentarioProyectoRegalias.objects.filter(pk=comentario.pk).update(
            fecha_creacion=timezone.now() - timedelta(days=6))
        self.client.post(self.url, {"accion": "borrar", "id": comentario.pk})
        self.assertTrue(self.proy.comentarios.filter(pk=comentario.pk).exists())

    def test_los_importados_no_tienen_autor_y_quedan_como_registro(self):
        comentario = ComentarioProyectoRegalias.objects.create(proyecto=self.proy, texto="Datos de la matriz anterior.")
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Importado de la matriz")
        self.client.post(self.url, {"accion": "borrar", "id": comentario.pk})
        self.assertTrue(self.proy.comentarios.filter(pk=comentario.pk).exists())

    def test_el_proyecto_de_otra_hoja_no_se_abre_por_esta(self):
        de_municipio = proyecto("2025000020002", MUNICIPIO)
        url = reverse("admin:regalias_proyectodepartamento_comentarios", args=(de_municipio.pk,))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_la_lista_general_no_borra(self):
        comentario = ComentarioProyectoRegalias.objects.create(proyecto=self.proy, texto="Uno", usuario=self.autora)
        url = reverse("admin:regalias_comentarioproyectoregalias_delete", args=(comentario.pk,))
        self.assertEqual(self.client.get(url).status_code, 403)
