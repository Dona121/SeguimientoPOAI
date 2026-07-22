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

Admin en http://localhost:8010/admin/ — usuario `admin`, clave `siifweb2026`.

## Cargar un reporte desde el admin

1. Cargas del reporte -> Anadir carga del reporte.
2. Elegir tipo (disponibilidades / compromisos / obligaciones / reservas / historial),
   vigencia y el archivo xlsx. Grabar.
3. En el listado, seleccionar la carga y ejecutar la accion
   **"Procesar los reportes seleccionados"**.
4. El resultado queda en las columnas `Estado` y `Resultado del proceso` del propio registro.

El mismo archivo no se puede cargar dos veces: se detecta por hash SHA-256 y el formulario
muestra el error antes de guardar.

### Procesar todos a la vez o uno por uno

Subir y procesar son dos pasos separados. Al grabar, la carga queda **pendiente**; no se
migra hasta correr la accion. Se pueden crear los cinco registros y luego seleccionarlos
todos y procesarlos de una sola pasada.

Cuidado con el orden: la accion no procesa en el orden en que se seleccionan, sino con
`queryset.order_by("vigencia", "id")`. Entre los consolidados de una misma vigencia manda
el `id` (orden de creacion), asi que crearlos en el orden de carga los procesa bien. Pero
**el historial no tiene vigencia (`NULL`), y en SQLite el `NULL` ordena primero**: en un
lote de "seleccionar todo", el historial correria ANTES que los consolidados de la vigencia
y los contratos de ese anio no encontrarian su RP (todavia no cargado), quedando sin
enganchar. Los de anios anteriores si enganchan, porque ya estan en la base.

Forma segura sin tocar codigo: procesar primero los **cuatro consolidados** juntos y en una
segunda pasada el **historial** solo.

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
| Valores en $ | `str` con **coma decimal** y sin separador de miles: `'1855247059,44'`; enteros tambien como texto | `decimal()` cambia `,` por `.` |
| Fechas | `str`, con **el anio mezclado**: `'05/01/2026'` en los consolidados y `'02/01/26'` / `'13/12/22'` en reservas e historial | `fecha()` prueba `%d/%m/%y`, `%d/%m/%Y`, `%Y-%m-%d` |
| Historial | filas de cabecera de contrato con las columnas presupuestales en `None` | los cargadores usan `.get()` y descartan filas totalmente vacias |

Ojo: como el `NIT` llega en `int`, la plataforma ya descarto cualquier cero a la izquierda
en origen — no es algo que introduzca la carga.

Verificado sobre los cinco reportes crudos de 2026 (corte 20260720, **67.000+ filas**):
cero fallos de parseo en valores y fechas, ningun codigo con `.0` ni notacion exponencial,
y todas las claves duras (`f["..."]`) presentes en su archivo. Los unicos valores que
quedan en `0` son ceros reales (saldos ya ejecutados), no errores de conversion.

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

El historial de contratos y el POAI se descargan por rango completo, asi que el historial
se reemplaza entero y el POAI es idempotente (solo rellena el catalogo de proyectos).

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

Los FK exigen que el padre exista antes que el hijo:

1. `cdp` de la vigencia
2. `compromisos` de la vigencia (apuntan a los CDP)
3. `obligaciones` de la vigencia (apuntan a los RP)
4. `reservas` de la vigencia v (apuntan a los **CDP de v-1**)
5. `historial` al final: engancha con los RP de **todas** las vigencias cargadas

Y las vigencias en orden ascendente: 2024 antes que 2025.

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

## Cruce POAI (carga opcional)

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

**Detalle del proyecto**: cinco inlines con lo que le cuelga — disponibilidades,
compromisos, obligaciones, contratos y reservas. Se limitan a 20 filas por inline: un
proyecto de nomina tiene cientos de imputaciones y los inlines no paginan.

**Ficha de ejecucion** (boton en el detalle, o el enlace del listado): una vista propia,
hecha con una changeform action de unfold, porque los inlines muestran filas sueltas y
aqui hace falta agregacion. Trae:

- Cuatro tarjetas con el total de cada etapa de la cadena.
- Tabla de ejecucion **por vigencia**: certificado, comprometido, obligado, pagado, y los
  dos saldos (sin comprometer, sin obligar) con barra de avance.
- Contratos del proyecto con contratista, valor, numero de actas y pagado real.
- **Calendario de pagos**: cada acta del contrato con su fecha, tipo, numero y contratista.
- Reservas, con el CDP de origen de la vigencia anterior, su obligado y su saldo.

