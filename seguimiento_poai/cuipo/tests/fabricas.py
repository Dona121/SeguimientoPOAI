"""Fabricas de las pruebas del CUIPO: reportes de ejecucion y libros de listas en memoria, las
listas CHIP minimas, cortes, formulaciones PIIP y el escenario del plano.

Reunidas en la fase 7; antes estaban repartidas en los archivos de prueba.
"""
import hashlib
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from itertools import count

from django.core.files.base import ContentFile
from openpyxl import Workbook

from cuipo import distribucion, ejecucion
from cuipo.models import (CPC, ConceptoCUIPO, CorteEjecucionGastos, DetalleSectorial, FuenteCUIPO, HomologacionFuente,
                          HomologacionRubro, PoliticaPublica, ProductoCUIPO, ReglaTercero, SeccionPresupuestal,
                          SituacionFondos, TerceroCUIPO, VersionListas, VigenciaGasto)
from cuipo.models import DistribucionBPIN
from siifweb.models import (CentroCosto, FormulacionProyecto, Fuente, IndicadorCatalogo, IndicadorProyecto,
                            ProductoCatalogo, Rubro)

D = Decimal


COLUMNAS = ["RUBRO_ID", "RUBRO", "NOMBRE_RUBRO", "RECURSO", "NOMBRE_RECURSO", "CENTROCOSTO",
            "NOMBRE_CENTROCOSTO", "PROYECTO", "APROPIACION_INICIAL", "ADICION", "DISMINUCION", "CREDITO",
            "CONTRACREDITO", "APLAZAMIENTOS", "DESAPLAZAMIENTOS", "APROPIACION_DEFINITIVA",
            "SOLICITUD_TRAMITE", "CDP", "RP", "OBLIGACION", "PAGO", "DISPONIBLE"]


def fila(rubro_id, rubro, rp, recurso=None, centro=None, proyecto=None, obligacion=None, pago=None, **otros):
    """Una fila del reporte. Sin recurso es un subtotal."""
    obligacion = rp if obligacion is None else obligacion
    pago = obligacion if pago is None else pago
    valores = {"APROPIACION_INICIAL": rp, "ADICION": 0, "DISMINUCION": 0, "CREDITO": 0, "CONTRACREDITO": 0,
               "APLAZAMIENTOS": 0, "DESAPLAZAMIENTOS": 0, "APROPIACION_DEFINITIVA": rp, "SOLICITUD_TRAMITE": rp,
               "CDP": rp, "RP": rp, "OBLIGACION": obligacion, "PAGO": pago, "DISPONIBLE": "0"}
    valores.update(otros)
    return {"RUBRO_ID": rubro_id, "RUBRO": rubro, "NOMBRE_RUBRO": f"Rubro {rubro}",
            "RECURSO": recurso, "NOMBRE_RECURSO": f"Recurso {recurso}" if recurso else None,
            "CENTROCOSTO": centro, "NOMBRE_CENTROCOSTO": f"Centro {centro}" if centro else None,
            "PROYECTO": proyecto if recurso else None, **valores}


def reporte_basico():
    """2 > 2.3 > 2.3.2.02.02.009 con dos filas de detalle (un proyecto y funcionamiento)."""
    return [
        fila(100, "2", 1500),
        fila(101, "2.3", 1500),
        fila(102, "2.3.2.02.02.009", 1500),
        fila(102, "2.3.2.02.02.009", 1000, "3", "2", "202500000039332"),
        fila(102, "2.3.2.02.02.009", 500, "7", "16", "0"),
    ]


def libro_ejecucion(filas):
    wb = Workbook()
    hoja = wb.active
    hoja.title = "Hoja1"
    hoja.append(COLUMNAS)
    for f in filas:
        hoja.append([f[c] for c in COLUMNAS])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def cortar(filas, vigencia=2026, fecha_fin=date(2026, 9, 30)):
    datos = libro_ejecucion(filas)
    corte = CorteEjecucionGastos(vigencia=vigencia, fecha_inicio=date(vigencia, 1, 1), fecha_fin=fecha_fin,
                                 hash=hashlib.sha256(datos).hexdigest())
    corte.archivo.save("ejecucion.xlsx", ContentFile(datos), save=True)
    ejecucion.procesar(corte)
    corte.refresh_from_db()
    return corte


