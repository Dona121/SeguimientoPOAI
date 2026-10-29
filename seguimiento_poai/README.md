# Seguimiento POAI - SIIFWEB (Django)

Aplicacion oficial de seguimiento de proyectos: migra los reportes de SIIFWEB a un modelo
relacional y los cruza con el POAI. Base de datos SQLite (`db.sqlite3`).

Nacio como prueba de que los reportes de SIIFWEB caben en el modelo; verificada la
migracion (cero descuadres en las conciliaciones), pasa a ser el proyecto de trabajo.

**Alcance: seguimiento de proyectos.** Solo se modelan los reportes cuyas filas llevan
`PROYECTO`. Quedan fuera, por decision del equipo (no se hace auditoria de procesos
financieros):

| Fuera del modelo | Por que |
|---|---|
| Auxiliar de ingresos | No tiene proyecto: es el lado del recaudo, por rubro y fuente |
| Bitacora de comprobantes | Es el log del proceso financiero (apropiaciones, traslados, ajustes) |
| Cuentas por pagar | Figura de tesoreria; el "obligado sin girar" ya esta en `ObligacionImputacion.saldo_obli` |
| Ordenes de pago por estado | Estado del giro: proceso de tesoreria |

Resultado: **18 modelos y 5 reportes que descargar** (antes 23 y 9). Se van los dos
archivos pesados (ingresos con 417 mil filas, bitacora con 46 mil).

## Arrancar

```bash
uv run --directory seguimiento_poai python manage.py runserver 8010
```

Admin en http://localhost:8010/admin/, con un superusuario de la base local
(`manage.py createsuperuser` si no hay uno).

Ojo: si existe el `.env`, su `DATABASE_URL` apunta a produccion (Supabase). Para trabajar
contra la sqlite local hay que pasarla explicita, y sin `.env` tambien hacen falta una
`SECRET_KEY` cualquiera y `DEBUG=True` (sin DEBUG, Django redirige todo a HTTPS):

```bash
SECRET_KEY=desarrollo-local DEBUG=True DATABASE_URL="sqlite:///$PWD/seguimiento_poai/db.sqlite3" \
  uv run --directory seguimiento_poai python manage.py runserver 8010
```

Con el `.env` presente, la subida de reportes desde el admin va al bucket S3 de
produccion; sin el, falla por falta de llaves. Para revisar paginas no hace falta.

### Retomar en otra maquina

El codigo esta en GitHub, pero el `.env` y las memorias del asistente no: viven en
`respaldo_claude/` (sincronizada con MEGA, ignorada por git). El paso a paso —incluido
el de Linux, con la sintaxis de bash y las tres diferencias que muerden al cambiar de
sistema— esta en `respaldo_claude/COMO_RESTAURAR.md`.

## Cargar un reporte desde el admin

1. Cargas del reporte -> Anadir carga del reporte.
2. Elegir tipo (disponibilidades / compromisos / obligaciones / reservas / historial /
   SECOP II), vigencia y el archivo xlsx. Grabar. La vigencia se deja vacia en los dos de
   rango completo: historial y SECOP II.
3. En el listado, seleccionar la carga y ejecutar la accion
   **"Procesar los reportes seleccionados"**.
4. El resultado queda en las columnas `Estado` y `Resultado del proceso` del propio registro.

El mismo archivo no se puede cargar dos veces: se detecta por hash SHA-256 y el formulario
muestra el error antes de guardar.

### Procesar todos a la vez o uno por uno

Subir y procesar son dos pasos separados. Al grabar, la carga queda **pendiente**; no se
migra hasta correr la accion.

**Se pueden subir todos los reportes en cualquier orden, seleccionarlos todos y procesarlos
de una sola pasada.** La accion no respeta el orden de seleccion ni el de creacion: ordena
ella misma por lo que exigen los FK, con
`order_by(F("vigencia").asc(nulls_last=True), "_orden", "id")`, donde `_orden` es la
posicion del tipo de reporte en `cargas.ORDEN_DE_CARGA`. Es decir, vigencia ascendente;
dentro de cada vigencia CDP -> compromisos -> obligaciones -> reservas; y al final los de
rango completo (historial y SECOP II), que enganchan con lo ya cargado.

> Antes habia que hacerlo en dos pasadas -los cuatro consolidados juntos y despues el
> historial- por dos razones que ya no aplican: se ordenaba solo por `vigencia`, y donde
> caen los nulos depende del motor (SQLite los pone primero, PostgreSQL al final), de modo
> que sobre SQLite el historial corria ANTES que los consolidados; y el desempate dentro de
> una vigencia era el `id`, asi que subir la obligacion antes que su CDP la procesaba en
> ese mismo orden y las imputaciones sin RP se descartaban.

Saltarse uno no obliga a ir de a uno: el proceso es idempotente (recargar reemplaza), asi
que se puede agregar el que falto y volver a correr la accion sobre todos, o solo sobre ese.

## Cargar desde consola

```bash
uv run python manage.py cargar_reporte cdp 2025 "C:\ruta\consolidado.xlsx"
uv run python manage.py validar --vigencia 2025
```

## Formato crudo de SIIFWEB

**Los xlsx se cargan tal cual los genera la plataforma: no hace falta pre-formatearlos.**
El cargador se escribio para ese formato crudo. Lo que emite SIIFWEB:

| Aspecto | Como llega | Como lo maneja la carga |
|---|---|---|
| Codigos (`NRO_*`, `NIT`, `PROYECTO`/BPIN, `FONDO`, `TERCERO`, centros) | `int` — p. ej. `PROYECTO=202500000034777` | `texto()` -> `str(int)`, sin `.0` |
| Valores en $ | `str` con **coma decimal** y sin separador de miles: `'1855247059,44'`; enteros tambien como texto | `decimal()` cambia `,` por `.`; si llegara separador de miles, el decimal es el ultimo signo (`'1.234,56'` = `'1,234.56'`) |
| Fechas | `str`, con **el anio mezclado**: `'05/01/2026'` en los consolidados y `'02/01/26'` / `'13/12/22'` en reservas e historial | `fecha()` prueba `%d/%m/%y`, `%d/%m/%Y`, `%Y-%m-%d` |
| Historial | filas de cabecera de contrato con las columnas presupuestales en `None` | los cargadores usan `.get()` y descartan filas totalmente vacias |

Ojo: como el `NIT` llega en `int`, la plataforma ya descarto cualquier cero a la izquierda
en origen — no es algo que introduzca la carga.

Verificado sobre los cinco reportes crudos de 2026 (corte 20260720, **67.000+ filas**):
cero fallos de parseo en valores y fechas, ningun codigo con `.0` ni notacion exponencial,
y todas las claves duras (`f["..."]`) presentes en su archivo. Los unicos valores que
quedan en `0` son ceros reales (saldos ya ejecutados), no errores de conversion.

