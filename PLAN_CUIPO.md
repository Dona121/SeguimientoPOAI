# Plan del módulo CUIPO (ejecución de gastos de inversión por producto MGA)

Documento autocontenido, redactado el 13 de noviembre de 2026. Reúne el diseño funcional,
lo que ya existe en el aplicativo, los ajustes que salieron de revisar los datos reales y
el plan por fases. Sirve para continuar el trabajo en otra conversación sin el historial.

**Quién lo construye.** Donaldo (Secretaría de Planeación, Gobernación de Sucre) escribe
los modelos y el código por fases para aprender construyéndolo; el asistente revisa lo que
él le pase. La excepción es el importador del reporte de ejecución, que ya está hecho
(sección 3) porque se pidió explícitamente.

---

## 1. Objetivo

Generar el reporte CUIPO de CHIP (Contaduría General), categoría `D_EJECUCION_DE_GASTOS`,
para la inversión (rubros 2.3), abierto por producto MGA. Hasta ahora se armaba en Excel
con Power Query y scripts de Python.

El flujo es:

1. Cargar el reporte de ejecución de gastos de SIIFWEB de un corte (ya existe).
2. Derivar de cada fila el concepto, la fuente CUIPO, la sección, la situación de fondos y
   el tercero, con homologaciones y reglas.
3. Distribuir cada fila de cada BPIN entre los productos del proyecto (precarga automática
   y ajuste en pantalla).
4. Validar la distribución.
5. Generar el plano de texto que se sube a CHIP.

---

## 2. El aplicativo (lo necesario para trabajar en él)

**Ubicación y despliegue**
- Repositorio en `C:\Users\Donal\Documents\MEGA\Paginas\Siifweb`; el proyecto Django en
  `seguimiento_poai/` (settings en `config/settings.py`).
- Apps propias: `siifweb` (todo lo existente) y `cuipo` (nueva).
- Django 6.0.7, Python 3.13, admin con django-unfold. Excel con openpyxl (no Polars ni
  pandas). No hay HTMX, Celery, `views.py` ni `services.py`: la lógica va en módulos por tema
  (`siifweb/cargas.py`, `reportes.py`, `tablero.py`) y las pantallas propias son vistas del
  admin registradas en `get_urls()` de un `ModelAdmin`, con plantillas que extienden
  `admin/base_site.html`.
- Producción: Railway + Postgres y bucket S3 de Supabase. Un push a `main` despliega y corre
  `migrate` contra Supabase: **antes de cada push con migraciones se respalda Supabase**.
- Se trabaja en ramas; a `main` solo cuando se decide desplegar.

**Trabajo local**
- Base local SQLite: los comandos llevan
  `DATABASE_URL="sqlite:///C:/Users/Donal/Documents/MEGA/Paginas/Siifweb/seguimiento_poai/db.sqlite3"`.
- Servidor: `uv run python manage.py runserver 8010` (desde `seguimiento_poai/`, con esa variable).
- Pruebas: `uv run python manage.py test` (unittest de Django; corren en SQLite en memoria y
  disco temporal). Hoy son 404.
- **Cuidado:** el almacenamiento de archivos en local es el bucket de producción. Subir un
  archivo desde el admin local lo sube a producción. Para probar con archivos reales se lee
  del disco reemplazando `siifweb.cargas.stream` en un script, sin guardar el archivo.

**Convenciones**
- Todos los modelos heredan `siifweb.models.Fechas` (`fecha_creacion`, `fecha_actualizacion`).
- Lectura de Excel: `siifweb.cargas.leer_filas(contenido, hoja=None, tabla=None, columnas=None)`,
  `texto()` (códigos sin `.0`) y `decimal()` (acepta la coma decimal de SIIFWEB y aborta si un
  valor es ilegible).
