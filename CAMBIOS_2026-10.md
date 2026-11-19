# Cambios de octubre de 2026

Lo que se agrego y corrigio en el proyecto de seguimiento POAI en esta tanda: saldo y
pagado en las obligaciones de la ficha, un filtro de fechas, el PDF de cada tabla, cinco
correcciones que salieron de una revision del codigo y la limpieza de `media/` (commits
`5849e05` y `86aabee`). Despues, sin commit todavia: la barra lateral reorganizada, una
copia de produccion en la sqlite local, las metas del plan de desarrollo traidas de SUTEC,
la programacion de proyectos traida del Access, la ficha de la meta y los reportes
(secciones 6 a 11).

---

## 1. La ficha del proyecto (panel SIIFWEB)

### Obligaciones: saldo y pagado

Dos columnas nuevas despues del valor definitivo: **Saldo** y **Pagado**, con su total.
No hizo falta tocar la carga: el consolidado de obligaciones ya trae `SALDO_OBLI` y
`PAGOS`, y se guardaban en `ObligacionImputacion`. En la base local se cumple
valor = saldo + pagado en todas las filas de las cinco vigencias.

Las tres sumas van sobre la misma relacion (las imputaciones del proyecto) en un solo
`annotate`, asi que comparten el join y no se multiplican aunque la obligacion tenga
varias imputaciones del proyecto.

Verificado en el proyecto con mas documentos (id 129, 1.880 obligaciones): el total de la
pagina coincide con la suma directa, $8.905.131.433,65 = $604.959.419,71 de saldo +
$8.300.172.013,94 pagados.

### Filtro de fechas

Desde / hasta sobre las tablas de CDPs, RPs y obligaciones, cada una cortada por **su
propia fecha**: disponibilidad, registro y obligacion. Es la misma regla del dashboard.
Los limites se incluyen. Las tarjetas, la cadena por vigencia, fuentes, contratos,
calendario de pagos y reservas no se filtran.

El filtro queda en la URL, asi que la ficha filtrada se comparte con el enlace. Los
conteos de los titulos y los totales de las tres tablas siguen al filtro.

### Formato de fecha

La fecha de la obligacion sale en el mismo formato regional que la de CDP y RP
(`1 de Marzo de 2025`). Las demas fechas de la ficha (contratos, calendario, SECOP II,
modales) siguen en `AAAA-MM-DD`.

### PDF de cada tabla

Cada titulo (CDPs, RPs, Obligaciones) tiene a la derecha un **Descargar PDF** que baja
solo esa tabla con el filtro aplicado. Detalle en el README, seccion *PDF de cada tabla*.

- `siifweb/pdf_ficha.py`, con ReportLab (Python puro, sin librerias del sistema).
- Usa las mismas consultas que la pantalla: el metodo `_documentos_filtrados` se saco de
  la vista para que ficha y PDF no puedan diferir.
- Encabezado con BPIN, nombre, **dependencia responsable (POAI)**, periodo y fecha de
  generacion. Tabla con bordes en todas las celdas y encabezados centrados.
- Fuente **Carlito**: la version abierta de Calibri. Calibri no esta en Railway y su
  licencia no permite subirla al repositorio; Carlito (OFL) si, en `siifweb/fuentes/`.

Con el ejemplo del usuario (proyecto 129, del 15 de septiembre al 25 de octubre de 2025):
0 CDPs, 34 RPs y 216 obligaciones, lo mismo que la base.

Nueva dependencia: `reportlab` (trae Pillow), en `seguimiento_poai/pyproject.toml`.

---

## 2. Correcciones de la revision

| Que | Antes | Ahora |
|---|---|---|
| Formulario de carga de SECOP II | Pedia vigencia, aunque el README decia dejarla vacia | La acepta vacia, como historial y POAI |
| `decimal()` en `cargas.py` | `'1.234,56'` y `'1,234.56'` daban 0; cualquier valor ilegible, 0 en silencio | Lee el separador de miles; un valor ilegible aborta la carga |
| Pruebas sin `.env` | 121 fallaban (301 a HTTPS) y otras por falta de `SECRET_KEY` | No dependen del `.env` |
| Atajos del dashboard | `date.today()`: en Railway (UTC), desde las 7 p. m. ya era el dia siguiente | Fecha de Bogota |
| Fecha imposible en la URL (`2025-13-45`) | Error 500 en ficha y dashboard | Se ignora (`fecha_del_get`) |
| Pruebas escribiendo en `media/` | `MEDIA_ROOT = BASE_DIR / 'media'` pisaba la carpeta temporal de la guarda | Las pruebas usan la temporal |

El cambio de `decimal()` se verifico sobre los 29 reportes reales de `media/` y
`data/secop/`: 1.123.428 valores, ninguno ilegible y el mismo resultado que la funcion
anterior en todos.

---

## 3. Limpieza

- `media/reportes`: se borraron **4.694 xlsx de prueba (150 MB)**, los que dejaban las
  pruebas por el defecto de `MEDIA_ROOT`. Criterio: nombre de las pruebas (`consolidado`,
  `cdp`, `obligaciones`, `mezclado`, con o sin sufijo de Django) y ninguna carga que los
  referencie. Los 59 reportes referenciados siguen en su lugar; quedan 6 copias de
  reportes reales sin referencia, que no se tocaron.
- README: se quito la clave del admin, que ya no abria la base local y estaba publicada
  en GitHub.

---

## 3b. El cruce POAI ya no se carga

El usuario dejo de usarlo. La dependencia responsable y las clasificaciones de cada
proyecto se mantienen a mano en el admin; el catalogo de dependencias responsables local se
sincronizo con el de produccion (22, con los nombres completos).

