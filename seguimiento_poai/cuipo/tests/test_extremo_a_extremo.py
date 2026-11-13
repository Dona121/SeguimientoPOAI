"""El CUIPO de punta a punta con el caso 202500000039332 (fase 7).

Del corte de ejecucion al plano: precarga, digitacion desde el PIIP, cualitativos, validacion y
generacion. El plano se compara byte a byte con `datos/plano_202500000039332.txt`, armado a mano
con el formato de CHIP: si cambia algo del formato, del orden o del redondeo, esta prueba lo dice.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from cuipo import distribucion, plano, validacion
from cuipo.models import ConceptoCUIPO, DistribucionBPIN, ProductoCUIPO, ReglaSeccion, SeccionPresupuestal, VigenciaGasto
from siifweb.models import CentroCosto

from .fabricas import corte_con, fila, formular, homologar, listas_distribucion

ESPERADO = Path(__file__).parent / "datos" / "plano_202500000039332.txt"
BPIN = "202500000039332"
# Lo que se reporto en el T3 para cada producto (compromisos del PIIP; obligaciones y pagos con
# la misma participacion, al centavo)
DIGITADO = {"2201048": ("717349192", "567333673.07"), "2201006": ("337409820", "266849052.93")}


class CasoDelPlan(TestCase):
    def setUp(self):
        listas_distribucion()
        ConceptoCUIPO.objects.filter(codigo="2.3.2.02.02.009").update(requiere_cpc=True)
        homologar("3", "1.2.4.1.01")
        ReglaSeccion.objects.create(centro_costo=CentroCosto.objects.get(codigo="2"),
                                    seccion=SeccionPresupuestal.objects.get(codigo="22.0"))
        formular(BPIN, "2201006", "2201048")
        self.corte = corte_con([fila(101, "2.3.2.02.02.009", Decimal("1054759012"), "3", "2", BPIN,
                                     obligacion=Decimal("834182726"))], fecha_fin=date(2026, 9, 30))
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")

    def distribuir(self):
        distribucion.precargar(self.corte)
        d = DistribucionBPIN.objects.get(bpin=BPIN)
        self.assertEqual(d.regla, DistribucionBPIN.Regla.PIIP)       # varios productos, una fuente
        f = d.filas().get()
        v1 = VigenciaGasto.objects.get(codigo="1").pk
        for codigo, (c, o) in DIGITADO.items():
            producto = ProductoCUIPO.objects.get(codigo=codigo).pk
            for campo, valor in (("compromisos", c), ("obligaciones", o), ("pagos", o)):
                distribucion.guardar_valor(d, f.pk, producto, v1, campo, valor)
        r = validacion.validar_distribucion(d)
        self.assertEqual([p.mensaje for p in r.errores if "falta el CPC" in p.mensaje],
                         [f"2.3.2.02.02.009 · recurso 3 · CC 2 · producto {c} · vigencia 1: falta el CPC"
                          for c in ("2201006", "2201048")])      # el concepto exige CPC
        for linea in d.lineas.all():
            distribucion.cambiar_cualitativo(d, linea.pk, "cpc", "85999")
        validacion.cambiar_estado(d, DistribucionBPIN.Estado.VALIDADO, self.usuario)
        return d

    def test_el_plano_es_el_esperado(self):
        self.distribuir()
        self.assertEqual(plano.generar(self.corte).encode("ascii"), ESPERADO.read_bytes())

    def test_el_plano_descargado_es_el_esperado(self):
        self.distribuir()
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse("admin:cuipo_corte_plano", args=(self.corte.pk,)), {"descargar": "1"})
        self.assertEqual(respuesta.content, ESPERADO.read_bytes())

    def test_el_redondeo_va_al_mayor_residuo(self):
        self.distribuir()
        lineas = [r.split("\t") for r in plano.generar(self.corte).splitlines() if r.split("\t")[4:5] != [""]][1:]
        obligaciones = {l[4]: int(l[13]) for l in lineas}
        # ,07 y ,93: el peso que sobra va al de residuo mayor (2201006)
        self.assertEqual(obligaciones, {"2201048": 567333673, "2201006": 266849053})
        self.assertEqual(sum(obligaciones.values()), 834182726)

    def test_despues_de_enviar_no_cambia(self):
        d = self.distribuir()
        validacion.cambiar_estado(d, DistribucionBPIN.Estado.ENVIADO, self.usuario)
        with self.assertRaises(ValueError):
            distribucion.guardar_valor(d, d.filas().get().pk, ProductoCUIPO.objects.get(codigo="2201048").pk,
                                       VigenciaGasto.objects.get(codigo="1").pk, "compromisos", "1")
        self.assertEqual(plano.generar(self.corte).encode("ascii"), ESPERADO.read_bytes())
