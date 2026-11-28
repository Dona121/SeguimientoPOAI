"""Importacion de la matriz y cargas de GESPROY.

La regla que se prueba en todas: se actualizan los campos de las llaves que aparecen y solo
con valores llenos; lo que no viene, o viene vacio, se deja.
"""
import tempfile
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from siifweb.models import DependenciaResponsable, Municipio, SectorMGA

from regalias import cargas, lectura
from regalias.models import (CambioProyectoRegalias, CargaRegalias, ContratoRegalias, EntidadEjecutora,
                             EstadoProyectoRegalias, ProyectoRegalias)

from .fabricas import DEPARTAMENTO, DESCENTRALIZADA, MUNICIPIO, estado, matriz, proyecto, reporte, usuario_de

EJECUCION = "CONTRATADO EN EJECUCIÓN"


def cargar(tipo, origen, usuario=None):
    carga = CargaRegalias.objects.create(tipo=tipo, usuario=usuario)
    cargas.procesar(carga, origen)
    return carga


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.transporte = SectorMGA.objects.get_or_create(codigo="24", defaults={"descripcion": "Transporte"})[0]
        cls.salud = DependenciaResponsable.objects.get_or_create(nombre="Secretaría de Salud")[0]
        cls.aguas = DependenciaResponsable.objects.get_or_create(nombre="Plan Departamental de Aguas")[0]
        cls.municipios = {n: Municipio.objects.get_or_create(nombre=n)[0] for n in (
            "Morroa", "Colosó", "San José De Toluviejo", "Palmito", "Ovejas", "San Onofre", "Sincelejo")}


class LecturaDeLosReportes(Base):
    def test_rechaza_un_reporte_de_otro_tipo(self):
        carga = cargar("proyectos", reporte("contratos", [{"BPIN": "1"}]))
        self.assertEqual(carga.estado, CargaRegalias.Estado.ERROR)
        self.assertIn("Parece un reporte de tipo contratos", carga.mensaje)

    def test_avisa_las_columnas_que_faltan(self):
        # Titulo de CG-carga con las columnas de CG-proy
        libro = reporte("proyectos", [{"BPIN": "1"}], titulo="CARGUE INFORMACIÓN EN GESPROY-SGR")
        with self.assertRaisesMessage(ValueError, "faltan columnas: AVANCE FISICO"):
            lectura.leer_reporte(libro, "cargue")

    def test_limpia_los_encabezados_con_tabulaciones(self):
        filas = lectura.leer_reporte(reporte("proyectos", [{"BPIN": "2025000020001", "NOMBRE PROYECTO": "Vía"}]),
                                     "proyectos")
        self.assertEqual(filas[0]["BPIN"], "2025000020001")
        self.assertEqual(filas[0]["NOMBRE PROYECTO"], "Vía")

    def test_los_municipios_se_separan_y_se_homologan(self):
        resumen = cargas.Resumen("prueba")
        cat = cargas.Catalogos(resumen)
        encontrados, sin_catalogo = cat.municipios_de(
            "Morroa, Colosó, Toluviejo, San\nAntonio de Palmito, Ovejas y San Onofre, Bogotá, D.C.", "1")
        self.assertEqual([m.nombre for m in encontrados],
                         ["Morroa", "Colosó", "San José De Toluviejo", "Palmito", "Ovejas", "San Onofre"])
        self.assertEqual(sin_catalogo, ["Bogotá"])


