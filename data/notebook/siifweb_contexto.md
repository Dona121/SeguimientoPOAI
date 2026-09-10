# SIIFWEB - analisis de origen

Extracto del notebook de trabajo `Plataformas_PIIP.ipynb`, recortado a la seccion de
SIIFWEB para usarlo como contexto. Es el analisis en polars con el que se determino,
antes de existir la aplicacion Django:

- que reportes de la plataforma servian y cuales se descartaban;
- cual es el grano minimo de la informacion (la imputacion: documento x rubro x fuente
  x proyecto) y por que la vigencia entra en toda llave;
- con que llaves cruza cada reporte con el siguiente a lo largo de la cadena del gasto;
- el reporte consolidado por (proyecto, vigencia), que es el antecesor directo del
  Reporte Financiero de la aplicacion.

Las rutas apuntan a la carpeta local de descargas de SIIFWEB y las salidas se limpiaron:
el notebook esta aqui para leerse, no para volver a ejecutarse.

```python
import polars as pl
import os
from datetime import date, datetime
#from itables import init_notebook_mode
#from itables import show
#init_notebook_mode(all_interactive=True)
#from itables import options
#options.columnDefs = [{"width": "120px", "targets": "_all"}]
```

## SIIFWEB

```python
"""RUTAS"""

dfs = {
    "cdps" : {
        "2022":"SIIFWEB/Informes/Consolidado disponibilidades/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_cert_dispw_2022_1Enero_31Diciembre.xlsx",
        "2023":"SIIFWEB/Informes/Consolidado disponibilidades/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_cert_dispw_2023_1Enero_31Diciembre.xlsx",
        "2024":"SIIFWEB/Informes/Consolidado disponibilidades/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_cert_dispw_2024_1Enero_31Diciembre.xlsx",
        "2025":"SIIFWEB/Informes/Consolidado disponibilidades/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_cert_dispw_2025_1Enero_31Diciembre.xlsx",
        "2026":"SIIFWEB/Informes/Consolidado disponibilidades/20260729/consolidado_cert_dispw_20260729.xlsx"
    },
    "compromisos" : {
        "2022":"SIIFWEB/Informes/Consolidado compromisos/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_compromisosw_2022_202607181700.xlsx",
        "2023":"SIIFWEB/Informes/Consolidado compromisos/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_compromisosw_2023_202607181700.xlsx",
        "2024":"SIIFWEB/Informes/Consolidado compromisos/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_compromisosw_2024_202607181700.xlsx",
        "2025":"SIIFWEB/Informes/Consolidado compromisos/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_compromisosw_2025_202607181700.xlsx",
        "2026":"SIIFWEB/Informes/Consolidado compromisos/20260729/consolidado_compromisosw_20260729.xlsx",
    },
    "obligaciones" : {
        "2022":"SIIFWEB/Informes/Consolidado obligaciones/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_obligacionw_2022_20260730.xlsx",
        "2023":"SIIFWEB/Informes/Consolidado obligaciones/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_obligacionw_2023_20260730.xlsx",
        "2024":"SIIFWEB/Informes/Consolidado obligaciones/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_obligacionw_2024_20260730.xlsx",
        "2025":"SIIFWEB/Informes/Consolidado obligaciones/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_obligacionw_2025_20260730.xlsx",
        "2026":"SIIFWEB/Informes/Consolidado obligaciones/20260729/consolidado_obligacionw_20260729.xlsx",
    },
    "reservas" : {
        "2024":"SIIFWEB/Informes/Consolidado reservas/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_reservaw_2024_20260730.xlsx",
        "2025":"SIIFWEB/Informes/Consolidado reservas/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_reservaw_2025_20260730.xlsx",
        "2026":"SIIFWEB/Informes/Consolidado reservas/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/consolidado_reservaw_2026_corte30Julio_20260730.xlsx",
    },
    "comprobantes" : {
        "2022":"SIIFWEB/Informes/Comprobante por centro de costo/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/aux_comprobantes32w_2022_20260730.xlsx",
        "2023":"SIIFWEB/Informes/Comprobante por centro de costo/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/aux_comprobantes32w_2023_20260730.xlsx",
        "2024":"SIIFWEB/Informes/Comprobante por centro de costo/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/aux_comprobantes32w_2024_20260730.xlsx",
        "2025":"SIIFWEB/Informes/Comprobante por centro de costo/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/aux_comprobantes32w_2025_20260730.xlsx",
        "2026":"SIIFWEB/Informes/Comprobante por centro de costo/SinFormatearEnExcel (Tal como se descarga desde SIIFWEB)/aux_comprobantes32w_2026_corte30Julio_20260730.xlsx",
    },
    "historico_gasto":{
        "2017_2026":"SIIFWEB/Informes/Historial de orden de gasto 2/20260729/historial_ordengasto2_20260729.xlsx"
    }
}
```