- Cargas dentro de `transaction.atomic()`, con un mensaje de resultado en el registro.
- Admin de solo lectura: `siifweb.admin.SoloLectura`. Menú lateral en `UNFOLD["SIDEBAR"]` de
  `config/settings.py`; cada enlace con `permission=_con_permiso("app.view_modelo")`.
- Roles existentes: grupos `Consulta` y `Seguimiento` (migración `siifweb/0009`). No hay
  roles de planeación ni de presupuesto.
- Algunos archivos de `siifweb` tienen fin de línea CRLF (`models.py`, `admin.py`,
  `cargas.py`, `config/settings.py`): al editarlos, conservarlo.

**Datos de `siifweb` que usa el CUIPO**
- `Fuente(codigo, nombre)`: el código es el número de recurso de SIIFWEB (3, 7, 114...).
- `Rubro(codigo, nombre)`, `CentroCosto(codigo, nombre)`, `Proyecto(bpin)`.
- Estos catálogos los crean las cargas de los consolidados (CDP, compromisos, obligaciones).
  Un código que aparece en el reporte de ejecución antes de cargar los consolidados no
  existe todavía en ellos.
- **Productos por BPIN (PIIP):** `FormulacionProyecto` (uno a uno con `Proyecto`,
  `related_name="formulacion"`) → `IndicadorProyecto` (`formulacion.indicadores`) →
  `IndicadorCatalogo` (`related_name="en_proyectos"` desde `IndicadorProyecto`) →
  `ProductoCatalogo` (código de 7 dígitos). Los productos de un BPIN:
  `ProductoCatalogo.objects.filter(indicadores__en_proyectos__formulacion__proyecto__bpin=bpin).distinct()`.
  Se llenan con la carga "Información general PIIP" (tabla `InfoGeneral`).
- **Reservas:** `Reserva` + `ReservaImputacion` (`valor_reserva_def`, `obligaciones_reserva`,
  `pagos_reserva`, `saldo_reserva`). No tienen centro de costo y cada carga sobrescribe la
  vigencia.
- Nombres que ya existen en `siifweb`: `ProductoMGA` (catálogo del plan de desarrollo) y
  `Tercero` (contratistas).

**Ramas (ninguna subida a `main`)**

```
main ← formulacion-piip ← centro-costo-compromisos ← cuipo-ejecucion-gastos
```

- `formulacion-piip`: catálogo PIIP y formulación de los proyectos (productos por BPIN).
  Migraciones `siifweb/0020` y `0021`.
- `centro-costo-compromisos`: centro de costo por línea en `CompromisoImputacion`
  (migración `siifweb/0022`). El CUIPO ya no la necesita; está por decidir si se conserva.
- `cuipo-ejecucion-gastos`: la app `cuipo` con el importador (migración `cuipo/0001`).

---

## 3. Lo que ya existe: el corte de ejecución de gastos (app `cuipo`)

**Decisión.** El insumo del CUIPO es el reporte de SIIFWEB "Ejecución presupuestal del gasto
por centro de costo y fondo" (`estado_ppto_gasto_gobatl_fyccw_Vigencia{v}_Fecha{f}.xlsx`),
cargado por corte. **No** se reconstruye agrupando el consolidado de compromisos: el reporte
es la cifra oficial contra la que se cruza el CUIPO y no depende de que los CDP estén
cargados. Sus datos solo los usa el CUIPO (no alimentan la ficha ni el tablero), por eso
los códigos se guardan como texto, tal como vienen.

**El reporte**
- Hoja plana, encabezado en la fila 1, 22 columnas: `RUBRO_ID, RUBRO, NOMBRE_RUBRO, RECURSO,
  NOMBRE_RECURSO, CENTROCOSTO, NOMBRE_CENTROCOSTO, PROYECTO, APROPIACION_INICIAL, ADICION,
  DISMINUCION, CREDITO, CONTRACREDITO, APLAZAMIENTOS, DESAPLAZAMIENTOS,
  APROPIACION_DEFINITIVA, SOLICITUD_TRAMITE, CDP, RP, OBLIGACION, PAGO, DISPONIBLE`.
