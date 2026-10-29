# -*- coding: utf-8 -*-
"""La programacion de proyectos en las metas, traida del Access "Seguimiento PDD STO".

La base de pruebas ya trae los datos: la migracion 0014 los carga al crearla.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from siifweb.models import (MetaIndicador, Municipio, ObservacionProyecto, ProgramacionMeta,
                            ProgramacionProyectos, TipoBanco)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser("admin", "a@b.co", "clave")

    def setUp(self):
        self.client.force_login(self.usuario)


class LosDatosMigrados(TestCase):
    def test_las_cifras_de_la_migracion(self):
        self.assertEqual(ProgramacionProyectos.objects.count(), 1265)
        self.assertEqual(ProgramacionMeta.objects.count(), 1609)
        self.assertEqual(ObservacionProyecto.objects.count(), 539)

    def test_las_observaciones_de_access_no_tienen_fecha(self):
        self.assertFalse(ObservacionProyecto.objects.exclude(fecha=None).exists())

    def test_el_bpin_solo_guarda_codigos(self):
        """Los textos ("Por Gestion"...) quedaron como observacion del proyecto."""
        for bpin in ProgramacionProyectos.objects.exclude(bpin="").values_list("bpin", flat=True):
            self.assertTrue(bpin.isdigit(), bpin)
        self.assertTrue(ObservacionProyecto.objects.filter(texto__startswith="BPIN en Access: Por").exists())

    def test_los_municipios_son_los_26_mas_todo_el_departamento(self):
        self.assertEqual(Municipio.objects.count(), 27)
        self.assertTrue(Municipio.objects.filter(nombre="Todo el departamento").exists())

    def test_sin_tipo_de_banco_queda_vacio(self):
        self.assertFalse(TipoBanco.objects.filter(nombre__icontains="sin tipo").exists())

    def test_la_vigencia_del_proyecto_lista_las_de_sus_programaciones(self):
        for proyecto in ProgramacionProyectos.objects.filter(programaciones__isnull=False).distinct()[:200]:
            self.assertEqual(proyecto.vigencias, proyecto.vigencias_programadas(), proyecto.pk)

    def test_la_meta_de_la_vigencia_guarda_exactos_los_cuatro_decimales_de_access(self):
        """Access trae metas viales con cuatro decimales (3,0976 km): con cinco no se redondean."""
        self.assertEqual(ProgramacionMeta._meta.get_field("meta_vigencia").decimal_places, 5)
        self.assertTrue(ProgramacionMeta.objects.filter(meta_vigencia=Decimal("3.0976")).exists())
        self.assertTrue(ProgramacionMeta.objects.filter(meta_vigencia=Decimal("96.1669")).exists())
        self.assertFalse(ObservacionProyecto.objects.filter(texto__contains="guardada como").exists())


class ElMenu(Base):
    def items(self, titulo):
        grupo = next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == titulo)
        return [str(i["link"]) for i in grupo["items"]]

    def test_la_programacion_va_en_seguimiento_despues_de_las_metas(self):
        enlaces = self.items("Seguimiento")
        metas = enlaces.index(reverse("admin:siifweb_metaindicador_changelist"))
        self.assertEqual(enlaces[metas + 1], reverse("admin:siifweb_programacionproyectos_changelist"))
        self.assertNotIn(reverse("admin:siifweb_programacionproyectos_changelist"), self.items("Plan de Desarrollo"))

    def test_los_roles_del_equipo_no_ven_enlaces_que_les_den_403(self):
        """Metas y programacion van con el permiso de su modelo, que los roles no tienen."""
        from django.contrib.auth.models import Group
        grupo = next(g for g in settings.UNFOLD["SIDEBAR"]["navigation"] if g["title"] == "Seguimiento")
        for rol in ("Seguimiento", "Consulta"):
            usuario = get_user_model().objects.create_user(f"u_{rol}", "x@b.co", "clave", is_staff=True)
            usuario.groups.add(Group.objects.get(name=rol))
            self.client.force_login(usuario)
            peticion = type("Peticion", (), {"user": usuario})()
            for item in grupo["items"]:
                if item["permission"](peticion):
                    with self.subTest(rol=rol, item=item["title"]):
                        self.assertEqual(self.client.get(str(item["link"])).status_code, 200)

    def test_tipos_de_banco_y_municipios_van_en_parametrizacion(self):
        enlaces = self.items("Configuración y parametrización")
        self.assertIn(reverse("admin:siifweb_tipobanco_changelist"), enlaces)
        self.assertIn(reverse("admin:siifweb_municipio_changelist"), enlaces)


class LasPaginas(Base):
    def test_el_listado_y_el_detalle_abren(self):
        proyecto = ProgramacionProyectos.objects.filter(programaciones__isnull=False,
                                                        observaciones__isnull=False).first()
        self.assertEqual(self.client.get(reverse("admin:siifweb_programacionproyectos_changelist")).status_code, 200)
        respuesta = self.client.get(reverse("admin:siifweb_programacionproyectos_change", args=(proyecto.pk,)))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "programaciones-TOTAL_FORMS")
        self.assertContains(respuesta, "observaciones-TOTAL_FORMS")

    def test_buscar_por_codigo_de_meta_no_repite_proyectos(self):
        respuesta = self.client.get(reverse("admin:siifweb_programacionproyectos_changelist"), {"q": "MT0"})
        resultados = list(respuesta.context["cl"].result_list)
        self.assertEqual(len(resultados), len({p.pk for p in resultados}))


class GuardarEnElAdmin(Base):
    """Las vigencias del proyecto se recalculan de sus programaciones al guardar."""

    def test_agregar_una_programacion_actualiza_las_vigencias(self):
        meta = MetaIndicador.objects.first()
        proyecto = ProgramacionProyectos.objects.create(nombre="Proyecto de prueba", vigencias="2025")
        existente = ProgramacionMeta.objects.create(proyecto=proyecto, meta=meta, vigencia=2025,
                                                    meta_vigencia=Decimal("10"))
        datos = {
            "bpin": "", "nombre": "Proyecto de prueba", "tipo_banco": "",
            "programaciones-TOTAL_FORMS": "2", "programaciones-INITIAL_FORMS": "1",
            "programaciones-MIN_NUM_FORMS": "0", "programaciones-MAX_NUM_FORMS": "1000",
            "programaciones-0-id": existente.pk, "programaciones-0-proyecto": proyecto.pk,
            "programaciones-0-meta": meta.pk, "programaciones-0-vigencia": "2025",
            "programaciones-0-meta_vigencia": "10",
            "programaciones-1-proyecto": proyecto.pk, "programaciones-1-meta": meta.pk,
            "programaciones-1-vigencia": "2027", "programaciones-1-meta_vigencia": "11.187",
            "observaciones-TOTAL_FORMS": "0", "observaciones-INITIAL_FORMS": "0",
            "observaciones-MIN_NUM_FORMS": "0", "observaciones-MAX_NUM_FORMS": "1000",
        }
        respuesta = self.client.post(
            reverse("admin:siifweb_programacionproyectos_change", args=(proyecto.pk,)), datos)
        self.assertEqual(respuesta.status_code, 302, respuesta.context and respuesta.context.get("errors"))
        proyecto.refresh_from_db()
        self.assertEqual(proyecto.vigencias, "2025, 2027")
        self.assertEqual(proyecto.programaciones.get(vigencia=2027).meta_vigencia, Decimal("11.187"))

    def test_una_observacion_nueva_lleva_la_fecha_del_dia(self):
        proyecto = ProgramacionProyectos.objects.create(nombre="Otro proyecto")
        nota = ObservacionProyecto.objects.create(proyecto=proyecto, texto="Revisado en comite")
        self.assertEqual(nota.fecha, timezone.localdate())


class LosProyectosDesdeLaMeta(Base):
    """El desplegable de proyectos en el listado de metas."""

    def meta_con_proyectos(self):
        return MetaIndicador.objects.filter(programaciones_de_proyectos__isnull=False).order_by("-codigo").first()

    def test_el_listado_de_metas_despliega_sus_proyectos(self):
        meta = self.meta_con_proyectos()
        programacion = meta.programaciones_de_proyectos.select_related("proyecto").first()
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_changelist"), {"q": meta.codigo})
        self.assertEqual(respuesta.status_code, 200)
        for encabezado in ("Proyectos programados", "BPIN", "Proyecto", "Vigencia",
                           "Meta de la vigencia", "Tipo de banco"):
            with self.subTest(encabezado=encabezado):
                self.assertContains(respuesta, encabezado)
        self.assertContains(respuesta, programacion.proyecto.nombre[:40])

    def test_las_cifras_van_sin_ceros_que_sobran(self):
        from siifweb.admin import cifra
        self.assertEqual(cifra(Decimal("15.00000")), "15")
        self.assertEqual(cifra(Decimal("3.09760")), "3,0976")
        self.assertEqual(cifra(Decimal("1715.00000")), "1.715")
        self.assertEqual(cifra(None), "-")

    def test_el_detalle_de_la_meta_no_trae_tabla_de_proyectos(self):
        """Los proyectos se ven en el desplegable del listado; el detalle solo edita la meta."""
        meta = self.meta_con_proyectos()
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_change", args=(meta.pk,)))
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, "programaciones_de_proyectos-TOTAL_FORMS")
        self.assertContains(respuesta, "vigencias-TOTAL_FORMS")


class LaFichaDeLaMeta(Base):
    def meta(self):
        return (MetaIndicador.objects.filter(programaciones_de_proyectos__meta_vigencia__isnull=False)
                .distinct().order_by("codigo").first())

    def url(self, meta):
        return reverse("admin:siifweb_metaindicador_ficha", args=(meta.pk,))

    def test_el_listado_va_de_menor_a_mayor_y_enlaza_la_ficha(self):
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_changelist"))
        codigos = [m.codigo for m in respuesta.context["cl"].result_list]
        self.assertEqual(codigos, sorted(codigos))
        self.assertEqual(codigos[0], MetaIndicador.objects.order_by("codigo").first().codigo)
        self.assertContains(respuesta, self.url(respuesta.context["cl"].result_list[0]))

    def test_la_ficha_cuadra_lo_programado_por_vigencia(self):
        from django.db.models import Sum
        meta = self.meta()
        respuesta = self.client.get(self.url(meta))
        self.assertEqual(respuesta.status_code, 200)
        filas = {f["vigencia"]: f for f in respuesta.context["filas"]}
        from siifweb.admin import cifra
        for vigencia, total in (meta.programaciones_de_proyectos.exclude(vigencia=None)
                                .values_list("vigencia").annotate(t=Sum("meta_vigencia"))):
            with self.subTest(vigencia=vigencia):
                self.assertEqual(filas[vigencia]["programado"], cifra(total or Decimal(0)))
        for v in meta.vigencias.all():
            with self.subTest(vigencia_del_plan=v.vigencia):
                self.assertEqual(filas[v.vigencia]["meta"], cifra(v.valor))
        # Cada programacion esta en el desplegable de su vigencia, y en ninguno mas
        self.assertEqual(sum(len(f["detalle"]) for f in respuesta.context["filas"]),
                         meta.programaciones_de_proyectos.count())
        self.assertNotContains(respuesta, "Proyectos programados (")

    def test_cada_proyecto_abre_su_detalle_en_un_modal(self):
        respuesta = self.client.get(self.url(self.meta()))
        self.assertContains(respuesta, 'id="modal-detalle"')
        self.assertContains(respuesta, "data-detalle")
        self.assertContains(respuesta, "data-municipios=")

    def test_una_meta_que_no_existe_da_404(self):
        self.assertEqual(self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(999999,))).status_code, 404)

    def test_quien_no_ve_metas_no_entra(self):
        otro = get_user_model().objects.create_user("sinrol", "s@b.co", "clave", is_staff=True)
        self.client.force_login(otro)
        self.assertEqual(self.client.get(self.url(self.meta())).status_code, 403)

    def test_cada_vigencia_despliega_sus_proyectos(self):
        meta = self.meta()
        respuesta = self.client.get(self.url(meta))
        for fila in respuesta.context["filas"]:
            if fila["vigencia"] == "Sin vigencia":
                continue
            with self.subTest(vigencia=fila["vigencia"]):
                self.assertEqual(len(fila["detalle"]),
                                 meta.programaciones_de_proyectos.filter(vigencia=fila["vigencia"]).count())
        self.assertContains(respuesta, "data-desplegar")
        self.assertContains(respuesta, "detalle-vigencia hidden")

    def test_el_icono_de_la_ficha_es_una_carpeta(self):
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_changelist"))
        self.assertContains(respuesta, "folder_open")

    def test_el_modal_lista_todas_las_metas_del_proyecto(self):
        from django.db.models import Count
        from siifweb.admin import cifra
        proyecto = (ProgramacionProyectos.objects.annotate(n=Count("programaciones__meta", distinct=True))
                    .filter(n__gt=1).first())
        meta = proyecto.programaciones.first().meta
        respuesta = self.client.get(self.url(meta))
        d = next(d for f in respuesta.context["filas"] for d in f["detalle"]
                 if d["programacion"].proyecto_id == proyecto.pk)
        lineas = d["metas"].split("\n")
        self.assertEqual(len(lineas), proyecto.programaciones.count())
        for p in proyecto.programaciones.select_related("meta"):
            with self.subTest(meta=p.meta.codigo, vigencia=p.vigencia):
                self.assertIn(f"{p.meta.codigo}\t{p.vigencia or 'Sin vigencia'}\t{cifra(p.meta_vigencia)}", lineas)
        self.assertContains(respuesta, f'data-meta="{meta.codigo}"')


class LaEjecucionEnLaFichaDeLaMeta(Base):
    """El cruce BPIN + vigencia con SIIFWEB: compromisos, obligaciones, pagos y reservas."""

    def setUp(self):
        super().setUp()
        from datetime import date
        from siifweb.models import Reserva, ReservaImputacion
        from .fabricas import cadena, catalogos, proyecto, tercero
        # Un proyecto programado con BPIN en 2025, y ese BPIN en SIIFWEB con su cadena
        self.programacion = (ProgramacionMeta.objects.filter(vigencia=2025)
                             .exclude(proyecto__bpin="").select_related("proyecto", "meta").first())
        self.meta = self.programacion.meta
        self.bpin = self.programacion.proyecto.bpin
        self.siifweb = proyecto(bpin=self.bpin, nombre="El mismo en SIIFWEB")
        cadena(self.siifweb, vigencia=2025)          # RP y obligacion de 10.000.000, pagado 5.000.000
        rubro, fuente, _ = catalogos()
        reserva = Reserva.objects.create(vigencia=2025, nro_reserva="7", fecha_reserva=date(2025, 1, 2),
                                         beneficiario=tercero())
        ReservaImputacion.objects.create(reserva=reserva, rubro=rubro, fuente=fuente, proyecto=self.siifweb,
                                         valor_reserva=Decimal("800000"), valor_reserva_def=Decimal("750000"),
                                         obligaciones_reserva=Decimal(0), pagos_reserva=Decimal(0),
                                         saldo_reserva=Decimal("750000"))

    def ficha(self):
        return self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(self.meta.pk,)))

    def test_la_fila_de_la_vigencia_trae_la_plata_de_sus_proyectos(self):
        fila = next(f for f in self.ficha().context["filas"] if f["vigencia"] == 2025)
        self.assertEqual(fila["ejecucion"], {"comprometido": Decimal("10000000"), "obligado": Decimal("10000000"),
                                             "pagado": Decimal("5000000"), "reservas": Decimal("750000")})

    def test_cada_proyecto_del_desplegable_trae_la_suya(self):
        fila = next(f for f in self.ficha().context["filas"] if f["vigencia"] == 2025)
        d = next(d for d in fila["detalle"] if d["programacion"].pk == self.programacion.pk)
        self.assertEqual(d["siifweb"]["comprometido"], Decimal("10000000"))
        self.assertEqual(d["siifweb"]["reservas"], Decimal("750000"))

    def test_otra_vigencia_no_se_mezcla(self):
        for f in self.ficha().context["filas"]:
            if f["vigencia"] != 2025 and f["ejecucion"]:
                with self.subTest(vigencia=f["vigencia"]):
                    self.assertEqual(f["ejecucion"]["comprometido"], Decimal(0))

    def test_el_modal_trae_las_cifras_y_el_enlace_a_la_ficha_de_ejecucion(self):
        respuesta = self.ficha()
        self.assertContains(respuesta, reverse("admin:siifweb_proyecto_ficha_ejecucion", args=(self.siifweb.pk,)))
        self.assertContains(respuesta, 'data-comprometido="10.000.000"')
        self.assertContains(respuesta, 'data-pagado="5.000.000"')


class LasObservacionesDesdeElModal(Base):
    def setUp(self):
        super().setUp()
        self.proyecto = ProgramacionProyectos.objects.filter(programaciones__isnull=False).first()
        self.url = reverse("admin:siifweb_programacionproyectos_observacion", args=(self.proyecto.pk,))

    def test_guarda_la_observacion_con_la_fecha_del_dia(self):
        respuesta = self.client.post(self.url, {"texto": "  Revisado en el comite de seguimiento  "})
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json(), {"fecha": f"{timezone.localdate():%Y-%m-%d}",
                                            "texto": "Revisado en el comite de seguimiento"})
        nota = self.proyecto.observaciones.get(texto="Revisado en el comite de seguimiento")
        self.assertEqual(nota.fecha, timezone.localdate())

    def test_una_observacion_vacia_no_se_guarda(self):
        antes = self.proyecto.observaciones.count()
        self.assertEqual(self.client.post(self.url, {"texto": "   "}).status_code, 400)
        self.assertEqual(self.proyecto.observaciones.count(), antes)

    def test_solo_por_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_sin_permiso_no_se_guarda_ni_se_ofrece(self):
        from django.contrib.auth.models import Group
        otro = get_user_model().objects.create_user("consulta1", "c@b.co", "clave", is_staff=True)
        otro.groups.add(Group.objects.get(name="Consulta"))
        from django.contrib.auth.models import Permission
        otro.user_permissions.add(Permission.objects.get(codename="view_metaindicador"))
        self.client.force_login(otro)
        self.assertEqual(self.client.post(self.url, {"texto": "algo"}).status_code, 403)
        meta = self.proyecto.programaciones.first().meta
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(meta.pk,)))
        self.assertContains(respuesta, 'data-observacion-url=""')

    def test_la_ficha_ofrece_el_formulario_a_quien_puede(self):
        meta = self.proyecto.programaciones.first().meta
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(meta.pk,)))
        self.assertContains(respuesta, 'id="nueva-observacion"')
        self.assertContains(respuesta, f'data-observacion-url="{self.url}"')
        self.assertContains(respuesta, "csrfmiddlewaretoken")


class NuevoProyectoDesdeLaFicha(Base):
    def setUp(self):
        super().setUp()
        self.meta = MetaIndicador.objects.get(codigo="MT323")
        self.ficha = reverse("admin:siifweb_metaindicador_ficha", args=(self.meta.pk,))
        self.alta = reverse("admin:siifweb_programacionproyectos_add")

    def enlace(self):
        return self.client.get(self.ficha).context["nuevo_proyecto"]

    def datos(self, **cambios):
        datos = {
            "bpin": "", "nombre": "Proyecto nuevo desde la ficha", "tipo_banco": "",
            "programaciones-TOTAL_FORMS": "1", "programaciones-INITIAL_FORMS": "0",
            "programaciones-MIN_NUM_FORMS": "0", "programaciones-MAX_NUM_FORMS": "1000",
            "programaciones-0-meta": self.meta.pk, "programaciones-0-vigencia": "2026",
            "programaciones-0-meta_vigencia": "2.5",
            "observaciones-TOTAL_FORMS": "0", "observaciones-INITIAL_FORMS": "0",
            "observaciones-MIN_NUM_FORMS": "0", "observaciones-MAX_NUM_FORMS": "1000",
        }
        datos.update(cambios)
        return datos

    def test_la_ficha_tiene_el_boton_y_el_formulario_completo_con_la_meta(self):
        respuesta = self.client.get(self.ficha)
        self.assertContains(respuesta, "Programar proyecto")
        self.assertContains(respuesta, "Abrir el formulario completo")
        self.assertTrue(self.enlace().startswith(self.alta + "?"))
        self.assertIn(f"meta={self.meta.pk}", self.enlace())

    def test_el_formulario_llega_con_la_meta_puesta(self):
        respuesta = self.client.get(self.enlace())
        self.assertEqual(respuesta.status_code, 200)
        formset = next(f for f in respuesta.context["inline_admin_formsets"]
                       if f.formset.prefix == "programaciones").formset
        self.assertEqual(len(formset.forms), 1)
        self.assertEqual(formset.forms[0].initial.get("meta"), self.meta.pk)

    def test_sin_venir_de_la_ficha_el_formulario_no_trae_filas(self):
        respuesta = self.client.get(self.alta)
        formset = next(f for f in respuesta.context["inline_admin_formsets"]
                       if f.formset.prefix == "programaciones").formset
        self.assertEqual(len(formset.forms), 0)

    def test_al_guardar_vuelve_a_la_ficha(self):
        respuesta = self.client.post(self.enlace(), self.datos())
        self.assertRedirects(respuesta, self.ficha, fetch_redirect_response=False)
        proyecto = ProgramacionProyectos.objects.get(nombre="Proyecto nuevo desde la ficha")
        self.assertEqual(proyecto.vigencias, "2026")
        self.assertEqual(proyecto.programaciones.get().meta, self.meta)

    def test_guardar_y_continuar_sigue_en_el_proyecto(self):
        respuesta = self.client.post(self.enlace(), self.datos(_continue="1"))
        proyecto = ProgramacionProyectos.objects.get(nombre="Proyecto nuevo desde la ficha")
        # El admin conserva la query (?meta=...&volver=...); en un proyecto que ya existe no hace nada
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta["Location"].split("?")[0],
                         reverse("admin:siifweb_programacionproyectos_change", args=(proyecto.pk,)))

    def test_no_vuelve_a_una_direccion_de_otro_sitio(self):
        respuesta = self.client.post(f"{self.alta}?meta={self.meta.pk}&volver=https://otro.example/",
                                     self.datos())
        self.assertNotEqual(respuesta["Location"], "https://otro.example/")

    def test_sin_permiso_de_crear_no_hay_boton(self):
        from django.contrib.auth.models import Permission
        otro = get_user_model().objects.create_user("solo_ve", "v@b.co", "clave", is_staff=True)
        otro.user_permissions.add(Permission.objects.get(codename="view_metaindicador"))
        self.client.force_login(otro)
        respuesta = self.client.get(self.ficha)
        self.assertEqual(respuesta.context["nuevo_proyecto"], "")
        self.assertIsNone(respuesta.context["programar"])
        self.assertNotContains(respuesta, "Programar proyecto")


class ProgramarDesdeElModal(Base):
    """El modal de la ficha: programar un proyecto existente o uno nuevo, en una o varias metas."""

    def setUp(self):
        super().setUp()
        self.meta = MetaIndicador.objects.get(codigo="MT323")
        self.otra = MetaIndicador.objects.get(codigo="MT010")
        self.url = reverse("admin:siifweb_metaindicador_programar", args=(self.meta.pk,))
        self.buscar = reverse("admin:siifweb_metaindicador_buscar_proyectos", args=(self.meta.pk,))

    def programar(self, filas, **datos):
        """filas: [(meta, vigencia, valor)], como las listas paralelas del modal."""
        datos.update({"meta": [m.pk for m, _, _ in filas], "vigencia": [v for _, v, _ in filas],
                      "meta_vigencia": [x for _, _, x in filas]})
        return self.client.post(self.url, datos)

    def test_la_ficha_ofrece_el_modal_con_la_meta_y_los_catalogos(self):
        respuesta = self.client.get(reverse("admin:siifweb_metaindicador_ficha", args=(self.meta.pk,)))
        self.assertContains(respuesta, 'id="modal-programar"')
        self.assertContains(respuesta, f'data-url="{self.url}"')
        programar = respuesta.context["programar"]
        self.assertEqual(programar["vigencias"], [2024, 2025, 2026, 2027])
        self.assertEqual(len(programar["metas"]), MetaIndicador.objects.count())
        self.assertEqual(programar["municipios"].count(), 27)
        self.assertContains(respuesta, 'name="municipios"')
        self.assertContains(respuesta, 'name="observacion"')

    def test_buscar_por_bpin_trae_primero_el_exacto_y_marca_los_de_la_meta(self):
        propio = (self.meta.programaciones_de_proyectos.exclude(proyecto__bpin="")
                  .select_related("proyecto").first().proyecto)
        resultados = self.client.get(self.buscar, {"q": propio.bpin}).json()["resultados"]
        self.assertEqual(resultados[0]["id"], propio.pk)
        self.assertTrue(resultados[0]["en_la_meta"])
        self.assertEqual(self.client.get(self.buscar, {"q": "ab"}).json()["resultados"], [])

    def test_un_proyecto_existente_en_esta_meta_y_en_otra(self):
        proyecto = (ProgramacionProyectos.objects.exclude(programaciones__meta=self.meta)
                    .exclude(programaciones__meta=self.otra).first())
        respuesta = self.programar([(self.meta, 2026, "3,0976"), (self.otra, 2027, "")],
                                   modo="existente", proyecto=proyecto.pk, observacion="Revisado")
        self.assertEqual(respuesta.status_code, 201)
        self.assertTrue(respuesta.json()["volver"].endswith("?abrir=2026"))
        self.assertEqual(proyecto.programaciones.get(meta=self.meta).meta_vigencia, Decimal("3.0976"))
        self.assertIsNone(proyecto.programaciones.get(meta=self.otra).meta_vigencia)
        self.assertEqual(proyecto.observaciones.get(texto="Revisado").fecha, timezone.localdate())
        proyecto.refresh_from_db()
        self.assertIn("2026", proyecto.vigencias)
        self.assertIn("2027", proyecto.vigencias)

    def test_un_proyecto_nuevo_con_municipios(self):
        banco = TipoBanco.objects.first()
        municipios = list(Municipio.objects.order_by("nombre")[:2])
        respuesta = self.programar([(self.meta, 2025, "")], modo="nuevo", nombre="  Via  nueva de prueba  ",
                                   bpin="209900000000001", tipo_banco=banco.pk,
                                   municipios=[m.pk for m in municipios])
        self.assertEqual(respuesta.status_code, 201)
        proyecto = ProgramacionProyectos.objects.get(bpin="209900000000001")
        self.assertEqual((proyecto.nombre, proyecto.tipo_banco, proyecto.vigencias),
                         ("Via nueva de prueba", banco, "2025"))
        self.assertEqual(set(proyecto.municipios.all()), set(municipios))

    def test_un_nuevo_con_bpin_o_nombre_que_ya_existen_se_rechaza(self):
        existente = ProgramacionProyectos.objects.exclude(bpin="").first()
        for datos in ({"bpin": existente.bpin, "nombre": "Otro nombre"},
                      {"bpin": "", "nombre": existente.nombre.upper() + "."}):
            with self.subTest(datos=datos):
                antes = ProgramacionProyectos.objects.count()
                respuesta = self.programar([(self.meta, 2025, "")], modo="nuevo", **datos)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn("Ya existe", respuesta.json()["error"])
                self.assertEqual(ProgramacionProyectos.objects.count(), antes)

    def test_todo_o_nada_si_una_fila_ya_estaba_programada(self):
        p = self.meta.programaciones_de_proyectos.exclude(vigencia=None).first()
        antes = ProgramacionMeta.objects.count()
        respuesta = self.programar([(self.otra, 2027, "1"), (self.meta, p.vigencia, "")],
                                   modo="existente", proyecto=p.proyecto_id)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("ya está programado", respuesta.json()["error"])
        self.assertEqual(ProgramacionMeta.objects.count(), antes)       # tampoco la de MT010

    def test_los_datos_invalidos_se_avisan_con_su_fila(self):
        proyecto = ProgramacionProyectos.objects.first()
        casos = [([(self.meta, "", "")], "fila 1: elija la vigencia"),
                 ([(self.meta, 2026, ""), (self.otra, 2026, "abc")], "fila 2"),
                 ([(self.meta, 2026, "1.123456")], "cinco"),
                 ([(self.meta, 2026, ""), (self.meta, 2026, "")], "repetida"),
                 ([], "al menos una meta")]
        for filas, mensaje in casos:
            with self.subTest(mensaje=mensaje):
                respuesta = self.programar(filas, modo="existente", proyecto=proyecto.pk)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(mensaje.lower(), respuesta.json()["error"].lower())
        for datos, mensaje in (({"modo": "existente", "proyecto": ""}, "elija el proyecto"),
                               ({"modo": "nuevo", "nombre": ""}, "nombre"),
                               ({"modo": "nuevo", "nombre": "X", "bpin": "12A"}, "bpin")):
            with self.subTest(mensaje=mensaje):
                respuesta = self.programar([(self.meta, 2026, "")], **datos)
                self.assertIn(mensaje, respuesta.json()["error"].lower())

    def test_solo_por_post_y_con_permiso(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        from django.contrib.auth.models import Permission
        otro = get_user_model().objects.create_user("solo_ve2", "v@b.co", "clave", is_staff=True)
        otro.user_permissions.add(Permission.objects.get(codename="view_metaindicador"))
        self.client.force_login(otro)
        self.assertEqual(self.programar([(self.meta, 2026, "")], modo="existente").status_code, 403)
        self.assertEqual(self.client.get(self.buscar, {"q": "pavimento"}).status_code, 403)
