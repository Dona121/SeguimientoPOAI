# Plan del módulo CUIPO (ejecución de gastos de inversión por producto MGA)

Documento autocontenido, redactado el 13 de noviembre de 2026 y actualizado el mismo día con
las decisiones tomadas al revisarlo contra los datos del CUIPO del tercer trimestre. Reúne el
diseño funcional, lo que ya existe en el aplicativo, los ajustes que salieron de revisar los
datos reales y el plan por fases. Sirve para continuar el trabajo en otra conversación sin el
historial.

**Quién lo construye.** Desde el 13 de noviembre lo implementa el asistente por fases, a
pedido de Donaldo (Secretaría de Planeación, Gobernación de Sucre), que revisa cada fase. El
importador del reporte de ejecución ya está hecho (sección 3).

---

## 0. Decisiones tomadas (13 de noviembre de 2026)

| Tema | Decisión |
|---|---|
| Alcance | Solo la categoría `D_EJECUCION_DE_GASTOS` y solo **vigencia actual**. Las reservas no se trabajan en el aplicativo |
| Vigencia de gasto | **Editable en la distribución** (decisión del 13/11): por defecto 1 (vigencia actual), y se puede elegir una o varias por fila, por ejemplo 1 y 4 (vigencias futuras - vigencia actual). En el CUIPO de junio 28 de 225 líneas de inversión fueron con 4 |
| Periodo | El tercer trimestre es 10909 y el cuarto 11212. Los valores son **el acumulado de la vigencia hasta el último día del trimestre** (aunque CHIP rotule el 10909 como "01-09-2026 al 30-09-2026") |
| Alcance del plano | Solo el detalle 2.3 del bloque `D_EJECUCION_DE_GASTOS` |
| Trimestres anteriores | No se copia una distribución de un trimestre al siguiente (puede cambiar). La pantalla muestra, como referencia, cómo se distribuyó el BPIN en los trimestres anteriores |
| Validación contra programación | No va en el aplicativo: el reporte de programación se usa como referencia externa antes del envío |
| Listas CHIP | Se construyen los modelos de parametrización desde `modelos-metas/Listas_Categoria_CUIPO_09-2026.xlsx` |
| Nombres | Sufijo `CUIPO` solo en los dos modelos que chocan con `siifweb`: `ProductoCUIPO` y `TerceroCUIPO`. Los demás sin sufijo |
| Cortes con distribución | No se pueden reprocesar ni borrar. Para actualizar, se carga un corte nuevo y se distribuye sobre él |
| Valores por producto (PIIP) | El reporte de AporteProductos del PIIP **no se carga** al aplicativo: los valores por producto se digitan a mano en la matriz a partir de ese reporte |
| Inversión sin BPIN | Entra al CUIPO con BPIN 0 y producto 0, el 100 % automático; solo se diligencian los cualitativos |
| Roles | Por ahora sin roles nuevos: quien tenga los permisos de los modelos del CUIPO puede distribuir y validar |
| Reparto | **Manual** (decisión del 13/11): sin los botones "Proporcional a compromisos" ni "Todo a un producto", porque pueden generar confusión o errores. La precarga sigue haciendo el 100 % cuando hay un solo producto y en la inversión sin BPIN |
| 2023002700021 | La fila de 15.251.706.362,76 (recurso 7, centro de costo 16) que aparecía duplicada en la ejecución al 30/09 se había agregado a mano. En el reporte oficial la llave de la fila es única |

---

## 1. Objetivo

Generar el reporte CUIPO de CHIP (Contaduría General), categoría `D_EJECUCION_DE_GASTOS`,
para la inversión (rubros 2.3), abierto por producto MGA, en vigencia actual. Hasta ahora se
armaba en Excel con Power Query y scripts de Python.

El flujo es:

1. Cargar el reporte de ejecución de gastos de SIIFWEB de un corte (ya existe).
2. Derivar de cada fila el concepto, la fuente CUIPO, la sección, la situación de fondos y
   el tercero, con homologaciones y reglas.
3. Distribuir cada fila de cada BPIN entre los productos del proyecto (precarga automática
   y ajuste o digitación en pantalla).
4. Validar la distribución.
5. Generar el bloque `D_EJECUCION_DE_GASTOS` del plano de texto que se sube a CHIP.

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
  disco temporal). Hoy son 541.
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
- Roles existentes: grupos `Consulta` y `Seguimiento` (migración `siifweb/0009`). Para el
  CUIPO no se crean roles nuevos por ahora (sección 4.5).
- Algunos archivos de `siifweb` tienen fin de línea CRLF (`models.py`, `admin.py`,
  `cargas.py`, `config/settings.py`): al editarlos, conservarlo.

**Datos de `siifweb` que usa el CUIPO**
- `Fuente(codigo, nombre)`: el código es el número de recurso de SIIFWEB (3, 7, 114...).
- `Rubro(codigo, nombre)`, `CentroCosto(codigo, nombre)`, `Proyecto(bpin)`.
- Estos catálogos los crean las cargas de los consolidados (CDP, compromisos, obligaciones).
  Un código que aparece en el reporte de ejecución antes de cargar los consolidados no
  existe todavía en ellos.
- **Productos por BPIN (PIIP):** `FormulacionProyecto` (con su propio `bpin`, único, y
  enlace opcional uno a uno con `Proyecto`, `related_name="formulacion"`) →
  `IndicadorProyecto` (`formulacion.indicadores`) → `IndicadorCatalogo`
  (`related_name="en_proyectos"` desde `IndicadorProyecto`) → `ProductoCatalogo` (código de 7
  dígitos). Los productos de un BPIN:
  `ProductoCatalogo.objects.filter(indicadores__en_proyectos__formulacion__bpin=bpin).distinct()`.
  Se llenan con la carga "Información general PIIP" (tabla `InfoGeneral`). Esto da **qué**
  productos tiene el BPIN, no cuánto vale cada uno.
