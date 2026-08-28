# Modelo de cruce — Ejecución presupuestal por proyecto

Explica las llaves con las que se arma el reporte, por qué no duplican y por qué tienen
lógica presupuestal.

---

## La idea central: las 4 coordenadas del gasto

En el presupuesto público, cada peso vive en una "línea de apropiación" que se identifica
con cuatro datos:

- **PROYECTO** → a qué proyecto (BPIN) sirve.
- **VIGENCIA** → en qué año.
- **RUBRO** → en qué clasificación del gasto (el "para qué").
- **RECURSO / FUENTE** → con qué plata se financia (el "de dónde sale").

Esa combinación es la **dirección** de un recurso dentro del presupuesto. Todo lo que pasa
después —certificar (CDP), comprometer (RP), obligar, pagar, reservar— ocurre **sobre esa
misma línea** y hereda esas cuatro coordenadas. Por eso todos los reportes se pueden juntar
por ahí: hablan de la misma línea, solo que cada uno cuenta un momento distinto de su vida.

---

## Conceptos presupuestales (qué es cada cosa)

Para entender las llaves hay que tener claro qué representa cada archivo. Todos son estados
de la **misma plata** en distinto momento de su ejecución.

### Las coordenadas — dónde vive la plata
- **Apropiación:** el techo de gasto autorizado para una línea en el año. Nace como
  *inicial* y puede cambiar con adiciones y traslados (*definitiva*).
- **Rubro (identificación presupuestal):** la clasificación del gasto — el *para qué*.
- **Fuente / recurso / fondo:** de dónde sale la plata (recursos propios, SGP, regalías…) —
  el *de dónde*.
- **Proyecto (BPIN):** en inversión, a qué proyecto sirve.
- **Vigencia:** el año fiscal. El presupuesto es **anual**: la apropiación nace el 1 de
  enero y muere el 31 de diciembre.

### Los momentos del gasto — qué le pasa a la plata
- **CDP – Certificado de Disponibilidad Presupuestal:** certifica que *hay* apropiación
  libre en la línea para iniciar el proceso. Aparta la plata de forma preliminar.
- **RP – Registro Presupuestal (compromiso):** *amarra* la plata a un contrato y un
  contratista. Aquí el gasto queda comprometido jurídicamente.
- **Obligación:** reconoce que el bien o servicio ya se recibió; la deuda queda *causada*
  (ya se debe).
- **Pago:** extingue la obligación (ya se pagó).
- **Reserva presupuestal:** al cierre del año, el compromiso (RP) que no se alcanzó a
  obligar no se pierde: sobrevive a la muerte de la apropiación y pasa al año siguiente
  como reserva, para pagarse allí.

Cada consolidado del modelo es, en el fondo, **uno de estos momentos**: Disponibilidades =
CDP, Compromisos = RP, Obligaciones = obligación, Reservas = reserva, e Historial = los
contratos que materializan el compromiso.

---

## La tabla base

**Ejecución presupuestal del gasto cc y fondo** es el eje. Ya viene al nivel de
**PROYECTO + VIGENCIA + RUBRO + RECURSO**, con los totales de cada paso (apropiación
inicial y definitiva, CDP, RP, obligación, pago). Es el resumen oficial; le falta el
detalle (fechas, números de documento, actos administrativos, contratos). Ese detalle lo
aportan los cinco consolidados que se le cruzan.

---

## La llave maestra

**PROYECTO + VIGENCIA + RUBRO + RECURSO.** Cada fuente la llama distinto:

| Coordenada | En Ejecución / Historial | En los Consolidados |
|---|---|---|
| Proyecto | `PROYECTO` | `PROYECTO` |
| Vigencia | `VIGENCIA` | `VIGENCIA` |
| Rubro | `RUBRO` | `IDENTIFICACION_PRESUPUESTAL` |
| Recurso / fuente | `RECURSO` | `FONDO` |

Es decir: `RUBRO = IDENTIFICACION_PRESUPUESTAL` y `RECURSO = FONDO`. Es el mismo dato con
otro nombre.

---

## Por qué los cruces no duplican

Antes de cruzar, **cada consolidado se agrupa a esa misma llave** (una fila por
proyecto+vigencia+rubro+fondo). Así cada tabla queda con **un solo registro por línea**, y
el cruce contra la base es **uno a uno**: ninguna fila se multiplica. Dentro de cada grupo
se calculan los agregados (la primera fecha, la lista de documentos, el acto administrativo),
pero hacia afuera entregan una sola fila por línea.

---

## Los cinco cruces, uno por uno

Todos parten de la base con `PROYECTO + VIGENCIA + RUBRO + RECURSO` y son `LeftOuter`
(conservan todas las líneas de la ejecución).

### 1. Disponibilidades (CDP)
- **Base:** PROYECTO, VIGENCIA, RUBRO, RECURSO
- **Consolidado:** PROYECTO, VIGENCIA, IDENTIFICACION_PRESUPUESTAL, FONDO
- **Trae:** `PRIMER_CDP` (fecha del primer CDP de la línea) y `CDPS_FECHA` (lista de CDPs).
- **Lógica:** el CDP certifica que había plata disponible en esa línea. Cruza directo.

### 2. Compromisos (RP)
- **Base:** PROYECTO, VIGENCIA, RUBRO, RECURSO
- **Consolidado:** PROYECTO, VIGENCIA, IDENTIFICACION_PRESUPUESTAL, FONDO
- **Trae:** `PRIMER_RP`, `RPS_FECHA` y `ACTOS_ADMON` (la modalidad con que se comprometieron
  los recursos).
- **Lógica:** el RP compromete la plata de esa línea al firmar. Misma dirección.