- Las filas sin `RECURSO` son subtotales del árbol de rubros (2, 2.1, 2.1.1...); las que lo
  traen son el detalle: rubro × recurso × centro de costo × proyecto (`PROYECTO` = BPIN,
  `0` = sin proyecto).
- `RUBRO_ID` es el id del rubro en SIIFWEB y cambia en cada vigencia. El reporte de 2023 trae,
  además de su árbol (raíz 11545), filas del árbol de 2022 (raíz 5582): 27 filas, 22 con
  BPIN, solo con obligación (16.890.687.467) y pago. Por eso rubro + recurso + centro de
  costo + proyecto se repite en 2023 y `RUBRO_ID` tiene que ir en la llave.
- Valores en float, entero o texto con coma decimal.

**Modelos** (`seguimiento_poai/cuipo/models.py`)
- `CorteEjecucionGastos`: `vigencia`, `fecha_inicio` y `fecha_fin` (el rango con que se
  descargó; para el CUIPO, que es acumulado, desde el 1 de enero; en una vigencia cerrada,
  hasta el 31 de diciembre), `fecha_descarga` (día en que se generó el archivo), `archivo`,
  `hash`, `filas`, `estado` (P / OK / E), `mensaje`. Único por (`vigencia`, `fecha_inicio`,
  `fecha_fin`). `clean()` exige inicio y fin dentro de la vigencia, fin ≥ inicio y
  descarga ≥ fin.
- `FilaEjecucionGastos`: `corte` (FK, CASCADE, `related_name="filas_ejecucion"`),
  `rubro_id_siifweb`, `de_otra_vigencia` (bool), `rubro`, `nombre_rubro`, `recurso`,
  `nombre_recurso`, `centro_costo`, `nombre_centro_costo`, `proyecto` (texto) y 13 valores
  `Decimal(20,2)`: `apropiacion_inicial`, `adicion`, `disminucion`, `credito`,
  `contracredito`, `aplazamientos`, `desaplazamientos`, `apropiacion_definitiva`,
  `solicitud_tramite`, `cdp`, `rp`, `obligacion`, `pago`. Única por (`corte`,
  `rubro_id_siifweb`, `recurso`, `centro_costo`, `proyecto`).

**Importador** (`seguimiento_poai/cuipo/ejecucion.py`)
- `importar(corte)`, atómico: lee el archivo, separa subtotales y detalle, asigna cada fila a
  su árbol (la raíz de mayor `RUBRO_ID` que no supere el suyo; el árbol de la vigencia es el
  de la raíz más reciente), **verifica que cada subtotal sea la suma de su detalle** en las
  13 columnas, rechaza filas repetidas, **borra las filas del corte y las vuelve a crear**.
- `procesar(corte)`: llama a `importar` y deja estado y mensaje; si falla, las filas previas
  del corte quedan intactas.
- No guarda `DISPONIBLE` ni los subtotales.

**Admin** (`seguimiento_poai/cuipo/admin.py`), menú "CUIPO"
- Cortes: se importa al guardar; acción "Volver a procesar"; totales de RP, obligación y pago;
  no acepta el mismo archivo dos veces.
- Filas: solo lectura, filtros por corte, vigencia y árbol de otra vigencia.

**Pruebas:** `seguimiento_poai/cuipo/tests/test_ejecucion_gastos.py` (17), con las funciones
`fila()`, `libro()` y `cortar()` para armar reportes en memoria.

**Datos de prueba**
- `modelos-metas/ejecucion-gastos/{2022..2026}/`: un reporte por vigencia (2022–2025
  descargados el 31/07/2026; 2026 al 11/11/2026). Cargados en la base local: 395, 463, 422,
  400 y 405 filas de detalle; los subtotales cuadran en los cinco.
- `modelos-metas/EjecucionGastos1Enero-30Septiembre.xlsx` tiene solo 10 columnas (una muestra
  de la estructura): **no se puede importar**. Falta descargar el corte 01/01–30/09/2026
  completo.

