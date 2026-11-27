# Cambios de agosto de 2026

Lo que se agrego al proyecto de seguimiento POAI en esta tanda: la contratacion publica
de SECOP II, el objeto y el beneficiario de las obligaciones, la ficha en dos pestanas y
una bateria de pruebas automaticas. Commits `f1d007e`, `7cdf343` y `dcbcfbe`.

---

## 1. SECOP II: tres modelos nuevos

Vienen del consolidado **"BPIN por proceso"**, que junta tres bases de datos abiertos del
DNP: *BPIN por Proceso* (trae el BPIN y las tres llaves), *Procesos de Contratacion* (las
fechas de publicacion y el estado del procedimiento) y *Contratos Electronicos* (el
contrato adjudicado). Una tabla por base de origen.

### Grano verificado sobre los datos

Medido sobre `data/secop/ReporteSIIFWEB_20260814.xlsx` (4.546 filas, 23 columnas):

| Relacion | Resultado |
|---|---|
| ID Proceso -> ID Portafolio | siempre uno (0 procesos con dos portafolios) |
| ID Portafolio -> ID Proceso | 114 portafolios agrupan 2-3 procesos |
| ID Proceso -> ID Contrato | 81 procesos con mas de un contrato |
| ID Contrato -> ID Proceso | siempre uno (3.988 de 3.988) |
| ID Contrato -> BPIN | 17 contratos financian mas de un BPIN |
| Datos del contrato repetidos entre filas | 0 inconsistencias de valor, referencia o estado |

Ademas: 526 filas con `ID Contrato = "No Definido"` (250 procesos publicados que aun no
adjudican), 12 filas duplicadas exactas y 2 contratos con valores imposibles.

### `ProcesoSecop` — el proceso de contratacion

| Campo | Tipo | Nota |
|---|---|---|
| `id_proceso` | CharField(60) **unique** | `CO1.REQ.…` |
| `id_portafolio` | CharField(60), indexado | `CO1.BDOS.…`; agrupa procesos |
| `estado_procedimiento` | CharField(60) | Seleccionado, Evaluacion, Cancelado… |
| `fecha_publicacion`, `fecha_ultima_publicacion`, `fecha_recepcion_respuestas`, `fecha_apertura_respuestas`, `fecha_apertura_efectiva` | Date, nulas | las tres ultimas solo existen cuando hay ofertas que abrir (90% vacias) |
| `reporte` | FK -> `CargaReporte` (PROTECT, nula) | trazabilidad de la carga |

### `ContratoSecop` — el contrato electronico

| Campo | Tipo | Nota |
|---|---|---|
| `id_contrato` | CharField(60) **unique** | `CO1.PCCNTR.…` |
| `proceso` | **FK -> `ProcesoSecop`** (PROTECT), `related_name="contratos_del_proceso"` | cada contrato cuelga de un proceso |
| `referencia` | CharField(120) | `CPS-872-2024`. **No es** el numero de contrato de SIIFWEB |
| `estado` | CharField(60) | En ejecucion, terminado, Modificado… |
| `objeto`, `descripcion_proceso` | TextField | casi siempre el mismo texto |
| `proveedor` | **FK -> `Tercero`** (PROTECT, nula), `related_name="contratos_secop"` | por `Documento Proveedor` |
| `valor` | Decimal(20,2), nulo | |
| `fecha_firma`, `fecha_inicio`, `fecha_fin` | Date, nulas | |
| `url_proceso` | TextField | enlace publico al proceso |
| `reporte` | FK -> `CargaReporte` | |

### `BpinProceso` — la fila del consolidado

Es una tabla propia y no un campo del contrato porque el grano lo exige: un contrato puede
financiar varios BPIN y un proceso puede no tener contrato.

| Campo | Tipo | Nota |
|---|---|---|
| `bpin` | CharField(25), indexado | **siempre se guarda**, aunque no haya proyecto |
| `proyecto` | **FK -> `Proyecto`** (PROTECT, nula), `related_name="procesos_secop"` | nula si el BPIN no esta en el catalogo |
| `proceso` | **FK -> `ProcesoSecop`** (PROTECT), `related_name="bpines"` | |
| `contrato_secop` | **FK -> `ContratoSecop`** (PROTECT, nula), `related_name="bpines"` | nula si el proceso no adjudico |
| `anio` | Integer, nulo | `Anno BPIN` |
| `validacion_bpin` | CharField(20) | Validado / No validado |
| `reporte` | FK -> `CargaReporte` | |

**Restriccion:** `UniqueConstraint(bpin, proceso, contrato_secop)` con nombre
`bpin_proceso_unico`. Ojo: `contrato_secop` admite nulos y en SQL dos nulos no colisionan,
asi que **no cubre las filas sin contrato**; por eso el cargador deduplica en Python antes
de insertar (el archivo trae 12 filas repetidas).

### Por que no hay enlace con el contrato de SIIFWEB