Implementacion: `@action(url_path="ficha-ejecucion")` + `actions_detail`, devolviendo un
`TemplateResponse` con `admin_site.each_context()` sobre una plantilla que extiende
`admin/base.html`, asi conserva la barra lateral y el tema de unfold. La URL propia se
registra ANTES de las del admin en `get_urls()`, porque `<path:object_id>/` las capturaria.

Un detalle que costo encontrar, y que aparecio dos veces: sumar dos relaciones a la vez
con `Sum()` **multiplica las filas**. El pagado de un contrato y el total del calendario
salian al doble porque el contrato tenia 2 imputaciones para ese proyecto y el join las
cruzaba con sus actas. Se resuelve con `Subquery` (helper `suma_de`) o filtrando por una
subconsulta de ids. Es el mismo problema del grano que cuidamos al cruzar los reportes.

## El admin (django-unfold)

Interfaz con [django-unfold](https://unfoldadmin.com/): barra lateral agrupada por
etapa de la cadena, filtros desplegables, rangos de fecha y badges de estado.

**Los inlines muestran la cadena completa sin salir de la pagina.** Cada documento
trae las tablas relacionadas como pestanas:

| Al abrir un... | Ves como pestanas |
|---|---|
| CDP | sus imputaciones, los RP con cargo a el, y las reservas que dejo en la vigencia siguiente |
| Compromiso (RP) | sus imputaciones, las obligaciones causadas, y el contrato que lo respalda |
| Obligacion | sus imputaciones |
| Reserva | sus imputaciones, con el CDP de origen de v-1 |
| **Proyecto** | disponibilidades, compromisos, obligaciones, contratos y reservas |
| Contrato | sus actas de pago y sus imputaciones presupuestales |

Ejemplo verificado (CDP 425 de 2024, energia solar rural): en una sola pagina se ve el
certificado por $1.256.674.257, el RP 2420 que lo comprometio, el saldo sin obligar de
$1.092.325.482 y la reserva 1 de 2025 constituida exactamente por ese saldo.

`prueba_admin_unfold.py` verifica que las 22 paginas de listado cargan con unfold y que
los inlines traen datos.

## Estructura

- `siifweb/models.py` — los modelos (cabecera + lineas, catalogos, cierre)
- `siifweb/cargas.py` — normalizacion (coma decimal, identificadores sin `.0`, fechas)
  y un cargador por tipo de reporte
- `siifweb/admin.py` — formulario con validacion de duplicados y la accion de procesar
- `siifweb/management/commands/cargar_reporte.py` — carga por consola
- `siifweb/management/commands/validar.py` — conciliaciones sobre lo migrado
- `prueba_admin.py` — ejerce el flujo del admin (subir + procesar) sin navegador
- `prueba_admin_unfold.py` — verifica que las 18 paginas cargan y que los inlines traen datos

## Los 18 modelos

```
CATALOGOS     Proyecto (bpin, nombre, dependencia)   <- el eje del seguimiento
              Rubro · Fuente · CentroCosto · Tercero · OrdenGasto

CADENA        Cdp ───────── CdpImputacion ─────────┐
              Compromiso ── CompromisoImputacion ──┤ FK a Proyecto
              Obligacion ── ObligacionImputacion ──┘

CIERRE        Reserva ───── ReservaImputacion ──────┘  (cdp_origen -> v-1)

CONTRACTUAL   Contrato ──┬─ ContratoActa (fecha y valor de cada pago)
                         └─ ContratoImputacion ────┘  (compromiso -> RP)

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
- Los catalogos se enriquecen entre reportes: solo se rellenan campos vacios.

## Dos trampas de Django que costaron encontrar

1. **`Sum()` sobre dos relaciones a la vez multiplica las filas.** Aparecio dos veces: el
   pagado de un contrato salia al doble (2 imputaciones del proyecto x sus actas), y el
   total del calendario de pagos tambien. Se resuelve con `Subquery` (helper `suma_de`) o
   filtrando por una subconsulta de ids en vez de por el join.
2. **`max_num` no limita un inline de solo lectura**: el admin lo pone en 0 cuando
   `has_add_permission` es False. Y `get_queryset` del inline tampoco sirve, porque ahi
   todavia no se filtro por el padre. El corte va en el formset (`FormSetLimitado`).