**Lo que mostró el cruce con los consolidados**
- El RP del reporte es el `VALOR_COMPROMISO_DEF` del consolidado de compromisos (no el
  `VALOR_REGISTRO`), y el centro de costo es el de cada fila, no el de la cabecera del RP.
- Hay movimientos que se registran después con fecha anterior (pagos de nómina fechados el
  25/09 que no aparecían en la ejecución al 30/09): dos descargas del mismo corte pueden
  diferir. Por eso el corte guarda la fecha de descarga.

**El corte de 2026 (al 11/11, sin el árbol de otra vigencia)**

| Grupo | Filas | Con valores | RP | Obligación | Pago |
|---|---|---|---|---|---|
| 2.1 | 74 | 70 | 84.561.691.505,54 | 81.302.339.014,10 | 75.754.423.202,68 |
| 2.2 | 4 | 4 | 18.976.774.323 | 9.526.762.957 | 9.526.762.957 |
| 2.3 | 327 | 224 | 1.024.227.220.324,22 | 901.628.453.314,84 | 846.578.327.851,09 |

- En 2.3: 101 BPIN con valores; de los 128 BPIN del 2.3, 119 tienen formulación PIIP.
- 63 filas de 2.3 sin BPIN (proyecto 0) con valores, 173.848.360.419,85 de RP.
- 2.1 y 2.2 nunca traen BPIN.

---

## 4. Diseño funcional

### 4.1 Catálogos CHIP

Se cargan desde `Listas_Categoria_CUIPO_09-2026.xlsx` (11 hojas, encabezado en la fila 1;
**el archivo todavía no está en el repositorio**).

Clase abstracta base: `codigo` (CharField único), `descripcion`, `activo`, FK `version` →
`VersionListas`. Modelos concretos:

| Modelo | Hoja | Particularidades |
|---|---|---|
| `ConceptoCUIPO` | Conceptos por ambito | `nivel` S/D, `habilitado_departamentos` (columna "438 - DEPARTAMENTOS"), `requiere_cpc` |
| (sin modelo) | Conceptos_CPC | Solo marca `requiere_cpc=True`; se procesa después de Conceptos |
| `FuenteCUIPO` | Fuentes de Financiación | |
| `SeccionPresupuestal` | Secciones Presupuestales | Solo columnas A:B (hay una nota suelta en la D) |
| `VigenciaGasto` | Vigencia Gasto | |
| `ProductoMGA`* | Producto MGA | `aplica_territoriales`; el importador crea además `0 - NO APLICA` |
| `CPC` | CPC | Longitud 1, 5 o 7 |
| `DetalleSectorial` | Detalle Sectorial | |
| `SituacionFondos` | Situación de Fondos | |
| `PoliticaPublica` | Politica Pública | |
| `Tercero`* | Tercero | |

\* Chocan de nombre con `siifweb.ProductoMGA` y `siifweb.Tercero`. Django lo permite en otra
app, pero confunde en el admin, los imports y los mensajes. Propuesta: sufijo `CUIPO`
(`ProductoCUIPO`, `TerceroCUIPO`) o en todos (`CPCCUIPO`...). Decisión pendiente.

`VersionListas`: nombre ("09-2026"), archivo, fecha y usuario de carga.

Importación: `manage.py importar_listas_cuipo <archivo> --version 09-2026` y, como en
producción no hay consola, también una acción del admin sobre `VersionListas`; las dos
llaman a la misma función (por ejemplo `cuipo/listas.py`).
- `update_or_create` por código; lo que no viene en la versión nueva queda `activo=False`,
  nunca se borra; todo en un `transaction.atomic()`.