### Funciones

```python
def procesar_float(df, *columna_valor) -> pl.Expr:
    return (
        df.with_columns(
            pl.col(col).str.replace_many({",":"."}).cast(pl.Float64).alias(col)
            for col in columna_valor
        )
    )

def procesar_date(df, *columna_fecha) -> pl.Expr:
    return(
        df.with_columns(
            pl.when( pl.col(col).str.len_chars() == 8 )
            .then( pl.col(col).str.strptime(pl.Date,"%d/%m/%y",strict=False) )
            .when( pl.col(col).str.len_chars() == 10 )
            .then( pl.col(col).str.strptime(pl.Date,"%d/%m/%Y",strict=False) )
            .otherwise(pl.lit(None,dtype=pl.Date))
            .alias(col)
            for col in columna_fecha
        )
    )

def procesar_int(df, columnas_numericas_int) -> pl.Expr:
    lectura_vigencia = df.with_columns(
        pl.col(columnas_numericas_int).cast(pl.Int32),
    )
    return lectura_vigencia
```

#### CDPs

```python
lista_consolidado_cdps = []

columnas_numericas_cdp = [
    "VALOR_CERTIFICADO",
    "VALOR_DISPONIBILIDAD_DEF",
    "VALOR_COMPROMISOS",
    "SALDO_CERTF",
    "OBLIGACIONES",
    "PAGOS"
]

columnas_fecha_cdp = ["FECHA_DISP",]

columnas_cdp = [
    "NRO_CDP",
    "VIGENCIA",
    "VALOR_CERTIFICADO",
    "VALOR_DISPONIBILIDAD_DEF",
    "VALOR_COMPROMISOS",
    "SALDO_CERTF",
    "OBLIGACIONES",
    "PAGOS"
]

for key, value in dfs.items():
    if key == "cdps":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = lectura_vigencia.with_columns(pl.lit(int(vigencia)).alias("VIGENCIA"))
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_cdp)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fecha_cdp)
            lista_consolidado_cdps.append(lectura_vigencia)

"""
1. Un mismo CDP puede provenir de diferentes rubros
2. Un CDP puede tener varios proyectos
3. Varios proyectos pueden tomar de un mismo CDP y un proyecto puede tomar de varios CDP
4. Voy a encontrar CDPs duplicados pero porque diferentes proyectos toman de ese CDP en diferentes fechas
5. .with_columns(pl.col("FECHA_DISP").min().over("NRO_CDP").alias("PRIMERA_FECHA_DISP")) no puedo hacer esto porque el numero del cdp se
   genera desde 1 en cada vigencia. Agrupar un CDP agruparia el mismo para diferentes vigencias
"""

cdps_por_proyecto = (
    # Cdps generados proyecto
    pl.concat(lista_consolidado_cdps)
    .filter(pl.col("PROYECTO")!="0")
    .sort(by=["NRO_CDP","VIGENCIA"],descending=False)
)

consolidado_cdps_por_vigencia = (
    # Ver los valores totales de los CDP generados en una vigencia
    pl.concat(lista_consolidado_cdps)
    .select(columnas_cdp)
    .group_by("NRO_CDP","VIGENCIA").agg(pl.col(columnas_numericas_cdp).sum())
)

cdps_por_proyecto = (
    cdps_por_proyecto
    .sort(by=[pl.col("NRO_CDP").cast(pl.Int32),"VIGENCIA"],descending=False)
    .group_by("PROYECTO","VIGENCIA").agg(
        pl.col("FECHA_DISP").min().alias("FechaPrimerCDP"),
        pl.col("VALOR_CERTIFICADO").sum().alias("ValorCertificado"),
        pl.col("VALOR_DISPONIBILIDAD_DEF").sum().alias("ValorDisponibilidadDefinitiva")
    )
)
```