- `cargar_poai` sale de `cargas.py`, junto con su lugar en `ORDEN_DE_CARGA`.
- El formulario de carga no ofrece el tipo; si se abre la carga de julio, se ve con su tipo.
- `CargaReporte.TipoReporte.POAI` se queda en el modelo para que esa carga se lea con su
  nombre. No cambia el esquema: no hay migracion.
- Los 79 proyectos con origen "Cruce POAI" lo conservan.

---

## 4. Pruebas

352 pruebas en catorce modulos (antes 186). Nuevos `test_pdf_ficha.py`, `test_plan_desarrollo.py`,
`test_programacion_proyectos.py` y `test_reportes.py`. Las de cada
correccion se verificaron contra el codigo anterior: fallan con el y pasan con el nuevo.

---

## 5. Restauracion en una maquina nueva

La carpeta llego por MEGA sin `.git`, `.env`, `.venv` ni memorias. Lo que hubo que hacer,
ademas de lo que ya dice `respaldo_claude/COMO_RESTAURAR.md`:

- **No correr `git checkout -- .`** al mover el `.git`: pisaria con la version de GitHub
  cualquier archivo local mas nuevo. Primero `git status` y `git diff --ignore-cr-at-eol`.
- En Windows con `core.autocrlf=true` global, todos los archivos salen modificados sin
  estarlo. Se fijo `git config core.autocrlf false` en el repo (los archivos estan
  guardados tal cual, mezcla de CRLF y LF) y se refresco el indice con `git add -u`,
  despues de comprobar que `git diff` salia vacio.
- La maquina no tenia identidad de git: se configuro en el repo la de los commits
  anteriores.
- `uv run --directory seguimiento_poai` solo instala las dependencias de esa carpeta; las
  de la raiz (`dotenv`, `whitenoise`, `gunicorn`...) llegan con un `uv sync` en la raiz,
  que a su vez desinstala las de la carpeta. Funciona en el orden `uv sync` y despues
  `uv run --directory`, que es lo que hace Railway.

---

## 6. La barra lateral

| Seccion | Que tiene |
|---|---|
| Seguimiento | Proyectos, Avance financiero (antes Dashboard), Reportes, Metas y Programacion de proyectos |
| Plan de Desarrollo | El catalogo del plan, en el orden de su jerarquia (ver la seccion 8) |
| SIIFWEB | Cadena de gasto, cierre de vigencia, contratos del historial y sus catalogos (terceros, rubros, fuentes, dependencias y clasificaciones) |
| Contratacion | Lo de SECOP II (antes "Contratacion publica (SECOP II)") |
| Configuracion y parametrizacion | Dependencias responsables, cargas del reporte, tipos de banco y municipios |

Metas y Programacion de proyectos van con el permiso de su propio modelo: los roles
Seguimiento y Consulta todavia no lo tienen, asi que no los ven (en vez de un enlace que
les responderia 403).

---

## 7. Copia de produccion en la sqlite local

La sqlite local se reemplazo por una copia de produccion (28/10/2026): `dumpdata` en una
transaccion de solo lectura, con llaves naturales, sin sesiones, permisos ni tipos de
contenido (Django los regenera). 304.677 objetos; las 33 tablas quedaron con las mismas
filas que produccion y obligado y pagado cuadran al centavo. Los usuarios son los de
produccion. La sqlite anterior quedo en `respaldo_claude/`.

Antes se sincronizo el catalogo de dependencias responsables: en produccion estaban
renombradas con su nombre completo ("Hacienda" -> "Secretaria de Hacienda"); se
emparejaron por los proyectos asignados (194 de 194 BPIN) y se agrego "Secretaria de
Transito y Transporte".

---

## 8. Metas del plan de desarrollo (de SUTEC)

Integradas segun `modelos-metas/PLAN_METAS_PDD.md`: 13 modelos al final de
`siifweb/models.py` y las migraciones `0011_metas_del_plan` (tablas) y
`0012_datos_de_las_metas` (datos de produccion de SUTEC del 21/09/2026). En local: 436
metas, 1.744 vigencias, 2.119 vinculos de relaciones multiples y 469 meta-dependencia,
sin el aviso de dependencias creadas.

- Admin de los 13 modelos, con autocompletado en los catalogos grandes y las vigencias
  dentro de la meta.
- `MetaIndicadorForm` valida que los indicadores PDD sean del programa de la meta; el
  `clean()` del modelo juzga los indicadores que se van a guardar, para que cambiar
  programa e indicadores a la vez no de un error falso.
- Listado de Metas de menor a mayor (orden en el admin, para no tocar la `0011`), con una
  flecha por meta que despliega sus proyectos programados (`list_sections` de unfold).
- Filtros: MT (texto), linea estrategica, sector, programa e indicador PDD, sector,
  programa, producto e indicador MGA, dependencia responsable y estado.

---

## 9. Programacion de proyectos (del Access "Seguimiento PDD STO")

La tabla `tblProyectos` paso a cinco modelos: `ProgramacionProyectos`, `ProgramacionMeta`,
`ObservacionProyecto`, `TipoBanco` y `Municipio`. Migraciones
`0013_programacion_de_proyectos` y `0014_datos_programacion_proyectos`; la `0014` la
escribe `modelos-metas/generar_migracion_proyectos.py` desde el Access. Las reglas de
limpieza estan en el README y en el generador.

Resultado, contrastado fila por fila con el Access: 1.265 proyectos, 1.609 programaciones
y 539 observaciones, sin diferencias. La meta de la vigencia lleva 5 decimales (primero
fueron 3, y 17 valores de metas viales con cuatro se redondeaban); se regenero la `0013`
y la `0014` antes de desplegar.

---

## 10. La ficha de la meta

Vista propia desde el icono de carpeta del listado o el boton del detalle: encabezado con
la ruta del plan, tarjetas, y la tabla de meta y programacion por vigencia (el porcentaje de
avance se quito despues: resultaba confuso). Cada vigencia despliega sus proyectos, con el nombre completo, y cada proyecto
abre un modal con sus municipios, vigencias, observaciones y todas las metas en que esta
programado, con su vigencia y su programacion.