### 3. Obligaciones
- **Base:** PROYECTO, VIGENCIA, RUBRO, RECURSO
- **Consolidado:** PROYECTO, VIGENCIA, IDENTIFICACION_PRESUPUESTAL, FONDO
- **Trae:** `PRIMERA_OBLIGACION`, `OBLIG_FECHA` y `TIPO_ORDEN_GASTO` (la misma modalidad del
  acto administrativo, sin el número).
- **Lógica:** la obligación causa el gasto ya ejecutado sobre esa línea.

### 4. Historial de orden de gasto 2 (contratos) — ajuste de vigencia
- **Base:** PROYECTO, VIGENCIA, RUBRO, RECURSO
- **Historial:** PROYECTO, **PREFIJO**, RUBRO, RECURSO
- **Trae:** `INFO_CONTRATOS`, `FECHA_FIRMA_PRIMER_CONTRATO`, `FECHA_INICIO_PRIMER_CONTRATO`.
- **Ajuste:** aquí la vigencia se llama `PREFIJO` (es la vigencia del contrato). Por eso
  `VIGENCIA ↔ PREFIJO`.
- **Lógica:** el historial dice qué contratos ejecutan esa línea. El PREFIJO del contrato es
  el año presupuestal al que está cargado, así que cumple el papel de la vigencia.

### 5. Reservas — ajuste de vigencia (año − 1)
- **Base:** PROYECTO, VIGENCIA, RUBRO, RECURSO
- **Consolidado:** PROYECTO, **VIGENCIA_CRUCE (VIGENCIA − 1)**, IDENTIFICACION_PRESUPUESTAL, FONDO
- **Trae:** `VALOR_RESERVA_DEF`, `SALDO_RESERVA`, `OBLIGACIONES_RESERVA`, `PAGOS_RESERVA`.
- **Ajuste:** la reserva se cruza contra la línea del **año anterior** (`VIGENCIA − 1`).
- **Lógica:** una reserva presupuestal nace de un compromiso del año anterior que no se
  alcanzó a ejecutar. La plata de la reserva de 2024 vivió en la línea de 2023; por eso se
  la asocia a la vigencia anterior, no a la propia.

---

## El sub-cruce del contrato (dentro del Historial)

Antes de subir al eje, el Historial resuelve **cuál duración** le corresponde a cada
contrato cruzándose con *Órdenes de gasto por fecha* por
**número de contrato + contratista + fecha de firma + RP**
(`DOCCONTRATO/NRO_CONTRATO`, `TERCERO`, `FECHA_FIRMA`, `NRODOC/COMPROMISO`).
Ese cruce está documentado aparte en [llave_cruce_contratos.md](llave_cruce_contratos.md).
La clave: el **RP** es el punto donde el contrato queda amarrado a una imputación puntual,
y por eso identifica cada línea de contrato sin duplicar.

---

## Cómo los conceptos fundamentan las llaves

Las llaves no son una decisión técnica: salen directo de tres principios del presupuesto
público. Cada principio justifica una parte de la llave.

### 1. Principio de imputación → funda las 4 coordenadas
Ningún peso se mueve sin quedar **imputado** a un rubro, una fuente y (en inversión) un
proyecto. Es una exigencia legal, y se cumple en **todos** los momentos del gasto: el CDP,
el RP, la obligación y la reserva llevan la misma imputación que la apropiación de origen.
Como esa dirección es obligatoria y estable a lo largo de toda la cadena,
`PROYECTO + RUBRO + RECURSO` es una identidad que todos los documentos comparten. Por eso
sirve de llave: no es que "coincidan por casualidad", es que **por ley tienen que coincidir**.

### 2. Principio de anualidad → funda la VIGENCIA y el ajuste de reservas
El presupuesto es anual: la apropiación vive un solo año. Por eso la **vigencia** entra en
la llave — una misma línea (proyecto+rubro+fuente) de 2023 y de 2024 son dos cosas
distintas y no se deben mezclar.
Y por eso las **reservas se cruzan contra la vigencia − 1**: la reserva es justamente el
mecanismo por el que un compromiso sobrevive a la muerte de su apropiación. La plata de la
reserva de 2024 se comprometió en la línea de 2023; su "dirección" natural es la del año
anterior.

### 3. Cadena de ejecución → funda que los momentos se junten
CDP → RP → obligación → pago no son cinco cosas separadas: son **estados sucesivos de la
misma línea de apropiación**.

```
Apropiación → CDP → RP (compromiso) → Obligación → Pago
                                   └→ Reserva (lo no ejecutado pasa al año siguiente)
```

Como son estados de la misma línea, comparten la imputación y se pueden empalmar por ella.
Cruzar los consolidados por las 4 coordenadas **reconstruye la vida completa de cada
línea**: cuánto se apropió, cuánto se certificó, cuándo salió el primer CDP y el primer RP,
con qué modalidad se comprometió, qué contratos la ejecutan, cuánto se obligó y pagó, y qué
quedó en reserva.

### 4. El RP como nexo contrato ↔ presupuesto → funda el sub-cruce del contrato
El RP es el acto que **amarra un contrato a una imputación**. Es el único punto donde
conviven, en un mismo registro, el contrato (número, contratista, firma) y la línea
presupuestal. Por eso el cruce contra el Historial de contratos se cierra con el **RP**: no
se cruzan contratos sueltos, se cruzan *compromisos*, que es lo que de verdad une un
contrato con una línea del presupuesto.

### En resumen
Los dos ajustes de la llave no son excepciones caprichosas, son el mismo marco legal:
- **Historial → PREFIJO** porque la vigencia del contrato es el año de la línea que ejecuta.
- **Reservas → vigencia − 1** porque, por anualidad, la reserva pertenece a la línea del
  año anterior.