```python
"""
A continuación presento una serie de calculos que confirman mi siguiente analisis de la base de datos de siifweb
1. Un CDP puede amparar varios proyectos de inversión.
2. Un proyecto puede ejecutarse con cargo a varios CDPs: la financiación de un proyecto puede estar respaldada por múltiples 
   certificados de disponibilidad, expedidos a lo largo de la vigencia
3. Un CDP puede afectar varios rubros presupuestales
4. La apropiación de un rubro puede ser afectada sucesivamente por múltiples CDPs, hasta agotar su saldo de apropiación disponible

El CDP es el instrumento mediante el cual se afecta preliminarmente la apropiación presupuestal. En su expedición, 
un mismo certificado puede amparar uno o varios proyectos de inversión y afectar uno o varios rubros y fuentes de financiación; 
a su vez, un proyecto puede ejecutarse con cargo a múltiples CDPs y la apropiación de un rubro puede ser afectada por sucesivos certificados. En consecuencia, la relación entre proyectos, certificados de disponibilidad y rubros presupuestales es de muchos a muchos, y el nivel mínimo de desagregación de la información es la imputación presupuestal: la combinación CDP–rubro–fuente

La apropiación se establece a nivel de rubro presupuestal. El CDP es el instrumento mediante el cual se afecta preliminarmente 
esa apropiación, garantizando la existencia de recursos para asumir un compromiso. Un mismo CDP puede amparar varios proyectos 
y afectar varios rubros y fuentes de financiación; a su vez, un proyecto puede ejecutarse con cargo a múltiples CDPs, sea 
porque concurre más de una fuente de financiación —cada una con su propia disponibilidad— o porque el proyecto se ejecuta 
mediante compromisos sucesivos a lo largo de la vigencia.

"""

comprobacion_cdp_proyectos = (
    # Con esto confirmo que un CDP puede contener varios proyectos.
    pl.concat(lista_consolidado_cdps).group_by("NRO_CDP","VIGENCIA")
    .agg(pl.col("PROYECTO").unique()).with_columns(pl.col("PROYECTO").list.len().alias("NUMERO PROYECTOS"))
    .sort(by="NUMERO PROYECTOS",descending=True)
)

comprobacion_proyectos_cdp = (
    # Con esto confirmo que un proyecto puede tomar de varios CDPs
    pl.concat(lista_consolidado_cdps).filter(pl.col("PROYECTO")!="0").group_by("PROYECTO","VIGENCIA")
    .agg(pl.col("NRO_CDP").unique()).with_columns(pl.col("NRO_CDP").list.len().alias("NUMERO CDP"))
    .sort(by="NUMERO CDP",descending=True)
)

comprobacion_cdp_rubro = (
    # Con esto confirmo que un cdp puede contener varios rubros
    pl.concat(lista_consolidado_cdps).group_by("NRO_CDP","VIGENCIA")
    .agg(pl.col("NOMBRE_RUBRO").unique()).with_columns(pl.col("NOMBRE_RUBRO").list.len().alias("NUMERO RUBROS"))
    .sort(by="NUMERO RUBROS",descending=True)
)

comprobacion_rubro_cdp = (
    # Con esto confirmo que un rubro puede contener varios cdps
    pl.concat(lista_consolidado_cdps).group_by("NOMBRE_RUBRO","VIGENCIA")
    .agg(pl.col("NRO_CDP").unique()).with_columns(pl.col("NRO_CDP").list.len().alias("NUMERO CDP"))
    .sort(by="NUMERO CDP",descending=True)
)

comprobacion_rubro_fuente = (
    # Con esto confirmo que un rubro puede contener varias fuentes
    pl.concat(lista_consolidado_cdps).group_by("NOMBRE_RUBRO","VIGENCIA")
    .agg(pl.col("FONDO").unique()).with_columns(pl.col("FONDO").list.len().alias("FONDOS"))
    .sort(by="FONDOS",descending=True)
)

comprobacion_fuente_rubro = (
    # Con esto confirmo que una fuente puede pertenecer a diferentes rubros
    pl.concat(lista_consolidado_cdps).group_by("NOMBRE_FONDO","VIGENCIA")
    .agg(pl.col("NOMBRE_RUBRO").unique()).with_columns(pl.col("NOMBRE_RUBRO").list.len().alias("RUBROS"))
    .sort(by="RUBROS",descending=True)
)

comprobacion_cdp_fecha = (
    # Con esto confirmo que un cdp contiene una fecha unico de expedición
    pl.concat(lista_consolidado_cdps).group_by("NRO_CDP","VIGENCIA")
    .agg(pl.col("FECHA_DISP").unique()).with_columns(pl.col("FECHA_DISP").list.len().alias("FECHAS"))
    .sort(by="FECHAS",descending=True).filter(pl.col("FECHAS")>1)
)
```