class CargaDeProyectos(Base):
    def test_crea_el_bpin_nuevo_en_el_departamento(self):
        carga = cargar("proyectos", reporte("proyectos", [{
            "BPIN": "2025000020001", "NOMBRE PROYECTO": "Vía", "SECTOR": "TRANSPORTE",
            "ESTADO PROYECTO": EJECUCION, "VALOR PAGOS": 1500000.5}]))
        self.assertEqual(carga.estado, CargaRegalias.Estado.PROCESADO, carga.mensaje)
        nuevo = ProyectoRegalias.objects.get(bpin="2025000020001")
        self.assertEqual((nuevo.clasificacion.codigo, nuevo.sector, nuevo.estado.codigo, nuevo.valor_pagos),
                         (DEPARTAMENTO, self.transporte, EstadoProyectoRegalias.CONTRATADO_EN_EJECUCION,
                          Decimal("1500000.50000")))
        self.assertTrue(nuevo.cambios.filter(origen=CambioProyectoRegalias.Origen.CARGA, carga=carga).exists())

    def test_lo_vacio_no_borra_y_el_bpin_ausente_no_se_toca(self):
        existente = proyecto("2025000020001", DEPARTAMENTO, valor_pagos=Decimal("10"))
        ausente = proyecto("2025000020002", DEPARTAMENTO, valor_pagos=Decimal("20"))
        carga = cargar("proyectos", reporte("proyectos", [{
            "BPIN": "2025000020001", "NOMBRE PROYECTO": "", "ESTADO PROYECTO": EJECUCION, "VALOR PAGOS": None}]))
        existente.refresh_from_db()
        ausente.refresh_from_db()
        self.assertEqual((existente.nombre, existente.valor_pagos), ("Proyecto 2025000020001", Decimal("10")))
        self.assertEqual(existente.estado.codigo, EstadoProyectoRegalias.CONTRATADO_EN_EJECUCION)
        self.assertIn("Cambios de estado", carga.mensaje)
        self.assertFalse(ausente.cambios.exists())

    def test_un_bpin_nuevo_sin_estado_se_crea_y_se_lista(self):
        carga = cargar("proyectos", reporte("proyectos", [
            {"BPIN": "2025000020003", "NOMBRE PROYECTO": "Sin estado", "ESTADO PROYECTO": ""},
            {"BPIN": "2025000020004", "NOMBRE PROYECTO": "Estado raro", "ESTADO PROYECTO": "SUSPENDIDO"}]))
        self.assertEqual(ProyectoRegalias.objects.filter(bpin__in=["2025000020003", "2025000020004"],
                                                         estado__isnull=True).count(), 2)
        self.assertIn("Pendientes de asignar estado (2)", carga.mensaje)
        self.assertIn("Estados no reconocidos (1): SUSPENDIDO", carga.mensaje)

    def test_el_estado_en_proceso_de_contratacion_existe(self):
        cargar("proyectos", reporte("proyectos", [{
            "BPIN": "2025000020005", "NOMBRE PROYECTO": "En proceso", "ESTADO PROYECTO": "EN PROCESO DE CONTRATACIÓN"}]))
        self.assertEqual(ProyectoRegalias.objects.get(bpin="2025000020005").estado.codigo,
                         EstadoProyectoRegalias.EN_PROCESO_CONTRATACION)


