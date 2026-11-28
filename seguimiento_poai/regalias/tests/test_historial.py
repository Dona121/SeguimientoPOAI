"""El historial de cambios de los proyectos y el formulario del admin.

Cada cambio de un campo deja una fila con el valor anterior, el nuevo, el usuario y el
origen. Guardar sin cambiar nada no deja filas, aunque la base devuelva los decimales con
ceros de mas.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from regalias import servicios
from regalias.models import CambioProyectoRegalias, EstadoProyectoRegalias, ProyectoRegalias

from .fabricas import (DEPARTAMENTO, DESCENTRALIZADA, NOMBRES_CALCULADOS, catalogos, clasificacion,
                       datos_del_formulario, estado, proyecto, usuario_de)

EDICION = CambioProyectoRegalias.Origen.EDICION
CARGA = CambioProyectoRegalias.Origen.CARGA


def cambios(obj):
    """Los cambios de los campos de datos. Los de los calculados se prueban en test_calculos."""
    return {c.campo: (c.valor_anterior, c.valor_nuevo) for c in obj.cambios.all() if c.campo not in NOMBRES_CALCULADOS}


class EnElAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de("Regalías", "regalias")
        cls.cat = catalogos()

    def setUp(self):
        self.client.force_login(self.usuario)
        self.obj = proyecto("2025000020001", DEPARTAMENTO, avance_fisico=Decimal("40"))
        self.url = reverse("admin:regalias_proyectodepartamento_change", args=[self.obj.pk])
        self.campos = list(self.client.get(self.url).context["adminform"].form.fields)

    def guardar(self, **cambios_del_formulario):
        datos = datos_del_formulario(self.obj, self.campos)
        datos.update(cambios_del_formulario)
        return self.client.post(self.url, datos)

    def test_un_cambio_deja_valor_anterior_nuevo_usuario_y_origen(self):
        en_ejecucion = estado(EstadoProyectoRegalias.CONTRATADO_EN_EJECUCION)
        respuesta = self.guardar(estado=en_ejecucion.pk, avance_fisico="45.5")
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(cambios(self.obj), {
            "Estado del proyecto": ("SIN CONTRATAR", "CONTRATADO EN EJECUCIÓN"),
            "Avance físico": ("40", "45.5"),
        })
        fila = self.obj.cambios.first()
        self.assertEqual((fila.usuario, fila.origen), (self.usuario, EDICION))

    def test_guardar_sin_cambios_no_deja_historial(self):
        self.assertEqual(self.guardar().status_code, 302)
        self.assertFalse(self.obj.cambios.exists())

    def test_los_municipios_quedan_en_el_historial(self):
        self.guardar(municipios=[self.cat["sincelejo"].pk, self.cat["corozal"].pk])
        self.assertEqual(cambios(self.obj), {"Municipios": ("", "Corozal, Sincelejo")})

    def test_el_formulario_exige_el_estado(self):
        respuesta = self.guardar(estado="")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("estado", respuesta.context["adminform"].form.errors)
        self.assertFalse(self.obj.cambios.exists())

    def test_crear_registra_los_campos_con_valor(self):
        datos = {"clasificacion": clasificacion(DEPARTAMENTO).pk, "bpin": "2025000020009",
                 "nombre": "Vía nueva", "estado": estado(EstadoProyectoRegalias.SIN_CONTRATAR).pk}
        respuesta = self.client.post(reverse("admin:regalias_proyectodepartamento_add"), datos)
        self.assertEqual(respuesta.status_code, 302)
        nuevo = ProyectoRegalias.objects.get(bpin="2025000020009")
        self.assertEqual(cambios(nuevo), {
            "Clasificación": ("", "Departamento"), "BPIN": ("", "2025000020009"),
            "Nombre del proyecto": ("", "Vía nueva"), "Estado del proyecto": ("", "SIN CONTRATAR"),
        })

    def test_el_alta_desde_descentralizadas_propone_esa_clasificacion(self):
        respuesta = self.client.get(reverse("admin:regalias_proyectodescentralizada_add"))
        self.assertEqual(respuesta.context["adminform"].form.initial["clasificacion"],
                         clasificacion(DESCENTRALIZADA).pk)

    def test_en_el_departamento_la_informacion_a_tiempo_no_se_digita(self):
        def campos_del_alta(modelo):
            return self.client.get(reverse(f"admin:regalias_{modelo}_add")).context["adminform"].form.fields

        self.assertNotIn("cal_informacion_a_tiempo", campos_del_alta("proyectodepartamento"))
        self.assertIn("cal_informacion_a_tiempo", campos_del_alta("proyectodescentralizada"))

    def test_el_historial_no_se_borra(self):
        self.guardar(avance_fisico="50")
        fila = self.obj.cambios.first()
        url = reverse("admin:regalias_cambioproyectoregalias_delete", args=[fila.pk])
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_el_boton_historial_lleva_a_los_cambios_del_proyecto(self):
        self.guardar(avance_fisico="50")
        otro = proyecto("2025000020002", DEPARTAMENTO)
        otro.avance_fisico = Decimal("10")
        servicios.guardar_proyecto(otro, usuario=self.usuario, origen=EDICION)
        url = reverse("admin:regalias_proyectodepartamento_historial", args=(self.obj.pk,))
        respuesta = self.client.get(url, follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual({c.proyecto_id for c in respuesta.context["cl"].result_list}, {self.obj.pk})


class ElServicio(TestCase):
    """guardar_proyecto: lo que usaran las cargas, la importacion y las acciones masivas."""

    def setUp(self):
        self.obj = proyecto("2025000020001", DEPARTAMENTO)

    def test_registra_lo_que_cambio_con_su_origen(self):
        self.obj.avance_financiero = Decimal("12.345")
        self.obj.estado = None
        # Sin estado tambien se vacian los calculados: el numero incluye esas filas
        self.assertEqual(servicios.guardar_proyecto(self.obj, usuario=None, origen=CARGA), self.obj.cambios.count())
        self.assertEqual(cambios(self.obj), {"Avance financiero": ("", "12.345"),
                                             "Estado del proyecto": ("SIN CONTRATAR", "")})
        self.assertEqual(set(self.obj.cambios.values_list("origen", flat=True)), {CARGA})

    def test_un_decimal_que_dice_lo_mismo_no_es_un_cambio(self):
        self.obj.avance_financiero = Decimal("12.5")
        servicios.guardar_proyecto(self.obj, usuario=None, origen=CARGA)
        recargado = ProyectoRegalias.objects.get(pk=self.obj.pk)     # la base lo devuelve como 12.500
        recargado.avance_financiero = Decimal("12.50")
        self.assertEqual(servicios.guardar_proyecto(recargado, usuario=None, origen=CARGA), 0)

    def test_fija_los_m2m_y_los_registra(self):
        cat = catalogos()
        servicios.guardar_proyecto(self.obj, usuario=None, origen=CARGA, m2m={"municipios": [cat["corozal"]]})
        self.assertEqual(cambios(self.obj), {"Municipios": ("", "Corozal")})
