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

345 pruebas en catorce modulos (antes 186). Nuevos `test_pdf_ficha.py`, `test_plan_desarrollo.py`,
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