class CargaDeContratos(Base):
    def setUp(self):
        self.proy = proyecto("2021000100333", DEPARTAMENTO)

    def fila(self, numero, suscripcion, tipo="Consultoría", valor=100, **extra):
        return {"BPIN": self.proy.bpin, "CONTRATO NUMERO": numero, "FECHA SUSCRIPCION": suscripcion,
                "TIPO CONTRATO": tipo, "ESTADO CONTRATO": "En ejecución  ", "VALOR TOTAL FUENTES SGR": valor, **extra}

    def test_dos_filas_con_el_mismo_numero_y_fecha_son_dos_contratos(self):
        """Como CONV-RE-SDED-028-2022 en los reportes de mayo a agosto de 2026."""
        cargar("contratos", reporte("contratos", [self.fila("CONV-028-2022", datetime(2022, 12, 30), valor=643),
                                                  self.fila("CONV-028-2022", datetime(2022, 12, 30), valor=365)]))
        self.assertEqual(sorted(self.proy.contratos.values_list("valor_fuentes_sgr", flat=True)),
                         [Decimal("365"), Decimal("643")])

    def test_un_cambio_de_fecha_no_deja_contratos_sobrantes(self):
        """GESPROY cambio la suscripcion de CM-011-2023 de 04/04/2024 a 21/02/2025 entre agosto y noviembre."""
        cargar("contratos", reporte("contratos", [self.fila("CM-011-2023", datetime(2024, 4, 4))]))
        cargar("contratos", reporte("contratos", [self.fila("CM-011-2023", datetime(2025, 2, 21))]))
        self.assertEqual(list(self.proy.contratos.values_list("fecha_suscripcion", flat=True)), [date(2025, 2, 21)])
        self.proy.refresh_from_db()
        self.assertEqual(self.proy.fecha_suscripcion_primer_contrato, date(2025, 2, 21))

    def test_el_principal_va_por_tipo_y_luego_por_valor_y_pasa_al_proyecto(self):
        cargar("contratos", reporte("contratos", [
            self.fila("SUM-1", datetime(2022, 1, 10), tipo="Suministro", valor=900),
            self.fila("OBRA-1", datetime(2022, 3, 1), tipo="Obra pública", valor=50,
                      **{"FECHA INICIAL": datetime(2022, 4, 1), "FECHA ACT ADTIVO APERT": datetime(2021, 11, 5)}),
            self.fila("OBRA-2", datetime(2022, 5, 1), tipo="Obra pública", valor=40)]))
        self.assertEqual(ContratoRegalias.objects.get(es_principal=True).numero, "OBRA-1")
        self.proy.refresh_from_db()
        self.assertEqual((self.proy.tipo_contrato, self.proy.estado_contrato), ("Obra pública", "En ejecución"))
        self.assertEqual((self.proy.fecha_suscripcion_principal, self.proy.fecha_acta_inicio,
                          self.proy.fecha_apertura_primer_proceso),
                         (date(2022, 3, 1), date(2022, 4, 1), date(2021, 11, 5)))
        self.assertEqual(self.proy.fecha_suscripcion_primer_contrato, date(2022, 1, 10))

    def test_los_contratos_del_bpin_que_viene_se_reemplazan_y_los_demas_se_conservan(self):
        otro = proyecto("2020700010140", DESCENTRALIZADA)
        ContratoRegalias.objects.create(proyecto=otro, numero="DESC-1")
        cargar("contratos", reporte("contratos", [self.fila("A-1", datetime(2022, 1, 1))]))
        carga = cargar("contratos", reporte("contratos", [
            self.fila("B-1", datetime(2022, 2, 1)), {"BPIN": "999", "CONTRATO NUMERO": "X"}]))
        self.assertEqual(list(self.proy.contratos.values_list("numero", flat=True)), ["B-1"])
        self.assertEqual(list(otro.contratos.values_list("numero", flat=True)), ["DESC-1"])
        self.assertIn("BPIN que no existen (no se cargaron sus contratos) (1): 999", carga.mensaje)

    def test_repetir_el_mismo_reporte_no_deja_historial_nuevo(self):
        libro = [self.fila("A-1", datetime(2022, 1, 1), valor=123.456789)]
        cargar("contratos", reporte("contratos", libro))
        antes = CambioProyectoRegalias.objects.count()
        cargar("contratos", reporte("contratos", libro))
        self.assertEqual(CambioProyectoRegalias.objects.count(), antes)
        self.assertEqual(self.proy.contratos.count(), 1)

    def test_editar_un_contrato_en_el_admin_actualiza_el_proyecto(self):
        cargar("contratos", reporte("contratos", [self.fila("A-1", datetime(2022, 1, 1))]))
        contrato = self.proy.contratos.get()
        usuario = usuario_de("Regalías", "regalias")
        self.client.force_login(usuario)
        url = reverse("admin:regalias_contratoregalias_change", args=[contrato.pk])
        formulario = self.client.get(url).context["adminform"].form
        datos = {nombre: (formulario.initial.get(nombre) if formulario.initial.get(nombre) is not None else "")
                 for nombre in formulario.fields}
        datos.update(estado="Terminado", fecha_suscripcion="2022-01-01", proyecto=self.proy.pk,
                     ejecuta_varios_proyectos="")
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        self.proy.refresh_from_db()
        self.assertEqual(self.proy.estado_contrato, "Terminado")
        self.assertTrue(self.proy.cambios.filter(campo="Estado del contrato", usuario=usuario).exists())


class CargaDelCargue(Base):
    def test_actualiza_avances_y_aprobacion_de_los_bpin_que_existen(self):
        proy = proyecto("2025000020001", DEPARTAMENTO)
        carga = cargar("cargue", reporte("cargue", [
            {"BPIN": proy.bpin, "AVANCE FISICO": 45.5, "AVANCE FINANCIERO": 100,
             "FECHA APROBACIÓN PROYECTO": datetime(2025, 3, 4)},
            {"BPIN": "999", "AVANCE FISICO": 10}]))
        proy.refresh_from_db()
        self.assertEqual((proy.avance_fisico, proy.avance_financiero, proy.fecha_aprobacion),
                         (Decimal("45.500"), Decimal("100.000"), date(2025, 3, 4)))
        self.assertFalse(ProyectoRegalias.objects.filter(bpin="999").exists())
        self.assertIn("BPIN que no existen (no se actualizaron) (1): 999", carga.mensaje)


COLUMNAS_DEPTO = ["BPIN", "ENTIDAD O SECRETARIA", "NOMBRE PROYECTO", "SECTOR", "INDICADOR DE PRODUCTO MGA",
                  "ESTADO PROYECTO", "FUENTE DE FINANCIACIÓN", "VALOR SGR", "AVANCE FISICO", "CPI",
                  "FECHA DE CORTE GESPROY", "CALIFICACIÓN INFORMACIÓN A TIEMPO", "COMENTARIOS CALIFICACIÓN",
                  "RESPONSABLE CARGUE EN GESPROY", "MUNICIPIOS"]