**Un valor monetario ilegible aborta la carga** (`ValueError: Valor monetario ilegible:
'N/A'`) y la transaccion no deja nada a medias. Antes se volvia cero en silencio: la carga
salia bien y el descuadre aparecia despues sin causa visible. El cambio se verifico sobre
1.123.428 valores de 29 reportes reales: ninguno ilegible y el mismo resultado de antes en
todos.

> Nota historica: los primeros archivos que se probaron venian con algunos tipos ya
> formateados (valores como numero, fechas como fecha). Ese paso era innecesario; el crudo
> entra igual.

## Flujo de trabajo del equipo

**La vigencia en curso se recarga cada vez que haga falta.** Cada carga REEMPLAZA a la
anterior: antes de insertar, se borran las imputaciones de esa vigencia y ese tipo de
reporte. Sin eso las lineas se acumularian y los valores saldrian duplicados — las
cabeceras estan protegidas por su UniqueConstraint, pero las imputaciones no.

Las cabeceras (Cdp, Compromiso, Obligacion, Reserva) no se borran: se actualizan en sitio
con `bulk_create(update_conflicts=True)`. Borrarlas romperia los documentos que las citan
(un RP apunta a su CDP). El mensaje de la carga informa cuantas imputaciones reemplazo.

El historial de contratos se descarga por rango completo, asi que se reemplaza entero.

**El equipo registra proyectos nuevos antes de que llegue la ejecucion.** Se crean desde
Proyectos -> Anadir, con su BPIN, nombre, dependencia responsable y clasificacion. Cuando
despues se carga un reporte:

- La carga **busca por BPIN** y engancha la ejecucion al registro que ya existe: no crea
  un duplicado.
- **No sobreescribe** lo que escribio el equipo: el nombre solo se rellena si esta vacio.
- El campo `origen` distingue los tres casos (ingresado por el equipo / detectado en un
  reporte / cruce POAI), se ve como etiqueta en el listado y sirve de filtro.
- El mensaje de la carga avisa cuantos proyectos del equipo estrenaron ejecucion y cuantos
  BPIN nuevos trajo el reporte.

El BPIN se normaliza al guardar (sin espacios, sin sufijo `.0`), asi que da igual si se
teclea o se pega desde Excel: siempre cruza. Verificado con `prueba_flujo_equipo.py`.

## Orden de carga (importante)

Los FK exigen que el padre exista antes que el hijo. Primero, **por cada vigencia y en
orden ascendente** (2024 antes que 2025):

1. `cdp` de la vigencia
2. `compromisos` de la vigencia (apuntan a los CDP)
3. `obligaciones` de la vigencia (apuntan a los RP; si el RP no esta en su vigencia se
   busca en v-1, que es ejecucion de reserva)
4. `reservas` de la vigencia v (apuntan a los **CDP de v-1**)

Y despues, una sola vez, los dos que se descargan por **rango completo** y no llevan
vigencia:

5. `historial` — engancha con los RP de **todas** las vigencias cargadas
6. `secop` — va de ultimo: engancha por BPIN y **no crea proyectos**, asi que cuantos mas
   proyectos haya en el catalogo, menos BPIN quedan sin enganchar

| Reporte | Vigencia | Depende de |
|---|---|---|
| `cdp` | por vigencia | — |
| `compromisos` | por vigencia | los CDP de esa vigencia |
| `obligaciones` | por vigencia | los RP de esa vigencia (y de v-1) |
| `reservas` | por vigencia | los CDP de v-1 |
| `historial` | rango completo | los RP de todas las vigencias |
| `secop` | rango completo | el catalogo de proyectos (por BPIN) |

## El historial de orden de gasto

Se descarga por **rango completo**, no por vigencia (el contrato cruza anios), asi que la
vigencia se deja vacia:

```bash
uv run python manage.py cargar_reporte historial rango "C:\ruta\historial_ordengasto2_...xlsx"
```

Una sola sabana se parte en tres tablas segun que columnas trae cada fila:

| Fila con... | Va a | 2022-2026 |
|---|---|---|
| solo datos del contrato | `Contrato` (ficha, con interventor) | 9.776 |
| `VALOR_PAGO` | `ContratoActa` (fecha y valor del pago) | 32.874 |
| `NRO_COMPROBANTEPPTAL` | `ContratoImputacion` (rubro, fuente, proyecto) | 10.099 |

La imputacion engancha al RP por `(PREFIJO, NRODOC)` -> `(vigencia, nro_rp)`. Con las
cinco vigencias cargadas: **10.092 de 10.099 (99,9%)**, 100% en cada vigencia de 2022 a
2026. Los 7 restantes son de 2021 (vigencia no cargada) y un huerfano conocido de 2024.

Es la unica fuente que da: interventor, el calendario de actas de cada contrato, y el
vinculo contrato -> proyecto directo (incluidos los convenios que la orden de gasto no trae).

## Cruce POAI (ya no se carga)

**Se dejo de cargar en octubre de 2026.** La dependencia responsable y las
clasificaciones de cada proyecto las mantiene ahora el equipo en el admin (Proyectos y
Configuracion y parametrizacion). El tipo de reporte sigue en el modelo para que la carga
de julio se lea con su nombre, pero el formulario no lo ofrece y no tiene cargador; los 79
proyectos que creo conservan su origen "Cruce POAI". Lo que sigue describe como funcionaba
y de donde salieron esos datos.

El archivo `CruceProyectosPOAI-GESPROYPIIP-PI` no es de SIIFWEB: viene del banco de
proyectos y solo alimenta el catalogo `Proyecto`. Se descarga sin vigencia (cubre varias)
y se lee la hoja **Completo**.

Trae una fila por indicador y vigencia, asi que cada BPIN se repite: **194 proyectos en
380 filas**. Los atributos del proyecto son identicos en todas las filas de un mismo BPIN
-verificado en las dos hojas-, de modo que la carga deduplica quedandose con la primera.

| Campo | Regla de escritura |
|---|---|
| `nombre` | Solo si SIIFWEB no lo trajo: el historial de contratos manda |
| `dependencia_responsable` | SIIFWEB no lo tiene; el POAI es la fuente y siempre actualiza |
| `clasificacion` | Igual: POAI 2026, regalias, vigencias futuras, recursos del balance... |

