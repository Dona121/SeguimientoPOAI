"""La pantalla por BPIN y su logica de edicion (fase 4 del CUIPO)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion
from cuipo.models import (CPC, DistribucionBPIN, LineaCUIPO, ProductoCUIPO, TerceroCUIPO, VigenciaGasto)

from .test_derivacion import corte_con
from .test_distribucion import corte_t3, formular, listas_distribucion
from .test_ejecucion_gastos import fila


class Repartir(TestCase):
    def test_suma_exacta_con_mayor_residuo(self):
        partes = distribucion.repartir(Decimal("100"), [1, 1, 1])
        self.assertEqual(sum(partes), Decimal("100"))
        self.assertEqual(sorted(partes), [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])

    def test_a_enteros(self):
        self.assertEqual(distribucion.repartir(Decimal("10"), [2, 1], decimales=0), [Decimal("7"), Decimal("3")])

    def test_sin_pesos(self):
        with self.assertRaises(ValueError):
            distribucion.repartir(Decimal("10"), [0, 0])


class Edicion(TestCase):
    def setUp(self):
        listas_distribucion()
        formular("202500000039332", "2201006", "2201048")
        formular("202500000029628", "4502034", "4502038")
        self.corte = corte_t3()
        distribucion.precargar(self.corte)
        self.vig1 = VigenciaGasto.objects.get(codigo="1")
        self.vig4 = VigenciaGasto.objects.get(codigo="4")

    def dist(self, bpin):
        return DistribucionBPIN.objects.get(corte=self.corte, bpin=bpin)

    def p(self, codigo):
        return ProductoCUIPO.objects.get(codigo=codigo).pk

    def test_202500000039332_digitar_desde_el_piip(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        for producto, c, o in (("2201048", "717349192", "567333673.07"), ("2201006", "337.409.820,00", "266849052,93")):
            distribucion.guardar_valor(d, f.pk, self.p(producto), self.vig1.pk, "compromisos", c)
            distribucion.guardar_valor(d, f.pk, self.p(producto), self.vig1.pk, "obligaciones", o)
            distribucion.guardar_valor(d, f.pk, self.p(producto), self.vig1.pk, "pagos", o)
        self.assertEqual(set(d.lineas.values_list("origen_valores", flat=True)), {"piip"})
        self.assertTrue(distribucion.matriz(d)[0]["cuadra"])

    def test_repartir_una_fila_entre_vigencias(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        distribucion.guardar_valor(d, f.pk, self.p("2201048"), self.vig1.pk, "compromisos", "1000")
        distribucion.agregar_vigencia(d, f.pk, self.p("2201048"), self.vig4.pk)
        self.assertEqual(sorted(d.lineas.values_list("vigencia_gasto__codigo", flat=True)), ["1", "4"])
        with self.assertRaisesMessage(ValueError, "Ya hay una línea"):
            distribucion.agregar_vigencia(d, f.pk, self.p("2201048"), self.vig4.pk)

    def test_cualitativos_por_codigo(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        distribucion.guardar_valor(d, f.pk, self.p("2201048"), self.vig1.pk, "compromisos", "1")
        linea = d.lineas.get()
        distribucion.cambiar_cualitativo(d, linea.pk, "cpc", "85999")
        linea.refresh_from_db()
        self.assertEqual((linea.cpc.codigo, linea.origen_cpc), ("85999", "manual"))
        with self.assertRaisesMessage(ValueError, "99999: no está en la lista CHIP"):
            distribucion.cambiar_cualitativo(d, linea.pk, "tercero", "99999")
        TerceroCUIPO.objects.filter(codigo="23900000").update(activo=False)
        with self.assertRaisesMessage(ValueError, "inactivo"):
            distribucion.cambiar_cualitativo(d, linea.pk, "tercero", "23900000")
        distribucion.cambiar_cualitativo(d, linea.pk, "cpc", "")
        linea.refresh_from_db()
        self.assertEqual((linea.cpc, linea.origen_cpc), (None, ""))

    def test_desasociar_borra_las_lineas(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        distribucion.guardar_valor(d, f.pk, self.p("2201048"), self.vig1.pk, "compromisos", "1000")
        distribucion.asociar(d, f.pk, self.p("2201048"), False)
        self.assertFalse(d.lineas.exists())
        self.assertFalse(d.asociaciones.filter(producto__codigo="2201048").exists())

    def test_lo_que_no_se_puede(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        with self.assertRaisesMessage(ValueError, "negativo"):
            distribucion.guardar_valor(d, f.pk, self.p("2201048"), self.vig1.pk, "compromisos", "-5")
        with self.assertRaisesMessage(ValueError, "El producto no es de este BPIN"):
            distribucion.guardar_valor(d, f.pk, self.p("4502038"), self.vig1.pk, "compromisos", "5")
        otra = self.corte.filas_ejecucion.get(proyecto="202500000029628", recurso="35")
        with self.assertRaisesMessage(ValueError, "La fila no es de este BPIN"):
            distribucion.guardar_valor(d, otra.pk, self.p("2201048"), self.vig1.pk, "compromisos", "5")
        d.estado = DistribucionBPIN.Estado.VALIDADO
        d.save()
        with self.assertRaisesMessage(ValueError, "no está en borrador"):
            distribucion.guardar_valor(d, f.pk, self.p("2201048"), self.vig1.pk, "compromisos", "5")



class Antecedente(TestCase):
    def test_la_distribucion_enviada_del_periodo_anterior(self):
        listas_distribucion()
        formular("202500000039332", "2201006", "2201048")
        t2 = corte_con([fila(101, "2.3.2.02.02.009", 100, "3", "2", "202500000039332")], fecha_fin=date(2026, 6, 30))
        distribucion.precargar(t2)
        d2 = DistribucionBPIN.objects.get(corte=t2)
        f = d2.filas().get()
        v1 = VigenciaGasto.objects.get(codigo="1").pk
        distribucion.guardar_valor(d2, f.pk, ProductoCUIPO.objects.get(codigo="2201048").pk, v1, "compromisos", "75")
        distribucion.guardar_valor(d2, f.pk, ProductoCUIPO.objects.get(codigo="2201006").pk, v1, "compromisos", "25")
        d2.estado = DistribucionBPIN.Estado.ENVIADO
        d2.save()
        t3 = corte_con([fila(101, "2.3.2.02.02.009", 300, "3", "2", "202500000039332")], fecha_fin=date(2026, 9, 30))
        distribucion.precargar(t3)
        anterior, filas = distribucion.antecedente(DistribucionBPIN.objects.get(corte=t3))
        self.assertEqual(anterior, d2)
        self.assertEqual([(c, v, p) for c, _, v, p in filas],
                         [("2201006", Decimal("25"), Decimal("25")), ("2201048", Decimal("75"), Decimal("75"))])
        self.assertFalse(DistribucionBPIN.objects.get(corte=t3).lineas.exists())     # no se copia


class Pantalla(TestCase):
    def setUp(self):
        listas_distribucion()
        formular("202500000039332", "2201006", "2201048")
        self.corte = corte_t3()
        distribucion.precargar(self.corte)
        self.d = DistribucionBPIN.objects.get(corte=self.corte, bpin="202500000039332")
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")
        self.client.force_login(self.usuario)
        self.url = reverse("admin:cuipo_distribuir", args=(self.d.pk,))

    def celda(self, valor="1"):
        return {"fila": self.d.filas().get().pk, "producto": ProductoCUIPO.objects.get(codigo="2201048").pk,
                "vigencia": VigenciaGasto.objects.get(codigo="1").pk, "campo": "compromisos", "valor": valor}

    def test_la_pantalla_abre(self):
        respuesta = self.client.get(self.url)
        self.assertNotContains(respuesta, "Proporcional a compromisos")     # el reparto es manual
        self.assertContains(respuesta, "2.3.2.02.02.009")
        self.assertContains(respuesta, 'id="elegir"')
        largo = "Servicio de apoyo financiero para la implementación de proyectos en materia educativa y de bienestar"
        ProductoCUIPO.objects.filter(codigo="2201048").update(descripcion=largo)
        self.assertContains(self.client.get(self.url), largo, count=None)      # el nombre completo, sin recortar
        self.assertContains(respuesta, 'id="fila-')
        self.assertContains(respuesta, "X-CSRFToken")
        self.assertContains(self.client.get(reverse("admin:cuipo_distribucionbpin_changelist")), self.url)

    def test_digitar_una_celda_devuelve_la_fila_y_los_totales(self):
        f = self.d.filas().get()
        respuesta = self.client.post(reverse("admin:cuipo_distribuir_celda", args=(self.d.pk,)), {
            "fila": f.pk, "producto": ProductoCUIPO.objects.get(codigo="2201048").pk,
            "vigencia": VigenciaGasto.objects.get(codigo="1").pk, "campo": "compromisos", "valor": "717349192"},
            HTTP_HX_REQUEST="true")
        html = respuesta.content.decode()
        self.assertIn(f'id="fila-{f.pk}"', html)
        self.assertIn('hx-swap-oob="true"', html)
        self.assertIn("diferencia 337.409.820,00", html)
        self.assertEqual(self.d.lineas.get().compromisos, Decimal("717349192"))

    def test_un_error_se_muestra_en_la_fila(self):
        f = self.d.filas().get()
        respuesta = self.client.post(reverse("admin:cuipo_distribuir_celda", args=(self.d.pk,)), {
            "fila": f.pk, "producto": ProductoCUIPO.objects.get(codigo="2201048").pk,
            "vigencia": VigenciaGasto.objects.get(codigo="1").pk, "campo": "compromisos", "valor": "-1"})
        self.assertContains(respuesta, "El valor no puede ser negativo")
        self.assertFalse(self.d.lineas.exists())

    def test_validada_es_solo_lectura(self):
        self.d.estado = DistribucionBPIN.Estado.VALIDADO
        self.d.save()
        self.assertContains(self.client.get(self.url), "Solo lectura")
        self.assertEqual(self.client.post(reverse("admin:cuipo_distribuir_celda", args=(self.d.pk,)),
                                          self.celda()).status_code, 403)

    def test_sin_permisos_del_cuipo_403(self):
        otro = User.objects.create_user("consulta", "c@example.com", "clave", is_staff=True)
        otro.user_permissions.add(Permission.objects.get(codename="view_proyecto"))
        self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_solo_ver_no_deja_editar(self):
        lector = User.objects.create_user("lector", "l@example.com", "clave", is_staff=True)
        lector.user_permissions.add(Permission.objects.get(codename="view_distribucionbpin"))
        self.client.force_login(lector)
        self.assertContains(self.client.get(self.url), "Solo lectura")
        self.assertEqual(self.client.post(reverse("admin:cuipo_distribuir_celda", args=(self.d.pk,)),
                                          self.celda()).status_code, 403)

    def test_la_lista_vacia_explica_como_se_crean(self):
        DistribucionBPIN.objects.all().delete()
        self.assertContains(self.client.get(reverse("admin:cuipo_distribucionbpin_changelist"), follow=True),
                            "Precargar la distribución del CUIPO")
