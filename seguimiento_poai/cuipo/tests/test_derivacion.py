"""Homologaciones y reglas: de la fila de ejecucion a los codigos CHIP (fase 2 del CUIPO)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from cuipo import derivacion
from cuipo.models import (ConceptoCUIPO, FuenteCUIPO, HomologacionFuente, HomologacionRubro, ReglaSeccion,
                          ReglaSituacionFondos, ReglaTercero, SeccionPresupuestal, SituacionFondos, TerceroCUIPO)
from siifweb.models import CentroCosto, Fuente, Rubro

from .fabricas import corte_con, fila, homologar, listas



class Derivar(TestCase):
    def setUp(self):
        listas()

    def una(self, rubro="2.3.2.02.02.009", recurso="3", centro="2", proyecto="202500000039332", vigencia=2026):
        corte = corte_con([fila(101, rubro, 1000, recurso, centro, proyecto)], vigencia=vigencia)
        return corte.filas_ejecucion.get()

    def test_202600000018441_recorre_todas_las_reglas(self):
        """Rubro no habilitado (homologado), recurso 108, centro de costo 10 (Fondo Mixto)."""
        HomologacionRubro.objects.create(rubro=Rubro.objects.get(codigo="2.3.3.05.09.054"),
                                         concepto=ConceptoCUIPO.objects.get(codigo="2.3.3.05.09.099"))
        homologar("108", "1.3.3.3.20")
        ReglaTercero.objects.create(centro_costo=CentroCosto.objects.get(codigo="10"),
                                    tercero=TerceroCUIPO.objects.get(codigo="220170001"))
        d = derivacion.derivar(self.una("2.3.3.05.09.054", "108", "10", "202600000018441"))
        self.assertTrue(d.completa, d.faltantes)
        self.assertEqual((d.concepto.codigo, d.fuente.codigo, d.seccion.codigo, d.situacion.codigo, d.tercero.codigo),
                         ("2.3.3.05.09.099", "1.3.3.3.20", "16.0", "C", "220170001"))
        self.assertEqual((d.origen_concepto, d.origen_seccion, d.origen_situacion, d.origen_tercero),
                         ("homologación del rubro", "por defecto", "por defecto", "regla del centro de costo"))

    def test_concepto_con_el_mismo_codigo(self):
        homologar("3", "1.2.4.1.01")
        d = derivacion.derivar(self.una())
        self.assertEqual((d.concepto.codigo, d.origen_concepto), ("2.3.2.02.02.009", "mismo código del rubro"))

    def test_concepto_no_habilitado_sin_homologacion_bloquea(self):
        homologar("108", "1.3.3.3.20")
        d = derivacion.derivar(self.una("2.3.3.05.09.054", "108", "10"))
        self.assertFalse(d.completa)
        self.assertIn("no está habilitado para departamentos", d.faltantes[0])

    def test_concepto_que_no_existe_bloquea(self):
        Rubro.objects.create(codigo="2.3.9.99", nombre="Otro")
        homologar("3", "1.2.4.1.01")
        d = derivacion.derivar(self.una("2.3.9.99"))
        self.assertEqual(d.faltantes, ["Rubro 2.3.9.99: no está en los conceptos CUIPO; falta su homologación"])

    def test_concepto_inactivo_bloquea(self):
        ConceptoCUIPO.objects.filter(codigo="2.3.2.02.02.009").update(activo=False)
        homologar("3", "1.2.4.1.01")
        self.assertIn("inactivo", derivacion.derivar(self.una()).faltantes[0])

    def test_recurso_sin_homologacion_bloquea(self):
        d = derivacion.derivar(self.una())
        self.assertEqual(d.faltantes, ["Recurso 3: sin homologación de fuente para 2026"])

    def test_la_homologacion_es_por_vigencia(self):
        homologar("3", "1.2.4.1.01", vigencia=2025)
        self.assertIn("sin homologación de fuente para 2026", derivacion.derivar(self.una()).faltantes[0])

    def test_recurso_que_no_esta_en_siifweb(self):
        d = derivacion.derivar(self.una(recurso="130"))
        self.assertIn("no está en los recursos de SIIFWEB", d.faltantes[0])

    def test_fuente_cuipo_inactiva_bloquea(self):
        homologar("3", "1.2.4.1.01")
        FuenteCUIPO.objects.filter(codigo="1.2.4.1.01").update(activo=False)
        self.assertIn("inactiva", derivacion.derivar(self.una()).faltantes[0])

    def test_seccion_por_regla_y_por_defecto(self):
        homologar("3", "1.2.4.1.01")
        homologar("7", "1.2.3.3.03")
        homologar("114", "1.2.3.3.03")
        ReglaSeccion.objects.create(centro_costo=CentroCosto.objects.get(codigo="3"),
                                    seccion=SeccionPresupuestal.objects.get(codigo="21.0"))
        # 2023002700021: dos secciones en el mismo BPIN
        corte = corte_con([fila(101, "2.3.2.01.01.001.02.08", 600, "7", "16", "2023002700021"),
                           fila(101, "2.3.2.01.01.001.02.08", 400, "114", "3", "2023002700021")])
        derivador = derivacion.Derivador(2026)
        secciones = {f.recurso: derivador.derivar(f).seccion.codigo for f in corte.filas_ejecucion.all()}
        self.assertEqual(secciones, {"7": "16.0", "114": "21.0"})

    def test_tercero_por_rubro_gana_al_del_centro_de_costo(self):
        homologar("3", "1.2.4.1.01")
        ReglaTercero.objects.create(rubro=Rubro.objects.get(codigo="2.3.1.01.02.006"),
                                    tercero=TerceroCUIPO.objects.get(codigo="23900000"))
        ReglaTercero.objects.create(centro_costo=CentroCosto.objects.get(codigo="11"),
                                    tercero=TerceroCUIPO.objects.get(codigo="128470000"))
        d = derivacion.derivar(self.una("2.3.1.01.02.006", "3", "11"))
        self.assertEqual((d.tercero.codigo, d.origen_tercero), ("23900000", "regla del rubro"))

    def test_tercero_por_defecto_no_aplica(self):
        homologar("3", "1.2.4.1.01")
        d = derivacion.derivar(self.una())
        self.assertEqual((d.tercero.codigo, d.origen_tercero), ("1", "por defecto"))

    def test_situacion_de_fondos(self):
        homologar("3", "1.2.4.1.01")
        homologar("1", "1.2.1.0.00")
        sin = SituacionFondos.objects.get(codigo="S")
        ReglaSituacionFondos.objects.create(prefijo_rubro="2.3.1.01.02.001",
                                            fuente_cuipo=FuenteCUIPO.objects.get(codigo="1.2.4.1.01"), situacion=sin)
        self.assertEqual(derivacion.derivar(self.una("2.3.1.01.02.001", "3")).situacion.codigo, "S")
        # Otra fuente: no aplica la regla
        self.assertEqual(derivacion.derivar(self.una("2.3.1.01.02.001", "1")).situacion.codigo, "C")

    def test_situacion_gana_el_prefijo_mas_largo(self):
        homologar("3", "1.2.4.1.01")
        ReglaSituacionFondos.objects.create(prefijo_rubro="2.3.1", situacion=SituacionFondos.objects.get(codigo="S"))
        ReglaSituacionFondos.objects.create(prefijo_rubro="2.3.1.01.02.001.",   # el punto final se quita
                                            situacion=SituacionFondos.objects.get(codigo="C"))
        self.assertEqual(ReglaSituacionFondos.objects.filter(prefijo_rubro="2.3.1.01.02.001").count(), 1)
        self.assertEqual(derivacion.derivar(self.una("2.3.1.01.02.001", "3")).situacion.codigo, "C")
        self.assertEqual(derivacion.derivar(self.una("2.3.1.01.02.006", "3")).situacion.codigo, "S")

    def test_sin_listas_la_seccion_por_defecto_falta(self):
        homologar("3", "1.2.4.1.01")
        SeccionPresupuestal.objects.filter(codigo="16.0").delete()
        self.assertIn("Falta la sección 16.0", derivacion.derivar(self.una(centro="16")).faltantes[0])


class Restricciones(TestCase):
    def setUp(self):
        listas()

    def test_una_homologacion_por_recurso_y_vigencia(self):
        homologar("3", "1.2.4.1.01")
        homologar("3", "1.2.4.1.01", vigencia=2025)
        with self.assertRaises(IntegrityError), transaction.atomic():
            homologar("3", "1.2.1.0.00")

    def test_la_regla_de_tercero_va_por_rubro_o_por_centro(self):
        tercero = TerceroCUIPO.objects.get(codigo="1")
        with self.assertRaises(ValidationError):
            ReglaTercero(tercero=tercero).full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReglaTercero.objects.create(rubro=Rubro.objects.get(codigo="2.3.1.01.02.006"),
                                        centro_costo=CentroCosto.objects.get(codigo="11"), tercero=tercero)


class FilasQueEntran(TestCase):
    def test_solo_inversion_de_la_vigencia_con_valores(self):
        corte = corte_con([
            fila(101, "2.3.2.02.02.009", 1000, "3", "2", "202500000039332"),
            fila(101, "2.3.2.02.02.009", 0, "159", "3", "2023002700021", APROPIACION_INICIAL=4949,
                 APROPIACION_DEFINITIVA=4949, SOLICITUD_TRAMITE=0, CDP=0),          # adicion sin RP: no entra
            fila(101, "2.3.7.05.03", 500, "128", "1", "0"),                     # sin BPIN: entra
            fila(101, "2.1.1.01.01.001.01", 700, "1", "1", "0"),                 # funcionamiento: no
        ])
        entran = sorted(derivacion.filas_cuipo(corte).values_list("recurso", flat=True))
        self.assertEqual(entran, ["128", "3"])


class Pendientes(TestCase):
    def setUp(self):
        listas()
        self.client.force_login(User.objects.create_superuser("admin", "admin@example.com", "clave"))
        self.corte = corte_con([
            fila(101, "2.3.2.02.02.009", 1000, "3", "2", "202500000039332"),
            fila(102, "2.3.3.05.09.054", 40, "108", "10", "202600000018441"),
        ])

    def test_lista_lo_que_falta(self):
        Fuente.objects.filter(codigo="108").update(nombre="1.3.3.3.20 - R.B. ESTAMPILLA PROCULTURA")
        FilaRecurso = self.corte.filas_ejecucion.filter(recurso="108")
        FilaRecurso.update(nombre_recurso="1.3.3.3.20 - R.B. ESTAMPILLA PROCULTURA")
        homologar("3", "1.2.4.1.01")
        p = derivacion.pendientes(self.corte)
        self.assertEqual((p["filas"], p["completas"], p["con_faltantes"]), (2, 1, 1))
        self.assertEqual([(r["recurso"], r["pista"], r["rp"]) for r in p["recursos"]],
                         [("108", "1.3.3.3.20", Decimal("40"))])
        self.assertEqual([r["rubro"] for r in p["rubros"]], ["2.3.3.05.09.054"])
        self.assertEqual({r["bpin"] for r in p["sin_piip"]}, {"202500000039332", "202600000018441"})
        self.assertEqual([r["centro_costo"] for r in p["por_defecto"]], ["10", "2"])   # sin reglas de seccion

    def test_la_pagina_abre_y_redirige_al_ultimo_corte(self):
        url = reverse("admin:cuipo_corte_pendientes", args=(self.corte.pk,))
        respuesta = self.client.get(url)
        self.assertContains(respuesta, "Recursos sin homologación de fuente")
        self.assertContains(respuesta, "2.3.3.05.09.054")
        self.assertRedirects(self.client.get(reverse("admin:cuipo_pendientes")), url)

    def test_crea_las_reglas_iniciales_sin_duplicar(self):
        for codigo in ("5", "25"):
            CentroCosto.objects.create(codigo=codigo, nombre=f"Centro {codigo}")
        url = reverse("admin:cuipo_corte_pendientes", args=(self.corte.pk,))
        self.client.post(url, {"reglas_iniciales": "1"})
        self.assertEqual(ReglaSeccion.objects.count(), 2)
        self.assertEqual(HomologacionRubro.objects.get().concepto.codigo, "2.3.3.05.09.099")
        self.assertEqual(ReglaSituacionFondos.objects.count(), 3)   # son prefijos: no exigen el rubro
        antes = ReglaTercero.objects.count()
        self.client.post(url, {"reglas_iniciales": "1"})
        self.assertEqual(ReglaTercero.objects.count(), antes)
        d = derivacion.derivar(self.corte.filas_ejecucion.get(recurso="108"))
        self.assertEqual((d.concepto.codigo, d.tercero.codigo), ("2.3.3.05.09.099", "220170001"))

    def test_trae_las_homologaciones_de_fuente_del_t3(self):
        """Las 62 que valido presupuesto; aqui solo existen algunos recursos y fuentes."""
        homologar("1", "1.2.4.1.01")        # una que ya estaba con otro valor: no se cambia
        url = reverse("admin:cuipo_corte_pendientes", args=(self.corte.pk,))
        respuesta = self.client.post(url, {"reglas_iniciales": "1"}, follow=True)
        self.assertContains(respuesta, "2 homologaciones de fuente del T3 2026")
        self.assertEqual(dict(HomologacionFuente.objects.values_list("fuente_siifweb__codigo", "fuente_cuipo__codigo")),
                         {"1": "1.2.4.1.01", "3": "1.2.4.1.01", "108": "1.3.3.3.20"})
        self.assertEqual(HomologacionFuente.objects.get(fuente_siifweb__codigo="108").observacion,
                         "Validada por presupuesto para el CUIPO del T3 2026")
        self.assertContains(respuesta, "fuente CUIPO 1.2.3.3.04 no existe")          # la del recurso 7
        self.client.post(url, {"reglas_iniciales": "1"})
        self.assertEqual(HomologacionFuente.objects.count(), 3)
        self.assertEqual(len(derivacion.FUENTES_T3_2026), 62)
        self.assertTrue(derivacion.derivar(self.corte.filas_ejecucion.get(recurso="108")).completa)


class AdminDeLasReglas(TestCase):
    def setUp(self):
        listas()
        self.usuario = User.objects.create_superuser("admin", "admin@example.com", "clave")
        self.client.force_login(self.usuario)

    def test_homologar_un_recurso_desde_la_fuente_cuipo(self):
        fuente = FuenteCUIPO.objects.get(codigo="1.3.3.3.20")
        url = reverse("admin:cuipo_fuentecuipo_change", args=(fuente.pk,))
        self.assertContains(self.client.get(url), "Recursos de SIIFWEB que se reportan con esta fuente")
        respuesta = self.client.post(url, {
            "homologaciones-TOTAL_FORMS": "1", "homologaciones-INITIAL_FORMS": "0",
            "homologaciones-MIN_NUM_FORMS": "0", "homologaciones-MAX_NUM_FORMS": "1000",
            "homologaciones-0-fuente_siifweb": str(Fuente.objects.get(codigo="108").pk),
            "homologaciones-0-vigencia": "2026", "homologaciones-0-observacion": "Estampilla procultura",
            "_save": "Guardar"})
        self.assertEqual(respuesta.status_code, 302, respuesta.content.decode()[:3000])
        h = HomologacionFuente.objects.get()
        self.assertEqual((h.fuente_cuipo, h.vigencia, h.validado_por), (fuente, 2026, self.usuario))
        self.assertIsNotNone(h.fecha_validacion)
        fuente.refresh_from_db()
        self.assertEqual(fuente.codigo, "1.3.3.3.20")   # la fuente de la lista no se toca

    def test_las_listas_de_reglas_abren(self):
        for modelo in ("homologacionfuente", "homologacionrubro", "reglaseccion", "reglatercero",
                       "reglasituacionfondos"):
            with self.subTest(modelo=modelo):
                self.assertEqual(self.client.get(reverse(f"admin:cuipo_{modelo}_changelist")).status_code, 200)
                self.assertEqual(self.client.get(reverse(f"admin:cuipo_{modelo}_add")).status_code, 200)

    def test_el_autocompletar_solo_ofrece_codigos_activos(self):
        FuenteCUIPO.objects.filter(codigo="1.2.1.0.00").update(activo=False)
        respuesta = self.client.get(reverse("admin:autocomplete"), {
            "term": "1.2", "app_label": "cuipo", "model_name": "homologacionfuente", "field_name": "fuente_cuipo"})
        codigos = [r["text"].split(" - ")[0] for r in respuesta.json()["results"]]
        self.assertIn("1.2.4.1.01", codigos)
        self.assertNotIn("1.2.1.0.00", codigos)