#### Compromisos

```python
lista_consolidado_compromisos = []

columnas_fechas_compromisos = ['FECHA_REG',]

columnas_numericas_compromisos = ['VALOR_REGISTRO','VALOR_COMPROMISO_DEF','SALDO_RP','OBLIGACIONES','PAGOS']

for key, value in dfs.items():
    if key == "compromisos":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = lectura_vigencia.with_columns(pl.lit(int(vigencia)).alias("VIGENCIA"))
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_compromisos)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fechas_compromisos)
            lista_consolidado_compromisos.append(lectura_vigencia)

consolidado_compromisos = (
    pl.concat(lista_consolidado_compromisos)
    .filter(pl.col("PROYECTO")!="0")
)

conteo_rp_proyecto = (
    consolidado_compromisos
    .group_by("NRO_RP").agg(pl.col("PROYECTO").unique())
    .with_columns(pl.col("PROYECTO").list.len())
    .sort(by=["PROYECTO"],descending=True)
    .row(0)
)

print(f"""
De acuerdo con la tabla de compromisos un rp puede contener varios proyectos. 
Veamos: el rp {conteo_rp_proyecto[0]} cuenta con {conteo_rp_proyecto[1]} proyectos""")


rps_por_proyecto = (
    consolidado_compromisos
    .group_by("PROYECTO","VIGENCIA").agg(
        pl.col("FECHA_REG").min().alias("FechaPrimerRP"),
        pl.col("VALOR_REGISTRO").sum().alias("ValorRegistro"),
        pl.col("VALOR_COMPROMISO_DEF").sum().alias("ValorCompromisoDefinitivo")
    )
)
```

#### Obligaciones

```python
lista_consolidado_obligaciones = []

columnas_fechas_obligaciones = ["FECHA_OBLI",]

columnas_numericas_obligaciones = ["VALOR_OBLIGACION","VALOR_OBLI_DEF","SALDO_OBLI","PAGOS"]

for key, value in dfs.items():
    if key == "obligaciones":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = lectura_vigencia.with_columns(pl.lit(int(vigencia)).alias("VIGENCIA"))
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_obligaciones)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fechas_obligaciones)
            lista_consolidado_obligaciones.append(lectura_vigencia)

consolidado_obligaciones = (
    pl.concat(lista_consolidado_obligaciones)
    .filter(pl.col("PROYECTO")!="0")
)


obligacion_por_proyecto = (
    consolidado_obligaciones
    .group_by("PROYECTO","VIGENCIA").agg(
        pl.col("TIPO_ORDEN_GASTO").unique().str.join(", "),
        pl.col("FECHA_OBLI").min().alias("FechaPrimeraObligacion"),
        pl.col("VALOR_OBLIGACION").sum().alias("ValorObligacion"),
        pl.col("VALOR_OBLI_DEF").sum().alias("ValorObligacionDefinitiva"),
        pl.col("SALDO_OBLI").sum().alias("ValorSaldoObligacion"),
        pl.col("PAGOS").sum().alias("ValorPagos")
    )
)
```

