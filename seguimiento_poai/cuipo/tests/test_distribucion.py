"""Distribucion por BPIN y precarga (fase 3 del CUIPO)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion, ejecucion
from cuipo.models import (CPC, ConceptoCUIPO, CorteEjecucionGastos, DetalleSectorial, DistribucionBPIN,
                          HomologacionRubro, LineaCUIPO,
                          PoliticaPublica, ProductoCUIPO, ReglaTercero, TerceroCUIPO, VersionListas, VigenciaGasto,
                          periodo_de)
from siifweb.models import (CentroCosto, FormulacionProyecto, IndicadorCatalogo, IndicadorProyecto,
                            ProductoCatalogo, Rubro)

from .test_derivacion import corte_con, homologar, listas
from .test_ejecucion_gastos import fila

PRODUCTOS = ("0", "2201006", "2201048", "1906005", "1906030", "4502034", "4502038", "3301053")


def listas_distribucion():
    v = listas()
    for codigo in PRODUCTOS:
        ProductoCUIPO.objects.create(codigo=codigo, descripcion="NO APLICA" if codigo == "0" else f"Producto {codigo}",
                                     version=v)
    for codigo, texto in (("1", "VIGENCIA ACTUAL"), ("4", "VIGENCIAS FUTURAS - VIGENCIA ACTUAL")):
        VigenciaGasto.objects.create(codigo=codigo, descripcion=texto, version=v)
    CPC.objects.create(codigo="0", descripcion="No aplica", version=v)
    CPC.objects.create(codigo="85999", descripcion="Otros servicios", version=v)
    DetalleSectorial.objects.create(codigo="0", descripcion="NO APLICA", version=v)
    PoliticaPublica.objects.create(codigo="0", descripcion="NO APLICA", version=v)
    return v


def formular(bpin, *productos):
    """La formulacion PIIP del BPIN con un indicador por producto."""
    f = FormulacionProyecto.objects.create(bpin=bpin, nombre=f"Proyecto {bpin}")
    for codigo in productos:
        producto, _ = ProductoCatalogo.objects.get_or_create(codigo=codigo, defaults={"nombre": f"Producto {codigo}"})
        indicador, _ = IndicadorCatalogo.objects.get_or_create(codigo=f"{codigo}00",
                                                               defaults={"producto": producto, "nombre": "Indicador"})
        IndicadorProyecto.objects.create(formulacion=f, indicador=indicador)
    return f


def corte_t3():
    """Los casos del plan con las cifras al 30/09/2026."""
    return corte_con([
        fila(101, "2.3.2.02.02.009", Decimal("1054759012"), "3", "2", "202500000039332",
             obligacion=Decimal("834182726")),
        fila(102, "2.3.2.01.01.001.02.08", Decimal("6016089072.27"), "7", "16", "2023002700021",
             obligacion=Decimal("6015697203.50")),
        fila(102, "2.3.2.01.01.001.02.08", Decimal("1027664538.50"), "114", "3", "2023002700021",
             obligacion=Decimal("1014627682")),
        fila(101, "2.3.2.02.02.009", Decimal("2979309905"), "35", "19", "202500000029628",
             obligacion=Decimal("2010861681.15")),
        fila(101, "2.3.2.02.02.009", Decimal("1000000000"), "54", "19", "202500000029628"),
        fila(101, "2.3.2.02.02.009", Decimal("425784947"), "125", "19", "202500000029628",
             obligacion=Decimal("314670429.87")),
        fila(103, "2.3.3.05.09.054", Decimal("40000000"), "108", "10", "202600000018441"),
        fila(104, "2.3.7.05.03", Decimal("389231271"), "128", "1", "0"),
        fila(105, "2.3.2.02.02.009", Decimal("5000"), "1", "2", "202600000099999"),     # sin PIIP
    ], fecha_fin=date(2026, 9, 30))


class PeriodoDelCorte(TestCase):
    def corte(self, inicio, fin, vigencia=2026):
        return CorteEjecucionGastos(vigencia=vigencia, fecha_inicio=inicio, fecha_fin=fin)

    def test_trimestres(self):
        self.assertEqual(periodo_de(self.corte(date(2026, 1, 1), date(2026, 9, 30))), "10909")
        self.assertEqual(periodo_de(self.corte(date(2026, 1, 1), date(2026, 12, 31))), "11212")
        self.assertEqual(periodo_de(self.corte(date(2026, 1, 1), date(2026, 3, 31))), "10303")

    def test_lo_que_no_es_un_trimestre_acumulado(self):
        self.assertIsNone(periodo_de(self.corte(date(2026, 1, 1), date(2026, 11, 11))))
        self.assertIsNone(periodo_de(self.corte(date(2026, 7, 1), date(2026, 9, 30))))
        self.assertIsNone(periodo_de(self.corte(date(2026, 1, 1), date(2026, 9, 29))))


class Precarga(TestCase):
    def setUp(self):
        listas_distribucion()
        formular("202500000039332", "2201006", "2201048")
        formular("2023002700021", "1906005", "1906030")
        formular("202500000029628", "4502034", "4502038")
        formular("202600000018441", "3301053")
        ReglaTercero.objects.create(centro_costo=CentroCosto.objects.get(codigo="10"),
                                    tercero=TerceroCUIPO.objects.get(codigo="220170001"))
        HomologacionRubro.objects.create(rubro=Rubro.objects.get(codigo="2.3.3.05.09.054"),
                                         concepto=ConceptoCUIPO.objects.get(codigo="2.3.3.05.09.099"))
        self.corte = corte_t3()
        self.mensaje = distribucion.precargar(self.corte)

    def dist(self, bpin):
        return DistribucionBPIN.objects.get(corte=self.corte, bpin=bpin)

    def test_resumen(self):
        self.assertEqual(self.mensaje, "Periodo 10909: 6 distribuciones nuevas y 2 líneas (1 un producto (100 %), "
                                       "1 varios productos y una fuente (por digitar), 2 manuales, "
                                       "1 sin BPIN (producto 0), 1 sin productos en la lista CHIP)")
        self.assertEqual(set(DistribucionBPIN.objects.values_list("periodo", flat=True)), {"10909"})

    def test_202500000039332_queda_por_digitar_desde_el_piip(self):
        d = self.dist("202500000039332")
        self.assertEqual(d.regla, DistribucionBPIN.Regla.PIIP)
        self.assertEqual(sorted(d.productos.values_list("codigo", flat=True)), ["2201006", "2201048"])
        self.assertFalse(d.lineas.exists())
        self.assertEqual(d.asociaciones.count(), 2)
        self.assertFalse(distribucion.cuadre(d)[0]["cuadra"])

    def test_varios_productos_y_varias_fuentes_es_manual(self):
        for bpin in ("2023002700021", "202500000029628"):
            with self.subTest(bpin=bpin):
                d = self.dist(bpin)
                self.assertEqual(d.regla, DistribucionBPIN.Regla.MANUAL)
                self.assertFalse(d.lineas.exists())
        self.assertEqual(self.dist("202500000029628").asociaciones.count(), 6)    # 3 filas x 2 productos

    def test_202600000018441_un_producto_al_100(self):
        d = self.dist("202600000018441")
        self.assertEqual(d.regla, DistribucionBPIN.Regla.UN_PRODUCTO)
        [linea] = d.lineas.all()
        self.assertEqual((linea.producto.codigo, linea.vigencia_gasto.codigo, linea.compromisos, linea.obligaciones,
                          linea.pagos, linea.origen_valores),
                         ("3301053", "1", Decimal("40000000"), Decimal("40000000"), Decimal("40000000"), "siifweb"))
        self.assertEqual((linea.tercero.codigo, linea.origen_tercero), ("220170001", "regla"))
        self.assertEqual((linea.cpc.codigo, linea.detalle_sectorial.codigo, linea.politica_publica.codigo),
                         ("0", "0", "0"))
        self.assertTrue(all(f["cuadra"] for f in distribucion.cuadre(d)))

    def test_sin_bpin_va_al_producto_cero(self):
        d = self.dist("0")
        self.assertEqual(d.regla, DistribucionBPIN.Regla.SIN_BPIN)
        self.assertEqual(d.lineas.get().producto.codigo, "0")
        self.assertTrue(all(f["cuadra"] for f in distribucion.cuadre(d)))

    def test_sin_formulacion_no_se_distribuye(self):
        d = self.dist("202600000099999")
        self.assertEqual((d.regla, d.observacion), (DistribucionBPIN.Regla.SIN_PRODUCTOS,
                                                     "El BPIN no tiene formulación PIIP."))

    def test_precargar_otra_vez_no_toca_lo_que_existe(self):
        linea = self.dist("202600000018441").lineas.get()
        LineaCUIPO.objects.filter(pk=linea.pk).update(compromisos=1)
        mensaje = distribucion.precargar(self.corte)
        self.assertEqual(mensaje, "Periodo 10909: 0 distribuciones nuevas y 0 líneas (6 ya estaban)")
        self.assertEqual(LineaCUIPO.objects.get(pk=linea.pk).compromisos, 1)

    def test_volver_a_precargar_un_borrador(self):
        d = self.dist("202600000018441")
        d.lineas.update(compromisos=1)
        distribucion.precargar_de_nuevo(d)
        self.assertEqual(self.dist("202600000018441").lineas.get().compromisos, Decimal("40000000"))
        enviada = self.dist("0")
        enviada.estado = DistribucionBPIN.Estado.ENVIADO
        enviada.save()
        with self.assertRaisesMessage(ValueError, "solo se vuelve a precargar una distribución en borrador"):
            distribucion.precargar_de_nuevo(enviada)

    def test_el_corte_con_distribuciones_no_se_reprocesa_ni_se_borra(self):
        with self.assertRaises(ejecucion.CorteConDistribucion):
            ejecucion.procesar(self.corte)
        self.assertEqual(self.corte.filas_ejecucion.count(), 9)
        with self.assertRaises(ProtectedError):
            self.corte.delete()

    def test_una_fila_se_reparte_entre_vigencias_de_gasto(self):
        d = self.dist("202500000039332")
        f = d.filas().get()
        producto = ProductoCUIPO.objects.get(codigo="2201048")
        vigencias = {v.codigo: v for v in VigenciaGasto.objects.all()}
        LineaCUIPO.objects.create(distribucion=d, fila=f, producto=producto, vigencia_gasto=vigencias["1"],
                                  compromisos=Decimal("717349192"))
        LineaCUIPO.objects.create(distribucion=d, fila=f, producto=producto, vigencia_gasto=vigencias["4"],
                                  compromisos=Decimal("337409820"))
        self.assertEqual(distribucion.cuadre(d)[0]["diferencia"][0], Decimal("0"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            LineaCUIPO.objects.create(distribucion=d, fila=f, producto=producto, vigencia_gasto=vigencias["1"])

    def test_la_linea_debe_ser_de_una_fila_del_bpin(self):
        d = self.dist("202500000039332")
        otra = self.corte.filas_ejecucion.get(proyecto="202600000018441")
        linea = LineaCUIPO(distribucion=d, fila=otra, producto=ProductoCUIPO.objects.get(codigo="2201006"),
                           vigencia_gasto=VigenciaGasto.objects.get(codigo="1"))
        with self.assertRaises(ValidationError):
            linea.clean()

    def test_concepto_que_exige_cpc_queda_sin_cpc(self):
        ConceptoCUIPO.objects.filter(codigo="2.3.3.05.09.099").update(requiere_cpc=True)
        d = self.dist("202600000018441")
        distribucion.precargar_de_nuevo(d)
        linea = self.dist("202600000018441").lineas.get()
        self.assertIsNone(linea.cpc)
        self.assertEqual(linea.origen_cpc, "")


class PrecargaSinPeriodo(TestCase):
    def test_un_corte_que_no_cierra_trimestre_no_se_precarga(self):
        listas_distribucion()
        corte = corte_con([fila(101, "2.3.7.05.03", 10, "128", "1", "0")])
        corte.fecha_fin = date(2026, 9, 29)
        corte.save()
        with self.assertRaisesMessage(ValueError, "cierre de un trimestre"):
            distribucion.precargar(corte)
        self.assertFalse(DistribucionBPIN.objects.exists())


class Antecedente(TestCase):
    def test_los_cualitativos_salen_de_la_distribucion_enviada_del_trimestre_anterior(self):
        listas_distribucion()
        formular("202500000039332", "2201048")
        detalle = DetalleSectorial.objects.create(codigo="22.01.01", descripcion="PERSONAL-DOCENTES",
                                                  version=VersionListas.objects.get())
        t2 = corte_con([fila(101, "2.3.2.02.02.009", 100, "3", "2", "202500000039332")])
        t2.fecha_fin = date(2026, 6, 30)
        t2.save()
        distribucion.precargar(t2)
        anterior = DistribucionBPIN.objects.get(corte=t2)
        anterior.lineas.update(cpc=CPC.objects.get(codigo="85999"), detalle_sectorial=detalle)
        anterior.estado = DistribucionBPIN.Estado.ENVIADO
        anterior.save()
        t3 = corte_con([fila(101, "2.3.2.02.02.009", 300, "3", "2", "202500000039332")], fecha_fin=date(2026, 9, 30))
        distribucion.precargar(t3)
        linea = DistribucionBPIN.objects.get(corte=t3).lineas.get()
        self.assertEqual((linea.cpc.codigo, linea.origen_cpc), ("85999", "antecedente"))
        self.assertEqual((linea.detalle_sectorial.codigo, linea.origen_detalle_sectorial), ("22.01.01", "antecedente"))
        self.assertEqual(linea.compromisos, Decimal("300"))       # los valores no se copian


class AdminDeLaDistribucion(TestCase):
    def setUp(self):
        listas_distribucion()
        formular("202600000018441", "3301053")
        formular("202500000039332", "2201006", "2201048")
        homologar("108", "1.3.3.3.20")
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")
        self.client.force_login(self.usuario)
        self.corte = corte_t3()

    def test_precargar_desde_los_cortes(self):
        respuesta = self.client.post(reverse("admin:cuipo_corteejecuciongastos_changelist"),
                                     {"action": "precargar_distribucion", "_selected_action": [self.corte.pk]},
                                     follow=True)
        self.assertContains(respuesta, "Periodo 10909")
        self.assertEqual(DistribucionBPIN.objects.count(), 6)
        cambio = reverse("admin:cuipo_corteejecuciongastos_change", args=(self.corte.pk,))
        self.assertNotContains(self.client.get(cambio), reverse("admin:cuipo_corteejecuciongastos_delete",
                                                                args=(self.corte.pk,)))

    def test_digitar_una_linea_la_marca_manual_y_validar_registra_quien(self):
        distribucion.precargar(self.corte)
        d = DistribucionBPIN.objects.get(bpin="202500000039332")
        url = reverse("admin:cuipo_distribucionbpin_change", args=(d.pk,))
        self.assertContains(self.client.get(url), "Cuadre con SIIFWEB")
        f = d.filas().get()
        datos = {
            "estado": "validado",
            "lineas-TOTAL_FORMS": "2", "lineas-INITIAL_FORMS": "0", "lineas-MIN_NUM_FORMS": "0",
            "lineas-MAX_NUM_FORMS": "1000", "_save": "Guardar",
        }
        for i, (producto, valor) in enumerate((("2201048", "717349192"), ("2201006", "337409820"))):
            datos.update({f"lineas-{i}-fila": f.pk, f"lineas-{i}-producto": ProductoCUIPO.objects.get(codigo=producto).pk,
                          f"lineas-{i}-vigencia_gasto": VigenciaGasto.objects.get(codigo="1").pk,
                          f"lineas-{i}-compromisos": valor, f"lineas-{i}-obligaciones": "0", f"lineas-{i}-pagos": "0",
                          f"lineas-{i}-cpc": CPC.objects.get(codigo="0").pk})
        respuesta = self.client.post(url, datos)
        self.assertEqual(respuesta.status_code, 302, respuesta.content.decode()[:2000])
        d.refresh_from_db()
        self.assertEqual((d.estado, d.validado_por), ("validado", self.usuario))
        self.assertEqual(set(d.lineas.values_list("origen_valores", "origen_cpc")), {("manual", "manual")})
        self.assertEqual(distribucion.cuadre(d)[0]["diferencia"][0], Decimal("0"))

    def test_la_lista_abre(self):
        distribucion.precargar(self.corte)
        respuesta = self.client.get(reverse("admin:cuipo_distribucionbpin_changelist"))
        self.assertContains(respuesta, "202600000018441")
        self.assertContains(respuesta, "Inversión sin proyecto")