- **Todo código se lee como texto** y se conserva exacto: `01111`, `0101004`, `16.0`. En CPC
  hay 7.098 códigos guardados como número en el Excel (Vigencia Gasto y Política Pública
  también traen números): si Excel ya perdió el cero inicial, leerlo como texto no lo
  recupera; la longitud válida del CPC (1, 5, 7) permite rellenar con `zfill`. Las secciones
  se leen con el formato de la celda, no como `float`.
- No es una migración de datos: las migraciones solo crean esquema. En consecuencia, las
  pruebas arman un libro de listas mínimo en memoria.

### 4.2 Homologaciones y reglas

Tablas propias; los modelos de `siifweb` no se modifican.

| Modelo | Contenido | Si falta |
|---|---|---|
| `HomologacionFuente` | FK a `siifweb.Fuente`, FK `FuenteCUIPO`, `vigencia`, `observacion`, `validado_por`, `fecha_validacion`; `UniqueConstraint(fuente_siifweb, vigencia)` | Bloquea |
| `HomologacionRubro` | Solo excepciones (ej. 2.3.3.05.09.054 → 2.3.3.05.09.099) | Se usa el mismo código si existe en `ConceptoCUIPO` y está habilitado para departamentos; si no, bloquea |
| `ReglaSeccion` | Centro de costo → sección (2 → 22.0 Educación, 3 → 21.0 Salud) | 16.0 |
| `ReglaTercero` | Por rubro (ICBF 23900000, SENA 26800000, ESAP 22000000, MEN 11300000) o por centro de costo (Inder 128470000, Fondo Mixto 220170001, Aguas de Sucre 923272066, Unisucre 128870000) | Pendiente |
| `ReglaSituacionFondos` | Prefijo de rubro + fuente CUIPO → S o C (ej. 2.3.1.01.02.001–003 con 1.2.4.1.01 → S) | — |

- `HomologacionFuente`: 62 recursos SIIFWEB → 28 fuentes CUIPO (muchos a uno). 20 recursos
  tienen en el nombre un código que no es su fuente correcta: no se deduce del nombre.
  Admin: `TabularInline` dentro del admin de `FuenteCUIPO`, con `autocomplete_fields` para la
  fuente SIIFWEB (no `filter_horizontal`: falla con M2M con `through`, admin.E013).
- **Cómo se cruza con la fila de ejecución:** la fila trae el recurso como texto; la fuente
  SIIFWEB se obtiene con `Fuente.objects.get(codigo=fila.recurso)`. Si el recurso todavía no
  existe en `siifweb.Fuente` (aparece en el reporte antes de cargar los consolidados), queda
  como pendiente. En el corte de 2026 al 11/11 solo pasó con el recurso 130 (la base local
  tiene los consolidados al 22/10). La regla práctica: cargar los consolidados antes de
  distribuir.
- La sección sale del centro de costo **de la fila de ejecución**.
- Conviene una vista de "pendientes": los recursos, rubros y centros de costo de un corte que
  no tienen homologación o regla.

### 4.3 Distribución por producto

**Modelos**
- `DistribucionBPIN`: **corte** (FK a `CorteEjecucionGastos`), periodo (ej. 10909), BPIN,
  vigencia de gasto, regla aplicada, estado (borrador → en validación → validado →
  enviado), `validado_por`.
- `AsociacionFuenteProducto`: distribución, **FK a `FilaEjecucionGastos`**, producto.
- `LineaCUIPO`: distribución, **FK a `FilaEjecucionGastos`** (`PROTECT`), producto; C, O y P
  en `DecimalField(…, decimal_places=2)`; CPC, detalle sectorial, tercero y política pública;
  `origen_valores` (SIIFWEB / PIIP / MANUAL) y un `origen_*` por cualitativo (regla /
  antecedente / PAS / manual). Única por (distribución, fila, producto).
- Rubro, fuente CUIPO, sección y situación de fondos **no** se guardan en `LineaCUIPO`: se
  derivan de la fila con las homologaciones.