- Desde la rama `piip-control-siifweb` la carga del PIIP crea la formulación de **todos** los
  BPIN del PIIP, estén o no en SIIFWEB, y el enlace con el proyecto se hace solo, por BPIN, en
  cualquier orden (detalle en `CATALOGO_PIIP.md`, sección 9). Ya no hace falta reprocesar el
  PIIP después de cargar los consolidados.
- Nombres que ya existen en `siifweb`: `ProductoMGA` (catálogo del plan de desarrollo) y
  `Tercero` (contratistas). Por eso los catálogos CHIP equivalentes llevan sufijo `CUIPO`.

**Ramas (ninguna subida a `main`)**

```
main ← formulacion-piip ← cuipo-ejecucion-gastos ← piip-control-siifweb
```

- `formulacion-piip`: catálogo PIIP y formulación de los proyectos (productos por BPIN).
  Migraciones `siifweb/0020` y `0021`.
- `cuipo-ejecucion-gastos`: la app `cuipo` con el importador (migración `cuipo/0001`, sin
  dependencias de `siifweb`).
- `piip-control-siifweb`: formulación de todos los BPIN del PIIP con semáforo de SIIFWEB
  (migración `siifweb/0022`).
- Las fases del CUIPO siguen sobre esta cadena, una rama por fase: `cuipo-fase1-listas`
  (sobre `piip-control-siifweb`) y las siguientes encima.

**Hecho el 13/11 (fase 0):** se descartó la rama `centro-costo-compromisos` (centro de costo
por línea en `CompromisoImputacion`, migración `siifweb/0022` de entonces): se hizo cuando el
CUIPO se iba a armar desde el consolidado de compromisos, y el reporte oficial ya trae el
centro de costo por fila. Pasos que se siguieron, por si hay que repetir algo parecido:

1. Revisar que ningún código de `cuipo` use el centro de costo de `CompromisoImputacion`.
2. En la base local, revertir `siifweb/0023` y `0022` (`migrate siifweb 0021`) antes de cambiar
   el código. Para revertir la `0023` hay que borrar antes las formulaciones sin proyecto (la
   reversa vuelve obligatorio el proyecto); se recuperan reprocesando el PIIP.
3. Rebasar las dos ramas sobre `formulacion-piip` dejando fuera el commit de
   `centro-costo-compromisos` (`git rebase --onto formulacion-piip centro-costo-compromisos
   piip-control-siifweb` y mover `cuipo-ejecucion-gastos` a su commit equivalente).
4. Renumerar la migración de la formulación como `siifweb/0022`, con dependencia de la `0021`.
5. Aplicar migraciones en local, reprocesar el PIIP, correr las pruebas y borrar la rama
   `centro-costo-compromisos`.

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
  costo + proyecto se repite en 2023 y `RUBRO_ID` tiene que ir en la llave. Las filas del
  árbol de otra vigencia no entran al CUIPO (solo vigencia actual).
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
- **Cambio pendiente (fase 3):** si el corte ya tiene distribuciones, `procesar` lo rechaza
  con un mensaje claro y el corte no se puede borrar (sección 4.3).

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
  de la estructura): **no se puede importar**. La versión de 34 columnas con la que se armó el
  CUIPO del T3 (con metas, programa MGA y número de distribuciones agregados) tampoco: no es el
  reporte oficial y trae la fila agregada a mano de 2023002700021. Falta descargar el corte
  oficial 01/01–30/09/2026 completo.

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

- En 2.3: 101 BPIN con valores, los 101 con formulación PIIP; de los 128 BPIN del 2.3, 127
  tienen formulación (con la carga de todos los BPIN del PIIP).
- 63 filas de 2.3 sin BPIN (proyecto 0) con valores, 173.848.360.419,85 de RP.
- 2.1 y 2.2 nunca traen BPIN.

---

## 4. Diseño funcional

### 4.1 Catálogos CHIP

**Fuente:** `modelos-metas/Listas_Categoria_CUIPO_09-2026.xlsx` (11 hojas, encabezado en la
fila 1). Desde este archivo se construyen los modelos de parametrización del CUIPO y se prueba
el importador de la fase 1.

Clase abstracta base: `codigo` (CharField único), `descripcion`, `activo`, FK `version` →
`VersionListas`. Modelos concretos:

| Modelo | Hoja | Particularidades |
|---|---|---|
| `ConceptoCUIPO` | Conceptos por ambito | `nivel` S/D, `habilitado_departamentos` (columna "438 - DEPARTAMENTOS"), `requiere_cpc` |
| (sin modelo) | Conceptos_CPC | Solo marca `requiere_cpc=True`; se procesa después de Conceptos |
| `FuenteCUIPO` | Fuentes de Financiación | |
| `SeccionPresupuestal` | Secciones Presupuestales | Solo columnas A:B (hay una nota suelta en la D) |
| `VigenciaGasto` | Vigencia Gasto | Se carga completa aunque el aplicativo solo use la 1 |
| `ProductoCUIPO` | Producto MGA | `aplica_territoriales`; el importador crea además `0 - NO APLICA` |
| `CPC` | CPC | Longitud 1, 5 o 7 |
| `DetalleSectorial` | Detalle Sectorial | |
| `SituacionFondos` | Situación de Fondos | |
| `PoliticaPublica` | Politica Pública | |
| `TerceroCUIPO` | Tercero | |

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
| `ReglaTercero` | Por rubro (ICBF 23900000, SENA 26800000, ESAP 22000000, MEN 11300000) o por centro de costo, **por código** (11 Inder 128470000, 10 Fondo Mixto 220170001, 5 Aguas de Sucre 923272066, 25 Universidad de Sucre 128870000) | `1 - NO APLICA` (ajustado en la fase 2: así van 184 de las 225 líneas de inversión del CUIPO de junio) |
| `ReglaSituacionFondos` | Prefijo de rubro + fuente CUIPO → S o C (ej. 2.3.1.01.02.001–003 con 1.2.4.1.01 → S) | — |