La numeracion de SECOP es independiente: de 1.342 casos con el mismo NIT y la misma fecha
de firma, en **0** coincide el numero de contrato. Y el dato abierto del DNP no trae
ninguna columna con el numero de SIIFWEB —se consulto el esquema del dataset—. Se probo una
cascada por NIT + valor + fecha que enlazaba el 84,8%, pero se descarto por decision del
equipo: **el cruce es a nivel de BPIN, es decir de proyecto**.

---

## 2. Obligaciones: dos campos nuevos

El consolidado de obligaciones paso de 25 a 27 columnas: agrego `OBJETO_OBLIG`, `NIT` y
`BENEFICIARIO`. Ojo con esto al validar contra `data/parquet/`: esos parquet son de julio y
tienen el esquema viejo.

| Campo | Tipo | Origen |
|---|---|---|
| `Obligacion.objeto_oblig` | TextField, vacio permitido | `OBJETO_OBLIG` |
| `Obligacion.beneficiario` | **FK -> `Tercero`** (PROTECT, nula), `related_name="obligaciones"` | `NIT` + `BENEFICIARIO` |

El beneficiario enriquece el catalogo: los terceros que estaban solo con NIT ganan razon
social. El objeto es util de verdad —"ACTA PARCIAL 3 …", "PAGO FACTURA N° FE7…"—, mucho
mas informativo que el objeto del RP.

Nota de nomenclatura: el "valor de la obligacion definitiva" ya estaba modelado. El
cargador guarda `VALOR_OBLI_DEF` en `ObligacionImputacion.valor_obligacion`; en 2025
`VALOR_OBLIGACION` y `VALOR_OBLI_DEF` coinciden en las 13.980 filas.

---

## 3. Metodos de cargue

### Tipo de reporte nuevo

`CargaReporte.TipoReporte.SECOP = "secop"`, sin vigencia (rango completo, como el
historial), y `cargas.PROCESADORES["secop"] = cargar_secop`.

### `leer_filas(ruta, hoja=None, tabla=None, columnas=None)`

Gana dos parametros:

- **`tabla`**: busca una TABLA de Excel **por su nombre**, en la hoja que sea, y lee solo
  sus celdas. Asi sirve cualquier libro que contenga `BPIN_por_proceso`, se llame como se
  llame el archivo. Sin esto, un libro de 24 hojas caia en la primera y cargaba basura en
  silencio. Requiere abrir el libro completo: `ws.tables` no existe en modo `read_only`.
- **`columnas`**: lista de encabezados obligatorios; si falta alguno, aborta con el nombre
  del que falta antes de escribir nada.

Los seis cargadores anteriores no pasan `tabla` y siguen leyendo igual (hoja por nombre, o
la primera). Hay pruebas de regresion para eso.

### `cargar_secop(carga)`

Atomico (`@transaction.atomic`) y con **reemplazo total**: borra `BpinProceso`,
`ContratoSecop` y `ProcesoSecop` y vuelve a escribir. Tres pasadas sobre las filas:

1. **Procesos**, deduplicando por `ID Proceso`. Verifica que `Proceso de Compra` sea igual
   a `ID Portafolio` (lo es en el 100% de las filas) y avisa en el mensaje si deja de serlo.
2. **Contratos**, deduplicando por `ID Contrato` y saltando `"No Definido"`. El proveedor
   sale de `Documento Proveedor` contra el catalogo `Tercero`.
3. **Filas BPIN**, deduplicando por `(bpin, proceso, contrato)`.

Reglas:

- **No crea proyectos.** Busca el BPIN en el catalogo; si no esta, la fila entra con
  `proyecto` nulo y el BPIN queda a la vista en el mensaje de la carga y en `validar`.
  Es deliberado: SECOP es una fuente de terceros y un BPIN suyo puede no ser un proyecto
  del departamento.
- Los identificadores se normalizan con `texto()` (sin sufijo `.0`), los valores con
  `decimal()` y las fechas con `fecha()`.

### Orden de proceso del lote

`cargas.ORDEN_DE_CARGA` declara la cadena:

```
cdp -> compromisos -> obligaciones -> reservas -> historial -> poai -> secop
```

La accion del admin ordena sola con
`order_by(F("vigencia").asc(nulls_last=True), "_orden", "id")`, donde `_orden` es la
posicion del tipo en esa lista. Es decir: vigencia ascendente, dentro de cada vigencia la
cadena, y al final los de rango completo. **Se pueden subir los reportes en cualquier orden
y procesarlos todos de una pasada.**

Antes hacia falta partir el lote en dos tandas por dos razones: se ordenaba solo por
`vigencia` y donde caen los nulos depende del motor (SQLite los pone primero, PostgreSQL al
final), y el desempate dentro de una vigencia era el `id`, o sea el orden de creacion.

### Si no se sube el POAI