COLUMNAS_DESC = ["BPIN", "EJECUTOR", "NOMBRE DEL PROYECTO", "ESTADO PROYECTO", "CALIFICACIÓN INFORMACIÓN A TIEMPO",
                 "MUNICIPIOS"]
COLUMNAS_MUN = ["BPIN", "EJECUTOR", "NOMBRE DEL PROYECTO", "ESTADO PROYECTO", "COMENTARIOS", "MUNICIPIOS"]


def libro_de_la_matriz():
    return matriz({
        "MatrizSeguimientoEvaluacion": (COLUMNAS_DEPTO, [{
            "BPIN": "2025000020001", "ENTIDAD O SECRETARIA": "Salud", "NOMBRE PROYECTO": "Hospital",
            "SECTOR": "TRANSPORTE", "INDICADOR DE PRODUCTO MGA": "Hospitales dotados", "ESTADO PROYECTO": EJECUCION,
            "FUENTE DE FINANCIACIÓN": "SGR - Asignación para la inversión regional 60%", "VALOR SGR": 1548027380,
            "AVANCE FISICO": 97.19, "CPI": 0.97, "FECHA DE CORTE GESPROY": datetime(2026, 10, 15),
            "CALIFICACIÓN INFORMACIÓN A TIEMPO": 80, "COMENTARIOS CALIFICACIÓN": "Va bien",
            "RESPONSABLE CARGUE EN GESPROY": "SERGIO VILLALBA MERCADO\nASDRUVAL AVILEZ DÍAZ",
            "MUNICIPIOS": "Sincelejo, Barranquilla"}]),
        "OtrosEjecutoresDescentralizadas": (COLUMNAS_DESC, [{
            "BPIN": "2020700010140", "EJECUTOR": "EMPRESA AGUAS DE SUCRE S.A. E.S.P.",
            "NOMBRE DEL PROYECTO": "Interceptor", "ESTADO PROYECTO": "TERMINADO",
            "CALIFICACIÓN INFORMACIÓN A TIEMPO": 100, "MUNICIPIOS": "Sincelejo"}]),
        "OtrosEjecutoresMunicipios": (COLUMNAS_MUN, [{
            "BPIN": "2012000020042", "EJECUTOR": "MUNICIPIO DE MORROA", "NOMBRE DEL PROYECTO": "Vía Montes de María",
            "ESTADO PROYECTO": "SIN CONTRATAR ", "COMENTARIOS": "", "MUNICIPIOS": "Morroa"}]),
    })


class ImportacionDeLaMatriz(Base):
    def test_crea_las_tres_hojas_con_sus_catalogos(self):
        carga = cargar("matriz", libro_de_la_matriz())
        self.assertEqual(carga.estado, CargaRegalias.Estado.PROCESADO, carga.mensaje)
        depto = ProyectoRegalias.objects.get(bpin="2025000020001")
        self.assertEqual((depto.clasificacion.codigo, depto.dependencia, depto.sector, depto.cpi, depto.fecha_corte),
                         (DEPARTAMENTO, self.salud, self.transporte, Decimal("0.970"), date(2026, 10, 15)))
        self.assertEqual(sorted(r.nombre for r in depto.responsables_cargue.all()),
                         ["ASDRUVAL AVILEZ DÍAZ", "SERGIO VILLALBA MERCADO"])
        self.assertEqual([m.nombre for m in depto.municipios.all()], ["Sincelejo"])
        desc = ProyectoRegalias.objects.get(bpin="2020700010140")
        self.assertEqual((desc.clasificacion.codigo, desc.dependencia), (DESCENTRALIZADA, self.aguas))
        mun = ProyectoRegalias.objects.get(bpin="2012000020042")
        self.assertEqual((mun.clasificacion.codigo, mun.entidad_ejecutora, mun.estado.codigo),
                         (MUNICIPIO, EntidadEjecutora.objects.get(nombre="MUNICIPIO DE MORROA"),
                          EstadoProyectoRegalias.SIN_CONTRATAR))
        self.assertIn("Municipios que no están en el catálogo (1): Barranquilla", carga.mensaje)

    def test_la_informacion_a_tiempo_solo_se_importa_fuera_del_departamento(self):
        cargar("matriz", libro_de_la_matriz())
        self.assertIsNone(ProyectoRegalias.objects.get(bpin="2025000020001").cal_informacion_a_tiempo)
        self.assertEqual(ProyectoRegalias.objects.get(bpin="2020700010140").cal_informacion_a_tiempo, Decimal("100"))

    def test_lo_que_ya_no_se_migra_queda_en_un_comentario(self):
        cargar("matriz", libro_de_la_matriz())
        textos = list(ProyectoRegalias.objects.get(bpin="2025000020001").comentarios.values_list("texto", flat=True))
        anterior = next(t for t in textos if t.startswith("Datos de la matriz anterior"))
        self.assertIn("Fuente: SGR - Asignación para la inversión regional 60%", anterior)
        self.assertIn("Indicador de producto MGA: Hospitales dotados", anterior)
        self.assertIn("Valor SGR: $ 1.548.027.380,00", anterior)
        self.assertIn("Municipios: Sincelejo, Barranquilla", anterior)
        self.assertIn("Va bien", textos)

    def test_repetir_la_importacion_no_duplica_ni_deja_historial(self):
        cargar("matriz", libro_de_la_matriz())
        cambios, comentarios = CambioProyectoRegalias.objects.count(), ProyectoRegalias.objects.get(
            bpin="2025000020001").comentarios.count()
        cargar("matriz", libro_de_la_matriz())
        self.assertEqual(CambioProyectoRegalias.objects.count(), cambios)
        self.assertEqual(ProyectoRegalias.objects.get(bpin="2025000020001").comentarios.count(), comentarios)

    def test_un_error_no_deja_nada_a_medias(self):
        carga = cargar("matriz", matriz({"OtraTabla": (["BPIN"], [{"BPIN": "1"}])}))
        self.assertEqual(carga.estado, CargaRegalias.Estado.ERROR)
        self.assertIn("MatrizSeguimientoEvaluacion", carga.mensaje)
        self.assertFalse(ProyectoRegalias.objects.exists())