- La FK va al id de la fila y no a rubro + recurso + centro de costo porque esa combinación
  se repite entre árboles de rubros (sección 3). Dentro de un mismo corte de 2026 no se
  repite: el BPIN 2023002700021 tiene la combinación rubro / 7 / 16 en 2023, 2024 y 2026,
  cada una con su `RUBRO_ID`.

**El corte y el periodo.** El periodo CUIPO es trimestral y acumulado: el corte de una
distribución debe ir del 1 de enero al último día del trimestre del periodo. La distribución
apunta al corte; así el CUIPO de septiembre se regenera aunque después se cargue octubre.

**Qué filas entran (vigencia de gasto 1):** las del corte con `de_otra_vigencia=False`,
rubro 2.3, BPIN distinto de 0 y algún valor distinto de cero. Las de otra vigencia y las de
2.3 sin BPIN quedan pendientes de decisión (sección 7).

**Reproceso de un corte con distribución.** Hoy `ejecucion.importar()` borra y vuelve a
crear las filas del corte; con `LineaCUIPO` apuntando a ellas con `PROTECT`, el borrado
fallaría. Propuesta: si el corte ya tiene distribución, `procesar` lo rechaza con un mensaje
claro, y para actualizar se carga un corte nuevo.

**Precarga automática por BPIN** (las reglas del Power Query):
- 1 producto: el 100 % de cada fila va a ese producto.
- Más de 1 producto y 1 fuente: según AporteProductos (PIIP).
- Más de 1 producto y más de 1 fuente: manual.

Los productos del BPIN salen de la formulación PIIP (sección 2) y deben existir en el
catálogo CHIP de productos.

**Pantalla por BPIN** (vista propia con HTMX, registrada en `get_urls()` del admin de
`DistribucionBPIN`; `htmx.min.js` como estático propio en `cuipo/static/cuipo/`, no por CDN):
1. Asociar filas con productos.
2. Matriz filas × productos con C, O y P y la diferencia contra SIIFWEB en vivo. Botones:
   "Según PIIP", "Proporcional a compromisos" (O y P con la participación de C) y "Todo a un
   producto".
3. Cualitativos por línea, mostrando su origen.

**Validaciones** (`validar_distribucion()`, que usan la pantalla y el generador):
- Suma por fila = valor de la fila en C, O y P, al peso.
- Por celda: O ≤ C, P ≤ O, nada negativo.
- El producto pertenece al BPIN.
- CPC vacío → bloquea; CPC 0 en un concepto con `requiere_cpc` → solo advertencia (CHIP lo
  aceptó).
- Código de catálogo inactivo → bloquea.

**Reservas (vigencia de gasto 2).** El diseño original las toma del consolidado de reservas,
pero este no tiene centro de costo (sin él no hay sección) y se sobrescribe. El reporte de
ejecución de una vigencia no trae las reservas que se ejecutan en ella. Falta definir la
fuente (sección 7).

### 4.4 Plano CHIP

- Texto separado por tabulaciones.
- Encabezado: `S\t117070000\t10909\t2026\tD_EJECUCION_DE_GASTOS`.
- Líneas D de 15 campos: D, CODIGO, VIG, SECCION, PROD, CPC, DETSEC, FUENTE, BPIN, SITFON,
  POLPUB, TERC, C, O, P.
- Valores enteros; se redondea solo al generar, con el método del mayor residuo para que los
  enteros cuadren con el total.
- Líneas resumen por cada nivel de prefijo del código, con los 8 cualitativos vacíos.
- Orden: vigencia → sección → segmentos del rubro.
- Las líneas con igual (VIG, SECCION, CODIGO, PROD, CPC, DETSEC, FUENTE, BPIN, SITFON, POLPUB,
  TERC) se agrupan sumando; las líneas en cero no van.
- Primera fase: solo el detalle 2.3, que reemplaza el 2.3 del plano de presupuesto y conserva
  sin cambios sus líneas 2.1, 2.2 y las demás categorías. Como el corte trae también 2.1 y
  2.2, más adelante se podría generar el formato D completo (pregunta abierta).