- `HomologacionFuente`: 62 recursos SIIFWEB → 28 fuentes CUIPO (muchos a uno). 20 recursos
  tienen en el nombre un código que no es su fuente correcta: no se deduce del nombre.
  Admin: `TabularInline` dentro del admin de `FuenteCUIPO`, con `autocomplete_fields` para la
  fuente SIIFWEB (no `filter_horizontal`: falla con M2M con `through`, admin.E013).
- **Cómo se cruza con la fila de ejecución:** la fila trae el recurso como texto; la fuente
  SIIFWEB se obtiene con `Fuente.objects.get(codigo=fila.recurso)`. Si el recurso todavía no
  existe en `siifweb.Fuente` (aparece en el reporte antes de cargar los consolidados), queda
  como pendiente. Con los consolidados al 22/10 pasó con el recurso 130; con los del 11/11 ya
  no hay ninguno. La regla práctica: cargar los consolidados antes de distribuir.
- La sección sale del centro de costo **de la fila de ejecución**.
- Conviene una vista de "pendientes": los recursos, rubros y centros de costo de un corte que
  no tienen homologación o regla, y los BPIN con ejecución sin formulación PIIP (con el aviso
  "el BPIN no está en la carga del PIIP: actualizar el exporte del PIIP y cargarlo").
- En los scripts del T3 la regla de tercero por centro de costo se hacía por el nombre
  (`NOMBRE_CENTROCOSTO`); en el aplicativo va por el código del centro de costo.

### 4.3 Distribución por producto

**Modelos**
- `DistribucionBPIN`: **corte** (FK a `CorteEjecucionGastos`, `on_delete=PROTECT`), periodo
  (ej. 10909), BPIN (`0` para la inversión sin proyecto), regla aplicada, estado (borrador →
  validado → enviado), `validado_por`.
- `AsociacionFuenteProducto`: distribución, **FK a `FilaEjecucionGastos`**, producto.
- `LineaCUIPO`: distribución, **FK a `FilaEjecucionGastos`** (`PROTECT`), producto,
  **vigencia de gasto** (FK a `VigenciaGasto`, por defecto 1); C, O y P en
  `DecimalField(…, decimal_places=2)`; CPC, detalle sectorial, tercero y política pública;
  `origen_valores` (SIIFWEB / PIIP / MANUAL) y un `origen_*` por cualitativo (regla /
  antecedente / PAS / manual). Única por (distribución, fila, producto, vigencia de gasto):
  una fila puede repartirse entre varias vigencias de gasto (por ejemplo 1 y 4) y la suma de
  sus líneas sigue debiendo dar el valor de la fila.
- Rubro, fuente CUIPO, sección y situación de fondos **no** se guardan en `LineaCUIPO`: se
  derivan de la fila con las homologaciones.
- La FK va al id de la fila y no a rubro + recurso + centro de costo porque esa combinación
  se repite entre árboles de rubros (sección 3). Dentro de un mismo corte oficial no se
  repite.

**El corte y el periodo.** El periodo es trimestral (tercer trimestre 10909, cuarto 11212) y
sus valores son el acumulado de la vigencia hasta el último día del trimestre: el corte de una
distribución va del 1 de enero al último día del trimestre del periodo. La distribución apunta
al corte; así el CUIPO de septiembre se regenera aunque después se cargue octubre.

**Trimestres anteriores.** No se copia la distribución de un trimestre al siguiente. En la
pantalla del BPIN se muestra, solo como referencia, la distribución por producto del mismo
BPIN en los periodos anteriores de la vigencia (valor y participación de cada producto), tomada
de su `DistribucionBPIN` más reciente en estado enviado.

**Qué filas entran:** las del corte con `de_otra_vigencia=False`, rubro 2.3 y `rp`,
`obligacion` o `pago` distinto de cero. **No** basta con "algún valor distinto de cero": en
2023002700021 el recurso 159 tenía al 30/09 una adición de 4.949.736.116,45 con RP en cero, y
no debe entrar.
- Con BPIN: se distribuyen entre los productos del proyecto.
- Sin BPIN (proyecto 0): una distribución con BPIN 0 y producto `0 - NO APLICA`, el 100 %
  automático; solo se diligencian los cualitativos. Así lo hace hoy presupuesto: el plano que
  aceptó CHIP en el T3 trae 34 líneas de 2.3 con BPIN 0 y producto 0, por 75.195.347.557 de
  compromisos (algunas con tercero o CPC).

**Cortes con distribución: ni reprocesar ni borrar.** Hoy `ejecucion.importar()` borra y
vuelve a crear las filas del corte. Si el corte ya tiene distribuciones:
- `procesar` lo rechaza con un mensaje claro;
- el admin no permite eliminarlo (`has_delete_permission`) y la FK `PROTECT` de
  `DistribucionBPIN` impide borrarlo por fuera del admin;
- para actualizar, se carga un corte nuevo y se distribuye sobre él.

**Precarga automática por BPIN:**
- 1 producto: el 100 % de cada fila va a ese producto (`origen_valores` = SIIFWEB).
- Más de 1 producto y 1 fuente: la matriz queda vacía y en estado "pendiente de digitar".
  Los valores por producto se digitan a mano desde el reporte de AporteProductos del PIIP, que
  no se carga al aplicativo (`origen_valores` = PIIP).
- Más de 1 producto y más de 1 fuente: manual (`origen_valores` = MANUAL).
- Sin BPIN: el 100 % al producto 0.

Los productos del BPIN salen de la formulación PIIP (sección 2) y deben existir en el
catálogo CHIP de productos. La carga del PIIP crea la formulación de todos los BPIN del PIIP,
así que un BPIN con ejecución solo queda sin productos si no está en el exporte del PIIP. Al
11/11/2026 los 101 BPIN de 2.3 con ejecución tienen formulación; el único del 2.3 sin ella
(2024002700177) está en cero y no está en el PIIP.

