"""Validaciones de la distribucion y cambio de estado (fase 5 del CUIPO)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion, validacion
from cuipo.models import (CPC, ConceptoCUIPO, DetalleSectorial, DistribucionBPIN, LineaCUIPO, ProductoCUIPO,
                          TerceroCUIPO, VigenciaGasto)

from .fabricas import corte_con, fila, formular, homologar, listas_distribucion


BPIN = "202500000039332"


class Base(TestCase):
    """Un BPIN de un producto, con todo homologado: la precarga lo deja valido."""

    def setUp(self):
        listas_distribucion()
        formular(BPIN, "2201048")
        homologar("3", "1.2.4.1.01")
        self.corte = corte_con([fila(101, "2.3.2.02.02.009", Decimal("1000"), "3", "2", BPIN,
                                     obligacion=Decimal("800"), pago=Decimal("600"))], fecha_fin=date(2026, 9, 30))
        distribucion.precargar(self.corte)
        self.d = DistribucionBPIN.objects.get(bpin=BPIN)
        self.linea = self.d.lineas.get()
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")

    def errores(self):
        return [p.mensaje for p in validacion.validar_distribucion(self.d).errores]


class Validar(Base):
    def test_la_precarga_completa_es_valida(self):
        r = validacion.validar_distribucion(self.d)
        self.assertTrue(r.valida, [p.mensaje for p in r.errores])
        self.assertEqual(r.advertencias, [])

    def test_la_fila_debe_cuadrar_en_c_o_y_p(self):
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(compromisos=999)
        self.assertIn("2.3.2.02.02.009 · recurso 3 · CC 2: compromisos distribuidos 999,00 y en SIIFWEB 1.000,00 "
                      "(diferencia 1,00)", self.errores())

    def test_obligaciones_mayores_que_compromisos_en_una_celda(self):
        """Repartida en dos vigencias, una celda puede tener O > C aunque la fila cuadre."""
        v4 = VigenciaGasto.objects.get(codigo="4")
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(compromisos=900, obligaciones=200, pagos=100)
        LineaCUIPO.objects.create(distribucion=self.d, fila=self.linea.fila, producto=self.linea.producto,
                                  vigencia_gasto=v4, compromisos=100, obligaciones=600, pagos=500,
                                  cpc=self.linea.cpc, detalle_sectorial=self.linea.detalle_sectorial,
                                  tercero=self.linea.tercero, politica_publica=self.linea.politica_publica)
        errores = self.errores()
        self.assertTrue(any("vigencia 4: obligaciones (600,00) mayores que compromisos (100,00)" in e for e in errores))
        self.assertFalse(any("distribuidos" in e for e in errores))      # la fila si cuadra

    def test_pagos_mayores_que_obligaciones_y_negativos(self):
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(pagos=900)
        self.assertTrue(any("pagos (900,00) mayores que obligaciones (800,00)" in e for e in self.errores()))
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(pagos=-1)
        self.assertTrue(any("negativos" in e for e in self.errores()))

    def test_el_producto_debe_ser_del_bpin(self):
        otro = ProductoCUIPO.objects.get(codigo="2201006")
        self.d.productos.add(otro)
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(producto=otro)
        self.assertTrue(any("el producto no está programado en 2026 según la formulación PIIP" in e for e in self.errores()))

    def test_cualitativos_vacios_e_inactivos(self):
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(cpc=None, tercero=None)
        errores = self.errores()
        self.assertTrue(any("falta el CPC" in e for e in errores))
        self.assertTrue(any("falta el tercero" in e for e in errores))
        DetalleSectorial.objects.filter(codigo="0").update(activo=False)
        self.assertTrue(any("el detalle sectorial 0 está inactivo" in e for e in self.errores()))

    def test_cpc_cero_en_concepto_que_lo_exige_es_advertencia(self):
        ConceptoCUIPO.objects.filter(codigo="2.3.2.02.02.009").update(requiere_cpc=True)
        r = validacion.validar_distribucion(self.d)
        self.assertTrue(r.valida)
        self.assertEqual(len(r.advertencias), 1)
        self.assertIn("CPC 0 (no aplica) en un concepto que exige CPC", r.advertencias[0].mensaje)

    def test_lo_que_no_deriva_bloquea(self):
        from cuipo.models import HomologacionFuente
        HomologacionFuente.objects.all().delete()
        self.assertIn("Recurso 3: sin homologación de fuente para 2026", self.errores())

    def test_sin_productos_no_se_valida(self):
        DistribucionBPIN.objects.filter(pk=self.d.pk).update(regla=DistribucionBPIN.Regla.SIN_PRODUCTOS)
        self.d.refresh_from_db()
        self.assertTrue(any("no tiene productos en la lista CHIP" in e for e in self.errores()))

    def test_todo_el_corte(self):
        [(d, r)] = validacion.validar_corte(self.corte)
        self.assertEqual(d, self.d)
        self.assertTrue(r.valida)


class Estados(Base):
    def test_borrador_validado_enviado(self):
        validacion.cambiar_estado(self.d, "validado", self.usuario)
        self.d.refresh_from_db()
        self.assertEqual((self.d.estado, self.d.validado_por), ("validado", self.usuario))
        with self.assertRaisesMessage(ValueError, "no está en borrador"):
            distribucion.guardar_valor(self.d, self.linea.fila_id, self.linea.producto_id,
                                       self.linea.vigencia_gasto_id, "compromisos", "1")
        validacion.cambiar_estado(self.d, "enviado", self.usuario)
        with self.assertRaisesMessage(ValueError, "De enviado no se pasa a borrador"):
            validacion.cambiar_estado(self.d, "borrador")

    def test_volver_a_borrador_limpia_la_validacion(self):
        validacion.cambiar_estado(self.d, "validado", self.usuario)
        validacion.cambiar_estado(self.d, "borrador")
        self.d.refresh_from_db()
        self.assertEqual((self.d.estado, self.d.validado_por, self.d.fecha_validacion), ("borrador", None, None))

    def test_con_errores_no_se_valida(self):
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(compromisos=1)
        with self.assertRaisesMessage(ValueError, "No se puede validar: 2 errores"):   # no cuadra y O > C
            validacion.cambiar_estado(self.d, "validado", self.usuario)
        self.d.refresh_from_db()
        self.assertEqual(self.d.estado, "borrador")

    def test_de_borrador_no_se_pasa_a_enviado(self):
        with self.assertRaisesMessage(ValueError, "De borrador no se pasa a enviado"):
            validacion.cambiar_estado(self.d, "enviado")


class EnLaPantallaYElAdmin(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.pantalla = reverse("admin:cuipo_distribuir", args=(self.d.pk,))
        self.estado = reverse("admin:cuipo_distribuir_estado", args=(self.d.pk,))

    def test_validar_desde_la_pantalla(self):
        html = self.client.get(self.pantalla).content.decode()
        self.assertIn(": sin errores.", html)
        self.assertIn('aria-label="Qué se valida"', html)                    # las reglas, en un globo
        self.assertIn('aria-label="Estados de la distribución"', html)
        respuesta = self.client.post(self.estado, {"estado": "validado"}, follow=True)
        self.assertContains(respuesta, "La distribución quedó validado")
        self.assertContains(respuesta, "Marcar enviada")
        self.assertContains(respuesta, "Solo lectura")

    def test_con_errores_la_pantalla_lo_dice_y_no_valida(self):
        LineaCUIPO.objects.filter(pk=self.linea.pk).update(tercero=None)
        self.assertContains(self.client.get(self.pantalla), "1 errores")
        respuesta = self.client.post(self.estado, {"estado": "validado"}, follow=True)
        self.assertContains(respuesta, "No se puede validar")
        self.d.refresh_from_db()
        self.assertEqual(self.d.estado, "borrador")

    def test_una_edicion_actualiza_la_validacion_fuera_de_banda(self):
        respuesta = self.client.post(reverse("admin:cuipo_distribuir_celda", args=(self.d.pk,)), {
            "fila": self.linea.fila_id, "producto": self.linea.producto_id, "vigencia": self.linea.vigencia_gasto_id,
            "campo": "compromisos", "valor": "10"})
        html = respuesta.content.decode()
        self.assertIn('id="validacion" hx-swap-oob="true"', html)
        self.assertIn("compromisos distribuidos 10,00", html)

    def test_accion_validar_las_seleccionadas(self):
        respuesta = self.client.post(reverse("admin:cuipo_distribucionbpin_changelist"),
                                     {"action": "validar_seleccionadas", "_selected_action": [self.d.pk]}, follow=True)
        self.assertContains(respuesta, "Validadas: 1.")
        self.d.refresh_from_db()
        self.assertEqual(self.d.estado, "validado")

    def test_el_estado_en_el_formulario_solo_ofrece_lo_permitido(self):
        url = reverse("admin:cuipo_distribucionbpin_change", args=(self.d.pk,))
        html = self.client.get(url).content.decode()
        self.assertIn('value="validado"', html)
        self.assertNotIn('value="enviado"', html)
        self.assertIn("Sin errores.", html)


class ElegirCualitativos(Base):
    """La ventana para elegir CPC, detalle sectorial, tercero o politica publica."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.url = reverse("admin:cuipo_distribuir_elegir", args=(self.d.pk,))

    def test_la_celda_muestra_codigo_descripcion_y_elegir(self):
        html = self.client.get(reverse("admin:cuipo_distribuir", args=(self.d.pk,))).content.decode()
        self.assertIn(f"campo=detalle_sectorial&linea={self.linea.pk}", html)
        self.assertIn("<b>0</b>", html)
        self.assertIn('title="NO APLICA">NO APLICA</span>', html)

    def test_la_ventana_lista_con_la_descripcion_completa(self):
        larga = "SPC - E4 ATENCIÓN PRIMARIA SALUD - L1 DESARROLLO INSTITUCIONAL Y SECTORIAL - DESARROLLO DE CAPACIDADES"
        DetalleSectorial.objects.create(codigo="19.02.01", descripcion=larga, version=self.linea.detalle_sectorial.version)
        respuesta = self.client.get(self.url, {"campo": "detalle_sectorial", "linea": self.linea.pk})
        self.assertContains(respuesta, "Elegir detalle sectorial")
        self.assertContains(respuesta, larga)
        self.assertContains(respuesta, 'class="opcion actual"')

    def test_buscar_por_codigo_o_palabras(self):
        datos = {"campo": "cpc", "linea": self.linea.pk, "solo": "resultados"}
        respuesta = self.client.get(self.url, {**datos, "codigo": "otros servicios"})
        self.assertContains(respuesta, "<b>85999</b>")
        self.assertNotContains(respuesta, "Elegir CPC")             # solo la lista
        self.assertContains(self.client.get(self.url, {**datos, "codigo": "859"}), "<b>85999</b>")
        self.assertContains(self.client.get(self.url, {**datos, "codigo": "nada parecido"}), "Nada coincide")
        TerceroCUIPO.objects.filter(codigo="220170001").update(activo=False)
        self.assertNotContains(self.client.get(self.url, {"campo": "tercero", "linea": self.linea.pk, "codigo": "2201"}),
                               "220170001")
        self.assertEqual(self.client.get(self.url, {"campo": "otro", "linea": self.linea.pk}).status_code, 400)

    def test_elegir_guarda_el_codigo(self):
        respuesta = self.client.post(reverse("admin:cuipo_distribuir_cualitativo", args=(self.d.pk,)),
                                     {"linea": self.linea.pk, "campo": "cpc", "codigo": "85999"})
        self.assertEqual(respuesta.status_code, 200)
        self.linea.refresh_from_db()
        self.assertEqual((self.linea.cpc, self.linea.origen_cpc), (CPC.objects.get(codigo="85999"), "manual"))

    def test_cambiar_la_vigencia_de_la_linea_con_el_buscador(self):
        respuesta = self.client.get(self.url, {"campo": "vigencia_gasto", "linea": self.linea.pk})
        self.assertContains(respuesta, "Elegir vigencia del gasto")
        self.assertContains(respuesta, "VIGENCIAS FUTURAS - VIGENCIA ACTUAL")
        self.client.post(reverse("admin:cuipo_distribuir_cualitativo", args=(self.d.pk,)),
                         {"linea": self.linea.pk, "campo": "vigencia_gasto", "codigo": "4"})
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.vigencia_gasto.codigo, "4")

    def test_repartir_en_otra_vigencia_con_el_buscador(self):
        datos = {"campo": "vigencia_gasto", "fila": self.linea.fila_id, "producto": self.linea.producto_id}
        respuesta = self.client.get(self.url, datos)
        self.assertContains(respuesta, "Repartir en otra vigencia del gasto")
        self.assertContains(respuesta, "<b>4</b>")
        self.assertNotContains(respuesta, "<b>1</b>")                    # ya la tiene
        self.client.post(reverse("admin:cuipo_distribuir_vigencia", args=(self.d.pk,)),
                         {**datos, "vigencia": VigenciaGasto.objects.get(codigo="4").pk})
        self.assertEqual(sorted(self.d.lineas.values_list("vigencia_gasto__codigo", flat=True)), ["1", "4"])
        self.assertContains(self.client.get(self.url, datos), "No hay opciones disponibles")
        # La linea en 4 no puede pasar a 1: ya hay una
        respuesta = self.client.post(reverse("admin:cuipo_distribuir_cualitativo", args=(self.d.pk,)),
                                     {"linea": self.d.lineas.get(vigencia_gasto__codigo="4").pk,
                                      "campo": "vigencia_gasto", "codigo": "1"})
        self.assertContains(respuesta, "Ya hay una línea de ese producto con la vigencia 1")

