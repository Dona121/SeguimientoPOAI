# Catálogo PIIP y Ficha PIIP

Cambios del 12 de noviembre de 2026, rama `formulacion-piip` (sin subir a `main`). Trae
las migraciones `0020` (esquema) y `0021` (datos): **antes del push hay que respaldar
Supabase**, porque el despliegue corre `migrate` allá.

## 1. Para qué

La ficha del proyecto necesitaba lo que cada proyecto formuló en el PIIP: sector,
programa, vigencias de inicio y fin, objetivo general, problema, descripción, población
afectada y objetivo, región, departamento, municipios y, por cada producto e indicador,
objetivo específico, etapa, UMP, UMI, tipo, acumula, meta total y meta por vigencia.

La fuente es la tabla de Excel `InfoGeneral` (hoja `IndicadoresPIIP` del libro
`ReporteSIIFWEB_*.xlsx`, el mismo de donde sale SECOP II). Es la consolidación de las
"Ficha actualizada del proyecto" del PIIP: una fila por proyecto × objetivo específico ×
producto × indicador × vigencia, con los datos del proyecto repetidos en sus filas.

Dos restricciones definieron el diseño:

- **El catálogo del plan de desarrollo no se toca.** `SectorMGA`, `ProgramaMGA`,
  `ProductoMGA` e `IndicadorMGA` son los del plan aprobado; agregarles productos implica
  llevarlo a la Asamblea. Los proyectos, en cambio, se formulan con el catálogo MGA
  completo. Por eso los productos e indicadores de los proyectos van en un catálogo aparte
  (el **Catálogo PIIP**) y cada indicador se vincula (homologa) con uno del plan.
- **Solo proyectos con ejecución en SIIFWEB.** Un BPIN que está en el PIIP pero no tiene
  documentos en SIIFWEB no tiene trazabilidad presupuestal, así que no se carga.

## 2. Modelos

### Nuevos

| Modelo | Qué es | Llave |
|---|---|---|
| `ProductoCatalogo` | Producto MGA con que se formuló algún proyecto: código, nombre y "medido a través de" (UMP). De él cuelga el objetivo específico. | `codigo` único |
| `IndicadorCatalogo` | Indicador de producto con que se formuló algún proyecto: código, nombre, unidad de medida del catálogo MGA, su producto y **su indicador del plan** (`indicador_pdd`), con `homologado_por_codigo` y `observacion`. | `codigo` único |
| `FormulacionProyecto` | La ficha PIIP de un proyecto: sector y programa (texto, como los trae el PIIP), vigencias de inicio y fin, objetivo general, problema, descripción, poblaciones, municipios, archivo de la ficha y la carga que la dejó. | uno a uno con `Proyecto` |
| `IndicadorProyecto` | Un indicador del proyecto: indicador del catálogo, objetivo específico, etapa, UMI (texto), tipo, acumula, meta total. El producto **no se guarda aquí**: sale de `indicador.producto`. | (`formulacion`, `indicador`) único |
| `MetaVigenciaIndicador` | Meta de un indicador del proyecto en una vigencia. | (`indicador_proyecto`, `vigencia`) único |
| `Departamento` | Nombre y región. Hoy: Sucre (Caribe) y los que se agreguen por proyectos de fuera. | `nombre` único |

### Cambios a modelos existentes

- `Municipio.departamento`: FK nueva (opcional) a `Departamento`. La `0021` pone en Sucre
  todos los municipios que ya existían.
