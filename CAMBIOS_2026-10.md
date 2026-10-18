# Cambios de octubre de 2026

Lo que se agrego y corrigio en el proyecto de seguimiento POAI en esta tanda: saldo y
pagado en las obligaciones de la ficha, un filtro de fechas, el PDF de cada tabla, cinco
correcciones que salieron de una revision del codigo y la limpieza de `media/`. Commit
`5849e05` y el de esta documentacion.

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

## 4. Pruebas

215 pruebas en diez modulos (antes 186). Nuevo `test_pdf_ficha.py`. Las de cada
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