class DesdeElAdminYElComando(Base):
    def test_subir_por_el_admin_procesa_y_rechaza_el_mismo_archivo(self):
        usuario = usuario_de("Regalías", "regalias")
        self.client.force_login(usuario)
        contenido = reporte("proyectos", [{"BPIN": "2025000020001", "NOMBRE PROYECTO": "Vía",
                                           "ESTADO PROYECTO": EJECUCION}]).getvalue()
        url = reverse("admin:regalias_cargaregalias_add")
        datos = {"tipo": "proyectos", "fecha_descarga": "2026-11-20"}
        respuesta = self.client.post(url, {**datos, "archivo": SimpleUploadedFile("CG-proy.xlsx", contenido)})
        self.assertEqual(respuesta.status_code, 302)
        carga = CargaRegalias.objects.get()
        self.assertEqual((carga.estado, carga.usuario, carga.nombre_archivo),
                         (CargaRegalias.Estado.PROCESADO, usuario, "CG-proy.xlsx"))
        self.assertTrue(ProyectoRegalias.objects.filter(bpin="2025000020001").exists())
        otra = self.client.post(url, {**datos, "archivo": SimpleUploadedFile("otro.xlsx", contenido)})
        self.assertEqual(otra.status_code, 200)
        self.assertEqual(CargaRegalias.objects.count(), 1)

    def test_el_admin_no_ofrece_ni_acepta_la_matriz(self):
        """La matriz se importa una sola vez con el comando; el sistema solo carga los reportes."""
        self.client.force_login(usuario_de("Regalías", "regalias"))
        url = reverse("admin:regalias_cargaregalias_add")
        opciones = [v for v, _ in self.client.get(url).context["adminform"].form.fields["tipo"].choices]
        self.assertEqual([v for v in opciones if v], ["proyectos", "contratos", "cargue"])
        respuesta = self.client.post(url, {"tipo": "matriz", "fecha_descarga": "2026-11-27",
                                           "archivo": SimpleUploadedFile("matriz.xlsx", libro_de_la_matriz().getvalue())})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("tipo", respuesta.context["adminform"].form.errors)
        self.assertFalse(CargaRegalias.objects.exists())

    def test_el_comando_procesa_un_archivo_local_y_no_repite(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "CG-proy.xlsx"
            ruta.write_bytes(reporte("proyectos", [{"BPIN": "2025000020001", "NOMBRE PROYECTO": "Vía",
                                                    "ESTADO PROYECTO": EJECUCION}]).getvalue())
            call_command("cargar_regalias", "proyectos", str(ruta), "--fecha", "20/11/2026", stdout=StringIO())
            carga = CargaRegalias.objects.get()
            self.assertEqual((carga.estado, carga.fecha_descarga, bool(carga.archivo)),
                             (CargaRegalias.Estado.PROCESADO, date(2026, 11, 20), False))
            with self.assertRaisesMessage(CommandError, "ya está cargado"):
                call_command("cargar_regalias", "proyectos", str(ruta))