def hojas_minimas():
    """Las once hojas con pocas filas, con los tipos que trae el archivo real."""
    return {
        "Conceptos por ambito": [
            ["Nivel", "CODIGO", "NOMBRE", "438 - DEPARTAMENTOS", "439 - MUNICIPIOS", "Notas"],
            ["S", "2.3", "INVERSION", 1, 1, None],
            ["D", "2.3.2.02.02.009", "SERVICIOS PARA LA COMUNIDAD", 1, 1, None],
            ["D", "2.3.3.05.09.054", "A ESTABLECIMIENTOS PUBLICOS", 0, 1, "Solo municipios"],
            ["D", "2.3.3.05.09.099", "APORTES A ESTABLECIMIENTOS PUBLICOS", 1, 1, None],
            [None, None, None, None, None, None],
        ],
        "Conceptos_CPC": [["Código", "Nombre", "Descripción"], ["2.3.2.02.02.009", "Servicios", "Servicios"],
                          [None, None, None]],
        "CPC": [["Código", "Clase o Subclase", "Sección", "División"],
                ["0", "No aplica", "NO APLICA", "NO APLICA"],
                ["01111", "Trigo semilla", "AGRICULTURA", "PRODUCTOS DE LA AGRICULTURA"],
                [1101001, "Antracita", "MINERALES", "CARBON"],     # numero en Excel, 7 digitos
                [21111, "Carne de bovino", "PRODUCTOS ALIMENTICIOS", "CARNE"]],
        "Fuentes de Financiación": [["Código", "Descripción"], ["1.2.1.0.00", "ICLD"], ["1.3.3.3.20", "R.B. ESTAMPILLAS"]],
        "Tercero": [["Código", "Entidad"], ["0", "OTRO"], ["220170001", "Fondo Mixto"]],
        "Politica Pública": [["Código", "Descripción"], [0, "NO APLICA"], [8182, "PDET"]],
        "Secciones Presupuestales": [["Código", "Descripción", None, "Nota suelta"],
                                     ["16.0", "ADMINISTRACION CENTRAL", None, "no es una columna"],
                                     ["21.0", "SALUD", None, None]],
        "Vigencia Gasto": [["Código", "Descripción", None], [1, "VIGENCIA ACTUAL", None], [2, "RESERVAS", None]],
        "Producto MGA": [["Codigo", "Descripción", "Sector", "Programa", "Aplica a Entidades Territoriales"],
                         ["0101004", "Servicios de difusion", "CONGRESO", "Eficiencia legislativa", None],
                         ["3301053", "Servicio de apoyo", "CULTURA", "Promocion cultural", None],
                         ["3201051", "Producto nuevo", "AMBIENTE", "Programa", "Nuevo"]],
        "Situación de Fondos": [["Código", "Descripción"], ["C", "CON SITUACION DE FONDOS"],
                                ["S", "SIN SITUACION DE FONDOS"]],
        "Detalle Sectorial": [["Código", "Concepto", "Grupo concepto", "Sector", None],
                              [0, "NO APLICA", "NO APLICA", "NO APLICA", None],
                              ["19.01.17", "RS - TRANSFERENCIAS", "RÉGIMEN SUBSIDIADO", "SALUD", None]],
    }


def libro_listas(**cambios):
    """Libro de listas en memoria. cambios: {nombre de hoja (con _ por espacio): filas o None}."""
    hojas = hojas_minimas()
    for clave, filas in cambios.items():
        nombre = next(h for h in hojas if h.replace(" ", "_") == clave or h == clave)
        if filas is None:
            del hojas[nombre]
        else:
            hojas[nombre] = filas
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        hoja = wb.create_sheet(nombre)
        for fila in filas:
            hoja.append(fila)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def listas():
    """Lo minimo de las listas CHIP y de los catalogos de SIIFWEB para derivar."""
    v = VersionListas.objects.create(nombre="09-2026")
    for codigo, habilitado in (("2.3.2.02.02.009", True), ("2.3.3.05.09.054", False), ("2.3.3.05.09.099", True),
                               ("2.3.1.01.02.001", True), ("2.3.1.01.02.006", True),
                               ("2.3.2.01.01.001.02.08", True)):
        ConceptoCUIPO.objects.create(codigo=codigo, descripcion=f"Concepto {codigo}", nivel="D",
                                     habilitado_departamentos=habilitado, version=v)
    for codigo in ("1.2.1.0.00", "1.2.4.1.01", "1.3.3.3.20", "1.2.3.3.03"):
        FuenteCUIPO.objects.create(codigo=codigo, descripcion=f"Fuente {codigo}", version=v)
    for codigo in ("16.0", "21.0", "22.0"):
        SeccionPresupuestal.objects.create(codigo=codigo, descripcion=f"Sección {codigo}", version=v)
    for codigo in ("C", "S"):
        SituacionFondos.objects.create(codigo=codigo, descripcion=f"Situación {codigo}", version=v)
    for codigo in ("1", "220170001", "23900000", "128470000"):
        TerceroCUIPO.objects.create(codigo=codigo, descripcion=f"Tercero {codigo}", version=v)
    for codigo in ("1", "3", "7", "108", "114"):
        Fuente.objects.create(codigo=codigo, nombre=f"Recurso {codigo}")
    for codigo in ("2.3.2.02.02.009", "2.3.3.05.09.054", "2.3.1.01.02.001", "2.3.1.01.02.006",
                   "2.3.2.01.01.001.02.08"):
        Rubro.objects.create(codigo=codigo, nombre=f"Rubro {codigo}")
    for codigo in ("2", "3", "10", "11", "16"):
        CentroCosto.objects.create(codigo=codigo, nombre=f"Centro {codigo}")
    return v


_dias = count()


def corte_con(detalle, vigencia=2026, fecha_fin=None):
    """Un corte cuyo unico subtotal es la raiz 2: cuadra con cualquier detalle. Cada corte de
    una prueba termina un dia antes que el anterior, para no repetir el rango."""
    columnas = ["APROPIACION_INICIAL", "ADICION", "DISMINUCION", "CREDITO", "CONTRACREDITO", "APLAZAMIENTOS",
                "DESAPLAZAMIENTOS", "APROPIACION_DEFINITIVA", "SOLICITUD_TRAMITE", "CDP", "RP", "OBLIGACION", "PAGO"]
    raiz = fila(100, "2", 0, **{c: sum(f[c] for f in detalle) for c in columnas})
    fin = fecha_fin or date(vigencia, 9, 30) - timedelta(days=next(_dias) % 200)
    corte = cortar([raiz, *detalle], vigencia=vigencia, fecha_fin=fin)
    assert corte.estado == corte.Estado.PROCESADO, corte.mensaje
    return corte


def homologar(recurso, fuente, vigencia=2026):
    return HomologacionFuente.objects.create(fuente_siifweb=Fuente.objects.get(codigo=recurso),
                                             fuente_cuipo=FuenteCUIPO.objects.get(codigo=fuente), vigencia=vigencia)


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


ENCABEZADO = "S\t117070000\t10909\t2026\tD_EJECUCION_DE_GASTOS"


def preparar_plano():
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