- `CargaReporte.tipo_reporte`: opción nueva `piip` ("Información general de los
  proyectos en PIIP"). No lleva vigencia.
- `CargaReporte.hash`: deja de ser único en general y pasa a ser único **por tipo de
  reporte** (se valida en el formulario). SECOP II y PIIP salen del mismo libro, que debe
  poderse cargar una vez para cada uno.

### Relaciones

```
Proyecto (SIIFWEB) 1──1 FormulacionProyecto ──* IndicadorProyecto ──* MetaVigenciaIndicador
                              │                       │
                              *                       *
                         Municipio ──> Departamento   IndicadorCatalogo ──> ProductoCatalogo ──> MedidoATravesDe
                                                       │       └──> UnidadMedida
                                                       └──> IndicadorMGA (plan) ──> ProductoMGA ──> ProgramaMGA ──> SectorMGA
FormulacionProyecto ──> CargaReporte (la carga que la dejó)
```

El sector, el programa y el producto **del plan** de un indicador se leen recorriendo
`indicador_pdd → producto_mga → programa_mga → sector_mga`. El catálogo PIIP no guarda
programa ni sector propios.

`MedidoATravesDe` y `UnidadMedida` se comparten con el catálogo del plan: son listas de
nombres, no metas.

### Qué pasa al borrar

| Si se borra… | Efecto |
|---|---|
| Un `Proyecto` | Se borra su formulación, con sus indicadores y metas (CASCADE). |
| Una `FormulacionProyecto` | Se borran sus indicadores y metas. El catálogo no se toca. |
| Un `IndicadorCatalogo` usado por algún proyecto | **No se deja** (PROTECT). |
| Un `ProductoCatalogo` con indicadores | **No se deja** (PROTECT). |
| Un `IndicadorMGA` del plan con indicadores homologados | **No se deja** (PROTECT). |
| Una `CargaReporte` de PIIP con formulaciones que la citan | **No se deja** (PROTECT). |
| Un `Municipio` | Desaparece de las formulaciones que lo tenían. |
| Un `Departamento` con municipios | **No se deja** (PROTECT). |
| `MedidoATravesDe` / `UnidadMedida` en uso | **No se deja** (PROTECT). |

## 3. Lo que trae la migración

- **`0020_catalogo_piip_y_formulacion`**: crea las tablas y los cambios de arriba.
- **`0021_datos_catalogo_piip`**: generada con
  `modelos-metas/generar_migracion_catalogo_territorial.py` a partir de
  `CatalogoProductoMGA_junio_2025.xlsx` y `ReporteSIIFWEB_20261111.xlsx`.
  - Toma los 190 códigos de indicador de `InfoGeneral` y los **valida por código contra
    el catálogo MGA**: los 190 están. Entran con el nombre y la unidad del catálogo, y
    sus 187 productos con nombre y "medido a través de".
  - Si un código de `InfoGeneral` no estuviera en el catálogo MGA, se lista en
    `FUERA_DEL_CATALOGO` y no entra (lo crearía después la carga).
  - **Homologa por código**: cada indicador cuyo código existe en `IndicadorMGA` queda
    vinculado a él con `homologado_por_codigo = True`. Son 163; los otros 27 quedan sin
    homologar para hacerlo a mano.
  - Crea el departamento Sucre (región Caribe) y se lo asigna a los municipios existentes.
  - Es reversible: la reversa borra el catálogo y el departamento de Sucre (con borrado
    directo, porque el borrado en cascada de los modelos históricos falla). Antes de
    revertir hay que borrar las formulaciones, que protegen los indicadores.

## 4. La carga, paso a paso

Se sube el libro en *Configuración y parametrización → Cargas del reporte* con el tipo
**Información general PIIP** (sin vigencia) y se procesa con la acción "Procesar los
reportes seleccionados". En esa acción va después de todos los reportes de SIIFWEB y de
SECOP, porque necesita los proyectos ya cargados.

Toda la carga corre en **una transacción**: si algo falla, no queda nada a medias; la
carga queda "Con error" y el mensaje dice por qué.

1. **Lee la tabla `InfoGeneral`** por su nombre, en la hoja que esté. Si falta la tabla o
   alguna de sus 27 columnas, la carga se detiene con el nombre de lo que falta.
2. **Agrupa por BPIN.** Las filas sin BPIN se ignoran.
3. **Filtra los proyectos:** solo sigue el BPIN que existe como `Proyecto` y tiene al
   menos un CDP, RP, obligación, reserva o contrato en SIIFWEB. Los demás se cuentan y
   se listan (los primeros 20) en el mensaje.
4. **Reemplaza la formulación** de cada BPIN que pasa: actualiza o crea su
   `FormulacionProyecto` con los datos generales, le pone sus municipios y borra sus
   indicadores y metas anteriores. Los BPIN que no vienen en el archivo conservan la
   formulación que tenían.
5. **Municipios:** la lista del PIIP se parte por comas, reconociendo primero los nombres
   que tienen coma ("Bogotá, D.C."). Cada nombre se busca sin tildes ni mayúsculas; el que
   no está en el admin no se asocia y se avisa. Si un municipio encontrado no tiene
   departamento, toma el del PIIP (creándolo con su región si no existe).
6. **Indicadores:** las filas del proyecto se agrupan por código de indicador (un
   indicador trae una fila por vigencia, y a veces se repite bajo dos objetivos). Por
   cada uno:
   - **Valida el código contra el catálogo PIIP.** Si está, lo usa tal cual. Si no está,
     lo crea con el nombre del PIIP; y su producto se valida igual por código: si no
     está, se crea con el nombre del PIIP (sin la marca "(Producto principal del
     proyecto)") y su UMP. Todo lo creado se lista en el mensaje con los BPIN que lo
     traían.
   - Crea el `IndicadorProyecto` con los objetivos específicos (si son varios, uno por
     línea), etapa, UMI, tipo, acumula y meta total.
   - Crea una `MetaVigenciaIndicador` por vigencia.
7. **Homologa por código** los indicadores usados en la carga que no tienen indicador
   del plan, si su código existe en el plan.
8. **Mensaje del resultado:** proyectos, indicadores y metas cargados; lo que se creó en
   el catálogo; cuántos se homologaron por código; BPIN omitidos; municipios no
   reconocidos; departamentos asignados; y avisos de metas contradictorias.

## 5. Validaciones que sí se hacen

| Validación | Qué pasa si falla |
|---|---|
| El libro trae la tabla `InfoGeneral` con sus 27 columnas | La carga se detiene con error. |
| El mismo archivo ya se cargó como PIIP | El formulario lo rechaza (el mismo archivo sí se puede cargar como SECOP). |
| El BPIN tiene ejecución en SIIFWEB | No se carga; se lista en el mensaje. |
| El código del indicador está en el catálogo PIIP | Si no, se crea y se avisa. |
| El código del producto está en el catálogo PIIP (solo al crear un indicador) | Si no, se crea y se avisa. |
| El municipio existe en el admin | Si no, no se asocia y se avisa. |
| Las metas y la meta total son números legibles | Si no, la carga se detiene con error ("Valor monetario ilegible"). |
| Un indicador no trae dos metas distintas para la misma vigencia | Si las trae, queda la primera y se avisa. |
| Un indicador repetido bajo dos objetivos | Queda una sola vez, con los dos objetivos; la meta no se duplica. |
| Un indicador sin homologar cuyo código está en el plan | Se homologa por código. |

## 6. Validaciones que no se hacen, y por qué

| No se valida | Por qué |
|---|---|
| Que el producto del PIIP coincida con el producto que tiene el indicador en el catálogo | Si el indicador ya está, manda el catálogo, que mantiene el equipo. Un desacuerdo no se reporta. |
| Que el nombre del indicador o del producto del PIIP coincida con el del catálogo | Mismo motivo: lo que está en el catálogo no se cambia ni se compara. |
| Que un indicador creado por la carga esté en el catálogo MGA (o sea territorial) | El catálogo MGA completo no está en la base (solo se usó al generar la migración). La carga confía en el código del PIIP y avisa lo creado. |
| Que el programa o sector del PIIP coincidan con los del indicador del plan homologado | Son fuentes distintas: el PIIP describe el proyecto y el plan el indicador. La ficha muestra ambos lado a lado para revisarlo a ojo. |
| Que las metas por vigencia sumen la meta total cuando el indicador acumula | En el archivo real cuadra en 130 de 131; queda a la vista en la ficha. |
| Que las vigencias de las metas caigan entre la vigencia de inicio y la de fin | El PIIP no lo garantiza y no hay regla definida. |
| Que la población sea un número | Si no lo es, queda vacía, sin aviso. |
| Que etapa, tipo de indicador o acumula traigan un valor conocido | Si no, quedan vacíos, sin aviso. |
| Que el departamento del PIIP coincida con el que ya tiene el municipio | Solo se usa para los municipios sin departamento; el que ya tiene no se cambia. |
| Que las metas del PIIP coincidan con la programación en metas (la del Access) | Son dos fuentes de la misma relación proyecto → meta del plan. En la base local coinciden en 327 combinaciones y difieren en 67; 217 del PIIP no están programadas. Unificarlas es una decisión pendiente. |
| Borrar formulaciones de BPIN que ya no vienen en el archivo | Cada carga solo reemplaza lo que trae: un archivo parcial no debe borrar el resto. |
| Que un código cambiado en el catálogo siga coincidiendo con el del PIIP | Si se cambia el código de un indicador y el PIIP sigue trayendo el anterior, la siguiente carga crea uno nuevo con el código del PIIP (y lo avisa). |

## 7. Qué se puede editar

| Dónde | Qué se puede hacer |
|---|---|
| Catálogo PIIP → Productos | Agregar, editar y borrar (los que no tienen indicadores). |
| Catálogo PIIP → Indicadores | Agregar, editar y borrar (los que no usa ningún proyecto). Elegir su **indicador del plan** y la observación. Ver la línea del plan (sector, programa, producto e indicador). |
| Catálogo PIIP → Formulación de proyectos | Solo consulta: la llena la carga. Se puede borrar una formulación; la siguiente carga la vuelve a crear si el BPIN viene en el archivo. |
| Configuración → Departamentos y Municipios | Agregar, editar y borrar. El nombre del municipio debe ser como lo escribe el PIIP (sin importar tildes ni mayúsculas). |
| Configuración → Cargas del reporte | Subir y procesar el libro como "Información general PIIP". |

El campo "Por código" del indicador no se edita: lo pone el sistema. Si se elige a mano
un indicador del plan, queda en "No".

Las secciones del menú Catálogo PIIP solo las ven los administradores; los roles
Seguimiento y Consulta no.

## 8. Qué pasa solo (no hay triggers de base de datos)

No hay triggers en la base ni señales de Django para estos modelos. Lo automático está en
tres lugares, y en ninguno más:

1. **La migración `0021`**: homologa por código una sola vez, al aplicarse.
2. **La carga PIIP**: crea indicadores y productos que falten, y homologa por código los
   indicadores usados que estén sin homologar.
3. **Guardar un indicador en el admin**: si queda sin indicador del plan y su código
   existe en el plan, se homologa por código (por ejemplo, al agregar uno nuevo o al
   cambiarle el código). Si el usuario eligió el indicador del plan a mano, se marca como
   manual y no se reemplaza.

La regla común: **la homologación automática solo toca indicadores sin homologar**. Una
homologación hecha a mano nunca la cambia el sistema; si se quiere volver a la
automática, se vacía el campo y se guarda.

Ya existían antes, y siguen igual: `Proyecto.save()` limpia el BPIN (espacios y ".0"), y
una señal sobre los indicadores PDD de la meta, ajena a este módulo.

## 9. Dónde se ve

- **Ficha del proyecto → pestaña Ficha PIIP**, en el orden de `InfoGeneral`:
  - Datos generales: sector, programa, vigencia de inicio y fin, objetivo general,
    problema, descripción, población afectada y objetivo, región, departamento y
    municipios. Región y departamento salen de los municipios.
  - Indicadores: objetivo específico, código y nombre del producto, etapa, UMP, código y
    nombre del indicador, UMI, tipo, acumula, meta total y una columna por vigencia. Al
    final, sombreada, la línea del plan homologado (sector, programa, producto e
    indicador del plan, y si fue "Por código" o "Homologado a mano"); se muestra aunque
    coincida con el PIIP, para comprobar que quedó bien homologado. Sin homologar dice
    "Sin homologar".
- **Catálogo PIIP → Indicadores**: columnas Homologado, Indicador del plan, Por código y
  Proyectos; filtros "Sin homologar", "Lo usa algún proyecto" y "Por código".

## 10. Pendiente para producción

1. Respaldar Supabase y subir la rama (aplica `0020` y `0021`).
2. En el admin de producción, igualar los nombres de municipio a los del PIIP (en local se
   cambiaron: "Todo el departamento de sucre", "San Luis De Sincé", "San José De
   Toluviejo", "San Juan De Betulia", "Palmito") y crear los de fuera de Sucre que use
   algún proyecto cargado (en local: Barranquilla, Garzón, San Andrés, Santiago De Cali).
3. Subir `ReporteSIIFWEB_20261111.xlsx` como "Información general PIIP" y procesarlo.
4. Homologar a mano los indicadores sin homologar que usan proyectos (18 en local).

## 11. Pruebas

`siifweb/tests/test_formulacion_piip.py` cubre el catálogo que deja la migración, la
carga (filtro por SIIFWEB, reemplazo por BPIN, indicador bajo dos objetivos, municipios,
indicador y producto que se crean con sus metas, homologación por código sin tocar la
manual), el mismo libro para SECOP y PIIP, la pestaña de la ficha, la ficha del indicador
en el admin y la sección del menú. La suite completa tiene 385 pruebas.