### 4.5 Roles

Hacen falta grupos nuevos (por ejemplo Planeación y Presupuesto) para el flujo borrador →
validado → enviado, con una migración de datos como `siifweb/0009`. El menú "CUIPO" hoy solo
lo ven quienes tienen el permiso de ver cortes.

---

## 5. Plan por fases

**Fase 0 — Prerrequisitos de datos**
- Hecho: importador de la ejecución por corte.
- Falta: desplegar las ramas (respaldo previo), cargar en producción el corte
  01/01–30/09/2026 completo, cargar los consolidados al día y definir la fuente de las
  reservas.

**Fase 1 — Catálogos e importador de listas**
- Archivos: `cuipo/models.py` (`VersionListas`, base abstracta, 10 modelos), `cuipo/listas.py`,
  `cuipo/management/commands/importar_listas_cuipo.py`, acción en `cuipo/admin.py`
  (catálogos en solo lectura con búsqueda), migración `cuipo/0002`.
- Aceptación:
  - Importar dos veces el mismo archivo da los mismos conteos.
  - Un código que no viene en la versión nueva queda inactivo, no se borra.
  - `01111`, `0101004` y `16.0` quedan exactos; el CPC solo admite longitud 1, 5 o 7.
  - Existe el producto `0 - NO APLICA`; Conceptos_CPC marca `requiere_cpc`.
  - Si falla una hoja, no queda nada a medias.

**Fase 2 — Homologaciones, reglas y admin**
- Archivos: los 5 modelos de la sección 4.2, `cuipo/derivacion.py` con `derivar(fila)`, admin
  (inline de `HomologacionFuente` en `FuenteCUIPO`), vista de pendientes, migración.
- Aceptación:
  - `UniqueConstraint(fuente_siifweb, vigencia)` funciona.
  - `derivar(fila)` devuelve concepto, fuente CUIPO, sección, situación de fondos y tercero,
    o la lista de lo que falta.
  - Con el corte de 2026, la vista de pendientes lista lo que no está homologado.
  - Casos mínimos: recursos 3, 7, 114, 159, 35, 54 y 125; centros de costo 2, 3, 16 y 19.

**Fase 3 — Distribución y precarga**
- Archivos: `DistribucionBPIN`, `AsociacionFuenteProducto`, `LineaCUIPO`,
  `cuipo/distribucion.py` (las tres reglas de precarga), el bloqueo de reproceso en
  `cuipo/ejecucion.py`, migración.
- Aceptación:
  - La suma de las líneas de cada fila da su C, O y P.
  - Un corte con distribución no se reprocesa y lo dice.
  - Los tres casos de la sección 6 dan la regla esperada.

**Fase 4 — Pantalla HTMX**
- Archivos: vistas en `get_urls()` del admin de `DistribucionBPIN`, `cuipo/templates/cuipo/`
  (pantalla y parciales), `cuipo/static/cuipo/htmx.min.js`.
- Aceptación:
  - La matriz recalcula la diferencia contra SIIFWEB sin recargar.
  - Los tres botones dan los valores esperados en los tres BPIN de prueba.
  - Los cualitativos muestran su origen; un rol sin permiso recibe 403.

**Fase 5 — Validaciones**
- Archivo: `cuipo/validacion.py` con `validar_distribucion()`.
- Aceptación: cada regla de la sección 4.3 tiene su prueba; en 202500000029628, recurso 35,
  ninguna celda deja O > C.

**Fase 6 — Generador del plano**
- Archivos: `cuipo/plano.py` y una vista o acción de descarga.
- Aceptación:
  - Encabezado exacto, 15 campos por línea D, líneas resumen con los cualitativos vacíos.
  - Orden y agrupación según la sección 4.4; sin líneas en cero.
  - El redondeo por mayor residuo cuadra con el total (se prueba con 202500000029628, que
    tiene centavos).
  - Al integrarse en el plano de presupuesto, las líneas 2.1 y 2.2 salen idénticas.