`dependencia_responsable` es un campo aparte de `dependencia` a proposito: la de SIIFWEB
es **quien ejecuta el gasto** y la del POAI **quien responde por el proyecto**, y difieren
en 18 casos (ej. SIIFWEB "Subsecretaria De Gestion De La Inclusion" vs POAI "Mujer,
Juventud e Inclusion Social").

Resultado de la carga: 142 nombres completados, 388 campos POAI escritos y **79 proyectos
nuevos** que estan en el POAI pero no tienen ninguna ejecucion en SIIFWEB — la mayoria
regalias, que se ejecutan por fuera del presupuesto departamental.

## Enriquecimiento de catalogos entre reportes

Un mismo catalogo aparece en varios reportes con distinta calidad de datos, y la carga
completa lo que falta en vez de quedarse con el primero que llego:

| Catalogo | Llega vacio desde | Se completa desde |
|---|---|---|
| `Proyecto.nombre` | los consolidados (solo BPIN) | historial (`NOMBRE_PROYECTO`) |
| `Proyecto.dependencia` | los consolidados | historial (`ID_CENTROCOSTO`) |
| `Tercero.nombre` | los consolidados (solo NIT) | reservas e historial |
| `Rubro.nombre` / `Fuente.nombre` | el reporte que lo cree primero | cualquiera que traiga el nombre |
| `Rubro.tipo` | — | se infiere del codigo: `1.x` ingreso, `2.x` gasto |

Resultado medido: **408 de 498 proyectos ganaron nombre y 416 su dependencia**, que los
consolidados no traian. La regla es conservadora: solo rellena campos vacios, nunca
sobreescribe un dato ya cargado.

## Resultado de la prueba

Cargado completo: cdp, compromisos y obligaciones de **2022 a 2026**, reservas de 2024 a
2026 y el historial de contratos 2022-2026.

| Vigencia | CDPs | RPs | Obligaciones | Reservas | Certificado | Obligado |
|---|---|---|---|---|---|---|
| 2022 | 2.125 | 7.253 | 12.445 | - | 952.295.694.315 | 807.789.446.196 |
| 2023 | 1.819 | 7.021 | 12.180 | - | 1.166.874.131.540 | 963.149.912.183 |
| 2024 | 1.769 | 7.312 | 11.724 | 15 | 1.289.994.759.727 | 1.077.380.363.710 |
| 2025 | 1.674 | 7.459 | 13.017 | 48 | 1.324.418.038.322 | 1.172.762.907.963 |
| 2026* | 776 | 4.291 | 7.376 | 51 | 819.678.337.506 | 566.104.053.406 |

\* 2026 corta al 15 de julio: vigencia en curso, no son saldos de cierre.

Las conciliaciones dan **cero descuadres en las cinco vigencias**, y el salto temporal de
reservas cuadra al 100% (16 de 16 en 2024, 52 de 52 en 2025, 56 de 56 en 2026).

Con todas las vigencias cargadas, el historial engancha **10.092 de 10.099 imputaciones
al RP (99,9%)**: 100% en 2022-2026 y solo 7 sin RP (6 de 2021, vigencia no cargada, y el
huerfano conocido de 2024).

La excepcion de 2023 quedo visible en la base: **35 obligaciones causadas contra RPs de
2022**, que son ejecucion de reservas mezclada en el consolidado ordinario.

Los totales coinciden al peso con los verificados en polars sobre los mismos archivos.

La seccion 6 mide el alcance real del seguimiento: **el resto de las imputaciones es
funcionamiento** (`PROYECTO = 0`), que no se sigue por proyecto. Al perder la bitacora se
pierde tambien la verificacion cruzada contra una fuente independiente; quedan las
identidades internas y la conciliacion padre-hijo, que siguen dando cero descuadres.

## Vista principal: el proyecto

`Proyectos` es la entrada del admin. El listado muestra certificado, obligado y una barra
de avance por proyecto; cada fila tiene enlace a su ficha.

**Detalle del proyecto**: solo los datos del proyecto — BPIN, nombre, dependencias,
clasificaciones y origen. Nada mas. Tuvo seis inlines (disponibilidades, compromisos,
obligaciones, contratos, reservas y SECOP II) recortados a 20 filas cada uno, y se
quitaron: repetian a medias lo que la ficha muestra completo y agregado.

**Ficha de ejecucion** (boton en el detalle, o el enlace del listado): una vista propia,
hecha con una changeform action de unfold, porque los inlines muestran filas sueltas y
aqui hace falta agregacion. Se divide en **dos pestanas sobre la misma URL**
(`?panel=siifweb|secop`), cada una enlazable y calculada solo cuando se abre.

Panel **SIIFWEB**:

- Cuatro tarjetas con el total de cada etapa de la cadena.
- Tabla de ejecucion **por vigencia**: certificado, comprometido, obligado, pagado, y los
  dos saldos (sin comprometer, sin obligar) con barra de avance.
- **Filtro de fechas** (desde / hasta) sobre las tres tablas de documentos. Cada una se
  corta por su propia fecha: CDPs por la de disponibilidad, RPs por la de registro y
  obligaciones por la de obligacion. Los limites se incluyen. Las tarjetas, la cadena por
  vigencia y las demas secciones no se filtran: siguen mostrando todo el proyecto. El
  filtro queda en la URL (`?desde=...&hasta=...`), asi que la ficha filtrada se comparte
  con el enlace.
- CDPs y RPs del proyecto, con su objeto y su valor.
- **Obligaciones**: vigencia, numero, fecha, beneficiario, NIT, objeto, tipo de orden de
  gasto, valor definitivo, **saldo** y **pagado**. El objeto sale de `OBJETO_OBLIG` (el
  consolidado paso de 25 a 27 columnas y ahora trae objeto, NIT y beneficiario); si una
  obligacion se cargo antes de que ese campo existiera, se muestra el objeto del RP contra
  el que se causo, resuelto por subconsulta para no multiplicar filas. Saldo y pagado son
  `SALDO_OBLI` y `PAGOS` del mismo consolidado (valor = saldo + pagado en todas las filas);
  suman sobre la misma relacion que el valor, asi que comparten el join y no se multiplican.
- Las fechas de CDPs, RPs y obligaciones van en el formato regional (`4 de Julio de 2025`).
- **PDF por tabla**: cada titulo (CDPs, RPs, Obligaciones) tiene a la derecha un
  "Descargar PDF" que baja solo esa tabla, con el filtro de fechas que este aplicado. Ver
  la seccion siguiente.
- Fuentes de financiacion, con lo comprometido por cada una.
- Contratos del proyecto con contratista, valor, numero de actas y pagado real.
- **Calendario de pagos**: cada acta del contrato con su fecha, tipo, numero y contratista.
- Reservas, con el CDP de origen de la vigencia anterior, su obligado y su saldo.

Panel **SECOP II**: procesos en tramite y contratos electronicos del BPIN (ver la seccion
de SECOP II). Cada fila abre un modal con el detalle, para no sacar al usuario de la ficha.

Implementacion: `@action(url_path="ficha-ejecucion")` + `actions_detail`, devolviendo un
`TemplateResponse` con `admin_site.each_context()` sobre una plantilla que extiende
`admin/base.html`, asi conserva la barra lateral y el tema de unfold. La URL propia se
registra ANTES de las del admin en `get_urls()`, porque `<path:object_id>/` las capturaria.

Un detalle que costo encontrar, y que aparecio dos veces: sumar dos relaciones a la vez
con `Sum()` **multiplica las filas**. El pagado de un contrato y el total del calendario
salian al doble porque el contrato tenia 2 imputaciones para ese proyecto y el join las
cruzaba con sus actas. Se resuelve con `Subquery` (helper `suma_de`) o filtrando por una
subconsulta de ids. Es el mismo problema del grano que cuidamos al cruzar los reportes.

### PDF de cada tabla

`?panel=siifweb&tabla=cdps|rps|obligaciones&descargar=pdf` (mas `desde`/`hasta` si hay
filtro) devuelve el PDF de esa tabla; otra `tabla` da 404. Lo arma `siifweb/pdf_ficha.py`
con ReportLab, a partir de **las mismas consultas** que dibuja la pantalla
(`ProyectoAdmin._documentos_filtrados`), asi que el reporte y la ficha no pueden diferir.

- Hoja carta horizontal. Encabezado con el BPIN, el nombre, la **dependencia responsable
  (POAI)**, el periodo y la fecha de generacion; pie con "Pagina X de Y".
- La tabla con las mismas columnas y totales de la pantalla, bordes en todas las celdas y
  encabezados centrados. El encabezado se repite en cada pagina.
- Fuente **Carlito**, la version abierta de Calibri (mismas formas y medidas). Calibri es
  de Microsoft: no esta en el servidor Linux de Railway y su licencia no deja subir el
  archivo al repositorio. Carlito (licencia OFL) vive en `siifweb/fuentes/` y queda
  incrustada en el PDF, asi que se ve igual en local y en produccion.
- ReportLab y no una conversion de HTML: es Python puro y no pide librerias del sistema.
- Medido sobre el proyecto con mas documentos (1.880 obligaciones): el PDF completo sale
  en unos 3 segundos; con un mes de filtro, en menos de uno.

## Avance financiero

`Seguimiento -> Avance financiero` (antes "Dashboard"). Responde una sola pregunta: **como va la
gestion de cada dependencia respecto a sus proyectos.**

Una fila por dependencia responsable (POAI), ordenada por lo comprometido, con cuatro
bloques: cuantos proyectos tiene asignados y en cuantos se movio cada etapa, cuantos
documentos se expidieron, los montos, y la contratacion en SECOP II. Al hacer clic en una
dependencia, debajo aparece la misma tabla por proyecto, y el nombre del proyecto abre su
ficha.

**Solo entran los proyectos con dependencia responsable asignada.** Hoy son 194 de 688: el
resto no tiene a quien atribuirle la gestion. El recorte va en el SQL de cada etapa, no
despues en Python, porque los otros 494 arrastran casi toda la ejecucion.

**Los tramites cancelados quedan fuera**: un proceso o un contrato cancelado no es gestion,
no hay nada que ejecutar. Ademas es donde vive la basura de la fuente: los 25 contratos
cancelados de estos proyectos suman $1.563 **billones** contra $87 mil millones de los
1.306 vigentes, y los dos contratos con valor imposible del DNP estan justamente
cancelados.

### Por que una fila puede salir en cero

Casi siempre porque el periodo elegido es posterior a lo cargado: los reportes entran por
tandas y a fin de agosto la ultima carga puede llegar a julio. La pagina lo dice sola —la
leyenda muestra "datos cargados hasta el ...", y un periodo sin movimientos sale con un
aviso en lugar de una tabla de ceros mudos—. Lo mismo pasa hacia atras: los proyectos con
dependencia responsable no registran nada en 2022 ni 2023, casi nada en 2024-2025 y
concentran su ejecucion en 2026.

### Los slicers

Atajos de periodo (esta semana, este mes, este trimestre, este ano), rango libre
desde/hasta, chips de vigencia, y filtros por dependencia y por clasificacion.

Los atajos se calculan con la fecha de Bogota (`timezone.localdate()`), no con la del
servidor: Railway corre en UTC y desde las 7 p. m. `date.today()` ya da el dia siguiente.
Una fecha bien formada pero imposible en la URL (`2025-13-45`) se ignora en vez de dar 500
(helper `fecha_del_get`, que usa tambien la ficha).

Lo que hace util el corte es que **cada etapa se filtra por su propia fecha**:

| Metrica | Fecha que la corta |
|---|---|
| CDPs y disponibilidad | `Cdp.fecha_disp` |
| RPs y comprometido | `Compromiso.fecha_reg` |
| Obligaciones, obligado y pagado | `Obligacion.fecha_obli` |
| Actas de pago | `ContratoActa.fecha_pago` |
| Procesos de SECOP | `ProcesoSecop.fecha_publicacion` |
| Contratos de SECOP | `ContratoSecop.fecha_firma` |

Asi, "del 1 al 7 de marzo" responde que se movio esa semana, y no que documentos
pertenecen a un lote. Los **proyectos asignados** son la excepcion a proposito: no
dependen del periodo, porque la comparacion que importa es "tiene 12 proyectos y esta
semana no se movio ninguno".

### Dos decisiones que conviene recordar

- **Pagos son dos cosas distintas y se muestran las dos.** *Actas de pago* son los giros,
  lo unico con fecha de pago propia; *Pagado* es el valor pagado de las obligaciones. El
  valor del acta no se puede sumar por dependencia: el camino hasta el proyecto pasa por
  las imputaciones del contrato y un contrato con dos imputaciones repetiria cada acta.
  Por eso las actas solo se cuentan (`distinct`) y el dinero sale de las obligaciones.
- **El valor de SECOP tampoco se puede sumar en la consulta**: un contrato que financia
  dos BPIN sale en dos filas de `BpinProceso`. Se piden las parejas (grupo, contrato,
  valor) distintas y se suman en Python. Ademas, la fila marca con un triangulo cuando
  arrastra alguno de los contratos con **valor imposible** que trae la fuente: hoy no
  aparece ninguno, porque los dos que hay estan cancelados, pero la marca queda para el
  proximo. Y un contrato que financia proyectos de dos dependencias cuenta en las dos: el
  total de la tabla es la suma de las filas, asi que puede superar el numero de contratos
  distintos (en la base real pasa con uno, de $877 millones).

El calculo vive en `siifweb/tablero.py`: una consulta agregada por etapa, cruzadas en
Python por la llave. Nunca dos `Sum` sobre joins distintos.

Para comprobarlo contra la base cargada, `uv run --directory seguimiento_poai python
prueba_tablero.py` recalcula cada metrica con consultas escritas aparte, rango por rango,
y muestra hasta que fecha llegan los datos.

## Plan de desarrollo y metas (traidas de SUTEC)

El catalogo de metas del plan de desarrollo, que vivia en SUTEC: el plan, sus lineas
estrategicas, sectores, programas e indicadores del PDD; la cadena MGA del DNP (sector,
programa, producto e indicador); los ODS; y las **436 metas** con sus **1.744 vigencias**
(2024 a 2027). Trece modelos al final de `siifweb/models.py`.

- `0011_metas_del_plan` crea las tablas y `0012_datos_de_las_metas` carga los datos del
  volcado de produccion de SUTEC del 21/09/2026, con sus id y sus fechas. La `0012` enlaza
  cada meta con su `DependenciaResponsable` **por el nombre**; si alguno no existe, lo crea
  y avisa en la salida de `migrate` ("Dependencias que no existian y se crearon").
- La meta cuelga solo de su programa: el sector, la linea y el plan suben desde el
  (`meta.sector_pdd`, `meta.linea_estrategica`, `meta.plan_desarrollo`).
- Sus indicadores PDD tienen que ser del programa. Lo vigila una senal sobre la relacion y,
  en el admin, el formulario de la meta (`MetaIndicadorForm`), que lo avisa en el campo y
  no como un 500. El modelo juzga los indicadores que se van a guardar, no los de la base:
  cambiar programa e indicadores a la vez no da un error falso.
- Las decisiones de diseno y los pasos de la integracion estan en
  `modelos-metas/PLAN_METAS_PDD.md` (carpeta fuera de git hasta desplegar).

**El listado de Metas** va de menor a mayor (MT001, MT002...), con la meta del cuatrienio
en el formato de la ficha (1.500, no 1500,000). El orden esta en el admin
y no en el `Meta` del modelo, para no tocar la `0011`. Cada meta tiene a la izquierda una
flecha que despliega sus **proyectos programados** (BPIN, proyecto, vigencia, meta de la
vigencia y tipo de banco), como el subformulario del Access; es un `TableSection` de
unfold (`list_sections`), con los proyectos de toda la pagina traidos en una consulta.

Filtros, en el orden de las dos jerarquias: la **MT** (texto: "MT323", o "MT32" para
varias), linea estrategica, sector, programa e indicador PDD; sector, programa, producto
e indicador MGA; dependencia responsable y estado.

### Ficha de la meta

Desde el icono de carpeta del listado o el boton del detalle. Una vista propia
(`MetaIndicadorAdmin.ficha_meta`, plantilla `ficha_meta.html`), como la del proyecto:

- Encabezado: codigo, indicador MGA, descripcion, la ruta en el plan (plan › linea ›
  sector › programa), dependencias responsables y ODS.
- Tarjetas: meta del cuatrienio, meta en las vigencias, programado por los proyectos y
  numero de proyectos.
- **Meta y programacion por vigencia**: la meta del plan, lo programado por los
  proyectos y los proyectos (con cuantos no traen valor); el porcentaje de avance se quito
  porque resultaba confuso (ver abajo). Cada
  vigencia despliega sus proyectos, con el nombre completo; cada proyecto abre un
  **modal** con sus municipios, vigencias, observaciones y **todas las metas en que esta
  programado** (meta, vigencia y programacion, con la de la ficha resaltada), sin salir
  de la ficha. Lo programado sin vigencia va en una fila "Sin vigencia".
- **Ejecucion en SIIFWEB** de los proyectos programados, en la misma tabla y en cada
  proyecto del desplegable: comprometido, obligado, pagado y reservas, cruzando el BPIN del
  proyecto con el `Proyecto` de SIIFWEB y la vigencia de la programacion con la del
  documento. Las reservas de una vigencia son los compromisos de la vigencia anterior que
  quedaron sin obligar y pasaron a ese ano. Cada BPIN cuenta una vez por vigencia. Es la plata del proyecto
  completo, no la parte de esta meta: SIIFWEB no la separa por meta.
- En el modal, si el BPIN esta en SIIFWEB: comprometido, obligado y pagado de todas las
  vigencias y el boton **Abrir la ficha de ejecucion**. Y un campo para **agregar una
  observacion** con la fecha del dia, que se guarda sin recargar la pagina
  (`ProgramacionProyectosAdmin.agregar_observacion`, por POST con su token CSRF); solo lo
  ve quien puede crear observaciones.
- **Programar proyecto** (boton del encabezado): un modal que programa en la meta un
  proyecto **existente** (buscador por BPIN o nombre, con el BPIN exacto primero y la marca
  de los que ya estan en la meta) o uno **nuevo** (BPIN, nombre, tipo de banco y
  municipios). Lleva filas de meta, vigencia y meta de la vigencia: la primera es la de la
  ficha y se pueden agregar otras metas; y una observacion opcional con la fecha del dia.
  Todo o nada: si una fila falla no se guarda ninguna. Para no duplicar, un proyecto nuevo
  no puede repetir un BPIN ni un nombre (comparado sin mayusculas, tildes ni signos), y un
  proyecto no se programa dos veces en la misma meta y vigencia. Al guardar, la ficha se
  recarga con esa vigencia desplegada. Rutas: `programar/` y `buscar-proyectos/` del
  admin de la meta. El formulario completo queda como enlace dentro del modal.
- **Editar** en el modal del proyecto: BPIN, nombre, tipo de banco y municipios y, con los
  permisos de crear, cambiar y borrar programaciones, sus filas de meta, vigencia y meta de
  la vigencia (la que se quita se borra; las del Access sin vigencia la conservan). Las
  mismas reglas que al programar; el BPIN y el nombre solo se comparan con los demas si
  cambian. Al guardar, la ficha se recarga con la vigencia desplegada y el proyecto
  abierto. Ruta: `editar-desde-ficha/` del admin de la programacion; lo ve quien puede
  cambiar proyectos programados.

Ojo al comparar meta y programado: lo programado es la suma de lo que el Access dice que
aporta cada proyecto. En las metas viales supera la meta (MT323: 10,75 contra 3 en 2024),
y hay proyectos con el mismo valor
en dos o tres vigencias; si el Access repetia la meta total del proyecto cada ano, la suma
la infla. Esta por confirmar con quien llevaba el Access.

## Programacion de proyectos (traida del Access "Seguimiento PDD STO")

La tabla `tblProyectos` del Access: cada fila era un proyecto en una meta y una vigencia,
con la meta del proyecto para ese ano. Cinco modelos:

| Modelo | Que guarda |
|---|---|
| `ProgramacionProyectos` | El proyecto: BPIN (20), nombre, tipo de banco, municipios y vigencias ("2024, 2025") |
| `ProgramacionMeta` | El proyecto en una meta (`MetaIndicador`) y una vigencia, con la meta de la vigencia (decimal, 5 decimales) y el `Id` de su fila en Access |
| `ObservacionProyecto` | Observaciones individuales del proyecto, con fecha |
| `TipoBanco` | Banco Territorial, de Gestiones, de Regalias, de Aliados |
| `Municipio` | Los 26 de Sucre, mas "Todo el departamento" |

No es el `Proyecto` de SIIFWEB: muchos no tienen BPIN (iniciativas por gestion, recursos
propios), asi que el BPIN es solo un dato. Las vigencias del proyecto se recalculan de sus
programaciones al guardar en el admin (`actualizar_vigencias()`), por eso salen de solo
lectura. En el admin, las programaciones y las observaciones son tablas dentro del proyecto.

`0013_programacion_de_proyectos` crea las tablas y `0014_datos_programacion_proyectos`
carga los datos. La `0014` la escribe `modelos-metas/generar_migracion_proyectos.py` a
partir del Access, para que el despliegue no dependa del archivo; no se edita a mano. Las
reglas de limpieza, acordadas el 29/10/2026:

| Caso | Regla |
|---|---|
| Que filas son el mismo proyecto | BPIN + nombre limpio (espacios y bordes, sin distinguir mayusculas ni tildes); sin BPIN, por el nombre. Se guarda la escritura mas repetida |
| BPIN escrito como texto ("Por Gestion", "Recursos Propios"...) | BPIN vacio y el texto a una observacion |
| "TODO EL DEPARTAMENTO", "Departamento de Sucre" | El municipio "Todo el departamento" |
| Municipio que no se reconoce ("SAN ANDRES") | A una observacion |
| "Sin Tipo de Banco" | Tipo vacio. Dos bancos, o bancos distintos entre filas: el mas repetido, y los demas a una observacion |
| Observaciones de Access | Sin fecha; las nuevas llevan la del dia |
| Meta que no esta en el catalogo (MT465, MT468) | Sin programacion; queda como observacion |
| Filas repetidas exactas | Una sola |
| Filas sin BPIN ni nombre (12, vacias) | No se cargan |

Resultado contra el Access, fila por fila: **1.265 proyectos, 1.609 programaciones y 539
observaciones**, sin diferencias de meta, vigencia ni valor. Las 17 filas sin programacion
son las 12 vacias, 3 repetidas y las 2 de metas fuera del catalogo. La meta de la vigencia
lleva 5 decimales porque hay metas viales con cuatro (3,0976 km): entran exactas.

### Despliegue pendiente

Las migraciones `0011` a `0014` no estan en produccion. En Railway el `preDeployCommand`
corre `migrate`, asi que **hacer push es aplicarlas en Supabase**: antes va la copia de
seguridad de la base (paso 6 de `PLAN_METAS_PDD.md`). Y con el `.env` presente, cualquier
`migrate` local sin `DATABASE_URL` explicita tambien va contra Supabase.

## Reportes

`Seguimiento -> Reportes` abre un indice con tres reportes. Cada uno tiene su pagina, con
sus filtros, el boton **Descargar Excel** y la lista de sus columnas:

| Reporte | Una fila por... | Filtros |
|---|---|---|
| Reporte Financiero del proyecto | proyecto y vigencia: CDP, compromiso, obligacion, reserva y contratacion | vigencia, BPIN, nombre |
| Plan indicativo | meta: su lugar en el plan, la cadena MGA y la meta fisica de cada ano | MT, linea, sector PDD, dependencia responsable |
| Proyectos programados | proyecto, meta y vigencia: la meta del plan y lo que aporta el proyecto | vigencia, MT, linea, sector PDD, dependencia, tipo de banco, BPIN, nombre |

El Plan indicativo y Proyectos programados siguen la estructura de las consultas `qryPI` y
`qryProyectos` del Access, con las columnas que hay en los modelos. Quedan fuera las que
no se trajeron de SUTEC (meta agrupada, serie, linea base, unidades de medida, ano base,
fuente, meta del indicador de resultado, tipo de acumulacion, observaciones) y la
Ejecucion por ano, que `tblProyectos` ya no tenia.

Cada reporte se define en `ProyectoAdmin._reportes` (filtros, columnas, constructor y
permiso) y comparte la plantilla `reporte.html`; los constructores estan en
`siifweb/reportes.py` (`construir`, `construir_plan`, `construir_proyectos`) y el Excel sale
de `a_excel`, que sirve para cualquier juego de columnas. Las metas van con formato
General: 15 y no 15,00000; 3,0976 completo. El indice solo muestra los reportes que el
usuario puede abrir: el Plan indicativo pide el permiso de metas y Proyectos programados el
de programacion, que los roles del equipo todavia no tienen.

## El admin (django-unfold)

Interfaz con [django-unfold](https://unfoldadmin.com/): barra lateral por modulos,
filtros desplegables, rangos de fecha y badges de estado.

| Seccion de la barra | Que tiene |
|---|---|
| Usuarios | Roles y usuarios |
| Seguimiento | Proyectos, Avance financiero, Reportes, Metas y Programacion de proyectos |
| Plan de Desarrollo | Planes, lineas estrategicas, sectores, programas e indicadores PDD; vigencias de las metas; sector, programa, producto e indicador MGA; ODS y metas ODS |
| SIIFWEB | CDP, RP, obligaciones, reservas, contratos, actas de pago, terceros, rubros, fuentes, dependencias y clasificaciones |
| Contratacion | Contratos, procesos y BPIN por proceso de SECOP II |
| Configuracion y parametrizacion | Dependencias responsables, cargas del reporte, tipos de banco y municipios |

**Los inlines muestran la cadena completa sin salir de la pagina.** Cada documento
trae las tablas relacionadas como pestanas:

| Al abrir un... | Ves como pestanas |
|---|---|
| CDP | sus imputaciones, los RP con cargo a el, y las reservas que dejo en la vigencia siguiente |
| Compromiso (RP) | sus imputaciones, las obligaciones causadas, y el contrato que lo respalda |
| Obligacion | sus imputaciones |
| Reserva | sus imputaciones, con el CDP de origen de v-1 |
| Contrato | sus actas de pago y sus imputaciones presupuestales |

El **proyecto** es la excepcion: su detalle no lleva inlines, porque toda su ejecucion se
revisa en la ficha.

Ejemplo verificado (CDP 425 de 2024, energia solar rural): en una sola pagina se ve el
certificado por $1.256.674.257, el RP 2420 que lo comprometio, el saldo sin obligar de
$1.092.325.482 y la reserva 1 de 2025 constituida exactamente por ese saldo.

`prueba_admin_unfold.py` verifica que las 22 paginas de listado cargan con unfold y que
los inlines traen datos.

## Roles y permisos

Dos grupos que crea la migracion `0009`, para no repartir permisos a mano:

| Rol | Que puede hacer |
|---|---|
| **Consulta** | Solo mirar: el proyecto, su informacion presupuestal (CDP, RP, obligaciones, reservas y sus imputaciones), los contratos de SIIFWEB y la contratacion de SECOP II, mas los catalogos. Entra al Avance financiero, a la ficha de ejecucion y al Reporte Financiero |
| **Seguimiento** | Lo mismo que Consulta y ademas **crear y editar proyectos**, que es el unico dato que el equipo alimenta a mano |

Ninguno de los dos ve las **cargas del reporte** (subir un archivo dispara el proceso y
reescribe datos) ni los **usuarios y roles** de Django, y ninguno puede **borrar**: un
proyecto con ejecucion colgando no se elimina, se corrige.

**En el menu lateral ven un solo modulo, el de Seguimiento** (Proyectos, Avance financiero y
Reportes). Metas y Programacion de proyectos van con el permiso de su propio modelo, que
los roles todavia no tienen: no los ven, en vez de ver un enlace que les responderia 403. Las
demas secciones —catalogos, cadena de gasto, cierre, contratacion y SECOP II— listan
documento por documento lo que producen las cargas, y esa misma informacion la revisan
agregada en la ficha del proyecto. Las paginas siguen abiertas por URL a proposito: los
modales de la ficha enlazan "Abrir el contrato" y "Abrir el proceso".

Para dar de alta a alguien: `Usuarios` -> nuevo usuario, marcar **"Es del equipo"**
(`is_staff`, sin eso no entra al admin) y asignarle el grupo. Nada de permisos sueltos.

Dos detalles de implementacion:

- Los enlaces del menu lateral llevan una llave `permission` (helpers `_con_permiso` y
  `_administra_los_datos` en `settings.py`), asi que cada rol solo ve lo suyo. Si una
  seccion se queda sin enlaces visibles, desaparece entera. La llave del resto del menu
  es `view_cargareporte`: quien sube los archivos es quien mantiene esas tablas.
- La ficha de ejecucion y el Reporte Financiero son vistas propias, y `admin_view()` solo
  exige ser staff: el permiso de vista se revisa dentro de cada una. Sin eso, cualquiera
  del equipo entraria por la URL.

Los roles se prueban en `siifweb/tests/test_roles.py`, que verifica tanto lo que abre
como lo que responde 403.

## Estructura

- `siifweb/models.py` — los modelos (cabecera + lineas, catalogos, cierre)
- `siifweb/cargas.py` — normalizacion (coma decimal, identificadores sin `.0`, fechas)
  y un cargador por tipo de reporte
- `siifweb/admin.py` — formulario con validacion de duplicados y la accion de procesar
- `siifweb/management/commands/cargar_reporte.py` — carga por consola
- `siifweb/management/commands/validar.py` — conciliaciones sobre lo migrado
- `siifweb/tablero.py` — el Avance financiero: agregacion por dependencia y por proyecto
- `siifweb/pdf_ficha.py` — el PDF de cada tabla de la ficha (ReportLab)
- `siifweb/fuentes/` — Carlito (regular y negrilla) con su licencia OFL, para el PDF
- `siifweb/reportes.py` — los tres reportes y su Excel; `templates/siifweb/reportes.html` (el
  indice) y `reporte.html` (la pagina de cada uno)
- `siifweb/templates/siifweb/ficha_meta.html` — la ficha de la meta, con
  `_proyecto_programado.html` (el enlace que abre el modal del proyecto)
- `siifweb/migrations/0011` a `0014` — metas del plan (SUTEC) y programacion de proyectos (Access)
- `../modelos-metas/` (fuera de git) — el plan de la integracion, los generadores de la
  `0012` y la `0014`, y el Access de origen
- `siifweb/migrations/0009_roles_seguimiento_y_consulta.py` — los dos roles del equipo
- `siifweb/tests/` — la bateria automatica (`manage.py test siifweb`)
- `prueba_admin.py` — ejerce el flujo del admin (subir + procesar) sin navegador
- `prueba_admin_unfold.py` — verifica que las 18 paginas cargan y que los inlines traen datos
- `prueba_secop.py` — carga el consolidado de SECOP II real en la sqlite local
- `prueba_tablero.py` — contrasta el Avance financiero contra la base real, rango por rango

## Validaciones

```bash
uv run --directory seguimiento_poai python manage.py validar --vigencia 2025
```

Siete secciones sobre lo migrado de SIIFWEB (totales, identidades del reporte,
conciliacion padre-hijo, salto temporal de reservas, ejecucion de reservas, cobertura
por proyecto y catalogo) y una octava sobre **SECOP II**, que no depende de la vigencia
porque el consolidado se descarga por rango completo. La octava revisa:

| Que | Que significa si falla |
|---|---|
| Cada fila apunta al proceso de su contrato | Incoherencia de la carga, no del dato |
| Todo contrato tiene su fila BPIN | Igual: quedo un contrato huerfano |
| Los BPIN de SECOP estan en el catalogo | **Accionable**: el equipo crea el proyecto o corrige el BPIN. Los lista uno por uno |
| Los BPIN estan validados por el DNP | Aviso: la fuente marca el BPIN como no validado |
| Los valores estan dentro de lo posible | Error de digitacion en SECOP (hay dos contratos con valores imposibles). Se cargan igual y se reportan; el total tambien se muestra sin ellos |

Y a titulo informativo: contratos sin proveedor o sin fecha de firma, proveedores sin
razon social, los procesos sin adjudicar agrupados por estado, y cuantos proyectos con
contratacion tienen tambien compromisos en SIIFWEB.

El contraste de valores entre SECOP y SIIFWEB es informativo y no una conciliacion: el
contrato es el total pactado y el compromiso es el RP de cada vigencia.

## Pruebas

```bash
uv run --directory seguimiento_poai python manage.py test siifweb
```

**Nunca tocan produccion.** El `.env` apunta a Supabase y el almacenamiento por defecto
es el bucket S3, asi que `settings.py` detecta el comando `test` y fuerza sqlite en
memoria, disco temporal para los archivos y un hasher rapido. No hay que acordarse de
exportar nada, y **no dependen del `.env`**: sin el, la guarda pone una `SECRET_KEY` de
relleno y apaga la redireccion a HTTPS (antes, sin `DEBUG=True`, 121 pruebas fallaban
con un 301).

Ojo con la carpeta temporal: `MEDIA_ROOT = BASE_DIR / 'media'` se define mas abajo que la
guarda y la pisaba, asi que cada corrida dejaba cientos de xlsx de prueba en
`media/reportes` (se acumularon 4.694, 150 MB, borrados en octubre de 2026). Ahora esa
linea no se ejecuta en pruebas, y `test_las_pruebas_no_corren_contra_produccion` lo vigila.

304 pruebas en trece modulos. Tardan algo mas de un minuto: la `0012` y la `0014` cargan sus
datos cada vez que se crea la base de pruebas, que asi trae el catalogo real.

| Modulo | Que vigila |
|---|---|
| `test_leer_filas.py` | El lector de xlsx: encontrar la TABLA por su nombre en la hoja que sea, fallar claro si no esta o si le faltan columnas, y seguir leyendo como antes los reportes sin tabla |
| `test_cargar_secop.py` | El cargador: grano, deduplicacion, procesos sin contrato, BPIN fuera del catalogo, normalizacion, idempotencia, atomicidad y el mensaje de resultado. Al final, las cifras del archivo real |
| `test_modelos_secop.py` | Llaves unicas, la restriccion de la fila BPIN, los `PROTECT` y el tipo de reporte nuevo |
| `test_ficha_proyecto.py` | Los dos paneles: que cada uno consulte solo lo suyo, el orden del tramite, el modal, las ayudas, las tablas con alto limitado y que ninguna suma se multiplique. El saldo y el pagado de las obligaciones, el filtro de fechas (cada tabla por su fecha, limites incluidos, tarjetas sin filtrar, fechas invalidas) y el formato de fecha |
| `test_pdf_ficha.py` | El PDF de cada tabla: que traiga solo la tabla pedida, que respete el filtro, el 404 de una tabla desconocida, los textos con `<`, `>` y `&`, las tablas de varias paginas, los permisos, el encabezado con la dependencia responsable y los enlaces junto a cada titulo |
| `test_regresion_cargadores.py` | Que los cargadores de siempre sigan funcionando, ya que comparten `leer_filas` con el de SECOP. Los valores monetarios: separador de miles y que un valor ilegible aborte la carga |
| `test_validar.py` | La seccion 8 del comando `validar` y que las siete anteriores sigan saliendo |
| `test_tablero.py` | El Avance financiero: solo proyectos con dependencia responsable, el grano (nada se cuenta dos veces), cada etapa cortada por su fecha y contrastada con la consulta directa, lo cancelado de SECOP fuera, atajos de periodo con la fecha de Bogota y filtros que no revientan |
| `test_roles.py` | Los roles Seguimiento y Consulta: que ven, que editan y el menu lateral de cada uno |
| `test_plan_desarrollo.py` | La seccion del menu y su orden, que cada enlace abra, que los roles no la vean, el detalle y el autocompletado de la meta, que el listado no haga una consulta por fila, cada filtro del listado con un valor real (MT, linea, indicador PDD y la cadena MGA, sin filas repetidas), y la regla de los indicadores del programa (rechazo en el campo y sin error falso al cambiar programa e indicadores a la vez) |
| `test_programacion_proyectos.py` | Las cifras de la `0014` y sus reglas (BPIN solo codigos, municipios, observaciones sin fecha, cinco decimales exactos), el menu, el recalculo de vigencias al guardar, el desplegable del listado de metas, el orden ascendente y la ficha de la meta (cifras por vigencia, desplegables, modal con todas las metas del proyecto, la ejecucion de SIIFWEB por BPIN y vigencia con reservas, las observaciones desde el modal, 404 y permisos) |
| `test_reportes.py` | El indice y la pagina de cada reporte, los permisos (los roles solo ven el financiero), el Excel del Plan indicativo y de Proyectos programados contra la base (filas, encabezados, datos de una meta, filtros, la meta del proyecto exacta), que no haga una consulta por fila y que las vigencias del filtro no se repitan |
| `test_admin_y_sistema.py` | Las paginas nuevas y **todas** las que ya existian, el menu lateral, `check`, que no queden migraciones sin crear, que las pruebas no toquen produccion ni `media/`, y el formulario de carga (vigencia obligatoria salvo en historial y SECOP II; el cruce POAI ya no se ofrece) |

Las cifras del archivo real (`data/secop/ReporteSIIFWEB_20260814.xlsx`) se comprueban solo
si el archivo esta a mano; en otra maquina esas pruebas se saltan solas.

Las pruebas se verificaron por mutacion: se rompio el codigo a proposito en veinte puntos
(la subconsulta que evita multiplicar filas, la deduplicacion, la validacion de columnas,
el `select_related`, el orden de las tarjetas, el comentario de la plantilla, la lectura
de `OBJETO_OBLIG`, su actualizacion en el upsert…) y en todos los casos fallo la prueba
que corresponde. Tres pruebas resultaron pasar con el codigo roto y se corrigieron: no
basta con que la suite este en verde.

## Los 41 modelos

```
CATALOGOS     Proyecto (bpin, nombre, dependencia)   <- el eje del seguimiento
              Rubro · Fuente · CentroCosto · Tercero · OrdenGasto
              DependenciaResponsable · Clasificacion  (POAI, las mantiene el equipo)

CADENA        Cdp ───────── CdpImputacion ─────────┐
              Compromiso ── CompromisoImputacion ──┤ FK a Proyecto
              Obligacion ── ObligacionImputacion ──┘

CIERRE        Reserva ───── ReservaImputacion ──────┘  (cdp_origen -> v-1)

CONTRACTUAL   Contrato ──┬─ ContratoActa (fecha y valor de cada pago)
                         └─ ContratoImputacion ────┘  (compromiso -> RP)

SECOP II      ProcesoSecop ── ContratoSecop ── BpinProceso (por BPIN al Proyecto)

PLAN (SUTEC)  PlanDesarrollo <- LineaEstrategica <- SectorPDD <- ProgramaPDD
              IndicadorPDD (varios programas) · ODS · MetaODS
              SectorMGA <- ProgramaMGA <- ProductoMGA <- IndicadorMGA
              MetaIndicador (programa, indicador MGA) ── VigenciaMeta

PROGRAMACION  ProgramacionProyectos ──┬─ ProgramacionMeta (meta x vigencia)
(Access)                              └─ ObservacionProyecto
              TipoBanco · Municipio

OPERACION     CargaReporte
```

Las cabeceras (`Cdp`, `Compromiso`, `Obligacion`, `Reserva`, `Contrato`) no llevan el campo
`proyecto`, pero se quedan porque aportan fecha, objeto y numero de documento: la
trazabilidad que hace falta cuando alguien pregunta con que CDP se contrato algo.
Los catalogos describen las imputaciones del proyecto.

## Reglas del negocio implementadas en la carga

- `PROYECTO = 0` se guarda como FK nulo (funcionamiento, sin proyecto).
- Una obligacion cuyo RP no existe en su vigencia se busca en v-1: es ejecucion de
  reserva (el caso de 2023, 43 imputaciones).
- Las reservas resuelven su CDP de origen contra la vigencia anterior.
- Los valores con coma decimal se convierten a Decimal; los identificadores pierden el `.0`.
  Un valor monetario ilegible aborta la carga en vez de quedar en cero.
- Los catalogos se enriquecen entre reportes: solo se rellenan campos vacios.

## Trampas que costaron encontrar

1. **`Sum()` sobre dos relaciones a la vez multiplica las filas.** Aparecio dos veces: el
   pagado de un contrato salia al doble (2 imputaciones del proyecto x sus actas), y el
   total del calendario de pagos tambien. Se resuelve con `Subquery` (helper `suma_de`) o
   filtrando por una subconsulta de ids en vez de por el join.
2. **`max_num` no limita un inline de solo lectura**: el admin lo pone en 0 cuando
   `has_add_permission` es False. Y `get_queryset` del inline tampoco sirve, porque ahi
   todavia no se filtro por el padre. El corte va en el formset (`FormSetLimitado`).
3. **`parse_date` no siempre devuelve `None`**: con un texto que no parece fecha si, pero
   con una bien formada e imposible (`2025-13-45`) lanza `ValueError`. Las vistas leen las
   fechas de la URL con `fecha_del_get`, que lo atrapa.
4. **unfold no trae todas las clases de Tailwind.** Sirve una hoja ya compilada con las
   clases que el mismo usa: `items-end` no existe y `text-base` es un color, no un tamano
   de letra. Una clase que falta no da error, simplemente no hace nada, y el defecto solo
   se ve en el navegador. En las plantillas propias, alineacion, alturas y tamanos de
   iconos van en un `<style>` con selector acotado (`#filtro-fechas ...`, `.btn-pdf`).
5. **En ReportLab, `keepWithNext` y `KeepTogether` agrupan el titulo con la tabla
   entera**: una tabla larga salta completa a la pagina siguiente y deja un hueco. Para
   que el titulo no quede solo al pie se usa `CondPageBreak` antes del titulo.