**Pantalla por BPIN** (vista propia con HTMX, registrada en `get_urls()` del admin de
`DistribucionBPIN`; `htmx.min.js` como estático propio en `cuipo/static/cuipo/`, no por CDN):
1. Asociar filas con productos.
2. Matriz filas × productos con C, O y P y la diferencia contra SIIFWEB en vivo. Los valores
   se digitan a mano (los del PIIP, directamente en las celdas); no hay botones de reparto
   automático (decisión del 13/11).
3. Cualitativos por línea, mostrando su origen.

**Validaciones** (`validar_distribucion()`, que usan la pantalla y el generador):
- Suma por fila = valor de la fila en C, O y P, al peso.
- Por celda: O ≤ C, P ≤ O, nada negativo.
- El producto pertenece al BPIN (salvo el producto 0 en la inversión sin BPIN).
- CPC vacío → bloquea; CPC 0 en un concepto con `requiere_cpc` → solo advertencia (CHIP lo
  aceptó en el T3 en los viáticos 2.1.2.02.02.010 y 2.3.2.02.02.010).
- Código de catálogo inactivo → bloquea.

### 4.4 Plano CHIP

**Estructura del archivo de presupuesto.** Es un solo archivo de texto con cinco categorías;
cada una empieza con su línea `S` y le siguen sus líneas de detalle. En el plano del T3:

| Orden | Encabezado | Líneas de detalle | Campos |
|---|---|---|---|
| 1 | `S	117070000	10909	2026	E_ID_SECCIONES_PRESUPUESTALES_ADICIONALES` | 1 | 4 |
| 2 | `S	117070000	10909	2026	D_EJECUCION_DE_GASTOS` | 580 | 15 |
| 3 | `S	117070000	10909	2026	C_PROGRAMACION_DE_GASTOS` | 421 | 9 |
| 4 | `S	117070000	10909	2026	B_EJECUCION_DE_INGRESOS` | 182 | 14 |
| 5 | `S	117070000	10909	2026	A_PROGRAMACION_DE_INGRESOS` | 125 | 5 |

La `D` al inicio de una línea de detalle **no** significa "ejecución de gastos": es la marca
de registro de detalle y la usan las cinco categorías (la programación tiene, por ejemplo,
líneas `D 2.1…` y `D 2.99…`). Por eso todo lo que haga el aplicativo sobre el archivo opera
**dentro del bloque** que va de la línea `S…D_EJECUCION_DE_GASTOS` a la siguiente línea `S`,
nunca buscando "líneas que empiezan por D" en todo el archivo.

**Formato del bloque D**
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

**Alcance:** el aplicativo genera solo el detalle 2.3. Al integrarlo en el plano de
presupuesto, dentro del bloque D reemplaza su detalle 2.3, conserva sin cambios sus líneas
2.1 y 2.2, recalcula las líneas resumen del bloque (2, 2.3 y los niveles intermedios) y deja
idénticas las demás categorías.

**Revisión externa antes del envío:** el reporte de programación de gastos se usa como
referencia por fuera del aplicativo (no se carga) para revisar que la ejecución de cada BPIN y
sección no supere su programación. Así salieron en el T3 las correcciones de 2023002700172 y
202600000015853.

### 4.5 Roles

Por ahora no se crean roles nuevos. Quien tenga los permisos de los modelos del CUIPO puede
distribuir, validar y marcar como enviado; `validado_por` registra quién validó. Si más
adelante se separan planeación y presupuesto, se crean los grupos con una migración de datos
como `siifweb/0009`. El menú "CUIPO" hoy solo lo ven quienes tienen el permiso de ver cortes.

---

## 5. Plan por fases

**Fase 0 — Prerrequisitos de datos**
- Hecho: importador de la ejecución por corte; archivo de listas CHIP en
  `modelos-metas/Listas_Categoria_CUIPO_09-2026.xlsx`.
- Hecho en local (13/11): consolidados de 2026 al 11/11 cargados y carga del PIIP (id 209)
  reprocesada con todos los BPIN: 488 formulaciones; los 101 BPIN de 2.3 con ejecución tienen
  productos. Respaldo previo: `db_antes_consolidados_1111.sqlite3`.
- Hecho (13/11): descartada la rama `centro-costo-compromisos` y renumerada la migración de
  la formulación como `siifweb/0022` (sección 2). Respaldo previo de la base local:
  `db_antes_fase0.sqlite3`.
- Falta: desplegar `formulacion-piip`, `cuipo-ejecucion-gastos` y `piip-control-siifweb`
  (respaldo previo de Supabase) y descargar el corte oficial 01/01–30/09/2026 completo.
- **Rutina en cada trimestre, antes de distribuir:**
  1. Cargar el corte de ejecución del trimestre.
  2. Cargar los consolidados al día (CDP, compromisos, obligaciones), para que existan los
     recursos y proyectos nuevos.
  3. Si hay un exporte nuevo del PIIP, cargarlo (el orden frente a los consolidados ya no
     importa).
  4. Revisar la vista de pendientes y distribuir.

**Fase 1 — Catálogos e importador de listas** — **hecha el 13/11** (rama
`cuipo-fase1-listas`, migración `cuipo/0002`, 20 pruebas en `cuipo/tests/test_listas.py`).
Importada en local la versión 09-2026: 3.075 conceptos (79 con CPC), 231 fuentes, 30
secciones, 6 vigencias del gasto, 5.072 productos (con el 0), 7.659 CPC, 167 detalles
sectoriales, 2 situaciones de fondos, 87 políticas públicas y 5.736 terceros; importarla de
nuevo no cambia nada. Ajustes frente a lo previsto:
- `ProductoCUIPO.aplica_territoriales` es texto, no booleano: la columna "Aplica a Entidades
  Territoriales" viene vacía en 5.067 productos y dice "Nuevo" en 4. Se guarda como viene.
- Se guardan también `notas` del concepto, `sector` y `programa` del producto, `seccion` y
  `division` del CPC, y `grupo` y `sector` del detalle sectorial.
- `version` de cada código es la **última versión que lo trajo**; `VersionListas` guarda
  además estado, mensaje y hash, y no se puede borrar mientras algún código la cite.
