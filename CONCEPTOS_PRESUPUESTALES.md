# Conceptos presupuestales del aplicativo

Qué significan los términos que se usan en el seguimiento del POAI y en el código: línea de
apropiación, partida, documento, imputación, cadena de gasto. Complementa `NOTAS_CRUCES.md`
(llaves para cruzar los reportes) y `ESTRUCTURA_BD.md` (tablas).

Los valores, números de documento y códigos de los ejemplos son ilustrativos.

---

## 1. La línea de apropiación

El presupuesto no se aprueba como una sola bolsa de plata. Se aprueba en **líneas**, y cada
línea es una combinación de cinco datos:

| dato | qué dice | otros nombres |
|---|---|---|
| **vigencia** | el año del presupuesto | año |
| **rubro** | en qué se gasta (clasificación del gasto) | partida, posición, rubro presupuestal |
| **fuente** | de qué recurso sale la plata | fondo (consolidados de SIIFWEB), recurso (reporte de ejecución de gastos) |
| **centro de costo** | qué dependencia lo ejecuta | dependencia ejecutora, sección |
| **proyecto** | a qué proyecto de inversión va | BPIN; "0" en funcionamiento |

Cada línea tiene su propia **apropiación** (cuánto se puede gastar) y su propia ejecución
(cuánto se ha certificado, comprometido, obligado y pagado).

**Ejemplo.** Un proyecto de inversión con dos fuentes en 2026:

| vigencia | rubro | fuente | centro de costo | BPIN | apropiación definitiva |
|---|---|---|---|---|---|
| 2026 | 2.3.2.02.02.009 | Recursos propios | 16 - Infraestructura | 202500000039332 | 600.000.000 |
| 2026 | 2.3.2.02.02.009 | SGP | 16 - Infraestructura | 202500000039332 | 400.000.000 |

Son **dos líneas distintas**: comparten rubro, centro de costo y proyecto, pero cambian de
fuente. Lo que se ejecuta de recursos propios no se puede pagar con la apropiación del SGP, y
al revés.

Si se cambia cualquiera de los cinco datos, es otra línea:

- la misma combinación en **2025** es otra línea (otro presupuesto);
- el mismo rubro y fuente en **otro centro de costo** es otra línea;
- el mismo rubro y fuente en **otro BPIN** es otra línea.

Así viene el reporte de **ejecución de gastos** de SIIFWEB que usa el CUIPO
(`FilaEjecucionGastos`): una fila por línea, con apropiación inicial, modificaciones,
apropiación definitiva, CDP, RP, obligación y pago.

### "Partida" en sentido estricto y en el uso diario

- En lenguaje técnico de presupuesto, la **partida** o **rubro presupuestal** es solo el
  rubro: `2.3.2.02.02.009`.
- En la conversación diaria se dice "la partida" para hablar de la línea completa (rubro,
  fuente, centro de costo, proyecto). No está mal, pero cuando haya que ser precisos conviene
  decir "línea de apropiación".

---

## 2. La cadena de gasto

La plata de una línea pasa por pasos, cada uno con su documento:

| paso | documento | qué significa |
|---|---|---|
| 1 | **Apropiación** | el presupuesto aprobado para la línea |
| 2 | **CDP** (certificado de disponibilidad presupuestal) | se aparta plata de la línea para un fin: "hay con qué" |
| 3 | **RP** (registro presupuestal) = **compromiso** | se compromete esa plata con un tercero (un contrato, una nómina) |
| 4 | **Obligación** | el bien o servicio se recibió y se debe pagar |
| 5 | **Pago** | sale la plata (orden de pago de tesorería) |

Al cierre del año:

- lo **comprometido sin obligar** pasa a la vigencia siguiente como **reserva presupuestal**;
- lo **obligado sin pagar** pasa como **cuenta por pagar**.

Cada paso sale del anterior: un RP toma de uno o varios CDP, y una obligación se causa contra
uno o varios RP. Esa relación entre documentos va en las **imputaciones** (sección 3), no en
el encabezado del documento.

---

## 3. Documento e imputación

### El documento

Un CDP, un RP o una obligación es un documento con un número, una fecha, un objeto y un valor
total. En el aplicativo es el **encabezado**: `Cdp`, `Compromiso`, `Obligacion`, `Reserva`.

El encabezado trae, entre otros:

- la **vigencia** y el **número**: la numeración vuelve a empezar en 1 cada año, así que el
  documento se identifica con los dos (el CDP 514 de 2025 y el CDP 514 de 2026 son distintos);
- el **centro de costo** que lo expide.

### La imputación

La **imputación** es la línea del documento que dice **a qué línea de apropiación se carga
cada parte de su valor**. Trae:

- **rubro**, **fuente** y **proyecto**;
- el **valor** que se carga a esa combinación;
- en el RP, el **CDP del que sale**; en la obligación, el **RP contra el que se causa**.

El centro de costo y la vigencia no se repiten en cada imputación: se toman del encabezado.
Juntando las dos cosas (encabezado + imputación) se llega a la línea de apropiación completa.

En el aplicativo: `CdpImputacion`, `CompromisoImputacion`, `ObligacionImputacion`,
`ReservaImputacion` y `ContratoImputacion`.