#### Reservas

```python
lista_consolidado_reservas = []

columnas_fechas_reservas = ["FECHA_RESERVA","FECHA_CDP"]

columnas_numericas_reservas = ["VALOR_RESERVA","VALOR_RESERVA_DEF","SALDO_RESERVA","OBLIGACIONES_RESERVA","PAGOS_RESERVA"]

for key, value in dfs.items():
    if key == "reservas":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = lectura_vigencia.with_columns(pl.lit(int(vigencia)).alias("VIGENCIA"))
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_reservas)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fechas_reservas)
            lista_consolidado_reservas.append(lectura_vigencia)

consolidado_reservas = (
    pl.concat(lista_consolidado_reservas)
    .filter(pl.col("PROYECTO")!="0")
)

reservas_por_proyecto = (
    consolidado_reservas
    .group_by("PROYECTO","VIGENCIA").agg(
        pl.col("FECHA_RESERVA").min().alias("FechaReserva"),
        pl.col("VALOR_RESERVA").sum().alias("ValorReserva"),
        pl.col("VALOR_RESERVA_DEF").sum().alias("ValorReservaDefinitiva"),
        pl.col("OBLIGACIONES_RESERVA").sum().alias("ObligacionesReservasDefinitivas"),
        pl.col("SALDO_RESERVA").sum().alias("ValorSaldoReservas"),
        pl.col("PAGOS_RESERVA").sum().alias("ValorPagoReservas")
    )
)
```

#### Comprobantes

```python
lista_consolidado_comprobantes = []

columnas_fechas_comprobantes = ["FECHA"]

columnas_numericas_comprobantes = ["VALOR"]

for key, value in dfs.items():
    if key == "comprobantes":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = lectura_vigencia.with_columns(pl.lit(int(vigencia)).alias("VIGENCIA"))
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_comprobantes)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fechas_comprobantes)
            lista_consolidado_comprobantes.append(lectura_vigencia)

consolidado_comprobantes = (
    pl.concat(lista_consolidado_comprobantes)
    .filter(pl.col("PROYECTO")!="0",pl.col("TIPO_COMPPTAL")=="CONTRACREDITO")
)

contracredito_por_proyecto = (
    consolidado_comprobantes
    .group_by("PROYECTO","VIGENCIA").agg(
        pl.col("FECHA").min().alias("FechaPrimerContracredito"),
        pl.col("VALOR").sum().alias("ValorContraceditos")
    ).join(cdps_por_proyecto.filter(pl.col("ValorDisponibilidadDefinitiva")==0),on=["PROYECTO","VIGENCIA"],validate="1:1")
    .drop("FechaPrimerCDP","ValorCertificado","ValorDisponibilidadDefinitiva")
) # Tener presente que un proyecto puede tener varios contracreditos
```

#### Historico de gasto