Despues se le sumo la ejecucion en SIIFWEB de los proyectos programados: comprometido,
obligado, pagado y reservas, cruzando BPIN y vigencia, en la tabla por vigencia y en cada
proyecto del desplegable (es la plata del proyecto completo, no la parte de la meta). El
modal muestra las cifras del BPIN con el enlace a su ficha de ejecucion, y permite agregar
observaciones con la fecha del dia. Contrastado con MT323: las cuatro vigencias cuadran con
una suma directa en la base.

Y un boton **Programar proyecto**: un modal para programar en la meta un proyecto existente
(con buscador) o uno nuevo (con municipios), en esta y otras metas, con una observacion
opcional. Rechaza BPIN o nombres repetidos y programaciones dobles, y guarda todo o nada.

El modal de cada proyecto se puede **editar** sin salir de la ficha: datos del proyecto,
municipios y sus programaciones en todas las metas. Al guardar vuelve a la ficha con el
proyecto abierto.

Queda por confirmar con quien llevaba el Access si la meta del proyecto era lo que aporta
en esa vigencia o el total repetido cada ano: en las metas viales lo programado supera la
meta (MT323: 10,75 programado contra 3 en 2024).

---

## 11. Los reportes

`Reportes` pasa a ser un indice con tres reportes, cada uno con su pagina, sus filtros y su
Excel: el Financiero de siempre, el **Plan indicativo** (una fila por meta, como `qryPI` del
Access) y **Proyectos programados** (una fila por proyecto, meta y vigencia, como
`qryProyectos`), con las columnas que hay en los modelos. La pagina de cada reporte es una
sola plantilla (`reporte.html`); `reporte_financiero.html` se borro.

Dos cosas que salieron al probar: Proyectos programados hacia 3.226 consultas (armaba el
indicador de resultado y los ODS de cada fila, que no lleva) y ahora hace 8; y el filtro de
vigencias repetia cada ano una vez por meta, por el orden por defecto de `ProgramacionMeta`
dentro del `distinct`.

Las migraciones `0011` a `0014` se desplegaron el 29/10/2026, despues de la copia de
seguridad de Supabase (`respaldo_claude/supabase_antes_de_metas_20261029.json`).

---

## 12. Ajustes del Access (29 de octubre y 1 de noviembre)

El Access se actualizo dos veces despues del despliegue. Comparando los datos de la `0014`
con los que el generador produce del Access nuevo (`tblProyectos` paso de 1.626 a 1.624
filas): cuatro filas borradas (Id 552, 553, 606 y 1648; cada una era la unica
programacion de su proyecto), una que cambio de vigencia (Id 1693, MT242, de 2026 a
2027) y, en la version del 1 de noviembre, dos nuevas (Id 1720 y 1721): el proyecto BPIN
2024002700194, "Elaborar los estudios y disenos que permitan implementar una alternativa
sostenible de provision de agua...", en MT273 y MT435 para 2027. Las observaciones no
cambiaron.

Van en `0015_ajustes_del_access`, que reconoce cada fila por su Id de Access y no toca las
que ya se hayan editado en la aplicacion. Quedan 1.262 proyectos, 1.607 programaciones y
539 observaciones. Probada en la sqlite local en los dos sentidos.