### Imputar

**Imputar** es asignar el valor de un documento a una o varias líneas de apropiación. Es decir,
decir de qué rubro, fuente y proyecto sale la plata.

---

## 4. Ejemplo completo

### CDP 514 de 2026, por 100.000.000, centro de costo 16

Encabezado:

| vigencia | número | fecha | centro de costo | objeto | valor |
|---|---|---|---|---|---|
| 2026 | 514 | 15/01/2026 | 16 - Infraestructura | Construcción de placa huella | 100.000.000 |

Imputaciones (de dónde sale la plata):

| rubro | fuente | BPIN | valor |
|---|---|---|---|
| 2.3.2.02.02.009 | Recursos propios | 202500000039332 | 60.000.000 |
| 2.3.2.02.02.009 | SGP | 202500000039332 | 40.000.000 |

El CDP aparta 60 millones de la línea de recursos propios y 40 millones de la línea del SGP.
La suma de sus imputaciones es el valor del documento.

### RP 300 de 2026, que toma de dos CDP

| CDP de origen | rubro | fuente | BPIN | valor |
|---|---|---|---|---|
| 514 | 2.3.2.02.02.009 | Recursos propios | 202500000039332 | 60.000.000 |
| 520 | 2.3.2.02.02.009 | Recursos propios | 202500000039332 | 15.000.000 |

Un solo RP (un contrato de 75 millones) se respalda con dos CDP. Por eso la relación RP → CDP
va en la imputación: en el encabezado no cabrían dos CDP.

### Un documento que reparte entre dos proyectos

Una obligación de 50 millones puede imputarse a dos BPIN distintos (por ejemplo, una
interventoría que cubre dos obras):

| RP | rubro | fuente | BPIN | valor |
|---|---|---|---|---|
| 300 | 2.3.2.02.02.009 | Recursos propios | 202500000039332 | 30.000.000 |
| 310 | 2.3.2.02.02.009 | Recursos propios | 202600000018441 | 20.000.000 |

Al proyecto 202500000039332 le corresponden 30 millones de esa obligación, no 50.

---

## 5. Por qué importa al sumar

**Lo que se le atribuye a un proyecto se suma por imputaciones, no por documentos.**

En el último ejemplo, si se sumara el valor del documento completo para cada proyecto, los dos
proyectos quedarían con 50 millones obligados, y entre los dos sumarían 100 cuando la
obligación es de 50. Sumando las imputaciones con el BPIN del proyecto, cada uno queda con lo
suyo (30 y 20).

Por eso la ficha del proyecto, el avance financiero y los reportes suman sobre las tablas
`*Imputacion` filtradas por proyecto.

Otras reglas que salen de lo mismo (detalle en `NOTAS_CRUCES.md`):

- **La vigencia va en toda llave**: sin ella se mezclan documentos distintos con el mismo
  número.
- **Agregar antes de cruzar**: un documento puede traer varias líneas sobre la misma
  imputación (mismo rubro, fuente y proyecto). Hay que sumarlas antes de compararlas con otra
  tabla.
- **Los acumulados se arrastran hacia atrás**: el reporte de CDP trae también lo comprometido,
  obligado y pagado de cada CDP. Para totales se usa una sola tabla, la más cercana al hecho
  (lo obligado, de las obligaciones), o se cuenta lo mismo varias veces.
- **No sumar dos relaciones a la vez en una consulta**: al juntar imputaciones con otra tabla
  hija (por ejemplo, las actas de un contrato) las filas se multiplican. Se resuelve con
  subconsultas (`suma_de` en admin.py).

---

## 6. Glosario rápido

| término | significado |
|---|---|
| **Apropiación inicial** | lo aprobado al empezar el año para la línea |
| **Apropiación definitiva** | la inicial más adiciones y créditos, menos reducciones y contracréditos |
| **Disponible** | apropiación definitiva menos lo certificado (CDP) |
| **CDP** | certificado de disponibilidad: aparta plata de la línea |
| **RP / compromiso** | registro presupuestal: compromete la plata con un tercero |
| **Obligación** | lo que se debe pagar porque el bien o servicio se recibió |
| **Pago** | lo que salió de tesorería |
| **Reserva presupuestal** | compromiso sin obligar al cierre, que pasa al año siguiente |
| **Cuenta por pagar** | obligación sin pagar al cierre, que pasa al año siguiente |
| **Fuente / fondo / recurso** | de dónde sale la plata (recursos propios, SGP, regalías...) |
| **Rubro / partida** | en qué se gasta, según el catálogo presupuestal |
| **Centro de costo** | la dependencia que ejecuta el gasto en SIIFWEB |
| **Dependencia responsable** | la que responde por el proyecto según el POAI; puede ser distinta del centro de costo |
| **BPIN** | código del proyecto de inversión; "0" en funcionamiento |
| **Vigencia** | el año presupuestal |
| **Línea de apropiación** | vigencia + rubro + fuente + centro de costo + BPIN |
| **Imputación** | la línea de un documento que carga parte de su valor a una línea de apropiación |
| **Imputar** | asignar el valor de un documento a una o varias líneas de apropiación |