```python
lista_historico_ordenes_gasto = []

columnas_entero_historico_orden_gasto = ["PREFIJO"]

columnas_numericas_historico_orden_gasto = ["VALOR_CONTRATO","VALOR_PAGO"]

columnas_fechas_historico_orden_gasto = ["FECHA_FIRMA","FECHA_FINAL1","FECHA_INICIO","FECHA_PAGO"]

for key, value in dfs.items():
    if key == "historico_gasto":
        for vigencia, ruta in value.items():
            lectura_vigencia = pl.read_excel(ruta,infer_schema_length=0)
            lectura_vigencia = procesar_float(lectura_vigencia,*columnas_numericas_historico_orden_gasto)
            lectura_vigencia = procesar_date(lectura_vigencia,*columnas_fechas_historico_orden_gasto)
            lectura_vigencia = procesar_int(lectura_vigencia,*columnas_entero_historico_orden_gasto)
            lista_historico_ordenes_gasto.append(lectura_vigencia)

historico_ordenes_gasto_contratos = (
    pl.concat(lista_historico_ordenes_gasto)
    .filter(pl.col("PROYECTO")!="0")
)

contratos_por_proyecto = (
    historico_ordenes_gasto_contratos
    .group_by("PROYECTO","PREFIJO").agg(
        pl.col("FECHA_FIRMA").min().alias("FechaFirmaPrimerContrato"),
        pl.col("TIPO_CONTRATO").len().alias("NumeroContratos"),
        pl.col("VALOR_CONTRATO").sum().alias("ValorContratos")
    ).rename({"PREFIJO":"VIGENCIA"})
)
```

### Comprobaciones

