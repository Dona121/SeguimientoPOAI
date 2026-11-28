"""La programacion de los proyectos de regalias (fase 6) y lo que llena en el proyecto.

La pantalla es una copia adaptada de la de SIIFWEB: financiera con fuentes SGR por producto y
fisica por indicador. Al guardar, el proyecto toma sus fuentes, sus valores por clasificacion,
su total y su indicador MGA, y el cambio queda en el historial con el usuario.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from siifweb.models import EntidadAportante, IndicadorCatalogo, ProductoCatalogo

from regalias import programacion, servicios
from regalias.models import (CambioProyectoRegalias, FuenteSGR, ProgramacionFinancieraRegalias,
                             ProgramacionFisicaRegalias)

from .fabricas import DEPARTAMENTO, proyecto, usuario_de

C = FuenteSGR.Clasificacion


def producto_piip(codigo, nombre=None):
    return ProductoCatalogo.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre or f"Producto {codigo}"})[0]


def indicador_piip(codigo, producto, nombre=None):
    return IndicadorCatalogo.objects.get_or_create(codigo=codigo, defaults={
        "producto": producto, "nombre": nombre or f"Indicador {codigo}"})[0]


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = usuario_de("Regalías", "regalias")
        cls.regional = FuenteSGR.objects.create(nombre="SGR - Asignación para la inversión regional 60%",
                                                clasificacion=C.SGR)
        cls.nacion = FuenteSGR.objects.create(nombre="Presupuesto General de la Nación", clasificacion=C.NACION)
        cls.propios = FuenteSGR.objects.create(nombre="Recursos propios", clasificacion=C.OTROS)
        cls.via = producto_piip("9990101", "Vía terciaria construida")
        cls.puente = producto_piip("9990102", "Puente construido")
        cls.km = indicador_piip("999010100", cls.via, "Vía terciaria construida, con obras")
        cls.puentes = indicador_piip("999010200", cls.puente, "Puentes construidos")
        cls.entidad = EntidadAportante.objects.create(nombre="Departamento de Sucre")
        cls.municipio = EntidadAportante.objects.create(nombre="Municipio de Coveñas")

    def setUp(self):
        self.proy = proyecto("2025000020001", DEPARTAMENTO)
        self.client.force_login(self.usuario)

    def url(self, nombre):
        return reverse(f"admin:regalias_proyectodepartamento_{nombre}", args=(self.proy.pk,))

    def guardar_financiera(self, valores, vigencia=2026, entidad=None):
        """valores: {(fuente, producto): texto}, todo de la `entidad` (la de la prueba si no se
        dice; 0, sin entidad)."""
        e = self.entidad.pk if entidad is None else (entidad.pk if entidad else programacion.SIN_ENTIDAD)
        datos = {"panel": "financiera", "vigencias": [vigencia], f"entidades-{vigencia}": [e],
                 f"fuentes-{vigencia}-{e}": sorted({f.pk for f, _ in valores}),
                 f"productos-{vigencia}": sorted({p.pk for _, p in valores})}
        datos.update({f"v-{vigencia}-{e}-{f.pk}-{p.pk}": texto for (f, p), texto in valores.items()})
        return self.client.post(self.url("pf_guardar"), datos)

    def guardar_fisica(self, valores, vigencia=2026):
        datos = {"panel": "fisica", "vigencias": [vigencia], f"indicadores-{vigencia}": [i.pk for i in valores]}
        datos.update({f"v-{vigencia}-{i.pk}": texto for i, texto in valores.items()})
        return self.client.post(self.url("pf_guardar"), datos)


class PestanaFinanciera(Base):
    def test_la_pantalla_abre_con_sus_dos_pestanas(self):
        respuesta = self.client.get(self.url("programacion"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([c for c, _ in respuesta.context["paneles"]], ["financiera", "fisica"])
        self.assertTrue(respuesta.context["editable"])

    def test_guardar_llena_fuentes_valores_y_total_del_proyecto_con_historial(self):
        respuesta = self.guardar_financiera({(self.regional, self.via): "1500000.5", (self.nacion, self.via): "200",
                                             (self.propios, self.puente): "300"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Guardado: 3 nuevos.")
        self.proy.refresh_from_db()
        self.assertEqual((self.proy.valor_sgr, self.proy.valor_nacion, self.proy.valor_otros,
                          self.proy.valor_otras_no_suifp, self.proy.valor_total),
                         (Decimal("1500000.5"), Decimal("200"), Decimal("300"), Decimal("0"), Decimal("1500500.5")))
        self.assertEqual(self.proy.fuentes, "Presupuesto General de la Nación, Recursos propios, "
                                            "SGR - Asignación para la inversión regional 60%")
        cambio = self.proy.cambios.get(campo="Valor total del proyecto")
        self.assertEqual((cambio.valor_nuevo, cambio.usuario, cambio.origen),
                         ("1500500.5", self.usuario, CambioProyectoRegalias.Origen.PROGRAMACION))

    def test_vacio_o_cero_borra_y_el_proyecto_queda_sin_valores(self):
        self.guardar_financiera({(self.regional, self.via): "100"})
        self.guardar_financiera({(self.regional, self.via): "0"})
        self.assertFalse(ProgramacionFinancieraRegalias.objects.exists())
        self.proy.refresh_from_db()
        self.assertEqual((self.proy.valor_total, self.proy.valor_sgr, self.proy.fuentes), (None, None, ""))

    def test_una_casilla_con_error_no_guarda_nada(self):
        respuesta = self.guardar_financiera({(self.regional, self.via): "100", (self.nacion, self.via): "abc"})
        self.assertContains(respuesta, "1 casilla con error")
        self.assertFalse(ProgramacionFinancieraRegalias.objects.exists())

    def test_agregar_un_producto_no_guarda(self):
        respuesta = self.client.get(self.url("pf_matriz"), {"panel": "financiera", "vigencias": [2026],
                                                            "en": 2026, "agregar_producto": self.via.pk})
        self.assertEqual(respuesta.context["m"]["bloques"][0]["productos"], [self.via.pk])
        self.assertFalse(ProgramacionFinancieraRegalias.objects.exists())


class PestanaFisicaYCoincidencia(Base):
    def test_guardar_la_fisica_llena_el_indicador_mga(self):
        self.guardar_fisica({self.km: "12.5", self.puentes: "2"})
        self.proy.refresh_from_db()
        self.assertEqual(self.proy.indicadores_mga, "999010100 - Vía terciaria construida, con obras; "
                                                    "999010200 - Puentes construidos")
        self.assertEqual(ProgramacionFisicaRegalias.objects.count(), 2)

    def test_la_financiera_trae_los_productos_de_la_fisica(self):
        self.guardar_fisica({self.km: "10"})
        bloque = programacion.matriz(self.proy)["bloques"][0]
        self.assertEqual(bloque["productos"], [self.via.pk])
        self.assertTrue(bloque["columnas"][0]["en_fisica"])

    def test_el_aviso_de_descuadre_no_bloquea(self):
        respuesta = self.guardar_financiera({(self.regional, self.via): "100", (self.regional, self.puente): "50"})
        self.assertContains(respuesta, "productos sin indicador en la física 9990101, 9990102")
        respuesta = self.guardar_fisica({self.km: "10"})
        self.assertNotContains(respuesta, "9990101,")
        self.assertContains(respuesta, "productos sin indicador en la física 9990102")
        self.assertEqual(ProgramacionFisicaRegalias.objects.count(), 1)

    def test_indicador_cuyo_producto_no_tiene_valor_financiero(self):
        self.guardar_fisica({self.puentes: "1"})
        self.assertIn("indicadores sin valor financiero de su producto 999010200",
                      programacion.mensaje_descuadre(self.proy))

    def test_las_vigencias_de_las_dos_pestanas_no_tienen_que_coincidir(self):
        """El caso real: fuentes programadas en 2025 y 2027 y la meta fisica en 2026."""
        for vigencia, valor in ((2025, 100), (2027, 200)):
            ProgramacionFinancieraRegalias.objects.create(proyecto=self.proy, vigencia=vigencia, fuente=self.regional,
                                                          producto=self.via, valor=valor, entidad_aportante=self.entidad)
        respuesta = self.guardar_fisica({self.km: "10"}, vigencia=2026)
        self.assertContains(respuesta, "Guardado: 1 nuevos.")
        self.assertNotContains(respuesta, "no coinciden")
        self.assertNotContains(respuesta, "No coincide")
        self.assertEqual(programacion.descuadres(self.proy), {})
        # cada pestana con sus propias vigencias
        self.assertEqual(sorted(programacion.estado_guardado(self.proy)), [2025, 2027])
        self.assertEqual(sorted(programacion.estado_guardado(self.proy, fisica=True)), [2026])
        self.assertTrue(all(b["columnas"][0]["en_fisica"] for b in programacion.matriz(self.proy)["bloques"]))
        self.assertTrue(programacion.matriz_fisica(self.proy)["bloques"][0]["filas"][0]["del_producto"])
        self.proy.refresh_from_db()
        self.assertEqual((self.proy.valor_sgr, self.proy.valor_total), (Decimal(300), Decimal(300)))

    def test_el_descuadre_mira_todo_el_proyecto(self):
        self.guardar_financiera({(self.regional, self.via): "100"}, vigencia=2025)
        respuesta = self.guardar_fisica({self.km: "10", self.puentes: "1"}, vigencia=2026)
        self.assertContains(respuesta, "no coinciden en ninguna vigencia: indicadores sin valor financiero de su "
                                       "producto 999010200.")
        self.assertEqual(programacion.descuadres(self.proy), {"sin_fisica": [], "sin_financiera": ["999010200"]})

    def test_una_vigencia_nueva_de_la_financiera_trae_los_productos_de_la_fisica(self):
        self.guardar_fisica({self.km: "10"}, vigencia=2026)
        respuesta = self.client.get(self.url("pf_matriz"), {"panel": "financiera", "vigencias": [2025],
                                                            "agregar_vigencia": 2027})
        bloques = {b["vigencia"]: b["productos"] for b in respuesta.context["m"]["bloques"]}
        self.assertEqual(bloques, {2025: [], 2027: [self.via.pk]})

    def test_la_ventana_marca_lo_de_la_otra_pestana(self):
        self.guardar_financiera({(self.regional, self.via): "100"}, vigencia=2025)   # otra vigencia: igual marca
        respuesta = self.client.get(self.url("pf_elegir"), {"panel": "fisica", "tipo": "indicador", "en": 2026,
                                                            "vigencias": [2026], "q": "99901"})
        lista = respuesta.context["lista"]
        self.assertEqual(lista[0][:2], (self.km.pk, "999010100"))
        self.assertTrue(lista[0][3])                              # del producto
        self.assertFalse(next(x for x in lista if x[0] == self.puentes.pk)[3])


class PorEntidadAportante(Base):
    """La financiera es la combinacion proyecto, vigencia, entidad aportante, fuente y producto."""

    def test_dos_entidades_en_la_misma_fuente_y_producto(self):
        e1, e2 = self.entidad.pk, self.municipio.pk
        datos = {"panel": "financiera", "vigencias": [2026], "entidades-2026": [e1, e2],
                 f"fuentes-2026-{e1}": [self.regional.pk], f"fuentes-2026-{e2}": [self.regional.pk],
                 "productos-2026": [self.via.pk],
                 f"v-2026-{e1}-{self.regional.pk}-{self.via.pk}": "100",
                 f"v-2026-{e2}-{self.regional.pk}-{self.via.pk}": "40"}
        respuesta = self.client.post(self.url("pf_guardar"), datos)
        self.assertContains(respuesta, "Guardado: 2 nuevos.")
        self.assertContains(respuesta, "<b>Municipio de Coveñas</b>")
        self.proy.refresh_from_db()
        self.assertEqual((self.proy.valor_sgr, self.proy.valor_total), (Decimal(140), Decimal(140)))
        self.assertEqual(self.proy.fuentes, "SGR - Asignación para la inversión regional 60%")

    def test_lo_programado_sin_entidad_no_se_guarda_hasta_asignarla(self):
        ProgramacionFinancieraRegalias.objects.create(proyecto=self.proy, vigencia=2026, fuente=self.regional,
                                                      producto=self.via, valor=100)
        respuesta = self.client.get(self.url("programacion"))
        self.assertContains(respuesta, "Sin entidad aportante")
        self.assertContains(respuesta, "Hay valores sin entidad aportante en 2026")
        respuesta = self.guardar_financiera({(self.regional, self.via): "100"}, entidad=0)
        self.assertContains(respuesta, "Asigne la entidad aportante antes de guardar.")
        sin = f"v-2026-0-{self.regional.pk}-{self.via.pk}"
        respuesta = self.client.get(self.url("pf_matriz"), {
            "panel": "financiera", "vigencias": [2026], "entidades-2026": [0], "fuentes-2026-0": [self.regional.pk],
            "productos-2026": [self.via.pk], sin: "100", "en": 2026, "asignar_entidad": self.municipio.pk})
        con = f"v-2026-{self.municipio.pk}-{self.regional.pk}-{self.via.pk}"
        self.assertContains(respuesta, f'name="{con}" id="pf-{con}" value="100"')
        self.assertContains(self.guardar_financiera({(self.regional, self.via): "100"}, entidad=self.municipio),
                            "Guardado: 1 nuevos, 1 borrados.")
        self.assertEqual(ProgramacionFinancieraRegalias.objects.get().entidad_aportante, self.municipio)

    def test_la_fuente_se_agrega_a_una_entidad(self):
        base = {"panel": "financiera", "vigencias": [2026], "entidades-2026": [self.entidad.pk],
                "productos-2026": [self.via.pk]}
        respuesta = self.client.get(self.url("pf_elegir"), {**base, "tipo": "fuente", "en": 2026,
                                                            "entidad": self.entidad.pk})
        self.assertContains(respuesta, f"Agregar una fuente de Departamento de Sucre a 2026")
        self.assertEqual(self.client.get(self.url("pf_elegir"), {**base, "tipo": "fuente", "en": 2026}).status_code, 400)
        respuesta = self.client.get(self.url("pf_matriz"), {**base, "en": 2026, "entidad": self.entidad.pk,
                                                            "agregar_fuente": self.nacion.pk})
        self.assertContains(respuesta, f'name="v-2026-{self.entidad.pk}-{self.nacion.pk}-{self.via.pk}"')


class ValoresYListas(Base):
    def test_valores_por_clasificacion(self):
        otra = FuenteSGR.objects.create(nombre="Cooperación", clasificacion=C.NO_SUIFP)
        for fuente, valor in ((self.regional, 10), (self.regional, 5), (otra, 7)):
            ProgramacionFinancieraRegalias.objects.create(proyecto=self.proy, vigencia=2025 if valor == 5 else 2026,
                                                          fuente=fuente, producto=self.via, valor=valor)
        valores = servicios.valores_de_programacion(self.proy)
        self.assertEqual((valores["valor_sgr"], valores["valor_otras_no_suifp"], valores["valor_total"]),
                         (Decimal(15), Decimal(7), Decimal(22)))

    def test_las_listas_de_programacion_son_de_consulta(self):
        self.guardar_financiera({(self.regional, self.via): "100"})
        fila = ProgramacionFinancieraRegalias.objects.get()
        self.assertEqual(self.client.get(reverse("admin:regalias_programacionfinancieraregalias_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:regalias_programacionfinancieraregalias_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:regalias_programacionfinancieraregalias_delete",
                                                 args=(fila.pk,))).status_code, 403)

    def test_el_rol_mantiene_las_fuentes_sgr(self):
        respuesta = self.client.post(reverse("admin:regalias_fuentesgr_add"),
                                     {"nombre": "SGR - Asignaciones directas", "clasificacion": C.SGR})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(FuenteSGR.objects.filter(nombre="SGR - Asignaciones directas").exists())
