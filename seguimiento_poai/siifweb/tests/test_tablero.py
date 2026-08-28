# -*- coding: utf-8 -*-
"""El tablero de gestion por dependencia responsable.

Lo que se vigila aqui es lo que ya mordio dos veces en este proyecto -el grano: contar
o sumar sobre dos relaciones a la vez multiplica las filas- y la regla que hace util el
corte de fechas: cada etapa se filtra por SU fecha, no por una sola.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Count, Sum
from django.test import TestCase
from django.urls import reverse

from siifweb import tablero
from siifweb.models import (BpinProceso, Cdp, CdpImputacion, Compromiso,
                            CompromisoImputacion, ContratoActa, ContratoSecop,
                            DependenciaResponsable, Obligacion, ObligacionImputacion,
                            ProcesoSecop)

from .fabricas import cadena, carga_secop, contrato_siifweb, fila, proyecto

MILLON = Decimal("10000000.00")


def dependencia(nombre):
    return DependenciaResponsable.objects.create(nombre=nombre)


class TableroBase(TestCase):
    """Dos dependencias, cuatro proyectos y un proyecto huerfano que no debe aparecer.

    El de Educacion lleva la cadena de 2025 (CDP en enero, RP en febrero, obligacion en
    marzo), un contrato con dos imputaciones y dos actas, y un contrato de SECOP que
    financia sus dos BPIN. El de Salud lleva la cadena de 2024.
    """

    @classmethod
    def setUpTestData(cls):
        cls.educacion = dependencia("Educacion")
        cls.salud = dependencia("Salud")

        cls.p1 = proyecto(bpin="202500000000001", dependencia_responsable=cls.educacion)
        cls.p2 = proyecto(bpin="202500000000002", nombre="Segundo de Educacion",
                          dependencia_responsable=cls.educacion)
        cls.p3 = proyecto(bpin="202400000000003", nombre="De Salud",
                          dependencia_responsable=cls.salud)
        cls.huerfano = proyecto(bpin="202500000000009", nombre="Sin responsable")

        cadena(cls.p1, vigencia=2025)
        cadena(cls.p3, vigencia=2024, nro="3")
        cadena(cls.huerfano, vigencia=2025, nro="9")
        cls.contrato = contrato_siifweb(cls.p1, imputaciones=2, actas=2)
        # El mismo contrato de SECOP financiando los dos BPIN de Educacion
        carga_secop([fila(), fila(**{"BPIN": "202500000000002"})])

    def educacion_en(self, **kwargs):
        filas, _ = tablero.por_dependencia(tablero.Filtros(**kwargs))
        return next(f for f in filas if f["llave"] == self.educacion.pk)


class SoloLosProyectosAsignados(TableroBase):
    def test_solo_salen_dependencias_con_proyectos(self):
        filas, _ = tablero.por_dependencia(tablero.Filtros())
        self.assertEqual([f["nombre"] for f in filas], ["Educacion", "Salud"])

    def test_el_proyecto_sin_dependencia_no_entra_en_ningun_total(self):
        _, totales = tablero.por_dependencia(tablero.Filtros())
        # Tres cadenas creadas, pero la del huerfano no se cuenta
        self.assertEqual(totales["proyectos"], 3)
        self.assertEqual(totales["rps"], 2)
        self.assertEqual(totales["comprometido"], MILLON * 2)

    def test_las_consultas_los_dejan_fuera_desde_el_sql(self):
        """No es cosmetica: son 494 proyectos en produccion, con casi toda la ejecucion.

        Si entraran a la agregacion para descartarse despues en Python, cada etapa
        recorreria cientos de miles de filas de mas.
        """
        qs = tablero._recortar(CdpImputacion.objects, tablero.Filtros(), "proyecto",
                               "cdp__fecha_disp", "cdp__vigencia")
        self.assertNotIn(self.huerfano.pk, set(qs.values_list("proyecto", flat=True)))

    def test_una_dependencia_sin_proyectos_no_aparece(self):
        dependencia("Sin proyectos todavia")
        filas, _ = tablero.por_dependencia(tablero.Filtros())
        self.assertNotIn("Sin proyectos todavia", [f["nombre"] for f in filas])


class ElGrano(TableroBase):
    def test_un_contrato_con_dos_imputaciones_no_duplica_sus_actas(self):
        """Dos imputaciones al mismo proyecto x dos actas darian 4 si se sumara el join."""
        self.assertEqual(self.educacion_en()["actas"], 2)

    def test_el_contrato_de_secop_que_financia_dos_bpin_se_cuenta_una_vez(self):
        fila_educacion = self.educacion_en()
        self.assertEqual(fila_educacion["procesos_secop"], 1)
        self.assertEqual(fila_educacion["contratos_secop"], 1)
        self.assertEqual(fila_educacion["valor_secop"], Decimal("9000000"))

    def test_los_documentos_se_cuentan_una_vez_por_documento(self):
        fila_educacion = self.educacion_en()
        self.assertEqual((fila_educacion["cdps"], fila_educacion["rps"],
                          fila_educacion["obligaciones"]), (1, 1, 1))

    def test_el_pagado_sale_de_las_obligaciones(self):
        # cadena() paga la mitad a proposito: si se leyera el valor de las actas
        # (2 x 500.000) o el obligado, el numero seria otro
        self.assertEqual(self.educacion_en()["pagado"], MILLON / 2)


class CadaEtapaConSuFecha(TableroBase):
    def test_el_rango_del_cdp_no_arrastra_el_rp_ni_la_obligacion(self):
        # CDP el 15 de enero, RP el 1 de febrero, obligacion el 1 de marzo
        enero = self.educacion_en(desde=date(2025, 1, 1), hasta=date(2025, 1, 31))
        self.assertEqual((enero["cdps"], enero["rps"], enero["obligaciones"]), (1, 0, 0))
        self.assertEqual(enero["disponible"], MILLON)
        self.assertEqual(enero["comprometido"], 0)

    def test_el_rango_del_pago_solo_trae_las_actas(self):
        # Las actas son del 1 y 2 de diciembre
        diciembre = self.educacion_en(desde=date(2025, 12, 1), hasta=date(2025, 12, 31))
        self.assertEqual(diciembre["actas"], 2)
        self.assertEqual(diciembre["obligaciones"], 0)

    def test_una_semana_sin_movimiento_deja_la_fila_en_cero(self):
        vacia = self.educacion_en(desde=date(2019, 1, 1), hasta=date(2019, 1, 7))
        self.assertEqual(vacia["cdps"], 0)
        self.assertEqual(vacia["comprometido"], 0)

    def test_los_proyectos_asignados_no_dependen_del_periodo(self):
        """Es la comparacion que importa: tiene 2 proyectos y ninguno se movio."""
        vacia = self.educacion_en(desde=date(2019, 1, 1), hasta=date(2019, 1, 7))
        self.assertEqual(vacia["proyectos"], 2)
        self.assertEqual(vacia["proyectos_con_cdp"], 0)

    def test_cuantos_proyectos_se_movieron_en_el_periodo(self):
        todo = self.educacion_en()
        self.assertEqual(todo["proyectos"], 2)
        self.assertEqual(todo["proyectos_con_cdp"], 1)
        self.assertEqual(todo["proyectos_con_pago"], 1)

    def test_la_vigencia_tambien_recorta(self):
        filas, _ = tablero.por_dependencia(tablero.Filtros(vigencias=(2024,)))
        educacion = next(f for f in filas if f["llave"] == self.educacion.pk)
        salud = next(f for f in filas if f["llave"] == self.salud.pk)
        self.assertEqual(educacion["rps"], 0)
        self.assertEqual(salud["rps"], 1)


class ElDetallePorProyecto(TableroBase):
    def test_sin_dependencia_elegida_no_hay_detalle(self):
        filas, _ = tablero.por_proyecto(tablero.Filtros())
        self.assertEqual(filas, [])

    def test_una_fila_por_proyecto_de_la_dependencia(self):
        filas, _ = tablero.por_proyecto(tablero.Filtros(dependencia=self.educacion.pk))
        self.assertEqual(len(filas), 2)
        self.assertIn("202500000000002", [f["nombre"] for f in filas][0]
                      + [f["nombre"] for f in filas][1])

    def test_el_detalle_suma_lo_mismo_que_la_fila_de_la_dependencia(self):
        _, totales = tablero.por_proyecto(tablero.Filtros(dependencia=self.educacion.pk))
        self.assertEqual(totales["comprometido"], self.educacion_en()["comprometido"])
        self.assertEqual(totales["obligaciones"], self.educacion_en()["obligaciones"])


class ValoresImposiblesDeSecop(TableroBase):
    def test_la_fila_avisa_cuando_arrastra_un_valor_imposible(self):
        """SECOP trae contratos con errores de digitacion; se suman, pero se marcan."""
        self.assertEqual(self.educacion_en()["secop_dudosos"], 0)
        ContratoSecop.objects.update(valor=tablero.VALOR_IMPOSIBLE * 2)
        self.assertEqual(self.educacion_en()["secop_dudosos"], 1)


class LosPresets(TestCase):
    def test_los_atajos_arman_el_rango_correcto(self):
        hoy = date(2026, 8, 28)  # un viernes
        self.assertEqual(tablero.rango_del_preset("semana", hoy),
                         (date(2026, 8, 24), date(2026, 8, 30)))
        self.assertEqual(tablero.rango_del_preset("mes", hoy),
                         (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(tablero.rango_del_preset("trimestre", hoy),
                         (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(tablero.rango_del_preset("anio", hoy),
                         (date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(tablero.rango_del_preset("", hoy), (None, None))


class LaPagina(TableroBase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            "consulta1", "c@sucre.gov.co", "clave", is_staff=True)
        self.usuario.groups.add(Group.objects.get(name="Consulta"))
        self.client.force_login(self.usuario)

    def test_abre_para_el_rol_de_consulta(self):
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_tablero"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Educacion")
        self.assertNotContains(respuesta, "Sin responsable")

    def test_los_filtros_no_revientan(self):
        url = reverse("admin:siifweb_proyecto_tablero")
        casos = [{"preset": "mes"}, {"desde": "2025-01-01", "hasta": "2025-01-31"},
                 {"vigencia": "2025"}, {"desde": "no es fecha"},
                 {"dependencia": self.educacion.pk}, {"dependencia": "abc"},
                 {"clasificacion": "999"}]
        for parametros in casos:
            with self.subTest(parametros=parametros):
                self.assertEqual(self.client.get(url, parametros).status_code, 200)

    def test_al_elegir_dependencia_baja_al_proyecto(self):
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_tablero"),
                                    {"dependencia": self.educacion.pk})
        self.assertContains(respuesta, "Proyectos de Educacion")
        self.assertContains(respuesta, "Segundo de Educacion")

    def test_el_staff_sin_rol_no_entra(self):
        suelto = get_user_model().objects.create_user(
            "suelto2", "s@sucre.gov.co", "clave", is_staff=True)
        self.client.force_login(suelto)
        self.assertEqual(
            self.client.get(reverse("admin:siifweb_proyecto_tablero")).status_code, 403)


class ContrasteConLaConsultaDirecta(TableroBase):
    """La bateria: cada metrica, recalculada sin pasar por tablero.py.

    El tablero cruza seis consultas agregadas; una llave mal escrita da un numero
    plausible pero falso. Aqui se contrastan los totales contra agregados escritos
    aparte, rango por rango, incluido un rango sin datos.
    """

    RANGOS = [
        ("toda la historia", None, None),
        ("2025 completo", date(2025, 1, 1), date(2025, 12, 31)),
        ("enero 2025", date(2025, 1, 1), date(2025, 1, 31)),
        ("marzo 2025", date(2025, 3, 1), date(2025, 3, 31)),
        ("diciembre 2025", date(2025, 12, 1), date(2025, 12, 31)),
        ("2024 completo", date(2024, 1, 1), date(2024, 12, 31)),
        ("un ano sin datos", date(2019, 1, 1), date(2019, 12, 31)),
    ]

    def directo(self, desde, hasta):
        """Los mismos numeros, contados a mano sobre los proyectos con dependencia."""
        def corte(qs, fecha):
            qs = qs.filter(proyecto__dependencia_responsable__isnull=False)
            if desde:
                qs = qs.filter(**{f"{fecha}__gte": desde})
            if hasta:
                qs = qs.filter(**{f"{fecha}__lte": hasta})
            return qs

        cdp = corte(CdpImputacion.objects, "cdp__fecha_disp")
        rp = corte(CompromisoImputacion.objects, "compromiso__fecha_reg")
        obli = corte(ObligacionImputacion.objects, "obligacion__fecha_obli")
        actas = ContratoActa.objects.filter(
            contrato__imputaciones_del_contrato__proyecto__dependencia_responsable__isnull=False)
        if desde:
            actas = actas.filter(fecha_pago__gte=desde)
        if hasta:
            actas = actas.filter(fecha_pago__lte=hasta)
        return {
            "cdps": cdp.aggregate(n=Count("cdp", distinct=True))["n"],
            "rps": rp.aggregate(n=Count("compromiso", distinct=True))["n"],
            "obligaciones": obli.aggregate(n=Count("obligacion", distinct=True))["n"],
            "actas": actas.values("id").distinct().count(),
            "disponible": cdp.aggregate(t=Sum("valor_disponibilidad_def"))["t"] or 0,
            "comprometido": rp.aggregate(t=Sum("valor_compromiso_def"))["t"] or 0,
            "obligado": obli.aggregate(t=Sum("valor_obligacion"))["t"] or 0,
            "pagado": obli.aggregate(t=Sum("pagos"))["t"] or 0,
        }

    def test_cada_rango_da_lo_mismo_que_la_consulta_directa(self):
        for nombre, desde, hasta in self.RANGOS:
            with self.subTest(rango=nombre):
                _, totales = tablero.por_dependencia(
                    tablero.Filtros(desde=desde, hasta=hasta))
                for metrica, esperado in self.directo(desde, hasta).items():
                    self.assertEqual(totales[metrica] or 0, esperado or 0,
                                     f"{nombre}: {metrica}")

    def test_el_rango_sin_datos_no_es_un_error_sino_un_cero(self):
        _, totales = tablero.por_dependencia(
            tablero.Filtros(desde=date(2019, 1, 1), hasta=date(2019, 12, 31)))
        self.assertEqual(totales["rps"], 0)
        # ...pero las dependencias siguen ahi, con sus proyectos asignados
        self.assertEqual(totales["proyectos"], 3)


class HastaDondeLleganLosDatos(TableroBase):
    """Los reportes se cargan por tandas: el corte de hoy no es el corte de los datos."""

    def test_ultimo_movimiento_es_la_fecha_mas_reciente_de_las_cuatro(self):
        esperado = max(filter(None, [
            Cdp.objects.order_by("-fecha_disp").values_list("fecha_disp", flat=True).first(),
            Compromiso.objects.order_by("-fecha_reg").values_list("fecha_reg", flat=True).first(),
            Obligacion.objects.order_by("-fecha_obli").values_list("fecha_obli", flat=True).first(),
            ContratoActa.objects.order_by("-fecha_pago").values_list("fecha_pago", flat=True).first(),
        ]))
        self.assertEqual(tablero.ultimo_movimiento(), esperado)

    def test_sin_datos_cargados_no_revienta(self):
        ContratoActa.objects.all().delete()
        ObligacionImputacion.objects.all().delete()
        Obligacion.objects.all().delete()
        CompromisoImputacion.objects.all().delete()
        Compromiso.objects.all().delete()
        CdpImputacion.objects.all().delete()
        Cdp.objects.all().delete()
        self.assertIsNone(tablero.ultimo_movimiento())


class ElAvisoDePeriodoVacio(LaPagina):
    def test_un_periodo_posterior_a_los_datos_se_explica(self):
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_tablero"),
                                    {"desde": "2019-01-01", "hasta": "2019-12-31"})
        self.assertContains(respuesta, "no registra movimientos")
        self.assertContains(respuesta, "Los reportes cargados llegan hasta el")

    def test_con_movimiento_no_aparece_el_aviso(self):
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_tablero"))
        self.assertNotContains(respuesta, "no registra movimientos")

    def test_el_atajo_del_ano_va_con_tilde(self):
        respuesta = self.client.get(reverse("admin:siifweb_proyecto_tablero"))
        self.assertContains(respuesta, "Este año")


class LoCanceladoNoCuenta(TableroBase):
    """Un tramite cancelado no es gestion, y es donde vive la basura de la fuente."""

    def test_el_contrato_cancelado_no_suma_ni_se_cuenta(self):
        antes = self.educacion_en()
        self.assertEqual(antes["contratos_secop"], 1)
        ContratoSecop.objects.update(estado="Cancelado")
        despues = self.educacion_en()
        self.assertEqual(despues["contratos_secop"], 0)
        self.assertEqual(despues["valor_secop"], 0)

    def test_da_igual_como_venga_escrito_el_estado(self):
        ContratoSecop.objects.update(estado="CANCELADO")
        self.assertEqual(self.educacion_en()["contratos_secop"], 0)

    def test_el_proceso_cancelado_no_se_cuenta(self):
        self.assertEqual(self.educacion_en()["procesos_secop"], 1)
        ProcesoSecop.objects.update(estado_procedimiento="Cancelado")
        self.assertEqual(self.educacion_en()["procesos_secop"], 0)

    def test_el_contrato_cancelado_no_arrastra_su_valor_imposible(self):
        """Los dos valores imposibles de la fuente estan justamente cancelados."""
        ContratoSecop.objects.update(estado="Cancelado", valor=tablero.VALOR_IMPOSIBLE * 3)
        fila = self.educacion_en()
        self.assertEqual(fila["valor_secop"], 0)
        self.assertEqual(fila["secop_dudosos"], 0)


class UnContratoDeDosDependencias(TableroBase):
    def test_cuenta_en_las_dos_filas(self):
        """No es doble conteo: cada fila responde que hay en ESA dependencia.

        Por eso el total de la tabla, que es la suma de las filas, puede superar el
        numero de contratos distintos. En la base real pasa con un contrato.
        """
        contrato = ContratoSecop.objects.get()
        BpinProceso.objects.create(bpin=self.p3.bpin, proyecto=self.p3,
                                   proceso=contrato.proceso, contrato_secop=contrato,
                                   anio=2025, validacion_bpin="Validado")
        filas, totales = tablero.por_dependencia(tablero.Filtros())
        educacion = next(f for f in filas if f["llave"] == self.educacion.pk)
        salud = next(f for f in filas if f["llave"] == self.salud.pk)
        self.assertEqual(educacion["contratos_secop"], 1)
        self.assertEqual(salud["contratos_secop"], 1)
        self.assertEqual(totales["contratos_secop"], 2)
        self.assertEqual(ContratoSecop.objects.count(), 1)