- El comando no sube el archivo al almacenamiento (en local es el bucket de producción); la
  versión creada por comando queda sin archivo. Desde el admin sí se guarda.
- Los CPC numéricos del archivo real ya tienen 5 o 7 dígitos; el relleno con ceros (4 → 5,
  6 → 7) queda para versiones futuras.
- Menú: "Versiones de las listas CHIP" en la sección CUIPO y una sección nueva "Listas CHIP"
  con los diez catálogos, en solo lectura (no se agregan, editan ni borran a mano).

- Archivos: `cuipo/models.py` (`VersionListas`, base abstracta, 10 modelos con
  `ProductoCUIPO` y `TerceroCUIPO`), `cuipo/listas.py`,
  `cuipo/management/commands/importar_listas_cuipo.py`, acción en `cuipo/admin.py`
  (catálogos en solo lectura con búsqueda), migración `cuipo/0002`.
- Insumo: `modelos-metas/Listas_Categoria_CUIPO_09-2026.xlsx`.
- Aceptación:
  - Importar dos veces el mismo archivo da los mismos conteos.
  - Un código que no viene en la versión nueva queda inactivo, no se borra.
  - `01111`, `0101004` y `16.0` quedan exactos; el CPC solo admite longitud 1, 5 o 7.
  - Existe el producto `0 - NO APLICA`; Conceptos_CPC marca `requiere_cpc`.
  - Si falla una hoja, no queda nada a medias.

**Fase 2 — Homologaciones, reglas y admin** — **hecha el 13/11** (rama `cuipo-fase2-reglas`,
migración `cuipo/0003`, 24 pruebas en `cuipo/tests/test_derivacion.py`).
- Modelos: `HomologacionFuente` (FK a `siifweb.Fuente`, por vigencia), `HomologacionRubro` y
  `ReglaTercero` (FK a `siifweb.Rubro`), `ReglaSeccion` y `ReglaTercero` (FK a
  `siifweb.CentroCosto`), `ReglaSituacionFondos` (prefijo de rubro como texto + fuente CUIPO
  opcional; gana el prefijo más largo y, a igual prefijo, la que nombra la fuente). La fila se
  cruza con ellos por código.
- `cuipo/derivacion.py`: `filas_cuipo(corte)` (las filas que entran), `Derivador(vigencia)` /
  `derivar(fila)` (concepto, fuente, sección, situación y tercero, con el origen de cada uno y
  la lista de faltantes), `pendientes(corte)` y `crear_reglas_iniciales()`.
- Pantalla **CUIPO → Pendientes** (`/admin/cuipo/corteejecuciongastos/<id>/pendientes/`, y sin
  id va al último corte procesado): recursos sin homologación (con el código del nombre como
  pista, marcada como no confiable), rubros sin concepto válido, otros faltantes, BPIN con
  ejecución sin formulación PIIP y centros de costo que van a la sección 16.0. Un botón crea
  las reglas iniciales del plan que falten (14), sin tocar las existentes.
- Admin: en cada fuente CUIPO, una tabla para registrar los recursos que la usan (guarda quién
  y cuándo validó); las cinco tablas en el menú CUIPO; el autocompletar solo ofrece códigos
  activos de las listas.
- **Homologaciones del T3:** las 62 de recurso a fuente CUIPO que presupuesto validó para el
  CUIPO del T3 2026 (`modelos-metas/Semillas_CUIPO_T3_2026.xlsx`) están escritas en
  `derivacion.FUENTES_T3_2026` y las crea el botón de las reglas iniciales, una sola vez (lo
  que ya existe no se toca; la del rubro ya estaba entre las reglas iniciales). Primero se hizo
  un importador del libro (`cuipo/semillas.py`, con comando y carga en pendientes); se quitó el
  13/11 porque es una carga de una sola vez.
- En local, con el corte al 11/11, las reglas iniciales y las semillas del T3 (62 recursos y 1
  rubro): de 224 filas, 217 se derivan completas. Faltan 7 recursos que no vienen en las
  semillas: 110, 125, 130, 160, 166, 35 y 91 (una fila cada uno). 202600000018441 deriva
  completo: 2.3.3.05.09.099, 1.3.3.3.20, 16.0, C y 220170001.

- Archivos: los 5 modelos de la sección 4.2, `cuipo/derivacion.py` con `derivar(fila)`, admin
  (inline de `HomologacionFuente` en `FuenteCUIPO`), vista de pendientes, migración.
- Aceptación:
  - `UniqueConstraint(fuente_siifweb, vigencia)` funciona.
  - `derivar(fila)` devuelve concepto, fuente CUIPO, sección, situación de fondos y tercero,
    o la lista de lo que falta.
  - Con el corte de 2026, la vista de pendientes lista lo que no está homologado.
  - Casos mínimos: recursos 3, 7, 114, 159, 35, 54, 108 y 125; centros de costo 2, 3, 10, 16
    y 19.
  - 202600000018441 (sección 6) deriva completo: concepto 099, fuente 1.3.3.3.20, sección
    16.0 y tercero 220170001.

**Fase 3 — Distribución y precarga** — **hecha el 13/11** (rama `cuipo-fase3-distribucion`,
migración `cuipo/0004`, 19 pruebas en `cuipo/tests/test_distribucion.py`).
- Modelos `DistribucionBPIN` (corte PROTECT, periodo, BPIN, regla, estado, productos del BPIN,
  validado por, observación; una por corte y BPIN), `AsociacionFuenteProducto` y `LineaCUIPO`
  (con vigencia de gasto, 1 por defecto; única por distribución, fila, producto y vigencia).
- `periodo_de(corte)`: 10303, 10606, 10909 o 11212 si el corte va del 1 de enero al cierre de
  un trimestre; si no, no hay periodo y la precarga no corre (el corte local al 11/11 no se
  puede distribuir: hace falta el del 30/09).