**Fase 7 — Pruebas**
- Pasar `fila()`, `libro()` y `cortar()` de `cuipo/tests/test_ejecucion_gastos.py` a
  `cuipo/tests/fabricas.py`; agregar un libro de listas mínimo y un plano esperado (golden
  file) de 202500000039332.

---

## 6. Casos de prueba

Cifras del corte 01/01–11/11/2026 (base local). Se recalculan con el corte al 30/09 cuando
esté cargado. Todas las filas son del rubro indicado y del árbol de 2026.

**202500000039332** — una fila, productos 2201006 y 2201048, regla "Según PIIP".

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.02.02.009 | 3 | 2 | 1.084.750.996 | 834.182.726 |

Al 30/09 el RP era 1.054.759.012 (del consolidado de compromisos filtrado por fecha).

**2023002700021** — tres filas, productos 1906005 y 1906030, manual. Dos secciones en el
mismo BPIN (centros de costo 16 y 3).

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.01.01.001.02.08 | 7 | 16 | 6.016.089.072,27 | 6.015.697.203,50 |
| 2.3.2.01.01.001.02.08 | 114 | 3 | 1.027.664.538,50 | 1.014.627.682,00 |
| 2.3.2.01.01.001.02.08 | 159 | 3 | 4.949.736.116,45 | 0 |

La fila del recurso 159 se registró después del 30/09: no estará en el corte de septiembre.

**202500000029628** — tres recursos, centro de costo 19, productos 4502034 y 4502038, manual.

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.02.02.009 | 35 | 19 | 2.979.309.905 | 2.010.861.681,15 |
| 2.3.2.02.02.009 | 54 | 19 | 1.000.000.000 | 1.000.000.000 |
| 2.3.2.02.02.009 | 125 | 19 | 425.784.947 | 314.670.429,87 |

---

## 7. Preguntas abiertas (de más a menos bloqueante)

1. **Archivo de listas.** Falta `Listas_Categoria_CUIPO_09-2026.xlsx` en el repositorio;
   sin él no se prueba la fase 1.
2. **Nombres de modelos.** ¿Sufijo `CUIPO` para no chocar con `siifweb.ProductoMGA` y
   `siifweb.Tercero`?
3. **Roles y flujo.** ¿Quién distribuye, quién valida y quién marca "enviado"? ¿Una
   distribución validada puede volver a borrador?
4. **AporteProductos.** ¿De qué exporte del PIIP sale el valor por producto para la regla
   "Según PIIP", con qué columnas y para qué vigencia?
5. **Inversión sin BPIN.** En 2026 hay 63 filas de 2.3 con proyecto 0 (173.848 M de RP):
   ¿van al CUIPO, con qué BPIN y con qué producto (¿0 - NO APLICA?)?
6. **BPIN sin formulación PIIP** (9 de 128 en 2026): ¿se asignan productos a mano sin
   validar que pertenezcan al BPIN?
7. **Reproceso de un corte con distribución.** ¿Se bloquea (propuesto) o se actualizan las
   filas por su llave?
8. **Reservas (vigencia de gasto 2).** ¿SIIFWEB tiene un reporte de ejecución de reservas
   por centro de costo y fondo? El consolidado de reservas no trae centro de costo.
9. **Filas del árbol de otra vigencia** (2023: 27 filas, 22 con BPIN, obligación 16.890 M):
   ¿qué son (reservas, cuentas por pagar) y van al CUIPO?
10. **Alcance del plano.** ¿Solo el 2.3 dentro del plano de presupuesto, o el formato D
    completo desde el corte?
11. **Periodo.** Confirmar la codificación (`10909` = julio a septiembre) y si una
    distribución se puede copiar al trimestre siguiente como punto de partida.
12. **Rama `centro-costo-compromisos`.** ¿Se conserva (corrige el centro de costo de los RP
    con varias líneas) o se descarta?
