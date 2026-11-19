"""Programacion financiera: los recursos de cada proyecto por vigencia, fuente y meta del plan.

El modelo, el valor programado del proyecto (que se recalcula solo) y la pantalla del proyecto:
una matriz con vigencias, fuentes y metas que se guarda con un boton.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from siifweb import programacion_financiera as pf
from siifweb.models import (Fuente, MetaIndicador, ProgramacionFinanciera, ProgramacionMeta, ProgramacionProyectos,
                            Proyecto)

from .fabricas import catalogos, proyecto

D = Decimal
ANIO = timezone.localdate().year


class LeerYFormatear(SimpleTestCase):
    def test_punto_decimal_como_en_el_cuipo(self):
        casos = {"1500000.5": D("1500000.5"), "1500000": D("1500000"), "$ 2000": D("2000"),
                 " 7.12345 ": D("7.12345"), "7,5": D("7.5"), "": D(0), "0": D(0)}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(pf.leer_valor(texto), esperado)

    def test_lo_que_no_se_acepta(self):
        casos = {"-5": "negativo", "1,2a": "tiene que ser un número", "abc": "tiene que ser un número",
                 "1,123456": "hasta 5 decimales", "1234567890123456": "hasta 15 dígitos enteros"}
        for texto, mensaje in casos.items():
            with self.subTest(texto=texto):
                with self.assertRaisesMessage(ValueError, mensaje):
                    pf.leer_valor(texto)

    def test_quince_enteros_y_cinco_decimales_si_caben(self):
        self.assertEqual(pf.leer_valor("999999999999999.99999"), D("999999999999999.99999"))

    def test_en_la_casilla(self):
        self.assertEqual(pf.en_casilla(D("1500000.50000")), "1500000.5")
        self.assertEqual(pf.en_casilla(D("2000.00000")), "2000")
        self.assertEqual(pf.en_casilla(D("0")), "")
        self.assertEqual(pf.en_casilla(None), "")


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.fuente, _ = catalogos()
        cls.otra = Fuente.objects.create(codigo="54", nombre="Sistema General de Participaciones")
        cls.proy = proyecto()
        cls.meta = MetaIndicador.objects.get(codigo="MT001")
        cls.meta2 = MetaIndicador.objects.get(codigo="MT002")
        # El proyecto esta programado en MT001 para la vigencia (Programacion de proyectos, por BPIN)
        programado = ProgramacionProyectos.objects.create(bpin=cls.proy.bpin, nombre="Proyecto de prueba")
        ProgramacionMeta.objects.create(proyecto=programado, meta=cls.meta, vigencia=ANIO, meta_vigencia=D("10"))
        cls.admin = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def programar(self, valor, fuente=None, meta=None, vigencia=ANIO):
        return ProgramacionFinanciera.objects.create(proyecto=self.proy, vigencia=vigencia, fuente=fuente or self.fuente,
                                                     meta=meta or self.meta, valor=D(valor))

    def total(self):
        return Proyecto.objects.get(pk=self.proy.pk).valor_programado


class ValorProgramado(Base):
    def test_se_recalcula_al_guardar_cambiar_y_borrar(self):
        a = self.programar("1000000")
        self.programar("500000.5", fuente=self.otra)
        self.programar("250000", meta=self.meta2, vigencia=ANIO + 1)        # suma todas las vigencias
        self.assertEqual(self.total(), D("1750000.5"))
        a.valor = D("2000000")
        a.save()
        self.assertEqual(self.total(), D("2750000.5"))
        a.delete()
        self.assertEqual(self.total(), D("750000.5"))
        ProgramacionFinanciera.objects.all().delete()                    # borrado masivo, como en el admin
        self.assertEqual(self.total(), D(0))

    def test_un_valor_por_proyecto_vigencia_fuente_y_meta(self):
        from django.db import IntegrityError, transaction
        self.programar("1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.programar("2")

    def test_borrar_el_proyecto_borra_su_programacion(self):
        self.programar("1")
        self.proy.delete()
        self.assertFalse(ProgramacionFinanciera.objects.exists())


class Pantalla(Base):
    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("admin:siifweb_proyecto_programacion_financiera", args=(self.proy.pk,))
        self.guardar_url = reverse("admin:siifweb_proyecto_pf_guardar", args=(self.proy.pk,))
        self.matriz = reverse("admin:siifweb_proyecto_pf_matriz", args=(self.proy.pk,))
        self.elegir = reverse("admin:siifweb_proyecto_pf_elegir", args=(self.proy.pk,))

    def casilla(self, vigencia=ANIO, fuente=None, meta=None):
        return f"v-{vigencia}-{(fuente or self.fuente).pk}-{(meta or self.meta).pk}"

    def estado(self, bloques=None, **extra):
        """Los campos ocultos de la pantalla: {vigencia: ([fuentes], [metas])}."""
        bloques = {ANIO: ([self.fuente], [self.meta])} if bloques is None else bloques
        datos = {"vigencias": list(bloques)}
        for v, (fuentes, metas) in bloques.items():
            datos[f"fuentes-{v}"] = [f.pk for f in fuentes]
            datos[f"metas-{v}"] = [m.pk for m in metas]
        return {**datos, **extra}

    def guardar(self, valores, bloques=None):
        return self.client.post(self.guardar_url, self.estado(bloques, **valores))

    def test_el_boton_esta_en_el_proyecto_y_el_detalle_muestra_el_total(self):
        self.programar("1500000")
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,)))
        self.assertContains(respuesta, self.url)
        self.assertContains(respuesta, "Valor programado")
        self.assertContains(respuesta, "$1,500,000")             # como las demas columnas del proyecto

    def test_al_abrir_sin_nada_guardado_no_trae_metas_solas(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, f"Vigencia {ANIO}")               # la del anio en curso
        self.assertContains(respuesta, "Sin fuentes ni metas.")
        self.assertNotContains(respuesta, "MT001")                       # la programada no se agrega sola

    def test_al_abrir_con_valores_cada_vigencia_trae_lo_suyo(self):
        self.programar("10", meta=self.meta2, vigencia=ANIO + 1)
        self.programar("20", fuente=self.otra)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, f'name="{self.casilla(ANIO + 1, meta=self.meta2)}"')
        self.assertContains(respuesta, f'name="{self.casilla(ANIO, fuente=self.otra)}"')
        self.assertNotContains(respuesta, f'name="{self.casilla(ANIO, meta=self.meta2)}"')
        self.assertNotContains(respuesta, f'name="{self.casilla(ANIO + 1)}"')

    def test_agregar_no_guarda_y_conserva_lo_digitado(self):
        respuesta = self.client.get(self.matriz, self.estado({ANIO: ([], [self.meta])}, en=ANIO,
                                                             agregar_fuente=self.fuente.pk))
        self.assertContains(respuesta, f'name="{self.casilla()}"')
        respuesta = self.client.get(self.matriz, self.estado(None, **{self.casilla(): "5", "agregar_vigencia": ANIO + 1}))
        self.assertContains(respuesta, f"Vigencia {ANIO + 1}")
        self.assertContains(respuesta, 'value="5"')
        self.assertContains(respuesta, " cambio")
        self.assertNotContains(respuesta, 'id="pf-pendiente" hidden')
        self.assertFalse(ProgramacionFinanciera.objects.exists())

    def test_quitar_la_fuente_de_una_vigencia_no_toca_la_otra(self):
        """La misma fuente en dos vigencias: quitarla de una deja la otra con lo digitado."""
        bloques = {ANIO: ([self.fuente], [self.meta]), ANIO + 1: ([self.fuente], [self.meta])}
        respuesta = self.client.get(self.matriz, self.estado(bloques, **{
            self.casilla(): "1000", self.casilla(ANIO + 1): "2000", "quitar_fuente": self.fuente.pk, "en": ANIO + 1}))
        self.assertContains(respuesta, f'name="{self.casilla()}"')
        self.assertContains(respuesta, 'value="1000"')
        self.assertNotContains(respuesta, f'name="{self.casilla(ANIO + 1)}"')
        # Y al guardar queda la de la primera vigencia
        self.guardar({self.casilla(): "1000"}, {ANIO: ([self.fuente], [self.meta]), ANIO + 1: ([], [self.meta])})
        self.assertEqual(list(ProgramacionFinanciera.objects.values_list("vigencia", "valor")), [(ANIO, D("1000"))])

    def test_quitar_una_meta_solo_en_su_vigencia(self):
        bloques = {ANIO: ([self.fuente], [self.meta]), ANIO + 1: ([self.fuente], [self.meta])}
        respuesta = self.client.get(self.matriz, self.estado(bloques, quitar_meta=self.meta.pk, en=ANIO))
        self.assertNotContains(respuesta, f'name="{self.casilla()}"')
        self.assertContains(respuesta, f'name="{self.casilla(ANIO + 1)}"')

    def test_guardar_crea_cambia_y_borra(self):
        respuesta = self.guardar({self.casilla(): "1500000.5", self.casilla(meta=self.meta2): ""},
                                 {ANIO: ([self.fuente], [self.meta, self.meta2])})
        self.assertContains(respuesta, "Guardado: 1 nuevos.")
        self.assertContains(respuesta, 'hx-swap-oob="true"')            # el total del encabezado
        self.assertContains(respuesta, 'value="1500000.5"')
        self.assertContains(respuesta, "1.500.000,50")                  # el total, como en el CUIPO
        self.assertEqual(self.total(), D("1500000.5"))
        self.assertContains(self.guardar({self.casilla(): "2000000"}), "Guardado: 1 cambiados.")
        self.assertEqual(ProgramacionFinanciera.objects.get().valor, D("2000000"))
        self.assertContains(self.guardar({self.casilla(): "2000000"}), "Sin cambios.")
        self.assertContains(self.guardar({self.casilla(): ""}), "Guardado: 1 borrados.")
        self.assertEqual(self.total(), D(0))

    def test_con_un_error_no_se_guarda_nada(self):
        respuesta = self.guardar({self.casilla(): "100", self.casilla(fuente=self.otra): "-3"},
                                 {ANIO: ([self.fuente, self.otra], [self.meta])})
        self.assertContains(respuesta, "1 casilla con error")
        self.assertContains(respuesta, 'aria-invalid="true"')
        self.assertContains(respuesta, 'value="-3"')                     # lo digitado no se pierde
        self.assertContains(respuesta, 'value="100"')
        self.assertFalse(ProgramacionFinanciera.objects.exists())

    def test_quitar_avisa_y_al_guardar_borra(self):
        self.programar("1")
        self.programar("2", fuente=self.otra)
        respuesta = self.client.get(self.matriz, self.estado({ANIO: ([self.fuente, self.otra], [self.meta])},
                                                             quitar_fuente=self.otra.pk, en=ANIO))
        self.assertNotContains(respuesta, f'name="{self.casilla(fuente=self.otra)}"')
        self.assertContains(respuesta, "se borran 1 valor de lo que se quitó")
        self.assertEqual(ProgramacionFinanciera.objects.count(), 2)      # quitar no borra
        self.guardar({self.casilla(): "1"})
        self.assertEqual(list(ProgramacionFinanciera.objects.values_list("fuente", flat=True)), [self.fuente.pk])
        self.assertEqual(self.total(), D("1"))

    def test_quitar_todo_y_volver_a_abrir_no_trae_nada(self):
        self.programar("1")
        self.guardar({}, {ANIO: ([], [])})
        self.assertFalse(ProgramacionFinanciera.objects.exists())
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Sin fuentes ni metas.")
        self.assertNotContains(respuesta, "MT001")

    def test_el_listado_busca_excluye_y_pasa_de_pagina(self):
        respuesta = self.client.get(self.elegir, self.estado(tipo="fuente", en=ANIO, q="Participaciones"))
        self.assertContains(respuesta, f"Agregar una fuente a {ANIO}")
        self.assertContains(respuesta, "Sistema General de Participaciones")
        resultados = self.client.get(self.elegir, self.estado({ANIO: ([self.otra], [])}, tipo="fuente", en=ANIO,
                                                              q="Participaciones", solo="resultados"))
        self.assertNotContains(resultados, "Sistema General de Participaciones")
        metas = self.client.get(self.elegir, self.estado({ANIO: ([], [])}, tipo="meta", en=ANIO, solo="resultados"))
        self.assertContains(metas, "1–50 de")
        self.assertContains(metas, "Siguiente")
        html = metas.content.decode()
        self.assertLess(html.index("<b>MT001</b>"), html.index("<b>MT002</b>"))
        self.assertIn("programada", html[html.index("<b>MT001</b>"):html.index("<b>MT002</b>")])
        segunda = self.client.get(self.elegir, self.estado({ANIO: ([], [])}, tipo="meta", en=ANIO, solo="resultados",
                                                           pagina=2))
        self.assertContains(segunda, "51–100 de")
        vigencias = self.client.get(self.elegir, self.estado(tipo="vigencia", solo="resultados"))
        self.assertContains(vigencias, f"<b>{ANIO + 1}</b>")
        self.assertNotContains(vigencias, f"<b>{ANIO}</b>")

    def test_las_programadas_van_primero_en_el_listado_de_metas(self):
        meta_tardia = MetaIndicador.objects.order_by("-codigo").first()
        programado = ProgramacionProyectos.objects.get(bpin=self.proy.bpin)
        ProgramacionMeta.objects.create(proyecto=programado, meta=meta_tardia, vigencia=ANIO, meta_vigencia=D("1"))
        html = self.client.get(self.elegir, self.estado({ANIO: ([], [])}, tipo="meta", en=ANIO,
                                                        solo="resultados")).content.decode()
        primeras = html[:html.index("<b>MT002</b>")]
        self.assertIn(f"<b>{meta_tardia.codigo}</b>", primeras)


class Permisos(Base):
    def usuario(self, *codigos):
        u = get_user_model().objects.create_user("u" + "".join(codigos)[:20], "u@b.co", "clave", is_staff=True)
        u.user_permissions.add(*Permission.objects.filter(codename__in=codigos))
        self.client.force_login(u)
        return u

    def test_sin_permiso_no_entra_ni_ve_el_boton(self):
        self.usuario("view_proyecto")
        url = reverse("admin:siifweb_proyecto_programacion_financiera", args=(self.proy.pk,))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:siifweb_proyecto_change", args=(self.proy.pk,))), url)

    def test_solo_ver_consulta_pero_no_edita(self):
        self.programar("10")
        self.usuario("view_proyecto", "view_programacionfinanciera")
        url = reverse("admin:siifweb_proyecto_programacion_financiera", args=(self.proy.pk,))
        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'value="10"')
        self.assertNotContains(respuesta, "hx-post")
        self.assertNotContains(respuesta, ">Guardar<")
        guardar = reverse("admin:siifweb_proyecto_pf_guardar", args=(self.proy.pk,))
        casilla = f"v-{ANIO}-{self.fuente.pk}-{self.meta.pk}"
        respuesta = self.client.post(guardar, {"vigencias": [ANIO], f"fuentes-{ANIO}": [self.fuente.pk],
                                               f"metas-{ANIO}": [self.meta.pk], casilla: "5"})
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(ProgramacionFinanciera.objects.get().valor, D("10"))