- `cuipo/distribucion.py`: `precargar(corte)` crea las distribuciones que falten (no toca las
  existentes), `precargar_de_nuevo(distribucion)` (solo borradores) y `cuadre(distribucion)`
  (por fila: SIIFWEB, distribuido y diferencia en C, O y P). Reglas: un producto → 100 %;
  varios productos y un recurso → por digitar desde AporteProductos; varios productos y
  varios recursos → manual; sin BPIN → producto 0; sin productos en la lista CHIP → no se
  distribuye y lo dice. Cualitativos de las líneas nuevas: tercero por regla, CPC 0 si el
  concepto no lo exige (si lo exige queda vacío), detalle sectorial y política pública 0; si
  el BPIN se envió en un periodo anterior de la vigencia, CPC, detalle y política se toman de
  esa línea (origen antecedente). Los valores nunca se copian.
- `ejecucion.procesar` rechaza un corte con distribuciones (`CorteConDistribucion`); el admin
  no deja cambiar su archivo ni borrarlo.
- Admin: acción "Precargar la distribución del CUIPO" en los cortes; **CUIPO → Distribuciones
  por BPIN** con regla, estado, líneas y si cuadra; en cada distribución, el cuadre por fila y
  las líneas editables (lo que se cambia a mano queda con origen manual; validar registra
  quién y cuándo). Es provisional hasta la pantalla de la fase 4.
- Ensayo en local con el corte de 2026 llevado a 30/09 dentro de una transacción revertida:
  102 distribuciones (79 de un producto, 20 por digitar desde el PIIP, 2 manuales, 1 sin
  BPIN); las 80 automáticas cuadran al peso.

- Archivos: `DistribucionBPIN`, `AsociacionFuenteProducto`, `LineaCUIPO`,
  `cuipo/distribucion.py` (las reglas de precarga, incluida la inversión sin BPIN), el bloqueo
  de reproceso en `cuipo/ejecucion.py` y de borrado en `cuipo/admin.py`, migración.
- Aceptación:
  - Solo entran filas de vigencia actual, 2.3, con RP, obligación o pago distinto de cero.
  - La vigencia de gasto de cada línea es 1 por defecto y se puede cambiar; una fila puede
    repartirse entre varias vigencias de gasto.
  - La suma de las líneas de cada fila da su C, O y P.
  - Un corte con distribución no se reprocesa ni se borra, y lo dice.
  - Los casos de la sección 6 dan la regla esperada; los de "varios productos, una fuente"
    quedan pendientes de digitar.

**Fase 4 — Pantalla HTMX** — **hecha el 13/11** (rama `cuipo-fase4-pantalla`, sin migraciones, 19
pruebas en `cuipo/tests/test_pantalla.py`).
- **HTMX:** se usa el que unfold ya carga en todas las páginas del admin (htmx 2.0.4,
  `unfold/js/htmx/htmx.js`); no se copió un `htmx.min.js` propio.
- Pantalla `/admin/cuipo/distribucionbpin/<id>/distribuir/` (enlace "Distribuir" en la lista
  de distribuciones y en cada distribución): encabezado (BPIN, nombre, corte, periodo, regla,
  estado, productos), referencia del periodo anterior enviado (valor y participación por
  producto, solo lectura), totales SIIFWEB / distribuido y filas que cuadran, y la matriz:
  por fila, el rubro, el recurso y el centro de costo con sus nombres completos y lo que
  llevan en el CUIPO (concepto, fuente CUIPO y sección), la casilla de
  cada producto (asociar), lo de SIIFWEB y la diferencia en C, O y P, y una línea por
  producto y vigencia del gasto con C, O y P editables, los cuatro cualitativos por código con
  su descripción y su origen, "+ vigencia" para repartir en otra vigencia del gasto y "×"
  para quitar la línea.
- Cada cambio se guarda al salir de la celda y vuelve solo la fila con su cuadre; los totales
  se actualizan fuera de banda (`hx-swap-oob`). Un error (valor negativo, código que no está
  en la lista, inactivo) se muestra en la fila y no se guarda.
- Lógica en `cuipo/distribucion.py`: `guardar_valor`, `asociar` (desasociar borra las líneas),
  `agregar_vigencia`, `quitar_linea`, `cambiar_cualitativo`, `antecedente` y `matriz`, y
  `repartir()` (mayor residuo, la usa el plano). Lo digitado queda con origen PIIP si la
  regla es "varios productos, una fuente" y manual en los demás casos. Los botones
  "Proporcional a compromisos" y "Todo a un producto" se hicieron y se quitaron el mismo día:
  el reparto es manual.
- Solo se edita una distribución en borrador y con permisos de agregar, cambiar y borrar
  líneas; sin permiso de ver distribuciones, 403.
- Cualitativos: cada celda muestra el código, la descripción completa (en dos líneas, entera
  al pasar el cursor) y su origen, con un botón **Elegir** que abre una ventana con buscador
  (por código o por palabras de la descripción) y la lista de opciones con la descripción
  completa; clic en una opción la guarda y cierra; Esc o clic fuera cierra
  (`distribuir/elegir/`). La vigencia del gasto usa la misma ventana: "Elegir" en la línea la
  cambia (`cambiar_vigencia`, sin repetir vigencia para la misma fila y producto) y
  "+ vigencia" agrega una línea en una vigencia que la fila y el producto todavía no tienen. Solo ofrece códigos activos y muestra hasta 60 coincidencias. Se
  probó antes con listas desplegables, pero los nombres largos no se leían.
- La lista de distribuciones vacía explica cómo se crean (con la precarga del corte).
- Ayudas en globo (el mismo de la ficha del proyecto): junto a "Validación", las reglas que
  impiden validar; junto al estado, qué significa borrador, validada y enviada. Los nombres de
  los productos van completos (encabezado, líneas y referencia del periodo anterior).
- No se probó en el navegador con datos locales: el corte local va al 11/11 y no tiene
  periodo. Las pruebas cubren la pantalla y cada acción.