El proyecto nuevo se parece al BPIN 2021000020074 ("Diseno de la alternativa sostenible de
provision de agua...", Banco Territorial), que sigue en el Access con las mismas metas,
vigencia y valor. Quedan los dos, como en el Access.

El Plan Indicativo del Access difiere del cargue de SUTEC en tres metas: en MT172 y MT390
la unidad de 2026 paso a 2027, y en MT175 la de 2027 paso a 2026. SUTEC todavia no se usa
y los ajustes se hacen en el Access, asi que la `0015` toma los valores del Access. El
Access trae ademas tres codigos que no estan en la base (MT465, MT466 y MT468).

En el listado de Metas, la columna Estado se cambio por la meta de cada vigencia (2024 a
2027).

---

## 13. Catalogo de productos MGA (3 de noviembre)

`ProductoMGA` suma la descripcion del producto y "medido a traves de", e `IndicadorMGA` la
unidad de medida y si es nacional y territorial (los dos catalogos, `MedidoATravesDe` y
`UnidadMedida`, como modelos propios con llave foranea), traidos del catalogo de productos MGA de
junio de 2025 (`modelos-metas/CatalogoProductoMGA_junio_2025.xlsx`) por el codigo del
producto y del indicador. Migraciones `0016_catalogo_mga` y `0017_datos_catalogo_mga`
(generada con `modelos-metas/generar_migracion_catalogo_mga.py`). Cruzan 375 de los 376
productos y de los 376 indicadores: el 4101093 y el 410109300 no estan en el catalogo de
2025, porque el plan se formulo con el de 2024. Los listados de productos e indicadores MGA
muestran los campos nuevos y filtran por ellos.

El encabezado de la ficha de la meta pasa a mostrar la linea jerarquica completa, en este
orden: plan de desarrollo, linea estrategica, sector PDD, programa PDD, sector MGA,
programa MGA, producto MGA, medido a traves de, indicador MGA y unidad de medida; debajo,
la descripcion del producto, las dependencias y los ODS. Una prueba nueva revisa que
ningun comentario `{# #}` de las plantillas ocupe dos lineas: Django lo mostraria como
texto, y ya habia pasado dos veces en la ficha.

---

## 14. Seguimiento de las metas (3 de noviembre)

Modelo `SeguimientoMeta`: lo que un proyecto reporta en una meta por vigencia y mes, con
valor de 5 decimales y observacion; uno por meta, proyecto, vigencia y mes. Y
`PeriodoReporte`: la fecha de inicio y de fin del reporte de cada vigencia, contra la que
el modelo valida la fecha del dia. Se reporta desde el modal del proyecto en la ficha de la
meta (boton **Agregar seguimiento**), que solo ofrece las vigencias abiertas; tambien desde
el admin. Migracion `0018_seguimiento_de_metas`. En la sqlite local quedaron configurados
2025 (01/01/2025 a 15/02/2026, cerrado) y 2026 (01/01/2026 a 15/02/2027).

Ajustes del 4 de noviembre: el valor es lo del mes, no el acumulado (texto de ayuda en la
`0019_valor_del_mes`, y el formulario dice "Valor del mes (no el acumulado)"); la vigencia
tiene que ser una en la que el proyecto este programado en la meta, y el modal solo ofrece
esas; el listado **Seguimiento de metas** paso de Seguimiento al final de Plan de Desarrollo.

Queda por decidir que roles reportan.

---

## 15. Centro de costo y Excel en la ficha del proyecto (5 de noviembre)

Las tablas de CDPs, RPs y obligaciones de la ficha de ejecucion muestran el **centro de
costo** de cada documento, despues de la fecha, y su PDF tambien. Junto al **Descargar
PDF** de cada tabla hay un **Descargar Excel** con las mismas columnas y el mismo filtro de
fechas (`?descargar=xlsx`). Las columnas se definen una sola vez en `pdf_ficha.COLUMNAS`,
de donde salen los dos formatos. En el PDF de obligaciones se redistribuyeron los anchos
para dar lugar a la columna nueva.

Despues, en el mismo dia: un **filtro de centro de costo** junto al de fechas (`?centro=`),
que recorta las tres tablas y sus descargas y solo ofrece los centros con documentos del
proyecto; y las tres tablas pasan de 26rem a 34rem de alto.

Las **reservas** pasan de tarjetas a una tabla: vigencia, numero, fecha, beneficiario, objeto,
acto administrativo y, sumados por reserva con lo de este proyecto, el valor definitivo, las
obligaciones, los pagos y el saldo, con fila de total.

La firma de los contratos de SIIFWEB (tabla y modal, con las fechas de inicio y fin del
modal) pasa al formato regional de CDPs, RPs y obligaciones.

El numero de cada reserva abre un **modal** con sus lineas de este proyecto: CDP de origen,
rubro, fuente, valor definitivo, obligaciones, pagos y saldo, con su total. Un ojo junto al
numero avisa que hay detalle. CDPs, RPs y obligaciones bajan a 30rem de alto.

El **calendario de pagos** pasa al modal de cada contrato de SIIFWEB (sus actas con fecha,
numero, tipo, concepto y valor, y el total) y sale la seccion aparte de la ficha. En el
encabezado, "Responsable" va debajo de "Ejecuta": en la misma linea quedaban pegados.

La tabla de **fuentes de financiacion** suma, ademas de lo comprometido, lo obligado y lo
pagado de cada fuente en el proyecto, con su total. Cada etapa se suma en su propia
consulta y se cruza por la fuente, para que varias obligaciones de un RP no dupliquen lo
comprometido.

## 16. Catalogo PIIP y Ficha PIIP (12 de noviembre)

Rama `formulacion-piip`, sin subir. Detalle completo en `CATALOGO_PIIP.md`.

**Que se pidio.** Que la ficha del proyecto muestre lo formulado en el PIIP (sector,
programa, vigencias, objetivo general, problema, descripcion, poblaciones, region,
departamento, municipios y, por producto e indicador, objetivo especifico, etapa, UMP,
UMI, tipo, acumula, meta total y metas por vigencia), tomado de la tabla `InfoGeneral`
del libro `ReporteSIIFWEB_*.xlsx`.

**Como quedo.**

- Catalogo PIIP aparte del catalogo del plan, porque este no admite productos nuevos sin
  pasar por la Asamblea. Solo producto e indicador (`ProductoCatalogo`,
  `IndicadorCatalogo`) y solo los que usan los proyectos: 190 indicadores y 187 productos,
  validados por codigo contra el catalogo MGA de junio de 2025 en la migracion `0021`.
- Cada indicador del catalogo apunta a un indicador del plan (`indicador_pdd`); de alla
  salen el producto, el programa y el sector del plan. La `0021` homologo 163 por codigo;
  los demas se homologan a mano en la ficha del indicador. La carga y el admin homologan
  por codigo los que queden sin homologar; una homologacion manual no la cambia nadie mas.
- La ficha PIIP de cada proyecto: `FormulacionProyecto` (uno a uno con `Proyecto`; sector y
  programa como texto del PIIP), `IndicadorProyecto` (el producto sale del indicador) y
  `MetaVigenciaIndicador`. Solo para BPIN con algun documento en SIIFWEB: sin ejecucion no
  hay trazabilidad presupuestal.
- `Departamento` (con region) y `Municipio.departamento`. Los municipios existentes quedan
  en Sucre.
- Carga **Informacion general PIIP**: atomica; reemplaza la ficha de cada BPIN que trae el
  archivo; valida cada indicador por codigo y crea el que falte (con su producto) y sus
  metas; avisa lo creado, los BPIN omitidos, los municipios no reconocidos y las metas
  contradictorias.
- `CargaReporte.hash` unico por tipo de reporte: el mismo libro se carga como SECOP II y
  como PIIP.
- Menu **Catalogo PIIP** (Formulacion de proyectos, Productos, Indicadores), solo para
  administradores. Pestana **Ficha PIIP** en la ficha, en el orden de `InfoGeneral`, con la
  linea del plan homologado al final, aunque coincida.

**En la base local.** 364 proyectos cargados, 436 indicadores y 519 metas; 124 BPIN del
PIIP sin ejecucion en SIIFWEB quedan fuera; 18 indicadores usados quedan por homologar a
mano; 4 municipios de fuera de Sucre por crear en el admin.

**Lo que se descarto en el camino.** Cargar el catalogo MGA territorial completo (5.739
indicadores, la mayoria sin uso); guardar sector y programa en el catalogo PIIP (salen del
plan); un modelo de homologacion aparte (es un campo del indicador); una tabla de
productos del proyecto (el producto sale del indicador); el campo "producto principal".

**Pruebas.** 385, todas pasan (`test_formulacion_piip.py` es nuevo).

## 17. Produccion con DEBUG=False (12 de noviembre)

En produccion no se podia poner `DEBUG=False`: toda pagina caia con `Missing staticfiles
manifest entry`. El `collectstatic` corria en el `preDeployCommand` de Railway, que se
ejecuta en un contenedor aparte cuyo disco no llega al que atiende; con `DEBUG=True`
Django no consulta el manifiesto de WhiteNoise y por eso funcionaba. Ahora corre en el
`buildCommand` y queda en la imagen; el `preDeployCommand` solo hace `migrate`. Subido a
`main` (`202e619`) y desplegado.
## 18. Corte de ejecucion de gastos para el CUIPO (13 de noviembre)

App nueva **`cuipo`**, con el importador del reporte "Ejecucion presupuestal del gasto por
centro de costo y fondo" de SIIFWEB (`estado_ppto_gasto_gobatl_fyccw_Vigencia{v}_Fecha{f}`).
Sus datos solo los usa el CUIPO: no alimentan la ficha, el tablero ni los catalogos de
`siifweb`, por eso rubro, recurso, centro de costo y proyecto van como texto, tal como
vienen, y no como llaves (la carga no crea rubros, fuentes ni proyectos).

- `CorteEjecucionGastos`: vigencia, fecha de inicio y de fin del corte, fecha de
  descarga, archivo, hash, estado y mensaje. Uno por vigencia y rango; cada corte se
  conserva (cargar octubre no toca septiembre). Se importa al guardarlo en el admin; la accion "Volver a
  procesar" lo repite.
- `FilaEjecucionGastos`: el detalle del reporte (las filas con recurso) con todas sus
  columnas menos DISPONIBLE: RUBRO_ID, rubro, recurso, centro de costo y proyecto con sus
  nombres, la apropiacion (inicial, adiciones, disminuciones, creditos, contracreditos,
  aplazamientos, desaplazamientos, definitiva), solicitud en tramite, CDP, RP, obligacion y
  pago. Unica por corte, RUBRO_ID, recurso, centro de costo y proyecto.
- Los subtotales del arbol de rubros no se guardan: la carga comprueba que cada uno sea la
  suma de su detalle y, si alguno no cuadra, aborta sin dejar nada.
- El reporte de 2023 trae, ademas de su arbol (RUBRO_ID 11545), filas del arbol de 2022
  (5582) con solo obligacion (16.890.687.467) y pago. Van marcadas como **de otra
  vigencia**; por ellas RUBRO_ID es parte de la llave.
- Menu **CUIPO**: cortes (con RP, obligacion y pago totales) y filas, visibles con el
  permiso de ver cortes. Los roles del equipo no lo tienen.
- **Fechas del corte.** Inicio y fin son el rango con que se descarga el reporte (para
  el CUIPO, que es acumulado, desde el 1 de enero; en una vigencia cerrada, hasta el 31 de
  diciembre); la de descarga, el dia en que se genero el archivo. El formulario exige que
  inicio y fin caigan en la vigencia, que el fin no sea anterior al inicio y que la
  descarga no sea anterior al fin.
- **Para el CUIPO se usa este reporte**, no la agrupacion del consolidado de compromisos.

**Con los archivos de `modelos-metas/ejecucion-gastos`** (2022 a 2026): 395, 463, 422, 400
y 405 filas de detalle; los subtotales cuadran en los cinco. El RP de 2026 al 11 de
noviembre (1.127.765.686.152,76) es el mismo del consolidado de compromisos de esa fecha.

**Pruebas.** 402, todas pasan (`cuipo/tests/test_ejecucion_gastos.py`, 17 nuevas).

## 19. Formulacion PIIP de todos los BPIN, con semaforo de SIIFWEB (13 de noviembre)

Rama `piip-control-siifweb`. Para controlar que proyectos del PIIP estan en SIIFWEB y
cuales no:

- `FormulacionProyecto` guarda su `bpin` (unico) y su `nombre` (columna `NombreProyecto`
  de `InfoGeneral`, que ahora es obligatoria). El `proyecto` de SIIFWEB pasa a ser
  opcional (`SET_NULL`).
- La carga del PIIP crea la formulacion de **todos** los BPIN y la enlaza con el `Proyecto`
  del mismo BPIN si existe. Antes solo entraban los que tenian documentos en SIIFWEB.
- Dos enlazadores por BPIN, uno para cada orden: la carga del PIIP enlaza con el proyecto
  que ya existe, y `Proyecto.save()` enlaza la formulacion que estaba esperando su BPIN
  cuando un reporte de SIIFWEB crea el proyecto, sin volver a procesar el PIIP. No hay
  triggers de base de datos. Detalle (cuando se activa cada uno, limites y ejemplo) en la
  seccion 9 de `CATALOGO_PIIP.md`.
- Lista de formulaciones: columna **BPIN en SIIFWEB** con semaforo (verde si el BPIN tiene
  algun CDP, RP, obligacion, reserva o contrato; rojo "No esta" si solo esta en el PIIP),
  filtro "En SIIFWEB", filtro por indicador y busqueda por codigo de indicador.
- Migracion `0022`: agrega los campos y llena BPIN y nombre de las formulaciones existentes
  desde su proyecto.

**En la base local** (PIIP del 11/11 y consolidados al 11/11): 488 formulaciones, 368 en
verde y 120 en rojo (10 de ellas enlazadas a un proyecto que existe sin documentos). La
carga no creo indicadores nuevos; los indicadores usados sin homologar pasan de 18 a 27.

**Pruebas.** 408, todas pasan (`test_formulacion_piip.py`, 6 nuevas).

**Ramas (13 de noviembre).** Se descarto la rama `centro-costo-compromisos` (centro de
costo por linea en `CompromisoImputacion`): se hizo cuando el CUIPO se iba a armar desde
el consolidado de compromisos, y el reporte oficial de ejecucion ya trae el centro de costo
por fila. La cadena queda `main <- formulacion-piip <- cuipo-ejecucion-gastos <-
piip-control-siifweb`, y la migracion de la formulacion paso a ser la `0022`.

## 20. CUIPO, fase 1: listas CHIP (13 de noviembre)

Rama `cuipo-fase1-listas`, sobre `piip-control-siifweb`. Primera fase del plan del CUIPO
(`PLAN_CUIPO.md`), que desde hoy implementa el asistente por fases.

- Diez catalogos CHIP en la app `cuipo` (conceptos, fuentes, secciones presupuestales,
  vigencias del gasto, productos MGA, CPC, detalles sectoriales, situaciones de fondos,
  politicas publicas y terceros) sobre una base comun: codigo unico como texto exacto,
  descripcion, activo y la ultima version que lo trajo. Los dos que chocaban de nombre con
  `siifweb` llevan sufijo: `ProductoCUIPO` y `TerceroCUIPO`.
- `VersionListas` y el importador `cuipo/listas.py`: lee las once hojas de
  `Listas_Categoria_CUIPO_MM-AAAA.xlsx`, crea lo nuevo, actualiza lo que cambio y deja
  inactivo lo que ya no viene; todo en una transaccion. Valida hojas, columnas, codigos
  repetidos, nivel S/D y largo del CPC (1, 5 o 7). La hoja Conceptos_CPC marca
  `requiere_cpc`; el producto `0 - NO APLICA` se crea aunque la hoja no lo traiga.
- Se importa desde el admin (al guardar la version; accion "Volver a importar") o con
  `manage.py importar_listas_cuipo <archivo> --version 09-2026`, que no sube el archivo.
- Menu: "Versiones de las listas CHIP" en CUIPO y la seccion "Listas CHIP", en solo lectura.
- Migracion `cuipo/0002`.

**En la base local**, version 09-2026: 3.075 conceptos (79 con CPC), 231 fuentes, 30
secciones, 6 vigencias, 5.072 productos, 7.659 CPC, 167 detalles sectoriales, 2
situaciones de fondos, 87 politicas publicas y 5.736 terceros, en 4 segundos. Importarla
otra vez no cambia nada.

**Pruebas.** 428, todas pasan (`cuipo/tests/test_listas.py`, 20 nuevas).

## 21. CUIPO, fase 2: homologaciones y reglas (13 de noviembre)

Rama `cuipo-fase2-reglas`, sobre `cuipo-fase1-listas`.

- Cinco tablas en `cuipo`: homologacion de fuentes (recurso de SIIFWEB -> fuente CUIPO, por
  vigencia, con quien la valido), homologacion de rubros (excepciones), reglas de seccion por
  centro de costo, de tercero por rubro o centro de costo, y de situacion de fondos por
  prefijo de rubro y fuente. Migracion `cuipo/0003`.
- `cuipo/derivacion.py` resuelve cada fila del corte: concepto, fuente, seccion, situacion de
  fondos y tercero, con el origen de cada uno y lo que falta. Sin regla: seccion 16.0,
  situacion C y tercero 1 - NO APLICA.
- Pantalla **CUIPO -> Pendientes** por corte: recursos sin homologar, rubros sin concepto, BPIN
  sin PIIP y centros de costo en la seccion por defecto; con un boton para crear las 14 reglas
  iniciales del plan.
- En cada fuente CUIPO del admin se registran los recursos que la usan.

- Semillas: `cuipo/semillas.py` carga las homologaciones de fuentes y rubros validadas en el
  CUIPO del T3 (`Semillas_CUIPO_T3_2026.xlsx`, 62 recursos y 1 rubro), por comando
  (`cargar_semillas_cuipo`) o subiendo el libro en la pantalla de pendientes. Solo crea lo
  que falta. En local quedan 217 de 224 filas completas; faltan 7 recursos que no estan en
  las semillas (110, 125, 130, 160, 166, 35 y 91).
- Decision: la vigencia de gasto sera editable en la distribucion (fase 3), una o varias por
  fila, 1 por defecto.

**Pruebas.** 458, todas pasan (`cuipo/tests/test_derivacion.py` y `test_semillas.py`, 30 nuevas).

## 22. CUIPO, fase 3: distribucion por BPIN y precarga (13 de noviembre)

Rama `cuipo-fase3-distribucion`, sobre `cuipo-fase2-reglas`.

- `DistribucionBPIN`, `AsociacionFuenteProducto` y `LineaCUIPO` (con vigencia de gasto
  editable, 1 por defecto; una fila puede repartirse entre productos y vigencias). Migracion
  `cuipo/0004`.
- `cuipo/distribucion.py`: la precarga crea la distribucion de cada BPIN del corte con la
  regla del Power Query (un producto al 100 %, varios productos y un recurso por digitar
  desde el PIIP, manual, sin BPIN al producto 0) y los cualitativos por defecto o del
  trimestre anterior enviado. Solo corre sobre cortes del 1 de enero al cierre de un
  trimestre (periodo 10303, 10606, 10909 o 11212).
- Un corte con distribuciones no se reprocesa ni se borra.
- Admin: accion de precarga en los cortes y **Distribuciones por BPIN**, con el cuadre por
  fila y las lineas editables mientras llega la pantalla de la fase 4.

**Pruebas.** 477, todas pasan (`cuipo/tests/test_distribucion.py`, 19 nuevas).

## 23. CUIPO, fase 4: pantalla de distribucion por BPIN (13 de noviembre)

Rama `cuipo-fase4-pantalla`, sobre `cuipo-fase3-distribucion`. Sin migraciones.

- Pantalla **Distribuir** de cada distribucion: matriz de filas por productos con la
  diferencia contra SIIFWEB en vivo (HTMX, el que trae unfold), lineas por producto y
  vigencia del gasto, cualitativos por codigo con su origen, y los botones "Proporcional a
  compromisos" y "Todo a un producto". Muestra como referencia la distribucion enviada del
  periodo anterior del mismo BPIN.
- La logica de edicion va en `cuipo/distribucion.py`; el reparto proporcional cuadra al
  centavo por el metodo del mayor residuo.
- Solo se edita en borrador y con permisos sobre las lineas.
- La lista de distribuciones vacia explica que se crean con la precarga del corte.

**Pruebas.** 496, todas pasan (`cuipo/tests/test_pantalla.py`, 19 nuevas).

## 24. CUIPO, fase 5: validaciones y estados de la distribucion (13 de noviembre)

Rama `cuipo-fase5-validaciones`, sobre `cuipo-fase4-pantalla`. Sin migraciones.

- `cuipo/validacion.py`: errores que bloquean (fila que no cuadra al centavo, O > C o P > O en
  una linea, negativos, producto que no es del BPIN, cualitativos vacios o inactivos, lo que
  no deriva) y advertencias (CPC 0 en un concepto que exige CPC).
- Estados borrador -> validado -> enviado: solo se valida sin errores; una validada vuelve a
  borrador; una enviada no cambia. Lineas editables solo en borrador.
- Pantalla: panel de validacion en vivo y botones de estado. Admin: accion para validar varias.
- En la pantalla, CPC, detalle sectorial, tercero y politica publica pasan a listas
  desplegables con descripcion (CPC y tercero se buscan al escribir).

**Pruebas.** 518, todas pasan (`cuipo/tests/test_validacion.py`, 22 nuevas).

## 25. CUIPO, fase 6: plano CHIP y ajustes de la pantalla (13 de noviembre)

Rama `cuipo-fase6-plano`, sobre `cuipo-fase5-validaciones`. Sin migraciones.

- Pantalla Distribuir: se quitaron "Proporcional a compromisos" y "Todo a un producto" (el
  reparto es manual); los cualitativos se eligen en una ventana con buscador y la
  descripcion completa; cada fila muestra rubro, recurso y centro de costo con sus nombres
  completos y su concepto, fuente CUIPO y seccion; los productos con su nombre completo; y
  en globos de ayuda, las reglas de validacion y que significa cada estado. La vigencia del
  gasto tambien se elige con el buscador (cambiarla en la linea o repartir en otra).
- `cuipo/plano.py`: el bloque D_EJECUCION_DE_GASTOS de la inversion (encabezado, lineas de 15
  campos, resumenes por prefijo, enteros con mayor residuo por fila, agrupacion, sin ceros,
  orden vigencia -> seccion -> codigo) y su integracion en el plano completo de presupuesto
  (cambia solo las lineas 2.3 y el resumen 2 del bloque D).
- Pantalla **Plano** por corte: problemas, vista previa, descarga, integracion y "Marcar
  enviadas las validadas".

**Pruebas.** 534, todas pasan (`cuipo/tests/test_plano.py`, 18 nuevas).

## 26. CUIPO, fase 7: pruebas (13 de noviembre)

Rama `cuipo-fase7-pruebas`, sobre `cuipo-fase6-plano`.

- Los ayudantes de las pruebas del CUIPO pasan a `cuipo/tests/fabricas.py`.
- Prueba de punta a punta de 202500000039332 contra un plano esperado escrito a mano
  (`cuipo/tests/datos/plano_202500000039332.txt`), comparado byte a byte; `.gitattributes`
  conserva su fin de linea.
- Con esta fase quedan hechas las siete del plan del CUIPO (`PLAN_CUIPO.md`, seccion 5, con
  los pasos para usarlo en produccion).

- El enlace a las distribuciones pasa al menu **Seguimiento** como "Distribuciones por BPIN
  CUIPO" (sigue pidiendo el permiso de ver distribuciones: los roles del equipo no lo ven).

- Las homologaciones de fuente del T3 (62) pasan al boton de reglas iniciales de la pantalla
  de pendientes (`derivacion.FUENTES_T3_2026`); se quita el importador de semillas
  (`cuipo/semillas.py`, el comando `cargar_semillas_cuipo` y la carga del libro), porque es
  una carga de una sola vez.

- El enlace CUIPO -> Pendientes abre el corte mas reciente que cierra un trimestre (el que se
  distribuye), no el de fecha de fin mas reciente.

- Pendientes ya no lista los recursos sin fuente CUIPO ni los rubros sin concepto: solo los
  cuenta y enlaza a las listas de **Fuentes** y **Rubros** de SIIFWEB, que ahora traen la columna
  **Homologado** (si/no), la fuente o el concepto CUIPO, y los filtros "Homologado (CUIPO)" y
  "En el corte del CUIPO". La fuente cuenta como homologada si lo esta para la vigencia del corte
  que se reporta; el rubro, si tiene concepto valido por homologacion o por su mismo codigo.

- Pendientes ya no lista los BPIN con ejecucion sin formulacion PIIP: la lista de **Filas de
  ejecucion de gastos** trae la columna **Productos PIIP** (Si / No / No aplica para el BPIN 0),
  segun la tabla InfoGeneral, con su filtro. Sus valores (apropiacion definitiva, CDP, RP,
  obligacion y pago) van en formato de moneda, como en las demas listas.
- Boton para aplicar los filtros ("Apply Filters") en las listas del CUIPO con filtros
  desplegables y en Fuentes y Rubros.
- Se quita la pantalla **Pendientes** y lo que mostraba pasa a las listas: Cortes (columna
  "Filas completas"), Dependencias (columna "Seccion CUIPO" con filtros por seccion y por
  corte) y el boton "Crear las reglas iniciales" arriba de Homologacion de fuentes.
- La precarga toma solo los productos del PIIP con **meta distinta de cero en la vigencia del
  corte** (tabla InfoGeneral); un producto programado solo en otro anio no entra y la
  observacion lo dice. La validacion y la columna Productos PIIP de las filas usan el mismo
  criterio.
- La regla de la precarga cuenta **registros** del corte y no fuentes: varios productos y un
  registro queda por digitar desde AporteProductos; varios registros, manual. Migracion
  `cuipo.0005` (solo cambia las etiquetas de la regla; no toca datos).
- **Distribuciones por BPIN CUIPO** trae las columnas **Filas** (registros del corte del BPIN que
  entran al CUIPO) y **Productos programados** (del PIIP con meta en la vigencia del corte), que
  se pueden ordenar y filtrar; las opciones del filtro son las cantidades que hay y se pueden
  elegir varias a la vez (por ejemplo 2, 3 y 7 productos).
- Modelo nuevo **Recursos CUIPO** (`cuipo.RecursoCUIPO`, migracion `cuipo.0006`): descripcion,
  archivo (en `cuipo/recursos/` del bucket), fechas de creacion y actualizacion y activo. Esta en
  el menu CUIPO. Los activos aparecen en la ficha de distribucion, en "Recursos para el
  diligenciamiento". El enlace `/admin/cuipo/distribucionbpin/recursos/<id>/` pide un link
  firmado nuevo al abrir; lo usa quien ve las distribuciones (solo activos) o los recursos.
- **Nombres de archivo sin tildes en todas las cargas.** Supabase responde 400 (Bad Request) a
  las llaves con tildes o enes: un recurso llamado "Guia de diligenciamiento" con tilde no se
  podia guardar, y lo mismo pasaba con cualquier reporte, corte o lista CHIP. El almacenamiento
  ahora es `siifweb.almacenamiento.S3NombresSeguros` (en pruebas,
  `ArchivosLocalesNombresSeguros`), que limpia el nombre antes de guardar: sin tildes ni enes,
  espacios y simbolos a "_" y la extension en minusculas ("Guia ano 2026.PDF" con tildes queda
  "Guia_ano_2026.pdf"). Aplica a los FileField y a cualquier `save()` del almacenamiento. Los
  archivos que ya estan en el bucket no cambian.

- En la ficha de distribucion, la descripcion de lo elegido en CPC, detalle sectorial, tercero
  y politica publica se ve completa (antes se cortaba en dos lineas y el resto solo salia al
  pasar el cursor).
- **Obligaciones <= compromisos y pagos <= obligaciones en cada linea.** La validacion ya lo
  exigia con centavos. Faltaba el plano: redondea cada campo de la fila a pesos por separado, y
  una linea correcta con centavos podia quedar con obligacion mayor que su compromiso (C 1,40 y
  O 1,40 en una linea y C 1,60 y O 1,40 en la otra daban C 1 y O 2). `plano.respetar_orden` pasa
  ese peso a otra linea de la misma fila con margen; los totales no cambian. En la ficha, la
  casilla de obligaciones o pagos que rompe la regla se ve en rojo con su aviso al digitar.

**Pruebas.** 565, todas pasan (170 del CUIPO).

## 27. Detalle del proyecto y programacion financiera (19 de noviembre)

- **Detalle del proyecto sin textos de relleno.** Se quitan las descripciones de las secciones
  Proyecto y Responsables. La nota "Si registras aqui un proyecto nuevo..." pasa de la seccion
  Origen a un globo de ayuda al lado del BPIN (regla `.ayuda` en `static/css/admin_styles.css`).
- **Programacion financiera** (`siifweb.ProgramacionFinanciera`, migracion `siifweb.0023`):
  proyecto, vigencia, fuente de SIIFWEB, meta del plan y valor (20 digitos: 15 enteros y 5
  decimales), con sus fechas. Un valor por proyecto, vigencia, fuente y meta. El equipo programa
  a principios de anio o durante el anio cuanto va de cada fuente a cada meta; no se contrasta
  con SIIFWEB.
- **Valor programado del proyecto** (`Proyecto.valor_programado`, no editable): la suma de su
  programacion financiera en todas las vigencias. Lo recalculan las senales post_save y
  post_delete del modelo (tambien en un borrado masivo del admin). Se ve en el detalle del
  proyecto, seccion "Programacion financiera", con lo de cada vigencia.
- **Pantalla "Programacion financiera"**: boton en el detalle del proyecto (accion de detalle).
  Matriz con tres listados que arma el equipo: vigencias (un bloque cada una), fuentes (filas)
  y metas (columnas), con totales por fuente, por meta, por vigencia y del total. Se agregan
  con una ventana de busqueda con paginas (Anterior / Siguiente, 50 por pagina) y se quitan con
  la x. Al abrir salen las vigencias, fuentes y metas con valores y las metas en que el
  proyecto esta programado (Programacion de proyectos, por el BPIN), marcadas "programada".
  Nada se guarda hasta oprimir **Guardar**, que deja la programacion como se ve: crea, cambia y
  borra (vacios, ceros y lo quitado). Con un error en alguna casilla no se guarda nada y las
  casillas con error quedan en rojo. Hay aviso de cambios sin guardar. Punto para miles y coma
  para decimales. Ver pide `view_programacionfinanciera`; guardar, agregar, cambiar y borrar.
  Logica en `siifweb/programacion_financiera.py`.
- La lista **Programacion financiera** del admin (`/admin/siifweb/programacionfinanciera/`)
  muestra todos los valores, con filtros por vigencia y fuente. No esta en el menu.

**Pruebas.** 584, todas pasan.