```python
reportes_sutec = [
    cdps_por_proyecto,
    consolidado_compromisos,
    consolidado_obligaciones,
    consolidado_ordenes_gasto,
    consolidado_reservas,
    consolidado_comprobantes,
    historico_ordenes_gasto_contratos
]

# -------------------------------------------------- CDP - COMPROMISOS -------------------------------------------------------------------

"""
El nivel de granularidad se refiere al grado de detalle o la profundidad con la que se registran, analizan o presentan los datos. 
A mayor detalle, mayor es la granularidad (o "grano fino"), y a menor detalle (datos agrupados o resumidos), menor es la granularidad 
(o "grano grueso")
"""

disponibilidades = (
    cdps_por_proyecto.group_by("VIGENCIA","NRO_CDP").agg(
        pl.col("VALOR_DISPONIBILIDAD_DEF").sum(),
        # La fecha de expedición es única por (VIGENCIA, NRO_CDP) — verificado en 2022-2026, cero excepciones — así que .first() es seguro
        pl.col("FECHA_DISP").first()
    )
)

compromisos_segun_cdp = (
    # Agrupo a nivel de proyecto para tener un nivel de granularidad de compromisos a nivel de proyecto, no de cdo
    # por que se usan todas estas llaves? Vayamos desglozando por llave: 
    # 1. VIGENCIA: Teniendo en cuenta que el CDP se reinicia desde 1 cada vigencia
    # 2. IDENTIFICACION_PRESUPUESTAL: Un CDP puede afectar varios rubros presupuestales
    # 3. FONDO: Un CDP puede afectar varias fuentes de financiación
    # 4. NRO_CDP: identifica el documento dentro de la vigencia
    # 5. PROYECTO: un CDP puede amparar varios proyectos; sin esta llave, sus porciones se suman como si fueran una sola
    # estas cinco columnas definen el grano imputación × proyecto; con menos llaves se mezclan valores de grupos distintos
    cdps_por_proyecto.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRO_CDP","PROYECTO").agg(
        pl.col("VALOR_COMPROMISOS").sum()
    )
)

compromisos_por_proyecto = (
    consolidado_compromisos.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRODOC_CDP","PROYECTO").agg(
        pl.col("VALOR_COMPROMISO_DEF").sum()
    )
)

comprobacion_disponibilidad_compromiso = (
    # Conciliación: VALOR_COMPROMISOS en disponibilidades es un acumulado arrastrado desde compromisos. 
    # Si las llaves y el grano están bien, el cruce debe dar diferencia cero en toda fila. Verificado: cuadra al peso en las 5 vigencias
    compromisos_segun_cdp
    .join(
        compromisos_por_proyecto,
        left_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRO_CDP","PROYECTO"],
        right_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRODOC_CDP","PROYECTO"],
        how="full",
        coalesce=True
    )
    .with_columns((pl.col("VALOR_COMPROMISOS").fill_null(0)-pl.col("VALOR_COMPROMISO_DEF").fill_null(0)).alias("COMP"))
    .filter(pl.col("COMP").abs()>=1)
)


# -------------------------------------------------- COMPROMISOS - OBLIGACIONES -------------------------------------------------------------------

obligaciones_segun_rp = (
    consolidado_compromisos.group_by("VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO").agg(
        pl.col("OBLIGACIONES").sum(),
        pl.col("FECHA_REG").first()
    )
)

obligaciones_por_vigencia = (
    consolidado_obligaciones.group_by("VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO").agg(
        pl.col("VALOR_OBLI_DEF").sum()
    )
)

comprobacion_obligacion = (
    # Conciliación: OBLIGACIONES en compromisos es un acumulado arrastrado desde obligaciones. 
    # Si las llaves y el grano están bien, el cruce debe dar diferencia cero en toda fila. Verificado: cuadra al peso en las 5 vigencias,
    # salvo 2023, donde el consolidado de obligaciones incluye 35 obligaciones de reservas (RPs de 2022) por $7.613 millones
    obligaciones_segun_rp.join(
        obligaciones_por_vigencia,
        left_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        how="full",
        coalesce=True
    ).with_columns((pl.col("OBLIGACIONES").fill_null(0)-pl.col("VALOR_OBLI_DEF").fill_null(0)).alias("OBLI"))
    .filter(pl.col("OBLI").abs()>=1)
)

comprobacion_reserva = (
    # Este codigo me da las obligaciones que se causaron con cargo a reservas — es decir, la ejecución de las reservas, no su constitución. 
    # Cada fila huérfana confirmada contra v−1 es "esta cuenta se recibió y causó en la vigencia v, contra un compromiso que quedó 
    # reservado del año v−1". Para 2023, eso reconstruye la ejecución de reservas que el sistema no reportó por ningún otro lado: es tu único 
    # registro de ese flujo.
    obligaciones_por_vigencia.join(
        obligaciones_segun_rp,
        left_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        how="anti",
    ).join(
        obligaciones_segun_rp,
        left_on=[pl.col("VIGENCIA")-1,"NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        how="left",
        suffix="_rp_anterior"
    ).with_columns(
        pl.col("OBLIGACIONES").is_null().alias("anomalia"),
        (pl.col("PROYECTO") != pl.col("PROYECTO_rp_anterior")).alias("proyecto_difiere"),
    ).join(
        compromisos_segun_cdp.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO").agg(pl.col("NRO_CDP").unique().alias("CDPs_d")),
        left_on=[pl.col("VIGENCIA")-1,"IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        how="left",
        suffix="_cdp"
    ).join(
        consolidado_reservas.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO").agg(pl.col("NUMERO_CDP").unique().alias("CDPs_r")),
        left_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        how="left"
    ).with_columns(pl.col("CDPs_d").list.set_intersection(pl.col("CDPs_r")).alias("CDPs_r_d"))
    .with_columns(pl.when(pl.col("CDPs_r_d").list.len()>0).then(pl.lit(True)).otherwise(pl.lit(False)).alias("coincidencia_cdps"))
    # Tiene sentido que todo sea False porque no hay reporte de reserva para 2023
)


# -------------------------------------------------- OBLIGACIONES - ORDENES DE GASTO-------------------------------------------------------------------


obligaciones_segun_orden_gasto = (
    consolidado_obligaciones.group_by("VIGENCIA","NRO_ORDEN_GASTO").agg(
        pl.col("VALOR_OBLI_DEF").sum()
    )
)

obligaciones_segun_contrato = (
    consolidado_ordenes_gasto.group_by("VIGENCIA","NRO_CONTRATO").agg(
        pl.col("TOTAL").sum()
    )
)

comprobacion_obliaciones_ordenes = (
    obligaciones_segun_contrato
    .join(
        obligaciones_segun_orden_gasto,
        left_on=["VIGENCIA","NRO_CONTRATO"],
        right_on=["VIGENCIA","NRO_ORDEN_GASTO"],
        how="left",
        coalesce=True
    )
)


# -------------------------------------------------- COMPROMISOS - HISTORICO GASTO -------------------------------------------------------------------

historico_ordenes_gasto_contratos_agrupado = (
    historico_ordenes_gasto_contratos.group_by("PREFIJO","NRODOC","RUBRO","RECURSO","PROYECTO").agg(
        pl.col("VALOR_CONTRATO").sum()
    )
)

comprobacion_contratos_compromisos = (
    obligaciones_segun_rp
    .join(
        historico_ordenes_gasto_contratos_agrupado,
        left_on=["VIGENCIA","NRO_RP","IDENTIFICACION_PRESUPUESTAL","FONDO","PROYECTO"],
        right_on=["PREFIJO","NRODOC","RUBRO","RECURSO","PROYECTO"],
        how="left"
    )
)
```