- Archivos: vistas en `get_urls()` del admin de `DistribucionBPIN`, `cuipo/templates/cuipo/`
  (pantalla y parciales), `cuipo/static/cuipo/htmx.min.js`.
- Aceptación:
  - La matriz recalcula la diferencia contra SIIFWEB sin recargar.
  - Los cualitativos muestran su origen; un usuario sin permiso sobre los modelos del CUIPO
    recibe 403.
  - Si el BPIN se distribuyó en un periodo anterior de la vigencia, se ve esa distribución
    (valor y participación por producto) en solo lectura.

**Fase 5 — Validaciones** — **hecha el 13/11** (rama `cuipo-fase5-validaciones`, sin migraciones,
22 pruebas en `cuipo/tests/test_validacion.py`).
- `cuipo/validacion.py`: `validar_distribucion()` (errores y advertencias, cada uno con su
  fila y línea) y `validar_corte()`. Errores: lo que no deriva (fuente sin homologar...), fila
  que no cuadra al centavo en C, O o P, valores negativos, O > C o P > O en una línea, producto
  que no es del BPIN según el PIIP (en la inversión sin BPIN, solo el 0), CPC, detalle
  sectorial, tercero o política pública vacíos, códigos inactivos (producto, vigencia del
  gasto, cualitativos) y distribución sin productos. Advertencia: CPC 0 en un concepto que
  exige CPC.
- Ajuste frente al plan: además del CPC, también bloquean el detalle sectorial, el tercero y
  la política pública vacíos, porque son campos obligatorios de la línea del plano.
- Estados: borrador → validado (solo sin errores; registra quién y cuándo) → enviado; una
  validada puede volver a borrador (se borra quién la validó); una enviada ya no cambia
  (`TRANSICIONES`, `cambiar_estado`). Solo en borrador se editan las líneas, también en el
  admin.
- Pantalla: panel de validación que se actualiza con cada cambio (fuera de banda) y botones
  Validar / Volver a borrador / Marcar enviada. Admin: acción "Validar las distribuciones
  seleccionadas", el resultado de la validación en cada distribución y el estado con solo
  las opciones permitidas.

- Archivo: `cuipo/validacion.py` con `validar_distribucion()`.
- Aceptación: cada regla de la sección 4.3 tiene su prueba; en 202500000029628, recurso 35,
  ninguna celda deja O > C.

**Fase 6 — Generador del plano** — **hecha el 13/11** (rama `cuipo-fase6-plano`, sin migraciones,
18 pruebas en `cuipo/tests/test_plano.py`).
- `cuipo/plano.py`: `revisar(corte)` (BPIN sin distribución y distribuciones con errores),
  `detalle(corte)` (líneas de detalle: cada valor de cada fila se redondea al peso y se
  reparte entre sus líneas por mayor residuo; luego se agrupan las iguales), `resumenes()`,
  `generar(corte)` (el bloque de la inversión con su encabezado, fin de línea CRLF) e
  `integrar(texto, corte)`. El código de la entidad sale de `settings.CUIPO_ENTIDAD`
  (por defecto 117070000).
- Integración en el plano de presupuesto: dentro del bloque D se quitan las líneas 2.3 y el
  resumen 2; las demás líneas quedan con su texto original; se agregan las 2.3 nuevas y el
  resumen 2 se recalcula como la suma de los resúmenes de primer nivel (2.1, 2.2… y la 2.3
  nueva) por vigencia y sección. El encabezado debe ser del mismo periodo y año del corte.
  Se conservan el fin de línea y la codificación del archivo subido.
- Pantalla **Plano** de cada corte (`/admin/cuipo/corteejecuciongastos/<id>/plano/`, enlace
  en la lista de cortes): estado de las distribuciones, problemas que impiden generar, vista
  previa de las primeras 40 líneas, descarga del bloque de inversión, integración subiendo el
  plano de presupuesto (no se guarda) y "Marcar enviadas las validadas".
- Se puede generar con distribuciones en borrador si no tienen errores; la pantalla muestra
  cuántas hay en cada estado.
- Por confirmar con el primer envío: que CHIP acepte las secciones como `16.0` y el fin de
  línea CRLF en el bloque generado (el integrado conserva el del archivo subido).

- Archivos: `cuipo/plano.py` y una vista o acción de descarga.
- Aceptación:
  - Encabezado exacto, 15 campos por línea D, líneas resumen con los cualitativos vacíos.
  - Orden y agrupación según la sección 4.4; sin líneas en cero.
  - El redondeo por mayor residuo cuadra con el total (se prueba con 202500000029628, que
    tiene centavos).
  - Al integrarse en el plano de presupuesto, solo cambia el bloque D: sus líneas 2.1 y 2.2
    y las categorías E, C, B y A salen idénticas, y el orden de bloques se conserva.

**Fase 7 — Pruebas** — **hecha el 13/11** (rama `cuipo-fase7-pruebas`).
- `cuipo/tests/fabricas.py` reúne los ayudantes que estaban repartidos: reportes de ejecución
  en memoria (`fila`, `libro_ejecucion`, `cortar`, `corte_con`), el libro de listas mínimo
  (`hojas_minimas`, `libro_listas`), las listas CHIP mínimas (`listas`,
  `listas_distribucion`), la formulación PIIP (`formular`), la homologación (`homologar`) y
  los escenarios (`corte_t3`, `preparar_plano`, `distribuir_manual`).
- `cuipo/tests/test_extremo_a_extremo.py`: 202500000039332 de punta a punta (corte al 30/09,
  precarga, digitación desde el PIIP, CPC, validación, plano) contra el plano esperado
  `cuipo/tests/datos/plano_202500000039332.txt`, byte a byte, también descargado desde la
  pantalla del plano. `.gitattributes` evita que git cambie su fin de línea.
- Las pruebas del CUIPO son 149, en 9 archivos.

