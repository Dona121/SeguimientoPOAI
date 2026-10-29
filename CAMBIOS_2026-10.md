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

297 pruebas en trece modulos (antes 186). Nuevos `test_pdf_ficha.py`, `test_plan_desarrollo.py`,
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

**Pendiente de desplegar:** las migraciones `0011` a `0014`. El push las aplica en
Supabase; antes va la copia de seguridad de la base.