No genera conflictos: el orden se acomoda a lo que haya y las cargas son acumulativas. Solo
cambian dos cosas: los proyectos que existen en el banco pero no ejecutan en SIIFWEB no
entran al catalogo (hoy 79; de ellos **2** tienen contratacion en SECOP, asi que sus filas
quedarian con proyecto nulo), y los proyectos nuevos entran sin clasificacion, que es lo que
filtra por defecto el listado de `Proyectos`.

---

## 4. La ficha de ejecucion

Dos pestanas sobre la misma URL, `?panel=siifweb|secop`, cada una enlazable y calculada
solo cuando se abre.

**Panel SIIFWEB** — lo que ya habia, mas la **seccion de obligaciones** (vigencia, numero,
fecha, beneficiario con NIT, objeto y valor definitivo), ubicada debajo de los RPs. El
objeto propio manda; si la obligacion se cargo antes de que existiera el campo, se muestra
el del RP, resuelto por subconsulta.

**Panel SECOP II** — tarjetas (procesos en tramite, contratos, valor contratado y el
comprometido de SIIFWEB como contraste), tabla de procesos sin adjudicar y tabla de
contratos. En ese orden, que es el del tramite.

Detalles de implementacion que conviene recordar:

- El detalle de cada contrato o proceso se abre en un **modal** alimentado por atributos
  `data-*` de la propia fila: no hay segunda consulta ni endpoint nuevo.
- Las tablas largas se cortan a 26 rem con scroll propio y encabezado fijo.
- Los titulos llevan un icono de ayuda con su explicacion, via
  `{% include "siifweb/_ayuda.html" with etiqueta="…" texto="…" %}`.
- **Trampa del grano, otra vez**: sumar dos relaciones a la vez con `Sum()` multiplica las
  filas. Los contratos del proyecto se resuelven con una subconsulta de ids y el valor de la
  obligacion con un solo `Sum` sobre la relacion ya filtrada.
- En las plantillas, `{# … #}` comenta **una sola linea**; para varias va
  `{% comment %}…{% endcomment %}`. Un comentario multilinea con `{# #}` se imprime en la
  pagina.

---

## 5. Validaciones

`manage.py validar` gana la **seccion 8**, que no depende de `--vigencia` porque el
consolidado se descarga por rango completo:

| Revision | Que significa si falla |
|---|---|
| Cada fila apunta al proceso de su contrato | incoherencia de la carga |
| Todo contrato tiene su fila BPIN | quedo un contrato huerfano |
| Los BPIN estan en el catalogo | **accionable**: crear el proyecto o revisar el BPIN. Los lista uno por uno |
| Los BPIN estan validados por el DNP | aviso de la fuente |
| Los valores estan dentro de lo posible | error de digitacion en SECOP; se cargan igual y se reportan |

Ademas informa contratos sin proveedor o sin fecha de firma, proveedores sin razon social,
los procesos sin adjudicar por estado, y cuantos proyectos con contratacion tienen tambien
compromisos en SIIFWEB. El contraste de valores entre SECOP y SIIFWEB es informativo, no una
conciliacion: el contrato es el total pactado y el compromiso es el RP de cada vigencia.

---

## 6. Pruebas

131 pruebas en `seguimiento_poai/siifweb/tests/`, que corren con
`uv run --directory seguimiento_poai python manage.py test siifweb`.

**Nunca tocan produccion**: `settings.py` detecta el comando `test` y fuerza sqlite en
memoria, almacenamiento temporal y un hasher rapido. Sin esa guarda, el `DATABASE_URL` del
`.env` habria creado la base de prueba en Supabase.

Se verificaron por mutacion: se rompio el codigo a proposito en veintitantos puntos y en
todos fallo la prueba que corresponde. **Tres pruebas resultaron pasar con el codigo roto y
hubo que corregirlas** — que la suite este en verde no basta.

---

## 7. Estado operativo

| Donde | Que hay |
|---|---|
| Supabase (produccion) | migraciones `0006`, `0007` y `0008` aplicadas; obligaciones 2022-2025 recargadas con objeto y beneficiario al 100%. **SECOP II todavia no esta cargado** y 2026 lo actualiza el equipo |
| sqlite local (`db.sqlite3`) | todo lo anterior mas el consolidado de SECOP II y las obligaciones 2026 |
| Migraciones | `0006` SECOP + tipo de reporte · `0007` `objeto_oblig` · `0008` `beneficiario` |

Pendientes anotados:

- Cargar el consolidado de SECOP II en produccion.
- Los 7 BPIN de SECOP sin proyecto en el catalogo (`validar` los lista).
- Recargar los compromisos en la sqlite local si se quiere ver el objeto del RP ahi
  (cosmetico: las obligaciones ya traen objeto propio).
- Evaluar un `.gitattributes` que fije los finales de linea en LF: la copia de MEGA usa
  CRLF y el repo LF, y eso ensucia los diff.