**Estado del módulo (13/11):** las siete fases están hechas en ramas encadenadas, sin subir:
`main ← formulacion-piip ← cuipo-ejecucion-gastos ← piip-control-siifweb ← cuipo-fase1-listas ←
cuipo-fase2-reglas ← cuipo-fase3-distribucion ← cuipo-fase4-pantalla ← cuipo-fase5-validaciones
← cuipo-fase6-plano ← cuipo-fase7-pruebas`. Migraciones: `siifweb/0020` a `0022` y `cuipo/0001`
a `0004`.

**Para usarlo en producción** (después de respaldar Supabase y subir la rama final):
0. Catálogo PIIP (antes de cargar el PIIP), en Configuración → Municipios: renombrar
   "San Antonio de Palmito" → "Palmito", "Toluviejo" → "San José De Toluviejo" y "Todo el
   departamento" → "Todo el departamento de sucre"; crear Barranquilla, Garzón, San Andrés y
   Santiago De Cali. Luego subir `ReporteSIIFWEB_20261111.xlsx` como "Información general
   PIIP", procesarlo y homologar a mano los indicadores sin homologar que usan proyectos.
   Dar los permisos del CUIPO a quien vaya a distribuir (no hay roles nuevos).
1. CUIPO → Versiones de las listas CHIP: subir `Listas_Categoria_CUIPO_09-2026.xlsx`.
2. Cargar los consolidados al día y, si hay uno nuevo, el exporte del PIIP.
3. CUIPO → Cortes: cargar el corte 01/01–30/09/2026 (completo, 22 columnas).
4. CUIPO → Pendientes: "Crear las reglas que falten" (las 14 del plan y las 62 homologaciones
   de fuente del T3). Lo que falte homologar se ve en SIIFWEB → Fuentes y SIIFWEB → Rubros,
   columna **Homologado**, con los filtros "Homologado (CUIPO): No" y "En el corte del CUIPO:
   Con filas en el corte" (al 30/09: los recursos 35 y 125).
5. Cortes: acción "Precargar la distribución del CUIPO".
6. Seguimiento → Distribuciones por BPIN CUIPO → Distribuir: digitar, elegir cualitativos y
   validar. (El enlace está en el menú Seguimiento desde el 13/11, a pedido del usuario.)
7. Cortes → Plano: descargar el bloque o integrarlo en el plano de presupuesto; después de
   enviar a CHIP, "Marcar enviadas las validadas".

---

## 6. Casos de prueba

Cifras del corte 01/01–11/11/2026 (base local). Se recalculan con el corte al 30/09 cuando
esté cargado. Todas las filas son del rubro indicado y del árbol de 2026.

**202500000039332** — una fila, productos 2201006 y 2201048. Regla "varios productos, una
fuente": pendiente de digitar desde el PIIP.

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.02.02.009 | 3 | 2 | 1.084.750.996 | 834.182.726 |

Al 30/09 el RP era 1.054.759.012 (del consolidado de compromisos filtrado por fecha). En el
T3 se reportó 717.349.192 para 2201048 y 337.409.820 para 2201006.

**2023002700021** — productos 1906005 y 1906030, manual. Dos secciones en el mismo BPIN
(centros de costo 16 y 3).

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.01.01.001.02.08 | 7 | 16 | 6.016.089.072,27 | 6.015.697.203,50 |
| 2.3.2.01.01.001.02.08 | 114 | 3 | 1.027.664.538,50 | 1.014.627.682,00 |
| 2.3.2.01.01.001.02.08 | 159 | 3 | 4.949.736.116,45 | 0 |

- Al 30/09 la fila del recurso 159 ya existía con la adición de 4.949.736.116,45 pero con RP
  en cero: en el corte de septiembre no entra.
- El T3 que está en CHIP incluye además 15.251.706.363 de compromisos y 10.841.369.180 de
  obligaciones y pagos del recurso 7 para 1906030, que se agregaron a mano y no están en el
  reporte oficial. Cuando el aplicativo genere el T4 ese valor no aparecerá: es esperado, no un
  error del aplicativo.

**202500000029628** — tres recursos, centro de costo 19, productos 4502034 y 4502038, manual.

| Rubro | Recurso | CC | RP | Obligación = Pago |
|---|---|---|---|---|
| 2.3.2.02.02.009 | 35 | 19 | 2.979.309.905 | 2.010.861.681,15 |
| 2.3.2.02.02.009 | 54 | 19 | 1.000.000.000 | 1.000.000.000 |
| 2.3.2.02.02.009 | 125 | 19 | 425.784.947 | 314.670.429,87 |

**Inversión sin BPIN** — proyecto 0, producto 0, el 100 % automático. Referencia del T3
(plano aceptado por CHIP, corte al 30/09): 2.3.2.01.01.001.03.02, sección 16.0, fuente
1.2.3.3.04, BPIN 0, 30.460.454.553 de compromisos. En total, 34 líneas por 75.195.347.557.

**202600000018441** — una fila, un producto (3301053), el 100 % automático. Recorre todas las
reglas de derivación en un solo caso: RP 6971 del 28/10/2026 (no estará en el corte del
30/09), transferencia de recursos del balance de estampilla procultura.

| Dato de la fila | Valor | Derivación esperada |
|---|---|---|
| Rubro | 2.3.3.05.09.054 | No habilitado para departamentos (columna 438 = 0) → `HomologacionRubro` → 2.3.3.05.09.099 |
| Recurso | 108 (R.B. Estampilla Pro Cultura) | `HomologacionFuente` → 1.3.3.3.20 |
| Centro de costo | 10 (Fondo Mixto) | Sección 16.0 (por defecto); tercero 220170001 por `ReglaTercero` |
| Producto | 3301053 | Existe en la lista CHIP de productos |
| RP | 40 millones aprox. | |

---

## 7. Preguntas abiertas

No quedan preguntas abiertas que bloqueen la fase 1.

**Fuera de alcance:** reservas (vigencia de gasto 2) y el árbol de otra vigencia; roles
separados de planeación y presupuesto; carga del reporte de AporteProductos del PIIP; copia
de distribuciones entre trimestres; carga del reporte de programación; bloque D completo
(2.1 y 2.2).
