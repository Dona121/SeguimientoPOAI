"""Plano CHIP del CUIPO (fase 6)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion, plano, validacion
from cuipo.models import (ConceptoCUIPO, DistribucionBPIN, FuenteCUIPO, HomologacionFuente, HomologacionRubro,
                          ProductoCUIPO, ReglaTercero, TerceroCUIPO, VersionListas, VigenciaGasto)
from siifweb.models import CentroCosto, Fuente, Rubro

from .test_derivacion import corte_con
from .test_distribucion import formular, listas_distribucion
from .test_ejecucion_gastos import fila

D = Decimal
ENCABEZADO = "S\t117070000\t10909\t2026\tD_EJECUCION_DE_GASTOS"


def preparar():
    """Listas, homologaciones y un corte al 30/09 con los casos del plan."""
    listas_distribucion()
    v = VersionListas.objects.get()
    ConceptoCUIPO.objects.create(codigo="2.3.7.05.03", descripcion="Pago de deficit", nivel="D",
                                 habilitado_departamentos=True, version=v)
    for codigo in ("1.3.2.3.11", "1.2.3.2.06", "1.3.3.4.01", "1.2.3.1.19"):
        FuenteCUIPO.objects.create(codigo=codigo, descripcion=f"Fuente {codigo}", version=v)
    for codigo in ("35", "54", "125", "128"):
        Fuente.objects.create(codigo=codigo, nombre=f"Recurso {codigo}")
    for codigo in ("19", "1"):
        CentroCosto.objects.get_or_create(codigo=codigo, defaults={"nombre": f"Centro {codigo}"})
    for recurso, fuente in (("108", "1.3.3.3.20"), ("35", "1.3.3.4.01"), ("54", "1.3.2.3.11"),
                            ("125", "1.3.2.3.11"), ("128", "1.2.3.1.19")):
        HomologacionFuente.objects.create(fuente_siifweb=Fuente.objects.get(codigo=recurso), vigencia=2026,
                                          fuente_cuipo=FuenteCUIPO.objects.get(codigo=fuente))
    HomologacionRubro.objects.create(rubro=Rubro.objects.get(codigo="2.3.3.05.09.054"),
                                     concepto=ConceptoCUIPO.objects.get(codigo="2.3.3.05.09.099"))
    ReglaTercero.objects.create(centro_costo=CentroCosto.objects.get(codigo="10"),
                                tercero=TerceroCUIPO.objects.get(codigo="220170001"))
    formular("202500000029628", "4502034", "4502038")
    formular("202600000018441", "3301053")
    corte = corte_con([
        fila(101, "2.3.2.02.02.009", D("2979309905"), "35", "19", "202500000029628", obligacion=D("2010861681.15")),
        fila(101, "2.3.2.02.02.009", D("1000000000"), "54", "19", "202500000029628"),
        fila(101, "2.3.2.02.02.009", D("425784947"), "125", "19", "202500000029628", obligacion=D("314670429.87")),
        fila(103, "2.3.3.05.09.054", D("40000000"), "108", "10", "202600000018441"),
        fila(104, "2.3.7.05.03", D("389231271"), "128", "1", "0"),
    ], fecha_fin=date(2026, 9, 30))
    distribucion.precargar(corte)
    return corte


def distribuir_manual(corte):
    """202500000029628: cada fila mitad y mitad entre sus dos productos, con centavos; el
    recurso 54 lleva una parte en vigencia futura (4)."""
    d = DistribucionBPIN.objects.get(corte=corte, bpin="202500000029628")
    p34, p38 = (ProductoCUIPO.objects.get(codigo=c).pk for c in ("4502034", "4502038"))
    v1, v4 = (VigenciaGasto.objects.get(codigo=c).pk for c in ("1", "4"))
    reparto = {
        "35": [(p34, v1, "1489654952.50", "1005430840.58"), (p38, v1, "1489654952.50", "1005430840.57")],
        "54": [(p34, v1, "600000000", "600000000"), (p38, v4, "400000000", "400000000")],
        "125": [(p34, v1, "212892473.50", "157335214.94"), (p38, v1, "212892473.50", "157335214.93")],
    }
    for f in d.filas():
        for producto, vigencia, c, o in reparto[f.recurso]:
            for campo, valor in (("compromisos", c), ("obligaciones", o), ("pagos", o)):
                distribucion.guardar_valor(d, f.pk, producto, vigencia, campo, valor)
    return d


def lineas_d(texto):
    return [r.split("\t") for r in texto.splitlines() if r.startswith("D\t")]


class Generar(TestCase):
    def setUp(self):
        self.corte = preparar()
        self.d = distribuir_manual(self.corte)
        self.texto = plano.generar(self.corte)
        self.lineas = lineas_d(self.texto)
        self.detalle = [l for l in self.lineas if any(l[4:12])]

    def test_encabezado_y_campos(self):
        self.assertEqual(self.texto.splitlines()[0], ENCABEZADO)
        self.assertTrue(all(len(l) == 15 for l in self.lineas))
        resumen = [l for l in self.lineas if not any(l[4:12])]
        self.assertTrue(all(l[4:12] == [""] * 8 for l in resumen))
        self.assertIn("\r\n", self.texto)

    def test_detalle_de_202600000018441(self):
        [linea] = [l for l in self.detalle if l[8] == "202600000018441"]
        self.assertEqual(linea, ["D", "2.3.3.05.09.099", "1", "16.0", "3301053", "0", "0", "1.3.3.3.20",
                                 "202600000018441", "C", "0", "220170001", "40000000", "40000000", "40000000"])

    def test_sin_bpin_va_con_producto_y_bpin_cero(self):
        [linea] = [l for l in self.detalle if l[1] == "2.3.7.05.03"]
        self.assertEqual((linea[4], linea[8], linea[12]), ("0", "0", "389231271"))

    def test_redondeo_al_peso_cuadra_con_el_total_de_la_fila(self):
        del_35 = [l for l in self.detalle if l[7] == "1.3.3.4.01"]
        self.assertEqual(sum(int(l[12]) for l in del_35), 2979309905)
        self.assertEqual(sum(int(l[13]) for l in del_35), 2010861681)       # 2.010.861.681,15
        self.assertEqual(sorted(int(l[12]) for l in del_35), [1489654952, 1489654953])

    def test_agrupa_lineas_iguales(self):
        """Los recursos 54 y 125 van a la misma fuente CUIPO: con el mismo producto y vigencia,
        una sola linea."""
        iguales = [l for l in self.detalle if l[7] == "1.3.2.3.11" and l[4] == "4502034" and l[2] == "1"]
        self.assertEqual(len(iguales), 1)
        self.assertEqual(int(iguales[0][12]), 600000000 + 212892474)        # 212.892.473,50 al peso
        self.assertEqual(int(iguales[0][13]), 600000000 + 157335215)
        # 125: O 314.670.429,87 -> 314.670.430 entre las dos lineas
        del_125_y_54 = [l for l in self.detalle if l[7] == "1.3.2.3.11"]
        self.assertEqual(sum(int(l[13]) for l in del_125_y_54), 1000000000 + 314670430)

    def test_vigencia_futura_en_su_propio_grupo(self):
        vigencias = [l[2] for l in self.lineas]
        self.assertEqual(vigencias, sorted(vigencias, key=int))
        futura = [l for l in self.lineas if l[2] == "4"]
        self.assertEqual([l[1] for l in futura if not any(l[4:12])], ["2", "2.3", "2.3.2", "2.3.2.02", "2.3.2.02.02",
                                                                      "2.3.2.02.02.009"])
        self.assertEqual(int(futura[0][12]), 400000000)

    def test_resumen_antes_del_detalle_y_orden_por_segmentos(self):
        de_la_vigencia_1 = [l for l in self.lineas if l[2] == "1" and l[3] == "16.0"]
        codigos = [l[1] for l in de_la_vigencia_1]
        self.assertEqual(codigos[:3], ["2", "2.3", "2.3.2"])
        self.assertLess(codigos.index("2.3.3.05.09.099"), codigos.index("2.3.7"))
        self.assertTrue(all(any(l[4:12]) for l in de_la_vigencia_1[codigos.index("2.3.3.05.09.099") + 1:][:1]))

    def test_el_resumen_suma_su_detalle(self):
        raiz = next(l for l in self.lineas if l[1] == "2" and l[2] == "1" and l[3] == "16.0")
        detalle = [l for l in self.detalle if l[2] == "1" and l[3] == "16.0"]
        for i in (12, 13, 14):
            self.assertEqual(int(raiz[i]), sum(int(l[i]) for l in detalle))

    def test_lineas_en_cero_no_van(self):
        f = self.d.filas().get(recurso="35")
        distribucion.agregar_vigencia(self.d, f.pk, ProductoCUIPO.objects.get(codigo="4502034").pk,
                                      VigenciaGasto.objects.get(codigo="4").pk)
        self.assertEqual(lineas_d(plano.generar(self.corte)), self.lineas)


class NoSeGenera(TestCase):
    def test_con_errores_o_sin_distribucion(self):
        corte = preparar()            # 202500000029628 queda sin distribuir: no cuadra
        with self.assertRaises(plano.PlanoInvalido) as error:
            plano.generar(corte)
        self.assertTrue(any("BPIN 202500000029628" in p for p in error.exception.problemas))
        DistribucionBPIN.objects.filter(bpin="202500000029628").delete()
        self.assertIn("BPIN 202500000029628: sus filas no tienen distribución (precargar el corte)",
                      plano.revisar(corte))


PRESUPUESTO = "\r\n".join([
    "S\t117070000\t10909\t2026\tE_ID_SECCIONES_PRESUPUESTALES_ADICIONALES",
    "D\t16.0\tADMINISTRACION CENTRAL\t1\tX",
    ENCABEZADO,
    "D\t2\t1\t16.0\t\t\t\t\t\t\t\t\t1500\t1400\t1300",
    "D\t2.1\t1\t16.0\t\t\t\t\t\t\t\t\t1000\t900\t800",
    "D\t2.1.1\t1\t16.0\t\t\t\t\t\t\t\t\t1000\t900\t800",
    "D\t2.1.1\t1\t16.0\t0\t0\t0\t1.2.1.0.00\t0\tC\t0\t1\t1000\t900\t800",
    "D\t2.3\t1\t16.0\t\t\t\t\t\t\t\t\t500\t500\t500",
    "D\t2.3.9\t1\t16.0\t\t\t\t\t\t\t\t\t500\t500\t500",
    "D\t2.3.9\t1\t16.0\t9999999\t0\t0\t1.2.1.0.00\t2022000000001\tC\t0\t1\t500\t500\t500",
    "S\t117070000\t10909\t2026\tC_PROGRAMACION_DE_GASTOS",
    "D\t2.1\t1\t16.0\t1\t2\t3\t4",
]) + "\r\n"


class Integrar(TestCase):
    def setUp(self):
        self.corte = preparar()
        distribuir_manual(self.corte)

    def test_reemplaza_la_inversion_y_recalcula_el_2(self):
        resultado = plano.integrar(PRESUPUESTO, self.corte)
        renglones = resultado.splitlines()
        originales = PRESUPUESTO.splitlines()
        self.assertEqual(renglones[:3], originales[:3])                       # E y el encabezado D
        self.assertEqual(renglones[-2:], originales[-2:])                     # C, intacto
        for linea in originales[4:7]:                                          # 2.1, intactas
            self.assertIn(linea, renglones)
        self.assertFalse(any("2.3.9" in r for r in renglones))               # la 2.3 vieja sale
        inversion = plano.generar(self.corte).splitlines()[1:]
        for linea in inversion:
            if not linea.startswith("D\t2\t"):
                self.assertIn(linea, renglones)
        dos = next(r.split("\t") for r in renglones if r.startswith("D\t2\t1\t16.0\t"))
        nueva = next(r.split("\t") for r in inversion if r.startswith("D\t2.3\t1\t16.0\t"))
        self.assertEqual(int(dos[12]), 1000 + int(nueva[12]))
        self.assertTrue(resultado.endswith("\r\n"))
        self.assertNotIn("\n", resultado.replace("\r\n", ""))

    def test_el_orden_de_los_bloques_se_conserva(self):
        resultado = plano.integrar(PRESUPUESTO, self.corte)
        categorias = [r.split("\t")[-1] for r in resultado.splitlines() if r.startswith("S\t")]
        self.assertEqual(categorias, ["E_ID_SECCIONES_PRESUPUESTALES_ADICIONALES", "D_EJECUCION_DE_GASTOS",
                                      "C_PROGRAMACION_DE_GASTOS"])

    def test_otro_periodo_o_sin_bloque(self):
        with self.assertRaisesMessage(ValueError, "periodo 10606"):
            plano.integrar(PRESUPUESTO.replace("\t10909\t", "\t10606\t"), self.corte)
        with self.assertRaisesMessage(ValueError, "no tiene el bloque"):
            plano.integrar("S\t117070000\t10909\t2026\tC_PROGRAMACION_DE_GASTOS\r\n", self.corte)


class PantallaDelPlano(TestCase):
    def setUp(self):
        self.corte = preparar()
        distribuir_manual(self.corte)
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")
        self.client.force_login(self.usuario)
        self.url = reverse("admin:cuipo_corte_plano", args=(self.corte.pk,))

    def test_abre_con_vista_previa(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Todas las filas de inversión tienen distribución sin errores")
        self.assertContains(respuesta, "D_EJECUCION_DE_GASTOS")
        self.assertContains(self.client.get(reverse("admin:cuipo_corteejecuciongastos_changelist")), self.url)

    def test_descargar(self):
        respuesta = self.client.get(self.url, {"descargar": "1"})
        self.assertEqual(respuesta["Content-Disposition"],
                         'attachment; filename="CUIPO_117070000_10909_2026_D_EJECUCION_DE_GASTOS_inversion.txt"')
        self.assertTrue(respuesta.content.decode().startswith(ENCABEZADO))

    def test_integrar_subiendo_el_plano(self):
        archivo = SimpleUploadedFile("Presupuesto_10909.txt", PRESUPUESTO.encode("latin-1"))
        respuesta = self.client.post(self.url, {"presupuesto": archivo})
        self.assertIn("Presupuesto_10909_con_inversion_CUIPO.txt", respuesta["Content-Disposition"])
        self.assertIn("C_PROGRAMACION_DE_GASTOS", respuesta.content.decode("latin-1"))

    def test_con_problemas_no_descarga(self):
        DistribucionBPIN.objects.filter(bpin="202500000029628").update(regla=DistribucionBPIN.Regla.SIN_PRODUCTOS)
        self.assertContains(self.client.get(self.url), "No se puede generar el plano")
        respuesta = self.client.get(self.url, {"descargar": "1"}, follow=True)
        self.assertContains(respuesta, "No se puede generar el plano")

    def test_marcar_enviadas_las_validadas(self):
        for d in DistribucionBPIN.objects.all():
            validacion.cambiar_estado(d, "validado", self.usuario)
        respuesta = self.client.post(self.url, {"marcar_enviadas": "1"}, follow=True)
        self.assertContains(respuesta, "Marcadas como enviadas: 3.")
        self.assertEqual(set(DistribucionBPIN.objects.values_list("estado", flat=True)), {"enviado"})