### Analisis

```python
from datetime import date

disponibilidad_def_segun_cdp = (
    cdps_por_proyecto.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRO_CDP","PROYECTO").agg(
        pl.col("VALOR_DISPONIBILIDAD_DEF").sum(),
        pl.col("FECHA_DISP").first()
    )
)

compromisos_por_proyecto = (
    consolidado_compromisos.group_by("VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRODOC_CDP","PROYECTO").agg(
        pl.col("VALOR_COMPROMISO_DEF").sum(),
    )
)

agregado_disponibilidades_compromisos = (
    disponibilidad_def_segun_cdp
    .join(
        compromisos_por_proyecto,
        left_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRO_CDP","PROYECTO"],
        right_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRODOC_CDP","PROYECTO"],
        how="inner",
    )
    .with_columns((pl.col("VALOR_DISPONIBILIDAD_DEF")-pl.col("VALOR_COMPROMISO_DEF")).alias("SALDO_SIN_COMPROMETER"))
)

disponibilidad_sin_compromiso = (
    compromisos_por_proyecto
    .join(
        disponibilidad_def_segun_cdp,
        left_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRODOC_CDP","PROYECTO"],
        right_on=["VIGENCIA","IDENTIFICACION_PRESUPUESTAL","FONDO","NRO_CDP","PROYECTO"],
        how="anti",
    )
)

#if disponibilidad_sin_compromiso.height == 0:
#    print(f"""De acuerdo con las llaves y el nivel de granularidad de la tabla de disponibilidades y compromisos 
#    todos los CDPs soportan al menos un RP. Vease {disponibilidad_sin_compromiso} 
#    el cual realiza un join tipo anti desde compromisos a disponibilidades""")
#else:
#    print(f"""De acuerdo con las llaves y el nivel de granularidad de la tabla de disponibilidades y compromisos 
#    hay algunos RPs que no están soportados por CDPs. Vease: {disponibilidad_sin_compromiso} 
#    el cual realiza un join tipo anti desde compromisos a disponibilidades""")
```

## Reporte

```python
consolidado_siifweb = (
    cdps_por_proyecto
    .join(rps_por_proyecto,on=["PROYECTO","VIGENCIA"],how="left",validate="1:1")
    .join(obligacion_por_proyecto,on=["PROYECTO","VIGENCIA"],how="left",validate="1:1")
    .join(reservas_por_proyecto,left_on=["PROYECTO","VIGENCIA"],right_on=["PROYECTO",pl.col("VIGENCIA")-1],how="left",validate="1:1")
    .drop("PROYECTO_right","VIGENCIA_right")
    .join(contracredito_por_proyecto,on=["PROYECTO","VIGENCIA"],how="left",validate="1:1")
    .join(contratos_por_proyecto,on=["PROYECTO","VIGENCIA"],how="left",validate="1:1")
)

consolidado_siifweb.write_excel("SIIFWEB/Reportes/ReporteSIIFWEB.xlsx",table_name="ReporteSIIFWEB")
```
